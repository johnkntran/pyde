import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QMessageBox

from pyde.keybindings import to_key_sequence
from pyde.main_window import MainWindow

BUTTON = QMessageBox.StandardButton


def show(window, wait_until):
    window.show()
    window.activateWindow()
    wait_until(window.isActiveWindow)


def press(target, key):
    QTest.keySequence(target, to_key_sequence(key))


def run(window, command_id):
    window.commands[command_id].action.trigger()


def tab_titles(window):
    return [window.tabs.tabText(index) for index in range(window.tabs.count())]


def answer_unsaved_changes(monkeypatch, button):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: button)


@pytest.fixture
def file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello\n")
    return path


# Layout


def test_a_new_window_has_no_folder_tabs_or_problems(window):
    assert window.windowTitle() == "Pyde"
    assert window.tabs.count() == 0
    assert window.file_tree_dock.isHidden()
    # Two default keys clashing would be reported here.
    assert window.statusBar().currentMessage() == ""


def test_the_terminal_dock_hosts_a_web_view_at_the_bottom(window):
    assert isinstance(window.terminal_dock.widget(), QWebEngineView)
    assert (
        window.dockWidgetArea(window.terminal_dock)
        == Qt.DockWidgetArea.BottomDockWidgetArea
    )


def test_every_default_key_is_valid(window):
    for command in window.commands:
        if command.default_key:
            to_key_sequence(command.default_key)


# Keyboard shortcuts


def test_pressing_the_default_key_toggles_the_terminal(window, wait_until):
    show(window, wait_until)
    assert window.terminal_dock.isVisible()

    press(window, "ctrl+`")
    assert not window.terminal_dock.isVisible()

    press(window, "ctrl+`")
    assert window.terminal_dock.isVisible()


def test_the_terminal_key_works_while_the_web_view_has_focus(window, wait_until):
    show(window, wait_until)
    window.terminal_view.setFocus()
    wait_until(lambda: window.focusWidget() is not None)

    press(window.focusWidget(), "ctrl+`")

    assert not window.terminal_dock.isVisible()


def test_the_keybindings_file_rebinds_a_command(qapp, tmp_path, wait_until):
    (tmp_path / "keybindings.json").write_text('{"view.toggleTerminal": "cmd+j"}')
    window = MainWindow(config_dir=tmp_path)
    show(window, wait_until)

    press(window, "ctrl+`")
    assert window.terminal_dock.isVisible()

    press(window, "cmd+j")
    assert not window.terminal_dock.isVisible()

    window.close()


def test_a_problem_in_the_keybindings_file_shows_in_the_status_bar(qapp, tmp_path):
    (tmp_path / "keybindings.json").write_text('{"view.toggleTerminal": "cmd+nope"}')

    window = MainWindow(config_dir=tmp_path)

    assert "cmd+nope" in window.statusBar().currentMessage()
    window.close()


def test_the_keyboard_shortcuts_file_opens_in_a_tab(window, tmp_path):
    run(window, "preferences.openKeybindings")

    assert tab_titles(window) == ["keybindings.json"]
    assert window.current_editor().path == tmp_path / "config" / "keybindings.json"
    assert window.current_editor().path.exists()


def test_the_default_shortcuts_open_read_only_and_refresh_when_reopened(window):
    run(window, "preferences.openDefaultKeybindings")
    editor = window.current_editor()
    assert editor.isReadOnly()
    assert '"file.save": "cmd+s", // Save' in editor.toPlainText()

    editor.path.write_text("stale")
    run(window, "preferences.openDefaultKeybindings")

    assert tab_titles(window) == ["default-keybindings.json"]
    assert '"file.save": "cmd+s", // Save' in editor.toPlainText()


# Opening files and folders


def test_opening_a_file_shows_it_in_a_tab(window, file):
    editor = window.open_file(file)

    assert tab_titles(window) == ["notes.txt"]
    assert window.current_editor() is editor
    assert editor.toPlainText() == "hello\n"
    assert window.tabs.tabToolTip(0) == str(file)


def test_the_placeholder_shows_only_while_no_file_is_open(window, file):
    assert not window.tabs.isVisibleTo(window)

    window.open_file(file)
    assert window.tabs.isVisibleTo(window)

    window.close_tab()
    assert not window.tabs.isVisibleTo(window)


def test_opening_a_file_twice_reuses_its_tab(window, file, tmp_path):
    first = window.open_file(file)
    (tmp_path / "other.txt").write_text("")
    window.open_file(tmp_path / "other.txt")

    again = window.open_file(file)

    assert again is first
    assert tab_titles(window) == ["notes.txt", "other.txt"]
    assert window.current_editor() is first


@pytest.mark.parametrize(
    ("name", "content", "reason"),
    [
        ("image.png", b"\x89PNG\xff\xfe", "not UTF-8 text"),
        ("missing.txt", None, "No such file or directory"),
    ],
)
def test_a_file_that_cannot_be_opened_is_reported(
    window, tmp_path, name, content, reason
):
    path = tmp_path / name
    if content is not None:
        path.write_bytes(content)

    assert window.open_file(path) is None

    assert window.tabs.count() == 0
    assert window.statusBar().currentMessage() == f"Cannot open {name}: {reason}"


def test_opening_a_folder_shows_it_in_the_file_tree(window, tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()

    window.open_folder(folder)

    assert window.folder == folder
    assert window.windowTitle() == "project — Pyde"
    assert not window.file_tree_dock.isHidden()


def test_open_path_tells_folders_from_files(window, file, tmp_path):
    window.open_path(tmp_path)
    window.open_path(file)

    assert window.folder == tmp_path
    assert tab_titles(window) == ["notes.txt"]


def test_choosing_a_file_in_the_tree_opens_it(window, file):
    window.file_tree.file_activated.emit(file)

    assert tab_titles(window) == ["notes.txt"]


def test_open_file_and_open_folder_use_the_dialog_choice(
    window, file, tmp_path, monkeypatch
):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(file), ""))
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path)
    )

    run(window, "file.open")
    run(window, "file.openFolder")

    assert tab_titles(window) == ["notes.txt"]
    assert window.folder == tmp_path


def test_canceling_the_open_dialogs_changes_nothing(window, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: "")

    run(window, "file.open")
    run(window, "file.openFolder")

    assert window.tabs.count() == 0
    assert window.folder is None


# Editing and saving


def test_editing_marks_the_tab_until_the_file_is_saved(window, file):
    editor = window.open_file(file)

    editor.appendPlainText("more")
    assert tab_titles(window) == ["notes.txt •"]

    assert window.save()
    assert tab_titles(window) == ["notes.txt"]
    assert file.read_text() == "hello\n\nmore"


def test_pressing_the_save_key_saves_from_inside_the_editor(window, file, wait_until):
    editor = window.open_file(file)
    show(window, wait_until)
    editor.appendPlainText("more")

    press(editor, "cmd+s")

    assert file.read_text() == "hello\n\nmore"


def test_saving_a_new_file_asks_where_to_put_it(window, tmp_path, monkeypatch):
    target = tmp_path / "new.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    run(window, "file.new")
    assert tab_titles(window) == ["Untitled"]
    window.current_editor().insertPlainText("fresh")

    assert window.save()

    assert target.read_text() == "fresh"
    assert tab_titles(window) == ["new.txt"]


def test_save_as_writes_a_copy_and_switches_the_tab_to_it(
    window, file, tmp_path, monkeypatch
):
    copy = tmp_path / "copy.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(copy), ""))
    window.open_file(file)

    run(window, "file.saveAs")

    assert copy.read_text() == "hello\n"
    assert tab_titles(window) == ["copy.txt"]


def test_canceling_the_save_dialog_saves_nothing(window, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    window.new_file()
    window.current_editor().insertPlainText("fresh")

    assert not window.save()

    assert tab_titles(window) == ["Untitled •"]


def test_a_failed_save_is_reported_and_the_tab_stays_modified(window, file, tmp_path):
    editor = window.open_file(file)
    editor.appendPlainText("more")
    editor.path = tmp_path / "no-such-folder" / "notes.txt"

    assert not window.save()

    assert window.statusBar().currentMessage() == (
        "Cannot save notes.txt: No such file or directory"
    )
    assert tab_titles(window) == ["notes.txt •"]


# Closing


def test_closing_an_unmodified_tab_asks_nothing(window, file):
    window.open_file(file)

    assert window.close_tab()

    assert window.tabs.count() == 0


def test_closing_a_modified_tab_can_save_first(window, file, monkeypatch):
    answer_unsaved_changes(monkeypatch, BUTTON.Save)
    window.open_file(file).appendPlainText("more")

    assert window.close_tab()

    assert window.tabs.count() == 0
    assert file.read_text() == "hello\n\nmore"


def test_closing_a_modified_tab_can_discard_the_changes(window, file, monkeypatch):
    answer_unsaved_changes(monkeypatch, BUTTON.Discard)
    window.open_file(file).appendPlainText("more")

    assert window.close_tab()

    assert window.tabs.count() == 0
    assert file.read_text() == "hello\n"


def test_closing_a_modified_tab_can_be_canceled(window, file, monkeypatch):
    answer_unsaved_changes(monkeypatch, BUTTON.Cancel)
    window.open_file(file).appendPlainText("more")

    assert not window.close_tab()

    assert tab_titles(window) == ["notes.txt •"]


def test_the_close_button_on_a_tab_closes_that_tab(window, file, tmp_path):
    (tmp_path / "other.txt").write_text("")
    window.open_file(file)
    window.open_file(tmp_path / "other.txt")

    window.tabs.tabCloseRequested.emit(0)

    assert tab_titles(window) == ["other.txt"]


def test_closing_the_window_with_unsaved_changes_can_be_canceled(
    window, file, monkeypatch, wait_until
):
    answer_unsaved_changes(monkeypatch, BUTTON.Cancel)
    window.open_file(file).appendPlainText("more")
    show(window, wait_until)

    assert not window.close()

    assert window.isVisible()


def test_close_tab_with_no_tabs_closes_the_window(window, wait_until):
    show(window, wait_until)

    press(window, "cmd+w")

    assert not window.isVisible()


# Tabs, panels, and find


def test_the_tab_commands_cycle_through_the_tabs(window, tmp_path):
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text("")
        window.open_file(tmp_path / name)
    assert window.tabs.currentIndex() == 2

    run(window, "view.nextTab")
    assert window.tabs.currentIndex() == 0

    run(window, "view.previousTab")
    run(window, "view.previousTab")
    assert window.tabs.currentIndex() == 1


def test_the_file_tree_can_be_toggled(window, tmp_path, wait_until):
    window.open_folder(tmp_path)
    show(window, wait_until)
    assert window.file_tree_dock.isVisible()

    press(window, "cmd+b")

    assert not window.file_tree_dock.isVisible()


def test_find_searches_the_current_file_and_escape_dismisses_it(
    window, file, wait_until
):
    editor = window.open_file(file)
    show(window, wait_until)

    press(editor, "cmd+f")
    assert window.find_bar.isVisible()
    QTest.keyClicks(window.find_bar.find_field, "ell")
    QTest.keyClick(window.find_bar.find_field, Qt.Key.Key_Return)
    assert editor.textCursor().selectedText() == "ell"

    QTest.keyClick(window.find_bar.find_field, Qt.Key.Key_Escape)
    assert not window.find_bar.isVisible()


def test_find_follows_the_current_tab(window, file, tmp_path):
    other = tmp_path / "other.txt"
    other.write_text("yellow\n")
    first = window.open_file(file)
    second = window.open_file(other)
    window.find_bar.find_field.setText("ell")

    run(window, "edit.findNext")
    window.tabs.setCurrentWidget(first)
    run(window, "edit.findNext")

    assert second.textCursor().selectedText() == "ell"
    assert first.textCursor().selectedText() == "ell"
