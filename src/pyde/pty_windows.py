"""The Windows pseudo-terminal session, built on pywinpty.

It offers what `pyde.pty_posix.PtySession` does. The difference inside is that
pywinpty's read blocks, so the reading is done on a thread of its own, which
hands what it reads to the window's thread through signals.
"""

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from winpty import PtyProcess

READ_SIZE = 65_536
# The exit status reported for a program that could not be started, as a Unix
# shell reports a command it cannot find.
NOT_FOUND = 127


class PtySession(QObject):
    """One process, usually a shell, and the pseudo-terminal it is attached to."""

    # Text the program wrote to the terminal.
    output = Signal(str)
    # The program has ended, with this exit status.
    exited = Signal(int)

    # From the reading thread to the window's thread, each with the process it
    # is about: some text was read, or the output has ended.
    _was_read = Signal(object, str)
    _has_ended = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: PtyProcess | None = None
        # Set when the process is stopped, to tell its reading thread so.
        self._stopped = threading.Event()
        # Cleared to hold the reading thread back while output is paused.
        self._reading = threading.Event()
        self._reading.set()
        self._was_read.connect(self._pass_on)
        self._has_ended.connect(self._finish)

    @property
    def running(self) -> bool:
        return self._process is not None

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
        # The folder may have been deleted; a shell somewhere beats none.
        folder = folder if folder.is_dir() else Path.home()
        try:
            process = PtyProcess.spawn(
                argv, cwd=str(folder), env=env, dimensions=(rows, columns)
            )
        except OSError as error:
            self.output.emit(f"{error}\r\n")
            self.exited.emit(NOT_FOUND)
            return
        self._process = process
        self._stopped = stopped = threading.Event()
        self._reading.set()
        threading.Thread(
            target=self._read_all, args=(process, stopped), daemon=True
        ).start()

    def write(self, text: str) -> None:
        """Send text to the program, as if typed."""
        if self._process is not None:
            try:
                self._process.write(text)
            except EOFError:
                pass

    def resize(self, rows: int, columns: int) -> None:
        if self._process is not None:
            self._process.setwinsize(rows, columns)

    def set_paused(self, paused: bool) -> None:
        """Stop or resume reading the program's output."""
        if paused:
            self._reading.clear()
        else:
            self._reading.set()

    def stop(self) -> None:
        """End the program."""
        process, self._process = self._process, None
        if process is not None:
            self._stopped.set()
            # Let its reading thread run on to the end of the output.
            self._reading.set()
            process.terminate(force=True)

    def _read_all(self, process: PtyProcess, stopped: threading.Event) -> None:
        """Read the program's output until it ends. Runs on its own thread.

        Once the program has been stopped it goes on reading, to the end of
        the output, but announces nothing: by then the session may be gone,
        along with the window it belonged to.
        """
        while True:
            self._reading.wait()
            try:
                text = process.read(READ_SIZE)
            except (EOFError, OSError):
                break
            if text and not stopped.is_set():
                self._was_read.emit(process, text)
        process.wait()
        if not stopped.is_set():
            self._has_ended.emit(process)

    def _pass_on(self, process: PtyProcess, text: str) -> None:
        # Output still arriving from a program that was replaced is dropped.
        if process is self._process:
            self.output.emit(text)

    def _finish(self, process: PtyProcess) -> None:
        if process is self._process:
            self._process = None
            status = process.exitstatus
            self.exited.emit(-1 if status is None else status)
