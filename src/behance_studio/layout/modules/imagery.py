"""Imagery and in-context modules.

Photographs and photographic mockups may run full-bleed and be cropped
within their measured allowance (never through detected typography).
Finished artwork is never cropped: it is staged on a surface, framed, shown
in a device or arranged at its own proportions.
"""

from __future__ import annotations

from behance_studio.design import color as C
from behance_studio.layout.model import Section
from behance_studio.layout.modules.identity import module
from behance_studio.layout.modules.kit import Kit
from behance_studio.planning.models import SectionPlan


def _ids(sp: SectionPlan) -> list[str]:
    return [a for a in sp.asset_ids if a]


def _rgba(color: str, alpha: float) -> str:
    r, g, b = C.parse_hex(color) or (0, 0, 0)
    return f"rgba({r},{g},{b},{alpha})"


# --------------------------------------------------------------- full bleed
@module("fullbleed")
def fullbleed(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """One image edge to edge, height from its own proportions."""
    W = k.W
    ids = _ids(sp)
    aid = ids[0]
    a = k.asset(aid)
    sb = k.section(sp, k.ad.dark, "fullbleed")
    if not k.may_crop(aid):
        if a.aspect >= 1.6:
            # Wide finished artwork (billboard): edge to edge at its exact proportions.
            H = W / a.aspect
            sb.add(k.natural(aid, 0, 0, W, H, upscale=2.0, z=1))
            return sb.finish(0, height=round(H, 2))
        return stage(k, sp, p)
    if a.aspect < 1.15 and k.ad.concept != "photo":
        return stage(k, sp, p)
    inset = k.ad.concept == "minimal"
    m = k.px(k.ad.margin) if inset else 0.0
    top = k.px(k.ad.vpad * 0.55) if inset else 0.0
    fw = W - 2 * m
    target = max(k.px(560), min(k.px(1000 if inset else 1080), fw / max(a.aspect, 0.5)))
    H = k.cover_height(aid, fw, k.px(480), k.px(1120), target)
    if H is None:
        return stage(k, sp, p)
    if inset:
        sb.background = k.surface()
    sb.add(k.place(aid, m, top, fw, H, prefer="cover", z=1))
    return sb.finish(0, height=round(H + 2 * top, 2))


@module("duo")
def duo(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Two images side by side: edge to edge when both may be cropped."""
    ad = k.ad
    W = k.W
    ids = _ids(sp)[:2]
    if len(ids) < 2:
        return fullbleed(k, sp, p)
    seamless = ad.seamless or p.get("seamless", False)
    m = 0.0 if seamless else k.px(ad.margin)
    g = k.px(ad.gutter) if (not seamless or ad.gutter >= 8) else 0.0
    if seamless and ad.concept == "bold":
        g = 0.0  # graphic concept: pairs butt together
    bg = p.get("bg") or (k.surface() if not seamless else k.stage_bg())
    sb = k.section(sp, bg, "duo")
    top = 0.0 if seamless else k.px(ad.vpad * 0.7)
    cell_w = (W - 2 * m - g) / 2
    if all(k.may_crop(i) for i in ids):
        from behance_studio.layout.fitting import can_cover

        aspect = next((r for r in (0.8, 0.9, 1.0, 0.75, 1.25) if all(can_cover(k.asset(i), r) for i in ids)), None)
        if aspect is not None:
            H = cell_w / aspect
            for i, aid in enumerate(ids):
                sb.add(k.place(aid, m + i * (cell_w + g), top, cell_w, H, prefer="cover", z=1))
            return sb.finish(0, height=round(top * 2 + H, 2))
    return _natural_row(k, sp, ids, "duo", bg if not seamless else k.stage_bg())


def _natural_row(k: Kit, sp: SectionPlan, ids: list[str], pattern: str, bg: str) -> Section:
    """Images aspect-true on a common height (nothing cropped)."""
    ad = k.ad
    W = k.W
    sb = k.section(sp, bg, pattern)
    m = k.px(max(96, ad.margin))
    top = k.px(ad.vpad * 0.7)
    blocks, _h = k.c.row(ids, m, top, W - 2 * m, k.px(max(28, ad.gutter)), max_h=k.px(780))
    for b in blocks:
        if ad.shadow and ad.shadow != "hard":
            b.shadow = "soft"
    sb.extend(blocks)
    return sb.finish(top)


@module("trio")
def trio(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """A lead image with two details stacked beside it."""
    ad = k.ad
    W = k.W
    ids = _ids(sp)[:3]
    if len(ids) < 3:
        return duo(k, sp, p) if len(ids) >= 2 else fullbleed(k, sp, p)
    if not all(k.may_crop(i) for i in ids):
        return _natural_row(k, sp, ids, "trio", k.stage_bg())
    seamless = ad.seamless
    m = 0.0 if seamless else k.px(ad.margin)
    g = k.px(ad.gutter) if ad.gutter else (0.0 if seamless else k.px(24))
    bg = p.get("bg") or k.surface()
    sb = k.section(sp, bg, "trio")
    top = 0.0 if seamless else k.px(ad.vpad * 0.7)
    inner = W - 2 * m
    lead_w = inner * 0.62
    side_w = inner - lead_w - g
    H = max(k.px(640), min(k.px(980), lead_w / 1.2))
    half = (H - g) / 2
    lead_right = p.get("flip", k.rng.random() < 0.5)
    lx = m + (side_w + g if lead_right else 0)
    sx = m if lead_right else m + lead_w + g
    from itertools import permutations

    from behance_studio.layout.fitting import choose_fit

    order = None
    for perm in permutations(ids):
        a0, a1, a2 = (k.asset(i) for i in perm)
        if (choose_fit(a0, lead_w, H).mode == "cover" and choose_fit(a1, side_w, half).mode == "cover"
                and choose_fit(a2, side_w, half).mode == "cover"):
            order = perm
            break
    if order is None:
        return _stacked_trio(k, sp, ids, bg, m, g, top)
    sb.add(k.place(order[0], lx, top, lead_w, H, z=1))
    sb.add(k.place(order[1], sx, top, side_w, half, z=1))
    sb.add(k.place(order[2], sx, top + half + g, side_w, half, z=1))
    return sb.finish(0, height=round(top * 2 + H, 2))


def _stacked_trio(k: Kit, sp: SectionPlan, ids: list[str], bg: str, m: float, g: float, top: float) -> Section:
    """Lead image across the full width, the other two as a pair below."""
    from behance_studio.layout.fitting import choose_fit

    W = k.W
    sb = k.section(sp, bg, "trio")
    inner = W - 2 * m
    lead = max(ids, key=lambda i: k.aspect(i))
    rest = [i for i in ids if i != lead]
    lh = k.cover_height(lead, inner, k.px(420), k.px(860), inner / max(k.aspect(lead), 1.0))
    y = top
    if lh is not None:
        sb.add(k.place(lead, m, y, inner, lh, z=1))
        y += lh + (g or k.px(16))
    else:
        rest = ids
    cell = (inner - (g or k.px(16))) / 2
    from behance_studio.layout.fitting import can_cover

    aspect = next((r for r in (1.0, 0.8, 1.25, 0.9) if all(can_cover(k.asset(i), r) for i in rest[:2])), None)
    if aspect is not None and len(rest) >= 2:
        h = cell / aspect
        for i, aid in enumerate(rest[:2]):
            sb.add(k.place(aid, m + i * (cell + (g or k.px(16))), y, cell, h, z=1))
        y += h
    else:
        blocks, h = k.c.row(rest, m, y, inner, g or k.px(16), max_h=k.px(700))
        sb.extend(blocks)
        y += h
    return sb.finish(0, height=round(y + top, 2))


# ------------------------------------------------------------------ stages
@module("stage")
def stage(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """One finished artwork, aspect-true, on a surface with depth."""
    ad = k.ad
    W = k.W
    aid = _ids(sp)[0]
    a = k.asset(aid)
    own = (a.analysis or {}).get("background")
    bg = p.get("bg") or k.stage_bg(own)
    sb = k.section(sp, bg, "stage")
    vpad = k.px(ad.vpad * 0.8)
    box_w = W * (0.62 if a.aspect < 1.2 else 0.78)
    box_h = k.px(860 if a.aspect < 1.2 else 700)
    shadow = ad.shadow
    shadow_color = C.mix(ad.dark, bg, 0.15) if shadow == "hard" else None
    b = k.natural(aid, (W - box_w) / 2, vpad, box_w, box_h, ay=0.0, shadow=shadow, shadow_color=shadow_color, radius=k.px(ad.radius) if ad.radius else 0)
    sb.add(b)
    return sb.finish(vpad + (k.px(24) if shadow == "hard" else 0))


@module("stage_pair")
def stage_pair(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Two artworks staged side by side, the second slightly lower."""
    ad = k.ad
    W = k.W
    ids = _ids(sp)[:2]
    if len(ids) < 2:
        return stage(k, sp, p)
    owns = [(k.asset(i).analysis or {}).get("background") for i in ids]
    bg = p.get("bg") or k.stage_bg(next((o for o in owns if o and o != "transparent"), None))
    sb = k.section(sp, bg, "stage_pair")
    m = k.px(max(96, ad.margin))
    g = k.px(max(48, ad.gutter * 2))
    vpad = k.px(ad.vpad * 0.8)
    cell_w = (W - 2 * m - g) / 2
    stagger = k.px(p.get("stagger", 90))
    shadow = ad.shadow
    shadow_color = C.mix(ad.dark, bg, 0.15) if shadow == "hard" else None
    for i, aid in enumerate(ids):
        y = vpad + (stagger if i == 1 else 0)
        sb.add(k.natural(aid, m + i * (cell_w + g), y, cell_w, k.px(900), ay=0.0, shadow=shadow, shadow_color=shadow_color))
    return sb.finish(vpad + (k.px(24) if shadow == "hard" else 0))


@module("doc_stage")
def doc_stage(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """A guideline page shown whole, like a printed sheet."""
    ad = k.ad
    W = k.W
    aid = _ids(sp)[0]
    bg = p.get("bg") or k.stage_bg((k.asset(aid).analysis or {}).get("background"))
    sb = k.section(sp, bg, "doc_stage")
    vpad = k.px(ad.vpad * 0.8)
    box_w = W * 0.74
    sb.add(k.natural(aid, (W - box_w) / 2, vpad, box_w, k.px(980), ay=0.0, shadow="soft" if not C.is_dark(bg) else "lifted"))
    return sb.finish(vpad)


@module("pattern_field")
def pattern_field(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """The brand pattern edge to edge, with the mark on a badge."""
    ad = k.ad
    W = k.W
    ids = _ids(sp)
    pid = ids[0]
    H = k.px(p.get("height", 720))
    sb = k.section(sp, ad.primary, "pattern_field")
    img = sb.add(k.place(pid, 0, 0, W, H, prefer="cover", z=1))
    if img is not None and img.fit != "cover":
        img.fit = "cover"  # patterns repeat: any crop keeps their character
    mark = sp.meta.get("logo_id")
    if mark and p.get("badge", True):
        d = k.px(300)
        badge_bg = ad.light
        sb.add(k.shape((W - d) / 2, (H - d) / 2, d, d, badge_bg, z=3, shape="circle", shadow="soft"))
        sb.add(k.logo(mark, W / 2, H / 2, d * 0.62, d * 0.5, badge_bg, z=4, layered=True))
    return sb.finish(0, height=H)


# -------------------------------------------------------------- in context
@module("poster_wall")
def poster_wall(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Posters in frames on a softly lit wall."""
    ad = k.ad
    W = k.W
    ids = _ids(sp)[:3]
    wall = p.get("bg") or (C.mix(ad.dark, ad.light, 0.12) if ad.concept in ("photo", "story") else C.mix(ad.light, ad.dark, 0.1))
    H = k.px(p.get("height", 1000))
    sb = k.section(sp, wall, "poster_wall")
    light = C.mix(wall, "#FFFFFF", 0.16)
    sb.gradient = f"radial-gradient(ellipse 70% 60% at 50% 38%, {light} 0%, {wall} 72%)"
    n = len(ids)
    frame_h = H * (0.6 if n > 1 else 0.68)
    gap = k.px(90)
    sizes = []
    from behance_studio.layout.devices import device_size

    for aid in ids:
        a = k.asset(aid)
        lo, hi = 10.0, W
        for _ in range(24):
            mid = (lo + hi) / 2
            if device_size("frame", mid, mid / a.aspect)[1] <= frame_h:
                lo = mid
            else:
                hi = mid
        sizes.append(device_size("frame", lo, lo / a.aspect))
    total = sum(w for w, _ in sizes) + gap * (n - 1)
    if total > W * 0.84:
        scale = W * 0.84 / total
        sizes = [(w * scale, h * scale) for w, h in sizes]
        gap *= scale
        total = W * 0.84
    x = (W - total) / 2
    base = H * 0.18 + frame_h
    frame_color = "#F4F1EC" if C.is_dark(wall) else "#1E1B18"
    for aid, (w, h) in zip(ids, sizes):
        sb.add(k.device(aid, "frame", x, base - h, w, h, ay=1.0, device_color=frame_color, shadow="lifted", mat="#FFFFFF"))
        x += w + gap
    return sb.finish(0, height=H)


@module("phones")
def phones(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Social or mobile designs on phones, the middle one raised."""
    ad = k.ad
    W = k.W
    ids = _ids(sp)[:3]
    bg = p.get("bg") or k.stage_bg()
    sb = k.section(sp, bg, "phones")
    vpad = k.px(ad.vpad * 0.75)
    phone_h = k.px(p.get("phone_height", 860))
    n = len(ids)
    screen_aspect = 9 / 19.5
    from behance_studio.layout.devices import device_size

    pw, ph = device_size("phone", phone_h * screen_aspect * 0.92, phone_h * 0.92)
    gap = k.px(70)
    total = n * pw + (n - 1) * gap
    if total > W * 0.86:
        scale = W * 0.86 / total
        pw, ph, gap = pw * scale, ph * scale, gap * scale
        total = W * 0.86
    x = (W - total) / 2
    lift = k.px(70) if n == 3 else 0.0
    for i, aid in enumerate(ids):
        y = vpad + (0.0 if (n == 3 and i == 1) else lift)
        sb.add(k.device(aid, "phone", x, y, pw, ph, screen_aspect=screen_aspect, shadow="lifted", z=3))
        x += pw + gap
    return sb.finish(vpad)


@module("feed_grid")
def feed_grid(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """A social feed: posts on a tight grid at their own proportions."""
    ad = k.ad
    W = k.W
    ids = _ids(sp)[:9]
    n = len(ids)
    cols = 2 if n in (2, 4) else (3 if n >= 3 else 1)
    if n > 4 and n % 3 == 1:
        ids = ids[: n - 1]
        n -= 1
    bg = p.get("bg") or k.surface()
    sb = k.section(sp, bg, "feed_grid")
    m = k.px(max(120, ad.margin)) if cols == 3 else k.px(260)
    g = k.px(ad.gutter if ad.gutter else 12)
    vpad = k.px(ad.vpad * 0.7)
    aspects = sorted(k.aspect(i) for i in ids)
    cell_aspect = aspects[len(aspects) // 2]
    cell_w = (W - 2 * m - (cols - 1) * g) / cols
    cell_h = cell_w / cell_aspect
    for i, aid in enumerate(ids):
        r, c = divmod(i, cols)
        x = m + c * (cell_w + g)
        y = vpad + r * (cell_h + g)
        mat = (k.asset(aid).analysis or {}).get("background")
        tile = k.c.tile(aid, x, y, cell_w, cell_h, mat if mat and mat != "transparent" else C.mix(bg, ad.dark, 0.06), pad_ratio=0.0, radius=k.px(ad.radius))
        sb.add(tile)
    return sb.finish(vpad)


@module("browser")
def browser(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """A website in a browser window."""
    ad = k.ad
    W = k.W
    aid = _ids(sp)[0]
    bg = p.get("bg") or k.stage_bg()
    sb = k.section(sp, bg, "browser")
    vpad = k.px(ad.vpad * 0.8)
    box_w = W * 0.8
    sb.add(k.device(aid, "browser", (W - box_w) / 2, vpad, box_w, box_w / 1.6 + k.px(40), screen_aspect=16 / 10, shadow="lifted"))
    return sb.finish(vpad)


@module("video_stage")
def video_stage(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Motion: wide films edge to edge, square/vertical pieces on a stage."""
    aid = _ids(sp)[0]
    a = k.asset(aid)
    if a.aspect >= 1.3 and k.may_crop(aid):
        return fullbleed(k, sp, p)
    if a.aspect < 0.8:
        return phones(k, sp, p)
    return stage(k, sp, p)


# ---------------------------------------------------------------- layered
@module("collage")
def collage(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """A masked photograph overlapped by a floating artwork card, with the
    section's words in the open space."""
    ad = k.ad
    W = k.W
    ids = _ids(sp)
    photo = next((i for i in ids if k.may_crop(i)), None)
    card = next((i for i in ids if i != photo and (k.asset(i).effective_kind not in ("logo", "logo_variant", "monogram"))), None)
    if photo is None or card is None:
        if sp.type == "cover":
            from behance_studio.layout.modules.identity import cover_split

            return cover_split(k, sp, p)
        return stage_pair(k, sp, p) if len(ids) >= 2 else stage(k, sp, p)
    bg = p.get("bg") or k.surface()
    H = k.px(p.get("height", 1000))
    sb = k.section(sp, bg, "collage")
    m = k.px(ad.margin)
    flip = p.get("flip", k.rng.random() < 0.5)
    top = k.px(90)
    pw = None
    for ph in (H - 2 * top, (H - 2 * top) * 0.85, (H - 2 * top) * 0.72):
        pw = k.cover_width(photo, ph, W * 0.42, W * 0.6, W * 0.54)
        if pw is not None:
            break
    if pw is None:
        if sp.type == "cover":
            from behance_studio.layout.modules.identity import cover_split

            return cover_split(k, sp, p)
        return stage_pair(k, sp, p)
    px_ = W - m - pw if flip else m
    clip = p.get("clip", k.rng.choice(["arch", "rounded"]))
    img = sb.add(k.place(photo, px_, top, pw, ph, z=1, clip=clip, radius=k.px(28) if clip == "rounded" else 0, layered=True))
    if img is not None and img.fit != "cover":
        img.clip = None
    cw = W * 0.27
    cx = (px_ - cw * 0.62) if flip else (px_ + pw - cw * 0.38)
    rot = (ad.rotation or 4.0) * (1 if flip else -1)
    card_top = H * 0.4
    sb.add(k.natural(card, cx, card_top, cw, H - card_top - k.px(70), ay=0.0, rotate=rot, shadow="float", z=4, layered=True))
    # Words in the free column, above the card.
    tx = m if flip else px_ + pw + k.px(72)
    tw = (px_ - m - k.px(72)) if flip else (W - tx - m)
    text = sp.title if sp.type == "cover" else (sp.subtitle or sp.title)
    field = "title" if sp.type == "cover" or not sp.subtitle else "subtitle"
    ink = k.ink(bg)
    y = top + k.px(10)
    if sp.type == "cover" and sp.eyebrow:
        lab = sb.add(k.label(sp.eyebrow, tx, y, tw, k.soft(bg), editable="eyebrow"))
        y = lab.bottom + k.px(20) if lab else y
    t = k.display(text, tx, y, tw, ink, 3, 34, 96 if sp.type == "cover" else 64, editable=field, max_height=card_top - y - k.px(60), line_height=1.0)
    if t is not None:
        sb.add(t)
        if sp.type == "cover" and sp.subtitle:
            sub = k.body(sp.subtitle, tx, t.bottom + k.px(18), tw, k.soft(bg, 0.2), 18, editable="subtitle")
            if sub is not None and sub.bottom < card_top - k.px(20):
                sb.add(sub)
    return sb.finish(0, height=H)


@module("float_stack")
def float_stack(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Finished artworks as cards, fanned and overlapping with depth."""
    ad = k.ad
    W = k.W
    ids = _ids(sp)[:4]
    if len(ids) < 2:
        return stage(k, sp, p)
    bg = p.get("bg") or k.surface(options=[ad.primary, ad.light, ad.secondary])
    H = k.px(p.get("height", 980))
    sb = k.section(sp, bg, "float_stack")
    pattern = sp.meta.get("pattern_id")
    if pattern:
        sb.add(k.shape(0, 0, W, H, bg, z=0, fill_asset=pattern, fill_size=k.px(360), opacity=0.16))
    n = len(ids)
    card_h = H * (0.64 if n <= 3 else 0.56)
    widths = [min(card_h * k.aspect(i), W * 0.36) for i in ids]
    span = W - 2 * k.px(ad.margin)
    step = (span - widths[-1]) / max(1, n - 1)
    rots = [-1.0, 0.6, -0.4, 0.8]
    x = k.px(ad.margin)
    for i, (aid, w) in enumerate(zip(ids, widths)):
        y = H * 0.18 + (k.px(60) if i % 2 else 0)
        sb.add(k.natural(aid, x, y, w, card_h, ay=0.0, rotate=round(rots[i % 4] * (ad.rotation or 4.0), 2), shadow="float", z=3 + i, layered=True))
        x += step
    return sb.finish(0, height=H)


@module("masked_trio")
def masked_trio(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Three photographs in contrasting masks, placed off-grid."""
    ad = k.ad
    W = k.W
    ids = [i for i in _ids(sp) if k.may_crop(i)][:3]
    if len(ids) < 3:
        return trio(k, sp, p)
    bg = p.get("bg") or k.surface()
    H = k.px(p.get("height", 960))
    sb = k.section(sp, bg, "masked_trio")
    m = k.px(ad.margin)
    d = W * 0.27
    sb.add(k.place(ids[0], m, k.px(110), d, d, clip="circle", z=2))
    aw = W * 0.3
    sb.add(k.place(ids[1], W / 2 - aw / 2, H - k.px(90) - aw * 1.32, aw, aw * 1.32, clip="arch", z=2))
    rw = W * 0.3
    sb.add(k.place(ids[2], W - m - rw, k.px(170), rw, rw * 0.8, clip="rounded", radius=k.px(28), z=2))
    for b in sb.blocks:
        b.meta["layered"] = True
        if b.asset_id and b.fit != "cover":
            b.clip = None
    return sb.finish(0, height=H)


# ------------------------------------------------------------- text + image
@module("split_feature")
def split_feature(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Image on one side, the section's own words on the other."""
    ad = k.ad
    W = k.W
    ids = _ids(sp)
    bg = p.get("bg") or k.surface()
    sb = k.section(sp, bg, "split_feature")
    ink = k.ink(bg)
    m = k.px(max(80, ad.margin))
    vpad = k.px(ad.vpad * 0.8)
    img_w = W * 0.56
    flip = p.get("flip", k.rng.random() < 0.5)
    ix = W - img_w if flip else 0.0
    H = k.px(p.get("height", 900))
    if ids:
        aid = ids[0]
        if k.may_crop(aid):
            sb.add(k.place(aid, ix, 0, img_w, H, z=1))
        else:
            sb.add(k.natural(aid, ix + k.px(60), vpad, img_w - k.px(120), H - 2 * vpad, shadow=ad.shadow if ad.shadow != "hard" else None))
    tx = m if flip else img_w + m * 0.8
    tw = (W - img_w) - m * 1.8
    y = vpad
    lab = k.label(sp.eyebrow, tx, y, tw, k.soft(bg), editable="eyebrow") if sp.eyebrow else None
    if lab is not None:
        sb.add(lab)
        y = lab.bottom + k.px(24)
    title = k.display(sp.title, tx, y, tw, ink, 3, 30, 60, role="title", editable="title")
    if title is not None:
        sb.add(title)
        y = title.bottom + k.px(22)
    sub = k.body(sp.subtitle, tx, y, tw, ink, 20, editable="subtitle", weight=500) if sp.subtitle else None
    if sub is not None:
        sb.add(sub)
        y = sub.bottom + k.px(18)
    body = k.body(sp.body, tx, y, tw, ink, 17) if sp.body else None
    if body is not None:
        sb.add(body)
        y = body.bottom
    for aid in ids[1:3]:
        y += k.px(28)
        b = k.natural(aid, tx, y, tw, k.px(260), ax=0.0, ay=0.0)
        if b is not None:
            sb.add(b)
            y = b.bottom
    return sb.finish(vpad, min_height=H)


# ------------------------------------------------------------------ story
@module("letterbox")
def letterbox(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """A cinematic 2.35:1 frame with a quiet caption line beneath."""
    ad = k.ad
    W = k.W
    aid = _ids(sp)[0]
    bg = p.get("bg") or ad.dark
    sb = k.section(sp, bg, "letterbox")
    H = k.cover_height(aid, W, W / 2.6, W / 1.9, W / 2.35)
    if H is None:
        return fullbleed(k, sp, p)
    sb.add(k.place(aid, 0, 0, W, H, z=1))
    m = k.px(ad.margin)
    cap = k.label(sp.title, m, H + k.px(30), W / 2 - m, k.soft(bg, 0.25), editable="title")
    num = k.label(str(p.get("index", "")).zfill(2) if p.get("index") else "", W / 2 + k.px(20), H + k.px(30), W / 2 - m - k.px(20), k.soft(bg, 0.25), align="right")
    sb.add(cap)
    sb.add(num)
    return sb.finish(0, height=round(H + k.px(84), 2))


@module("filmstrip")
def filmstrip(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Three frames in sequence, numbered like stills from a film."""
    ad = k.ad
    W = k.W
    ids = [i for i in _ids(sp) if k.may_crop(i)][:3]
    if len(ids) < 3:
        return trio(k, sp, p)
    from behance_studio.layout.fitting import can_cover

    aspect = next((r for r in (16 / 9, 3 / 2, 4 / 3, 1.0) if all(can_cover(k.asset(i), r) for i in ids)), None)
    if aspect is None:
        return trio(k, sp, p)
    bg = p.get("bg") or ad.dark
    sb = k.section(sp, bg, "filmstrip")
    m = k.px(max(72, ad.margin * 0.6))
    g = k.px(18)
    top = k.px(ad.vpad * 0.6)
    cw = (W - 2 * m - 2 * g) / 3
    ch = cw / aspect
    for i, aid in enumerate(ids):
        x = m + i * (cw + g)
        sb.add(k.place(aid, x, top, cw, ch, z=1))
        sb.add(k.label(f"{i + 1:02d}", x, top + ch + k.px(18), cw, k.soft(bg, 0.25)))
    return sb.finish(k.px(ad.vpad * 0.6), height=round(top + ch + k.px(18 + 40) + k.px(ad.vpad * 0.5), 2))


@module("chapter_spread")
def chapter_spread(k: Kit, sp: SectionPlan, p: dict) -> Section:
    """Chapter opening: numeral and title on a colour field beside an image
    (or the logo on its own ground)."""
    ad = k.ad
    W = k.W
    ids = _ids(sp)
    H = k.px(p.get("height", 860))
    field_bg = p.get("bg") or k.surface(options=[ad.primary, ad.secondary, ad.dark])
    sb = k.section(sp, field_bg, "chapter_spread")
    flip = p.get("flip", (int(p.get("number", 1)) % 2) == 0)
    half = W * 0.5
    fx = half if flip else 0.0
    ix = 0.0 if flip else half
    ink = k.ink(field_bg)
    m = k.px(max(72, ad.margin * 0.7))
    number = str(p.get("number", 1)).zfill(2)
    num = k.c.text(number, fx + m - k.px(6), m, half - 2 * m, k.style("numeral", k.px(220), ink, line_height=0.86, stroke=ink, weight=ad.display_weight), "numeral")
    if num is not None:
        num.decorative = True
        sb.add(num)
    title = k.display(sp.title, fx + m, 0, half - 2 * m, ink, 2, 40, 84, editable="title")
    if title is not None:
        title.y = round(H - m - title.h, 2)
        sb.add(title)
        sb.add(k.label(f"{k.t('chapter')} {number}", fx + m, title.y - k.px(40), half - 2 * m, k.soft(field_bg)))
    if ids:
        aid = ids[0]
        a = k.asset(aid)
        if k.may_crop(aid):
            placed = k.place(aid, ix, 0, half, H, z=1)
            if placed is not None and placed.fit == "cover":
                sb.add(placed)
                return sb.finish(0, height=H)
        own = (a.analysis or {}).get("background")
        ground = own if own and own != "transparent" else k.logo_surface(aid, [ad.light, ad.primary, ad.dark])
        sb.add(k.shape(ix, 0, half, H, ground, z=0))
        if asset_kind := a.effective_kind:
            if asset_kind in ("logo", "logo_variant", "monogram"):
                sb.add(k.logo(aid, ix + half / 2, H / 2, half * 0.66, H * 0.36, ground))
            else:
                sb.add(k.natural(aid, ix + half * 0.12, H * 0.12, half * 0.76, H * 0.76, shadow="soft"))
    return sb.finish(0, height=H)
