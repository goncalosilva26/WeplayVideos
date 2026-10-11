"""Creative direction: the visual identity a presentation should express.

Derived (in precedence order) from the brief, then from the brand assets
themselves (colours measured in logos, palettes, packaging...), then from
defaults. The direction is shared by all proposals of a generation so that
the brand stays recognisable across the six layout families; each family
then interprets it with its own composition system.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from behance_studio.brief.brief import CreativeBrief
from behance_studio.design import color as C
from behance_studio.design.category import CategoryResult
from behance_studio.design.typography import AXES, TypeSystem, rank_pairings
from behance_studio.projects.models import AssetRecord

KIND_COLOR_WEIGHT = {
    "palette": 4.0, "logo": 3.0, "monogram": 2.6, "logo_variant": 2.2, "pattern": 2.0, "packaging": 1.4,
    "poster": 1.2, "stationery": 1.2, "social": 1.0, "outdoor": 1.0, "illustration": 1.0, "motion": 0.8,
    "mockup": 0.8, "website": 0.8, "mobile": 0.8, "ui": 0.8, "editorial": 0.8, "typography": 0.5,
    "photo": 0.3, "product": 0.4, "lifestyle": 0.3, "portrait": 0.2, "before_after": 0.1, "video": 0.3, "other": 0.3,
}


@dataclass
class Swatch:
    hex: str
    role: str  # primary | secondary | accent | dark | light | neutral
    name: str | None = None
    weight: float = 0.0
    source: str = "assets"

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class BrandPalette:
    primary: str
    secondary: str
    accent: str
    ink: str
    paper: str
    swatches: list[Swatch] = field(default_factory=list)
    source: str = "assets"  # brief | assets | default
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["swatches"] = [s.to_dict() for s in self.swatches]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BrandPalette":
        d = dict(data)
        d["swatches"] = [Swatch(**s) for s in d.get("swatches", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @property
    def presentable(self) -> list[Swatch]:
        """Swatches worth showing in a colour section (distinct, ordered)."""
        out: list[Swatch] = []
        for s in self.swatches:
            if all(C.delta_e(s.hex, o.hex) > 8 for o in out):
                out.append(s)
        return out[:6]


@dataclass
class CreativeDirection:
    personality: dict[str, float]
    mood_words: list[str]
    palette: BrandPalette
    type_system: TypeSystem
    tone: str = "light"  # light | dark | balanced
    density: str = "balanced"  # airy | balanced | dense
    corner_radius: int = 0
    rhythm: str = "steady"  # steady | dynamic
    brand_fonts_known: bool = False
    family_preferences: list[str] = field(default_factory=list)
    category: str = "mixed"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "personality": self.personality,
            "mood_words": self.mood_words,
            "palette": self.palette.to_dict(),
            "type_system": self.type_system.to_dict(),
            "tone": self.tone,
            "density": self.density,
            "corner_radius": self.corner_radius,
            "rhythm": self.rhythm,
            "brand_fonts_known": self.brand_fonts_known,
            "family_preferences": self.family_preferences,
            "category": self.category,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CreativeDirection":
        return cls(
            personality=data.get("personality", {}),
            mood_words=data.get("mood_words", []),
            palette=BrandPalette.from_dict(data["palette"]),
            type_system=TypeSystem.from_dict(data["type_system"]),
            tone=data.get("tone", "light"),
            density=data.get("density", "balanced"),
            corner_radius=int(data.get("corner_radius", 0)),
            rhythm=data.get("rhythm", "steady"),
            brand_fonts_known=bool(data.get("brand_fonts_known", False)),
            family_preferences=data.get("family_preferences", []),
            category=data.get("category", "mixed"),
            notes=data.get("notes", []),
        )

    def axis(self, name: str) -> float:
        return float(self.personality.get(name, 0.0))


# ---------------------------------------------------------------- palette
def _collect_asset_colors(assets: list[AssetRecord]) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []
    for asset in assets:
        a = asset.analysis or {}
        if not a or asset.excluded or not asset.is_visual:
            continue
        kind_w = KIND_COLOR_WEIGHT.get(asset.effective_kind, 0.3)
        colors = a.get("colors") if asset.effective_kind in ("palette", "pattern") else (a.get("content_colors") or a.get("colors") or [])
        for c in colors or []:
            w = kind_w * float(c.get("weight", 0))
            if w <= 0.002:
                continue
            candidates.append((c["hex"], w))
        bg = a.get("background")
        if bg and bg != "transparent" and asset.effective_kind in ("social", "poster", "packaging", "pattern", "stationery", "outdoor"):
            candidates.append((bg, kind_w * 0.35))
    return candidates


def _merge_colors(candidates: list[tuple[str, float]], threshold: float = 14.0) -> list[tuple[str, float]]:
    clusters: list[list[Any]] = []  # [lab_sum, weight, count]
    for hexv, w in sorted(candidates, key=lambda c: -c[1]):
        lab = C.hex_to_lab(hexv)
        for cl in clusters:
            center = tuple(v / cl[1] for v in cl[0])
            if math.dist(center, lab) < threshold:
                cl[0] = [cl[0][i] + lab[i] * w for i in range(3)]
                cl[1] += w
                break
        else:
            clusters.append([[lab[i] * w for i in range(3)], w])
    merged = [(C.lab_to_hex(tuple(v / cl[1] for v in cl[0])), cl[1]) for cl in clusters]  # type: ignore[arg-type]
    total = sum(w for _, w in merged) or 1.0
    return sorted(((h, w / total) for h, w in merged), key=lambda x: -x[1])


def _derive_paper(primary: str, warmth: float) -> str:
    hue_hex = C.with_lightness(primary, 96, chroma_scale=0.08)
    if abs(warmth) < 0.15:
        return C.mix(hue_hex, "#F7F7F5", 0.5)
    return hue_hex


def _derive_ink(primary: str) -> str:
    return C.with_lightness(primary, 13, chroma_scale=0.35)


def build_palette(brief: CreativeBrief, assets: list[AssetRecord]) -> BrandPalette:
    swatches: list[Swatch] = []
    source = "assets"
    confidence = 0.5
    if len(brief.colors) >= 2:
        source = "brief"
        confidence = 1.0
        entries = [(c.hex, 1.0 / (i + 1), c.name) for i, c in enumerate(brief.colors)]
    else:
        merged = _merge_colors(_collect_asset_colors(assets))
        entries = [(h, w, None) for h, w in merged[:10]]
        for bc in brief.colors:
            entries.insert(0, (bc.hex, 1.0, bc.name))
            source = "mixed"
        confidence = 0.6 if len(entries) >= 3 else 0.3
    if not entries:
        entries = [("#1D1D1F", 1.0, None), ("#F4F2EE", 0.8, None), ("#C9532C", 0.5, None)]
        source, confidence = "default", 0.1

    def info(h: str) -> tuple[float, float]:
        return C.lightness(h), C.chroma(h)

    darks = [(h, w, n) for h, w, n in entries if info(h)[0] < 30]
    lights = [(h, w, n) for h, w, n in entries if info(h)[0] > 86 and info(h)[1] < 22]
    hues = [(h, w, n) for h, w, n in entries if info(h)[1] >= 16 and 30 <= info(h)[0] <= 92]
    if source != "brief":
        # rank brand hues by weight and saturation
        hues.sort(key=lambda e: -(e[1] * (0.6 + min(1.0, info(e[0])[1] / 60))))
    primary_e = hues[0] if hues else (darks[0] if darks else entries[0])
    primary = primary_e[0]
    secondary_e = next((e for e in hues[1:] if C.delta_e(e[0], primary) > 22), None)
    accent_e = None
    if secondary_e:
        accent_e = next(
            (e for e in hues if e[0] not in (primary, secondary_e[0]) and C.delta_e(e[0], primary) > 22 and C.delta_e(e[0], secondary_e[0]) > 22),
            None,
        )
    warmth = sum(C.warmth(h) * w for h, w, _ in entries) / max(1e-6, sum(w for _, w, _ in entries))
    ink = darks[0][0] if darks else _derive_ink(primary)
    paper = lights[0][0] if lights else _derive_paper(primary, warmth)
    secondary = secondary_e[0] if secondary_e else C.mix(primary, paper, 0.55)
    accent = accent_e[0] if accent_e else (secondary_e[0] if secondary_e else C.hsv_rotate(primary, 30))

    names = {h: n for h, _w, n in entries if n}
    used: set[str] = set()

    def add(hexv: str, role: str, weight: float, src: str) -> None:
        if hexv in used:
            return
        used.add(hexv)
        swatches.append(Swatch(hex=hexv, role=role, name=names.get(hexv), weight=round(weight, 3), source=src))

    if source == "brief":
        for h, w, n in entries:
            role = "dark" if h == ink else "light" if h == paper else "primary" if h == primary else "secondary" if h == secondary else "accent" if h == accent else "neutral"
            add(h, role, w, "brief")
    else:
        add(primary, "primary", primary_e[1], source if primary_e[2] is None else "brief")
        if secondary_e:
            add(secondary, "secondary", secondary_e[1], "assets")
        if accent_e:
            add(accent, "accent", accent_e[1], "assets")
        if darks:
            add(ink, "dark", darks[0][1], "assets")
        if lights:
            add(paper, "light", lights[0][1], "assets")
    return BrandPalette(primary, secondary, accent, ink, paper, swatches, source, confidence)


# -------------------------------------------------------------- personality
def infer_personality(palette: BrandPalette, category: CategoryResult, assets: list[AssetRecord]) -> dict[str, float]:
    cols = [palette.primary, palette.secondary, palette.accent]
    warmth = sum(C.warmth(c) for c in cols) / 3
    chroma = sum(C.chroma(c) for c in cols) / 3
    energy = max(-1.0, min(1.0, (chroma - 35) / 35))
    contrast = C.contrast_ratio(palette.ink, palette.paper)
    boldness = max(-1.0, min(1.0, (chroma - 35) / 50 + (contrast - 12) / 30))
    refinement = max(-1.0, min(1.0, (30 - chroma) / 40))
    modernity = 0.3
    if category.category in ("ui_ux", "website", "app"):
        modernity = 0.8
    elif category.category in ("photography", "illustration", "editorial"):
        modernity = 0.0
    organic = 0.3 if any(a.effective_kind == "illustration" for a in assets) else 0.25 * warmth
    return {
        "warmth": round(warmth, 3),
        "energy": round(energy, 3),
        "refinement": round(refinement, 3),
        "boldness": round(boldness, 3),
        "modernity": round(modernity, 3),
        "organic": round(organic, 3),
    }


def build_direction(brief: CreativeBrief, assets: list[AssetRecord], category: CategoryResult) -> CreativeDirection:
    palette = build_palette(brief, assets)
    inferred = infer_personality(palette, category, assets)
    personality = dict(inferred)
    notes: list[str] = []
    if brief.personality:
        for axis in AXES:
            if axis in brief.personality:
                # The brief wins, softly blended with what the assets show.
                personality[axis] = round(0.8 * brief.personality[axis] + 0.2 * inferred.get(axis, 0.0), 3)
            else:
                # Axes the brief is silent about are only weakly inferred.
                personality[axis] = round(0.6 * inferred.get(axis, 0.0), 3)
        notes.append("Brand personality taken from the brief.")
    else:
        notes.append("Brand personality estimated from the colours and assets (no brief).")

    if brief.display_font or brief.text_font:
        display = brief.display_font or brief.text_font or "Inter"
        text = brief.text_font or brief.display_font or "Inter"
        type_system = TypeSystem(display=display, text=text, label=text, display_weight=500, source="brief")
        brand_fonts_known = True
        notes.append(f"Typography from the brief: {display} / {text}.")
    else:
        best = rank_pairings(personality)[0]
        type_system = TypeSystem(display=best.display, text=best.text, label=best.label, display_weight=best.display_weight, source="inferred")
        brand_fonts_known = False

    if brief.tone:
        tone = brief.tone
    else:
        brightness = [a.analysis.get("brightness", 0.5) for a in assets if a.analysis and a.effective_kind not in ("logo", "logo_variant", "monogram")]
        avg = sum(brightness) / len(brightness) if brightness else 0.6
        tone = "dark" if avg < 0.3 else "light" if avg > 0.55 else "balanced"
    refinement = personality.get("refinement", 0)
    energy = personality.get("energy", 0)
    density = "airy" if refinement > 0.4 or energy < -0.4 else "dense" if energy > 0.6 and personality.get("boldness", 0) > 0.4 else "balanced"
    organic = personality.get("organic", 0)
    corner = 0
    if organic > 0.3 or (energy > 0.4 and personality.get("warmth", 0) > 0.3):
        corner = 14
    if refinement > 0.6 or personality.get("modernity", 0) > 0.85:
        corner = 0
    rhythm = "dynamic" if energy > 0.3 else "steady"
    return CreativeDirection(
        personality=personality,
        mood_words=brief.mood_words,
        palette=palette,
        type_system=type_system,
        tone=tone,
        density=density,
        corner_radius=corner,
        rhythm=rhythm,
        brand_fonts_known=brand_fonts_known,
        family_preferences=list(brief.family_preferences),
        category=category.category,
        notes=notes + list(brief.font_notes),
    )
