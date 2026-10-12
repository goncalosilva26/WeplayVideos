"""The end-to-end generation pipeline.

Stages (reported with real, measured progress):

 1. Importing assets             6. Generating layout proposals
 2. Analyzing materials          7. Rendering previews
 3. Understanding the project    8. Quality validation
 4. Planning the presentation    9. Saving versions
 5. Developing creative directions  10. Presenting results

Each proposal is generated independently: a failure in one does not discard
the others. Compositions with validation errors are revised automatically
(sections re-composed with other variants) before being saved.
"""

from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from behance_studio.assets.analysis import ANALYSIS_VERSION
from behance_studio.assets.importer import ImportReport, analyze_assets, import_paths
from behance_studio.brief.directives import Directives, build_directives
from behance_studio.brief.script import ScriptIssue
from behance_studio.core.errors import OperationCancelled, ScriptError
from behance_studio.core.logging_setup import get_logger
from behance_studio.core.tasks import CancelToken, ProgressEvent, StageTracker
from behance_studio.design.direction import CreativeDirection, build_direction
from behance_studio.generation.proposal import ProposalData
from behance_studio.layout.engine import ProposalSpec, build_plan, compose
from behance_studio.layout.families import available_families, family_info
from behance_studio.layout.validate import Issue, QualityReport, layout_distance, validate_presentation
from behance_studio.planning.planner import PlanningContext
from behance_studio.projects.models import VersionRecord
from behance_studio.projects.versions import VersionManager
from behance_studio.render.previews import render_previews

log = get_logger(__name__)

STAGES = ["import", "analyze", "understand", "plan", "direct", "layout", "render", "validate", "save", "present"]
STAGE_LABELS = {
    "import": "Importing assets",
    "analyze": "Analyzing materials",
    "understand": "Understanding the project",
    "plan": "Planning the presentation",
    "direct": "Developing creative directions",
    "layout": "Generating layout proposals",
    "render": "Rendering previews",
    "validate": "Quality validation",
    "save": "Saving versions",
    "present": "Presenting results",
}
STAGE_WEIGHTS = {"import": 2, "analyze": 3, "understand": 0.4, "plan": 0.4, "direct": 0.4, "layout": 2, "render": 3, "validate": 0.4, "save": 0.5, "present": 0.1}


@dataclass
class GenerationRequest:
    families: list[str] = field(default_factory=list)  # empty = all
    count: int = 0  # 0 = one per family
    creativity: float = 0.5
    width: int = 1400
    seed: int | None = None
    import_paths: list[Path] = field(default_factory=list)
    missing_reference_policy: str = "continue"  # continue | abort
    render_previews: bool = True
    browser_path: str = ""
    workers: int = 4
    use_ai: bool = True


@dataclass
class GenerationResult:
    versions: list[VersionRecord] = field(default_factory=list)
    failures: list[tuple[str, int, str]] = field(default_factory=list)
    script_issues: list[ScriptIssue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    import_report: ImportReport | None = None
    category: str = ""
    language: str = ""
    elapsed: float = 0.0
    ai_used: bool = False


def _hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


def proposal_specs(request: GenerationRequest, allowed: list[str] | None) -> list[ProposalSpec]:
    from behance_studio.layout.families import CONCEPT_FAMILIES

    defaults = [f for f in CONCEPT_FAMILIES if f in available_families()] or available_families()
    families = [f for f in (request.families or defaults) if f in available_families()]
    if allowed:
        families = [f for f in families if f in allowed] or list(allowed)
    if not families:
        families = defaults
    count = request.count or len(families)
    base = request.seed if request.seed is not None else random.randint(1, 900_000)
    specs = []
    for i in range(count):
        family = families[i % len(families)]
        round_ = i // len(families)
        specs.append(ProposalSpec(family=family, seed=base + i * 7919 + round_ * 13, creativity=request.creativity, width=request.width))
    return specs


def revise(proposal: ProposalData, assets: dict, max_rounds: int = 3) -> ProposalData:
    """Re-compose sections that failed validation with alternative variants."""
    report = proposal.quality
    rounds = 0
    while report.errors and rounds < max_rounds:
        rounds += 1
        bad_sections = {i.section_id for i in report.errors if i.section_id}
        plan_ids = {s.plan_id for s in proposal.presentation.sections if s.id in bad_sections}
        if not plan_ids:
            break
        overrides = dict(proposal.spec.overrides)
        for pid in plan_ids:
            entry = dict(overrides.get(pid, {}))
            entry["variant_seed"] = int(entry.get("variant_seed", 0)) + 101 * rounds
            overrides[pid] = entry
        spec = ProposalSpec(proposal.spec.family, proposal.spec.seed, proposal.spec.creativity, proposal.spec.width, overrides)
        pres = compose(proposal.plan, assets, proposal.direction, spec)
        new_report = validate_presentation(pres, assets, proposal.plan)
        if len(new_report.errors) <= len(report.errors):
            proposal = ProposalData(spec, proposal.plan, proposal.direction, pres, new_report, proposal.notes, proposal.sources)
            report = new_report
    if rounds:
        proposal.notes.append(f"Automatically revised {rounds} time(s) to resolve layout issues.")
    return proposal


FIXABLE_RENDERED = {"rendered_whitespace", "rendered_blank_media", "rendered_contrast", "rendered_off_balance"}


def refine_rendered(project, proposals: list[ProposalData], issues: dict[int, list[dict]], staging, assets: dict,
                    browser_path: str = "", token: CancelToken | None = None, note=lambda m: None, max_rounds: int = 2) -> None:
    """Targeted correction from rendered measurements (bounded).

    Sections flagged by the rendered QA are recomposed with an alternative
    module (same content), the proposal is re-rendered, and the change is
    kept only if the rendered score improves and no geometry error appears.
    """
    from behance_studio.qa.rendered import score

    for i, proposal in enumerate(proposals):
        found = [x for x in issues.get(i, []) if x.get("kind") in FIXABLE_RENDERED]
        rounds = 0
        while found and rounds < max_rounds:
            if token:
                token.raise_if_cancelled()
            rounds += 1
            bad = {x.get("section") for x in found}
            plan_ids = {s.plan_id for s in proposal.presentation.sections if s.id in bad and s.plan_id}
            if not plan_ids:
                break
            overrides = dict(proposal.spec.overrides)
            for pid in plan_ids:
                entry = dict(overrides.get(pid, {}))
                entry["variant_seed"] = int(entry.get("variant_seed", 0)) + 101
                overrides[pid] = entry
            spec = ProposalSpec(proposal.spec.family, proposal.spec.seed, proposal.spec.creativity, proposal.spec.width, overrides)
            pres = compose(proposal.plan, assets, proposal.direction, spec)
            report = validate_presentation(pres, assets, proposal.plan)
            if len(report.errors) > len(proposal.quality.errors):
                break
            trial_thumb, trial_strip = staging / f"{i}-trial-thumb.jpg", staging / f"{i}-trial-strip.jpg"
            trial = render_previews(project, [(pres, trial_thumb, trial_strip)], token, browser_path=browser_path).get(0, [])
            if score(trial) < score(issues.get(i, [])):
                proposal.spec, proposal.presentation, proposal.quality = spec, pres, report
                trial_thumb.replace(staging / f"{i}-thumb.jpg")
                trial_strip.replace(staging / f"{i}-strip.jpg")
                issues[i] = trial
                proposal.notes.append(f"Rendered check: {len(plan_ids)} section(s) recomposed to fix visual issues.")
                found = [x for x in trial if x.get("kind") in FIXABLE_RENDERED]
                note(f"Refined {family_info(proposal.spec.family).name}")
            else:
                for path in (trial_thumb, trial_strip):
                    if path.exists():
                        path.unlink()
                break


def merge_browser_issues(report: QualityReport, browser_issues: list[dict]) -> None:
    for item in browser_issues:
        kind = item.get("kind")
        if str(kind).startswith("rendered_"):
            report.issues.append(Issue(item.get("severity", "warning"), kind, item.get("message", ""), item.get("section", ""), item.get("block", "")))
            continue
        if kind == "text_overflow":
            report.issues.append(Issue("warning", "rendered_overflow", f"Rendered text is {item.get('overflow', 0):.0f}px wider than its box.", item.get("section", ""), item.get("block", "")))
        elif kind == "broken_image":
            report.issues.append(Issue("error", "broken_image", "An image could not be displayed in the rendered preview.", item.get("section", ""), item.get("block", "")))
    report.metrics["rendered_check"] = 1.0


def understand(project, assets) -> tuple[Directives, CreativeDirection]:
    directives = build_directives(
        project.name,
        assets,
        brief_text=project.brief_text,
        script_text=project.script_text,
        project_language=project.config.language,
        category_override=project.config.category_override,
    )
    direction = build_direction(directives.brief, assets, directives.category)
    return directives, direction


def generate(
    project,
    request: GenerationRequest,
    token: CancelToken | None = None,
    progress: Callable[[ProgressEvent], None] = lambda e: None,
    ai_service=None,
) -> GenerationResult:
    started = time.monotonic()
    token = token or CancelToken()
    tracker = StageTracker(STAGES, progress, STAGE_WEIGHTS)
    result = GenerationResult()

    # 1 ── import
    tracker.start("import", STAGE_LABELS["import"])
    if request.import_paths:
        result.import_report = import_paths(project, request.import_paths, token=token, progress=lambda f, m: tracker.update(f, m), workers=request.workers, analyze=False)
        if result.import_report.cancelled:
            raise OperationCancelled("Generation cancelled")
    tracker.update(1.0, "Assets ready")
    token.raise_if_cancelled()

    # 2 ── analyze
    tracker.start("analyze", STAGE_LABELS["analyze"])
    assets = project.list_assets()
    stale = [a for a in assets if a.is_visual and (a.analysis or {}).get("version") != ANALYSIS_VERSION]
    if stale:
        analyze_assets(project, stale, token=token, progress=lambda f, m: tracker.update(f * (0.7 if ai_service else 1.0), m), workers=request.workers)
    project.refresh_missing()
    assets = project.list_assets()
    if ai_service is not None and request.use_ai:
        try:
            changed = ai_service.classify_assets(project, assets, token=token, progress=lambda f, m: tracker.update(0.7 + 0.3 * f, m))
            if changed:
                result.ai_used = True
                assets = project.list_assets()
        except OperationCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - AI is optional
            log.warning("AI classification skipped: %s", exc)
            result.notes.append(f"AI analysis was skipped: {getattr(exc, 'message', exc)}")
    usable = [a for a in assets if a.is_visual and not a.excluded]
    if not usable:
        raise ScriptError("There are no usable images or videos in this project yet. Import some assets first.")
    tracker.update(1.0, f"{len(usable)} visual asset(s) analysed")
    token.raise_if_cancelled()

    # 3 ── understand
    tracker.start("understand", STAGE_LABELS["understand"])
    directives, direction = understand(project, assets)
    if ai_service is not None and request.use_ai:
        try:
            if ai_service.refine_direction(project, directives, direction):
                result.ai_used = True
        except Exception as exc:  # noqa: BLE001
            log.warning("AI brief interpretation skipped: %s", exc)
    result.script_issues = list(directives.issues)
    result.category = directives.category.category
    result.language = directives.language
    result.notes.extend(directives.notes)
    if directives.blocking_issues and request.missing_reference_policy == "abort":
        raise ScriptError(
            "The project script refers to files that could not be found. Review the script issues before generating.",
            "\n".join(i.message for i in directives.blocking_issues),
        )
    tracker.update(1.0, f"{directives.category.label(directives.language)} · {directives.language.upper()}")

    # 4 ── plan
    tracker.start("plan", STAGE_LABELS["plan"])
    ctx = PlanningContext(project.name, assets, directives, direction)
    specs = proposal_specs(request, directives.families_allowed)
    plans = []
    for i, spec in enumerate(specs):
        token.raise_if_cancelled()
        try:
            plan = build_plan(ctx, spec)
            if ai_service is not None and request.use_ai:
                try:
                    if ai_service.write_copy(project, plan, directives, direction):
                        result.ai_used = True
                except Exception as exc:  # noqa: BLE001
                    log.warning("AI copywriting skipped: %s", exc)
            plans.append((spec, plan))
        except Exception as exc:  # noqa: BLE001
            log.exception("Planning failed for %s", spec.family)
            result.failures.append((spec.family, spec.seed, f"Planning failed: {exc}"))
        tracker.update((i + 1) / len(specs), f"Planned {family_info(spec.family).name}")

    # 5 ── creative directions
    tracker.start("direct", STAGE_LABELS["direct"])
    tracker.update(1.0, f"{len(plans)} creative direction(s)")

    # 6 ── layout
    tracker.start("layout", STAGE_LABELS["layout"])
    by_id = {a.id: a for a in assets}
    sources = {
        "brief_hash": _hash(project.brief_text),
        "script_hash": _hash(project.script_text),
        "category": directives.category.category,
        "language": directives.language,
        "provenance": directives.provenance,
        "ai": bool(result.ai_used),
    }
    proposals: list[ProposalData] = []
    for i, (spec, plan) in enumerate(plans):
        token.raise_if_cancelled()
        try:
            pres = compose(plan, by_id, direction, spec)
            report = validate_presentation(pres, by_id, plan)
            proposal = ProposalData(spec, plan, direction, pres, report, list(plan.notes), dict(sources))
            if report.errors:
                proposal = revise(proposal, by_id)
            proposals.append(proposal)
        except OperationCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - isolate failures per proposal
            log.exception("Layout failed for %s", spec.family)
            result.failures.append((spec.family, spec.seed, f"Layout failed: {exc}"))
        tracker.update((i + 1) / max(1, len(plans)), f"Composed {family_info(spec.family).name}")

    # 7 ── render previews (thumbnails go into a staging folder first)
    tracker.start("render", STAGE_LABELS["render"])
    staging = project.cache_subdir("staging") / f"gen-{int(time.time() * 1000)}"
    staging.mkdir(parents=True, exist_ok=True)
    browser_issues: dict[int, list[dict]] = {}
    if request.render_previews and proposals:
        jobs = [(p.presentation, staging / f"{i}-thumb.jpg", staging / f"{i}-strip.jpg") for i, p in enumerate(proposals)]
        try:
            browser_issues = render_previews(project, jobs, token, lambda f, m: tracker.update(f, m), request.browser_path)
        except OperationCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Preview rendering failed")
            result.notes.append(f"Previews could not be rendered: {getattr(exc, 'message', exc)}")
    tracker.update(1.0, "Previews ready")

    # 7b ── rendered QA: recompose weak sections, re-render, keep improvements
    if request.render_previews and proposals and browser_issues:
        try:
            refine_rendered(project, proposals, browser_issues, staging, by_id, request.browser_path, token, lambda m: tracker.update(1.0, m))
        except OperationCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - refinement is best effort
            log.warning("Rendered refinement skipped: %s", exc)

    # 8 ── validate
    tracker.start("validate", STAGE_LABELS["validate"])
    for i, proposal in enumerate(proposals):
        if i in browser_issues:
            merge_browser_issues(proposal.quality, browser_issues[i])
        for j in range(i):
            if proposals[j].spec.family == proposal.spec.family and layout_distance(proposals[j].presentation, proposal.presentation) < 0.08:
                proposal.notes.append("Very similar to another proposal of the same family.")
    tracker.update(1.0, "Validated")

    # 9 ── save
    tracker.start("save", STAGE_LABELS["save"])
    manager = VersionManager(project)
    for i, proposal in enumerate(proposals):
        token.raise_if_cancelled()
        try:
            record = manager.create(proposal)
            for kind in ("thumb", "strip"):
                src = staging / f"{i}-{kind}.jpg"
                if src.exists():
                    src.replace(manager.folder(record) / f"{kind}.jpg")
            result.versions.append(record)
        except Exception as exc:  # noqa: BLE001
            log.exception("Saving proposal failed")
            result.failures.append((proposal.spec.family, proposal.spec.seed, f"Saving failed: {exc}"))
        tracker.update((i + 1) / max(1, len(proposals)), f"Saved {i + 1} of {len(proposals)}")
    try:
        for leftover in staging.glob("*"):
            leftover.unlink()
        staging.rmdir()
    except OSError:
        pass

    # 10 ── present
    tracker.start("present", STAGE_LABELS["present"])
    if ai_service is not None and request.use_ai:
        result.notes.extend(getattr(ai_service, "log", []))
        status = getattr(ai_service, "status", None)
        if callable(status) and not result.ai_used:
            result.notes.append(status())
    result.elapsed = time.monotonic() - started
    tracker.update(1.0, f"{len(result.versions)} proposal(s) ready")
    log.info("Generated %d proposal(s) for %s in %.1fs (%d failure(s))", len(result.versions), project.name, result.elapsed, len(result.failures))
    return result
