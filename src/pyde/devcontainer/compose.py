"""The Docker commands and the Compose file that bring a dev container up.

Nothing here runs anything: these functions only work out what to run, and
make sense of what Docker reports back.
"""

import json
import re
from collections.abc import Mapping
from typing import Any

from pyde.devcontainer.config import DevContainerConfig, substitute_container_env

# Labels that Compose puts on every container it creates.
_PROJECT_LABEL = "com.docker.compose.project"
_SERVICE_LABEL = "com.docker.compose.service"
# A label that images built for dev containers carry: a JSON list of pieces of
# devcontainer.json, such as the user to work as.
_METADATA_LABEL = "devcontainer.metadata"

# Keeps a container running when its own command would exit straight away.
_STAY_ALIVE = "trap 'exit 0' TERM; while sleep 1 & wait $!; do :; done"
# Run by /bin/sh inside the container: become the current user's own shell, as
# a login shell, or /bin/sh if they have none worth using.
_OWN_SHELL = (
    'shell=$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f7); '
    'case "$shell" in ""|*/nologin|*/false) shell=/bin/sh;; esac; '
    'exec "$shell" -l'
)
_VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def project_name(compose_name: str, config: DevContainerConfig) -> str:
    """The Compose project name to use, given the one Compose would pick.

    Left alone, Compose names a project after the folder its first file is in,
    so every project whose file is in a .devcontainer folder would be called
    "devcontainer" and they would all share containers. VS Code names those
    "<folder>_devcontainer" instead; doing the same also means Pyde and VS
    Code find each other's containers.
    """
    in_devcontainer_folder = (
        config.compose_files[0].parent == config.folder / ".devcontainer"
    )
    if compose_name == "devcontainer" and in_devcontainer_folder:
        compose_name = f"{config.folder.name}_devcontainer"
    return re.sub(r"[^-_a-z0-9]", "", compose_name.lower())


def override(config: DevContainerConfig) -> dict[str, Any]:
    """A Compose file, layered over the project's own, that applies the
    devcontainer.json to the service."""
    service: dict[str, Any] = {
        # The labels VS Code uses to recognize a folder's dev container.
        "labels": {
            "devcontainer.local_folder": str(config.folder),
            "devcontainer.config_file": str(config.path),
        }
    }
    if config.container_env:
        service["environment"] = config.container_env
    if config.mounts:
        service["volumes"] = list(config.mounts)
    if config.override_command:
        service["entrypoint"] = ["/bin/sh", "-c", _STAY_ALIVE]
        service["command"] = []

    document: dict[str, Any] = {"services": {config.service: service}}
    # Compose wants named volumes declared. Naming each after itself stops
    # Compose prefixing it with the project name.
    named = {
        mount["source"]: {"name": mount["source"]}
        for mount in config.mounts
        if mount.get("type") == "volume" and mount.get("source")
    }
    if named:
        document["volumes"] = named
    return document


def config_command(docker: str, config: DevContainerConfig) -> list[str]:
    """Ask Compose for the project as it understands it, as JSON."""
    return [
        docker,
        "compose",
        *_files(config.compose_files),
        "config",
        "--format",
        "json",
    ]


def find_container_command(docker: str, project: str, service: str) -> list[str]:
    """List the service's container, running or not, by its id."""
    return [
        docker,
        "ps",
        "--all",
        "--quiet",
        "--filter",
        f"label={_PROJECT_LABEL}={project}",
        "--filter",
        f"label={_SERVICE_LABEL}={service}",
    ]


def up_command(
    docker: str,
    project: str,
    config: DevContainerConfig,
    override_file: str,
    container_exists: bool,
) -> list[str]:
    command = [
        docker,
        "compose",
        "--project-name",
        project,
        *_files([*config.compose_files, override_file]),
        "up",
        "--detach",
    ]
    if container_exists:
        # Leave a container that is already there as it is, rather than
        # replace it because Pyde's settings differ from whoever made it.
        command.append("--no-recreate")
    services = list(config.run_services)
    if services and config.service not in services:
        services.append(config.service)
    return command + services


def stop_command(docker: str, project: str, config: DevContainerConfig) -> list[str]:
    return [
        docker,
        "compose",
        "--project-name",
        project,
        *_files(config.compose_files),
        "stop",
    ]


def inspect_command(docker: str, container: str) -> list[str]:
    return [docker, "inspect", container]


def shell_command(
    docker: str,
    container: str,
    config: DevContainerConfig,
    inspected: Mapping[str, Any],
) -> list[str]:
    """Open the user's shell inside the container, given what `docker inspect`
    reported about it."""
    command = [docker, "exec", "--interactive", "--tty"]
    user = remote_user(config, inspected)
    if user:
        command += ["--user", user]
    command += ["--workdir", config.workspace_folder]

    script = _OWN_SHELL
    variables = {"TERM": "xterm-256color", "COLORTERM": "truecolor"}
    variables.update(remote_env(config, inspected))
    for name, value in variables.items():
        if not _VARIABLE_NAME.fullmatch(name):
            continue
        if value is None:
            # A null in remoteEnv takes the variable away.
            script = f"unset {name}; {script}"
        else:
            command += ["--env", f"{name}={value}"]
    return [*command, container, "/bin/sh", "-c", script]


def remote_user(config: DevContainerConfig, inspected: Mapping[str, Any]) -> str | None:
    """Who to work as: the devcontainer.json's choice, then the image's."""
    if config.remote_user:
        return config.remote_user
    for piece in reversed(_metadata(inspected)):
        if piece.get("remoteUser"):
            return piece["remoteUser"]
    return None


def remote_env(
    config: DevContainerConfig, inspected: Mapping[str, Any]
) -> dict[str, str | None]:
    """The terminal's extra environment, with ${containerEnv:...} filled in."""
    merged: dict[str, str | None] = {}
    for piece in _metadata(inspected):
        merged.update(piece.get("remoteEnv") or {})
    merged.update(config.remote_env)
    container_env = dict(
        entry.partition("=")[::2] for entry in inspected["Config"].get("Env") or ()
    )
    return substitute_container_env(merged, container_env)


def is_running(inspected: Mapping[str, Any]) -> bool:
    return bool(inspected.get("State", {}).get("Running"))


def _metadata(inspected: Mapping[str, Any]) -> list[dict[str, Any]]:
    labels = inspected["Config"].get("Labels") or {}
    try:
        pieces = json.loads(labels.get(_METADATA_LABEL, "[]"))
    except ValueError:
        return []
    if isinstance(pieces, dict):
        pieces = [pieces]
    return [piece for piece in pieces if isinstance(piece, dict)]


def _files(paths: list | tuple) -> list[str]:
    return [argument for path in paths for argument in ("-f", str(path))]
