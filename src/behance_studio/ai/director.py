"""AI Creative Director: a provider proposes the storyboard, the app decides
whether it can be used.

The provider sees the project the way a designer would brief a creative
director: the brief in the user's own words, the brand messages, a contact
sheet of the material (only when sending previews is allowed), measured
facts about every asset, the concept to develop and a catalogue of
compositional modules. It answers with a *storyboard* — which module each
section uses, which assets go where, where chapters and brand messages
pause the sequence, and which assets it leaves out and why.

What the provider can **not** do:

* write presentation text — sections reference brand messages by number,
  chapter names come from a fixed list, everything else is the user's text
  or the offline copy;
* reference anything that does not exist — unknown handles, modules or
  messages are discarded;
* break the format rules — finished artwork never goes into crop-only
  modules, counts are clamped to what each module can show, the cover comes
  first and the closing last.

Every storyboard is validated and repaired here; if too little survives,
the offline Creative Director's plan is used instead. The result is a normal
``PresentationPlan`` (sections carry ``meta.module``), so composition,
validation, rendered QA, editing and export are identical for both
directors.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import random
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from behance_studio.ai.providers import ImagePart
from behance_studio.assets.understanding import asset_nature, strength
from behance_studio.brief.language import detect_language
from behance_studio.core.logging_setup import get_logger
from behance_studio.director import director as D
from behance_studio.director.concepts import CONCEPTS
from behance_studio.director.inventory import Inventory, build_inventory
from behance_studio.planning.copy import Copywriter
from behance_studio.planning.models import PresentationPlan
from behance_studio.planning.planner import PlanningContext, assign_stable_ids
from behance_studio.projects.models import AssetRecord

log = get_logger(__name__)

PROMPT_VERSION = 1
MAX_ASSETS = 36
MAX_SECTIONS = 18
ANSWER_TOKENS = 2600

IMAGES = {"photo", "scene"}
ART = {"poster", "artwork", "social", "outdoor"}
LOGOS = {"logo", "logo_alt", "logo_panel", "mark"}
SHEETS = {"palette_sheet", "type_sheet", "document"}


@dataclass(frozen=True)
class ModuleSpec:
    min: int
    max: int
    groups: frozenset[str]
    text: str


def _spec(lo: int, hi: int, groups: set[str], text: str) -> ModuleSpec:
    return ModuleSpec(lo, hi, frozenset(groups), text)


CATALOGUE: dict[str, ModuleSpec] = {
    "statement": _spec(0, 0, set(), "introduction: the brief's own description with client, category and deliverables (use once, early)"),
    "quote_band": _spec(0, 0, set(), "a pause: one brand message set large (needs \"message\")"),
    "chapter": _spec(0, 0, set(), "a numbered chapter title card (needs \"chapter\")"),
    "chapter_spread": _spec(1, 1, IMAGES | {"poster", "logo"}, "chapter title beside one tall image (needs \"chapter\")"),
    "logo_hero": _spec(1, 1, {"logo", "logo_alt"}, "one logo, large and alone"),
    "logo_pair": _spec(2, 2, {"logo", "logo_panel"}, "the logo on a plain ground next to the logo on its own artwork"),
    "logo_tiles": _spec(2, 4, {"logo_alt", "logo_panel", "mark"}, "logo variants and marks as a grid of tiles"),
    "logo_cards": _spec(2, 4, LOGOS, "the logo system on overlapping cards (first asset: the primary logo)"),
    "mark_feature": _spec(1, 1, {"mark"}, "the symbol at poster scale"),
    "palette_columns": _spec(0, 0, set(), "brand colours as tall columns"),
    "palette_circles": _spec(0, 0, set(), "brand colours as overlapping circles"),
    "type_specimen": _spec(0, 0, set(), "typeface specimen (only when the brand fonts are known)"),
    "doc_stage": _spec(1, 1, SHEETS, "a brand sheet (colour or type document) on a surface"),
    "pattern_field": _spec(1, 1, {"pattern"}, "the brand pattern as a full field"),
    "fullbleed": _spec(1, 1, IMAGES | {"outdoor"}, "one landscape image edge to edge"),
    "letterbox": _spec(1, 1, IMAGES, "a cinematic wide frame (wide photographs only)"),
    "stage": _spec(1, 1, IMAGES | ART | {"screen", "pattern"} | SHEETS, "one piece on a surface with generous space"),
    "duo": _spec(2, 2, IMAGES | ART, "two images side by side"),
    "trio": _spec(3, 3, IMAGES | ART, "three images in a row"),
    "masked_trio": _spec(3, 3, IMAGES, "three photographs in circle, arch and landscape masks"),
    "filmstrip": _spec(3, 3, IMAGES, "a sequence of three cinematic frames"),
    "stage_pair": _spec(2, 2, ART | {"scene"}, "two finished pieces staged with shadows"),
    "poster_wall": _spec(2, 3, {"poster", "artwork"}, "posters presented together"),
    "float_stack": _spec(2, 4, {"poster", "social", "artwork"}, "floating, slightly rotated cards"),
    "phones": _spec(1, 3, {"social", "screen"}, "content inside phone frames"),
    "feed_grid": _spec(3, 9, {"social"}, "a social media feed grid"),
    "browser": _spec(1, 1, {"screen"}, "a screen inside a browser window"),
    "video_stage": _spec(1, 1, {"motion"}, "a video on a surface"),
}
COVERS: dict[str, ModuleSpec] = {
    "cover_logo": _spec(0, 0, set(), "the logo with the project title on a field"),
    "cover_hero": _spec(1, 1, IMAGES, "one landscape photograph edge to edge with the title over it"),
    "cover_split": _spec(1, 1, IMAGES | ART, "title on one half, an image on the other"),
    "collage": _spec(2, 2, IMAGES | ART, "a photograph overlapped by one finished artwork card, with the title"),
}
CHAPTER_KEYS = list(D.CHAPTERS)
MODULE_TYPE = {
    "logo_hero": "logo", "logo_pair": "logo", "logo_cards": "logo", "mark_feature": "logo", "logo_tiles": "logo_variations",
    "palette_columns": "palette", "palette_circles": "palette", "type_specimen": "typography", "pattern_field": "visual_language",
    "phones": "social", "feed_grid": "social", "browser": "website", "video_stage": "motion", "quote_band": "brand_story",
    "poster_wall": "campaign", "float_stack": "campaign", "statement": "intro",
}
CONCEPT_PARAMS = {("story", "statement"): {"align": "center"}, ("photo", "palette_columns"): {"height": 380},
                  ("minimal", "pattern_field"): {"badge": False}}

SYSTEM = (
    "You are the creative director of a brand design studio, planning a Behance case study for a designer's project. "
    "You decide the art-directed sequence: which compositional module each section uses, which assets it shows, where "
    "chapters and brand messages pause the story, and which material is left out. Think like an editor: lead with the "
    "strongest work, vary scale and rhythm, avoid repeating the same module back to back, and leave out weak, "
    "near-duplicate or off-concept material. You never write text for the presentation and never invent facts — text "
    "comes only from the designer's brief, referenced by number. Use only the handles, modules, chapters and message "
    "numbers you are given. Answer with JSON only."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "idea": {"type": "string"},
        "cover": {
            "type": "object",
            "properties": {
                "module": {"type": "string", "enum": list(COVERS)},
                "assets": {"type": "array", "items": {"type": "string"}},
                "message": {"type": "integer"},
            },
            "required": ["module", "assets", "message"],
            "additionalProperties": False,
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "module": {"type": "string", "enum": list(CATALOGUE)},
                    "assets": {"type": "array", "items": {"type": "string"}},
                    "chapter": {"type": "string", "enum": ["none", *CHAPTER_KEYS]},
                    "message": {"type": "integer"},
                    "why": {"type": "string"},
                },
                "required": ["module", "assets", "chapter", "message", "why"],
                "additionalProperties": False,
            },
        },
        "closing_message": {"type": "integer"},
        "left_out": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"asset": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["asset", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["idea", "cover", "sections", "closing_message", "left_out"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------- context
def inventory_groups(inv: Inventory) -> list[tuple[str, AssetRecord]]:
    """(group, asset) for everything the director may use, strongest first per group."""
    out: list[tuple[str, AssetRecord]] = []
    if inv.logo:
        out.append(("logo", inv.logo))
    out += [("logo_alt", a) for a in inv.logo_alts] + [("logo_panel", a) for a in inv.logo_panels] + [("mark", a) for a in inv.marks]
    out += [("pattern", a) for a in inv.patterns]
    for kind, items in inv.documents.items():
        group = {"palette": "palette_sheet", "typography": "type_sheet"}.get(kind, "document")
        out += [(group, a) for a in items]
    for group, items in (("photo", inv.photos), ("scene", inv.scenes), ("poster", inv.posters), ("outdoor", inv.outdoor),
                         ("social", inv.social), ("artwork", inv.artworks), ("screen", inv.screens), ("motion", inv.motion)):
        out += [(group, a) for a in items]
    if len(out) > MAX_ASSETS:  # keep identity, then the strongest of the rest
        head = [x for x in out if x[0] in LOGOS | {"pattern"} | SHEETS][: MAX_ASSETS // 3]
        rest = sorted([x for x in out if x not in head], key=lambda x: -strength(x[1]))[: MAX_ASSETS - len(head)]
        keep = {id(x) for x in head + rest}
        out = [x for x in out if id(x) in keep]
    return out


def brand_messages(ctx: PlanningContext) -> list[str]:
    return [m for m in ctx.directives.brief.messages if detect_language(m, ctx.language) == ctx.language]


def _asset_line(handle: str, group: str, a: AssetRecord) -> str:
    info = a.analysis or {}
    bits = [handle, group, a.effective_kind, asset_nature(a), f"aspect {a.aspect:.2f}", f"strength {strength(a):.2f}"]
    if info.get("background") == "transparent":
        bits.append("transparent")
    if info.get("text_fraction", 0) >= 0.03:
        bits.append("contains text")
    if a.media_type == "video":
        bits.append("video")
    desc = (a.description or (info.get("ai") or {}).get("description") or "").strip()
    name = a.filename.rsplit(".", 1)[0][:48]
    bits.append(f"file “{name}”")
    if desc:
        bits.append(f"shows: {desc[:80]}")
    return " · ".join(bits)


def shared_context(ctx: PlanningContext, groups: list[tuple[str, AssetRecord]], handles: dict[str, str],
                   messages: list[str], sheet: bool, references: int) -> str:
    """Context identical for every concept of a run (cached by the provider)."""
    brief = ctx.directives.brief
    d = ctx.direction
    lines = [
        "PROJECT",
        f"Title: {ctx.title}",
        f"Category: {ctx.directives.category.category}",
        f"Presentation language: {ctx.language}",
        "Brief (the designer's own words; may be empty):",
        '"""', (brief.raw or "")[:5000], '"""',
        "Brand messages (the only sentences that may appear; reference them by number, -1 for none):",
    ]
    lines += [f"{i}: {m}" for i, m in enumerate(messages)] or ["(none)"]
    lines += [
        f"Brand colours available for colour modules: {len(d.palette.presentable)} ({d.palette.source})",
        f"Brand fonts known: {'yes' if d.brand_fonts_known else 'no'}",
        "",
        "ASSETS (handle · group · kind · nature · aspect w/h · measured strength 0–1 · notes)",
    ]
    lines += [_asset_line(handles[a.id], g, a) for g, a in groups]
    if sheet:
        lines.append("The first image is a contact sheet: every asset is labelled with its handle.")
    if references:
        lines.append(f"The last image shows {references} reference screenshot(s) the designer admires. Use them only as "
                     "a guide to pacing and mood; never place them, and do not copy their content.")
    lines += ["", "COVER MODULES"]
    lines += [f"{n}: {s.min}–{s.max} asset(s) from {sorted(s.groups) or 'none'} — {s.text}" for n, s in COVERS.items()]
    lines += ["", "SECTION MODULES"]
    lines += [f"{n}: {s.min}–{s.max} asset(s) from {sorted(s.groups) or 'none'} — {s.text}" for n, s in CATALOGUE.items()]
    lines += [
        "", f"CHAPTERS (for chapter / chapter_spread): {', '.join(CHAPTER_KEYS)}",
        "",
        "RULES",
        "- Each asset at most once (the primary logo may repeat).",
        "- Finished artwork (posters, social posts, artwork, documents, screens) must never be cropped: show it with "
        "stage, stage_pair, poster_wall, float_stack, phones, feed_grid, duo or trio — not fullbleed, letterbox, "
        "masked_trio or filmstrip.",
        "- fullbleed and cover_hero need landscape images; letterbox needs wide ones; masked_trio needs photographs that "
        "can be cropped to a circle, an arch and a landscape.",
        "- Use statement at most once. A closing section is added automatically.",
        "- About 6–14 sections after the cover; fewer for small projects. Quality over quantity.",
        "- In left_out, name assets you deliberately leave out with a short reason.",
    ]
    return "\n".join(lines)


def concept_prompt(concept: str, seed: int, others: list[str], baseline: PresentationPlan, handles: dict[str, str]) -> str:
    info = CONCEPTS[concept]
    lines = [
        f"CONCEPT TO DEVELOP: {info.name} — {info.tagline}.",
        info.description,
        f"Variation seed: {seed} (a different seed asks for a different but equally strong storyboard).",
    ]
    if others:
        names = ", ".join(CONCEPTS[o].name for o in others if o in CONCEPTS and o != concept)
        lines.append(f"The other proposals develop: {names}. Make this one clearly different in sequence, scale and modules.")
    lines.append("Baseline storyboard from the offline director (improve it: reorder, change modules, choose stronger "
                 "assets, add or remove sections):")
    for i, sp in enumerate(baseline.sections):
        ids = " ".join(handles.get(a, "?") for a in sp.asset_ids if a in handles)
        lines.append(f"{i}. {sp.meta.get('module', '?')} [{ids}]")
    lines.append('Answer with JSON: {"idea": "<one sentence: the art-direction idea>", "cover": {"module", "assets", '
                 '"message"}, "sections": [{"module", "assets", "chapter", "message", "why"}], "closing_message": <n or -1>, '
                 '"left_out": [{"asset", "reason"}]}')
    return "\n".join(lines)


def contact_sheet(project, items: list[tuple[str, AssetRecord]], cell: int = 168, cols: int = 6) -> ImagePart | None:
    """A labelled grid of small previews (one image instead of dozens)."""
    from behance_studio.assets.derivatives import ensure_thumbnail

    if not items:
        return None
    cols = min(cols, len(items))
    rows = math.ceil(len(items) / cols)
    label_h = 24
    sheet = Image.new("RGB", (cols * cell, rows * (cell + label_h)), (232, 232, 232))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=16)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    for i, (handle, asset) in enumerate(items):
        x0, y0 = (i % cols) * cell, (i // cols) * (cell + label_h)
        try:
            with Image.open(ensure_thumbnail(project, asset)) as im:
                im = im.convert("RGBA")
                im.thumbnail((cell - 12, cell - 12), Image.Resampling.LANCZOS)
                ground = Image.new("RGB", im.size, (255, 255, 255))
                ground.paste(im, mask=im.split()[3])
            sheet.paste(ground, (x0 + (cell - ground.width) // 2, y0 + 6 + (cell - 12 - ground.height) // 2))
        except Exception as exc:  # noqa: BLE001 - one unreadable preview must not stop the sheet
            log.debug("Contact sheet skipped %s: %s", asset.filename, exc)
        draw.text((x0 + 6, y0 + cell - 2), handle, fill=(20, 20, 20), font=font)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=80)  # re-encoded: no file metadata leaves the machine
    return ImagePart(buf.getvalue(), "image/jpeg", sheet.width, sheet.height)


# ------------------------------------------------------------- validation
def _int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def storyboard_to_plan(ctx: PlanningContext, inv: Inventory, groups: list[tuple[str, AssetRecord]], handles: dict[str, str],
                       concept: str, seed: int, data: dict[str, Any]) -> tuple[PresentationPlan | None, list[str]]:
    """Validate and repair an AI storyboard; return a plan or None."""
    from behance_studio.layout.fitting import can_cover

    report: list[str] = []
    by_handle = {h: aid for aid, h in handles.items()}
    group_of = {a.id: g for g, a in groups}
    assets = {a.id: a for _, a in groups}
    messages = brand_messages(ctx)
    b = D._Builder(ctx, inv, concept, random.Random(f"ai-director:{concept}:{seed}"), Copywriter(ctx.language))
    logo_id = inv.logo.id if inv.logo else None

    def message(idx: Any) -> str:
        i = _int(idx)
        if 0 <= i < len(messages) and messages[i] not in b.messages_used:
            b.messages_used.add(messages[i])
            return messages[i]
        return ""

    def resolve(raw: Any, spec: ModuleSpec, module: str, rejected: list[AssetRecord] | None = None) -> list[AssetRecord]:
        out: list[AssetRecord] = []
        for h in raw if isinstance(raw, list) else []:
            aid = by_handle.get(str(h).strip())
            if aid is None:
                report.append(f"{module}: unknown asset “{str(h)[:12]}” ignored")
                continue
            if (aid in b.used and aid != logo_id) or any(a.id == aid for a in out):
                report.append(f"{module}: {handles[aid]} already used")
                continue
            if group_of[aid] not in spec.groups:
                report.append(f"{module}: {handles[aid]} ({group_of[aid]}) does not suit this module")
                if rejected is not None and all(r.id != aid for r in rejected):
                    rejected.append(assets[aid])
                continue
            out.append(assets[aid])
        return out[: spec.max]

    # ---- cover
    cover = data.get("cover") if isinstance(data.get("cover"), dict) else {}
    cmod = str(cover.get("module", "cover_logo"))
    cspec = COVERS.get(cmod, COVERS["cover_logo"])
    cassets = resolve(cover.get("assets"), cspec, cmod) if cmod in COVERS else []
    tagline = message(cover.get("message")) or (D._tagline(ctx)[0] if _int(cover.get("message")) != -1 else "")
    if tagline:
        b.messages_used.add(tagline)
    if cmod == "collage":
        photo = next((a for a in cassets if group_of[a.id] in IMAGES and can_cover(a, 1.2)), None)
        card = next((a for a in cassets if a is not photo and group_of[a.id] in ART), None)
        if photo is not None and card is not None:
            b.add("cover", "collage", [photo, card], title=ctx.title, subtitle=tagline, exact_text=bool(tagline),
                  eyebrow=b.writer.category_label(ctx.directives.category.category), logo_id=logo_id)
        else:
            report.append("collage cover needs a photograph and an artwork card: replaced")
            cmod, cassets = ("cover_split", [photo or card]) if (photo or card) else ("cover_logo", [])
    if cmod == "cover_hero" and not (cassets and cassets[0].aspect >= 1.2 and can_cover(cassets[0], 1.6)):
        report.append("cover_hero needs a landscape photograph: replaced")
        cmod = "cover_split" if cassets else "cover_logo"
    if cmod == "cover_split" and not cassets:
        cmod = "cover_logo"
    if cmod != "collage":
        D._common_opening(b, cmod, cassets[0] if cassets else None, tagline)

    # ---- sections
    raw_sections = data.get("sections") if isinstance(data.get("sections"), list) else []
    statement_done = False
    letterbox_no = 0
    for item in raw_sections[:MAX_SECTIONS]:
        if not isinstance(item, dict):
            continue
        module = str(item.get("module", ""))
        spec = CATALOGUE.get(module)
        if spec is None:
            report.append(f"unknown module “{module[:20]}” ignored")
            continue
        why = str(item.get("why", "")).strip()[:160]
        rejected: list[AssetRecord] = []
        chosen = resolve(item.get("assets"), spec, module, rejected)
        if not chosen and rejected and spec.min > 0:
            # Keep the director's intent (show these here) in a format that suits them,
            # e.g. a poster asked for edge to edge is staged instead of cropped.
            n = min(3, len(rejected))
            staged = {1: "stage", 2: "stage_pair" if all(group_of[a.id] in ART | {"scene"} for a in rejected[:2]) else "duo", 3: "trio"}[n]
            fits = [a for a in rejected if group_of[a.id] in CATALOGUE[staged].groups][: CATALOGUE[staged].max]
            if len(fits) >= CATALOGUE[staged].min:
                report.append(f"{module}: shown as {staged} instead")
                module, spec, chosen = staged, CATALOGUE[staged], fits
        chapter = str(item.get("chapter", "none"))
        params = dict(CONCEPT_PARAMS.get((concept, module), {}))
        extra: dict[str, Any] = {}

        # Text-only modules.
        if module == "statement":
            if statement_done:
                continue
            statement_done = True
            before = len(b.sections)
            D._statement(b, params)
            if len(b.sections) > before and why:
                b.sections[-1].meta["ai_note"] = why
            continue
        if module == "quote_band":
            text = message(item.get("message"))
            if not text:
                report.append("quote_band without an unused brand message: dropped")
                continue
            b.add("brand_story", "quote_band", [], body=text, exact_text=True, ai_note=why)
            continue
        if module in ("palette_columns", "palette_circles"):
            sw = D._swatches(ctx)
            if len(sw) >= 2:
                b.add("palette", module, [], swatches=sw, params=params, ai_note=why)
            elif inv.documents.get("palette") and inv.documents["palette"][0].id not in b.used:
                b.add("palette", "doc_stage", inv.documents["palette"][:1], ai_note=why)
            else:
                report.append(f"{module}: no brand colours to show: dropped")
            continue
        if module == "type_specimen":
            if ctx.direction.brand_fonts_known:
                ts = ctx.direction.type_system
                b.add("typography", "type_specimen", [], fonts={"display": ts.display, "text": ts.text}, ai_note=why)
            else:
                report.append("type_specimen: brand fonts unknown: dropped")
            continue
        if module in ("chapter", "chapter_spread"):
            if chapter not in D.CHAPTERS:
                report.append(f"{module} without a chapter name: dropped")
                continue
            lead = chosen[0] if chosen else None
            if module == "chapter_spread" and lead is not None and not (group_of[lead.id] == "logo" or can_cover(lead, 0.8)):
                report.append(f"chapter_spread: {handles[lead.id]} cannot fill a tall half: plain chapter")
                lead = None
            b.chapter(chapter, lead if module == "chapter_spread" else None)
            if why:
                b.sections[-1].meta["ai_note"] = why
            continue

        # Repairs by count and format.
        if len(chosen) < spec.min:
            n = len(chosen)
            if n == 0:
                report.append(f"{module}: no usable assets: dropped")
                continue
            fallback = {1: "stage", 2: "duo", 3: "trio"}.get(n, module)
            if n == 1 and group_of[chosen[0].id] in IMAGES | {"outdoor"} and chosen[0].aspect >= 1.25:
                fallback = "fullbleed"
            report.append(f"{module}: {n} asset(s) is too few: {fallback}")
            module, spec = fallback, CATALOGUE[fallback]
            chosen = [a for a in chosen if group_of[a.id] in spec.groups]
            if len(chosen) < spec.min:
                continue
        if module == "fullbleed" and chosen[0].aspect < 1.25 and group_of[chosen[0].id] != "outdoor":
            module = "stage" if concept != "photo" else "fullbleed"
        if module == "letterbox" and chosen[0].aspect < 1.3:
            module = "fullbleed" if chosen[0].aspect >= 1.25 else "stage"
        if module == "letterbox":
            letterbox_no += 1
            params.setdefault("index", letterbox_no)
        if module == "masked_trio":
            combo = D._pick_maskable(chosen)
            if combo is None:
                report.append("masked_trio: these photographs cannot take the masks: trio")
                module = "trio"
            else:
                chosen = combo
        if module in ("logo_hero", "logo_pair", "logo_cards", "mark_feature"):
            extra["logo_id"] = logo_id
        if module == "logo_cards" and logo_id and chosen and chosen[0].id != logo_id and inv.logo:
            chosen = [inv.logo] + [a for a in chosen if a.id != logo_id][:3]
        if module == "pattern_field":
            extra["logo_id"] = inv.marks[0].id if inv.marks else logo_id
        if module in ("logo_cards", "float_stack"):
            extra["pattern_id"] = inv.patterns[0].id if inv.patterns else None
        if module == "mark_feature":
            extra["title"] = ctx.title
        type_ = MODULE_TYPE.get(module) or D._type_for(chosen, "photography" if all(group_of[a.id] == "photo" for a in chosen) else "applications")
        title = extra.pop("title", "")
        b.add(type_, module, chosen, title=title, params=params, ai_note=why, **extra)

    body = [s for s in b.sections if s.type != "cover"]
    minimum = 2 if inv.count() < 6 else 3
    if len(body) < minimum:
        report.append(f"only {len(body)} usable section(s)")
        return None, report
    D._closing(b, message(data.get("closing_message")))

    sections = b.sections
    used = {aid for s in sections for aid in s.asset_ids}
    unused = [aid for aid in inv.by_id if aid not in used]
    idea = str(data.get("idea", "")).strip()[:220]
    notes = [f"Concept: {concept}. {len(sections)} sections, art-directed with AI."]
    if idea:
        notes.append(f"AI art-direction idea: {idea}")
    for entry in (data.get("left_out") or [])[:6]:
        if isinstance(entry, dict) and str(entry.get("asset", "")) in by_handle:
            a = assets[by_handle[str(entry["asset"])]]
            notes.append(f"Left out by the AI director: {a.filename} — {str(entry.get('reason', ''))[:100]}")
    if report:
        notes.append(f"{len(report)} storyboard item(s) were corrected or dropped by validation.")
    writer = Copywriter(ctx.language)
    plan = PresentationPlan(
        sections=sections,
        language=ctx.language,
        project_title=ctx.title,
        category=ctx.directives.category.category,
        category_label=writer.category_label(ctx.directives.category.category),
        hero_asset_id=next((s.asset_ids[0] for s in sections if s.type == "cover" and s.asset_ids), None),
        logo_asset_id=logo_id,
        unused_asset_ids=unused,
        notes=notes,
        script_driven=False,
    )
    sections[0].meta["director"] = {"concept": concept, "source": "ai", "idea": idea, "corrections": report[:20], "dropped": inv.dropped}
    return assign_stable_ids(plan), report


# ------------------------------------------------------------------ request
@dataclass
class DirectorRequest:
    system: str
    shared: str
    prompt: str
    images: list[ImagePart]
    handles: dict[str, str]
    groups: list[tuple[str, AssetRecord]]
    inventory: Inventory

    def key(self, provider_kind: str, model: str) -> str:
        digest = hashlib.sha256()
        for part in (str(PROMPT_VERSION), provider_kind, model, self.system, self.shared, self.prompt):
            digest.update(part.encode("utf-8"))
        for image in self.images:
            digest.update(hashlib.sha256(image.data).digest())
        return digest.hexdigest()[:32]


def build_request(project, ctx: PlanningContext, concept: str, seed: int, creativity: float, others: list[str],
                  with_images: bool, references: list[AssetRecord]) -> DirectorRequest:
    inv = build_inventory(ctx)
    groups = inventory_groups(inv)
    handles = {a.id: f"A{i + 1}" for i, (_, a) in enumerate(groups)}
    images: list[ImagePart] = []
    if with_images:
        sheet = contact_sheet(project, [(handles[a.id], a) for _, a in groups])
        if sheet is not None:
            images.append(sheet)
        if references:
            ref = contact_sheet(project, [(f"R{i + 1}", a) for i, a in enumerate(references[:6])], cell=320, cols=3)
            if ref is not None:
                images.append(ref)
    refs = len(references[:6]) if with_images and references else 0
    shared = shared_context(ctx, groups, handles, brand_messages(ctx), bool(images), refs)
    baseline = D.direct(ctx, concept, seed, creativity)
    prompt = concept_prompt(concept, seed, others, baseline, handles)
    return DirectorRequest(SYSTEM, shared, prompt, images, handles, groups, inv)


def parse_storyboard(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, str):
        from behance_studio.ai.providers import extract_json

        raw = extract_json(raw)
    if not isinstance(raw, dict) or not isinstance(raw.get("sections"), list):
        return None
    return raw


def describe(data: dict[str, Any]) -> str:
    """Compact text form of a storyboard (logs and tests)."""
    return json.dumps({"cover": data.get("cover"), "sections": [s.get("module") for s in data.get("sections", []) if isinstance(s, dict)]})
