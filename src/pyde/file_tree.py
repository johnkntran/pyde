"""The tree of files in the open folder."""

from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, QSortFilterProxyModel, Signal
from PySide6.QtWidgets import QFileSystemModel, QTreeView, QWidget

# Clutter that is never worth showing. Other dotfiles stay visible, because
# files such as .gitignore and .devcontainer are ones people edit.
HIDDEN_NAMES = {".git", ".DS_Store"}


class _FoldersFirst(QSortFilterProxyModel):
    """Sorts folders ahead of files, and leaves out the hidden names."""

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        return self.sourceModel().index(row, 0, parent).data() not in HIDDEN_NAMES

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        files = self.sourceModel()
        if files.isDir(left) != files.isDir(right):
            return files.isDir(left)
        return files.fileName(left).lower() < files.fileName(right).lower()


class FileTree(QTreeView):
    # The user opened a file, by double-clicking it or pressing Return on it.
    file_activated = Signal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._files = QFileSystemModel(self)
        self._files.setFilter(
            QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden
        )
        self._sorted = _FoldersFirst(self)
        self._sorted.setSourceModel(self._files)
        self._sorted.sort(0)

        self.setHeaderHidden(True)
        self.activated.connect(self._on_activated)

    def set_folder(self, folder: Path) -> None:
        """Show the contents of a folder."""
        # The model is attached only now, so that the tree is empty, not a view
        # of the whole disk, until a folder is opened.
        if self.model() is None:
            self.setModel(self._sorted)
            # Name is the only column worth the space; hide size, type, and date.
            for column in range(1, self._files.columnCount()):
                self.hideColumn(column)
        root = self._files.setRootPath(str(folder))
        self.setRootIndex(self._sorted.mapFromSource(root))

    def _on_activated(self, index: QModelIndex) -> None:
        source = self._sorted.mapToSource(index)
        if not self._files.isDir(source):
            self.file_activated.emit(Path(self._files.filePath(source)))
