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


@pytest.fixture(autouse=True)
def no_unexpected_dialogs(monkeypatch):
    """Fail, rather than hang, if a dialog opens that the test did not answer.

    A test that expects a dialog replaces the same function with its answer.
    """
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    def unexpected(*args, **kwargs):
        raise AssertionError("a dialog opened that the test did not expect")

    monkeypatch.setattr(QMessageBox, "warning", unexpected)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", unexpected)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", unexpected)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", unexpected)


@pytest.fixture
def window(qapp, tmp_path):
    """A main window whose settings live in a temporary folder."""
    from pyde.main_window import MainWindow

    window = MainWindow(config_dir=tmp_path / "config")
    yield window
    # Closing would otherwise ask about any changes the test left unsaved.
    for editor in window.editors():
        editor.document().setModified(False)
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


@pytest.fixture
def color_at():
    """Look up the text color the syntax highlighter gave a character."""
    from PySide6.QtCore import Qt

    def color_at(document, line, column):
        """The color as "#rrggbb", or None where the text has the default color."""
        block = document.findBlockByNumber(line)
        for span in block.layout().formats():
            if span.start <= column < span.start + span.length:
                brush = span.format.foreground()
                if brush.style() != Qt.BrushStyle.NoBrush:
                    return brush.color().name()
        return None

    return color_at
