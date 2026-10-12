"""Proposal preview images: a cover thumbnail and a full-length strip.

Rendered with Chromium when available (identical to exports) — the same pass
also runs the in-browser layout check (text overflow, broken images). Falls
back to the Pillow renderer otherwise.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

from PIL import Image

from behance_studio.core.errors import RenderError
from behance_studio.core.logging_setup import get_logger
from behance_studio.core.tasks import CancelToken
from behance_studio.layout.model import Presentation
from behance_studio.render.browser import BrowserSession, browser_available
from behance_studio.render.pillow_render import PillowRenderer
from behance_studio.render.project_render import write_html

log = get_logger(__name__)

THUMB_W, THUMB_H = 720, 540
STRIP_W = 360
CAPTURE_SCALE = 0.5


def _save_thumbs(full: Image.Image, thumb_path: Path, strip_path: Path) -> None:
    full = full.convert("RGB")
    w = full.width
    cover_h = int(w * THUMB_H / THUMB_W)
    cover = full.crop((0, 0, w, min(full.height, cover_h)))
    if cover.height < cover_h:
        padded = Image.new("RGB", (w, cover_h), full.getpixel((0, max(0, full.height - 1))))
        padded.paste(cover, (0, 0))
        cover = padded
    cover = cover.resize((THUMB_W, THUMB_H), Image.Resampling.LANCZOS)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    cover.save(thumb_path, "JPEG", quality=86, optimize=True)
    strip_h = max(1, int(full.height * STRIP_W / w))
    strip = full.resize((STRIP_W, strip_h), Image.Resampling.LANCZOS)
    strip.save(strip_path, "JPEG", quality=82, optimize=True)


def render_previews(
    project,
    jobs: list[tuple[Presentation, Path, Path]],
    token: CancelToken | None = None,
    progress: Callable[[float, str], None] = lambda f, m: None,
    browser_path: str = "",
    captures: dict[int, Path] | None = None,
) -> dict[int, list[dict]]:
    """Render thumbnails for (presentation, thumb_path, strip_path) jobs.

    Returns browser layout issues per job index (empty when the Pillow
    fallback was used). ``captures`` maps job indexes to paths where the
    full-length capture is also saved (JPEG), e.g. for the AI critique.
    """
    captures = captures or {}
    issues: dict[int, list[dict]] = {}
    if not jobs:
        return issues
    use_browser = browser_available(browser_path)
    if use_browser:
        try:
            with BrowserSession(browser_path) as browser, tempfile.TemporaryDirectory(prefix="bs-preview-") as tmp:
                for i, (pres, thumb, strip) in enumerate(jobs):
                    if token:
                        token.raise_if_cancelled()
                    html = write_html(project, pres, Path(tmp) / f"p{i}.html", mode="static", scale=CAPTURE_SCALE, quality="standard")
                    page = browser.open(html, pres.width, scale=CAPTURE_SCALE)
                    try:
                        issues[i] = browser.layout_issues(page)
                        png = Path(tmp) / f"p{i}.png"
                        browser.capture(page, 0, pres.height, pres.width, CAPTURE_SCALE, png)
                        with Image.open(png) as full:
                            _save_thumbs(full, thumb, strip)
                            if i in captures:
                                full.convert("RGB").save(captures[i], "JPEG", quality=85)
                            try:
                                from behance_studio.qa.rendered import inspect_rendered

                                issues[i] = list(issues[i]) + inspect_rendered(pres, full, CAPTURE_SCALE)
                            except Exception as exc:  # noqa: BLE001 - QA must never block previews
                                log.warning("Rendered QA failed: %s", exc)
                    finally:
                        browser.close_page(page)
                    progress((i + 1) / len(jobs), f"Rendered preview {i + 1} of {len(jobs)}")
            return issues
        except RenderError as exc:
            log.warning("Browser previews unavailable (%s); using fallback renderer", exc.detail or exc.message)
    renderer = PillowRenderer(project, scale=0.35)
    for i, (pres, thumb, strip) in enumerate(jobs):
        if token:
            token.raise_if_cancelled()
        full = renderer.presentation(pres)
        _save_thumbs(full, thumb, strip)
        if i in captures:
            full.convert("RGB").save(captures[i], "JPEG", quality=85)
        issues[i] = []
        progress((i + 1) / len(jobs), f"Rendered preview {i + 1} of {len(jobs)}")
    return issues
