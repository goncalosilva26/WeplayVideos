"""Keep every image in a section that matches what it is.

Sections are planned from each asset's type, but a plan can still end up
with an image in the wrong place: a storyboard from an AI director, a type
corrected by AI or by the user after planning, or a generic composition
choice. :func:`enforce_section_fit` runs after planning and before layout:

* an asset whose type does not belong in its section (a social post in
  "Packaging", a photograph in "Logo") is moved to a section of its own kind
  — an existing one when it has room, otherwise a new one placed right
  after;
* a section whose images *all* belong elsewhere is re-labelled instead;
* script sections and locked sections are never changed — the script is the
  user's decision — they are only reported (and the validator warns).

Assets are only ever moved, never swapped for other images or dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from behance_studio.planning.models import PresentationPlan, SectionPlan
from behance_studio.planning.sections import section_type

# Section type -> asset kinds that belong there (beyond the type's own kinds).
EXTRA_KINDS: dict[str, set[str]] = {
    "logo": {"logo", "logo_variant", "monogram"},
    "logo_variations": {"logo", "logo_variant", "monogram"},
    "logo_construction": {"logo", "logo_variant", "monogram"},
    "visual_language": {"monogram"},
    "packaging": {"product", "mockup"},
    "product": {"packaging", "photo"},
    "campaign": {"illustration", "editorial"},
    "posters": {"illustration"},
    "outdoor": {"poster"},
    "website": {"mobile", "ui"},
    "mobile": {"ui", "website"},
    "photography": {"before_after"},
    "illustration": {"poster"},
    "mockups": {"packaging", "stationery", "product"},
    "video": {"motion"},
}
# Section types that may show any material (no check).
GENERIC = {"cover", "closing", "custom", "applications", "gallery", "final", "overview", "concept",
           "creative_direction", "brand_story", "intro"}
# Where each asset type belongs when it has to move.
HOME = {
    "logo": "logo", "logo_variant": "logo_variations", "monogram": "logo_variations",
    "palette": "palette", "typography": "typography", "pattern": "visual_language", "illustration": "illustration",
    "packaging": "packaging", "product": "product", "poster": "campaign", "outdoor": "outdoor", "social": "social",
    "stationery": "applications", "mockup": "applications", "editorial": "editorial",
    "website": "website", "mobile": "mobile", "ui": "ui_screens",
    "photo": "photography", "lifestyle": "photography", "portrait": "photography", "before_after": "before_after",
    "video": "motion", "motion": "motion", "document": "applications", "other": "applications",
}


def allowed_kinds(type_id: str) -> set[str] | None:
    """Kinds allowed in a section type, or None when anything goes."""
    if type_id in GENERIC:
        return None
    try:
        own = set(section_type(type_id).kinds)
    except (KeyError, ValueError):
        return None
    if not own:
        return None
    return own | EXTRA_KINDS.get(type_id, set())


@dataclass
class FitReport:
    moved: list[tuple[str, str, str]] = field(default_factory=list)  # (asset id, from section title, to section title)
    retyped: list[tuple[str, str]] = field(default_factory=list)  # (old title, new title)
    kept: list[tuple[str, str]] = field(default_factory=list)  # (asset id, section title) — script/locked, reported only

    @property
    def changed(self) -> bool:
        return bool(self.moved or self.retyped)

    def notes(self, names: dict[str, str]) -> list[str]:
        out = []
        for aid, src, dst in self.moved[:8]:
            out.append(f"Section check: “{names.get(aid, aid)}” moved from “{src}” to “{dst}”, where it belongs.")
        for old, new in self.retyped[:8]:
            out.append(f"Section check: “{old}” renamed “{new}” to match its images.")
        for aid, title in self.kept[:8]:
            out.append(f"Section check: “{names.get(aid, aid)}” does not look like it belongs in “{title}” (kept: set by your script).")
        return out


def mismatches(sp: SectionPlan, kinds: dict[str, str]) -> list[str]:
    allowed = allowed_kinds(sp.type)
    if allowed is None:
        return []
    return [aid for aid in sp.asset_ids if aid in kinds and kinds[aid] not in allowed]


def _module_for(ids: list[str], assets: dict, concept: bool) -> tuple[str | None, list[str]]:
    """A composition module for moved assets (2.0 plans), by count and kind."""
    if not concept:
        return None, ids
    from behance_studio.assets.understanding import asset_nature

    kinds = {assets[i].effective_kind for i in ids}
    natures = {asset_nature(assets[i]) for i in ids}
    n = len(ids)
    if kinds <= {"social"}:
        return ("feed_grid", ids[:9]) if n >= 4 else ("phones", ids[:3])
    if kinds <= {"website"}:
        return "browser", ids[:1]
    if kinds <= {"mobile", "ui"}:
        return "phones", ids[:3]
    if kinds <= {"video", "motion"}:
        return "video_stage", ids[:1]
    if kinds <= {"logo", "logo_variant", "monogram"}:
        return ("logo_hero", ids[:1]) if n == 1 else ("logo_tiles", ids[:4])
    if kinds <= {"pattern"}:
        return "pattern_field", ids[:1]
    if kinds <= {"palette", "typography"}:
        return "doc_stage", ids[:1]
    if natures <= {"photo"}:
        if n == 1:
            return ("fullbleed" if assets[ids[0]].aspect >= 1.25 else "stage"), ids
        return ("duo", ids[:2]) if n == 2 else ("trio", ids[:3])
    if n == 1:
        return "stage", ids
    return ("stage_pair", ids[:2]) if n == 2 else ("trio", ids[:3])


def _capacity(sp: SectionPlan) -> int:
    module = sp.meta.get("module")
    if not module:
        return 99  # classic layouts arrange any number of images
    from behance_studio.ai.director import CATALOGUE

    spec = CATALOGUE.get(module)
    return spec.max if spec else len(sp.asset_ids)


def _retitle(sp: SectionPlan, type_id: str, language: str) -> None:
    sp.type = type_id
    if not sp.exact_text:
        sp.title = section_type(type_id).title(language)


def enforce_section_fit(plan: PresentationPlan, assets: dict) -> FitReport:
    """Move mis-sectioned assets (see module docstring). Changes ``plan`` in place."""
    from behance_studio.director.director import ALTERNATIVES

    report = FitReport()
    kinds = {aid: a.effective_kind for aid, a in assets.items()}
    concept = any(s.meta.get("module") for s in plan.sections)
    language = plan.language
    i = 0
    while i < len(plan.sections):
        sp = plan.sections[i]
        wrong = mismatches(sp, kinds)
        if not wrong:
            i += 1
            continue
        if sp.locked or sp.source == "script":
            report.kept += [(aid, sp.title) for aid in wrong]
            i += 1
            continue
        homes = {HOME.get(kinds[aid], "applications") for aid in wrong}
        if len(wrong) == len(sp.asset_ids) and len(homes) == 1:
            old = sp.title
            _retitle(sp, homes.pop(), language)
            report.retyped.append((old, sp.title))
            i += 1
            continue
        # Remove the misplaced assets, then give each group a proper home.
        sp.asset_ids = [aid for aid in sp.asset_ids if aid not in wrong]
        if concept:
            _refit_module(sp, assets, plan, ALTERNATIVES)
        groups: dict[str, list[str]] = {}
        for aid in wrong:
            groups.setdefault(HOME.get(kinds[aid], "applications"), []).append(aid)
        insert_at = i + 1
        for home, ids in groups.items():
            target = next((s for s in plan.sections if s is not sp and s.type == home and not s.locked and s.source != "script"
                           and len(s.asset_ids) + len(ids) <= _capacity(s)), None)
            if target is not None:
                target.asset_ids.extend(ids)
                report.moved += [(aid, sp.title, target.title) for aid in ids]
                continue
            while ids:
                module, chunk = _module_for(ids, assets, concept)
                ids = [x for x in ids if x not in chunk]
                new = SectionPlan(type=home, title=section_type(home).title(language), asset_ids=list(chunk))
                new.meta["fit_moved"] = True
                if module:
                    new.meta.update({"module": module, "params": {}, "alternatives": ALTERNATIVES.get(module, [module])})
                    _set_identity_meta(new, plan)
                plan.sections.insert(insert_at, new)
                insert_at += 1
                report.moved += [(aid, sp.title, new.title) for aid in chunk]
        i = insert_at
    if report.changed:
        from behance_studio.planning.planner import assign_stable_ids

        assign_stable_ids(plan)
    return report


def _refit_module(sp: SectionPlan, assets: dict, plan: PresentationPlan, alternatives: dict) -> None:
    """After removing assets, keep a module that can show what is left."""
    from behance_studio.ai.director import CATALOGUE

    spec = CATALOGUE.get(sp.meta.get("module", ""))
    if spec is None or spec.min <= len(sp.asset_ids) <= spec.max:
        return
    module, _ = _module_for(sp.asset_ids, assets, True)
    if module:
        sp.meta.update({"module": module, "params": {}, "alternatives": alternatives.get(module, [module])})
        _set_identity_meta(sp, plan)


def _set_identity_meta(sp: SectionPlan, plan: PresentationPlan) -> None:
    if sp.meta.get("module") in ("logo_hero", "logo_tiles", "logo_cards", "logo_pair", "pattern_field") and plan.logo_asset_id:
        sp.meta.setdefault("logo_id", plan.logo_asset_id)
