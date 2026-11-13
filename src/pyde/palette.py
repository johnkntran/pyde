"""A popup for picking one item from a long list by typing a few characters."""

from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pyde.fuzzy import rank

# How many matches are listed, and how many of those show without scrolling.
MAX_MATCHES = 50
VISIBLE_ROWS = 12
WIDTH = 600
# Space kept clear between the palette and the edges of the window.
MARGIN = 8


class Palette(QFrame):
    """A search field over a list of matches, floating at the top of a window.

    It knows nothing about what the items are: it is given strings and calls
    back with the one the user chose.
    """

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._candidates: Sequence[str] = ()
        self._on_choose: Callable[[str], None] = lambda item: None
        # Where keyboard focus returns to if the palette is dismissed.
        self._focus_before: QWidget | None = None

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        self.field = QLineEdit()
        self.matches = QListWidget()
        # Focus stays in the field, so that typing always edits the query.
        self.matches.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        layout.addWidget(self.field)
        layout.addWidget(self.matches)

        self.field.textChanged.connect(self._show_matches)
        self.field.installEventFilter(self)
        self.matches.itemClicked.connect(self._choose)
        self.hide()

    def open(
        self,
        candidates: Sequence[str],
        on_choose: Callable[[str], None],
        placeholder: str = "",
    ) -> None:
        """Offer the candidates, and call `on_choose` with the one picked."""
        self._candidates = candidates
        self._on_choose = on_choose
        self._focus_before = QApplication.focusWidget()
        self.field.setPlaceholderText(placeholder)
        self.field.clear()
        self._show_matches("")
        self.show()
        self.raise_()
        self.field.setFocus()

    def dismiss(self) -> None:
        """Close without choosing, handing focus back to where it was."""
        self.hide()
        if self._focus_before is not None:
            self._focus_before.setFocus()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Handle the keys that drive the list while focus is in the field."""
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._move_selection(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._choose(self.matches.currentItem())
                return True
            if key == Qt.Key.Key_Escape:
                self.dismiss()
                return True
        elif event.type() == QEvent.Type.FocusOut:
            # Clicking elsewhere, or switching apps, closes the palette.
            self.hide()
        return super().eventFilter(watched, event)

    def _show_matches(self, query: str) -> None:
        self.matches.clear()
        self.matches.addItems(rank(query, self._candidates, MAX_MATCHES))
        if self.matches.count() == 0:
            placeholder = QListWidgetItem("No matches", self.matches)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        self.matches.setCurrentRow(0)
        self._fit_to_matches()

    def _fit_to_matches(self) -> None:
        """Size the palette to its matches and center it along the top."""
        rows = min(self.matches.count(), VISIBLE_ROWS)
        row_height = self.matches.sizeHintForRow(0)
        self.matches.setFixedHeight(rows * row_height + 2 * self.matches.frameWidth())
        window = self.parentWidget()
        width = min(WIDTH, window.width() - 2 * MARGIN)
        self.setFixedWidth(width)
        self.adjustSize()
        self.move((window.width() - width) // 2, MARGIN)

    def _move_selection(self, step: int) -> None:
        row = self.matches.currentRow() + step
        self.matches.setCurrentRow(max(0, min(row, self.matches.count() - 1)))

    def _choose(self, item: QListWidgetItem | None) -> None:
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        self.hide()
        self._on_choose(item.text())
