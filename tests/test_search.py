import subprocess
import threading

import pytest
from PySide6.QtTest import QTest

from pyde import search
from pyde.editor import CodeEditor
from pyde.search import Match, Searcher, compile_query, find_in_file


def write(folder, name, text):
    """Write a file exactly as given: UTF-8, and its line endings untouched."""
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def find(path, query, match_case=False):
    return find_in_file(path, compile_query(query, match_case))


# One file


def test_each_matching_line_comes_with_its_number_column_and_text(tmp_path):
    path = write(tmp_path, "notes.txt", "needle one\nnothing\n    two needle\n")

    assert find(path, "needle") == [
        Match(1, 0, "needle one"),
        # The column counts the indentation that the shown text leaves out.
        Match(3, 8, "two needle"),
    ]


def test_case_is_ignored_unless_asked_to_match_it(tmp_path):
    path = write(tmp_path, "notes.txt", "Needle\nneedle\nNEEDLE\n")

    assert [match.line for match in find(path, "needle")] == [1, 2, 3]
    assert [match.line for match in find(path, "needle", match_case=True)] == [2]


def test_the_query_is_plain_text_not_an_expression(tmp_path):
    path = write(tmp_path, "code.py", "abc\na.c\nf(x)* [y]\n")

    assert [match.line for match in find(path, "a.c")] == [2]
    assert [match.line for match in find(path, "f(x)* [y]")] == [3]


def test_a_line_is_listed_once_however_often_it_matches(tmp_path):
    path = write(tmp_path, "notes.txt", "x = x + x\n")

    assert find(path, "x") == [Match(1, 0, "x = x + x")]


def test_columns_count_characters(tmp_path):
    path = write(tmp_path, "notes.txt", "café 😀 needle\n")

    assert find(path, "needle") == [Match(1, 7, "café 😀 needle")]


def test_line_numbers_agree_with_the_editors(qapp, tmp_path):
    # Every way a line can end, and two characters that look as if they might.
    text = "one\rtwo\r\nthree four\x0cfive six\nneedle\n"
    path = write(tmp_path, "notes.txt", text)
    editor = CodeEditor()
    editor.load(path)

    (match,) = find(path, "needle")

    assert editor.document().findBlockByNumber(match.line - 1).text() == "needle"
    editor.deleteLater()


def test_a_file_that_is_not_text_has_no_matches(tmp_path):
    binary = tmp_path / "image.bin"
    binary.write_bytes(b"needle\0needle")
    latin_1 = tmp_path / "old.txt"
    latin_1.write_bytes("needle café".encode("latin-1"))

    assert find(binary, "needle") == []
    assert find(latin_1, "needle") == []


def test_a_file_that_cannot_be_read_has_no_matches(tmp_path):
    (tmp_path / "folder").mkdir()

    assert find(tmp_path / "missing.txt", "needle") == []
    assert find(tmp_path / "folder", "needle") == []


def test_a_very_large_file_is_passed_over(tmp_path, monkeypatch):
    path = write(tmp_path, "data.txt", "needle\n" * 10)
    monkeypatch.setattr(search, "MAX_FILE_BYTES", 69)

    assert find(path, "needle") == []

    monkeypatch.setattr(search, "MAX_FILE_BYTES", 70)
    assert len(find(path, "needle")) == 10


# The text shown for a match


def shown(tmp_path, line, query="needle"):
    (match,) = find(write(tmp_path, "notes.txt", line + "\n"), query)
    return match.text


def test_the_shown_text_drops_the_space_around_the_line(tmp_path):
    assert shown(tmp_path, "\t\t  a needle  ") == "a needle"


def test_a_tab_inside_the_line_shows_as_a_space(tmp_path):
    assert shown(tmp_path, "one\ttwo needle") == "one two needle"


def test_a_match_in_the_indentation_keeps_it(tmp_path):
    assert shown(tmp_path, "    needle", query="  needle") == "  needle"


def test_a_long_line_is_cut_short(tmp_path):
    text = shown(tmp_path, "needle " + "x" * 1000)

    assert text == ("needle " + "x" * 1000)[: search.MAX_SHOWN]


def test_a_match_far_along_a_long_line_is_shown_with_a_little_before_it(tmp_path):
    text = shown(tmp_path, "a" * 500 + "needle" + "b" * 500)

    assert text.startswith("…" + "a" * search.SHOWN_BEFORE + "needle")
    assert len(text) == 1 + search.MAX_SHOWN


# A whole folder


class Harness:
    """A searcher, and everything it has announced."""

    def __init__(self):
        self.searcher = Searcher()
        # Each file's path with the numbers of its matching lines.
        self.found = []
        self.finished = []
        self.searcher.found.connect(
            lambda path, matches: self.found.append(
                (path, [match.line for match in matches])
            )
        )
        self.searcher.finished.connect(self.finished.append)

    def search(self, folder, query, match_case=False):
        """Start a search, and return the thread that carries it out."""
        before = set(threading.enumerate())
        self.searcher.start(folder, compile_query(query, match_case))
        (thread,) = set(threading.enumerate()) - before
        return thread


@pytest.fixture
def examined(monkeypatch):
    """The files that searches read, each as (what was searched for, its name)."""
    examined = []
    find_in_file = search.find_in_file

    def recording(path, pattern):
        examined.append((pattern.pattern, path.name))
        return find_in_file(path, pattern)

    monkeypatch.setattr(search, "find_in_file", recording)
    return examined


@pytest.fixture
def harness(qapp):
    return Harness()


def test_a_search_announces_each_file_with_matches_then_that_it_is_over(
    harness, tmp_path, wait_until
):
    write(tmp_path, "a.txt", "needle\n")
    write(tmp_path, "b.txt", "nothing\n")
    write(tmp_path, "src/c.txt", "one\nneedle\nneedle\n")

    harness.search(tmp_path, "needle")
    assert harness.searcher.running
    wait_until(lambda: harness.finished)

    assert harness.found == [("a.txt", [1]), ("src/c.txt", [2, 3])]
    assert harness.finished == [False]
    assert not harness.searcher.running


def test_files_that_git_ignores_are_not_searched(harness, tmp_path, wait_until):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    write(tmp_path, ".gitignore", "build/\n")
    write(tmp_path, "build/output.txt", "needle\n")
    write(tmp_path, "source.txt", "needle\n")

    harness.search(tmp_path, "needle")
    wait_until(lambda: harness.finished)

    assert harness.found == [("source.txt", [1])]


def test_a_search_stops_at_the_limit_and_says_so(
    harness, tmp_path, wait_until, monkeypatch, examined
):
    monkeypatch.setattr(search, "MAX_MATCHES", 3)
    for name in ("a.txt", "b.txt", "c.txt"):
        write(tmp_path, name, "needle\nneedle\n")

    harness.search(tmp_path, "needle")
    wait_until(lambda: harness.finished)

    assert harness.found == [("a.txt", [1, 2]), ("b.txt", [1])]
    assert harness.finished == [True]
    # It does not read on once it has all it will show.
    assert examined == [("needle", "a.txt"), ("needle", "b.txt")]


def test_a_new_search_stops_the_one_still_going(harness, tmp_path, examined):
    for number in range(50):
        write(tmp_path, f"{number}.txt", "first second\n")

    first = harness.search(tmp_path, "first")
    second = harness.search(tmp_path, "second")
    first.join(timeout=30)
    second.join(timeout=30)

    assert not first.is_alive() and not second.is_alive()
    assert len([name for query, name in examined if query == "second"]) == 50
    assert len([name for query, name in examined if query == "first"]) < 50


def test_what_an_earlier_search_found_is_dropped_once_a_new_one_starts(
    harness, tmp_path, wait_until
):
    write(tmp_path, "notes.txt", "first\nsecond\n")

    # The first search runs to its end, but nothing has yet looked at what it
    # has to say when the second one starts.
    harness.search(tmp_path, "first").join(timeout=30)
    harness.search(tmp_path, "second")
    wait_until(lambda: harness.finished)
    QTest.qWait(100)

    assert harness.found == [("notes.txt", [2])]
    assert harness.finished == [False]
    assert not harness.searcher.running


def test_a_cancelled_search_is_not_heard_from_again(harness, tmp_path):
    write(tmp_path, "notes.txt", "needle\n")

    # Even one that had finished its work before it was cancelled.
    harness.search(tmp_path, "needle").join(timeout=30)
    harness.searcher.cancel()
    QTest.qWait(100)

    assert not harness.searcher.running
    assert harness.found == []
    assert harness.finished == []


def test_a_cancelled_search_stops_reading_files(harness, tmp_path, examined):
    for number in range(50):
        write(tmp_path, f"{number}.txt", "needle\n")

    thread = harness.search(tmp_path, "needle")
    harness.searcher.cancel()
    thread.join(timeout=30)

    assert not thread.is_alive()
    assert len(examined) < 50
