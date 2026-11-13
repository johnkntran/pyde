import os

import pytest
from PySide6.QtTest import QTest

from pyde.pty_session import PtySession

ENV = {"HOME": os.environ["HOME"], "PATH": "/usr/bin:/bin", "TERM": "xterm-256color"}
SHELL = ["/bin/sh", "-l"]


class Harness:
    """A session running /bin/sh, with everything it has written so far."""

    def __init__(self, folder):
        self.session = PtySession()
        self.text = ""
        # The exit status of each program that has ended.
        self.statuses = []
        self.session.output.connect(self._collect)
        self.session.exited.connect(self.statuses.append)
        self.session.start(SHELL, folder, ENV, rows=24, columns=80)

    def _collect(self, text):
        self.text += text.replace("\r", "")

    @property
    def exits(self):
        return len(self.statuses)

    def run(self, command):
        self.session.write(command + "\n")


@pytest.fixture
def harness(qapp, tmp_path):
    harness = Harness(tmp_path)
    yield harness
    harness.session.stop()


def test_commands_typed_into_the_shell_run_and_their_output_comes_back(
    harness, wait_until
):
    harness.run("echo $((6 * 7))-done")

    wait_until(lambda: "42-done" in harness.text)


def test_the_shell_starts_in_the_given_folder(harness, tmp_path, wait_until):
    harness.run("pwd")

    wait_until(lambda: f"\n{tmp_path}\n" in harness.text)


def test_a_missing_folder_still_gets_a_shell(qapp, tmp_path, wait_until):
    harness = Harness(tmp_path / "deleted")

    harness.run("echo still-$((1 + 1))-here")

    wait_until(lambda: "still-2-here" in harness.text)
    harness.session.stop()


def test_the_shell_has_a_controlling_terminal(harness, wait_until):
    # `ps` names a process's controlling terminal, or "??" if it has none.
    # Without one there is no job control and ctrl+c reaches nothing.
    harness.run("echo controlled-by=[$(ps -o tty= -p $$)]")

    wait_until(lambda: "controlled-by=[ttys" in harness.text)
    assert "no job control" not in harness.text


def test_the_shell_is_given_the_environment_and_starts_as_a_login_shell(
    harness, wait_until
):
    harness.run("echo term=$TERM login=$0")

    wait_until(lambda: "term=xterm-256color login=" in harness.text)


def test_the_terminal_size_is_set_at_the_start_and_follows_a_resize(
    harness, wait_until
):
    harness.run("stty size")
    wait_until(lambda: "\n24 80\n" in harness.text)

    harness.session.resize(rows=40, columns=120)
    harness.run("stty size")

    wait_until(lambda: "\n40 120\n" in harness.text)


def test_ctrl_c_interrupts_the_running_command_but_not_the_shell(harness, wait_until):
    harness.run("echo sleeping-$((1 + 1)); sleep 30")
    # Wait until the sleep is really running: typed any earlier, ctrl+c would
    # only throw away the command before the shell had read it.
    wait_until(lambda: "sleeping-2" in harness.text)
    QTest.qWait(200)

    harness.session.write("\x03")
    harness.run("echo back-$((2 + 3))")

    wait_until(lambda: "back-5" in harness.text)
    assert harness.session.running


def test_text_split_across_reads_is_not_garbled(harness, wait_until):
    harness.run("printf 'caf\\303'; sleep 0.3; printf '\\251 ok\\n'")

    wait_until(lambda: "café ok" in harness.text)


def test_a_large_paste_arrives_whole(harness, wait_until):
    # Far more than the terminal device accepts in one write. Raw mode, because
    # a terminal reading whole lines caps a line at about a thousand characters.
    harness.run("stty raw -echo; echo raw-$((1 + 1))-on; head -c 200000 | wc -c")
    # Wait for raw mode itself, not just for the command to be echoed back.
    wait_until(lambda: "raw-2-on" in harness.text)

    harness.session.write("x" * 200_000)

    wait_until(lambda: "200000" in harness.text.split("raw-2-on")[-1], timeout=20)


def test_output_stops_while_paused_and_resumes_afterward(harness, wait_until):
    harness.run("echo ready")
    wait_until(lambda: "\nready\n" in harness.text)

    harness.session.set_paused(True)
    harness.run("echo while-$((1 + 1))-paused")
    with pytest.raises(AssertionError):
        wait_until(lambda: "while-2-paused" in harness.text, timeout=0.5)

    harness.session.set_paused(False)
    wait_until(lambda: "while-2-paused" in harness.text)


def test_the_session_reports_the_shell_exiting_with_its_last_output(
    harness, wait_until
):
    harness.run("echo bye-$((3 + 4)); exit")

    wait_until(lambda: harness.exits == 1)
    assert "bye-7" in harness.text
    assert not harness.session.running


def test_the_exit_status_is_the_programs_exit_code(harness, wait_until):
    harness.run("exit 7")

    wait_until(lambda: harness.statuses == [7])


def test_a_program_killed_by_a_signal_reports_the_signal(harness, wait_until):
    # An interactive shell ignores the gentler signals.
    harness.run("kill -KILL $$")

    wait_until(lambda: harness.statuses == [-9])


def test_any_command_can_be_run_not_only_a_shell(qapp, tmp_path, wait_until):
    session = PtySession()
    text, statuses = [], []
    session.output.connect(text.append)
    session.exited.connect(statuses.append)

    session.start(["/bin/echo", "one two", "three"], tmp_path, ENV, 24, 80)

    wait_until(lambda: statuses == [0])
    assert "one two three" in "".join(text)


def test_stop_ends_the_shell_without_reporting_an_exit(harness, wait_until):
    harness.run("echo up")
    wait_until(lambda: "\nup\n" in harness.text)

    harness.session.stop()

    assert not harness.session.running
    assert harness.exits == 0


def test_the_last_output_of_a_process_that_exits_at_once_is_not_lost(
    harness, wait_until
):
    harness.run("echo ready")
    wait_until(lambda: "\nready\n" in harness.text)

    # Reading is paused, as when the terminal page has fallen behind, while a
    # program prints and exits straight away.
    harness.session.set_paused(True)
    harness.run("exec echo last-$((5 + 5))-words")
    QTest.qWait(500)
    assert harness.exits == 0
    harness.session.set_paused(False)

    wait_until(lambda: harness.exits == 1)
    assert "last-10-words" in harness.text


def test_stop_kills_a_process_that_ignores_hangup(harness, wait_until):
    # Replace the shell with a process that ignores the hangup signal and
    # never reads the terminal, so closing the terminal alone will not end it.
    harness.run("echo going-$((1 + 1)); trap '' HUP; exec sleep 1000")
    wait_until(lambda: "going-2" in harness.text)
    QTest.qWait(200)
    pid = harness.session._pid

    harness.session.stop()

    assert not harness.session.running
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_starting_again_replaces_the_running_shell(harness, tmp_path, wait_until):
    other = tmp_path / "other"
    other.mkdir()

    harness.session.start(SHELL, other, ENV, rows=24, columns=80)
    harness.run("pwd")

    wait_until(lambda: f"\n{other}\n" in harness.text)
