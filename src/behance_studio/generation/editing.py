"""Optional refinement of a generated proposal.

Edits are stored as *overrides* on top of the generated plan, so they
survive re-composition, can be undone (each save keeps the previous state in
the version history) and never alter source assets. Content that the project
script fixes (exact text, order, assigned images) can only be changed with
an explicit ``allow_script_override``.
"""

from __future__ import annotations

import copy
from dataclasses import replace

from behance_studio.core.errors import ScriptError, UserFacingError
from behance_studio.generation.proposal import ProposalData
from behance_studio.layout.engine import ProposalSpec, compose
from behance_studio.layout.validate import validate_presentation
from behance_studio.planning.models import SectionPlan
from behance_studio.planning.planner import assign_stable_ids
from behance_studio.projects.models import new_id
from behance_studio.projects.versions import VersionManager
from behance_studio.render.previews import render_previews

CONTENT_FIELDS = {"title", "subtitle", "body", "eyebrow", "asset_ids", "captions"}
STYLE_FIELDS = {"background", "spacing", "variant_seed", "hidden", "focal", "layout_hint"}


def _section(proposal: ProposalData, section_id: str) -> SectionPlan:
    for sp in proposal.plan.sections:
        if sp.id == section_id:
            return sp
    raise UserFacingError("That section no longer exists in this proposal.")


def _recompose(project, proposal: ProposalData, spec: ProposalSpec | None = None) -> ProposalData:
    spec = spec or proposal.spec
    assets = {a.id: a for a in project.list_assets()}
    pres = compose(proposal.plan, assets, proposal.direction, spec)
    report = validate_presentation(pres, assets, proposal.plan)
    return ProposalData(spec, proposal.plan, proposal.direction, pres, report, list(proposal.notes), dict(proposal.sources))


def edit_section(project, proposal: ProposalData, section_id: str, changes: dict, allow_script_override: bool = False) -> ProposalData:
    sp = _section(proposal, section_id)
    unknown = set(changes) - CONTENT_FIELDS - STYLE_FIELDS
    if unknown:
        raise UserFacingError(f"Unsupported edit: {', '.join(sorted(unknown))}")
    if sp.locked and not allow_script_override:
        protected = {k for k in changes if k in CONTENT_FIELDS}
        if "hidden" in changes and changes["hidden"]:
            protected.add("hidden")
        if protected:
            raise ScriptError(
                "This section's content is defined by the project script (GUIAO_PROJETO.txt). "
                "Confirm the override to change it.",
                f"protected fields: {sorted(protected)}",
            )
    overrides = copy.deepcopy(proposal.spec.overrides)
    entry = dict(overrides.get(section_id, {}))
    for key, value in changes.items():
        if key == "captions":
            caps = dict(entry.get("captions", {}))
            caps.update(value or {})
            entry["captions"] = caps
        elif key == "focal":
            focal = dict(entry.get("focal", {}))
            focal.update(value or {})
            entry["focal"] = focal
        elif value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    overrides[section_id] = entry
    spec = replace(proposal.spec, overrides=overrides)
    result = _recompose(project, proposal, spec)
    if sp.locked and allow_script_override and set(changes) & CONTENT_FIELDS:
        result.notes.append(f"Script content of '{sp.title}' was overridden by the user.")
    return result


def regenerate_section(project, proposal: ProposalData, section_id: str) -> ProposalData:
    entry = proposal.spec.overrides.get(section_id, {})
    return edit_section(project, proposal, section_id, {"variant_seed": int(entry.get("variant_seed", 0)) + 1})


def move_section(project, proposal: ProposalData, section_id: str, delta: int, allow_script_override: bool = False) -> ProposalData:
    plan = copy.deepcopy(proposal.plan)
    ids = [s.id for s in plan.sections]
    i = ids.index(section_id)
    j = max(0, min(len(ids) - 1, i + delta))
    if i == j:
        return proposal
    if (plan.sections[i].locked or plan.sections[j].locked or plan.script_driven) and not allow_script_override:
        raise ScriptError("The section order is defined by the project script. Confirm the override to reorder.")
    if plan.sections[j].type in ("cover",) or plan.sections[i].type in ("cover", "closing"):
        raise UserFacingError("The cover and closing sections keep their positions.")
    plan.sections.insert(j, plan.sections.pop(i))
    new = ProposalData(proposal.spec, plan, proposal.direction, proposal.presentation, proposal.quality, list(proposal.notes), dict(proposal.sources))
    return _recompose(project, new)


def duplicate_section(project, proposal: ProposalData, section_id: str) -> ProposalData:
    plan = copy.deepcopy(proposal.plan)
    i = next(k for k, s in enumerate(plan.sections) if s.id == section_id)
    if plan.sections[i].type in ("cover", "closing"):
        raise UserFacingError("The cover and closing cannot be duplicated.")
    clone = copy.deepcopy(plan.sections[i])
    clone.id = new_id()
    clone.locked = False
    clone.source = "user"
    plan.sections.insert(i + 1, clone)
    spec = proposal.spec
    if section_id in spec.overrides:
        overrides = copy.deepcopy(spec.overrides)
        overrides[clone.id] = dict(overrides[section_id])
        overrides[clone.id]["variant_seed"] = int(overrides[clone.id].get("variant_seed", 0)) + 1
        spec = replace(spec, overrides=overrides)
    new = ProposalData(spec, plan, proposal.direction, proposal.presentation, proposal.quality, list(proposal.notes), dict(proposal.sources))
    return _recompose(project, new)


def apply_family(project, proposal: ProposalData, family: str) -> ProposalData:
    """Same plan, text and overrides, composed by another layout family."""
    spec = replace(proposal.spec, family=family)
    return _recompose(project, proposal, spec)


def refresh(project, proposal: ProposalData) -> ProposalData:
    """Re-compose with current assets (e.g. after relinking a missing file)."""
    return _recompose(project, proposal)


def save_and_preview(project, version_id: str, proposal: ProposalData, label: str, browser_path: str = "") -> None:
    manager = VersionManager(project)
    record = manager.save(version_id, proposal, label=label)
    try:
        render_previews(project, [(proposal.presentation, manager.thumb_path(record), manager.strip_path(record))], browser_path=browser_path)
    except Exception:  # noqa: BLE001 - previews are best effort after an edit
        pass


def new_seed_version(project, version_id: str, seed: int | None = None, family: str | None = None, browser_path: str = "") -> str:
    """Regenerate a proposal (new seed and/or family) as a new version."""
    import random

    from behance_studio.generation.pipeline import understand
    from behance_studio.layout.engine import build_plan
    from behance_studio.planning.planner import PlanningContext

    manager = VersionManager(project)
    old = manager.load(version_id)
    assets = project.list_assets()
    directives, direction = understand(project, assets)
    spec = ProposalSpec(family or old.spec.family, seed if seed is not None else random.randint(1, 900_000), old.spec.creativity, old.spec.width)
    ctx = PlanningContext(project.name, assets, directives, direction)
    plan = assign_stable_ids(build_plan(ctx, spec))
    by_id = {a.id: a for a in assets}
    pres = compose(plan, by_id, direction, spec)
    report = validate_presentation(pres, by_id, plan)
    proposal = ProposalData(spec, plan, direction, pres, report, list(plan.notes), dict(old.sources))
    if report.errors:
        from behance_studio.generation.pipeline import revise

        proposal = revise(proposal, by_id)
    record = manager.create(proposal, parent_id=version_id)
    try:
        render_previews(project, [(proposal.presentation, manager.thumb_path(record), manager.strip_path(record))], browser_path=browser_path)
    except Exception:  # noqa: BLE001
        pass
    return record.id
