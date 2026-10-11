"""Export Center."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from behance_studio.export.exporter import FORMATS, ExportOptions, export_versions, open_folder
from behance_studio.layout.families import family_info
from behance_studio.ui.dialogs.messages import info, show_error
from behance_studio.ui.widgets.common import PageHeader, button, label, section_title

FORMAT_HELP = {
    "pdf": "The long-form presentation, page sizes follow the design (best for Behance & sharing).",
    "pdf_a4": "Printable A4 pages; sections are paginated without cutting text.",
    "jpg": "Behance-ready images (sRGB). Long projects are split at section boundaries.",
    "png": "Lossless images.",
    "webp": "Small, high-quality images for the web (max 16,383 px per file).",
    "tiff": "Lossless archival images (LZW).",
    "html": "A self-contained web page with animations and video.",
    "zip": "One portable package with the formats above.",
    "text": "All presentation text as Markdown.",
}


class ExportPage(QWidget):
    def __init__(self, state, actions, toast) -> None:
        super().__init__()
        self.state, self.actions, self.toast = state, actions, toast
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(32, 26, 32, 24)
        root.setSpacing(16)
        header = PageHeader("Export", "PDF first: reliable, high-resolution and faithful to the preview. Every file is verified after it is written.", "Export Center")
        root.addWidget(header)

        cols = QHBoxLayout()
        cols.setSpacing(24)
        left = QVBoxLayout()
        left.addWidget(section_title("Proposals"))
        quick = QHBoxLayout()
        for text, mode in (("Preferred", "preferred"), ("Favourites", "favorites"), ("All", "all"), ("None", "none")):
            quick.addWidget(button(text, None, "Ghost", on_click=lambda _=False, m=mode: self._select(m)))
        quick.addStretch(1)
        left.addLayout(quick)
        self.versions = QListWidget()
        self.versions.setMinimumHeight(220)
        self.versions.itemChanged.connect(lambda _i: self._refresh_sections())
        left.addWidget(self.versions)
        left.addWidget(section_title("Sections (optional)"))
        self.sections = QListWidget()
        self.sections.setMaximumHeight(170)
        left.addWidget(self.sections)
        left.addWidget(label("Leave all sections checked to export the whole presentation. Section choice applies when one proposal is selected.", "Faint", wrap=True))
        cols.addLayout(left, 1)

        right = QVBoxLayout()
        right.addWidget(section_title("Formats"))
        grid = QGridLayout()
        self.format_checks: dict[str, QCheckBox] = {}
        for i, (fmt, text) in enumerate(FORMATS.items()):
            cb = QCheckBox(text)
            cb.setToolTip(FORMAT_HELP.get(fmt, ""))
            cb.setChecked(fmt in self.state.settings.export.formats)
            self.format_checks[fmt] = cb
            grid.addWidget(cb, i // 2, i % 2)
        right.addLayout(grid)
        right.addSpacing(6)
        right.addWidget(section_title("Settings"))
        form = QFormLayout()
        form.setSpacing(9)
        self.width = QComboBox()
        self.width.setEditable(True)
        for w in ("1400", "1920", "2100", "2800", "3200"):
            self.width.addItem(w)
        self.width.setCurrentText(str(self.state.settings.export.width))
        form.addRow("Image width (px)", self.width)
        self.quality = QComboBox()
        for key, text in (("standard", "Standard (smaller files)"), ("high", "High"), ("maximum", "Maximum (largest files)")):
            self.quality.addItem(text, key)
        self.quality.setCurrentIndex(max(0, self.quality.findData(self.state.settings.export.quality)))
        form.addRow("Image quality", self.quality)
        self.jpeg_quality = QSpinBox()
        self.jpeg_quality.setRange(60, 100)
        self.jpeg_quality.setValue(self.state.settings.export.jpeg_quality)
        form.addRow("JPG / WebP quality", self.jpeg_quality)
        self.long_mode = QComboBox()
        for key, text in (("auto", "Automatic"), ("continuous", "One continuous image"), ("segments", "Split into segments"), ("sections", "One image per section")):
            self.long_mode.addItem(text, key)
        self.long_mode.setCurrentIndex(max(0, self.long_mode.findData(self.state.settings.export.long_image_mode)))
        form.addRow("Long images", self.long_mode)
        self.segment = QSpinBox()
        self.segment.setRange(1000, 30000)
        self.segment.setSingleStep(500)
        self.segment.setValue(self.state.settings.export.segment_height)
        form.addRow("Segment height (px)", self.segment)
        self.a4_margins = QCheckBox("Add 12 mm margins to A4 pages")
        self.a4_margins.setChecked(self.state.settings.export.a4_margins)
        form.addRow("", self.a4_margins)
        self.pattern = QLineEdit(self.state.settings.export.filename_pattern)
        self.pattern.setToolTip("Tokens: {project} {proposal} {family} {number} {date}")
        form.addRow("File names", self.pattern)
        dest_row = QHBoxLayout()
        self.dest = QLineEdit()
        dest_row.addWidget(self.dest, 1)
        dest_row.addWidget(button("Browse…", "folder", "Ghost", on_click=self._browse))
        form.addRow("Destination", dest_row)
        self.open_after = QCheckBox("Open the folder when finished")
        self.open_after.setChecked(self.state.settings.export.open_folder_after)
        form.addRow("", self.open_after)
        right.addLayout(form)
        right.addSpacing(8)
        self.go = button("Export", "export", "Primary", on_click=self._export)
        self.go.setMinimumHeight(40)
        right.addWidget(self.go)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.hide()
        right.addWidget(self.progress)
        self.status = label("", "Muted", wrap=True)
        right.addWidget(self.status)
        right.addStretch(1)
        cols.addLayout(right, 1)
        root.addLayout(cols)

        root.addWidget(section_title("Export history"))
        self.history = QTableWidget(0, 4)
        self.history.setHorizontalHeaderLabels(["When", "Proposal", "Format", "File"])
        self.history.horizontalHeader().setStretchLastSection(True)
        self.history.verticalHeader().hide()
        self.history.setMinimumHeight(180)
        self.history.cellDoubleClicked.connect(self._open_history)
        root.addWidget(self.history)
        state.project_changed.connect(lambda _p: self.refresh())
        state.versions_changed.connect(self.refresh)

    def showEvent(self, event) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(event)

    def preselect(self, ids: list[str]) -> None:
        self.refresh()
        for i in range(self.versions.count()):
            item = self.versions.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in ids else Qt.CheckState.Unchecked)

    def refresh(self) -> None:
        project = self.state.project
        checked = set(self._checked_ids())
        self.versions.blockSignals(True)
        self.versions.clear()
        if project is None:
            self.versions.blockSignals(False)
            return
        if not self.dest.text() or not Path(self.dest.text()).parent.exists():
            self.dest.setText(self.state.settings.last_export_dir or str(project.exports_dir))
        manager = self.state.versions
        preferred = project.config.preferred_version_id
        for v in manager.list():
            text = f"{v.number:03d} · {v.name}  —  {family_info(v.family).name}" + ("  ★" if v.favorite else "") + ("  (preferred)" if v.id == preferred else "")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, v.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            state = v.id in checked or (not checked and v.id == preferred)
            item.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
            self.versions.addItem(item)
        self.versions.blockSignals(False)
        self._refresh_sections()
        self._refresh_history()

    def _checked_ids(self) -> list[str]:
        return [self.versions.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.versions.count()) if self.versions.item(i).checkState() == Qt.CheckState.Checked]

    def _select(self, mode: str) -> None:
        project = self.state.project
        if project is None:
            return
        manager = self.state.versions
        records = {v.id: v for v in manager.list()}
        for i in range(self.versions.count()):
            item = self.versions.item(i)
            vid = item.data(Qt.ItemDataRole.UserRole)
            on = {"all": True, "none": False, "preferred": vid == project.config.preferred_version_id, "favorites": records[vid].favorite}[mode]
            item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _refresh_sections(self) -> None:
        self.sections.clear()
        ids = self._checked_ids()
        if len(ids) != 1:
            self.sections.setEnabled(False)
            return
        self.sections.setEnabled(True)
        try:
            proposal = self.state.versions.load(ids[0])
        except Exception:  # noqa: BLE001
            return
        for s in proposal.presentation.sections:
            if s.type == "divider":
                continue
            item = QListWidgetItem(s.title or s.type)
            item.setData(Qt.ItemDataRole.UserRole, s.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.sections.addItem(item)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export to", self.dest.text())
        if folder:
            self.dest.setText(folder)

    def _export(self) -> None:
        project = self.state.project
        if project is None:
            return
        ids = self._checked_ids()
        formats = [f for f, cb in self.format_checks.items() if cb.isChecked()]
        if not ids or not formats:
            show_error(self, "Choose at least one proposal and one format.")
            return
        try:
            width = int(self.width.currentText())
            if not 200 <= width <= 10000:
                raise ValueError
        except ValueError:
            show_error(self, "Enter an image width between 200 and 10,000 pixels.")
            return
        section_ids = None
        if self.sections.isEnabled() and self.sections.count():
            chosen = [self.sections.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.sections.count()) if self.sections.item(i).checkState() == Qt.CheckState.Checked]
            if not chosen:
                show_error(self, "Choose at least one section.")
                return
            if len(chosen) < self.sections.count():
                section_ids = chosen
        destination = Path(self.dest.text() or project.exports_dir)
        s = self.state.settings
        s.export.formats = formats
        s.export.width = width
        s.export.quality = self.quality.currentData()
        s.export.long_image_mode = self.long_mode.currentData()
        s.export.segment_height = self.segment.value()
        s.export.jpeg_quality = self.jpeg_quality.value()
        s.export.a4_margins = self.a4_margins.isChecked()
        s.export.filename_pattern = self.pattern.text() or "{project} - {proposal}"
        s.export.open_folder_after = self.open_after.isChecked()
        s.last_export_dir = str(destination)
        self.state.save_settings()
        options = ExportOptions(
            formats=formats, destination=destination, width=width, quality=s.export.quality, long_image_mode=s.export.long_image_mode,
            segment_height=s.export.segment_height, jpeg_quality=s.export.jpeg_quality, filename_pattern=s.export.filename_pattern,
            section_ids=section_ids, a4_margins=s.export.a4_margins, browser_path=s.browser_path, reduce_motion=s.reduce_motion,
        )
        self.go.setEnabled(False)
        self.progress.show()
        self.progress.setValue(0)
        self.status.setText("Exporting…")

        def work(token, progress):
            return export_versions(project, ids, options, token, progress)

        def done(report) -> None:
            self.go.setEnabled(True)
            self.progress.hide()
            self.status.setText(report.summary())
            self._refresh_history()
            if report.failures:
                info(self, "Export finished with problems", report.summary(), "\n".join(f"• {n} — {f}: {m}" for n, f, m in report.failures[:10]))
            else:
                self.toast(report.summary())
            if report.files and self.open_after.isChecked():
                open_folder(destination)

        def progress_cb(event) -> None:
            if event.fraction is not None:
                self.progress.setValue(int(event.fraction * 1000))
            if event.message:
                self.status.setText(event.message)

        self.state.runner.start(work, "export", on_done=done, on_error=lambda e: (self.go.setEnabled(True), self.progress.hide(), show_error(self, e, "Export failed")), on_progress=progress_cb)

    def _refresh_history(self) -> None:
        project = self.state.project
        self.history.setRowCount(0)
        if project is None:
            return
        names = {v.id: v.name for v in project.list_versions(include_trashed=True)}
        for rec in project.list_exports()[:200]:
            row = self.history.rowCount()
            self.history.insertRow(row)
            for col, text in enumerate((rec.created_at[:16].replace("T", " "), names.get(rec.version_id, "—"), rec.format.upper(), rec.path)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.history.setItem(row, col, item)
        self.history.resizeColumnsToContents()

    def _open_history(self, row: int, _col: int) -> None:
        path = Path(self.history.item(row, 3).text())
        open_folder(path if path.is_dir() else path.parent)
