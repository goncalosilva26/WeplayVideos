"""Shared UI state: the open project and change notifications."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from behance_studio.core.settings import SettingsStore, get_settings_store
from behance_studio.projects.library import ProjectLibrary
from behance_studio.projects.store import Project
from behance_studio.projects.versions import VersionManager
from behance_studio.ui.worker import TaskRunner


class AppState(QObject):
    project_changed = Signal(object)  # Project | None
    assets_changed = Signal()
    versions_changed = Signal()
    texts_changed = Signal()
    settings_changed = Signal()
    open_version = Signal(str)  # request to show a version in the viewer
    compare_versions = Signal(list)
    export_versions = Signal(list)
    navigate = Signal(str)  # page id
    busy_changed = Signal(bool)

    def __init__(self, settings: SettingsStore | None = None) -> None:
        super().__init__()
        self.settings_store = settings or get_settings_store()
        self.library = ProjectLibrary()
        self.runner = TaskRunner(self.settings.worker_count())
        self.runner.busy_changed.connect(self.busy_changed)
        self.project: Project | None = None

    @property
    def settings(self):
        return self.settings_store.settings

    def save_settings(self) -> None:
        self.settings_store.save()
        self.settings_changed.emit()

    @property
    def versions(self) -> VersionManager | None:
        return VersionManager(self.project) if self.project else None

    def set_project(self, project: Project | None) -> None:
        self.project = project
        if project is not None:
            self.touch_library()
        self.project_changed.emit(project)

    def open_project(self, path: Path) -> Project:
        project = Project.open(path)
        project.refresh_missing()
        self.set_project(project)
        return project

    def touch_library(self) -> None:
        if self.project is not None:
            thumb = ""
            manager = VersionManager(self.project)
            preferred = manager.preferred() or next(iter(manager.list()), None)
            if preferred is not None:
                path = manager.thumb_path(preferred)
                thumb = str(path) if path.exists() else ""
            self.library.register(self.project, thumbnail=thumb)
