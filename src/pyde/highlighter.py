"""Syntax highlighting, using Pygments to find the tokens.

Adapted from two BSD-licensed sources, whose license texts are in licenses/:

- qtconsole's pygments_highlighter.py, Copyright (c) Jupyter Development Team,
  for the approach: lex one line at a time, resuming from the state the
  previous line ended in.
- Pygments' RegexLexer.get_tokens_unprocessed, Copyright 2006-present by the
  Pygments team, for the lexing loop that approach has to replace.

Changes from qtconsole's version:

- Ported from qtpy to PySide6.
- The state at the end of each line is stored as the Qt block state, not as
  block user data. Qt compares block states to decide whether the lines below
  an edit need highlighting again, which they do when, say, a multi-line
  string is opened or closed.
- The lexing loop is copied from the current Pygments, which, unlike the older
  copy in qtconsole, survives the stray state pops that half-typed code causes.
- Style sheet support is gone. Colors come from a Pygments style chosen to suit
  light or dark mode.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from pygments.lexer import Lexer, RegexLexer
from pygments.lexers import get_lexer_for_filename
from pygments.styles import get_style_by_name
from pygments.token import Error, Whitespace, _TokenType
from pygments.util import ClassNotFound
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)

LIGHT_STYLE = "default"
DARK_STYLE = "github-dark"


def lexer_for(filename: str, text: str = "") -> Lexer | None:
    """The Pygments lexer for a file, judged by its name, or None if unknown.

    The text settles it when more than one language uses the same extension.
    """
    try:
        return get_lexer_for_filename(filename, text)
    except ClassNotFound:
        return None


def _get_tokens_unprocessed(self, text, stack=("root",)):
    """RegexLexer.get_tokens_unprocessed, made to resume and to remember.

    It starts from the state stack saved on the lexer, if there is one, and
    saves the stack it ends with back on the lexer. Everything in between is
    Pygments' own loop, unchanged.
    """
    pos = 0
    tokendefs = self._tokens
    statestack = list(getattr(self, "_saved_state_stack", stack))
    statetokens = tokendefs[statestack[-1]]
    while 1:
        for rexmatch, action, new_state in statetokens:
            m = rexmatch(text, pos)
            if m:
                if action is not None:
                    if type(action) is _TokenType:
                        yield pos, action, m.group()
                    else:
                        yield from action(self, m)
                pos = m.end()
                if new_state is not None:
                    # state transition
                    if isinstance(new_state, tuple):
                        for state in new_state:
                            if state == "#pop":
                                if len(statestack) > 1:
                                    statestack.pop()
                            elif state == "#push":
                                statestack.append(statestack[-1])
                            else:
                                statestack.append(state)
                    elif isinstance(new_state, int):
                        # pop, but keep at least one state on the stack
                        # (random code leading to unexpected pops should
                        # not allow exceptions)
                        if abs(new_state) >= len(statestack):
                            del statestack[1:]
                        else:
                            del statestack[new_state:]
                    elif new_state == "#push":
                        statestack.append(statestack[-1])
                    else:
                        raise AssertionError(f"wrong state def: {new_state!r}")
                    statetokens = tokendefs[statestack[-1]]
                break
        else:
            # We are here only if all state tokens have been considered
            # and there was not a match on any of them.
            try:
                if text[pos] == "\n":
                    # at EOL, reset state to "root"
                    statestack = ["root"]
                    statetokens = tokendefs["root"]
                    yield pos, Whitespace, "\n"
                    pos += 1
                    continue
                yield pos, Error, text[pos]
                pos += 1
            except IndexError:
                break
    self._saved_state_stack = tuple(statestack)


@contextmanager
def _resumable_lexing() -> Iterator[None]:
    """Swap the resumable loop into RegexLexer for the duration of a block.

    The swap is on the class, not the lexer instance, because lexers such as
    the C one override get_tokens_unprocessed and call RegexLexer's from there.
    It is undone straight away so that nothing else using Pygments is affected.
    """
    original = RegexLexer.get_tokens_unprocessed
    RegexLexer.get_tokens_unprocessed = _get_tokens_unprocessed
    try:
        yield
    finally:
        RegexLexer.get_tokens_unprocessed = original


def _utf16_length(text: str) -> int:
    """How long Qt considers a string, which counts UTF-16 units, not characters."""
    return len(text.encode("utf-16-le")) // 2


class SyntaxHighlighter(QSyntaxHighlighter):
    """Colors a document one line at a time, as Qt asks for each line."""

    def __init__(self, document: QTextDocument, lexer: Lexer) -> None:
        super().__init__(document)
        self._lexer = lexer
        # A line's Qt block state is an index into _stacks: the lexer's state
        # stack as of the end of that line.
        self._stacks: list[tuple[str, ...]] = []
        self._state_ids: dict[tuple[str, ...], int] = {}
        self._formats: dict[_TokenType, QTextCharFormat] = {}

        hints = QGuiApplication.styleHints()
        hints.colorSchemeChanged.connect(self._follow_color_scheme)
        self._style = get_style_by_name(self._style_name(hints.colorScheme()))

    def highlightBlock(self, text: str) -> None:
        lexer = self._lexer
        with _resumable_lexing():
            previous = self.previousBlockState()
            if 0 <= previous < len(self._stacks):
                lexer._saved_state_stack = self._stacks[previous]
            else:
                lexer.__dict__.pop("_saved_state_stack", None)
            index = 0
            for token, value in lexer.get_tokens(text):
                length = _utf16_length(value)
                self.setFormat(index, length, self._format(token))
                index += length
            # Only lexers built on RegexLexer leave a stack behind. The rest
            # start every line afresh, which costs them multi-line constructs.
            stack = lexer.__dict__.pop("_saved_state_stack", None)
        self.setCurrentBlockState(-1 if stack is None else self._state_id(stack))

    def set_style(self, name: str) -> None:
        """Switch to another Pygments style and recolor the document."""
        self._style = get_style_by_name(name)
        self._formats.clear()
        self.rehighlight()

    def _follow_color_scheme(self, scheme: Qt.ColorScheme) -> None:
        self.set_style(self._style_name(scheme))

    @staticmethod
    def _style_name(scheme: Qt.ColorScheme) -> str:
        return DARK_STYLE if scheme == Qt.ColorScheme.Dark else LIGHT_STYLE

    def _state_id(self, stack: tuple[str, ...]) -> int:
        if stack not in self._state_ids:
            self._state_ids[stack] = len(self._stacks)
            self._stacks.append(stack)
        return self._state_ids[stack]

    def _format(self, token: _TokenType) -> QTextCharFormat:
        """The character format the current style gives a token type."""
        if token not in self._formats:
            # Styles only know the standard token types. Lexers also invent
            # their own subtypes, which take the style of their nearest
            # standard ancestor.
            known = token
            while not self._style.styles_token(known):
                known = known.parent
            style = self._style.style_for_token(known)
            result = QTextCharFormat()
            if style["color"]:
                result.setForeground(QColor(f"#{style['color']}"))
            if style["bgcolor"]:
                result.setBackground(QColor(f"#{style['bgcolor']}"))
            if style["bold"]:
                result.setFontWeight(QFont.Weight.Bold)
            if style["italic"]:
                result.setFontItalic(True)
            if style["underline"]:
                result.setFontUnderline(True)
            self._formats[token] = result
        return self._formats[token]
