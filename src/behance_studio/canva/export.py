"""Export to Canva: proposals → editable PowerPoint files (+ upload to Canva).

For each proposal (or all of them in one combined design):

* ``<name>.pptx`` — the design, one page size, every text box, picture and
  shape separately editable;
* ``<name> - Canva report.txt`` — how to open it in Canva, the page and
  section structure, the conversion check, and every approximation;
* ``<name>.canva.json`` — the exported pages as a structured scene
  (elements with geometry, styles and stacking order) for other tools;
* ``Fonts for Canva/`` — the font files used, with their licences (SIL OFL),
  for uploading to a Canva Brand Kit when Canva's library lacks a family.

With a connected Canva account the file is also imported into Canva through
the Connect API and the design's edit link is returned.
"""

from __future__ import annotations

import shutil
from collections import Counter
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from behance_studio.canva.build import BuildOptions, build_scene
from behance_studio.canva.media import DENSITY
from behance_studio.canva.model import PagedScene
from behance_studio.canva.pages import combine, paginate, paginate_many
from behance_studio.canva.pptx_out import write_pptx
from behance_studio.core.errors import ExportError, OperationCancelled, UserFacingError
from behance_studio.core.fsutil import atomic_write_json, atomic_write_text, safe_filename, unique_path
from behance_studio.core.logging_setup import get_logger
from behance_studio.core.tasks import CancelToken
from behance_studio.projects.models import ExportRecord, new_id
from behance_studio.projects.versions import VersionManager

log = get_logger(__name__)

CANVA_MAX_BYTES = 50 * 1024 * 1024  # Canva Help Center: PowerPoint imports up to 50 MB
SAFE_BYTES = 45 * 1024 * 1024
CANVA_MAX_PAGES = 100


@dataclass
class CanvaOptions:
    destination: Path
    page_height: int | None = None  # None/0 = automatic
    mode: str = "exact"  # exact | editable
    quality: str = "high"  # standard | high | maximum
    section_ids: list[str] | None = None
    combine: bool = False  # all proposals in one design
    upload: bool = False  # import into Canva (needs a connected account)
    check: bool = True  # compare exported pages with the original (Chromium)
    check_with_libreoffice: bool = False  # also render the .pptx with LibreOffice when installed
    browser_path: str = ""
    filename_pattern: str = "{project} - {proposal}"
    include_fonts: bool = True


@dataclass
class CanvaDesign:
    name: str
    version_ids: list[str]
    pptx: Path
    report: Path
    scene_json: Path
    pages: int
    page_size: tuple[int, int]
    size_bytes: int
    counts: dict[str, int]
    similarity: float | None = None  # conversion check (0..1)
    office_similarity: float | None = None
    notes: list[str] = field(default_factory=list)
    edit_url: str = ""
    upload_error: str = ""


@dataclass
class CanvaReport:
    designs: list[CanvaDesign] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    fonts_dir: Path | None = None
    cancelled: bool = False

    @property
    def files(self) -> list[Path]:
        return [d.pptx for d in self.designs]

    def summary(self) -> str:
        n = len(self.designs)
        text = f"{n} Canva design file{'s' if n != 1 else ''} created"
        uploaded = sum(1 for d in self.designs if d.edit_url)
        if uploaded:
            text += f", {uploaded} opened in Canva"
        if self.failures:
            text += f", {len(self.failures)} problem(s)"
        if self.cancelled:
            text += " (cancelled)"
        return text


# ------------------------------------------------------------------- report
def _counts(paged: PagedScene) -> dict[str, int]:
    c: Counter = Counter()
    for p in paged.pages:
        for e in p.elements:
            if e.role == "filler":
                continue
            c["text boxes" if e.kind == "text" else "pictures" if e.kind == "image" else "shapes"] += 1
    return dict(c)


def _approximations(paged: PagedScene) -> list[str]:
    seen: dict[str, set] = {}
    for p in paged.pages:
        for e in p.elements:
            for n in e.notes:
                if "continues across the page edge" in n:
                    continue
                # one element split over two pages counts once
                seen.setdefault(n, set()).add((e.section, e.block_id or e.role, e.kind))
    ranked = sorted(seen.items(), key=lambda kv: -len(kv[1]))
    return [f"{n} ({len(k)}×)" if len(k) > 1 else n for n, k in ranked]


def _fonts_note(paged: PagedScene) -> list[str]:
    from behance_studio.design.typography import FONTS

    out = []
    for fam, weights in sorted(paged.scene.fonts.items()):
        f = FONTS.get(fam)
        ws = ", ".join(str(w) for w in sorted(weights))
        out.append(f"{fam} (weights used: {ws}){' — variable font' if f and f.variable else ''}")
    return out


def report_text(project, name: str, design: CanvaDesign, paged: PagedScene, uploaded: bool) -> str:
    W, H = design.page_size
    lines = [
        f"Behance Studio → Canva — {name}",
        f"Project: {project.name}    Created: {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"File: {design.pptx.name}  ({design.pages} page(s) of {W} × {H} px, {design.size_bytes / 1e6:.1f} MB)",
        "",
        "HOW TO OPEN IT IN CANVA",
    ]
    if design.edit_url:
        lines.append(f"  Already imported into your Canva account: {design.edit_url}")
        lines.append("  (Canva's editing links are temporary; the design itself stays in your Canva projects.)")
    else:
        lines += [
            "  1. Go to canva.com (signed in) and drag this .pptx file onto the home page,",
            "     or choose Create a design → Import file and select it.",
            "  2. Canva converts it into an editable design: every text box, picture and shape is",
            "     its own element. (Canva accepts PowerPoint files up to 50 MB and 100 pages.)",
            "  Tip: connect your Canva account in Settings → Canva to do this automatically.",
        ]
    lines += ["", "WHAT IS EDITABLE"]
    lines.append("  " + ", ".join(f"{v} {k}" for k, v in sorted(design.counts.items())) + " — each separately selectable.")
    lines.append("  Text keeps its font, size, colour, spacing and line breaks; paragraphs of body text re-wrap when edited.")
    lines.append("  Pictures keep their crop: double-click a picture in Canva to adjust it.")
    lines += ["", "PAGES AND SECTIONS (the presentation reads top to bottom across pages)"]
    titles = {s.index: s.title for s in paged.scene.sections}
    for p in paged.pages:
        names = ", ".join(dict.fromkeys(titles.get(i, "") for i in p.sections if titles.get(i))) or "—"
        extra = f"  (+{p.filler:.0f} px background at the end)" if p.filler > 0.5 else ""
        lines.append(f"  Page {p.index + 1}: {(p.label + ' — ') if p.label else ''}{names}{extra}")
    lines.append("  To publish on Behance: download every page from Canva as PNG/JPG and upload them in order;")
    lines.append("  set the spacing between images to 0 so the pages join seamlessly.")
    lines += ["", "VISUAL CHECK"]
    if design.similarity is not None:
        lines.append(f"  Conversion check: {design.similarity * 100:.1f}% of the page area matches the original "
                     "(the exported pages drawn with exactly the properties stored in the file).")
    else:
        lines.append("  Conversion check: not run.")
    if design.office_similarity is not None:
        lines.append(f"  PowerPoint file rendered by LibreOffice: {design.office_similarity * 100:.1f}% matches the original.")
    lines.append("  Canva's own rendering could not be measured here: compare the first pages in Canva with the preview.")
    approx = _approximations(paged)
    lines += ["", "APPROXIMATIONS (closest editable alternative used)"]
    lines += [f"  • {a}" for a in approx] or ["  • none"]
    for n in paged.notes:
        lines.append(f"  • {n}")
    lines += ["", "FONTS"]
    lines += [f"  • {f}" for f in _fonts_note(paged)]
    lines += [
        "  Text boxes name these fonts. Canva uses them when its font library has the family (all are Google Fonts);",
        "  otherwise Canva substitutes a font. The font files are in 'Fonts for Canva' next to this file — with Canva Pro",
        "  or Teams you can upload them to your Brand Kit. PowerPoint files store only regular/bold: other weights",
        "  (e.g. 500 or 850) are shown as the nearest of the two.",
        "",
        "NOT TRANSFERRED",
        "  • Animation and video playback (videos are shown as their poster frame).",
        "  • Variable-font details: exact weights other than regular/bold, width and optical-size variations.",
    ]
    if not uploaded and not design.edit_url and design.upload_error:
        lines += ["", f"UPLOAD TO CANVA FAILED: {design.upload_error}"]
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------- fonts
def copy_fonts(families: set[str], destination: Path) -> Path | None:
    from behance_studio.core.paths import FONTS_DIR
    from behance_studio.design.typography import FONTS

    if not families:
        return None
    folder = destination / "Fonts for Canva"
    folder.mkdir(parents=True, exist_ok=True)
    for fam in sorted(families):
        f = FONTS.get(fam)
        if f is None:
            continue
        for path in {f.path(), f.path(italic=True)}:
            if path.exists() and not (folder / path.name).exists():
                shutil.copy2(path, folder / path.name)
        lic = FONTS_DIR / "licenses" / f"{fam.lower().replace(' ', '')}-OFL.txt"
        if lic.exists() and not (folder / lic.name).exists():
            shutil.copy2(lic, folder / lic.name)
    atomic_write_text(folder / "README.txt",
                      "These open-source fonts (SIL Open Font License, see the licence files) are used by the exported design.\n"
                      "Canva uses fonts from its own library by name. If a font is missing in Canva, Canva Pro/Teams users can\n"
                      "upload these files under Brand Kit → Brand fonts and then select the font in the text boxes.\n")
    return folder


# ------------------------------------------------------------------- export
def _base_name(options: CanvaOptions, project, record) -> str:
    from behance_studio.export.exporter import base_name

    return base_name(options.filename_pattern, project, record)


def _build(project, presentation, options: CanvaOptions, workdir: Path, token: CancelToken):
    density = DENSITY.get(options.quality, 2.0)
    for attempt in range(3):
        if token.cancelled:
            raise OperationCancelled("Export cancelled")
        scene = build_scene(project, presentation, BuildOptions(options.mode, density, options.section_ids), workdir / f"media{attempt}")
        size = sum(Path(p).stat().st_size for p in {e.picture.path for e in scene.elements if e.picture is not None})
        if size <= SAFE_BYTES or density <= 1.0:
            return scene, density
        density = max(1.0, density * 0.6)  # stay under Canva's file size limit
        log.info("Canva export: pictures are %.0f MB; rebuilding at density %.2f", size / 1e6, density)
    return scene, density


def export_to_canva(project, version_ids: list[str], options: CanvaOptions, client=None, token: CancelToken | None = None,
                    progress: Callable[[float, str], None] = lambda f, m: None) -> CanvaReport:
    token = token or CancelToken()
    report = CanvaReport()
    if not version_ids:
        raise UserFacingError("Choose at least one proposal to export to Canva.")
    destination = Path(options.destination)
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(f"The export folder could not be created:\n{destination}", str(exc)) from exc
    manager = VersionManager(project)
    steps = len(version_ids) * 3 + (len(version_ids) if options.upload else 0) + 1
    done = 0

    def step(message: str) -> None:
        nonlocal done
        progress(min(0.99, done / steps), message)
        done += 1

    with tempfile.TemporaryDirectory(prefix="bs-canva-") as tmpname:
        tmp = Path(tmpname)
        built: list[tuple[str, list[str], object, PagedScene]] = []  # (name, ids, presentation, paged)
        scenes = []
        try:
            for vid in version_ids:
                record = manager.get(vid)
                pres = manager.load(vid).presentation
                step(f"{record.name}: building editable layers")
                scene, _density = _build(project, pres, options, tmp / vid, token)
                scenes.append((record, pres, scene))
            step("Laying out pages")
            if options.combine and len(scenes) > 1 and len({s.width for _r, _p, s in scenes}) == 1:
                paged_list = paginate_many([s for _r, _p, s in scenes], options.page_height or None)
                title = f"{project.name} — {len(scenes)} proposals"
                merged = combine(paged_list, title, [r.name for r, _p, _s in scenes])
                built.append((title, [r.id for r, _p, _s in scenes], None, merged))
                singles = list(zip(scenes, paged_list))
            else:
                if options.combine and len(scenes) > 1:
                    report.failures.append(("Combine", "The proposals have different widths, so each gets its own design."))
                singles = [((r, p, s), paginate(s, options.page_height or None)) for r, p, s in scenes]
                built = [(r.name, [r.id], p, pg) for (r, p, _s), pg in singles]
        except OperationCancelled:
            report.cancelled = True
            return report

        fonts: set[str] = set()
        for _name, _ids, _pres, paged in built:
            fonts.update(paged.scene.fonts)
        if options.include_fonts:
            try:
                report.fonts_dir = copy_fonts(fonts, destination)
            except OSError as exc:
                log.warning("Fonts for Canva not copied: %s", exc)

        for name, ids, pres, paged in built:
            if token.cancelled:
                report.cancelled = True
                break
            try:
                if len(paged.pages) > CANVA_MAX_PAGES:
                    raise ExportError(f"{name}: {len(paged.pages)} pages is more than Canva imports (100). Choose a larger page height.")
                record = manager.get(ids[0])
                base = _base_name(options, project, record) if len(ids) == 1 else safe_filename(name, fallback="Proposals")
                pptx = unique_path(destination / f"{base}.pptx")
                step(f"{name}: writing the PowerPoint file")
                section_titles = {s.index: s.title for s in paged.scene.sections}
                notes = {p.index: f"{p.label or name} — page {p.index + 1} of {len(paged.pages)} — "
                                  + ", ".join(dict.fromkeys(section_titles.get(i, "") for i in p.sections if section_titles.get(i)))
                         for p in paged.pages}
                write_pptx(paged, pptx, title=name, notes=notes)
                size = pptx.stat().st_size
                design = CanvaDesign(name, ids, pptx, pptx.with_name(f"{pptx.stem} - Canva report.txt"), pptx.with_suffix(".canva.json"),
                                     len(paged.pages), (paged.scene.width, paged.page_height), size, _counts(paged))
                if size > CANVA_MAX_BYTES:
                    design.notes.append(f"The file is {size / 1e6:.0f} MB; Canva imports PowerPoint files up to 50 MB. "
                                        "Export with 'Standard' picture quality.")
                atomic_write_json(design.scene_json, paged.to_dict())
                if options.check:
                    step(f"{name}: checking the pages against the original")
                    parts = [(pres, paged)] if pres is not None else [(p, pg) for (_r, p, _s), pg in singles]
                    checks = [_check(project, p, pg, options, pptx if pres is not None else None) for p, pg in parts]
                    conv = [c[0] for c in checks if c[0] is not None]
                    office = [c[1] for c in checks if c[1] is not None]
                    design.similarity = sum(conv) / len(conv) if conv else None
                    design.office_similarity = sum(office) / len(office) if office else None
                if options.upload and client is not None:
                    step(f"{name}: importing into Canva")
                    try:
                        imported = client.import_design(pptx, name, cancelled=lambda: token.cancelled)
                        design.edit_url = imported.edit_url
                    except OperationCancelled:
                        raise
                    except UserFacingError as exc:
                        design.upload_error = exc.message
                        report.failures.append((name, f"Upload to Canva failed: {exc.message}"))
                atomic_write_text(design.report, report_text(project, name, design, paged, bool(design.edit_url)))
                report.designs.append(design)
                for vid in ids:
                    project.record_export(ExportRecord(id=new_id(), version_id=vid, format="canva", path=str(pptx),
                                                       details={"pages": design.pages, "page_height": paged.page_height,
                                                                "edit_url": design.edit_url, "similarity": design.similarity}))
            except OperationCancelled:
                report.cancelled = True
                break
            except UserFacingError as exc:
                log.error("Canva export %s failed: %s", name, exc.detail or exc.message)
                report.failures.append((name, exc.message))
            except Exception as exc:  # noqa: BLE001 - one proposal must not stop the others
                log.exception("Canva export %s failed", name)
                report.failures.append((name, str(exc)))
    progress(1.0, report.summary())
    return report


def _check(project, presentation, paged: PagedScene, options: CanvaOptions, pptx: Path) -> tuple[float | None, float | None]:
    from behance_studio.canva.check import check_fidelity
    from behance_studio.render.browser import BrowserSession, browser_available

    if not browser_available(options.browser_path):
        return None, None
    try:
        with BrowserSession(options.browser_path) as browser:
            result = check_fidelity(project, presentation, paged, browser, pptx if options.check_with_libreoffice else None,
                                    section_ids=options.section_ids)
        return result.conversion_similarity, result.powerpoint_similarity
    except Exception as exc:  # noqa: BLE001 - the check is informative only
        log.warning("Canva conversion check failed: %s", exc)
        return None, None
