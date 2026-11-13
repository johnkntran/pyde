import os

import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from pyde import jsonc, keybindings
from pyde.commands import CommandRegistry
from pyde.keybindings import Keybindings, modifiers_for, to_key_sequence

PORTABLE = QKeySequence.SequenceFormat.PortableText
NATIVE = QKeySequence.SequenceFormat.NativeText


@pytest.fixture(autouse=True)
def mac_modifiers(monkeypatch):
    """Read keys the way a Mac does, whatever system the tests run on."""
    monkeypatch.setattr(keybindings, "_MODIFIERS", modifiers_for("darwin"))


@pytest.mark.parametrize(
    ("key", "qt_spelling"),
    [
        ("cmd+p", "Ctrl+P"),
        ("CMD+P", "Ctrl+P"),
        ("ctrl+`", "Meta+`"),
        ("cmd+shift+f", "Ctrl+Shift+F"),
        ("alt+up", "Alt+Up"),
        ("option+up", "Alt+Up"),
        ("f5", "F5"),
        ("cmd++", "Ctrl++"),
        ("cmd+enter", "Ctrl+Return"),
        ("cmd+pagedown", "Ctrl+PgDown"),
        ("cmd+k cmd+s", "Ctrl+K, Ctrl+S"),
    ],
)
def test_keys_translate_to_qt_sequences(qapp, key, qt_spelling):
    assert to_key_sequence(key).toString(PORTABLE) == qt_spelling


@pytest.mark.parametrize(
    "key",
    ["", "cmd", "cmd+", "super+p", "cmd+nosuchkey", "cmd+p cmd+", "a b c d e"],
)
def test_invalid_keys_are_rejected(qapp, key):
    with pytest.raises(ValueError):
        to_key_sequence(key)


def test_without_a_command_key_both_names_mean_control(qapp, monkeypatch):
    assert modifiers_for("darwin")["ctrl"] == "Meta"
    assert modifiers_for("win32")["ctrl"] == "Ctrl"
    monkeypatch.setattr(keybindings, "_MODIFIERS", modifiers_for("win32"))

    assert to_key_sequence("cmd+p").toString(PORTABLE) == "Ctrl+P"
    assert to_key_sequence("ctrl+`").toString(PORTABLE) == "Ctrl+`"
    assert to_key_sequence("cmd+k cmd+s").toString(PORTABLE) == "Ctrl+K, Ctrl+S"


class Harness:
    """A registry with two commands, and keybindings that read a temporary file."""

    def __init__(self, folder):
        self.owner = QWidget()
        self.registry = CommandRegistry(self.owner)
        self.registry.register("demo.one", "One", lambda: None, key="cmd+1")
        self.registry.register("demo.two", "Two", lambda: None)
        self.path = folder / "keybindings.json"
        self.bindings = Keybindings(self.registry, self.path, parent=self.owner)
        self.messages = []
        self.bindings.message.connect(self.messages.append)

    def shortcuts(self):
        return {
            command.id: command.action.shortcut().toString(PORTABLE)
            for command in self.registry
        }

    def load(self, text):
        self.path.write_text(text)
        self.bindings.load()


@pytest.fixture
def harness(qapp, tmp_path):
    harness = Harness(tmp_path)
    yield harness
    harness.owner.deleteLater()


def test_without_a_file_commands_get_their_default_keys(harness):
    harness.bindings.load()

    assert harness.shortcuts() == {"demo.one": "Ctrl+1", "demo.two": ""}
    assert harness.messages == []


def test_the_file_overrides_default_keys(harness):
    harness.load('{"demo.one": "cmd+9", "demo.two": "cmd+k cmd+2"}')

    assert harness.shortcuts() == {"demo.one": "Ctrl+9", "demo.two": "Ctrl+K, Ctrl+2"}
    assert harness.messages == []


@pytest.mark.parametrize("value", ['""', "null"])
def test_an_empty_key_removes_the_shortcut(harness, value):
    harness.load(f'{{"demo.one": {value}}}')

    assert harness.shortcuts()["demo.one"] == ""
    assert harness.messages == []


def test_the_file_may_contain_comments_and_trailing_commas(harness):
    harness.load('// mine\n{\n  "demo.one": "cmd+9", // was cmd+1\n}\n')

    assert harness.shortcuts()["demo.one"] == "Ctrl+9"
    assert harness.messages == []


def test_an_unknown_command_is_reported_and_the_rest_still_applies(harness):
    harness.load('{"demo.missing": "cmd+3", "demo.two": "cmd+2"}')

    assert harness.shortcuts() == {"demo.one": "Ctrl+1", "demo.two": "Ctrl+2"}
    assert harness.messages == ["keybindings.json: unknown command 'demo.missing'"]


@pytest.mark.parametrize("value", ['"cmd+nosuchkey"', '"super+1"', "7", '["cmd+9"]'])
def test_an_invalid_key_is_reported_and_the_default_is_kept(harness, value):
    harness.load(f'{{"demo.one": {value}}}')

    assert harness.shortcuts()["demo.one"] == "Ctrl+1"
    assert len(harness.messages) == 1
    assert harness.messages[0].startswith("keybindings.json: demo.one: ")


def test_a_key_shared_by_two_commands_is_reported(harness):
    harness.load('{"demo.two": "cmd+1"}')

    # Shown the way this system writes keys: ⌘1 on a Mac.
    key = QKeySequence("Ctrl+1").toString(NATIVE)
    assert harness.messages == [
        f"keybindings.json: {key} is bound to both demo.one and demo.two"
    ]


@pytest.mark.parametrize("broken", ['{"demo.one": ', '["demo.one"]'])
def test_an_unreadable_file_is_reported_and_current_shortcuts_are_kept(harness, broken):
    harness.load('{"demo.one": "cmd+9"}')

    harness.load(broken)

    assert harness.shortcuts()["demo.one"] == "Ctrl+9"
    assert len(harness.messages) == 1
    assert harness.messages[0].startswith("keybindings.json: ")


def test_saving_the_file_reapplies_it(harness, wait_until):
    harness.load('{"demo.one": "cmd+8"}')

    harness.path.write_text('{"demo.one": "cmd+9"}')

    wait_until(lambda: harness.shortcuts()["demo.one"] == "Ctrl+9")
    assert harness.messages == ["Keyboard shortcuts reloaded"]


def test_saving_by_replacing_the_file_keeps_being_noticed(harness, wait_until):
    harness.load('{"demo.one": "cmd+7"}')

    # Many editors save by writing a new file and renaming it over the old one.
    for key in ("8", "9"):
        replacement = harness.path.with_suffix(".tmp")
        replacement.write_text(f'{{"demo.one": "cmd+{key}"}}')
        os.replace(replacement, harness.path)
        wait_until(lambda key=key: harness.shortcuts()["demo.one"] == f"Ctrl+{key}")


def test_a_file_created_later_is_picked_up(harness, wait_until):
    harness.bindings.load()

    harness.path.write_text('{"demo.one": "cmd+9"}')

    wait_until(lambda: harness.shortcuts()["demo.one"] == "Ctrl+9")


def test_deleting_the_file_restores_the_defaults(harness, wait_until):
    harness.load('{"demo.one": "cmd+9"}')

    harness.path.unlink()

    wait_until(lambda: harness.shortcuts()["demo.one"] == "Ctrl+1")


def test_other_files_changing_in_the_folder_do_not_announce_a_reload(
    harness, wait_until
):
    harness.load('{"demo.one": "cmd+9"}')

    (harness.path.parent / "other.json").write_text("{}")
    # Give that change time to be noticed on its own, then make a real one.
    QTest.qWait(700)
    harness.path.write_text('{"demo.one": "cmd+8"}')

    wait_until(lambda: harness.shortcuts()["demo.one"] == "Ctrl+8")
    assert harness.messages == ["Keyboard shortcuts reloaded"]


def test_ensure_user_file_creates_a_template_that_changes_nothing(qapp, tmp_path):
    harness = Harness(tmp_path / "not-created-yet")

    path = harness.bindings.ensure_user_file()

    assert jsonc.loads(path.read_text()) == {}
    assert harness.shortcuts() == {"demo.one": "Ctrl+1", "demo.two": ""}
    assert harness.messages == []


def test_ensure_user_file_leaves_an_existing_file_alone(harness):
    harness.load('{"demo.one": "cmd+9"}')

    path = harness.bindings.ensure_user_file()

    assert path.read_text() == '{"demo.one": "cmd+9"}'


def test_the_defaults_file_lists_every_command_with_its_default_key(harness):
    harness.load('{"demo.one": "cmd+9"}')

    path = harness.bindings.write_defaults_file()

    assert path.name == "default-keybindings.json"
    assert jsonc.loads(path.read_text()) == {"demo.one": "cmd+1", "demo.two": ""}
    assert '"demo.one": "cmd+1", // One' in path.read_text()
