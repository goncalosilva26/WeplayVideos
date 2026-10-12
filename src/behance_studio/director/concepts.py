"""The five creative concepts and their art direction.

A concept is not a template: it is a set of art-direction decisions —
surfaces, type treatment, spacing system, image treatments, rhythm and
which compositional modules suit it. The Creative Director combines a
concept with the brand (palette, fonts, assets) and a seed to plan a
complete presentation; the module engine executes that plan.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from typing import Any

from behance_studio.design import color as C
from behance_studio.design.direction import CreativeDirection
from behance_studio.design.typography import TypeSystem, get_font, rank_pairings


@dataclass(frozen=True)
class ConceptInfo:
    id: str
    name: str
    tagline: str
    description: str
    badge: str
    voices: tuple[str, ...]  # font voices used when the brand fonts are unknown


CONCEPTS: dict[str, ConceptInfo] = {
    "minimal": ConceptInfo(
        "minimal", "Minimal Editorial", "Quiet, precise, generous space",
        "Calm editorial art direction: light surfaces, large images framed by negative space, refined serif "
        "typography, small tracked labels and an unhurried rhythm.",
        "#C9B79C", ("editorial",),
    ),
    "bold": ConceptInfo(
        "bold", "Bold Graphic", "Brand colour, scale and impact",
        "Graphic art direction: full brand-colour fields, oversized type, seamless modules, artwork staged with "
        "hard shadows and the identity used at poster scale.",
        "#F2B63D", ("condensed", "expressive"),
    ),
    "photo": ConceptInfo(
        "photo", "Premium Photographic", "Imagery first, dark and cinematic",
        "Photography-led art direction: dark surfaces, edge-to-edge imagery, seamless pairs, framed campaign "
        "pieces under soft light and minimal, finely tracked typography.",
        "#8E7A66", ("editorial", "technical"),
    ),
    "layered": ConceptInfo(
        "layered", "Layered Experimental", "Overlaps, masks and movement",
        "Experimental art direction: overlapping cards, masked photographs, rotated artwork with depth, "
        "pattern grounds and off-grid placement.",
        "#7C6CF0", ("expressive", "technical"),
    ),
    "story": ConceptInfo(
        "story", "Immersive Story", "Chapters, pacing and transitions",
        "Narrative art direction: numbered chapters, immersive full-bleed sequences, brand messages as "
        "pauses, alternating light and dark acts and a closing statement.",
        "#E2574C", ("editorial",),
    ),
}

CONCEPT_ORDER = ["minimal", "bold", "photo", "layered", "story"]


@dataclass
class ArtDirection:
    concept: str
    # colour
    page: str
    surfaces: list[str]
    light: str
    dark: str
    primary: str
    secondary: str
    accent: str
    # typography
    display: str
    display_weight: int
    display_upper: bool
    display_tracking: float
    display_italic: bool
    text: str
    label: str
    brand_fonts: bool
    # space and effects
    margin: float
    gutter: float
    vpad: float
    radius: float
    shadow: str | None
    seamless: bool
    labels: bool
    rotation: float
    scale: float  # how large hero media are relative to the artboard (0–1)
    stages: list[str] = field(default_factory=list)  # surfaces on which artwork is staged
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtDirection":
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in names})


def _lightest(colors: list[str]) -> str:
    return max(colors, key=C.relative_luminance)


def _darkest(colors: list[str]) -> str:
    return min(colors, key=C.relative_luminance)


def _distinct(colors: list[str], minimum: float = 6.0) -> list[str]:
    out: list[str] = []
    for c in colors:
        if c and all(C.delta_e(c, o) >= minimum for o in out):
            out.append(c)
    return out


def _type_for(concept: ConceptInfo, direction: CreativeDirection, rng: random.Random) -> tuple[str, str, str, bool]:
    ts = direction.type_system
    if direction.brand_fonts_known:
        return ts.display, ts.text, ts.label or ts.text, True
    ranked = rank_pairings(direction.personality, set(concept.voices))
    pick = ranked[0] if rng.random() < 0.6 or len(ranked) < 2 else ranked[1]
    return pick.display, pick.text, pick.label, False


def art_direction(concept_id: str, direction: CreativeDirection, rng: random.Random, creativity: float = 0.5) -> ArtDirection:
    concept = CONCEPTS[concept_id]
    pal = direction.palette
    swatches = [s.hex for s in pal.presentable] or [pal.primary, pal.secondary, pal.accent]
    pool = _distinct([pal.primary, pal.secondary, pal.accent, pal.ink, pal.paper, *swatches])
    light = _lightest(pool + [pal.paper])
    dark = _darkest(pool + [pal.ink])
    if C.relative_luminance(light) < 0.72:
        light = C.mix(light, "#FFFFFF", 0.82)
    if C.relative_luminance(dark) > 0.06:
        dark = C.mix(dark, "#000000", 0.55)
    chroma_sorted = sorted([c for c in pool if C.delta_e(c, light) > 10 and C.delta_e(c, dark) > 10], key=lambda c: -C.chroma(c))
    primary = chroma_sorted[0] if chroma_sorted else pal.primary
    secondary = chroma_sorted[1] if len(chroma_sorted) > 1 else C.mix(primary, dark, 0.35)
    accent = chroma_sorted[2] if len(chroma_sorted) > 2 else secondary
    display, text, label, brand_fonts = _type_for(concept, direction, rng)
    disp_font = get_font(display)

    def weight(wanted: int) -> int:
        return disp_font.clamp_weight(wanted)

    jitter = 0.5 + creativity
    if concept_id == "minimal":
        page = light
        tint = C.mix(light, dark, 0.045)
        return ArtDirection(
            concept_id, page, [page, tint], light, dark, primary, secondary, accent,
            display, weight(400), False, -0.01, rng.random() < 0.25 * jitter, text, label, brand_fonts,
            margin=rng.choice([140, 160, 180]), gutter=rng.choice([24, 28, 32]), vpad=rng.choice([150, 170]),
            radius=0.0, shadow="soft", seamless=False, labels=True, rotation=0.0, scale=0.82, stages=[tint, light],
        )
    if concept_id == "bold":
        order = _distinct([primary, secondary, dark, accent, light], 8)
        rng.shuffle(order)
        if order[0] in (light,):
            order.append(order.pop(0))
        return ArtDirection(
            concept_id, order[0], order, light, dark, primary, secondary, accent,
            display, weight(800), True, -0.015, False, text, label, brand_fonts,
            margin=rng.choice([64, 80]), gutter=rng.choice([0, 0, 20]), vpad=rng.choice([110, 130]),
            radius=0.0, shadow="hard", seamless=True, labels=False, rotation=0.0, scale=1.0, stages=[c for c in order if c != light] + [light],
        )
    if concept_id == "photo":
        deep = C.mix(dark, "#000000", 0.35)
        return ArtDirection(
            concept_id, dark, [dark, deep], light, dark, primary, secondary, accent,
            display, weight(300), True, 0.12, False, text, label, brand_fonts,
            margin=rng.choice([0, 0, 96]), gutter=rng.choice([0, 8]), vpad=rng.choice([140, 160]),
            radius=0.0, shadow="lifted", seamless=True, labels=True, rotation=0.0, scale=1.0,
            stages=[deep, dark, C.mix(dark, light, 0.12)],
        )
    if concept_id == "layered":
        soft = C.mix(light, primary, 0.22)
        return ArtDirection(
            concept_id, light, [light, primary, soft, accent], light, dark, primary, secondary, accent,
            display, weight(600), False, -0.02, rng.random() < 0.5, text, label, brand_fonts,
            margin=rng.choice([100, 120]), gutter=24, vpad=rng.choice([120, 140]),
            radius=rng.choice([0.0, 18.0]), shadow="lifted", seamless=False, labels=True,
            rotation=rng.choice([4.0, 5.0, 6.0]) * jitter, scale=0.9, stages=[soft, primary, light, accent],
        )
    # story
    return ArtDirection(
        "story", dark, [dark, light], light, dark, primary, secondary, accent,
        display, weight(400), False, -0.01, rng.random() < 0.35, text, label, brand_fonts,
        margin=rng.choice([120, 140]), gutter=rng.choice([0, 16]), vpad=rng.choice([160, 180]),
        radius=0.0, shadow="lifted", seamless=True, labels=True, rotation=0.0, scale=0.95,
        stages=[dark, C.mix(dark, light, 0.1), light],
    )


def type_system_for(ad: ArtDirection) -> TypeSystem:
    return TypeSystem(ad.display, ad.text, ad.label, ad.display_weight, 400, "brief" if ad.brand_fonts else "inferred")
