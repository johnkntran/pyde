"""The find-and-replace bar, which works on whichever editor is current."""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from pyde.editor import CodeEditor

# Qt puts this character, not "\n", between the lines of a multi-line selection.
_PARAGRAPH_SEPARATOR = " "


class FindBar(QWidget):
    def __init__(
        self,
        current_editor: Callable[[], CodeEditor | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._current_editor = current_editor

        self.find_field = QLineEdit(placeholderText="Find")
        self.replace_field = QLineEdit(placeholderText="Replace")
        self.match_case = QCheckBox("Match Case")
        self.status = QLabel()
        buttons = [
            ("Previous", self.find_previous, 0, 1),
            ("Next", self.find_next, 0, 2),
            ("Done", self.dismiss, 0, 4),
            ("Replace", self.replace, 1, 1),
            ("Replace All", self.replace_all, 1, 2),
        ]

        layout = QGridLayout(self)
        layout.addWidget(self.find_field, 0, 0)
        layout.addWidget(self.replace_field, 1, 0)
        layout.addWidget(self.match_case, 0, 3)
        layout.addWidget(self.status, 1, 3)
        for label, action, row, column in buttons:
            button = QPushButton(label)
            button.clicked.connect(action)
            layout.addWidget(button, row, column)
        layout.setColumnStretch(0, 1)

        self.find_field.returnPressed.connect(self.find_next)
        self.replace_field.returnPressed.connect(self.replace)
        self.find_field.textChanged.connect(self.status.clear)
        self.hide()

    def show_find(self) -> None:
        """Show the bar, ready to type a search, starting from the selection."""
        editor = self._current_editor()
        if editor is None:
            return
        selected = editor.textCursor().selectedText()
        if selected and _PARAGRAPH_SEPARATOR not in selected:
            self.find_field.setText(selected)
        self.show()
        self.find_field.setFocus()
        self.find_field.selectAll()

    def show_replace(self) -> None:
        self.show_find()
        if self.isVisible():
            self.replace_field.setFocus()

    def dismiss(self) -> None:
        self.hide()
        editor = self._current_editor()
        if editor is not None:
            editor.setFocus()

    def find_next(self) -> bool:
        return self._find(backward=False)

    def find_previous(self) -> bool:
        return self._find(backward=True)

    def replace(self) -> None:
        """Replace the selected match, then move to the next one."""
        editor = self._current_editor()
        if editor is None:
            return
        cursor = editor.textCursor()
        if self._is_match(cursor.selectedText()):
            cursor.insertText(self.replace_field.text())
        self.find_next()

    def replace_all(self) -> None:
        """Replace every match in the file, as a single undo step."""
        editor = self._current_editor()
        query = self.find_field.text()
        if editor is None or not query:
            return
        document = editor.document()
        flags = self._flags(backward=False)
        count = 0
        edit = QTextCursor(document)
        edit.beginEditBlock()
        match = document.find(query, 0, flags)
        while not match.isNull():
            match.insertText(self.replace_field.text())
            count += 1
            # Searching on from the cursor skips over the text just inserted.
            match = document.find(query, match, flags)
        edit.endEditBlock()
        self.status.setText(f"Replaced {count}" if count else "No results")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(event)

    def _flags(self, backward: bool) -> QTextDocument.FindFlag:
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if self.match_case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def _is_match(self, text: str) -> bool:
        query = self.find_field.text()
        if self.match_case.isChecked():
            return bool(query) and text == query
        return bool(query) and text.lower() == query.lower()

    def _find(self, backward: bool) -> bool:
        editor = self._current_editor()
        query = self.find_field.text()
        if editor is None or not query:
            return False
        flags = self._flags(backward)
        found = editor.find(query, flags)
        if not found:
            # Wrap around: search again from the other end of the file.
            original = editor.textCursor()
            wrapped = QTextCursor(original)
            wrapped.movePosition(
                QTextCursor.MoveOperation.End
                if backward
                else QTextCursor.MoveOperation.Start
            )
            editor.setTextCursor(wrapped)
            found = editor.find(query, flags)
            if not found:
                editor.setTextCursor(original)
        self.status.setText("" if found else "No results")
        return found
