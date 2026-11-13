"""A program running on a pseudo-terminal, driven from the Qt event loop.

macOS provides pseudo-terminals itself; on Windows the pywinpty library does.
Each has its own implementation, with the same signals and methods, and this
module offers whichever suits the system as `PtySession`.
"""

import sys

if sys.platform == "win32":
    from pyde.pty_windows import PtySession
else:
    from pyde.pty_posix import PtySession

__all__ = ["PtySession"]
