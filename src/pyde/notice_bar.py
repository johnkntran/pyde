"""A strip across the top of the window for telling the user something."""

from collections.abc import Callable

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget


class NoticeBar(QFrame):
    """One line of text, an optional button that acts on it, and a way to
    dismiss it. Showing a new notice replaces the old one."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.action_button = QPushButton()
        self.dismiss_button = QPushButton("Dismiss")
        self._action: Callable[[], None] | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.addWidget(self.label, stretch=1)
        layout.addWidget(self.action_button)
        layout.addWidget(self.dismiss_button)

        self.action_button.clicked.connect(self._act)
        self.dismiss_button.clicked.connect(self.hide)
        self.hide()

    def show_notice(
        self,
        text: str,
        action_label: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        """Show `text`, with a button labelled `action_label` if one is given."""
        self.label.setText(text)
        self._action = action
        self.action_button.setText(action_label or "")
        self.action_button.setVisible(action_label is not None)
        self.show()

    def _act(self) -> None:
        action = self._action
        self.hide()
        if action is not None:
            action()
