import subprocess
import sys
from importlib.metadata import version


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
