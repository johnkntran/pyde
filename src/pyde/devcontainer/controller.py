"""Bringing a folder's dev container up and putting the terminal inside it."""

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QProcess,
    QProcessEnvironment,
    QTimer,
    Signal,
)

from pyde import shell_env
from pyde.devcontainer import compose
from pyde.devcontainer.config import HOOKS, DevContainerConfig
from pyde.terminal import TerminalView, default_shell, shell_environment

# How long the user's shell gets to report its environment before Pyde gives
# up on it. A startup file that waits for input would otherwise hang forever.
ENVIRONMENT_TIMEOUT_MS = 10_000


class DevContainer(QObject):
    """One folder's dev container, from "Reopen in Container" to leaving it.

    Bringing it up is a chain of commands. Each short Docker command runs out
    of sight and hands its output to the next step. The long ones, `docker
    compose up` and the devcontainer.json's lifecycle commands, run in the
    terminal, where they can be watched. Nothing blocks the window meanwhile.
    """

    # The terminal is now a shell inside the container.
    connected = Signal()
    # The container could not be brought up. The text says what went wrong.
    failed = Signal(str)
    # Something went wrong that the container can be used in spite of.
    warned = Signal(str)

    # The `docker compose stop` commands still running, by project name. A
    # bring-up of the same project waits for its one to finish; otherwise the
    # stop would take down the containers the bring-up had just started.
    _stopping: dict[str, QProcess] = {}

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
        self._rebuild = False
        # Learned along the way: whether the service had a container before
        # this, then the container's id and Docker's description of it.
        self._container_existed = False
        self._container = ""
        self._inspected: dict = {}

    def start(self, rebuild: bool = False) -> None:
        """Begin bringing the container up. Ends in `connected` or `failed`.

        With `rebuild`, the images are built again and the containers replaced,
        so the commands that run once per container run again.
        """
        self._active = True
        self._rebuild = rebuild
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

    def leave(self, stop: bool = True, quitting: bool = False) -> None:
        """Stop working in the container. The terminal is left to the caller.

        Abandons a bring-up in progress. Unless `stop` is false, as when the
        container is about to be brought up again, it also stops the
        containers if the devcontainer.json asks for that. Pass `quitting`
        when Pyde is about to exit, so that the stop outlives it.
        """
        self._active = False
        if self._process is not None:
            self._process.kill()
            self._process = None
        if not (stop and self._docker and self._project and self.config.stop_on_close):
            return

        command = compose.stop_command(self._docker, self._project, self.config)
        stopper = QProcess(None if quitting else QCoreApplication.instance())
        stopper.setProgram(command[0])
        stopper.setArguments(command[1:])
        stopper.setProcessEnvironment(_process_environment(self._env))
        if quitting:
            stopper.setStandardOutputFile(QProcess.nullDevice())
            stopper.setStandardErrorFile(QProcess.nullDevice())
            stopper.startDetached()
            return
        project = self._project
        DevContainer._stopping[project] = stopper
        stopper.finished.connect(lambda *_: _forget_stop(project, stopper))
        stopper.errorOccurred.connect(lambda *_: _forget_stop(project, stopper))
        stopper.start()

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
        self._find_container(self._initialize)

    def _initialize(self, output: str) -> None:
        self._container_existed = bool(output.strip())
        if self.config.ignored:
            ignored = ", ".join(self.config.ignored)
            self._terminal.show_message(
                f"Pyde does not act on these devcontainer.json properties: {ignored}."
            )
        # initializeCommand runs here on the Mac, before any container starts.
        commands = self.config.hooks.get("initializeCommand", ())
        tasks = [("initializeCommand", compose.host_command(c)) for c in commands]
        self._run_tasks(tasks, self._bring_up, on_failure=self._task_failed)

    def _bring_up(self, *_: object) -> None:
        if not self._active:
            return
        stopping = DevContainer._stopping.get(self._project)
        if stopping is not None:
            # Left a moment ago, and the containers are still stopping.
            self._terminal.show_message("Waiting for the containers to finish stopping")
            stopping.finished.connect(self._bring_up)
            return
        self._override_file.parent.mkdir(parents=True, exist_ok=True)
        # JSON is YAML too, so Compose reads this like any other Compose file.
        document = compose.override(self.config)
        self._override_file.write_text(json.dumps(document, indent=2), encoding="utf-8")

        command = compose.up_command(
            self._docker,
            self._project,
            self.config,
            str(self._override_file),
            container_exists=self._container_existed,
            rebuild=self._rebuild,
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
        self._container = containers[0]
        self._capture(
            compose.inspect_command(self._docker, self._container), self._find_stale
        )

    def _find_stale(self, output: str) -> None:
        try:
            self._inspected = json.loads(output)[0]
        except (ValueError, IndexError, KeyError):
            self._fail("Docker's description of the container made no sense.")
            return
        if not compose.is_running(self._inspected):
            self._fail(
                f"The {self.config.service!r} container is not running. If its"
                ' command exits straight away, set "overrideCommand": true in'
                " devcontainer.json."
            )
            return
        command = compose.stale_hooks_command(
            self._docker, self._container, self.config, self._inspected
        )
        self._capture(command, self._run_hooks)

    def _run_hooks(self, output: str) -> None:
        """Run the lifecycle commands that are due, inside the container."""
        stale = set(output.split())
        tasks = []
        for hook in HOOKS[1:]:
            # postAttachCommand runs every time. The others run once per
            # container, or once per start, and only if still due.
            once_only = hook != "postAttachCommand"
            if once_only and hook not in stale:
                continue
            commands = self.config.hooks.get(hook, ())
            for position, command in enumerate(commands, start=1):
                # A hook counts as done when the last of its commands succeeds.
                record = hook if once_only and position == len(commands) else None
                task = compose.hook_command(
                    self._docker,
                    self._container,
                    self.config,
                    self._inspected,
                    command,
                    record,
                )
                tasks.append((hook, task))
        self._run_tasks(tasks, self._open_shell, on_failure=self._hook_failed)

    def _hook_failed(self, hook: str, status: int) -> None:
        # The container itself is fine, so carry on to the shell and say so.
        self._open_shell()
        self.warned.emit(
            f"{hook} failed with exit status {status}, so the lifecycle"
            " commands after it were skipped."
        )

    def _open_shell(self) -> None:
        command = compose.shell_command(
            self._docker, self._container, self.config, self._inspected
        )
        # What ran before stays on screen above the prompt.
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

    def _run_tasks(
        self,
        tasks: list[tuple[str, list[str]]],
        then: Callable[[], None],
        on_failure: Callable[[str, int], None],
    ) -> None:
        """Run lifecycle commands in the terminal, one after another, then `then`.

        Each comes with the name of its hook. It stops at the first that fails,
        and gives `on_failure` that one's hook and exit status.
        """
        if not self._active:
            return
        if not tasks:
            then()
            return
        (name, command), rest = tasks[0], tasks[1:]

        def done(status: int) -> None:
            if not self._active:
                return
            if status == 0:
                self._run_tasks(rest, then, on_failure)
            else:
                on_failure(name, status)

        self._terminal.show_message(f"Running {name}")
        self._terminal.run_task(command, self._terminal_env(), done)

    def _task_failed(self, name: str, status: int) -> None:
        self._fail(f"{name} failed with exit status {status}. See the terminal.")

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


def _forget_stop(project: str, stopper: QProcess) -> None:
    if DevContainer._stopping.get(project) is stopper:
        del DevContainer._stopping[project]
    stopper.deleteLater()


def _process_environment(env: dict[str, str]) -> QProcessEnvironment:
    environment = QProcessEnvironment()
    for name, value in env.items():
        environment.insert(name, value)
    return environment
