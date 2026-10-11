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


def render_shape(b: Block) -> str:
    css = _box(b)
    if b.fill:
        css["background"] = b.fill
    if b.shape == "circle":
        css["border-radius"] = "50%"
    elif b.radius:
        css["border-radius"] = f"{_num(b.radius)}px"
    if b.shape == "ring" or b.stroke:
        css["border"] = f"{_num(max(1.0, b.stroke_width))}px solid {b.stroke or b.fill}"
        if b.shape == "ring":
            css["border-radius"] = "50%"
            css["background"] = "transparent"
    if b.opacity < 1:
        css["opacity"] = _num(b.opacity)
    return f'<div class="bs-b bs-shape" data-b="{b.id}" aria-hidden="true" style="{_style(css)}"></div>'


def render_media(b: Block, options: RenderOptions) -> str:
    css = _box(b)
    if b.radius:
        css["border-radius"] = f"{_num(b.radius)}px"
    if b.mat:
        css["background"] = b.mat
    if b.pad:
        css["padding"] = f"{_num(b.pad)}px"
    if b.edge == "outline":
        css["box-shadow"] = f"0 0 0 1px {b.edge_color or 'rgba(0,0,0,.12)'}"
    elif b.edge == "soft":
        css["box-shadow"] = "0 24px 48px -24px rgba(0,0,0,.38),0 2px 8px rgba(0,0,0,.08)"
    url = options.asset_url(b) if options.asset_url else ""
    img_css = _style({"object-fit": b.fit, "object-position": f"{_num(b.focal[0])}% {_num(b.focal[1])}%"})
    loading = ' loading="lazy"' if options.lazy else ""
    if b.kind == "video" and options.animated and not options.reduce_motion:
        poster = options.poster_url(b) if options.poster_url else ""
        poster_attr = f' poster="{html.escape(poster)}"' if poster else ""
        inner = f'<video src="{html.escape(url)}"{poster_attr} muted autoplay loop playsinline preload="metadata" style="{img_css}"></video>'
    else:
        if b.kind == "video":
            url = options.poster_url(b) if options.poster_url else url
        inner = f'<img src="{html.escape(url)}" alt="" decoding="async"{loading} style="{img_css}">'
    asset_attr = f' data-asset="{b.asset_id}"' if b.asset_id else ""
    return f'<div class="bs-b bs-img" data-b="{b.id}"{asset_attr} style="{_style(css)}">{inner}</div>'


def render_block(b: Block, options: RenderOptions) -> str:
    if b.kind == "text":
        return render_text(b)
    if b.kind == "shape":
        return render_shape(b)
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
