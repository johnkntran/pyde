"""A text file that is read again whenever it changes on disk."""

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

# Editors save in bursts, and some replace the file instead of writing to it,
# so a change is acted on only after this long a quiet moment.
SETTLE_MS = 100


class WatchedFile(QObject):
    """A file, such as a settings file, that may not exist yet.

    `read` gives its text. `changed` says that reading it again would give
    something different, whether it was edited, created, replaced, or deleted.
    """

    changed = Signal()

    def __init__(self, path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path = path
        # The text as of the last read; None if the file was missing.
        self._text: str | None = None

        self._settle = QTimer(self, singleShot=True, interval=SETTLE_MS)
        self._settle.timeout.connect(self._check)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(lambda _path: self._settle.start())
        self._watcher.directoryChanged.connect(lambda _path: self._settle.start())

    def read(self) -> str | None:
        """The file's text, or None if it does not exist. Watches it from now on."""
        self._watch()
        self._text = self._read_now()
        return self._text

    def _watch(self) -> None:
        # The folder is watched as well as the file, because an editor that
        # saves by replacing the file leaves the old watch pointing at nothing.
        watched = self._watcher.files() + self._watcher.directories()
        for target in (self.path, self.path.parent):
            if target.exists() and str(target) not in watched:
                self._watcher.addPath(str(target))

    def _read_now(self) -> str | None:
        try:
            return self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def _check(self) -> None:
        self._watch()
        # The folder also changes when other files in it do.
        if self._read_now() != self._text:
            self.changed.emit()
