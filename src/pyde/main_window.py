"""The main application window."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow

from pyde import __version__
from pyde.commands import CommandRegistry
from pyde.keybindings import Keybindings

RESOURCES = Path(__file__).parent / "resources"

STATUS_MESSAGE_MS = 10_000


def default_config_dir() -> Path:
    """Where the user's settings live: ~/Library/Application Support/Pyde."""
    location = QStandardPaths.StandardLocation.AppDataLocation
    return Path(QStandardPaths.writableLocation(location))


def open_externally(path: Path) -> None:
    """Open a file in the user's default app for it."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


class MainWindow(QMainWindow):
    def __init__(self, config_dir: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Pyde")
        self.resize(1200, 800)

        # Placeholder until the editor lands.
        placeholder = QLabel(f"Pyde {__version__}")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setEnabled(False)
        self.setCentralWidget(placeholder)

        # The terminal will be xterm.js running in this web view. Until then it
        # shows a static page, so every build already bundles and exercises
        # QtWebEngine.
        self.terminal_view = QWebEngineView()
        self.terminal_view.load(QUrl.fromLocalFile(RESOURCES / "terminal.html"))

        self.terminal_dock = QDockWidget("Terminal", self)
        self.terminal_dock.setObjectName("terminal")
        self.terminal_dock.setWidget(self.terminal_view)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.terminal_dock)
        # Without this the web view's size hint claims most of the window.
        self.resizeDocks([self.terminal_dock], [260], Qt.Orientation.Vertical)

        self.commands = CommandRegistry(self)
        self._add_commands()

        config_dir = config_dir or default_config_dir()
        self.keybindings = Keybindings(
            self.commands, config_dir / "keybindings.json", parent=self
        )
        status_bar = self.statusBar()
        self.keybindings.message.connect(
            lambda text: status_bar.showMessage(text, STATUS_MESSAGE_MS)
        )
        self.keybindings.load()

    def _add_commands(self) -> None:
        register = self.commands.register
        toggle_terminal = register(
            "view.toggleTerminal", "Toggle Terminal", self.toggle_terminal, key="ctrl+`"
        )
        open_keybindings = register(
            "preferences.openKeybindings",
            "Open Keyboard Shortcuts",
            self.open_keybindings,
            key="cmd+k cmd+s",
        )
        open_default_keybindings = register(
            "preferences.openDefaultKeybindings",
            "Open Default Keyboard Shortcuts",
            self.open_default_keybindings,
        )

        menu_bar = self.menuBar()
        menu_bar.addMenu("View").addAction(toggle_terminal)

        # macOS moves actions with this role into the application menu, and
        # hides the menu they came from once it is empty.
        preferences_menu = menu_bar.addMenu("Preferences")
        for action in (open_keybindings, open_default_keybindings):
            action.setMenuRole(QAction.MenuRole.ApplicationSpecificRole)
            preferences_menu.addAction(action)

    def toggle_terminal(self) -> None:
        self.terminal_dock.setVisible(not self.terminal_dock.isVisible())

    def open_keybindings(self) -> None:
        open_externally(self.keybindings.ensure_user_file())

    def open_default_keybindings(self) -> None:
        open_externally(self.keybindings.write_defaults_file())
