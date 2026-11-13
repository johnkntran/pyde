import os

import pytest

# Keep windows off the screen while testing. This has to be set before Qt loads.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    # QtWebEngine has to be imported before the QApplication is created.
    from PySide6.QtWidgets import QApplication

    import pyde.main_window  # noqa: F401

    return QApplication.instance() or QApplication([])
