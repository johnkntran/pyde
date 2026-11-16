import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from pyde.file_tree import FileTree


@pytest.fixture
def tree(qapp):
    tree = FileTree()
    yield tree
    tree.deleteLater()


def rows(tree):
    """The index of every entry at the top level of the tree, in order."""
    model = tree.model()
    count = model.rowCount(tree.rootIndex())
    return [model.index(row, 0, tree.rootIndex()) for row in range(count)]


def names(tree):
    return [index.data() for index in rows(tree)]


def test_the_tree_is_empty_until_a_folder_is_opened(tree):
    assert tree.model() is None


def test_folders_come_first_and_clutter_is_left_out(tree, tmp_path, wait_until):
    for folder in ("zeta", ".github", ".git"):
        (tmp_path / folder).mkdir()
    for file in ("b.txt", "A.txt", ".gitignore", ".DS_Store"):
        (tmp_path / file).write_text("")

    tree.set_folder(tmp_path)

    expected = [".github", "zeta", ".gitignore", "A.txt", "b.txt"]
    wait_until(lambda: names(tree) == expected)


def test_only_the_name_column_is_shown(tree, tmp_path, wait_until):
    (tmp_path / "file.txt").write_text("")
    tree.set_folder(tmp_path)
    wait_until(lambda: names(tree) == ["file.txt"])

    shown = [
        column
        for column in range(tree.model().columnCount())
        if not tree.isColumnHidden(column)
    ]
    assert shown == [0]


def test_activating_a_file_announces_its_path(tree, tmp_path, wait_until):
    (tmp_path / "folder").mkdir()
    (tmp_path / "file.txt").write_text("")
    tree.set_folder(tmp_path)
    wait_until(lambda: names(tree) == ["folder", "file.txt"])
    activated = []
    tree.file_activated.connect(activated.append)

    folder, file = rows(tree)
    tree.activated.emit(folder)
    tree.activated.emit(file)

    assert activated == [tmp_path / "file.txt"]


@pytest.fixture
def shown(tree, tmp_path, wait_until):
    """The tree on screen, showing a folder and a file, ready to be clicked."""
    (tmp_path / "folder").mkdir()
    (tmp_path / "file.txt").write_text("")
    tree.set_folder(tmp_path)
    tree.resize(300, 200)
    tree.show()
    wait_until(lambda: names(tree) == ["folder", "file.txt"])
    wait_until(
        lambda: all(not tree.visualRect(index).isEmpty() for index in rows(tree))
    )
    clicked, activated = [], []
    tree.file_clicked.connect(clicked.append)
    tree.file_activated.connect(activated.append)
    return clicked, activated


def click(tree, index, button=Qt.MouseButton.LeftButton):
    QTest.mouseClick(tree.viewport(), button, pos=tree.visualRect(index).center())


def test_clicking_a_file_announces_it_to_look_at(tree, tmp_path, shown):
    clicked, activated = shown
    folder, file = rows(tree)

    click(tree, folder)
    click(tree, file, button=Qt.MouseButton.RightButton)
    assert clicked == []

    click(tree, file)
    assert clicked == [tmp_path / "file.txt"]
    # A single click is not the same as opening the file to work in.
    assert activated == []


def test_double_clicking_a_file_announces_it_to_work_in(
    tree, tmp_path, shown, double_click
):
    clicked, activated = shown
    folder, file = rows(tree)

    double_click(tree.viewport(), tree.visualRect(folder).center())
    double_click(tree.viewport(), tree.visualRect(file).center())

    assert activated == [tmp_path / "file.txt"]


def test_opening_another_folder_replaces_the_contents(tree, tmp_path, wait_until):
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
        (tmp_path / name / f"{name}.txt").write_text("")
    tree.set_folder(tmp_path / "first")
    wait_until(lambda: names(tree) == ["first.txt"])

    tree.set_folder(tmp_path / "second")

    wait_until(lambda: names(tree) == ["second.txt"])
