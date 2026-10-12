"""Export to Canva: choose proposals and options, then open the result in Canva."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from behance_studio.canva.connect import CanvaConnect
from behance_studio.canva.export import CanvaOptions, export_to_canva
from behance_studio.export.exporter import open_folder
from behance_studio.layout.families import family_info
from behance_studio.ui.dialogs.messages import show_error
from behance_studio.ui.widgets.common import button, label, section_title

CANVA_HOME = "https://www.canva.com/"
PAGE_SIZES = [(0, "Automatic (fewest cuts, recommended)"), (1400, "1400 × 1400 px (square pages)"), (1800, "1400 × 1800 px"),
              (2400, "1400 × 2400 px"), (-1, "Custom height…")]


class CanvaExportDialog(QDialog):
    def __init__(self, state, version_ids: list[str], parent=None, toast=lambda m: None) -> None:
        super().__init__(parent)
        self.state, self.toast = state, toast
        self.setWindowTitle("Export to Canva")
        self.setMinimumWidth(640)
        self._task = None
        self.report = None
        s = state.settings
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addWidget(label("Export to Canva", "H2"))
        root.addWidget(label("Creates a Canva design in which every text box, picture and shape stays separately editable, "
                             "laid out exactly like the proposal. Long presentations are split into pages of one size "
                             "without cutting text.", "Muted", wrap=True))

        root.addWidget(section_title("Proposals"))
        self.versions = QListWidget()
        self.versions.setMaximumHeight(150)
        project = state.project
        for v in state.versions.list():
            item = QListWidgetItem(f"{v.number:03d} · {v.name} — {family_info(v.family).name}")
            item.setData(Qt.ItemDataRole.UserRole, v.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if v.id in version_ids else Qt.CheckState.Unchecked)
            self.versions.addItem(item)
        root.addWidget(self.versions)
        quick = QHBoxLayout()
        quick.addWidget(button("All proposals (whole project)", None, "Ghost", on_click=lambda: self._check_all(True)))
        quick.addWidget(button("None", None, "Ghost", on_click=lambda: self._check_all(False)))
        quick.addStretch(1)
        root.addLayout(quick)
        self.combine = QCheckBox("Put all selected proposals in one Canva design (otherwise one design each)")
        root.addWidget(self.combine)

        root.addWidget(section_title("Options"))
        form = QFormLayout()
        self.pages = QComboBox()
        for value, text in PAGE_SIZES:
            self.pages.addItem(text, value)
        self.custom = QSpinBox()
        self.custom.setRange(800, 6000)
        self.custom.setSingleStep(100)
        self.custom.setSuffix(" px")
        self.custom.setValue(s.canva.page_height or 2000)
        page_row = QHBoxLayout()
        page_row.addWidget(self.pages, 1)
        page_row.addWidget(self.custom)
        index = self.pages.findData(s.canva.page_height)
        self.pages.setCurrentIndex(index if index >= 0 else len(PAGE_SIZES) - 1)
        self.pages.currentIndexChanged.connect(lambda _i: self.custom.setVisible(self.pages.currentData() == -1))
        self.custom.setVisible(self.pages.currentData() == -1)
        form.addRow("Page size", page_row)
        self.mode = QComboBox()
        self.mode.addItem("Exact look — masks and gradients drawn into their picture (recommended)", "exact")
        self.mode.addItem("Maximum editability — masks and gradients as shape properties", "editable")
        self.mode.setCurrentIndex(max(0, self.mode.findData(s.canva.mode)))
        form.addRow("Effects", self.mode)
        self.quality = QComboBox()
        for key, text in (("standard", "Standard (smaller file)"), ("high", "High (sharp on retina screens)"), ("maximum", "Maximum")):
            self.quality.addItem(text, key)
        self.quality.setCurrentIndex(max(0, self.quality.findData(s.canva.quality)))
        form.addRow("Picture quality", self.quality)
        self.check = QCheckBox("Compare the exported pages with the original and report the match")
        self.check.setChecked(s.canva.check)
        form.addRow("", self.check)
        dest_row = QHBoxLayout()
        self.dest = QLineEdit(s.last_export_dir or (str(project.exports_dir) if project else ""))
        dest_row.addWidget(self.dest, 1)
        dest_row.addWidget(button("Browse…", "folder", "Ghost", on_click=self._browse))
        form.addRow("Save files in", dest_row)
        root.addLayout(form)

        root.addWidget(section_title("Then"))
        client = CanvaConnect.from_settings(s)
        self.connected = client.connected
        account = s.canva.account_name
        self.upload = QRadioButton(f"Open it in my Canva account{' (' + account + ')' if account else ''} — imported automatically")
        self.manual = QRadioButton("Save the file; I will import it in Canva (drag it onto canva.com)")
        self.upload.setEnabled(self.connected)
        (self.upload if self.connected and s.canva.upload else self.manual).setChecked(True)
        root.addWidget(self.upload)
        root.addWidget(self.manual)
        if not self.connected:
            root.addWidget(label("To open designs in Canva automatically, connect your account in Settings → Canva (optional).", "Faint", wrap=True))

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.hide()
        root.addWidget(self.progress)
        self.status = label("", "Muted", wrap=True)
        root.addWidget(self.status)
        self.results = QVBoxLayout()
        root.addLayout(self.results)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_btn = button("Close", None, "Ghost", on_click=self._close)
        self.go = button("Export to Canva", "external", "Primary", on_click=self._export)
        buttons.addWidget(self.close_btn)
        buttons.addWidget(self.go)
        root.addLayout(buttons)

    # ----------------------------------------------------------- helpers
    def _check_all(self, on: bool) -> None:
        for i in range(self.versions.count()):
            self.versions.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def checked_ids(self) -> list[str]:
        return [self.versions.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.versions.count())
                if self.versions.item(i).checkState() == Qt.CheckState.Checked]

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save Canva files in", self.dest.text())
        if folder:
            self.dest.setText(folder)

    def options(self) -> CanvaOptions:
        page = self.pages.currentData()
        height = self.custom.value() if page == -1 else (page or None)
        project = self.state.project
        return CanvaOptions(
            destination=Path(self.dest.text() or project.exports_dir), page_height=height, mode=self.mode.currentData(),
            quality=self.quality.currentData(), combine=self.combine.isChecked(), upload=self.upload.isChecked() and self.connected,
            check=self.check.isChecked(), browser_path=self.state.settings.browser_path,
            filename_pattern=self.state.settings.export.filename_pattern,
        )

    def _remember(self, options: CanvaOptions) -> None:
        c = self.state.settings.canva
        c.page_height = int(options.page_height or 0)
        c.mode, c.quality, c.check = options.mode, options.quality, options.check
        if self.connected:
            c.upload = self.upload.isChecked()
        self.state.settings.last_export_dir = str(options.destination)
        self.state.save_settings()

    # ------------------------------------------------------------ export
    def _export(self) -> None:
        project = self.state.project
        ids = self.checked_ids()
        if project is None or not ids:
            show_error(self, "Choose at least one proposal.")
            return
        options = self.options()
        self._remember(options)
        client = CanvaConnect.from_settings(self.state.settings) if options.upload else None
        self.go.setEnabled(False)
        self.close_btn.setText("Cancel")
        self.progress.show()
        self.progress.setValue(0)
        self.status.setText("Preparing…")

        def work(token, progress):
            return export_to_canva(project, ids, options, client=client, token=token, progress=progress)

        def progress_cb(event) -> None:
            if event.fraction is not None:
                self.progress.setValue(int(event.fraction * 1000))
            if event.message:
                self.status.setText(event.message)

        self._task = self.state.runner.start(work, "canva-export", on_done=self._done, on_error=self._failed, on_progress=progress_cb,
                                             on_cancel=lambda: self._finish("Cancelled."))

    def _finish(self, text: str) -> None:
        self._task = None
        self.go.setEnabled(True)
        self.close_btn.setText("Close")
        self.progress.hide()
        self.status.setText(text)

    def _failed(self, exc) -> None:
        self._finish("")
        show_error(self, exc, "Export to Canva failed")

    def _done(self, report) -> None:
        self.report = report
        self._finish(report.summary())
        while self.results.count():
            item = self.results.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for d in report.designs:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            check = f" · {d.similarity * 100:.1f}% match" if d.similarity is not None else ""
            lay.addWidget(label(f"{d.name}: {d.pages} page(s) of {d.page_size[0]} × {d.page_size[1]} px{check}", None, wrap=True), 1)
            if d.edit_url:
                lay.addWidget(button("Open in Canva", "external", "Primary", on_click=lambda _=False, u=d.edit_url: QDesktopServices.openUrl(QUrl(u))))
            lay.addWidget(button("Report", "file-text", "Ghost", on_click=lambda _=False, p=d.report: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))))
            lay.addWidget(button("Show file", "folder", "Ghost", on_click=lambda _=False, p=d.pptx: open_folder(p.parent)))
            self.results.addWidget(row)
        for name, message in report.failures:
            self.results.addWidget(label(f"⚠ {name}: {message}", "Muted", wrap=True))
        manual = [d for d in report.designs if not d.edit_url]
        if manual:
            self.results.addWidget(label("Import in Canva: open canva.com and drag the .pptx file onto the home page "
                                         "(or Create a design → Import file).", "Faint", wrap=True))
            self.results.addWidget(button("Open canva.com", "external", "Ghost", on_click=lambda: QDesktopServices.openUrl(QUrl(CANVA_HOME))))
            if self.state.settings.canva.open_after:
                open_folder(manual[0].pptx.parent)
        elif report.designs and self.state.settings.canva.open_after:
            QDesktopServices.openUrl(QUrl(report.designs[0].edit_url))
        if report.designs:
            self.toast(report.summary())

    def _close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            return
        self.accept()
