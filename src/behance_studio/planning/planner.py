"""Automatic narrative planning.

Turns the project material into an ordered list of sections. Two modes:

* **Script mode** – the sections, their order, text and images come from
  ``GUIAO_PROJETO.txt`` exactly; nothing is added in strict mode.
* **Automatic mode** – a category-specific story template is filled only with
  sections that the available material justifies, curated to the project
  size (a five-image project gets a compact presentation, hundreds of assets
  are curated down instead of producing an endless scroll).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Iterable

from behance_studio.assets.analysis import hamming
from behance_studio.assets.roles import quality_score
from behance_studio.brief.directives import Directives
from behance_studio.brief.language import detect_language
from behance_studio.design.direction import CreativeDirection
from behance_studio.planning.copy import Copywriter
from behance_studio.planning.models import PresentationPlan, SectionPlan
from behance_studio.planning.sections import section_type
from behance_studio.projects.models import LOGO_KINDS, PHOTO_KINDS, AssetRecord


@dataclass(frozen=True)
class Recipe:
    type: str
    kinds: tuple[str, ...]
    min_count: int = 1
    identity: bool = False  # palette/typography: can exist without image assets


@dataclass
class PlanPreferences:
    """How a layout family likes its story told."""

    max_per_section: int = 9
    include_intro: bool = True
    closing_image: bool = False
    hero_rank: int = 0
    merge_small: int = 1  # sections with fewer assets merge into a related one
    split_logo_variations: bool = True
    shuffle: float = 0.0  # 0..1 how freely optional sections may reorder
    hero_aspect: float | None = None  # frame the family's cover wants to fill


IDENTITY_STORY = [
    Recipe("logo", ("logo", "monogram", "logo_variant")),
    Recipe("palette", ("palette",), identity=True),
    Recipe("typography", ("typography",), identity=True),
    Recipe("visual_language", ("pattern", "illustration")),
    Recipe("applications", ("stationery", "mockup")),
    Recipe("packaging", ("packaging",)),
    Recipe("product", ("product",)),
    Recipe("campaign", ("poster", "outdoor")),
    Recipe("social", ("social",)),
    Recipe("editorial", ("editorial",)),
    Recipe("website", ("website",)),
    Recipe("mobile", ("mobile", "ui")),
    Recipe("photography", ("photo", "lifestyle", "portrait")),
    Recipe("motion", ("video", "motion")),
    Recipe("before_after", ("before_after",), 2),
]

TEMPLATES: dict[str, list[Recipe]] = {
    "brand_identity": IDENTITY_STORY,
    "logo_design": [
        Recipe("logo", ("logo", "monogram", "logo_variant")),
        Recipe("palette", ("palette",), identity=True),
        Recipe("typography", ("typography",), identity=True),
        Recipe("applications", ("stationery", "mockup", "packaging", "social", "poster", "outdoor")),
        Recipe("photography", ("photo", "lifestyle", "product")),
    ],
    "packaging": [
        Recipe("packaging", ("packaging",)),
        Recipe("product", ("product",)),
        Recipe("logo", ("logo", "monogram", "logo_variant")),
        Recipe("palette", ("palette",), identity=True),
        Recipe("typography", ("typography",), identity=True),
        Recipe("visual_language", ("pattern", "illustration")),
        Recipe("photography", ("photo", "lifestyle")),
        Recipe("campaign", ("poster", "outdoor")),
        Recipe("social", ("social",)),
        Recipe("motion", ("video", "motion")),
    ],
    "advertising": [
        Recipe("campaign", ("poster",)),
        Recipe("outdoor", ("outdoor",)),
        Recipe("social", ("social",)),
        Recipe("video", ("video", "motion")),
        Recipe("photography", ("photo", "lifestyle", "product")),
        Recipe("logo", ("logo", "monogram", "logo_variant")),
        Recipe("applications", ("mockup", "stationery", "packaging")),
    ],
    "campaign": [
        Recipe("campaign", ("poster", "outdoor")),
        Recipe("social", ("social",)),
        Recipe("video", ("video", "motion")),
        Recipe("photography", ("photo", "lifestyle", "product")),
        Recipe("applications", ("mockup", "stationery", "packaging")),
        Recipe("logo", ("logo", "monogram", "logo_variant")),
    ],
    "social_media": [
        Recipe("social", ("social",)),
        Recipe("campaign", ("poster", "outdoor")),
        Recipe("motion", ("video", "motion")),
        Recipe("photography", ("photo", "lifestyle", "product")),
        Recipe("logo", ("logo", "monogram", "logo_variant")),
    ],
    "photography": [
        Recipe("photography", ("photo", "lifestyle", "portrait", "product")),
        Recipe("before_after", ("before_after",), 2),
        Recipe("video", ("video", "motion")),
    ],
    "retouching": [
        Recipe("before_after", ("before_after",), 2),
        Recipe("photography", ("photo", "portrait", "lifestyle", "product")),
    ],
    "motion": [
        Recipe("motion", ("motion", "video")),
        Recipe("photography", ("photo", "lifestyle")),
        Recipe("visual_language", ("illustration", "pattern")),
        Recipe("logo", ("logo", "monogram", "logo_variant")),
    ],
    "video": [
        Recipe("video", ("video",)),
        Recipe("motion", ("motion",)),
        Recipe("photography", ("photo", "lifestyle", "portrait")),
    ],
    "illustration": [
        Recipe("illustration", ("illustration",)),
        Recipe("visual_language", ("pattern",)),
        Recipe("applications", ("mockup", "packaging", "poster", "social", "stationery", "editorial")),
        Recipe("motion", ("motion", "video")),
    ],
    "ui_ux": [
        Recipe("website", ("website",)),
        Recipe("mobile", ("mobile",)),
        Recipe("ui_screens", ("ui",)),
        Recipe("logo", ("logo", "monogram", "logo_variant")),
        Recipe("palette", ("palette",), identity=True),
        Recipe("typography", ("typography",), identity=True),
        Recipe("mockups", ("mockup",)),
    ],
    "typography": [
        Recipe("typography", ("typography",)),
        Recipe("posters", ("poster",)),
        Recipe("applications", ("mockup", "social", "packaging", "stationery", "editorial")),
    ],
    "editorial": [
        Recipe("editorial", ("editorial",)),
        Recipe("typography", ("typography",), identity=True),
        Recipe("photography", ("photo", "lifestyle", "portrait")),
        Recipe("applications", ("mockup", "stationery")),
    ],
}
TEMPLATES["website"] = TEMPLATES["ui_ux"]
TEMPLATES["app"] = [TEMPLATES["ui_ux"][1], TEMPLATES["ui_ux"][0]] + TEMPLATES["ui_ux"][2:]
TEMPLATES["product"] = TEMPLATES["packaging"]
TEMPLATES["graphic_design"] = [
    Recipe("posters", ("poster",)),
    Recipe("editorial", ("editorial",)),
    Recipe("visual_language", ("pattern", "illustration")),
    Recipe("applications", ("stationery", "mockup", "packaging")),
    Recipe("social", ("social",)),
    Recipe("outdoor", ("outdoor",)),
    Recipe("logo", ("logo", "monogram", "logo_variant")),
    Recipe("photography", ("photo", "lifestyle", "product")),
]
TEMPLATES["multimedia"] = TEMPLATES["campaign"]
TEMPLATES["mixed"] = IDENTITY_STORY

# Sections that may swap places in creative variations (never in script mode).
SWAP_PAIRS = [("palette", "typography"), ("packaging", "applications"), ("campaign", "social"), ("photography", "motion"), ("website", "mobile")]

# Small sections may only merge with neighbours of the same nature.
AFFINITY = [
    {"packaging", "product", "applications", "mockups"},
    {"campaign", "posters", "outdoor", "social"},
    {"photography", "product", "gallery"},
    {"motion", "video"},
    {"website", "mobile", "ui_screens"},
    {"visual_language", "illustration"},
]


def _related(a: str, b: str) -> bool:
    return a == b or any(a in g and b in g for g in AFFINITY)


HERO_KINDS = PHOTO_KINDS | {"mockup", "packaging", "product", "lifestyle", "outdoor", "video", "illustration", "poster", "editorial", "website"}


@dataclass
class PlanningContext:
    project_name: str
    assets: list[AssetRecord]
    directives: Directives
    direction: CreativeDirection
    issues: list[str] = field(default_factory=list)

    @property
    def language(self) -> str:
        return self.directives.language

    @property
    def title(self) -> str:
        return self.directives.project_title or self.directives.brief.project or self.project_name

    def asset(self, asset_id: str) -> AssetRecord | None:
        for a in self.assets:
            if a.id == asset_id:
                return a
        return None


def _natural_key(asset: AssetRecord) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", f"{asset.import_group}/{asset.filename}")]


def usable_assets(ctx: PlanningContext) -> list[AssetRecord]:
    excluded = ctx.directives.excluded_asset_ids
    return [a for a in ctx.assets if a.is_visual and a.id not in excluded and not a.excluded]


def dedupe_near_duplicates(assets: list[AssetRecord]) -> tuple[list[AssetRecord], list[str]]:
    """Keep the best version of visually near-identical images."""
    kept: list[AssetRecord] = []
    dropped: list[str] = []
    for asset in sorted(assets, key=lambda a: -quality_score(a)):
        dup = next(
            (k for k in kept if k.phash and asset.phash and abs(k.aspect - asset.aspect) < 0.05 and hamming(k.phash, asset.phash) <= 6 and k.effective_kind == asset.effective_kind),
            None,
        )
        if dup is not None and asset.effective_kind != "before_after":
            dropped.append(asset.id)
        else:
            kept.append(asset)
    order = {a.id: i for i, a in enumerate(assets)}
    kept.sort(key=lambda a: order[a.id])
    return kept, dropped


def curate(assets: list[AssetRecord], limit: int) -> tuple[list[AssetRecord], list[AssetRecord]]:
    """Choose up to ``limit`` assets: best quality first, avoiding look-alikes."""
    if len(assets) <= limit:
        return assets, []
    ranked = sorted(assets, key=lambda a: -quality_score(a))
    chosen: list[AssetRecord] = []
    for a in ranked:
        if len(chosen) >= limit:
            break
        if any(c.phash and a.phash and hamming(c.phash, a.phash) <= 10 for c in chosen):
            continue
        chosen.append(a)
    for a in ranked:
        if len(chosen) >= limit:
            break
        if a not in chosen:
            chosen.append(a)
    rest = [a for a in assets if a not in chosen]
    chosen.sort(key=_natural_key)
    return chosen, rest


def order_section_assets(type_id: str, assets: list[AssetRecord]) -> list[AssetRecord]:
    if not assets:
        return assets
    if type_id in ("logo", "logo_variations"):
        priority = {"logo": 0, "logo_variant": 1, "monogram": 2}

        def logo_key(a: AssetRecord):
            name = a.filename.lower()
            primary = 0 if any(w in name for w in ("primary", "principal", "main", "master")) else 1
            transparent = 0 if a.has_alpha else 1
            return (priority.get(a.effective_kind, 3), primary, transparent, -a.kind_confidence, _natural_key(a))

        return sorted(assets, key=logo_key)
    if type_id == "before_after":
        pairs: dict[str, list[AssetRecord]] = {}
        loose = []
        for a in assets:
            pair = (a.analysis or {}).get("pair")
            if pair:
                key = "|".join(sorted([a.id, pair["partner"]]))
                pairs.setdefault(key, []).append(a)
            else:
                loose.append(a)
        ordered: list[AssetRecord] = []
        for group in pairs.values():
            group.sort(key=lambda a: 0 if a.analysis.get("pair", {}).get("role") == "before" else 1)
            ordered.extend(group)
        return ordered + sorted(loose, key=_natural_key)
    natural = sorted(assets, key=_natural_key)
    if type_id in ("photography", "product", "packaging", "applications", "campaign", "motion", "video"):
        lead = max(natural, key=lambda a: (a.roles or {}).get("hero", 0) + quality_score(a) * 0.3)
        natural.remove(lead)
        natural.insert(0, lead)
    return natural


def _best_logo(assets: Iterable[AssetRecord]) -> AssetRecord | None:
    logos = [a for a in assets if a.effective_kind in LOGO_KINDS]
    if not logos:
        return None
    return order_section_assets("logo", logos)[0]


def hero_candidates(assets: list[AssetRecord]) -> list[AssetRecord]:
    pool = [a for a in assets if a.effective_kind in HERO_KINDS and (a.roles or {}).get("hero", 0) > 0.3]
    return sorted(pool, key=lambda a: -((a.roles or {}).get("hero", 0) + (0.1 if a.aspect >= 1.2 else 0)))


def _captions(ctx: PlanningContext, assets: list[AssetRecord], writer: Copywriter) -> dict[str, str]:
    captions = {}
    for a in assets:
        if a.kind_source == "user" or a.kind_confidence >= 0.7:
            cap = writer.kind_caption(a.effective_kind)
            if cap:
                captions[a.id] = cap
    return captions


# ------------------------------------------------------------- script mode
def plan_from_script(ctx: PlanningContext, prefs: PlanPreferences, seed: int) -> PresentationPlan:
    script = ctx.directives.script
    assert script is not None
    writer = Copywriter(ctx.language)
    usable = {a.id: a for a in usable_assets(ctx)}
    sections: list[SectionPlan] = []
    hero = None
    logo = _best_logo(usable.values())
    used: set[str] = set()
    for ss in script.sections:
        asset_ids = [aid for img in ss.images for aid in img.asset_ids if aid in usable]
        captions: dict[str, str] = {}
        for img in ss.images:
            if img.caption:
                for aid in img.asset_ids:
                    captions[aid] = img.caption
        title = ss.title if ss.title is not None else ss.name
        plan = SectionPlan(
            type=ss.type,
            title=title,
            subtitle=ss.subtitle or "",
            eyebrow=ss.eyebrow or "",
            body=ss.text or "",
            asset_ids=asset_ids,
            captions=captions,
            layout_hint=ss.layout,
            background=ss.background,
            source="script",
            exact_text=True,
            locked=True,
        )
        plan.meta["preserve_case"] = script.preserve_case
        if ss.type == "cover":
            if asset_ids:
                hero = asset_ids[0]
            elif ss.layout != "text":
                cands = [c for c in hero_candidates(list(usable.values())) if c.id not in script.referenced_asset_ids()]
                cands = cands or hero_candidates(list(usable.values()))
                if cands:
                    hero = cands[prefs.hero_rank % len(cands)].id
                    plan.asset_ids = [hero]
                    plan.meta["auto_image"] = True
            if logo:
                plan.meta["logo_id"] = logo.id
        if ss.type == "palette":
            plan.meta["swatches"] = [s.to_dict() for s in ctx.direction.palette.presentable]
        if ss.type == "typography":
            plan.meta["fonts"] = _font_meta(ctx, writer)
        if ss.type == "closing" and logo:
            plan.meta["logo_id"] = logo.id
        used.update(plan.asset_ids)
        sections.append(plan)

    notes: list[str] = []
    unused = [aid for aid in usable if aid not in used]
    if not script.strict and unused:
        # AUTO_SECTIONS: yes → place remaining material before the closing.
        extra_ctx = PlanningContext(ctx.project_name, [usable[a] for a in unused], ctx.directives, ctx.direction)
        auto = _auto_sections(extra_ctx, prefs, random.Random(seed), writer, exclude_types={s.type for s in sections})
        insert_at = next((i for i, s in enumerate(sections) if s.type == "closing"), len(sections))
        sections[insert_at:insert_at] = auto
        used.update(a for s in auto for a in s.asset_ids)
        unused = [aid for aid in usable if aid not in used]
        notes.append(f"{len(auto)} automatic section(s) added because the script allows extra sections.")
    if unused and script.strict:
        notes.append(f"{len(unused)} asset(s) are not referenced by the script and were not used.")
    return PresentationPlan(
        sections=sections,
        language=ctx.language,
        project_title=ctx.title,
        category=ctx.directives.category.category,
        category_label=writer.category_label(ctx.directives.category.category),
        hero_asset_id=hero,
        logo_asset_id=logo.id if logo else None,
        unused_asset_ids=unused,
        notes=notes,
        script_driven=True,
    )


def _font_meta(ctx: PlanningContext, writer: Copywriter) -> dict:
    ts = ctx.direction.type_system
    return {
        "display": ts.display,
        "text": ts.text,
        "known": ctx.direction.brand_fonts_known,
        "display_label": writer.s("headlines"),
        "text_label": writer.s("body_copy"),
    }


# ------------------------------------------------------------- auto mode
def _auto_sections(
    ctx: PlanningContext,
    prefs: PlanPreferences,
    rng: random.Random,
    writer: Copywriter,
    exclude_types: set[str] | None = None,
    reserved: set[str] | None = None,
) -> list[SectionPlan]:
    exclude_types = exclude_types or set()
    reserved = reserved or set()
    assets = [a for a in usable_assets(ctx) if a.id not in reserved]
    assets, _dropped = dedupe_near_duplicates(assets)
    buckets: dict[str, list[AssetRecord]] = {}
    for a in assets:
        buckets.setdefault(a.effective_kind, []).append(a)
    template = list(TEMPLATES.get(ctx.directives.category.category, IDENTITY_STORY))
    # Kinds not covered by the template still deserve a home.
    covered = {k for r in template for k in r.kinds}
    for kind in buckets:
        if kind not in covered:
            fallback = {
                "palette": Recipe("palette", ("palette",), identity=True),
                "typography": Recipe("typography", ("typography",), identity=True),
                "website": Recipe("website", ("website",)),
                "mobile": Recipe("mobile", ("mobile", "ui")),
                "ui": Recipe("ui_screens", ("ui",)),
                "before_after": Recipe("before_after", ("before_after",), 2),
            }.get(kind, Recipe("gallery", (kind,)))
            template.append(fallback)
            covered.update(fallback.kinds)

    total = len(assets)
    sections: list[SectionPlan] = []
    brief = ctx.directives.brief
    fonts_known = ctx.direction.brand_fonts_known
    palette_from_brief = ctx.direction.palette.source in ("brief", "mixed")
    palette_confident = palette_from_brief or (
        ctx.direction.palette.confidence >= 0.6
        and ctx.directives.category.category in ("brand_identity", "logo_design", "packaging", "ui_ux")
        and len(assets) >= 8
    )
    for recipe in template:
        if recipe.type in exclude_types:
            continue
        items: list[AssetRecord] = []
        for kind in recipe.kinds:
            items.extend(buckets.pop(kind, []))
        if recipe.identity and not items:
            if recipe.type == "palette" and palette_confident and total >= 4:
                plan = SectionPlan(type="palette", title=writer.section_title("palette"), body=writer.palette_body())
                plan.meta["swatches"] = [s.to_dict() for s in ctx.direction.palette.presentable]
                plan.meta["generated"] = True
                sections.append(plan)
            elif recipe.type == "typography" and fonts_known and total >= 4:
                plan = SectionPlan(type="typography", title=writer.section_title("typography"))
                plan.meta["fonts"] = _font_meta(ctx, writer)
                plan.body = writer.typography_body(ctx.direction.type_system.display, ctx.direction.type_system.text)
                plan.meta["generated"] = True
                sections.append(plan)
            continue
        if len(items) < recipe.min_count:
            for a in items:
                buckets.setdefault(a.effective_kind, []).append(a)
            continue
        if not items:
            continue
        items = order_section_assets(recipe.type, items)
        # Split logo system into identity + variations when rich enough.
        if recipe.type == "logo" and prefs.split_logo_variations and len(items) >= 4:
            main, variations = items[:2], items[2:]
            sections.append(_section(ctx, "logo", main, writer))
            sections.append(_section(ctx, "logo_variations", variations[: prefs.max_per_section], writer))
            continue
        chosen, rest = curate(items, prefs.max_per_section)
        chosen = order_section_assets(recipe.type, chosen)
        sections.append(_section(ctx, recipe.type, chosen, writer))
        # A second chapter for large collections, then stop (curation).
        if rest and len(rest) >= 3 and recipe.type in ("photography", "social", "campaign", "packaging", "illustration", "ui_screens", "website", "mobile"):
            more, _ = curate(rest, prefs.max_per_section)
            extra = _section(ctx, recipe.type, order_section_assets(recipe.type, more), writer)
            extra.meta["continuation"] = True
            extra.title = writer.section_title(recipe.type)
            sections.append(extra)
        if recipe.type == "palette":
            sections[-1].meta["swatches"] = [s.to_dict() for s in ctx.direction.palette.presentable]
            sections[-1].body = writer.palette_body() if not sections[-1].body else sections[-1].body
        if recipe.type == "typography" and fonts_known:
            sections[-1].meta["fonts"] = _font_meta(ctx, writer)
            sections[-1].body = writer.typography_body(ctx.direction.type_system.display, ctx.direction.type_system.text)

    # Leftover kinds (too few to stand alone) join the most related section.
    leftovers = [a for items in buckets.values() for a in items]
    if leftovers:
        target = next((s for s in sections if s.type in ("applications", "gallery", "campaign", "photography")), None)
        if target is not None and len(target.asset_ids) + len(leftovers) <= prefs.max_per_section + 3:
            target.asset_ids.extend(a.id for a in leftovers)
        elif len(leftovers) >= 2:
            sections.append(_section(ctx, "gallery", sorted(leftovers, key=_natural_key)[: prefs.max_per_section], writer))
        elif sections and len(leftovers) == 1:
            sections[-1].asset_ids.append(leftovers[0].id)

    # Merge very small sections into a related neighbour (either side).
    if prefs.merge_small > 1:
        changed = True
        while changed:
            changed = False
            for i, s in enumerate(sections):
                if not s.asset_ids or len(s.asset_ids) >= prefs.merge_small or s.meta.get("continuation"):
                    continue
                for j in (i - 1, i + 1):
                    if 0 <= j < len(sections):
                        other = sections[j]
                        if (
                            other.asset_ids
                            and _related(s.type, other.type)
                            and len(other.asset_ids) + len(s.asset_ids) <= prefs.max_per_section
                        ):
                            big, small = (other, s) if len(other.asset_ids) >= len(s.asset_ids) else (s, other)
                            if j < i:
                                other.asset_ids.extend(s.asset_ids)
                            else:
                                other.asset_ids[:0] = s.asset_ids
                            other.captions.update(s.captions)
                            other.type, other.title = big.type, big.title
                            sections.pop(i)
                            changed = True
                            break
                if changed:
                    break

    # Creative reordering of interchangeable neighbours.
    if prefs.shuffle > 0:
        types = [s.type for s in sections]
        for a, b in SWAP_PAIRS:
            if a in types and b in types and rng.random() < prefs.shuffle:
                ia, ib = types.index(a), types.index(b)
                sections[ia], sections[ib] = sections[ib], sections[ia]
                types[ia], types[ib] = types[ib], types[ia]
    return sections


def _useful_captions(captions: dict[str, str], title: str) -> dict[str, str]:
    """Keep generated captions only when they tell items apart."""
    t = title.casefold()
    kept = {k: v for k, v in captions.items() if v.casefold() not in t and t not in v.casefold()}
    if len(set(kept.values())) < 2:
        return {}
    return kept


def _section(ctx: PlanningContext, type_id: str, assets: list[AssetRecord], writer: Copywriter) -> SectionPlan:
    title = writer.section_title(type_id)
    plan = SectionPlan(
        type=type_id,
        title=title,
        asset_ids=[a.id for a in assets],
        captions=_useful_captions(_captions(ctx, assets, writer), title),
    )
    plan.importance = min(1.0, 0.4 + 0.08 * len(assets))
    return plan


def plan_automatic(ctx: PlanningContext, prefs: PlanPreferences, seed: int) -> PresentationPlan:
    rng = random.Random(seed)
    writer = Copywriter(ctx.language)
    usable = usable_assets(ctx)
    brief = ctx.directives.brief
    heroes = hero_candidates(usable)
    if prefs.hero_aspect and heroes:
        from behance_studio.layout.fitting import can_cover

        fits = [h for h in heroes if can_cover(h, prefs.hero_aspect)]
        heroes = fits + [h for h in heroes if h not in fits]
    hero = heroes[prefs.hero_rank % len(heroes)] if heroes else None
    logo = _best_logo(usable)
    # The hero opens the cover and is not repeated in the body sections.
    reserved: set[str] = {hero.id} if hero is not None else set()
    body_sections = _auto_sections(ctx, prefs, rng, writer, reserved=reserved)

    sections: list[SectionPlan] = []
    cover = SectionPlan(type="cover", title=ctx.title)
    tagline = brief.messages[0] if brief.messages and detect_language(brief.messages[0], ctx.language) == ctx.language else ""
    if tagline:
        cover.subtitle = tagline
        cover.exact_text = True
        cover.meta["subtitle_source"] = "brief"
    cover.eyebrow = writer.category_label(ctx.directives.category.category)
    if hero is not None:
        cover.asset_ids = [hero.id]
    if logo is not None:
        cover.meta["logo_id"] = logo.id
    cover.importance = 1.0
    sections.append(cover)

    total_assets = len(usable)
    if prefs.include_intro and (brief.about or (total_assets >= 6 and len(body_sections) >= 3)):
        intro = SectionPlan(type="intro", title=writer.s("intro_title"))
        if brief.about and detect_language(brief.about, ctx.language) == ctx.language:
            intro.body = brief.about.strip()
            intro.exact_text = True
            intro.meta["body_source"] = "brief"
        else:
            intro.body = writer.intro_text(ctx.title, ctx.directives.category.category, [s.type for s in body_sections])
            intro.meta["body_source"] = "generated"
        if brief.audience and brief.about:
            intro.meta["audience"] = brief.audience.strip()
        if len(brief.messages) > 1:
            intro.meta["quote"] = brief.messages[1]
        intro.importance = 0.6
        sections.append(intro)

    sections.extend(body_sections)

    closing = SectionPlan(type="closing", title=writer.s("thank_you"))
    if logo is not None:
        closing.meta["logo_id"] = logo.id
    if prefs.closing_image:
        used = {aid for s in sections for aid in s.asset_ids}
        candidate = next((h for h in heroes if h.id not in used), None)
        if candidate is not None:
            closing.asset_ids = [candidate.id]
        elif hero is not None:
            closing.asset_ids = [hero.id]
            closing.meta["reprise"] = True  # justified repeat of the cover image
    closing.importance = 0.5
    sections.append(closing)

    used_ids = {aid for s in sections for aid in s.asset_ids}
    unused = [a.id for a in usable if a.id not in used_ids]
    notes = []
    if unused:
        notes.append(f"{len(unused)} asset(s) were left out to keep the presentation focused (near-duplicates or lower priority).")
    return PresentationPlan(
        sections=sections,
        language=ctx.language,
        project_title=ctx.title,
        category=ctx.directives.category.category,
        category_label=writer.category_label(ctx.directives.category.category),
        hero_asset_id=hero.id if hero else None,
        logo_asset_id=logo.id if logo else None,
        unused_asset_ids=unused,
        notes=notes,
        script_driven=False,
    )


def assign_stable_ids(plan: PresentationPlan) -> PresentationPlan:
    """Content-derived section ids: re-planning the same material yields the
    same ids, so seeded compositions are exactly reproducible."""
    import hashlib

    for index, sp in enumerate(plan.sections):
        key = f"{index}:{sp.type}:{sp.title}:{','.join(sp.asset_ids)}"
        sp.id = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return plan


def plan_presentation(ctx: PlanningContext, prefs: PlanPreferences | None = None, seed: int = 0) -> PresentationPlan:
    prefs = prefs or PlanPreferences()
    if ctx.directives.script_locked:
        return assign_stable_ids(plan_from_script(ctx, prefs, seed))
    return assign_stable_ids(plan_automatic(ctx, prefs, seed))


def describe_plan(plan: PresentationPlan) -> str:
    lines = [f"{plan.project_title} — {plan.category_label} ({plan.language})"]
    for i, s in enumerate(plan.sections, 1):
        lines.append(f"{i:02d}. {section_type(s.type).id:16} {s.title!r} assets={len(s.asset_ids)}{' [script]' if s.source == 'script' else ''}")
    return "\n".join(lines)
