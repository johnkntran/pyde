"""The thread that reads a Windows session's output, given a process to read.

A stand-in process says what the test tells it to, when it is told to, so
these run the same on every system and do not depend on how fast a real one
happens to be.
"""

import importlib
import importlib.util
import queue
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import shiboken6
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest


class FakeProcess:
    """Stands in for pywinpty's process."""

    exitstatus = 0

    def __init__(self):
        # What `read` hands over next; it waits while there is nothing. None
        # is the end of the output.
        self.output = queue.Queue()
        self.terminated = False

    def read(self, size):
        text = self.output.get(timeout=30)
        if text is None:
            raise EOFError
        return text

    def terminate(self, force=False):
        self.terminated = True

    def wait(self):
        return self.exitstatus


class Harness:
    """A session reading from a stand-in process, and what it has announced."""

    def __init__(self, module, monkeypatch, parent=None):
        spawn = lambda *args, **kwargs: self.process  # noqa: E731
        monkeypatch.setattr(module, "PtyProcess", SimpleNamespace(spawn=spawn))
        # The threads the session starts, kept as they are started.
        self.threads = []

        def thread(**arguments):
            self.threads.append(threading.Thread(**arguments))
            return self.threads[-1]

        stand_in = SimpleNamespace(Thread=thread, Event=threading.Event)
        monkeypatch.setattr(module, "threading", stand_in)

        self.session = module.PtySession(parent)
        self.text = []
        self.statuses = []
        self.session.output.connect(self.text.append)
        self.session.exited.connect(self.statuses.append)
        self.start()

    def start(self):
        """Start the session on a new process, as its shell."""
        self.process = FakeProcess()
        self.session.start(["shell"], Path.cwd(), {}, rows=24, columns=80)
        self.thread = self.threads[-1]

    def end_output(self, *text):
        """Have the process write this, then reach the end of its output."""
        for piece in (*text, None):
            self.process.output.put(piece)
        self.thread.join(timeout=30)
        assert not self.thread.is_alive()


@pytest.fixture
def pty_windows(monkeypatch):
    """The module that holds the Windows session.

    It imports pywinpty, which is installed only on Windows. Elsewhere a
    stand-in for it is enough, since these tests supply the process.
    """
    if importlib.util.find_spec("winpty") is None:
        monkeypatch.setitem(sys.modules, "winpty", SimpleNamespace(PtyProcess=None))
    return importlib.import_module("pyde.pty_windows")


@pytest.fixture
def thread_errors(monkeypatch):
    """The exceptions that end threads, which Python would otherwise only print."""
    errors = []
    monkeypatch.setattr(threading, "excepthook", errors.append)
    return errors


def test_what_the_process_writes_is_announced_and_then_its_exit_status(
    qapp, pty_windows, monkeypatch, wait_until
):
    harness = Harness(pty_windows, monkeypatch)
    harness.process.exitstatus = 3

    harness.process.output.put("hello")
    wait_until(lambda: harness.text == ["hello"])
    assert harness.session.running

    harness.end_output("bye")
    wait_until(lambda: harness.statuses)

    assert harness.text == ["hello", "bye"]
    assert harness.statuses == [3]
    assert not harness.session.running


def test_a_stopped_session_announces_nothing_more(qapp, pty_windows, monkeypatch):
    harness = Harness(pty_windows, monkeypatch)

    harness.session.stop()
    assert harness.process.terminated
    harness.end_output("written while it was being stopped")
    QTest.qWait(100)

    assert harness.text == []
    assert harness.statuses == []


def test_a_session_started_again_announces_its_new_process(
    qapp, pty_windows, monkeypatch, wait_until
):
    harness = Harness(pty_windows, monkeypatch)
    harness.session.stop()
    harness.end_output("from the first")

    harness.start()
    harness.end_output("from the second")
    wait_until(lambda: harness.statuses)

    assert harness.text == ["from the second"]
    assert harness.statuses == [0]


def test_a_reader_that_outlives_its_session_ends_quietly(
    qapp, pty_windows, monkeypatch, thread_errors
):
    # As when the window closes: the session is stopped, and then goes with
    # the window while its thread is still reading.
    window = QObject()
    harness = Harness(pty_windows, monkeypatch, parent=window)

    harness.session.stop()
    shiboken6.delete(window)
    harness.end_output("written while it was being stopped")

    # Announcing anything now would fail, there being no session to do it.
    assert thread_errors == []
