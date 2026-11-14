"""The Find in Files panel: a search of the open folder, and what it found."""

import re
from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QObject, QRect, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pyde.search import Match, Searcher, compile_query

# Where a result's row keeps its Match. A file's row has none.
MATCH_ROLE = Qt.ItemDataRole.UserRole
# Space around the field and the results. The panel is short, so not much.
MARGIN = 6


class SearchPanel(QWidget):
    """A field to search the open folder's files, over a list of the results.

    The results are grouped by file, one row for each line that matches.
    """

    # The user chose a result: the file, its line counted from 1, and the
    # column and length of the text found in that line.
    match_activated = Signal(Path, int, int, int)
    # The user pressed Escape, to go back to what they were doing.
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The folder searched; None until one is opened.
        self._folder: Path | None = None
        # About the search whose results are showing: how long the text
        # searched for is, and how many lines it has found so far.
        self._query_length = 0
        self._count = 0
        self._searcher = Searcher(self)
        self._searcher.found.connect(self._add_file)
        self._searcher.finished.connect(self._finished)

        self.field = QLineEdit(placeholderText="Find in files")
        self.match_case = QCheckBox("Match Case")
        self.status = QLabel()
        self.results = QTreeWidget()
        self.results.setHeaderHidden(True)
        self.results.setUniformRowHeights(True)
        self._delegate = _MatchDelegate(self.results)
        self.results.setItemDelegate(self._delegate)
        # Lines of code read best in the font the editor shows them in.
        self._code_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._code_font.setPointSizeF(self.results.font().pointSizeF())

        top = QHBoxLayout()
        top.addWidget(self.field, stretch=1)
        top.addWidget(self.match_case)
        top.addSpacing(2 * MARGIN)
        top.addWidget(self.status)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN, MARGIN, 0)
        layout.setSpacing(MARGIN)
        layout.addLayout(top)
        layout.addWidget(self.results)

        self.field.returnPressed.connect(self.search)
        self.match_case.toggled.connect(self.search)
        self.results.itemDoubleClicked.connect(self._open)
        self.field.installEventFilter(self)
        self.results.installEventFilter(self)

    @property
    def searching(self) -> bool:
        return self._searcher.running

    def set_folder(self, folder: Path) -> None:
        """Search this folder from now on. Results from another are dropped."""
        self._folder = folder
        self._clear()

    def start_typing(self, text: str = "") -> None:
        """Put keyboard focus in the field, with `text` in it if there is any."""
        if text:
            self.field.setText(text)
        self.field.setFocus()
        self.field.selectAll()

    def search(self) -> None:
        """Search the folder for the text in the field, replacing the results."""
        self._clear()
        query = self.field.text()
        if not query or self._folder is None:
            return
        pattern = compile_query(query, self.match_case.isChecked())
        self._delegate.pattern = pattern
        self._query_length = len(query)
        self.status.setText("Searching…")
        self._searcher.start(self._folder, pattern)

    def shutdown(self) -> None:
        """Stop any search. Call before the window goes away."""
        self._searcher.cancel()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Handle the keys that move between the field, the results, and a file."""
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.dismissed.emit()
                return True
            if watched is self.field and key == Qt.Key.Key_Down:
                self._focus_results()
                return True
            # Qt leaves Return in a list to the platform, and on macOS it does
            # nothing there.
            if watched is self.results and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                item = self.results.currentItem()
                if item is not None and not self._open(item):
                    item.setExpanded(not item.isExpanded())
                return True
        return super().eventFilter(watched, event)

    def _clear(self) -> None:
        self._searcher.cancel()
        self.results.clear()
        self.status.clear()
        self._count = 0

    def _add_file(self, relative_path: str, matches: list[Match]) -> None:
        file_row = QTreeWidgetItem(self.results, [relative_path])
        # Line numbers are padded to the longest, so the lines start level.
        width = len(str(matches[-1].line))
        for match in matches:
            row = QTreeWidgetItem(file_row, [f"{match.line:>{width}}: {match.text}"])
            row.setData(0, MATCH_ROLE, match)
            row.setFont(0, self._code_font)
        file_row.setExpanded(True)
        self._count += len(matches)

    def _finished(self, stopped_early: bool) -> None:
        files = self.results.topLevelItemCount()
        if self._count == 0:
            text = "No results"
        elif stopped_early:
            text = f"Showing the first {self._count:,} results"
        else:
            text = (
                f"{self._count:,} {'result' if self._count == 1 else 'results'}"
                f" in {files:,} {'file' if files == 1 else 'files'}"
            )
        self.status.setText(text)

    def _focus_results(self) -> None:
        """Move keyboard focus to the results, onto the first unless one is current."""
        if self.results.topLevelItemCount() == 0:
            return
        if self.results.currentItem() is None:
            self.results.setCurrentItem(self.results.topLevelItem(0).child(0))
        self.results.setFocus()

    def _open(self, item: QTreeWidgetItem) -> bool:
        """Announce that a result was chosen. False for a file's row, which is none."""
        match = item.data(0, MATCH_ROLE)
        if match is None:
            return False
        path = self._folder / item.parent().text(0)
        self.match_activated.emit(path, match.line, match.column, self._query_length)
        return True


def split_at_occurrences(text: str, pattern: re.Pattern[str]) -> list[tuple[str, bool]]:
    """The text in pieces, each with whether it is an occurrence of the pattern."""
    pieces = []
    end = 0
    for found in pattern.finditer(text):
        pieces.append((text[end : found.start()], False))
        pieces.append((found.group(), True))
        end = found.end()
    pieces.append((text[end:], False))
    return [(piece, found) for piece, found in pieces if piece]


class _MatchDelegate(QStyledItemDelegate):
    """Draws a result's row with the text that was searched for in bold."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        # What the results being shown were a search for.
        self.pattern: re.Pattern[str] | None = None

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        match = index.data(MATCH_ROLE)
        if match is None or self.pattern is None:
            super().paint(painter, option, index)
            return
        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        widget = option.widget
        style = widget.style()
        area = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, option, widget
        )
        # The style draws the row and its selection, and this the text.
        text, option.text = option.text, ""
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, option, painter, widget
        )

        # The colors a list's own text would have.
        group = QPalette.ColorGroup.Disabled
        if option.state & QStyle.StateFlag.State_Enabled:
            active = option.state & QStyle.StateFlag.State_Active
            group = (
                QPalette.ColorGroup.Active if active else QPalette.ColorGroup.Inactive
            )
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        role = (
            QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        )
        color = option.palette.color(group, role)
        dim = option.palette.color(group, QPalette.ColorRole.PlaceholderText)
        bold = QFont(option.font)
        bold.setBold(True)

        # The line number, dimmed, then the line with each occurrence in bold.
        number = text[: len(text) - len(match.text)]
        pieces = [(number, option.font, color if selected else dim)]
        for piece, found in split_at_occurrences(match.text, self.pattern):
            pieces.append((piece, bold if found else option.font, color))

        margin = style.pixelMetric(
            QStyle.PixelMetric.PM_FocusFrameHMargin, None, widget
        )
        left = area.left() + margin + 1
        flags = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine
        painter.save()
        painter.setClipRect(area)
        for piece, font, pen in pieces:
            painter.setFont(font)
            painter.setPen(pen)
            painter.drawText(
                QRect(left, area.top(), area.right() - left, area.height()),
                flags,
                piece,
            )
            left += QFontMetrics(font).horizontalAdvance(piece)
        painter.restore()
