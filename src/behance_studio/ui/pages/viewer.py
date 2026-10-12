"""Presentation viewer and optional editor.

The preview is rendered by Qt WebEngine (Chromium) from the same HTML/CSS
that exports use, so what you see is what you export.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from behance_studio.assets.derivatives import thumbnail_path
from behance_studio.core.errors import ScriptError, UserFacingError
from behance_studio.export.exporter import presentation_text
from behance_studio.generation import editing
from behance_studio.generation.proposal import ProposalData
from behance_studio.layout.families import available_families, family_info
from behance_studio.planning.sections import section_type
from behance_studio.projects.models import ASSET_KINDS
from behance_studio.render.project_render import make_options
from behance_studio.render.html import render_html
from behance_studio.core.fsutil import atomic_write_text
from behance_studio.ui.dialogs.messages import confirm, show_error
from behance_studio.ui.icons import icon
from behance_studio.ui.theme import FAMILY_COLORS, T
from behance_studio.ui.widgets.common import Badge, EmptyState, Thumb, button, clear_layout, label, section_title, tool_button

CHANNEL_JS = """<style>html{overflow-x:hidden}</style>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>document.addEventListener('DOMContentLoaded',function(){ if(window.qt&&qt.webChannelTransport){ new QWebChannel(qt.webChannelTransport,function(ch){ window.bsBridge=ch.objects.bridge; }); } });</script>"""


class Bridge(QObject):
    selected = Signal(str, str)
    visible = Signal(str)

    @Slot(str, str)
    def select(self, section_id: str, block_id: str) -> None:
        self.selected.emit(section_id, block_id)

    @Slot(str, str)
    def visibleSection(self, section_id: str, _unused: str = "") -> None:  # noqa: N802
        self.visible.emit(section_id)


class ResizeWatcher(QObject):
    """Calls ``callback`` (debounced) whenever the watched widget is resized."""

    def __init__(self, widget: QWidget, callback) -> None:
        super().__init__(widget)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(callback)
        widget.installEventFilter(self)

    def eventFilter(self, _obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Resize:
            self._timer.start()
        return False


def configure_view(view: QWebEngineView) -> None:
    s = view.settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
    s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
    s.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)
    view.page().setBackgroundColor(QColor(T.bg))


def write_preview(project, version_id: str, proposal: ProposalData, reduce_motion: bool = False) -> Path:
    """Preview HTML with right-sized cached media and the selection bridge."""
    path = project.cache_subdir("preview") / f"{version_id}.html"
    options = make_options(project, proposal.presentation, "preview", scale=1.6, quality="standard", reduce_motion=reduce_motion)
    options.extra_head = CHANNEL_JS
    document = render_html(proposal.presentation, options).replace("send('visible',cur)", "send('visibleSection',cur)")
    atomic_write_text(path, document)
    return path


class AssetPicker(QDialog):
    def __init__(self, parent: QWidget, project) -> None:
        super().__init__(parent)
        self.setWindowTitle("Replace image")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        lay.addWidget(label("Choose an asset from this project", "H2"))
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(150, 120))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setSpacing(6)
        for asset in project.list_assets(include_excluded=False, visual_only=True):
            item = QListWidgetItem(asset.filename)
            item.setData(Qt.ItemDataRole.UserRole, asset.id)
            thumb = thumbnail_path(project, asset)
            if thumb and thumb.exists():
                item.setIcon(QIcon(str(thumb)))
            item.setToolTip(ASSET_KINDS.get(asset.effective_kind, ""))
            self.list.addItem(item)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Use image")
        ok.setObjectName("Primary")
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def chosen(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None


class Inspector(QWidget):
    """Edits one section (stored as overrides; script content is protected)."""

    apply_changes = Signal(str, dict)
    action = Signal(str, str)  # (action, section id)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(330)
        self.setMaximumWidth(400)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(16, 14, 16, 16)
        self.lay.setSpacing(10)
        self.section_id: str | None = None
        self.locked = False
        self.show_placeholder()

    def show_placeholder(self) -> None:
        clear_layout(self.lay)
        self.lay.addWidget(label("Edit", "H2"))
        self.lay.addWidget(label("Click a section in the preview, or pick one from the list, to refine its text, images, colour or spacing. Edits are optional — the generated design is complete.", "Muted", wrap=True))
        self.lay.addStretch(1)

    def load(self, project, proposal: ProposalData, section_id: str, block_id: str = "") -> None:
        clear_layout(self.lay)
        sp = next((s for s in proposal.plan.sections if s.id == section_id), None)
        section = next((s for s in proposal.presentation.sections if s.plan_id == section_id), None)
        if sp is None:
            self.show_placeholder()
            return
        self.section_id = sp.id
        self.locked = sp.locked
        overrides = proposal.spec.overrides.get(sp.id, {})
        head = QHBoxLayout()
        head.addWidget(label(section_type(sp.type).title("en"), "H2"))
        head.addStretch(1)
        if sp.locked:
            head.addWidget(Badge("From script", T.warning))
        self.lay.addLayout(head)
        if sp.locked:
            self.lay.addWidget(label("This section's text, images and position come from GUIAO_PROJETO.txt. Changing them asks for confirmation.", "Faint", wrap=True))
        form = QFormLayout()
        form.setSpacing(8)
        self.title = QLineEdit(overrides.get("title", sp.title))
        self.subtitle = QLineEdit(overrides.get("subtitle", sp.subtitle))
        self.body = QPlainTextEdit(overrides.get("body", sp.body))
        self.body.setMinimumHeight(110)
        form.addRow("Title", self.title)
        form.addRow("Subtitle", self.subtitle)
        form.addRow("Text", self.body)
        self.lay.addLayout(form)

        self.lay.addWidget(section_title("Appearance"))
        bg_row = QHBoxLayout()
        self.bg_value = overrides.get("background")
        current_bg = self.bg_value or (section.background if section else "#FFFFFF")
        self.bg_button = QPushButton(current_bg)
        self.bg_button.setStyleSheet(f"QPushButton{{background:{current_bg};color:{'#000' if QColor(current_bg).lightness() > 140 else '#FFF'};border-radius:8px;}}")
        self.bg_button.clicked.connect(self._pick_bg)
        bg_row.addWidget(self.bg_button, 1)
        reset = QPushButton("Reset")
        reset.setObjectName("Ghost")
        reset.clicked.connect(self._reset_bg)
        bg_row.addWidget(reset)
        self.lay.addLayout(bg_row)
        self.spacing = QSlider(Qt.Orientation.Horizontal)
        self.spacing.setRange(60, 160)
        self.spacing.setValue(int(float(overrides.get("spacing", 1.0)) * 100))
        sp_row = QHBoxLayout()
        sp_row.addWidget(label("Spacing", "Muted"))
        sp_row.addWidget(self.spacing, 1)
        self.lay.addLayout(sp_row)
        self.hidden = QCheckBox("Hide this section")
        self.hidden.setChecked(bool(overrides.get("hidden", False)))
        self.lay.addWidget(self.hidden)

        self.images: list[str] = list(overrides.get("asset_ids", sp.asset_ids))
        self.focal: dict[str, list[float]] = dict(overrides.get("focal", {}))
        if self.images:
            self.lay.addWidget(section_title("Images"))
            for idx, aid in enumerate(self.images):
                asset = project.get_asset(aid)
                row = QHBoxLayout()
                t = Thumb(64, 48, radius=5, mode="contain")
                if asset:
                    t.set_path(thumbnail_path(project, asset))
                row.addWidget(t)
                info_col = QVBoxLayout()
                info_col.addWidget(label(asset.filename if asset else "(missing)", None))
                block = next((b for b in (section.blocks if section else []) if b.asset_id == aid), None)
                if block is not None and asset is not None:
                    shown = max(block.w, block.h * asset.aspect) if block.fit == "cover" else min(block.w - 2 * block.pad, (block.h - 2 * block.pad) * asset.aspect)
                    info_col.addWidget(label(f"{asset.width}×{asset.height}px · {block.fit}{f', {block.crop:.0%} cropped' if block.crop > 0.01 else ''} · shown ~{shown:.0f}px wide", "Faint", wrap=True))
                row.addLayout(info_col, 1)
                rep = QToolButton()
                rep.setIcon(icon("refresh"))
                rep.setToolTip("Replace with another asset…")
                rep.clicked.connect(lambda _=False, i=idx: self.action.emit(f"replace:{i}", sp.id))
                row.addWidget(rep)
                rm = QToolButton()
                rm.setIcon(icon("x"))
                rm.setToolTip("Remove from this section")
                rm.clicked.connect(lambda _=False, i=idx: self._remove_image(i))
                row.addWidget(rm)
                self.lay.addLayout(row)
                if block is not None and block.fit == "cover" and block.crop > 0.01:
                    fx, fy = self.focal.get(aid, list(block.focal))
                    sx, sy = QSlider(Qt.Orientation.Horizontal), QSlider(Qt.Orientation.Horizontal)
                    for s_, v_ in ((sx, fx), (sy, fy)):
                        s_.setRange(0, 100)
                        s_.setValue(int(v_))
                    sx.valueChanged.connect(lambda v, a=aid, other=sy: self.focal.__setitem__(a, [float(v), float(other.value())]))
                    sy.valueChanged.connect(lambda v, a=aid, other=sx: self.focal.__setitem__(a, [float(other.value()), float(v)]))
                    fr = QHBoxLayout()
                    fr.addWidget(label("Crop focus", "Faint"))
                    fr.addWidget(sx)
                    fr.addWidget(sy)
                    self.lay.addLayout(fr)
        if block_id and section is not None:
            blk = next((b for b in section.blocks if b.id == block_id), None)
            if blk is not None and blk.asset_id:
                asset = project.get_asset(blk.asset_id)
                if asset is not None:
                    self.lay.addWidget(section_title("Selected image"))
                    cls = (asset.analysis or {}).get("classification", {})
                    self.lay.addWidget(label(f"{asset.filename}\n{ASSET_KINDS.get(asset.effective_kind)} · {asset.kind_source} · {asset.width}×{asset.height}px\n{', '.join(cls.get('reasons', [])[:3])}", "Muted", wrap=True))

        apply_btn = button("Apply changes", "check", "Primary", on_click=self._emit_apply)
        self.lay.addWidget(apply_btn)
        row = QHBoxLayout()
        row.addWidget(button("Regenerate", "refresh", on_click=lambda: self.action.emit("regenerate", sp.id), tooltip="Re-compose this section with a different variation"))
        row.addWidget(button("Duplicate", "copy", "Ghost", on_click=lambda: self.action.emit("duplicate", sp.id)))
        self.lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(button("Move up", "arrow-up", "Ghost", on_click=lambda: self.action.emit("up", sp.id)))
        row2.addWidget(button("Move down", "arrow-down", "Ghost", on_click=lambda: self.action.emit("down", sp.id)))
        self.lay.addLayout(row2)
        self.lay.addStretch(1)

    def set_image(self, index: int, asset_id: str) -> None:
        if 0 <= index < len(self.images):
            self.images[index] = asset_id

    def _remove_image(self, index: int) -> None:
        if 0 <= index < len(self.images):
            self.images.pop(index)
            self._emit_apply()

    def _pick_bg(self) -> None:
        color = QColorDialog.getColor(QColor(self.bg_button.text()), self, "Section background")
        if color.isValid():
            self.bg_value = color.name().upper()
            self.bg_button.setText(self.bg_value)
            self.bg_button.setStyleSheet(f"QPushButton{{background:{self.bg_value};color:{'#000' if color.lightness() > 140 else '#FFF'};border-radius:8px;}}")

    def _reset_bg(self) -> None:
        self.bg_value = None
        self.bg_button.setText("Default")

    def _emit_apply(self) -> None:
        if self.section_id is None:
            return
        changes = {
            "title": self.title.text(),
            "subtitle": self.subtitle.text(),
            "body": self.body.toPlainText(),
            "background": self.bg_value,
            "spacing": round(self.spacing.value() / 100, 2),
            "hidden": self.hidden.isChecked(),
            "asset_ids": list(self.images),
            "focal": dict(self.focal),
        }
        self.apply_changes.emit(self.section_id, changes)


class FullscreenPreview(QWidget):
    def __init__(self, url: QUrl, zoom: float) -> None:
        super().__init__()
        self.setWindowTitle("Presentation preview")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = QWebEngineView()
        configure_view(self.view)
        self.view.load(url)
        self.view.setZoomFactor(zoom)
        lay.addWidget(self.view)
        QShortcut(QKeySequence("Esc"), self, activated=self.close)
        QShortcut(QKeySequence("F11"), self, activated=self.close)


class ViewerPage(QWidget):
    def __init__(self, state, actions) -> None:
        super().__init__()
        self.state, self.actions = state, actions
        self.version_id: str | None = None
        self.proposal: ProposalData | None = None
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self._restore_scroll: float | None = None
        self._fullscreen: FullscreenPreview | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setStyleSheet(f"background:{T.surface};border-bottom:1px solid {T.border};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 8, 16, 8)
        bl.setSpacing(6)
        self.picker = QComboBox()
        self.picker.setMinimumWidth(260)
        self.picker.currentIndexChanged.connect(self._picked)
        bl.addWidget(self.picker)
        self.family_badge = Badge("")
        bl.addWidget(self.family_badge)
        bl.addSpacing(10)
        bl.addWidget(tool_button("zoom-out", "Zoom out (Ctrl+-)", lambda: self._zoom(1 / 1.15)))
        self.zoom_label = label("100%", "Muted")
        self.zoom_label.setFixedWidth(44)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(self.zoom_label)
        bl.addWidget(tool_button("zoom-in", "Zoom in (Ctrl++)", lambda: self._zoom(1.15)))
        bl.addWidget(tool_button("fit-width", "Fit to width (Ctrl+0)", self.fit_width))
        bl.addWidget(tool_button("maximize", "Full screen (F11)", self.fullscreen))
        bl.addStretch(1)
        self.undo_btn = tool_button("undo", "Undo edit (Ctrl+Z)", self.undo)
        self.redo_btn = tool_button("redo", "Redo edit (Ctrl+Y)", self.redo)
        bl.addWidget(self.undo_btn)
        bl.addWidget(self.redo_btn)
        self.history_btn = tool_button("restore", "Restore an earlier state", None)
        self.history_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.history_menu = QMenu(self)
        self.history_menu.aboutToShow.connect(self._fill_history)
        self.history_btn.setMenu(self.history_menu)
        bl.addWidget(self.history_btn)
        bl.addWidget(tool_button("copy", "Copy all presentation text", self._copy_text))
        self.edit_toggle = QPushButton("Edit")
        self.edit_toggle.setCheckable(True)
        self.edit_toggle.setIcon(icon("edit"))
        self.edit_toggle.toggled.connect(lambda on: self.inspector.setVisible(on))
        bl.addWidget(self.edit_toggle)
        self.fam_btn = QPushButton("Family")
        self.fam_btn.setIcon(icon("layers"))
        fam_menu = QMenu(self)
        for fid in available_families():
            fam_menu.addAction(family_info(fid).name, lambda f=fid: self._apply_family(f))
        self.fam_btn.setMenu(fam_menu)
        bl.addWidget(self.fam_btn)
        bl.addWidget(button("Preferred", "flag", "Ghost", on_click=self._set_preferred, tooltip="Mark as the preferred / final version"))
        bl.addWidget(button("Canva", "external", "Ghost", tooltip="Export to Canva as an editable design",
                            on_click=lambda: self.version_id and self.state.export_canva.emit([self.version_id])))
        bl.addWidget(button("Export", "export", "Primary", on_click=lambda: self.version_id and self.state.export_versions.emit([self.version_id])))
        root.addWidget(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, 1)
        nav = QWidget()
        nl = QVBoxLayout(nav)
        nl.setContentsMargins(12, 12, 8, 12)
        nl.addWidget(label("SECTIONS", "Eyebrow"))
        self.sections = QListWidget()
        self.sections.setStyleSheet("QListWidget{border:none;background:transparent;}")
        self.sections.itemClicked.connect(self._section_clicked)
        nl.addWidget(self.sections, 1)
        self.quality = label("", "Faint", wrap=True)
        nl.addWidget(self.quality)
        nav.setMinimumWidth(200)
        nav.setMaximumWidth(280)
        split.addWidget(nav)

        self.stack = QStackedWidget()
        self.loading = EmptyState("sparkles", "Preparing preview…", "Rendering the presentation with full-quality typography.")
        self.empty = EmptyState("eye", "No proposal selected", "Open a proposal from the Proposals page to preview it here.")
        self.view = QWebEngineView()
        configure_view(self.view)
        self.bridge = Bridge()
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.bridge.selected.connect(self._on_select)
        self.bridge.visible.connect(self._on_visible)
        self.view.loadFinished.connect(self._loaded)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.loading)
        self.stack.addWidget(self.view)
        split.addWidget(self.stack)
        self.inspector = Inspector()
        self.inspector.apply_changes.connect(self._apply)
        self.inspector.action.connect(self._inspector_action)
        self.inspector.hide()
        split.addWidget(self.inspector)
        split.setStretchFactor(1, 1)
        split.setSizes([210, 1000, 330])

        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self.redo)
        QShortcut(QKeySequence("Ctrl+0"), self, activated=self.fit_width)
        QShortcut(QKeySequence("Ctrl++"), self, activated=lambda: self._zoom(1.15))
        QShortcut(QKeySequence("Ctrl+="), self, activated=lambda: self._zoom(1.15))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self._zoom(1 / 1.15))
        QShortcut(QKeySequence("F11"), self, activated=self.fullscreen)
        state.versions_changed.connect(self._reload_picker)
        state.project_changed.connect(lambda _p: self.clear())
        self._auto_fit = True
        self._resize_watch = ResizeWatcher(self.view, lambda: self._auto_fit and self.fit_width())
        self._update_buttons()

    # ------------------------------------------------------------ loading
    def clear(self) -> None:
        self.version_id = None
        self.proposal = None
        self.stack.setCurrentWidget(self.empty)
        self.sections.clear()
        self._reload_picker()

    def _reload_picker(self) -> None:
        manager = self.state.versions
        self.picker.blockSignals(True)
        self.picker.clear()
        if manager is not None:
            for v in manager.list():
                self.picker.addItem(f"{v.number:03d} · {v.name}", v.id)
            if self.version_id:
                idx = self.picker.findData(self.version_id)
                if idx >= 0:
                    self.picker.setCurrentIndex(idx)
                else:
                    self.clear()
        self.picker.blockSignals(False)

    def _picked(self, index: int) -> None:
        vid = self.picker.itemData(index)
        if vid and vid != self.version_id:
            self.show_version(vid)

    def show_version(self, version_id: str) -> None:
        manager = self.state.versions
        if manager is None:
            return
        try:
            proposal = manager.load(version_id)
        except UserFacingError as exc:
            show_error(self, exc)
            return
        if version_id != self.version_id:
            self.undo_stack.clear()
            self.redo_stack.clear()
        self.version_id = version_id
        self.proposal = proposal
        self._reload_picker()
        info = family_info(proposal.spec.family)
        self.family_badge.setText(info.name)
        self.family_badge.setStyleSheet(f"background:{FAMILY_COLORS.get(info.id)};color:#0E0F11;border-radius:9px;padding:2px 8px;font-size:8pt;font-weight:600;")
        self._fill_sections()
        self._render_preview()
        self._update_buttons()

    def _fill_sections(self) -> None:
        self.sections.clear()
        if self.proposal is None:
            return
        overrides = self.proposal.spec.overrides
        hidden = {pid for pid, o in overrides.items() if o.get("hidden")}
        n = 0
        for sp in self.proposal.plan.sections:
            prefix = "◌ " if sp.id in hidden else ""
            title = overrides.get(sp.id, {}).get("title") or sp.title or section_type(sp.type).title("en")
            item = QListWidgetItem(f"{prefix}{title}")
            item.setData(Qt.ItemDataRole.UserRole, sp.id)
            item.setToolTip(f"{section_type(sp.type).title('en')}{' · from script' if sp.locked else ''}{' · hidden' if sp.id in hidden else ''}")
            if sp.locked:
                item.setIcon(icon("lock", T.warning))
            self.sections.addItem(item)
            n += 1
        q = self.proposal.quality
        self.quality.setText(f"Checks: {len(q.errors)} error(s), {len(q.warnings)} warning(s).\nAutomated checks are a technical aid, not an artistic judgement.")

    def _render_preview(self) -> None:
        if self.proposal is None or self.version_id is None:
            return
        project = self.state.project
        proposal, vid = self.proposal, self.version_id
        reduce_motion = self.state.settings.reduce_motion
        if self.stack.currentWidget() is not self.view:
            self.stack.setCurrentWidget(self.loading)

        def work(token, progress):
            return write_preview(project, vid, proposal, reduce_motion)

        self.state.runner.start(work, "preview", on_done=self._preview_ready, on_error=lambda e: show_error(self, e))

    def _preview_ready(self, path: Path) -> None:
        if self.stack.currentWidget() is self.view:
            self.view.page().runJavaScript("window.scrollY", 0, lambda y: setattr(self, "_restore_scroll", y))
        self.view.load(QUrl.fromLocalFile(str(path)))

    def _loaded(self, ok: bool) -> None:
        self.stack.setCurrentWidget(self.view)
        if self._restore_scroll:
            self.view.page().runJavaScript(f"window.scrollTo(0,{float(self._restore_scroll)})")
            self._restore_scroll = None
        else:
            QTimer.singleShot(30, self.fit_width)

    # ------------------------------------------------------------ zooming
    def _zoom(self, factor: float) -> None:
        self._auto_fit = False
        z = max(0.2, min(3.0, self.view.zoomFactor() * factor))
        self.view.setZoomFactor(z)
        self.zoom_label.setText(f"{z * 100:.0f}%")

    def fit_width(self) -> None:
        if self.proposal is None:
            return
        self._auto_fit = True
        width = max(200, self.view.width() - 18)
        z = max(0.2, min(3.0, width / self.proposal.presentation.width))
        self.view.setZoomFactor(z)
        self.zoom_label.setText(f"{z * 100:.0f}%")

    def fullscreen(self) -> None:
        if self.version_id is None or self.state.project is None:
            return
        path = self.state.project.cache_dir / "preview" / f"{self.version_id}.html"
        self._fullscreen = FullscreenPreview(QUrl.fromLocalFile(str(path)), 1.0)
        self._fullscreen.showFullScreen()
        screen = QGuiApplication.primaryScreen().size().width()
        self._fullscreen.view.setZoomFactor(max(0.3, min(2.0, screen / self.proposal.presentation.width)))

    # -------------------------------------------------------- navigation
    def _section_clicked(self, item: QListWidgetItem) -> None:
        pid = item.data(Qt.ItemDataRole.UserRole)
        sec = next((s for s in self.proposal.presentation.sections if s.plan_id == pid), None) if self.proposal else None
        if sec is not None:
            self.view.page().runJavaScript(f"window.bsScrollTo && bsScrollTo({json.dumps(sec.id)})")
        if self.edit_toggle.isChecked():
            self.inspector.load(self.state.project, self.proposal, pid)

    def _on_select(self, section_id: str, block_id: str) -> None:
        if self.proposal is None:
            return
        sec = next((s for s in self.proposal.presentation.sections if s.id == section_id), None)
        if sec is None or not sec.plan_id:
            return
        for i in range(self.sections.count()):
            if self.sections.item(i).data(Qt.ItemDataRole.UserRole) == sec.plan_id:
                self.sections.setCurrentRow(i)
        if not self.edit_toggle.isChecked():
            self.edit_toggle.setChecked(True)
        self.inspector.load(self.state.project, self.proposal, sec.plan_id, block_id)

    def _on_visible(self, section_id: str) -> None:
        if self.proposal is None:
            return
        sec = next((s for s in self.proposal.presentation.sections if s.id == section_id), None)
        if sec is None:
            return
        for i in range(self.sections.count()):
            item = self.sections.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == sec.plan_id:
                self.sections.blockSignals(True)
                self.sections.setCurrentRow(i)
                self.sections.blockSignals(False)

    # ------------------------------------------------------------ editing
    def _commit(self, new: ProposalData, label_text: str) -> None:
        """Save an edited proposal (with undo) and refresh the preview."""
        if self.proposal is None or self.version_id is None:
            return
        self.undo_stack.append(self.proposal.to_dict())
        self.redo_stack.clear()
        self._save(new, label_text)

    def _save(self, new: ProposalData, label_text: str) -> None:
        project, vid, browser = self.state.project, self.version_id, self.state.settings.browser_path
        self.proposal = new
        self._fill_sections()
        self._update_buttons()

        def work(token, progress):
            editing.save_and_preview(project, vid, new, label_text, browser)
            return write_preview(project, vid, new, self.state.settings.reduce_motion)

        self.state.runner.start(work, "save-edit", on_done=lambda path: (self._preview_ready(path), self.state.versions_changed.emit()), on_error=lambda e: show_error(self, e))

    def _run_edit(self, fn, label_text: str) -> None:
        if self.proposal is None:
            return
        try:
            new = fn(False)
        except ScriptError:
            if not confirm(self, "Override the project script?", "This change contradicts content fixed by GUIAO_PROJETO.txt.", "Override", detail="The script stays unchanged; this proposal will deviate from it and the change is noted in the proposal."):
                return
            try:
                new = fn(True)
            except UserFacingError as exc:
                show_error(self, exc)
                return
        except UserFacingError as exc:
            show_error(self, exc)
            return
        self._commit(new, label_text)

    def _apply(self, section_id: str, changes: dict) -> None:
        sp = next((s for s in self.proposal.plan.sections if s.id == section_id), None)
        if sp is None:
            return
        current = self.proposal.spec.overrides.get(section_id, {})
        effective = {}
        for key, value in changes.items():
            base = current.get(key, getattr(sp, key, None) if key in ("title", "subtitle", "body", "asset_ids") else None)
            if key == "spacing" and float(value) == float(current.get("spacing", 1.0)):
                continue
            if key == "hidden" and bool(value) == bool(current.get("hidden", False)):
                continue
            if key == "focal" and value == current.get("focal", {}):
                continue
            if key == "background" and value == current.get("background"):
                continue
            if key in ("title", "subtitle", "body", "asset_ids") and value == base:
                continue
            effective[key] = value
        if not effective:
            return
        self._run_edit(lambda allow: editing.edit_section(self.state.project, self.proposal, section_id, effective, allow_script_override=allow), f"Edit {sp.title}")

    def _inspector_action(self, action: str, section_id: str) -> None:
        project = self.state.project
        if action == "regenerate":
            self._run_edit(lambda _allow: editing.regenerate_section(project, self.proposal, section_id), "Regenerate section")
        elif action == "duplicate":
            self._run_edit(lambda _allow: editing.duplicate_section(project, self.proposal, section_id), "Duplicate section")
        elif action in ("up", "down"):
            self._run_edit(lambda allow: editing.move_section(project, self.proposal, section_id, -1 if action == "up" else 1, allow), "Move section")
        elif action.startswith("replace:"):
            index = int(action.split(":")[1])
            picker = AssetPicker(self, project)
            if picker.exec() and picker.chosen():
                self.inspector.set_image(index, picker.chosen())
                self.inspector._emit_apply()
        QTimer.singleShot(50, lambda: self.inspector.load(project, self.proposal, section_id) if self.proposal else None)

    def undo(self) -> None:
        if not self.undo_stack or self.proposal is None:
            return
        self.redo_stack.append(self.proposal.to_dict())
        self._save(ProposalData.from_dict(self.undo_stack.pop()), "Undo")

    def redo(self) -> None:
        if not self.redo_stack or self.proposal is None:
            return
        self.undo_stack.append(self.proposal.to_dict())
        self._save(ProposalData.from_dict(self.redo_stack.pop()), "Redo")

    def _update_buttons(self) -> None:
        self.undo_btn.setEnabled(bool(self.undo_stack))
        self.redo_btn.setEnabled(bool(self.redo_stack))
        has = self.proposal is not None
        for w in (self.edit_toggle, self.fam_btn, self.history_btn):
            w.setEnabled(has)

    def _fill_history(self) -> None:
        self.history_menu.clear()
        if not self.version_id:
            return
        states = self.state.versions.history(self.version_id)
        if not states:
            act = self.history_menu.addAction("No earlier states yet")
            act.setEnabled(False)
            return
        for state_id, ts, label_text in states[:20]:
            self.history_menu.addAction(f"{ts[:19].replace('T', ' ')} — before “{label_text}”", lambda s=state_id: self._restore_state(s))

    def _restore_state(self, state_id: str) -> None:
        try:
            self.undo_stack.append(self.proposal.to_dict())
            restored = self.state.versions.restore_state(self.version_id, state_id)
            self.proposal = restored
            self._fill_sections()
            self._render_preview()
            self.state.versions_changed.emit()
        except UserFacingError as exc:
            show_error(self, exc)

    def _apply_family(self, family: str) -> None:
        if self.proposal is None:
            return
        project = self.state.project
        manager = self.state.versions
        base_id = self.version_id
        proposal = self.proposal
        browser = self.state.settings.browser_path

        def work(token, progress):
            new = editing.apply_family(project, proposal, family)
            record = manager.create(new, parent_id=base_id)
            from behance_studio.render.previews import render_previews

            render_previews(project, [(new.presentation, manager.thumb_path(record), manager.strip_path(record))], browser_path=browser)
            return record.id

        self.state.runner.start(work, "apply-family", on_done=lambda vid: (self.state.versions_changed.emit(), self.show_version(vid)), on_error=lambda e: show_error(self, e))

    def _set_preferred(self) -> None:
        if self.version_id:
            self.state.versions.set_preferred(self.version_id)
            self.state.touch_library()
            self.state.versions_changed.emit()

    def _copy_text(self) -> None:
        if self.proposal is not None:
            QGuiApplication.clipboard().setText(presentation_text(self.proposal.presentation))
