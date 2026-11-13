"""User-configurable keyboard shortcuts.

Every command has a default key. The user's keybindings file overrides them:

    {
      "view.toggleTerminal": "cmd+j",     // a different key
      "preferences.openKeybindings": ""   // no shortcut at all
    }

The file is watched, so changes apply as soon as it is saved.
"""

import json
import sys
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence

from pyde import jsonc
from pyde.commands import CommandRegistry


def modifiers_for(platform: str) -> dict[str, str]:
    """What Qt calls each modifier the keybindings file can name.

    The file names modifiers the way a Mac keyboard does. On macOS Qt names
    them differently: its "Ctrl" is the Command key and its "Meta" is Control.
    Other keyboards have no Command key, and what a Mac does with it they do
    with Control, so there both names mean Control.
    """
    control = "Meta" if platform == "darwin" else "Ctrl"
    return {
        "cmd": "Ctrl",
        "ctrl": control,
        "alt": "Alt",
        "option": "Alt",
        "shift": "Shift",
    }


_MODIFIERS = modifiers_for(sys.platform)
# Names that Qt spells differently, or reads as a different key: its "Enter" is
# the one on the numeric keypad.
_KEY_ALIASES = {"enter": "Return", "pageup": "PgUp", "pagedown": "PgDown"}

_USER_FILE_TEMPLATE = """\
// Pyde keyboard shortcuts.
//
// Map a command to a key to change its shortcut, or to "" to remove it.
// Changes apply as soon as you save this file.
//
// Keys look like "cmd+p", "ctrl+`", or "cmd+shift+f". A two-step shortcut is
// two keys separated by a space, like "cmd+k cmd+s".
//
// To see every command and its default key, choose
// "Open Default Keyboard Shortcuts" from the application menu.
{
  // "view.toggleTerminal": "ctrl+`"
}
"""

_DEFAULTS_FILE_HEADER = """\
// Every Pyde command and its default key, for reference.
//
// This file is rewritten each time it is opened. To change a shortcut, copy
// its line into keybindings.json and edit it there.
"""


def to_key_sequence(key: str) -> QKeySequence:
    """Translate a key such as "cmd+k cmd+s" into a Qt key sequence.

    Raises ValueError if the key is not valid.
    """
    steps = key.split()
    try:
        portable = ", ".join(_step_to_qt(step) for step in steps)
    except KeyError as error:
        raise ValueError(f"{key!r} uses an unknown modifier, {error}") from None
    sequence = QKeySequence.fromString(
        portable, QKeySequence.SequenceFormat.PortableText
    )

    recognized = 0 < len(steps) == sequence.count() and all(
        sequence[i].key() != Qt.Key.Key_unknown for i in range(sequence.count())
    )
    if not recognized:
        raise ValueError(f"{key!r} is not a valid key")
    return sequence


def _step_to_qt(step: str) -> str:
    """Translate one step, such as "cmd+shift+p", into Qt's spelling."""
    head, _, name = step.lower().rpartition("+")
    if not name and (not head or head.endswith("+")):
        # The key is "+" itself, as in "cmd++".
        head, name = head.rstrip("+"), "+"
    modifiers = head.split("+") if head else []
    return "+".join([*(_MODIFIERS[m] for m in modifiers), _KEY_ALIASES.get(name, name)])


def _sequence(key: object) -> QKeySequence:
    """The key sequence for a value from the file; "" and null mean no shortcut."""
    if key is None or key == "":
        return QKeySequence()
    if not isinstance(key, str):
        raise ValueError(f"{key!r} is not a valid key")
    return to_key_sequence(key)


class Keybindings(QObject):
    """Keeps the commands' shortcuts in step with the user's keybindings file."""

    # A one-line status for the user: a reload confirmation, or what is wrong
    # with the file.
    message = Signal(str)

    def __init__(
        self, registry: CommandRegistry, path: Path, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.path = path
        self._registry = registry
        # The file's text as of the last time it was applied; None if missing.
        self._text: str | None = None

        # Editors save in bursts, and some replace the file instead of writing
        # to it, so wait for a quiet moment before reading it.
        self._change_timer = QTimer(self, singleShot=True, interval=100)
        self._change_timer.timeout.connect(self._on_change)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(lambda _path: self._change_timer.start())
        self._watcher.directoryChanged.connect(lambda _path: self._change_timer.start())

    def load(self) -> None:
        """Apply the file, or the defaults if it does not exist, and watch it."""
        self._watch()
        self._apply(self._read())

    def ensure_user_file(self) -> Path:
        """Create the keybindings file from a template if it does not exist."""
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(_USER_FILE_TEMPLATE, encoding="utf-8")
            self.load()
        return self.path

    def write_defaults_file(self) -> Path:
        """Write the reference file listing every command and its default key."""
        lines = [
            f"  {json.dumps(command.id)}: {json.dumps(command.default_key)},"
            f" // {command.action.text()}"
            for command in sorted(self._registry, key=lambda command: command.id)
        ]
        path = self.path.with_name("default-keybindings.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _DEFAULTS_FILE_HEADER + "{\n" + "\n".join(lines) + "\n}\n", encoding="utf-8"
        )
        return path

    def _watch(self) -> None:
        # The folder is watched as well as the file, because an editor that
        # saves by replacing the file leaves the old watch pointing at nothing.
        watched = self._watcher.files() + self._watcher.directories()
        for target in (self.path, self.path.parent):
            if target.exists() and str(target) not in watched:
                self._watcher.addPath(str(target))

    def _read(self) -> str | None:
        try:
            return self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def _on_change(self) -> None:
        self._watch()
        text = self._read()
        # The folder also changes when other files in it do.
        if text != self._text and self._apply(text):
            self.message.emit("Keyboard shortcuts reloaded")

    def _apply(self, text: str | None) -> bool:
        """Set every command's shortcut. Returns whether the file was problem-free."""
        self._text = text
        try:
            overrides = jsonc.loads(text) if text is not None else {}
            if not isinstance(overrides, dict):
                raise ValueError("expected an object that maps commands to keys")
        except ValueError as error:
            # Likely a half-finished edit: leave the current shortcuts alone.
            self.message.emit(f"{self.path.name}: {error}")
            return False

        problems = [
            f"unknown command {command_id!r}"
            for command_id in overrides
            if command_id not in self._registry
        ]
        owners: dict[str, str] = {}
        for command in self._registry:
            sequence = _sequence(command.default_key)
            if command.id in overrides:
                try:
                    sequence = _sequence(overrides[command.id])
                except ValueError as error:
                    problems.append(f"{command.id}: {error}")
            command.action.setShortcut(sequence)

            # Qt ignores a shortcut that two commands share, so say so.
            shortcut = sequence.toString(QKeySequence.SequenceFormat.NativeText)
            if shortcut in owners:
                problems.append(
                    f"{shortcut} is bound to both {owners[shortcut]} and {command.id}"
                )
            elif shortcut:
                owners[shortcut] = command.id

        if problems:
            self.message.emit(f"{self.path.name}: " + "; ".join(problems))
        return not problems
