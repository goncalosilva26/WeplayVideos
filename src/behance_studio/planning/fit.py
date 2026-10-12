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
from behance_studio.planning.assignment import HOME  # noqa: E402 - one table for where each kind belongs


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
    reordered: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.moved or self.retyped or self.reordered)

    def notes(self, names: dict[str, str]) -> list[str]:
        out = []
        for aid, src, dst in self.moved[:8]:
            if src == "(not planned)":
                out.append(f"Section check: “{names.get(aid, aid)}” added to “{dst}” (the plan had left its section out).")
            else:
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


def enforce_section_fit(plan: PresentationPlan, assets: dict, assignment=None) -> FitReport:
    """Move mis-sectioned assets (see module docstring). Changes ``plan`` in place.

    With a folder-based ``assignment`` (planning.assignment) the designer's
    folders decide: every image is kept in, or moved back to, the section of
    its folder, and sections follow the folder order."""
    if assignment is not None and getattr(assignment, "by_folders", False):
        report = FitReport()
        _enforce_folders(plan, assets, assignment, report)
        if report.changed:
            from behance_studio.planning.planner import assign_stable_ids

            assign_stable_ids(plan)
        return report
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


# ------------------------------------------------------------ folder mode
def _body(plan: PresentationPlan) -> list[SectionPlan]:
    return [s for s in plan.sections if s.type not in ("cover", "closing")]


def _enforce_folders(plan: PresentationPlan, assets: dict, asg, report: FitReport) -> None:
    from behance_studio.assets.folders import NON_SECTION_TYPES
    from behance_studio.director.director import ALTERNATIVES

    placements = asg.placements
    concept = any(s.meta.get("module") for s in plan.sections)
    # 1. Each body section belongs to one folder section.
    for sp in _body(plan):
        keys = [placements[a].key for a in sp.asset_ids if a in placements]
        if keys and not sp.meta.get("folder_section"):
            sp.meta["folder_section"] = max(dict.fromkeys(keys), key=keys.count)
    # 2. Take out images that belong to another folder section.
    pending: dict[str, list[tuple[str, str]]] = {}
    for sp in _body(plan):
        key = sp.meta.get("folder_section")
        if not key:
            continue
        wrong = [a for a in sp.asset_ids if a in placements and placements[a].key != key]
        if not wrong:
            continue
        if sp.locked or sp.source == "script":
            report.kept += [(a, sp.title) for a in wrong]
            continue
        sp.asset_ids = [a for a in sp.asset_ids if a not in wrong]
        for a in wrong:
            pending.setdefault(placements[a].key, []).append((a, sp.title))
        if concept and sp.asset_ids:
            _refit_module(sp, assets, plan, ALTERNATIVES)
    # Sections left without the images their module needs disappear.
    plan.sections = [s for s in plan.sections if s.asset_ids or not s.meta.get("module") or _needs_no_assets(s)]
    # 3. Put them back where they belong.
    for key, items in pending.items():
        placement = placements[items[0][0]]
        ids = [a for a, _ in items]
        for target in [s for s in _body(plan) if s.meta.get("folder_section") == key and not s.meta.get("chapter")]:
            room = _capacity(target) - len(target.asset_ids)
            if room > 0 and ids:
                take, ids = ids[:room], ids[room:]
                target.asset_ids.extend(take)
                report.moved += [(a, src, target.title) for a, src in items if a in take]
        if not ids:
            continue
        positions = [i for i, s in enumerate(plan.sections) if s.meta.get("folder_section") == key]
        insert_at = positions[-1] + 1 if positions else max(1, len(plan.sections) - 1)
        kinds = [assets[a].effective_kind for a in ids if a in assets]
        type_id = placement.type if placement.type not in NON_SECTION_TYPES else HOME.get(max(set(kinds), key=kinds.count), "gallery")
        while ids:
            module, chunk = _module_for(ids, assets, concept)
            ids = [x for x in ids if x not in chunk]
            new = SectionPlan(type=type_id, title=placement.title, asset_ids=list(chunk))
            new.meta.update({"fit_moved": True, "folder_section": key})
            if module:
                new.meta.update({"module": module, "params": {}, "alternatives": ALTERNATIVES.get(module, [module])})
                _set_identity_meta(new, plan)
            plan.sections.insert(insert_at, new)
            insert_at += 1
            report.moved += [(a, src, new.title) for a, src in items if a in chunk]
    # 3b. A folder section the plan left out entirely (e.g. an AI storyboard) is added back.
    shown = {a for s in plan.sections for a in s.asset_ids}
    for placement, ids in asg.groups():
        if placement.source != "folder" or any(s.meta.get("folder_section") == placement.key for s in _body(plan)):
            continue
        missing = [a for a in ids if a not in shown and a in assets]
        if not missing:
            continue
        kinds = [assets[a].effective_kind for a in missing]
        type_id = placement.type if placement.type not in NON_SECTION_TYPES else HOME.get(max(set(kinds), key=kinds.count), "gallery")
        insert_at = max(1, len(plan.sections) - (1 if plan.sections and plan.sections[-1].type == "closing" else 0))
        while missing:
            module, chunk = _module_for(missing, assets, concept)
            missing = [x for x in missing if x not in chunk]
            new = SectionPlan(type=type_id, title=placement.title, asset_ids=list(chunk))
            new.meta.update({"fit_moved": True, "folder_section": placement.key})
            if module:
                new.meta.update({"module": module, "params": {}, "alternatives": ALTERNATIVES.get(module, [module])})
                _set_identity_meta(new, plan)
            plan.sections.insert(insert_at, new)
            insert_at += 1
            report.moved += [(a, "(not planned)", placement.title) for a in chunk]
    # 4. Folder sections carry the designer's title — chapter cards included:
    #    a chapter opens the folder section that follows it.
    body = _body(plan)
    for i, sp in enumerate(body):
        if sp.meta.get("chapter") and not sp.meta.get("folder_section"):
            nxt = next((x.meta["folder_section"] for x in body[i + 1:] if x.meta.get("folder_section")), None)
            if nxt:
                sp.meta["folder_section"] = nxt
    titles = {p.key: p for p in placements.values()}
    for sp in _body(plan):
        p = titles.get(sp.meta.get("folder_section", ""))
        if p is None or sp.locked or sp.source == "script":
            continue
        if sp.meta.get("chapter"):
            sp.title = p.title
            continue
        if sp.title != p.title and not sp.exact_text:
            if sp.asset_ids and sp.title and sp.meta.get("title_source") not in ("folder", "type"):
                report.retyped.append((sp.title, p.title))
            sp.title = p.title
        if p.type not in NON_SECTION_TYPES and sp.type != p.type:
            sp.type = p.type
    # 5. Sections follow the folder order (text pauses travel with the next section).
    report.reordered = _reorder(plan, asg) or report.reordered


def _needs_no_assets(sp: SectionPlan) -> bool:
    from behance_studio.ai.director import CATALOGUE, COVERS

    spec = CATALOGUE.get(sp.meta.get("module", "")) or COVERS.get(sp.meta.get("module", ""))
    return spec is None or spec.min == 0


def _reorder(plan: PresentationPlan, asg) -> bool:
    if any(s.locked or s.source == "script" for s in plan.sections):
        return False
    head = [s for s in plan.sections if s.type == "cover"]
    tail = [s for s in plan.sections if s.type == "closing"]
    body = _body(plan)
    keyed = [asg.order_of(s.meta["folder_section"]) if s.meta.get("folder_section") else None for s in body]
    ranks: list[float] = []
    for i, rank in enumerate(keyed):
        if rank is None:  # a text pause (statement, quote, swatches): stays before the next section
            rank = next((r for r in keyed[i + 1:] if r is not None), float("inf"))
        ranks.append(rank)
    ordered = [s for _, _, s in sorted(zip(ranks, range(len(body)), body), key=lambda t: (t[0], t[1]))]
    if ordered == body:
        return False
    plan.sections = head + ordered + tail
    return True


def placement_violations(plan: PresentationPlan, asset_sections: dict) -> list[tuple[str, str, str]]:
    """(asset id, section title, intended section title) for every image shown
    outside its intended section (cover and closing excepted)."""
    out = []
    for sp in plan.sections:
        if sp.type in ("cover", "closing"):
            continue
        key = sp.meta.get("folder_section")
        for a in sp.asset_ids:
            want = asset_sections.get(a)
            if want and key and want.get("key") != key:
                out.append((a, sp.title, want.get("title", "")))
            elif want and not key and not str(want.get("key", "")).startswith("kind:") and sp.source != "script":
                out.append((a, sp.title, want.get("title", "")))
    return out
