from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QFont, QTextCursor, QTextFormat

from pyde.editor import CodeEditor
from pyde.preview import FileView, MarkdownPreview, TablePreview, can_preview


@pytest.mark.parametrize(
    "name", ["README.md", "NOTES.MD", "guide.markdown", "data.csv", "data.TSV"]
)
def test_markdown_and_delimited_files_have_a_preview(tmp_path, name):
    assert can_preview(tmp_path / name)


@pytest.mark.parametrize("name", ["app.py", "notes.txt", "md", "data.csv.bak"])
def test_other_files_do_not(tmp_path, name):
    assert not can_preview(tmp_path / name)


def test_a_file_never_saved_has_no_preview():
    assert not can_preview(None)


# Markdown


MARKDOWN = """\
# Title

Some **bold** and *italic* words, and `code`.

---

## Section

- first
- second
"""


@pytest.fixture
def markdown(qapp, tmp_path):
    preview = MarkdownPreview()
    preview.show_text(MARKDOWN, tmp_path / "README.md")
    yield preview
    preview.deleteLater()


def blocks(preview):
    block = preview.document().begin()
    while block.isValid():
        yield block
        block = block.next()


def format_at(preview, word):
    """The character format of the first letter of `word`."""
    cursor = preview.document().find(word)
    assert not cursor.isNull(), f"{word!r} is not in the preview"
    cursor.setPosition(cursor.selectionStart() + 1)
    return cursor.charFormat()


def test_markdown_is_shown_without_its_markup(markdown):
    text = markdown.toPlainText()

    assert "Title" in text and "Section" in text
    assert "Some bold and italic words, and code." in text
    for markup in ("#", "**", "*italic*", "`", "---"):
        assert markup not in text


def test_headings_are_real_headings(markdown):
    levels = {
        block.text(): block.blockFormat().headingLevel() for block in blocks(markdown)
    }

    assert levels["Title"] == 1
    assert levels["Section"] == 2
    assert levels["Some bold and italic words, and code."] == 0


def test_bold_and_italic_are_real_bold_and_italic(markdown):
    assert format_at(markdown, "bold").fontWeight() == QFont.Weight.Bold
    assert format_at(markdown, "italic").fontItalic()
    plain = format_at(markdown, "Some")
    assert plain.fontWeight() == QFont.Weight.Normal and not plain.fontItalic()


def test_a_rule_is_a_real_horizontal_rule(markdown):
    rule = QTextFormat.Property.BlockTrailingHorizontalRulerWidth
    rules = [
        block for block in blocks(markdown) if block.blockFormat().hasProperty(rule)
    ]

    assert len(rules) == 1


def test_a_list_is_a_real_list(markdown):
    items = [block.text() for block in blocks(markdown) if block.textList()]

    assert items == ["first", "second"]


def test_the_markdown_preview_cannot_be_edited(markdown):
    assert markdown.isReadOnly()


def test_relative_links_are_relative_to_the_files_folder(qapp, tmp_path):
    preview = MarkdownPreview()

    preview.show_text("[other](docs/other.md)", tmp_path / "README.md")

    # Compared as paths: Qt writes a Windows path with forward slashes.
    link = preview.document().baseUrl().resolved(QUrl("docs/other.md"))
    assert Path(link.toLocalFile()) == tmp_path / "docs" / "other.md"


# Tables


def table(tmp_path, name, text):
    preview = TablePreview()
    preview.show_text(text, tmp_path / name)
    return preview


def contents(preview):
    """The table as a list of rows, the first being the column headings."""
    model = preview.model()
    columns = range(model.columnCount())
    names = [model.headerData(c, Qt.Orientation.Horizontal) for c in columns]
    rows = [
        [model.index(row, column).data() for column in columns]
        for row in range(model.rowCount())
    ]
    return [names, *rows]


def test_comma_separated_values_become_a_table_headed_by_the_first_row(qapp, tmp_path):
    preview = table(tmp_path, "people.csv", "name,age\nAda,36\nGrace,45\n")

    assert contents(preview) == [["name", "age"], ["Ada", "36"], ["Grace", "45"]]


def test_tab_separated_values_split_on_tabs_and_keep_their_commas(qapp, tmp_path):
    preview = table(tmp_path, "people.tsv", "name\tcity\nAda\tLondon, UK\n")

    assert contents(preview) == [["name", "city"], ["Ada", "London, UK"]]


def test_quoted_values_may_hold_commas_quotes_and_line_breaks(qapp, tmp_path):
    text = 'name,note\nAda,"first, ""programmer""\nsecond line"\n'

    preview = table(tmp_path, "notes.csv", text)

    assert contents(preview) == [
        ["name", "note"],
        ["Ada", 'first, "programmer"\nsecond line'],
    ]


def test_rows_of_different_lengths_are_padded_to_the_widest(qapp, tmp_path):
    preview = table(tmp_path, "ragged.csv", "a,b\n1\n1,2,3\n")

    assert contents(preview) == [["a", "b", ""], ["1", "", ""], ["1", "2", "3"]]


def test_rows_are_numbered_from_one(qapp, tmp_path):
    preview = table(tmp_path, "people.csv", "name\nAda\nGrace\n")
    model = preview.model()

    numbers = [model.headerData(row, Qt.Orientation.Vertical) for row in range(2)]

    assert numbers == [1, 2]


def test_an_empty_file_is_an_empty_table(qapp, tmp_path):
    assert contents(table(tmp_path, "empty.csv", "")) == [[]]


def test_the_table_cannot_be_edited(qapp, tmp_path):
    preview = table(tmp_path, "people.csv", "name\nAda\n")
    cell = preview.model().index(0, 0)

    assert not preview.model().flags(cell) & Qt.ItemFlag.ItemIsEditable
    assert not preview.model().setData(cell, "changed")


def test_a_very_wide_column_is_capped(qapp, tmp_path):
    preview = table(tmp_path, "wide.csv", "text\n" + "x" * 5000 + "\n")

    assert preview.columnWidth(0) <= 400


# A file's view


@pytest.fixture
def view(qapp, tmp_path):
    path = tmp_path / "README.md"
    path.write_text("# Title\n")
    editor = CodeEditor()
    editor.load(path)
    view = FileView(editor)
    yield view
    view.deleteLater()


def test_a_view_starts_on_its_editor(view):
    assert view.can_preview
    assert not view.previewing
    assert view.currentWidget() is view.editor


def test_previewing_shows_the_preview_and_leaving_it_shows_the_editor(view):
    view.set_previewing(True)
    assert view.previewing
    assert isinstance(view.currentWidget(), MarkdownPreview)
    assert view.currentWidget().toPlainText() == "Title"

    view.set_previewing(False)
    assert view.currentWidget() is view.editor


def test_the_preview_shows_edits_not_yet_saved(view):
    cursor = view.editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.insertText("\nA **new** line.\n")

    view.set_previewing(True)

    assert "A new line." in view.currentWidget().toPlainText()
    # Looking at the preview changes nothing.
    assert view.editor.toPlainText() == "# Title\n\nA **new** line.\n"


def test_a_file_without_a_preview_stays_on_its_editor(qapp, tmp_path):
    path = tmp_path / "app.py"
    path.write_text("x = 1\n")
    editor = CodeEditor()
    editor.load(path)
    view = FileView(editor)

    view.set_previewing(True)

    assert not view.can_preview
    assert not view.previewing


def test_saving_as_another_kind_of_file_changes_the_kind_of_preview(view, tmp_path):
    view.set_previewing(True)
    view.set_previewing(False)
    view.editor.setPlainText("a,b\n1,2\n")

    view.editor.save(tmp_path / "data.csv")
    view.set_previewing(True)

    assert isinstance(view.currentWidget(), TablePreview)
    assert view.count() == 2
