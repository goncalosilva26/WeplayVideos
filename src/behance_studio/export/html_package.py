"""Self-contained HTML package export.

Produces ``index.html`` plus ``assets/`` and ``fonts/`` with relative paths,
so the presentation opens in any modern browser without Behance Studio.
Animated GIFs and videos stay animated; videos are provided as broadly
compatible MP4 (H.264) or WebM.
"""

from __future__ import annotations

import html as html_lib
import re
import shutil
from pathlib import Path

from behance_studio.assets import media
from behance_studio.assets.derivatives import render_source, still_frame_path
from behance_studio.core.errors import ExportError
from behance_studio.core.fsutil import atomic_write_text, safe_filename
from behance_studio.core.logging_setup import get_logger
from behance_studio.core.paths import FONTS_DIR
from behance_studio.design.typography import FONTS
from behance_studio.layout.model import Block, Presentation
from behance_studio.render.html import RenderOptions, render_html
from behance_studio.render.project_render import needed_edge

log = get_logger(__name__)

README = """{title}
{underline}

Open index.html in a web browser (Chrome, Edge, Firefox or Safari).

Folders
  assets/  images, animations and videos used by the presentation
  fonts/   open-source (SIL OFL) fonts used by the presentation, with licences

Exported with Behance Studio. The presentation is {width}px wide and scales
down automatically on smaller screens.
"""


def export_html_package(project, presentation: Presentation, target_dir: Path, quality: str = "high", reduce_motion: bool = False) -> Path:
    target_dir.mkdir(parents=True, exist_ok=False)
    assets_dir = target_dir / "assets"
    fonts_dir = target_dir / "fonts"
    assets_dir.mkdir()
    fonts_dir.mkdir()
    copied: dict[str, str] = {}

    def copy_once(src: Path, name: str) -> str:
        key = str(src.resolve())
        if key in copied:
            return copied[key]
        dest = assets_dir / safe_filename(name)
        counter = 2
        while dest.exists():
            dest = assets_dir / f"{dest.stem}-{counter}{dest.suffix}"
            counter += 1
        shutil.copy2(src, dest)
        copied[key] = f"assets/{dest.name}"
        return copied[key]

    def asset_url(block: Block) -> str:
        asset = project.get_asset(block.asset_id) if block.asset_id else None
        if asset is None:
            return ""
        original = project.resolve_asset_path(asset)
        stem = Path(asset.filename).stem
        try:
            if asset.media_type == "video":
                ext = original.suffix.lower()
                if ext in (".mp4", ".webm", ".m4v") and asset.analysis.get("codec", "h264") in ("h264", "vp8", "vp9", "av1"):
                    return copy_once(original, f"{stem}{ext}")
                converted = project.cache_subdir("html-video") / f"{asset.id}.mp4"
                if not converted.exists():
                    media.make_video_mp4(original, converted)
                return copy_once(converted, f"{stem}.mp4")
            if asset.media_type in ("gif", "svg"):
                return copy_once(original, asset.filename)
            src = render_source(project, asset, needed_edge(block, 2.0), static=True, quality=90)
            return copy_once(src, f"{stem}-{asset.id[:6]}{src.suffix}")
        except Exception as exc:  # noqa: BLE001
            raise ExportError(f"'{asset.filename}' could not be added to the HTML package.", str(exc)) from exc

    def poster_url(block: Block) -> str:
        asset = project.get_asset(block.asset_id) if block.asset_id else None
        if asset is None:
            return ""
        frame = still_frame_path(project, asset)
        return copy_once(frame, f"{Path(asset.filename).stem}-poster{frame.suffix}")

    def font_url(path: Path) -> str:
        dest = fonts_dir / path.name
        if not dest.exists():
            shutil.copy2(path, dest)
        return f"fonts/{path.name}"

    options = RenderOptions(mode="html", asset_url=asset_url, poster_url=poster_url, font_url=font_url, title=presentation.title, lazy=True, reduce_motion=reduce_motion)
    document = render_html(presentation, options)
    atomic_write_text(target_dir / "index.html", document)
    licenses = fonts_dir / "licenses"
    licenses.mkdir(exist_ok=True)
    used_fonts = {p.name for p in fonts_dir.glob("*.ttf")}
    for fam in FONTS.values():
        if fam.regular in used_fonts:
            slug = fam.name.lower().replace(" ", "")
            lic = FONTS_DIR / "licenses" / f"{slug}-OFL.txt"
            if lic.exists():
                shutil.copy2(lic, licenses / lic.name)
    atomic_write_text(target_dir / "README.txt", README.format(title=presentation.title, underline="=" * len(presentation.title or "x"), width=presentation.width))
    problems = validate_html_package(target_dir)
    if problems:
        raise ExportError("The HTML package is incomplete.", "\n".join(problems))
    return target_dir / "index.html"


def validate_html_package(folder: Path) -> list[str]:
    index = folder / "index.html"
    if not index.exists():
        return ["index.html is missing"]
    text = index.read_text(encoding="utf-8")
    problems = []
    for ref in set(re.findall(r'(?:src|poster)="([^"]+)"', text)) | set(re.findall(r"url\('([^']+)'\)", text)):
        ref = html_lib.unescape(ref)
        if not ref or ref.startswith(("data:", "http:", "https:")):
            continue
        if ref.startswith("file:") or Path(ref).is_absolute():
            problems.append(f"absolute reference: {ref}")
            continue
        if not (folder / ref).exists():
            problems.append(f"missing file: {ref}")
    return problems
