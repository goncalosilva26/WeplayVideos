"""The five Behance Studio 2.0 concepts as layout families.

Each concept family plans with the Creative Director (or an AI director)
and composes every section with the module named in its plan. Because
they are ordinary families, versions, history, section regeneration,
editing, validation and every export work exactly as for v1 layouts.
"""

from __future__ import annotations

import random
from typing import Any

from behance_studio.design.typography import TypeSystem
from behance_studio.director.concepts import CONCEPTS, ArtDirection, art_direction, type_system_for
from behance_studio.layout.composer import ComposeContext, Composer
from behance_studio.layout.families.base import ComposeState, FamilyInfo, LayoutFamily
from behance_studio.layout.model import Block, Section
from behance_studio.layout.modules import MODULES, TEXT_MODULES
from behance_studio.layout.modules.kit import Kit
from behance_studio.planning.models import PresentationPlan, SectionPlan
from behance_studio.planning.planner import PlanPreferences


def fallback_module(sp: SectionPlan, comp: Composer) -> str:
    ids = comp.assets_of(sp)
    if sp.type == "cover":
        return "cover_logo"
    if sp.type == "closing":
        return "closing"
    if not ids:
        return "statement"
    return {1: "fullbleed", 2: "duo", 3: "trio"}.get(len(ids), "feed_grid")


class ConceptFamily(LayoutFamily):
    concept = "minimal"
    edge_style = None

    def __init__(self) -> None:
        self.ad: ArtDirection | None = None

    # ---------------------------------------------------------- planning
    def preferences(self, rng: random.Random, creativity: float) -> PlanPreferences:
        return PlanPreferences()

    def plan(self, ctx, spec) -> PresentationPlan:
        from behance_studio.director.director import direct

        return direct(ctx, self.concept, spec.seed, spec.creativity)

    # ------------------------------------------------------------ styling
    def variant(self, ctx: ComposeContext, rng: random.Random) -> dict[str, Any]:
        ad = art_direction(self.concept, ctx.direction, rng, ctx.creativity)
        return {"art_direction": ad.to_dict(), "concept": self.concept}

    def choose_type_system(self, ctx: ComposeContext, rng: random.Random) -> TypeSystem:
        ad = self.ad or art_direction(self.concept, ctx.direction, rng, ctx.creativity)
        return type_system_for(ad)

    def setup(self, comp: Composer, variant: dict[str, Any]) -> None:
        self.ad = ArtDirection.from_dict(variant["art_direction"])
        variant["type_system"] = type_system_for(self.ad).to_dict()

    # ------------------------------------------------------------ compose
    def compose_section(self, comp: Composer, sp: SectionPlan, state: ComposeState, is_last: bool) -> Section:
        assert self.ad is not None
        kit = Kit(comp, self.ad, state)
        name = sp.meta.get("module") or fallback_module(sp, comp)
        alts = list(sp.meta.get("alternatives") or [])
        vs = int(sp.meta.get("variant_seed", 0) or 0)
        if vs and len(alts) > 1:
            name = alts[(vs // 101) % len(alts)]
        fn = MODULES.get(name) or MODULES[fallback_module(sp, comp)]
        params = dict(sp.meta.get("params") or {})
        section = fn(kit, sp, params)
        section.meta["module"] = getattr(fn, "module_name", name)
        section.pattern = section.meta["module"]
        if self._needs_text_header(sp, section.meta["module"]):
            section = self._text_header(kit, sp, section)
        self._edges(kit, section)
        return section

    @staticmethod
    def _edges(kit: Kit, section: Section) -> None:
        """Finished artwork whose plain ground matches what lies behind it
        gets a hairline, so its format stays readable."""
        from behance_studio.assets.understanding import asset_nature
        from behance_studio.design import color as C

        shapes = [b for b in section.blocks if b.kind == "shape" and b.fill and C.parse_hex(str(b.fill))]
        for b in section.blocks:
            if b.kind not in ("image", "video") or not b.asset_id or b.edge or b.shadow or b.device or b.tint:
                continue
            asset = kit.asset(b.asset_id)
            if asset is None or asset_nature(asset) not in ("artwork", "document", "screen"):
                continue
            info = asset.analysis or {}
            ground = b.mat or (info.get("background") if info.get("background_uniformity", 0) >= 0.8 else None)
            if not ground or ground == "transparent" or not C.parse_hex(ground):
                continue
            behind = section.background
            cx, cy = b.x + b.w / 2, b.y + b.h / 2
            for sh in shapes:
                if sh.z < b.z and sh.x <= cx <= sh.right and sh.y <= cy <= sh.bottom:
                    behind = sh.fill
            if C.parse_hex(behind) and C.delta_e(ground, behind) < 7:
                b.edge = "outline"
                b.edge_color = C.mix(behind, kit.ad.dark, 0.16)

    @staticmethod
    def _needs_text_header(sp: SectionPlan, module: str) -> bool:
        if module in TEXT_MODULES:
            return False
        has_text = bool((sp.title or "").strip() and (sp.source == "script" or sp.meta.get("user_text"))) or bool(
            (sp.subtitle or "").strip() or (sp.body or "").strip()
        ) and (sp.source == "script" or sp.meta.get("user_text"))
        return has_text

    def _text_header(self, kit: Kit, sp: SectionPlan, section: Section) -> Section:
        """Put the section's own words above its composition (script text is
        always shown exactly)."""
        ad = kit.ad
        bg = section.background
        ink = kit.ink(bg)
        m = kit.px(max(80, ad.margin))
        y = kit.px(ad.vpad * 0.8)
        blocks: list[Block] = []
        for text, role, field in ((sp.eyebrow, "label", "eyebrow"), (sp.title, "title", "title"), (sp.subtitle, "subtitle", "subtitle"), (sp.body, "body", "body")):
            if not (text or "").strip():
                continue
            if role == "label":
                b = kit.label(text, m, y, kit.W - 2 * m, kit.soft(bg), editable=field)
            elif role == "title":
                b = kit.display(text, m, y, kit.W * 0.7, ink, 3, 32, 64, role="title", editable=field)
            else:
                b = kit.body(text, m, y, min(kit.W - 2 * m, kit.px(820)), ink, 20 if role == "subtitle" else 17, editable=field)
            if b is not None:
                blocks.append(b)
                y = b.bottom + kit.px(18)
        if not blocks:
            return section
        shift = y + kit.px(40)
        for b in section.blocks:
            b.y = round(b.y + shift, 2)
        section.blocks = blocks + section.blocks
        section.height = round(section.height + shift, 2)
        section.breaks = [shift] + [round(v + shift, 2) for v in section.breaks]
        return section

    def safe_section(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        state.variant.setdefault("type_system", type_system_for(self.ad).to_dict() if self.ad else state.variant.get("type_system"))
        return super().safe_section(comp, sp, state)


def _family(concept_id: str) -> type[ConceptFamily]:
    info = CONCEPTS[concept_id]

    class _F(ConceptFamily):
        concept = concept_id

    _F.info = FamilyInfo(info.id, info.name, info.tagline, info.description, ["Brand identity", "Case studies"], info.badge)
    _F.__name__ = f"{concept_id.title()}Concept"
    return _F


MinimalConcept = _family("minimal")
BoldConcept = _family("bold")
PhotoConcept = _family("photo")
LayeredConcept = _family("layered")
StoryConcept = _family("story")
