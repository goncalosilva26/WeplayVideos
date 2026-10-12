"""Settings: folders, generation, rendering, AI, export, performance, diagnostics."""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
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
from behance_studio.ai.costs import PRICES_AS_OF, UsageLedger, resolve_prices
from behance_studio.ai.ollama import RECOMMENDED
from behance_studio.ai.providers import ANTHROPIC_MODELS, DEFAULT_MODELS, DEFAULT_URLS
from behance_studio.core.fsutil import dir_size, human_size
from behance_studio.core.logging_setup import log_file_path
from behance_studio.core.paths import logs_dir
from behance_studio.export.exporter import open_folder
from behance_studio.layout.families import available_families, family_info
from behance_studio.ui.dialogs.messages import confirm, info, show_error
from behance_studio.ui.widgets.common import PageHeader, button, label, section_title

PROVIDERS = [
    ("ollama", "Ollama — free local AI on this PC (recommended)"),
    ("none", "None — offline only"),
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
        from PySide6.QtWidgets import QGridLayout

        from behance_studio.layout.families import CONCEPT_FAMILIES

        self.families: dict[str, QCheckBox] = {}
        for title, group in (("Concepts", [f for f in available_families() if f in CONCEPT_FAMILIES]),
                             ("Classic layouts", [f for f in available_families() if f not in CONCEPT_FAMILIES])):
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            for i, fid in enumerate(group):
                cb = QCheckBox(family_info(fid).name)
                cb.setChecked(fid in s.families)
                cb.setToolTip(family_info(fid).tagline)
                self.families[fid] = cb
                grid.addWidget(cb, i // 3, i % 3)
            form.addRow(title, grid)
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
        root.addWidget(label("Recommended: Ollama runs a vision model on this PC — free, no account, nothing leaves your computer. "
                             "It recognises what each image is for, plans the five concepts and can critique the result. Without AI, "
                             "Behance Studio still works fully offline (measured image analysis and a rules-based director). Cloud "
                             "providers are optional and billed by the provider: you see the estimate before every paid generation, "
                             "and images are only sent when you enable it here AND allow it for a project.", "Faint", wrap=True))
        form = QFormLayout()
        form.setSpacing(9)
        self.provider = QComboBox()
        for key, text in PROVIDERS:
            self.provider.addItem(text, key)
        self.provider.setCurrentIndex(max(0, self.provider.findData(s.ai.provider)))
        self.provider.currentIndexChanged.connect(self._provider_changed)
        form.addRow("Provider", self.provider)
        self.ollama_box = self._ollama_panel()
        form.addRow("Local AI", self.ollama_box)
        self.base_url = QLineEdit(s.ai.base_url)
        self.base_url.setPlaceholderText(DEFAULT_URLS.get(s.ai.provider, ""))
        form.addRow("API address", self.base_url)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(self._model_suggestions(s.ai.provider))
        self.model.setCurrentText(s.ai.model or DEFAULT_MODELS.get(s.ai.provider, ""))
        self.model.currentTextChanged.connect(lambda _t: self._update_price_info())
        form.addRow("Model", self.model)
        self.price_info = label("", "Faint", wrap=True)
        form.addRow("", self.price_info)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Not stored" if not get_api_key(s.ai.provider) else "•••••••• (stored securely)")
        form.addRow("API key", self.api_key)
        self.key_info = label(storage_description(), "Faint", wrap=True)
        form.addRow("", self.key_info)
        self.allow_images = QCheckBox("Allow sending downscaled asset previews for analysis (each project must also allow it)")
        self.allow_images.setChecked(s.ai.allow_image_upload)
        form.addRow("", self.allow_images)
        if s.ai.provider == "ollama":
            for widget in (self.api_key, self.key_info, self.allow_images):
                widget.setEnabled(False)  # no key needed; previews never leave this PC
        self.ai_classify = QCheckBox("Recognise asset types")
        self.ai_classify.setChecked(s.ai.use_for_classification)
        self.ai_copy = QCheckBox("Draft section descriptions (never facts, metrics or awards)")
        self.ai_copy.setChecked(s.ai.use_for_copywriting)
        self.ai_brief = QCheckBox("Interpret the creative brief")
        self.ai_brief.setChecked(s.ai.use_for_brief)
        self.ai_direct = QCheckBox("Direct the five concepts (AI storyboards, validated; the offline director is the fallback)")
        self.ai_direct.setChecked(s.ai.use_for_direction)
        self.ai_critique = QCheckBox("Critique the rendered proposals (sends rendered previews; one bounded round of fixes)")
        self.ai_critique.setChecked(s.ai.use_for_evaluation)
        for cb in (self.ai_classify, self.ai_copy, self.ai_brief, self.ai_direct, self.ai_critique):
            form.addRow("", cb)
        self.run_limit = self._money(s.ai.run_limit_usd, "No limit")
        form.addRow("Limit per generation", self.run_limit)
        self.monthly_limit = self._money(s.ai.monthly_limit_usd, "No limit")
        form.addRow("Monthly limit", self.monthly_limit)
        price_row = QHBoxLayout()
        price_row.setSpacing(10)
        self.price_in = self._money(s.ai.price_input_per_mtok, "List price", 500.0)
        self.price_out = self._money(s.ai.price_output_per_mtok, "List price", 500.0)
        price_row.addWidget(label("Input", "Muted"))
        price_row.addWidget(self.price_in)
        price_row.addWidget(label("Output", "Muted"))
        price_row.addWidget(self.price_out)
        price_row.addStretch(1)
        form.addRow("Price per million tokens", price_row)
        self.confirm_paid = QCheckBox("Show the cost estimate and ask before every paid generation")
        self.confirm_paid.setChecked(s.ai.confirm_paid_runs)
        form.addRow("", self.confirm_paid)
        self.spend_info = label("", "Faint", wrap=True)
        form.addRow("", self.spend_info)
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
        if self.provider.currentData() == "ollama":
            self._check_ollama()
        super().showEvent(event)

    @staticmethod
    def _money(value: float, zero_text: str, maximum: float = 10_000.0) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(0.0, maximum)
        box.setDecimals(2)
        box.setSingleStep(0.5)
        box.setPrefix("$ ")
        box.setSpecialValueText(zero_text)
        box.setValue(float(value or 0.0))
        box.setMinimumWidth(130)
        box.setMaximumWidth(200)
        return box

    def _update_price_info(self) -> None:
        kind = self.provider.currentData()
        model = self.model.currentText().strip()
        if kind in (None, "none"):
            self.price_info.setText("")
            return
        from behance_studio.ai.providers import is_private_url

        local = kind in ("local", "ollama") and is_private_url(self.base_url.text().strip() or DEFAULT_URLS.get(kind, ""))
        prices = resolve_prices(kind, model, local)
        if prices is not None and prices.source == "free":
            self.price_info.setText("Runs on your computer or network: no charge.")
        elif prices is not None:
            self.price_info.setText(f"List price: ${prices.input_per_mtok:g} input / ${prices.output_per_mtok:g} output per million "
                                    f"tokens ({PRICES_AS_OF}). Enter your own prices below if they differ.")
        else:
            self.price_info.setText("Price unknown for this model: enter it below to see costs. While a spending limit is set, "
                                    "paid requests are not made without a price.")

    def _load_project_bits(self) -> None:
        project = self.state.project
        self.project_consent.setEnabled(project is not None)
        self.project_consent.setChecked(bool(project and project.config.ai_consent))
        self.cache_label.setText(human_size(dir_size(project.cache_dir)) if project else "No project open")
        month = UsageLedger().month()
        if month.get("requests"):
            cost = f"≈ ${float(month.get('cost', 0.0)):.2f}" if "cost" in month else "cost unknown"
            unpriced = f" ({month['unpriced_requests']} without a known price)" if month.get("unpriced_requests") else ""
            self.spend_info.setText(f"This month: {month['requests']} AI request(s), {cost}{unpriced}. Only counts and "
                                    "amounts are recorded, never content.")
        else:
            self.spend_info.setText("No AI requests this month.")
        self._update_price_info()

    def _provider_changed(self) -> None:
        key = self.provider.currentData()
        url = self.base_url.text().strip()
        self.base_url.setPlaceholderText(DEFAULT_URLS.get(key, ""))
        if url and url in DEFAULT_URLS.values() and key in DEFAULT_URLS:
            self.base_url.setText(DEFAULT_URLS[key])  # another provider's default: switch it too
        current = self.model.currentText()
        known = set(DEFAULT_MODELS.values()) | set(ANTHROPIC_MODELS) | {m.name for m in RECOMMENDED}
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(self._model_suggestions(key))
        self.model.setCurrentText(DEFAULT_MODELS.get(key, current) if (not current or current in known) else current)
        self.model.blockSignals(False)
        self._update_price_info()
        self.api_key.setPlaceholderText("Not stored" if not get_api_key(key) else "•••••••• (stored securely)")
        local = key == "ollama"
        self.ollama_box.setVisible(local)
        for widget in (self.api_key, self.key_info, self.allow_images):
            widget.setEnabled(not local)  # no key needed; previews never leave this PC
        if local:
            self._check_ollama()

    @staticmethod
    def _model_suggestions(key: str) -> list[str]:
        if key == "anthropic":
            return list(ANTHROPIC_MODELS)
        if key == "ollama":
            return [m.name for m in RECOMMENDED]
        return []

    # ----------------------------------------------------------- ollama
    def _ollama_panel(self) -> QFrame:
        box = QFrame()
        box.setObjectName("Card")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        self.ollama_status = label("Checking Ollama…", "H3", wrap=True)
        lay.addWidget(self.ollama_status)
        self.ollama_steps = label("", "Muted", wrap=True)
        self.ollama_steps.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.ollama_steps)
        row = QHBoxLayout()
        self.ollama_check = button("Check again", "refresh", "Ghost", on_click=self._check_ollama)
        self.ollama_get = button("Download Ollama", "external", "Ghost", on_click=self._open_ollama_download)
        self.ollama_start = button("Start Ollama", "play", "Ghost", on_click=self._start_ollama)
        self.ollama_pull = button("Download model", "download", "Primary", on_click=self._pull_model)
        self.ollama_copy = button("Copy command", "copy", "Ghost", on_click=self._copy_pull_command)
        for b in (self.ollama_check, self.ollama_get, self.ollama_start, self.ollama_pull, self.ollama_copy):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lines = [f"• {m.name} — {m.label}, ≈{m.download_gb:g} GB download, ≈{m.vram_gb:g} GB GPU memory. {m.note}" for m in RECOMMENDED[:3]]
        lay.addWidget(label("Models for an RTX 3060 12 GB:\n" + "\n".join(lines), "Faint", wrap=True))
        box.setVisible(self.state.settings.ai.provider == "ollama")
        self.state.local_ai_changed.connect(self._show_ollama_status)
        return box

    def _ollama_target(self) -> tuple[str, str]:
        from behance_studio.ai.ollama import DEFAULT_MODEL, DEFAULT_URL

        return self.base_url.text().strip() or DEFAULT_URL, self.model.currentText().strip() or DEFAULT_MODEL

    def _check_ollama(self) -> None:
        from behance_studio.ai.ollama import detect

        url, model = self._ollama_target()
        self.ollama_status.setText("Checking Ollama…")
        self.state.runner.start(lambda token, progress: detect(url, model), "ollama-check",
                                on_done=self._show_ollama_status, on_error=lambda e: self.ollama_status.setText(f"Check failed: {e}"))

    def _show_ollama_status(self, status) -> None:
        from behance_studio.ai.ollama import setup_steps

        if status is None or not hasattr(self, "ollama_status"):
            return
        self.ollama_status.setText(("✓ " if status.ready else "") + status.summary())
        steps = setup_steps(status)
        self.ollama_steps.setText("\n".join(f"{i}. {t}" for i, t in enumerate(steps, 1)) if steps else
                                  "Imported images are recognised automatically; the five concepts are planned with local AI. Free.")
        state = status.state
        self.ollama_get.setVisible(state == "not_installed")
        self.ollama_start.setVisible(state == "not_running" and bool(status.installed))
        self.ollama_pull.setVisible(state in ("model_missing",))
        self.ollama_copy.setVisible(state in ("not_installed", "model_missing"))
        if status.models:
            known = {self.model.itemText(i) for i in range(self.model.count())}
            extra = [m for m in status.models if m not in known]
            if extra:
                self.model.blockSignals(True)
                self.model.addItems(extra)
                self.model.blockSignals(False)

    def _open_ollama_download(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from behance_studio.ai.ollama import DOWNLOAD_URL

        QDesktopServices.openUrl(QUrl(DOWNLOAD_URL))

    def _copy_pull_command(self) -> None:
        _url, model = self._ollama_target()
        QApplication.clipboard().setText(f"ollama pull {model}")
        self.toast(f"Copied: ollama pull {model}")

    def _start_ollama(self) -> None:
        from behance_studio.ai.ollama import start_server

        url, _model = self._ollama_target()
        self.ollama_status.setText("Starting Ollama…")
        self.state.runner.start(lambda token, progress: start_server(url=url), "ollama-start",
                                on_done=lambda ok: (self.toast("Ollama started" if ok else "Ollama did not start"), self._check_ollama()),
                                on_error=lambda e: show_error(self, e, "Could not start Ollama"))

    def _pull_model(self) -> None:
        from behance_studio.ai.ollama import RECOMMENDED as models
        from behance_studio.ai.ollama import pull_model, same_model
        from behance_studio.ui.dialogs.progress import ProgressDialog

        url, model = self._ollama_target()
        size = next((m.download_gb for m in models if same_model(m.name, model)), None)
        if not confirm(self, "Download model", f"Download “{model}” through Ollama?", "Download",
                       detail=(f"About {size:g} GB, " if size else "") + "downloaded once and stored by Ollama. Free."):
            return
        dlg = ProgressDialog(self, f"Downloading {model}")

        def work(token, progress):
            pull_model(url, model, progress=lambda f, m: progress(f, m), cancelled=lambda: token.cancelled)
            return True

        task = self.state.runner.start(work, "ollama-pull",
                                       on_done=lambda _r: (dlg.finish(), self.toast(f"{model} is ready"), self._check_ollama()),
                                       on_error=lambda e: (dlg.reject(), show_error(self, e, "Download failed")),
                                       on_progress=dlg.update_progress)
        dlg.cancel_requested.connect(task.cancel)
        dlg.exec()

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
        s.ai.model = self.model.currentText().strip()
        s.ai.allow_image_upload = self.allow_images.isChecked()
        s.ai.use_for_classification = self.ai_classify.isChecked()
        s.ai.use_for_copywriting = self.ai_copy.isChecked()
        s.ai.use_for_brief = self.ai_brief.isChecked()
        s.ai.use_for_direction = self.ai_direct.isChecked()
        s.ai.use_for_evaluation = self.ai_critique.isChecked()
        s.ai.run_limit_usd = round(self.run_limit.value(), 2)
        s.ai.monthly_limit_usd = round(self.monthly_limit.value(), 2)
        s.ai.price_input_per_mtok = round(self.price_in.value(), 4)
        s.ai.price_output_per_mtok = round(self.price_out.value(), 4)
        s.ai.confirm_paid_runs = self.confirm_paid.isChecked()
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
