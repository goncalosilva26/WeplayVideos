"""Rhythm: no proposal repeats the same composition back to back.

Planners work section by section, so a folder with many images of one kind
can produce a long run of identical modules (stage, stage, stage…), which
reads as a catalogue rather than an art-directed case study. After
planning — for the offline and the AI director alike — this pass:

1. combines two consecutive sections of the same module and section when
   the module takes both sets of images (e.g. two phone sections);
2. pairs up runs of single-image modules so the rhythm alternates between
   one large piece and a pair (stage → stage pair, full-bleed → duo,
   logo → logo tiles);
3. gives any remaining back-to-back repeat a compatible alternative module.

Images never change section: only sections of the same folder section (or,
without folders, the same section type) are combined, and script or locked
sections are never touched.
"""

from __future__ import annotations

from behance_studio.planning.models import PresentationPlan, SectionPlan

ALIGNABLE = {"stage", "doc_stage", "video_stage"}
TEXT_ONLY = {"statement", "chapter", "quote_band", "palette_columns", "palette_circles", "type_specimen"}
# single-image module → the pair module that suits the two images (by group)
PAIRS = {
    "stage": [("stage_pair", {"poster", "artwork", "social", "outdoor", "scene"}), ("duo", {"photo", "scene", "poster", "artwork", "social", "outdoor"}),
              ("poster_wall", {"poster", "artwork"}), ("float_stack", {"poster", "social", "artwork"})],
    "fullbleed": [("duo", {"photo", "scene", "outdoor"})],
    "letterbox": [("duo", {"photo", "scene"})],
    "logo_hero": [("logo_tiles", {"logo_alt", "logo_panel", "mark"}), ("logo_cards", {"logo", "logo_alt", "logo_panel", "mark"})],
    "mark_feature": [("logo_tiles", {"logo_alt", "logo_panel", "mark"})],
}


# Extra compositions the rhythm pass may switch to (on top of the director's ALTERNATIVES).
RHYTHM_ALTERNATIVES = {
    "phones": ["float_stack", "feed_grid", "stage_pair", "stage"],
    "float_stack": ["stage_pair", "poster_wall", "phones", "feed_grid"],
    "duo": ["stage_pair", "trio"],
    "stage_pair": ["float_stack", "duo"],
    "poster_wall": ["float_stack", "stage_pair"],
    "logo_hero": ["logo_tiles", "logo_cards"],
}
# A different variant of the same composition when no other composition fits.
VARIANTS = {"duo": {"seamless": True}}
# Each concept's own taste when a composition must change, so that the five proposals do not all drift
# towards the same replacements (e.g. every concept turning its stages into stage pairs).
FAMILY_TASTE = {
    "minimal": ["stage_pair", "duo", "trio"],
    "bold": ["poster_wall", "fullbleed", "float_stack", "feed_grid"],
    "photo": ["fullbleed", "letterbox", "duo", "trio"],
    "layered": ["float_stack", "masked_trio", "stage_pair"],
    "story": ["letterbox", "fullbleed", "float_stack", "stage_pair"],
}


def _preferred(options: list[str], family: str, used: dict[str, int]) -> list[str]:
    """Options in the concept's order of taste, then those the other proposals use least."""
    taste = FAMILY_TASTE.get(family, [])
    unique = list(dict.fromkeys(options))
    return sorted(unique, key=lambda m: (taste.index(m) if m in taste else len(taste), used.get(m, 0), unique.index(m)))


def _spec(module: str):
    from behance_studio.ai.director import CATALOGUE

    return CATALOGUE.get(module)


# Wide-only compositions: minimum width/height ratio of the image.
MIN_ASPECT = {"fullbleed": 1.25, "letterbox": 1.3}


def _fits(module: str, groups: list[str], aspects: list[float] | None = None) -> bool:
    spec = _spec(module)
    if spec is None or not spec.min <= len(groups) <= spec.max or not all(g in spec.groups for g in groups):
        return False
    return module not in MIN_ASPECT or (aspects is not None and all(a >= MIN_ASPECT[module] for a in aspects))


def _key(sp: SectionPlan) -> str:
    return sp.meta.get("folder_section") or f"type:{sp.type}"


def _free(sp: SectionPlan) -> bool:
    return not sp.locked and sp.source != "script" and not sp.meta.get("chapter") and bool(sp.asset_ids)


def _module(sp: SectionPlan) -> str:
    return sp.meta.get("module", "")


def _set_module(sp: SectionPlan, module: str) -> None:
    from behance_studio.director.director import ALTERNATIVES

    sp.meta["module"] = module
    sp.meta["params"] = {}
    sp.meta["alternatives"] = ALTERNATIVES.get(module, [module])
    sp.meta["rhythm"] = True


def _merge(a: SectionPlan, b: SectionPlan, module: str) -> None:
    a.asset_ids = a.asset_ids + [x for x in b.asset_ids if x not in a.asset_ids]
    a.captions = {**(b.captions or {}), **(a.captions or {})}
    _set_module(a, module)


def vary_rhythm(plan: PresentationPlan, group_of: dict[str, str], family: str = "", used: dict[str, int] | None = None,
                aspect_of: dict[str, float] | None = None) -> int:
    """Apply the rules above in place; returns the number of changes.

    ``family`` is the concept being planned and ``used`` counts the compositions of the proposals
    already planned in this generation: replacements follow the concept's taste and otherwise
    prefer what the other proposals use least.
    """
    if not any(_module(s) for s in plan.sections):
        return 0  # classic layouts choose their own patterns
    used = used or {}
    changes = 0
    groups = lambda sp: [group_of.get(a, "artwork") for a in sp.asset_ids]  # noqa: E731
    aspects = lambda sp: [aspect_of[a] for a in sp.asset_ids if a in aspect_of] if aspect_of else None  # noqa: E731
    taste = FAMILY_TASTE.get(family, [])

    from behance_studio.director.director import ALTERNATIVES

    # 1 + 2: combine / pair consecutive identical modules of the same section
    out: list[SectionPlan] = []
    run = 0  # length of the current run of identical single-image modules
    for sp in plan.sections:
        prev = out[-1] if out else None
        same = (prev is not None and _free(prev) and _free(sp) and _module(prev) == _module(sp)
                and _module(sp) not in TEXT_ONLY and _key(prev) == _key(sp))
        if same:
            module = _module(sp)
            combined = groups(prev) + groups(sp)
            if not prev.meta.get("rhythm") and _fits(module, combined) and len(prev.asset_ids) + len(sp.asset_ids) > 1 and (_spec(module).max > 1):
                _merge(prev, sp, module)
                changes += 1
                continue
            run += 1
            # the concept's own single-image composition for every second piece (Bold: stage / full-bleed…)
            solo = next((m for m in ALTERNATIVES.get(module, []) + RHYTHM_ALTERNATIVES.get(module, [])
                         if m in taste and m != module and _spec(m) is not None and _spec(m).max == 1 and _fits(m, groups(sp), aspects(sp))), None)
            if run % 2 == 1 and solo is not None:
                _set_module(sp, solo)
                changes += 1
                run = 0
                out.append(sp)
                continue
            if run % 2 == 1 and len(prev.asset_ids) == 1 and len(sp.asset_ids) == 1:
                fitting = [m for m, ok in PAIRS.get(module, []) if all(g in ok for g in combined) and _fits(m, combined)]
                pair = next(iter(_preferred(fitting, family, used)), None)
                if pair is not None and not prev.meta.get("rhythm"):
                    _merge(prev, sp, pair)
                    changes += 1
                    run = 0
                    continue
        else:
            run = 0
        out.append(sp)
    plan.sections = out

    # 3: alternatives for remaining back-to-back repeats
    side = "left"
    for i in range(1, len(plan.sections)):
        prev, sp = plan.sections[i - 1], plan.sections[i]
        module = _module(sp)
        if not module or module in TEXT_ONLY or module != _module(prev) or not _free(sp):
            continue
        nxt = _module(plan.sections[i + 1]) if i + 1 < len(plan.sections) else ""
        options = _preferred(ALTERNATIVES.get(module, []) + RHYTHM_ALTERNATIVES.get(module, []), family, used)
        alt = next((m for m in options if m not in (module, nxt) and _fits(m, groups(sp), aspects(sp))), None)
        if alt is not None:
            _set_module(sp, alt)
            changes += 1
        elif module in ALIGNABLE and (prev.meta.get("params") or {}).get("align", "center") == (sp.meta.get("params") or {}).get("align", "center"):
            # no other composition suits these images: vary the placement instead
            sp.meta["params"] = {**(sp.meta.get("params") or {}), "align": side}
            sp.meta["rhythm"] = True
            side = "right" if side == "left" else "left"
            changes += 1
        elif module in VARIANTS and not (prev.meta.get("params") or {}).get("rhythm_variant"):
            sp.meta["params"] = {**(sp.meta.get("params") or {}), **VARIANTS[module], "rhythm_variant": True}
            sp.meta["rhythm"] = True
            changes += 1
    return changes


def asset_groups(ctx) -> dict[str, str]:
    """The director's material groups (photo, scene, poster, logo_alt…) per asset."""
    from behance_studio.ai.director import inventory_groups
    from behance_studio.assets.understanding import asset_nature
    from behance_studio.director.inventory import build_inventory

    out = {a.id: g for g, a in inventory_groups(build_inventory(ctx))}
    fallback = {"photo": "photo", "motion": "motion", "screen": "screen", "document": "document", "element": "mark"}
    for a in ctx.assets:
        if a.id not in out:
            out[a.id] = fallback.get(asset_nature(a), "artwork")
    return out
