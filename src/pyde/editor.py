"""The text editing widget: one per open file."""

import re
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QFontDatabase,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QResizeEvent,
    QTextCursor,
)
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from pyde.highlighter import SyntaxHighlighter, lexer_for, utf16_length

INDENT_WIDTH = 4
FONT_SIZE = 13
# Space between the line numbers and the edges of their gutter.
GUTTER_PADDING = 8

_KEEP_ANCHOR = QTextCursor.MoveMode.KeepAnchor


class _LineNumberArea(QWidget):
    """The gutter down the left side of an editor. The editor paints it."""

    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        self._editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The file this editor holds; None until a new file is first saved.
        self.path: Path | None = None
        # How the file on disk ends its lines and indents, so that saving and
        # typing keep to the file's own style.
        self._newline = "\n"
        self._indent = " " * INDENT_WIDTH
        # Colors the text; None while the file's language is unknown.
        self._highlighter: SyntaxHighlighter | None = None

        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(FONT_SIZE)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(
            INDENT_WIDTH * self.fontMetrics().horizontalAdvance(" ")
        )

        self._line_numbers = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_left_margin)
        self.updateRequest.connect(self._scroll_line_numbers)
        self._update_left_margin()

    @property
    def title(self) -> str:
        return self.path.name if self.path else "Untitled"

    def load(self, path: Path) -> None:
        """Replace the contents with a file's text.

        Raises OSError if the file cannot be read, and UnicodeDecodeError if it
        is not UTF-8 text.
        """
        # newline="" keeps the file's line endings, so they can be detected.
        with open(path, encoding="utf-8", newline="") as file:
            text = file.read()
        self._newline = "\r\n" if "\r\n" in text else "\n"
        uses_tabs = re.search(r"^\t", text, re.MULTILINE)
        self._indent = "\t" if uses_tabs else " " * INDENT_WIDTH
        self.setPlainText(text.replace("\r\n", "\n"))
        self.path = path
        self._highlight_for_path()

    def save(self, path: Path | None = None) -> None:
        """Write the contents to the file, or to a new path. Raises OSError."""
        path = path or self.path
        text = self.toPlainText().replace("\n", self._newline)
        with open(path, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        renamed = path != self.path
        self.path = path
        self.document().setModified(False)
        if renamed:
            self._highlight_for_path()

    def select(self, line: int, column: int, length: int) -> None:
        """Select part of a line, and scroll so that it shows.

        The line is counted from 1, and the column from 0, in characters. If
        the text has changed and no longer reaches that far, the nearest place
        that exists is used.
        """
        block = self.document().findBlockByNumber(line - 1)
        if not block.isValid():
            block = self.document().lastBlock()
        text = block.text()
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + utf16_length(text[:column]))
        end = block.position() + utf16_length(text[: column + length])
        cursor.setPosition(end, _KEEP_ANCHOR)
        self.setTextCursor(cursor)
        self.centerCursor()

    def _highlight_for_path(self) -> None:
        """Color the text as the language that the file's name implies."""
        if self._highlighter is not None:
            self._highlighter.setDocument(None)
            self._highlighter.deleteLater()
            self._highlighter = None
        lexer = lexer_for(self.path.name, self.toPlainText())
        if lexer is not None:
            self._highlighter = SyntaxHighlighter(self.document(), lexer)

    # Line numbers

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(self.blockCount())))
        return 2 * GUTTER_PADDING + digits * self.fontMetrics().horizontalAdvance("9")

    def paint_line_numbers(self, event: QPaintEvent) -> None:
        painter = QPainter(self._line_numbers)
        palette = self.palette()
        painter.fillRect(event.rect(), palette.color(QPalette.ColorRole.Window))
        painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
        painter.setFont(self.font())

        width = self._line_numbers.width() - GUTTER_PADDING
        line_height = self.fontMetrics().height()
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        while block.isValid() and top <= event.rect().bottom():
            bottom = top + self.blockBoundingRect(block).height()
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block.blockNumber() + 1)
                painter.drawText(
                    0,
                    round(top),
                    width,
                    line_height,
                    Qt.AlignmentFlag.AlignRight,
                    number,
                )
            block, top = block.next(), bottom

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        area = self.contentsRect()
        self._line_numbers.setGeometry(
            QRect(area.left(), area.top(), self.line_number_area_width(), area.height())
        )

    def _update_left_margin(self) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _scroll_line_numbers(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_numbers.scroll(0, dy)
        else:
            self._line_numbers.update(
                0, rect.y(), self._line_numbers.width(), rect.height()
            )

    # Indentation

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        plain = event.modifiers() in (
            Qt.KeyboardModifier.NoModifier,
            Qt.KeyboardModifier.KeypadModifier,
        )
        if key == Qt.Key.Key_Tab and plain:
            if self.textCursor().hasSelection():
                self._shift_selected_lines(indent=True)
            else:
                self._indent_to_next_stop()
        elif key == Qt.Key.Key_Backtab:
            self._shift_selected_lines(indent=False)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and plain:
            self._insert_indented_newline()
        else:
            super().keyPressEvent(event)

    def _indent_to_next_stop(self) -> None:
        cursor = self.textCursor()
        if self._indent == "\t":
            cursor.insertText("\t")
        else:
            column = cursor.positionInBlock()
            cursor.insertText(" " * (INDENT_WIDTH - column % INDENT_WIDTH))

    def _insert_indented_newline(self) -> None:
        """Start a new line at the same indentation as the current one."""
        cursor = self.textCursor()
        before_cursor = cursor.block().text()[: cursor.positionInBlock()]
        indentation = re.match(r"[ \t]*", before_cursor).group()
        cursor.insertText("\n" + indentation)
        self.ensureCursorVisible()

    def _shift_selected_lines(self, indent: bool) -> None:
        """Indent or outdent every line the selection touches, as one undo step."""
        cursor = self.textCursor()
        document = self.document()
        first = document.findBlock(cursor.selectionStart())
        last = document.findBlock(cursor.selectionEnd())
        # A selection that ends at the very start of a line does not include it.
        if last != first and cursor.selectionEnd() == last.position():
            last = last.previous()

        cursor.beginEditBlock()
        block = first
        while block.isValid() and block.blockNumber() <= last.blockNumber():
            line = QTextCursor(block)
            if indent:
                if block.text().strip():  # Leave blank lines blank.
                    line.insertText(self._indent)
            else:
                removable = re.match(rf"\t| {{1,{INDENT_WIDTH}}}", block.text())
                if removable:
                    line.setPosition(block.position() + removable.end(), _KEEP_ANCHOR)
                    line.removeSelectedText()
            block = block.next()
        cursor.endEditBlock()
