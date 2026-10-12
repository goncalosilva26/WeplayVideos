"""Design Spec → scene of editable primitives.

The conversion reads the same layer properties the HTML renderer reads
(:mod:`behance_studio.render.html`), so the Canva version reproduces the
presentation the user saw:

* text layers → one text box each, with the exact line breaks, font family,
  size, weight (regular/bold), italic, colour, opacity, letter spacing,
  line height, alignment, rotation and outline;
* shapes → rectangles, rounded rectangles and ellipses with solid or
  gradient fills, borders, opacity, rotation and shadows;
* images and video posters → pictures with their crop (cover/contain,
  focal point, zoom), padding mats, corner masks, shadows and rotation;
  device frames are rebuilt from shapes around the picture;
* section backgrounds → one rectangle (or gradient picture) per section.

Two modes: ``exact`` (default) draws masks and gradients into the picture
they belong to, so the result looks the same everywhere; ``editable`` keeps
them as native PowerPoint shape properties where they exist (corner masks,
linear gradients), which some editors may display differently.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from behance_studio.canva import media as M
from behance_studio.canva.css import parse_fill, parse_rgba, solid_color
from behance_studio.canva.model import Element, Gradient, Line, Picture, Scene, SceneSection, Shadow, Solid, TextFrame
from behance_studio.design.typography import get_font
from behance_studio.layout.devices import browser_bar, screen_rect
from behance_studio.layout.model import Block, Presentation, Section
from behance_studio.render.html import DROP_SHADOWS, SHADOWS

MODES = ("exact", "editable")
EDGE_SOFT = "0 24px 48px -24px rgba(0,0,0,.38)"
DEVICE_COLORS = {"phone": "#121214", "tablet": "#1B1B1D", "browser": "#FFFFFF", "frame": "#1D1A17"}


@dataclass
class BuildOptions:
    mode: str = "exact"  # exact | editable
    density: float = 2.0  # picture pixels per design pixel (capped by the source)
    section_ids: list[str] | None = None


# ------------------------------------------------------------------ helpers
_SHADOW_RE = re.compile(r"(-?[\d.]+)(?:px)?\s+(-?[\d.]+)(?:px)?\s+(-?[\d.]+)(?:px)?(?:\s+(-?[\d.]+)(?:px)?)?\s+(rgba?\([^)]*\)|#[0-9a-fA-F]{3,8}|[a-z]+)")


def css_shadow(css: str | None) -> Shadow | None:
    """The dominant (first) layer of a CSS box-/drop-shadow."""
    if not css:
        return None
    m = _SHADOW_RE.search(css)
    if not m:
        return None
    dx, dy, blur = float(m.group(1)), float(m.group(2)), float(m.group(3))
    spread = float(m.group(4)) if m.group(4) else 0.0
    color = parse_rgba(m.group(5)) or ("#000000", 0.3)
    kind = "glow" if dx == 0 and dy == 0 and blur > 0 else "outer"
    return Shadow(kind, dx, dy, blur, spread, color[0], color[1])


def block_shadow(b: Block, drop: bool) -> Shadow | None:
    if b.shadow == "hard":
        k = max(8.0, min(24.0, min(b.w, b.h) * 0.03))
        c = parse_rgba(b.shadow_color or "rgba(0,0,0,.85)") or ("#000000", 0.85)
        return Shadow("outer", k, k, 0.0, 0.0, c[0], c[1])
    if not b.shadow:
        return None
    return css_shadow((DROP_SHADOWS if drop else SHADOWS).get(b.shadow, ""))


def gradient_image(g: Gradient, w: int, h: int) -> Image.Image:
    """Rasterise a CSS gradient (premultiplied sRGB interpolation)."""
    from behance_studio.design.color import parse_hex

    w, h = max(1, w), max(1, h)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    xs, ys = (xs + 0.5) / w, (ys + 0.5) / h
    if g.kind == "linear":
        a = math.radians(g.angle)
        dx, dy = math.sin(a), -math.cos(a)
        length = abs(w * dx) + abs(h * dy)
        t = ((xs - 0.5) * w * dx + (ys - 0.5) * h * dy) / max(length, 1e-6) + 0.5
    else:
        t = np.sqrt(((xs - g.cx) / max(g.rx, 1e-6)) ** 2 + ((ys - g.cy) / max(g.ry, 1e-6)) ** 2)
    t = np.clip(t, 0, 1)
    pos = np.array([s.pos for s in g.stops], dtype=np.float32)
    cols = np.array([[*(np.array(parse_hex(s.color) or (0, 0, 0)) / 255.0 * s.alpha), s.alpha] for s in g.stops], dtype=np.float32)
    out = np.empty((h, w, 4), dtype=np.float32)
    for c in range(4):
        out[..., c] = np.interp(t, pos, cols[:, c])
    alpha = out[..., 3:4]
    rgb = np.where(alpha > 1e-6, out[..., :3] / np.maximum(alpha, 1e-6), 0)
    rgba = np.concatenate([rgb, alpha], axis=-1)
    return Image.fromarray((np.clip(rgba, 0, 1) * 255).round().astype(np.uint8), "RGBA")


def _geometry(radii) -> tuple[str, float]:
    if radii == "ellipse":
        return "ellipse", 0.0
    tl, tr, br, bl = radii
    if max(radii) <= 0.01:
        return "rect", 0.0
    if tl > 0 and tr > 0 and br <= 0.01 and bl <= 0.01:
        return "round2SameRect", tl
    return "roundRect", max(radii)


def _rotate_about(el: Element, cx: float, cy: float, angle: float) -> None:
    """Rotate a child element with its container (around the container centre)."""
    if not angle:
        return
    a = math.radians(angle)
    ex, ey = el.x + el.w / 2 - cx, el.y + el.h / 2 - cy
    nx, ny = ex * math.cos(a) - ey * math.sin(a), ex * math.sin(a) + ey * math.cos(a)
    el.x, el.y = cx + nx - el.w / 2, cy + ny - el.h / 2
    el.rotation = (el.rotation + angle + 180) % 360 - 180


def _overlaps(a: Block, b: Block) -> bool:
    ax0, ay0, ax1, ay1 = a.bounds()
    bx0, by0, bx1, by1 = b.bounds()
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


# ------------------------------------------------------------------ builder
class SceneBuilder:
    def __init__(self, project, presentation: Presentation, options: BuildOptions, workdir: Path) -> None:
        self.project = project
        self.pres = presentation
        self.opt = options
        self.ctx = M.MediaContext(project, workdir, density=options.density)
        self.elements: list[Element] = []
        self.fonts: dict[str, set[int]] = {}
        self.notes: list[str] = []
        self._section: Section | None = None
        self._index = 0
        self._oy = 0.0

    @property
    def exact(self) -> bool:
        return self.opt.mode != "editable"

    def build(self) -> Scene:
        sections = self.pres.sections
        if self.opt.section_ids:
            wanted = set(self.opt.section_ids)
            sections = [s for s in sections if s.id in wanted or s.plan_id in wanted] or sections
        out_sections = []
        y = 0.0
        for index, section in enumerate(sections):
            self._section, self._index, self._oy = section, index, y
            start = len(self.elements)
            self._background(section)
            for b in sorted(section.blocks, key=lambda blk: blk.z):  # stable: equal z keep spec order
                if b.kind == "text":
                    self._text(b)
                elif b.kind == "shape":
                    self._shape(b)
                elif b.kind in ("image", "video"):
                    self._media(b)
            self._clip_to_section(self.elements[start:], y, y + section.height)
            out_sections.append(SceneSection(index, section.id, section.title or section.type.replace("_", " ").title(), section.type, y,
                                             section.height, solid_color(section.gradient or section.background, self.pres.page_background)))
            y += section.height
        return Scene(self.pres.width, y, self.pres.title, self.elements, out_sections, self.fonts, self.notes)

    # ------------------------------------------------------------ common
    def _add(self, el: Element, b: Block | None = None, role: str = "") -> Element:
        el.section = self._index
        if b is not None:
            el.block_id = b.id
        el.role = role or el.role
        if not el.name:
            el.name = self._name(b, el)
        self.elements.append(el)
        return el

    def _name(self, b: Block | None, el: Element) -> str:
        title = (self._section.title if self._section else "") or (self._section.type if self._section else "")
        what = {"text": "Text", "image": "Image", "rect": "Shape", "ellipse": "Shape"}.get(el.kind, el.kind)
        if b is not None and b.kind == "text" and b.role:
            what = f"Text ({b.role})"
        elif el.role == "background":
            what = "Background"
        elif b is not None and b.asset_id:
            asset = self.project.get_asset(b.asset_id) if self.project is not None else None
            if asset is not None:
                what = f"Image {asset.filename}"
        return f"{self._index + 1:02d} {title} · {what}"[:120]

    def _backdrop(self, b: Block) -> str | None:
        """The plain colour behind ``b`` (None when other layers are behind it)."""
        sec = self._section
        if sec is None or sec.gradient or "gradient" in (sec.background or ""):
            return None
        for other in sorted(sec.blocks, key=lambda blk: blk.z):  # drawing order
            if other is b:
                return sec.background
            if _overlaps(other, b):
                return None
        return sec.background

    def _scale(self, w: float, h: float, src_px_per_css: float = 1e9) -> float:
        return max(0.25, min(self.opt.density, max(1.0, src_px_per_css), M.MAX_EDGE / max(w, h, 1)))

    def _picture(self, img: Image.Image, key: str, asset_id: str | None = None, crop=(0.0, 0.0, 0.0, 0.0), baked=None) -> Picture:
        path, pw, ph = self.ctx.save(img, key)
        return Picture(path, crop, pw, ph, asset_id, list(baked or []))

    # -------------------------------------------------------- backgrounds
    def _background(self, section: Section) -> None:
        value = section.gradient or section.background
        fill = parse_fill(value) or Solid(solid_color(self.pres.page_background))
        el = Element("rect", 0.0, self._oy, float(self.pres.width), float(section.height), role="background")
        if isinstance(fill, Gradient) and (self.exact or fill.kind == "radial"):
            img = gradient_image(fill, int(round(self.pres.width)), int(round(section.height))).convert("RGB")
            el.kind = "image"
            el.picture = self._picture(img, f"bg|{value}|{self.pres.width}|{section.height}", baked=["gradient"])
            el.fill = Solid(fill.stops[-1].color)  # representative colour (fillers, reports)
            el.notes.append("background gradient drawn as a picture")
        else:
            el.fill = fill
        self._add(el, role="background")

    # --------------------------------------------------------------- text
    def _text(self, b: Block) -> None:
        from behance_studio.layout.text import line_width

        st = b.style
        if st is None or not any(line.strip() for line in b.lines):
            return
        fam = get_font(st.family)
        weight = fam.clamp_weight(st.weight)
        color = parse_rgba(st.color) or ("#111111", 1.0)
        notes = []
        rgb, alpha = color[0], color[1] * (st.opacity if st.opacity < 1 else 1.0)
        if b.blend and b.blend != "normal":
            backdrop = self._backdrop(b)
            mixed = M.blend_color(rgb, b.blend, backdrop) if backdrop else None
            if mixed:
                rgb = mixed
                notes.append(f"'{b.blend}' blend applied to the text colour")
            else:
                notes.append(f"'{b.blend}' blend not reproduced (no editable equivalent over a mixed background)")
        frame = TextFrame(
            lines=list(b.lines), family=fam.name, size=st.size, weight=weight, italic=st.italic, color=rgb, alpha=alpha,
            tracking=st.tracking, line_px=st.line_px, gap_px=st.line_px * b.para_gap, align=b.align,
            single_line=b.role == "marquee",
        )
        if st.stroke:
            frame.stroke = st.stroke
            frame.stroke_px = max(1.0, st.size / 60)
            notes.append("outlined type exported as a text outline")
        if weight not in (400, 700):
            notes.append(f"{fam.name} weight {weight} shown as {'bold' if weight >= 600 else 'regular'}")
        if st.stretch != 100:
            notes.append(f"{fam.name} width {st.stretch}% shown at normal width")
        self.fonts.setdefault(fam.name, set()).add(weight)
        # Widths as the file will show them: PowerPoint/Canva use regular or bold.
        stored = st.with_(weight=fam.clamp_weight(700 if weight >= 600 else 400), stretch=100)
        natural_w = _natural_width(b, stored) if b.role in NATURAL_ROLES else None
        if natural_w is not None:
            frame.natural = True  # paragraphs wrap at a width that gives the designed lines
            new_w = natural_w
            shift = {"left": (new_w - b.w) / 2, "center": 0.0, "right": -(new_w - b.w) / 2}.get(b.align, 0.0)
        else:
            # Designed line breaks: the box never wraps and leaves room for wider
            # metrics in other text engines (within the page).
            texts = [" ".join(t for t in b.lines if t)] if frame.single_line else [t for t in b.lines if t]
            widest = max((max(line_width(t, st), line_width(t, stored)) for t in texts), default=0.0)
            width = max(b.w, widest)
            room = {"left": self.pres.width - b.x - width, "right": b.x + b.w - width,
                    "center": 2 * min(b.x, self.pres.width - b.x - b.w)}.get(b.align, 0.0)
            extra = max(0.0, min(max(0.12 * width, 1.0 * st.size), room)) if not b.rotate else max(0.12 * width, st.size)
            new_w = width + extra
            shift = {"left": (new_w - b.w) / 2, "center": 0.0, "right": -(new_w - b.w) / 2}.get(b.align, 0.0)
        cx, cy = b.x + b.w / 2, self._oy + b.y + b.h / 2
        if b.rotate:
            a = math.radians(b.rotate)
            cx, cy = cx + shift * math.cos(a), cy + shift * math.sin(a)
        else:
            cx += shift
        el = Element("text", cx - new_w / 2, cy - b.h / 2, new_w, b.h, rotation=b.rotate, text=frame, notes=notes)
        self._add(el, b, "text")

    # -------------------------------------------------------------- shapes
    def _shape(self, b: Block) -> None:
        x, y, w, h = b.x, self._oy + b.y, b.w, b.h
        radii = "ellipse" if b.shape in ("circle", "ring") else M.corner_radii(None, b.radius, w, h)
        if b.clip or (b.radius and b.shape not in ("circle", "ring")):
            radii = M.corner_radii(b.clip, b.radius, w, h)
        fill = parse_fill(b.fill) if b.fill and b.shape != "ring" else None
        notes = []
        if b.filter and isinstance(fill, Solid):
            px = M.apply_filter(Image.new("RGB", (1, 1), fill.color), b.filter).getpixel((0, 0))
            fill = Solid("#{:02X}{:02X}{:02X}".format(*px[:3]), fill.alpha)
        if b.blend and b.blend != "normal" and isinstance(fill, Solid):
            backdrop = self._backdrop(b)
            mixed = M.blend_color(fill.color, b.blend, backdrop) if backdrop else None
            if mixed:
                fill = Solid(mixed, fill.alpha)
            else:
                notes.append(f"'{b.blend}' blend not reproduced")
        line = None
        if b.shape == "ring" or b.stroke:
            c = parse_rgba(b.stroke or b.fill) or ("#000000", 1.0)
            line = Line(c[0], max(1.0, b.stroke_width), c[1])
        shadow = block_shadow(b, drop=False)
        bake = bool(b.fill_asset or b.fade or b.perspective or (isinstance(fill, Gradient) and (self.exact or fill.kind == "radial")))
        if bake:
            scale = self._scale(w, h, 1.0 if not b.fill_asset else 2.0)
            tile = None
            if b.fill_asset:
                src = self.ctx.source(b.fill_asset)
                if src is not None:
                    tile = (src[0], b.fill_size or 240.0)
                notes.append("pattern fill drawn as a picture")
            if isinstance(fill, Gradient):
                canvas = gradient_image(fill, int(round(w * scale)), int(round(h * scale)))
                notes.append("gradient drawn as a picture")
            else:
                canvas = M.render_box(self.ctx, w, h, scale, b.fill if isinstance(fill, Solid) else None, None, None, tile)
            if M.has_radius(radii):
                canvas = M.apply_mask(canvas, M.mask_image(canvas.width, canvas.height, radii, scale))
            el = self._baked(b, canvas, scale, x, y, w, h, f"shape|{b.id}|{b.fill}|{b.fill_asset}|{w}|{h}|{radii}|{b.fade}|{b.perspective}")
            el.line, el.shadow, el.opacity = line, shadow, b.opacity
            el.notes += notes
            self._add(el, b, "shape")
            return
        geometry, radius = _geometry(radii)
        if line is not None:  # CSS borders are drawn inside the box; PowerPoint lines are centred
            k = line.width / 2
            x, y, w, h = x + k, y + k, max(0.5, w - 2 * k), max(0.5, h - 2 * k)
            radius = max(0.0, radius - k)
        el = Element("ellipse" if geometry == "ellipse" else "rect", x, y, w, h, rotation=b.rotate, opacity=b.opacity, fill=fill,
                     line=line, geometry=geometry, radius=radius, shadow=shadow, notes=notes)
        self._add(el, b, "shape")

    def _baked(self, b: Block, canvas: Image.Image, scale: float, x: float, y: float, w: float, h: float, key: str,
               asset_id: str | None = None, baked: list[str] | None = None, rotate: bool = True) -> Element:
        """A layer drawn into a picture (fade and perspective applied here).
        ``rotate=False``: the caller rotates the element with its container."""
        baked = list(baked or [])
        if b.fade:
            canvas = M.apply_mask(canvas, M.fade_mask(canvas.width, canvas.height, b.fade))
            baked.append(f"{b.fade} edge fade")
        rotation = b.rotate if rotate else 0.0
        if b.perspective:
            quad = M.perspective_quad(w, h, b.perspective[0], b.perspective[1], b.rotate)
            canvas, ox, oy = M.warp_perspective(canvas, quad, scale)
            cx, cy = x + w / 2, y + h / 2
            x, y = cx + ox, cy + oy
            w, h = canvas.width / scale, canvas.height / scale
            rotation = 0.0
            baked.append("perspective tilt")
        pic = self._picture(canvas, f"{key}|{scale}|{b.fade}|{b.perspective}|{b.rotate}", asset_id, baked=baked)
        el = Element("image", x, y, w, h, rotation=rotation, picture=pic)
        if baked:
            el.notes.append("drawn into the picture: " + ", ".join(baked))
        return el

    # --------------------------------------------------------------- media
    def _media(self, b: Block) -> None:
        X, Y, W, H = b.x, self._oy + b.y, b.w, b.h
        cx, cy = X + W / 2, Y + H / 2
        children: list[Element] = []
        notes: list[str] = []
        src = self.ctx.source(b.asset_id) if b.asset_id else None
        if b.kind == "video":
            notes.append("video shown as its poster frame (add the video in Canva if needed)")
        drop = bool(b.tint or b.meta.get("alpha"))
        shadow = block_shadow(b, drop)
        if shadow is None and b.edge == "soft":
            shadow = css_shadow(EDGE_SOFT)
        outline = None
        if b.edge == "outline" and not (b.shadow and not drop):
            c = parse_rgba(b.edge_color or "rgba(0,0,0,.12)") or ("#000000", 0.12)
            outline = Line(c[0], 1.0, c[1])
        if b.clip or b.radius:
            radii = M.corner_radii(b.clip, b.radius, W, H)
        elif b.device:
            r = screen_rect(b.device, W, H).outer_radius
            radii = (r, r, r, r)
        else:
            radii = (0.0, 0.0, 0.0, 0.0)
        if src is not None and shadow is not None and not drop and not b.mat and not b.device and _transparent(src):
            # CSS box-shadow of a transparent box is the box's shape, drawn outside it;
            # a picture shadow would follow the artwork instead.
            children += self._box_shadow(shadow, X, Y, W, H, radii, f"{b.id}|{b.shadow}")
            shadow = None
        if src is None:
            el = Element("rect", X, Y, W, H, fill=Solid(solid_color(b.mat or "#E6E6E6")), notes=["image file missing: grey placeholder"])
            children.append(el)
        elif b.device:
            children += self._device(b, src, X, Y, W, H, radii, shadow, outline, notes)
        elif b.tint:
            children += self._tinted(b, src, X, Y, W, H, radii, shadow, notes)
        else:
            children += self._plain_media(b, src, X, Y, W, H, radii, shadow, outline, notes)
        primary = next((e for e in reversed(children) if e.kind == "image"), children[-1])
        primary.notes += [n for n in notes if n not in primary.notes]
        for el in children:
            if b.opacity < 1:
                el.opacity *= b.opacity
            tilted = el.picture is not None and "perspective tilt" in el.picture.baked  # rotation drawn in
            if b.rotate and not tilted:
                _rotate_about(el, cx, cy, b.rotate)
            self._add(el, b, el.role or "media")

    def _box_shadow(self, s: Shadow, X: float, Y: float, W: float, H: float, radii, key: str) -> list[Element]:
        """The shadow of a transparent box as its own element(s), behind it."""
        color = Solid(s.color, s.alpha)
        if s.kind == "outer" and s.blur <= 0.01 and not M.has_radius(radii) and not s.spread:
            dx, dy = s.dx, s.dy  # hard offset shadow: the visible part is two strips
            out = []
            if dx > 0:
                out.append(Element("rect", X + W, Y + max(0.0, dy), dx, H - max(0.0, dy) + max(0.0, dy), fill=color, role="shadow"))
            if dy > 0:
                out.append(Element("rect", X + max(0.0, dx), Y + H, W - max(0.0, dx), dy, fill=color, role="shadow"))
            for el in out:
                el.notes.append("box shadow of a transparent image drawn as shapes")
            return out
        grow = s.blur + abs(s.spread) + 2
        x0, y0 = min(0.0, s.dx - grow), min(0.0, s.dy - grow)
        x1, y1 = max(W, W + s.dx + grow), max(H, H + s.dy + grow)
        scale = 2.0 if s.blur < 4 else 1.0
        cw, ch = int(math.ceil((x1 - x0) * scale)), int(math.ceil((y1 - y0) * scale))
        from PIL import ImageFilter

        sw, sh = max(1, int(round((W + 2 * s.spread) * scale))), max(1, int(round((H + 2 * s.spread) * scale)))
        r_shadow = radii if radii == "ellipse" else tuple(max(0.0, r + s.spread) if r else 0.0 for r in radii)
        shape = M.mask_image(sw, sh, r_shadow, scale)
        alpha = Image.new("L", (cw, ch), 0)
        alpha.paste(shape, (int(round((s.dx - s.spread - x0) * scale)), int(round((s.dy - s.spread - y0) * scale))))
        if s.blur > 0:
            alpha = alpha.filter(ImageFilter.GaussianBlur(s.blur * scale / 2))
        hole = Image.new("L", (cw, ch), 0)
        hole.paste(M.mask_image(max(1, int(round(W * scale))), max(1, int(round(H * scale))), radii, scale), (int(round(-x0 * scale)), int(round(-y0 * scale))))
        a = np.asarray(alpha).astype(np.float32) * (1 - np.asarray(hole).astype(np.float32) / 255.0) * s.alpha
        from behance_studio.design.color import parse_hex

        rgba = np.zeros((ch, cw, 4), dtype=np.uint8)
        rgba[..., :3] = parse_hex(s.color) or (0, 0, 0)
        rgba[..., 3] = np.clip(a, 0, 255).round().astype(np.uint8)
        pic = self._picture(Image.fromarray(rgba, "RGBA"), f"boxshadow|{key}|{W}|{H}|{radii}|{s}", baked=["box shadow"])
        el = Element("image", X + x0, Y + y0, cw / scale, ch / scale, picture=pic, role="shadow",
                     notes=["box shadow of a transparent image drawn as a picture"])
        return [el]

    def _content(self, b: Block, src, bw: float, bh: float, fit: str, zoom: float) -> tuple[float, float, float, float]:
        img = src[0]
        return M.fit_rect(img.width, img.height, bw, bh, fit, b.focal, zoom if fit == "cover" else 1.0)

    def _plain_media(self, b, src, X, Y, W, H, radii, shadow, outline, notes) -> list[Element]:
        img, _alpha = src
        pad = b.pad if b.pad else 0.0
        bw, bh = max(1.0, W - 2 * pad), max(1.0, H - 2 * pad)
        rect = self._content(b, src, bw, bh, b.fit, b.zoom)
        backdrop = self._backdrop(b) if b.blend and b.blend != "normal" else None
        bake = bool(b.fade or b.perspective or b.filter or backdrop or (self.exact and M.has_radius(radii)))
        if b.blend and b.blend != "normal" and not backdrop:
            notes.append(f"'{b.blend}' blend not reproduced (layers behind it)")
        if bake:
            scale = self._scale(W, H, img.width / max(rect[2], 1.0))
            canvas = M.render_box(self.ctx, W, H, scale, b.mat, img, (rect[0] + pad, rect[1] + pad, rect[2], rect[3]))
            baked = []
            if b.filter:
                canvas = M.apply_filter(canvas, b.filter)
                baked.append(f"{b.filter} filter")
            if M.has_radius(radii):
                canvas = M.apply_mask(canvas, M.mask_image(canvas.width, canvas.height, radii, scale))
                baked.append("ellipse mask" if radii == "ellipse" else "rounded corners")
            if backdrop:
                mixed = M.blend_onto(canvas, b.blend, backdrop)
                if mixed is not None:
                    canvas = mixed
                    baked.append(f"{b.blend} blend")
            el = self._baked(b, canvas, scale, X, Y, W, H, f"media|{b.asset_id}|{W}|{H}|{rect}|{pad}|{b.mat}|{radii}|{b.filter}|{b.blend}|{backdrop}",
                             b.asset_id, baked, rotate=False)
            el.shadow, el.line = shadow, outline
            return [el]
        out = []
        geometry, radius = _geometry(radii)
        if b.mat:
            mat = parse_fill(b.mat)
            out.append(Element("ellipse" if geometry == "ellipse" else "rect", X, Y, W, H, fill=mat, geometry=geometry, radius=radius,
                               shadow=shadow, line=outline, role="mat"))
            shadow = outline = None
        x, y, rw, rh = rect
        if b.fit == "contain" or (rw <= bw + 0.01 and rh <= bh + 0.01):
            # The whole image is visible: the picture is the image rectangle.
            part = M.scaled(img, *(_fit_px(img, rw, rh, self.opt.density)))
            pic = self._picture(part, f"whole|{b.asset_id}|{part.size}", b.asset_id)
            el = Element("image", X + pad + x, Y + pad + y, rw, rh, picture=pic, shadow=shadow, line=outline)
            if not b.mat and geometry != "rect":
                el.geometry, el.radius = geometry, radius
        else:
            part, crop = M.crop_for_picture(img, rect, bw, bh, self.opt.density)
            pic = self._picture(part, f"crop|{b.asset_id}|{part.size}|{rect}|{bw}|{bh}", b.asset_id, crop)
            el = Element("image", X + pad, Y + pad, bw, bh, picture=pic, shadow=shadow, line=outline)
            if not b.mat and geometry != "rect":
                el.geometry, el.radius = geometry, radius
        out.append(el)
        return out

    def _tinted(self, b, src, X, Y, W, H, radii, shadow, notes) -> list[Element]:
        img, _alpha = src
        out = []
        if b.mat:
            geometry, radius = _geometry(radii)
            out.append(Element("ellipse" if geometry == "ellipse" else "rect", X, Y, W, H, fill=parse_fill(b.mat), geometry=geometry,
                               radius=radius, role="mat"))
        pad = b.pad or 0.0
        bw, bh = max(1.0, W - 2 * pad), max(1.0, H - 2 * pad)
        x, y, rw, rh = M.fit_rect(img.width, img.height, bw, bh, "contain", (50.0, 50.0))
        sil = M.tint_silhouette(M.scaled(img, *(_fit_px(img, rw, rh, self.opt.density))), b.tint or "#000")
        pic = self._picture(sil, f"tint|{b.asset_id}|{b.tint}|{sil.size}", b.asset_id, baked=["recoloured mark"])
        el = Element("image", X + pad + x, Y + pad + y, rw, rh, picture=pic, shadow=shadow, notes=["recoloured mark drawn as a picture"])
        out.append(el)
        return out

    def _device(self, b, src, X, Y, W, H, radii, shadow, outline, notes) -> list[Element]:
        img, _alpha = src
        dev = b.device or ""
        scr = screen_rect(dev, W, H)
        out = []
        body_color = b.device_color if b.device_color and dev != "browser" else DEVICE_COLORS.get(dev, "#111111")
        if dev == "browser":
            body_color = b.mat or "#FFFFFF"
        geometry, radius = _geometry(radii)
        out.append(Element("rect", X, Y, W, H, fill=parse_fill(body_color), geometry=geometry, radius=radius, shadow=shadow, line=outline,
                           role="frame", name=""))
        if dev == "browser":
            bar = browser_bar(W)
            bar_color = b.device_color or "#F3F3F1"
            r = radius if geometry != "rect" else 0.0
            out.append(Element("rect", X, Y, W, bar, fill=parse_fill(bar_color), geometry="round2SameRect" if r else "rect", radius=min(r, bar / 2),
                               role="frame"))
            dot = max(6.0, bar * 0.26)
            dx = X + bar * 0.5
            for c in ("#FF5F57", "#FEBC2E", "#28C840"):
                out.append(Element("ellipse", dx, Y + (bar - dot) / 2, dot, dot, fill=Solid(c), geometry="ellipse", role="frame"))
                dx += dot * 1.7
        sx, sy, sw, sh = X + scr.x, Y + scr.y, scr.w, scr.h
        if b.mat:
            out.append(Element("rect", sx, sy, sw, sh, fill=parse_fill(b.mat), geometry="roundRect" if scr.radius else "rect", radius=scr.radius,
                               role="mat"))
        pad = b.pad or 0.0
        bw, bh = max(1.0, sw - 2 * pad), max(1.0, sh - 2 * pad)
        rect = self._content(b, src, bw, bh, b.fit, b.zoom)
        sradii = (scr.radius,) * 4 if scr.radius else (0.0, 0.0, 0.0, 0.0)
        fills_box = rect[2] >= bw - 0.5 and rect[3] >= bh - 0.5 and not pad
        if self.exact and scr.radius and fills_box:
            scale = self._scale(sw, sh, img.width / max(rect[2], 1.0))
            canvas = M.render_box(self.ctx, sw, sh, scale, None, img, rect)
            canvas = M.apply_mask(canvas, M.mask_image(canvas.width, canvas.height, sradii, scale))
            if b.filter:
                canvas = M.apply_filter(canvas, b.filter)
            pic = self._picture(canvas, f"screen|{b.asset_id}|{sw}|{sh}|{rect}|{scr.radius}|{b.filter}|{scale}", b.asset_id, baked=["screen corners"])
            out.append(Element("image", sx, sy, sw, sh, picture=pic, role="media"))
        else:
            x, y, rw, rh = rect
            if b.fit == "contain" or (rw <= bw + 0.01 and rh <= bh + 0.01):
                part = M.scaled(img, *(_fit_px(img, rw, rh, self.opt.density)))
                part = M.apply_filter(part, b.filter)
                pic = self._picture(part, f"whole|{b.asset_id}|{part.size}|{b.filter}", b.asset_id)
                el = Element("image", sx + pad + x, sy + pad + y, rw, rh, picture=pic, role="media")
            else:
                part, crop = M.crop_for_picture(img, rect, bw, bh, self.opt.density)
                part = M.apply_filter(part, b.filter)
                pic = self._picture(part, f"crop|{b.asset_id}|{part.size}|{rect}|{bw}|{bh}|{b.filter}", b.asset_id, crop)
                el = Element("image", sx + pad, sy + pad, bw, bh, picture=pic, role="media")
                if scr.radius and fills_box:
                    el.geometry, el.radius = "roundRect", scr.radius
            out.append(el)
        if dev == "phone":
            iw, ih = W * 0.27, W * 0.075
            out.append(Element("rect", X + (W - iw) / 2, sy + W * 0.03, iw, ih, fill=Solid("#0B0B0C"), geometry="roundRect", radius=ih / 2, role="frame"))
        if b.fade or b.perspective:
            notes.append("device frame: fade/perspective not reproduced")
        return out

    # ------------------------------------------------------------- clipping
    def _clip_to_section(self, elements: list[Element], top: float, bottom: float) -> None:
        """Sections clip their layers (overflow: hidden): do the same."""
        keep = []
        for el in elements:
            x0, y0, x1, y1 = el.bounds()
            if y0 >= top - 0.5 and y1 <= bottom + 0.5:
                keep.append(el)
                continue
            if y1 <= top or y0 >= bottom:
                continue  # entirely outside its section: invisible in the original
            if el.splittable and el.kind in ("rect", "image"):
                clip_vertical(el, max(top, el.y), min(bottom, el.bottom))
            else:
                el.notes.append("extends beyond its section (the original clips it)")
            keep.append(el)
        removed = {id(e) for e in elements} - {id(e) for e in keep}
        if removed:
            self.elements = [e for e in self.elements if id(e) not in removed]


NATURAL_ROLES = {"body", "caption", "quote", "subtitle"}


NATURAL_MARGIN = 0.035  # wrapping must survive ±3.5 % metric differences


def _natural_width(b: Block, style) -> float | None:
    """A box width at which every paragraph wraps into exactly the designed
    lines (with a safety margin), or None to keep explicit line breaks."""
    from behance_studio.layout.text import line_width

    groups: list[list[str]] = [[]]
    for line in b.lines:
        if line == "":
            if groups[-1]:
                groups.append([])
        else:
            groups[-1].append(line)
    groups = [g for g in groups if g]
    if not groups or all(len(g) == 1 for g in groups):
        return None  # single lines: nothing to re-wrap
    widest, limit = 0.0, float("inf")
    for g in groups:
        for i, line in enumerate(g):
            if "  " in line or line != line.strip():
                return None
            widest = max(widest, line_width(line, style))
            if i + 1 < len(g):  # the next word must not fit on this line
                nxt = g[i + 1].split(" ")[0]
                limit = min(limit, line_width(f"{line} {nxt}", style))
    if limit == float("inf"):
        return None
    lo, hi = widest * (1 + NATURAL_MARGIN), limit * (1 - NATURAL_MARGIN)
    if lo > hi:
        return None
    return (lo + hi) / 2


def _transparent(src) -> bool:
    img, alpha = src
    return bool(alpha) and img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 250


def _fit_px(img: Image.Image, rw: float, rh: float, density: float) -> tuple[float, float]:
    """Pixel size for an image shown at rw × rh (never upscaled, capped)."""
    f = min(1.0, density * rw / img.width, M.MAX_EDGE / max(img.width, img.height))
    return img.width * f, img.height * f


def clip_vertical(el: Element, y0: float, y1: float) -> None:
    """Keep the part of a splittable element between y0 and y1 (absolute)."""
    if y1 - y0 < 0.01:
        el.h = 0.0
        return
    if el.picture is not None:
        l, t, r, b = el.picture.crop
        span = 1.0 - t - b  # fraction of the image shown over el.h
        top_cut = (y0 - el.y) / el.h * span
        bottom_cut = (el.bottom - y1) / el.h * span
        el.picture.crop = (l, t + max(0.0, top_cut), r, b + max(0.0, bottom_cut))
    if isinstance(el.fill, Gradient) and el.fill.kind == "linear" and el.fill.angle % 180 == 0:
        el.fill = _sub_gradient(el.fill, (y0 - el.y) / el.h, (y1 - el.y) / el.h)
    el.y, el.h = y0, y1 - y0


def _sub_gradient(g: Gradient, a: float, b: float) -> Gradient:
    """The part of a vertical linear gradient between fractions a..b of its box."""
    from behance_studio.canva.model import Stop

    flip = g.angle % 360 == 0  # "to top": positions run bottom→top
    lo, hi = (1 - b, 1 - a) if flip else (a, b)
    span = max(hi - lo, 1e-6)
    stops = [Stop(0.0, *g.color_at(lo))]
    stops += [Stop((s.pos - lo) / span, s.color, s.alpha) for s in g.stops if lo < s.pos < hi]
    stops.append(Stop(1.0, *g.color_at(hi)))
    return Gradient("linear", stops, angle=g.angle)


def build_scene(project, presentation: Presentation, options: BuildOptions | None = None, workdir: Path | None = None) -> Scene:
    import tempfile

    options = options or BuildOptions()
    workdir = workdir or Path(tempfile.mkdtemp(prefix="bs-canva-"))
    builder = SceneBuilder(project, presentation, options, workdir)
    scene = builder.build()
    scene.notes = builder.notes
    return scene
