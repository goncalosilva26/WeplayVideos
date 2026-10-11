"""Composition toolkit shared by the layout families.

The families decide *what* to compose (art direction); this module provides
precise, integrity-preserving building blocks: text blocks with exact line
breaking, image blocks with safe fitting, and arrangement algorithms
(justified rows, equal-height columns, masonry, uniform grids).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterable

from behance_studio.assets.analysis import region_luminance
from behance_studio.design import color as C
from behance_studio.design.direction import CreativeDirection
from behance_studio.layout import text as T
from behance_studio.layout.fitting import choose_fit, native_limit
from behance_studio.layout.model import Block, Section, TextStyle
from behance_studio.planning.copy import Copywriter
from behance_studio.planning.models import PresentationPlan, SectionPlan
from behance_studio.projects.models import MEDIA_VIDEO, AssetRecord


@dataclass
class ComposeContext:
    plan: PresentationPlan
    assets: dict[str, AssetRecord]
    direction: CreativeDirection
    width: int = 1400
    seed: int = 0
    creativity: float = 0.5
    overrides: dict[str, dict] = field(default_factory=dict)  # section plan id -> overrides

    @property
    def language(self) -> str:
        return self.plan.language

    @property
    def copy(self) -> Copywriter:
        return Copywriter(self.plan.language)


class SectionBuilder:
    def __init__(self, plan: SectionPlan, background: str, theme: str = "light", pattern: str = "") -> None:
        self.plan = plan
        self.background = background
        self.theme = theme
        self.pattern = pattern
        self.blocks: list[Block] = []
        self.y = 0.0
        self.breaks: list[float] = []
        self.gradient: str | None = None
        self.meta: dict = {}

    def add(self, block: Block | None) -> Block | None:
        if block is not None:
            self.blocks.append(block)
        return block

    def extend(self, blocks: Iterable[Block]) -> None:
        self.blocks.extend(blocks)

    def gap(self, px: float) -> None:
        self.y += px

    def mark_break(self, y: float | None = None) -> None:
        self.breaks.append(round(self.y if y is None else y, 2))

    def content_bottom(self) -> float:
        return max((b.bottom for b in self.blocks if not b.decorative), default=0.0)

    def finish(self, bottom_padding: float, min_height: float = 0.0, height: float | None = None) -> Section:
        h = height if height is not None else max(min_height, max(self.y, self.content_bottom()) + bottom_padding)
        h = round(h, 2)
        breaks = sorted({b for b in self.breaks if 0 < b < h - 1})
        return Section(
            type=self.plan.type,
            height=h,
            background=self.background,
            blocks=self.blocks,
            plan_id=self.plan.id,
            title=self.plan.title,
            theme=self.theme,
            pattern=self.pattern,
            breaks=breaks,
            gradient=self.gradient,
            meta=dict(self.meta),
        )


class Composer:
    """Stateful helper bound to one presentation being composed."""

    def __init__(self, ctx: ComposeContext, rng: random.Random) -> None:
        self.ctx = ctx
        self.W = ctx.width
        self.rng = rng
        self.k = ctx.width / 1400.0  # scale factor for all px design values
        self.palette = ctx.direction.palette
        self.copy = ctx.copy

    # ------------------------------------------------------------- utilities
    def px(self, value: float) -> float:
        return round(value * self.k, 2)

    def asset(self, asset_id: str) -> AssetRecord | None:
        return self.ctx.assets.get(asset_id)

    def aspect(self, asset_id: str) -> float:
        a = self.asset(asset_id)
        return a.aspect if a else 1.0

    def assets_of(self, plan: SectionPlan) -> list[str]:
        return [aid for aid in plan.asset_ids if aid in self.ctx.assets]

    def text_color(self, bg: str, preferred: str | None = None, minimum: float = 4.5) -> str:
        pal = self.palette
        candidates = [c for c in (preferred, pal.ink, pal.paper, "#111111", "#FFFFFF") if c]
        for c in candidates:
            if C.contrast_ratio(c, bg) >= minimum:
                return c
        return C.ensure_contrast(candidates[0], bg, minimum)

    def muted(self, fg: str, bg: str, amount: float = 0.35, minimum: float = 4.5) -> str:
        """A softer version of fg on bg that still meets contrast."""
        candidate = C.mix(fg, bg, amount)
        return candidate if C.contrast_ratio(candidate, bg) >= minimum else C.ensure_contrast(candidate, bg, minimum)

    def is_dark(self, bg: str) -> bool:
        return C.is_dark(bg)

    # ------------------------------------------------------------------ text
    def text(
        self,
        text: str,
        x: float,
        y: float,
        w: float,
        style: TextStyle,
        role: str,
        align: str = "left",
        editable: str | None = None,
        balance: bool = False,
        para_gap: float = 0.6,
    ) -> Block | None:
        if not text or not text.strip():
            return None
        lines = T.balance(text, style, w) if balance else T.wrap(text, style, w)
        h = T.text_height(lines, style, para_gap)
        return Block(
            kind="text", x=round(x, 2), y=round(y, 2), w=round(w, 2), h=h, text=text, lines=lines,
            style=style, align=align, role=role, editable=editable, para_gap=para_gap, z=3,
        )

    def fitted_text(
        self,
        text: str,
        x: float,
        y: float,
        w: float,
        style: TextStyle,
        role: str,
        max_lines: int,
        min_size: float,
        max_size: float,
        align: str = "left",
        editable: str | None = None,
        max_height: float | None = None,
        balance: bool = True,
    ) -> Block | None:
        if not text or not text.strip():
            return None
        size = T.fit_size(text, style, w, max_lines, min_size, max_size, max_height)
        st = style.with_(size=size)
        return self.text(text, x, y, w, st, role, align, editable, balance=balance)

    def line_fitted(self, words: list[str], x: float, y: float, w: float, style: TextStyle, role: str, editable: str | None = None, max_size: float = 900.0, line_height: float = 0.9, align: str = "left", source_text: str | None = None) -> list[Block]:
        """Poster-style display: each line scaled to span the full width."""
        blocks: list[Block] = []
        cy = y
        for word in words:
            if not word.strip():
                continue
            size = T.fit_line_to_width(word, style, w, max_size=max_size)
            st = style.with_(size=size, line_height=line_height)
            line = T.transform(word, st)
            b = Block(kind="text", x=round(x, 2), y=round(cy, 2), w=round(w, 2), h=st.line_px, text=word, lines=[line], style=st, align=align, role=role, editable=None, z=3)
            b.meta["fitted"] = True
            if source_text is not None:
                b.meta["source_text"] = source_text
            blocks.append(b)
            cy += st.line_px
        if blocks and editable:
            blocks[0].editable = editable
            blocks[0].meta["group"] = len(blocks)
        return blocks

    # ---------------------------------------------------------------- images
    def image(
        self,
        asset_id: str,
        x: float,
        y: float,
        w: float,
        h: float,
        prefer: str = "cover",
        mat: str | None = None,
        pad: float = 0.0,
        radius: float = 0.0,
        z: int = 2,
    ) -> Block | None:
        asset = self.asset(asset_id)
        if asset is None or w <= 1 or h <= 1:
            return None
        fit = choose_fit(asset, w, h, prefer=prefer)
        kind = "video" if asset.media_type == MEDIA_VIDEO else "image"
        block = Block(
            kind=kind, x=round(x, 2), y=round(y, 2), w=round(w, 2), h=round(h, 2), z=z, asset_id=asset_id,
            fit=fit.mode, focal=fit.position, crop=round(fit.crop, 4), radius=radius, mat=mat, pad=pad,
        )
        if fit.mode == "contain":
            block.crop = 0.0
            inner_w, inner_h = max(1.0, w - 2 * pad), max(1.0, h - 2 * pad)
            scale = min(inner_w / asset.aspect, inner_h) if asset.aspect else inner_h
            shown_w = scale * asset.aspect
            limit = native_limit(asset)
            if shown_w > limit:
                factor = limit / shown_w
                extra = (min(inner_w, inner_h * asset.aspect) * (1 - factor)) / 2
                block.pad = round(pad + max(0.0, extra), 2)
                block.meta["upscale_limited"] = True
        block.meta["visible"] = fit.visible
        return block

    def natural(self, asset_id: str, x: float, y: float, w: float, max_h: float | None = None, align: str = "center", radius: float = 0.0, mat: str | None = None) -> Block | None:
        """Image at its own proportions (never cropped), width-limited by native size."""
        asset = self.asset(asset_id)
        if asset is None:
            return None
        width = min(w, native_limit(asset))
        height = width / asset.aspect
        if max_h and height > max_h:
            height = max_h
            width = height * asset.aspect
        offset = {"left": 0.0, "center": (w - width) / 2, "right": w - width}[align]
        return self.image(asset_id, x + offset, y, width, height, prefer="contain", radius=radius, mat=mat)

    def tile(self, asset_id: str, x: float, y: float, w: float, h: float, bg: str, pad_ratio: float = 0.14, radius: float = 0.0, prefer: str = "cover") -> Block | None:
        """Image in a tile: covers when allowed, otherwise sits on a mat with padding."""
        asset = self.asset(asset_id)
        if asset is None:
            return None
        fit = choose_fit(asset, w, h, prefer=prefer)
        if fit.mode == "cover":
            return self.image(asset_id, x, y, w, h, prefer="cover", radius=radius)
        pad = min(w, h) * pad_ratio
        mat = self.mat_for(asset, bg)
        return self.image(asset_id, x, y, w, h, prefer="contain", mat=mat, pad=pad, radius=radius)

    def mat_for(self, asset: AssetRecord, default_bg: str) -> str:
        """Background behind a contained image: seamless with its own plain
        background when it has one, otherwise a contrasting neutral."""
        a = asset.analysis or {}
        bg = a.get("background")
        if bg and bg != "transparent" and a.get("background_uniformity", 0) >= 0.9:
            return bg
        if bg == "transparent":
            return self.logo_backdrop(asset, default_bg, options=[default_bg])
        return default_bg

    def logo_backdrop(self, asset: AssetRecord, preferred: str, avoid: str | None = None, options: list[str] | None = None) -> str:
        """Pick a backdrop on which a (transparent) mark stays clearly visible.

        ``avoid`` is the surrounding background: a tile identical to it would
        be invisible, so it is skipped when alternatives exist."""
        colors = (asset.analysis or {}).get("content_colors") or (asset.analysis or {}).get("colors") or []
        main = colors[0]["hex"] if colors else "#000000"
        pal = self.palette
        pool = [preferred] + list(options or []) + [C.mix(pal.paper, pal.ink, 0.08), pal.primary, pal.secondary, pal.ink, pal.paper, "#FFFFFF", "#111111"]
        for candidate in pool:
            if avoid and C.delta_e(candidate, avoid) < 5:
                continue
            if C.contrast_ratio(main, candidate) >= 3.0:
                return candidate
        return preferred

    def overlay_style(self, image_block: Block, rect: tuple[float, float, float, float], light: str, dark: str) -> tuple[str, bool]:
        """Text colour for text placed over an image, and whether a scrim is needed."""
        asset = self.asset(image_block.asset_id or "")
        if asset is None:
            return light, True
        vis = image_block.meta.get("visible", (0, 0, 1, 1))
        x0 = vis[0] + (rect[0] - image_block.x) / image_block.w * (vis[2] - vis[0])
        x1 = vis[0] + (rect[0] + rect[2] - image_block.x) / image_block.w * (vis[2] - vis[0])
        y0 = vis[1] + (rect[1] - image_block.y) / image_block.h * (vis[3] - vis[1])
        y1 = vis[1] + (rect[1] + rect[3] - image_block.y) / image_block.h * (vis[3] - vis[1])
        lum = region_luminance(asset.analysis or {}, max(0, x0), max(0, y0), min(1, x1), min(1, y1))
        # sRGB-ish luminance to relative luminance
        rel = lum ** 2.2
        light_c = C.contrast_with_luminance(light, rel)
        dark_c = C.contrast_with_luminance(dark, rel)
        if light_c >= dark_c:
            return light, light_c < 4.5
        return dark, dark_c < 4.5

    def subject_overlap(self, image_block: Block, rect: tuple[float, float, float, float]) -> float:
        """Fraction of ``rect`` covering the image's salient subject."""
        asset = self.asset(image_block.asset_id or "")
        if asset is None:
            return 1.0
        sal = (asset.analysis or {}).get("salient_bbox") or [0.3, 0.3, 0.7, 0.7]
        vis = image_block.meta.get("visible", (0, 0, 1, 1))
        vw, vh = max(1e-6, vis[2] - vis[0]), max(1e-6, vis[3] - vis[1])
        sx0 = image_block.x + (sal[0] - vis[0]) / vw * image_block.w
        sx1 = image_block.x + (sal[2] - vis[0]) / vw * image_block.w
        sy0 = image_block.y + (sal[1] - vis[1]) / vh * image_block.h
        sy1 = image_block.y + (sal[3] - vis[1]) / vh * image_block.h
        x0, y0, w, h = rect
        iw = min(x0 + w, sx1) - max(x0, sx0)
        ih = min(y0 + h, sy1) - max(y0, sy0)
        if iw <= 0 or ih <= 0 or w * h <= 0:
            return 0.0
        return (iw * ih) / (w * h)

    def quiet_corner(self, image_block: Block, w: float, h: float, inset: float) -> tuple[float, float]:
        """Top-left position for a w×h label in the image corner with the
        flattest content (least likely to hide important detail)."""
        import numpy as np

        asset = self.asset(image_block.asset_id or "")
        grid = np.asarray((asset.analysis or {}).get("luminance_grid") or [[0.5] * 8] * 8, dtype=float) if asset else np.full((8, 8), 0.5)
        vis = image_block.meta.get("visible", (0, 0, 1, 1))
        corners = {
            "tl": (image_block.x + inset, image_block.y + inset),
            "tr": (image_block.right - inset - w, image_block.y + inset),
            "bl": (image_block.x + inset, image_block.bottom - inset - h),
            "br": (image_block.right - inset - w, image_block.bottom - inset - h),
        }
        best, best_score = corners["tl"], float("inf")
        for name, (x, y) in corners.items():
            fx0 = vis[0] + (x - image_block.x) / image_block.w * (vis[2] - vis[0])
            fx1 = vis[0] + (x + w - image_block.x) / image_block.w * (vis[2] - vis[0])
            fy0 = vis[1] + (y - image_block.y) / image_block.h * (vis[3] - vis[1])
            fy1 = vis[1] + (y + h - image_block.y) / image_block.h * (vis[3] - vis[1])
            gx0, gx1 = int(max(0, min(7, fx0 * 8))), int(max(1, min(8, math.ceil(fx1 * 8))))
            gy0, gy1 = int(max(0, min(7, fy0 * 8))), int(max(1, min(8, math.ceil(fy1 * 8))))
            region = grid[gy0:gy1, gx0:gx1]
            score = float(region.std()) + self.subject_overlap(image_block, (x, y, w, h)) * 2
            if score < best_score:
                best, best_score = (x, y), score
        return best

    # ---------------------------------------------------------- arrangements
    def row(self, ids: list[str], x: float, y: float, width: float, gap: float, max_h: float | None = None, align: str = "center", radius: float = 0.0) -> tuple[list[Block], float]:
        """One justified row at the images' natural proportions."""
        if not ids:
            return [], 0.0
        aspects = [self.aspect(i) for i in ids]
        h = (width - gap * (len(ids) - 1)) / sum(aspects)
        limit = min(native_limit(self.asset(i)) / self.aspect(i) for i in ids if self.asset(i))
        if max_h:
            limit = min(limit, max_h)
        h = min(h, limit)
        total_w = sum(a * h for a in aspects) + gap * (len(ids) - 1)
        cx = x + {"left": 0.0, "center": (width - total_w) / 2, "right": width - total_w}[align]
        blocks = []
        for aid, a in zip(ids, aspects):
            w = a * h
            b = self.image(aid, cx, y, w, h, prefer="contain", radius=radius)
            if b:
                blocks.append(b)
            cx += w + gap
        return blocks, h

    def justified(self, ids: list[str], x: float, y: float, width: float, gap: float, target_h: float, max_per_row: int = 3, radius: float = 0.0, last_align: str = "center", row_gap: float | None = None) -> tuple[list[Block], float, list[float]]:
        """Partition into rows (dynamic programming) of near-target height."""
        if not ids:
            return [], 0.0, []
        row_gap = gap if row_gap is None else row_gap
        aspects = [self.aspect(i) for i in ids]
        n = len(ids)
        INF = float("inf")
        best = [INF] * (n + 1)
        prev = [0] * (n + 1)
        best[0] = 0.0
        for j in range(1, n + 1):
            for k in range(1, min(max_per_row, j) + 1):
                i = j - k
                s = sum(aspects[i:j])
                h = (width - gap * (k - 1)) / s
                if j == n and h > target_h:
                    cost = ((h - target_h) * 0.3) ** 2  # short last row is fine
                else:
                    cost = (h - target_h) ** 2
                if k == 1 and n > 1:
                    cost *= 1.6  # prefer pairs and triples over singles
                if best[i] + cost < best[j]:
                    best[j] = best[i] + cost
                    prev[j] = i
        cuts = []
        j = n
        while j > 0:
            cuts.append((prev[j], j))
            j = prev[j]
        cuts.reverse()
        blocks: list[Block] = []
        cy = y
        breaks: list[float] = []
        for index, (i, j) in enumerate(cuts):
            row_ids = ids[i:j]
            is_last = index == len(cuts) - 1
            max_h = target_h * 1.25 if is_last else None
            row_blocks, h = self.row(row_ids, x, cy, width, gap, max_h=max_h, align=last_align if is_last else "center", radius=radius)
            blocks.extend(row_blocks)
            cy += h
            if not is_last:
                breaks.append(cy + row_gap / 2)
                cy += row_gap
        return blocks, cy - y, breaks

    def columns(self, left: list[str], right: list[str], x: float, y: float, width: float, gap: float, radius: float = 0.0) -> tuple[list[Block], float]:
        """Two stacked columns with equal total height (natural proportions)."""
        s1 = sum(1 / self.aspect(i) for i in left)
        s2 = sum(1 / self.aspect(i) for i in right)
        g1 = gap * (len(left) - 1)
        g2 = gap * (len(right) - 1)
        avail = width - gap
        w1 = (avail * s2 + (g2 - g1)) / (s1 + s2)
        w2 = avail - w1
        blocks: list[Block] = []
        cy = y
        for aid in left:
            h = w1 / self.aspect(aid)
            b = self.image(aid, x, cy, w1, h, prefer="contain", radius=radius)
            if b:
                blocks.append(b)
            cy += h + gap
        cy = y
        for aid in right:
            h = w2 / self.aspect(aid)
            b = self.image(aid, x + w1 + gap, cy, w2, h, prefer="contain", radius=radius)
            if b:
                blocks.append(b)
            cy += h + gap
        height = w1 * s1 + g1
        return blocks, height

    def masonry(self, ids: list[str], x: float, y: float, width: float, cols: int, gap: float, radius: float = 0.0) -> tuple[list[Block], float]:
        col_w = (width - gap * (cols - 1)) / cols
        heights = [0.0] * cols
        placements: list[tuple[str, int, float, float]] = []
        for aid in ids:
            c = min(range(cols), key=lambda i: heights[i])
            h = col_w / self.aspect(aid)
            placements.append((aid, c, heights[c], h))
            heights[c] += h + gap
        blocks = []
        for aid, c, top, h in placements:
            b = self.image(aid, x + c * (col_w + gap), y + top, col_w, h, prefer="contain", radius=radius)
            if b:
                blocks.append(b)
        return blocks, max(heights) - gap

    def grid(self, ids: list[str], x: float, y: float, width: float, cols: int, gap: float, cell_aspect: float, bg: str, radius: float = 0.0, pad_ratio: float = 0.08) -> tuple[list[Block], float, list[float]]:
        """Uniform cells; images cover when allowed, otherwise sit on mats."""
        cols = max(1, min(cols, len(ids)))
        cell_w = (width - gap * (cols - 1)) / cols
        cell_h = cell_w / cell_aspect
        blocks = []
        breaks = []
        rows = math.ceil(len(ids) / cols)
        for index, aid in enumerate(ids):
            r, c = divmod(index, cols)
            # centre an incomplete last row
            in_row = min(cols, len(ids) - r * cols)
            offset = (width - (in_row * cell_w + (in_row - 1) * gap)) / 2 if r == rows - 1 else 0.0
            b = self.tile(aid, x + offset + c * (cell_w + gap), y + r * (cell_h + gap), cell_w, cell_h, bg, pad_ratio=pad_ratio, radius=radius)
            if b:
                blocks.append(b)
        for r in range(1, rows):
            breaks.append(y + r * (cell_h + gap) - gap / 2)
        return blocks, rows * cell_h + (rows - 1) * gap, breaks

    # ------------------------------------------------------------ analysis
    def common_aspect(self, ids: list[str], tolerance: float = 0.04) -> float | None:
        if not ids:
            return None
        aspects = [self.aspect(i) for i in ids]
        first = aspects[0]
        if all(abs(a - first) / first <= tolerance for a in aspects):
            return first
        return None

    def kinds(self, ids: list[str]) -> list[str]:
        return [self.asset(i).effective_kind for i in ids if self.asset(i)]

    def all_croppable(self, ids: list[str], aspect: float) -> bool:
        return all(choose_fit(self.asset(i), aspect * 1000, 1000).mode == "cover" for i in ids if self.asset(i))


# ------------------------------------------------------------------------
# Candidate arrangements with scoring
# ------------------------------------------------------------------------
@dataclass
class Arrangement:
    name: str
    blocks: list[Block]
    height: float
    breaks: list[float] = field(default_factory=list)
    score: float = 0.0


def _lead_block(comp: "Composer", aid: str, x: float, y: float, width: float, max_h: float, aspects: tuple[float, ...] = (16 / 9, 3 / 2, 2.0)) -> Block | None:
    from behance_studio.layout.fitting import best_crop_aspect

    asset = comp.asset(aid)
    if asset is None:
        return None
    aspect = best_crop_aspect(asset, list(aspects))
    if aspect and width / aspect <= max_h and native_limit(asset) >= width * 0.85:
        return comp.image(aid, x, y, width, width / aspect)
    return comp.natural(aid, x, y, width, max_h=max_h)


def candidate_arrangements(
    comp: "Composer",
    ids: list[str],
    x: float,
    y: float,
    width: float,
    gap: float,
    target_h: float,
    max_h: float,
    patterns: Iterable[str],
    radius: float = 0.0,
    last_stretch: float = 1.8,
) -> list[Arrangement]:
    out: list[Arrangement] = []
    n = len(ids)
    patterns = set(patterns)

    def add(name: str, blocks: list[Block], height: float, breaks: list[float] | None = None) -> None:
        if blocks:
            out.append(Arrangement(name, blocks, height, breaks or []))

    if n == 1:
        b = _lead_block(comp, ids[0], x, y, width, max_h) if "lead" in patterns else comp.natural(ids[0], x, y, width, max_h=max_h)
        if b is not None:
            add("single", [b], b.h)
        return out
    if "rows" in patterns:
        blocks, h, br = comp.justified(ids, x, y, width, gap, target_h, max_per_row=3, radius=radius, last_align="center")
        add("rows", blocks, h, br)
        _stretch_last_row(comp, out[-1] if out else None, x, width, gap, target_h * last_stretch)
    if "rows4" in patterns and n >= 4:
        blocks, h, br = comp.justified(ids, x, y, width, gap, target_h * 0.8, max_per_row=4, radius=radius)
        add("rows4", blocks, h, br)
        _stretch_last_row(comp, out[-1] if out else None, x, width, gap, target_h * last_stretch)
    if "pair" in patterns and n == 2:
        blocks, h = comp.row(ids, x, y, width, gap, radius=radius)
        add("pair", blocks, h)
    if "lead" in patterns and n >= 3:
        lead = _lead_block(comp, ids[0], x, y, width, max_h * 0.75)
        if lead is not None:
            cy = lead.bottom + gap
            blocks, h, br = comp.justified(ids[1:], x, cy, width, gap, target_h, max_per_row=3, radius=radius)
            arr = Arrangement("lead", [lead] + blocks, lead.h + gap + h, [lead.bottom + gap / 2] + br)
            _stretch_last_row(comp, arr, x, width, gap, target_h * last_stretch)
            out.append(arr)
    if "asym" in patterns and 2 <= n <= 4:
        ranked = sorted(ids, key=lambda i: -(comp.aspect(i) * (comp.asset(i).width if comp.asset(i) else 1)))
        lead = ranked[0]
        rest = [i for i in ids if i != lead]
        for side, (left, right) in (("asym-l", ([lead], rest)), ("asym-r", (rest, [lead]))):
            blocks, h = comp.columns(left, right, x, y, width, gap, radius=radius)
            add(side, blocks, h)
    if "stack2" in patterns and n == 4:
        blocks, h = comp.columns(ids[:2], ids[2:], x, y, width, gap, radius=radius)
        add("stack2", blocks, h)
    if "masonry" in patterns and n >= 4:
        cols = 3 if n >= 5 else 2
        blocks, h = comp.masonry(ids, x, y, width, cols, gap, radius=radius)
        add("masonry", blocks, h)
    return out


def _stretch_last_row(comp: "Composer", arr: Arrangement | None, x: float, width: float, gap: float, max_h: float) -> None:
    """Grow a short last row to the full width when it stays reasonably sized."""
    if arr is None or not arr.blocks:
        return
    last_top = max(b.y for b in arr.blocks)
    row = [b for b in arr.blocks if abs(b.y - last_top) < 0.5]
    row_w = sum(b.w for b in row) + gap * (len(row) - 1)
    if row_w >= width - 1 or not row:
        return
    h = row[0].h
    new_h = h * (width - gap * (len(row) - 1)) / (row_w - gap * (len(row) - 1))
    limit = min(native_limit(comp.asset(b.asset_id)) / comp.aspect(b.asset_id) for b in row if b.asset_id and comp.asset(b.asset_id))
    if new_h > max_h or new_h > limit:
        return
    cx = x
    for b in sorted(row, key=lambda b: b.x):
        aspect = comp.aspect(b.asset_id) if b.asset_id else b.w / b.h
        b.x = round(cx, 2)
        b.w = round(aspect * new_h, 2)
        b.h = round(new_h, 2)
        cx += b.w + gap
    arr.height += new_h - h


def score_arrangement(comp: "Composer", arr: Arrangement, width: float, max_h: float, recent: list[str], novelty: float = 0.6) -> float:
    media = [b for b in arr.blocks if b.asset_id]
    if not media:
        return -99.0
    areas = [b.w * b.h for b in media]
    balance = min(areas) / max(areas)
    score = 2.0 * min(1.0, balance / 0.3)
    min_w = min(b.w for b in media)
    if min_w < comp.px(220):
        score -= 3.0 * (1 - min_w / comp.px(220))
    if arr.height > max_h:
        score -= 2.5 * (arr.height / max_h - 1)
    lefts = min(b.x for b in media)
    rights = max(b.right for b in media)
    coverage = (rights - lefts) / width
    score += 0.8 * coverage
    # full-width rows (clean edges) are better than ragged ones
    rows: dict[float, list[Block]] = {}
    for b in media:
        rows.setdefault(round(b.y, 0), []).append(b)
    ragged = sum(1 for r in rows.values() if (max(b.right for b in r) - min(b.x for b in r)) < width * 0.97)
    score -= 0.35 * ragged
    upscaled = 0
    for b in media:
        asset = comp.asset(b.asset_id)
        if asset and b.fit == "cover" and b.w > native_limit(asset) * 1.05:
            upscaled += 1
    score -= 0.8 * upscaled
    score -= 0.8 * sum(b.crop for b in media)
    if arr.name in recent:
        score -= novelty
    return score


def best_arrangement(
    comp: "Composer",
    ids: list[str],
    x: float,
    y: float,
    width: float,
    gap: float,
    target_h: float,
    max_h: float,
    patterns: Iterable[str],
    recent: list[str] | None = None,
    radius: float = 0.0,
    jitter: float = 0.25,
    last_stretch: float = 1.8,
) -> Arrangement:
    cands = candidate_arrangements(comp, ids, x, y, width, gap, target_h, max_h, patterns, radius, last_stretch)
    if not cands:
        blocks, h, br = comp.justified(ids, x, y, width, gap, target_h, radius=radius)
        return Arrangement("rows", blocks, h, br)
    for c in cands:
        c.score = score_arrangement(comp, c, width, max_h, recent or []) + comp.rng.uniform(0, jitter)
    return max(cands, key=lambda c: c.score)
