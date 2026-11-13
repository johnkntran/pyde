import pytest
from pygments.lexer import RegexLexer
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QTextCursor, QTextDocument
from PySide6.QtWidgets import QPlainTextDocumentLayout

from pyde.highlighter import DARK_STYLE, SyntaxHighlighter, lexer_for, styles

# Colors from Pygments' "default" style, which the tests run under.
KEYWORD = "#008000"
STRING = "#ba2121"
COMMENT = "#3d7b7b"


def highlighted(filename, text):
    """A document holding `text`, colored as the language `filename` implies."""
    document = QTextDocument()
    document.setDocumentLayout(QPlainTextDocumentLayout(document))
    document.setPlainText(text)
    highlighter = SyntaxHighlighter(document, lexer_for(filename, text))
    highlighter.rehighlight()
    return document, highlighter


@pytest.mark.parametrize(
    ("filename", "language"),
    [
        ("app.py", "Python"),
        ("settings.json", "JSON"),
        ("compose.yml", "YAML"),
        ("pyproject.toml", "TOML"),
        ("index.html", "HTML"),
        ("README.md", "Markdown"),
        ("Dockerfile", "Docker"),
        ("Makefile", "Makefile"),
    ],
)
def test_the_lexer_is_chosen_by_file_name(filename, language):
    assert lexer_for(filename).name == language


@pytest.mark.parametrize("filename", ["notes.unknownext", ".gitignore", "LICENSE"])
def test_a_file_of_unknown_type_has_no_lexer(filename):
    assert lexer_for(filename) is None


def test_keywords_strings_and_comments_get_their_colors(qapp, color_at):
    document, _ = highlighted("a.py", 'def f():\n    return "text"  # note\n')

    assert color_at(document, 0, 0) == KEYWORD
    assert color_at(document, 1, 4) == KEYWORD
    assert color_at(document, 1, 11) == STRING
    assert color_at(document, 1, 19) == COMMENT


def test_a_string_spanning_lines_stays_a_string_until_it_closes(qapp, color_at):
    document, _ = highlighted("a.py", 'x = """first\nsecond\nthird"""\nreturn\n')

    assert color_at(document, 1, 0) == STRING
    assert color_at(document, 2, 0) == STRING
    assert color_at(document, 3, 0) == KEYWORD


def test_opening_a_string_recolors_the_lines_below_it(qapp, color_at):
    document, _ = highlighted("a.py", "x = 1\nreturn\nreturn\n")
    assert color_at(document, 2, 0) == KEYWORD

    cursor = QTextCursor(document)
    cursor.insertText('"""')

    assert color_at(document, 1, 0) == STRING
    assert color_at(document, 2, 0) == STRING


def test_closing_the_string_again_restores_the_lines_below_it(qapp, color_at):
    document, _ = highlighted("a.py", '"""\nreturn\nreturn\n')
    assert color_at(document, 2, 0) == STRING

    cursor = QTextCursor(document)
    cursor.movePosition(QTextCursor.MoveOperation.EndOfLine)
    cursor.insertText('"""')

    assert color_at(document, 1, 0) == KEYWORD
    assert color_at(document, 2, 0) == KEYWORD


def test_colors_line_up_after_characters_outside_the_basic_plane(qapp, color_at):
    # Qt counts the emoji as two units, Python as one character.
    document, _ = highlighted("a.py", 'x = "🎉" # note\n')

    assert color_at(document, 0, 7) == STRING
    assert color_at(document, 0, 8) is None
    assert color_at(document, 0, 9) == COMMENT


def test_token_types_that_styles_do_not_list_still_get_a_color(qapp, color_at):
    # The YAML lexer uses its own token subtypes, such as Literal.Scalar.Plain.
    document, _ = highlighted("a.yml", "key: value\n# note\n")

    assert color_at(document, 0, 0) == KEYWORD
    assert color_at(document, 1, 0) == COMMENT


def test_lexers_not_built_on_regexlexer_are_colored_line_by_line(qapp, color_at):
    document, _ = highlighted("a.json", '{\n  "key": "value"\n}\n')

    assert not isinstance(lexer_for("a.json"), RegexLexer)
    assert color_at(document, 1, 2) == KEYWORD
    assert color_at(document, 1, 9) == STRING


def test_setting_a_style_recolors_the_document(qapp, color_at):
    document, highlighter = highlighted("a.py", "return\n")

    highlighter.set_style(DARK_STYLE)

    assert color_at(document, 0, 0) == "#ff7b72"


def test_the_style_follows_the_system_color_scheme(qapp, color_at):
    document, _ = highlighted("a.py", "return\n")
    # The test platform has no color scheme to switch, so announce a change
    # the way Qt does when macOS switches appearance.
    scheme_changed = QGuiApplication.styleHints().colorSchemeChanged

    scheme_changed.emit(Qt.ColorScheme.Dark)
    assert color_at(document, 0, 0) == "#ff7b72"

    scheme_changed.emit(Qt.ColorScheme.Light)
    assert color_at(document, 0, 0) == KEYWORD


def test_changing_the_shared_styles_recolors_open_documents(qapp, color_at):
    document, _ = highlighted("a.py", "return\n")
    assert color_at(document, 0, 0) == KEYWORD

    styles.set(light="xcode", dark=DARK_STYLE)

    # The keyword color of the "xcode" style.
    assert color_at(document, 0, 0) == "#a90d91"


def test_a_new_document_starts_with_the_shared_styles(qapp, color_at):
    styles.set(light="xcode", dark=DARK_STYLE)

    document, _ = highlighted("a.py", "return\n")

    assert color_at(document, 0, 0) == "#a90d91"


def test_dark_mode_uses_the_shared_dark_style(qapp, color_at):
    document, _ = highlighted("a.py", "return\n")
    styles.set(light="default", dark="monokai")

    QGuiApplication.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)

    # The keyword color of the "monokai" style.
    assert color_at(document, 0, 0) == "#66d9ef"


def test_pygments_is_left_as_it_was_found(qapp):
    lexer = lexer_for("a.py")

    document = QTextDocument()
    document.setPlainText('x = """open\n')
    SyntaxHighlighter(document, lexer).rehighlight()

    # Judged by where the function lives, so that an earlier test leaving the
    # replacement in place cannot make this one pass.
    assert RegexLexer.get_tokens_unprocessed.__module__ == "pygments.lexer"
    assert not hasattr(lexer, "_saved_state_stack")
