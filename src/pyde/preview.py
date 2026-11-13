"""Read-only previews, for files that are easier to read rendered than raw.

Markdown is shown formatted, and comma- or tab-separated values as a table.
A preview shows the editor's text as it stood when the preview was opened;
to change the file, the user goes back to the editor.
"""

import csv
import io
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, QUrl
from PySide6.QtWidgets import QStackedWidget, QTableView, QTextBrowser, QWidget

from pyde.editor import CodeEditor

MARKDOWN_SUFFIXES = {".md", ".markdown"}
# The character that separates values, by file suffix.
DELIMITERS = {".csv": ",", ".tsv": "\t"}

# Space around the rendered Markdown, in pixels.
MARKDOWN_MARGIN = 16
# Columns are sized to fit their contents, judged from this many rows so that
# a long file opens quickly, and no wider than this many pixels.
ROWS_MEASURED = 100
MAX_COLUMN_WIDTH = 400


def can_preview(path: Path | None) -> bool:
    """Whether a file is of a kind that has a preview."""
    suffix = path.suffix.lower() if path else ""
    return suffix in MARKDOWN_SUFFIXES or suffix in DELIMITERS


class MarkdownPreview(QTextBrowser):
    """Markdown as formatted text: real headings, bold, rules, and tables."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Links to the web open in the browser.
        self.setOpenExternalLinks(True)
        self.document().setDocumentMargin(MARKDOWN_MARGIN)

    def show_text(self, text: str, path: Path) -> None:
        # Relative links and images are relative to the file's folder.
        self.document().setBaseUrl(QUrl.fromLocalFile(f"{path.parent}/"))
        self.setMarkdown(text)


class _Table(QAbstractTableModel):
    """Rows of values, the first of which names the columns."""

    def __init__(self, rows: list[list[str]], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._names = rows[0] if rows else []
        self._rows = rows[1:]
        # Rows may be of different lengths; the table is as wide as the longest.
        self._width = max((len(row) for row in rows), default=0)

    # A table has no rows or columns below any of its cells, which is what a
    # valid parent would be asking about.

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else self._width

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        row = self._rows[index.row()]
        return row[index.column()] if index.column() < len(row) else ""

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return self._names[section] if section < len(self._names) else ""


class TablePreview(QTableView):
    """Comma- or tab-separated values as a table, with the first row as its
    column headings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        header = self.horizontalHeader()
        header.setResizeContentsPrecision(ROWS_MEASURED)
        header.setMaximumSectionSize(MAX_COLUMN_WIDTH)

    def show_text(self, text: str, path: Path) -> None:
        delimiter = DELIMITERS[path.suffix.lower()]
        # newline="" lets a quoted value contain line breaks.
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
        previous = self.model()
        self.setModel(_Table(rows, self))
        if previous is not None:
            previous.deleteLater()
        self.resizeColumnsToContents()


class FileView(QStackedWidget):
    """One open file: its editor and, for some kinds of file, a read-only
    preview that can be shown in the editor's place."""

    def __init__(self, editor: CodeEditor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.addWidget(editor)
        self._preview: MarkdownPreview | TablePreview | None = None

    @property
    def can_preview(self) -> bool:
        return can_preview(self.editor.path)

    @property
    def previewing(self) -> bool:
        return self.currentWidget() is not self.editor

    def set_previewing(self, previewing: bool) -> None:
        """Show the preview, made from the editor's current text, or the editor.

        A file of a kind that has no preview always shows its editor.
        """
        if not (previewing and self.can_preview):
            self.setCurrentWidget(self.editor)
            return
        path = self.editor.path
        kind = (
            MarkdownPreview
            if path.suffix.lower() in MARKDOWN_SUFFIXES
            else TablePreview
        )
        if not isinstance(self._preview, kind):
            # The first preview, or the file was saved as a different kind.
            if self._preview is not None:
                self.removeWidget(self._preview)
                self._preview.deleteLater()
            self._preview = kind()
            self.addWidget(self._preview)
        self._preview.show_text(self.editor.toPlainText(), path)
        self.setCurrentWidget(self._preview)
