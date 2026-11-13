import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWidgets import QApplication

from pyde import terminal as terminal_module
from pyde.terminal import TerminalView, default_shell, shell_environment

# Everything on the terminal's screen and in its scrollback, with lines that
# xterm.js wrapped joined back together.
SCREEN = """
(() => {
  const buffer = terminal.buffer.active;
  let text = "";
  for (let row = 0; row < buffer.length; row++) {
    const line = buffer.getLine(row);
    text += (line.isWrapped ? "" : "\\n") + line.translateToString(true);
  }
  return text;
})()
"""


class Harness:
    """A terminal on screen, with helpers to type into it and read it."""

    def __init__(self, folder, wait_until):
        self.wait_until = wait_until
        self.view = TerminalView()
        self.view.set_folder(folder)
        self.view.resize(800, 400)
        started = []
        self.view.started.connect(lambda: started.append(True))
        self.view.show()
        wait_until(lambda: started, timeout=30)

    def evaluate(self, script):
        results = []
        self.view.page().runJavaScript(script, results.append)
        self.wait_until(lambda: results)
        return results[0]

    def type(self, text):
        """Type text the way a user would, through xterm.js."""
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r")
        self.evaluate(f'terminal.input("{escaped}")')

    def screen(self):
        return self.evaluate(SCREEN)

    def wait_for(self, text, timeout=10):
        self.wait_until(lambda: text in self.screen(), timeout=timeout)

    def focus(self):
        """Put keyboard focus in the terminal, and wait for the page to have it."""
        self.view.focus_terminal()
        focused = "document.activeElement.className === 'xterm-helper-textarea'"
        self.wait_until(lambda: self.evaluate(focused))


@pytest.fixture
def harness(qapp, tmp_path, wait_until):
    harness = Harness(tmp_path, wait_until)
    yield harness
    harness.view.shutdown()
    harness.view.close()


def test_typing_a_command_runs_it_and_shows_its_output(harness):
    assert harness.view.running

    harness.type("echo sum-$((40 + 2))\r")

    harness.wait_for("sum-42")


def test_the_shell_starts_in_the_terminals_folder(harness, tmp_path):
    harness.type("pwd\r")

    harness.wait_for(f"\n{tmp_path}\n")


def test_changing_folder_restarts_the_shell_there_on_a_clean_screen(harness, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    harness.type("echo before-$((1 + 1))\r")
    harness.wait_for("before-2")

    harness.view.set_folder(other)
    harness.type("pwd\r")

    harness.wait_for(f"\n{other}\n")
    assert "before-2" not in harness.screen()


def test_the_shell_knows_the_terminals_size_and_follows_it(harness, wait_until):
    size = harness.evaluate("`${terminal.rows} ${terminal.cols}`")
    harness.type("stty size\r")
    harness.wait_for(f"\n{size}\n")

    harness.view.resize(500, 250)
    wait_until(lambda: harness.evaluate("`${terminal.rows} ${terminal.cols}`") != size)
    smaller = harness.evaluate("`${terminal.rows} ${terminal.cols}`")
    harness.type("stty size\r")

    harness.wait_for(f"\n{smaller}\n")


def test_after_the_shell_exits_return_starts_a_new_one(harness, wait_until):
    harness.type("exit\r")
    harness.wait_for("The shell has exited")
    assert not harness.view.running

    harness.type("x")
    assert not harness.view.running
    harness.type("\r")
    wait_until(lambda: harness.view.running)
    harness.type("echo again-$((1 + 1))\r")

    harness.wait_for("again-2")


def test_pasting_types_the_clipboard_into_the_shell(harness):
    QApplication.clipboard().setText("echo pasted-$((2 + 2))\n")
    harness.focus()

    harness.view.triggerPageAction(QWebEnginePage.WebAction.Paste)

    harness.wait_for("pasted-4")


def test_copying_takes_the_selected_terminal_text(harness, wait_until):
    harness.type("echo copy-$((3 + 3))-me\r")
    harness.wait_for("copy-6-me")
    QApplication.clipboard().setText("")
    harness.focus()

    harness.evaluate("terminal.selectAll()")
    harness.view.triggerPageAction(QWebEnginePage.WebAction.Copy)

    wait_until(lambda: "copy-6-me" in QApplication.clipboard().text())


def test_a_flood_of_output_is_shown_through_to_its_end(harness):
    harness.type("seq 1 30000\r")

    harness.wait_for("\n29999\n30000\n", timeout=60)


def test_the_shell_is_paused_while_the_page_is_behind(harness, monkeypatch):
    monkeypatch.setattr(terminal_module, "HIGH_WATER_MARK", 100)
    monkeypatch.setattr(terminal_module, "LOW_WATER_MARK", 50)
    pauses = []
    monkeypatch.setattr(harness.view._session, "set_paused", pauses.append)
    harness.view._unacknowledged = 0

    harness.view._send("x" * 80)
    harness.view._send_outbox()
    assert pauses == []

    harness.view._send("x" * 80)
    harness.view._send_outbox()
    assert pauses == [True]

    harness.view.acknowledged(80)
    harness.view.acknowledged(80)
    assert pauses[-1] is False


def test_the_colors_follow_the_system_color_scheme(harness, wait_until):
    def background():
        return harness.evaluate("terminal.options.theme.background")

    assert background() == "#ffffff"

    scheme_changed = QGuiApplication.styleHints().colorSchemeChanged
    scheme_changed.emit(Qt.ColorScheme.Dark)
    wait_until(lambda: background() == "#1e1e1e")

    scheme_changed.emit(Qt.ColorScheme.Light)
    wait_until(lambda: background() == "#ffffff")


def test_the_shell_environment_describes_the_terminal(monkeypatch):
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    monkeypatch.setenv("KEPT", "yes")

    env = shell_environment()

    assert env["TERM"] == "xterm-256color"
    assert env["COLORTERM"] == "truecolor"
    assert env["TERM_PROGRAM"] == "Pyde"
    assert env["KEPT"] == "yes"
    assert env["LANG"] == "fr_FR.UTF-8"


@pytest.mark.parametrize(
    ("system_locale", "expected"),
    [("fr_CA", "fr_CA.UTF-8"), ("C", "en_US.UTF-8")],
)
def test_a_utf8_locale_is_supplied_when_none_is_set(
    qapp, monkeypatch, system_locale, expected
):
    for name in ("LC_ALL", "LC_CTYPE", "LANG"):
        monkeypatch.delenv(name, raising=False)

    class FakeLocale:
        @staticmethod
        def system():
            return FakeLocale()

        def name(self):
            return system_locale

    monkeypatch.setattr(terminal_module, "QLocale", FakeLocale)

    assert shell_environment()["LANG"] == expected


def test_the_default_shell_is_the_users_own(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/example")
    assert default_shell() == "/bin/example"

    monkeypatch.delenv("SHELL")
    assert os.path.isabs(default_shell())
