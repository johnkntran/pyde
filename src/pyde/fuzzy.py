"""Fuzzy matching for the palette: which candidates a query matches, best first.

A candidate matches when it contains the query's characters in order, ignoring
case. Matches score higher when the characters sit together, fall in the file
name rather than its folders, and land on the starts of words. A query of
several words matches a candidate that matches every word.
"""

from collections.abc import Sequence

# Characters that separate the words of a path.
_SEPARATORS = "/_-. "

# What a matched character earns.
_CONSECUTIVE = 5.0  # It directly follows the previous matched character.
_NAME_START = 8.0  # It is the first character of the file name.
_WORD_START = 4.0  # It starts some other word.
_IN_NAME = 2.0  # It is in the file name, not in a folder.
# What a match loses.
_GAP = 0.5  # Per unmatched character between the first and last matched ones.
_LENGTH = 0.02  # Per character of the candidate, so that shorter paths win ties.


def rank(query: str, candidates: Sequence[str], limit: int) -> list[str]:
    """The candidates that match the query, best first, at most `limit` of them.

    An empty query matches everything, in the order given.
    """
    words = query.lower().split()
    if not words:
        return list(candidates[:limit])

    scored = []
    for candidate in candidates:
        lower = candidate.lower()
        name_start = lower.rfind("/") + 1
        total = 0.0
        for word in words:
            score = _score(word, candidate, lower, name_start)
            if score is None:
                break
            total += score
        else:
            scored.append((-total, candidate))
    scored.sort()
    return [candidate for _, candidate in scored[:limit]]


def _score(word: str, text: str, lower: str, name_start: int) -> float | None:
    """How well one word of the query matches; None if it does not."""
    positions = _match(word, lower, name_start)
    if positions is None:
        return None

    score = -_LENGTH * len(text)
    score -= _GAP * (positions[-1] - positions[0] + 1 - len(positions))
    previous = None
    for position in positions:
        if previous is not None and position == previous + 1:
            score += _CONSECUTIVE
        if position == name_start:
            score += _NAME_START
        elif position > 0 and _starts_word(text, position):
            score += _WORD_START
        if position >= name_start:
            score += _IN_NAME
        previous = position
    return score


def _match(word: str, lower: str, name_start: int) -> Sequence[int] | None:
    """Where in the text the word's characters are taken to match."""
    # The word appearing whole beats any scattered match. Look in the file
    # name first, then for the occurrence nearest to it.
    start = lower.find(word, name_start)
    if start < 0:
        start = lower.rfind(word)
    if start >= 0:
        return range(start, start + len(word))
    return _scattered(word, lower, name_start) or _scattered(word, lower, 0)


def _scattered(word: str, lower: str, start: int) -> list[int] | None:
    """The earliest position of each character, in order, from `start` on."""
    positions = []
    for character in word:
        start = lower.find(character, start)
        if start < 0:
            return None
        positions.append(start)
        start += 1
    return positions


def _starts_word(text: str, position: int) -> bool:
    before, character = text[position - 1], text[position]
    return before in _SEPARATORS or (character.isupper() and before.islower())
