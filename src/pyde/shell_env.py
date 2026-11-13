"""The environment the user's shell sets up, for commands Pyde runs itself.

An app launched from the Finder starts with a bare environment: its PATH has
only the system folders, so tools such as docker, which a shell profile adds,
are not found. The fix is to ask the user's shell what its environment is.
"""

# Printed either side of the environment, to tell it from anything the
# shell's startup files print.
_MARK = "__PYDE_ENVIRONMENT__"


def environment_command(shell: str) -> list[str]:
    """A command that prints the environment of a new login shell.

    The shell is run as both a login and an interactive one, so that it reads
    every startup file a terminal would: tools add themselves to PATH in
    either kind.
    """
    script = f"printf %s {_MARK}; /usr/bin/env -0; printf %s {_MARK}"
    return [shell, "-l", "-i", "-c", script]


def parse_environment(output: str) -> dict[str, str] | None:
    """The environment from that command's output, or None if it is not there."""
    parts = output.split(_MARK)
    if len(parts) < 3:
        return None
    entries = (entry.partition("=") for entry in parts[1].split("\0") if entry)
    return {name: value for name, _, value in entries}
