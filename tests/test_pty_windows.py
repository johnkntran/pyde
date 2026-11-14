"""The Windows pseudo-terminal session, driving the Command Prompt."""

import os
import sys

import pytest

from pyde.pty_session import PtySession

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="the Windows pseudo-terminal needs Windows"
)

ENV = dict(os.environ)
SHELL = ["cmd.exe"]


class Harness:
    """A session running the Command Prompt, with everything it has written."""

    def __init__(self, folder):
        self.session = PtySession()
        self.text = ""
        self.statuses = []
        self.session.output.connect(self._collect)
        self.session.exited.connect(self.statuses.append)
        self.session.start(SHELL, folder, ENV, rows=24, columns=120)

    def _collect(self, text):
        self.text += text

    def run(self, command):
        self.session.write(command + "\r\n")


@pytest.fixture
def harness(qapp, tmp_path):
    harness = Harness(tmp_path)
    yield harness
    harness.session.stop()


def test_commands_typed_into_the_shell_run_and_their_output_comes_back(
    harness, wait_until
):
    # The answer appears only if the command ran, not where it is echoed back.
    harness.run("set /a 6*7")

    wait_until(lambda: "42" in harness.text, timeout=30)
    assert harness.session.running


def test_the_shell_starts_in_the_given_folder(harness, tmp_path, wait_until):
    harness.run("cd")

    wait_until(lambda: tmp_path.name in harness.text, timeout=30)


def test_the_exit_status_is_the_programs_exit_code(harness, wait_until):
    harness.run("exit 7")

    wait_until(lambda: harness.statuses == [7], timeout=30)
    assert not harness.session.running


def test_any_command_can_be_run_not_only_a_shell(qapp, tmp_path, wait_until):
    session = PtySession()
    text, statuses = [], []
    session.output.connect(text.append)
    session.exited.connect(statuses.append)

    session.start(["cmd.exe", "/c", "echo one two"], tmp_path, ENV, 24, 120)

    wait_until(lambda: statuses == [0], timeout=30)
    assert "one two" in "".join(text)


def test_a_program_that_cannot_be_found_is_reported(qapp, tmp_path, wait_until):
    session = PtySession()
    text, statuses = [], []
    session.output.connect(text.append)
    session.exited.connect(statuses.append)

    session.start(["no-such-program-anywhere"], tmp_path, ENV, 24, 120)

    assert statuses == [127]
    assert "no-such-program-anywhere" in "".join(text)


def test_resizing_and_pausing_do_not_disturb_the_shell(harness, wait_until):
    harness.session.resize(rows=40, columns=100)
    harness.session.set_paused(True)
    harness.session.set_paused(False)
    harness.run("set /a 3*3")

    wait_until(lambda: "9" in harness.text, timeout=30)


def test_stop_ends_the_shell_without_reporting_an_exit(harness, wait_until):
    harness.run("set /a 2*2")
    wait_until(lambda: "4" in harness.text, timeout=30)

    harness.session.stop()

    assert not harness.session.running
    assert harness.statuses == []
