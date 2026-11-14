import pytest
from pygments.styles import get_all_styles

from pyde import highlighter, jsonc
from pyde.settings import Settings


class Harness:
    """Settings that read a temporary file, and the messages they have sent."""

    def __init__(self, folder):
        self.path = folder / "settings.json"
        self.settings = Settings(self.path)
        self.messages = []
        self.settings.message.connect(self.messages.append)

    def load(self, text):
        self.path.write_text(text)
        self.settings.load()

    @property
    def styles(self):
        return highlighter.styles.light, highlighter.styles.dark


@pytest.fixture
def harness(qapp, tmp_path):
    return Harness(tmp_path)


def test_without_a_file_the_styles_are_the_ones_pyde_ships_with(harness):
    harness.settings.load()

    assert harness.styles == ("default", "github-dark")
    assert harness.messages == []


def test_the_theme_names_a_style_for_each_mode(harness):
    harness.load('{"theme": {"light": "xcode", "dark": "monokai"}}')

    assert harness.styles == ("xcode", "monokai")
    assert harness.messages == []


def test_a_mode_left_out_keeps_its_usual_style(harness):
    harness.load('{"theme": {"dark": "dracula"}}')

    assert harness.styles == ("default", "dracula")
    assert harness.messages == []


def test_the_file_may_contain_comments_and_trailing_commas(harness):
    harness.load('// mine\n{\n  "theme": { "dark": "nord", }, // cooler\n}\n')

    assert harness.styles == ("default", "nord")
    assert harness.messages == []


def test_an_unknown_style_is_reported_and_the_rest_still_applies(harness):
    harness.load('{"theme": {"light": "no-such-style", "dark": "monokai"}}')

    assert harness.styles == ("default", "monokai")
    assert harness.messages == [
        "settings.json: unknown style 'no-such-style' for light mode"
    ]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('{"theme": {"light": 5}}', "unknown style 5 for light mode"),
        ('{"theme": {"dim": "monokai"}}', "unknown theme mode 'dim'"),
        ('{"theme": "monokai"}', '"theme" must be an object'),
        ('{"font": "Menlo"}', "unknown setting 'font'"),
    ],
)
def test_other_mistakes_are_reported_and_change_nothing(harness, text, problem):
    harness.load(text)

    assert harness.styles == ("default", "github-dark")
    assert len(harness.messages) == 1
    assert problem in harness.messages[0]


@pytest.mark.parametrize("broken", ['{"theme": ', '["monokai"]'])
def test_an_unreadable_file_is_reported_and_current_settings_are_kept(harness, broken):
    harness.load('{"theme": {"dark": "monokai"}}')

    harness.load(broken)

    assert harness.styles == ("default", "monokai")
    assert len(harness.messages) == 1
    assert harness.messages[0].startswith("settings.json: ")


def test_removing_the_theme_restores_the_usual_styles(harness):
    harness.load('{"theme": {"light": "xcode", "dark": "monokai"}}')

    harness.load("{}")

    assert harness.styles == ("default", "github-dark")


def test_saving_the_file_reapplies_it(harness, wait_until):
    harness.load('{"theme": {"dark": "monokai"}}')

    harness.path.write_text('{"theme": {"dark": "dracula"}}')

    wait_until(lambda: harness.styles == ("default", "dracula"))
    assert harness.messages == ["Settings reloaded"]


def test_ensure_user_file_creates_a_template_that_changes_nothing(qapp, tmp_path):
    harness = Harness(tmp_path / "not-created-yet")

    path = harness.settings.ensure_user_file()
    text = path.read_text()

    assert jsonc.loads(text) == {}
    assert harness.styles == ("default", "github-dark")
    assert harness.messages == []
    # It lists every style there is to choose from, each name in one piece.
    lines = [line.removeprefix("  //").strip() for line in text.splitlines()]
    start = lines.index("The styles to choose from:") + 1
    listed = " ".join(lines[start : lines.index("", start)])
    assert listed.split(", ") == sorted(get_all_styles())
    # And it shows the setting itself, ready to uncomment.
    assert '// "theme": { "light": "default", "dark": "github-dark" }' in text
    assert max(len(line) for line in text.splitlines()) <= 80


def test_ensure_user_file_leaves_an_existing_file_alone(harness):
    harness.load('{"theme": {"dark": "monokai"}}')

    path = harness.settings.ensure_user_file()

    assert path.read_text() == '{"theme": {"dark": "monokai"}}'
