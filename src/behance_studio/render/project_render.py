"""Rendering helpers bound to a project: asset URLs, HTML files on disk."""

from __future__ import annotations

from pathlib import Path

from behance_studio.assets.derivatives import render_source, still_frame_path, video_preview_proxy
from behance_studio.core.fsutil import atomic_write_text
from behance_studio.core.logging_setup import get_logger
from behance_studio.layout.model import Block, Presentation
from behance_studio.render.html import RenderOptions, render_html

log = get_logger(__name__)

QUALITY_SCALE = {"standard": 1.0, "high": 1.6, "maximum": 2.4}


def needed_edge(block: Block, scale: float, quality_factor: float = 1.0) -> int:
    inner_w = max(1.0, block.w - 2 * block.pad)
    inner_h = max(1.0, block.h - 2 * block.pad)
    return int(max(inner_w, inner_h) * scale * quality_factor) + 1


def make_options(project, presentation: Presentation, mode: str, scale: float = 1.0, quality: str = "high", reduce_motion: bool = False, jpeg_quality: int = 90) -> RenderOptions:
    """Render options with file:// URLs to cached, right-sized media."""
    factor = QUALITY_SCALE.get(quality, 1.6)
    static = mode == "static"

    def asset_url(block: Block) -> str:
        asset = project.get_asset(block.asset_id) if block.asset_id else None
        if asset is None:
            return ""
        try:
            if asset.media_type == "video" and not static:
                proxy = video_preview_proxy(project, asset) if mode == "preview" else project.resolve_asset_path(asset)
                return (proxy or still_frame_path(project, asset)).resolve().as_uri()
            path = render_source(project, asset, needed_edge(block, scale, factor), static=static, quality=jpeg_quality)
            return path.resolve().as_uri()
        except Exception as exc:  # noqa: BLE001 - missing/corrupt asset: keep rendering
            log.warning("Asset %s unavailable for rendering: %s", asset.filename, exc)
            return ""

    def poster_url(block: Block) -> str:
        asset = project.get_asset(block.asset_id) if block.asset_id else None
        if asset is None:
            return ""
        try:
            return still_frame_path(project, asset).resolve().as_uri()
        except Exception:  # noqa: BLE001
            return ""

    return RenderOptions(mode=mode, asset_url=asset_url, poster_url=poster_url, title=presentation.title, lazy=(mode == "preview"), reduce_motion=reduce_motion)


def write_html(project, presentation: Presentation, path: Path, mode: str = "static", scale: float = 1.0, quality: str = "high", section_ids: list[str] | None = None, reduce_motion: bool = False) -> Path:
    options = make_options(project, presentation, mode, scale, quality, reduce_motion)
    options.section_ids = section_ids
    atomic_write_text(path, render_html(presentation, options))
    return path
