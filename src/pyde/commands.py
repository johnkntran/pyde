"""The command registry: every action the user can invoke, by name."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class Command:
    id: str
    action: QAction
    # Written the way keybindings.json writes keys, e.g. "cmd+p". Empty for none.
    default_key: str


class CommandRegistry:
    """The commands of one window, in the order they were registered."""

    def __init__(self, window: QWidget) -> None:
        self._window = window
        self._commands: dict[str, Command] = {}

    def register(
        self, command_id: str, title: str, callback: Callable[[], object], key: str = ""
    ) -> QAction:
        """Add a command and return its action, e.g. to put it in a menu."""
        if command_id in self._commands:
            raise ValueError(f"command {command_id!r} is already registered")
        action = QAction(title, self._window)
        action.triggered.connect(lambda _checked=False: callback())
        # Attached to the window so that the shortcut works even when the
        # command appears in no menu.
        self._window.addAction(action)
        self._commands[command_id] = Command(command_id, action, key)
        return action

    def __getitem__(self, command_id: str) -> Command:
        return self._commands[command_id]

    def __contains__(self, command_id: str) -> bool:
        return command_id in self._commands

    def __iter__(self) -> Iterator[Command]:
        return iter(self._commands.values())
