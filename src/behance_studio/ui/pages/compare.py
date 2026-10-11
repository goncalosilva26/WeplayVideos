"""Side-by-side comparison of two or three proposals."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QPushButton, QSplitter, QVBoxLayout, QWidget

from behance_studio.layout.families import family_info
from behance_studio.ui.dialogs.messages import show_error
from behance_studio.ui.pages.viewer import ResizeWatcher, configure_view, write_preview
from behance_studio.ui.theme import FAMILY_COLORS, T
from behance_studio.ui.widgets.common import Badge, EmptyState, PageHeader, button, label


class ComparePane(QWidget):
    def __init__(self, page: "ComparePage", index: int) -> None:
        super().__init__()
        self.page, self.index = page, index
        self.version_id: str | None = None
        self.width_px = 1400
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.picker = QComboBox()
        self.picker.currentIndexChanged.connect(self._picked)
        top.addWidget(self.picker, 1)
        self.badge = Badge("")
        top.addWidget(self.badge)
        lay.addLayout(top)
        self.view = QWebEngineView()
        configure_view(self.view)
        self.view.loadFinished.connect(lambda _ok: QTimer.singleShot(30, self.fit))
        self.view.page().scrollPositionChanged.connect(self._scrolled)
        self._resize_watch = ResizeWatcher(self.view, self.fit)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addWidget(button("Open", "eye", "Ghost", on_click=lambda: self.version_id and self.page.state.open_version.emit(self.version_id)))
        row.addWidget(button("Favourite", "star", "Ghost", on_click=self._favorite))
        row.addStretch(1)
        row.addWidget(button("Choose this one", "flag", "Primary", on_click=self._prefer))
        lay.addLayout(row)

    def fill(self, versions, selected: str | None) -> None:
        self.picker.blockSignals(True)
        self.picker.clear()
        for v in versions:
            self.picker.addItem(f"{v.number:03d} · {v.name}", v.id)
        if selected:
            idx = self.picker.findData(selected)
            if idx >= 0:
                self.picker.setCurrentIndex(idx)
        self.picker.blockSignals(False)
        vid = self.picker.currentData()
        if vid:
            self.load(vid)

    def _picked(self, _i: int) -> None:
        vid = self.picker.currentData()
        if vid:
            self.load(vid)

    def load(self, vid: str) -> None:
        state = self.page.state
        self.version_id = vid
        try:
            proposal = state.versions.load(vid)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        self.width_px = proposal.presentation.width
        info = family_info(proposal.spec.family)
        self.badge.setText(info.name)
        self.badge.setStyleSheet(f"background:{FAMILY_COLORS.get(info.id)};color:#0E0F11;border-radius:9px;padding:2px 8px;font-size:8pt;font-weight:600;")
        project = state.project
        state.runner.start(lambda token, progress: write_preview(project, vid, proposal, True), "compare-preview", on_done=lambda path: self.view.load(QUrl.fromLocalFile(str(path))), on_error=lambda e: show_error(self, e))

    def fit(self) -> None:
        self.view.setZoomFactor(max(0.15, (self.view.width() - 18) / self.width_px))

    def _scrolled(self, pos: QPointF) -> None:
        self.page.on_scrolled(self, pos.y())

    def _favorite(self) -> None:
        if self.version_id:
            rec = self.page.state.versions.get(self.version_id)
            self.page.state.versions.set_favorite(self.version_id, not rec.favorite)
            self.page.state.versions_changed.emit()

    def _prefer(self) -> None:
        if self.version_id:
            self.page.state.versions.set_preferred(self.version_id)
            self.page.state.touch_library()
            self.page.state.versions_changed.emit()
            self.page.toast(f"Preferred version set: {self.picker.currentText()}")


class ComparePage(QWidget):
    def __init__(self, state, actions, toast) -> None:
        super().__init__()
        self.state, self.actions, self.toast = state, actions, toast
        self._syncing = False
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 16)
        root.setSpacing(12)
        header = PageHeader("Compare", "Scroll one proposal and the others follow — or turn synchronisation off to explore freely.", "Proposals")
        self.sync = QCheckBox("Synchronised scrolling")
        self.sync.setChecked(True)
        header.add_action(self.sync)
        self.three = QPushButton("Three columns")
        self.three.setCheckable(True)
        self.three.toggled.connect(self._columns)
        header.add_action(self.three)
        root.addWidget(header)
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.panes = [ComparePane(self, i) for i in range(3)]
        for pane in self.panes:
            self.split.addWidget(pane)
        self.panes[2].hide()
        self.empty = EmptyState("compare", "Nothing to compare yet", "Generate at least two proposals, then select two or three in the Proposals page and choose Compare.")
        root.addWidget(self.split, 1)
        root.addWidget(self.empty, 1)
        state.project_changed.connect(lambda _p: self.show_versions([]))

    def _columns(self, on: bool) -> None:
        self.panes[2].setVisible(on)
        if on and self.state.versions:
            versions = self.state.versions.list()
            self.panes[2].fill(versions, versions[2].id if len(versions) > 2 else None)
        QTimer.singleShot(50, lambda: [p.fit() for p in self.panes if p.isVisible()])

    def show_versions(self, ids: list[str]) -> None:
        manager = self.state.versions
        versions = manager.list() if manager else []
        has = len(versions) >= 2
        self.split.setVisible(has)
        self.empty.setVisible(not has)
        if not has:
            return
        ids = list(ids) or [v.id for v in versions[:2]]
        if len(ids) < 2:
            ids.append(next(v.id for v in versions if v.id not in ids))
        self.three.blockSignals(True)
        self.three.setChecked(len(ids) >= 3)
        self.three.blockSignals(False)
        self.panes[2].setVisible(len(ids) >= 3)
        for pane, vid in zip(self.panes, ids):
            pane.fill(versions, vid)

    def showEvent(self, event) -> None:  # noqa: N802
        if not any(p.version_id for p in self.panes):
            self.show_versions([])
        super().showEvent(event)

    def on_scrolled(self, source: ComparePane, y: float) -> None:
        if self._syncing or not self.sync.isChecked():
            return
        self._syncing = True
        try:
            ratio_js = "(document.documentElement.scrollHeight - window.innerHeight) || 1"
            source.view.page().runJavaScript(f"window.scrollY / ({ratio_js})", 0, lambda r: self._apply_ratio(source, r))
        finally:
            QTimer.singleShot(60, lambda: setattr(self, "_syncing", False))

    def _apply_ratio(self, source: ComparePane, ratio) -> None:
        try:
            ratio = float(ratio)
        except (TypeError, ValueError):
            return
        for pane in self.panes:
            if pane is source or not pane.isVisible():
                continue
            pane.view.page().runJavaScript(f"window.scrollTo(0, {ratio} * ((document.documentElement.scrollHeight - window.innerHeight) || 1))")
