"""Reading a folder's devcontainer.json.

Pyde supports the Docker Compose form of the Dev Container specification
(https://containers.dev/implementors/json_reference/), and of that, the parts
that bring the containers up and put a terminal in one. What it does not act
on is listed in `DevContainerConfig.ignored`, so the user can be told.
"""

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyde import jsonc

# Where the file may be, relative to the folder, in the order they are tried.
CONFIG_PATHS = (".devcontainer/devcontainer.json", ".devcontainer.json")

# Properties that select a kind of dev container Pyde cannot run.
_NOT_COMPOSE = ("image", "build", "dockerFile")
# Properties Pyde reads past, and the name each goes by in the notice.
_IGNORED = {"features": "Features", "forwardPorts": "forwardPorts"}
# The lifecycle commands, in the order they run. The first runs on this Mac
# before the containers start; the rest run inside the container.
HOOKS = (
    "initializeCommand",
    "onCreateCommand",
    "updateContentCommand",
    "postCreateCommand",
    "postStartCommand",
    "postAttachCommand",
)

# One command of a lifecycle hook: a string for a shell to run, or a list
# giving a program and its arguments to run directly.
Command = str | list[str]

# ${name} or ${name:argument}, as in ${localEnv:HOME}.
_VARIABLE = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")
# ${containerEnv:NAME} or ${containerEnv:NAME:default}.
_CONTAINER_ENV = re.compile(r"\$\{containerEnv:(\w+)(?::([^}]*))?\}")


class ConfigError(ValueError):
    """The devcontainer.json cannot be used. The message says why."""


@dataclass(frozen=True)
class DevContainerConfig:
    # The devcontainer.json itself, and the folder it configures.
    path: Path
    folder: Path
    # What to call the dev container on screen.
    name: str
    compose_files: tuple[Path, ...]
    # The Compose service the terminal goes into.
    service: str
    # The services to start; empty for all of them.
    run_services: tuple[str, ...]
    # Where the terminal starts, inside the container.
    workspace_folder: str
    # Who the terminal runs as; None leaves it to the container.
    remote_user: str | None
    # Environment variables for the container itself.
    container_env: dict[str, str]
    # Environment variables for the terminal. None removes a variable. Values
    # may still hold ${containerEnv:NAME}, which needs the running container.
    remote_env: dict[str, str | None]
    # Extra mounts for the service, in Compose's long volume syntax.
    mounts: tuple[dict[str, Any], ...]
    # Whether to replace the service's command with one that just stays alive.
    override_command: bool
    # Whether closing the folder stops the containers.
    stop_on_close: bool
    # The lifecycle commands the file sets, by name. A hook may hold several.
    hooks: dict[str, tuple[Command, ...]]
    # Identifies this dev container; the same value VS Code computes.
    id: str
    # Properties present in the file that Pyde does not act on.
    ignored: tuple[str, ...]


def find_config(folder: Path) -> Path | None:
    """The folder's devcontainer.json, if it has one."""
    for relative in CONFIG_PATHS:
        path = folder / relative
        if path.is_file():
            return path
    return None


def load_config(path: Path, folder: Path) -> DevContainerConfig:
    """Read and check a devcontainer.json. Raises ConfigError if unusable."""
    try:
        raw = jsonc.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConfigError(f"{path.name} could not be read: {error}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name} does not hold a JSON object")

    if "dockerComposeFile" not in raw:
        kind = next((name for name in _NOT_COMPOSE if name in raw), None)
        detail = f"this one uses {kind!r}" if kind else "this one has none"
        raise ConfigError(
            f"Pyde needs a dockerComposeFile in {path.name}, and {detail}"
        )
    if not isinstance(raw.get("service"), str):
        raise ConfigError(f"{path.name} does not name the service to work in")

    try:
        container_id = _container_id(folder, path)
        variables = {
            "localWorkspaceFolder": str(folder),
            "localWorkspaceFolderBasename": folder.name,
            "devcontainerId": container_id,
        }
        workspace_folder = _substitute(raw.get("workspaceFolder", "/"), variables)
        variables["containerWorkspaceFolder"] = workspace_folder
        variables["containerWorkspaceFolderBasename"] = Path(workspace_folder).name
        raw = _substitute(raw, variables)

        compose_files = raw["dockerComposeFile"]
        if isinstance(compose_files, str):
            compose_files = [compose_files]
        return DevContainerConfig(
            path=path,
            folder=folder,
            name=raw.get("name") or folder.name,
            # Relative paths are relative to the devcontainer.json.
            compose_files=tuple(path.parent / file for file in compose_files),
            service=raw["service"],
            run_services=tuple(raw.get("runServices", ())),
            workspace_folder=workspace_folder,
            remote_user=raw.get("remoteUser"),
            container_env=dict(raw.get("containerEnv", {})),
            remote_env=dict(raw.get("remoteEnv", {})),
            mounts=tuple(_mount(mount) for mount in raw.get("mounts", ())),
            override_command=raw.get("overrideCommand", False),
            stop_on_close=raw.get("shutdownAction", "stopCompose") == "stopCompose",
            hooks={name: _commands(raw[name]) for name in HOOKS if raw.get(name)},
            id=container_id,
            ignored=tuple(
                label
                for name, label in _IGNORED.items()
                if raw.get(name) not in (None, [], {}, "")
            ),
        )
    except (AttributeError, KeyError, TypeError) as error:
        # A property holding the wrong kind of value, such as a string where
        # the specification asks for a list.
        raise ConfigError(f"{path.name} has a malformed property: {error}") from None


def substitute_container_env(
    remote_env: Mapping[str, str | None], container_env: Mapping[str, str]
) -> dict[str, str | None]:
    """Fill in ${containerEnv:NAME} from the running container's environment."""

    def fill(value: str) -> str:
        return _CONTAINER_ENV.sub(
            lambda match: container_env.get(match.group(1), match.group(2) or ""),
            value,
        )

    return {
        name: None if value is None else fill(value)
        for name, value in remote_env.items()
    }


def _substitute(value: Any, variables: Mapping[str, str]) -> Any:
    """Replace ${...} variables throughout a JSON value.

    ${containerEnv:...} is left for later, and so is anything unrecognized.
    """
    if isinstance(value, str):
        return _VARIABLE.sub(lambda match: _variable(match, variables), value)
    if isinstance(value, list):
        return [_substitute(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, variables) for key, item in value.items()}
    return value


def _variable(match: re.Match[str], variables: Mapping[str, str]) -> str:
    name, argument = match.group(1), match.group(2)
    if name == "localEnv" and argument:
        # ${localEnv:NAME} or ${localEnv:NAME:default}
        variable, _, default = argument.partition(":")
        return os.environ.get(variable, default)
    if argument is None and name in variables:
        return variables[name]
    return match.group()


def _commands(hook: Any) -> tuple[Command, ...]:
    """The commands of one lifecycle hook.

    A hook is a single command, or an object of named commands. The
    specification runs an object's commands side by side; Pyde runs them one
    after another, in the order written, so that their output stays readable.
    """
    commands = list(hook.values()) if isinstance(hook, dict) else [hook]
    for command in commands:
        is_argv = isinstance(command, list) and all(
            isinstance(word, str) for word in command
        )
        if not (isinstance(command, str) or is_argv):
            raise TypeError("a lifecycle command must be a string or a list of strings")
    return tuple(commands)


def _mount(mount: Any) -> dict[str, Any]:
    """One entry of "mounts", as a Compose volume in its long syntax.

    An entry is an object, or a string in Docker's --mount form, such as
    "source=cache,target=/cache,type=volume".
    """
    if isinstance(mount, str):
        fields = dict(part.partition("=")[::2] for part in mount.split(","))
    else:
        fields = dict(mount)
    volume = {
        "type": fields.get("type", "volume"),
        "source": fields.get("source") or fields.get("src"),
        "target": fields.get("target")
        or fields.get("dst")
        or fields.get("destination"),
    }
    if "readonly" in fields or "ro" in fields:
        volume["read_only"] = True
    return {key: value for key, value in volume.items() if value is not None}


def _container_id(folder: Path, config_path: Path) -> str:
    """The value of ${devcontainerId}.

    Computed as the Dev Container reference implementation does, from the two
    labels that identify a dev container, so that names built from it, such as
    volume names, match the ones VS Code uses for the same folder.
    """
    labels = {
        "devcontainer.config_file": str(config_path),
        "devcontainer.local_folder": str(folder),
    }
    text = json.dumps(labels, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _base32(int.from_bytes(hashlib.sha256(text.encode()).digest()))


def _base32(number: int, width: int = 52) -> str:
    """A number in base 32, digits 0-9 then a-v, padded with zeros to `width`."""
    digits = "0123456789abcdefghijklmnopqrstuv"
    encoded = ""
    while number:
        number, digit = divmod(number, 32)
        encoded = digits[digit] + encoded
    return encoded.rjust(width, "0")
