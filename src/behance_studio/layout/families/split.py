"""Family 3 — Split Narrative.

Asymmetric split screens: every chapter opens with a coloured text panel
beside a full-height image panel, alternating sides to create a reading
rhythm. Large outlined numerals, text and imagery working together, and
staggered two-column continuations for the remaining images.
"""

from __future__ import annotations

from typing import Any

from behance_studio.design import color as C
from behance_studio.design.typography import TypeSystem, get_font
from behance_studio.layout.composer import Composer, SectionBuilder, best_arrangement
from behance_studio.layout.families.base import ComposeState, FamilyInfo, LayoutFamily
from behance_studio.layout.fitting import choose_fit, native_limit
from behance_studio.layout.model import Block, Section, TextStyle
from behance_studio.planning.models import SectionPlan
from behance_studio.planning.planner import PlanPreferences


class SplitFamily(LayoutFamily):
    info = FamilyInfo(
        id="split",
        name="Split Narrative",
        tagline="Asymmetric split screens where text and image converse",
        description="Alternating split-screen chapters with coloured text panels, full-height imagery, outlined numerals and staggered continuations.",
        ideal_for=["Concept-driven branding", "Case studies", "Design process", "Image + text storytelling"],
        badge="#5B8DEF",
    )
    voices = {"editorial", "expressive"}

    def preferences(self, rng, creativity) -> PlanPreferences:
        return PlanPreferences(max_per_section=6, include_intro=True, closing_image=False, hero_rank=1 if rng.random() < 0.5 else 0, merge_small=2, split_logo_variations=False, shuffle=0.3 * creativity, hero_aspect=0.9)

    def variant(self, ctx, rng) -> dict[str, Any]:
        return {
            "ratio": rng.choice([0.42, 0.45, 0.5]),
            "start": rng.choice([0, 1]),
            "cycle": rng.choice(["warm", "contrast", "soft"]),
            "numeral": rng.choice(["outline", "solid"]),
            "min_h": rng.choice([780, 860, 940]),
            "stagger": rng.random() < 0.7,
        }

    def setup(self, comp: Composer, v: dict[str, Any]) -> None:
        self.v = v
        self.ts = TypeSystem.from_dict(v["type_system"])
        pal = comp.palette
        self.paper = pal.paper if C.lightness(pal.paper) > 85 else C.with_lightness(pal.paper, 95, 0.4)
        self.paper_alt = C.mix(self.paper, pal.ink, 0.07)
        tint = C.mix(pal.primary, self.paper, 0.55)
        cycles = {
            "warm": [pal.primary, self.paper, pal.ink, tint, pal.secondary],
            "contrast": [pal.ink, pal.primary, self.paper, pal.secondary, tint],
            "soft": [tint, self.paper_alt, pal.primary, self.paper, pal.ink],
        }
        self.cycle = [c for c in dict.fromkeys(cycles[v["cycle"]])]
        self.M = comp.px(88)
        self.G = comp.px(20)
        fam = get_font(self.ts.display)
        self.display_weight = fam.clamp_weight(500 if fam.category == "serif" else 600)
        self.min_h = comp.px(v["min_h"])

    # ------------------------------------------------------------ helpers
    def panel_color(self, state: ComposeState, offset: int = 0) -> str:
        return self.cycle[(state.index + offset) % len(self.cycle)]

    def st_title(self, comp, size, color) -> TextStyle:
        return TextStyle(self.ts.display, comp.px(size), self.display_weight, 1.05, -0.015, color)

    def st_body(self, comp, color, size=18) -> TextStyle:
        return TextStyle(self.ts.text, comp.px(size), get_font(self.ts.text).clamp_weight(400), 1.62, 0.0, color)

    def st_label(self, comp, color, size=12) -> TextStyle:
        return TextStyle(self.ts.label, comp.px(size), get_font(self.ts.label).clamp_weight(600), 1.4, 0.14, color, uppercase=True)

    def numeral(self, comp, n: int, color: str, size: float = 170) -> TextStyle:
        st = TextStyle(self.ts.display, comp.px(size), get_font(self.ts.display).clamp_weight(700), 0.9, -0.02, color)
        if self.v["numeral"] == "outline":
            st = st.with_(stroke=color)
        return st

    def text_panel(self, comp: Composer, sb: SectionBuilder | None, sp: SectionPlan, x: float, w: float, h: float, bg: str, number: int | None, title_size: float = 60, with_body: bool = True) -> float:
        """Numeral at the top, title and text anchored to the bottom of the
        panel. Returns the panel height needed (≥ h when content is long)."""
        fg = comp.text_color(bg)
        soft = comp.muted(fg, bg, 0.3)
        pad = comp.px(80)
        inner = w - 2 * pad
        top_blocks: list[Block] = []
        top_h = 0.0
        if number is not None:
            num = comp.text(f"{number:02d}", x + pad, pad, inner, self.numeral(comp, number, fg), "numeral")
            if num:
                top_blocks.append(num)
                top_h = num.h + comp.px(48)
        content: list[Block] = []
        cy = 0.0
        if sp.eyebrow:
            label = comp.text(sp.eyebrow, x + pad, cy, inner, self.st_label(comp, soft), "eyebrow", editable="eyebrow")
            if label:
                content.append(label)
                cy = label.bottom + comp.px(18)
        title = comp.fitted_text(sp.title, x + pad, cy, inner, self.st_title(comp, title_size, fg), "title", max_lines=3, min_size=comp.px(34), max_size=comp.px(title_size), editable="title")
        if title:
            content.append(title)
            cy = title.bottom
        sub = comp.text(sp.subtitle, x + pad, cy + comp.px(20), inner, self.st_body(comp, fg, 21).with_(line_height=1.45), "subtitle", editable="subtitle")
        if sub:
            content.append(sub)
            cy = sub.bottom
        if with_body:
            body = comp.text(sp.body, x + pad, cy + comp.px(22), min(inner, comp.px(520)), self.st_body(comp, fg, 17), "body", editable="body")
            if body:
                content.append(body)
                cy = body.bottom
        needed = pad + top_h + cy + pad
        panel_h = max(h, needed)
        top = panel_h - pad - cy
        for b in content:
            b.y = round(b.y + top, 2)
        if sb is not None:
            sb.extend(top_blocks + content)
        return needed

    def image_panel(self, comp: Composer, sb: SectionBuilder, aid: str, x: float, w: float, h: float, mat: str) -> None:
        asset = comp.asset(aid)
        if asset is None:
            return
        fit = choose_fit(asset, w, h)
        if fit.mode == "cover" and native_limit(asset, 1.7) >= w * 0.7:
            sb.add(comp.image(aid, x, 0, w, h))
            return
        sb.add(Block(kind="shape", x=x, y=0, w=w, h=h, fill=mat, decorative=True, z=1))
        pad = min(w, h) * 0.11
        sb.add(comp.image(aid, x + pad, pad, w - 2 * pad, h - 2 * pad, prefer="contain"))

    def ideal_height(self, comp: Composer, aid: str | None, panel_w: float) -> float:
        if not aid or comp.asset(aid) is None:
            return self.min_h
        asset = comp.asset(aid)
        h = panel_w / asset.aspect
        return max(self.min_h, min(comp.px(1120), h))

    def sides(self, comp: Composer, state: ComposeState) -> tuple[float, float, float, float]:
        """(text_x, text_w, image_x, image_w) alternating per section."""
        tw = comp.W * self.v["ratio"]
        iw = comp.W - tw
        image_left = (state.side + self.v["start"]) % 2 == 0
        state.side += 1
        if image_left:
            return iw, tw, 0.0, iw
        return 0.0, tw, tw, iw

    def continuation(self, comp: Composer, sb: SectionBuilder, ids: list[str], y: float, bg: str, state: ComposeState) -> float:
        if not ids:
            return y
        y += comp.px(96)
        sb.mark_break(y - comp.px(48))
        M, G = comp.px(120), comp.px(36)
        width = comp.W - 2 * M
        if len(ids) == 1:
            # A single follow-up image sits off-centre, opposite the text panel.
            w = width * 0.64
            x = M if state.side % 2 == 0 else M + width - w
            b = comp.natural(ids[0], x, y, w, max_h=comp.px(900), align="left" if state.side % 2 == 0 else "right")
            sb.add(b)
            sb.pattern += "+single"
            return b.bottom if b else y
        if self.v["stagger"] and 2 <= len(ids) <= 6:
            col_w = (width - G * 2) / 2
            cols = [y, y + comp.px(150)]
            xs = [M, M + col_w + G * 2]
            placed: list[Block] = []
            for aid in ids:
                c = 0 if cols[0] <= cols[1] else 1
                b = comp.natural(aid, xs[c], cols[c], col_w, max_h=comp.px(900), align="left" if c == 0 else "right")
                if b:
                    placed.append(b)
                    cols[c] = b.bottom + G * 2
            spread = abs(cols[0] - cols[1]) / max(1.0, max(cols) - y)
            if spread <= 0.35:
                sb.extend(placed)
                sb.pattern += "+stagger"
                return max(cols) - G * 2
        arr = best_arrangement(comp, ids, M, y, width, G, comp.px(420), comp.px(1600), ["rows", "pair", "asym", "lead"], state.recent())
        sb.extend(arr.blocks)
        for br in arr.breaks:
            sb.mark_break(br)
        sb.pattern += "+" + arr.name
        return y + arr.height

    # -------------------------------------------------------------- cover
    def cover(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        bg = comp.palette.primary if self.v["cycle"] != "contrast" else comp.palette.ink
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "cover-split")
        tx, tw, ix, iw = self.sides(comp, state)
        h = max(comp.px(900), self.ideal_height(comp, ids[0] if ids else None, iw))
        fg = comp.text_color(bg)
        soft = comp.muted(fg, bg, 0.3)
        pad = comp.px(80)
        sb.add(comp.text(sp.eyebrow or comp.ctx.plan.category_label, tx + pad, pad, tw - 2 * pad, self.st_label(comp, soft), "eyebrow", editable="eyebrow"))
        title = comp.fitted_text(sp.title, tx + pad, 0, tw - 2 * pad, self.st_title(comp, 124, fg).with_(line_height=0.98), "display", max_lines=3, min_size=comp.px(54), max_size=comp.px(132), editable="title")
        sub = comp.text(sp.subtitle, tx + pad, 0, tw - 2 * pad, self.st_body(comp, fg, 22).with_(line_height=1.45), "subtitle", editable="subtitle")
        stack = (title.h if title else 0) + ((sub.h + comp.px(28)) if sub else 0)
        top = h - pad - stack
        if title:
            title.y = top
            sb.add(title)
        if sub:
            sub.y = top + (title.h if title else 0) + comp.px(28)
            sb.add(sub)
        if ids:
            self.image_panel(comp, sb, ids[0], ix, iw, h, self.paper_alt)
        else:
            logo = sp.meta.get("logo_id")
            if logo and comp.asset(logo):
                tile = comp.logo_backdrop(comp.asset(logo), self.paper, avoid=bg)
                sb.add(Block(kind="shape", x=ix, y=0, w=iw, h=h, fill=tile, decorative=True))
                sb.add(comp.image(logo, ix + iw * 0.2, h * 0.3, iw * 0.6, h * 0.4, prefer="contain"))
        return sb.finish(0, height=h)

    # ---------------------------------------------------------- statement
    def statement(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        panel = self.panel_color(state)
        sb = SectionBuilder(sp, self.paper, "light", "statement-split")
        tx, tw, ix, iw = self.sides(comp, state)
        fg = comp.text_color(self.paper)
        pad = comp.px(96)
        body_w = min(iw - 2 * pad, comp.px(640))
        size = 28 if len(sp.body) < 500 else 22
        body = comp.text(sp.body, ix + pad, 0, body_w, TextStyle(self.ts.display, comp.px(size), get_font(self.ts.display).clamp_weight(400), 1.42, -0.005, fg), "body", editable="body")
        quote = sp.meta.get("quote")
        q = None
        text_h = body.h if body else 0
        if quote:
            q = comp.text(f"“{quote}”", ix + pad, 0, body_w, self.st_title(comp, 34, comp.text_color(self.paper, comp.palette.secondary, 3.0)), "quote")
            if q:
                text_h += comp.px(48) + q.h
        title_only = SectionPlan(type=sp.type, title=sp.title, eyebrow=sp.eyebrow, id=sp.id)
        needed = self.text_panel(comp, None, title_only, tx, tw, 0, panel, state.content_index + 1, 56, with_body=False)
        h = max(comp.px(640), text_h + 2 * pad, needed)
        sb.add(Block(kind="shape", x=tx, y=0, w=tw, h=h, fill=panel, decorative=True))
        self.text_panel(comp, sb, title_only, tx, tw, h, panel, state.content_index + 1, 56, with_body=False)
        y = (h - text_h) / 2
        if body:
            body.y = round(y, 2)
            sb.add(body)
            y = body.bottom
        if q:
            q.y = round(y + comp.px(48), 2)
            sb.add(q)
        return sb.finish(0, height=h)

    # -------------------------------------------------------------- media
    def media(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        bg = self.panel_color(state)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "split")
        tx, tw, ix, iw = self.sides(comp, state)
        lead = ids[0]
        h = self.ideal_height(comp, lead, iw)
        need = self.text_panel(comp, sb, sp, tx, tw, h, bg, state.content_index + 1)
        h = max(h, need)
        mat = C.mix(bg, comp.palette.paper if C.is_dark(bg) else comp.palette.ink, 0.08)
        self.image_panel(comp, sb, lead, ix, iw, h, mat)
        y = self.continuation(comp, sb, ids[1:], h, bg, state)
        sb.y = y
        return sb.finish(comp.px(110) if len(ids) > 1 else 0, height=None if len(ids) > 1 else h)

    def logo(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        bg = self.panel_color(state)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "split-logo")
        tx, tw, ix, iw = self.sides(comp, state)
        h = self.min_h
        need = self.text_panel(comp, sb, sp, tx, tw, h, bg, state.content_index + 1)
        h = max(h, need)
        first = comp.asset(ids[0])
        a = first.analysis or {}
        if a.get("background") not in (None, "transparent") and a.get("background_uniformity", 0) >= 0.9:
            tile = a["background"]
        else:
            tile = comp.logo_backdrop(first, self.paper if bg != self.paper else comp.palette.primary, avoid=bg)
        sb.add(Block(kind="shape", x=ix, y=0, w=iw, h=h, fill=tile, decorative=True))
        sb.add(comp.image(ids[0], ix + iw * 0.18, h * 0.3, iw * 0.64, h * 0.4, prefer="contain"))
        rest = ids[1:]
        y = h
        if rest:
            n = len(rest)
            per_row = min(4, n)
            w = comp.W / per_row
            th = min(comp.px(420), w * 0.85)
            options = [self.paper, comp.palette.primary, comp.palette.ink, comp.palette.secondary, self.paper_alt]
            for i, aid in enumerate(rest):
                r, c = divmod(i, per_row)
                if c == 0:
                    sb.mark_break(y + r * th)
                ra = comp.asset(aid)
                ab = (ra.analysis or {}).get("background")
                if ab and ab != "transparent" and ra.analysis.get("background_uniformity", 0) >= 0.9:
                    fill = ab
                else:
                    fill = comp.logo_backdrop(ra, options[(i + state.index) % len(options)], options=options)
                sb.add(Block(kind="shape", x=c * w, y=y + r * th, w=w, h=th, fill=fill, decorative=True))
                sb.add(comp.image(aid, c * w + w * 0.2, y + r * th + th * 0.22, w * 0.6, th * 0.56, prefer="contain"))
            y += ((n + per_row - 1) // per_row) * th
        return sb.finish(0, height=y)

    def palette(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        bg = self.panel_color(state)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "split-palette")
        tx, tw, ix, iw = self.sides(comp, state)
        swatches = [] if ids else (sp.meta.get("swatches") or [])
        h = self.min_h
        sp2 = sp
        need = self.text_panel(comp, sb, sp2, tx, tw, h, bg, state.content_index + 1)
        h = max(h, need)
        if swatches:
            n = len(swatches)
            sw_w = iw / n
            for i, sw in enumerate(swatches):
                x = ix + i * sw_w
                sb.add(Block(kind="shape", x=x, y=0, w=sw_w + 0.5, h=h, fill=sw["hex"], z=1))
                fg = comp.text_color(sw["hex"])
                name = sw.get("name") or comp.copy.swatch_role(sw.get("role", "neutral"))
                sb.add(comp.text(f"{name}\n{sw['hex']}", x + comp.px(18), h - comp.px(92), sw_w - comp.px(30), TextStyle(self.ts.label, comp.px(12), 600, 1.5, 0.08, fg), "label"))
        elif ids:
            mat = C.mix(bg, comp.palette.ink if not C.is_dark(bg) else comp.palette.paper, 0.08)
            self.image_panel(comp, sb, ids[0], ix, iw, h, mat)
        y = self.continuation(comp, sb, ids[1:], h, bg, state) if len(ids) > 1 else h
        return sb.finish(comp.px(100) if len(ids) > 1 else 0, height=None if len(ids) > 1 else y)

    def typography(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        bg = self.panel_color(state)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "split-type")
        tx, tw, ix, iw = self.sides(comp, state)
        fonts = None if ids else sp.meta.get("fonts")
        h = self.min_h
        need = self.text_panel(comp, sb, sp, tx, tw, h, bg, state.content_index + 1)
        h = max(h, need)
        if fonts:
            panel = comp.palette.primary if comp.palette.primary != bg else comp.palette.ink
            fg = comp.text_color(panel)
            sb.add(Block(kind="shape", x=ix, y=0, w=iw, h=h, fill=panel, decorative=True))
            fam = get_font(fonts["display"])
            glyph = comp.text("Aa", ix, h * 0.12, iw, TextStyle(fonts["display"], comp.px(330), fam.clamp_weight(600), 1.0, -0.02, fg), "label", align="center")
            sb.add(glyph)
            gy = glyph.bottom if glyph else h * 0.5
            sb.add(comp.text(fam.name, ix, gy + comp.px(10), iw, TextStyle(fonts["display"], comp.px(40), fam.clamp_weight(500), 1.2, 0, fg), "label", align="center"))
            if fonts["text"] != fonts["display"]:
                tf = get_font(fonts["text"])
                sb.add(comp.text(f"{tf.name} — Aa Bb Cc 0123", ix, gy + comp.px(72), iw, TextStyle(fonts["text"], comp.px(22), tf.clamp_weight(500), 1.3, 0, fg), "label", align="center"))
        elif ids:
            mat = C.mix(bg, comp.palette.ink if not C.is_dark(bg) else comp.palette.paper, 0.08)
            self.image_panel(comp, sb, ids[0], ix, iw, h, mat)
        y = self.continuation(comp, sb, ids[1:], h, bg, state) if len(ids) > 1 else h
        return sb.finish(comp.px(100) if len(ids) > 1 else 0, height=None if len(ids) > 1 else y)

    def before_after(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        bg = self.panel_color(state)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "split-ba")
        y = 0.0
        fg = comp.text_color(bg)
        for i in range(0, len(ids) - 1, 2):
            before, after = ids[i], ids[i + 1]
            w = comp.W / 2
            h = min(w / comp.aspect(before), comp.px(1000))
            sb.mark_break(y)
            for j, aid in enumerate((before, after)):
                sb.add(comp.image(aid, j * w, y, w, h))
            label_y = y + h + comp.px(24)
            sb.add(comp.text(comp.copy.s("before"), comp.px(40), label_y, w - comp.px(80), self.st_label(comp, fg), "caption"))
            sb.add(comp.text(comp.copy.s("after"), w + comp.px(40), label_y, w - comp.px(80), self.st_label(comp, fg), "caption"))
            y = label_y + comp.px(64)
        head = SectionPlan(type=sp.type, title=sp.title, body=sp.body, id=sp.id)
        pad = comp.px(80)
        t = comp.fitted_text(head.title, pad, y + comp.px(40), comp.W - 2 * pad, self.st_title(comp, 56, fg), "title", max_lines=2, min_size=comp.px(32), max_size=comp.px(56), editable="title")
        sb.add(t)
        y = (t.bottom if t else y) + comp.px(20)
        body = comp.text(sp.body, pad, y, comp.px(640), self.st_body(comp, fg), "body", editable="body")
        if body:
            sb.add(body)
            y = body.bottom
        sb.y = y
        return sb.finish(comp.px(100))

    # ------------------------------------------------------------ closing
    def closing(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        bg = comp.palette.ink if self.v["cycle"] != "contrast" else comp.palette.primary
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "closing-split")
        tx, tw, ix, iw = self.sides(comp, state)
        h = comp.px(720)
        fg = comp.text_color(bg)
        pad = comp.px(80)
        t = comp.fitted_text(sp.title, tx + pad, 0, tw - 2 * pad, self.st_title(comp, 110, fg), "display", max_lines=2, min_size=comp.px(48), max_size=comp.px(118), editable="title")
        sub = comp.text(sp.subtitle or f"{comp.ctx.plan.project_title}\n{comp.ctx.plan.category_label}", tx + pad, 0, tw - 2 * pad, self.st_label(comp, comp.muted(fg, bg, 0.3)), "subtitle", editable="subtitle")
        stack = (t.h if t else 0) + (sub.h + comp.px(32) if sub else 0)
        top = (h - stack) / 2
        if t:
            t.y = top
            sb.add(t)
        if sub:
            sub.y = top + (t.h if t else 0) + comp.px(32)
            sb.add(sub)
        ids = comp.assets_of(sp)
        logo = sp.meta.get("logo_id")
        if ids:
            self.image_panel(comp, sb, ids[0], ix, iw, h, self.paper_alt)
        elif logo and comp.asset(logo):
            la = comp.asset(logo)
            tile = comp.logo_backdrop(la, self.paper, avoid=bg)
            sb.add(Block(kind="shape", x=ix, y=0, w=iw, h=h, fill=tile, decorative=True))
            sb.add(comp.image(logo, ix + iw * 0.22, h * 0.34, iw * 0.56, h * 0.32, prefer="contain"))
        return sb.finish(0, height=h)
