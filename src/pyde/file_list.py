"""Listing the files of a folder, for Go to File."""

import os
import subprocess
from pathlib import Path

# Folders a plain walk does not descend into. Git's own listing does not need
# this, because it follows .gitignore.
SKIPPED_FOLDERS = {".git", "node_modules", "__pycache__", ".venv"}
SKIPPED_FILES = {".DS_Store"}
# A plain walk stops here, so that opening a huge folder that is not a
# repository cannot hang the app.
MAX_WALKED_FILES = 20_000
GIT_TIMEOUT_SECONDS = 10


def list_files(folder: Path) -> list[str]:
    """The files under a folder, as sorted paths relative to it.

    The paths use "/" between folders on every system, as Git's do.

    In a Git repository these are the files Git tracks, plus the new ones it
    does not ignore. Anywhere else, or if Git cannot be run, they are whatever
    a walk of the folder finds outside the usual clutter.
    """
    listing = [
        "git",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    ]
    try:
        result = subprocess.run(
            listing,
            cwd=folder,
            capture_output=True,
            text=True,
            check=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return _walk(folder)
    return sorted(path for path in result.stdout.split("\0") if path)


def _walk(folder: Path) -> list[str]:
    paths = []
    for parent, folders, files in os.walk(folder):
        folders[:] = sorted(set(folders) - SKIPPED_FOLDERS)
        for name in files:
            if name not in SKIPPED_FILES:
                paths.append(Path(parent, name).relative_to(folder).as_posix())
        if len(paths) >= MAX_WALKED_FILES:
            break
    return sorted(paths)
