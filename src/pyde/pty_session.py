"""A program running on a pseudo-terminal, driven from the Qt event loop."""

import codecs
import fcntl
import os
import signal
import struct
import termios
import time
from pathlib import Path

from PySide6.QtCore import QObject, QSocketNotifier, QTimer, Signal

READ_SIZE = 65_536
# How often to check whether the shell is still alive.
EXIT_POLL_MS = 200
# How long a shell gets to exit on its own when stopped, before it is killed.
STOP_GRACE_SECONDS = 0.5

# Runs under /bin/sh: go to the folder in $0, then become the program in the
# remaining arguments. The folder may have been deleted; a shell somewhere
# beats no shell at all.
_LAUNCH = 'cd -- "$0" 2>/dev/null; exec "$@"'


class PtySession(QObject):
    """One process, usually a shell, and the terminal device it is attached to."""

    # Text the program wrote to the terminal.
    output = Signal(str)
    # The program has ended, with this exit status: its exit code, or the
    # negative of the number of the signal that killed it.
    exited = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pid: int | None = None
        # The two ends of the terminal device: Pyde reads and writes the
        # master, and the shell is attached to the slave.
        self._master = -1
        self._slave = -1
        # Input not yet accepted by the terminal device.
        self._pending = bytearray()
        self._reader: QSocketNotifier | None = None
        self._writer: QSocketNotifier | None = None
        self._exit_poll = QTimer(self, interval=EXIT_POLL_MS)
        self._exit_poll.timeout.connect(self._check_exited)

    @property
    def running(self) -> bool:
        return self._pid is not None

    def start(
        self,
        argv: list[str],
        folder: Path,
        env: dict[str, str],
        rows: int,
        columns: int,
    ) -> None:
        """Run a command in `folder`, replacing whatever was running."""
        self.stop()
        master = os.posix_openpt(os.O_RDWR | os.O_NOCTTY)
        os.grantpt(master)
        os.unlockpt(master)
        os.set_blocking(master, False)
        slave_name = os.ptsname(master)
        # Pyde keeps the slave open too, though it never uses it. With nothing
        # else holding it, macOS throws away the unread output of a process
        # the moment it exits. With it held, the exit waits until that output
        # has been read, so a program's last words always arrive.
        slave = os.open(slave_name, os.O_RDWR | os.O_NOCTTY)
        self._master, self._slave = master, slave
        self.resize(rows, columns)

        # The child starts a session of its own and then opens the terminal by
        # name, which on macOS makes it the session's controlling terminal:
        # what job control and ctrl+c depend on. posix_spawn does this without
        # running any Python in the child, unlike fork, which is unsafe in a
        # process that already has threads, as a Qt app does.
        stdin, stdout, stderr = 0, 1, 2
        file_actions = [
            (os.POSIX_SPAWN_OPEN, stdin, slave_name, os.O_RDWR, 0),
            (os.POSIX_SPAWN_DUP2, stdin, stdout),
            (os.POSIX_SPAWN_DUP2, stdin, stderr),
        ]
        launch = ["/bin/sh", "-c", _LAUNCH, str(folder), *argv]
        try:
            self._pid = os.posix_spawn(
                "/bin/sh", launch, env, file_actions=file_actions, setsid=True
            )
        except OSError:
            self._release()
            raise

        # Text can arrive split in the middle of a multi-byte character.
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._reader = QSocketNotifier(master, QSocketNotifier.Type.Read, self)
        self._reader.activated.connect(self._read)
        self._writer = QSocketNotifier(master, QSocketNotifier.Type.Write, self)
        self._writer.setEnabled(False)
        self._writer.activated.connect(self._flush)
        self._exit_poll.start()

    def write(self, text: str) -> None:
        """Send text to the shell, as if typed."""
        if self.running:
            self._pending += text.encode()
            self._flush()

    def resize(self, rows: int, columns: int) -> None:
        """Tell the terminal device its size, which notifies the shell."""
        if self._master >= 0:
            size = struct.pack("HHHH", rows, columns, 0, 0)
            fcntl.ioctl(self._master, termios.TIOCSWINSZ, size)

    def set_paused(self, paused: bool) -> None:
        """Stop or resume reading the shell's output.

        While paused the terminal device fills up and the shell's programs
        wait, which is how a flood of output is kept from swamping the reader.
        """
        if self._reader is not None:
            self._reader.setEnabled(not paused)

    def stop(self) -> None:
        """End the shell, and wait until it has gone."""
        pid = self._pid
        if pid is None:
            return
        self._release()
        # Closing the terminal device hangs up on the shell, which is its cue
        # to exit. One that ignores it is killed.
        deadline = time.monotonic() + STOP_GRACE_SECONDS
        while os.waitpid(pid, os.WNOHANG)[0] == 0:
            if time.monotonic() > deadline:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                break
            time.sleep(0.01)

    def _read(self) -> None:
        try:
            data = os.read(self._master, READ_SIZE)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if data:
            self.output.emit(self._decoder.decode(data))
        elif self._reader is not None:
            # The terminal device has failed. Stop listening; the exit check
            # will notice when the shell has gone.
            self._reader.setEnabled(False)

    def _flush(self) -> None:
        while self._pending:
            try:
                written = os.write(self._master, self._pending)
            except BlockingIOError:
                # The terminal device is full; carry on when it has room.
                self._writer.setEnabled(True)
                return
            except OSError:
                self._pending.clear()
                break
            del self._pending[:written]
        if self._writer is not None:
            self._writer.setEnabled(False)

    def _check_exited(self) -> None:
        if self._pid is None:
            return
        pid, status = os.waitpid(self._pid, os.WNOHANG)
        if pid:
            self._release()
            self.exited.emit(os.waitstatus_to_exitcode(status))

    def _release(self) -> None:
        """Forget the shell and close the terminal device."""
        self._exit_poll.stop()
        for notifier in (self._reader, self._writer):
            if notifier is not None:
                notifier.setEnabled(False)
                notifier.deleteLater()
        self._reader = self._writer = None
        for end in (self._master, self._slave):
            if end >= 0:
                os.close(end)
        self._master = self._slave = -1
        self._pending.clear()
        self._pid = None
