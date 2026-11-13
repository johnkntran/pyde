"""The user's settings file.

    {
      "theme": { "light": "xcode", "dark": "monokai" }
    }

So far it sets one thing: which Pygments style colors the code, in light mode
and in dark. The file is watched, so changes apply as soon as it is saved.
"""

import textwrap
from pathlib import Path

from pygments.styles import get_all_styles
from PySide6.QtCore import QObject, Signal

from pyde import highlighter, jsonc
from pyde.watched_file import WatchedFile

_TEMPLATE = """\
// Pyde settings. Changes apply as soon as you save this file.
{{
  // The colors of the code, in light mode and in dark mode. Each is the name
  // of a Pygments style; https://pygments.org/styles/ shows what they look
  // like. Only the code's colors change: the background stays the system's.
  //
  // The styles to choose from:
{styles}
  //
  // "theme": {{ "light": "{light}", "dark": "{dark}" }}
}}
"""


class Settings(QObject):
    """Keeps Pyde in step with the user's settings file."""

    # A one-line status for the user: a reload confirmation, or what is wrong
    # with the file.
    message = Signal(str)

    def __init__(self, path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self._file = WatchedFile(path, self)
        self._file.changed.connect(self._reload)

    def load(self) -> None:
        """Apply the file, or the defaults if it does not exist, and watch it."""
        self._apply(self._file.read())

    def ensure_user_file(self) -> Path:
        """Create the settings file from a template if it does not exist."""
        if not self.path.exists():
            names = ", ".join(sorted(get_all_styles()))
            # Names such as github-dark must not be split at their hyphen.
            lines = textwrap.wrap(names, width=72, break_on_hyphens=False)
            template = _TEMPLATE.format(
                styles="\n".join(f"  //   {line}" for line in lines),
                light=highlighter.LIGHT_STYLE,
                dark=highlighter.DARK_STYLE,
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(template, encoding="utf-8")
            self.load()
        return self.path

    def _reload(self) -> None:
        if self._apply(self._file.read()):
            self.message.emit("Settings reloaded")

    def _apply(self, text: str | None) -> bool:
        """Put the settings into effect. Returns whether the file was problem-free."""
        try:
            settings = jsonc.loads(text) if text is not None else {}
            if not isinstance(settings, dict):
                raise ValueError("expected an object of settings")
        except ValueError as error:
            # Likely a half-finished edit: leave the current settings alone.
            self.message.emit(f"{self.path.name}: {error}")
            return False

        problems = [f"unknown setting {name!r}" for name in settings if name != "theme"]
        theme = settings.get("theme", {})
        if not isinstance(theme, dict):
            problems.append('"theme" must be an object with "light" and "dark"')
            theme = {}

        # A mode left out, or given a style that does not exist, keeps the
        # style Pyde comes with.
        chosen = {"light": highlighter.LIGHT_STYLE, "dark": highlighter.DARK_STYLE}
        available = set(get_all_styles())
        for mode, style in theme.items():
            if mode not in chosen:
                problems.append(f'unknown theme mode {mode!r}; use "light" or "dark"')
            elif style not in available:
                problems.append(f"unknown style {style!r} for {mode} mode")
            else:
                chosen[mode] = style
        highlighter.styles.set(chosen["light"], chosen["dark"])

        if problems:
            self.message.emit(f"{self.path.name}: " + "; ".join(problems))
        return not problems
