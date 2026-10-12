"""Application-wide preferences persisted as JSON in the user data folder.

Secrets (API keys) are never stored here; see ``behance_studio.ai.credentials``.
"""

from __future__ import annotations

import dataclasses
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from behance_studio.core.fsutil import atomic_write_json, read_json
from behance_studio.core.logging_setup import get_logger
from behance_studio.core.paths import default_projects_dir, user_data_dir

log = get_logger(__name__)

# 2.0 concepts (the default) followed by the classic v1 layouts.
DEFAULT_FAMILIES = ["minimal", "bold", "photo", "layered", "story"]
CLASSIC_FAMILIES = ["editorial", "cinematic", "split", "posters", "gallery", "modular"]
ALL_FAMILIES = DEFAULT_FAMILIES + CLASSIC_FAMILIES
SETTINGS_VERSION = 2


@dataclass
class AISettings:
    provider: str = "none"  # none | openai | anthropic | local
    base_url: str = ""
    model: str = ""
    timeout_s: float = 60.0
    max_retries: int = 2
    # Privacy: images are only sent when this is enabled *and* the project
    # has granted consent (see ProjectConfig.ai_consent).
    allow_image_upload: bool = False
    use_for_classification: bool = True
    use_for_copywriting: bool = True
    use_for_brief: bool = True
    use_for_evaluation: bool = False


@dataclass
class ExportDefaults:
    formats: list[str] = field(default_factory=lambda: ["pdf"])
    width: int = 1400
    quality: str = "high"  # standard | high | maximum
    long_image_mode: str = "auto"  # auto | continuous | segments | sections
    segment_height: int = 8000
    filename_pattern: str = "{project} - {proposal}"
    open_folder_after: bool = True
    a4_margins: bool = False
    jpeg_quality: int = 92


@dataclass
class AppSettings:
    projects_dir: str = ""
    copy_assets_on_import: bool = True
    presentation_language: str = "en"
    design_width: int = 1400
    proposal_count: int = 5
    families: list[str] = field(default_factory=lambda: list(DEFAULT_FAMILIES))
    creativity: float = 0.5
    worker_threads: int = 0  # 0 = automatic
    browser_path: str = ""
    cache_limit_mb: int = 4096
    reduce_motion: bool = False
    ai: AISettings = field(default_factory=AISettings)
    export: ExportDefaults = field(default_factory=ExportDefaults)
    window_geometry: str = ""
    last_import_dir: str = ""
    last_export_dir: str = ""
    onboarding_done: bool = False
    settings_version: int = SETTINGS_VERSION

    def resolved_projects_dir(self) -> Path:
        path = Path(self.projects_dir) if self.projects_dir else default_projects_dir()
        return path.expanduser()

    def worker_count(self) -> int:
        if self.worker_threads > 0:
            return self.worker_threads
        return max(2, min(8, (os.cpu_count() or 4) - 1))

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        return _from_dict(cls, data or {})


def _from_dict(cls: type, data: dict[str, Any]) -> Any:
    kwargs: dict[str, Any] = {}
    hints = {f.name: f for f in dataclasses.fields(cls)}
    for name, fdef in hints.items():
        if name not in data:
            continue
        value = data[name]
        default = (
            fdef.default_factory()  # type: ignore[misc]
            if fdef.default_factory is not dataclasses.MISSING
            else fdef.default
        )
        if dataclasses.is_dataclass(default) and isinstance(value, dict):
            kwargs[name] = _from_dict(type(default), value)
        elif default is dataclasses.MISSING or value is None:
            continue
        elif isinstance(default, bool):
            kwargs[name] = bool(value)
        elif isinstance(default, int) and not isinstance(default, bool):
            try:
                kwargs[name] = int(value)
            except (TypeError, ValueError):
                pass
        elif isinstance(default, float):
            try:
                kwargs[name] = float(value)
            except (TypeError, ValueError):
                pass
        elif isinstance(default, list) and isinstance(value, list):
            kwargs[name] = list(value)
        elif isinstance(default, str):
            kwargs[name] = str(value)
    return cls(**kwargs)


class SettingsStore:
    """Loads and saves :class:`AppSettings`; tolerant of corrupt files."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (user_data_dir() / "settings.json")
        self._lock = threading.Lock()
        self.settings = self.load()

    def load(self) -> AppSettings:
        try:
            data = read_json(self.path, default={})
        except (ValueError, OSError) as exc:
            log.warning("Settings file unreadable (%s); using defaults", exc)
            backup = self.path.with_suffix(".corrupt.json")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            data = {}
        settings = AppSettings.from_dict(data if isinstance(data, dict) else {})
        if isinstance(data, dict) and data and int(data.get("settings_version", 1)) < 2:
            # Upgrading from 1.x: generate the five 2.0 concepts by default;
            # the classic layouts stay available in Settings.
            settings.families = list(DEFAULT_FAMILIES)
            settings.proposal_count = len(DEFAULT_FAMILIES)
            settings.settings_version = SETTINGS_VERSION
        settings.families = [f for f in settings.families if f in ALL_FAMILIES] or list(DEFAULT_FAMILIES)
        return settings

    def save(self) -> None:
        with self._lock:
            atomic_write_json(self.path, self.settings.to_dict())


_store: SettingsStore | None = None


def get_settings_store() -> SettingsStore:
    global _store
    if _store is None:
        _store = SettingsStore()
    return _store


def reset_settings_store_for_tests() -> None:
    global _store
    _store = None
