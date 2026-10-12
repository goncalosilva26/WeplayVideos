"""Identity and text-led modules: covers, statements, logo, colour, type,
pattern, quotes, chapters and closings.

Every module receives the section plan (content: assets, exact texts) and
parameters chosen by the Creative Director, and returns a Section of
absolutely positioned layers. Modules never invent facts: texts come from
the plan (user text or the honest generated copy), labels are generic
section names.
"""

from __future__ import annotations

from behance_studio.design import color as C
from behance_studio.design.typography import get_font
from behance_studio.layout.model import Section
from behance_studio.layout.modules.kit import Kit
from behance_studio.planning.models import SectionPlan

MODULES: dict = {}


def module(name: str):
    def deco(fn):
        MODULES[name] = fn
        fn.module_name = name
        return fn

    return deco


def _logo_id(sp: SectionPlan) -> str | None:
    """The logo a section shows: its own image. ``meta.logo_id`` (the brand's
    primary logo) is used only when the section has no image of its own or
    includes it — a section never swaps its image for another one."""
    meta = sp.meta.get("logo_id")
    ids = list(sp.asset_ids)
    if ids and meta not in ids:
        return ids[0]
    return meta or (ids[0] if ids else None)


def _corner_labels(k: Kit, sb, bg: str, left: str, right: str, y: float, m: float) -> None:
    color = k.soft(bg, 0.3)
    half = (k.W - 2 * m) / 2
    sb.add(k.label(left, m, y, half, color, editable="eyebrow" if left else None))
    sb.add(k.label(right, m + half, y, half, color, align="right"))


# ------------------------------------------------------------------ covers
@module("cover_logo")
def cover_logo(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """The brand mark alone on a field of colour: the classic opener."""
    ad = k.ad
    W = k.W
    lid = _logo_id(sp)
    candidates = [p["bg"]] if p.get("bg") else list(ad.surfaces) + [ad.light, ad.primary, ad.dark]
    bg = k.logo_surface(lid, candidates)
    H = k.px(p.get("height", 920))
    sb = k.section(sp, bg, "cover_logo")
    m = k.px(ad.margin if ad.margin >= 60 else 64)
    ink = k.ink(bg)
    tagline = sp.subtitle.strip()
    cy = H * (0.44 if tagline else 0.5)
    logo = None
    if lid:
        a = k.asset(lid)
        wide = a.aspect >= 2.0
        scale = {"bold": 0.56, "minimal": 0.36}.get(ad.concept, 0.44)
        logo = sb.add(k.logo(lid, W / 2, cy, W * scale, H * (0.26 if wide else 0.44), bg))
    if logo is None:
        logo = sb.add(k.display(sp.title, m, cy - k.px(80), W - 2 * m, ink, 2, 48, 150, align="center", editable="title"))
    if tagline and logo is not None:
        quote_role = "quote" if ad.concept in ("minimal", "story", "layered") else "display"
        size = 38 if ad.concept != "bold" else 30
        t = k.display(tagline, W * 0.18, logo.bottom + k.px(64), W * 0.64, ink, 2, 22, size, align="center", role=quote_role, editable="subtitle", line_height=1.12)
        sb.add(t)
    _corner_labels(k, sb, bg, sp.eyebrow, sp.title, k.px(48), m)
    sb.add(k.label(k.t("case_study"), m, H - k.px(66), W - 2 * m, k.soft(bg, 0.3)))
    return sb.finish(0, height=H)


@module("cover_hero")
def cover_hero(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Full-bleed key visual with the brand name set over a measured scrim."""
    ad = k.ad
    W = k.W
    hero = next((a for a in sp.asset_ids if k.may_crop(a)), None)
    if hero is None:
        return cover_split(k, sp, p)
    a = k.asset(hero)
    H = k.cover_height(hero, W, k.px(720), k.px(1060), max(k.px(780), min(k.px(1000), W / max(a.aspect, 0.8))))
    if H is None:
        return cover_split(k, sp, p)
    sb = k.section(sp, ad.dark, "cover_hero")
    img = sb.add(k.place(hero, 0, 0, W, H, prefer="cover", z=1))
    if img is None or img.fit != "cover":
        return cover_split(k, sp, p)
    m = k.px(max(72, ad.margin * 0.7))
    # Measure the photograph under the title zone: light imagery takes dark
    # type over a light veil, dark imagery light type over a dark scrim.
    zone = (m, H * 0.55, W * 0.6, H * 0.45 - m * 0.5)
    _color, _needs = k.c.overlay_style(img, zone, ad.light, ad.dark)
    light_image = _color == ad.dark
    shade = C.mix(ad.light, "#FFFFFF", 0.4) if light_image else C.mix(ad.dark, "#000000", 0.3)
    r, g, b = C.parse_hex(shade)
    strength = 0.7 if light_image else 0.78
    sb.add(k.shape(0, H * 0.38, W, H * 0.62, f"linear-gradient(to top, rgba({r},{g},{b},{strength}), rgba({r},{g},{b},0))", z=2))
    sb.add(k.shape(0, 0, W, H * 0.22, f"linear-gradient(to bottom, rgba({r},{g},{b},0.45), rgba({r},{g},{b},0))", z=2))
    light = (ad.dark if C.contrast_ratio(ad.dark, shade) >= 4.5 else "#111111") if light_image else (ad.light if C.contrast_ratio(ad.light, shade) >= 4.5 else "#FFFFFF")
    lid = sp.meta.get("logo_id")
    title_top = H - m
    from behance_studio.director.inventory import reversible

    if lid and reversible(k.asset(lid)):
        logo = k.logo(lid, m + W * 0.17, H - m - k.px(70), W * 0.34, k.px(140), shade)
        if logo is not None:
            logo.x = m
            logo.tint = light
            logo.overlay = True
            sb.add(logo)
            title_top = logo.y
    else:
        size = 132 if ad.concept == "story" else 104
        title = k.display(sp.title, m, 0, W * 0.56, light, 2, 54, size, editable="title", line_height=0.98)
        if title is not None:
            title.y = round(H - m - title.h, 2)
            title.overlay = True
            title.z = 3
            sb.add(title)
            title_top = title.y
    eyebrow = k.label(sp.eyebrow, m, title_top - k.px(34), W * 0.5, light, editable="eyebrow")
    if eyebrow is not None:
        eyebrow.overlay = True
        eyebrow.z = 3
        sb.add(eyebrow)
    if sp.subtitle:
        sub = k.body(sp.subtitle, W * 0.64, 0, W * 0.36 - m, light, 17, editable="subtitle", align="right")
        if sub is not None:
            sub.y = round(H - m - sub.h, 2)
            sub.overlay = True
            sub.z = 3
            sb.add(sub)
    top = k.label(sp.title, m, k.px(44), W - 2 * m, light, align="right")
    if top is not None:
        top.overlay = True
        top.z = 3
        sb.add(top)
    return sb.finish(0, height=H)


@module("cover_split")
def cover_split(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Image on one side, the identity on a colour field on the other."""
    ad = k.ad
    W = k.W
    H = k.px(p.get("height", 920))
    lid = sp.meta.get("logo_id")
    side = p.get("side", k.rng.choice(["left", "right"]))
    hero_id = sp.asset_ids[0] if sp.asset_ids and sp.asset_ids[0] != lid else None
    img_w = round(W * 0.56, 2)
    if hero_id and k.may_crop(hero_id):
        # Landscape key visuals get a shorter cover rather than a hard crop.
        for h in (H, k.px(820), k.px(740)):
            fitted = k.cover_width(hero_id, h, W * 0.42, W * 0.64, W * 0.56)
            if fitted:
                img_w, H = round(fitted, 2), h
                break
    field_x = img_w if side == "left" else 0.0
    field_w = W - img_w
    candidates = [ad.primary, ad.light, ad.secondary, ad.dark] if ad.concept != "minimal" else [ad.light, ad.surfaces[-1]]
    bg = k.logo_surface(lid, candidates)
    sb = k.section(sp, bg, "cover_split")
    hero = sp.asset_ids[0] if sp.asset_ids and sp.asset_ids[0] != lid else None
    if hero:
        ix = 0.0 if side == "left" else W - img_w
        placed = k.place(hero, ix, 0, img_w, H, prefer="cover", z=1) if k.may_crop(hero) else None
        if placed is not None and placed.fit == "cover":
            sb.add(placed)
        else:
            sb.add(k.shape(ix, 0, img_w, H, ad.surfaces[-1] if ad.surfaces[-1] != bg else ad.dark, z=0))
            sb.add(k.natural(hero, ix + img_w * 0.12, H * 0.12, img_w * 0.76, H * 0.76, shadow=ad.shadow))
    else:
        field_x, field_w = 0.0, W
    cx = field_x + field_w / 2
    logo = sb.add(k.logo(lid, cx, H * 0.45, field_w * 0.62, H * 0.34, bg)) if lid else None
    ink = k.ink(bg)
    if logo is None:
        logo = sb.add(k.display(sp.title, field_x + k.px(60), H * 0.38, field_w - k.px(120), ink, 3, 40, 96, align="center", editable="title"))
    if sp.subtitle and logo is not None:
        sb.add(k.display(sp.subtitle, field_x + field_w * 0.12, logo.bottom + k.px(48), field_w * 0.76, ink, 2, 18, 28, align="center", role="quote", editable="subtitle", line_height=1.15))
    m = k.px(48)
    sb.add(k.label(sp.eyebrow, field_x + m, k.px(44), field_w - 2 * m, k.soft(bg, 0.3), editable="eyebrow"))
    return sb.finish(0, height=H)


# -------------------------------------------------------------- statements
@module("statement")
def statement(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """The project in a few lines, set large — plus factual credits."""
    ad = k.ad
    W = k.W
    bg = p.get("bg") or k.surface()
    sb = k.section(sp, bg, "statement")
    ink = k.ink(bg)
    m = k.px(ad.margin if ad.margin >= 80 else 96)
    vpad = k.px(ad.vpad)
    y = vpad
    text = sp.body.strip() or sp.subtitle.strip()
    centered = ad.concept in ("story",) or p.get("align") == "center"
    # The section's own title (script or user edit) replaces the generic label.
    own_title = (sp.source == "script" or sp.meta.get("user_text")) and sp.title.strip()
    about = sp.title if own_title else k.t("about")
    about_field = "title" if own_title else None
    if ad.concept == "bold":
        if own_title:
            lab = k.label(about, m, y, W - 2 * m, k.soft(bg), editable=about_field)
            if lab is not None:
                sb.add(lab)
                y = lab.bottom + k.px(28)
        if sp.subtitle:
            head = k.display(sp.subtitle, m, y, W - 2 * m, ink, 3, 44, 132, editable="subtitle", line_height=0.94)
            if head is not None:
                sb.add(head)
                y = head.bottom + k.px(56)
        body = k.body(text, m, y, min(W - 2 * m, k.px(860)), ink, 26, weight=500, line_height=1.42) if text and text != sp.subtitle else None
        if body is not None:
            sb.add(body)
            y = body.bottom
    elif centered:
        sb.add(k.label(about, m, y, W - 2 * m, k.soft(bg), align="center", editable=about_field))
        y += k.px(54)
        block = k.display(text, W * 0.14, y, W * 0.72, ink, 7, 26, 46, align="center", role="title", editable="body", line_height=1.26)
        if block is not None:
            sb.add(block)
            y = block.bottom
    else:
        col = (W - 2 * m) / 12
        sb.add(k.label(about, m, y + k.px(10), col * 3, k.soft(bg), editable=about_field))
        block = k.display(text, m + col * 4, y, col * 8, ink, 8, 24, 42, role="title", editable="body", line_height=1.28)
        if block is not None:
            sb.add(block)
            y = block.bottom
    facts = sp.meta.get("facts") or []
    if facts:
        y += k.px(96)
        sb.add(k.shape(m, y, W - 2 * m, max(1.0, k.px(1)), C.mix(ink, bg, 0.75), z=1))
        y += k.px(28)
        n = len(facts)
        colw = (W - 2 * m) / max(3, n)
        bottom = y
        for i, (key, value) in enumerate(facts):
            x = m + i * colw
            lab = k.label(key, x, y, colw - k.px(24), k.soft(bg))
            if lab is not None:
                sb.add(lab)
                val = k.body(value, x, lab.bottom + k.px(10), colw - k.px(24), ink, 16, editable=None, line_height=1.45)
                if val is not None:
                    sb.add(val)
                    bottom = max(bottom, val.bottom)
        y = bottom
    return sb.finish(vpad, min_height=k.px(520))


@module("quote_band")
def quote_band(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """A brand message as a pause in the sequence."""
    ad = k.ad
    W = k.W
    bg = p.get("bg") or k.surface(prefer=ad.primary if ad.concept in ("bold", "layered") else None)
    sb = k.section(sp, bg, "quote_band")
    ink = k.ink(bg)
    text = (sp.body or sp.subtitle or sp.title).strip()
    m = k.px(max(64, ad.margin * 0.6))
    vpad = k.px(ad.vpad * 0.85)
    if ad.concept == "bold" and len(text.split()) <= 6:
        words = text.upper().replace(".", ". ").split()
        lines, cur = [], ""
        for w_ in words:
            cand = (cur + " " + w_).strip()
            if len(cand) > 12 and cur:
                lines.append(cur)
                cur = w_
            else:
                cur = cand
        if cur:
            lines.append(cur)
        blocks = k.c.line_fitted(lines, m, vpad, W - 2 * m, k.style("display", k.px(200), ink), "display", editable="body", max_size=k.px(230), line_height=0.92, source_text=text)
        sb.extend(blocks)
    else:
        sb.add(k.display(text, W * 0.12, vpad, W * 0.76, ink, 3, 40, 92, align="center", role="quote", editable="body", line_height=1.1, italic=ad.display_italic or ad.concept == "story"))
    return sb.finish(vpad, min_height=k.px(420))


@module("chapter")
def chapter(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Chapter card: a large numeral and the chapter name."""
    ad = k.ad
    W = k.W
    bg = p.get("bg") or k.surface(options=[ad.primary, ad.secondary, ad.dark])
    sb = k.section(sp, bg, "chapter")
    ink = k.ink(bg)
    m = k.px(ad.margin)
    H = k.px(p.get("height", 560))
    number = str(p.get("number", sp.meta.get("number", 1))).zfill(2)
    num = k.c.text(number, m - k.px(8), 0, k.px(520), k.style("numeral", k.px(300), ink, line_height=0.86, stroke=ink, weight=ad.display_weight), "numeral")
    if num is not None:
        num.y = round(H - k.px(96) - num.h, 2)
        num.decorative = True
        sb.add(num)
    title = k.display(sp.title, W * 0.42, 0, W * 0.58 - m, ink, 2, 40, 86, editable="title")
    if title is not None:
        title.y = round(H - k.px(110) - title.h, 2)
        sb.add(title)
        sb.add(k.label(f"{k.t('chapter')} {number}", W * 0.42, title.y - k.px(40), k.px(400), k.soft(bg)))
    return sb.finish(0, height=H)


# ------------------------------------------------------------------- logo
@module("logo_hero")
def logo_hero(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """The primary logo, large and alone."""
    ad = k.ad
    W = k.W
    lid = _logo_id(sp)
    options = [p["bg"]] if p.get("bg") else ([ad.light, ad.surfaces[-1]] if ad.concept in ("minimal",) else list(ad.surfaces) + [ad.light, ad.primary])
    bg = k.logo_surface(lid, [o for o in options if o != k.previous_bg()] or options)
    H = k.px(p.get("height", 880))
    sb = k.section(sp, bg, "logo_hero")
    if lid:
        a = k.asset(lid)
        wide = a.aspect >= 2.0
        scale = 0.5 if ad.concept in ("bold", "photo") else 0.42
        sb.add(k.logo(lid, W / 2, H / 2, W * scale, H * (0.3 if wide else 0.5), bg))
    if ad.labels:
        m = k.px(max(56, ad.margin * 0.6))
        sb.add(k.label(k.t("primary_logo"), m, H - k.px(70), W / 2, k.soft(bg)))
    return sb.finish(0, height=H)


@module("logo_pair")
def logo_pair(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Positive and reversed versions side by side, edge to edge."""
    ad = k.ad
    W = k.W
    H = k.px(p.get("height", 760))
    ids = list(sp.asset_ids)
    lid = _logo_id(sp)
    panel = next((i for i in ids if i != lid and (k.asset(i).analysis or {}).get("background") not in (None, "transparent")), None)
    light_bg = k.logo_surface(lid, [ad.light, ad.primary, ad.surfaces[0]])
    sb = k.section(sp, light_bg, "logo_pair")
    half = W / 2
    if lid:
        sb.add(k.logo(lid, half / 2, H / 2, half * 0.66, H * 0.4, light_bg))
    if panel:
        own = (k.asset(panel).analysis or {}).get("background")
        sb.add(k.shape(half, 0, half, H, own, z=0))
        sb.add(k.c.tile(panel, half, 0, half, H, own, pad_ratio=0.0))
    else:
        dark = ad.dark
        sb.add(k.shape(half, 0, half, H, dark, z=0))
        alt = next((i for i in ids if i != lid), lid)
        if alt:
            sb.add(k.logo(alt, half + half / 2, H / 2, half * 0.66, H * 0.4, dark))
    return sb.finish(0, height=H)


@module("logo_tiles")
def logo_tiles(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Logo system: variants and marks, each on its own colour tile."""
    ad = k.ad
    W = k.W
    ids = list(sp.asset_ids)[:4]
    seamless = ad.seamless and ad.concept != "photo"
    m = 0.0 if seamless else k.px(ad.margin)
    g = 0.0 if seamless else k.px(ad.gutter)
    n = max(1, len(ids))
    tile_w = (W - 2 * m - (n - 1) * g) / n
    tile_h = max(k.px(380), min(k.px(640), tile_w * (1.0 if n >= 3 else 0.72)))
    bg = p.get("bg") or k.surface()
    sb = k.section(sp, bg, "logo_tiles")
    top = 0.0 if seamless else k.px(ad.vpad * 0.6)
    pool = [ad.light, ad.primary, ad.dark, ad.secondary, ad.accent, C.mix(ad.light, ad.dark, 0.06)]
    used: list[str] = []
    for i, aid in enumerate(ids):
        x = m + i * (tile_w + g)
        a = k.asset(aid)
        info = a.analysis or {}
        if info.get("background") not in (None, "transparent") and info.get("background_uniformity", 0) >= 0.85:
            tbg = info["background"]
            sb.add(k.shape(x, top, tile_w, tile_h, tbg, z=0, radius=k.px(ad.radius)))
            sb.add(k.natural(aid, x + tile_w * 0.04, top + tile_h * 0.04, tile_w * 0.92, tile_h * 0.92))
        else:
            options = [c for c in pool if c not in used] + pool
            tbg = k.logo_surface(aid, options)
            used.append(tbg)
            sb.add(k.shape(x, top, tile_w, tile_h, tbg, z=0, radius=k.px(ad.radius)))
            sb.add(k.logo(aid, x + tile_w / 2, top + tile_h / 2, tile_w * 0.6, tile_h * 0.46, tbg))
    if not seamless and ad.labels:
        sb.add(k.label(k.t("logo_system"), m, top + tile_h + k.px(22), W / 2, k.soft(bg)))
        return sb.finish(k.px(ad.vpad * 0.6), height=top + tile_h + k.px(ad.vpad * 0.6) + k.px(40))
    return sb.finish(0, height=top * 2 + tile_h)


@module("logo_cards")
def logo_cards(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """The logo system as cards with depth: the primary mark on a large card,
    variants on smaller tilted cards around it, over the brand pattern."""
    ad = k.ad
    W = k.W
    ids = list(sp.asset_ids)
    lid = _logo_id(sp)
    others = [i for i in ids if i != lid][:3]
    H = k.px(p.get("height", 980))
    bg = p.get("bg") or k.surface(options=[ad.primary, ad.light, ad.secondary])
    sb = k.section(sp, bg, "logo_cards")
    pattern = sp.meta.get("pattern_id")
    if pattern:
        sb.add(k.shape(0, 0, W, H, bg, z=0, fill_asset=pattern, fill_size=k.px(320), opacity=0.14))
    cw, ch = W * 0.46, H * 0.48
    cx, cy = W / 2, H * 0.47
    card_bg = k.logo_surface(lid, [ad.light, "#FFFFFF", ad.primary]) if lid else ad.light
    main = k.shape(cx - cw / 2, cy - ch / 2, cw, ch, card_bg, z=5, rotate=-2.0, shadow="float", radius=k.px(ad.radius))
    main.decorative = False
    main.meta["layered"] = True
    sb.add(main)
    if lid:
        sb.add(k.logo(lid, cx, cy, cw * 0.66, ch * 0.42, card_bg, z=6, rotate=-2.0, layered=True))
    spots = [(0.2, 0.26, -6.0), (0.8, 0.3, 5.0), (0.24, 0.76, 4.0), (0.78, 0.74, -4.0)]
    pool = [ad.dark, ad.secondary, ad.light, ad.accent]
    for i, aid in enumerate(others):
        fx, fy, rot = spots[i]
        sw, sh = W * 0.24, W * 0.24 * 0.78
        a = k.asset(aid)
        info = a.analysis or {}
        own = info.get("background") if info.get("background") not in (None, "transparent") and info.get("background_uniformity", 0) >= 0.85 else None
        tbg = own or k.logo_surface(aid, [c for c in pool if c != card_bg] + pool)
        x, y = W * fx - sw / 2, H * fy - sh / 2
        card = k.shape(x, y, sw, sh, tbg, z=3 + i, rotate=rot * (ad.rotation or 4.0) / 5, shadow="lifted", radius=k.px(ad.radius))
        card.decorative = False
        card.meta["layered"] = True
        sb.add(card)
        if own:
            sb.add(k.natural(aid, x + sw * 0.04, y + sh * 0.04, sw * 0.92, sh * 0.92, z=3 + i, rotate=card.rotate, layered=True))
        else:
            sb.add(k.logo(aid, x + sw / 2, y + sh / 2, sw * 0.6, sh * 0.5, tbg, z=3 + i, rotate=card.rotate, layered=True))
    return sb.finish(0, height=H)


@module("mark_feature")
def mark_feature(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """The brand symbol at poster scale beside a short message."""
    ad = k.ad
    W = k.W
    H = k.px(p.get("height", 820))
    mid = sp.asset_ids[0] if sp.asset_ids else None
    options = [ad.primary, ad.secondary, ad.light, ad.dark]
    bg = k.logo_surface(mid, [o for o in options if o != k.previous_bg()] or options)
    sb = k.section(sp, bg, "mark_feature")
    ink = k.ink(bg)
    m = k.px(max(72, ad.margin * 0.7))
    if mid:
        size = H * 0.74
        sb.add(k.logo(mid, W - m - size / 2, H / 2, size, size, bg))
    text = sp.subtitle or sp.body or sp.title
    sb.add(k.display(text, m, m, W * 0.46, ink, 4, 40, 112, editable="subtitle" if sp.subtitle else "title", line_height=0.96))
    return sb.finish(0, height=H)


# ----------------------------------------------------------------- colour
def _swatches(sp: SectionPlan) -> list[dict]:
    return list(sp.meta.get("swatches") or [])


@module("palette_columns")
def palette_columns(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Brand colours as full-height columns with their values."""
    ad = k.ad
    W = k.W
    sw = _swatches(sp)[:6]
    seamless = ad.seamless
    m = 0.0 if seamless else k.px(ad.margin)
    H = k.px(p.get("height", 640 if seamless else 560))
    top = 0.0 if seamless else k.px(ad.vpad * 0.6)
    bg = p.get("bg") or k.surface()
    sb = k.section(sp, bg, "palette_columns")
    shares = [1.7] + [1.0] * (len(sw) - 1)
    total = sum(shares) or 1
    x = m
    for s, share in zip(sw, shares):
        w = (W - 2 * m) * share / total
        col = k.shape(x, top, w, H, s["hex"], z=1)
        if C.delta_e(s["hex"], bg) < 6:
            col.stroke = C.mix(bg, ad.dark, 0.16)
            col.stroke_width = max(1.0, k.px(1))
        sb.add(col)
        ink = k.ink(s["hex"])
        pad = k.px(26)
        y = top + H - pad
        rows = [C.rgb_string(s["hex"]), s["hex"].upper()]
        for txt in rows:
            lab = k.label(txt, x + pad, 0, w - 2 * pad, ink, size=11)
            if lab is not None:
                y -= lab.h + k.px(4)
                lab.y = round(y, 2)
                sb.add(lab)
        if s.get("name"):
            name = k.c.text(s["name"], x + pad, 0, w - 2 * pad, k.style("title", k.px(30 if share > 1 else 24), ink, line_height=1.1), "title")
            if name is not None:
                name.y = round(y - name.h - k.px(10), 2)
                sb.add(name)
        x += w
    if not seamless and ad.labels:
        sb.add(k.label(k.t("colour"), m, top + H + k.px(22), W / 2, k.soft(bg)))
        return sb.finish(0, height=top + H + k.px(22) + k.px(40) + top * 0.6)
    return sb.finish(0, height=top * 2 + H)


@module("palette_circles")
def palette_circles(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Overlapping colour discs — a layered take on the palette."""
    ad = k.ad
    W = k.W
    sw = _swatches(sp)[:6]
    n = max(1, len(sw))
    m = k.px(ad.margin)
    D = min(k.px(420), (W - 2 * m) / (n * 0.78 + 0.22))
    step = D * 0.78
    bg = p.get("bg") or k.surface()
    sb = k.section(sp, bg, "palette_circles")
    top = k.px(ad.vpad)
    x0 = (W - (step * (n - 1) + D)) / 2
    for i, s in enumerate(sw):
        x = x0 + i * step
        c = k.shape(x, top, D, D, s["hex"], z=2 + i, shape="circle")
        if C.delta_e(s["hex"], bg) < 6:
            c.stroke = C.mix(bg, ad.dark, 0.2)
            c.stroke_width = max(1.0, k.px(1.5))
        c.decorative = False
        c.meta["layered"] = True
        sb.add(c)
        ink = k.soft(bg, 0.2)
        lab = k.label(s.get("name") or s["hex"].upper(), x, top + D + k.px(28), step if i < n - 1 else D, ink)
        if lab is not None:
            sb.add(lab)
            sb.add(k.label(s["hex"].upper(), x, lab.bottom + k.px(6), step if i < n - 1 else D, k.soft(bg), size=10.5))
    return sb.finish(k.px(ad.vpad), height=top + D + k.px(28 + 60) + k.px(ad.vpad))


# ------------------------------------------------------------- typography
@module("type_specimen")
def type_specimen(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """The brand typefaces, set live in the fonts themselves."""
    ad = k.ad
    W = k.W
    bg = p.get("bg") or k.surface()
    sb = k.section(sp, bg, "type_specimen")
    ink = k.ink(bg)
    soft = k.soft(bg)
    m = k.px(ad.margin if ad.margin >= 80 else 96)
    top = k.px(ad.vpad)
    fonts = sp.meta.get("fonts") or {}
    display = fonts.get("display") or ad.display
    text_font = fonts.get("text") or ad.text
    disp = get_font(display)
    col = W * 0.46
    aa = k.c.text("Aa", m - k.px(6), top, col - m - k.px(30), k.style("display", k.px(300), ink, line_height=0.9, uppercase=False, tracking=-0.02, weight=disp.clamp_weight(ad.display_weight)), "display")
    sb.add(aa)
    y = top + k.px(18)
    sb.add(k.label(k.t("display"), col, y, W - col - m, soft))
    name = k.c.text(display, col, y + k.px(30), W - col - m, k.style("title", k.px(54), ink, uppercase=False, line_height=1.05), "title")
    sb.add(name)
    y = (name.bottom if name else y) + k.px(26)
    for line in ("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz", "0123456789 &!?"):
        b = k.c.text(line, col, y, W - col - m, k.style("title", k.px(22), ink, uppercase=False, tracking=0.02, line_height=1.35), "caption")
        if b is not None:
            sb.add(b)
            y = b.bottom + k.px(4)
    y = max(y, (aa.bottom if aa else y)) + k.px(70)
    sb.add(k.shape(m, y, W - 2 * m, max(1.0, k.px(1)), C.mix(ink, bg, 0.75), z=1))
    y += k.px(34)
    sb.add(k.label(k.t("text"), m, y, k.px(300), soft))
    tname = k.c.text(text_font, col, y - k.px(6), W - col - m, k.style("body", k.px(40), ink, weight=500, line_height=1.1), "title")
    sb.add(tname)
    y = (tname.bottom if tname else y) + k.px(18)
    sample = sp.body or "The quick brown fox jumps over the lazy dog."
    sb.add(k.body(sample, col, y, W - col - m, ink, 19, editable=None))
    return sb.finish(k.px(ad.vpad))


# ---------------------------------------------------------------- closing
@module("closing")
def closing(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Sign-off: the mark, a thank-you and (optionally) the brand message."""
    ad = k.ad
    W = k.W
    lid = sp.meta.get("logo_id")
    pref = {"minimal": ad.light, "bold": ad.primary, "photo": ad.dark, "layered": ad.primary, "story": ad.dark}.get(ad.concept, ad.light)
    options = [pref] + [s for s in ad.surfaces if s != pref]
    bg = k.logo_surface(lid, [o for o in options if o != k.previous_bg()] or options)
    H = k.px(p.get("height", 760 if ad.concept != "minimal" else 640))
    sb = k.section(sp, bg, "closing")
    ink = k.ink(bg)
    message = sp.body.strip()
    if message and ad.concept in ("bold", "story"):
        msg = k.display(message, W * 0.12, k.px(120), W * 0.76, ink, 3, 40, 96 if ad.concept == "bold" else 70, align="center",
                        role="display" if ad.concept == "bold" else "quote", editable="body", line_height=1.0)
        if msg is not None:
            sb.add(msg)
            cy = msg.bottom + (H - msg.bottom) / 2 - k.px(20)
        else:
            cy = H / 2
    else:
        cy = H * 0.44
    logo = None
    panel = sp.meta.get("logo_panel_id")
    if lid and k.logo_contrast(lid, bg) < 3.0 and panel and k.asset(panel) is not None:
        own = (k.asset(panel).analysis or {}).get("background")
        if own and own != "transparent":
            # The brand's own reversed artwork, seamless on its own ground.
            sb.background = own
            bg = own
            ink = k.ink(bg)
            pw = W * 0.42
            logo = sb.add(k.natural(panel, (W - pw) / 2, cy - pw / k.aspect(panel) / 2, pw, pw / k.aspect(panel)))
    if logo is None and lid:
        if k.logo_contrast(lid, bg) < 3.0:
            from behance_studio.director.inventory import reversible

            if not reversible(k.asset(lid)):
                sb.background = bg = k.logo_surface(lid, [ad.light, ad.primary, ad.secondary])
                ink = k.ink(bg)
                for b in sb.blocks:
                    if b.kind == "text" and b.style is not None:
                        b.style = b.style.with_(color=ink)
        logo = sb.add(k.logo(lid, W / 2, cy, W * 0.26, H * 0.2, bg))
    ty = (logo.bottom if logo else cy) + k.px(48)
    sb.add(k.label(sp.title or k.t("thank_you"), W * 0.2, ty, W * 0.6, k.soft(bg, 0.25), align="center", editable="title"))
    return sb.finish(0, height=H)
