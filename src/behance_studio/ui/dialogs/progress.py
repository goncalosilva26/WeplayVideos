"""Progress dialog for multi-stage jobs (generation, import, export)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from behance_studio.core.tasks import ProgressEvent
from behance_studio.ui.icons import pixmap
from behance_studio.ui.theme import T
from behance_studio.ui.widgets.common import label


class StageRow(QWidget):
    def __init__(self, text: str) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        self.text = label(text)
        lay.addWidget(self.icon)
        lay.addWidget(self.text, 1)
        self.set_state("pending")

    def set_state(self, state: str) -> None:
        if state == "done":
            self.icon.setPixmap(pixmap("check-circle", T.success, 18))
            self.text.setStyleSheet(f"color:{T.text2};")
        elif state == "active":
            self.icon.setPixmap(pixmap("sparkles", T.accent_hover, 18))
            self.text.setStyleSheet(f"color:{T.text};font-weight:600;")
        else:
            self.icon.setPixmap(pixmap("chevron-right", T.text3, 18))
            self.text.setStyleSheet(f"color:{T.text3};")


class ProgressDialog(QDialog):
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None, title: str, stages: list[tuple[str, str]] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 26, 28, 22)
        lay.setSpacing(12)
        self.title = label(title, "H2")
        lay.addWidget(self.title)
        self.message = label("Starting…", "Muted", wrap=True)
        lay.addWidget(self.message)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar)
        self.percent = label("", "Faint")
        lay.addWidget(self.percent)
        self.rows: dict[str, StageRow] = {}
        self._order: list[str] = []
        if stages:
            box = QWidget()
            box.setObjectName("Panel")
            box_lay = QVBoxLayout(box)
            box_lay.setContentsMargins(16, 12, 16, 12)
            for key, text in stages:
                row = StageRow(text)
                self.rows[key] = row
                self._order.append(key)
                box_lay.addWidget(row)
            lay.addWidget(box)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._cancel)
        buttons.addWidget(self.cancel_button)
        lay.addLayout(buttons)

    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancelling…")
        self.message.setText("Stopping after the current step…")
        self.cancel_requested.emit()

    def update_progress(self, event: ProgressEvent) -> None:
        if event.fraction is None:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(event.fraction * 1000))
            self.percent.setText(f"{event.fraction * 100:.0f}%")
        if event.message:
            self.message.setText(event.message)
        if event.stage in self.rows:
            current = self._order.index(event.stage)
            for i, key in enumerate(self._order):
                self.rows[key].set_state("done" if i < current else "active" if i == current else "pending")

    def finish(self) -> None:
        for row in self.rows.values():
            row.set_state("done")
        self.bar.setRange(0, 1000)
        self.bar.setValue(1000)
        self.accept()
