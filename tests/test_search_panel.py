import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from pyde import search
from pyde.search import compile_query
from pyde.search_panel import SearchPanel, split_at_occurrences


@pytest.fixture
def folder(tmp_path):
    folder = tmp_path / "project"
    (folder / "src").mkdir(parents=True)
    (folder / "notes.txt").write_text("a needle\nnothing\n")
    (folder / "src" / "code.py").write_text(
        "x = 1\n    needle = 2\n" + "y = 3\n" * 7 + "print(NEEDLE, needle)\n"
    )
    return folder


class Harness:
    """A search panel pointed at a folder, and what it has announced."""

    def __init__(self, folder, wait_until):
        self.panel = SearchPanel()
        self.panel.set_folder(folder)
        self._wait_until = wait_until
        self.activated = []
        self.dismissals = []
        self.panel.match_activated.connect(lambda *match: self.activated.append(match))
        self.panel.dismissed.connect(lambda: self.dismissals.append(True))

    def search(self, query):
        """Type a search, press Return, and wait for it to finish."""
        self.panel.field.setText(query)
        QTest.keyClick(self.panel.field, Qt.Key.Key_Return)
        self._wait_until(lambda: not self.panel.searching)

    def results(self):
        """Each file's row with the rows under it, as their text."""
        tree = self.panel.results
        files = [tree.topLevelItem(row) for row in range(tree.topLevelItemCount())]
        return [
            (
                file.text(0),
                [file.child(row).text(0) for row in range(file.childCount())],
            )
            for file in files
        ]

    def row(self, file, line):
        """One of the rows: a file's, or with `line` the one for that line."""
        file_row = self.panel.results.topLevelItem(file)
        return file_row if line is None else file_row.child(line)

    def show(self):
        self.panel.show()
        self.panel.activateWindow()
        self._wait_until(self.panel.isActiveWindow)


@pytest.fixture
def harness(qapp, folder, wait_until):
    harness = Harness(folder, wait_until)
    yield harness
    harness.panel.shutdown()
    harness.panel.close()


# Searching


def test_return_searches_and_lists_the_matching_lines_by_file(harness):
    harness.search("needle")

    assert harness.results() == [
        ("notes.txt", ["1: a needle"]),
        # Line numbers are padded to the longest, so the lines start level.
        ("src/code.py", [" 2: needle = 2", "10: print(NEEDLE, needle)"]),
    ]
    assert harness.panel.status.text() == "3 results in 2 files"
    # The files start unfolded, with their matches showing.
    assert harness.row(0, None).isExpanded()


def test_the_status_counts_one_result_as_one(harness):
    harness.search("a needle")

    assert harness.panel.status.text() == "1 result in 1 file"


def test_a_search_that_finds_nothing_says_so(harness):
    harness.search("haystack")

    assert harness.results() == []
    assert harness.panel.status.text() == "No results"


def test_a_search_cut_short_says_how_much_it_shows(harness, monkeypatch):
    monkeypatch.setattr(search, "MAX_MATCHES", 2)

    harness.search("needle")

    assert harness.panel.status.text() == "Showing the first 2 results"


def test_the_status_says_a_search_is_under_way(harness):
    harness.panel.field.setText("needle")

    harness.panel.search()

    assert harness.panel.searching
    assert harness.panel.status.text() == "Searching…"


def test_match_case_searches_again(harness):
    harness.search("NEEDLE")
    assert harness.panel.status.text() == "3 results in 2 files"

    harness.panel.match_case.click()
    harness._wait_until(lambda: not harness.panel.searching)

    assert harness.results() == [("src/code.py", ["10: print(NEEDLE, needle)"])]


def test_a_new_search_replaces_the_old_results(harness):
    harness.search("needle")

    harness.search("nothing")

    assert harness.results() == [("notes.txt", ["2: nothing"])]
    assert harness.panel.status.text() == "1 result in 1 file"


def test_searching_for_nothing_clears_the_results(harness):
    harness.search("needle")

    harness.search("")

    assert harness.results() == []
    assert harness.panel.status.text() == ""


def test_another_folder_drops_the_results_and_is_searched_next(harness, tmp_path):
    harness.search("needle")
    other = tmp_path / "other"
    other.mkdir()
    (other / "elsewhere.txt").write_text("needle\n")

    harness.panel.set_folder(other)
    assert harness.results() == []
    assert harness.panel.status.text() == ""

    harness.search("needle")
    assert harness.results() == [("elsewhere.txt", ["1: needle"])]


def test_a_search_without_a_folder_does_nothing(qapp):
    panel = SearchPanel()
    panel.field.setText("needle")

    panel.search()

    assert not panel.searching
    assert panel.status.text() == ""


# Choosing a result


def test_double_clicking_a_result_announces_where_the_text_is(harness, folder):
    harness.search("needle")

    harness.panel.results.itemDoubleClicked.emit(harness.row(1, 0), 0)

    # The file, the line, and the column and length of the text in it.
    assert harness.activated == [(folder / "src" / "code.py", 2, 4, 6)]


def test_double_clicking_a_files_row_announces_nothing(harness):
    harness.search("needle")

    harness.panel.results.itemDoubleClicked.emit(harness.row(1, None), 0)

    assert harness.activated == []


def test_return_on_a_result_announces_it(harness, folder):
    harness.search("needle")
    harness.panel.results.setCurrentItem(harness.row(1, 1))

    QTest.keyClick(harness.panel.results, Qt.Key.Key_Return)

    assert harness.activated == [(folder / "src" / "code.py", 10, 6, 6)]


def test_return_on_a_files_row_folds_and_unfolds_it(harness):
    harness.search("needle")
    file_row = harness.row(0, None)
    harness.panel.results.setCurrentItem(file_row)

    QTest.keyClick(harness.panel.results, Qt.Key.Key_Return)
    assert not file_row.isExpanded()

    QTest.keyClick(harness.panel.results, Qt.Key.Key_Return)
    assert file_row.isExpanded()
    assert harness.activated == []


# Moving about with the keyboard


def test_start_typing_focuses_the_field_with_its_text_selected(harness):
    harness.show()
    harness.panel.field.setText("old")
    harness.panel.results.setFocus()
    assert not harness.panel.field.hasFocus()

    harness.panel.start_typing()
    assert harness.panel.field.hasFocus()
    assert harness.panel.field.selectedText() == "old"

    harness.panel.start_typing("new")
    assert harness.panel.field.selectedText() == "new"


def test_down_moves_from_the_field_to_the_first_result(harness):
    harness.show()
    harness.search("needle")

    QTest.keyClick(harness.panel.field, Qt.Key.Key_Down)

    assert harness.panel.results.hasFocus()
    assert harness.panel.results.currentItem() is harness.row(0, 0)


def test_down_returns_to_the_result_that_was_current(harness):
    harness.show()
    harness.search("needle")
    harness.panel.results.setCurrentItem(harness.row(1, 1))

    QTest.keyClick(harness.panel.field, Qt.Key.Key_Down)

    assert harness.panel.results.currentItem() is harness.row(1, 1)


def test_down_stays_in_the_field_when_there_are_no_results(harness):
    harness.show()
    harness.panel.start_typing()

    QTest.keyClick(harness.panel.field, Qt.Key.Key_Down)

    assert harness.panel.field.hasFocus()


def test_escape_in_the_field_or_the_results_asks_to_go_back(harness):
    QTest.keyClick(harness.panel.field, Qt.Key.Key_Escape)
    QTest.keyClick(harness.panel.results, Qt.Key.Key_Escape)

    assert harness.dismissals == [True, True]


# Drawing a result


def test_text_is_split_at_each_occurrence_of_what_was_searched_for():
    pattern = compile_query("ab", match_case=False)

    assert split_at_occurrences("xabyAB", pattern) == [
        ("x", False),
        ("ab", True),
        ("y", False),
        ("AB", True),
    ]
    assert split_at_occurrences("abab", pattern) == [("ab", True), ("ab", True)]
    assert split_at_occurrences("none here", pattern) == [("none here", False)]


def test_a_result_and_a_files_row_both_draw(harness):
    harness.search("needle")
    tree = harness.panel.results
    state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Active
    white = QColor("white")

    for row in (harness.row(1, 0), harness.row(1, None)):
        for selected in (False, True):
            image = QImage(400, 30, QImage.Format.Format_RGB32)
            image.fill(white)
            option = QStyleOptionViewItem()
            option.initFrom(tree)
            option.widget = tree
            option.font = tree.font()
            option.rect = QRect(0, 0, 400, 30)
            option.state = state
            if selected:
                option.state |= QStyle.StateFlag.State_Selected
            painter = QPainter(image)
            tree.itemDelegate().paint(painter, option, tree.indexFromItem(row))
            painter.end()

            pixels = {
                image.pixelColor(x, y).name() for x in range(400) for y in range(30)
            }
            assert len(pixels) > 1, "nothing was drawn"
