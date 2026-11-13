"""JSON with comments and trailing commas, as hand-edited config files use."""

import json
import re
from typing import Any

# Each pattern also matches whole strings, so that comment markers and commas
# inside a string are skipped over rather than treated as syntax.
_STRING = r'"(?:\\.|[^"\\])*"'
_COMMENT = re.compile(rf"{_STRING}|//[^\n]*|/\*.*?\*/", re.DOTALL)
_TRAILING_COMMA = re.compile(rf"{_STRING}|,(?=\s*[}}\]])")


def loads(text: str) -> Any:
    """Parse JSON that may contain // and /* */ comments and trailing commas.

    Raises ValueError if what remains is not valid JSON.
    """

    def blank(match: re.Match[str]) -> str:
        token = match.group()
        if token.startswith('"'):
            return token
        # Keep line breaks so that line numbers in error messages stay right.
        return re.sub(r"[^\n]", " ", token)

    text = _COMMENT.sub(blank, text)
    text = _TRAILING_COMMA.sub(blank, text)
    return json.loads(text)
