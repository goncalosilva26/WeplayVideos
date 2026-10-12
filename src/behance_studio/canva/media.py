"""Pictures for the scene: fitting, lossless cropping and per-element effects.

A picture stays a picture: an effect that PowerPoint and Canva cannot express
as an editable property (an edge fade, a CSS filter, a blend mode over a
plain background, a recoloured mark, a perspective tilt, a pattern fill) is
drawn into the pixels of *that one image* — the element remains separately
selectable, movable and replaceable. Pages are never flattened.

Cropping uses the picture's crop rectangle (PowerPoint ``srcRect``) on an
image that keeps the hidden parts, so the crop can be adjusted in Canva.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from behance_studio.canva.css import parse_rgba
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)

MAX_EDGE = 4096  # longest side of a prepared image (keeps files importable)
DENSITY = {"standard": 1.25, "high": 2.0, "maximum": 3.0}


@dataclass
class MediaContext:
    project: object
    workdir: Path
    density: float = 2.0
    jpeg_quality: int = 90
    _sources: dict = field(default_factory=dict)
    _written: dict = field(default_factory=dict)
    bytes_written: int = 0

    def source(self, asset_id: str) -> tuple[Image.Image, bool] | None:
        """The asset as an upright sRGB image (largest useful size, cached)."""
        if asset_id in self._sources:
            return self._sources[asset_id]
        from behance_studio.assets.derivatives import load_visual

        asset = self.project.get_asset(asset_id) if asset_id else None
        result = None
        if asset is not None:
            try:
                img, alpha = load_visual(self.project, asset, max_size=MAX_EDGE)
                img = img.convert("RGBA" if alpha or img.mode == "RGBA" else "RGB")
                result = (img, img.mode == "RGBA")
            except Exception as exc:  # noqa: BLE001 - a missing file must not stop the export
                log.warning("Canva export: asset %s unavailable: %s", getattr(asset, "filename", asset_id), exc)
        self._sources[asset_id] = result
        return result

    def save(self, img: Image.Image, key: str) -> tuple[str, int, int]:
        """Write ``img`` once (PNG with transparency, otherwise JPEG)."""
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        if digest in self._written:
            return self._written[digest]
        self.workdir.mkdir(parents=True, exist_ok=True)
        alpha = img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 255
        if alpha:
            path = self.workdir / f"{digest}.png"
            bleed_alpha(img).save(path, "PNG", compress_level=6)
        else:
            path = self.workdir / f"{digest}.jpg"
            img.convert("RGB").save(path, "JPEG", quality=self.jpeg_quality, optimize=True, subsampling=0 if self.jpeg_quality >= 90 else 2)
        self.bytes_written += path.stat().st_size
        out = (str(path), img.width, img.height)
        self._written[digest] = out
        return out


def bleed_alpha(img: Image.Image, radius: float = 6.0) -> Image.Image:
    """Give fully transparent pixels the colour of their visible neighbours.

    Programs that scale or rotate pictures without premultiplied alpha blend
    the colour stored in invisible pixels (often white) into the edges,
    drawing a light halo around logos. The visible image is unchanged."""
    from PIL import ImageFilter

    arr = np.asarray(img.convert("RGBA")).astype(np.float32)
    a = arr[..., 3:4] / 255.0
    if (a > 0).all():
        return img
    weight = Image.fromarray((a[..., 0] * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(radius))
    w = np.asarray(weight).astype(np.float32)[..., None] / 255.0
    out = arr.copy()
    for c in range(3):
        premul = Image.fromarray(np.clip(arr[..., c] * a[..., 0], 0, 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(radius))
        spread = np.asarray(premul).astype(np.float32) / np.maximum(w[..., 0], 1e-4)
        visible = a[..., 0] > 0
        mean = float((arr[..., c] * a[..., 0]).sum() / max(a.sum(), 1e-4))
        fill = np.where(w[..., 0] > 0.01, np.clip(spread, 0, 255), mean)
        out[..., c] = np.where(visible, arr[..., c], fill)
    return Image.fromarray(out.round().astype(np.uint8), "RGBA")


# ----------------------------------------------------------------- fitting
def fit_rect(iw: float, ih: float, bw: float, bh: float, fit: str, focal: tuple[float, float], zoom: float = 1.0) -> tuple[float, float, float, float]:
    """Where the whole image lands inside a box (CSS object-fit/position + zoom)."""
    fx, fy = focal[0] / 100.0, focal[1] / 100.0
    s = (max if fit == "cover" else min)(bw / iw, bh / ih)
    rw, rh = iw * s, ih * s
    x, y = (bw - rw) * fx, (bh - rh) * fy
    if fit == "cover" and zoom and zoom > 1.0:
        px, py = fx * bw, fy * bh
        x, y, rw, rh = px + (x - px) * zoom, py + (y - py) * zoom, rw * zoom, rh * zoom
    return x, y, rw, rh


def corner_radii(clip: str | None, radius: float, w: float, h: float) -> tuple[float, float, float, float] | str:
    """CSS border radius of a layer as (tl, tr, br, bl) px, or "ellipse"."""
    if clip in ("circle", "oval"):
        return "ellipse"
    if clip == "pill":
        r = min(w, h) / 2
        return (r, r, r, r)
    if clip == "arch":
        r = min(w / 2, h)
        return (r, r, 0.0, 0.0)
    if clip == "rounded":
        r = radius or min(w, h) * 0.04
        return (r, r, r, r)
    if radius:
        r = min(radius, w / 2, h / 2)
        return (r, r, r, r)
    return (0.0, 0.0, 0.0, 0.0)


def has_radius(radii) -> bool:
    return radii == "ellipse" or any(r > 0.01 for r in radii)


def mask_image(w: int, h: int, radii, scale: float = 1.0) -> Image.Image:
    """Antialiased alpha mask of a rounded rectangle / ellipse."""
    ss = max(1, min(4, int(4000 / max(w, h, 1))))
    W, H = max(1, w * ss), max(1, h * ss)
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    if radii == "ellipse":
        d.ellipse((0, 0, W - 1, H - 1), fill=255)
    else:
        tl, tr, br, bl = (r * scale * ss for r in radii)
        rmax = max(tl, tr, br, bl)
        if rmax <= 0:
            d.rectangle((0, 0, W, H), fill=255)
        else:
            corners = tuple(r > 0 for r in (tl, tr, br, bl))
            d.rounded_rectangle((0, 0, W - 1, H - 1), radius=rmax, fill=255, corners=corners)  # type: ignore[arg-type]
    return m.resize((w, h), Image.Resampling.LANCZOS) if ss > 1 else m


# ----------------------------------------------------------------- effects
FADE_SOLID = 0.58  # mask stays opaque for 58 % of the box, then fades (renderer FADES)


def fade_mask(w: int, h: int, side: str) -> Image.Image:
    """Alpha of an edge fade: ``side`` is the edge that fades out."""
    n = h if side in ("top", "bottom") else w
    # t: distance from the opaque edge, 0..1 (rows top→bottom, columns left→right)
    t = np.linspace(1.0, 0.0, n) if side in ("top", "left") else np.linspace(0.0, 1.0, n)
    a = np.clip(1.0 - (t - FADE_SOLID) / (1.0 - FADE_SOLID), 0.0, 1.0)
    if side in ("top", "bottom"):
        arr = np.repeat(a[:, None], w, axis=1)
    else:
        arr = np.repeat(a[None, :], h, axis=0)
    return Image.fromarray((arr * 255).round().astype(np.uint8), "L")


def apply_filter(img: Image.Image, name: str | None) -> Image.Image:
    """CSS grayscale(1) / saturate(.62) / brightness(.82) (renderer FILTERS)."""
    if not name:
        return img
    rgba = img.convert("RGBA")
    arr = np.asarray(rgba).astype(np.float32) / 255.0
    rgb = arr[..., :3]
    if name == "grayscale":
        m = np.array([[0.2126, 0.7152, 0.0722]] * 3, dtype=np.float32)
        rgb = rgb @ m.T
    elif name == "muted":
        s = 0.62
        m = np.array([[0.213 + 0.787 * s, 0.715 - 0.715 * s, 0.072 - 0.072 * s],
                      [0.213 - 0.213 * s, 0.715 + 0.285 * s, 0.072 - 0.072 * s],
                      [0.213 - 0.213 * s, 0.715 - 0.715 * s, 0.072 + 0.928 * s]], dtype=np.float32)
        rgb = rgb @ m.T
    elif name == "dim":
        rgb = rgb * 0.82
    arr[..., :3] = np.clip(rgb, 0, 1)
    out = Image.fromarray((arr * 255).round().astype(np.uint8), "RGBA")
    return out if img.mode == "RGBA" else out.convert("RGB")


def _lum(c: np.ndarray) -> np.ndarray:
    return 0.3 * c[..., 0] + 0.59 * c[..., 1] + 0.11 * c[..., 2]


def blend_channel(src: np.ndarray, dst: np.ndarray, mode: str) -> np.ndarray | None:
    """W3C compositing blend of ``src`` over backdrop ``dst`` (0..1 arrays)."""
    if mode == "multiply":
        return src * dst
    if mode == "screen":
        return src + dst - src * dst
    if mode == "darken":
        return np.minimum(src, dst)
    if mode == "lighten":
        return np.maximum(src, dst)
    if mode == "overlay":
        return np.where(dst <= 0.5, 2 * src * dst, 1 - 2 * (1 - src) * (1 - dst))
    if mode == "soft-light":
        d = np.where(dst <= 0.25, ((16 * dst - 12) * dst + 4) * dst, np.sqrt(dst))
        return np.where(src <= 0.5, dst - (1 - 2 * src) * dst * (1 - dst), dst + (2 * src - 1) * (d - dst))
    if mode == "luminosity":
        out = dst + (_lum(src) - _lum(dst))[..., None]
        lum = _lum(out)[..., None]
        mn, mx = out.min(axis=-1, keepdims=True), out.max(axis=-1, keepdims=True)
        out = np.where(mn < 0, lum + (out - lum) * lum / np.maximum(lum - mn, 1e-6), out)
        out = np.where(mx > 1, lum + (out - lum) * (1 - lum) / np.maximum(mx - lum, 1e-6), out)
        return out
    return None


def blend_onto(img: Image.Image, mode: str, backdrop: str) -> Image.Image | None:
    """Apply a blend mode against a plain backdrop colour (alpha kept)."""
    color = parse_rgba(backdrop)
    if color is None:
        return None
    from behance_studio.design.color import parse_hex

    rgba = np.asarray(img.convert("RGBA")).astype(np.float32) / 255.0
    dst = np.broadcast_to(np.array(parse_hex(color[0]), dtype=np.float32) / 255.0, rgba[..., :3].shape)
    out = blend_channel(rgba[..., :3], dst, mode)
    if out is None:
        return None
    rgba[..., :3] = np.clip(out, 0, 1)
    return Image.fromarray((rgba * 255).round().astype(np.uint8), "RGBA")


def blend_color(color: str, mode: str, backdrop: str) -> str | None:
    """A solid colour blended over a plain backdrop (text and shapes)."""
    img = Image.new("RGBA", (1, 1), color)
    out = blend_onto(img, mode, backdrop)
    if out is None:
        return None
    r, g, b, _ = out.getpixel((0, 0))
    return f"#{r:02X}{g:02X}{b:02X}"


# ------------------------------------------------------------- perspective
def perspective_quad(w: float, h: float, rx: float, ry: float, rz: float = 0.0) -> list[tuple[float, float]]:
    """Screen corners (relative to the box centre) of a box under CSS
    ``perspective(2.4·max(w,h)) rotateX(rx) rotateY(ry) rotate(rz)``."""
    p = max(w, h) * 2.4
    ax, ay, az = math.radians(rx), math.radians(ry), math.radians(rz)
    out = []
    for x, y in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        x, y = x * math.cos(az) - y * math.sin(az), x * math.sin(az) + y * math.cos(az)  # rotate (Z)
        x, z = x * math.cos(ay), -x * math.sin(ay)  # rotateY
        y, z = y * math.cos(ax) - z * math.sin(ax), y * math.sin(ax) + z * math.cos(ax)  # rotateX
        k = 1.0 / (1.0 - z / p)
        out.append((x * k, y * k))
    return out


def _coeffs(dst: list[tuple[float, float]], src: list[tuple[float, float]]) -> list[float]:
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs += [u, v]
    return list(np.linalg.solve(np.array(rows, dtype=np.float64), np.array(rhs, dtype=np.float64)))


def warp_perspective(img: Image.Image, quad: list[tuple[float, float]], scale: float) -> tuple[Image.Image, float, float]:
    """Warp ``img`` onto ``quad`` (box-centre relative, CSS px); returns the
    image and its top-left offset from the box centre (CSS px)."""
    xs, ys = [q[0] for q in quad], [q[1] for q in quad]
    x0, y0 = min(xs), min(ys)
    W, H = max(1, math.ceil((max(xs) - x0) * scale)), max(1, math.ceil((max(ys) - y0) * scale))
    dst = [((qx - x0) * scale, (qy - y0) * scale) for qx, qy in quad]
    src = [(0, 0), (img.width, 0), (img.width, img.height), (0, img.height)]
    out = img.convert("RGBA").transform((W, H), Image.Transform.PERSPECTIVE, _coeffs(dst, src), Image.Resampling.BICUBIC)
    return out, x0, y0


# -------------------------------------------------------------- composing
def scaled(img: Image.Image, w: int, h: int) -> Image.Image:
    w, h = max(1, int(round(w))), max(1, int(round(h)))
    if (w, h) == img.size:
        return img
    return img.resize((w, h), Image.Resampling.LANCZOS)


def render_box(ctx: MediaContext, w: float, h: float, scale: float, background: str | None, image: Image.Image | None,
               rect: tuple[float, float, float, float] | None, tile: tuple[Image.Image, float] | None = None) -> Image.Image:
    """The content of a layer box drawn like the browser does (box px × scale)."""
    W, H = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if background:
        c = parse_rgba(background)
        if c:
            from behance_studio.design.color import parse_hex

            r, g, b = parse_hex(c[0]) or (0, 0, 0)
            canvas.paste(Image.new("RGBA", (W, H), (r, g, b, int(round(c[1] * 255)))), (0, 0))
    if tile is not None:
        timg, size = tile
        tw = max(1, int(round(size * scale)))
        th = max(1, int(round(timg.height * tw / timg.width)))
        t = scaled(timg.convert("RGBA"), tw, th)
        for ty in range(0, H, th):
            for tx in range(0, W, tw):
                canvas.alpha_composite(t, (tx, ty))
    if image is not None and rect is not None:
        x, y, rw, rh = rect
        sx, sy = int(math.floor(x * scale)), int(math.floor(y * scale))
        ew = int(math.ceil((x + rw) * scale)) - sx
        eh = int(math.ceil((y + rh) * scale)) - sy
        # Only the visible part is resampled (zoomed details stay cheap).
        vx0, vy0 = max(0, sx), max(0, sy)
        vx1, vy1 = min(W, sx + ew), min(H, sy + eh)
        if vx1 > vx0 and vy1 > vy0:
            fx, fy = image.width / ew, image.height / eh
            box = ((vx0 - sx) * fx, (vy0 - sy) * fy, (vx1 - sx) * fx, (vy1 - sy) * fy)
            part = image.convert("RGBA").resize((vx1 - vx0, vy1 - vy0), Image.Resampling.LANCZOS, box=box)
            canvas.alpha_composite(part, (vx0, vy0))
    return canvas


def apply_mask(img: Image.Image, mask: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    alpha = np.asarray(img.getchannel("A")).astype(np.uint16) * np.asarray(mask.resize(img.size)).astype(np.uint16) // 255
    img.putalpha(Image.fromarray(alpha.astype(np.uint8), "L"))
    return img


def tint_silhouette(img: Image.Image, color: str) -> Image.Image:
    """A strictly single-colour mark recoloured (CSS mask with the image alpha)."""
    c = parse_rgba(color) or ("#000000", 1.0)
    from behance_studio.design.color import parse_hex

    r, g, b = parse_hex(c[0]) or (0, 0, 0)
    alpha = img.convert("RGBA").getchannel("A")
    if c[1] < 1:
        alpha = Image.fromarray((np.asarray(alpha).astype(np.float32) * c[1]).round().astype(np.uint8), "L")
    out = Image.new("RGBA", img.size, (r, g, b, 255))
    out.putalpha(alpha)
    return out


def crop_for_picture(img: Image.Image, rect: tuple[float, float, float, float], bw: float, bh: float, density: float) -> tuple[Image.Image, tuple[float, float, float, float]]:
    """A right-sized copy of the image and the crop that shows the box.

    ``rect`` is the whole image's rectangle relative to the box (it may be
    larger than the box: cover/zoom). Hidden parts are kept (adjustable crop)
    unless they are most of the image, in which case a margin is kept."""
    x, y, rw, rh = rect
    # visible part of the image rect, as fractions of the image
    l, t = max(0.0, -x / rw), max(0.0, -y / rh)
    r, b = max(0.0, (x + rw - bw) / rw), max(0.0, (y + rh - bh) / rh)
    visible = (1 - l - r) * (1 - t - b)
    src = img
    if visible < 0.4:  # mostly hidden: keep the visible part plus a margin
        m = 0.12
        L, T = max(0.0, l - m * (1 - l - r)), max(0.0, t - m * (1 - t - b))
        R, B = max(0.0, r - m * (1 - l - r)), max(0.0, b - m * (1 - t - b))
        box = (int(L * img.width), int(T * img.height), int(math.ceil((1 - R) * img.width)), int(math.ceil((1 - B) * img.height)))
        src = img.crop(box)
        cw, ch = src.width, src.height
        l = (l * img.width - box[0]) / cw
        t = (t * img.height - box[1]) / ch
        r = (box[2] - (1 - r) * img.width) / cw
        b = (box[3] - (1 - b) * img.height) / ch
        rw, rh = rw * cw / img.width, rh * ch / img.height
    # pixels needed: the displayed size of the (whole) image × density
    f = min(1.0, density * rw / src.width, MAX_EDGE / max(src.width, src.height))
    if f < 0.999:
        src = scaled(src, src.width * f, src.height * f)
    return src, (max(0.0, l), max(0.0, t), max(0.0, r), max(0.0, b))
