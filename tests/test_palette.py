import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from pyde.palette import MAX_MATCHES, Palette

ITEMS = ["src/editor.py", "src/main_window.py", "tests/test_editor.py"]


class Harness:
    """A window with a palette in it, recording what gets chosen."""

    def __init__(self):
        self.window = QWidget()
        self.window.resize(800, 600)
        # Two places keyboard focus can be before the palette opens. Left to
        # itself, Qt would hand focus to the first one when the palette closes.
        self.first = QLineEdit()
        self.elsewhere = QLineEdit()
        layout = QVBoxLayout(self.window)
        layout.addWidget(self.first)
        layout.addWidget(self.elsewhere)
        self.palette = Palette(self.window)
        self.chosen = []

    def open(self, items=ITEMS):
        self.palette.open(items, self.chosen.append, placeholder="Pick one")

    def type(self, text):
        QTest.keyClicks(self.palette.field, text)

    def press(self, key):
        QTest.keyClick(self.palette.field, key)

    def listed(self):
        matches = self.palette.matches
        return [matches.item(row).text() for row in range(matches.count())]

    def selected(self):
        return self.palette.matches.currentItem().text()


@pytest.fixture
def harness(qapp, wait_until):
    harness = Harness()
    harness.window.show()
    harness.window.activateWindow()
    wait_until(harness.window.isActiveWindow)
    yield harness
    harness.window.close()


def test_the_palette_is_hidden_until_opened(harness):
    assert harness.palette.isHidden()

    harness.open()

    assert harness.palette.isVisible()
    assert harness.palette.field.placeholderText() == "Pick one"
    assert harness.listed() == ITEMS
    assert harness.selected() == "src/editor.py"


def test_typing_narrows_and_ranks_the_matches(harness):
    harness.open()

    harness.type("edit")

    assert harness.listed() == ["src/editor.py", "tests/test_editor.py"]
    assert harness.selected() == "src/editor.py"


def test_return_chooses_the_selected_match_and_closes(harness):
    harness.open()
    harness.type("main")

    harness.press(Qt.Key.Key_Return)

    assert harness.chosen == ["src/main_window.py"]
    assert harness.palette.isHidden()


def test_the_arrow_keys_move_the_selection_and_stop_at_the_ends(harness):
    harness.open()

    harness.press(Qt.Key.Key_Up)
    assert harness.selected() == "src/editor.py"

    for _ in range(5):
        harness.press(Qt.Key.Key_Down)
    assert harness.selected() == "tests/test_editor.py"

    harness.press(Qt.Key.Key_Up)
    harness.press(Qt.Key.Key_Return)
    assert harness.chosen == ["src/main_window.py"]


def test_clicking_a_match_chooses_it(harness):
    harness.open()
    matches = harness.palette.matches
    target = matches.visualItemRect(matches.item(2)).center()

    QTest.mouseClick(matches.viewport(), Qt.MouseButton.LeftButton, pos=target)

    assert harness.chosen == ["tests/test_editor.py"]
    assert harness.palette.isHidden()


def test_escape_closes_without_choosing_and_returns_focus(harness, wait_until):
    harness.elsewhere.setFocus()
    harness.open()
    wait_until(harness.palette.field.hasFocus)

    harness.press(Qt.Key.Key_Escape)

    assert harness.chosen == []
    assert harness.palette.isHidden()
    assert harness.elsewhere.hasFocus()


def test_focus_leaving_the_field_closes_the_palette(harness, wait_until):
    harness.open()
    wait_until(harness.palette.field.hasFocus)

    harness.elsewhere.setFocus()

    assert harness.palette.isHidden()
    assert harness.chosen == []


def test_a_query_with_no_match_says_so_and_cannot_be_chosen(harness):
    harness.open()

    harness.type("zzz")
    harness.press(Qt.Key.Key_Return)

    assert harness.listed() == ["No matches"]
    assert harness.chosen == []
    assert harness.palette.isVisible()


def test_reopening_starts_from_an_empty_query(harness):
    harness.open()
    harness.type("edit")
    harness.press(Qt.Key.Key_Escape)

    harness.open(["other.txt"])

    assert harness.palette.field.text() == ""
    assert harness.listed() == ["other.txt"]


def test_a_long_list_is_cut_off_and_scrolls(harness):
    harness.open([f"file{number:03}.txt" for number in range(200)])

    assert len(harness.listed()) == MAX_MATCHES
    assert harness.palette.height() < harness.window.height()


def test_the_palette_is_centered_and_fits_a_narrow_window(harness):
    harness.window.resize(400, 600)

    harness.open()

    palette = harness.palette
    assert palette.width() < 400
    left_gap = palette.x()
    right_gap = harness.window.width() - palette.x() - palette.width()
    assert abs(left_gap - right_gap) <= 1
