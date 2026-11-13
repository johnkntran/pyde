"""The main application window."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow

from pyde import __version__

RESOURCES = Path(__file__).parent / "resources"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
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
