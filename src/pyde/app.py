"""Application startup."""

import argparse
import sys
from pathlib import Path

from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pyde import __version__
from pyde.highlighter import DARK_STYLE, LIGHT_STYLE, lexer_for

# Importing the window also imports QtWebEngine, which Qt requires to happen
# before the QApplication is created.
from pyde.main_window import MainWindow

SMOKE_TEST_TIMEOUT_MS = 30_000
# One file name for each of the Pygments lexer modules worth checking.
SMOKE_TEST_FILE_NAMES = ("a.py", "a.json", "a.toml", "a.html", "a.md", "Dockerfile")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pyde", description="The Pyde code editor.")
    parser.add_argument("--version", action="version", version=f"pyde {__version__}")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="start, check the terminal and syntax highlighting, then exit; "
        "used to verify packaged builds",
    )
    parser.add_argument(
        "path", nargs="?", type=Path, help="a folder or file to open at startup"
    )
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Pyde")
    app.setApplicationVersion(__version__)

    window = MainWindow()
    if args.path:
        window.open_path(args.path)
    if args.smoke_test:
        _run_smoke_test(app, window)
    window.show()
    return app.exec()


def _run_smoke_test(app: QApplication, window: MainWindow) -> None:
    """Exit 0 if the parts a packaged build is most likely to lack all work.

    Those are the parts loaded by name at run time, which PyInstaller cannot
    see when it decides what to bundle: Pygments' lexers and styles, and the
    terminal, which needs the web engine's helper process, the xterm.js files,
    and a shell on a pseudo-terminal.
    """
    problems = _highlighting_problems()

    def finish(terminal_started: bool) -> None:
        if not terminal_started:
            problems.append("the terminal did not start")
        for problem in problems:
            print(f"smoke test failed: {problem}", file=sys.stderr)
        window.terminal_view.shutdown()
        app.exit(1 if problems else 0)

    window.terminal_view.started.connect(lambda: finish(True))
    QTimer.singleShot(SMOKE_TEST_TIMEOUT_MS, lambda: finish(False))


def _highlighting_problems() -> list[str]:
    problems = []
    for name in SMOKE_TEST_FILE_NAMES:
        try:
            lexer = lexer_for(name)
        except ImportError:
            lexer = None
        if lexer is None:
            problems.append(f"no syntax highlighting for {name}")
    for style in (LIGHT_STYLE, DARK_STYLE):
        try:
            get_style_by_name(style)
        except ClassNotFound:
            problems.append(f"the {style} color style is missing")
    return problems
