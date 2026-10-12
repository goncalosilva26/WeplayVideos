"""Persistent data model for projects, assets, proposal versions and exports."""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

PROJECT_SCHEMA_VERSION = 1

MEDIA_IMAGE = "image"
MEDIA_SVG = "svg"
MEDIA_GIF = "gif"
MEDIA_VIDEO = "video"
MEDIA_DOCUMENT = "document"
VISUAL_MEDIA = {MEDIA_IMAGE, MEDIA_SVG, MEDIA_GIF, MEDIA_VIDEO}

# Semantic asset kinds. They are *estimates* (heuristic or AI) unless the user
# sets them explicitly; ``kind_source`` records which.
ASSET_KINDS: dict[str, str] = {
    "logo": "Logo",
    "logo_variant": "Logo variant",
    "monogram": "Monogram / symbol",
    "palette": "Colour palette",
    "typography": "Typography",
    "pattern": "Pattern / graphic element",
    "illustration": "Illustration",
    "packaging": "Packaging",
    "poster": "Poster",
    "outdoor": "Outdoor advertising",
    "social": "Social media",
    "stationery": "Stationery / collateral",
    "editorial": "Editorial / publication",
    "mockup": "Mockup / application",
    "website": "Website",
    "mobile": "Mobile app",
    "ui": "Interface screen",
    "photo": "Photograph",
    "product": "Product photograph",
    "lifestyle": "Lifestyle photograph",
    "portrait": "Portrait",
    "before_after": "Before / after",
    "video": "Video",
    "motion": "Motion / animation",
    "document": "Document",
    "reference": "Reference / inspiration (never shown)",
    "other": "Other",
}

PHOTO_KINDS = {"photo", "product", "lifestyle", "portrait", "before_after"}
LOGO_KINDS = {"logo", "logo_variant", "monogram"}
UI_KINDS = {"website", "mobile", "ui"}
MOTION_KINDS = {"video", "motion"}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class AssetRecord:
    id: str
    media_type: str
    filename: str
    rel_path: str  # relative to project root (POSIX separators) or absolute when referenced
    source_path: str = ""
    import_group: str = ""  # relative folder within the imported folder
    size_bytes: int = 0
    sha256: str = ""
    phash: str = ""
    width: int = 0
    height: int = 0
    duration: float = 0.0
    fps: float = 0.0
    frame_count: int = 0
    has_alpha: bool = False
    animated: bool = False
    status: str = "ok"  # ok | corrupt | missing
    error: str = ""
    excluded: bool = False
    kind: str = "other"
    kind_confidence: float = 0.0
    kind_source: str = "heuristic"  # heuristic | ai | user
    user_kind: str | None = None
    tags: list[str] = field(default_factory=list)
    description: str = ""
    analysis: dict[str, Any] = field(default_factory=dict)
    roles: dict[str, float] = field(default_factory=dict)
    imported_at: str = field(default_factory=now_iso)
    order: int = 0

    @property
    def effective_kind(self) -> str:
        return self.user_kind or self.kind

    @property
    def aspect(self) -> float:
        if self.width > 0 and self.height > 0:
            return self.width / self.height
        return 1.0

    @property
    def is_visual(self) -> bool:
        return self.media_type in VISUAL_MEDIA and self.status == "ok"

    @property
    def orientation(self) -> str:
        if not self.width or not self.height:
            return "unknown"
        ratio = self.width / self.height
        if ratio > 1.08:
            return "landscape"
        if ratio < 0.92:
            return "portrait"
        return "square"

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssetRecord":
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class VersionRecord:
    id: str
    number: int
    name: str
    family: str
    seed: int
    folder: str  # relative to project root
    status: str = "active"  # active | trashed
    favorite: bool = False
    created_at: str = field(default_factory=now_iso)
    modified_at: str = field(default_factory=now_iso)
    trashed_at: str | None = None
    quality: float = 0.0
    parent_id: str | None = None
    notes: str = ""
    issues: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VersionRecord":
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class ExportRecord:
    id: str
    version_id: str
    format: str
    path: str
    created_at: str = field(default_factory=now_iso)
    status: str = "ok"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationDefaults:
    proposal_count: int = 6
    families: list[str] = field(default_factory=list)  # empty = all
    creativity: float = 0.5
    width: int = 1400
    seed_base: int = 0


@dataclass
class ProjectConfig:
    id: str
    name: str
    schema_version: int = PROJECT_SCHEMA_VERSION
    app_version: str = ""
    created_at: str = field(default_factory=now_iso)
    modified_at: str = field(default_factory=now_iso)
    language: str = "auto"  # auto | en | pt
    category_override: str | None = None
    generation: GenerationDefaults = field(default_factory=GenerationDefaults)
    ai_consent: bool = False
    preferred_version_id: str | None = None
    brief_file: str = "brief.txt"
    script_file: str = "GUIAO_PROJETO.txt"
    copy_assets: bool = True
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectConfig":
        names = {f.name for f in dataclasses.fields(cls)}
        payload = {k: v for k, v in data.items() if k in names}
        gen = payload.get("generation")
        if isinstance(gen, dict):
            gnames = {f.name for f in dataclasses.fields(GenerationDefaults)}
            payload["generation"] = GenerationDefaults(
                **{k: v for k, v in gen.items() if k in gnames}
            )
        else:
            payload.pop("generation", None)
        return cls(**payload)
