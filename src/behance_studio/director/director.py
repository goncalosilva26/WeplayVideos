"""Local Creative Director: plans a complete case study for one concept.

The director decides — like a designer would — which assets to show, how
the story opens and closes, the order of chapters, which compositional
module each section uses, where the brand messages pause the sequence and
how long the presentation is. Its output is a normal ``PresentationPlan``
whose sections carry ``meta.module`` and ``meta.params``, so the result is
reproducible, editable section by section and validated like any other
plan. An AI director (``behance_studio.ai``) produces the same structure.

Rules that keep it honest:

* text comes only from the user (brief, script) or is generic and factual
  (section names, deliverables derived from the assets present);
* finished artwork is never planned into crop-only modules;
* script-driven projects keep the script's order, text and images exactly.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from behance_studio.brief.language import detect_language
from behance_studio.design import color as C
from behance_studio.director.inventory import Inventory, build_inventory
from behance_studio.planning.copy import Copywriter
from behance_studio.planning.models import PresentationPlan, SectionPlan
from behance_studio.planning.planner import PlanningContext, PlanPreferences, assign_stable_ids, plan_from_script
from behance_studio.projects.models import AssetRecord

DELIVERABLES = {
    "logo": ("Logo", "Logótipo"),
    "palette": ("Colour", "Cor"),
    "typography": ("Typography", "Tipografia"),
    "pattern": ("Pattern", "Padrão"),
    "packaging": ("Packaging", "Embalagem"),
    "stationery": ("Stationery", "Papelaria"),
    "campaign": ("Campaign", "Campanha"),
    "outdoor": ("Outdoor", "Exterior"),
    "social": ("Social media", "Redes sociais"),
    "photography": ("Photography", "Fotografia"),
    "digital": ("Digital", "Digital"),
    "motion": ("Motion", "Motion"),
}

CHAPTERS = {
    "identity": ("Identity", "Identidade"),
    "colour": ("Colour & type", "Cor e tipografia"),
    "places": ("Applications", "Aplicações"),
    "campaign": ("Campaign", "Campanha"),
    "social": ("Social", "Redes sociais"),
    "imagery": ("Imagery", "Imagem"),
}

# Alternatives a section may switch to when regenerated (same content).
ALTERNATIVES = {
    "fullbleed": ["fullbleed", "stage"],
    "duo": ["duo", "trio", "stage_pair"],
    "trio": ["trio", "duo", "masked_trio"],
    "stage": ["stage", "fullbleed"],
    "stage_pair": ["stage_pair", "float_stack", "poster_wall"],
    "poster_wall": ["poster_wall", "stage_pair", "float_stack"],
    "float_stack": ["float_stack", "stage_pair", "poster_wall"],
    "phones": ["phones", "feed_grid"],
    "feed_grid": ["feed_grid", "phones"],
    "logo_hero": ["logo_hero", "logo_pair"],
    "logo_tiles": ["logo_tiles", "logo_hero"],
    "logo_cards": ["logo_cards", "logo_tiles"],
    "palette_columns": ["palette_columns", "palette_circles"],
    "palette_circles": ["palette_circles", "palette_columns"],
    "cover_logo": ["cover_logo", "cover_split"],
    "cover_hero": ["cover_hero", "cover_split"],
    "cover_split": ["cover_split", "cover_logo"],
    "collage": ["collage", "stage_pair"],
    "masked_trio": ["masked_trio", "trio"],
    "letterbox": ["letterbox", "fullbleed"],
    "filmstrip": ["filmstrip", "trio"],
    "chapter_spread": ["chapter_spread", "chapter"],
    "statement": ["statement"],
    "quote_band": ["quote_band"],
}


@dataclass
class _Builder:
    ctx: PlanningContext
    inv: Inventory
    concept: str
    rng: random.Random
    writer: Copywriter
    sections: list[SectionPlan] = field(default_factory=list)
    used: set[str] = field(default_factory=set)
    messages_used: set[str] = field(default_factory=set)
    chapter_no: int = 0

    def message(self, candidates: list[str]) -> str:
        """The first brand message not shown yet (each is used once)."""
        for m in candidates:
            if m and m not in self.messages_used:
                self.messages_used.add(m)
                return m
        return ""

    def lang_pick(self, pair: tuple[str, str]) -> str:
        return pair[1] if self.ctx.language == "pt" else pair[0]

    def add(self, type_: str, module: str, assets: list[AssetRecord] | list[str] = (), title: str = "", **kw) -> SectionPlan:
        ids = [a.id if isinstance(a, AssetRecord) else a for a in assets]
        sp = SectionPlan(type=type_, title=title or self.writer.section_title(type_), asset_ids=ids)
        params = kw.pop("params", {})
        for key, value in kw.items():
            if key in ("subtitle", "body", "eyebrow", "exact_text"):
                setattr(sp, key, value)
            else:
                sp.meta[key] = value
        sp.meta["module"] = module
        sp.meta["params"] = params
        sp.meta["alternatives"] = ALTERNATIVES.get(module, [module])
        self.used.update(i for i in ids if i)
        self.sections.append(sp)
        return sp

    @property
    def compact(self) -> bool:
        """Small projects get a short, focused presentation."""
        return self.inv.count() < 8

    def take(self, group: list[AssetRecord], n: int) -> list[AssetRecord]:
        picks = [a for a in group if a.id not in self.used][:n]
        return picks

    def chapter(self, key: str, asset: AssetRecord | None = None) -> None:
        self.chapter_no += 1
        if asset is not None:
            self.add("custom", "chapter_spread", [asset], title=self.lang_pick(CHAPTERS[key]), params={"number": self.chapter_no}, chapter=True)
        else:
            self.add("custom", "chapter", title=self.lang_pick(CHAPTERS[key]), params={"number": self.chapter_no}, chapter=True)


def _tagline(ctx: PlanningContext) -> tuple[str, list[str]]:
    msgs = [m for m in ctx.directives.brief.messages if detect_language(m, ctx.language) == ctx.language]
    return (msgs[0], msgs[1:]) if msgs else ("", [])


def _deliverables(inv: Inventory, ctx: PlanningContext, lang: str) -> str:
    keys = []
    if inv.logo or inv.marks:
        keys.append("logo")
    if len(ctx.direction.palette.presentable) >= 2:
        keys.append("palette")
    if ctx.direction.brand_fonts_known or inv.documents.get("typography"):
        keys.append("typography")
    if inv.patterns:
        keys.append("pattern")
    kinds = {a.effective_kind for a in inv.scenes + inv.artworks}
    if "packaging" in kinds:
        keys.append("packaging")
    if "stationery" in kinds:
        keys.append("stationery")
    if inv.posters:
        keys.append("campaign")
    if inv.outdoor or "outdoor" in kinds:
        keys.append("outdoor")
    if inv.social:
        keys.append("social")
    if inv.photos:
        keys.append("photography")
    if inv.screens:
        keys.append("digital")
    if inv.motion:
        keys.append("motion")
    labels = [DELIVERABLES[k][1 if lang == "pt" else 0] for k in keys]
    return ", ".join(labels)


def _hero(inv: Inventory, rank: int) -> AssetRecord | None:
    pool = [a for a in inv.imagery if a.aspect >= 1.2] or list(inv.imagery)
    pool.sort(key=lambda a: -((a.roles or {}).get("hero", 0) * 0.6 + (0.25 if a.aspect >= 1.3 else 0) + (a.analysis or {}).get("sharpness", 0) / 4000))
    return pool[rank % len(pool)] if pool else None


def _swatches(ctx: PlanningContext) -> list[dict]:
    pal = ctx.direction.palette
    out = []
    for s in pal.presentable:
        out.append({"hex": s.hex, "name": s.name if pal.source == "brief" else None, "role": s.role})
    # Lead with the most characteristic colour (highest chroma).
    out.sort(key=lambda s: -C.chroma(s["hex"]) if s["role"] != "dark" else 0)
    return out


KIND_SECTION = {"packaging": "packaging", "product": "product", "outdoor": "outdoor", "mockup": "mockups",
                "stationery": "applications", "photo": "photography", "lifestyle": "photography", "portrait": "photography"}


def _type_for(group: list[AssetRecord], default: str) -> str:
    """The most specific section type the group's assets share."""
    kinds = {KIND_SECTION.get(a.effective_kind) for a in group}
    return kinds.pop() if len(kinds) == 1 and None not in kinds else default


def _imagery_groups(b: _Builder, assets: list[AssetRecord], pattern: list[str], type_: str) -> None:
    """Emit image sections following a rhythm of module sizes.

    Full-bleed slots take landscape images; squares and portraits are paired
    (a full-width square or portrait would be cropped hard or enormous)."""
    i = 0
    queue = list(assets)
    guard = 0
    while queue and guard < 40:
        guard += 1
        module = pattern[i % len(pattern)]
        i += 1
        if module == "fullbleed":
            wide = next((a for a in queue if a.aspect >= 1.25), None)
            if wide is None:
                if len(queue) == 1:
                    lone = queue.pop(0)
                    b.add(_type_for([lone], type_), "stage" if b.concept != "photo" else "fullbleed", [lone])
                continue
            queue.remove(wide)
            b.add(_type_for([wide], type_), "fullbleed", [wide])
            continue
        need = {"stage": 1, "duo": 2, "trio": 3, "masked_trio": 3, "collage": 2}.get(module, 2)
        if len(queue) < need:
            if len(queue) == 1:
                lone = queue.pop(0)
                b.add(_type_for([lone], type_), "fullbleed" if lone.aspect >= 1.25 else "stage", [lone])
                continue
            module, need = "duo", 2
        group, queue = queue[:need], queue[need:]
        b.add(_type_for(group, type_ if type_ in ("applications", "gallery") else "gallery"), module, group)


def _common_opening(b: _Builder, cover_module: str, hero: AssetRecord | None, tagline: str) -> None:
    ctx, inv = b.ctx, b.inv
    assets = [hero] if hero is not None and cover_module != "cover_logo" else ([inv.logo] if inv.logo else [])
    b.add(
        "cover", cover_module, assets, title=ctx.title, subtitle=tagline, eyebrow=b.writer.category_label(ctx.directives.category.category),
        exact_text=bool(tagline), logo_id=inv.logo.id if inv.logo else None,
    )


def _statement(b: _Builder, params: dict | None = None) -> None:
    ctx = b.ctx
    brief = ctx.directives.brief
    about = brief.about.strip() if brief.about and detect_language(brief.about, ctx.language) == ctx.language else ""
    if not about and b.inv.count() < 6:
        return
    body = about or b.writer.intro_text(ctx.title, ctx.directives.category.category, [s.type for s in b.sections])
    facts = [
        (b.lang_pick(("Client", "Cliente")), ctx.title),
        (b.lang_pick(("Category", "Categoria")), b.writer.category_label(ctx.directives.category.category)),
    ]
    deliv = _deliverables(b.inv, ctx, ctx.language)
    if deliv:
        facts.append((b.lang_pick(("Deliverables", "Entregáveis")), deliv))
    _tagline_, rest = _tagline(ctx)
    head = rest[0] if (b.concept == "bold" and rest) else ""
    if head:
        b.messages_used.add(head)
    b.add("intro", "statement", body=body, exact_text=bool(about), subtitle=head,
          facts=facts, body_source="brief" if about else "generated", params=params or {})


def _identity(b: _Builder, hero_module: str, tiles: bool = True, pair: bool = False) -> None:
    inv = b.inv
    if b.compact:
        tiles = tiles and len(inv.logo_alts + inv.marks + inv.logo_panels) >= 2
    if inv.logo:
        b.add("logo", hero_module, [inv.logo], logo_id=inv.logo.id)
    if pair and inv.logo and inv.logo_panels:
        b.add("logo_variations", "logo_pair", [inv.logo, inv.logo_panels[0]], logo_id=inv.logo.id)
    rest = [a for a in inv.logo_alts + inv.marks + inv.logo_panels if a.id not in b.used]
    if tiles and rest:
        b.add("logo_variations", "logo_tiles", rest[:4])


def _colour_and_type(b: _Builder, palette_module: str) -> None:
    ctx, inv = b.ctx, b.inv
    sw = _swatches(ctx)
    if b.compact and ctx.direction.palette.source != "brief":
        sw = []  # a palette sampled from five images is not worth a section
    if len(sw) >= 2:
        b.add("palette", palette_module, [], swatches=sw)
    elif inv.documents.get("palette"):
        b.add("palette", "doc_stage", inv.documents["palette"][:1])
    ts = ctx.direction.type_system
    if ctx.direction.brand_fonts_known:
        b.add("typography", "type_specimen", [], fonts={"display": ts.display, "text": ts.text})
    elif inv.documents.get("typography"):
        b.add("typography", "doc_stage", inv.documents["typography"][:1])


def _social(b: _Builder, module: str, n: int) -> None:
    posts = b.take(b.inv.social, n)
    if not posts:
        return
    if module == "phones" and len(posts) > 3:
        posts = posts[:3]
    b.add("social", module if len(posts) >= 2 or module == "phones" else "stage", posts)


def _closing(b: _Builder, message: str = "") -> None:
    inv = b.inv
    b.add("closing", "closing", [], title=b.writer.s("thank_you"), body=message, exact_text=bool(message),
          logo_id=inv.logo.id if inv.logo else None, logo_panel_id=inv.logo_panels[0].id if inv.logo_panels else None)


def _maskable(photos: list[AssetRecord]) -> bool:
    """Can these three photographs take circle, arch and landscape masks?"""
    from behance_studio.layout.fitting import can_cover

    if len(photos) < 3:
        return False
    return can_cover(photos[0], 1.0) and can_cover(photos[1], 1 / 1.32) and can_cover(photos[2], 1.25)


def _pick_maskable(pool: list[AssetRecord]) -> list[AssetRecord] | None:
    from itertools import permutations

    for combo in permutations(pool[:6], 3):
        if _maskable(list(combo)):
            return list(combo)
    return None


# ----------------------------------------------------------------- concepts
def _minimal(b: _Builder) -> None:
    inv = b.inv
    tagline, _rest = _tagline(b.ctx)
    hero = _hero(inv, b.rng.randrange(2))
    cover = "cover_split" if hero is not None and b.rng.random() < 0.45 else "cover_logo"
    _common_opening(b, cover, hero, tagline)
    _statement(b)
    if cover == "cover_logo" and hero is not None and not b.compact:
        b.add(_type_for([hero], "gallery"), "fullbleed", [hero])
    _identity(b, "logo_hero")
    _colour_and_type(b, "palette_columns")
    if inv.patterns:
        b.add("visual_language", "pattern_field", inv.patterns[:1], params={"badge": False})
    _imagery_groups(b, b.take(inv.scenes, 4), ["duo", "fullbleed"], "applications")
    posters = b.take(inv.posters, 2)
    if posters:
        b.add("campaign", "stage_pair" if len(posters) > 1 else "stage", posters)
    for art in b.take(inv.outdoor, 1):
        b.add("outdoor", "fullbleed", [art])
    _imagery_groups(b, b.take(inv.photos, 4), ["trio", "duo"], "photography")
    _social(b, "feed_grid", 6)
    for s in b.take(inv.screens, 1):
        b.add("website", "browser" if s.aspect >= 1 else "phones", [s])
    for m in b.take(inv.motion, 1):
        b.add("motion", "video_stage", [m])
    _closing(b)


def _bold(b: _Builder) -> None:
    inv = b.inv
    tagline, rest = _tagline(b.ctx)
    _common_opening(b, "cover_logo", None, tagline)
    _statement(b)
    if inv.marks:
        b.add("logo", "mark_feature", inv.marks[:1], title=b.ctx.title)
    _identity(b, "logo_hero")
    _colour_and_type(b, "palette_columns")
    if inv.patterns:
        b.add("visual_language", "pattern_field", inv.patterns[:1], logo_id=(inv.marks[0].id if inv.marks else (inv.logo.id if inv.logo else None)))
    _imagery_groups(b, b.take(inv.scenes, 4), ["duo", "duo", "fullbleed"], "applications")
    quote = b.message(rest)
    if quote:
        b.add("brand_story", "quote_band", [], body=quote, exact_text=True)
    posters = b.take(inv.posters, 3)
    if posters:
        b.add("campaign", "stage_pair" if len(posters) >= 2 else "stage", posters[:2])
    for art in b.take(inv.outdoor, 1):
        b.add("outdoor", "fullbleed", [art])
    _social(b, "phones", 3)
    _imagery_groups(b, b.take(inv.photos, 3), ["duo", "fullbleed"], "photography")
    for m in b.take(inv.motion, 1):
        b.add("motion", "video_stage", [m])
    _closing(b, tagline)


def _photo(b: _Builder) -> None:
    inv = b.inv
    tagline, rest = _tagline(b.ctx)
    hero = _hero(inv, b.rng.randrange(3))
    _common_opening(b, "cover_hero" if hero is not None else "cover_logo", hero, tagline)
    _statement(b)
    lead = b.take(inv.photos, 1)
    if lead:
        b.add("photography", "fullbleed", lead)
    if inv.logo and inv.logo_panels:
        b.add("logo", "logo_pair", [inv.logo, inv.logo_panels[0]], logo_id=inv.logo.id)
    else:
        _identity(b, "logo_hero", tiles=False)
    _imagery_groups(b, b.take(inv.photos, 5), ["duo", "trio", "fullbleed"], "photography")
    _imagery_groups(b, b.take(inv.scenes, 4), ["fullbleed", "duo"], "applications")
    posters = b.take(inv.posters, 3)
    if posters:
        b.add("campaign", "poster_wall", posters)
    for art in b.take(inv.outdoor, 1):
        b.add("outdoor", "fullbleed", [art])
    _social(b, "feed_grid", 6)
    sw = _swatches(b.ctx)
    if len(sw) >= 2:
        b.add("palette", "palette_columns", [], swatches=sw, params={"height": 380})
    for m in b.take(inv.motion, 1):
        b.add("motion", "video_stage", [m])
    _closing(b)


def _layered(b: _Builder) -> None:
    inv = b.inv
    tagline, rest = _tagline(b.ctx)
    hero = _hero(inv, b.rng.randrange(2) + 1)
    card = (inv.posters or inv.social or inv.artworks or [None])[0]
    if hero is not None and card is not None:
        b.add("cover", "collage", [hero, card], title=b.ctx.title, subtitle=tagline, exact_text=bool(tagline),
              eyebrow=b.writer.category_label(b.ctx.directives.category.category), logo_id=inv.logo.id if inv.logo else None)
    else:
        _common_opening(b, "cover_split" if hero else "cover_logo", hero, tagline)
    _statement(b)
    if inv.logo:
        system = [inv.logo] + [a for a in inv.logo_alts + inv.marks + inv.logo_panels][:3]
        b.add("logo", "logo_cards", system, logo_id=inv.logo.id, pattern_id=inv.patterns[0].id if inv.patterns else None)
    _colour_and_type(b, "palette_circles")
    cards = b.take(inv.posters, 3) + b.take(inv.social, 4)
    cards = [c for c in cards if c.id not in b.used]
    if len(cards) >= 2:
        b.add("campaign", "float_stack", cards[:4], pattern_id=inv.patterns[0].id if inv.patterns else None)
    trio = _pick_maskable([a for a in inv.imagery if a.id not in b.used])
    if trio:
        b.add(_type_for(trio, "gallery"), "masked_trio", trio)
    else:
        _imagery_groups(b, b.take(inv.photos, 3), ["trio", "duo"], "photography")
    scenes = b.take(inv.scenes, 4)
    arts = [a for a in inv.posters + inv.social + inv.artworks if a.id not in b.used]
    if scenes and arts:
        msg = b.message(rest)
        b.add("applications", "collage", [scenes[0], arts[0]], subtitle=msg, exact_text=bool(msg))
        scenes = scenes[1:]
    _imagery_groups(b, scenes, ["duo", "fullbleed"], "applications")
    if inv.patterns and inv.patterns[0].id not in b.used:
        b.add("visual_language", "pattern_field", inv.patterns[:1], logo_id=(inv.marks[0].id if inv.marks else (inv.logo.id if inv.logo else None)))
    for art in b.take(inv.outdoor, 1):
        b.add("outdoor", "fullbleed", [art])
    _social(b, "phones", 3)
    _closing(b)


def _story(b: _Builder) -> None:
    """Acts with chapter spreads, cinematic frames and sequences."""
    inv = b.inv
    tagline, rest = _tagline(b.ctx)
    b.messages_used.add(tagline)
    hero = _hero(inv, b.rng.randrange(2))
    _common_opening(b, "cover_hero" if hero is not None else "cover_logo", hero, tagline)
    _statement(b, {"align": "center"})
    b.chapter("identity", inv.logo)
    if inv.logo:
        b.used.add(inv.logo.id)
    rest_marks = [a for a in inv.logo_alts + inv.marks + inv.logo_panels if a.id not in b.used]
    if rest_marks:
        b.add("logo_variations", "logo_tiles", rest_marks[:4])
    _colour_and_type(b, "palette_columns")
    quote = b.message(rest)
    if quote:
        b.add("brand_story", "quote_band", [], body=quote, exact_text=True)
    imagery = [a for a in inv.imagery if a.id not in b.used]
    if imagery:
        from behance_studio.layout.fitting import can_cover

        # A chapter spread shows its image in a tall half: pick one that fills it.
        lead = next((a for a in imagery if can_cover(a, 0.8)), None)
        b.chapter("places", lead)
        if lead is not None:
            imagery = [a for a in imagery if a.id != lead.id]
        wide = [a for a in imagery if a.aspect >= 1.3]
        if wide:
            b.add(_type_for(wide[:1], "gallery"), "letterbox", wide[:1], params={"index": 1})
            imagery = [a for a in imagery if a.id != wide[0].id]
        if len(imagery) >= 3:
            b.add(_type_for(imagery[:3], "gallery"), "filmstrip", imagery[:3])
            imagery = imagery[3:]
        _imagery_groups(b, imagery[:3], ["duo", "fullbleed"], "gallery")
    posters = b.take(inv.posters, 3)
    outdoor = b.take(inv.outdoor, 1)
    if posters or outdoor or inv.social:
        # A portrait poster suits the tall half of the chapter spread.
        b.chapter("campaign", posters[0] if posters else None)
        if len(posters) > 1:
            b.add("campaign", "stage_pair" if len(posters) >= 3 else "stage", posters[1:3])
        for art in outdoor:
            b.add("outdoor", "fullbleed", [art])
        _social(b, "phones", 3)
    _closing(b, tagline)


# ------------------------------------------------------- folder-organised projects
# When the designer organised the files in section folders, each concept keeps
# every image inside its folder's section. Concepts still differ in cover,
# modules, image sizes, rhythm, chapters, pauses and backgrounds.
LOGO_KINDS_ = {"logo", "logo_variant", "monogram"}
# How each concept shows photographs inside a folder section.
FOLDER_PHOTO_PATTERN = {"minimal": ["duo", "duo", "fullbleed"], "bold": ["stage"], "photo": ["trio", "fullbleed", "duo"],
                        "layered": ["trio", "duo"], "story": ["fullbleed", "duo"]}


def _treatment(a: AssetRecord) -> str:
    from behance_studio.assets.understanding import asset_nature

    kind, nature = a.effective_kind, asset_nature(a)
    if kind in LOGO_KINDS_:
        return "logo"
    if kind in ("palette", "typography") or nature == "document":
        return "sheet"
    if kind == "pattern":
        return "pattern"
    if nature == "motion":
        return "motion"
    if kind == "social":
        return "social"
    if nature == "screen":
        return "screen"
    if nature == "artwork":
        return "art"
    return "photo"


def _folder_hero(b: "_Builder", groups) -> AssetRecord | None:
    """A cover image: a landscape photograph, preferably from a photography folder."""
    from behance_studio.assets.understanding import asset_nature
    from behance_studio.layout.fitting import can_cover

    def pool(types: set[str] | None) -> list[AssetRecord]:
        out = []
        for placement, ids in groups:
            if types is not None and placement.type not in types:
                continue
            out += [b.inv.by_id[i] for i in ids if i in b.inv.by_id and asset_nature(b.inv.by_id[i]) == "photo"]
        return [a for a in out if a.aspect >= 1.2 and can_cover(a, 1.6)]

    candidates = pool({"photography"}) or pool(None)
    from behance_studio.assets.understanding import strength

    candidates.sort(key=lambda a: (-(strength(a) + 0.25 * (a.roles or {}).get("hero", 0)), a.filename.lower()))
    if not candidates:
        return None
    rank = {"photo": 0, "story": 1}.get(b.concept, b.rng.randrange(2))  # concepts open on different images
    return candidates[rank % len(candidates)]


def _chunks(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# Module per concept for each kind of material (photographs use FOLDER_PHOTO_PATTERN).
GROUP_MODULE = {
    "sheet": {"minimal": "doc_stage", "bold": "stage_pair", "photo": "poster_wall", "layered": "float_stack", "story": "doc_stage"},
    "pattern": {"minimal": "pattern_field", "bold": "pattern_field", "photo": "poster_wall", "layered": "float_stack", "story": "duo"},
    "social": {"minimal": "phones", "bold": "feed_grid", "photo": "poster_wall", "layered": "float_stack", "story": "stage_pair"},
    "art": {"minimal": "trio", "bold": "stage_pair", "photo": "poster_wall", "layered": "float_stack", "story": "stage"},
}
GROUP_SIZE = {"doc_stage": 1, "stage": 1, "pattern_field": 1, "stage_pair": 2, "duo": 2, "trio": 3, "poster_wall": 3, "phones": 3,
              "float_stack": 4, "feed_grid": 9, "logo_tiles": 4, "logo_cards": 4}
GROUP_MIN = {"stage_pair": 2, "duo": 2, "trio": 3, "poster_wall": 2, "float_stack": 2, "feed_grid": 3, "logo_tiles": 2, "logo_cards": 2}


def _emit_grouped(b: "_Builder", type_: str, module: str, assets: list[AssetRecord], single: str = "stage", **meta) -> None:
    for chunk in _chunks(assets, GROUP_SIZE.get(module, 1)):
        if len(chunk) < GROUP_MIN.get(module, 1):
            for a in chunk:
                b.add(_type_for([a], type_), single, [a], **meta)
        else:
            b.add(_type_for(chunk, type_), module, chunk, **meta)


def _emit(b: "_Builder", treatment: str, assets: list[AssetRecord]) -> None:
    """Modules for one kind of material inside a folder section (concept-specific)."""
    concept, inv = b.concept, b.inv
    if treatment == "logo":
        first, rest = assets[0], assets[1:]
        if concept == "layered" and len(assets) >= 2:
            b.add("logo", "logo_cards", assets[:4], logo_id=first.id, pattern_id=inv.patterns[0].id if inv.patterns else None)
            rest = assets[4:]
        elif concept == "story" and len(assets) >= 2:
            rest = assets  # the chapter card introduces it: a grid of the whole system
        elif concept == "photo" and rest and (first.analysis or {}).get("background") == "transparent" \
                and (rest[0].analysis or {}).get("background") != "transparent":
            b.add("logo", "logo_pair", [first, rest[0]], logo_id=first.id)
            rest = rest[1:]
        elif concept == "bold":
            # Poster-scale identity: each lockup gets its own field.
            for a in assets[:3]:
                if a.effective_kind == "monogram":
                    b.add("logo", "mark_feature", [a], title=b.ctx.title)
                else:
                    b.add("logo", "logo_hero", [a], logo_id=a.id)
            rest = assets[3:]
        else:
            b.add("logo", "logo_hero", [first], logo_id=first.id)
        for chunk in _chunks(rest, 4):
            if len(chunk) == 1:
                b.add("logo", "logo_hero", chunk, logo_id=chunk[0].id)
            else:
                b.add("logo_variations", "logo_tiles", chunk)
        return
    if treatment == "motion":
        for a in assets:
            b.add("motion", "video_stage", [a])
        return
    if treatment == "screen":
        wide = [a for a in assets if a.aspect >= 1.0]
        for a in wide:
            b.add(_type_for([a], "website"), "browser", [a])
        for chunk in _chunks([a for a in assets if a.aspect < 1.0], 3):
            b.add(_type_for(chunk, "mobile"), "phones", chunk)
        return
    if treatment == "pattern":
        module = GROUP_MODULE["pattern"][concept]
        mark = inv.marks[0].id if inv.marks else (inv.logo.id if inv.logo else None)
        if module == "pattern_field":
            for i, a in enumerate(assets):
                if concept == "minimal" and i:
                    b.add("visual_language", "stage", [a])
                else:
                    b.add("visual_language", "pattern_field", [a], logo_id=mark, params={"badge": concept == "bold"})
            return
        _emit_grouped(b, "visual_language", module, assets)
        return
    if treatment in ("sheet", "social", "art"):
        module = GROUP_MODULE[treatment][concept]
        if treatment == "social" and len(assets) > 9:
            module = "feed_grid"
        if treatment == "art" and concept in ("bold", "photo"):
            wide = [a for a in assets if a.effective_kind == "outdoor" and a.aspect >= 1.6]
            for a in wide:
                b.add(_type_for([a], "outdoor"), "fullbleed", [a])
            assets = [a for a in assets if a not in wide]
        default = {"sheet": "visual_language", "social": "social", "art": "campaign"}[treatment]
        _emit_grouped(b, default, module, assets, single="phones" if treatment == "social" and concept != "story" else "stage")
        return
    # Photographs and photographed scenes.
    rest = list(assets)
    if concept == "layered":
        trio = _pick_maskable(rest)
        if trio:
            b.add(_type_for(trio, "gallery"), "masked_trio", trio)
            rest = [a for a in rest if a not in trio]
    if concept == "story" and rest:
        wide = next((a for a in rest if a.aspect >= 1.3), None)
        if wide is not None:
            b.add(_type_for([wide], "gallery"), "letterbox", [wide], params={"index": len(b.sections)})
            rest.remove(wide)
        if len(rest) >= 4:
            b.add(_type_for(rest[:3], "gallery"), "filmstrip", rest[:3])
            rest = rest[3:]
    if rest:
        _imagery_groups(b, rest, FOLDER_PHOTO_PATTERN[concept], "gallery")


def _folder_story(b: "_Builder") -> None:
    """Plan a concept section by section, following the designer's folders."""
    from behance_studio.assets.folders import NON_SECTION_TYPES

    ctx, inv, concept = b.ctx, b.inv, b.concept
    groups = ctx.sections.groups()
    tagline, rest_messages = _tagline(ctx)
    b.messages_used.add(tagline)
    hero = _folder_hero(b, groups)
    cover = {"minimal": "cover_split" if hero is not None and b.rng.random() < 0.5 else "cover_logo", "bold": "cover_logo",
             "photo": "cover_hero" if hero is not None else "cover_logo", "layered": "cover_split" if hero is not None else "cover_logo",
             "story": "cover_hero" if hero is not None else "cover_logo"}[concept]
    _common_opening(b, cover, hero, tagline)
    b.used.clear()  # the cover image also appears in its own section
    _statement(b, {"align": "center"} if concept == "story" else None)
    has_palette = any(p.type == "palette" for p, _ in groups)
    swatches = _swatches(ctx) if ctx.direction.palette.source == "brief" and not has_palette else []
    identity_types = {"logo", "logo_variations", "logo_construction", "palette", "typography", "visual_language"}
    pending_swatches = len(swatches) >= 2
    for index, (placement, ids) in enumerate(groups):
        assets = [inv.by_id[i] for i in ids if i in inv.by_id and "near-duplicate" not in inv.dropped.get(i, "")]
        if not assets:
            continue
        if pending_swatches and placement.type not in identity_types and index > 0:
            b.add("palette", "palette_columns" if concept != "layered" else "palette_circles", [], swatches=swatches)
            pending_swatches = False
        start = len(b.sections)
        if concept == "story":
            from behance_studio.layout.fitting import can_cover

            lead = next((a for a in assets if _treatment(a) == "photo" and can_cover(a, 0.8)), None)
            b.chapter_no += 1
            if lead is not None:
                b.add("custom", "chapter_spread", [lead], title=placement.title, params={"number": b.chapter_no}, chapter=True)
                assets = [a for a in assets if a.id != lead.id]
            else:
                b.add("custom", "chapter", [], title=placement.title, params={"number": b.chapter_no}, chapter=True)
        elif concept == "bold" and index and index % 3 == 0:
            quote = b.message(rest_messages)
            if quote:
                b.add("brand_story", "quote_band", [], body=quote, exact_text=True)
                start = len(b.sections)
        order: list[str] = []
        by_treatment: dict[str, list[AssetRecord]] = {}
        for a in assets:
            t = _treatment(a)
            if t not in by_treatment:
                order.append(t)
            by_treatment.setdefault(t, []).append(a)
        for t in order:
            _emit(b, t, by_treatment[t])
        # Every section of this folder carries its title and identity.
        for sp in b.sections[start:]:
            sp.meta["folder_section"] = placement.key
            if sp.meta.get("chapter"):
                continue
            sp.title = placement.title
            sp.meta["title_source"] = "folder" if placement.source == "folder" else "type"
            if placement.type not in NON_SECTION_TYPES:
                sp.type = placement.type
    if pending_swatches:
        b.add("palette", "palette_columns", [], swatches=swatches)
    _closing(b, tagline if concept in ("bold", "story") else "")


CONCEPT_PLANNERS = {"minimal": _minimal, "bold": _bold, "photo": _photo, "layered": _layered, "story": _story}


# -------------------------------------------------------------------- main
def direct(ctx: PlanningContext, concept: str, seed: int, creativity: float = 0.5) -> PresentationPlan:
    """Plan a complete presentation for one concept (deterministic per seed)."""
    rng = random.Random(f"director:{concept}:{seed}")
    writer = Copywriter(ctx.language)
    inv = build_inventory(ctx)
    if ctx.directives.script_locked:
        plan = plan_from_script(ctx, PlanPreferences(), seed)
        annotate_script_plan(plan, inv, concept)
        plan.notes.append("The project script fixes content and order; the concept sets the visual treatment.")
        return assign_stable_ids(plan)
    builder = _Builder(ctx, inv, concept, rng, writer)
    if ctx.by_folders:
        _folder_story(builder)
    else:
        CONCEPT_PLANNERS[concept](builder)
    sections = builder.sections
    usable_ids = set(inv.by_id)
    used = {aid for s in sections for aid in s.asset_ids} | {s.meta.get("logo_id") for s in sections if s.meta.get("logo_id")}
    unused = [aid for aid in usable_ids if aid not in used]
    notes = [f"Concept: {concept}. {len(sections)} sections."]
    if unused:
        notes.append(f"{len(unused)} asset(s) were not selected for this concept (weaker, near-duplicates or not needed for the story).")
    plan = PresentationPlan(
        sections=sections,
        language=ctx.language,
        project_title=ctx.title,
        category=ctx.directives.category.category,
        category_label=writer.category_label(ctx.directives.category.category),
        hero_asset_id=next((s.asset_ids[0] for s in sections if s.type == "cover" and s.asset_ids), None),
        logo_asset_id=inv.logo.id if inv.logo else None,
        unused_asset_ids=unused,
        notes=notes,
        script_driven=False,
    )
    plan_meta = {"dropped": inv.dropped}
    if sections:
        sections[0].meta["director"] = {"concept": concept, **plan_meta}
    return assign_stable_ids(plan)


def annotate_script_plan(plan: PresentationPlan, inv: Inventory, concept: str) -> None:
    """Choose a module for each script section without touching its content."""
    for sp in plan.sections:
        ids = sp.asset_ids
        has_text = bool((sp.body or "").strip() or (sp.subtitle or "").strip())
        if sp.type == "cover":
            sp.meta["module"] = "cover_hero" if ids and any(inv.by_id.get(i) and inv.by_id[i].effective_kind not in ("logo", "logo_variant", "monogram") for i in ids) else "cover_logo"
            if inv.logo and not sp.meta.get("logo_id"):
                sp.meta["logo_id"] = inv.logo.id
        elif sp.type == "closing":
            sp.meta["module"] = "closing"
            if inv.logo and not sp.meta.get("logo_id"):
                sp.meta["logo_id"] = inv.logo.id
        elif not ids:
            sp.meta["module"] = "statement" if sp.body else "quote_band"
        elif has_text:
            sp.meta["module"] = "split_feature"
        elif sp.type in ("logo", "logo_variations"):
            sp.meta["module"] = "logo_tiles" if len(ids) > 1 else "logo_hero"
        elif sp.type == "social":
            sp.meta["module"] = "feed_grid" if len(ids) > 3 else "phones"
        else:
            sp.meta["module"] = {1: "fullbleed", 2: "duo", 3: "trio"}.get(len(ids), "feed_grid")
        sp.meta["alternatives"] = ALTERNATIVES.get(sp.meta["module"], [sp.meta["module"]])
        sp.meta["params"] = {}
