"""The validated asset → section association every planner must respect.

Decided once per generation, before any layout:

1. **Folders** (authoritative). When the project is organised in folders
   (see :mod:`behance_studio.assets.folders`), each image belongs to the
   section its folder names. AI and heuristics may refine an image's *kind*
   (how it is shown) but never move it to another section — unless the user
   switches the project to "Let AI organise by content".
2. **Content** for images without a meaningful folder: the image's kind (from
   the vision model when it answered confidently, otherwise the measured
   heuristics, or the user's own choice) decides its section. In an
   organised project such an image joins the folder section of the same type
   when there is one.

The result is stored on each asset (``analysis["section"]``) and on the plan
(``PresentationPlan.asset_sections``) so layouts, validation and diagnostics
all use the same mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from behance_studio.assets.folders import FolderMap, FolderSection, build_folder_map, folder_parts
from behance_studio.planning.sections import section_type

# Where an asset of each kind belongs when no folder says otherwise.
HOME = {
    "logo": "logo", "logo_variant": "logo_variations", "monogram": "logo_variations",
    "palette": "palette", "typography": "typography", "pattern": "visual_language", "illustration": "illustration",
    "packaging": "packaging", "product": "product", "poster": "campaign", "outdoor": "outdoor", "social": "social",
    "stationery": "applications", "mockup": "applications", "editorial": "editorial",
    "website": "website", "mobile": "mobile", "ui": "ui_screens",
    "photo": "photography", "lifestyle": "photography", "portrait": "photography", "before_after": "before_after",
    "video": "motion", "motion": "motion", "document": "applications", "other": "applications",
}
MODES = ("auto", "folders", "content")


@dataclass
class Placement:
    """Where one asset belongs, and why."""

    key: str  # section key: folder path, or "kind:<type>"
    title: str
    type: str
    source: str  # folder | ai | heuristic | user
    folder: str = ""  # the asset's source folder
    confidence: float = 1.0
    reasons: list[str] = field(default_factory=list)
    order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "title": self.title, "type": self.type, "source": self.source, "folder": self.folder,
                "confidence": round(float(self.confidence), 3), "reasons": list(self.reasons), "order": self.order}


@dataclass
class SectionAssignment:
    mode: str  # "folders" or "content" (the mode actually used)
    folder_map: FolderMap | None = None
    placements: dict[str, Placement] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def by_folders(self) -> bool:
        return self.mode == "folders"

    def key(self, asset_id: str) -> str | None:
        p = self.placements.get(asset_id)
        return p.key if p else None

    def order_of(self, key: str) -> int:
        for p in self.placements.values():
            if p.key == key:
                return p.order
        return 10_000

    def groups(self) -> list[tuple[Placement, list[str]]]:
        """(section, asset ids) in presentation order."""
        out: dict[str, tuple[Placement, list[str]]] = {}
        for aid, p in self.placements.items():
            out.setdefault(p.key, (p, []))[1].append(aid)
        return sorted(out.values(), key=lambda g: (g[0].order, g[0].key))

    def to_plan(self) -> dict[str, dict[str, Any]]:
        return {aid: p.to_dict() for aid, p in self.placements.items()}


def _kind_reason(asset) -> tuple[str, float, list[str]]:
    if asset.user_kind:
        return "user", 1.0, [f"you set the type to {asset.user_kind.replace('_', ' ')}"]
    ai = (asset.analysis or {}).get("ai") or {}
    if asset.kind_source == "ai":
        return "ai", float(ai.get("confidence", asset.kind_confidence) or 0.0), [f"vision model: {ai.get('kind', asset.kind)} ({float(ai.get('confidence', 0) or 0):.2f})"]
    reasons = list(((asset.analysis or {}).get("classification") or {}).get("reasons") or [])[:3]
    if ai.get("decision"):
        reasons.append(f"vision model answer not applied: {ai['decision']}")
    return "heuristic", float(asset.kind_confidence or 0.0), reasons or ["measured image features"]


def assign_sections(assets, mode: str = "auto", language: str = "en") -> SectionAssignment:
    """Decide every usable asset's section (see module docstring)."""
    mode = mode if mode in MODES else "auto"
    usable = [a for a in assets if a.is_visual and not a.excluded and a.effective_kind != "reference"]
    fmap = build_folder_map(usable) if mode != "content" else None
    use_folders = bool(fmap and fmap.sections and (fmap.organized or mode == "folders"))
    result = SectionAssignment("folders" if use_folders else "content", fmap if use_folders else None)
    folder_sections: list[FolderSection] = fmap.sections if use_folders else []
    base = len(folder_sections)
    kind_order = {t: i for i, t in enumerate(dict.fromkeys(HOME.values()))}
    for a in usable:
        folder = "/".join(folder_parts(a))
        fs = fmap.by_asset.get(a.id) if use_folders else None
        if fs is not None:
            reasons = [f"in folder '{fs.key}'"]
            if fs.chapter:
                reasons.append(f"chapter '{fs.chapter}'")
            kind = a.effective_kind
            if fs.specific and kind not in _folder_kinds(fs.type):
                reasons.append(f"its type ({kind.replace('_', ' ')}) differs from the folder; the folder decides the section")
            result.placements[a.id] = Placement(fs.key, fs.title, fs.type, "folder", folder, 1.0, reasons, fs.order)
            continue
        source, confidence, reasons = _kind_reason(a)
        home = HOME.get(a.effective_kind, "applications")
        joined = next((s for s in folder_sections if s.type == home), None)
        if joined is not None:
            reasons = reasons + [f"joins the folder section '{joined.title}' of the same type"]
            result.placements[a.id] = Placement(joined.key, joined.title, joined.type, source, folder, confidence, reasons, joined.order)
        else:
            title = section_type(home).title(language)
            result.placements[a.id] = Placement(f"kind:{home}", title, home, source, folder, confidence, reasons,
                                                base + kind_order.get(home, 99))
    if use_folders:
        loose = sum(1 for p in result.placements.values() if p.source != "folder")
        result.notes.append(f"Sections follow your folders ({len(folder_sections)} section folder(s))"
                            + (f"; {loose} image(s) outside them were placed by content." if loose else "."))
    elif mode != "content" and fmap is not None and fmap.sections:
        result.notes.append("The folders do not describe sections, so images were grouped by what they show.")
    return result


def _folder_kinds(type_id: str) -> set[str]:
    from behance_studio.assets.folders import FOLDER_KINDS

    return FOLDER_KINDS.get(type_id, set())


def persist(assignment: SectionAssignment, assets) -> list:
    """Store each asset's placement in ``analysis["section"]``; returns changed assets."""
    changed = []
    for a in assets:
        p = assignment.placements.get(a.id)
        if p is None:
            continue
        data = p.to_dict()
        if (a.analysis or {}).get("section") != data:
            a.analysis["section"] = data
            changed.append(a)
    return changed
