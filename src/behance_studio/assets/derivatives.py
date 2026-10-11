"""Cached derived files: thumbnails, render derivatives, still frames, proxies.

All derived files live under ``<project>/Cache`` and can be regenerated at any
time. Writes are atomic so concurrent workers never see partial files.
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from pathlib import Path

from PIL import Image

from behance_studio.assets import media
from behance_studio.assets.formats import BROWSER_IMAGE_EXTENSIONS
from behance_studio.core.errors import AssetError
from behance_studio.core.logging_setup import get_logger
from behance_studio.projects.models import (
    MEDIA_GIF,
    MEDIA_IMAGE,
    MEDIA_SVG,
    MEDIA_VIDEO,
    AssetRecord,
)

log = get_logger(__name__)

THUMB_SIZE = 512
SIZE_BUCKETS = (480, 800, 1200, 1600, 2400, 3200, 4800, 6400, 9600)

_path_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _locks_guard:
        return _path_locks[str(path)]


def _save_atomic(img: Image.Image, path: Path, fmt: str, **kwargs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    img.save(tmp, fmt, **kwargs)
    os.replace(tmp, path)


def save_image(img: Image.Image, path: Path, quality: int = 90) -> Path:
    """Save as PNG when transparent, otherwise JPEG (``path`` suffix adjusted)."""
    if img.mode == "RGBA":
        path = path.with_suffix(".png")
        _save_atomic(img, path, "PNG", optimize=False, compress_level=6)
    else:
        path = path.with_suffix(".jpg")
        _save_atomic(img.convert("RGB"), path, "JPEG", quality=quality, optimize=True, progressive=True, subsampling=0 if quality >= 90 else 2)
    return path


def load_visual(project, asset: AssetRecord, max_size: int | None = None) -> tuple[Image.Image, bool]:
    """Decode any visual asset into an upright sRGB still image."""
    path = project.resolve_asset_path(asset)
    if not path.exists():
        raise AssetError(f"The file is missing: {asset.filename}")
    if asset.media_type == MEDIA_IMAGE:
        return media.open_image(path, max_size=max_size)
    if asset.media_type == MEDIA_SVG:
        img = media.rasterize_svg(path, max_size=max_size or 1600)
        return img, True
    if asset.media_type == MEDIA_GIF:
        return media.gif_still(path, max_size=max_size)
    if asset.media_type == MEDIA_VIDEO:
        frame_path = still_frame_path(project, asset)
        img = Image.open(frame_path)
        img.load()
        img = img.convert("RGB")
        if max_size and max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        return img, False
    raise AssetError(f"Unsupported asset type for {asset.filename}")


def still_frame_path(project, asset: AssetRecord) -> Path:
    """A representative still for videos and animated GIFs (static exports)."""
    frames_dir = project.cache_subdir("frames")
    if asset.media_type == MEDIA_VIDEO:
        target = frames_dir / f"{asset.id}.jpg"
        with _lock_for(target):
            if not target.exists():
                frame = media.video_poster(project.resolve_asset_path(asset), asset.duration)
                _save_atomic(frame, target, "JPEG", quality=92)
        return target
    if asset.media_type == MEDIA_GIF:
        existing = [p for p in (frames_dir / f"{asset.id}.png", frames_dir / f"{asset.id}.jpg") if p.exists()]
        if existing:
            return existing[0]
        target = frames_dir / f"{asset.id}"
        with _lock_for(target):
            img, _alpha = media.gif_still(project.resolve_asset_path(asset))
            return save_image(img, target, quality=92)
    return project.resolve_asset_path(asset)


def thumbnail_path(project, asset: AssetRecord) -> Path | None:
    thumbs = project.cache_dir / "thumbs"
    for ext in (".jpg", ".png"):
        candidate = thumbs / f"{asset.id}{ext}"
        if candidate.exists():
            return candidate
    return None


def ensure_thumbnail(project, asset: AssetRecord, image: Image.Image | None = None) -> Path:
    existing = thumbnail_path(project, asset)
    if existing:
        return existing
    target = project.cache_subdir("thumbs") / asset.id
    with _lock_for(target):
        existing = thumbnail_path(project, asset)
        if existing:
            return existing
        if image is None:
            image, _alpha = load_visual(project, asset, max_size=THUMB_SIZE)
        thumb = image.copy()
        thumb.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
        return save_image(thumb, target, quality=86)


def _bucket(size: int) -> int:
    for bucket in SIZE_BUCKETS:
        if size <= bucket:
            return bucket
    return SIZE_BUCKETS[-1]


def render_source(
    project,
    asset: AssetRecord,
    needed_long_edge: int,
    static: bool,
    quality: int = 90,
) -> Path:
    """Return a file that browsers render faithfully for this asset.

    * SVG is used as-is (vector, crisp at any scale).
    * Animated GIF/video use the original (or a preview proxy) when motion is
      allowed and a representative still frame for static exports.
    * Raster images use the original when it is browser-safe and not much
      larger than needed; otherwise an sRGB derivative of a bucketed size.
    """
    path = project.resolve_asset_path(asset)
    if asset.media_type == MEDIA_SVG:
        return path
    if asset.media_type == MEDIA_GIF:
        if static or not asset.animated:
            return still_frame_path(project, asset) if asset.animated else path
        return path
    if asset.media_type == MEDIA_VIDEO:
        return still_frame_path(project, asset)
    long_edge = max(asset.width, asset.height)
    target_edge = min(long_edge, _bucket(max(64, int(needed_long_edge))))
    browser_safe = (
        path.suffix.lower() in BROWSER_IMAGE_EXTENSIONS
        and (asset.analysis or {}).get("browser_safe", False)
    )
    if browser_safe and long_edge <= target_edge * 1.15:
        return path
    derived = project.cache_subdir("derived")
    stem = f"{asset.id}_{target_edge}_q{quality}"
    for ext in (".jpg", ".png"):
        candidate = derived / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    target = derived / stem
    with _lock_for(target):
        for ext in (".jpg", ".png"):
            candidate = derived / f"{stem}{ext}"
            if candidate.exists():
                return candidate
        img, _alpha = media.open_image(path, max_size=target_edge)
        return save_image(img, target, quality=quality)


def video_preview_proxy(project, asset: AssetRecord) -> Path | None:
    """WebM proxy for in-app playback; None if it cannot be produced."""
    if asset.media_type != MEDIA_VIDEO:
        return None
    target = project.cache_subdir("proxies") / f"{asset.id}.webm"
    if target.exists():
        return target
    source = project.resolve_asset_path(asset)
    if source.suffix.lower() == ".webm":
        return source
    with _lock_for(target):
        if target.exists():
            return target
        try:
            return media.make_video_proxy(source, target)
        except AssetError as exc:
            log.warning("Video proxy failed for %s: %s", asset.filename, exc.detail or exc)
            return None
