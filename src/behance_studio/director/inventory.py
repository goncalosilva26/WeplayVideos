"""Brand inventory: the material a Creative Director can work with.

Usable assets are grouped by the role they can play in a case study, ranked
by measured strength, and near-duplicates are collapsed so the strongest
version is chosen. Not every asset has to be used — selection is the
director's job; the inventory only makes the options explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from behance_studio.assets.analysis import hamming
from behance_studio.assets.understanding import asset_nature, is_single_colour_mark, logo_ink, strength
from behance_studio.design import color as C
from behance_studio.planning.planner import PlanningContext, usable_assets
from behance_studio.projects.models import AssetRecord


@dataclass
class Inventory:
    logo: AssetRecord | None = None  # primary logo (transparent preferred)
    logo_alts: list[AssetRecord] = field(default_factory=list)  # other lockups / variants (transparent)
    logo_panels: list[AssetRecord] = field(default_factory=list)  # logo artwork with its own background
    marks: list[AssetRecord] = field(default_factory=list)  # monograms / symbols
    patterns: list[AssetRecord] = field(default_factory=list)
    documents: dict[str, list[AssetRecord]] = field(default_factory=dict)  # palette / typography sheets
    photos: list[AssetRecord] = field(default_factory=list)  # photography (environment, lifestyle, product)
    scenes: list[AssetRecord] = field(default_factory=list)  # photographic mockups (packaging, stationery, outdoor)
    posters: list[AssetRecord] = field(default_factory=list)
    outdoor: list[AssetRecord] = field(default_factory=list)  # flat outdoor artwork (billboards)
    social: list[AssetRecord] = field(default_factory=list)
    artworks: list[AssetRecord] = field(default_factory=list)  # other finished artwork (editorial, illustration, flat packaging)
    screens: list[AssetRecord] = field(default_factory=list)
    motion: list[AssetRecord] = field(default_factory=list)
    dropped: dict[str, str] = field(default_factory=dict)  # asset id -> reason not offered
    by_id: dict[str, AssetRecord] = field(default_factory=dict)

    @property
    def imagery(self) -> list[AssetRecord]:
        """Photographs and photographic mockups (full-bleed material)."""
        return self.photos + self.scenes

    def count(self) -> int:
        groups = [self.logo_alts, self.logo_panels, self.marks, self.patterns, self.photos, self.scenes, self.posters,
                  self.outdoor, self.social, self.artworks, self.screens, self.motion]
        return (1 if self.logo else 0) + sum(len(g) for g in groups) + sum(len(v) for v in self.documents.values())


WEAK_IMAGERY = 0.66


def _rank(assets: list[AssetRecord]) -> list[AssetRecord]:
    return sorted(assets, key=lambda a: (-strength(a), a.filename.lower()))


def _collapse_near_duplicates(assets: list[AssetRecord], dropped: dict[str, str]) -> list[AssetRecord]:
    kept: list[AssetRecord] = []
    for a in _rank(assets):
        twin = next((k for k in kept if k.phash and a.phash and abs(k.aspect - a.aspect) < 0.06 and hamming(k.phash, a.phash) <= 6), None)
        if twin is not None:
            dropped[a.id] = f"near-duplicate of {twin.filename}"
            continue
        kept.append(a)
    return kept


def _logo_rank_key(a: AssetRecord) -> tuple:
    name = a.filename.lower()
    primary = 0 if any(w in name for w in ("primary", "principal", "main", "master")) else 1
    horizontal = 0 if a.aspect >= 2.0 else 1
    transparent = 0 if (a.analysis or {}).get("background") == "transparent" else 1
    return (transparent, primary, 0 if a.effective_kind == "logo" else 1, horizontal, -a.kind_confidence, name)


def build_inventory(ctx: PlanningContext) -> Inventory:
    inv = Inventory()
    usable = usable_assets(ctx)
    inv.by_id = {a.id: a for a in usable}
    visual = _collapse_near_duplicates([a for a in usable if a.is_visual], inv.dropped)
    logos = [a for a in visual if a.effective_kind in ("logo", "logo_variant")]
    marks = [a for a in visual if a.effective_kind == "monogram"]
    transparent_logos = sorted([a for a in logos if (a.analysis or {}).get("background") == "transparent"], key=_logo_rank_key)
    panels = [a for a in logos if (a.analysis or {}).get("background") != "transparent"]
    if transparent_logos:
        inv.logo = transparent_logos[0]
        inv.logo_alts = transparent_logos[1:]
    elif panels:
        inv.logo = sorted(panels, key=_logo_rank_key)[0]
        panels = [p for p in panels if p.id != inv.logo.id]
    inv.logo_panels = _rank(panels)
    # Marks: prefer raster/vector duplicates collapsed by name similarity.
    seen_marks: list[AssetRecord] = []
    for m in sorted(marks, key=_logo_rank_key):
        if any(abs(m.aspect - s.aspect) < 0.05 and C.delta_e(logo_ink(m), logo_ink(s)) < 6 for s in seen_marks):
            inv.dropped[m.id] = "another file of the same mark"
            continue
        seen_marks.append(m)
    inv.marks = seen_marks
    element_ids = {a.id for a in logos} | {a.id for a in marks}
    for a in visual:
        if a.id in element_ids:
            continue
        kind = a.effective_kind
        nature = asset_nature(a)
        if kind == "pattern":
            inv.patterns.append(a)
        elif nature == "document":
            inv.documents.setdefault(kind, []).append(a)
        elif nature == "motion":
            inv.motion.append(a)
        elif nature == "screen":
            inv.screens.append(a)
        elif kind == "social":
            inv.social.append(a)
        elif kind == "poster":
            inv.posters.append(a)
        elif kind == "outdoor" and nature == "artwork":
            inv.outdoor.append(a)
        elif nature == "artwork":
            inv.artworks.append(a)
        elif kind in ("photo", "lifestyle", "portrait", "before_after"):
            inv.photos.append(a)
        else:
            inv.scenes.append(a)
    for name in ("patterns", "photos", "scenes", "posters", "outdoor", "social", "artworks", "screens", "motion"):
        setattr(inv, name, _rank(getattr(inv, name)))
    # Weak imagery (soft, low-interest or tiny frames) is held back when
    # enough stronger material exists: quality over quantity.
    for name in ("photos", "scenes"):
        group = getattr(inv, name)
        strong = [a for a in group if strength(a) >= WEAK_IMAGERY]
        if len(strong) >= 2:
            for a in group:
                if a not in strong:
                    inv.dropped[a.id] = "weaker image (soft or low visual interest)"
            setattr(inv, name, strong)
    for key in inv.documents:
        inv.documents[key] = _rank(inv.documents[key])
    return inv


def reversible(asset: AssetRecord | None) -> bool:
    return asset is not None and is_single_colour_mark(asset)
