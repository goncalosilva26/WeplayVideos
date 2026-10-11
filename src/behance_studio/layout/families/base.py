"""Layout family framework.

A family is a complete design system: its own grid, spacing scale, type
hierarchy, colour strategy, composition patterns and transitions. Families
receive the same narrative plan and creative direction and produce a
``Presentation`` with absolute geometry.

Determinism: every section is composed with its own RNG seeded from
(proposal seed, section id, section variant), so a proposal can be
regenerated exactly, and a single section can be re-rolled without
affecting the others.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Any

from behance_studio.core.logging_setup import get_logger
from behance_studio.design import color as C
from behance_studio.design.typography import TypeSystem, get_font, rank_pairings
from behance_studio.layout.composer import ComposeContext, Composer, SectionBuilder
from behance_studio.layout.model import Block, Presentation, Section, TextStyle
from behance_studio.planning.models import SectionPlan
from behance_studio.planning.planner import PlanPreferences

log = get_logger(__name__)

TEXTUAL_TYPES = {"intro", "overview", "concept", "creative_direction", "brand_story"}
LOGO_TYPES = {"logo", "logo_variations", "logo_construction"}


@dataclass
class FamilyInfo:
    id: str
    name: str
    tagline: str
    description: str
    ideal_for: list[str]
    badge: str  # UI accent colour for the family label


@dataclass
class ComposeState:
    """Rhythm memory while composing a presentation."""

    index: int = 0
    content_index: int = 0  # numbering of body sections (excludes cover/closing)
    patterns: list[str] = field(default_factory=list)
    backgrounds: list[str] = field(default_factory=list)
    side: int = 0  # alternating left/right for asymmetric families
    variant: dict[str, Any] = field(default_factory=dict)

    def recent(self, n: int = 2) -> list[str]:
        return self.patterns[-n:]


def apply_overrides(plan: SectionPlan, overrides: dict[str, Any] | None) -> SectionPlan:
    if not overrides:
        return plan
    sp = copy.deepcopy(plan)
    for key in ("title", "subtitle", "body", "eyebrow", "background", "layout_hint"):
        if key in overrides and overrides[key] is not None:
            setattr(sp, key, overrides[key])
    if "asset_ids" in overrides and overrides["asset_ids"] is not None:
        sp.asset_ids = list(overrides["asset_ids"])
    if "captions" in overrides:
        sp.captions.update(overrides["captions"] or {})
    sp.meta = dict(sp.meta)
    for key in ("spacing", "variant_seed", "hidden", "focal", "text_scale"):
        if key in overrides:
            sp.meta[key] = overrides[key]
    return sp


ARTWORK_KINDS = {"social", "poster", "stationery", "editorial", "palette", "typography", "outdoor", "website", "mobile", "ui", "illustration", "pattern", "mockup", "packaging", "product", "photo", "lifestyle"}


class LayoutFamily:
    info: FamilyInfo
    voices: set[str] | None = None  # preferred pairing voices when brand fonts are unknown
    edge_style: str | None = "outline"  # how artwork is separated from a similar background

    # --------------------------------------------------------------- planning
    def preferences(self, rng: random.Random, creativity: float) -> PlanPreferences:
        return PlanPreferences()

    # ------------------------------------------------------------- variants
    def choose_type_system(self, ctx: ComposeContext, rng: random.Random) -> TypeSystem:
        ts = ctx.direction.type_system
        if ctx.direction.brand_fonts_known:
            return TypeSystem(ts.display, ts.text, ts.label, ts.display_weight, ts.text_weight, "brief")
        ranked = rank_pairings(ctx.direction.personality, self.voices)
        top = ranked[: 3 if ctx.creativity >= 0.4 else 1]
        pick = top[0] if rng.random() < 0.55 else rng.choice(top)
        return TypeSystem(pick.display, pick.text, pick.label, pick.display_weight, 400, "inferred")

    def variant(self, ctx: ComposeContext, rng: random.Random) -> dict[str, Any]:
        return {}

    # -------------------------------------------------------------- compose
    def compose(self, ctx: ComposeContext) -> Presentation:
        base_rng = random.Random(f"{self.info.id}:{ctx.seed}")
        variant = self.variant(ctx, base_rng)
        variant.setdefault("type_system", self.choose_type_system(ctx, base_rng).to_dict())
        state = ComposeState(variant=variant)
        comp = Composer(ctx, base_rng)
        self.setup(comp, variant)
        sections: list[Section] = []
        plans = [apply_overrides(sp, ctx.overrides.get(sp.id)) for sp in ctx.plan.sections]
        visible = [sp for sp in plans if not sp.meta.get("hidden")]
        for index, sp in enumerate(visible):
            state.index = index
            comp.rng = random.Random(f"{self.info.id}:{ctx.seed}:{sp.id}:{sp.meta.get('variant_seed', 0)}")
            is_last = index == len(visible) - 1
            try:
                section = self.compose_section(comp, sp, state, is_last)
            except Exception as exc:  # noqa: BLE001 - never lose a whole proposal
                log.exception("Section %s failed in %s; using safe layout", sp.type, self.info.id)
                section = self.safe_section(comp, sp, state)
                section.meta["fallback"] = str(exc)
            self.apply_section_overrides(section, sp)
            self.edge_treatment(comp, section)
            section.meta.setdefault("number", state.content_index)
            sections.append(section)
            state.patterns.append(section.pattern)
            state.backgrounds.append(section.background)
            if sp.type not in ("cover", "closing"):
                state.content_index += 1
        sections = self.finalize(comp, sections, state)
        fonts = sorted({b.style.family for s in sections for b in s.blocks if b.style})
        return Presentation(
            family=self.info.id,
            seed=ctx.seed,
            width=ctx.width,
            sections=sections,
            title=ctx.plan.project_title,
            language=ctx.language,
            page_background=sections[0].background if sections else "#FFFFFF",
            fonts=fonts,
            variant=variant,
        )

    def setup(self, comp: Composer, variant: dict[str, Any]) -> None:
        """Hook for families to prepare styles from the variant."""

    def finalize(self, comp: Composer, sections: list[Section], state: ComposeState) -> list[Section]:
        return sections

    def compose_section(self, comp: Composer, sp: SectionPlan, state: ComposeState, is_last: bool) -> Section:
        t = sp.type
        has_images = bool(comp.assets_of(sp))
        if t == "cover":
            return self.cover(comp, sp, state)
        if t == "closing":
            return self.closing(comp, sp, state)
        if t in TEXTUAL_TYPES and not has_images:
            return self.statement(comp, sp, state)
        if t in LOGO_TYPES and has_images:
            return self.logo(comp, sp, state)
        if t == "palette" and (sp.meta.get("swatches") or has_images):
            return self.palette(comp, sp, state)
        if t == "typography" and (sp.meta.get("fonts") or has_images):
            return self.typography(comp, sp, state)
        if t == "before_after" and len(comp.assets_of(sp)) >= 2:
            return self.before_after(comp, sp, state)
        if not has_images:
            return self.statement(comp, sp, state)
        return self.media(comp, sp, state)

    # ------------------------------------------------- family must implement
    def cover(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        raise NotImplementedError

    def statement(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        raise NotImplementedError

    def logo(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        return self.media(comp, sp, state)

    def palette(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        return self.media(comp, sp, state)

    def typography(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        return self.media(comp, sp, state)

    def before_after(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        return self.media(comp, sp, state)

    def media(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        raise NotImplementedError

    def closing(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        raise NotImplementedError

    # ------------------------------------------------------------ edges
    def edge_treatment(self, comp: Composer, section: Section) -> None:
        """Give artwork whose plain edges match what is behind it a hairline
        (or soft shadow) so its format stays readable."""
        if not self.edge_style:
            return
        shapes = [b for b in section.blocks if b.kind == "shape" and b.fill and not str(b.fill).startswith(("linear", "radial"))]
        for b in section.blocks:
            if b.kind not in ("image", "video") or not b.asset_id or b.mat or b.edge:
                continue
            asset = comp.asset(b.asset_id)
            if asset is None or asset.effective_kind not in ARTWORK_KINDS:
                continue
            a = asset.analysis or {}
            edge = a.get("background")
            if not edge or edge == "transparent" or a.get("background_uniformity", 0) < 0.8:
                continue
            cx, cy = b.x + b.w / 2, b.y + b.h / 2
            behind = section.background
            for sh in shapes:
                if sh.z < b.z and sh.x <= cx <= sh.right and sh.y <= cy <= sh.bottom:
                    behind = sh.fill  # type: ignore[assignment]
            if C.delta_e(edge, behind) < 7:
                b.edge = self.edge_style
                b.edge_color = C.mix(behind, comp.palette.ink, 0.16) if self.edge_style == "outline" else None

    # ------------------------------------------------------------ overrides
    def apply_section_overrides(self, section: Section, sp: SectionPlan) -> None:
        focal = sp.meta.get("focal") or {}
        if focal:
            for b in section.blocks:
                if b.asset_id in focal and b.fit == "cover":
                    fx, fy = focal[b.asset_id]
                    b.focal = (float(fx), float(fy))
        if sp.background and C.parse_color(sp.background):
            bg = C.parse_color(sp.background)
            old = section.background
            section.background = bg  # type: ignore[assignment]
            section.gradient = None
            for b in section.blocks:
                if b.kind == "text" and b.style and not b.overlay and C.contrast_ratio(b.style.color, bg) < 4.5:  # type: ignore[arg-type]
                    b.style = b.style.with_(color=C.ensure_contrast(b.style.color, bg))  # type: ignore[arg-type]
                if b.mat == old:
                    b.mat = bg
        spacing = sp.meta.get("spacing")
        if spacing and spacing != 1.0:
            self._scale_spacing(section, float(spacing))

    @staticmethod
    def _scale_spacing(section: Section, factor: float) -> None:
        """Scale the empty space above/below the content (refinement control)."""
        content = [b for b in section.blocks if not b.decorative]
        if not content:
            return
        top = min(b.y for b in content)
        bottom = max(b.bottom for b in content)
        below = section.height - bottom
        new_top = top * factor
        shift = new_top - top
        full_height = [b for b in section.blocks if b.y <= 0.5 and b.bottom >= section.height - 0.5]
        for b in section.blocks:
            if b in full_height:
                continue
            b.y = round(b.y + shift, 2)
        section.height = round(max(1.0, bottom + shift + below * factor), 2)
        for b in full_height:
            b.h = section.height
        section.breaks = [round(y + shift, 2) for y in section.breaks if 0 < y + shift < section.height]

    # --------------------------------------------------------------- safety
    def safe_section(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        """Minimal, always-valid composition used if a pattern fails."""
        pal = comp.palette
        bg = pal.paper
        ink = comp.text_color(bg)
        ts = TypeSystem.from_dict(state.variant["type_system"])
        sb = SectionBuilder(sp, bg, "light", "safe")
        m = comp.px(120)
        sb.y = comp.px(120)
        width = comp.W - 2 * m
        title = comp.text(sp.title, m, sb.y, width, TextStyle(ts.display, comp.px(48), 500, 1.15, color=ink), "title", editable="title")
        if title:
            sb.add(title)
            sb.y = title.bottom + comp.px(24)
        body = comp.text(sp.body, m, sb.y, min(width, comp.px(720)), TextStyle(ts.text, comp.px(18), 400, 1.6, color=ink), "body", editable="body")
        if body:
            sb.add(body)
            sb.y = body.bottom + comp.px(48)
        for aid in comp.assets_of(sp):
            b = comp.natural(aid, m, sb.y, width, max_h=comp.px(1100))
            if b:
                sb.add(b)
                sb.y = b.bottom + comp.px(32)
                sb.mark_break(sb.y - comp.px(16))
        return sb.finish(comp.px(88))


def font_weight(family: str, wanted: int) -> int:
    return get_font(family).clamp_weight(wanted)
