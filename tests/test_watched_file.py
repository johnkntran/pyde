import os

import pytest
from PySide6.QtTest import QTest

from pyde.watched_file import WatchedFile


class Harness:
    """A watched file, and how many times it has said it changed."""

    def __init__(self, path):
        self.path = path
        self.file = WatchedFile(path)
        self.changes = 0
        self.file.changed.connect(self._count)

    def _count(self):
        self.changes += 1


@pytest.fixture
def harness(qapp, tmp_path):
    return Harness(tmp_path / "settings.json")


def test_a_missing_file_reads_as_nothing(harness):
    assert harness.file.read() is None


def test_an_existing_file_reads_as_its_text(harness):
    harness.path.write_text("first")

    assert harness.file.read() == "first"
    assert harness.changes == 0


def test_saving_the_file_announces_a_change(harness, wait_until):
    harness.path.write_text("first")
    harness.file.read()

    harness.path.write_text("second")

    wait_until(lambda: harness.changes == 1)
    assert harness.file.read() == "second"


def test_a_file_created_later_announces_a_change(harness, wait_until):
    harness.file.read()

    harness.path.write_text("created")

    wait_until(lambda: harness.changes == 1)


def test_a_file_replaced_by_another_keeps_being_watched(harness, wait_until):
    harness.path.write_text("0")
    harness.file.read()

    # Many editors save by writing a new file and renaming it over the old one.
    for count in (1, 2):
        replacement = harness.path.with_suffix(".tmp")
        replacement.write_text(str(count))
        os.replace(replacement, harness.path)
        wait_until(lambda count=count: harness.changes == count)
        assert harness.file.read() == str(count)


def test_deleting_the_file_announces_a_change(harness, wait_until):
    harness.path.write_text("first")
    harness.file.read()

    harness.path.unlink()

    wait_until(lambda: harness.changes == 1)
    assert harness.file.read() is None


def test_other_files_in_the_folder_and_unchanged_saves_announce_nothing(
    harness, wait_until
):
    harness.path.write_text("same")
    harness.file.read()

    (harness.path.parent / "other.json").write_text("{}")
    harness.path.write_text("same")
    # Time for those to be noticed, then a real change to prove they were.
    QTest.qWait(700)
    assert harness.changes == 0
    harness.path.write_text("different")

    wait_until(lambda: harness.changes == 1)


def test_a_change_is_announced_once_until_the_file_is_read_again(harness, wait_until):
    harness.path.write_text("first")
    harness.file.read()

    harness.path.write_text("second")
    wait_until(lambda: harness.changes == 1)
    harness.path.write_text("third")

    # Nobody has read "second" yet, so "third" is still a change from "first".
    wait_until(lambda: harness.changes == 2)
