"""Fidelity check: exported pages against the original presentation.

Three renderings can be compared page by page:

* **reference** — the original presentation rendered by Chromium (the same
  renderer as previews and exports), cut into the export's pages;
* **scene** — the exported pages drawn from the scene with the properties the
  PowerPoint file actually stores (e.g. bold instead of semibold): measures
  what the conversion itself changes;
* **PowerPoint** — the .pptx file rendered by LibreOffice (when installed):
  an independent program reading the actual file.

Canva's own rendering cannot be run locally; these checks measure the file
Canva receives, not Canva's import.
"""

from __future__ import annotations

import html
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from behance_studio.canva.model import Element, Gradient, PagedScene, Solid
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class PageDiff:
    page: int
    mean_diff: float  # mean absolute difference, 0..1
    changed: float  # share of pixels that differ visibly (after a light blur), 0..1

    @property
    def similarity(self) -> float:
        return 1.0 - self.changed


def compare(a: Image.Image, b: Image.Image, page: int = 0) -> PageDiff:
    """Visual difference that tolerates anti-aliasing and sub-pixel shifts."""
    if a.size != b.size:
        b = b.resize(a.size, Image.Resampling.LANCZOS)
    fa = np.asarray(a.convert("RGB"), dtype=np.float32) / 255.0
    fb = np.asarray(b.convert("RGB"), dtype=np.float32) / 255.0
    mean = float(np.abs(fa - fb).mean())
    small = (max(1, a.width // 2), max(1, a.height // 2))
    ga = np.asarray(a.convert("L").resize(small, Image.Resampling.BOX).filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32) / 255.0
    gb = np.asarray(b.convert("L").resize(small, Image.Resampling.BOX).filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32) / 255.0
    changed = float((np.abs(ga - gb) > 0.12).mean())
    return PageDiff(page, mean, changed)


# ---------------------------------------------------------------- reference
def reference_pages(project, presentation, paged: PagedScene, browser, tmp: Path, section_ids: list[str] | None = None) -> list[Image.Image]:
    """The original presentation (Chromium) cut into the export's pages."""
    from behance_studio.render.browser import BrowserSession
    from behance_studio.render.project_render import write_html

    html_path = write_html(project, presentation, tmp / "reference.html", mode="static", scale=1.0, quality="high", section_ids=section_ids)
    page = browser.open(html_path, presentation.width, scale=1.0)
    out = []
    try:
        for p in paged.pages:
            shot = tmp / f"ref-{p.index}.png"
            BrowserSession.capture(page, p.y0, p.y1 - p.y0, presentation.width, 1.0, shot)
            with Image.open(shot) as img:
                canvas = Image.new("RGB", (paged.scene.width, paged.page_height), _filler_color(p))
                canvas.paste(img.convert("RGB"), (0, 0))
            out.append(canvas)
    finally:
        BrowserSession.close_page(page)
    return out


def _filler_color(page) -> str:
    for e in page.elements:
        if e.role == "filler" and isinstance(e.fill, Solid):
            return e.fill.color
    return "#FFFFFF"


# --------------------------------------------------------------- scene HTML
def _rgba(color: str, alpha: float) -> str:
    c = color.lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return f"rgba({r},{g},{b},{max(0.0, min(1.0, alpha)):.4f})"


def _fill_css(fill, opacity: float = 1.0) -> str:
    if fill is None:
        return "transparent"
    if isinstance(fill, Solid):
        return _rgba(fill.color, fill.alpha * opacity)
    assert isinstance(fill, Gradient)
    stops = ", ".join(f"{_rgba(s.color, s.alpha * opacity)} {s.pos * 100:.3f}%" for s in fill.stops)
    if fill.kind == "linear":
        return f"linear-gradient({fill.angle:.3f}deg, {stops})"
    return f"radial-gradient(ellipse {fill.rx * 100:.2f}% {fill.ry * 100:.2f}% at {fill.cx * 100:.2f}% {fill.cy * 100:.2f}%, {stops})"


def _radius_css(el: Element) -> str:
    if el.kind == "ellipse" or el.geometry == "ellipse":
        return "50%"
    r = min(el.radius, el.w / 2, el.h / 2)
    if el.geometry == "roundRect":
        return f"{r:.2f}px"
    if el.geometry == "round2SameRect":
        return f"{r:.2f}px {r:.2f}px 0 0"
    return "0"


def _shadow_css(el: Element, image: bool) -> tuple[str, str]:
    s = el.shadow
    if s is None:
        return "", ""
    color = _rgba(s.color, s.alpha * el.opacity)
    if s.kind == "glow":
        return f"box-shadow:0 0 {s.blur:.1f}px {s.spread:.1f}px {color};", ""
    if image and not s.spread:  # PowerPoint picture shadows follow transparency
        return "", f"filter:drop-shadow({s.dx:.1f}px {s.dy:.1f}px {s.blur / 2:.1f}px {color});"
    return f"box-shadow:{s.dx:.1f}px {s.dy:.1f}px {s.blur:.1f}px {s.spread:.1f}px {color};", ""


def _element_html(el: Element) -> str:
    base = f"position:absolute;left:{el.x:.2f}px;top:{el.y:.2f}px;width:{el.w:.2f}px;height:{el.h:.2f}px;"
    if el.rotation:
        base += f"transform:rotate({el.rotation:.3f}deg);transform-origin:50% 50%;"
    if el.kind == "text" and el.text is not None:
        from behance_studio.canva.pptx_out import paragraphs

        t = el.text
        style = (f"font-family:'{t.family}';font-size:{t.size:.2f}px;font-weight:{700 if t.weight >= 600 else 400};"
                 f"font-style:{'italic' if t.italic else 'normal'};line-height:{t.line_px:.2f}px;letter-spacing:{t.tracking:.4f}em;"
                 f"text-align:{t.align};white-space:pre;color:{_rgba(t.color, 0 if t.stroke else t.alpha)};")
        if t.stroke:
            style += f"-webkit-text-stroke:{t.stroke_px:.2f}px {_rgba(t.stroke, t.alpha)};"
        if t.natural:
            style = style.replace("white-space:pre;", "white-space:normal;")
            paras = "".join(f'<div style="margin-top:{gap:.2f}px">{html.escape(" ".join(lines))}</div>' for lines, gap in paragraphs(t))
        else:
            paras = "".join(f'<div style="margin-top:{gap:.2f}px">{"<br>".join(html.escape(x) for x in lines)}</div>' for lines, gap in paragraphs(t))
        return f'<div style="{base}{style}">{paras}</div>'
    box, drop = _shadow_css(el, el.kind == "image")
    border = ""
    if el.line is not None:  # PowerPoint outlines are centred on the edge
        k = el.line.width / 2
        base = (f"position:absolute;left:{el.x - k:.2f}px;top:{el.y - k:.2f}px;width:{el.w + 2 * k:.2f}px;height:{el.h + 2 * k:.2f}px;"
                + (f"transform:rotate({el.rotation:.3f}deg);transform-origin:50% 50%;" if el.rotation else ""))
        border = f"border:{el.line.width:.2f}px solid {_rgba(el.line.color, el.line.alpha * el.opacity)};"
    radius = f"border-radius:{_radius_css(el)};"
    if el.kind == "image" and el.picture is not None:
        l, t, r, b = el.picture.crop
        iw, ih = el.w / max(1e-6, 1 - l - r), el.h / max(1e-6, 1 - t - b)
        src = Path(el.picture.path).resolve().as_uri()
        img = (f'<img src="{src}" style="position:absolute;left:{-l * iw:.2f}px;top:{-t * ih:.2f}px;width:{iw:.2f}px;height:{ih:.2f}px;'
               f'max-width:none;opacity:{el.opacity:.4f}">')
        return f'<div style="{base}{drop}"><div style="position:absolute;inset:0;overflow:hidden;{radius}{border}{box}">{img}</div></div>'
    return f'<div style="{base}{radius}{border}{box}background:{_fill_css(el.fill, el.opacity)};"></div>'


def scene_html(paged: PagedScene) -> str:
    """The exported pages drawn with exactly the stored properties."""
    from behance_studio.render.html import font_face_css

    families = sorted(paged.scene.fonts)
    pages = []
    for p in paged.pages:
        inner = "".join(_element_html(e) for e in p.elements if e.w > 0.01 and e.h > 0.01)
        pages.append(f'<section class="pg" style="width:{paged.scene.width}px;height:{paged.page_height}px">{inner}</section>')
    css = font_face_css(families, lambda path: path.resolve().as_uri())
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{css}*{{margin:0;padding:0;box-sizing:border-box}}"
            f".pg{{position:relative;overflow:hidden;background:#fff}}body{{background:#fff;-webkit-font-smoothing:antialiased}}"
            f"</style></head><body>{''.join(pages)}</body></html>")


def render_scene_pages(paged: PagedScene, browser, tmp: Path) -> list[Image.Image]:
    from behance_studio.render.browser import BrowserSession

    path = tmp / "scene.html"
    path.write_text(scene_html(paged), encoding="utf-8")
    page = browser.open(path, paged.scene.width, scale=1.0)
    out = []
    try:
        for p in paged.pages:
            shot = tmp / f"scene-{p.index}.png"
            BrowserSession.capture(page, p.index * paged.page_height, paged.page_height, paged.scene.width, 1.0, shot)
            with Image.open(shot) as img:
                out.append(img.convert("RGB"))
    finally:
        BrowserSession.close_page(page)
    return out


# --------------------------------------------------------------- LibreOffice
def libreoffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in (r"C:\Program Files\LibreOffice\program\soffice.exe", r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
        if Path(candidate).exists():
            return candidate
    return None


def _fontconfig(tmp: Path) -> Path:
    from behance_studio.core.paths import FONTS_DIR

    conf = tmp / "fonts.conf"
    conf.write_text(
        '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
        f"<include ignore_missing=\"yes\">/etc/fonts/fonts.conf</include><dir>{html.escape(str(FONTS_DIR))}</dir>"
        f"<cachedir>{html.escape(str(tmp / 'fc-cache'))}</cachedir></fontconfig>", encoding="utf-8")
    return conf


def render_pptx_pages(pptx: Path, tmp: Path, timeout: float = 240.0) -> list[Image.Image] | None:
    """Render a .pptx with LibreOffice (PDF) and rasterise it at 96 dpi."""
    soffice = libreoffice()
    pdftoppm = shutil.which("pdftoppm")
    if soffice is None or pdftoppm is None:
        return None
    work = Path(tempfile.mkdtemp(dir=tmp, prefix="lo-"))
    env = dict(os.environ)
    env["FONTCONFIG_FILE"] = str(_fontconfig(work))
    env["HOME"] = str(work)
    profile = (work / "profile").as_uri()
    cmd = [soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(work), str(pptx)]
    subprocess.run(cmd, env=env, timeout=timeout, capture_output=True, check=False)
    pdf = work / (Path(pptx).stem + ".pdf")
    if not pdf.exists():
        log.warning("LibreOffice did not produce a PDF for %s", pptx)
        return None
    subprocess.run([pdftoppm, "-r", "96", "-png", str(pdf), str(work / "page")], timeout=timeout, capture_output=True, check=False)
    pages = sorted(work.glob("page*.png"), key=lambda p: int(p.stem.split("-")[-1]))
    out = []
    for p in pages:
        with Image.open(p) as img:
            out.append(img.convert("RGB"))
    return out


@dataclass
class FidelityResult:
    conversion: list[PageDiff]  # scene vs original
    powerpoint: list[PageDiff] | None = None  # LibreOffice rendering of the .pptx vs original

    @staticmethod
    def _avg(diffs: list[PageDiff] | None) -> float | None:
        if not diffs:
            return None
        return sum(d.similarity for d in diffs) / len(diffs)

    @property
    def conversion_similarity(self) -> float | None:
        return self._avg(self.conversion)

    @property
    def powerpoint_similarity(self) -> float | None:
        return self._avg(self.powerpoint)


def check_fidelity(project, presentation, paged: PagedScene, browser, pptx: Path | None = None, section_ids=None, keep: Path | None = None) -> FidelityResult:
    with tempfile.TemporaryDirectory(prefix="bs-canva-check-") as name:
        tmp = Path(name)
        ref = reference_pages(project, presentation, paged, browser, tmp, section_ids)
        scene = render_scene_pages(paged, browser, tmp)
        conversion = [compare(a, b, i) for i, (a, b) in enumerate(zip(ref, scene))]
        office = None
        if keep is not None:
            keep.mkdir(parents=True, exist_ok=True)
        if pptx is not None:
            rendered = render_pptx_pages(pptx, tmp)
            if rendered:
                office = [compare(a, b, i) for i, (a, b) in enumerate(zip(ref, rendered))]
                if keep is not None:
                    for i, img in enumerate(rendered):
                        img.save(keep / f"pptx-{i + 1:02d}.png")
        if keep is not None:
            for i, (a, b) in enumerate(zip(ref, scene)):
                a.save(keep / f"reference-{i + 1:02d}.png")
                b.save(keep / f"scene-{i + 1:02d}.png")
        return FidelityResult(conversion, office)
