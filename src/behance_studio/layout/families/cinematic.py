"""Family 2 — Cinematic Story.

Immersive, dark and image-led. Photographs and mockups run full-bleed in
widescreen crops (only within each asset's crop allowance); artwork that must
not be cropped is presented "on stage" on dark backgrounds with a soft
spotlight. Chapters open with title cards or titles overlaid on imagery
(with measured contrast and gradient scrims). Strong pacing, minimal text.
"""

from __future__ import annotations

from typing import Any

from behance_studio.design import color as C
from behance_studio.design.typography import TypeSystem, get_font
from behance_studio.layout.composer import Composer, SectionBuilder
from behance_studio.layout.families.base import ComposeState, FamilyInfo, LayoutFamily
from behance_studio.layout.fitting import best_crop_aspect, choose_fit, native_limit
from behance_studio.layout.model import Block, Section, TextStyle
from behance_studio.planning.models import SectionPlan
from behance_studio.planning.planner import PlanPreferences


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = C.parse_hex(hex_color) or (0, 0, 0)
    return f"rgba({r},{g},{b},{alpha:.2f})"


class CinematicFamily(LayoutFamily):
    info = FamilyInfo(
        id="cinematic",
        name="Cinematic Story",
        tagline="Immersive full-bleed imagery and dramatic pacing",
        description="Dark, image-led storytelling: widescreen full-bleed sequences, chapter title cards, overlay titles and artwork staged under a spotlight.",
        ideal_for=["Photography", "Film and video", "Motion graphics", "Advertising campaigns"],
        badge="#E2574C",
    )
    voices = {"editorial", "condensed", "technical"}
    edge_style = None

    def preferences(self, rng, creativity) -> PlanPreferences:
        return PlanPreferences(max_per_section=6, include_intro=True, closing_image=True, hero_rank=0, merge_small=2, split_logo_variations=False, shuffle=0.25 * creativity, hero_aspect=16 / 9)

    def variant(self, ctx, rng) -> dict[str, Any]:
        return {
            "bg": rng.choice(["black", "ink"]),
            "gap": rng.choice([0, 8, 14]),
            "cover": rng.choice(["overlay-bottom", "overlay-center"]),
            "chapter": rng.choice(["card", "overlay", "card"]),
            "aspects": rng.choice([[2.39, 2.0, 16 / 9], [2.0, 16 / 9, 3 / 2], [16 / 9, 2.39, 3 / 2]]),
            "title_case": rng.choice(["upper", "natural"]),
        }

    def setup(self, comp: Composer, v: dict[str, Any]) -> None:
        self.v = v
        self.ts = TypeSystem.from_dict(v["type_system"])
        pal = comp.palette
        ink = pal.ink if C.lightness(pal.ink) < 22 else C.with_lightness(pal.ink, 14, 0.5)
        self.bg = C.mix(ink, "#000000", 0.55) if v["bg"] == "black" else C.with_lightness(ink, 9, 0.8)
        self.bg2 = C.with_lightness(self.bg, C.lightness(self.bg) + 5, 1.0)
        light = pal.paper if C.lightness(pal.paper) > 85 else "#F4F1EC"
        self.fg = comp.text_color(self.bg, light, 7.0)
        self.muted = comp.muted(self.fg, self.bg, 0.38)
        self.accent = pal.primary if C.contrast_ratio(pal.primary, self.bg) >= 3 else (pal.secondary if C.contrast_ratio(pal.secondary, self.bg) >= 3 else self.fg)
        self.M = comp.px(112)
        self.gap = comp.px(v["gap"])
        fam = get_font(self.ts.display)
        self.display_weight = fam.clamp_weight(300 if fam.category in ("serif", "sans", "display") else 400)
        self.upper = v["title_case"] == "upper" or fam.uppercase_only

    # ---------------------------------------------------------- styles
    def st_title(self, comp, size, color=None) -> TextStyle:
        if self.upper:
            return TextStyle(self.ts.display, comp.px(size), self.display_weight, 1.04, 0.06, color or self.fg, uppercase=True)
        return TextStyle(self.ts.display, comp.px(size), self.display_weight, 1.04, -0.015, color or self.fg)

    def st_label(self, comp, color=None, size=12) -> TextStyle:
        return TextStyle(self.ts.label, comp.px(size), get_font(self.ts.label).clamp_weight(500), 1.4, 0.32, color or self.muted, uppercase=True)

    def st_body(self, comp, size=17, color=None) -> TextStyle:
        return TextStyle(self.ts.text, comp.px(size), get_font(self.ts.text).clamp_weight(400), 1.7, 0.01, color or self.muted)

    def chapter_label(self, comp, state: ComposeState) -> str:
        word = comp.copy.s("chapter")
        return f"{word} {state.content_index + 1:02d}"

    # ------------------------------------------------------- primitives
    def scrim(self, x: float, y: float, w: float, h: float, direction: str = "to top", strength: float = 0.82) -> Block:
        grad = f"linear-gradient({direction}, {_rgba(self.bg, strength)} 0%, {_rgba(self.bg, strength * 0.55)} 38%, {_rgba(self.bg, 0)} 75%)"
        return Block(kind="shape", x=x, y=y, w=w, h=h, fill=grad, z=2, decorative=True, overlay=True)

    def bleed(self, comp: Composer, aid: str, y: float) -> Block | None:
        """Full-bleed image in the widest allowed cinematic crop."""
        asset = comp.asset(aid)
        if asset is None:
            return None
        aspect = best_crop_aspect(asset, list(self.v["aspects"]))
        if aspect is None:
            return None
        if native_limit(asset, 1.6) < comp.W * 0.7:
            return None  # too small to run full-bleed
        return comp.image(aid, 0, y, comp.W, comp.W / aspect)

    def stage(self, comp: Composer, sb: SectionBuilder, ids: list[str], y: float) -> float:
        """Uncroppable artwork presented under a spotlight on a dark band."""
        pad_y = comp.px(110)
        width = comp.W - 2 * comp.px(150)
        from behance_studio.layout.composer import best_arrangement

        arr = best_arrangement(comp, ids, comp.px(150), y + pad_y, width, comp.px(40), comp.px(460), comp.px(1300), ["rows", "pair", "asym", "rows4"], [])
        h = arr.height + 2 * pad_y
        spot = f"radial-gradient(ellipse at 50% 45%, {self.bg2} 0%, {self.bg} 72%)"
        sb.add(Block(kind="shape", x=0, y=y, w=comp.W, h=h, fill=spot, z=1, decorative=True))
        sb.extend(arr.blocks)
        for b in arr.blocks:
            b.z = 2
        sb.mark_break(y)
        return y + h

    def overlay_layout(self, comp: Composer, img: Block, title: str, label: str | None, body: str | None, size: float, anchors: list[str]) -> tuple[str, float, float, float, float] | None:
        """Find an anchor where the title block does not cover the subject."""
        pad = self.M
        width = min(comp.px(820), comp.W - 2 * pad)
        st = self.st_title(comp, size)
        probe = comp.fitted_text(title, pad, 0, width, st, "title", max_lines=2, min_size=comp.px(40), max_size=comp.px(size))
        th = probe.h if probe else 0
        label_h = comp.px(34) if label else 0
        body_block = comp.text(body or "", pad, 0, min(width, comp.px(560)), self.st_body(comp, 17, self.fg), "body") if body else None
        bh = body_block.h + comp.px(20) if body_block else 0
        total = label_h + th + bh
        if total > img.h - 2 * pad * 0.6:
            return None
        for anchor in anchors:
            if anchor == "center":
                x, top = (comp.W - width) / 2, img.y + (img.h - total) / 2
            elif anchor == "bottom":
                x, top = pad, img.bottom - pad * 0.8 - total
            elif anchor == "bottom-right":
                x, top = comp.W - pad - width, img.bottom - pad * 0.8 - total
            elif anchor == "top":
                x, top = pad, img.y + pad * 0.8
            else:  # top-right
                x, top = comp.W - pad - width, img.y + pad * 0.8
            if comp.subject_overlap(img, (x, top, width, total)) < 0.12:
                return anchor, x, top, width, total
        return None

    def overlay_title(self, comp: Composer, sb: SectionBuilder, img: Block, title: str, label: str | None, body: str | None, anchor: str, size: float, editable_title: str = "title") -> bool:
        anchors = [anchor] + [a for a in ("bottom", "top", "bottom-right", "top-right", "center") if a != anchor]
        found = self.overlay_layout(comp, img, title, label, body, size, anchors)
        if found is None:
            return False
        anchor, x, top, width, total = found
        align = "center" if anchor == "center" else ("right" if anchor.endswith("right") else "left")
        st = self.st_title(comp, size)
        label_h = comp.px(34) if label else 0
        rect = (x, top, width, total)
        color, need_scrim = comp.overlay_style(img, rect, self.fg, comp.palette.ink)
        if color != self.fg:
            need_scrim = need_scrim  # dark text on a light image
        if need_scrim or color == self.fg:
            direction = "to bottom" if anchor.startswith("top") else "to top"
            sb.add(self.scrim(img.x, img.y, img.w, img.h, direction, 0.86 if anchor != "center" else 0.6))
            if anchor == "center":
                sb.add(Block(kind="shape", x=img.x, y=img.y, w=img.w, h=img.h, fill=_rgba(self.bg, 0.35), z=2, decorative=True, overlay=True))
            color = self.fg
        y = top
        if label:
            lb = comp.text(label, x, y, width, self.st_label(comp, color if color != self.fg else self.fg, 12), "eyebrow", align=align)
            if lb:
                lb.overlay = True
                sb.add(lb)
            y += label_h
        t = comp.fitted_text(title, x, y, width, st.with_(color=color), "title", max_lines=2, min_size=comp.px(40), max_size=comp.px(size), align=align, editable=editable_title)
        if t:
            t.overlay = True
            t.z = 4
            sb.add(t)
            y = t.bottom
        if body:
            bw = min(width, comp.px(560))
            bx = {"left": x, "center": (comp.W - bw) / 2, "right": x + width - bw}[align]
            b2 = comp.text(body, bx, y + comp.px(20), bw, self.st_body(comp, 17, color), "body", align=align, editable="body")
            if b2:
                b2.overlay = True
                b2.z = 4
                sb.add(b2)
        return True

    def chapter_card(self, comp: Composer, sb: SectionBuilder, sp: SectionPlan, state: ComposeState, y: float) -> float:
        top = y + comp.px(150)
        label = comp.text(sp.eyebrow or self.chapter_label(comp, state), 0, top, comp.W, self.st_label(comp, self.accent, 12), "eyebrow", align="center", editable="eyebrow" if sp.eyebrow else None)
        sb.add(label)
        cy = (label.bottom if label else top) + comp.px(26)
        t = comp.fitted_text(sp.title, comp.px(160), cy, comp.W - comp.px(320), self.st_title(comp, 84), "title", max_lines=2, min_size=comp.px(40), max_size=comp.px(92), align="center", editable="title")
        sb.add(t)
        cy = t.bottom if t else cy
        sub = comp.text(sp.subtitle, comp.px(260), cy + comp.px(22), comp.W - comp.px(520), self.st_body(comp, 20, self.fg), "subtitle", align="center", editable="subtitle")
        if sub:
            sb.add(sub)
            cy = sub.bottom
        body = comp.text(sp.body, (comp.W - comp.px(600)) / 2, cy + comp.px(28), comp.px(600), self.st_body(comp, 17), "body", align="center", editable="body")
        if body:
            sb.add(body)
            cy = body.bottom
        return cy + comp.px(130)

    # ------------------------------------------------------------ cover
    def cover(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.bg, "dark", "cover-" + self.v["cover"])
        hero = ids[0] if ids else None
        img = None
        if hero:
            asset = comp.asset(hero)
            aspect = best_crop_aspect(asset, [16 / 9, 3 / 2, 2.0]) if asset else None
            if aspect and native_limit(asset, 1.6) >= comp.W * 0.7:
                h = min(comp.W / aspect, comp.px(980))
                img = comp.image(hero, 0, 0, comp.W, h)
        label = f"{sp.eyebrow or comp.ctx.plan.category_label}"
        if img is not None:
            sb.add(img)
            anchor = "center" if self.v["cover"] == "overlay-center" else "bottom"
            if not self.overlay_title(comp, sb, img, sp.title, label, sp.subtitle or None, anchor, 132):
                y = img.bottom + comp.px(110)
                sb.pattern = "cover-below"
                sb.add(comp.text(label, self.M, y, comp.px(600), self.st_label(comp, self.accent), "eyebrow", editable="eyebrow"))
                t = comp.fitted_text(sp.title, self.M, y + comp.px(40), comp.W - 2 * self.M, self.st_title(comp, 128), "display", max_lines=2, min_size=comp.px(56), max_size=comp.px(140), editable="title")
                sb.add(t)
                y = (t.bottom if t else y) + comp.px(24)
                sub = comp.text(sp.subtitle, self.M, y, comp.px(760), self.st_body(comp, 20, self.fg), "subtitle", editable="subtitle")
                if sub:
                    sb.add(sub)
                    y = sub.bottom
                sb.y = y
                return sb.finish(comp.px(120))
            top_label = comp.text(comp.ctx.plan.project_title, self.M, comp.px(48), comp.px(600), self.st_label(comp, self.fg, 11), "label")
            if top_label and anchor != "center":
                color, _ = comp.overlay_style(img, (top_label.x, top_label.y, top_label.w, top_label.h), self.fg, comp.palette.ink)
                top_label.style = top_label.style.with_(color=color)
                top_label.overlay = True
                top_label.z = 4
                sb.add(top_label)
            sb.y = img.bottom
            return sb.finish(0, height=img.bottom)
        # Letterbox cover: title on black, artwork staged below.
        y = comp.px(170)
        sb.add(comp.text(label, 0, y, comp.W, self.st_label(comp, self.accent), "eyebrow", align="center", editable="eyebrow"))
        t = comp.fitted_text(sp.title, comp.px(120), y + comp.px(40), comp.W - comp.px(240), self.st_title(comp, 128), "display", max_lines=2, min_size=comp.px(56), max_size=comp.px(140), align="center", editable="title")
        sb.add(t)
        y = (t.bottom if t else y) + comp.px(24)
        sub = comp.text(sp.subtitle, comp.px(240), y, comp.W - comp.px(480), self.st_body(comp, 20, self.fg), "subtitle", align="center", editable="subtitle")
        if sub:
            sb.add(sub)
            y = sub.bottom
        y += comp.px(60)
        if hero:
            y = self.stage(comp, sb, [hero], y)
        else:
            logo = sp.meta.get("logo_id")
            if logo and comp.asset(logo):
                box = comp.px(420)
                bg = comp.logo_backdrop(comp.asset(logo), self.bg, options=[comp.palette.paper])
                if bg != self.bg:
                    sb.add(Block(kind="shape", x=(comp.W - box * 2) / 2, y=y, w=box * 2, h=box, fill=bg, radius=comp.px(6), decorative=True))
                sb.add(comp.image(logo, (comp.W - box * 1.4) / 2, y + box * 0.2, box * 1.4, box * 0.6, prefer="contain"))
                y += box + comp.px(120)
        sb.y = y
        return sb.finish(comp.px(40))

    # -------------------------------------------------------- statement
    def statement(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.bg, "dark", "statement")
        y = comp.px(200)
        sb.add(comp.text(sp.title, 0, y, comp.W, self.st_label(comp, self.accent), "title", align="center", editable="title"))
        y += comp.px(64)
        size = 40 if len(sp.body) < 380 else 30
        body = comp.text(sp.body, comp.px(230), y, comp.W - comp.px(460), TextStyle(self.ts.display, comp.px(size), self.display_weight, 1.36, -0.005, self.fg), "body", align="center", editable="body")
        if body:
            sb.add(body)
            y = body.bottom
        quote = sp.meta.get("quote")
        if quote:
            y += comp.px(80)
            sb.add(Block(kind="shape", x=comp.W / 2 - comp.px(30), y=y, w=comp.px(60), h=max(1.0, comp.px(2)), fill=self.accent, decorative=True))
            q = comp.text(quote, comp.px(200), y + comp.px(40), comp.W - comp.px(400), self.st_title(comp, 30, self.fg), "quote", align="center")
            if q:
                sb.add(q)
                y = q.bottom
        sb.y = y
        return sb.finish(comp.px(200))

    # ------------------------------------------------------------ media
    def sequence(self, comp: Composer, sb: SectionBuilder, ids: list[str], y: float, first_overlay: tuple[SectionPlan, ComposeState] | None = None) -> float:
        """Full-bleed run of images; uncroppable artwork grouped on stages."""
        stage_buffer: list[str] = []
        i = 0
        first = True

        def flush(cur_y: float) -> float:
            nonlocal stage_buffer
            if stage_buffer:
                cur_y = self.stage(comp, sb, stage_buffer, cur_y)
                stage_buffer = []
            return cur_y

        while i < len(ids):
            aid = ids[i]
            asset = comp.asset(aid)
            # Two portrait photographs side by side, edge to edge.
            if (
                asset is not None
                and asset.aspect < 0.9
                and i + 1 < len(ids)
                and comp.asset(ids[i + 1]) is not None
                and comp.asset(ids[i + 1]).aspect < 0.9
                and choose_fit(asset, 700, 900).mode == "cover"
                and choose_fit(comp.asset(ids[i + 1]), 700, 900).mode == "cover"
            ):
                y = flush(y)
                w = (comp.W - self.gap) / 2
                h = min(w / 0.78, comp.px(980))
                for j, pid in enumerate((aid, ids[i + 1])):
                    b = comp.image(pid, j * (w + self.gap), y, w, h)
                    sb.add(b)
                sb.mark_break(y)
                y += h + self.gap
                i += 2
                first = False
                continue
            if self.bleed(comp, aid, 0) is not None:
                y = flush(y)
                img = self.bleed(comp, aid, y)
                sb.mark_break(y)
                sb.add(img)
                if first and first_overlay is not None:
                    sp, state = first_overlay
                    self.overlay_title(comp, sb, img, sp.title, sp.eyebrow or self.chapter_label(comp, state), sp.body or None, "bottom", 84)
                y = img.bottom + self.gap
                first = False
                i += 1
                continue
            stage_buffer.append(aid)
            if len(stage_buffer) >= 4:
                y = flush(y)
            first = False
            i += 1
        y = flush(y)
        return y

    def media(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.bg, "dark", "")
        first_bleedable = bool(ids) and self.bleed(comp, ids[0], 0) is not None
        use_overlay = self.v["chapter"] == "overlay" and first_bleedable and sp.layout_hint != "text"
        y = 0.0
        if use_overlay:
            probe = self.bleed(comp, ids[0], 0)
            fits = probe is not None and self.overlay_layout(comp, probe, sp.title, sp.eyebrow or "x", sp.body or None, 84, ["bottom", "top", "bottom-right", "top-right"]) is not None
            use_overlay = fits
        if use_overlay:
            sb.pattern = "overlay-chapter"
            y = self.sequence(comp, sb, ids, y, (sp, state))
        else:
            sb.pattern = "card-chapter"
            y = self.chapter_card(comp, sb, sp, state, y)
            sb.mark_break(y)
            y = self.sequence(comp, sb, ids, y)
        sb.y = y
        return sb.finish(0)

    def logo(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.bg, "dark", "logo-reveal")
        y = self.chapter_card(comp, sb, sp, state, 0)
        pal = comp.palette
        first, rest = ids[0], ids[1:]
        asset = comp.asset(first)
        panel_h = comp.px(720)
        a = asset.analysis or {}
        if a.get("background") not in (None, "transparent") and a.get("background_uniformity", 0) >= 0.9:
            bg = a["background"]
        else:
            bg = comp.logo_backdrop(asset, pal.paper, options=[pal.primary])
        sb.mark_break(y)
        sb.add(Block(kind="shape", x=0, y=y, w=comp.W, h=panel_h, fill=bg, decorative=True, z=1))
        sb.add(comp.image(first, comp.W * 0.25, y + panel_h * 0.28, comp.W * 0.5, panel_h * 0.44, prefer="contain"))
        y += panel_h + self.gap
        if rest:
            n = len(rest)
            w = (comp.W - self.gap * (n - 1)) / n
            h = min(comp.px(520), w * 0.8)
            options = [pal.primary, pal.secondary, pal.ink, pal.paper]
            sb.mark_break(y)
            for i, aid in enumerate(rest):
                x = i * (w + self.gap)
                ra = comp.asset(aid)
                rb = ra.analysis.get("background") if ra and ra.analysis else None
                if rb and rb != "transparent" and ra.analysis.get("background_uniformity", 0) >= 0.9:
                    tile_bg = rb
                else:
                    tile_bg = comp.logo_backdrop(ra, options[i % len(options)], options=options)
                sb.add(Block(kind="shape", x=x, y=y, w=w, h=h, fill=tile_bg, decorative=True, z=1))
                sb.add(comp.image(aid, x + w * 0.22, y + h * 0.22, w * 0.56, h * 0.56, prefer="contain"))
            y += h
        sb.y = y
        return sb.finish(0)

    def palette(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.bg, "dark", "palette-bands")
        y = self.chapter_card(comp, sb, sp, state, 0)
        ids = comp.assets_of(sp)
        swatches = [] if ids else (sp.meta.get("swatches") or [])
        if swatches:
            h = comp.px(620)
            w = comp.W / len(swatches)
            sb.mark_break(y)
            for i, sw in enumerate(swatches):
                fill = sw["hex"]
                x = i * w
                sb.add(Block(kind="shape", x=x, y=y, w=w + 0.5, h=h, fill=fill, z=1))
                fg = comp.text_color(fill)
                name = sw.get("name") or comp.copy.swatch_role(sw.get("role", "neutral"))
                sb.add(comp.text(name.upper(), x + comp.px(28), y + h - comp.px(96), w - comp.px(56), self.st_label(comp, fg, 13).with_(tracking=0.22), "label"))
                sb.add(comp.text(sw["hex"], x + comp.px(28), y + h - comp.px(64), w - comp.px(56), TextStyle(self.ts.label, comp.px(12), 400, 1.4, 0.12, fg), "label"))
            y += h
        if ids:
            y = self.stage(comp, sb, ids, y)
        sb.y = y
        return sb.finish(0)

    def typography(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        sb = SectionBuilder(sp, self.bg, "dark", "type-cinema")
        y = self.chapter_card(comp, sb, sp, state, 0)
        ids = comp.assets_of(sp)
        fonts = None if ids else sp.meta.get("fonts")
        if fonts:
            for fam_name, label in ((fonts["display"], fonts.get("display_label", "")), (fonts["text"], fonts.get("text_label", ""))):
                fam = get_font(fam_name)
                glyph = comp.text("Aa", 0, y, comp.W, TextStyle(fam_name, comp.px(300), fam.clamp_weight(300 if fam.variable else 400), 1.0, -0.02, self.fg), "label", align="center")
                sb.add(glyph)
                y = (glyph.bottom if glyph else y) + comp.px(20)
                sb.add(comp.text(f"{fam.name} — {label}", 0, y, comp.W, self.st_label(comp, self.accent, 13), "label", align="center"))
                y += comp.px(120)
                sb.mark_break(y - comp.px(60))
                if fonts["text"] == fonts["display"]:
                    break
        if ids:
            y = self.stage(comp, sb, ids, y)
        sb.y = y
        return sb.finish(comp.px(40))

    def before_after(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.bg, "dark", "before-after")
        y = self.chapter_card(comp, sb, sp, state, 0)
        for i in range(0, len(ids) - 1, 2):
            pair = ids[i : i + 2]
            w = (comp.W - self.gap) / 2
            asp = comp.aspect(pair[0])
            h = min(w / asp, comp.px(1000))
            sb.mark_break(y)
            for j, aid in enumerate(pair):
                b = comp.image(aid, j * (w + self.gap), y, w, h)
                sb.add(b)
                label = comp.copy.s("before") if j == 0 else comp.copy.s("after")
                lb = comp.text(label, j * (w + self.gap) + comp.px(32), y + comp.px(32), comp.px(300), self.st_label(comp, self.fg, 12), "caption")
                if lb and b:
                    color, scrim = comp.overlay_style(b, (lb.x, lb.y, lb.w, lb.h), self.fg, comp.palette.ink)
                    if scrim:
                        sb.add(Block(kind="shape", x=lb.x - comp.px(12), y=lb.y - comp.px(8), w=comp.px(140), h=lb.h + comp.px(16), fill=_rgba(self.bg, 0.75), z=3, overlay=True, radius=comp.px(4)))
                        color = self.fg
                    lb.style = lb.style.with_(color=color)
                    lb.overlay = True
                    lb.z = 4
                    sb.add(lb)
            y += h + self.gap
        sb.y = y
        return sb.finish(0)

    # ---------------------------------------------------------- closing
    def closing(self, comp: Composer, sp: SectionPlan, state: ComposeState) -> Section:
        ids = comp.assets_of(sp)
        sb = SectionBuilder(sp, self.bg, "dark", "closing")
        img = self.bleed(comp, ids[0], 0) if ids else None
        if img is not None:
            aspect = img.w / img.h
            img.h = min(img.h, comp.px(860))
            from behance_studio.layout.fitting import choose_fit

            fit = choose_fit(comp.asset(ids[0]), img.w, img.h)
            img.fit, img.focal, img.crop, img.meta["visible"] = fit.mode, fit.position, fit.crop, fit.visible
            if fit.mode == "cover":
                sb.add(img)
                sb.add(Block(kind="shape", x=0, y=0, w=comp.W, h=img.h, fill=_rgba(self.bg, 0.55), z=2, decorative=True, overlay=True))
                if self.overlay_title(comp, sb, img, sp.title, comp.ctx.plan.project_title, sp.body or None, "center", 120):
                    return sb.finish(0, height=img.h)
                sb.blocks.clear()
        y = comp.px(220)
        if ids and not sb.blocks:
            y = self.stage(comp, sb, ids[:1], 0) + comp.px(100)
        logo = sp.meta.get("logo_id")
        if logo and comp.asset(logo):
            la = comp.asset(logo)
            bg = comp.logo_backdrop(la, self.bg, options=[comp.palette.paper])
            if bg != self.bg:
                disc = comp.px(220)
                sb.add(Block(kind="shape", x=(comp.W - disc) / 2, y=y, w=disc, h=disc, fill=bg, shape="circle", decorative=True))
                sb.add(comp.image(logo, (comp.W - disc * 0.6) / 2, y + disc * 0.2, disc * 0.6, disc * 0.6, prefer="contain"))
                y += disc + comp.px(80)
            else:
                sb.add(comp.image(logo, (comp.W - comp.px(420)) / 2, y, comp.px(420), comp.px(120), prefer="contain"))
                y += comp.px(200)
        t = comp.fitted_text(sp.title, comp.px(120), y, comp.W - comp.px(240), self.st_title(comp, 120), "display", max_lines=2, min_size=comp.px(48), max_size=comp.px(130), align="center", editable="title")
        sb.add(t)
        y = (t.bottom if t else y) + comp.px(36)
        sb.add(comp.text(sp.subtitle or comp.ctx.plan.project_title, 0, y, comp.W, self.st_label(comp, self.muted), "subtitle", align="center", editable="subtitle"))
        sb.y = y + comp.px(40)
        return sb.finish(comp.px(220))
