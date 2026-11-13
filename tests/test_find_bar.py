import pytest

from pyde.editor import CodeEditor
from pyde.find_bar import FindBar


class Harness:
    """An editor with some text, and a find bar that works on it."""

    def __init__(self, text):
        self.editor = CodeEditor()
        self.editor.setPlainText(text)
        self.bar = FindBar(lambda: self.editor)

    def search(self, query, replacement=""):
        self.bar.find_field.setText(query)
        self.bar.replace_field.setText(replacement)

    def selection(self):
        """Where the selection starts, and what it holds."""
        cursor = self.editor.textCursor()
        return cursor.selectionStart(), cursor.selectedText()


@pytest.fixture
def harness(qapp):
    return Harness("cat Cat dog cat")


def test_find_next_moves_through_matches_and_wraps_around(harness):
    harness.search("cat")

    found = [harness.bar.find_next() and harness.selection() for _ in range(4)]

    assert found == [(0, "cat"), (4, "Cat"), (12, "cat"), (0, "cat")]


def test_find_previous_moves_backward_and_wraps_around(harness):
    harness.search("cat")

    found = [harness.bar.find_previous() and harness.selection() for _ in range(3)]

    assert found == [(12, "cat"), (4, "Cat"), (0, "cat")]


def test_match_case_skips_matches_with_different_capitals(harness):
    harness.search("cat")
    harness.bar.match_case.setChecked(True)

    found = [harness.bar.find_next() and harness.selection() for _ in range(3)]

    assert found == [(0, "cat"), (12, "cat"), (0, "cat")]


def test_a_search_with_no_match_says_so_and_leaves_the_cursor_alone(harness):
    harness.search("bird")

    assert not harness.bar.find_next()

    assert harness.bar.status.text() == "No results"
    assert harness.selection() == (0, "")


def test_typing_a_new_search_clears_the_status(harness):
    harness.search("bird")
    harness.bar.find_next()

    harness.search("cat")

    assert harness.bar.status.text() == ""


def test_replace_swaps_the_selected_match_and_moves_to_the_next(harness):
    harness.search("cat", "bird")
    harness.bar.find_next()

    harness.bar.replace()

    assert harness.editor.toPlainText() == "bird Cat dog cat"
    assert harness.selection() == (5, "Cat")


def test_replace_without_a_selected_match_only_finds_the_first_one(harness):
    harness.search("dog", "bird")

    harness.bar.replace()

    assert harness.editor.toPlainText() == "cat Cat dog cat"
    assert harness.selection() == (8, "dog")


def test_replace_all_replaces_every_match_as_one_undo_step(harness):
    harness.search("cat", "bird")

    harness.bar.replace_all()

    assert harness.editor.toPlainText() == "bird bird dog bird"
    assert harness.bar.status.text() == "Replaced 3"

    harness.editor.undo()
    assert harness.editor.toPlainText() == "cat Cat dog cat"


def test_replace_all_respects_match_case(harness):
    harness.search("cat", "bird")
    harness.bar.match_case.setChecked(True)

    harness.bar.replace_all()

    assert harness.editor.toPlainText() == "bird Cat dog bird"


def test_replace_all_ends_when_the_replacement_contains_the_search(harness):
    harness.search("cat", "catcat")

    harness.bar.replace_all()

    assert harness.editor.toPlainText() == "catcat catcat dog catcat"


def test_showing_the_bar_starts_from_the_selected_text(harness):
    harness.search("cat")
    harness.bar.find_next()
    harness.bar.find_next()

    harness.bar.show_find()

    assert not harness.bar.isHidden()
    assert harness.bar.find_field.text() == "Cat"


def test_dismissing_hides_the_bar(harness):
    harness.bar.show_find()

    harness.bar.dismiss()

    assert harness.bar.isHidden()


def test_the_bar_stays_hidden_when_no_file_is_open(qapp):
    bar = FindBar(lambda: None)

    bar.show_find()
    bar.find_field.setText("anything")

    assert bar.isHidden()
    assert not bar.find_next()
