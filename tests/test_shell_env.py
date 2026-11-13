import os
import subprocess

from pyde.shell_env import environment_command, parse_environment


def test_the_command_runs_the_shell_as_a_login_and_interactive_one():
    command = environment_command("/bin/zsh")

    assert command[:4] == ["/bin/zsh", "-l", "-i", "-c"]


def test_the_environment_is_read_from_a_real_shell(monkeypatch):
    monkeypatch.setenv("PYDE_TEST_VALUE", "two words = and more")

    result = subprocess.run(
        environment_command("/bin/sh"),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    environment = parse_environment(result.stdout)

    assert environment["PYDE_TEST_VALUE"] == "two words = and more"
    assert environment["HOME"] == os.environ["HOME"]


def test_what_startup_files_print_around_it_is_ignored():
    command = environment_command("/bin/sh")
    script = f"echo welcome banner; {command[-1]}; echo goodbye"

    output = subprocess.run(
        ["/bin/sh", "-c", script], capture_output=True, text=True, timeout=30
    ).stdout
    environment = parse_environment(output)

    assert "welcome banner" in output
    assert "PATH" in environment
    assert not any("banner" in name or "goodbye" in name for name in environment)


def test_values_may_span_lines():
    marked = environment_command("/bin/sh")[-1].split()[2].rstrip(";")
    output = f"{marked}A=one\ntwo\0B=three\0{marked}"

    assert parse_environment(output) == {"A": "one\ntwo", "B": "three"}


def test_output_without_the_environment_gives_nothing():
    assert parse_environment("") is None
    assert parse_environment("zsh: command not found") is None
