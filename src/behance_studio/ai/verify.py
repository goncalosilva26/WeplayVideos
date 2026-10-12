"""Verify local AI with a real model (``behance-studio ai-check --test``).

Runs the app's own AI steps against the configured Ollama model and reports
what actually happened — no simulated answers:

1. **Design-purpose recognition** on the bundled test images (a synthetic
   Butter & Bean set with known purposes) or on a folder of your own images.
   File names are hidden by default, so the score measures what the model
   *sees*, not what the files are called.
2. **Speed and GPU use** — seconds per image and how much of the model sits
   in GPU memory (Ollama's ``/api/ps``).
3. **Creative direction** — one storyboard for a concept, and whether it
   passed the app's validation.

The test images are drawn by ``tools/make_demo_assets.py``; they are
simplified graphics, so a model's score on real photographs and real
design files can differ. Run it on your own project folder as well.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Purposes accepted as correct for each test image (synthetic Butter & Bean set).
EXPECTED: dict[str, set[str]] = {
    "butter-bean-logo-primary.png": {"logo", "logo_variant"},
    "butter-bean-logo-alternative-stacked.png": {"logo", "logo_variant"},
    "butter-bean-monogram.png": {"monogram", "logo", "logo_variant"},
    "logo-negative-on-espresso.jpg": {"logo", "logo_variant"},
    "colour-palette.png": {"palette"},
    "typography-specimen.png": {"typography"},
    "brand-pattern.png": {"pattern", "illustration"},
    # The "photographs" are drawn scenes: a model may fairly call them illustrations.
    "DSC_0142.jpg": {"photo", "product", "lifestyle", "illustration"},
    "DSC_0157 shop interior.jpg": {"photo", "lifestyle", "illustration"},
    "DSC_0163.jpg": {"photo", "product", "lifestyle", "illustration"},
    "DSC_0171.jpg": {"photo", "product", "illustration"},
    "DSC_0188.jpg": {"photo", "lifestyle", "illustration"},
    "coffee-bag-mockup.jpg": {"packaging", "mockup", "product"},
    "takeaway-cups.jpg": {"packaging", "mockup", "product"},
    "pastry-box.jpg": {"packaging", "mockup", "product"},
    "poster-specialty-coffee.jpg": {"poster", "outdoor"},
    "poster-favourite-corner.jpg": {"poster", "outdoor"},
    "billboard-48-sheet.jpg": {"outdoor", "poster"},
    "instagram-post-01.jpg": {"social", "poster"},
    "instagram-post-02.jpg": {"social", "poster"},
    "instagram-post-03.jpg": {"social", "poster"},
    "instagram-post-04.jpg": {"social", "poster"},
}


@dataclass
class ImageResult:
    filename: str
    kind: str | None
    presentation: str | None
    confidence: float
    seconds: float
    expected: set[str] | None = None
    rejected: str = ""
    error: str = ""

    @property
    def correct(self) -> bool | None:
        if self.expected is None:
            return None
        return self.kind in self.expected and not self.rejected


@dataclass
class VerifyReport:
    status: object = None  # OllamaStatus
    images: list[ImageResult] = field(default_factory=list)
    gpu: list[dict] = field(default_factory=list)
    director: str = ""
    director_ok: bool | None = None
    director_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def scored(self) -> list[ImageResult]:
        return [r for r in self.images if r.expected is not None and not r.error]

    @property
    def accuracy(self) -> float | None:
        scored = self.scored
        return sum(1 for r in scored if r.correct) / len(scored) if scored else None

    @property
    def failures(self) -> int:
        return sum(1 for r in self.images if r.error)

    def lines(self) -> list[str]:
        out = [self.status.summary() if self.status else "Local AI not checked."]
        if self.images:
            out.append("")
            out.append("Design-purpose recognition:")
            for r in self.images:
                if r.error:
                    mark, what = "!", f"error: {r.error}"
                else:
                    mark = {True: "✓", False: "✗", None: "·"}[r.correct]
                    what = f"{r.kind} ({r.presentation or '-'}, {r.confidence:.2f})"
                    if r.rejected:
                        what += f" — not applied: {r.rejected}"
                    if r.correct is False:
                        what += f" — expected {' / '.join(sorted(r.expected or []))}"
                out.append(f"  {mark} {r.filename:<44} {what}  [{r.seconds:.1f}s]")
            times = [r.seconds for r in self.images if not r.error]
            if times:
                out.append(f"  {len(times)} image(s), {sum(times) / len(times):.1f}s per image on average")
            if self.accuracy is not None:
                out.append(f"  Accuracy on labelled test images: {self.accuracy:.0%} ({sum(1 for r in self.scored if r.correct)}/{len(self.scored)})")
        if self.gpu:
            out.append("")
            for g in self.gpu:
                share = f"{g['gpu_share']:.0%} in GPU memory" if g["size_gb"] else "size unknown"
                out.append(f"GPU: {g['name']} uses {g['size_gb']} GB, {share}.")
        if self.director:
            out.append("")
            out.append(f"Creative direction: {self.director} [{self.director_seconds:.0f}s]")
        out += [f"Note: {n}" for n in self.notes]
        return out


def _project_with(images_dir: Path | None, work: Path):
    from behance_studio.assets.importer import import_paths
    from behance_studio.projects.store import Project

    if images_dir is None:
        import sys

        from behance_studio.core.paths import tools_dir

        sys.path.insert(0, str(tools_dir()))
        from make_demo_assets import build_demo_assets

        images_dir = build_demo_assets(work / "Butter & Bean test images")
    project = Project.create(work / "projects", "AI check", copy_assets=False)
    import_paths(project, [images_dir])
    return project


def verify_local_ai(settings, folder: Path | None = None, hide_names: bool = True, director: bool = True,
                    limit: int = 40, progress: Callable[[str], None] = lambda m: None) -> VerifyReport:
    """Run the real model (see module docstring). Never raises for model errors."""
    from behance_studio.ai.ollama import DEFAULT_MODEL, DEFAULT_URL, detect, gpu_usage
    from behance_studio.ai.orchestrator import AIService
    from behance_studio.ai.providers import create_provider
    from behance_studio.core.errors import ProviderError

    report = VerifyReport()
    ai = settings.ai
    url, model = ai.base_url or DEFAULT_URL, ai.model or DEFAULT_MODEL
    report.status = detect(url, model, timeout=5.0)
    if not report.status.ready:
        return report
    work = Path(tempfile.mkdtemp(prefix="bs-ai-check-"))
    try:
        progress("Preparing test images…")
        project = _project_with(Path(folder) if folder else None, work)
        provider = create_provider(settings)
        service = AIService(provider, settings, project)
        assets = [a for a in project.list_assets() if a.is_visual and a.media_type != "video" and not a.animated][:limit]
        for i, asset in enumerate(assets, 1):
            progress(f"Recognising {i}/{len(assets)}: {asset.filename}")
            started = time.monotonic()
            expected = EXPECTED.get(asset.filename) if folder is None else None
            try:
                result = service._classify_one(asset, include_names=not hide_names)
            except ProviderError as exc:
                report.images.append(ImageResult(asset.filename, None, None, 0.0, time.monotonic() - started, expected, error=exc.message))
                if i == 1:
                    break  # the model does not answer at all: stop here
                continue
            seconds = time.monotonic() - started
            if result is None:
                report.images.append(ImageResult(asset.filename, None, None, 0.0, seconds, expected, error="unusable answer"))
                continue
            from behance_studio.ai.vision import implausible

            report.images.append(ImageResult(asset.filename, result["kind"], result.get("presentation"), result["confidence"],
                                             seconds, expected, rejected=implausible(result, asset)))
            if i == 1:
                report.gpu = gpu_usage(url)
        if not report.gpu:
            report.gpu = gpu_usage(url)
        all_failed = bool(report.images) and report.failures == len(report.images)
        if director and not all_failed:
            progress("Planning one concept with the AI director…")
            report.director, report.director_ok, report.director_seconds = _direct_once(service, project)
        if hide_names:
            report.notes.append("File names were hidden from the model: the score reflects what it sees.")
        if folder is None:
            report.notes.append("Test images are simplified synthetic graphics; also try your own project folder.")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return report


def _direct_once(service, project) -> tuple[str, bool, float]:
    from behance_studio.generation.pipeline import understand
    from behance_studio.layout.engine import ProposalSpec
    from behance_studio.planning.planner import PlanningContext

    assets = project.list_assets()
    directives, direction = understand(project, assets)
    ctx = PlanningContext(project.name, assets, directives, direction)
    started = time.monotonic()
    plan = service.direct_plan(project, ctx, ProposalSpec("minimal", 7, 0.5, 1400), ["minimal", "bold", "photo"])
    seconds = time.monotonic() - started
    if plan is None:
        reason = next((n for n in reversed(service.log) if "director" in n.lower() or "storyboard" in n.lower()), "no plan returned")
        return f"fell back to the offline director ({reason})", False, seconds
    info = plan.sections[0].meta.get("director", {})
    fixes = len(info.get("corrections", []))
    modules = ", ".join(s.meta.get("module", "?") for s in plan.sections)
    return f"AI storyboard accepted: {len(plan.sections)} sections ({modules}); {fixes} item(s) corrected by validation", True, seconds
