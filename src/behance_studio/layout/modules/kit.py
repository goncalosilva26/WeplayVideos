"""Composition kit: concept-aware primitives the modules are built from.

The kit wraps the v1 :class:`Composer` (exact text measurement, integrity-
first image fitting) and adds what editorial modules need: type styles
derived from the art direction, labels, logo placement with measured
contrast, aspect-true placement inside a box, device frames, layer effects
and surface choice.
"""

from __future__ import annotations

from typing import Any

from behance_studio.assets.understanding import is_single_colour_mark, logo_ink, treatment
from behance_studio.design import color as C
from behance_studio.director.concepts import ArtDirection
from behance_studio.layout.composer import Composer, SectionBuilder
from behance_studio.layout.devices import device_size, screen_rect
from behance_studio.layout.fitting import choose_fit, native_limit
from behance_studio.layout.model import Block, TextStyle
from behance_studio.planning.models import SectionPlan
from behance_studio.projects.models import MEDIA_VIDEO

LABELS = {
    "about": ("About", "Sobre"),
    "client": ("Client", "Cliente"),
    "category": ("Category", "Categoria"),
    "deliverables": ("Deliverables", "Entregáveis"),
    "primary_logo": ("Primary logo", "Logótipo principal"),
    "logo_system": ("Logo system", "Sistema de logótipos"),
    "colour": ("Colour", "Cor"),
    "typography": ("Typography", "Tipografia"),
    "display": ("Display", "Títulos"),
    "text": ("Text", "Texto"),
    "thank_you": ("Thank you", "Obrigado"),
    "chapter": ("Chapter", "Capítulo"),
    "case_study": ("Case study", "Estudo de caso"),
}

EFFECT_KEYS = ("rotate", "shadow", "shadow_color", "clip", "fade", "blend", "filter", "zoom", "perspective", "device_color", "opacity")


class Kit:
    def __init__(self, comp: Composer, ad: ArtDirection, state: Any = None) -> None:
        self.c = comp
        self.ad = ad
        self.state = state
        self.W = comp.W
        self.k = comp.k
        self.lang = comp.ctx.language

    @property
    def rng(self):
        return self.c.rng

    def px(self, v: float) -> float:
        return self.c.px(v)

    def t(self, key: str) -> str:
        en, pt = LABELS[key]
        return pt if self.lang == "pt" else en

    def asset(self, aid: str | None):
        return self.c.asset(aid) if aid else None

    def aspect(self, aid: str) -> float:
        return self.c.aspect(aid)

    # ------------------------------------------------------------ colour
    def ink(self, bg: str) -> str:
        preferred = self.ad.light if C.is_dark(bg) else self.ad.dark
        return preferred if C.contrast_ratio(preferred, bg) >= 4.5 else C.ensure_contrast(preferred, bg, 4.5)

    def soft(self, bg: str, amount: float = 0.38) -> str:
        fg = self.ink(bg)
        cand = C.mix(fg, bg, amount)
        return cand if C.contrast_ratio(cand, bg) >= 4.5 else C.ensure_contrast(cand, bg, 4.5)

    def section(self, sp: SectionPlan, bg: str, pattern: str) -> SectionBuilder:
        return SectionBuilder(sp, bg, "dark" if C.is_dark(bg) else "light", pattern)

    def previous_bg(self) -> str | None:
        if self.state is not None and getattr(self.state, "backgrounds", None):
            return self.state.backgrounds[-1]
        return None

    def surface(self, prefer: str | None = None, avoid_previous: bool = True, options: list[str] | None = None) -> str:
        """A section background from the concept's surfaces, varying rhythm."""
        pool = list(options or self.ad.surfaces)
        prev = self.previous_bg() if avoid_previous else None
        if prefer and (not prev or C.delta_e(prefer, prev) > 4 or len(pool) == 1):
            return prefer
        idx = (self.state.index if self.state is not None else 0) % len(pool)
        rotated = pool[idx:] + pool[:idx]
        for c in rotated:
            if not prev or C.delta_e(c, prev) > 4:
                return c
        return rotated[0]

    # ------------------------------------------------------------ type
    def style(self, role: str, size: float, color: str, **kw: Any) -> TextStyle:
        ad = self.ad
        if role in ("display", "title", "quote", "numeral"):
            # Wide tracking is for set-in-caps display lines only.
            tracking = ad.display_tracking if role == "display" else min(ad.display_tracking, 0.0)
            base = TextStyle(
                ad.display, size, ad.display_weight, kw.pop("line_height", 1.04), kw.pop("tracking", tracking), color,
                italic=kw.pop("italic", ad.display_italic and role == "quote"), uppercase=kw.pop("uppercase", ad.display_upper and role == "display"),
            )
        elif role == "label":
            base = TextStyle(ad.label, size, kw.pop("weight", 600), kw.pop("line_height", 1.3), kw.pop("tracking", 0.16), color, uppercase=kw.pop("uppercase", True))
        else:
            base = TextStyle(ad.text, size, kw.pop("weight", 400), kw.pop("line_height", 1.55), kw.pop("tracking", 0.0), color)
        return base.with_(**kw) if kw else base

    def label(self, text: str, x: float, y: float, w: float, color: str, align: str = "left", size: float = 11.5, editable: str | None = None) -> Block | None:
        if not text:
            return None
        return self.c.text(text, x, y, w, self.style("label", self.px(size), color), "label", align=align, editable=editable)

    def display(
        self, text: str, x: float, y: float, w: float, color: str, max_lines: int = 3, min_size: float = 28, max_size: float = 120,
        align: str = "left", role: str = "display", editable: str | None = None, line_height: float = 1.04, max_height: float | None = None, **kw: Any,
    ) -> Block | None:
        st = self.style(role, self.px(max_size), color, line_height=line_height, **kw)
        return self.c.fitted_text(text, x, y, w, st, role, max_lines, self.px(min_size), self.px(max_size), align=align, editable=editable, max_height=max_height)

    def body(self, text: str, x: float, y: float, w: float, color: str, size: float = 18, editable: str | None = "body", align: str = "left", **kw: Any) -> Block | None:
        return self.c.text(text, x, y, w, self.style("body", self.px(size), color, **kw), "body", align=align, editable=editable)

    # ----------------------------------------------------------- media
    def _apply(self, b: Block | None, fx: dict[str, Any]) -> Block | None:
        if b is None:
            return None
        for key in EFFECT_KEYS:
            if key in fx and fx[key] is not None:
                setattr(b, key, fx[key])
        if fx.get("z") is not None:
            b.z = int(fx["z"])
        if fx.get("layered"):
            b.meta["layered"] = True
        if fx.get("bleed"):
            b.meta["bleed"] = True
        asset = self.asset(b.asset_id)
        if asset is not None and (asset.analysis or {}).get("background") == "transparent":
            b.meta["alpha"] = True
        return b

    def place(self, aid: str, x: float, y: float, w: float, h: float, prefer: str = "cover", mat: str | None = None, pad: float = 0.0, radius: float = 0.0, **fx: Any) -> Block | None:
        b = self.c.image(aid, x, y, w, h, prefer=prefer, mat=mat, pad=pad, radius=radius, z=fx.pop("z", 2))
        return self._apply(b, fx)

    def fit_size(self, aid: str, bw: float, bh: float, upscale: float = 1.15) -> tuple[float, float]:
        """Largest aspect-true size inside a box (limited by native resolution)."""
        a = self.asset(aid)
        aspect = a.aspect if a else 1.0
        w = min(bw, bh * aspect)
        if a is not None and a.media_type != "svg" and a.width:
            w = min(w, a.width * upscale)
        return round(w, 2), round(w / aspect, 2)

    def natural(self, aid: str, x: float, y: float, bw: float, bh: float, ax: float = 0.5, ay: float = 0.5, upscale: float = 1.15, **fx: Any) -> Block | None:
        """The asset at its own proportions, as large as fits the box."""
        w, h = self.fit_size(aid, bw, bh, upscale)
        bx = x + (bw - w) * ax
        by = y + (bh - h) * ay
        b = self.c.image(aid, bx, by, w, h, prefer="contain", z=fx.pop("z", 2))
        if b is not None:
            b.fit = "cover"  # the box has the asset's proportions: nothing is hidden
            b.crop = 0.0
        return self._apply(b, fx)

    def logo_contrast(self, aid: str, bg: str) -> float:
        a = self.asset(aid)
        if a is None:
            return 0.0
        if (a.analysis or {}).get("background") != "transparent":
            return 21.0  # carries its own background
        return C.contrast_ratio(logo_ink(a), bg)

    def logo_surface(self, aid: str | None, candidates: list[str]) -> str:
        """First candidate background on which the logo reads clearly."""
        if aid is None:
            return candidates[0]
        best = max(candidates, key=lambda c: self.logo_contrast(aid, c))
        for c in candidates:
            if self.logo_contrast(aid, c) >= 3.0:
                return c
        return best

    def logo(self, aid: str, cx: float, cy: float, max_w: float, max_h: float, bg: str, **fx: Any) -> Block | None:
        """A logo centred on (cx, cy), never cropped. A strictly single-colour
        mark that would not read on ``bg`` is shown reversed (tinted)."""
        a = self.asset(aid)
        if a is None:
            return None
        w, h = self.fit_size(aid, max_w, max_h, upscale=2.5 if a.media_type == "svg" or max(a.width, a.height) >= 800 else 1.3)
        b = self.c.image(aid, cx - w / 2, cy - h / 2, w, h, prefer="contain", z=fx.pop("z", 3))
        if b is None:
            return None
        b.fit, b.crop = "contain", 0.0
        if self.logo_contrast(aid, bg) < 3.0 and is_single_colour_mark(a):
            b.tint = self.ink(bg)
            b.meta["derived"] = "single-colour mark shown reversed"
        return self._apply(b, fx)

    def device(self, aid: str, device: str, x: float, y: float, bw: float, bh: float, ax: float = 0.5, ay: float = 0.5,
               screen_aspect: float | None = None, mat: str | None = None, **fx: Any) -> Block | None:
        """Artwork inside a CSS-drawn device/frame that fits the box."""
        a = self.asset(aid)
        if a is None:
            return None
        sa = screen_aspect or a.aspect
        # Solve for the largest device whose outer box fits (bw, bh).
        lo, hi = 10.0, bw
        for _ in range(28):
            mid = (lo + hi) / 2
            dw, dh = device_size(device, mid, mid / sa)
            if dw <= bw and dh <= bh:
                lo = mid
            else:
                hi = mid
        dw, dh = device_size(device, lo, lo / sa)
        dx, dy = x + (bw - dw) * ax, y + (bh - dh) * ay
        scr = screen_rect(device, dw, dh)
        fit = choose_fit(a, scr.w, scr.h, prefer="cover")
        if mat is None and fit.mode == "contain":
            info = a.analysis or {}
            mat = info.get("background") if info.get("background") not in (None, "transparent") and info.get("background_uniformity", 0) >= 0.85 else "#111111"
        kind = "video" if a.media_type == MEDIA_VIDEO else "image"
        b = Block(kind=kind, x=round(dx, 2), y=round(dy, 2), w=dw, h=dh, z=fx.pop("z", 3), asset_id=aid, fit=fit.mode, focal=fit.position,
                  crop=round(fit.crop, 4) if fit.mode == "cover" else 0.0, device=device, mat=mat)
        b.meta["visible"] = fit.visible
        if fit.mode == "contain":
            limit = native_limit(a)
            shown = min(scr.w, scr.h * a.aspect)
            if shown > limit:
                b.pad = round((shown - limit) / 2 * (scr.w / shown), 2)
        return self._apply(b, fx)

    def stage_bg(self, own: str | None = None, prefer: str | None = None) -> str:
        """A staging surface for artwork: from the concept's stages, clearly
        different from the artwork's own ground and from the previous section."""
        pool = ([prefer] if prefer else []) + list(self.ad.stages or self.ad.surfaces)
        prev = self.previous_bg()
        for c in pool:
            if own and own != "transparent" and C.parse_hex(own) and C.delta_e(c, own) < 14:
                continue
            if prev and C.delta_e(c, prev) < 4 and len(pool) > 1:
                continue
            return c
        return pool[0]

    def cover_height(self, aid: str, w: float, lo: float, hi: float, target: float) -> float | None:
        """A frame height in [lo, hi], closest to ``target``, at which the asset
        may cover a frame of width ``w`` (crop allowance and text safety)."""
        from behance_studio.layout.fitting import choose_fit

        a = self.asset(aid)
        if a is None:
            return None
        natural = w / a.aspect
        candidates = sorted({round(min(hi, max(lo, h)), 1) for h in (target, natural)} | {round(lo + (hi - lo) * i / 12, 1) for i in range(13)}, key=lambda h: abs(h - target))
        for h in candidates:
            if choose_fit(a, w, h, prefer="cover").mode == "cover":
                return h
        return None

    def cover_width(self, aid: str, h: float, lo: float, hi: float, target: float) -> float | None:
        a = self.asset(aid)
        if a is None:
            return None
        from behance_studio.layout.fitting import choose_fit

        candidates = sorted({round(lo + (hi - lo) * i / 12, 1) for i in range(13)} | {round(min(hi, max(lo, target)), 1)}, key=lambda w: abs(w - target))
        for w in candidates:
            if choose_fit(a, w, h, prefer="cover").mode == "cover":
                return w
        return None

    def may_crop(self, aid: str) -> bool:
        a = self.asset(aid)
        return a is not None and treatment(a).may_crop

    def shape(self, x: float, y: float, w: float, h: float, fill: str, z: int = 0, **kw: Any) -> Block:
        b = Block(kind="shape", x=round(x, 2), y=round(y, 2), w=round(w, 2), h=round(h, 2), z=z, fill=fill, decorative=True)
        for key, value in kw.items():
            setattr(b, key, value)
        return b
