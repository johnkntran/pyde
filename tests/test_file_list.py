import subprocess

import pytest

from pyde import file_list
from pyde.file_list import list_files


def git(folder, *args):
    subprocess.run(["git", *args], cwd=folder, check=True, capture_output=True)


def write(folder, *paths):
    for path in paths:
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_text("")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init")
    return tmp_path


def test_a_repository_lists_tracked_and_new_files_but_not_ignored_ones(repo):
    write(repo, "tracked.py", "src/new.py", "build/output.o", "notes.log")
    (repo / ".gitignore").write_text("build/\n*.log\n")
    git(repo, "add", "tracked.py")

    assert list_files(repo) == [".gitignore", "src/new.py", "tracked.py"]


def test_a_folder_inside_a_repository_lists_paths_relative_to_itself(repo):
    write(repo, "top.py", "app/views.py", "app/templates/index.html")

    assert list_files(repo / "app") == ["templates/index.html", "views.py"]


def test_names_with_spaces_and_accents_come_through_intact(repo):
    write(repo, "my notes.txt", "café/menü.txt")

    assert list_files(repo) == ["café/menü.txt", "my notes.txt"]


def test_outside_a_repository_the_folder_is_walked_skipping_clutter(tmp_path):
    write(
        tmp_path,
        "app.py",
        "pkg/module.py",
        ".env.example",
        ".DS_Store",
        "node_modules/lib/index.js",
        "pkg/__pycache__/module.pyc",
        ".venv/bin/python",
    )

    assert list_files(tmp_path) == [".env.example", "app.py", "pkg/module.py"]


def test_the_folder_is_walked_when_git_cannot_be_run(repo, monkeypatch):
    write(repo, "app.py", "build/output.o")
    (repo / ".gitignore").write_text("build/\n")

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)

    # Without Git there is nothing to say that build/ is ignored.
    assert list_files(repo) == [".gitignore", "app.py", "build/output.o"]


def test_a_walk_stops_at_the_file_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(file_list, "MAX_WALKED_FILES", 3)
    write(tmp_path, *(f"folder{n}/file.txt" for n in range(10)))

    assert len(list_files(tmp_path)) == 3
