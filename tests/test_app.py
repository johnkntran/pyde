import subprocess
import sys
from importlib.metadata import version

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWebEngineWidgets import QWebEngineView

import pyde.main_window
from pyde.keybindings import to_key_sequence
from pyde.main_window import MainWindow


def run_pyde(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pyde", *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def show(window, wait_until):
    window.show()
    window.activateWindow()
    wait_until(window.isActiveWindow)


def press(window, key):
    QTest.keySequence(window, to_key_sequence(key))


def test_version_flag_prints_the_project_version():
    result = run_pyde("--version")

    assert result.returncode == 0
    assert result.stdout.strip() == f"pyde {version('pyde')}"


def test_smoke_test_loads_the_web_view_and_exits_cleanly():
    result = run_pyde("--smoke-test")

    assert result.returncode == 0, result.stderr


def test_main_window_hosts_a_web_view_in_the_bottom_dock(window):
    assert window.windowTitle() == "Pyde"
    assert isinstance(window.terminal_dock.widget(), QWebEngineView)
    assert (
        window.dockWidgetArea(window.terminal_dock)
        == Qt.DockWidgetArea.BottomDockWidgetArea
    )


def test_pressing_the_default_key_toggles_the_terminal(window, wait_until):
    show(window, wait_until)
    assert window.terminal_dock.isVisible()

    press(window, "ctrl+`")
    assert not window.terminal_dock.isVisible()

    press(window, "ctrl+`")
    assert window.terminal_dock.isVisible()


def test_the_terminal_key_works_while_the_web_view_has_focus(window, wait_until):
    show(window, wait_until)
    window.terminal_view.setFocus()
    wait_until(lambda: window.focusWidget() is not None)

    QTest.keySequence(window.focusWidget(), to_key_sequence("ctrl+`"))

    assert not window.terminal_dock.isVisible()


def test_the_keybindings_file_rebinds_a_command(qapp, tmp_path, wait_until):
    (tmp_path / "keybindings.json").write_text('{"view.toggleTerminal": "cmd+j"}')
    window = MainWindow(config_dir=tmp_path)
    show(window, wait_until)

    press(window, "ctrl+`")
    assert window.terminal_dock.isVisible()

    press(window, "cmd+j")
    assert not window.terminal_dock.isVisible()

    window.close()


def test_a_problem_in_the_keybindings_file_shows_in_the_status_bar(qapp, tmp_path):
    (tmp_path / "keybindings.json").write_text('{"view.toggleTerminal": "cmd+nope"}')

    window = MainWindow(config_dir=tmp_path)

    assert "cmd+nope" in window.statusBar().currentMessage()
    window.close()


def test_open_keyboard_shortcuts_creates_the_file_and_opens_it(
    window, tmp_path, monkeypatch
):
    opened = []
    monkeypatch.setattr(pyde.main_window, "open_externally", opened.append)

    window.commands["preferences.openKeybindings"].action.trigger()

    assert opened == [tmp_path / "keybindings.json"]
    assert opened[0].exists()


def test_open_default_keyboard_shortcuts_lists_the_window_commands(
    window, tmp_path, monkeypatch
):
    opened = []
    monkeypatch.setattr(pyde.main_window, "open_externally", opened.append)

    window.commands["preferences.openDefaultKeybindings"].action.trigger()

    assert opened == [tmp_path / "default-keybindings.json"]
    assert (
        '"view.toggleTerminal": "ctrl+`", // Toggle Terminal' in opened[0].read_text()
    )
