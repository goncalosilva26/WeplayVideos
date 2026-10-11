"""Settings: folders, generation, rendering, AI, export, performance, diagnostics."""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from behance_studio import APP_NAME, __version__
from behance_studio.ai.credentials import get_api_key, set_api_key, storage_description
from behance_studio.ai.providers import DEFAULT_MODELS, DEFAULT_URLS
from behance_studio.core.fsutil import dir_size, human_size
from behance_studio.core.logging_setup import log_file_path
from behance_studio.core.paths import logs_dir
from behance_studio.export.exporter import open_folder
from behance_studio.layout.families import available_families, family_info
from behance_studio.ui.dialogs.messages import confirm, info, show_error
from behance_studio.ui.widgets.common import PageHeader, button, label, section_title

PROVIDERS = [
    ("none", "None — offline only (default)"),
    ("openai", "OpenAI-compatible API (OpenAI, OpenRouter, Azure…)"),
    ("anthropic", "Anthropic API (Claude)"),
    ("local", "Local model (Ollama / LM Studio, OpenAI-compatible)"),
]


class SettingsPage(QWidget):
    def __init__(self, state, actions, toast) -> None:
        super().__init__()
        self.state, self.actions, self.toast = state, actions, toast
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        body.setMaximumWidth(1080)
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(32, 26, 32, 30)
        root.setSpacing(14)
        header = PageHeader("Settings", "Sensible defaults work out of the box; everything here is optional.", "Preferences")
        header.add_action(button("Save settings", "check", "Primary", on_click=self.save))
        root.addWidget(header)
        s = state.settings

        # ---------------------------------------------------------- general
        root.addWidget(section_title("Projects"))
        form = QFormLayout()
        form.setSpacing(9)
        row = QHBoxLayout()
        self.projects_dir = QLineEdit(str(s.resolved_projects_dir()))
        row.addWidget(self.projects_dir, 1)
        row.addWidget(button("Browse…", "folder", "Ghost", on_click=self._browse_projects))
        form.addRow("Projects folder", row)
        self.copy_assets = QCheckBox("Copy imported files into the project (recommended — originals are never modified either way)")
        self.copy_assets.setChecked(s.copy_assets_on_import)
        form.addRow("", self.copy_assets)
        self.language = QComboBox()
        self.language.addItem("English", "en")
        self.language.addItem("Português", "pt")
        self.language.setCurrentIndex(max(0, self.language.findData(s.presentation_language)))
        form.addRow("Default presentation language", self.language)
        root.addLayout(form)

        # -------------------------------------------------------- generation
        root.addWidget(section_title("Generation"))
        form = QFormLayout()
        form.setSpacing(9)
        self.count = QSpinBox()
        self.count.setRange(1, 24)
        self.count.setValue(s.proposal_count)
        form.addRow("Proposals per generation", self.count)
        self.creativity = QSlider(Qt.Orientation.Horizontal)
        self.creativity.setRange(0, 100)
        self.creativity.setValue(int(s.creativity * 100))
        form.addRow("Creative variation", self.creativity)
        self.width = QComboBox()
        for w in ("1200", "1400", "1600", "1920"):
            self.width.addItem(w)
        self.width.setCurrentText(str(s.design_width))
        form.addRow("Design width (px)", self.width)
        fam_row = QHBoxLayout()
        self.families: dict[str, QCheckBox] = {}
        for fid in available_families():
            cb = QCheckBox(family_info(fid).name)
            cb.setChecked(fid in s.families)
            self.families[fid] = cb
            fam_row.addWidget(cb)
        fam_row.addStretch(1)
        form.addRow("Families", fam_row)
        self.reduce_motion = QCheckBox("Reduce motion in previews (no autoplay, no marquees)")
        self.reduce_motion.setChecked(s.reduce_motion)
        form.addRow("", self.reduce_motion)
        root.addLayout(form)

        # --------------------------------------------------------- rendering
        root.addWidget(section_title("Rendering"))
        form = QFormLayout()
        row = QHBoxLayout()
        self.browser = QLineEdit(s.browser_path)
        self.browser.setPlaceholderText("Automatic (bundled Chromium, then Microsoft Edge / Google Chrome)")
        row.addWidget(self.browser, 1)
        row.addWidget(button("Browse…", "folder", "Ghost", on_click=self._browse_browser))
        row.addWidget(button("Test", "check-circle", "Ghost", on_click=self._test_browser))
        form.addRow("Rendering browser", row)
        root.addLayout(form)

        # ---------------------------------------------------------------- AI
        root.addWidget(section_title("AI assistance (optional)"))
        root.addWidget(label("Without a provider, Behance Studio works fully offline using measured image analysis and heuristics. "
                             "A multimodal AI provider can improve asset recognition and draft copy. Requests to cloud providers may be billed by the provider. "
                             "Images are only sent when you enable it here AND allow it for a project.", "Faint", wrap=True))
        form = QFormLayout()
        form.setSpacing(9)
        self.provider = QComboBox()
        for key, text in PROVIDERS:
            self.provider.addItem(text, key)
        self.provider.setCurrentIndex(max(0, self.provider.findData(s.ai.provider)))
        self.provider.currentIndexChanged.connect(self._provider_changed)
        form.addRow("Provider", self.provider)
        self.base_url = QLineEdit(s.ai.base_url)
        form.addRow("API address", self.base_url)
        self.model = QLineEdit(s.ai.model)
        form.addRow("Model", self.model)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Not stored" if not get_api_key(s.ai.provider) else "•••••••• (stored securely)")
        form.addRow("API key", self.api_key)
        self.key_info = label(storage_description(), "Faint", wrap=True)
        form.addRow("", self.key_info)
        self.allow_images = QCheckBox("Allow sending downscaled asset previews for analysis (each project must also allow it)")
        self.allow_images.setChecked(s.ai.allow_image_upload)
        form.addRow("", self.allow_images)
        self.ai_classify = QCheckBox("Recognise asset types")
        self.ai_classify.setChecked(s.ai.use_for_classification)
        self.ai_copy = QCheckBox("Draft section descriptions (never facts, metrics or awards)")
        self.ai_copy.setChecked(s.ai.use_for_copywriting)
        self.ai_brief = QCheckBox("Interpret the creative brief")
        self.ai_brief.setChecked(s.ai.use_for_brief)
        for cb in (self.ai_classify, self.ai_copy, self.ai_brief):
            form.addRow("", cb)
        self.project_consent = QCheckBox("Allow AI assistance for the current project (sends its brief and, if allowed above, small previews)")
        form.addRow("", self.project_consent)
        test_row = QHBoxLayout()
        test_row.addWidget(button("Test connection", "cpu", on_click=self._test_ai))
        test_row.addStretch(1)
        form.addRow("", test_row)
        root.addLayout(form)

        # ------------------------------------------------------- performance
        root.addWidget(section_title("Performance & storage"))
        form = QFormLayout()
        self.threads = QSpinBox()
        self.threads.setRange(0, 32)
        self.threads.setSpecialValueText("Automatic")
        self.threads.setValue(s.worker_threads)
        form.addRow("Worker threads", self.threads)
        cache_row = QHBoxLayout()
        self.cache_label = label("", "Muted")
        cache_row.addWidget(self.cache_label, 1)
        cache_row.addWidget(button("Clear project cache", "trash", "Ghost", on_click=self._clear_cache))
        form.addRow("Current project cache", cache_row)
        root.addLayout(form)

        # ------------------------------------------------------- diagnostics
        root.addWidget(section_title("Diagnostics"))
        self.diag = QPlainTextEdit()
        self.diag.setReadOnly(True)
        self.diag.setFont(QFont("JetBrains Mono", 9))
        self.diag.setMinimumHeight(170)
        root.addWidget(self.diag)
        row = QHBoxLayout()
        row.addWidget(button("Open log folder", "folder", "Ghost", on_click=lambda: open_folder(logs_dir())))
        row.addWidget(button("Copy report", "copy", "Ghost", on_click=lambda: QGuiApplication.clipboard().setText(self.diag.toPlainText())))
        row.addWidget(button("Refresh", "refresh", "Ghost", on_click=self._diagnostics))
        row.addStretch(1)
        root.addLayout(row)
        root.addStretch(1)
        for form in body.findChildren(QFormLayout):
            form.setHorizontalSpacing(18)
            for i in range(form.rowCount()):
                item = form.itemAt(i, QFormLayout.ItemRole.LabelRole)
                if item is not None and item.widget() is not None:
                    item.widget().setFixedWidth(200)
        state.project_changed.connect(lambda _p: self._load_project_bits())

    def showEvent(self, event) -> None:  # noqa: N802
        self._load_project_bits()
        self._diagnostics()
        super().showEvent(event)

    def _load_project_bits(self) -> None:
        project = self.state.project
        self.project_consent.setEnabled(project is not None)
        self.project_consent.setChecked(bool(project and project.config.ai_consent))
        self.cache_label.setText(human_size(dir_size(project.cache_dir)) if project else "No project open")

    def _provider_changed(self) -> None:
        key = self.provider.currentData()
        if key in DEFAULT_URLS and not self.base_url.text():
            self.base_url.setText(DEFAULT_URLS[key])
        if key in DEFAULT_MODELS and not self.model.text():
            self.model.setText(DEFAULT_MODELS[key])
        self.api_key.setPlaceholderText("Not stored" if not get_api_key(key) else "•••••••• (stored securely)")

    def _browse_projects(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Projects folder", self.projects_dir.text())
        if folder:
            self.projects_dir.setText(folder)

    def _browse_browser(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose chrome.exe / msedge.exe")
        if path:
            self.browser.setText(path)

    def _test_browser(self) -> None:
        from behance_studio.render import browser as browser_mod

        browser_mod._browser_cache.clear()
        found = browser_mod.find_browser(self.browser.text().strip())
        if not found:
            show_error(self, "No usable browser was found. Run the setup script again or install Microsoft Edge / Google Chrome.")
            return
        try:
            with browser_mod.BrowserSession(self.browser.text().strip()):
                pass
            info(self, "Rendering works", f"Using:\n{found}")
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)

    def _test_ai(self) -> None:
        self.save(quiet=True)
        from behance_studio.ai.providers import create_provider

        try:
            provider = create_provider(self.state.settings)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc, "AI is not ready")
            return
        if provider is None:
            info(self, "AI is off", "Choose a provider first.")
            return
        self.toast("Testing the connection…")
        self.state.runner.start(
            lambda token, progress: provider.test_connection(),
            "ai-test",
            on_done=lambda message: info(self, "Connection works", message),
            on_error=lambda exc: show_error(self, exc, "Connection failed"),
        )

    def _clear_cache(self) -> None:
        project = self.state.project
        if project is None:
            return
        if not confirm(self, "Clear cache", "Delete thumbnails, previews and other regenerable files for this project?", "Clear cache", detail="Assets, proposals and exports are not affected. Thumbnails will be rebuilt when needed."):
            return
        for sub in ("derived", "preview", "proxies", "staging", "html-video"):
            shutil.rmtree(project.cache_dir / sub, ignore_errors=True)
        self._load_project_bits()
        self.toast("Cache cleared")

    def _diagnostics(self) -> None:
        from behance_studio.assets.media import ffmpeg_exe
        from behance_studio.render.browser import find_browser

        try:
            ff = ffmpeg_exe()
        except Exception as exc:  # noqa: BLE001
            ff = f"missing ({exc})"
        from PySide6 import __version__ as qt

        lines = [
            f"{APP_NAME} {__version__}",
            f"Python {sys.version.split()[0]} · {platform.platform()}",
            f"PySide6 {qt}",
            f"Browser: {find_browser(self.state.settings.browser_path) or 'NOT FOUND'}",
            f"FFmpeg: {ff}",
            f"Projects: {self.state.settings.resolved_projects_dir()}",
            f"Log file: {log_file_path()}",
            f"AI provider: {self.state.settings.ai.provider}",
        ]
        try:
            tail = Path(log_file_path()).read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
            lines += ["", "Recent log:"] + tail
        except OSError:
            pass
        self.diag.setPlainText("\n".join(lines))

    def save(self, quiet: bool = False) -> None:
        s = self.state.settings
        s.projects_dir = self.projects_dir.text().strip()
        s.copy_assets_on_import = self.copy_assets.isChecked()
        s.presentation_language = self.language.currentData()
        s.proposal_count = self.count.value()
        s.creativity = self.creativity.value() / 100
        try:
            s.design_width = max(800, min(2400, int(self.width.currentText())))
        except ValueError:
            pass
        fams = [f for f, cb in self.families.items() if cb.isChecked()]
        s.families = fams or list(available_families())
        s.reduce_motion = self.reduce_motion.isChecked()
        s.browser_path = self.browser.text().strip()
        s.ai.provider = self.provider.currentData()
        s.ai.base_url = self.base_url.text().strip()
        s.ai.model = self.model.text().strip()
        s.ai.allow_image_upload = self.allow_images.isChecked()
        s.ai.use_for_classification = self.ai_classify.isChecked()
        s.ai.use_for_copywriting = self.ai_copy.isChecked()
        s.ai.use_for_brief = self.ai_brief.isChecked()
        s.worker_threads = self.threads.value()
        if self.api_key.text().strip():
            where = set_api_key(s.ai.provider, self.api_key.text().strip())
            self.api_key.clear()
            self.api_key.setPlaceholderText("•••••••• (stored securely)" if where == "keyring" else "•••••••• (this session only)")
        project = self.state.project
        if project is not None and project.config.ai_consent != self.project_consent.isChecked():
            project.config.ai_consent = self.project_consent.isChecked()
            project.save_config()
        self.state.save_settings()
        from behance_studio.render import browser as browser_mod

        browser_mod._browser_cache.clear()
        if not quiet:
            self.toast("Settings saved")
