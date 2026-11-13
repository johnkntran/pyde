"""The terminal panel: xterm.js in a web view, attached to a shell."""

import os
import pwd
from pathlib import Path

from PySide6.QtCore import QLocale, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget

from pyde import __version__
from pyde.pty_session import PtySession

RESOURCES = Path(__file__).parent / "resources"

# A shell writes its output in many small pieces, often a line at a time.
# Passing each one to the page separately is slow, so they are gathered for
# this long and sent together. It is too short a wait to notice when typing.
OUTPUT_BATCH_MS = 5
# How much output may be on its way to the page, in characters. Past the high
# mark the shell is paused; it resumes once the page is back under the low one.
HIGH_WATER_MARK = 1_000_000
LOW_WATER_MARK = 200_000

# Erases the screen and scrollback, for a fresh start in a new folder.
RESET = "\x1bc"
EXITED_NOTICE = "\r\n[The shell has exited. Press Return to start a new one.]\r\n"


def default_shell() -> str:
    """The user's own shell."""
    return os.environ.get("SHELL") or pwd.getpwuid(os.getuid()).pw_shell


def shell_environment() -> dict[str, str]:
    """The environment a shell in the terminal starts with."""
    env = dict(os.environ)
    env.update(
        TERM="xterm-256color",
        COLORTERM="truecolor",
        TERM_PROGRAM="Pyde",
        TERM_PROGRAM_VERSION=__version__,
    )
    # An app launched from the Finder has no locale in its environment, and
    # without a UTF-8 one a shell garbles anything that is not ASCII.
    if not any(env.get(name) for name in ("LC_ALL", "LC_CTYPE", "LANG")):
        language = QLocale.system().name()
        # Qt answers "C" when it cannot tell, and macOS has no C.UTF-8 locale
        # on older versions.
        if "_" not in language:
            language = "en_US"
        env["LANG"] = f"{language}.UTF-8"
    return env


class _Bridge(QObject):
    """The one object the terminal page can see, over the Qt web channel.

    Its signals go to the page; its slots are what the page may call.
    """

    output = Signal(str)
    theme = Signal(bool)
    focus = Signal()

    def __init__(self, terminal: "TerminalView") -> None:
        super().__init__(terminal)
        self._terminal = terminal

    @Slot(int, int)
    def start(self, rows: int, columns: int) -> None:
        self._terminal.page_ready(rows, columns)

    @Slot(str)
    def write(self, text: str) -> None:
        self._terminal.typed(text)

    @Slot(int, int)
    def resize(self, rows: int, columns: int) -> None:
        self._terminal.resized(rows, columns)

    @Slot(int)
    def ack(self, count: int) -> None:
        self._terminal.acknowledged(count)


class TerminalView(QWebEngineView):
    # The page has loaded and a shell is running in it.
    started = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Where shells start.
        self.folder = Path.home()
        # The page's size in rows and columns; None until it has loaded.
        self._size: tuple[int, int] | None = None
        # Characters sent to the page that it has not yet drawn.
        self._unacknowledged = 0
        # Output waiting to be sent to the page in one go.
        self._outbox: list[str] = []
        self._outbox_timer = QTimer(self, singleShot=True, interval=OUTPUT_BATCH_MS)
        self._outbox_timer.timeout.connect(self._send_outbox)

        self._session = PtySession(self)
        self._session.output.connect(self._send)
        self._session.exited.connect(lambda: self._send(EXITED_NOTICE))

        self._bridge = _Bridge(self)
        channel = QWebChannel(self)
        channel.registerObject("pty", self._bridge)
        self.page().setWebChannel(channel)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._send_theme)
        self.load(QUrl.fromLocalFile(RESOURCES / "terminal.html"))

    @property
    def running(self) -> bool:
        """Whether a shell is currently running in the terminal."""
        return self._session.running

    def set_folder(self, folder: Path) -> None:
        """Start shells in `folder`, replacing the current shell with one there."""
        self.folder = folder
        if self._size is not None:
            self._send(RESET)
            self._start_shell()

    def focus_terminal(self) -> None:
        """Put keyboard focus in the terminal, ready to type a command."""
        self.setFocus()
        self._bridge.focus.emit()

    def shutdown(self) -> None:
        """End the shell. Call before the window goes away."""
        self._session.stop()

    # Called by the page, through the bridge.

    def page_ready(self, rows: int, columns: int) -> None:
        self._size = (rows, columns)
        self._send_theme(QGuiApplication.styleHints().colorScheme())
        self._start_shell()
        self.started.emit()

    def typed(self, text: str) -> None:
        if self._session.running:
            self._session.write(text)
        elif "\r" in text:
            self._start_shell()

    def resized(self, rows: int, columns: int) -> None:
        self._size = (rows, columns)
        self._session.resize(rows, columns)

    def acknowledged(self, count: int) -> None:
        self._unacknowledged -= count
        if self._unacknowledged < LOW_WATER_MARK:
            self._session.set_paused(False)

    def _start_shell(self) -> None:
        rows, columns = self._size
        self._session.start(
            default_shell(), self.folder, shell_environment(), rows, columns
        )

    def _send(self, text: str) -> None:
        """Show text in the terminal, shortly."""
        self._outbox.append(text)
        if not self._outbox_timer.isActive():
            self._outbox_timer.start()

    def _send_outbox(self) -> None:
        """Pass the gathered output on, pausing the shell if the page is behind."""
        text = "".join(self._outbox)
        self._outbox.clear()
        self._unacknowledged += len(text)
        if self._unacknowledged > HIGH_WATER_MARK:
            self._session.set_paused(True)
        self._bridge.output.emit(text)

    def _send_theme(self, scheme: Qt.ColorScheme) -> None:
        self._bridge.theme.emit(scheme == Qt.ColorScheme.Dark)
