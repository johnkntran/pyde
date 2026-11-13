"""Bringing a folder's dev container up and putting the terminal inside it."""

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from pyde import shell_env
from pyde.devcontainer import compose
from pyde.devcontainer.config import DevContainerConfig
from pyde.terminal import TerminalView, default_shell, shell_environment

# How long the user's shell gets to report its environment before Pyde gives
# up on it. A startup file that waits for input would otherwise hang forever.
ENVIRONMENT_TIMEOUT_MS = 10_000


class DevContainer(QObject):
    """One folder's dev container, from "Reopen in Container" to leaving it.

    Bringing it up is a chain of Docker commands. Each short one runs out of
    sight and hands its output to the next step. The long one, `docker compose
    up`, runs in the terminal, where its progress can be watched. Nothing
    blocks the window while it all happens.
    """

    # The terminal is now a shell inside the container.
    connected = Signal()
    # The container could not be brought up. The text says what went wrong.
    failed = Signal(str)

    def __init__(
        self,
        config: DevContainerConfig,
        terminal: TerminalView,
        data_folder: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._terminal = terminal
        # Pyde's Compose file goes here, out of the user's project.
        self._override_file = data_folder / "devcontainers" / config.id / "compose.json"
        # Set once known: the docker program, the environment to run it in,
        # and the Compose project name.
        self._docker: str | None = None
        self._env: dict[str, str] = dict(os.environ)
        self._project: str | None = None
        # The out-of-sight command in progress, if any.
        self._process: QProcess | None = None
        self._active = False

    def start(self) -> None:
        """Begin bringing the container up. Ends in `connected` or `failed`."""
        self._active = True
        self._env = dict(os.environ)
        self._docker = shutil.which("docker")
        if self._docker:
            self._read_project()
        else:
            # Probably launched from the Finder, where the shell's PATH is
            # missing. Ask the shell for it.
            self._capture(
                shell_env.environment_command(default_shell()),
                self._use_shell_environment,
                on_failure=lambda reason: self._use_shell_environment(""),
                timeout_ms=ENVIRONMENT_TIMEOUT_MS,
            )

    def leave(self) -> None:
        """Stop working in the container.

        Abandons a bring-up in progress, and stops the containers if the
        devcontainer.json asks for that. The terminal is left to the caller.
        """
        self._active = False
        if self._process is not None:
            self._process.kill()
            self._process = None
        if self._docker and self._project and self.config.stop_on_close:
            command = compose.stop_command(self._docker, self._project, self.config)
            # Detached, so that it carries on even when Pyde is quitting.
            stopper = QProcess()
            stopper.setProgram(command[0])
            stopper.setArguments(command[1:])
            stopper.setProcessEnvironment(_process_environment(self._env))
            stopper.setStandardOutputFile(QProcess.nullDevice())
            stopper.setStandardErrorFile(QProcess.nullDevice())
            stopper.startDetached()

    # The steps, in order.

    def _use_shell_environment(self, output: str) -> None:
        environment = shell_env.parse_environment(output)
        if environment:
            self._env = environment
        self._docker = shutil.which("docker", path=self._env.get("PATH"))
        if self._docker:
            self._read_project()
        else:
            self._fail("Docker was not found. Is it installed and on your PATH?")

    def _read_project(self) -> None:
        self._capture(
            compose.config_command(self._docker, self.config), self._find_existing
        )

    def _find_existing(self, output: str) -> None:
        try:
            project = json.loads(output)
        except ValueError:
            self._fail("Docker Compose's description of the project made no sense.")
            return
        if self.config.service not in project.get("services", {}):
            self._fail(
                f"The Compose files have no service named {self.config.service!r}."
            )
            return
        self._project = compose.project_name(project.get("name", ""), self.config)
        self._find_container(self._bring_up)

    def _bring_up(self, output: str) -> None:
        self._override_file.parent.mkdir(parents=True, exist_ok=True)
        # JSON is YAML too, so Compose reads this like any other Compose file.
        document = compose.override(self.config)
        self._override_file.write_text(json.dumps(document, indent=2), encoding="utf-8")

        if self.config.ignored:
            ignored = ", ".join(self.config.ignored)
            self._terminal.show_message(
                f"Pyde does not act on these devcontainer.json properties: {ignored}."
            )
        command = compose.up_command(
            self._docker,
            self._project,
            self.config,
            str(self._override_file),
            container_exists=bool(output.strip()),
        )
        self._terminal.show_message(f"Starting the dev container: {self.config.name}")
        self._terminal.run_task(command, self._terminal_env(), self._brought_up)

    def _brought_up(self, status: int) -> None:
        if not self._active:
            return
        if status != 0:
            self._fail("docker compose up failed. Its output is in the terminal.")
            return
        self._find_container(self._inspect)

    def _inspect(self, output: str) -> None:
        containers = output.split()
        if not containers:
            self._fail(f"No container was created for {self.config.service!r}.")
            return
        self._capture(
            compose.inspect_command(self._docker, containers[0]),
            lambda inspected: self._open_shell(containers[0], inspected),
        )

    def _open_shell(self, container: str, output: str) -> None:
        try:
            inspected = json.loads(output)[0]
        except (ValueError, IndexError, KeyError):
            self._fail("Docker's description of the container made no sense.")
            return
        if not compose.is_running(inspected):
            self._fail(
                f"The {self.config.service!r} container is not running. If its"
                ' command exits straight away, set "overrideCommand": true in'
                " devcontainer.json."
            )
            return
        command = compose.shell_command(self._docker, container, self.config, inspected)
        # The output of `docker compose up` stays on screen above the prompt.
        self._terminal.use_shell(command, self._terminal_env(), clear=False)
        self.connected.emit()

    # Helpers.

    def _find_container(self, then: Callable[[str], None]) -> None:
        command = compose.find_container_command(
            self._docker, self._project, self.config.service
        )
        self._capture(command, then)

    def _terminal_env(self) -> dict[str, str]:
        """The environment for Docker commands that run in the terminal."""
        return shell_environment(self._env)

    def _capture(
        self,
        command: list[str],
        then: Callable[[str], None],
        on_failure: Callable[[str], None] | None = None,
        timeout_ms: int | None = None,
    ) -> None:
        """Run a command out of sight and pass what it printed to `then`.

        If it cannot be run, or exits with an error, `on_failure` gets the
        reason; by default that fails the whole bring-up.
        """
        on_failure = on_failure or self._fail
        process = QProcess(self)
        self._process = process
        process.setProgram(command[0])
        process.setArguments(command[1:])
        process.setWorkingDirectory(str(self.config.folder))
        process.setProcessEnvironment(_process_environment(self._env))

        def finish(succeeded: bool) -> None:
            if self._process is not process:
                # Abandoned by `leave`, or already finished another way.
                return
            self._process = None
            process.deleteLater()
            output = bytes(process.readAllStandardOutput()).decode(errors="replace")
            if succeeded:
                then(output)
                return
            errors = bytes(process.readAllStandardError()).decode(errors="replace")
            lines = (errors.strip() or output.strip()).splitlines()
            program = Path(command[0]).name
            on_failure(lines[-1] if lines else f"{program} could not be run.")

        process.finished.connect(
            lambda code, status: finish(
                code == 0 and status == QProcess.ExitStatus.NormalExit
            )
        )
        # `finished` is not sent for a program that never started.
        process.errorOccurred.connect(
            lambda error: (
                finish(False) if error == QProcess.ProcessError.FailedToStart else None
            )
        )
        if timeout_ms is not None:
            QTimer.singleShot(timeout_ms, process, process.kill)
        process.start()

    def _fail(self, reason: str) -> None:
        if self._active:
            self._active = False
            self.failed.emit(reason)


def _process_environment(env: dict[str, str]) -> QProcessEnvironment:
    environment = QProcessEnvironment()
    for name, value in env.items():
        environment.insert(name, value)
    return environment
