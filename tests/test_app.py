import subprocess
import sys
from importlib.metadata import version

from PySide6.QtCore import Qt
from PySide6.QtWebEngineWidgets import QWebEngineView


def run_pyde(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pyde", *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_version_flag_prints_the_project_version():
    result = run_pyde("--version")

    assert result.returncode == 0
    assert result.stdout.strip() == f"pyde {version('pyde')}"


def test_smoke_test_loads_the_web_view_and_exits_cleanly():
    result = run_pyde("--smoke-test")

    assert result.returncode == 0, result.stderr


def test_main_window_hosts_a_web_view_in_the_bottom_dock(qapp):
    from pyde.main_window import MainWindow

    window = MainWindow()

    assert window.windowTitle() == "Pyde"
    assert isinstance(window.terminal_dock.widget(), QWebEngineView)
    assert (
        window.dockWidgetArea(window.terminal_dock)
        == Qt.DockWidgetArea.BottomDockWidgetArea
    )
