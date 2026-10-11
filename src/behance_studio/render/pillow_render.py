"""Approximate raster renderer using Pillow (no browser required).

Used for proposal thumbnails when no Chromium-based browser is available and
for quick previews in tests. It draws the same geometry with the same fonts,
but is not used for final exports (those always go through Chromium).
"""

from __future__ import annotations

import re

from PIL import Image, ImageDraw

from behance_studio.assets.derivatives import load_visual, thumbnail_path
from behance_studio.core.logging_setup import get_logger
from behance_studio.design import color as C
from behance_studio.layout import text as T
from behance_studio.layout.model import Block, Presentation, Section

log = get_logger(__name__)


def _rgb(value: str | None, default=(255, 255, 255)) -> tuple[int, int, int] | None:
    if not value:
        return None
    if value.startswith("#"):
        return C.parse_hex(value) or default
    m = re.search(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", value)
    if m and "linear" not in value and "radial" not in value:
        return tuple(int(x) for x in m.groups())  # type: ignore[return-value]
    m = re.search(r"#[0-9A-Fa-f]{6}", value)
    if m:
        return C.parse_hex(m.group(0))
    return None


class PillowRenderer:
    def __init__(self, project, scale: float) -> None:
        self.project = project
        self.scale = scale
        self._cache: dict[tuple[str, int], Image.Image] = {}

    def _source(self, asset_id: str, edge: int) -> Image.Image | None:
        bucket = 512 if edge <= 512 else 1200
        key = (asset_id, bucket)
        if key in self._cache:
            return self._cache[key]
        asset = self.project.get_asset(asset_id)
        if asset is None:
            return None
        try:
            if bucket <= 512 and thumbnail_path(self.project, asset):
                img = Image.open(thumbnail_path(self.project, asset))
                img.load()
                img = img.convert("RGBA")
            else:
                img, _ = load_visual(self.project, asset, max_size=bucket)
                img = img.convert("RGBA")
        except Exception as exc:  # noqa: BLE001
            log.debug("Thumbnail source failed: %s", exc)
            return None
        self._cache[key] = img
        return img

    def _media(self, canvas: Image.Image, b: Block) -> None:
        s = self.scale
        x, y, w, h = int(b.x * s), int(b.y * s), max(1, int(b.w * s)), max(1, int(b.h * s))
        if b.mat:
            fill = _rgb(b.mat)
            if fill:
                ImageDraw.Draw(canvas).rectangle([x, y, x + w, y + h], fill=fill)
        pad = int(b.pad * s)
        iw, ih = max(1, w - 2 * pad), max(1, h - 2 * pad)
        src = self._source(b.asset_id or "", max(iw, ih))
        if src is None:
            ImageDraw.Draw(canvas).rectangle([x, y, x + w, y + h], fill=(200, 200, 200))
            return
        sw, sh = src.size
        if b.fit == "cover":
            scale = max(iw / sw, ih / sh)
            nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
            img = src.resize((nw, nh), Image.Resampling.BILINEAR)
            ox = int((nw - iw) * b.focal[0] / 100)
            oy = int((nh - ih) * b.focal[1] / 100)
            img = img.crop((ox, oy, ox + iw, oy + ih))
            px, py = x + pad, y + pad
        else:
            scale = min(iw / sw, ih / sh)
            nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
            img = src.resize((nw, nh), Image.Resampling.BILINEAR)
            px, py = x + pad + (iw - nw) // 2, y + pad + (ih - nh) // 2
        if b.radius:
            mask = Image.new("L", img.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], radius=int(b.radius * s), fill=255)
            alpha = img.getchannel("A") if img.mode == "RGBA" else Image.new("L", img.size, 255)
            from PIL import ImageChops

            img.putalpha(ImageChops.multiply(alpha, mask))
        canvas.paste(img, (px, py), img if img.mode == "RGBA" else None)

    def _shape(self, canvas: Image.Image, b: Block) -> None:
        s = self.scale
        box = [b.x * s, b.y * s, (b.x + b.w) * s, (b.y + b.h) * s]
        draw = ImageDraw.Draw(canvas)
        fill = _rgb(b.fill) if b.fill and b.fill != "transparent" else None
        outline = _rgb(b.stroke) if b.stroke else None
        width = max(1, int(b.stroke_width * s)) if outline else 0
        if b.shape in ("circle", "ring"):
            draw.ellipse(box, fill=None if b.shape == "ring" else fill, outline=outline, width=width)
        elif b.radius:
            draw.rounded_rectangle(box, radius=b.radius * s, fill=fill, outline=outline, width=width)
        else:
            draw.rectangle(box, fill=fill, outline=outline, width=width)

    def _text(self, canvas: Image.Image, b: Block) -> None:
        st = b.style
        if st is None:
            return
        s = self.scale
        px = max(1, int(round(st.size * s)))
        font = T.font_at(st.family, st.weight, px, st.size, st.italic, st.stretch)
        ascent, descent = font.getmetrics()
        color = _rgb(st.color, (0, 0, 0)) or (0, 0, 0)
        draw = ImageDraw.Draw(canvas)
        y = b.y * s
        line_h = st.line_px * s
        for line in b.lines:
            if line == "":
                y += line_h * b.para_gap
                continue
            width = T.line_width(line, st) * s
            if b.align == "center":
                x = b.x * s + (b.w * s - width) / 2
            elif b.align == "right":
                x = b.x * s + b.w * s - width
            else:
                x = b.x * s
            ty = y + (line_h - (ascent + descent)) / 2
            if b.role == "marquee":
                x = b.x * s
            kwargs = {}
            if st.stroke:
                kwargs = {"stroke_width": max(1, int(px / 60)), "stroke_fill": _rgb(st.stroke, (0, 0, 0))}
            if st.tracking:
                cx = x
                for ch in line:
                    draw.text((cx, ty), ch, font=font, fill=None if st.stroke else color, **kwargs)
                    cx += font.getlength(ch) + st.tracking * st.size * s
            else:
                draw.text((x, ty), line, font=font, fill=None if st.stroke else color, **kwargs)
            y += line_h

    def section(self, section: Section, width: int) -> Image.Image:
        s = self.scale
        bg = _rgb(section.gradient) or _rgb(section.background) or (255, 255, 255)
        canvas = Image.new("RGB", (max(1, int(width * s)), max(1, int(section.height * s))), bg)
        for b in sorted(section.blocks, key=lambda b: b.z):
            try:
                if b.kind == "shape":
                    self._shape(canvas, b)
                elif b.kind in ("image", "video"):
                    self._media(canvas, b)
                elif b.kind == "text":
                    self._text(canvas, b)
            except Exception as exc:  # noqa: BLE001 - thumbnails are best effort
                log.debug("Pillow render block failed: %s", exc)
        return canvas

    def presentation(self, pres: Presentation, max_height: int | None = None) -> Image.Image:
        parts = []
        total = 0
        for section in pres.sections:
            img = self.section(section, pres.width)
            parts.append(img)
            total += img.height
            if max_height and total >= max_height:
                break
        out = Image.new("RGB", (int(pres.width * self.scale), sum(p.height for p in parts)))
        y = 0
        for p in parts:
            out.paste(p, (0, y))
            y += p.height
        return out
