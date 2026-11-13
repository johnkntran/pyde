import json
import os
import sys
import time

import pytest

# Keep windows off the screen while testing. This has to be set before Qt loads.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Terminals in tests run a plain shell, not the user's own with its profile.
os.environ["SHELL"] = "/bin/sh"


@pytest.fixture(scope="session")
def qapp():
    # QtWebEngine has to be imported before the QApplication is created.
    from PySide6.QtWidgets import QApplication

    import pyde.main_window  # noqa: F401

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_unexpected_dialogs(monkeypatch):
    """Fail, rather than hang, if a dialog opens that the test did not answer.

    A test that expects a dialog replaces the same function with its answer.
    """
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    def unexpected(*args, **kwargs):
        raise AssertionError("a dialog opened that the test did not expect")

    monkeypatch.setattr(QMessageBox, "warning", unexpected)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", unexpected)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", unexpected)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", unexpected)


@pytest.fixture
def window(qapp, tmp_path):
    """A main window whose settings live in a temporary folder."""
    from pyde.main_window import MainWindow

    window = MainWindow(config_dir=tmp_path / "config")
    yield window
    # Closing would otherwise ask about any changes the test left unsaved.
    for editor in window.editors():
        editor.document().setModified(False)
    window.close()


@pytest.fixture
def wait_until(qapp):
    """Run the Qt event loop until a condition holds, failing after a timeout."""
    from PySide6.QtTest import QTest

    def wait_until(condition, timeout=5.0):
        deadline = time.monotonic() + timeout
        while not condition():
            assert time.monotonic() < deadline, "timed out waiting for the condition"
            QTest.qWait(20)

    return wait_until


@pytest.fixture
def color_at():
    """Look up the text color the syntax highlighter gave a character."""
    from PySide6.QtCore import Qt

    def color_at(document, line, column):
        """The color as "#rrggbb", or None where the text has the default color."""
        block = document.findBlockByNumber(line)
        for span in block.layout().formats():
            if span.start <= column < span.start + span.length:
                brush = span.format.foreground()
                if brush.style() != Qt.BrushStyle.NoBrush:
                    return brush.color().name()
        return None

    return color_at


# Stands in for the docker program. It records how it was called and answers
# from files in its state folder, so tests need neither Docker nor a network.
FAKE_DOCKER = """\
#!{python}
import json, os, pathlib, sys

state = pathlib.Path(__file__).parent.parent / "state"
args = sys.argv[1:]
with open(state / "calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")

if args[:1] == ["compose"] and "config" in args:
    print((state / "config.json").read_text())
elif args[:1] == ["compose"] and "up" in args:
    code = int((state / "up_exit_code").read_text())
    if code == 0:
        print("fake docker: containers started")
        (state / "container").write_text("abc123")
    else:
        print("fake docker: could not start", file=sys.stderr)
    sys.exit(code)
elif args[:1] == ["compose"] and "stop" in args:
    import time

    time.sleep(float((state / "stop_seconds").read_text()))
    (state / "stopped").write_text("yes")
    with open(state / "calls.jsonl", "a") as log:
        log.write(json.dumps(["stop-finished"]) + "\\n")
elif args[:1] == ["ps"]:
    if (state / "container").exists():
        print((state / "container").read_text())
elif args[:1] == ["inspect"]:
    print((state / "inspect.json").read_text())
elif args[:1] == ["exec"] and "markers" in args:
    # Which once-only lifecycle hooks have yet to run.
    print((state / "stale_hooks").read_text())
elif args[:1] == ["exec"] and "pyde" in args and args[-1] != "pyde":
    # A lifecycle command: the words after the script's name are the marker
    # file, its stamp, the kind of command, and the command itself.
    marker, stamp, kind, *command = args[args.index("pyde") + 1 :]
    print("fake docker: ran", " ".join(command))
    failing = (state / "failing_command").read_text()
    if failing and failing in command:
        sys.exit(9)
    if marker:
        with open(state / "recorded_hooks", "a") as recorded:
            recorded.write(marker + "\\n")
elif args[:1] == ["exec"]:
    # A local shell plays the part of the one inside the container. It gets
    # the variables that were passed with --env, so tests can look for them.
    for flag, value in zip(args, args[1:]):
        if flag == "--env":
            name, _, text = value.partition("=")
            os.environ[name] = text
    os.environ["INSIDE"] = "fake-container"
    os.execv("/bin/sh", ["/bin/sh"])
else:
    sys.exit(2)
"""


class FakeDocker:
    """The stand-in docker program, and what it has been asked to do."""

    def __init__(self, folder):
        self.bin = folder / "bin"
        self.state = folder / "state"
        self.bin.mkdir(parents=True)
        self.state.mkdir()
        program = self.bin / "docker"
        program.write_text(FAKE_DOCKER.format(python=sys.executable))
        program.chmod(0o755)
        self.set_project({"name": "devcontainer", "services": {"app": {}}})
        self.set_container()
        self.set_up_exit_code(0)
        self.set_stale_hooks(
            "onCreateCommand",
            "updateContentCommand",
            "postCreateCommand",
            "postStartCommand",
        )
        self.set_failing_command("")
        self.set_stop_seconds(0)

    def set_project(self, project):
        """What `docker compose config` reports."""
        (self.state / "config.json").write_text(json.dumps(project))

    def set_container(self, running=True, user="", env=(), labels=None):
        """What `docker inspect` reports about the service's container."""
        config = {"User": user, "Env": list(env), "Labels": labels or {}}
        state = {"Running": running, "StartedAt": "2026-01-02T00:00:00Z"}
        inspected = [
            {"Created": "2026-01-01T00:00:00Z", "State": state, "Config": config}
        ]
        (self.state / "inspect.json").write_text(json.dumps(inspected))

    def set_stale_hooks(self, *hooks):
        """The once-only lifecycle hooks that have yet to run in the container."""
        (self.state / "stale_hooks").write_text("\n".join(hooks))

    def set_stop_seconds(self, seconds):
        """How long `docker compose stop` takes."""
        (self.state / "stop_seconds").write_text(str(seconds))

    def set_failing_command(self, command):
        """Make the lifecycle command with this text exit with an error."""
        (self.state / "failing_command").write_text(command)

    @property
    def recorded_hooks(self):
        """The marker files written by hooks that ran to the end."""
        recorded = self.state / "recorded_hooks"
        return recorded.read_text().split() if recorded.exists() else []

    def set_up_exit_code(self, code):
        (self.state / "up_exit_code").write_text(str(code))

    def container_exists(self):
        """Pretend an earlier session left the container behind."""
        (self.state / "container").write_text("abc123")

    @property
    def calls(self):
        """The arguments of every call so far, in order."""
        log = self.state / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def calls_to(self, *words):
        """The calls whose arguments include all of `words`."""
        return [call for call in self.calls if all(word in call for word in words)]

    @property
    def shell_calls(self):
        """The calls that opened a shell in the container."""
        return [call for call in self.calls_to("exec") if call[-1] == "pyde"]

    @property
    def hook_commands(self):
        """The lifecycle commands run in the container, as lists of words."""
        commands = []
        for call in self.calls_to("exec"):
            if "markers" not in call and call[-1] != "pyde":
                commands.append(call[call.index("pyde") + 4 :])
        return commands

    @property
    def stopped(self):
        return (self.state / "stopped").exists()


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    """Put the stand-in docker first on the PATH."""
    if sys.platform == "win32":
        pytest.skip("the stand-in docker is a Unix script")
    fake = FakeDocker(tmp_path / "fake-docker")
    monkeypatch.setenv("PATH", f"{fake.bin}{os.pathsep}{os.environ['PATH']}")
    return fake


@pytest.fixture
def project(tmp_path):
    """A folder with a small Docker Compose dev container configuration."""
    folder = tmp_path / "project"
    (folder / ".devcontainer").mkdir(parents=True)
    (folder / ".devcontainer" / "docker-compose.yml").write_text("services: {}\n")
    (folder / ".devcontainer" / "devcontainer.json").write_text(
        json.dumps(
            {
                "name": "Sample",
                "dockerComposeFile": "docker-compose.yml",
                "service": "app",
                "workspaceFolder": "/workspace",
            }
        )
    )
    return folder
