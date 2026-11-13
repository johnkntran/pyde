import os
import time

import pytest

# Keep windows off the screen while testing. This has to be set before Qt loads.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    # QtWebEngine has to be imported before the QApplication is created.
    from PySide6.QtWidgets import QApplication

    import pyde.main_window  # noqa: F401

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path):
    """A main window whose settings live in a temporary folder."""
    from pyde.main_window import MainWindow

    window = MainWindow(config_dir=tmp_path)
    yield window
    window.close()


@pytest.fixture
def wait_until(qapp):
    """Run the Qt event loop until a condition holds, failing after a timeout."""
    from PySide6.QtTest import QTest

    def wait_until(condition, timeout=5.0):
        deadline = time.monotonic() + timeout
        while not condition():
            assert time.monotonic() < deadline, "timed out waiting for the condition"
            QTest.qWait(20)

    return wait_until
