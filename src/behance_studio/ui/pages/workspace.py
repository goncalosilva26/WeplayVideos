"""Project workspace: assets, project understanding, brief, script, generation."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from behance_studio.assets.derivatives import thumbnail_path
from behance_studio.brief.directives import build_directives
from behance_studio.brief.script import script_template
from behance_studio.core.errors import UserFacingError
from behance_studio.core.fsutil import read_text_file
from behance_studio.design.direction import build_direction
from behance_studio.export.exporter import open_folder
from behance_studio.layout.families import available_families, family_info
from behance_studio.projects.models import ASSET_KINDS, LOGO_KINDS, PHOTO_KINDS, UI_KINDS
from behance_studio.ui.dialogs.messages import confirm, show_error
from behance_studio.ui.theme import FAMILY_COLORS, T
from behance_studio.ui.widgets.common import EmptyState, PageHeader, Swatches, button, clear_layout, label, section_title
from behance_studio.ui.worker import image_loader

ROLE_ID = Qt.ItemDataRole.UserRole
ROLE_KIND = Qt.ItemDataRole.UserRole + 1
ROLE_STATUS = Qt.ItemDataRole.UserRole + 2
ROLE_SOURCE = Qt.ItemDataRole.UserRole + 3

FILTERS = [
    ("all", "All", None),
    ("brand", "Identity", LOGO_KINDS | {"palette", "typography", "pattern"}),
    ("photo", "Photography", PHOTO_KINDS),
    ("apps", "Applications", {"packaging", "stationery", "mockup", "product", "editorial"}),
    ("campaign", "Campaign", {"poster", "outdoor", "social"}),
    ("ui", "Interfaces", UI_KINDS),
    ("motion", "Motion", {"video", "motion"}),
    ("other", "Other", {"illustration", "other", "document"}),
]

TILE = QSize(176, 176)


class AssetDelegate(QStyledItemDelegate):
    def __init__(self, view: "AssetGrid") -> None:
        super().__init__(view)
        self.view = view

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(TILE.width() + 12, TILE.height() + 46)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = option.rect.adjusted(6, 6, -6, -6)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        img_rect = QRectF(rect.x(), rect.y(), rect.width(), TILE.height() - 10)
        path = QPainterPath()
        path.addRoundedRect(img_rect, 9, 9)
        p.fillPath(path, QColor(T.surface3))
        aid = index.data(ROLE_ID)
        pix: QPixmap | None = self.view.pixmaps.get(aid)
        if pix is not None and not pix.isNull():
            p.setClipPath(path)
            scale = min(img_rect.width() / pix.width(), img_rect.height() / pix.height())
            w, h = pix.width() * scale, pix.height() * scale
            # checkerboard behind transparent artwork
            p.fillRect(img_rect, QColor("#2A2E34"))
            p.drawPixmap(QRectF(img_rect.center().x() - w / 2, img_rect.center().y() - h / 2, w, h), pix, QRectF(pix.rect()))
            p.setClipping(False)
        status = index.data(ROLE_STATUS)
        if status in ("excluded", "missing", "corrupt"):
            p.fillPath(path, QColor(0, 0, 0, 150))
            p.setPen(QColor("#FFFFFF" if status == "excluded" else T.danger))
            p.drawText(img_rect, Qt.AlignmentFlag.AlignCenter, {"excluded": "Excluded", "missing": "File missing", "corrupt": "Damaged"}[status])
        if selected or hovered:
            p.setPen(QPen(QColor(T.accent if selected else T.border_strong), 2))
            p.drawPath(path)
        kind = index.data(ROLE_KIND) or ""
        source = index.data(ROLE_SOURCE) or "heuristic"
        badge_text = kind + ("" if source == "user" else (" · AI" if source == "ai" else " ·  ~"))
        font = QFont(p.font())
        font.setPointSizeF(7.5)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        tw = p.fontMetrics().horizontalAdvance(badge_text) + 14
        badge = QRectF(img_rect.left() + 7, img_rect.bottom() - 26, tw, 19)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(14, 15, 17, 215))
        p.drawRoundedRect(badge, 9, 9)
        p.setPen(QColor(T.text if source == "user" else T.text2))
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, badge_text)
        name_font = QFont(option.font)
        name_font.setPointSizeF(8.6)
        p.setFont(name_font)
        p.setPen(QColor(T.text2))
        text_rect = QRect(rect.x() + 2, int(img_rect.bottom()) + 6, rect.width() - 4, 18)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, p.fontMetrics().elidedText(index.data(Qt.ItemDataRole.DisplayRole), Qt.TextElideMode.ElideMiddle, text_rect.width()))
        p.restore()


class AssetGrid(QListWidget):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.pixmaps: dict[str, QPixmap] = {}
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSpacing(2)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setItemDelegate(AssetDelegate(self))
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setStyleSheet("QListWidget{background:transparent;border:none;}")

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()


class WorkspacePage(QWidget):
    def __init__(self, state, actions) -> None:
        super().__init__()
        self.state, self.actions = state, actions
        self.filter = "all"
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 26, 32, 20)
        root.setSpacing(16)
        self.header = PageHeader("Workspace", "", "Project")
        self.header.add_action(button("Rename", "edit", "Ghost", on_click=self._rename))
        self.header.add_action(button("Open folder", "folder", "Ghost", on_click=lambda: self.state.project and open_folder(self.state.project.root)))
        self.header.add_action(button("Add assets", "plus", on_click=self.actions.add_assets_dialog))
        self.generate_btn = button("Generate Projects", "sparkles", "Primary", on_click=lambda: self.actions.generate(), tooltip="Generate complete presentation proposals (Ctrl+G)")
        self.header.add_action(self.generate_btn)
        root.addWidget(self.header)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 16, 0)
        ll.setSpacing(10)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.chip_buttons: dict[str, QPushButton] = {}
        for key, text, _kinds in FILTERS:
            chip = QPushButton(text)
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            chip.setChecked(key == "all")
            chip.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self.chip_buttons[key] = chip
            chips.addWidget(chip)
        chips.addStretch(1)
        self.asset_count = label("", "Faint")
        chips.addWidget(self.asset_count)
        ll.addLayout(chips)
        self.grid = AssetGrid()
        self.grid.files_dropped.connect(self.actions.import_assets)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._asset_menu)
        self.grid.itemDoubleClicked.connect(lambda item: self._reveal([item.data(ROLE_ID)]))
        ll.addWidget(self.grid, 1)
        self.empty = EmptyState("images", "Drop your project material here", "Drag files or whole folders onto this area — logos, photography, mockups, posters, social posts, videos. Nothing needs to be organised first.", "Add assets", self.actions.add_assets_dialog)
        ll.addWidget(self.empty, 1)
        hint = label("Types marked “~” are offline estimates; “AI” comes from a configured provider. Right-click to correct them.", "Faint", wrap=True)
        ll.addWidget(hint)
        split.addWidget(left)

        right = self.tabs = QTabWidget()
        right.setMinimumWidth(380)
        right.setMaximumWidth(520)
        self.overview = QWidget()
        self.overview_lay = QVBoxLayout(self.overview)
        self.overview_lay.setContentsMargins(4, 14, 4, 4)
        self.overview_lay.setSpacing(10)
        ov_scroll = QScrollArea()
        ov_scroll.setWidgetResizable(True)
        ov_scroll.setWidget(self.overview)
        right.addTab(ov_scroll, "Overview")
        right.addTab(self._text_tab("brief"), "Brief")
        right.addTab(self._text_tab("script"), "Script")
        right.addTab(self._generate_tab(), "Generate")
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)

        state.project_changed.connect(lambda _p: self.refresh())
        state.assets_changed.connect(self.refresh)
        state.texts_changed.connect(self._load_texts)

    # --------------------------------------------------------------- tabs
    def _text_tab(self, kind: str) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(4, 14, 4, 4)
        lay.setSpacing(8)
        if kind == "brief":
            lay.addWidget(label("Creative brief · guides the visual identity (mood, colours, fonts, audience).", "Faint", wrap=True))
        else:
            lay.addWidget(label("Project script (GUIAO_PROJETO.txt) · authoritative for sections, exact text, images and order.", "Faint", wrap=True))
        editor = QPlainTextEdit()
        editor.setFont(QFont("JetBrains Mono", 9))
        lay.addWidget(editor, 1)
        row = QHBoxLayout()
        row.addWidget(button("Save", "check", "Primary", on_click=lambda: self._save_text(kind)))
        row.addWidget(button("Load file…", "file-text", "Ghost", on_click=lambda: self._load_text_file(kind)))
        if kind == "script":
            row.addWidget(button("Template", "plus", "Ghost", on_click=self._insert_template))
            row.addWidget(button("Check", "check-circle", "Ghost", on_click=self._check_script))
        row.addStretch(1)
        lay.addLayout(row)
        status = label("", "Faint", wrap=True)
        lay.addWidget(status)
        if kind == "brief":
            self.brief_edit, self.brief_status = editor, status
        else:
            self.script_edit, self.script_status = editor, status
        return tab

    def _generate_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(4, 14, 4, 4)
        lay.setSpacing(12)
        lay.addWidget(label("Everything here is optional — the defaults generate one complete proposal per layout family.", "Faint", wrap=True))
        form = QFormLayout()
        form.setSpacing(10)
        self.count = QSpinBox()
        self.count.setRange(1, 24)
        self.count.setValue(6)
        form.addRow("Proposals", self.count)
        self.creativity = QSlider(Qt.Orientation.Horizontal)
        self.creativity.setRange(0, 100)
        self.creativity.setValue(int(self.state.settings.creativity * 100))
        form.addRow("Creative variation", self.creativity)
        lay.addLayout(form)
        lay.addWidget(section_title("Layout families"))
        grid = QGridLayout()
        self.family_checks: dict[str, QCheckBox] = {}
        for i, fid in enumerate(available_families()):
            info = family_info(fid)
            cb = QCheckBox(info.name)
            cb.setChecked(fid in self.state.settings.families)
            cb.setToolTip(f"{info.tagline}\nIdeal for: {', '.join(info.ideal_for)}")
            cb.setStyleSheet(f"QCheckBox::indicator:checked{{background:{FAMILY_COLORS.get(fid, T.accent)};border-color:{FAMILY_COLORS.get(fid, T.accent)};}}")
            self.family_checks[fid] = cb
            grid.addWidget(cb, i // 2, i % 2)
        lay.addLayout(grid)
        lay.addSpacing(6)
        go = button("Generate Projects", "sparkles", "Primary", on_click=self._generate_custom)
        go.setMinimumHeight(40)
        lay.addWidget(go)
        lay.addStretch(1)
        return tab

    # ------------------------------------------------------------- refresh
    def showEvent(self, event) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(event)

    def refresh(self) -> None:
        project = self.state.project
        if project is None:
            self.header.title.setText("No project open")
            self.grid.clear()
            return
        self.header.title.setText(project.name)
        self.header.set_subtitle(str(project.root))
        self._load_assets()
        self._load_texts()
        self._load_overview()

    def _set_filter(self, key: str) -> None:
        self.filter = key
        for k, chip in self.chip_buttons.items():
            chip.setChecked(k == key)
        self._load_assets()

    def _load_assets(self) -> None:
        project = self.state.project
        self.grid.clear()
        assets = [a for a in project.list_assets() if a.media_type != "document"]
        kinds = dict((k, v) for k, _t, v in FILTERS)
        wanted = kinds.get(self.filter)
        shown = [a for a in assets if wanted is None or a.effective_kind in wanted]
        self.asset_count.setText(f"{len(shown)} of {len(assets)}")
        self.empty.setVisible(not assets)
        self.grid.setVisible(bool(assets))
        self.generate_btn.setEnabled(bool(assets))
        for asset in shown:
            item = QListWidgetItem(asset.filename)
            item.setData(ROLE_ID, asset.id)
            item.setData(ROLE_KIND, ASSET_KINDS.get(asset.effective_kind, asset.effective_kind))
            status = "excluded" if asset.excluded else asset.status
            item.setData(ROLE_STATUS, status if status != "ok" else "")
            item.setData(ROLE_SOURCE, "user" if asset.user_kind else asset.kind_source)
            reasons = ", ".join((asset.analysis or {}).get("classification", {}).get("reasons", [])[:3])
            confidence = "set by you" if asset.user_kind else f"{asset.kind_source} estimate, confidence {asset.kind_confidence:.0%}"
            item.setToolTip(f"{asset.filename}\n{asset.width}×{asset.height} · {asset.media_type}\nType: {ASSET_KINDS.get(asset.effective_kind)} ({confidence})" + (f"\nBecause: {reasons}" if reasons else ""))
            item.setSizeHint(QSize(TILE.width() + 12, TILE.height() + 46))
            self.grid.addItem(item)
            thumb = thumbnail_path(project, asset)
            if thumb and asset.id not in self.grid.pixmaps:
                image_loader().load(thumb, QSize(360, 360), lambda pix, aid=asset.id: self._thumb_loaded(aid, pix))

    def _thumb_loaded(self, aid: str, pix: QPixmap) -> None:
        self.grid.pixmaps[aid] = pix
        self.grid.viewport().update()

    def _load_texts(self) -> None:
        project = self.state.project
        if project is None:
            return
        self.brief_edit.setPlainText(project.brief_text)
        self.script_edit.setPlainText(project.script_text)
        self.brief_status.setText("")
        self.script_status.setText("")

    def _load_overview(self) -> None:
        clear_layout(self.overview_lay)
        project = self.state.project
        assets = project.list_assets()
        visual = [a for a in assets if a.is_visual]
        if not visual:
            self.overview_lay.addWidget(label("Import assets to see how Behance Studio understands the project.", "Muted", wrap=True))
            self.overview_lay.addStretch(1)
            return
        try:
            d = build_directives(project.name, assets, project.brief_text, project.script_text, project.config.language, project.config.category_override)
            direction = build_direction(d.brief, assets, d.category)
        except Exception as exc:  # noqa: BLE001
            self.overview_lay.addWidget(label(f"Analysis unavailable: {exc}", "Muted", wrap=True))
            return
        lay = self.overview_lay
        lay.addWidget(section_title("Project"))
        lay.addWidget(label(d.category.label(d.language), "H2"))
        lay.addWidget(label(f"Category from {d.provenance.get('category', 'assets')} · confidence {d.category.confidence:.0%} · language {d.language.upper()} ({d.provenance.get('language')})", "Faint", wrap=True))
        counts: dict[str, int] = {}
        for a in visual:
            counts[a.effective_kind] = counts.get(a.effective_kind, 0) + 1
        lay.addWidget(label(" · ".join(f"{n} {ASSET_KINDS.get(k, k).lower()}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1])), "Muted", wrap=True))
        lay.addSpacing(8)
        lay.addWidget(section_title("Brand colours"))
        sw = Swatches([s.hex for s in direction.palette.swatches] or [direction.palette.primary, direction.palette.secondary, direction.palette.ink, direction.palette.paper], 26)
        lay.addWidget(sw)
        lay.addWidget(label(f"Source: {direction.palette.source}", "Faint"))
        lay.addSpacing(8)
        lay.addWidget(section_title("Typography"))
        ts = direction.type_system
        lay.addWidget(label(f"{ts.display} / {ts.text}" + (" (from brief)" if direction.brand_fonts_known else " (suggested — families may vary)"), "Muted", wrap=True))
        lay.addSpacing(8)
        lay.addWidget(section_title("Personality"))
        names = {"warmth": ("Cool", "Warm"), "energy": ("Calm", "Playful"), "refinement": ("Casual", "Refined"), "boldness": ("Subtle", "Bold"), "modernity": ("Classic", "Contemporary"), "organic": ("Geometric", "Organic")}
        for axis, (lo, hi) in names.items():
            v = direction.personality.get(axis, 0.0)
            filled = int(round((v + 1) * 2.5))
            bar = "●" * filled + "○" * (5 - filled)
            lay.addWidget(label(f"{lo:<12} {bar}  {hi}", "Muted"))
        if direction.mood_words:
            lay.addWidget(label("Mood: " + ", ".join(direction.mood_words[:8]), "Faint", wrap=True))
        script_errors = [i for i in d.issues if i.severity == "error"]
        if d.script_locked:
            lay.addSpacing(8)
            lay.addWidget(section_title("Script"))
            lay.addWidget(label(f"{len(d.script.sections)} section(s) defined{' — strict' if d.strict else ''}. {len(script_errors)} problem(s).", "Muted", wrap=True))
        for note in d.notes[:4]:
            lay.addWidget(label(f"• {note}", "Faint", wrap=True))
        lay.addSpacing(8)
        lay.addWidget(section_title("Analysis"))
        provider = self.state.settings.ai.provider
        ai_text = "Offline heuristics only (no AI provider configured)." if provider in ("", "none") else (
            f"AI provider: {provider}. " + ("Image analysis allowed for this project." if project.config.ai_consent else "Images are not sent until you allow it for this project.")
        )
        lay.addWidget(label(ai_text, "Faint", wrap=True))
        lay.addStretch(1)

    # -------------------------------------------------------------- actions
    def _rename(self) -> None:
        project = self.state.project
        if project is None:
            return
        name, ok = QInputDialog.getText(self, "Rename project", "Project name", text=project.name)
        if ok and name.strip():
            old = project.root
            try:
                project.rename(name.strip())
                self.state.library.update_path(old, project)
                self.refresh()
            except UserFacingError as exc:
                show_error(self, exc)

    def _save_text(self, kind: str) -> None:
        project = self.state.project
        if project is None:
            return
        editor = self.brief_edit if kind == "brief" else self.script_edit
        project.write_text(kind, editor.toPlainText())
        (self.brief_status if kind == "brief" else self.script_status).setText("Saved.")
        if kind == "script":
            self._check_script()
        self._load_overview()

    def _load_text_file(self, kind: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open text file", "", "Text (*.txt *.md *.json);;All files (*)")
        if path:
            (self.brief_edit if kind == "brief" else self.script_edit).setPlainText(read_text_file(Path(path)))

    def _insert_template(self) -> None:
        project = self.state.project
        lang = project.config.language if project and project.config.language in ("en", "pt") else "en"
        if self.script_edit.toPlainText().strip() and not confirm(self, "Replace script", "Replace the current script with a template?"):
            return
        self.script_edit.setPlainText(script_template(project.name if project else "Project", lang))

    def _check_script(self) -> None:
        project = self.state.project
        if project is None:
            return
        d = build_directives(project.name, project.list_assets(), project.brief_text, self.script_edit.toPlainText())
        if not d.script:
            self.script_status.setText("No script: the presentation structure is planned automatically.")
            return
        lines = [f"{len(d.script.sections)} section(s): " + ", ".join(s.display_title for s in d.script.sections)]
        for issue in d.issues:
            hint = f" Did you mean: {', '.join(issue.suggestions)}?" if issue.suggestions else ""
            lines.append(f"{'✖' if issue.severity == 'error' else '•'} {issue.message}{hint}")
        if not d.issues:
            lines.append("✔ All referenced files were found.")
        self.script_status.setText("\n".join(lines))

    def _generate_custom(self) -> None:
        families = [f for f, cb in self.family_checks.items() if cb.isChecked()]
        if not families:
            show_error(self, "Choose at least one layout family.")
            return
        self.actions.generate(families=families, count=self.count.value(), creativity=self.creativity.value() / 100)

    # ---------------------------------------------------------- asset menu
    def _selected_ids(self) -> list[str]:
        return [i.data(ROLE_ID) for i in self.grid.selectedItems()]

    def _asset_menu(self, pos) -> None:
        ids = self._selected_ids()
        if not ids:
            item = self.grid.itemAt(pos)
            if item is None:
                return
            ids = [item.data(ROLE_ID)]
        menu = QMenu(self)
        kinds = menu.addMenu("Set type")
        for key, name in ASSET_KINDS.items():
            if key in ("document",):
                continue
            kinds.addAction(name, lambda k=key: self._set_kind(ids, k))
        kinds.addSeparator()
        kinds.addAction("Automatic (estimate)", lambda: self._set_kind(ids, None))
        project = self.state.project
        assets = [project.get_asset(i) for i in ids]
        if all(a and a.excluded for a in assets):
            menu.addAction("Include in presentations", lambda: self._set_excluded(ids, False))
        else:
            menu.addAction("Exclude from presentations", lambda: self._set_excluded(ids, True))
        menu.addSeparator()
        menu.addAction("Show in folder", lambda: self._reveal(ids))
        if len(ids) == 1 and assets[0] and assets[0].status == "missing":
            menu.addAction("Relink missing file…", lambda: self._relink(ids[0]))
        menu.addSeparator()
        menu.addAction("Remove from project…", lambda: self._remove(ids))
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def _set_kind(self, ids: list[str], kind: str | None) -> None:
        project = self.state.project
        changed = []
        for aid in ids:
            asset = project.get_asset(aid)
            if asset:
                asset.user_kind = kind
                from behance_studio.assets.roles import infer_roles

                asset.roles = infer_roles(asset)
                changed.append(asset)
        project.save_assets(changed)
        self.state.assets_changed.emit()

    def _set_excluded(self, ids: list[str], excluded: bool) -> None:
        project = self.state.project
        changed = []
        for aid in ids:
            asset = project.get_asset(aid)
            if asset:
                asset.excluded = excluded
                changed.append(asset)
        project.save_assets(changed)
        self.state.assets_changed.emit()

    def _reveal(self, ids: list[str]) -> None:
        project = self.state.project
        asset = project.get_asset(ids[0]) if ids else None
        if asset:
            open_folder(project.resolve_asset_path(asset).parent)

    def _relink(self, aid: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Locate the missing file")
        if path:
            try:
                self.state.project.relink_asset(aid, Path(path))
                self.state.assets_changed.emit()
            except UserFacingError as exc:
                show_error(self, exc)

    def _remove(self, ids: list[str]) -> None:
        if not confirm(self, "Remove assets", f"Remove {len(ids)} asset(s) from this project?", "Remove",
                       destructive=True, detail="Copies inside the project are moved to the project's Trash folder. Your original files are never deleted. Proposals that used these images will show them as missing until regenerated."):
            return
        self.state.project.remove_assets(ids)
        self.state.assets_changed.emit()
