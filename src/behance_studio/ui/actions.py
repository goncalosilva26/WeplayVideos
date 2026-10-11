"""High-level user actions shared by pages (with progress and errors)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QFileDialog, QWidget

from behance_studio.ai.service import service_for_project
from behance_studio.assets.formats import FILE_DIALOG_FILTER
from behance_studio.assets.importer import import_paths
from behance_studio.core.errors import UserFacingError
from behance_studio.generation.pipeline import STAGE_LABELS, STAGES, GenerationRequest, GenerationResult, generate
from behance_studio.projects.store import Project
from behance_studio.ui.dialogs.messages import info, show_error
from behance_studio.ui.dialogs.new_project import NewProjectDialog
from behance_studio.ui.dialogs.progress import ProgressDialog
from behance_studio.ui.state import AppState


class Actions(QObject):
    def __init__(self, state: AppState, window: QWidget, toast: Callable[[str], None]) -> None:
        super().__init__()
        self.state = state
        self.window = window
        self.toast = toast

    # ------------------------------------------------------------ projects
    def new_project(self, initial_paths: list[str] | None = None, name: str = "") -> None:
        dialog = NewProjectDialog(self.window, self.state.settings.resolved_projects_dir(), initial_paths, name)
        if not dialog.exec():
            return
        v = dialog.values()
        try:
            project = Project.create(v["projects_dir"], v["name"], copy_assets=self.state.settings.copy_assets_on_import)
        except UserFacingError as exc:
            show_error(self.window, exc)
            return
        if v["brief"].strip():
            project.write_text("brief", v["brief"])
        if v["script"].strip():
            project.write_text("script", v["script"])
        if v["language"] != "auto":
            project.config.language = v["language"]
            project.save_config()
        self.state.set_project(project)
        self.state.navigate.emit("workspace")
        after = (lambda: self.generate()) if v["generate"] else None
        if v["paths"]:
            self.import_assets(v["paths"], after=after)
        elif after:
            info(self.window, "Add assets first", "The project was created. Add some images to generate proposals.")

    def open_project_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self.window, "Open a Behance Studio project", str(self.state.settings.resolved_projects_dir()))
        if folder:
            self.open_project(Path(folder))

    def open_project(self, path: Path) -> None:
        try:
            self.state.open_project(path)
            self.state.navigate.emit("workspace")
        except UserFacingError as exc:
            show_error(self.window, exc, "Cannot open project")

    def import_folder_as_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(self.window, "Choose a folder of project material")
        if folder:
            self.new_project([folder], name=Path(folder).name)

    def create_demo(self) -> None:
        tools = Path(__file__).resolve().parents[3] / "tools"
        sys.path.insert(0, str(tools))
        try:
            from make_demo_assets import build_demo_assets
        except ImportError:
            show_error(self.window, "The demo generator is not available in this installation.")
            return
        base = self.state.settings.resolved_projects_dir()

        def work(token, progress):
            progress(0.1, "Drawing the Butter & Bean demo assets…")
            target = base / "_demo assets" / "Butter & Bean"
            if not target.exists():
                build_demo_assets(target)
            return target

        dlg = ProgressDialog(self.window, "Preparing the demo project")
        task = self.state.runner.start(work, "demo", on_done=lambda target: (dlg.finish(), QTimer.singleShot(0, lambda: self.new_project([str(target)], name="Butter & Bean"))), on_error=lambda e: (dlg.reject(), show_error(self.window, e)), on_progress=dlg.update_progress)
        dlg.cancel_requested.connect(task.cancel)
        dlg.exec()

    # -------------------------------------------------------------- assets
    def add_assets_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self.window, "Add assets", self.state.settings.last_import_dir, FILE_DIALOG_FILTER)
        if files:
            self.state.settings.last_import_dir = str(Path(files[0]).parent)
            self.state.save_settings()
            self.import_assets(files)

    def add_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self.window, "Add a folder of assets", self.state.settings.last_import_dir)
        if folder:
            self.import_assets([folder])

    def import_assets(self, paths: list[str], after: Callable[[], None] | None = None) -> None:
        project = self.state.project
        if project is None:
            self.new_project(paths)
            return
        workers = self.state.settings.worker_count()
        dlg = ProgressDialog(self.window, "Importing assets")

        def work(token, progress):
            return import_paths(project, [Path(p) for p in paths], token=token, progress=progress, workers=workers)

        def done(report) -> None:
            dlg.finish()
            self.state.assets_changed.emit()
            if report.brief_imported or report.script_imported:
                self.state.texts_changed.emit()
            message = report.summary()
            details = []
            for path, msg in report.errors[:8]:
                details.append(f"• {Path(path).name}: {msg}")
            if report.project_texts_ignored:
                details.append("• A brief/script file was found but the project already has one; it was not replaced.")
            if report.errors or report.project_texts_ignored:
                info(self.window, "Import finished", message, "\n".join(details))
            else:
                self.toast(message)
            if after is not None and project.list_assets(visual_only=True):
                QTimer.singleShot(0, after)

        task = self.state.runner.start(work, "import", on_done=done, on_error=lambda e: (dlg.reject(), show_error(self.window, e)), on_progress=dlg.update_progress, on_cancel=lambda: (dlg.reject(), self.state.assets_changed.emit(), self.toast("Import cancelled")))
        dlg.cancel_requested.connect(task.cancel)
        dlg.exec()

    # ---------------------------------------------------------- generation
    def generate(self, families: list[str] | None = None, count: int = 0, creativity: float | None = None, seed: int | None = None) -> None:
        project = self.state.project
        if project is None:
            return
        settings = self.state.settings
        request = GenerationRequest(
            families=families or list(project.config.generation.families or settings.families),
            count=count or project.config.generation.proposal_count or settings.proposal_count,
            creativity=settings.creativity if creativity is None else creativity,
            width=settings.design_width,
            seed=seed,
            browser_path=settings.browser_path,
            workers=settings.worker_count(),
        )
        ai = None
        try:
            ai = service_for_project(project, settings)
        except Exception:  # noqa: BLE001 - AI is optional
            ai = None
        dlg = ProgressDialog(self.window, "Generating proposals", [(s, STAGE_LABELS[s]) for s in STAGES])

        def work(token, progress):
            return generate(project, request, token=token, progress=progress, ai_service=ai)

        def done(result: GenerationResult) -> None:
            dlg.finish()
            self.state.versions_changed.emit()
            self.state.touch_library()
            notes = [f"• {i.message}" for i in result.script_issues if i.severity == "error"]
            notes += [f"• {family}: {msg}" for family, _seed, msg in result.failures]
            if notes:
                info(self.window, f"{len(result.versions)} proposal(s) generated", "Some items need your attention:", "\n".join(notes[:10]))
            else:
                self.toast(f"{len(result.versions)} proposals generated in {result.elapsed:.0f}s")
            QTimer.singleShot(0, lambda: self.state.navigate.emit("gallery"))

        task = self.state.runner.start(work, "generate", on_done=done, on_error=lambda e: (dlg.reject(), show_error(self.window, e, "Generation stopped")), on_progress=dlg.update_progress, on_cancel=lambda: (dlg.reject(), self.state.versions_changed.emit(), self.toast("Generation cancelled")))
        dlg.cancel_requested.connect(task.cancel)
        dlg.exec()
