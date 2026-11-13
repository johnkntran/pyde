"""The main application window."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pyde import __version__
from pyde.commands import CommandRegistry
from pyde.devcontainer.config import (
    ConfigError,
    DevContainerConfig,
    find_config,
    load_config,
)
from pyde.devcontainer.controller import DevContainer
from pyde.editor import CodeEditor
from pyde.file_list import list_files
from pyde.file_tree import FileTree
from pyde.find_bar import FindBar
from pyde.keybindings import Keybindings
from pyde.notice_bar import NoticeBar
from pyde.palette import Palette
from pyde.settings import Settings
from pyde.terminal import TerminalView

STATUS_MESSAGE_MS = 10_000
# Appended to the tab title of a file with unsaved changes.
MODIFIED_MARK = " •"


def default_config_dir() -> Path:
    """Where the user's settings live: ~/Library/Application Support/Pyde."""
    location = QStandardPaths.StandardLocation.AppDataLocation
    return Path(QStandardPaths.writableLocation(location))


class MainWindow(QMainWindow):
    def __init__(self, config_dir: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Pyde")
        self.resize(1200, 800)
        # The folder shown in the file tree; None until one is opened.
        self.folder: Path | None = None
        # Where the user's settings, and Pyde's own working files, are kept.
        self._config_dir = config_dir or default_config_dir()
        # The open folder's dev container configuration, if it has a usable
        # one, and the dev container itself once the user has asked for it.
        self._container_config: DevContainerConfig | None = None
        self.dev_container: DevContainer | None = None
        self._in_container = False

        # The middle of the window: one tab per open file, or a placeholder
        # when there are none, with the find bar underneath.
        self.tabs = QTabWidget(documentMode=True, tabsClosable=True, movable=True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        placeholder = QLabel(f"Pyde {__version__}")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setEnabled(False)
        stack = QStackedWidget()
        stack.addWidget(placeholder)
        stack.addWidget(self.tabs)
        self.tabs.currentChanged.connect(
            lambda index: stack.setCurrentWidget(
                self.tabs if index >= 0 else placeholder
            )
        )
        self.find_bar = FindBar(self.current_editor)
        self.notice_bar = NoticeBar()
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.notice_bar)
        layout.addWidget(stack)
        layout.addWidget(self.find_bar)
        self.setCentralWidget(central)

        self.file_tree = FileTree()
        self.file_tree.file_activated.connect(self.open_file)
        self.file_tree_dock = self._add_dock(
            "Files", "files", self.file_tree, Qt.DockWidgetArea.LeftDockWidgetArea
        )
        # There is nothing to show until a folder is opened.
        self.file_tree_dock.hide()

        self.terminal_view = TerminalView()
        self.terminal_dock = self._add_dock(
            "Terminal",
            "terminal",
            self.terminal_view,
            Qt.DockWidgetArea.BottomDockWidgetArea,
        )

        # The file tree runs the full height of the window, with the terminal
        # beside it rather than underneath.
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.resizeDocks([self.file_tree_dock], [240], Qt.Orientation.Horizontal)
        # Without this the web view's size hint claims most of the window.
        self.resizeDocks([self.terminal_dock], [260], Qt.Orientation.Vertical)

        # Floats over the top of the window while it is open.
        self.palette = Palette(self)

        self.commands = CommandRegistry(self)
        self._add_commands()

        self.keybindings = Keybindings(
            self.commands, self._config_dir / "keybindings.json", parent=self
        )
        self.keybindings.message.connect(self._report)
        self.settings = Settings(self._config_dir / "settings.json", parent=self)
        self.settings.message.connect(self._report)
        # Shown at the right of the status bar while working in a container.
        self.container_label = QLabel()
        self.container_label.hide()
        self.statusBar().addPermanentWidget(self.container_label)
        self.keybindings.load()
        self.settings.load()

    def _add_dock(
        self, title: str, name: str, widget: QWidget, area: Qt.DockWidgetArea
    ) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _add_commands(self) -> None:
        find = self.find_bar
        self._add_menu(
            "File",
            ("file.new", "New File", self.new_file, "cmd+n"),
            ("file.open", "Open File…", self.pick_file, "cmd+o"),
            ("file.openFolder", "Open Folder…", self.pick_folder, "cmd+shift+o"),
            ("file.goToFile", "Go to File…", self.go_to_file, "cmd+p"),
            (
                "devcontainer.reopenInContainer",
                "Reopen in Container",
                self.reopen_in_container,
            ),
            (
                "devcontainer.reopenLocally",
                "Reopen Folder Locally",
                self.reopen_locally,
            ),
            ("devcontainer.rebuild", "Rebuild Container", self.rebuild_container),
            ("file.save", "Save", self.save, "cmd+s"),
            ("file.saveAs", "Save As…", self.save_as, "cmd+shift+s"),
            ("file.closeTab", "Close Tab", self.close_tab, "cmd+w"),
        )
        self._add_menu(
            "Edit",
            ("edit.find", "Find", find.show_find, "cmd+f"),
            ("edit.replace", "Replace", find.show_replace, "cmd+alt+f"),
            ("edit.findNext", "Find Next", find.find_next, "cmd+g"),
            ("edit.findPrevious", "Find Previous", find.find_previous, "cmd+shift+g"),
        )
        self._add_menu(
            "View",
            ("view.toggleFileTree", "Toggle File Tree", self.toggle_file_tree, "cmd+b"),
            ("view.toggleTerminal", "Toggle Terminal", self.toggle_terminal, "ctrl+`"),
            ("view.nextTab", "Next Tab", self.next_tab, "ctrl+tab"),
            ("view.previousTab", "Previous Tab", self.previous_tab, "ctrl+shift+tab"),
        )
        preferences = self._add_menu(
            "Preferences",
            ("preferences.openSettings", "Open Settings", self.open_settings, "cmd+,"),
            (
                "preferences.openKeybindings",
                "Open Keyboard Shortcuts",
                self.open_keybindings,
                "cmd+k cmd+s",
            ),
            (
                "preferences.openDefaultKeybindings",
                "Open Default Keyboard Shortcuts",
                self.open_default_keybindings,
            ),
        )
        # macOS moves actions with these roles into the application menu, and
        # hides the menu they came from once it is empty. The settings one
        # takes the place macOS reserves for an app's settings.
        settings = self.commands["preferences.openSettings"].action
        for action in preferences.actions():
            is_settings = action is settings
            action.setMenuRole(
                QAction.MenuRole.PreferencesRole
                if is_settings
                else QAction.MenuRole.ApplicationSpecificRole
            )

    def _add_menu(self, title: str, *commands: tuple) -> QMenu:
        """Add a menu of commands, each given as (id, title, callback, key)."""
        menu = self.menuBar().addMenu(title)
        for command in commands:
            menu.addAction(self.commands.register(*command))
        return menu

    # Opening

    def current_editor(self) -> CodeEditor | None:
        return self.tabs.currentWidget()

    def editors(self) -> list[CodeEditor]:
        return [self.tabs.widget(index) for index in range(self.tabs.count())]

    def open_path(self, path: Path) -> None:
        """Open a folder in the file tree, or a file in a tab."""
        if path.is_dir():
            self.open_folder(path)
        else:
            self.open_file(path)

    def open_folder(self, folder: Path) -> None:
        self._leave_container()
        self.folder = folder.resolve()
        self.file_tree.set_folder(self.folder)
        self.terminal_view.set_folder(self.folder)
        self.file_tree_dock.show()
        self._update_title()
        self._offer_container()

    def open_file(self, path: Path) -> CodeEditor | None:
        """Show a file in a tab, reusing its tab if it is already open."""
        path = path.resolve()
        for editor in self.editors():
            if editor.path == path:
                self.tabs.setCurrentWidget(editor)
                return editor

        editor = CodeEditor()
        try:
            editor.load(path)
        except (OSError, UnicodeDecodeError) as error:
            reason = error.strerror if isinstance(error, OSError) else "not UTF-8 text"
            self._report(f"Cannot open {path.name}: {reason}")
            editor.deleteLater()
            return None
        self._add_tab(editor)
        return editor

    def new_file(self) -> None:
        self._add_tab(CodeEditor())

    def pick_file(self) -> None:
        start = str(self.folder or Path.home())
        chosen, _ = QFileDialog.getOpenFileName(self, "Open File", start)
        if chosen:
            self.open_file(Path(chosen))

    def pick_folder(self) -> None:
        start = str(self.folder or Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Open Folder", start)
        if chosen:
            self.open_folder(Path(chosen))

    def go_to_file(self) -> None:
        """Pick one of the open folder's files by typing part of its name."""
        folder = self.folder
        if folder is None:
            self._report("Open a folder to use Go to File")
            return
        self.palette.open(
            list_files(folder),
            lambda relative_path: self.open_file(folder / relative_path),
            placeholder="Go to file",
        )

    def open_settings(self) -> None:
        self.open_file(self.settings.ensure_user_file())

    def open_keybindings(self) -> None:
        self.open_file(self.keybindings.ensure_user_file())

    def open_default_keybindings(self) -> None:
        editor = self.open_file(self.keybindings.write_defaults_file())
        if editor is not None:
            # The file was just rewritten, and its tab may already have been
            # open with the old text.
            editor.load(editor.path)
            editor.setReadOnly(True)

    # Saving and closing

    def save(self) -> bool:
        """Save the current file, asking where to if it is new."""
        editor = self.current_editor()
        if editor is None:
            return False
        if editor.path is None:
            return self.save_as()
        return self._write(editor, editor.path)

    def save_as(self) -> bool:
        editor = self.current_editor()
        if editor is None:
            return False
        start = str(editor.path or self.folder or Path.home())
        chosen, _ = QFileDialog.getSaveFileName(self, "Save As", start)
        return bool(chosen) and self._write(editor, Path(chosen))

    def close_tab(self, index: int | None = None) -> bool:
        """Close a tab, by default the current one. Returns whether it closed.

        With no tabs open this does nothing. It never closes the window:
        quitting is cmd+q's job.
        """
        editor = self.current_editor() if index is None else self.tabs.widget(index)
        if editor is None:
            return False
        if not self._may_close(editor):
            return False
        self.tabs.removeTab(self.tabs.indexOf(editor))
        editor.deleteLater()
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if all(self._may_close(editor) for editor in self.editors()):
            self._leave_container(quitting=True)
            self.terminal_view.shutdown()
            event.accept()
        else:
            event.ignore()

    def _may_close(self, editor: CodeEditor) -> bool:
        """Offer to save an editor's unsaved changes. False means canceled."""
        if not editor.document().isModified():
            return True
        self.tabs.setCurrentWidget(editor)
        buttons = QMessageBox.StandardButton
        answer = QMessageBox.warning(
            self,
            "Unsaved Changes",
            f"Do you want to save the changes you made to {editor.title}?",
            buttons.Save | buttons.Discard | buttons.Cancel,
            buttons.Save,
        )
        if answer == buttons.Save:
            return self.save()
        return answer == buttons.Discard

    def _write(self, editor: CodeEditor, path: Path) -> bool:
        try:
            editor.save(path.resolve())
        except OSError as error:
            self._report(f"Cannot save {path.name}: {error.strerror}")
            return False
        self._label_tab(editor)
        return True

    # Tabs and panels

    def _add_tab(self, editor: CodeEditor) -> None:
        self.tabs.addTab(editor, "")
        editor.document().modificationChanged.connect(
            lambda _modified: self._label_tab(editor)
        )
        self._label_tab(editor)
        self.tabs.setCurrentWidget(editor)
        editor.setFocus()

    def _label_tab(self, editor: CodeEditor) -> None:
        index = self.tabs.indexOf(editor)
        modified = editor.document().isModified()
        self.tabs.setTabText(index, editor.title + (MODIFIED_MARK if modified else ""))
        self.tabs.setTabToolTip(index, str(editor.path or ""))

    def next_tab(self) -> None:
        self._step_tab(1)

    def previous_tab(self) -> None:
        self._step_tab(-1)

    def _step_tab(self, step: int) -> None:
        if self.tabs.count():
            index = (self.tabs.currentIndex() + step) % self.tabs.count()
            self.tabs.setCurrentIndex(index)

    def toggle_file_tree(self) -> None:
        self.file_tree_dock.setVisible(not self.file_tree_dock.isVisible())

    def toggle_terminal(self) -> None:
        """Show the terminal and type into it, or hide it and return to the file."""
        if self.terminal_dock.isVisible():
            self.terminal_dock.hide()
            editor = self.current_editor()
            if editor is not None:
                editor.setFocus()
        else:
            self.terminal_dock.show()
            self.terminal_view.focus_terminal()

    def _report(self, text: str) -> None:
        self.statusBar().showMessage(text, STATUS_MESSAGE_MS)

    def _update_title(self) -> None:
        title = "Pyde"
        if self.folder is not None:
            place = self.folder.name
            if self._in_container:
                place += f" [Dev Container: {self.dev_container.config.name}]"
            title = f"{place} — Pyde"
        self.setWindowTitle(title)

    # Dev containers

    def reopen_in_container(self, rebuild: bool = False) -> None:
        """Bring the folder's dev container up and move the terminal into it.

        The files are still edited where they are: a dev container mounts the
        folder, so only what runs, which is the terminal, moves.
        """
        # The file may have been edited since the folder was opened.
        self._offer_container()
        if self._container_config is None:
            if self.notice_bar.isHidden():
                self._report("This folder has no dev container configuration")
            return
        # About to bring it up again, so leave the containers running.
        self._leave_container(stop=False)
        self.dev_container = DevContainer(
            self._container_config, self.terminal_view, self._config_dir, parent=self
        )
        self.dev_container.connected.connect(self._container_connected)
        self.dev_container.failed.connect(self._container_failed)
        self.dev_container.warned.connect(self.notice_bar.show_notice)
        self.notice_bar.show_notice("Starting the dev container…")
        self.terminal_dock.show()
        self.dev_container.start(rebuild)

    def rebuild_container(self) -> None:
        """Build the images again and replace the containers with new ones.

        The lifecycle commands that run once per container then run again.
        """
        self.reopen_in_container(rebuild=True)

    def reopen_locally(self) -> None:
        """Leave the dev container and return the terminal to this Mac."""
        if self.dev_container is None:
            return
        self._leave_container()
        self.terminal_view.use_shell()
        self._offer_container()

    def _offer_container(self) -> None:
        """Tell the user if the open folder has a dev container configuration."""
        self._container_config = None
        self.notice_bar.hide()
        path = find_config(self.folder) if self.folder else None
        if path is None:
            return
        try:
            self._container_config = load_config(path, self.folder)
        except ConfigError as error:
            self.notice_bar.show_notice(
                f"This folder's dev container configuration can't be used: {error}."
            )
            return
        self.notice_bar.show_notice(
            "This folder has a dev container configuration.",
            "Reopen in Container",
            self.reopen_in_container,
        )

    def _leave_container(self, stop: bool = True, quitting: bool = False) -> None:
        if self.dev_container is not None:
            self.dev_container.leave(stop, quitting)
            self.dev_container.deleteLater()
            self.dev_container = None
        self._in_container = False
        self.container_label.hide()
        self._update_title()

    def _container_connected(self) -> None:
        self._in_container = True
        self.notice_bar.hide()
        self.container_label.setText(f"Dev Container: {self.dev_container.config.name}")
        self.container_label.show()
        self._update_title()
        self.terminal_view.focus_terminal()

    def _container_failed(self, reason: str) -> None:
        self.notice_bar.show_notice(
            f"The dev container did not start. {reason}",
            "Retry",
            self.reopen_in_container,
        )
