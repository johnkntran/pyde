import pytest

from pyde.fuzzy import rank

FILES = [
    ".github/workflows/ci.yml",
    "README.md",
    "pyproject.toml",
    "src/pyde/__main__.py",
    "src/pyde/editor.py",
    "src/pyde/highlighter.py",
    "src/pyde/keybindings.py",
    "src/pyde/main_window.py",
    "src/pyde/tomorrow.py",
    "tests/test_editor.py",
    "tests/test_highlighter.py",
    "tests/test_keybindings.py",
    "tests/test_main_window.py",
]


def best(query, count=1):
    return rank(query, FILES, count)


def test_an_empty_query_lists_the_candidates_in_their_own_order():
    assert rank("", FILES, 3) == FILES[:3]
    assert rank("   ", FILES, 3) == FILES[:3]


def test_candidates_without_the_characters_in_order_are_left_out():
    assert rank("zzz", FILES, 10) == []
    # Every character of "rotide" is in editor.py, but not in that order.
    assert rank("rotide", FILES, 10) == []


def test_matching_ignores_case():
    assert best("readme") == ["README.md"]
    assert best("EDITOR") == ["src/pyde/editor.py"]


def test_no_more_than_the_limit_are_returned():
    assert len(rank("e", FILES, 4)) == 4


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        # The start of a file name beats the same text later in a name.
        ("edit", ["src/pyde/editor.py", "tests/test_editor.py"]),
        ("main", ["src/pyde/main_window.py", "src/pyde/__main__.py"]),
        # Initials: the starts of words beat letters buried inside them.
        ("mw", ["src/pyde/main_window.py", "tests/test_main_window.py"]),
        ("tk", ["tests/test_keybindings.py"]),
        # Parts of two words, run together.
        ("mainwin", ["src/pyde/main_window.py", "tests/test_main_window.py"]),
        # A file name beats a folder name.
        ("test", ["tests/test_editor.py"]),
        # Folders can be part of the query.
        ("pyde/ed", ["src/pyde/editor.py"]),
        ("workflows", [".github/workflows/ci.yml"]),
    ],
)
def test_the_best_matches_come_first(query, expected):
    assert best(query, len(expected)) == expected


def test_characters_together_beat_the_same_characters_scattered():
    candidates = ["src/the_other_module.py", "src/tom.py"]

    assert rank("tom", candidates, 2) == ["src/tom.py", "src/the_other_module.py"]


def test_a_shorter_path_wins_between_otherwise_equal_matches():
    candidates = ["deep/inside/folders/settings.py", "settings.py"]

    assert rank("settings", candidates, 2) == [
        "settings.py",
        "deep/inside/folders/settings.py",
    ]


def test_every_word_of_the_query_has_to_match_in_any_order():
    assert rank("test main", FILES, 10) == ["tests/test_main_window.py"]
    assert rank("main test", FILES, 10) == ["tests/test_main_window.py"]
    assert rank("high test", FILES, 10) == ["tests/test_highlighter.py"]


def test_capitals_inside_a_name_count_as_word_starts():
    # Equal in length and spacing, and the plain name sorts first, so only the
    # capitals can put the other one ahead.
    candidates = ["src/amainwindow.js", "src/xMainWindow.js"]

    assert rank("mw", candidates, 1) == ["src/xMainWindow.js"]


def test_a_word_found_whole_beats_its_letters_found_earlier_but_apart():
    # Taking the first s, e, and t of "user_settings" would scatter the match
    # and rank it below "sweet".
    candidates = ["src/sweet.py", "src/user_settings.py"]

    assert rank("set", candidates, 1) == ["src/user_settings.py"]


def test_matched_characters_close_together_beat_ones_far_apart():
    # Both match "b" at the start and "c" at a word start, are the same
    # length, and the spread-out one sorts first.
    candidates = ["b0000000_c.py", "b_c0000000.py"]

    assert rank("bc", candidates, 1) == ["b_c0000000.py"]
