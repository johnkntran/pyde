"""Application startup."""

import argparse
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pyde import __version__

# Importing the window also imports QtWebEngine, which Qt requires to happen
# before the QApplication is created.
from pyde.main_window import MainWindow

SMOKE_TEST_TIMEOUT_MS = 30_000


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pyde", description="The Pyde code editor.")
    parser.add_argument("--version", action="version", version=f"pyde {__version__}")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="start, wait for the web engine to load a page, then exit; "
        "used to verify packaged builds",
    )
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Pyde")
    app.setApplicationVersion(__version__)

    window = MainWindow()
    if args.smoke_test:
        _exit_when_web_view_loads(app, window)
    window.show()
    return app.exec()


def _exit_when_web_view_loads(app: QApplication, window: MainWindow) -> None:
    """Exit 0 once the web view has loaded its page, 1 on failure or timeout."""

    def finish(ok: bool) -> None:
        if not ok:
            print("smoke test failed: the web view did not load", file=sys.stderr)
        app.exit(0 if ok else 1)

    window.terminal_view.loadFinished.connect(finish)
    QTimer.singleShot(SMOKE_TEST_TIMEOUT_MS, lambda: finish(False))
