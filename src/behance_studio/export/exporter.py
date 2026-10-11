"""Export pipeline: PDF (continuous / A4), JPG, PNG, WebP, TIFF, HTML, ZIP, text.

Every export renders through Chromium from the same HTML used by the
preview, so the output matches what the user saw. Files are never
overwritten silently, names are made unique, and every written file is
re-opened and validated before being reported as successful.
"""

from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image, ImageCms
from pypdf import PdfReader, PdfWriter

from behance_studio import APP_NAME, __version__
from behance_studio.core.errors import ExportError, OperationCancelled, UserFacingError
from behance_studio.core.fsutil import atomic_write_text, safe_filename, unique_path
from behance_studio.core.logging_setup import get_logger
from behance_studio.core.tasks import CancelToken
from behance_studio.export.html_package import export_html_package
from behance_studio.export.paginate import Page, paginate_fixed, section_ranges, vertical_ranges
from behance_studio.layout.families import family_info
from behance_studio.layout.model import Presentation
from behance_studio.projects.models import ExportRecord, new_id
from behance_studio.projects.versions import VersionManager
from behance_studio.render.browser import BrowserSession
from behance_studio.render.html import render_pages_html
from behance_studio.render.project_render import make_options, write_html

log = get_logger(__name__)

FORMATS = {
    "pdf": "PDF — continuous presentation",
    "pdf_a4": "PDF — A4 pages",
    "jpg": "JPG images",
    "png": "PNG images",
    "webp": "WebP images",
    "tiff": "TIFF images",
    "html": "HTML package",
    "zip": "ZIP package",
    "text": "Presentation text (Markdown)",
}
RASTER = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "tiff": "TIFF"}
# Practical single-image height limits (output pixels).
MAX_IMAGE_HEIGHT = {"jpg": 65000, "png": 60000, "webp": 16383, "tiff": 60000}
CONTINUOUS_COMFORT = 30000  # above this, "auto" splits into segments
PDF_MAX_PAGE_PX = 18000  # Chromium/PDF page-size safety limit (CSS px)
A4_W_PX, A4_H_PX = 793.7008, 1122.5197
SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


@dataclass
class ExportOptions:
    formats: list[str]
    destination: Path
    width: int = 1400
    quality: str = "high"  # standard | high | maximum
    long_image_mode: str = "auto"  # auto | continuous | segments | sections
    segment_height: int = 8000  # output px
    jpeg_quality: int = 92
    filename_pattern: str = "{project} - {proposal}"
    section_ids: list[str] | None = None
    a4_margins: bool = False
    browser_path: str = ""
    reduce_motion: bool = False


@dataclass
class ExportOutput:
    format: str
    paths: list[Path]
    ok: bool = True
    message: str = ""


@dataclass
class ExportReport:
    outputs: list[tuple[str, ExportOutput]] = field(default_factory=list)  # (version name, output)
    failures: list[tuple[str, str, str]] = field(default_factory=list)  # (version, format, message)
    cancelled: bool = False

    @property
    def files(self) -> list[Path]:
        return [p for _, o in self.outputs if o.ok for p in o.paths]

    def summary(self) -> str:
        n = len(self.files)
        text = f"{n} file(s) exported"
        if self.failures:
            text += f", {len(self.failures)} failure(s)"
        if self.cancelled:
            text += " (cancelled)"
        return text


def base_name(pattern: str, project, record) -> str:
    tokens = {
        "project": project.name,
        "proposal": record.name,
        "family": family_info(record.family).name,
        "number": f"{record.number:03d}",
        "date": datetime.now().strftime("%Y-%m-%d"),
    }
    try:
        text = pattern.format(**tokens)
    except (KeyError, IndexError, ValueError):
        text = f"{project.name} - {record.name}"
    return safe_filename(text, fallback="Presentation")


def _subset(presentation: Presentation, section_ids: list[str] | None) -> list:
    if not section_ids:
        return list(presentation.sections)
    wanted = set(section_ids)
    sections = [s for s in presentation.sections if s.id in wanted or s.plan_id in wanted]
    if not sections:
        raise UserFacingError("None of the selected sections exist in this proposal.")
    return sections


# --------------------------------------------------------------------- PDF
def _write_pages_pdf(project, presentation: Presentation, pages: list[Page], out: Path, options: ExportOptions, browser: BrowserSession, tmp: Path, margin: float = 0.0) -> Path:
    render_opts = make_options(project, presentation, "static", scale=1.0, quality=options.quality, jpeg_quality=options.jpeg_quality)
    html_path = tmp / f"pdf-{new_id()}.html"
    atomic_write_text(html_path, render_pages_html(presentation, pages, render_opts, margin=margin))
    page = browser.open(html_path, int(max(p.width for p in pages)), scale=1.0)
    try:
        pdf_tmp = tmp / f"{new_id()}.pdf"
        page.pdf(path=str(pdf_tmp), print_background=True, prefer_css_page_size=True)
    finally:
        browser.close_page(page)
    reader = PdfReader(str(pdf_tmp))
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    writer.add_metadata({"/Title": presentation.title, "/Creator": f"{APP_NAME} {__version__}", "/Producer": f"{APP_NAME} (Chromium)"})
    final_tmp = out.with_name(f".{out.name}.partial")
    with open(final_tmp, "wb") as fh:
        writer.write(fh)
    os.replace(final_tmp, out)
    try:
        _validate_pdf(out, len(pages))
    except ExportError:
        out.unlink(missing_ok=True)  # never leave an invalid export behind
        raise
    return out


def _validate_pdf(path: Path, expected_pages: int) -> None:
    try:
        reader = PdfReader(str(path))
        n = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise ExportError("The PDF file could not be verified.", str(exc)) from exc
    if n != expected_pages or path.stat().st_size < 1000:
        raise ExportError("The PDF file is incomplete.", f"pages={n} expected={expected_pages}")


def export_pdf(project, presentation, sections, out: Path, options: ExportOptions, browser, tmp: Path) -> ExportOutput:
    ranges = vertical_ranges(presentation, sections, PDF_MAX_PAGE_PX)
    pages = [Page(r, presentation.width, sum(s.height for s in r), r[-1].section.background) for r in ranges]
    path = _write_pages_pdf(project, presentation, pages, out, options, browser, tmp)
    return ExportOutput("pdf", [path], True, f"{len(pages)} page(s)")


def export_pdf_a4(project, presentation, sections, out: Path, options: ExportOptions, browser, tmp: Path) -> ExportOutput:
    margin = 45.35 if options.a4_margins else 0.0  # 12 mm
    pages = paginate_fixed(presentation, sections, A4_W_PX, A4_H_PX, margin=margin)
    if options.a4_margins:
        for p in pages:
            p.background = "#FFFFFF"
    path = _write_pages_pdf(project, presentation, pages, out, options, browser, tmp, margin=margin)
    return ExportOutput("pdf_a4", [path], True, f"{len(pages)} A4 page(s)")


# ------------------------------------------------------------------ raster
def _save_raster(img: Image.Image, path: Path, fmt: str, options: ExportOptions) -> Path:
    img = img.convert("RGB")
    tmp = path.with_name(f".{path.name}.partial")
    if fmt == "jpg":
        q = max(60, min(100, options.jpeg_quality))
        img.save(tmp, "JPEG", quality=q, optimize=True, progressive=True, subsampling=0 if q >= 90 else 2, icc_profile=SRGB_ICC, dpi=(144, 144))
    elif fmt == "png":
        img.save(tmp, "PNG", compress_level=6, icc_profile=SRGB_ICC, dpi=(144, 144))
    elif fmt == "webp":
        q = max(60, min(100, options.jpeg_quality))
        img.save(tmp, "WEBP", quality=q, method=4, icc_profile=SRGB_ICC, lossless=q >= 100)
    elif fmt == "tiff":
        img.save(tmp, "TIFF", compression="tiff_lzw", icc_profile=SRGB_ICC, dpi=(144, 144))
    os.replace(tmp, path)
    try:
        with Image.open(path) as check:
            check.verify()
        with Image.open(path) as check:
            if check.size != img.size:
                raise ExportError(f"The image {path.name} was not written correctly.")
    except ExportError:
        path.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        path.unlink(missing_ok=True)
        raise ExportError(f"The image {path.name} could not be verified.", str(exc)) from exc
    return path


def export_raster(project, presentation, sections, fmt: str, base: Path, options: ExportOptions, browser, tmp: Path, html_path: Path, page) -> ExportOutput:
    scale = options.width / presentation.width
    limit_px = MAX_IMAGE_HEIGHT[fmt]
    total_css = sum(s.height for s in sections)
    mode = options.long_image_mode
    if mode == "auto":
        mode = "continuous" if total_css * scale <= min(limit_px, CONTINUOUS_COMFORT) else "segments"
    if mode == "continuous" and total_css * scale > limit_px:
        mode = "segments"
    if mode == "continuous":
        ranges = [[sl for r in vertical_ranges(presentation, sections, total_css + 1) for sl in r]]
    elif mode == "sections":
        ranges = section_ranges(sections, min(limit_px, 20000) / scale)
    else:
        seg = max(1000, min(options.segment_height, limit_px)) / scale
        ranges = vertical_ranges(presentation, sections, seg)
    offsets = {}
    y = 0.0
    for s in presentation.sections:
        offsets[s.id] = y
        y += s.height
    paths: list[Path] = []
    ext = "jpg" if fmt == "jpg" else fmt
    for index, rng in enumerate(ranges, start=1):
        # Merge contiguous slices into page spans and snap them to device
        # pixels, so stitched heights are exact (no per-section rounding).
        spans: list[list[float]] = []
        for sl in rng:
            start, end = offsets[sl.section.id] + sl.y0, offsets[sl.section.id] + sl.y1
            if spans and abs(spans[-1][1] - start) < 0.01:
                spans[-1][1] = end
            else:
                spans.append([start, end])
        parts = []
        for start, end in spans:
            px0, px1 = round(start * scale), round(end * scale)
            if px1 <= px0:
                continue
            png = tmp / f"cap-{new_id()}.png"
            BrowserSession.capture(page, px0 / scale, (px1 - px0) / scale, presentation.width, scale, png)
            parts.append(png)
        images = [Image.open(p) for p in parts]
        width = images[0].width
        height = sum(i.height for i in images)
        canvas = Image.new("RGB", (width, height))
        cy = 0
        for im in images:
            canvas.paste(im.convert("RGB"), (0, cy))
            cy += im.height
            im.close()
        for p in parts:
            p.unlink(missing_ok=True)
        name = f"{base.name}.{ext}" if len(ranges) == 1 else f"{base.name}_{index:02d}.{ext}"
        path = unique_path(base.parent / name)
        paths.append(_save_raster(canvas, path, fmt, options))
        canvas.close()
    return ExportOutput(fmt, paths, True, f"{len(paths)} image(s), {options.width}px wide")


# ------------------------------------------------------------------- text
def presentation_text(presentation: Presentation) -> str:
    lines = [f"# {presentation.title}", ""]
    current = None
    for section, role, text in presentation.all_text():
        if section != current:
            lines += ["", f"## {section}", ""]
            current = section
        lines.append(text if role not in ("eyebrow", "label", "caption") else f"_{text}_")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# ------------------------------------------------------------------ driver
def export_versions(
    project,
    version_ids: list[str],
    options: ExportOptions,
    token: CancelToken | None = None,
    progress: Callable[[float, str], None] = lambda f, m: None,
) -> ExportReport:
    token = token or CancelToken()
    report = ExportReport()
    manager = VersionManager(project)
    order = list(FORMATS)
    formats = sorted({f for f in options.formats if f in FORMATS}, key=order.index)  # ZIP last
    if not formats:
        raise UserFacingError("Choose at least one export format.")
    if not version_ids:
        raise UserFacingError("Choose at least one proposal to export.")
    destination = Path(options.destination)
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(f"The export folder could not be created:\n{destination}", str(exc)) from exc
    steps = len(version_ids) * len(formats)
    done = 0
    needs_browser = any(f in formats for f in ("pdf", "pdf_a4", "jpg", "png", "webp", "tiff")) or ("zip" in formats and len(formats) == 1)
    browser_cm = BrowserSession(options.browser_path) if needs_browser else None
    try:
        browser = browser_cm.__enter__() if browser_cm else None
        for vid in version_ids:
            record = manager.get(vid)
            proposal = manager.load(vid)
            pres = proposal.presentation
            sections = _subset(pres, options.section_ids)
            base = destination / base_name(options.filename_pattern, project, record)
            produced: list[ExportOutput] = []
            with tempfile.TemporaryDirectory(prefix="bs-export-") as tmpname:
                tmp = Path(tmpname)
                raster_page = None
                html_path = None
                zip_only = formats == ["zip"]
                work_formats = ["pdf", "html", "text"] + ["zip"] if zip_only else formats
                for fmt in work_formats:
                    if token.cancelled:
                        report.cancelled = True
                        raise OperationCancelled("Export cancelled")
                    progress(done / max(1, steps), f"{record.name}: {FORMATS[fmt]}")
                    try:
                        target_dir = tmp / "zip-content" if (zip_only and fmt != "zip") else destination
                        target_dir.mkdir(parents=True, exist_ok=True)
                        tbase = target_dir / base.name
                        if fmt == "pdf":
                            out = export_pdf(project, pres, sections, unique_path(tbase.with_name(tbase.name + ".pdf")), options, browser, tmp)
                        elif fmt == "pdf_a4":
                            out = export_pdf_a4(project, pres, sections, unique_path(tbase.with_name(tbase.name + " (A4).pdf")), options, browser, tmp)
                        elif fmt in RASTER:
                            if raster_page is None:
                                html_path = write_html(project, pres, tmp / "raster.html", mode="static", scale=options.width / pres.width, quality=options.quality, section_ids=None)
                                raster_page = browser.open(html_path, pres.width, scale=options.width / pres.width)
                            out = export_raster(project, pres, sections, fmt, tbase, options, browser, tmp, html_path, raster_page)
                        elif fmt == "html":
                            sub = pres if not options.section_ids else Presentation(pres.family, pres.seed, pres.width, sections, pres.title, pres.language, pres.page_background, pres.fonts, pres.variant, pres.id)
                            folder = unique_path(target_dir / f"{base.name} - HTML")
                            index = export_html_package(project, sub, folder, quality=options.quality, reduce_motion=options.reduce_motion)
                            out = ExportOutput("html", [index.parent], True, "HTML package")
                        elif fmt == "text":
                            path = unique_path(tbase.with_name(tbase.name + " - text.md"))
                            atomic_write_text(path, presentation_text(pres))
                            out = ExportOutput("text", [path], True, "Text")
                        elif fmt == "zip":
                            out = _zip_outputs(produced, unique_path(destination / f"{base.name}.zip"), base.name)
                        else:  # pragma: no cover
                            continue
                        if not (zip_only and fmt != "zip"):
                            report.outputs.append((record.name, out))
                            project.record_export(ExportRecord(id=new_id(), version_id=vid, format=fmt, path=str(out.paths[0]), details={"files": [str(p) for p in out.paths]}))
                        produced.append(out)
                    except OperationCancelled:
                        raise
                    except UserFacingError as exc:
                        log.error("Export %s failed: %s", fmt, exc.detail or exc.message)
                        report.failures.append((record.name, fmt, exc.message))
                    except Exception as exc:  # noqa: BLE001 - report partial failures
                        log.exception("Export %s failed", fmt)
                        report.failures.append((record.name, fmt, str(exc)))
                    done += 1
                if raster_page is not None:
                    BrowserSession.close_page(raster_page)
        progress(1.0, report.summary())
    except OperationCancelled:
        report.cancelled = True
    finally:
        if browser_cm is not None:
            try:
                browser_cm.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
    return report


def _zip_outputs(outputs: list[ExportOutput], zip_path: Path, root: str) -> ExportOutput:
    folders = {"pdf": "PDF", "pdf_a4": "PDF", "jpg": "Images", "png": "Images", "webp": "Images", "tiff": "Images", "html": "HTML", "text": "Text"}
    tmp = zip_path.with_name(f".{zip_path.name}.partial")
    count = 0
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for out in outputs:
            if not out.ok or out.format == "zip":
                continue
            sub = folders.get(out.format, "Files")
            for path in out.paths:
                if path.is_dir():
                    for file in sorted(path.rglob("*")):
                        if file.is_file():
                            zf.write(file, f"{root}/{sub}/{path.name}/{file.relative_to(path).as_posix()}")
                            count += 1
                else:
                    zf.write(path, f"{root}/{sub}/{path.name}")
                    count += 1
    os.replace(tmp, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise ExportError(f"The ZIP file is damaged ({bad}).")
    if count == 0:
        zip_path.unlink(missing_ok=True)
        raise ExportError("There was nothing to put in the ZIP package.")
    return ExportOutput("zip", [zip_path], True, f"{count} file(s)")


def open_folder(path: Path) -> None:
    import subprocess
    import sys

    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:  # noqa: BLE001
        log.warning("Could not open folder %s", path)


__all__ = ["ExportOptions", "ExportReport", "FORMATS", "export_versions", "presentation_text", "open_folder"]
