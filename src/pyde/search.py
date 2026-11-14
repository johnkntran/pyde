"""Searching the text of every file in a folder, for Find in Files."""

import re
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from pyde.file_list import list_files

# A search stops once it has found this many lines. Past that, the search
# wants narrowing more than its results want reading.
MAX_MATCHES = 5_000
# Larger files are passed over: they are data, not something written by hand.
MAX_FILE_BYTES = 5_000_000
# How much of a line is shown with a match, and how much of that comes before
# the match when it is far along a long line.
MAX_SHOWN = 240
SHOWN_BEFORE = 40
# What ends a line, which is whatever the editor starts a new one at.
_LINE_END = re.compile("\r\n|[\n\r\u2029]")


@dataclass(frozen=True)
class Match:
    """A line of a file that contains the text searched for."""

    # Which line, counted from 1 as the editor's line numbers are.
    line: int
    # Where in the line the text first occurs, counted from 0.
    column: int
    # The line as the results show it: without its indentation, and cut down
    # to the part around the match if it is long.
    text: str


def compile_query(query: str, match_case: bool) -> re.Pattern[str]:
    """A pattern that finds the query as plain text, not as an expression."""
    return re.compile(re.escape(query), 0 if match_case else re.IGNORECASE)


def find_in_file(path: Path, pattern: re.Pattern[str]) -> list[Match]:
    """The lines of a file that the pattern is found in.

    There are none in a file the editor could not open either: one that cannot
    be read, or is not UTF-8 text.
    """
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        data = path.read_bytes()
    except OSError:
        return []
    # A zero byte is the usual sign of a binary file, as it is for Git.
    if b"\0" in data:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    if not pattern.search(text):
        return []

    matches = []
    for number, line in enumerate(_LINE_END.split(text), start=1):
        found = pattern.search(line)
        if found:
            matches.append(Match(number, found.start(), _shown(line, found.start())))
    return matches


def _shown(line: str, column: int) -> str:
    """The part of a line to show for a match that starts at `column`."""
    start = min(len(line) - len(line.lstrip()), column)
    lead = ""
    if column - start > MAX_SHOWN // 2:
        start = column - SHOWN_BEFORE
        lead = "…"
    # A tab would be drawn as wide as the list pleases; a space is predictable.
    return lead + line[start : start + MAX_SHOWN].rstrip().replace("\t", " ")


class Searcher(QObject):
    """Searches a folder on a thread of its own, one search at a time.

    Reading thousands of files takes a moment, and the window must not freeze
    meanwhile. Results arrive a file at a time, as they are found.
    """

    # A file with matches: its path relative to the folder, with "/" between
    # folders, and its list of matches.
    found = Signal(str, object)
    # The search is over. True if it stopped early, at MAX_MATCHES.
    finished = Signal(bool)

    # From the searching thread to the window's thread, each with the search
    # it belongs to.
    _was_found = Signal(object, str, object)
    _has_finished = Signal(object, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Set to stop the search in progress. None when there is none.
        self._stop: threading.Event | None = None
        self._was_found.connect(self._pass_on)
        self._has_finished.connect(self._finish)

    @property
    def running(self) -> bool:
        return self._stop is not None

    def start(self, folder: Path, pattern: re.Pattern[str]) -> None:
        """Search the folder's files, in place of any search still going."""
        self.cancel()
        self._stop = stop = threading.Event()
        threading.Thread(
            target=self._search, args=(stop, folder, pattern), daemon=True
        ).start()

    def cancel(self) -> None:
        """Abandon the search in progress. Nothing more is heard from it."""
        if self._stop is not None:
            self._stop.set()
            self._stop = None

    def _search(
        self, stop: threading.Event, folder: Path, pattern: re.Pattern[str]
    ) -> None:
        """Do the search. Runs on its own thread.

        It checks that it has not been cancelled before it announces anything,
        and not only to save work: a cancelled search may have outlived the
        window it belonged to, and then there is nothing left to announce to.
        """
        count = 0
        for relative_path in list_files(folder):
            matches = find_in_file(folder / relative_path, pattern)
            if stop.is_set():
                return
            matches = matches[: MAX_MATCHES - count]
            if matches:
                count += len(matches)
                self._was_found.emit(stop, relative_path, matches)
                if count == MAX_MATCHES:
                    break
        if not stop.is_set():
            self._has_finished.emit(stop, count == MAX_MATCHES)

    def _pass_on(
        self, stop: threading.Event, relative_path: str, matches: list
    ) -> None:
        # Results still arriving from a search that was replaced are dropped.
        if stop is self._stop:
            self.found.emit(relative_path, matches)

    def _finish(self, stop: threading.Event, stopped_early: bool) -> None:
        if stop is self._stop:
            self._stop = None
            self.finished.emit(stopped_early)
