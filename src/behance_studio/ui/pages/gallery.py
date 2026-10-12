"""Proposal gallery: all generated presentations, filter, compare, manage."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QMenu, QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget

from behance_studio.core.errors import UserFacingError
from behance_studio.generation import editing
from behance_studio.layout.families import available_families, family_info
from behance_studio.projects.models import VersionRecord
from behance_studio.ui.dialogs.messages import confirm, show_error
from behance_studio.ui.dialogs.progress import ProgressDialog
from behance_studio.ui.icons import icon
from behance_studio.ui.theme import FAMILY_COLORS, T
from behance_studio.ui.widgets.common import Badge, Card, EmptyState, FlowLayout, PageHeader, StripPreview, button, label


def _date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d %b %Y, %H:%M")
    except ValueError:
        return iso


class ProposalCard(Card):
    toggled = Signal(str, bool)
    open_requested = Signal(str)
    favorite_toggled = Signal(str, bool)

    def __init__(self, record: VersionRecord, strip_path, preferred: bool, selected: bool) -> None:
        super().__init__()
        self.record = record
        self.setFixedSize(304, 468)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 12)
        lay.setSpacing(7)
        self.strip = StripPreview(284, 330)
        self.strip.set_path(strip_path if strip_path.exists() else None)
        self.strip.setToolTip("Hover to scroll through the whole presentation · double-click to open")
        lay.addWidget(self.strip)
        top = QHBoxLayout()
        top.setSpacing(6)
        info = family_info(record.family)
        top.addWidget(Badge(info.name, FAMILY_COLORS.get(record.family)))
        if preferred:
            top.addWidget(Badge("Preferred", T.accent, "#FFFFFF"))
        top.addStretch(1)
        self.fav = QToolButton()
        self.fav.setCheckable(True)
        self.fav.setChecked(record.favorite)
        self.fav.setIcon(icon("star-filled" if record.favorite else "star", T.warning if record.favorite else T.text2, T.warning))
        self.fav.setToolTip("Favourite")
        self.fav.clicked.connect(lambda checked: self.favorite_toggled.emit(record.id, checked))
        top.addWidget(self.fav)
        self.check = QCheckBox()
        self.check.setChecked(selected)
        self.check.setToolTip("Select (for compare, export, trash)")
        self.check.toggled.connect(lambda on: self.toggled.emit(record.id, on))
        top.addWidget(self.check)
        lay.addLayout(top)
        lay.addWidget(label(record.name, "H3"))
        issues = f" · {record.issues} issue(s)" if record.issues else ""
        lay.addWidget(label(f"{_date(record.created_at)} · seed {record.seed}{issues}", "Faint"))
        self.set_selected(selected)
        self.double_clicked.connect(lambda: self.open_requested.emit(record.id))
        self.clicked.connect(lambda: self.check.setChecked(not self.check.isChecked()))


class GalleryPage(QWidget):
    def __init__(self, state, actions) -> None:
        super().__init__()
        self.state, self.actions = state, actions
        self.selected: set[str] = set()
        self.family_filter = "all"
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 20)
        root.setSpacing(14)
        self.header = PageHeader("Proposals", "Every proposal is a complete presentation. Hover a card to scroll through it.", "Generated")
        self.header.add_action(button("Generate more", "sparkles", on_click=lambda: self.actions.generate()))
        root.addWidget(self.header)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.chips: dict[str, QPushButton] = {}
        from behance_studio.layout.families import CONCEPT_FAMILIES

        concept_chips = [(f, family_info(f).name) for f in available_families() if f in CONCEPT_FAMILIES]
        for key, text in [("all", "All")] + concept_chips + [("classic", "Classic layouts"), ("favorites", "★ Favourites")]:
            chip = QPushButton(text)
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            chip.setChecked(key == "all")
            chip.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self.chips[key] = chip
            bar.addWidget(chip)
        bar.addStretch(1)
        self.sort = QComboBox()
        self.sort.addItems(["Newest first", "Oldest first", "By family", "Best checks first"])
        self.sort.currentIndexChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.sort)
        root.addLayout(bar)

        actions_bar = QHBoxLayout()
        self.sel_label = label("", "Muted")
        actions_bar.addWidget(self.sel_label)
        actions_bar.addStretch(1)
        self.btn_open = button("Open", "eye", "Ghost", on_click=self._open_selected)
        self.btn_compare = button("Compare", "compare", on_click=self._compare)
        self.btn_export = button("Export", "export", on_click=lambda: self.state.export_versions.emit(sorted(self.selected)))
        self.btn_canva = button("Export to Canva", "external", "Ghost", on_click=self._canva)
        self.btn_trash = button("Move to Trash", "trash", "Danger", on_click=self._trash_selected)
        for b in (self.btn_open, self.btn_compare, self.btn_export, self.btn_canva, self.btn_trash):
            actions_bar.addWidget(b)
        root.addLayout(actions_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.holder = QWidget()
        self.flow = FlowLayout(spacing=18)
        self.holder.setLayout(self.flow)
        scroll.setWidget(self.holder)
        root.addWidget(scroll, 1)
        state.project_changed.connect(lambda _p: (self.selected.clear(), self.refresh()))
        state.versions_changed.connect(self.refresh)
        self._update_actions()

    def showEvent(self, event) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(event)

    def _set_filter(self, key: str) -> None:
        self.family_filter = key
        for k, c in self.chips.items():
            c.setChecked(k == key)
        self.refresh()

    def refresh(self) -> None:
        self.flow.clear()
        manager = self.state.versions
        if manager is None:
            return
        versions = manager.list()
        self.selected &= {v.id for v in versions}
        from behance_studio.layout.families import CLASSIC_FAMILIES

        if self.family_filter == "favorites":
            versions = [v for v in versions if v.favorite]
        elif self.family_filter == "classic":
            versions = [v for v in versions if v.family in CLASSIC_FAMILIES]
        elif self.family_filter != "all":
            versions = [v for v in versions if v.family == self.family_filter]
        order = self.sort.currentIndex()
        if order == 0:
            versions.sort(key=lambda v: v.number, reverse=True)
        elif order == 2:
            fam = available_families()
            versions.sort(key=lambda v: (fam.index(v.family) if v.family in fam else 99, -v.number))
        elif order == 3:
            versions.sort(key=lambda v: (v.issues, -v.quality, -v.number))
        if not versions:
            has_assets = bool(self.state.project and self.state.project.list_assets(visual_only=True))
            self.flow.addWidget(EmptyState("layers", "No proposals yet" if self.family_filter == "all" else "Nothing matches this filter",
                                           "Generate five complete case-study concepts from your assets — each with its own art direction." if has_assets else "Add assets in the Workspace first.",
                                           "Generate Projects" if has_assets else "", (lambda: self.actions.generate()) if has_assets else None))
        preferred = self.state.project.config.preferred_version_id if self.state.project else None
        for v in versions:
            card = ProposalCard(v, manager.strip_path(v), v.id == preferred, v.id in self.selected)
            card.toggled.connect(self._toggle)
            card.open_requested.connect(self.state.open_version.emit)
            card.favorite_toggled.connect(self._favorite)
            card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            card.customContextMenuRequested.connect(lambda pos, rec=v, c=card: self._menu(rec, c.mapToGlobal(pos)))
            self.flow.addWidget(card)
        self._update_actions()

    def _toggle(self, vid: str, on: bool) -> None:
        if on:
            self.selected.add(vid)
        else:
            self.selected.discard(vid)
        for i in range(self.flow.count()):
            w = self.flow.itemAt(i).widget()
            if isinstance(w, ProposalCard) and w.record.id == vid:
                w.set_selected(on)
        self._update_actions()

    def _update_actions(self) -> None:
        n = len(self.selected)
        self.sel_label.setText(f"{n} selected" if n else "Select proposals to compare, export or remove")
        self.btn_open.setEnabled(n == 1)
        self.btn_compare.setEnabled(2 <= n <= 3)
        self.btn_export.setEnabled(n >= 1)
        self.btn_canva.setText("Export to Canva" if n else "Export project to Canva")
        self.btn_trash.setEnabled(n >= 1)

    def _open_selected(self) -> None:
        if len(self.selected) == 1:
            self.state.open_version.emit(next(iter(self.selected)))

    def _compare(self) -> None:
        self.state.compare_versions.emit(sorted(self.selected, key=lambda vid: self.state.project.get_version(vid).number))

    def _favorite(self, vid: str, on: bool) -> None:
        self.state.versions.set_favorite(vid, on)
        self.refresh()

    def _trash_selected(self) -> None:
        ids = sorted(self.selected)
        if ids and confirm(self, "Move to Trash", f"Move {len(ids)} proposal(s) to the Trash?", "Move to Trash", detail="You can restore them from the Trash page. Source assets are not affected."):
            self.state.versions.trash(ids)
            self.selected.clear()
            self.state.versions_changed.emit()

    def _menu(self, record: VersionRecord, pos) -> None:
        manager = self.state.versions
        menu = QMenu(self)
        menu.addAction(icon("eye"), "Open", lambda: self.state.open_version.emit(record.id))
        menu.addAction(icon("edit"), "Rename…", lambda: self._rename(record))
        menu.addAction(icon("copy"), "Duplicate", lambda: (manager.duplicate(record.id), self.state.versions_changed.emit()))
        menu.addAction(icon("refresh"), "Regenerate (new variation)", lambda: self._regenerate(record.id))
        fam_menu = menu.addMenu(icon("layers"), "Apply layout family")
        for fid in available_families():
            if fid != record.family:
                fam_menu.addAction(family_info(fid).name, lambda f=fid: self._regenerate(record.id, family=f, keep_plan=True))
        menu.addSeparator()
        menu.addAction(icon("flag"), "Set as preferred version", lambda: (manager.set_preferred(record.id), self.state.touch_library(), self.refresh()))
        menu.addAction(icon("star"), "Remove from favourites" if record.favorite else "Add to favourites", lambda: self._favorite(record.id, not record.favorite))
        menu.addAction(icon("export"), "Export…", lambda: self.state.export_versions.emit([record.id]))
        menu.addAction(icon("external"), "Export to Canva…", lambda: self.state.export_canva.emit([record.id]))
        menu.addSeparator()
        menu.addAction(icon("trash"), "Move to Trash", lambda: (manager.trash([record.id]), self.selected.discard(record.id), self.state.versions_changed.emit()))
        menu.exec(pos)

    def _canva(self) -> None:
        """Selected proposals, or the whole project when none is selected."""
        ids = sorted(self.selected) or [v.id for v in self.state.versions.list()]
        if ids:
            self.state.export_canva.emit(ids)

    def _rename(self, record: VersionRecord) -> None:
        name, ok = QInputDialog.getText(self, "Rename proposal", "Name", text=record.name)
        if ok and name.strip():
            try:
                self.state.versions.rename(record.id, name.strip())
                self.refresh()
            except UserFacingError as exc:
                show_error(self, exc)

    def _regenerate(self, version_id: str, family: str | None = None, keep_plan: bool = False) -> None:
        project = self.state.project
        browser = self.state.settings.browser_path
        dlg = ProgressDialog(self, "Creating a new variation" if not keep_plan else "Applying layout family")

        def work(token, progress):
            progress(0.2, "Composing…")
            if keep_plan:
                manager = self.state.versions
                proposal = manager.load(version_id)
                new = editing.apply_family(project, proposal, family)
                record = manager.create(new, parent_id=version_id)
                from behance_studio.render.previews import render_previews

                render_previews(project, [(new.presentation, manager.thumb_path(record), manager.strip_path(record))], browser_path=browser)
                return record.id
            return editing.new_seed_version(project, version_id, family=family, browser_path=browser)

        task = self.state.runner.start(work, "regenerate", on_done=lambda _vid: (dlg.finish(), self.state.versions_changed.emit()), on_error=lambda e: (dlg.reject(), show_error(self, e)), on_progress=dlg.update_progress)
        dlg.cancel_requested.connect(task.cancel)
        dlg.exec()
