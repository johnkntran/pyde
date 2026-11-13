import subprocess
import sys
from importlib.metadata import version

from pygments.util import ClassNotFound

import pyde.app


def run_pyde(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pyde", *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_version_flag_prints_the_project_version():
    result = run_pyde("--version")

    assert result.returncode == 0
    assert result.stdout.strip() == f"pyde {version('pyde')}"


def test_smoke_test_loads_the_web_view_and_exits_cleanly():
    result = run_pyde("--smoke-test")

    assert result.returncode == 0, result.stderr


def test_the_app_starts_with_a_folder_or_a_file_to_open(tmp_path):
    file = tmp_path / "notes.txt"
    file.write_text("hello\n")

    for path in (tmp_path, file):
        result = run_pyde("--smoke-test", str(path))

        assert result.returncode == 0, result.stderr


def test_the_smoke_test_finds_nothing_missing_from_a_complete_install():
    assert pyde.app._highlighting_problems() == []


def test_the_smoke_test_reports_lexers_and_styles_left_out_of_a_build(monkeypatch):
    def lexer_for(name):
        if name == "a.py":
            raise ImportError("No module named 'pygments.lexers.python'")
        return None if name == "a.md" else object()

    def get_style_by_name(name):
        raise ClassNotFound(name)

    monkeypatch.setattr(pyde.app, "lexer_for", lexer_for)
    monkeypatch.setattr(pyde.app, "get_style_by_name", get_style_by_name)

    assert pyde.app._highlighting_problems() == [
        "no syntax highlighting for a.py",
        "no syntax highlighting for a.md",
        "the default color style is missing",
        "the github-dark color style is missing",
    ]
