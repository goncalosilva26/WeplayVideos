"""Family 1 — Editorial Classic.

Premium editorial design: a 12-column grid with generous outer margins,
hanging section headers (number in the first columns, serif title on the
grid), hairline rules, controlled whitespace, captioned images and a calm,
balanced rhythm. Light paper backgrounds dominate; colour appears in
palette swatches and occasional identity panels.
"""

from __future__ import annotations

from typing import Any

from behance_studio.design import color as C
from behance_studio.design.typography import TypeSystem, get_font
from behance_studio.layout.composer import Composer, SectionBuilder, best_arrangement
from behance_studio.layout.families.base import ComposeState, FamilyInfo, LayoutFamily
from behance_studio.layout.fitting import best_crop_aspect
from behance_studio.layout.model import Block, Section, TextStyle
from behance_studio.planning.models import SectionPlan
from behance_studio.planning.planner import PlanPreferences

ALPHABET = "ABCDEFGHIJKLM\nNOPQRSTUVWXYZ\nabcdefghijklm\nnopqrstuvwxyz\n0123456789 &?!"


class EditorialFamily(LayoutFamily):
    info = FamilyInfo(
        id="editorial",
        name="Editorial Classic",
        tagline="Refined grids, serif headlines, controlled whitespace",
        description="Premium editorial design with a 12-column grid, hanging headers, hairline rules and captioned, balanced compositions.",
        ideal_for=["Brand identity", "Graphic design", "Minimal identities", "Premium products"],
        badge="#C9A46A",
    )
    voices = {"editorial"}

    def preferences(self, rng, creativity) -> PlanPreferences:
        return PlanPreferences(max_per_section=8, include_intro=True, closing_image=False, hero_rank=0, merge_small=2, split_logo_variations=True, shuffle=0.15 * creativity, hero_aspect=16 / 9)

    def variant(self, ctx, rng) -> dict[str, Any]:
        return {
            "margin": rng.choice([96, 112, 128]),
            "gutter": 24,
            "pad": rng.choice([136, 152, 168]),
            "header": rng.choice(["hanging", "hanging", "stacked"]),
            "cover": rng.choice(["masthead", "image_first"]),
            "title_size": rng.choice([58, 64, 72]),
            "logo_panel": rng.choice(["alt", "primary", "ink"]),
            "numbering": rng.choice(["digits", "no", "roman"]),
            "full_bleed": rng.random() < 0.5,
        }

    # ----------------------------------------------------------- styles
    def setup(self, comp: Composer, v: dict[str, Any]) -> None:
        self.v = v
        self.ts = TypeSystem.from_dict(v["type_system"])
        k = comp.k
        pal = comp.palette
        self.paper = pal.paper if C.lightness(pal.paper) > 85 else C.with_lightness(pal.paper, 95, 0.4)
        self.paper_alt = C.mix(self.paper, pal.ink, 0.075)
        self.ink = comp.text_color(self.paper, pal.ink)
        self.soft = comp.muted(self.ink, self.paper, 0.32)
        self.rule = C.mix(self.ink, self.paper, 0.82)
        self.M = v["margin"] * k
        self.G = v["gutter"] * k
        self.CW = comp.W - 2 * self.M
        self.col = (self.CW - 11 * self.G) / 12
        self.P = v["pad"] * k
        self.Pt = self.P * 0.62  # space above the section rule
        self.Pb = self.P * 0.6  # space below the last content
        dw = 400 if get_font(self.ts.display).category == "serif" else 500
        self.display_weight = get_font(self.ts.display).clamp_weight(dw)

    def cx(self, col: int) -> float:
        return self.M + col * (self.col + self.G)

    def span(self, cols: int) -> float:
        return cols * self.col + (cols - 1) * self.G

    def st_display(self, comp, size, color=None, weight=None) -> TextStyle:
        return TextStyle(self.ts.display, comp.px(size), weight or self.display_weight, 1.06, -0.012, color or self.ink)

    def st_body(self, comp, size=18, color=None) -> TextStyle:
        return TextStyle(self.ts.text, comp.px(size), get_font(self.ts.text).clamp_weight(400), 1.62, 0.0, color or self.ink)

    def st_label(self, comp, color=None, size=12) -> TextStyle:
        return TextStyle(self.ts.label, comp.px(size), get_font(self.ts.label).clamp_weight(600), 1.4, 0.16, color or self.soft, uppercase=True)

    def number(self, n: int) -> str:
        style = self.v["numbering"]
        if style == "roman":
            return ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX"][(n - 1) % 20]
        if style == "no":
            return f"No. {n:02d}"
        return f"{n:02d}"

    # ------------------------------------------------------------ header
    def header(self, comp: Composer, sb: SectionBuilder, sp: SectionPlan, state: ComposeState, bg: str) -> None:
        ink = comp.text_color(bg, self.ink)
        soft = comp.muted(ink, bg, 0.32)
        rule = C.mix(ink, bg, 0.82)
        num = self.number(state.content_index + 1)
        sb.y = self.Pt
        sb.add(Block(kind="shape", x=self.M, y=sb.y, w=self.CW, h=max(1.0, comp.px(1)), fill=rule, decorative=True, z=1))
        sb.y += comp.px(28)
        size = self.v["title_size"]
        if self.v["header"] == "hanging":
            label = comp.text(num, self.M, sb.y + comp.px(4), self.span(2), self.st_label(comp, soft, 13), "eyebrow")
            sb.add(label)
            eyebrow_text = sp.eyebrow if sp.eyebrow else ""
            if eyebrow_text and label:
                sb.add(comp.text(eyebrow_text, self.M, label.bottom + comp.px(6), self.span(3), self.st_label(comp, soft, 11), "eyebrow", editable="eyebrow"))
            title = comp.fitted_text(sp.title, self.cx(3), sb.y, self.span(9), self.st_display(comp, size, ink), "title", max_lines=2, min_size=comp.px(36), max_size=comp.px(size), editable="title")
            sb.add(title)
            y = title.bottom if title else sb.y
            sub = comp.text(sp.subtitle, self.cx(3), y + comp.px(18), self.span(7), self.st_body(comp, 22, ink).with_(line_height=1.45), "subtitle", editable="subtitle")
            if sub:
                sb.add(sub)
                y = sub.bottom
            body = comp.text(sp.body, self.cx(3), y + comp.px(24), self.span(6), self.st_body(comp, 18, ink), "body", editable="body")
            if body:
                sb.add(body)
                y = body.bottom
            sb.y = y
        else:
            label_text = f"{num}   {sp.eyebrow}".strip() if sp.eyebrow else num
            label = comp.text(label_text, self.M, sb.y, self.span(6), self.st_label(comp, soft, 13), "eyebrow")
            sb.add(label)
            y = (label.bottom if label else sb.y) + comp.px(20)
            title = comp.fitted_text(sp.title, self.M, y, self.span(9), self.st_display(comp, size, ink), "title", max_lines=2, min_size=comp.px(36), max_size=comp.px(size), editable="title")
            sb.add(title)
            y = title.bottom if title else y
            sub = comp.text(sp.subtitle, self.M, y + comp.px(18), self.span(7), self.st_body(comp, 22, ink).with_(line_height=1.45), "subtitle", editable="subtitle")
            if sub:
                sb.add(sub)
                y = sub.bottom
            body = comp.text(sp.body, self.M, y + comp.px(22), self.span(6), self.st_body(comp, 18, ink), "body", editable="body")
            if body:
                sb.add(body)
                y = body.bottom
            sb.y = y
        sb.y += comp.px(64)
        sb.mark_break(sb.y - comp.px(32))

    # ------------------------------------------------------------- cover
    def cover(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        hero = ids[0] if ids else None
        style = self.v["cover"] if hero else "logo"
        sb = SectionBuilder(sp, self.paper, "light", f"cover-{style}")
        k = comp.k
        if style == "masthead":
            top = comp.px(56)
            sb.add(comp.text(sp.title, self.M, top, self.span(6), self.st_label(comp, self.ink, 12), "label"))
            sb.add(comp.text(sp.eyebrow or comp.ctx.plan.category_label, self.cx(6), top, self.span(6), self.st_label(comp, self.soft, 12), "eyebrow", align="right", editable="eyebrow"))
            sb.add(Block(kind="shape", x=self.M, y=top + comp.px(36), w=self.CW, h=max(1.0, k), fill=self.rule, decorative=True))
            y = top + comp.px(110)
            title = comp.fitted_text(sp.title, self.M, y, self.span(11), self.st_display(comp, 168, self.ink).with_(line_height=0.98, tracking=-0.025), "display", max_lines=2, min_size=comp.px(72), max_size=comp.px(176), editable="title")
            sb.add(title)
            y = title.bottom + comp.px(28) if title else y
            sub = comp.text(sp.subtitle, self.M, y, self.span(6), self.st_body(comp, 24, self.ink).with_(line_height=1.4), "subtitle", editable="subtitle")
            if sub:
                sb.add(sub)
                y = sub.bottom
            y += comp.px(72)
            sb.mark_break(y - comp.px(36))
            asset = comp.asset(hero)
            aspect = best_crop_aspect(asset, [16 / 9, 2.0, 3 / 2]) if asset else None
            if aspect:
                h = self.CW / aspect
                sb.add(comp.image(hero, self.M, y, self.CW, h))
            else:
                b = comp.natural(hero, self.M, y, self.CW, max_h=comp.px(900))
                sb.add(b)
                h = b.h if b else 0
            sb.y = y + h
            return sb.finish(comp.px(112))
        if style == "image_first":
            asset = comp.asset(hero)
            aspect = best_crop_aspect(asset, [16 / 9, 3 / 2, 2.0]) if asset else None
            if aspect:
                h = min(comp.W / aspect, comp.px(900))
                sb.add(comp.image(hero, 0, 0, comp.W, h))
                y = h
            else:
                sb.add(Block(kind="shape", x=0, y=0, w=comp.W, h=comp.px(860), fill=self.paper_alt, decorative=True))
                b = comp.natural(hero, self.M, comp.px(96), self.CW, max_h=comp.px(668))
                sb.add(b)
                y = comp.px(860)
            y += comp.px(88)
            sb.mark_break(y - comp.px(44))
            sb.add(comp.text(sp.eyebrow or comp.ctx.plan.category_label, self.M, y + comp.px(14), self.span(3), self.st_label(comp, self.soft, 12), "eyebrow", editable="eyebrow"))
            title = comp.fitted_text(sp.title, self.cx(3), y, self.span(9), self.st_display(comp, 120, self.ink).with_(line_height=1.0, tracking=-0.02), "display", max_lines=2, min_size=comp.px(64), max_size=comp.px(132), editable="title")
            sb.add(title)
            y = title.bottom + comp.px(24) if title else y
            sub = comp.text(sp.subtitle, self.cx(3), y, self.span(6), self.st_body(comp, 22, self.ink).with_(line_height=1.45), "subtitle", editable="subtitle")
            if sub:
                sb.add(sub)
                y = sub.bottom
            sb.y = y
            return sb.finish(comp.px(120))
        # logo-centric cover (no hero image)
        logo_id = sp.meta.get("logo_id")
        y = comp.px(180)
        if logo_id and comp.asset(logo_id):
            box_w, box_h = self.span(6), comp.px(300)
            b = comp.image(logo_id, (comp.W - box_w) / 2, y, box_w, box_h, prefer="contain")
            sb.add(b)
            y += box_h + comp.px(96)
        title = comp.fitted_text(sp.title, self.M, y, self.CW, self.st_display(comp, 112, self.ink), "display", max_lines=2, min_size=comp.px(56), max_size=comp.px(120), align="center", editable="title")
        sb.add(title)
        y = title.bottom + comp.px(24) if title else y
        sub = comp.text(sp.subtitle, self.cx(3), y, self.span(6), self.st_body(comp, 22, self.ink), "subtitle", align="center", editable="subtitle")
        if sub:
            sb.add(sub)
            y = sub.bottom
        sb.add(comp.text(sp.eyebrow or comp.ctx.plan.category_label, self.M, y + comp.px(48), self.CW, self.st_label(comp, self.soft), "eyebrow", align="center", editable="eyebrow"))
        sb.y = y + comp.px(80)
        return sb.finish(comp.px(160))

    # --------------------------------------------------------- statement
    def statement(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.paper, "light", "statement")
        num = self.number(state.content_index + 1)
        sb.y = self.Pt
        sb.add(Block(kind="shape", x=self.M, y=sb.y, w=self.CW, h=max(1.0, comp.k), fill=self.rule, decorative=True))
        sb.y += comp.px(28)
        sb.add(comp.text(num, self.M, sb.y + comp.px(4), self.span(2), self.st_label(comp, self.soft, 13), "eyebrow"))
        sb.add(comp.text(sp.title, self.M, sb.y + comp.px(28), self.span(3), self.st_label(comp, self.soft, 11), "title", editable="title"))
        lead_style = TextStyle(self.ts.display, comp.px(34), self.display_weight, 1.32, -0.01, self.ink)
        if len(sp.body) > 520:
            lead_style = lead_style.with_(size=comp.px(26), line_height=1.42)
        body = comp.text(sp.body, self.cx(3), sb.y, self.span(8), lead_style, "body", editable="body")
        y = sb.y
        if body:
            sb.add(body)
            y = body.bottom
        audience = sp.meta.get("audience")
        quote = sp.meta.get("quote")
        if quote:
            y += comp.px(64)
            q = comp.text(f"“{quote}”", self.cx(3), y, self.span(8), TextStyle(self.ts.display, comp.px(44), self.display_weight, 1.12, -0.015, self.ink, italic=bool(get_font(self.ts.display).italic)), "quote")
            if q:
                sb.add(Block(kind="shape", x=self.cx(3) - comp.px(28), y=y + comp.px(6), w=max(2.0, comp.px(3)), h=q.h - comp.px(10), fill=C.ensure_contrast(comp.palette.secondary, self.paper, 3.0), decorative=True))
                sb.add(q)
                y = q.bottom
        sb.y = y
        return sb.finish(self.P * 0.9)

    # -------------------------------------------------------------- logo
    def logo_tile(self, comp: Composer, sb: SectionBuilder, aid: str, x: float, y: float, w: float, h: float, preferred_bg: str, scale: float = 0.56) -> None:
        asset = comp.asset(aid)
        if asset is None:
            return
        a = asset.analysis or {}
        if a.get("background") not in (None, "transparent") and a.get("background_uniformity", 0) >= 0.9:
            # The logo sits on its own plain background: extend it as the tile.
            bg = a["background"]
        else:
            bg = comp.logo_backdrop(asset, preferred_bg, avoid=self.paper)
        sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill=bg, decorative=True, z=1))
        bw, bh = w * scale, h * scale
        sb.add(comp.image(aid, x + (w - bw) / 2, y + (h - bh) / 2, bw, bh, prefer="contain", z=2))

    def logo(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.paper, "light", "logo-tiles")
        self.header(comp, sb, sp, state, self.paper)
        pal = comp.palette
        panel = {"alt": self.paper_alt, "primary": pal.primary, "ink": pal.ink}[self.v["logo_panel"]]
        cycle = [panel, self.paper_alt, pal.primary, pal.ink, pal.secondary]
        cycle = list(dict.fromkeys(cycle))
        y = sb.y
        n = len(ids)
        G = self.G

        def caption(aid: str, x: float, top: float, w: float) -> float:
            cap = sp.captions.get(aid)
            if not cap:
                return top
            t = comp.text(cap, x, top + comp.px(12), w, self.st_label(comp, self.soft, 11), "caption", editable=f"caption:{aid}")
            sb.add(t)
            return t.bottom if t else top

        if n == 2:
            w = (self.CW - G) / 2
            h = w * 0.82
            bottom = y + h
            for i, aid in enumerate(ids):
                x = self.M + i * (w + G)
                self.logo_tile(comp, sb, aid, x, y, w, h, cycle[i % len(cycle)], scale=0.56)
                bottom = max(bottom, caption(aid, x, y + h, w))
            y = bottom
        else:
            first, rest = ids[0], ids[1:]
            h = comp.px(560) if comp.aspect(first) >= 1.4 else comp.px(680)
            self.logo_tile(comp, sb, first, self.M, y, self.CW, h, cycle[0], scale=0.5)
            y = caption(first, self.M, y + h, self.CW) + G
            if rest:
                sb.mark_break(y - G / 2)
                per_row = 3 if len(rest) >= 3 and len(rest) != 4 else 2
                tile_w = (self.CW - G * (per_row - 1)) / per_row
                tile_h = tile_w * (0.78 if per_row == 3 else 0.68)
                row_bottom = y
                for i, aid in enumerate(rest):
                    r, c = divmod(i, per_row)
                    top = y + r * (tile_h + G + comp.px(28 if sp.captions else 0))
                    if c == 0 and r > 0:
                        sb.mark_break(top - G / 2)
                    x = self.M + c * (tile_w + G)
                    self.logo_tile(comp, sb, aid, x, top, tile_w, tile_h, cycle[(i + 1) % len(cycle)], scale=0.5)
                    row_bottom = max(row_bottom, caption(aid, x, top + tile_h, tile_w))
                y = row_bottom
        sb.y = y
        return sb.finish(self.Pb)

    # ----------------------------------------------------------- palette
    def palette(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.paper, "light", "palette-columns")
        self.header(comp, sb, sp, state, self.paper)
        image_ids = comp.assets_of(sp)
        # The designer's own palette artwork takes precedence over generated swatches.
        swatches = [] if image_ids else (sp.meta.get("swatches") or [])
        y = sb.y
        if swatches:
            n = len(swatches)
            weights = [2.0 if i == 0 else 1.0 for i in range(n)]
            total = sum(weights)
            avail = self.CW
            h = comp.px(460)
            x = self.M
            for i, sw in enumerate(swatches):
                w = avail * weights[i] / total
                fill = sw["hex"]
                sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill=fill, z=1))
                if C.delta_e(fill, self.paper) < 6:
                    sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill="transparent", stroke=self.rule, stroke_width=max(1.0, comp.k), z=1, decorative=True))
                fg = comp.text_color(fill)
                name = sw.get("name") or comp.copy.swatch_role(sw.get("role", "neutral"))
                pad = comp.px(22)
                label_y = y + h - pad - comp.px(64)
                sb.add(comp.text(name, x + pad, label_y, w - 2 * pad, TextStyle(self.ts.display, comp.px(24 if w > comp.px(200) else 19), self.display_weight, 1.15, 0, fg), "label"))
                sb.add(comp.text(f"{sw['hex']}\nRGB {C.rgb_string(fill)}", x + pad, label_y + comp.px(32), w - 2 * pad, TextStyle(self.ts.label, comp.px(11), 500, 1.45, 0.08, fg, uppercase=True), "label"))
                x += w
            y += h
        if image_ids:
            arr = best_arrangement(comp, image_ids, self.M, y, self.CW, self.G, comp.px(560), comp.px(1500), ["lead", "rows", "pair"], state.recent())
            sb.extend(arr.blocks)
            for br in arr.breaks:
                sb.mark_break(br)
            y += arr.height
        sb.y = y
        return sb.finish(self.Pb)

    # -------------------------------------------------------- typography
    def specimen(self, comp: Composer, sb: SectionBuilder, family: str, role_label: str, y: float, big: float) -> float:
        fam = get_font(family)
        glyph_style = TextStyle(family, comp.px(big), fam.clamp_weight(500 if fam.category != "serif" else 400), 1.0, -0.02, self.ink)
        glyph = comp.text("Aa", self.M, y, self.span(5), glyph_style, "label")
        sb.add(glyph)
        right = self.cx(5)
        sb.add(comp.text(role_label, right, y + comp.px(8), self.span(7), self.st_label(comp, self.soft, 12), "label"))
        name = comp.text(fam.name, right, y + comp.px(36), self.span(7), TextStyle(family, comp.px(46), fam.clamp_weight(500), 1.1, -0.01, self.ink), "label")
        sb.add(name)
        alpha = comp.text(ALPHABET, right, (name.bottom if name else y) + comp.px(22), self.span(7), TextStyle(family, comp.px(24), fam.clamp_weight(400), 1.4, 0.02, self.ink), "label")
        sb.add(alpha)
        bottom = max(b.bottom for b in (glyph, name, alpha) if b is not None)
        return bottom

    def typography(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.paper, "light", "type-specimen")
        self.header(comp, sb, sp, state, self.paper)
        image_ids = comp.assets_of(sp)
        fonts = None if image_ids else sp.meta.get("fonts")
        y = sb.y
        if fonts:
            y = self.specimen(comp, sb, fonts["display"], fonts.get("display_label", "Headlines"), y, 260)
            if fonts["text"] != fonts["display"]:
                y += comp.px(56)
                sb.add(Block(kind="shape", x=self.M, y=y, w=self.CW, h=max(1.0, comp.k), fill=self.rule, decorative=True))
                sb.mark_break(y)
                y += comp.px(56)
                y = self.specimen(comp, sb, fonts["text"], fonts.get("text_label", "Body copy"), y, 200)
        if image_ids:
            for i, aid in enumerate(image_ids):
                if i:
                    sb.mark_break(y - self.G / 2)
                b = comp.natural(aid, self.M, y, self.CW, max_h=comp.px(1000))
                if b:
                    sb.add(b)
                    y = b.bottom + self.G
            y -= self.G
        sb.y = y
        return sb.finish(self.Pb)

    # ------------------------------------------------------------- media
    def caption_under(self, comp: Composer, sb: SectionBuilder, sp: SectionPlan, block: Block | None) -> float:
        if block is None or not block.asset_id:
            return block.bottom if block else 0.0
        cap = sp.captions.get(block.asset_id)
        if not cap:
            return block.bottom
        t = comp.text(cap, block.x, block.bottom + comp.px(14), max(block.w, comp.px(160)), self.st_label(comp, self.soft, 11), "caption", editable=f"caption:{block.asset_id}")
        sb.add(t)
        return t.bottom if t else block.bottom

    def media(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        n = len(ids)
        hint = sp.layout_hint
        sb = SectionBuilder(sp, self.paper, "light", "")
        self.header(comp, sb, sp, state, self.paper)
        y = sb.y
        M, CW, G = self.M, self.CW, self.G
        recent = state.recent(2)
        asset = comp.asset(ids[0])
        bleed_aspect = best_crop_aspect(asset, [16 / 9, 3 / 2]) if asset else None
        if n == 1 and bleed_aspect and asset.width >= comp.W * 0.8 and (hint == "full-bleed" or (self.v["full_bleed"] and "single-bleed" not in recent and hint != "single")):
            sb.pattern = "single-bleed"
            h = comp.W / bleed_aspect
            sb.add(comp.image(ids[0], 0, y, comp.W, h))
            sb.y = y + h
            return sb.finish(self.Pb)
        if hint == "two-up" and n >= 2:
            patterns = ["pair", "rows"]
        elif hint == "grid":
            patterns = ["rows", "rows4", "masonry"]
        elif hint in ("single", "hero", "full-bleed"):
            patterns = ["lead", "rows"]
        else:
            patterns = ["rows", "lead", "asym", "pair", "stack2", "rows4"]
        arr = best_arrangement(comp, ids, M, y, CW, G, comp.px(400), comp.px(1900), patterns, recent)
        sb.pattern = arr.name
        sb.extend(arr.blocks)
        for br in arr.breaks:
            sb.mark_break(br)
        y += arr.height
        media_tops = {round(b.y) for b in arr.blocks if b.asset_id}
        if n <= 3 and sp.captions and len(media_tops) == 1:
            bottom = y
            for b in arr.blocks:
                bottom = max(bottom, self.caption_under(comp, sb, sp, b))
            y = bottom
        sb.y = y
        return sb.finish(self.Pb)

    def before_after(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.paper, "light", "before-after")
        self.header(comp, sb, sp, state, self.paper)
        y = sb.y
        for i in range(0, len(ids) - 1, 2):
            pair = ids[i : i + 2]
            blocks, h = comp.row(pair, self.M, y, self.CW, self.G)
            sb.extend(blocks)
            for blk, label in zip(blocks, (comp.copy.s("before"), comp.copy.s("after"))):
                sb.add(comp.text(label, blk.x, blk.bottom + comp.px(14), blk.w, self.st_label(comp, self.soft, 11), "caption"))
            y += h + comp.px(48) + self.G
            sb.mark_break(y - self.G)
        sb.y = y - self.G
        return sb.finish(self.Pb)

    # ------------------------------------------------------------ closing
    def closing(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.paper, "light", "closing")
        y = self.P
        sb.add(Block(kind="shape", x=self.M, y=y, w=self.CW, h=max(1.0, comp.k), fill=self.rule, decorative=True))
        y += comp.px(120)
        ids = comp.assets_of(sp)
        if ids:
            b = comp.natural(ids[0], self.M, y, self.CW, max_h=comp.px(720))
            sb.add(b)
            y = (b.bottom if b else y) + comp.px(96)
        logo_id = sp.meta.get("logo_id")
        if logo_id and comp.asset(logo_id) and logo_id not in ids:
            box_w, box_h = self.span(4), comp.px(120)
            sb.add(comp.image(logo_id, (comp.W - box_w) / 2, y, box_w, box_h, prefer="contain"))
            y += box_h + comp.px(72)
        title = comp.fitted_text(sp.title, self.M, y, self.CW, self.st_display(comp, 110, self.ink), "display", max_lines=2, min_size=comp.px(48), max_size=comp.px(120), align="center", editable="title")
        sb.add(title)
        y = title.bottom if title else y
        sub_text = sp.subtitle or f"{comp.ctx.plan.project_title} — {comp.ctx.plan.category_label}"
        sub = comp.text(sub_text, self.M, y + comp.px(32), self.CW, self.st_label(comp, self.soft, 12), "subtitle", align="center", editable="subtitle")
        if sub:
            sb.add(sub)
            y = sub.bottom
        body = comp.text(sp.body, self.cx(3), y + comp.px(28), self.span(6), self.st_body(comp, 17, self.ink), "body", align="center", editable="body")
        if body:
            sb.add(body)
            y = body.bottom
        sb.y = y
        return sb.finish(comp.px(180))
