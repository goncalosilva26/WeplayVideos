"""Trash: restore or permanently delete proposals."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from behance_studio.layout.families import family_info
from behance_studio.ui.dialogs.messages import confirm, show_error
from behance_studio.ui.theme import FAMILY_COLORS
from behance_studio.ui.widgets.common import Badge, Card, EmptyState, PageHeader, Thumb, button, clear_layout, label


class TrashRow(Card):
    def __init__(self, record, thumb_path) -> None:
        super().__init__()
        self.record = record
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 14, 10)
        lay.setSpacing(14)
        self.check = QCheckBox()
        lay.addWidget(self.check)
        t = Thumb(120, 90, radius=6)
        t.set_path(thumb_path if thumb_path.exists() else None)
        lay.addWidget(t)
        texts = QVBoxLayout()
        texts.addWidget(label(record.name, "H3"))
        when = record.trashed_at or record.modified_at
        try:
            when = datetime.fromisoformat(when).astimezone().strftime("%d %b %Y, %H:%M")
        except (TypeError, ValueError):
            pass
        texts.addWidget(label(f"Moved to Trash {when}", "Faint"))
        lay.addLayout(texts, 1)
        lay.addWidget(Badge(family_info(record.family).name, FAMILY_COLORS.get(record.family)))
        self.clicked.connect(lambda: self.check.setChecked(not self.check.isChecked()))


class TrashPage(QWidget):
    def __init__(self, state, actions, toast) -> None:
        super().__init__()
        self.state, self.actions, self.toast = state, actions, toast
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 20)
        root.setSpacing(14)
        header = PageHeader("Trash", "Deleted proposals stay here until you remove them permanently. Source assets are never affected.", "Recovery")
        header.add_action(button("Restore", "restore", on_click=self._restore))
        header.add_action(button("Delete permanently", "trash", "Danger", on_click=self._delete))
        header.add_action(button("Empty Trash", "trash", "Ghost", on_click=self._empty))
        root.addWidget(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        self.list = QVBoxLayout(holder)
        self.list.setSpacing(10)
        self.list.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)
        self.rows: list[TrashRow] = []
        state.project_changed.connect(lambda _p: self.refresh())
        state.versions_changed.connect(self.refresh)

    def showEvent(self, event) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(event)

    def refresh(self) -> None:
        clear_layout(self.list)
        self.rows = []
        manager = self.state.versions
        trashed = manager.trashed() if manager else []
        if not trashed:
            self.list.addWidget(EmptyState("trash", "The Trash is empty", "Proposals you delete appear here and can be restored."))
            return
        for record in sorted(trashed, key=lambda r: r.trashed_at or "", reverse=True):
            row = TrashRow(record, manager.thumb_path(record))
            self.rows.append(row)
            self.list.addWidget(row)

    def _checked(self) -> list[str]:
        return [r.record.id for r in self.rows if r.check.isChecked()]

    def _restore(self) -> None:
        ids = self._checked()
        if not ids:
            return
        n = self.state.versions.restore(ids)
        self.state.versions_changed.emit()
        self.toast(f"{n} proposal(s) restored")

    def _delete(self) -> None:
        ids = self._checked()
        if not ids:
            return
        if confirm(self, "Delete permanently", f"Permanently delete {len(ids)} proposal(s)?", "Delete permanently", destructive=True, detail="This cannot be undone. Other proposals and your source assets are not affected."):
            try:
                self.state.versions.delete_permanently(ids)
            except Exception as exc:  # noqa: BLE001
                show_error(self, exc)
            self.state.versions_changed.emit()

    def _empty(self) -> None:
        manager = self.state.versions
        if manager is None or not manager.trashed():
            return
        if confirm(self, "Empty Trash", f"Permanently delete all {len(manager.trashed())} proposal(s) in the Trash?", "Empty Trash", destructive=True, detail="This cannot be undone."):
            manager.empty_trash()
            self.state.versions_changed.emit()
