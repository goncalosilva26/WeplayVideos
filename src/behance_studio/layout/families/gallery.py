"""Family 5 — Curated Gallery.

Museum-like curation: a quiet wall colour, every image at its own proportions
(never cropped), varied scales and asymmetric "hangs" with generous breathing
room, small figure labels, soft shadows, minimal typography and a contents
index on the cover. The imagery dominates.
"""

from __future__ import annotations

from typing import Any

from behance_studio.design import color as C
from behance_studio.design.typography import TypeSystem, get_font
from behance_studio.layout.composer import Composer, SectionBuilder
from behance_studio.layout.families.base import ComposeState, FamilyInfo, LayoutFamily
from behance_studio.layout.model import Block, Section, TextStyle
from behance_studio.planning.models import SectionPlan
from behance_studio.planning.planner import PlanPreferences

ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"]


class GalleryFamily(LayoutFamily):
    info = FamilyInfo(
        id="gallery",
        name="Curated Gallery",
        tagline="Museum-like curation where the work speaks",
        description="Quiet walls, uncropped images at varied scales, asymmetric hangs, figure labels and minimal typography with generous breathing room.",
        ideal_for=["Photography", "Illustration", "Product photography", "Visual art"],
        badge="#9AA5A0",
    )
    voices = {"editorial"}
    edge_style = "soft"

    def preferences(self, rng, creativity) -> PlanPreferences:
        return PlanPreferences(max_per_section=7, include_intro=True, closing_image=False, hero_rank=0, merge_small=2, split_logo_variations=False, shuffle=0.2 * creativity)

    def variant(self, ctx, rng) -> dict[str, Any]:
        return {
            "wall": rng.choice(["white", "warm", "stone"]),
            "margin": rng.choice([168, 192]),
            "labels": rng.choice(["fig", "index"]),
            "title_style": rng.choice(["italic", "roman"]),
            "header_align": rng.choice(["left", "left", "center"]),
            "numbering": rng.choice(["roman", "digits"]),
        }

    def setup(self, comp: Composer, v: dict[str, Any]) -> None:
        self.v = v
        self.ts = TypeSystem.from_dict(v["type_system"])
        pal = comp.palette
        paper = pal.paper if C.lightness(pal.paper) > 80 else "#F6F4EF"
        self.wall = {
            "white": C.mix(paper, "#FFFFFF", 0.7),
            "warm": C.mix(paper, "#FFFFFF", 0.35),
            "stone": C.mix(C.mix(paper, "#FFFFFF", 0.4), "#8C8C88", 0.12),
        }[v["wall"]]
        self.ink = comp.text_color(self.wall, pal.ink)
        self.soft = comp.muted(self.ink, self.wall, 0.4)
        self.M = comp.px(v["margin"])
        self.CW = comp.W - 2 * self.M
        fam = get_font(self.ts.display)
        self.italic = v["title_style"] == "italic" and bool(fam.italic)
        self.display_weight = fam.clamp_weight(400)
        self.fig = 0

    # ------------------------------------------------------------ styles
    def st_title(self, comp, size) -> TextStyle:
        return TextStyle(self.ts.display, comp.px(size), self.display_weight, 1.15, -0.005, self.ink, italic=self.italic)

    def st_label(self, comp, size=11, color=None) -> TextStyle:
        return TextStyle(self.ts.label, comp.px(size), get_font(self.ts.label).clamp_weight(500), 1.45, 0.18, color or self.soft, uppercase=True)

    def st_body(self, comp, size=16) -> TextStyle:
        return TextStyle(self.ts.text, comp.px(size), get_font(self.ts.text).clamp_weight(400), 1.7, 0.0, self.ink)

    def number(self, n: int) -> str:
        return ROMAN[(n - 1) % 20] if self.v["numbering"] == "roman" else f"{n:02d}"

    def label_for(self, comp: Composer, sp: SectionPlan, aid: str) -> str:
        self.fig += 1
        cap = sp.captions.get(aid)
        if self.v["labels"] == "fig":
            base = f"Fig. {self.fig:02d}"
        else:
            base = f"{self.fig:02d}"
        return f"{base} — {cap}" if cap else f"{base} — {sp.title}"

    # ----------------------------------------------------------- edges
    def edge_treatment(self, comp: Composer, section: Section) -> None:
        for b in section.blocks:
            if b.kind not in ("image", "video") or not b.asset_id or b.mat:
                continue
            asset = comp.asset(b.asset_id)
            if asset is None or asset.has_alpha:
                continue
            if b.w >= comp.W - 1:
                continue
            b.edge = "soft"

    # ----------------------------------------------------------- header
    def header(self, comp: Composer, sb: SectionBuilder, sp: SectionPlan, state: ComposeState) -> float:
        y = comp.px(210)
        align = self.v["header_align"]
        num = self.number(state.content_index + 1)
        if align == "center":
            sb.add(comp.text(num, self.M, y, self.CW, self.st_label(comp, 12), "eyebrow", align="center"))
            t = comp.fitted_text(sp.title, self.M, y + comp.px(30), self.CW, self.st_title(comp, 42), "title", max_lines=2, min_size=comp.px(28), max_size=comp.px(42), align="center", editable="title")
            sb.add(t)
            y = (t.bottom if t else y) + comp.px(18)
            body = comp.text(sp.body or sp.subtitle, self.M + (self.CW - comp.px(520)) / 2, y, comp.px(520), self.st_body(comp), "body", align="center", editable="body" if sp.body else "subtitle")
        else:
            sb.add(comp.text(num, self.M, y + comp.px(14), comp.px(80), self.st_label(comp, 12), "eyebrow"))
            t = comp.fitted_text(sp.title, self.M + comp.px(80), y, self.CW * 0.6, self.st_title(comp, 42), "title", max_lines=2, min_size=comp.px(28), max_size=comp.px(42), editable="title")
            sb.add(t)
            y = (t.bottom if t else y) + comp.px(18)
            body = comp.text(sp.body or sp.subtitle, self.M + comp.px(80), y, comp.px(500), self.st_body(comp), "body", editable="body" if sp.body else "subtitle")
        if body:
            sb.add(body)
            y = body.bottom
        y += comp.px(120)
        sb.mark_break(y - comp.px(60))
        return y

    # ------------------------------------------------------------ hanging
    def caption(self, comp: Composer, sb: SectionBuilder, sp: SectionPlan, b: Block | None) -> float:
        if b is None:
            return 0.0
        label = self.label_for(comp, sp, b.asset_id or "")
        t = comp.text(label, b.x, b.bottom + comp.px(16), max(b.w, comp.px(240)), self.st_label(comp, 10.5), "caption", editable=f"caption:{b.asset_id}" if b.asset_id in sp.captions else None)
        if t and t.right > comp.W - self.M * 0.5:
            t.x = round(max(self.M * 0.5, b.right - t.w), 2)
            t.align = "right"
        sb.add(t)
        return t.bottom if t else b.bottom

    def hang(self, comp: Composer, sb: SectionBuilder, sp: SectionPlan, ids: list[str], y: float, state: ComposeState) -> float:
        """Sequence of groups: singles, offset pairs and triptychs."""
        i = 0
        group = 0
        rng = comp.rng
        while i < len(ids):
            remaining = len(ids) - i
            aspects = [comp.aspect(a) for a in ids[i : i + 3]]
            choice = "single"
            if remaining >= 3 and all(a < 1.1 for a in aspects) and rng.random() < 0.6:
                choice = "triptych"
            elif remaining >= 2 and rng.random() < 0.65:
                choice = "pair"
            if group > 0:
                sb.mark_break(y - comp.px(70))
            if choice == "single":
                aid = ids[i]
                frac = rng.choice([0.62, 0.74, 0.86, 0.94]) if comp.aspect(aid) >= 1 else rng.choice([0.44, 0.52, 0.6])
                w = self.CW * frac
                pos = rng.choice(["center", "left", "right"])
                x = {"center": self.M + (self.CW - w) / 2, "left": self.M, "right": self.M + self.CW - w}[pos]
                b = comp.natural(aid, x, y, w, max_h=comp.px(900), align={"center": "center", "left": "left", "right": "right"}[pos])
                sb.add(b)
                y = self.caption(comp, sb, sp, b)
                i += 1
            elif choice == "pair":
                a, b2 = ids[i], ids[i + 1]
                wa, wb = self.CW * 0.5, self.CW * 0.33
                if group % 2:
                    wa, wb = wb, wa
                gap = self.CW - wa - wb - comp.px(40)
                gap = max(comp.px(72), min(gap, comp.px(120)))
                total = wa + wb + gap
                x0 = self.M + (self.CW - total) / 2
                pa = comp.natural(a, x0, 0, wa, max_h=comp.px(860), align="left")
                pb = comp.natural(b2, x0 + wa + gap, 0, wb, max_h=comp.px(760), align="left")
                ha, hb = (pa.h if pa else 0), (pb.h if pb else 0)
                base = y + max(ha, hb)
                if pa:
                    pa.y = round(base - ha, 2)
                    sb.add(pa)
                if pb:
                    pb.y = round(base - hb, 2)
                    sb.add(pb)
                y = max(self.caption(comp, sb, sp, pa), self.caption(comp, sb, sp, pb))
                i += 2
            else:
                trio = ids[i : i + 3]
                blocks, h = comp.row(trio, self.M + self.CW * 0.07, y, self.CW * 0.86, comp.px(56), max_h=comp.px(620))
                sb.extend(blocks)
                bottom = y + h
                for blk in blocks:
                    bottom = max(bottom, self.caption(comp, sb, sp, blk))
                y = bottom
                i += 3
            y += comp.px(140)
            group += 1
        return y - comp.px(140)

    # ------------------------------------------------------------- cover
    def cover(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.wall, "light", "cover-gallery")
        y = comp.px(120)
        t = comp.fitted_text(sp.title, self.M, y, self.CW * 0.6, self.st_title(comp, 56), "display", max_lines=2, min_size=comp.px(34), max_size=comp.px(60), editable="title")
        sb.add(t)
        sb.add(comp.text(sp.eyebrow or comp.ctx.plan.category_label, self.M + self.CW * 0.6, y + comp.px(18), self.CW * 0.4, self.st_label(comp, 11), "eyebrow", align="right", editable="eyebrow"))
        y = (t.bottom if t else y) + comp.px(10)
        sub = comp.text(sp.subtitle, self.M, y, self.CW * 0.6, self.st_body(comp, 17), "subtitle", editable="subtitle")
        if sub:
            sb.add(sub)
            y = sub.bottom
        y += comp.px(120)
        ids = comp.assets_of(sp)
        if ids:
            b = comp.natural(ids[0], self.M + self.CW * 0.14, y, self.CW * 0.72, max_h=comp.px(860))
            sb.add(b)
            y = (b.bottom if b else y) + comp.px(20)
        y += comp.px(120)
        sb.mark_break(y - comp.px(60))
        # Contents index: the sections of this presentation (true information).
        entries = [s for s in comp.ctx.plan.sections if s.type not in ("cover", "closing") and not s.meta.get("hidden")]
        if entries:
            sb.add(Block(kind="shape", x=self.M, y=y, w=self.CW, h=max(1.0, comp.k), fill=C.mix(self.ink, self.wall, 0.85), decorative=True))
            y += comp.px(28)
            sb.add(comp.text(comp.copy.s("contents"), self.M, y, comp.px(200), self.st_label(comp, 11), "label"))
            cols = 2
            per_col = (len(entries) + cols - 1) // cols
            col_w = (self.CW - comp.px(260)) / cols
            bottom = y
            for idx, s in enumerate(entries):
                c, r = divmod(idx, per_col)
                x = self.M + comp.px(260) + c * col_w
                line_y = y + r * comp.px(30)
                tb = comp.text(f"{self.number(idx + 1)}    {s.title}", x, line_y, col_w - comp.px(20), TextStyle(self.ts.text, comp.px(14), 400, 1.4, 0.0, self.ink), "label")
                sb.add(tb)
                bottom = max(bottom, tb.bottom if tb else line_y)
            y = bottom
        sb.y = y
        return sb.finish(comp.px(150))

    # ---------------------------------------------------------- statement
    def statement(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.wall, "light", "statement-gallery")
        y = comp.px(200)
        sb.add(comp.text(f"{self.number(state.content_index + 1)}   {sp.title}", self.M, y, self.CW, self.st_label(comp, 11), "title", align="center", editable="title"))
        y += comp.px(56)
        w = comp.px(640)
        body = comp.text(sp.body, (comp.W - w) / 2, y, w, TextStyle(self.ts.display, comp.px(23), self.display_weight, 1.55, 0.0, self.ink), "body", align="center", editable="body")
        if body:
            sb.add(body)
            y = body.bottom
        quote = sp.meta.get("quote")
        if quote:
            q = comp.text(f"— {quote}", (comp.W - w) / 2, y + comp.px(40), w, self.st_title(comp, 24).with_(italic=bool(get_font(self.ts.display).italic)), "quote", align="center")
            if q:
                sb.add(q)
                y = q.bottom
        sb.y = y
        return sb.finish(comp.px(200))

    # ------------------------------------------------------------- media
    def media(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.wall, "light", "hang")
        y = self.header(comp, sb, sp, state)
        y = self.hang(comp, sb, sp, ids, y, state)
        sb.y = y
        return sb.finish(comp.px(120))

    def logo(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.wall, "light", "logo-plinths")
        y = self.header(comp, sb, sp, state)
        n = len(ids)
        per_row = 1 if n == 1 else (2 if n in (2, 4) else 3)
        cell_w = (self.CW - comp.px(48) * (per_row - 1)) / per_row
        cell_h = cell_w * (0.5 if per_row == 1 else 0.72)
        for i, aid in enumerate(ids):
            r, c = divmod(i, per_row)
            x = self.M + c * (cell_w + comp.px(48))
            top = y + r * (cell_h + comp.px(90))
            if c == 0 and r > 0:
                sb.mark_break(top - comp.px(45))
            asset = comp.asset(aid)
            a = (asset.analysis or {}) if asset else {}
            if a.get("background") not in (None, "transparent") and a.get("background_uniformity", 0) >= 0.9:
                b = comp.natural(aid, x + cell_w * 0.12, top, cell_w * 0.76, max_h=cell_h)
                sb.add(b)
                self.caption(comp, sb, sp, b)
                continue
            backdrop = comp.logo_backdrop(asset, self.wall)
            if backdrop != self.wall:
                sb.add(Block(kind="shape", x=x, y=top, w=cell_w, h=cell_h, fill=backdrop, decorative=True))
            b = comp.image(aid, x + cell_w * 0.2, top + cell_h * 0.22, cell_w * 0.6, cell_h * 0.56, prefer="contain")
            sb.add(b)
            lab = comp.text(self.label_for(comp, sp, aid), x, top + cell_h + comp.px(16), cell_w, self.st_label(comp, 10.5), "caption")
            sb.add(lab)
        rows = (n + per_row - 1) // per_row
        y += rows * cell_h + (rows - 1) * comp.px(90) + comp.px(40)
        sb.y = y
        return sb.finish(comp.px(120))

    def palette(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.wall, "light", "palette-chips")
        y = self.header(comp, sb, sp, state)
        swatches = [] if ids else (sp.meta.get("swatches") or [])
        if swatches:
            n = len(swatches)
            d = comp.px(150)
            gap = comp.px(64)
            total = n * d + (n - 1) * gap
            x0 = (comp.W - total) / 2
            for i, sw in enumerate(swatches):
                x = x0 + i * (d + gap)
                sb.add(Block(kind="shape", x=x, y=y, w=d, h=d, fill=sw["hex"], shape="circle", z=1))
                if C.delta_e(sw["hex"], self.wall) < 8:
                    sb.add(Block(kind="shape", x=x, y=y, w=d, h=d, shape="ring", stroke=C.mix(self.ink, self.wall, 0.8), stroke_width=1, decorative=True))
                name = sw.get("name") or comp.copy.swatch_role(sw.get("role", "neutral"))
                sb.add(comp.text(f"{name}\n{sw['hex']}", x - comp.px(20), y + d + comp.px(22), d + comp.px(40), self.st_label(comp, 10.5), "label", align="center"))
            y += d + comp.px(90)
        if ids:
            y = self.hang(comp, sb, sp, ids, y, state)
        sb.y = y
        return sb.finish(comp.px(120))

    def typography(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.wall, "light", "type-gallery")
        y = self.header(comp, sb, sp, state)
        fonts = None if ids else sp.meta.get("fonts")
        if fonts:
            half = self.CW / 2
            for i, fam_name in enumerate(dict.fromkeys([fonts["display"], fonts["text"]])):
                fam = get_font(fam_name)
                x = self.M + i * half
                glyph = comp.text("Aa", x, y, half, TextStyle(fam_name, comp.px(180), fam.clamp_weight(400), 1.0, -0.01, self.ink), "label", align="center")
                sb.add(glyph)
                sb.add(comp.text(fam.name, x, (glyph.bottom if glyph else y) + comp.px(10), half, self.st_label(comp, 11), "label", align="center"))
            y += comp.px(260)
        if ids:
            y = self.hang(comp, sb, sp, ids, y, state)
        sb.y = y
        return sb.finish(comp.px(120))

    def before_after(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.wall, "light", "ba-gallery")
        y = self.header(comp, sb, sp, state)
        for i in range(0, len(ids) - 1, 2):
            blocks, h = comp.row(ids[i : i + 2], self.M, y, self.CW, comp.px(48), max_h=comp.px(760))
            sb.extend(blocks)
            for b, label in zip(blocks, (comp.copy.s("before"), comp.copy.s("after"))):
                sb.add(comp.text(label, b.x, b.bottom + comp.px(16), b.w, self.st_label(comp, 10.5), "caption"))
            y += h + comp.px(150)
            sb.mark_break(y - comp.px(75))
        sb.y = y - comp.px(100)
        return sb.finish(comp.px(120))

    # ------------------------------------------------------------ closing
    def closing(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.wall, "light", "closing-gallery")
        y = comp.px(240)
        logo = sp.meta.get("logo_id")
        if logo and comp.asset(logo):
            la = comp.asset(logo)
            backdrop = comp.logo_backdrop(la, self.wall)
            box_w, box_h = comp.px(300), comp.px(90)
            if backdrop != self.wall:
                sb.add(Block(kind="shape", x=(comp.W - box_w * 1.4) / 2, y=y - box_h * 0.3, w=box_w * 1.4, h=box_h * 1.6, fill=backdrop, decorative=True))
            sb.add(comp.image(logo, (comp.W - box_w) / 2, y, box_w, box_h, prefer="contain"))
            y += box_h + comp.px(90)
        t = comp.text(sp.title, self.M, y, self.CW, self.st_title(comp, 44), "display", align="center", editable="title")
        sb.add(t)
        y = (t.bottom if t else y) + comp.px(18)
        s2 = comp.text(sp.subtitle or f"{comp.ctx.plan.project_title} — {comp.ctx.plan.category_label}", self.M, y, self.CW, self.st_label(comp, 11), "subtitle", align="center", editable="subtitle")
        sb.add(s2)
        sb.y = (s2.bottom if s2 else y)
        return sb.finish(comp.px(240))
