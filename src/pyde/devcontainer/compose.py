"""The Docker commands and the Compose file that bring a dev container up.

Nothing here runs anything: these functions only work out what to run, and
make sense of what Docker reports back.
"""

import json
import re
from collections.abc import Mapping
from typing import Any

from pyde.devcontainer.config import (
    Command,
    DevContainerConfig,
    substitute_container_env,
)

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
# Run by /bin/sh inside the container to run one lifecycle command. Its
# arguments are a marker file's name, what to write in it, the kind of command
# ("shell" for a string, "exec" for a program and its arguments), and then the
# command itself.
#
# The command gets the environment of the user's shell started as a login and
# interactive one, so that it finds what a terminal in the container would.
# A string is still run by /bin/sh, as the specification says. If the command
# succeeds, the marker is written, which is how it is known to have run.
_RUN_HOOK = """\
marker=$1 stamp=$2 kind=$3
shift 3
shell=$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f7)
case "$shell" in */bash|*/zsh|*/sh|*/dash|*/ash|*/ksh) ;; *) shell=/bin/sh;; esac
if [ "$kind" = shell ]; then
  "$shell" -l -i -c 'exec /bin/sh -c "$0"' "$1"
else
  "$shell" -l -i -c 'exec "$@"' "$shell" "$@"
fi
status=$?
if [ "$status" -eq 0 ] && [ -n "$marker" ]; then
  mkdir -p "$HOME/.devcontainer"
  printf '%s\\n' "$stamp" > "$HOME/.devcontainer/$marker"
fi
exit "$status"
"""
# Run by /bin/sh inside the container. Each argument is hook=stamp; it prints
# the hooks whose marker file does not hold that stamp.
_STALE_MARKERS = """\
for entry in "$@"; do
  hook=${entry%%=*} stamp=${entry#*=}
  recorded=$(cat "$HOME/.devcontainer/.${hook}Marker" 2>/dev/null)
  [ "$recorded" = "$stamp" ] || echo "$hook"
done
"""
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
    rebuild: bool = False,
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
    if rebuild:
        # Build the images again and replace the containers with new ones.
        command += ["--build", "--force-recreate"]
    elif container_exists:
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
    return _exec(docker, container, config, inspected, _OWN_SHELL)


def hook_command(
    docker: str,
    container: str,
    config: DevContainerConfig,
    inspected: Mapping[str, Any],
    command: Command,
    hook: str | None = None,
) -> list[str]:
    """Run one lifecycle command inside the container.

    If `hook` is given, a successful run is recorded, so that the hook is not
    listed by `stale_hooks_command` again.
    """
    marker, stamp = "", ""
    if hook is not None:
        marker, stamp = f".{hook}Marker", _stamps(inspected)[hook]
    if isinstance(command, str):
        arguments = [marker, stamp, "shell", command]
    else:
        arguments = [marker, stamp, "exec", *command]
    return _exec(docker, container, config, inspected, _RUN_HOOK, arguments)


def stale_hooks_command(
    docker: str,
    container: str,
    config: DevContainerConfig,
    inspected: Mapping[str, Any],
) -> list[str]:
    """Ask which once-only hooks have yet to run. It prints their names."""
    command = [docker, "exec"]
    user = remote_user(config, inspected)
    if user:
        command += ["--user", user]
    entries = [f"{hook}={stamp}" for hook, stamp in _stamps(inspected).items()]
    return [*command, container, "/bin/sh", "-c", _STALE_MARKERS, "markers", *entries]


def host_command(command: Command) -> list[str]:
    """Run a lifecycle command on this Mac."""
    return ["/bin/sh", "-c", command] if isinstance(command, str) else list(command)


def _exec(
    docker: str,
    container: str,
    config: DevContainerConfig,
    inspected: Mapping[str, Any],
    script: str,
    arguments: list[str] | tuple[str, ...] = (),
) -> list[str]:
    """Run a /bin/sh script inside the container, attached to the terminal.

    It runs the way everything of the user's does there: as the remote user,
    in the workspace folder, and with the terminal's environment.
    """
    command = [docker, "exec", "--interactive", "--tty"]
    user = remote_user(config, inspected)
    if user:
        command += ["--user", user]
    command += ["--workdir", config.workspace_folder]

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
    # The word after the script is its $0; the arguments follow it.
    return [*command, container, "/bin/sh", "-c", script, "pyde", *arguments]


def _stamps(inspected: Mapping[str, Any]) -> dict[str, str]:
    """For each once-only hook, what tells this run of it from the last.

    Three hooks run once in the life of a container, so they are stamped with
    when it was created. One runs each time it starts.
    """
    created, started = inspected["Created"], inspected["State"]["StartedAt"]
    return {
        "onCreateCommand": created,
        "updateContentCommand": created,
        "postCreateCommand": created,
        "postStartCommand": started,
    }


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
