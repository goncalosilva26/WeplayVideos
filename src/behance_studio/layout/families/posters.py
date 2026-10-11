"""Family 4 — Graphic Posters.

Every section is a poster: saturated brand-colour fields, enormous
uppercase type fitted line-by-line to the full width, pill "stickers",
circular badges, outlined numerals, dramatic scale contrast between images,
and marquee bands that carry the brand messages between sections.
"""

from __future__ import annotations

from typing import Any

from behance_studio.design import color as C
from behance_studio.design.typography import TypeSystem, get_font
from behance_studio.layout import text as T
from behance_studio.layout.composer import Composer, SectionBuilder, best_arrangement
from behance_studio.layout.families.base import ComposeState, FamilyInfo, LayoutFamily
from behance_studio.layout.fitting import best_crop_aspect, can_cover, native_limit
from behance_studio.layout.model import Block, Section, TextStyle
from behance_studio.planning.models import SectionPlan
from behance_studio.planning.planner import PlanPreferences


def poster_lines(text: str, min_chars: int = 4, max_lines: int = 4) -> list[str]:
    """Split a title into display lines; very short words join a neighbour."""
    words = text.split()
    lines: list[str] = []
    for word in words:
        if lines and (len(word) < min_chars or len(lines[-1]) < min_chars):
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    while len(lines) > max_lines:
        shortest = min(range(len(lines) - 1), key=lambda i: len(lines[i]) + len(lines[i + 1]))
        lines[shortest : shortest + 2] = [f"{lines[shortest]} {lines[shortest + 1]}"]
    return lines


class PostersFamily(LayoutFamily):
    info = FamilyInfo(
        id="posters",
        name="Graphic Posters",
        tagline="Bold type, colour fields and poster energy",
        description="Expressive poster-inspired compositions: giant fitted typography, saturated colour fields, stickers, badges and dynamic scale.",
        ideal_for=["Advertising", "Poster design", "Experimental branding", "Youthful identities"],
        badge="#F2B63D",
    )
    voices = {"condensed", "expressive"}
    edge_style = "outline"

    def preferences(self, rng, creativity) -> PlanPreferences:
        return PlanPreferences(max_per_section=6, include_intro=True, closing_image=False, hero_rank=0, merge_small=2, split_logo_variations=False, shuffle=0.35 * creativity)

    def variant(self, ctx, rng) -> dict[str, Any]:
        order = ["primary", "ink", "secondary", "paper"]
        rng.shuffle(order)
        if order[0] == "paper":
            order = order[1:] + order[:1]
        return {
            "order": order,
            "title_mode": rng.choice(["stack", "stack", "two-line"]),
            "marquee": rng.random() < 0.75,
            "stickers": rng.random() < 0.8,
            "margin": rng.choice([56, 72]),
            "cover_image": rng.choice(["rect", "circle"]),
        }

    def setup(self, comp: Composer, v: dict[str, Any]) -> None:
        self.v = v
        self.ts = TypeSystem.from_dict(v["type_system"])
        pal = comp.palette
        paper = pal.paper if C.lightness(pal.paper) > 85 else C.with_lightness(pal.paper, 95, 0.4)
        named = {"primary": pal.primary, "ink": pal.ink, "secondary": pal.secondary, "paper": paper}
        self.colors = list(dict.fromkeys(named[k] for k in v["order"]))
        self.paper = paper
        self.M = comp.px(v["margin"])
        self.CW = comp.W - 2 * self.M
        self.G = comp.px(28)
        fam = get_font(self.ts.display)
        self.heavy = fam.clamp_weight(850 if fam.variable else 400)

    # ------------------------------------------------------------ styles
    def bg_for(self, state: ComposeState, offset: int = 0) -> str:
        return self.colors[(state.index + offset) % len(self.colors)]

    def st_display(self, comp, size, color) -> TextStyle:
        return TextStyle(self.ts.display, size, self.heavy, 0.9, -0.01, color, uppercase=True)

    def st_label(self, comp, color, size=13) -> TextStyle:
        return TextStyle(self.ts.label, comp.px(size), get_font(self.ts.label).clamp_weight(800), 1.2, 0.08, color, uppercase=True)

    def st_body(self, comp, color, size=19) -> TextStyle:
        return TextStyle(self.ts.text, comp.px(size), get_font(self.ts.text).clamp_weight(500), 1.5, 0.0, color)

    def pill(self, comp: Composer, sb: SectionBuilder, text: str, x: float, y: float, fill: str, fg: str, size: float = 13, overlay: bool = False, align: str = "left", on_image: Block | None = None) -> Block | None:
        st = self.st_label(comp, fg, size)
        line = T.transform(text, st)
        w = T.line_width(line, st) / T.SAFETY + comp.px(36) + 2
        h = st.line_px + comp.px(18)
        if align == "right":
            x = x - w
        if on_image is not None:
            if w > on_image.w - comp.px(40):
                return None
            x, y = comp.quiet_corner(on_image, w, h, comp.px(20))
        shape = Block(kind="shape", x=x, y=y, w=w, h=h, fill=fill, radius=h / 2, z=4 if overlay else 2, overlay=overlay, decorative=not overlay)
        label = comp.text(text, x + comp.px(18), y + comp.px(9), w - comp.px(36), st, "label")
        if label:
            label.z = 5 if overlay else 3
            label.overlay = overlay
            sb.add(shape)
            sb.add(label)
        return shape

    def headline(self, comp: Composer, sb: SectionBuilder, text: str, y: float, color: str, max_size: float = 330, editable: str = "title") -> float:
        if self.v["title_mode"] == "stack" and len(text) <= 42:
            lines = poster_lines(text)
            blocks = comp.line_fitted(lines, self.M, y, self.CW, self.st_display(comp, 100, color), "display", editable=editable, max_size=comp.px(max_size), line_height=0.92, source_text=text)
            if blocks:
                blocks[0].text = text if len(blocks) == 1 else blocks[0].text
                sb.extend(blocks)
                return blocks[-1].bottom
        b = comp.fitted_text(text, self.M, y, self.CW, self.st_display(comp, comp.px(200), color).with_(line_height=0.92), "display", max_lines=2, min_size=comp.px(64), max_size=comp.px(min(max_size, 220)), editable=editable)
        if b:
            sb.add(b)
            return b.bottom
        return y

    def marquee_section(self, comp: Composer, text: str, bg: str, fg: str) -> Section:
        from behance_studio.planning.models import SectionPlan as SP

        sp = SP(type="divider", title="")
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "marquee")
        h = comp.px(84)
        st = TextStyle(self.ts.display, comp.px(34), self.heavy, 1.0, 0.02, fg, uppercase=True)
        unit = f"{text}  ✦  "
        unit_w = max(1.0, T.line_width(T.transform(unit, st), st))
        reps = int(comp.W * 2 / unit_w) + 2
        line = (T.transform(unit, st) * reps).rstrip()
        b = Block(kind="text", x=0, y=(h - st.line_px) / 2, w=comp.W, h=st.line_px, text=text, lines=[line], style=st, role="marquee", z=3)
        sb.add(b)
        return sb.finish(0, height=h)

    def finalize(self, comp: Composer, sections: list[Section], state: ComposeState) -> list[Section]:
        if not self.v["marquee"]:
            return sections
        brief = comp.ctx.plan
        messages = []
        cover = next((s for s in sections if s.type == "cover"), None)
        for sp in comp.ctx.plan.sections:
            if sp.type == "cover" and sp.subtitle:
                messages.append(sp.subtitle)
            if sp.meta.get("quote"):
                messages.append(sp.meta["quote"])
        messages = messages or [brief.project_title]
        out: list[Section] = []
        inserted = 0
        for i, s in enumerate(sections):
            out.append(s)
            nxt = sections[i + 1] if i + 1 < len(sections) else None
            if nxt is None or s.type == "divider":
                continue
            # A band after the cover and roughly every third section.
            if s.type == "cover" or (i % 3 == 2 and nxt.type != "closing"):
                bg = comp.palette.ink if not C.is_dark(s.background) else comp.palette.primary
                if bg == s.background or bg == nxt.background:
                    bg = comp.palette.secondary
                fg = comp.text_color(bg)
                out.append(self.marquee_section(comp, messages[inserted % len(messages)], bg, fg))
                inserted += 1
        _ = cover
        return out

    # ------------------------------------------------------------- cover
    def cover(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        bg = self.colors[0]
        fg = comp.text_color(bg)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "cover-poster")
        y = comp.px(56)
        self.pill(comp, sb, sp.eyebrow or comp.ctx.plan.category_label, self.M, y, fg, bg)
        sb.add(comp.text(comp.ctx.plan.project_title, self.M + self.CW / 2, y + comp.px(10), self.CW / 2, self.st_label(comp, fg, 12), "label", align="right"))
        y += comp.px(110)
        y = self.headline(comp, sb, sp.title, y, fg, max_size=360) + comp.px(48)
        sb.mark_break(y - comp.px(24))
        ids = comp.assets_of(sp)
        if ids:
            hero = ids[0]
            asset = comp.asset(hero)
            if self.v["cover_image"] == "circle" and asset is not None and can_cover(asset, 1.0):
                d = min(self.CW * 0.62, comp.px(820))
                b = comp.image(hero, self.M + self.CW - d, y, d, d, radius=d / 2)
                sb.add(b)
                if sp.subtitle:
                    sub = comp.fitted_text(sp.subtitle, self.M, y + d * 0.35, self.CW - d - comp.px(48), TextStyle(self.ts.display, comp.px(48), self.heavy, 1.0, -0.01, fg), "subtitle", max_lines=4, min_size=comp.px(26), max_size=comp.px(64), editable="subtitle")
                    sb.add(sub)
                y += d
            else:
                aspect = best_crop_aspect(asset, [16 / 9, 3 / 2]) if asset else None
                if aspect and native_limit(asset, 1.6) >= self.CW * 0.7:
                    b = comp.image(hero, self.M, y, self.CW, self.CW / aspect)
                else:
                    b = comp.natural(hero, self.M, y, self.CW, max_h=comp.px(860))
                sb.add(b)
                if b is not None:
                    if sp.subtitle and self.v["stickers"]:
                        self.pill(comp, sb, sp.subtitle, b.x, b.y, fg, bg, size=16, overlay=True, on_image=b)
                    y = b.bottom
                    if sp.subtitle and not self.v["stickers"]:
                        s2 = comp.text(sp.subtitle, self.M, y + comp.px(28), self.CW, self.st_label(comp, fg, 20), "subtitle", editable="subtitle")
                        sb.add(s2)
                        y = s2.bottom if s2 else y
        elif sp.subtitle:
            s2 = comp.fitted_text(sp.subtitle, self.M, y, self.CW, TextStyle(self.ts.display, comp.px(56), self.heavy, 1.0, -0.01, fg), "subtitle", max_lines=3, min_size=comp.px(28), max_size=comp.px(72), editable="subtitle")
            sb.add(s2)
            y = s2.bottom if s2 else y
        sb.y = y
        return sb.finish(comp.px(72))

    # ---------------------------------------------------------- statement
    def statement(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        bg = self.bg_for(state)
        fg = comp.text_color(bg)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "statement-poster")
        y = comp.px(72)
        self.pill(comp, sb, f"{state.content_index + 1:02d} — {sp.title}", self.M, y, fg, bg)
        y += comp.px(100)
        size = 46 if len(sp.body) < 320 else 34
        body = comp.text(sp.body, self.M, y, self.CW * 0.86, TextStyle(self.ts.display, comp.px(size), get_font(self.ts.display).clamp_weight(700), 1.1, -0.01, fg), "body", editable="body")
        if body:
            sb.add(body)
            y = body.bottom
        quote = sp.meta.get("quote")
        if quote:
            y += comp.px(64)
            sb.mark_break(y - comp.px(32))
            y = self.headline(comp, sb, quote, y, comp.text_color(bg, comp.palette.secondary if bg != comp.palette.secondary else comp.palette.primary, 3.0), max_size=200, editable="")
        sb.y = y
        return sb.finish(comp.px(96))

    # ------------------------------------------------------------- media
    def section_head(self, comp: Composer, sb: SectionBuilder, sp: SectionPlan, state: ComposeState, bg: str) -> float:
        fg = comp.text_color(bg)
        y = comp.px(64)
        num = f"{state.content_index + 1:02d}"
        self.pill(comp, sb, num, self.M, y, fg, bg)
        if sp.eyebrow:
            sb.add(comp.text(sp.eyebrow, self.M + comp.px(90), y + comp.px(10), self.CW / 2, self.st_label(comp, fg, 12), "eyebrow", editable="eyebrow"))
        y += comp.px(84)
        y = self.headline(comp, sb, sp.title, y, fg)
        if sp.subtitle or sp.body:
            col = self.CW * 0.48
            sub = comp.text(sp.subtitle, self.M + self.CW - col, y + comp.px(32), col, self.st_body(comp, fg, 24).with_(line_height=1.3), "subtitle", editable="subtitle")
            cy = y + comp.px(32)
            if sub:
                sb.add(sub)
                cy = sub.bottom + comp.px(16)
            body = comp.text(sp.body, self.M + self.CW - col, cy, col, self.st_body(comp, fg), "body", editable="body")
            if body:
                sb.add(body)
                cy = body.bottom
            y = cy
        y += comp.px(56)
        sb.mark_break(y - comp.px(28))
        return y

    def big_small(self, comp: Composer, sb: SectionBuilder, ids: list[str], y: float, flip: bool) -> float:
        big, small = ids[0], ids[1]
        bw, sw = self.CW * 0.6, self.CW * 0.32
        bb = comp.natural(big, self.M if not flip else self.M + self.CW - bw, y, bw, max_h=comp.px(1100), align="left" if not flip else "right")
        sb.add(bb)
        bh = bb.h if bb else 0
        sx = self.M + self.CW - sw if not flip else self.M
        probe = comp.natural(small, sx, 0, sw, max_h=comp.px(700), align="right" if not flip else "left")
        sh = probe.h if probe else 0
        sy = y + max(0.0, bh - sh)  # bottom-aligned with the big image
        sbk = comp.natural(small, sx, sy, sw, max_h=comp.px(700), align="right" if not flip else "left")
        sb.add(sbk)
        return y + max(bh, sh)

    def media(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        bg = self.bg_for(state)
        fg = comp.text_color(bg)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "")
        y = self.section_head(comp, sb, sp, state, bg)
        flip = state.index % 2 == 1
        if len(ids) == 2 and sp.layout_hint not in ("two-up", "grid"):
            sb.pattern = "big-small"
            y = self.big_small(comp, sb, ids, y, flip)
        else:
            arr = best_arrangement(comp, ids, self.M, y, self.CW, self.G, comp.px(470), comp.px(2100), ["asym", "rows", "pair", "rows4", "lead", "stack2"], state.recent(), radius=0.0)
            sb.pattern = arr.name
            sb.extend(arr.blocks)
            for br in arr.breaks:
                sb.mark_break(br)
            y += arr.height
        media_blocks = [b for b in sb.blocks if b.asset_id]
        if self.v["stickers"] and media_blocks:
            first = media_blocks[0]
            cap = sp.captions.get(first.asset_id or "") or f"{state.content_index + 1:02d}/{len(ids):02d}"
            if first.w > comp.px(260) and first.h > comp.px(120):
                self.pill(comp, sb, cap, first.x, first.y, fg if fg != bg else comp.palette.ink, bg, size=12, overlay=True, on_image=first)
        sb.y = y
        return sb.finish(comp.px(88))

    def logo(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        bg = self.bg_for(state)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "logo-badges")
        y = self.section_head(comp, sb, sp, state, bg)
        first = comp.asset(ids[0])
        a = first.analysis or {}
        if a.get("background") not in (None, "transparent") and a.get("background_uniformity", 0) >= 0.9:
            tile = a["background"]
        else:
            tile = comp.logo_backdrop(first, self.paper, avoid=bg)
        h = comp.px(620)
        sb.add(Block(kind="shape", x=self.M, y=y, w=self.CW, h=h, fill=tile, decorative=True, radius=comp.px(28)))
        sb.add(comp.image(ids[0], self.M + self.CW * 0.2, y + h * 0.26, self.CW * 0.6, h * 0.48, prefer="contain"))
        y += h
        rest = ids[1:]
        if rest:
            y += self.G
            sb.mark_break(y - self.G / 2)
            n = min(4, len(rest))
            d = min((self.CW - self.G * (n - 1)) / n, comp.px(360))
            total = n * d + (n - 1) * self.G
            x0 = self.M + (self.CW - total) / 2
            options = [self.paper, comp.palette.primary, comp.palette.secondary, comp.palette.ink]
            for i, aid in enumerate(rest[:8]):
                r, c = divmod(i, n)
                cx = x0 + c * (d + self.G)
                cy = y + r * (d + self.G)
                ra = comp.asset(aid)
                ab = (ra.analysis or {}).get("background")
                if ab and ab != "transparent" and ra.analysis.get("background_uniformity", 0) >= 0.9:
                    fill = ab
                else:
                    fill = comp.logo_backdrop(ra, options[i % len(options)], avoid=bg, options=options)
                sb.add(Block(kind="shape", x=cx, y=cy, w=d, h=d, fill=fill, shape="circle", decorative=True))
                if C.delta_e(fill, bg) < 6:
                    sb.add(Block(kind="shape", x=cx, y=cy, w=d, h=d, shape="ring", stroke=comp.text_color(bg), stroke_width=max(2.0, comp.px(3)), decorative=True))
                sb.add(comp.image(aid, cx + d * 0.22, cy + d * 0.22, d * 0.56, d * 0.56, prefer="contain"))
            rows = (min(8, len(rest)) + n - 1) // n
            y += rows * d + (rows - 1) * self.G
        sb.y = y
        return sb.finish(comp.px(88))

    def palette(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        bg = self.bg_for(state)
        fg = comp.text_color(bg)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "palette-circles")
        y = self.section_head(comp, sb, sp, state, bg)
        swatches = [] if ids else (sp.meta.get("swatches") or [])
        if swatches:
            n = len(swatches)
            d = min((self.CW - self.G * (n - 1)) / n, comp.px(340))
            total = n * d + (n - 1) * self.G
            x0 = self.M + (self.CW - total) / 2
            for i, sw in enumerate(swatches):
                x = x0 + i * (d + self.G)
                sb.add(Block(kind="shape", x=x, y=y, w=d, h=d, fill=sw["hex"], shape="circle", z=1))
                if C.delta_e(sw["hex"], bg) < 8:
                    sb.add(Block(kind="shape", x=x, y=y, w=d, h=d, shape="ring", stroke=fg, stroke_width=max(2.0, comp.px(3)), decorative=True, z=1))
                name = sw.get("name") or comp.copy.swatch_role(sw.get("role", "neutral"))
                sb.add(comp.text(f"{name}\n{sw['hex']}", x, y + d + comp.px(20), d, self.st_label(comp, fg, 14), "label", align="center"))
            y += d + comp.px(80)
        for i, aid in enumerate(ids):
            b = comp.natural(aid, self.M, y, self.CW, max_h=comp.px(1000))
            if b:
                sb.add(b)
                y = b.bottom + self.G
        sb.y = y
        return sb.finish(comp.px(64))

    def typography(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        bg = self.bg_for(state)
        fg = comp.text_color(bg)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "type-poster")
        y = self.section_head(comp, sb, sp, state, bg)
        fonts = None if ids else sp.meta.get("fonts")
        if fonts:
            for fam_name in dict.fromkeys([fonts["display"], fonts["text"]]):
                fam = get_font(fam_name)
                st = TextStyle(fam_name, comp.px(100), fam.clamp_weight(800), 0.95, -0.01, fg, uppercase=False)
                blocks = comp.line_fitted([fam.name], self.M, y, self.CW, st, "label", max_size=comp.px(300))
                sb.extend(blocks)
                y = blocks[-1].bottom + comp.px(16) if blocks else y
                alpha = comp.line_fitted(["ABCDEFGHIJKLMNOPQRSTUVWXYZ"], self.M, y, self.CW, st.with_(weight=fam.clamp_weight(400)), "label", max_size=comp.px(90))
                sb.extend(alpha)
                y = (alpha[-1].bottom if alpha else y) + comp.px(64)
                sb.mark_break(y - comp.px(32))
        for aid in ids:
            b = comp.natural(aid, self.M, y, self.CW, max_h=comp.px(1000))
            if b:
                sb.add(b)
                y = b.bottom + self.G
        sb.y = y
        return sb.finish(comp.px(64))

    def before_after(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        bg = self.bg_for(state)
        fg = comp.text_color(bg)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "ba-poster")
        y = self.section_head(comp, sb, sp, state, bg)
        for i in range(0, len(ids) - 1, 2):
            blocks, h = comp.row(ids[i : i + 2], self.M, y, self.CW, self.G)
            sb.extend(blocks)
            for b, label in zip(blocks, (comp.copy.s("before"), comp.copy.s("after"))):
                self.pill(comp, sb, label, b.x + comp.px(20), b.y + comp.px(20), fg, bg, overlay=True)
            y += h + self.G
            sb.mark_break(y - self.G / 2)
        sb.y = y - self.G
        return sb.finish(comp.px(88))

    # ------------------------------------------------------------ closing
    def closing(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        bg = self.colors[0]
        fg = comp.text_color(bg)
        sb = SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", "closing-poster")
        y = comp.px(110)
        y = self.headline(comp, sb, sp.title, y, fg, max_size=420) + comp.px(56)
        logo = sp.meta.get("logo_id")
        if logo and comp.asset(logo):
            la = comp.asset(logo)
            d = comp.px(240)
            fill = comp.logo_backdrop(la, self.paper, avoid=bg)
            sb.add(Block(kind="shape", x=self.M, y=y, w=d, h=d, fill=fill, shape="circle", decorative=True))
            sb.add(comp.image(logo, self.M + d * 0.18, y + d * 0.18, d * 0.64, d * 0.64, prefer="contain"))
            sb.add(comp.text(sp.subtitle or f"{comp.ctx.plan.project_title}\n{comp.ctx.plan.category_label}", self.M + d + comp.px(40), y + d / 2 - comp.px(24), self.CW - d - comp.px(40), self.st_label(comp, fg, 16), "subtitle", editable="subtitle"))
            y += d
        else:
            s2 = comp.text(sp.subtitle or comp.ctx.plan.project_title, self.M, y, self.CW, self.st_label(comp, fg, 18), "subtitle", editable="subtitle")
            sb.add(s2)
            y = s2.bottom if s2 else y
        sb.y = y
        return sb.finish(comp.px(96))
