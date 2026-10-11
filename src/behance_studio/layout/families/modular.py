"""Family 6 — Modular Identity.

A structured visual system: a 12-column grid of square modules, bento-style
tiles with consistent gutters and corner radii, brand colours as tiles,
monospaced labels and systematic section relationships. A packer searches
tile spans that respect each image's proportions (cropping only within its
allowance) while leaving as few holes as possible; remaining holes become
colour tiles of the identity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from behance_studio.design import color as C
from behance_studio.design.typography import TypeSystem, get_font
from behance_studio.layout.composer import Composer, SectionBuilder
from behance_studio.layout.families.base import ComposeState, FamilyInfo, LayoutFamily
from behance_studio.layout.fitting import choose_fit, max_crop
from behance_studio.layout.model import Block, Section, TextStyle
from behance_studio.planning.models import SectionPlan
from behance_studio.planning.planner import PlanPreferences

COLS = 12
SPANS = [(12, 6), (12, 5), (8, 6), (8, 5), (8, 4), (6, 6), (6, 5), (6, 4), (6, 3), (4, 6), (4, 5), (4, 4), (4, 3), (3, 4), (3, 3), (9, 5), (9, 4), (3, 5), (5, 4), (7, 5), (5, 6)]


@dataclass
class Tile:
    cols: int
    rows: int
    kind: str  # image | text | color | logo | custom
    payload: Any = None
    row: int = 0
    col: int = 0
    options: list[tuple[int, int]] = field(default_factory=list)


def _place(tiles: list[Tile], cols: int = COLS) -> tuple[list[Tile], int, list[list[bool]]]:
    grid: list[list[bool]] = []

    def free(r: int, c: int, w: int, h: int) -> bool:
        if c + w > cols:
            return False
        for rr in range(r, r + h):
            while rr >= len(grid):
                grid.append([False] * cols)
            for cc in range(c, c + w):
                if grid[rr][cc]:
                    return False
        return True

    for t in tiles:
        r = 0
        placed = False
        while not placed:
            for c in range(cols):
                if free(r, c, t.cols, t.rows):
                    for rr in range(r, r + t.rows):
                        for cc in range(c, c + t.cols):
                            grid[rr][cc] = True
                    t.row, t.col = r, c
                    placed = True
                    break
            r += 1
    used_rows = max((t.row + t.rows for t in tiles), default=0)
    return tiles, used_rows, grid[:used_rows]


def _holes(grid: list[list[bool]]) -> list[tuple[int, int, int, int]]:
    """Cover empty cells with rectangles (greedy, row-major)."""
    taken = [row[:] for row in grid]
    rects = []
    for r in range(len(taken)):
        for c in range(COLS):
            if taken[r][c]:
                continue
            w = 1
            while c + w < COLS and not taken[r][c + w]:
                w += 1
            h = 1
            while r + h < len(taken) and all(not taken[r + h][cc] for cc in range(c, c + w)):
                h += 1
            for rr in range(r, r + h):
                for cc in range(c, c + w):
                    taken[rr][cc] = True
            rects.append((r, c, w, h))
    return rects


class ModularFamily(LayoutFamily):
    info = FamilyInfo(
        id="modular",
        name="Modular Identity",
        tagline="A systematic bento grid built from the identity",
        description="Structured modular grids: bento tiles, brand-colour modules, monospaced labels and consistent rhythm across every section.",
        ideal_for=["Branding systems", "Packaging", "UI/UX", "Large identity projects"],
        badge="#7C6CF0",
    )
    voices = {"technical", "condensed"}
    edge_style = None

    def preferences(self, rng, creativity) -> PlanPreferences:
        return PlanPreferences(max_per_section=8, include_intro=True, closing_image=False, hero_rank=2 if rng.random() < 0.4 else 0, merge_small=2, split_logo_variations=False, shuffle=0.2 * creativity, hero_aspect=1.6)

    def variant(self, ctx, rng) -> dict[str, Any]:
        radius = ctx.direction.corner_radius
        return {
            "margin": rng.choice([48, 64]),
            "gutter": rng.choice([12, 16, 20]),
            "radius": rng.choice([radius or 0, 14, 22]) if radius else rng.choice([0, 0, 12, 20]),
            "header_side": rng.choice(["left", "right"]),
            "cover": rng.choice(["A", "B"]),
            "mono": rng.random() < 0.75,
        }

    def setup(self, comp: Composer, v: dict[str, Any]) -> None:
        self.v = v
        self.ts = TypeSystem.from_dict(v["type_system"])
        pal = comp.palette
        self.paper = pal.paper if C.lightness(pal.paper) > 85 else C.with_lightness(pal.paper, 95, 0.4)
        self.paper_alt = C.mix(self.paper, pal.ink, 0.07)
        self.tile_colors = list(dict.fromkeys([pal.primary, pal.ink, pal.secondary, self.paper_alt, pal.accent]))
        self.M = comp.px(v["margin"])
        self.G = comp.px(v["gutter"])
        self.CW = comp.W - 2 * self.M
        self.u = (self.CW - (COLS - 1) * self.G) / COLS
        self.R = comp.px(v["radius"])
        self.label_font = "JetBrains Mono" if v["mono"] else self.ts.label
        fam = get_font(self.ts.display)
        self.display_weight = fam.clamp_weight(600 if fam.category != "serif" else 500)
        self._color_i = 0

    # ----------------------------------------------------------- geometry
    def rect(self, row: int, col: int, cols: int, rows: int, top: float) -> tuple[float, float, float, float]:
        x = self.M + col * (self.u + self.G)
        y = top + row * (self.u + self.G)
        w = cols * self.u + (cols - 1) * self.G
        h = rows * self.u + (rows - 1) * self.G
        return x, y, w, h

    def next_color(self, avoid: set[str] | None = None) -> str:
        for _ in range(len(self.tile_colors)):
            c = self.tile_colors[self._color_i % len(self.tile_colors)]
            self._color_i += 1
            if not avoid or c not in avoid:
                return c
        return self.tile_colors[0]

    def st_label(self, comp, color, size=11) -> TextStyle:
        fam = get_font(self.label_font)
        return TextStyle(self.label_font, comp.px(size), fam.clamp_weight(500), 1.45, 0.06, color, uppercase=True)

    def st_title(self, comp, size, color) -> TextStyle:
        return TextStyle(self.ts.display, comp.px(size), self.display_weight, 1.04, -0.02, color)

    def st_body(self, comp, color, size=16) -> TextStyle:
        return TextStyle(self.ts.text, comp.px(size), get_font(self.ts.text).clamp_weight(400), 1.55, 0.0, color)

    # -------------------------------------------------------------- tiles
    def image_spans(self, comp: Composer, aid: str, lead: bool) -> list[tuple[int, int]]:
        asset = comp.asset(aid)
        a = asset.aspect if asset else 1.0
        limit = max(0.04, max_crop(asset)) if asset else 0.04
        scored = []
        for c, r in SPANS:
            w = c * self.u + (c - 1) * self.G
            h = r * self.u + (r - 1) * self.G
            ta = w / h
            err = abs(math.log(ta) - math.log(a))
            size = c * r
            if lead:
                size_pen = 0.0 if size >= 36 else (36 - size) / 36
            else:
                size_pen = 0.0 if 12 <= size <= 36 else (abs(size - 24) / 24)
            fits_crop = 1 - min(ta / a, a / ta) <= limit
            scored.append((err * (0.6 if fits_crop else 1.6) + size_pen * 0.5, (c, r)))
        scored.sort()
        return [s for _, s in scored[:4]]

    def pack(self, comp: Composer, tiles: list[Tile]) -> tuple[list[Tile], int, list[tuple[int, int, int, int]]]:
        """Try span combinations; keep the packing with fewest holes."""
        best = None
        rng = comp.rng
        for attempt in range(48):
            trial = []
            for t in tiles:
                opts = t.options or [(t.cols, t.rows)]
                if attempt == 0:
                    span = opts[0]
                else:
                    span = opts[min(len(opts) - 1, int(rng.random() ** 1.6 * len(opts)))]
                trial.append(Tile(span[0], span[1], t.kind, t.payload, options=t.options))
            placed, rows, grid = _place(trial)
            holes = _holes(grid)
            hole_cells = sum(w * h for _, _, w, h in holes)
            aspect_err = 0.0
            for t in placed:
                if t.kind == "image":
                    w = t.cols * self.u + (t.cols - 1) * self.G
                    h = t.rows * self.u + (t.rows - 1) * self.G
                    aspect_err += abs(math.log((w / h) / max(0.05, comp.aspect(t.payload))))
            slivers = sum(w * h for _, _, w, h in holes if w == 1 or (h == 1 and w > 2))
            score = hole_cells * 1.0 + slivers * 1.2 + aspect_err * 3.0 + rows * 0.15
            if best is None or score < best[0]:
                best = (score, placed, rows, holes)
            if hole_cells == 0 and attempt > 8:
                break
        assert best is not None
        return best[1], best[2], best[3]

    def draw_tiles(self, comp: Composer, sb: SectionBuilder, tiles: list[Tile], rows: int, holes, top: float, render: Callable[[Tile, tuple[float, float, float, float]], None]) -> float:
        for t in tiles:
            render(t, self.rect(t.row, t.col, t.cols, t.rows, top))
        for (r, c, w, h) in holes:
            x, y, tw, th = self.rect(r, c, w, h, top)
            fill = self.next_color()
            sb.add(Block(kind="shape", x=x, y=y, w=tw, h=th, fill=fill, radius=self.R, decorative=True, z=1))
        # rows that no tile crosses are safe page breaks
        for r in range(1, rows):
            if all(not (t.row < r < t.row + t.rows) for t in tiles) and all(not (hr < r < hr + hh) for hr, _c, _w, hh in holes):
                sb.mark_break(top + r * (self.u + self.G) - self.G / 2)
        return top + rows * self.u + (rows - 1) * self.G

    def render_image(self, comp: Composer, sb: SectionBuilder, aid: str, rect, mat: str | None = None) -> None:
        x, y, w, h = rect
        asset = comp.asset(aid)
        if asset is None:
            return
        fit = choose_fit(asset, w, h)
        if fit.mode == "cover":
            sb.add(comp.image(aid, x, y, w, h, radius=self.R))
            return
        bg = mat or comp.mat_for(asset, self.paper_alt)
        if bg == self.paper:
            bg = self.paper_alt
        sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill=bg, radius=self.R, decorative=True, z=1))
        pad = min(w, h) * 0.08
        sb.add(comp.image(aid, x + pad, y + pad, w - 2 * pad, h - 2 * pad, prefer="contain"))

    def text_tile(self, comp: Composer, sb: SectionBuilder, rect, fill: str, label: str, title: str, body: str = "", title_size: float = 52, editable: bool = True) -> None:
        x, y, w, h = rect
        fg = comp.text_color(fill)
        soft = comp.muted(fg, fill, 0.3)
        sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill=fill, radius=self.R, decorative=True, z=1))
        pad = comp.px(28)
        sb.add(comp.text(label, x + pad, y + pad, w - 2 * pad, self.st_label(comp, soft), "eyebrow"))
        avail_h = h - 2 * pad - comp.px(34)
        body_block = comp.text(body, x + pad, 0, min(w - 2 * pad, comp.px(560)), self.st_body(comp, fg), "body", editable="body" if editable else None) if body else None
        body_h = (body_block.h + comp.px(18)) if body_block else 0
        title_block = comp.fitted_text(title, x + pad, 0, w - 2 * pad, self.st_title(comp, title_size, fg), "title", max_lines=3, min_size=comp.px(26), max_size=comp.px(title_size), max_height=max(comp.px(40), avail_h - body_h), editable="title" if editable else None)
        stack = (title_block.h if title_block else 0) + body_h
        cy = y + h - pad - stack
        if title_block:
            title_block.y = round(cy, 2)
            sb.add(title_block)
            cy = title_block.bottom + comp.px(18)
        if body_block:
            body_block.y = round(cy, 2)
            if body_block.bottom > y + h - pad + 1:
                # Body too long for the tile: let the caller give it more room.
                raise ValueError("text tile too small")
            sb.add(body_block)

    def number_tile(self, comp: Composer, sb: SectionBuilder, rect, fill: str, number: int, caption: str) -> None:
        x, y, w, h = rect
        fg = comp.text_color(fill)
        sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill=fill, radius=self.R, decorative=True, z=1))
        pad = comp.px(28)
        st = TextStyle(self.ts.display, comp.px(200), get_font(self.ts.display).clamp_weight(700), 0.9, -0.03, fg)
        num = comp.fitted_text(f"{number:02d}", x + pad, y + pad, w - 2 * pad, st, "numeral", max_lines=1, min_size=comp.px(60), max_size=min(h * 0.62, comp.px(220)))
        sb.add(num)
        sb.add(comp.text(caption, x + pad, y + h - pad - comp.px(16), w - 2 * pad, self.st_label(comp, comp.muted(fg, fill, 0.3)), "label"))

    def logo_tile(self, comp: Composer, sb: SectionBuilder, aid: str, rect, preferred: str) -> None:
        x, y, w, h = rect
        asset = comp.asset(aid)
        if asset is None:
            return
        a = asset.analysis or {}
        if a.get("background") not in (None, "transparent") and a.get("background_uniformity", 0) >= 0.9:
            fill = a["background"]
        else:
            fill = comp.logo_backdrop(asset, preferred, avoid=self.paper, options=self.tile_colors)
        sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill=fill, radius=self.R, decorative=True, z=1))
        sb.add(comp.image(aid, x + w * 0.2, y + h * 0.25, w * 0.6, h * 0.5, prefer="contain"))

    def section_label(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> str:
        return f"{state.content_index + 1:02d} — {comp.copy.section_title(sp.type) if sp.type != 'custom' else sp.title}"

    def header_tiles(self, comp: Composer, sp: SectionPlan, state: ComposeState, n_items: int) -> list[Tile]:
        has_body = bool(sp.body or sp.subtitle)
        text_rows = 3 if not has_body else (4 if len(sp.body or "") < 260 else 5)
        if len(sp.body or "") > 520:
            text_rows = 6
        text = Tile(8, text_rows, "text", {"sp": sp})
        num = Tile(4, text_rows, "number", {"n": state.content_index + 1, "count": n_items})
        left = self.v["header_side"] == "left" if state.index % 2 == 0 else self.v["header_side"] != "left"
        return [text, num] if left else [num, text]

    def render_header(self, comp: Composer, sb: SectionBuilder, t: Tile, rect, state: ComposeState) -> None:
        if t.kind == "text":
            sp: SectionPlan = t.payload["sp"]
            body = "\n\n".join(p for p in (sp.subtitle, sp.body) if p)
            fill = self.paper_alt
            try:
                self.text_tile(comp, sb, rect, fill, self.section_label(comp, sp, state), sp.title, body)
            except ValueError:
                # fall back: title only in the tile, body below in the grid flow
                sb.blocks = [b for b in sb.blocks if not (b.y >= rect[1] - 0.5 and b.bottom <= rect[1] + rect[3] + 0.5 and b.x >= rect[0] - 0.5 and b.right <= rect[0] + rect[2] + 0.5)]
                self.text_tile(comp, sb, rect, fill, self.section_label(comp, sp, state), sp.title, "")
        else:
            fill = self.tile_colors[(state.index) % len(self.tile_colors)]
            if fill == self.paper_alt:
                fill = self.tile_colors[0]
            count = t.payload["count"]
            items = "item" if count == 1 else "items"
            if comp.ctx.language == "pt":
                items = "elemento" if count == 1 else "elementos"
            self.number_tile(comp, sb, rect, fill, t.payload["n"], f"{count} {items}" if count else "")

    # -------------------------------------------------------------- cover
    def cover(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.paper, "light", "cover-bento-" + self.v["cover"])
        top = self.M
        ids = comp.assets_of(sp)
        pal = comp.palette
        logo = sp.meta.get("logo_id")
        if self.v["cover"] == "A" or not ids:
            layout = [("title", 0, 0, 8, 5), ("logo", 0, 8, 4, 5)]
            if ids:
                hero_rows = max(5, min(9, round(12 * self.u / comp.aspect(ids[0]) / (self.u + self.G))))
                layout.append(("hero", 5, 0, 12, hero_rows))
                base = 5 + hero_rows
            else:
                base = 5
            layout += [("label", base, 0, 6, 2)] + [(f"c{i}", base, 6 + i * 2, 2, 2) for i in range(3)]
        else:
            layout = [("hero", 0, 0, 8, 8), ("title", 0, 8, 4, 5), ("label", 5, 8, 4, 3), ("logo", 8, 0, 4, 3)] + [(f"c{i}", 8, 4 + i * 2, 2, 3) for i in range(4)]
        rows = max(r + h for _, r, _, _, h in layout)
        colors = [pal.primary, pal.secondary, pal.ink, pal.accent, self.paper_alt]
        ci = 0
        for name, r, c, w, h in layout:
            rect = self.rect(r, c, w, h, top)
            if name == "title":
                fill = pal.primary
                x, y, tw, th = rect
                fg = comp.text_color(fill)
                sb.add(Block(kind="shape", x=x, y=y, w=tw, h=th, fill=fill, radius=self.R, decorative=True, z=1))
                pad = comp.px(32)
                sb.add(comp.text(sp.eyebrow or comp.ctx.plan.category_label, x + pad, y + pad, tw - 2 * pad, self.st_label(comp, comp.muted(fg, fill, 0.3)), "eyebrow", editable="eyebrow"))
                sub = comp.text(sp.subtitle, x + pad, 0, min(tw - 2 * pad, comp.px(560)), self.st_body(comp, fg, 18), "subtitle", editable="subtitle")
                sub_h = sub.h + comp.px(18) if sub else 0
                t = comp.fitted_text(sp.title, x + pad, 0, tw - 2 * pad, self.st_title(comp, 140, fg).with_(line_height=0.98), "display", max_lines=3, min_size=comp.px(40), max_size=comp.px(150), max_height=th - 2 * pad - comp.px(40) - sub_h, editable="title")
                cy = y + th - pad - (t.h if t else 0) - sub_h
                if t:
                    t.y = round(cy, 2)
                    sb.add(t)
                    cy = t.bottom + comp.px(18)
                if sub:
                    sub.y = round(cy, 2)
                    sb.add(sub)
            elif name == "logo":
                if logo and comp.asset(logo):
                    self.logo_tile(comp, sb, logo, rect, self.paper_alt)
                else:
                    sb.add(Block(kind="shape", x=rect[0], y=rect[1], w=rect[2], h=rect[3], fill=pal.ink, radius=self.R, decorative=True))
            elif name == "hero" and ids:
                self.render_image(comp, sb, ids[0], rect)
            elif name == "label":
                fill = pal.ink
                x, y, tw, th = rect
                fg = comp.text_color(fill)
                sb.add(Block(kind="shape", x=x, y=y, w=tw, h=th, fill=fill, radius=self.R, decorative=True))
                pad = comp.px(24)
                entries = [s.title for s in comp.ctx.plan.sections if s.type not in ("cover", "closing")][:6]
                text = f"{comp.ctx.plan.project_title}\n{len(entries)} {('secções' if comp.ctx.language == 'pt' else 'sections')}"
                sb.add(comp.text(text, x + pad, y + pad, tw - 2 * pad, self.st_label(comp, fg, 12), "label"))
            else:
                fill = colors[ci % len(colors)]
                ci += 1
                sb.add(Block(kind="shape", x=rect[0], y=rect[1], w=rect[2], h=rect[3], fill=fill, radius=self.R, decorative=True))
        y = top + rows * self.u + (rows - 1) * self.G
        sb.y = y
        return sb.finish(self.G * 3)

    # ---------------------------------------------------------- statement
    def statement(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.paper, "light", "statement-bento")
        top = self.G * 3
        long = len(sp.body or "") > 300
        rows = 4 if not long else 6
        quote = sp.meta.get("quote")
        text_rect = self.rect(0, 0, 8 if quote else 12, rows, top)
        try:
            self.text_tile(comp, sb, text_rect, self.paper_alt, self.section_label(comp, sp, state), sp.title, sp.body, title_size=40)
        except ValueError:
            rows += 3
            text_rect = self.rect(0, 0, 8 if quote else 12, rows, top)
            sb.blocks.clear()
            self.text_tile(comp, sb, text_rect, self.paper_alt, self.section_label(comp, sp, state), sp.title, sp.body, title_size=40)
        if quote:
            rect = self.rect(0, 8, 4, rows, top)
            fill = comp.palette.primary
            x, y, w, h = rect
            fg = comp.text_color(fill)
            sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill=fill, radius=self.R, decorative=True))
            pad = comp.px(28)
            q = comp.fitted_text(f"“{quote}”", x + pad, y + pad, w - 2 * pad, self.st_title(comp, 40, fg), "quote", max_lines=5, min_size=comp.px(20), max_size=comp.px(44), max_height=h - 2 * pad)
            sb.add(q)
        sb.y = top + rows * self.u + (rows - 1) * self.G
        return sb.finish(self.G * 3)

    # -------------------------------------------------------------- media
    def media(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.paper, "light", "bento")
        top = self.G * 3
        tiles = self.header_tiles(comp, sp, state, len(ids))
        for i, aid in enumerate(ids):
            opts = self.image_spans(comp, aid, lead=(i == 0))
            tiles.append(Tile(opts[0][0], opts[0][1], "image", aid, options=opts))
        placed, rows, holes = self.pack(comp, tiles)

        def render(t: Tile, rect) -> None:
            if t.kind in ("text", "number"):
                self.render_header(comp, sb, t, rect, state)
            else:
                self.render_image(comp, sb, t.payload, rect)

        y = self.draw_tiles(comp, sb, placed, rows, holes, top, render)
        sb.y = y
        return sb.finish(self.G * 3)

    def logo(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.paper, "light", "bento-logo")
        top = self.G * 3
        tiles = self.header_tiles(comp, sp, state, len(ids))
        for i, aid in enumerate(ids):
            if i == 0:
                tiles.append(Tile(8, 5, "logo", aid, options=[(8, 5), (12, 5), (8, 6)]))
            else:
                tiles.append(Tile(4, 4, "logo", aid, options=[(4, 4), (4, 5), (6, 4), (3, 3)]))
        placed, rows, holes = self.pack(comp, tiles)
        colors = [comp.palette.primary, self.paper_alt, comp.palette.ink, comp.palette.secondary]

        def render(t: Tile, rect) -> None:
            if t.kind in ("text", "number"):
                self.render_header(comp, sb, t, rect, state)
            else:
                idx = ids.index(t.payload)
                self.logo_tile(comp, sb, t.payload, rect, colors[idx % len(colors)])

        y = self.draw_tiles(comp, sb, placed, rows, holes, top, render)
        sb.y = y
        return sb.finish(self.G * 3)

    def palette(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.paper, "light", "bento-palette")
        top = self.G * 3
        swatches = [] if ids else (sp.meta.get("swatches") or [])
        tiles = self.header_tiles(comp, sp, state, len(ids) or len(swatches))
        for i, sw in enumerate(swatches):
            tiles.append(Tile(6 if i == 0 else 3, 4, "swatch", sw, options=[(6, 4)] if i == 0 else [(3, 4), (4, 4), (3, 3)]))
        for i, aid in enumerate(ids):
            opts = self.image_spans(comp, aid, lead=(i == 0))
            tiles.append(Tile(opts[0][0], opts[0][1], "image", aid, options=opts))
        placed, rows, holes = self.pack(comp, tiles)

        def render(t: Tile, rect) -> None:
            if t.kind in ("text", "number"):
                self.render_header(comp, sb, t, rect, state)
            elif t.kind == "swatch":
                sw = t.payload
                x, y, w, h = rect
                sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill=sw["hex"], radius=self.R, z=1))
                if C.delta_e(sw["hex"], self.paper) < 6:
                    sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill="transparent", stroke=C.mix(self.paper, comp.palette.ink, 0.2), stroke_width=1, radius=self.R, decorative=True, z=1))
                fg = comp.text_color(sw["hex"])
                pad = comp.px(22)
                name = sw.get("name") or comp.copy.swatch_role(sw.get("role", "neutral"))
                sb.add(comp.text(f"{name}\n{sw['hex']}\nRGB {C.rgb_string(sw['hex'])}", x + pad, y + h - pad - comp.px(54), w - 2 * pad, self.st_label(comp, fg, 11), "label"))
            else:
                self.render_image(comp, sb, t.payload, rect)

        y = self.draw_tiles(comp, sb, placed, rows, holes, top, render)
        sb.y = y
        return sb.finish(self.G * 3)

    def typography(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.paper, "light", "bento-type")
        top = self.G * 3
        fonts = None if ids else sp.meta.get("fonts")
        tiles = self.header_tiles(comp, sp, state, len(ids) or 2)
        if fonts:
            tiles.append(Tile(6, 5, "glyph", fonts["display"]))
            tiles.append(Tile(6, 5, "alphabet", fonts["display"]))
            if fonts["text"] != fonts["display"]:
                tiles.append(Tile(4, 4, "glyph", fonts["text"]))
                tiles.append(Tile(8, 4, "alphabet", fonts["text"]))
        for i, aid in enumerate(ids):
            opts = self.image_spans(comp, aid, lead=(i == 0))
            tiles.append(Tile(opts[0][0], opts[0][1], "image", aid, options=opts))
        placed, rows, holes = self.pack(comp, tiles)

        def render(t: Tile, rect) -> None:
            x, y, w, h = rect
            if t.kind in ("text", "number"):
                self.render_header(comp, sb, t, rect, state)
            elif t.kind == "glyph":
                fill = comp.palette.primary
                fg = comp.text_color(fill)
                sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill=fill, radius=self.R, decorative=True))
                fam = get_font(t.payload)
                g = comp.fitted_text("Aa", x, y + h * 0.12, w, TextStyle(t.payload, comp.px(300), fam.clamp_weight(500), 1.0, -0.02, fg), "label", max_lines=1, min_size=comp.px(60), max_size=h * 0.62, align="center")
                sb.add(g)
                sb.add(comp.text(fam.name, x + comp.px(24), y + h - comp.px(44), w - comp.px(48), self.st_label(comp, comp.muted(fg, fill, 0.3)), "label"))
            elif t.kind == "alphabet":
                fill = self.paper_alt
                fg = comp.text_color(fill)
                sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill=fill, radius=self.R, decorative=True))
                fam = get_font(t.payload)
                pad = comp.px(28)
                txt = "ABCDEFGHIJKLM\nNOPQRSTUVWXYZ\nabcdefghijklm\nnopqrstuvwxyz\n0123456789"
                a = comp.fitted_text(txt, x + pad, y + pad, w - 2 * pad, TextStyle(t.payload, comp.px(30), fam.clamp_weight(400), 1.3, 0.02, fg), "label", max_lines=5, min_size=comp.px(12), max_size=comp.px(34), max_height=h - 2 * pad, balance=False)
                sb.add(a)
            else:
                self.render_image(comp, sb, t.payload, rect)

        y = self.draw_tiles(comp, sb, placed, rows, holes, top, render)
        sb.y = y
        return sb.finish(self.G * 3)

    def before_after(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.paper, "light", "bento-ba")
        top = self.G * 3
        tiles = self.header_tiles(comp, sp, state, len(ids))
        placed, rows, holes = self.pack(comp, tiles)
        y = self.draw_tiles(comp, sb, placed, rows, holes, top, lambda t, r: self.render_header(comp, sb, t, r, state))
        y += self.G
        for i in range(0, len(ids) - 1, 2):
            pair = ids[i : i + 2]
            w = 6 * self.u + 5 * self.G
            a = comp.aspect(pair[0])
            h = w / a
            for j, aid in enumerate(pair):
                x = self.M + j * (w + self.G)
                sb.add(comp.image(aid, x, y, w, h, radius=self.R))
                label = comp.copy.s("before") if j == 0 else comp.copy.s("after")
                pill_w = comp.px(110)
                sb.add(Block(kind="shape", x=x + comp.px(16), y=y + comp.px(16), w=pill_w, h=comp.px(32), fill=comp.palette.ink, radius=comp.px(16), z=4, overlay=True))
                lb = comp.text(label, x + comp.px(30), y + comp.px(23), pill_w - comp.px(28), self.st_label(comp, comp.text_color(comp.palette.ink), 11), "caption")
                if lb:
                    lb.overlay, lb.z = True, 5
                    sb.add(lb)
            y += h + self.G
            sb.mark_break(y - self.G / 2)
        sb.y = y - self.G
        return sb.finish(self.G * 3)

    # ------------------------------------------------------------ closing
    def closing(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.paper, "light", "closing-bento")
        top = self.G * 3
        pal = comp.palette
        rect = self.rect(0, 0, 8, 4, top)
        x, y, w, h = rect
        fill = pal.ink
        fg = comp.text_color(fill)
        sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill=fill, radius=self.R, decorative=True))
        pad = comp.px(32)
        sb.add(comp.text(sp.subtitle or comp.ctx.plan.project_title, x + pad, y + pad, w - 2 * pad, self.st_label(comp, comp.muted(fg, fill, 0.3)), "subtitle", editable="subtitle"))
        t = comp.fitted_text(sp.title, x + pad, 0, w - 2 * pad, self.st_title(comp, 120, fg), "display", max_lines=2, min_size=comp.px(40), max_size=comp.px(130), max_height=h - 2 * pad - comp.px(40), editable="title")
        if t:
            t.y = round(y + h - pad - t.h, 2)
            sb.add(t)
        logo = sp.meta.get("logo_id")
        lrect = self.rect(0, 8, 4, 4, top)
        if logo and comp.asset(logo):
            self.logo_tile(comp, sb, logo, lrect, pal.primary)
        else:
            sb.add(Block(kind="shape", x=lrect[0], y=lrect[1], w=lrect[2], h=lrect[3], fill=pal.primary, radius=self.R, decorative=True))
        colors = list(dict.fromkeys([pal.primary, pal.secondary, pal.accent, self.paper_alt, pal.ink, C.mix(pal.primary, self.paper, 0.5)]))
        for i in range(6):
            r = self.rect(4, i * 2, 2, 1, top)
            sb.add(Block(kind="shape", x=r[0], y=r[1], w=r[2], h=r[3], fill=colors[i % len(colors)], radius=self.R, decorative=True))
        sb.y = top + 5 * self.u + 4 * self.G
        return sb.finish(self.M)
