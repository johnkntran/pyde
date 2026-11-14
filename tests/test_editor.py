import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest

from pyde.editor import CodeEditor

KEEP_ANCHOR = QTextCursor.MoveMode.KeepAnchor


@pytest.fixture
def editor(qapp):
    editor = CodeEditor()
    yield editor
    editor.deleteLater()


def put_cursor(editor, position, anchor=None):
    """Place the cursor, selecting from `anchor` to `position` if given."""
    cursor = editor.textCursor()
    cursor.setPosition(position if anchor is None else anchor)
    if anchor is not None:
        cursor.setPosition(position, KEEP_ANCHOR)
    editor.setTextCursor(cursor)


def press(editor, key, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(editor, key, modifier)


def test_a_new_editor_is_untitled_and_unmodified(editor):
    assert editor.title == "Untitled"
    assert editor.path is None
    assert not editor.document().isModified()


def test_loading_a_file_shows_its_text(editor, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("first\nsecond\n")

    editor.load(path)

    assert editor.toPlainText() == "first\nsecond\n"
    assert editor.title == "notes.txt"
    assert not editor.document().isModified()


def test_saving_writes_the_text_and_clears_the_modified_flag(editor, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("first\n")
    editor.load(path)

    editor.appendPlainText("second")
    assert editor.document().isModified()
    editor.save()

    assert path.read_text() == "first\n\nsecond"
    assert not editor.document().isModified()


def test_saving_to_a_new_path_adopts_it(editor, tmp_path):
    editor.setPlainText("text")

    editor.save(tmp_path / "new.txt")

    assert (tmp_path / "new.txt").read_text() == "text"
    assert editor.title == "new.txt"


def test_windows_line_endings_survive_a_save(editor, tmp_path):
    path = tmp_path / "windows.txt"
    path.write_bytes(b"one\r\ntwo\r\n")
    editor.load(path)
    assert editor.toPlainText() == "one\ntwo\n"

    editor.appendPlainText("three")
    editor.save()

    assert path.read_bytes() == b"one\r\ntwo\r\n\r\nthree"


def test_loading_a_file_that_is_not_text_is_an_error(editor, tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")

    with pytest.raises(UnicodeDecodeError):
        editor.load(path)


def test_tab_inserts_spaces_up_to_the_next_stop(editor):
    editor.setPlainText("ab")
    put_cursor(editor, 2)

    press(editor, Qt.Key.Key_Tab)

    assert editor.toPlainText() == "ab  "


def test_tab_inserts_a_tab_in_a_file_indented_with_tabs(editor, tmp_path):
    path = tmp_path / "Makefile"
    path.write_text("build:\n\techo hi\n")
    editor.load(path)
    put_cursor(editor, 0)

    press(editor, Qt.Key.Key_Tab)

    assert editor.toPlainText() == "\tbuild:\n\techo hi\n"


def test_return_keeps_the_indentation_of_the_current_line(editor):
    editor.setPlainText("    indented")
    put_cursor(editor, len("    indented"))

    press(editor, Qt.Key.Key_Return)
    QTest.keyClicks(editor, "next")

    assert editor.toPlainText() == "    indented\n    next"


def test_return_inside_the_indentation_copies_only_what_is_before_the_cursor(editor):
    editor.setPlainText("        deep")
    put_cursor(editor, 4)

    press(editor, Qt.Key.Key_Return)

    assert editor.toPlainText() == "    \n        deep"


def test_tab_indents_every_selected_line_as_one_undo_step(editor):
    editor.setPlainText("one\n\ntwo\nthree")
    put_cursor(editor, len("one\n\ntw"), anchor=1)

    press(editor, Qt.Key.Key_Tab)
    # The blank line stays blank, and the line the selection never reached
    # is untouched.
    assert editor.toPlainText() == "    one\n\n    two\nthree"

    editor.undo()
    assert editor.toPlainText() == "one\n\ntwo\nthree"


def test_a_selection_ending_at_the_start_of_a_line_leaves_that_line_alone(editor):
    editor.setPlainText("one\ntwo\nthree")
    put_cursor(editor, len("one\ntwo\n"), anchor=0)

    press(editor, Qt.Key.Key_Tab)

    assert editor.toPlainText() == "    one\n    two\nthree"


def test_shift_tab_outdents_the_selected_lines(editor):
    editor.setPlainText("        deep\n  shallow\nflush\n\ttabbed")
    editor.selectAll()

    press(editor, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)

    assert editor.toPlainText() == "    deep\nshallow\nflush\ntabbed"


def test_shift_tab_without_a_selection_outdents_the_current_line(editor):
    editor.setPlainText("    one\n    two")
    put_cursor(editor, len("    one\n    t"))

    press(editor, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)

    assert editor.toPlainText() == "    one\ntwo"


def test_the_line_number_gutter_widens_for_longer_files(editor):
    editor.setPlainText("\n".join(["line"] * 99))
    narrow = editor.line_number_area_width()
    assert editor.viewportMargins().left() == narrow

    editor.setPlainText("\n".join(["line"] * 10_000))

    assert editor.line_number_area_width() > narrow
    assert editor.viewportMargins().left() == editor.line_number_area_width()


def test_a_file_is_colored_by_its_type_without_counting_as_an_edit(
    editor, tmp_path, color_at, wait_until
):
    path = tmp_path / "script.py"
    path.write_text("return 1\n")

    editor.load(path)

    wait_until(lambda: color_at(editor.document(), 0, 0) == "#008000")
    assert not editor.document().isModified()
    assert not editor.document().isUndoAvailable()


def test_a_file_of_unknown_type_is_left_uncolored(
    editor, tmp_path, color_at, wait_until
):
    path = tmp_path / "script.unknownext"
    path.write_text("return 1\n")

    editor.load(path)
    QTest.qWait(50)

    assert color_at(editor.document(), 0, 0) is None


def test_saving_under_a_new_name_recolors_for_the_new_type(
    editor, tmp_path, color_at, wait_until
):
    editor.setPlainText("return 1\n")

    editor.save(tmp_path / "script.py")
    wait_until(lambda: color_at(editor.document(), 0, 0) == "#008000")

    editor.save(tmp_path / "script.unknownext")
    wait_until(lambda: color_at(editor.document(), 0, 0) is None)

    # Swapping the colors in and out is not an edit.
    assert not editor.document().isModified()
    assert not editor.document().isUndoAvailable()


# Selecting part of a line


def test_select_picks_out_part_of_a_line(editor):
    editor.setPlainText("first\nsecond needle\nthird")

    editor.select(2, 7, 6)

    assert editor.textCursor().selectedText() == "needle"
    assert editor.textCursor().blockNumber() == 1


def test_select_counts_characters_however_qt_stores_them(editor):
    # Qt holds each of these faces as two units, and counts in units.
    editor.setPlainText("😀😀 needle 😀")

    editor.select(1, 3, 8)

    assert editor.textCursor().selectedText() == "needle 😀"


def test_select_settles_for_the_nearest_place_when_the_text_has_changed(editor):
    editor.setPlainText("one\ntwo")

    # A line past the end is taken as the last one.
    editor.select(9, 0, 3)
    assert editor.textCursor().selectedText() == "two"

    # A selection that runs past the end of its line stops there.
    editor.select(1, 2, 50)
    assert editor.textCursor().selectedText() == "e"

    editor.select(1, 40, 5)
    assert not editor.textCursor().hasSelection()
    assert editor.textCursor().position() == 3


def test_select_scrolls_to_the_line(editor, wait_until):
    editor.setPlainText("\n".join(f"line {number}" for number in range(1, 501)))
    editor.resize(400, 300)
    editor.show()
    wait_until(lambda: editor.viewport().height() > 0)

    editor.select(400, 0, 4)

    # The line is brought to the middle, where there is context either side.
    height = editor.viewport().height()
    assert abs(editor.cursorRect().center().y() - height / 2) < height / 4
    assert editor.textCursor().blockNumber() == 399
