"""Presentation → HTML/CSS.

A single renderer serves every output:

* ``preview``  – in-app viewer (animated media, click-to-select hooks)
* ``html``     – exported package (animated media, responsive scaling)
* ``static``   – PDF and image exports (still frames, no animation)

Because geometry and line breaks are computed beforehand, all modes show
the same composition; only media behaviour differs.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from behance_studio.design.typography import FONTS, get_font
from behance_studio.layout.devices import browser_bar, screen_rect
from behance_studio.layout.model import Block, Presentation, Section

UrlFn = Callable[[Block], str]


@dataclass
class RenderOptions:
    mode: str = "static"  # preview | html | static
    asset_url: UrlFn | None = None  # URL of the displayed media for a block
    poster_url: UrlFn | None = None  # still image for video blocks
    font_url: Callable[[Path], str] = lambda p: p.resolve().as_uri()
    section_ids: list[str] | None = None  # render a subset (in order)
    title: str = ""
    lazy: bool = False
    reduce_motion: bool = False
    extra_head: str = ""
    extra_body: str = ""
    page_margin: bool = False
    data: dict = field(default_factory=dict)

    @property
    def animated(self) -> bool:
        return self.mode in ("preview", "html")


def _num(v: float) -> str:
    text = f"{v:.2f}".rstrip("0").rstrip(".")
    return text if text not in ("-0", "") else "0"


def font_face_css(families: list[str], url_for: Callable[[Path], str]) -> str:
    rules = []
    for name in families:
        fam = FONTS.get(name)
        if fam is None:
            continue
        weights = f"{fam.weight_min} {fam.weight_max}" if fam.variable else str(fam.weight_min)
        stretch = f"font-stretch: {fam.width_axis[0]}% {fam.width_axis[1]}%;" if fam.width_axis else ""
        rules.append(
            f"@font-face{{font-family:'{fam.name}';src:url('{url_for(fam.path())}') format('truetype');"
            f"font-weight:{weights};font-style:normal;{stretch}font-display:block;}}"
        )
        if fam.italic:
            rules.append(
                f"@font-face{{font-family:'{fam.name}';src:url('{url_for(fam.path(italic=True))}') format('truetype');"
                f"font-weight:{weights};font-style:italic;{stretch}font-display:block;}}"
            )
    return "\n".join(rules)


BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:var(--page)}
body{-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;text-rendering:optimizeLegibility;font-kerning:normal;font-optical-sizing:auto;print-color-adjust:exact;-webkit-print-color-adjust:exact}
.bs-deck{position:relative;width:var(--w);margin:0 auto;background:var(--page)}
.bs-sec{position:relative;width:var(--w);overflow:hidden}
.bs-b{position:absolute}
.bs-img{overflow:hidden}
.bs-img img,.bs-img video{display:block;width:100%;height:100%;border-radius:inherit}
.bs-txt{white-space:pre}
.bs-dev{overflow:hidden}
.bs-screen{position:absolute;overflow:hidden}
.bs-screen img,.bs-screen video{display:block;width:100%;height:100%}
.bs-bar{position:absolute;left:0;top:0;right:0;display:flex;align-items:center}
.bs-bar i{display:block;border-radius:50%}
.bs-txt .ln{display:block;white-space:pre}
.bs-marquee .ln{display:inline-block}
"""

ANIMATION_CSS = """
@keyframes bs-marquee{from{transform:translateX(0)}to{transform:translateX(-50%)}}
.bs-marquee-run{display:inline-block;white-space:nowrap;animation:bs-marquee 40s linear infinite}
.bs-marquee-run .ln{display:inline-block}
"""

PREVIEW_CSS = """
.bs-sec.bs-selected{outline:3px solid #4F7CFF;outline-offset:-3px}
.bs-b.bs-selected{outline:2px dashed #4F7CFF;outline-offset:2px}
.bs-sec{cursor:default}
"""

RESPONSIVE_JS = """
(function(){var d=document.querySelector('.bs-deck');var W=%s;
function fit(){var s=Math.min(1,document.documentElement.clientWidth/W);d.style.zoom=s;}
window.addEventListener('resize',fit);fit();})();
"""

PREVIEW_JS = """
(function(){
  function send(kind,a,b){ if(window.bsBridge&&window.bsBridge[kind]){window.bsBridge[kind](a,b||'');} }
  document.addEventListener('click',function(e){
    var blk=e.target.closest('.bs-b'); var sec=e.target.closest('.bs-sec');
    document.querySelectorAll('.bs-selected').forEach(function(n){n.classList.remove('bs-selected')});
    if(sec){sec.classList.add('bs-selected');}
    if(blk){blk.classList.add('bs-selected');}
    send('select', sec?sec.dataset.sec:'', blk?blk.dataset.b:'');
  });
  window.bsScrollTo=function(id){var el=document.getElementById('s-'+id); if(el){el.scrollIntoView({behavior:'smooth',block:'start'});}};
  window.bsSections=function(){return Array.prototype.map.call(document.querySelectorAll('.bs-sec'),function(s){var r=s.getBoundingClientRect();return {id:s.dataset.sec,top:r.top+window.scrollY,height:r.height};});};
  var last=null; window.addEventListener('scroll',function(){
    var secs=document.querySelectorAll('.bs-sec'); var mid=window.innerHeight*0.35; var cur=null;
    for(var i=0;i<secs.length;i++){var r=secs[i].getBoundingClientRect(); if(r.top<=mid&&r.bottom>mid){cur=secs[i].dataset.sec;break;}}
    if(cur&&cur!==last){last=cur;send('visible',cur);}
  },{passive:true});
})();
"""


def _style(parts: dict[str, str]) -> str:
    return ";".join(f"{k}:{v}" for k, v in parts.items() if v not in (None, ""))


SHADOWS = {
    "soft": "0 28px 56px -28px rgba(0,0,0,.42),0 3px 10px rgba(0,0,0,.07)",
    "lifted": "0 46px 80px -34px rgba(0,0,0,.50),0 10px 22px -10px rgba(0,0,0,.18)",
    "float": "0 70px 110px -40px rgba(0,0,0,.55),0 18px 34px -18px rgba(0,0,0,.25)",
    "glow": "0 0 120px 10px rgba(255,255,255,.22)",
}
# For transparent artwork (logos, cut-outs): shadows follow the shape.
DROP_SHADOWS = {
    "soft": "0 16px 22px rgba(0,0,0,.26)",
    "lifted": "0 24px 30px rgba(0,0,0,.30)",
    "float": "0 34px 40px rgba(0,0,0,.34)",
    "glow": "0 0 36px rgba(255,255,255,.35)",
}
FILTERS = {"grayscale": "grayscale(1)", "muted": "saturate(.62)", "dim": "brightness(.82)"}
FADES = {
    "top": "linear-gradient(to top,#000 58%,transparent)",
    "bottom": "linear-gradient(to bottom,#000 58%,transparent)",
    "left": "linear-gradient(to left,#000 58%,transparent)",
    "right": "linear-gradient(to right,#000 58%,transparent)",
}


def _shadow(b: Block, drop: bool = False) -> str:
    if b.shadow == "hard":
        k = max(8.0, min(24.0, min(b.w, b.h) * 0.03))
        return f"{_num(k)}px {_num(k)}px 0 {b.shadow_color or 'rgba(0,0,0,.85)'}"
    return (DROP_SHADOWS if drop else SHADOWS).get(b.shadow or "", "")


def _radius(b: Block) -> str:
    if b.clip in ("circle", "oval"):
        return "50%"
    if b.clip == "pill":
        return "9999px"
    if b.clip == "arch":
        r = _num(b.w / 2)
        return f"{r}px {r}px 0 0"
    if b.clip == "rounded":
        return f"{_num(b.radius or min(b.w, b.h) * 0.04)}px"
    return f"{_num(b.radius)}px" if b.radius else ""


def _effects(css: dict[str, str], b: Block, shadow_as_filter: bool = False) -> None:
    """Layer transforms, masks and effects shared by every layer kind."""
    transform = []
    if b.perspective:
        rx, ry = b.perspective
        transform.append(f"perspective({_num(max(b.w, b.h) * 2.4)}px) rotateX({_num(rx)}deg) rotateY({_num(ry)}deg)")
    if b.rotate:
        transform.append(f"rotate({_num(b.rotate)}deg)")
    if transform:
        css["transform"] = " ".join(transform)
        css["transform-origin"] = "50% 50%"
    radius = _radius(b)
    if radius:
        css["border-radius"] = radius
    drop = shadow_as_filter or bool(b.meta.get("alpha"))
    shadow = _shadow(b, drop)
    filters = [FILTERS[b.filter]] if b.filter in FILTERS else []
    if shadow:
        if drop:
            filters.append(f"drop-shadow({shadow})")
        else:
            css["box-shadow"] = shadow
    if filters:
        css["filter"] = " ".join(filters)
    if b.blend:
        css["mix-blend-mode"] = b.blend
    if b.fade in FADES:
        css["-webkit-mask-image"] = FADES[b.fade]
        css["mask-image"] = FADES[b.fade]
    if b.opacity < 1 and b.kind != "text":
        css["opacity"] = _num(b.opacity)


def _box(b: Block) -> dict[str, str]:
    return {
        "left": f"{_num(b.x)}px",
        "top": f"{_num(b.y)}px",
        "width": f"{_num(b.w)}px",
        "height": f"{_num(b.h)}px",
        "z-index": str(b.z),
    }


def render_text(b: Block) -> str:
    st = b.style
    assert st is not None
    fam = get_font(st.family)
    css = _box(b)
    css.update(
        {
            "font-family": fam.css_stack,
            "font-size": f"{_num(st.size)}px",
            "font-weight": str(fam.clamp_weight(st.weight)),
            "line-height": f"{_num(st.line_px)}px",
            "letter-spacing": f"{_num(st.tracking)}em" if st.tracking else "",
            "color": st.color,
            "text-align": b.align,
            "font-style": "italic" if st.italic else "",
            "font-stretch": f"{st.stretch}%" if st.stretch != 100 else "",
            "opacity": _num(st.opacity) if st.opacity < 1 else "",
        }
    )
    if st.stroke:
        css["color"] = "transparent"
        css["-webkit-text-stroke"] = f"{_num(max(1.0, st.size / 60))}px {st.stroke}"
    if b.rotate:
        css["transform"] = f"rotate({_num(b.rotate)}deg)"
        css["transform-origin"] = "50% 50%"
    if b.blend:
        css["mix-blend-mode"] = b.blend
    gap_px = st.line_px * b.para_gap
    lines = []
    for line in b.lines:
        if line == "":
            lines.append(f'<span class="ln" style="height:{_num(gap_px)}px"></span>')
        else:
            lines.append(f'<span class="ln">{html.escape(line)}</span>')
    classes = "bs-b bs-txt"
    inner = "".join(lines)
    if b.role == "marquee":
        classes += " bs-marquee"
        css["overflow"] = "hidden"
        inner = f'<span class="bs-marquee-inner">{inner}</span>'
    return f'<div class="{classes}" data-b="{b.id}" data-role="{b.role}" style="{_style(css)}">{inner}</div>'


def render_shape(b: Block, options: RenderOptions | None = None) -> str:
    css = _box(b)
    if b.fill:
        css["background"] = b.fill
    if b.fill_asset and options is not None and options.asset_url:
        size = b.fill_size or 240.0
        tile = Block(kind="image", x=0, y=0, w=size, h=size, asset_id=b.fill_asset)
        url = options.asset_url(tile)
        if url:
            css["background-image"] = f"url('{html.escape(url)}')"
            css["background-size"] = f"{_num(size)}px auto"
            css["background-repeat"] = "repeat"
    if b.shape == "circle":
        css["border-radius"] = "50%"
    elif b.radius:
        css["border-radius"] = f"{_num(b.radius)}px"
    if b.shape == "ring" or b.stroke:
        css["border"] = f"{_num(max(1.0, b.stroke_width))}px solid {b.stroke or b.fill}"
        if b.shape == "ring":
            css["border-radius"] = "50%"
            css["background"] = "transparent"
    _effects(css, b)
    return f'<div class="bs-b bs-shape" data-b="{b.id}" aria-hidden="true" style="{_style(css)}"></div>'


def _device_html(b: Block, media: str) -> str:
    """Frame around the media: drawn with CSS so the artwork stays exact."""
    scr = screen_rect(b.device or "", b.w, b.h)
    screen_css = {
        "left": f"{_num(scr.x)}px", "top": f"{_num(scr.y)}px", "width": f"{_num(scr.w)}px", "height": f"{_num(scr.h)}px",
        "border-radius": f"{_num(scr.radius)}px" if scr.radius else "", "background": b.mat or "",
        "padding": f"{_num(b.pad)}px" if b.pad else "",
    }
    parts = []
    if b.device == "browser":
        bar = browser_bar(b.w)
        dot = max(6.0, bar * 0.26)
        dots = "".join(f'<i style="width:{_num(dot)}px;height:{_num(dot)}px;background:{c};margin-right:{_num(dot * 0.7)}px"></i>' for c in ("#FF5F57", "#FEBC2E", "#28C840"))
        bar_bg = b.device_color or "#F3F3F1"
        parts.append(f'<div class="bs-bar" style="height:{_num(bar)}px;padding-left:{_num(bar * 0.5)}px;background:{bar_bg}">{dots}</div>')
    parts.append(f'<div class="bs-screen" style="{_style(screen_css)}">{media}</div>')
    if b.device == "phone":
        island_w, island_h = b.w * 0.27, b.w * 0.075
        parts.append(
            f'<div style="position:absolute;left:{_num((b.w - island_w) / 2)}px;top:{_num(scr.y + b.w * 0.03)}px;width:{_num(island_w)}px;'
            f'height:{_num(island_h)}px;border-radius:{_num(island_h)}px;background:#0B0B0C"></div>'
        )
    return "".join(parts)


def render_media(b: Block, options: RenderOptions) -> str:
    css = _box(b)
    if b.radius:
        css["border-radius"] = f"{_num(b.radius)}px"
    if b.mat and not b.device:
        css["background"] = b.mat
    if b.pad and not b.device and not b.tint:
        css["padding"] = f"{_num(b.pad)}px"
    if b.edge == "outline":
        css["box-shadow"] = f"0 0 0 1px {b.edge_color or 'rgba(0,0,0,.12)'}"
    elif b.edge == "soft":
        css["box-shadow"] = "0 24px 48px -24px rgba(0,0,0,.38),0 2px 8px rgba(0,0,0,.08)"
    if b.device:
        defaults = {"phone": "#121214", "tablet": "#1B1B1D", "browser": "#FFFFFF", "frame": "#1D1A17"}
        css["background"] = b.device_color if b.device_color and b.device != "browser" else defaults.get(b.device, "#111")
        if b.device == "browser":
            css["background"] = b.mat or "#FFFFFF"
        css["border-radius"] = f"{_num(screen_rect(b.device, b.w, b.h).outer_radius)}px"
    _effects(css, b, shadow_as_filter=bool(b.tint))
    url = options.asset_url(b) if options.asset_url else ""
    img_parts = {"object-fit": b.fit, "object-position": f"{_num(b.focal[0])}% {_num(b.focal[1])}%"}
    if b.zoom and b.zoom > 1.0 and b.fit == "cover":
        img_parts["transform"] = f"scale({b.zoom:.4f})"
        img_parts["transform-origin"] = f"{_num(b.focal[0])}% {_num(b.focal[1])}%"
    img_css = _style(img_parts)
    loading = ' loading="lazy"' if options.lazy else ""
    if b.tint and b.kind == "image" and url:
        # Recoloured silhouette of a strictly single-colour mark.
        mask = f"url('{html.escape(url)}') center / contain no-repeat"
        inner = f'<div style="position:absolute;inset:{_num(b.pad)}px;background:{b.tint};-webkit-mask:{mask};mask:{mask}"></div>'
        css.pop("overflow", None)
    elif b.kind == "video" and options.animated and not options.reduce_motion:
        poster = options.poster_url(b) if options.poster_url else ""
        poster_attr = f' poster="{html.escape(poster)}"' if poster else ""
        inner = f'<video src="{html.escape(url)}"{poster_attr} muted autoplay loop playsinline preload="metadata" style="{img_css}"></video>'
    else:
        if b.kind == "video":
            url = options.poster_url(b) if options.poster_url else url
        inner = f'<img src="{html.escape(url)}" alt="" decoding="async"{loading} style="{img_css}">'
    classes = "bs-b bs-img"
    if b.device:
        inner = _device_html(b, inner)
        classes += " bs-dev"
    asset_attr = f' data-asset="{b.asset_id}"' if b.asset_id else ""
    return f'<div class="{classes}" data-b="{b.id}"{asset_attr} style="{_style(css)}">{inner}</div>'


def render_block(b: Block, options: RenderOptions) -> str:
    if b.kind == "text":
        return render_text(b)
    if b.kind == "shape":
        return render_shape(b, options)
    if b.kind in ("image", "video"):
        return render_media(b, options)
    return ""


def render_section(section: Section, options: RenderOptions) -> str:
    css = {"height": f"{_num(section.height)}px", "background": section.gradient or section.background}
    blocks = sorted(section.blocks, key=lambda b: b.z)
    inner = "\n".join(render_block(b, options) for b in blocks)
    return (
        f'<section class="bs-sec" id="s-{section.id}" data-sec="{section.id}" data-type="{section.type}" '
        f'data-height="{_num(section.height)}" style="{_style(css)}">\n{inner}\n</section>'
    )


def render_html(presentation: Presentation, options: RenderOptions) -> str:
    sections = presentation.sections
    if options.section_ids is not None:
        wanted = set(options.section_ids)
        sections = [s for s in sections if s.id in wanted]
    families = sorted({b.style.family for s in sections for b in s.blocks if b.style} | set(presentation.fonts))
    css = [
        f":root{{--w:{presentation.width}px;--page:{presentation.page_background}}}",
        font_face_css(families, options.font_url),
        BASE_CSS,
    ]
    if options.animated and not options.reduce_motion:
        css.append(ANIMATION_CSS)
    if options.mode == "preview":
        css.append(PREVIEW_CSS)
    body = "\n".join(render_section(s, options) for s in sections)
    scripts = ""
    if options.mode == "html":
        scripts += f"<script>{RESPONSIVE_JS % presentation.width}</script>"
    if options.mode == "preview":
        scripts += f"<script>{PREVIEW_JS}</script>"
    if options.animated and not options.reduce_motion:
        scripts += (
            "<script>document.querySelectorAll('.bs-marquee .bs-marquee-inner').forEach(function(m){"
            "m.innerHTML=m.innerHTML+m.innerHTML;m.classList.add('bs-marquee-run');});</script>"
        )
    title = html.escape(options.title or presentation.title or "Presentation")
    lang = presentation.language if presentation.language in ("en", "pt") else "en"
    return (
        f'<!DOCTYPE html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta name="generator" content="Behance Studio">\n<title>{title}</title>\n'
        f"<style>\n{chr(10).join(css)}\n</style>\n{options.extra_head}</head>\n<body>\n"
        f'<main class="bs-deck">\n{body}\n</main>\n{scripts}{options.extra_body}\n</body>\n</html>\n'
    )


def render_pages_html(presentation: Presentation, pages: list, options: RenderOptions, margin: float = 0.0) -> str:
    """Print document: each page has its own named @page size; sections are
    sliced/scaled into pages (see ``export.paginate``)."""
    families = sorted({b.style.family for p in pages for sl in p.slices for b in sl.section.blocks if b.style} | set(presentation.fonts))
    css = [
        f":root{{--w:{presentation.width}px;--page:{presentation.page_background}}}",
        font_face_css(families, options.font_url),
        BASE_CSS,
        ".pg{position:relative;overflow:hidden;break-after:page;break-inside:avoid}",
        ".pg:last-child{break-after:auto}",
        # inline-block slices are monolithic for print fragmentation: clipped
        # overflow can never spill onto an extra page.
        ".row{display:block;line-height:0;font-size:0;text-align:center}",
        ".slice{position:relative;overflow:hidden;display:inline-block;vertical-align:top;text-align:left}",
        "html,body{background:transparent}",
    ]
    body = []
    for i, page in enumerate(pages):
        css.append(f"@page p{i}{{size:{_num(page.width)}px {_num(page.height)}px;margin:0}}")
        # The box is a hair shorter than the page: sub-pixel rounding must
        # never spill into an extra (blank, default-sized) page.
        css.append(f".pg{i}{{page:p{i};width:{_num(page.width)}px;height:{_num(page.height - 1.0)}px;background:{page.background};padding:{_num(margin)}px {_num(margin)}px}}")
        parts = []
        for sl in page.slices:
            sec_html = render_section(sl.section, options)
            parts.append(
                f'<div class="row"><div class="slice" style="height:{_num(sl.height)}px;width:{_num(presentation.width * sl.scale)}px">'
                f'<div style="zoom:{sl.scale:.6f};margin-top:{_num(-sl.y0)}px;width:{presentation.width}px">{sec_html}</div></div></div>'
            )
        body.append(f'<div class="pg pg{i}">{"".join(parts)}</div>')
    title = html.escape(options.title or presentation.title or "Presentation")
    lang = presentation.language if presentation.language in ("en", "pt") else "en"
    return (
        f'<!DOCTYPE html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n<title>{title}</title>\n'
        f"<style>\n{chr(10).join(css)}\n</style>\n</head>\n<body>\n{''.join(body)}\n</body>\n</html>\n"
    )
