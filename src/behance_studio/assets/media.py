"""Low-level media decoding: images, SVG, GIF and video.

Originals are only ever *read*. All decoded images are normalised to sRGB,
upright (EXIF orientation applied) RGB/RGBA so that analysis, thumbnails and
render derivatives agree with what browsers display.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageCms, ImageOps, ImageSequence

from behance_studio.core.errors import AssetError
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)

# Large print-resolution artwork is legitimate input; keep a sane upper bound.
Image.MAX_IMAGE_PIXELS = 600_000_000

_SRGB = ImageCms.createProfile("sRGB")
_ORIENTATION_TAG = 0x0112


# ---------------------------------------------------------------- images
def _apply_icc(img: Image.Image) -> Image.Image:
    icc = img.info.get("icc_profile")
    if not icc:
        return img
    try:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        if img.mode == "RGBA":
            rgb = img.convert("RGB")
            converted = ImageCms.profileToProfile(rgb, src, _SRGB, outputMode="RGB")
            converted.putalpha(img.getchannel("A"))
            return converted
        if img.mode in ("RGB", "CMYK", "L"):
            out_mode = "L" if img.mode == "L" else "RGB"
            return ImageCms.profileToProfile(img, src, _SRGB, outputMode=out_mode)
    except Exception as exc:  # noqa: BLE001 - broken profiles are common
        log.debug("ICC conversion skipped: %s", exc)
    return img


def normalize_image(img: Image.Image) -> tuple[Image.Image, bool]:
    """Return an upright sRGB RGB/RGBA image and whether it uses transparency."""
    try:
        img = ImageOps.exif_transpose(img) or img
    except Exception:  # noqa: BLE001 - malformed EXIF must not block import
        pass
    mode = img.mode
    if mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        arr = np.asarray(img, dtype=np.float64)
        hi = float(arr.max()) or 1.0
        img = Image.fromarray(np.clip(arr / hi * 255.0, 0, 255).astype(np.uint8), "L")
    elif mode == "1":
        img = img.convert("L")
    if img.mode == "CMYK":
        img = _apply_icc(img)
        if img.mode == "CMYK":
            img = img.convert("RGB")
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (
        img.mode == "P" and "transparency" in img.info
    )
    if has_alpha:
        icc = img.info.get("icc_profile")
        img = img.convert("RGBA")
        if icc:
            img.info["icc_profile"] = icc
        alpha_min = img.getchannel("A").getextrema()[0]
        if alpha_min >= 250:
            has_alpha = False
            img = img.convert("RGB")
    else:
        icc = img.info.get("icc_profile")
        img = img.convert("RGB")
        if icc:
            img.info["icc_profile"] = icc
    img = _apply_icc(img)
    img.info.pop("icc_profile", None)
    return img, has_alpha


def image_header(path: Path) -> dict[str, Any]:
    """Cheap metadata without decoding the pixels."""
    with Image.open(path) as img:
        width, height = img.size
        orientation = 1
        try:
            orientation = int(img.getexif().get(_ORIENTATION_TAG, 1) or 1)
        except Exception:  # noqa: BLE001
            orientation = 1
        if orientation in (5, 6, 7, 8):
            width, height = height, width
        n_frames = getattr(img, "n_frames", 1)
        dpi = img.info.get("dpi")
        return {
            "width": width,
            "height": height,
            "format": img.format,
            "mode": img.mode,
            "exif_orientation": orientation,
            "frames": n_frames,
            "dpi": [float(dpi[0]), float(dpi[1])] if dpi else None,
            "has_icc": bool(img.info.get("icc_profile")),
        }


def open_image(path: Path, max_size: int | None = None) -> tuple[Image.Image, bool]:
    """Decode and normalise an image file, optionally downscaled.

    JPEG draft mode decodes at a reduced DCT scale, which makes thumbnails
    of very large photographs fast and memory-friendly. The whole stream is
    still read, so truncated files are detected.
    """
    try:
        with Image.open(path) as img:
            if max_size and img.format == "JPEG":
                img.draft("RGB", (max_size, max_size))
            img.load()
            out, has_alpha = normalize_image(img)
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise AssetError(f"The image could not be read: {Path(path).name}", str(exc)) from exc
    if max_size and max(out.size) > max_size:
        out.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return out, has_alpha


def verify_image(path: Path) -> None:
    """Raise AssetError if the file is not a decodable image."""
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            if img.format == "JPEG":
                img.draft("RGB", (256, 256))
            img.load()
    except Exception as exc:  # noqa: BLE001
        raise AssetError(f"The file appears to be damaged: {Path(path).name}", str(exc)) from exc


# ------------------------------------------------------------------- GIF
def gif_info(path: Path) -> dict[str, Any]:
    with Image.open(path) as img:
        frames = getattr(img, "n_frames", 1)
        duration = 0.0
        if frames > 1:
            for frame in ImageSequence.Iterator(img):
                duration += (frame.info.get("duration") or 100) / 1000.0
        return {
            "width": img.size[0],
            "height": img.size[1],
            "frames": frames,
            "animated": frames > 1,
            "duration": round(duration, 3),
        }


def gif_still(path: Path, max_size: int | None = None) -> tuple[Image.Image, bool]:
    """Pick a representative still frame (the most detailed of a few samples)."""
    with Image.open(path) as img:
        frames = getattr(img, "n_frames", 1)
        candidates = sorted({0, frames // 3, frames // 2, (2 * frames) // 3}) if frames > 1 else [0]
        best, best_score = None, -1.0
        for index in candidates:
            img.seek(index)
            frame = img.convert("RGBA")
            score = float(np.asarray(frame.convert("L"), dtype=np.float32).std())
            if score > best_score:
                best, best_score = frame.copy(), score
    assert best is not None
    out, has_alpha = normalize_image(best)
    if max_size and max(out.size) > max_size:
        out.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return out, has_alpha


# ------------------------------------------------------------------- SVG
def _parse_length(value: str | None) -> float | None:
    if not value:
        return None
    match = re.match(r"\s*([0-9.]+)\s*(px|pt|mm|cm|in)?\s*$", value)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or "px"
    return number * {"px": 1, "pt": 4 / 3, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96}[unit]


def svg_size(path: Path) -> tuple[float, float]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise AssetError(f"The SVG file is not valid: {Path(path).name}", str(exc)) from exc
    if not root.tag.lower().endswith("svg"):
        raise AssetError(f"The file is not an SVG image: {Path(path).name}")
    width = _parse_length(root.get("width"))
    height = _parse_length(root.get("height"))
    viewbox = root.get("viewBox") or root.get("viewbox")
    if viewbox and (not width or not height):
        parts = [float(p) for p in re.split(r"[\s,]+", viewbox.strip()) if p]
        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
            if width and not height:
                height = width * parts[3] / parts[2]
            elif height and not width:
                width = height * parts[2] / parts[3]
            else:
                width, height = parts[2], parts[3]
    return (width or 300.0, height or 150.0)


_svg_lock = threading.Lock()


def rasterize_svg(path: Path, max_size: int = 1024) -> Image.Image:
    from behance_studio.core.qtsupport import ensure_gui_application

    if not ensure_gui_application():
        raise AssetError("SVG rendering is not available in this context.")
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    width, height = svg_size(path)
    scale = max_size / max(width, height)
    out_w, out_h = max(1, round(width * scale)), max(1, round(height * scale))
    with _svg_lock:
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            raise AssetError(f"The SVG file could not be rendered: {Path(path).name}")
        image = QImage(out_w, out_h, QImage.Format.Format_RGBA8888)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, out_w, out_h))
        painter.end()
        ptr = image.constBits()
        data = bytes(ptr)[: image.sizeInBytes()]
        pil = Image.frombuffer("RGBA", (out_w, out_h), data, "raw", "RGBA", image.bytesPerLine(), 1).copy()
    return pil


# ----------------------------------------------------------------- video
def ffmpeg_exe() -> str:
    override = os.environ.get("BEHANCE_STUDIO_FFMPEG")
    if override and Path(override).exists():
        return override
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        found = shutil.which("ffmpeg")
        if found:
            return found
    raise AssetError("FFmpeg is not available, so video files cannot be processed.")


def _run(args: list[str], timeout: float = 120, capture_stdout: bool = False) -> subprocess.CompletedProcess:
    kwargs: dict[str, Any] = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(
        args,
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        **kwargs,
    )


def video_info(path: Path) -> dict[str, Any]:
    proc = _run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], timeout=60)
    text = proc.stderr.decode("utf-8", errors="replace")
    video = re.search(r"Stream #\d+:\d+.*?: Video: ([^\s,]+).*?(\d{2,5})x(\d{2,5})", text)
    if not video:
        raise AssetError(f"No video stream found in {Path(path).name}", text[-800:])
    width, height = int(video.group(2)), int(video.group(3))
    duration = 0.0
    dmatch = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if dmatch:
        h, m, s = dmatch.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    fps = 0.0
    fmatch = re.search(r"(\d+(?:\.\d+)?) fps", text)
    if fmatch:
        fps = float(fmatch.group(1))
    rotation = 0
    rmatch = re.search(r"rotate\s*:\s*(-?\d+)", text) or re.search(
        r"rotation of (-?\d+(?:\.\d+)?) degrees", text
    )
    if rmatch:
        rotation = int(round(float(rmatch.group(1)))) % 360
    if rotation in (90, 270):
        width, height = height, width
    return {
        "width": width,
        "height": height,
        "duration": round(duration, 3),
        "fps": fps,
        "codec": video.group(1),
        "has_audio": " Audio: " in text,
        "rotation": rotation,
        "frame_count": int(duration * fps) if fps else 0,
    }


def video_frame(path: Path, time_s: float) -> Image.Image:
    proc = _run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, time_s):.3f}",
            "-i", str(path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
        ],
        timeout=120,
        capture_stdout=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise AssetError(
            f"A frame could not be extracted from {Path(path).name}",
            proc.stderr.decode("utf-8", errors="replace")[-800:],
        )
    img = Image.open(io.BytesIO(proc.stdout))
    img.load()
    return img.convert("RGB")


def video_poster(path: Path, duration: float) -> Image.Image:
    """Choose a representative frame: the most detailed of a few candidates."""
    times = [duration * f for f in (0.1, 0.33, 0.5, 0.66)] if duration > 0.5 else [0.0]
    best, best_score = None, -1.0
    for t in times:
        try:
            frame = video_frame(path, t)
        except AssetError:
            continue
        gray = np.asarray(frame.convert("L").resize((160, 90)), dtype=np.float32)
        score = float(gray.std()) + float(np.abs(np.diff(gray, axis=1)).mean()) * 2
        if score > best_score:
            best, best_score = frame, score
    if best is None:
        best = video_frame(path, 0.0)
    return best


def make_video_proxy(path: Path, out_path: Path, max_width: int = 1280) -> Path:
    """Muted VP9 WebM proxy for the in-app preview (Qt WebEngine has no H.264)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.stem + ".partial.webm")
    proc = _run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
            "-vf", f"scale='min({max_width},iw)':-2", "-an", "-c:v", "libvpx-vp9",
            "-b:v", "0", "-crf", "36", "-deadline", "realtime", "-cpu-used", "8",
            "-row-mt", "1", str(tmp),
        ],
        timeout=1800,
    )
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise AssetError("A preview version of the video could not be created.", proc.stderr.decode("utf-8", "replace")[-800:])
    os.replace(tmp, out_path)
    return out_path


def make_video_mp4(path: Path, out_path: Path, max_width: int = 1920) -> Path:
    """Broadly compatible H.264 MP4 (for HTML packages)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.stem + ".partial.mp4")
    proc = _run(
        [
            ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
            "-vf", f"scale='min({max_width},iw)':-2", "-an", "-c:v", "libx264", "-preset", "medium",
            "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp),
        ],
        timeout=3600,
    )
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise AssetError("The video could not be converted for the HTML package.", proc.stderr.decode("utf-8", "replace")[-800:])
    os.replace(tmp, out_path)
    return out_path
