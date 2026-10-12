"""Deterministic, fully offline visual analysis of an image.

These are measurable signal-processing features (colour statistics, edges,
saliency, transparency...). They are *not* semantic understanding; semantic
labels are estimated from them in :mod:`behance_studio.assets.classify` and
can be improved with an optional AI provider.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

import cv2
import numpy as np
from PIL import Image

ANALYSIS_VERSION = 4
ANALYSIS_SIZE = 384


def _to_arrays(img: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Return (rgb uint8 HxWx3, alpha float HxW in 0..1)."""
    work = img.copy()
    work.thumbnail((ANALYSIS_SIZE, ANALYSIS_SIZE), Image.Resampling.BILINEAR)
    if work.mode == "RGBA":
        arr = np.asarray(work, dtype=np.uint8)
        return arr[..., :3].copy(), arr[..., 3].astype(np.float32) / 255.0
    arr = np.asarray(work.convert("RGB"), dtype=np.uint8)
    return arr, np.ones(arr.shape[:2], dtype=np.float32)


def rgb_to_hex(rgb) -> str:
    r, g, b = (int(max(0, min(255, round(float(c))))) for c in rgb[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


def _lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB uint8 (...x3) → CIE Lab float (OpenCV scale corrected)."""
    shape = rgb.shape
    flat = rgb.reshape(-1, 1, 3).astype(np.float32) / 255.0
    lab = cv2.cvtColor(flat, cv2.COLOR_RGB2LAB).reshape(shape)
    return lab


def dominant_colors(rgb: np.ndarray, weights: np.ndarray | None = None, k: int = 6) -> list[dict[str, Any]]:
    pixels = rgb.reshape(-1, 3).astype(np.float32)
    if weights is not None:
        mask = weights.reshape(-1) > 0.5
        pixels = pixels[mask]
    if len(pixels) == 0:
        return []
    if len(pixels) > 12000:
        rng = np.random.default_rng(1234)
        pixels = pixels[rng.choice(len(pixels), 12000, replace=False)]
    k = max(1, min(k, len(np.unique(pixels.astype(np.uint8), axis=0))))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    cv2.setRNGSeed(7)
    _compactness, labels, centers = cv2.kmeans(pixels, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.reshape(-1), minlength=k).astype(np.float64)
    total = counts.sum() or 1.0
    order = np.argsort(-counts)
    out = []
    labs = _lab(centers.reshape(1, -1, 3).clip(0, 255).astype(np.uint8)).reshape(-1, 3)
    for idx in order:
        if counts[idx] <= 0:
            continue
        r, g, b = centers[idx]
        l, a, bb = labs[idx]
        out.append(
            {
                "hex": rgb_to_hex((r, g, b)),
                "weight": round(float(counts[idx] / total), 4),
                "lab": [round(float(l), 1), round(float(a), 1), round(float(bb), 1)],
                "chroma": round(float(math.hypot(a, bb)), 1),
            }
        )
    return out


def colorfulness(rgb: np.ndarray) -> float:
    """Hasler & Süsstrunk colourfulness metric (0 ≈ grey, >80 very colourful)."""
    r, g, b = (rgb[..., i].astype(np.float32) for i in range(3))
    rg = np.abs(r - g)
    yb = np.abs(0.5 * (r + g) - b)
    return float(math.hypot(rg.std(), yb.std()) + 0.3 * math.hypot(rg.mean(), yb.mean()))


def _saliency(gray: np.ndarray) -> np.ndarray:
    """Spectral-residual saliency map (Hou & Zhang 2007), normalised 0..1."""
    small = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
    spectrum = np.fft.fft2(small)
    log_amp = np.log(np.abs(spectrum) + 1e-6)
    phase = np.angle(spectrum)
    residual = log_amp - cv2.blur(log_amp, (3, 3))
    sal = np.abs(np.fft.ifft2(np.exp(residual + 1j * phase))) ** 2
    sal = cv2.GaussianBlur(sal.astype(np.float32), (9, 9), 2.5)
    sal = cv2.resize(sal, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_LINEAR)
    sal -= sal.min()
    peak = sal.max()
    return sal / peak if peak > 0 else sal


@lru_cache(maxsize=1)
def _face_cascade():
    try:
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"  # type: ignore[attr-defined]
        cascade = cv2.CascadeClassifier(path)
        return None if cascade.empty() else cascade
    except Exception:  # noqa: BLE001
        return None


def _palette_like(rgb: np.ndarray, alpha: np.ndarray) -> float:
    """Score how much the image looks like a colour-swatch presentation."""
    h, w = rgb.shape[:2]
    small = cv2.resize(rgb, (min(160, w), min(160, h)), interpolation=cv2.INTER_AREA)
    pixels = small.reshape(-1, 3).astype(np.float32)
    cv2.setRNGSeed(3)
    k = 8
    _c, labels, centers = cv2.kmeans(
        pixels, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0), 2, cv2.KMEANS_PP_CENTERS
    )
    labels = labels.reshape(small.shape[:2])
    big_rect_colors = set()
    area_total = labels.size
    for idx in range(k):
        mask = (labels == idx).astype(np.uint8)
        n, comp, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
        for j in range(1, n):
            x, y, cw, ch, area = stats[j]
            if area < area_total * 0.035:
                continue
            rectangularity = area / float(cw * ch)
            if rectangularity > 0.88:
                big_rect_colors.add(rgb_to_hex(centers[idx]))
    distinct = len(big_rect_colors)
    if distinct < 3:
        return 0.0
    return float(min(1.0, (distinct - 2) / 3.0))


def phash(img: Image.Image) -> str:
    """64-bit DCT perceptual hash as hex (robust to resizing/compression)."""
    work = img
    if work.mode == "RGBA":
        bg = Image.new("RGB", work.size, (255, 255, 255))
        bg.paste(work, mask=work.getchannel("A"))
        work = bg
    gray = np.asarray(work.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float32)
    dct = cv2.dct(gray)[:8, :8]
    flat = dct.reshape(-1)[1:]
    bits = flat > np.median(flat)
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def hamming(a: str, b: str) -> int:
    if not a or not b:
        return 64
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def text_regions(gray: np.ndarray, opaque: np.ndarray | None = None) -> tuple[list[tuple[float, float, float, float]], float]:
    """Lines of typography in an image (classical detector, no AI).

    Strong edges are joined horizontally into candidate lines, which are kept
    only when they look like type: an elongated box, ink strongly separated
    from a plain ground, and many stroke transitions. Returns normalised
    boxes and their total area fraction. Textures (wood grain, foliage) have
    weak or irregular edges and are rejected; the result is an estimate.
    """
    h, w = gray.shape
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, k)
    thr = max(50, int(cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[0]))
    bw = (grad >= thr).astype(np.uint8) * 255
    if opaque is not None:
        bw[~opaque] = 0
    kw = max(5, w // 90)
    joined = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 1)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    boxes = []
    for i in range(1, n):
        x, y, bw_, bh, area = stats[i]
        if bh < max(5, h * 0.008) or bh > h * 0.22 or bw_ < bh * 1.6 or bw_ < w * 0.025:
            continue
        roi = bw[y:y + bh, x:x + bw_]
        fill = roi.mean() / 255
        if not 0.18 <= fill <= 0.75:
            continue
        g = gray[y:y + bh, x:x + bw_]
        # Text: strongly bimodal (ink on a plain ground).
        _t, split = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        a, b = g[split > 0], g[split == 0]
        if a.size < 4 or b.size < 4:
            continue
        sep = abs(float(a.mean()) - float(b.mean())) / (float(g.std()) + 1e-6)
        spread = (float(a.std()) + float(b.std())) / 2
        if sep < 1.6 or spread > 34:
            continue
        # Character-like vertical strokes: many transitions along the middle row.
        mid = split[bh // 2]
        transitions = int(np.count_nonzero(np.diff(mid.astype(np.int16)) != 0))
        if transitions < max(4, bw_ / bh * 1.2):
            continue
        boxes.append((x / w, y / h, (x + bw_) / w, (y + bh) / h))
    boxes.sort(key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes)
    return boxes, float(area)


def analyze_image(img: Image.Image) -> dict[str, Any]:
    rgb, alpha = _to_arrays(img)
    h, w = rgb.shape[:2]
    opaque = alpha > 0.5
    opaque_fraction = float(opaque.mean())
    transparent_fraction = float((alpha < 0.06).mean())
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # --- content bounding box (alpha or solid background) -----------------
    border = np.concatenate([rgb[:3].reshape(-1, 3), rgb[-3:].reshape(-1, 3), rgb[:, :3].reshape(-1, 3), rgb[:, -3:].reshape(-1, 3)])
    border_alpha = np.concatenate([alpha[:3].reshape(-1), alpha[-3:].reshape(-1), alpha[:, :3].reshape(-1), alpha[:, -3:].reshape(-1)])
    background = None
    bg_uniformity = 0.0
    if transparent_fraction > 0.05 and border_alpha.mean() < 0.5:
        content_mask = opaque
        background = "transparent"
        bg_uniformity = 1.0
    else:
        bg_rgb = np.median(border, axis=0)
        border_dev = np.abs(border.astype(np.float32) - bg_rgb).mean(axis=1)
        bg_uniformity = float((border_dev < 12).mean())
        diff = np.abs(rgb.astype(np.float32) - bg_rgb).max(axis=2)
        content_mask = diff > 28
        background = rgb_to_hex(bg_rgb) if bg_uniformity > 0.85 else None
    ys, xs = np.nonzero(content_mask)
    if len(xs) > 0:
        bbox = [float(xs.min() / w), float(ys.min() / h), float((xs.max() + 1) / w), float((ys.max() + 1) / h)]
        fill_ratio = float(content_mask.mean())
    else:
        bbox = [0.0, 0.0, 1.0, 1.0]
        fill_ratio = 0.0
    bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])

    # --- colour statistics -----------------------------------------------
    colors = dominant_colors(rgb, alpha, k=6)
    content_colors = colors
    if background and background != "transparent":
        bg_lab = _lab(np.array([[[int(background[i : i + 2], 16) for i in (1, 3, 5)]]], dtype=np.uint8)).reshape(3)
        content_colors = [
            c for c in colors if np.linalg.norm(np.array(c["lab"]) - bg_lab) > 10
        ] or colors
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    sat = hsv[..., 1][opaque] if opaque.any() else hsv[..., 1].reshape(-1)
    val = gray[opaque] if opaque.any() else gray.reshape(-1)
    quant = (rgb[opaque] // 16).astype(np.int32) if opaque.any() else (rgb.reshape(-1, 3) // 16).astype(np.int32)
    codes = quant[:, 0] * 256 + quant[:, 1] * 16 + quant[:, 2]
    counts = np.sort(np.bincount(codes, minlength=4096))[::-1]
    cumulative = np.cumsum(counts) / max(1, counts.sum())
    n90 = int(np.searchsorted(cumulative, 0.9) + 1)

    # --- structure ---------------------------------------------------------
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    flat_ratio = float((mag[opaque] < 8).mean()) if opaque.any() else 1.0
    edges = cv2.Canny(gray, 60, 160)
    edge_density = float((edges > 0)[opaque].mean()) if opaque.any() else 0.0
    strong = mag > 60
    if strong.sum() > 50:
        angles = np.degrees(np.arctan2(gy[strong], gx[strong])) % 180
        axis = ((angles < 4) | (angles > 176) | (np.abs(angles - 90) < 4)).mean()
        axis_alignment = float(axis)
    else:
        axis_alignment = 0.0

    # Sharpness on a standard size for comparability.
    std_gray = cv2.resize(gray, (256, max(1, int(256 * h / w))), interpolation=cv2.INTER_AREA)
    sharpness = float(cv2.Laplacian(std_gray, cv2.CV_64F).var())

    # --- saliency / focal point / negative space --------------------------
    sal = _saliency(gray) * alpha
    threshold = np.quantile(sal, 0.9) if sal.size else 0
    hot = sal >= threshold
    if hot.any():
        hy, hx = np.nonzero(hot)
        focal = [float(hx.mean() / w), float(hy.mean() / h)]
        sal_bbox = [float(hx.min() / w), float(hy.min() / h), float((hx.max() + 1) / w), float((hy.max() + 1) / h)]
        spread = float(np.hypot(hx.std() / w, hy.std() / h))
    else:
        focal, sal_bbox, spread = [0.5, 0.5], [0, 0, 1, 1], 0.5
    busy = cv2.resize((sal * 0.6 + (edges > 0).astype(np.float32) * 0.4), (3, 3), interpolation=cv2.INTER_AREA)
    names = [["top-left", "top", "top-right"], ["left", "center", "right"], ["bottom-left", "bottom", "bottom-right"]]
    quiet_idx = np.unravel_index(np.argmin(busy), busy.shape)
    quiet_region = names[quiet_idx[0]][quiet_idx[1]]
    quietness = float(1.0 - busy.min() / (busy.max() + 1e-6))
    lum_grid = cv2.resize(gray.astype(np.float32) / 255.0, (8, 8), interpolation=cv2.INTER_AREA)

    # --- faces --------------------------------------------------------------
    faces = []
    cascade = _face_cascade()
    if cascade is not None and n90 > 60:
        found = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(max(24, w // 12), max(24, h // 12)))
        for (fx, fy, fw, fh) in found[:8]:
            faces.append([float(fx / w), float(fy / h), float(fw / w), float(fh / h)])

    # --- typography inside the image --------------------------------------
    text_gray = gray if opaque.all() else np.where(opaque, gray, 255).astype(np.uint8)
    try:
        text_boxes, text_area = text_regions(text_gray, opaque if not opaque.all() else None)
    except cv2.error:  # pragma: no cover - degenerate images
        text_boxes, text_area = [], 0.0

    mean_sat = float(sat.mean() / 255.0) if sat.size else 0.0
    return {
        "version": ANALYSIS_VERSION,
        "text_lines": len(text_boxes),
        "text_fraction": round(text_area, 4),
        "text_boxes": [[round(v, 4) for v in b] for b in text_boxes[:16]],
        "colors": colors,
        "content_colors": content_colors,
        "background": background,
        "background_uniformity": round(bg_uniformity, 3),
        "content_bbox": [round(v, 4) for v in bbox],
        "content_bbox_area": round(bbox_area, 4),
        "fill_ratio": round(fill_ratio, 4),
        "opaque_fraction": round(opaque_fraction, 4),
        "transparent_fraction": round(transparent_fraction, 4),
        "brightness": round(float(val.mean() / 255.0) if val.size else 0.5, 4),
        "contrast": round(float(val.std() / 255.0) if val.size else 0.0, 4),
        "saturation": round(mean_sat, 4),
        "colorfulness": round(colorfulness(rgb), 2),
        "grayscale": bool(mean_sat < 0.06),
        "n90_colors": n90,
        "flat_ratio": round(flat_ratio, 4),
        "edge_density": round(edge_density, 4),
        "axis_alignment": round(axis_alignment, 4),
        "sharpness": round(sharpness, 1),
        "focal_point": [round(v, 4) for v in focal],
        "salient_bbox": [round(v, 4) for v in sal_bbox],
        "saliency_spread": round(spread, 4),
        "quiet_region": quiet_region,
        "quietness": round(quietness, 4),
        "luminance_grid": [[round(float(v), 3) for v in row] for row in lum_grid],
        "faces": faces,
        "palette_like": round(_palette_like(rgb, alpha), 3),
    }


def region_luminance(analysis: dict[str, Any], x0: float, y0: float, x1: float, y1: float) -> float:
    """Mean luminance (0..1) of a normalised region using the 8x8 grid."""
    grid = analysis.get("luminance_grid")
    if not grid:
        return analysis.get("brightness", 0.5)
    arr = np.asarray(grid, dtype=np.float32)
    gx0, gx1 = int(max(0, min(7, math.floor(x0 * 8)))), int(max(1, min(8, math.ceil(x1 * 8))))
    gy0, gy1 = int(max(0, min(7, math.floor(y0 * 8)))), int(max(1, min(8, math.ceil(y1 * 8))))
    return float(arr[gy0:gy1, gx0:gx1].mean())
