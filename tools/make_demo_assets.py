"""Generate a synthetic "Butter & Bean" brand-identity asset folder.

The fictional coffee-shop identity is used for demonstrations and automated
tests, so that nobody's real artwork is needed. Files are deliberately named
and organised the way a designer's delivery folder typically is.

Usage::

    python tools/make_demo_assets.py "<output folder>" [--no-video]
"""

from __future__ import annotations

import math
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
try:  # the app's bundled fonts (works in the repository and in the packaged build)
    from behance_studio.core.paths import FONTS_DIR as FONTS
except ImportError:
    FONTS = ROOT / "src" / "behance_studio" / "resources" / "fonts"

ESPRESSO = (46, 31, 23)
BUTTER = (244, 201, 93)
CREAM = (247, 239, 227)
TERRACOTTA = (217, 102, 63)
LATTE = (200, 162, 124)
SAGE = (141, 164, 126)

BRIEF = """Project: Butter & Bean
Type: Specialty coffee shop brand identity
Language: English

About: Butter & Bean is a neighbourhood specialty coffee shop and bakery. The identity brings together carefully sourced coffee and pastries baked fresh every morning.

Brand personality: warm, welcoming, contemporary, approachable, slightly playful and premium without feeling overly luxurious.
Audience: young professionals, students and families from the neighbourhood.

Brand messages:
- "Specialty Coffee. Freshly Baked."
- "Your New Favourite Corner."

Colours: Espresso #2E1F17, Butter #F4C95D, Cream #F7EFE3, Terracotta #D9663F
Typography: Fraunces for expressive editorial headings, Manrope for body copy and supporting information.
Mood: warm, friendly editorial compositions with lifestyle imagery.
"""


def font(name: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    path = FONTS / name
    f = ImageFont.truetype(str(path), size)
    try:
        axes = f.get_variation_axes()
    except Exception:  # noqa: BLE001 - static font
        return f
    values = []
    for axis in axes:
        tag = axis["name"] if isinstance(axis["name"], str) else axis["name"].decode()
        tag = tag.lower()
        if "weight" in tag and weight:
            values.append(max(axis["minimum"], min(axis["maximum"], weight)))
        elif "optical" in tag:
            values.append(max(axis["minimum"], min(axis["maximum"], size)))
        elif "wonky" in tag:
            values.append(0)
        elif "soft" in tag:
            values.append(50)
        else:
            values.append(axis["default"])
    f.set_variation_by_axes(values)
    return f


def fraunces(size: int, weight: int = 600) -> ImageFont.FreeTypeFont:
    return font("Fraunces-VF.ttf", size, weight)


def manrope(size: int, weight: int = 500) -> ImageFont.FreeTypeFont:
    return font("Manrope-VF.ttf", size, weight)


def centered_text(draw: ImageDraw.ImageDraw, xy, text, fnt, fill, anchor="mm", spacing=0):
    draw.text(xy, text, font=fnt, fill=fill, anchor=anchor, spacing=spacing)


def add_noise(img: Image.Image, amount: float = 9.0, seed: int = 0) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    grain = rng.normal(0, amount, arr.shape[:2])[..., None]
    arr = np.clip(arr + grain, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def vignette(img: Image.Image, strength: float = 0.45) -> Image.Image:
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    mask = np.clip(1 - strength * (d ** 2) / 2, 0.35, 1)[..., None]
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) * mask
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


def gradient(size, top, bottom) -> Image.Image:
    w, h = size
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    arr = np.array(top, dtype=np.float32) * (1 - t) + np.array(bottom, dtype=np.float32) * t
    return Image.fromarray(np.repeat(arr, w, axis=1).astype(np.uint8), "RGB")


def wood(size, base=(120, 78, 50), seed=1) -> Image.Image:
    w, h = size
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    phase = rng.uniform(0, 6.28)
    grain = np.sin(yy / 9.0 + np.sin(xx / 210.0 + phase) * 3.2) * 0.5 + 0.5
    grain2 = np.sin(yy / 2.7 + xx / 400.0) * 0.5 + 0.5
    shade = 0.78 + 0.16 * grain + 0.06 * grain2
    arr = np.array(base, dtype=np.float32)[None, None, :] * shade[..., None]
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")


def bean_symbol(draw: ImageDraw.ImageDraw, cx, cy, size, fill, line):
    w, h = size * 0.62, size
    draw.ellipse([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], fill=fill)
    # centre crease
    pts = []
    for i in range(40):
        t = i / 39
        y = cy - h * 0.4 + t * h * 0.8
        x = cx + math.sin(t * math.pi * 2) * w * 0.12
        pts.append((x, y))
    draw.line(pts, fill=line, width=max(2, int(size * 0.06)), joint="curve")


# ------------------------------------------------------------------ brand
def logo_primary(color=ESPRESSO, accent=BUTTER) -> Image.Image:
    img = Image.new("RGBA", (2400, 760), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bean_symbol(d, 300, 380, 420, color + (255,), accent + (255,))
    d.text((560, 380), "Butter & Bean", font=fraunces(250, 640), fill=color + (255,), anchor="lm")
    d.text((572, 600), "SPECIALTY COFFEE · BAKERY", font=manrope(62, 600), fill=color + (255,), anchor="lm")
    return img.crop(img.getbbox())


def logo_stacked(color=ESPRESSO, accent=TERRACOTTA) -> Image.Image:
    img = Image.new("RGBA", (1600, 1500), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bean_symbol(d, 800, 360, 480, color + (255,), accent + (255,))
    d.text((800, 820), "Butter", font=fraunces(260, 640), fill=color + (255,), anchor="mm")
    d.text((800, 1080), "& Bean", font=fraunces(260, 640), fill=color + (255,), anchor="mm")
    d.text((800, 1320), "EST. NEIGHBOURHOOD", font=manrope(54, 600), fill=color + (255,), anchor="mm")
    return img.crop(img.getbbox())


def monogram(color=ESPRESSO, ring=TERRACOTTA) -> Image.Image:
    img = Image.new("RGBA", (1200, 1200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([60, 60, 1140, 1140], outline=ring + (255,), width=34)
    d.text((600, 610), "B&B", font=fraunces(380, 700), fill=color + (255,), anchor="mm")
    return img


def logo_on_dark() -> Image.Image:
    img = Image.new("RGB", (2400, 1600), ESPRESSO)
    logo = logo_primary(CREAM, BUTTER)
    logo.thumbnail((1500, 600), Image.Resampling.LANCZOS)
    img.paste(logo, ((2400 - logo.width) // 2, (1600 - logo.height) // 2), logo)
    return img


def palette_sheet() -> Image.Image:
    w, h = 2400, 1350
    img = Image.new("RGB", (w, h), CREAM)
    d = ImageDraw.Draw(img)
    swatches = [("Espresso", ESPRESSO), ("Butter", BUTTER), ("Terracotta", TERRACOTTA), ("Latte", LATTE), ("Cream", (236, 224, 206))]
    sw = (w - 200) / len(swatches)
    for i, (name, col) in enumerate(swatches):
        x0 = 100 + i * sw
        d.rectangle([x0, 120, x0 + sw - 30, 1050], fill=col)
        text_col = CREAM if sum(col) < 380 else ESPRESSO
        d.text((x0 + 40, 960), name, font=fraunces(64, 560), fill=text_col, anchor="ls")
        d.text((x0 + 40, 1010), "#%02X%02X%02X" % col, font=manrope(34, 600), fill=text_col, anchor="ls")
    d.text((100, 1180), "Colour palette — Butter & Bean", font=manrope(40, 600), fill=ESPRESSO, anchor="ls")
    return img


def typography_sheet() -> Image.Image:
    w, h = 2400, 1500
    img = Image.new("RGB", (w, h), (250, 246, 239))
    d = ImageDraw.Draw(img)
    d.text((120, 120), "Aa", font=fraunces(620, 600), fill=ESPRESSO, anchor="lt")
    d.text((1180, 170), "Fraunces", font=fraunces(150, 600), fill=ESPRESSO, anchor="lt")
    d.text((1180, 370), "Display / Headlines", font=manrope(48, 600), fill=TERRACOTTA, anchor="lt")
    d.text((1180, 470), "ABCDEFGHIJKLMNOPQRSTUVWXYZ\nabcdefghijklmnopqrstuvwxyz\n0123456789 &!?", font=fraunces(52, 400), fill=ESPRESSO, anchor="la", spacing=18)
    d.line([(120, 920), (w - 120, 920)], fill=LATTE, width=3)
    d.text((120, 990), "Manrope", font=manrope(130, 700), fill=ESPRESSO, anchor="lt")
    d.text((120, 1170), "Body copy and supporting information. Clear, friendly and contemporary.", font=manrope(54, 500), fill=ESPRESSO, anchor="lt")
    d.text((120, 1270), "Regular · Medium · SemiBold · Bold", font=manrope(44, 500), fill=TERRACOTTA, anchor="lt")
    return img


def pattern_sheet() -> Image.Image:
    w, h = 2000, 2000
    img = Image.new("RGB", (w, h), BUTTER)
    d = ImageDraw.Draw(img)
    step = 250
    for row, y in enumerate(range(-50, h + 100, step)):
        for col, x in enumerate(range(-50, w + 100, step)):
            ox = x + (step / 2 if row % 2 else 0)
            if (row + col) % 3 == 0:
                d.ellipse([ox - 50, y - 50, ox + 50, y + 50], outline=TERRACOTTA, width=14)
            else:
                bean_symbol(d, ox, y, 120, ESPRESSO, BUTTER)
    return img


# ------------------------------------------------------------- "photos"
def cup_topdown(d: ImageDraw.ImageDraw, cx, cy, r):
    d.ellipse([cx - r * 1.45, cy - r * 1.45, cx + r * 1.45, cy + r * 1.45], fill=(238, 233, 226))
    d.ellipse([cx - r * 1.05, cy - r * 1.05, cx + r * 1.05, cy + r * 1.05], fill=(250, 248, 244))
    d.ellipse([cx - r * 0.88, cy - r * 0.88, cx + r * 0.88, cy + r * 0.88], fill=(120, 72, 40))
    d.ellipse([cx - r * 0.78, cy - r * 0.78, cx + r * 0.78, cy + r * 0.78], fill=(160, 105, 62))
    # latte-art heart
    d.ellipse([cx - r * 0.42, cy - r * 0.38, cx - r * 0.02, cy + r * 0.05], fill=(238, 220, 196))
    d.ellipse([cx + r * 0.02, cy - r * 0.38, cx + r * 0.42, cy + r * 0.05], fill=(238, 220, 196))
    d.polygon([(cx - r * 0.40, cy - r * 0.08), (cx + r * 0.40, cy - r * 0.08), (cx, cy + r * 0.42)], fill=(238, 220, 196))
    # handle
    d.rounded_rectangle([cx + r * 1.0, cy - r * 0.16, cx + r * 1.42, cy + r * 0.16], radius=r * 0.15, fill=(250, 248, 244))


def croissant(d: ImageDraw.ImageDraw, cx, cy, s, angle=0.0):
    for i in range(7):
        t = (i - 3) / 3
        x = cx + math.cos(angle) * t * s * 0.9 - math.sin(angle) * (abs(t) ** 2) * s * 0.35
        y = cy + math.sin(angle) * t * s * 0.9 + math.cos(angle) * (abs(t) ** 2) * s * 0.35
        rad = s * (0.42 - 0.22 * abs(t))
        shade = int(30 * abs(t))
        d.ellipse([x - rad, y - rad * 0.8, x + rad, y + rad * 0.8], fill=(212 - shade, 140 - shade, 60 - shade // 2))
        d.ellipse([x - rad * 0.6, y - rad * 0.55, x + rad * 0.3, y - rad * 0.1], fill=(232, 172, 92))


def photo_topdown(seed=11) -> Image.Image:
    w, h = 2600, 1734
    img = wood((w, h), base=(132, 88, 58), seed=seed)
    shadow = Image.new("L", (w, h), 0)
    sd = ImageDraw.Draw(shadow)
    sd.ellipse([1180, 520, 2120, 1460], fill=150)
    sd.ellipse([340, 760, 1100, 1320], fill=120)
    shadow = shadow.filter(ImageFilter.GaussianBlur(60))
    dark = Image.new("RGB", (w, h), (40, 24, 14))
    img = Image.composite(dark, img, shadow.point(lambda v: v * 0.6))
    d = ImageDraw.Draw(img)
    cup_topdown(d, 1580, 900, 300)
    croissant(d, 720, 1000, 330, angle=-0.4)
    d.rounded_rectangle([140, 160, 860, 520], radius=30, fill=CREAM)
    logo = logo_primary(ESPRESSO, TERRACOTTA)
    logo.thumbnail((600, 220))
    img.paste(logo, (500 - logo.width // 2, 340 - logo.height // 2), logo)
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    return vignette(add_noise(img, 7, seed), 0.35)


def photo_interior(seed=21) -> Image.Image:
    w, h = 2800, 1866
    img = gradient((w, h), (236, 214, 186), (190, 150, 112))
    d = ImageDraw.Draw(img)
    # back shelves
    for i in range(3):
        y = 330 + i * 230
        d.rectangle([180, y, 1300, y + 26], fill=(110, 72, 46))
        for j in range(9):
            x = 220 + j * 118
            col = [BUTTER, TERRACOTTA, CREAM, SAGE, LATTE][(i + j) % 5]
            d.rounded_rectangle([x, y - 120, x + 80, y], radius=10, fill=col)
    # window with light
    d.rectangle([1650, 200, 2560, 1050], fill=(253, 246, 228))
    d.rectangle([2090, 200, 2120, 1050], fill=(150, 112, 80))
    d.rectangle([1650, 610, 2560, 640], fill=(150, 112, 80))
    # pendant lamps
    for x in (700, 1450, 2200):
        d.line([(x, 0), (x, 300)], fill=(40, 28, 20), width=6)
        d.pieslice([x - 110, 240, x + 110, 420], 180, 360, fill=ESPRESSO)
        d.ellipse([x - 40, 320, x + 40, 380], fill=(255, 236, 170))
    # counter
    counter = wood((w, 760), base=(126, 82, 52), seed=seed)
    img.paste(counter, (0, h - 760))
    d.rectangle([0, h - 790, w, h - 760], fill=(70, 46, 30))
    # cups on counter
    for x in (520, 900, 1900):
        d.rounded_rectangle([x, h - 960, x + 150, h - 790], radius=18, fill=(250, 246, 238))
        d.rectangle([x, h - 900, x + 150, h - 850], fill=BUTTER)
    glow = Image.new("L", (w, h), 0)
    gd = ImageDraw.Draw(glow)
    for x in (700, 1450, 2200):
        gd.ellipse([x - 380, 100, x + 380, 760], fill=90)
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.composite(Image.new("RGB", (w, h), (255, 226, 160)), img, glow)
    img = img.filter(ImageFilter.GaussianBlur(2.2))
    return vignette(add_noise(img, 8, seed), 0.5)


def photo_croissants(seed=31) -> Image.Image:
    w, h = 1800, 2250
    img = Image.new("RGB", (w, h), TERRACOTTA)
    rng = random.Random(seed)
    d = ImageDraw.Draw(img)
    for i in range(0, h, 90):
        d.rectangle([0, i, w, i + 18], fill=(200, 88, 54))
    d.ellipse([200, 420, 1600, 1820], fill=(240, 236, 230))
    d.ellipse([290, 510, 1510, 1730], fill=(250, 248, 244))
    for k in range(3):
        croissant(d, 620 + k * 260 + rng.randint(-40, 40), 900 + k * 230, 300, angle=rng.uniform(-0.6, 0.6))
    img = img.filter(ImageFilter.GaussianBlur(1.6))
    return vignette(add_noise(img, 8, seed), 0.4)


def photo_beans(seed=41) -> Image.Image:
    w, h = 2400, 1600
    img = Image.new("RGB", (w, h), (66, 40, 26))
    d = ImageDraw.Draw(img)
    rng = random.Random(seed)
    for _ in range(900):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        s = rng.uniform(46, 90)
        tone = rng.randint(-18, 18)
        bean_symbol(d, x, y, s, (92 + tone, 56 + tone, 34 + tone), (46 + tone, 28, 18))
    img = img.filter(ImageFilter.GaussianBlur(1.5))
    blurmask = gradient((w, h), (255, 255, 255), (0, 0, 0)).convert("L")
    img = Image.composite(img.filter(ImageFilter.GaussianBlur(9)), img, blurmask.point(lambda v: int(v * 0.8)))
    return vignette(add_noise(img, 9, seed), 0.55)


def photo_window(seed=51) -> Image.Image:
    w, h = 1800, 2400
    img = gradient((w, h), (248, 240, 222), (214, 186, 150))
    d = ImageDraw.Draw(img)
    d.rectangle([180, 120, 1620, 1300], fill=(255, 252, 240))
    d.rectangle([880, 120, 920, 1300], fill=(160, 120, 86))
    for i in range(6):
        d.ellipse([260 + i * 220, 1000 - (i % 2) * 60, 420 + i * 220, 1160], fill=(170, 196, 150))
    table = wood((w, 1000), base=(150, 104, 70), seed=seed)
    img.paste(table, (0, h - 1000))
    d.rounded_rectangle([620, h - 1230, 980, h - 960], radius=40, fill=(252, 250, 246))
    d.rectangle([620, h - 1140, 980, h - 1080], fill=TERRACOTTA)
    d.ellipse([560, h - 1000, 1040, h - 920], fill=(236, 230, 222))
    img = img.filter(ImageFilter.GaussianBlur(2.5))
    return vignette(add_noise(img, 7, seed), 0.35)


# ------------------------------------------------------------- packaging
def studio_bg(size, seed=0) -> Image.Image:
    w, h = size
    img = gradient(size, (236, 230, 220), (214, 205, 192))
    return add_noise(img, 3, seed)


def soft_shadow(img: Image.Image, box, blur=40, opacity=110):
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse(box, fill=opacity)
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    return Image.composite(Image.new("RGB", (w, h), (60, 44, 30)), img, mask)


def packaging_bag(seed=61) -> Image.Image:
    w, h = 2000, 2000
    img = soft_shadow(studio_bg((w, h), seed), [560, 1620, 1440, 1780])
    d = ImageDraw.Draw(img)
    d.polygon([(640, 420), (1360, 420), (1400, 1700), (600, 1700)], fill=ESPRESSO)
    d.rectangle([640, 330, 1360, 440], fill=(60, 42, 32))
    for i in range(9):
        d.line([(660 + i * 78, 340), (660 + i * 78, 430)], fill=(80, 58, 44), width=6)
    d.rounded_rectangle([730, 820, 1270, 1420], radius=24, fill=CREAM)
    logo = logo_stacked(ESPRESSO, TERRACOTTA)
    logo.thumbnail((380, 380))
    img.paste(logo, (1000 - logo.width // 2, 1040 - logo.height // 2), logo)
    d.text((1000, 1330), "HOUSE BLEND · 250 G", font=manrope(34, 700), fill=ESPRESSO, anchor="mm")
    return add_noise(img.filter(ImageFilter.GaussianBlur(0.8)), 4, seed)


def packaging_cup(seed=71) -> Image.Image:
    w, h = 2200, 1650
    img = soft_shadow(studio_bg((w, h), seed), [600, 1380, 1600, 1520])
    d = ImageDraw.Draw(img)
    for i, (x, col) in enumerate(((760, BUTTER), (1300, CREAM))):
        d.polygon([(x - 230, 380), (x + 230, 380), (x + 180, 1420), (x - 180, 1420)], fill=col)
        d.rounded_rectangle([x - 250, 330, x + 250, 400], radius=18, fill=(252, 250, 246))
        mono = monogram(ESPRESSO, TERRACOTTA)
        mono.thumbnail((260, 260))
        img.paste(mono, (x - mono.width // 2, 780 - mono.height // 2), mono)
    return add_noise(img.filter(ImageFilter.GaussianBlur(0.8)), 4, seed)


def packaging_box(seed=81) -> Image.Image:
    w, h = 2200, 1650
    img = soft_shadow(studio_bg((w, h), seed), [500, 1240, 1700, 1440])
    d = ImageDraw.Draw(img)
    d.polygon([(600, 700), (1100, 900), (1100, 1380), (600, 1180)], fill=(214, 92, 56))
    d.polygon([(1100, 900), (1640, 700), (1640, 1180), (1100, 1380)], fill=TERRACOTTA)
    d.polygon([(600, 700), (1130, 520), (1640, 700), (1100, 900)], fill=(236, 128, 90))
    logo = logo_primary(CREAM, BUTTER)
    logo.thumbnail((440, 160))
    logo = logo.rotate(-20, expand=True, resample=Image.Resampling.BICUBIC)
    img.paste(logo, (1370 - logo.width // 2, 1010 - logo.height // 2), logo)
    return add_noise(img.filter(ImageFilter.GaussianBlur(0.8)), 4, seed)


# ---------------------------------------------------------------- campaign
def poster(headline: str, bg, fg, photo: Image.Image, seed=0) -> Image.Image:
    w, h = 1414, 2000
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    d.multiline_text((90, 110), headline, font=fraunces(170, 640), fill=fg, spacing=6)
    ph = photo.copy()
    ph = ph.resize((1234, int(1234 * ph.height / ph.width)))
    ph = ph.crop((0, 0, 1234, min(ph.height, 900)))
    img.paste(ph, (90, 820))
    logo = logo_primary(fg, BUTTER if bg != BUTTER else TERRACOTTA)
    logo.thumbnail((620, 200))
    img.paste(logo, (90, 1830 - logo.height // 2), logo)
    d.text((w - 90, 1830), "Open daily · 7am", font=manrope(40, 600), fill=fg, anchor="rm")
    return img


def billboard(photo: Image.Image) -> Image.Image:
    w, h = 3000, 1000
    img = Image.new("RGB", (w, h), BUTTER)
    ph = photo.copy().resize((1500, int(1500 * photo.height / photo.width)))
    top = max(0, (ph.height - h) // 2)
    img.paste(ph.crop((0, top, 1500, top + h)), (0, 0))
    d = ImageDraw.Draw(img)
    d.multiline_text((1620, 160), "Your New\nFavourite Corner.", font=fraunces(170, 650), fill=ESPRESSO, spacing=10)
    logo = logo_primary(ESPRESSO, TERRACOTTA)
    logo.thumbnail((600, 190))
    img.paste(logo, (1620, 780), logo)
    return img


def social_post(i: int, photo: Image.Image, size=(1080, 1350)) -> Image.Image:
    w, h = size
    bgs = [CREAM, BUTTER, ESPRESSO, TERRACOTTA]
    bg = bgs[i % len(bgs)]
    fg = CREAM if bg in (ESPRESSO, TERRACOTTA) else ESPRESSO
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    texts = ["Freshly\nbaked.", "Morning\nritual.", "Your new\nfavourite\ncorner.", "Specialty\ncoffee."]
    if i % 2 == 0:
        ph = photo.copy()
        ph = ph.resize((w - 120, int((w - 120) * ph.height / ph.width)))
        ph = ph.crop((0, 0, w - 120, min(ph.height, int(h * 0.52))))
        img.paste(ph, (60, h - ph.height - 60))
        d.multiline_text((60, 70), texts[i % 4], font=fraunces(110, 640), fill=fg, spacing=4)
    else:
        d.multiline_text((70, h // 2), texts[i % 4], font=fraunces(150, 680), fill=fg, anchor="lm", spacing=6)
        mono = monogram(fg, BUTTER if bg != BUTTER else TERRACOTTA)
        mono.thumbnail((160, 160))
        img.paste(mono, (w - 220, 60), mono)
    d.text((60, h - 30), "@butterandbean", font=manrope(30, 600), fill=fg, anchor="ls") if i % 2 else None
    return img


def logo_gif(path: Path) -> None:
    frames = []
    for i in range(16):
        img = Image.new("RGB", (480, 480), CREAM)
        d = ImageDraw.Draw(img)
        t = i / 16
        bean_symbol(d, 240, 210 - math.sin(t * math.pi * 2) * 30, 150, ESPRESSO, BUTTER)
        d.text((240, 380), "Butter & Bean", font=fraunces(52, 640), fill=ESPRESSO, anchor="mm")
        frames.append(img.convert("P", palette=Image.Palette.ADAPTIVE, colors=64))
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)


def teaser_video(path: Path, photo: Image.Image) -> bool:
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return False
    w, h = 1280, 720
    frames_dir = path.parent / ".frames"
    frames_dir.mkdir(exist_ok=True)
    base = photo.copy().resize((w, int(w * photo.height / photo.width))).crop((0, 0, w, h))
    logo = logo_primary(CREAM, BUTTER)
    logo.thumbnail((700, 240))
    n = 48
    for i in range(n):
        t = i / (n - 1)
        frame = Image.blend(base, Image.new("RGB", (w, h), ESPRESSO), min(0.75, t * 1.2))
        alpha = int(255 * max(0.0, min(1.0, (t - 0.3) / 0.4)))
        lg = logo.copy()
        lg.putalpha(lg.getchannel("A").point(lambda v: v * alpha // 255))
        frame.paste(lg, ((w - lg.width) // 2, (h - lg.height) // 2 + int(30 * (1 - t))), lg)
        frame.save(frames_dir / f"f{i:03d}.png")
    proc = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-framerate", "24", "-i", str(frames_dir / "f%03d.png"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)],
        capture_output=True,
    )
    for f in frames_dir.glob("*.png"):
        f.unlink()
    frames_dir.rmdir()
    return proc.returncode == 0


def build_demo_assets(target: Path, include_video: bool = True, include_brief: bool = True) -> Path:
    target = Path(target)
    (target).mkdir(parents=True, exist_ok=True)
    folders = {k: target / k for k in ("01 Logo", "02 Brand Elements", "03 Photography", "04 Packaging", "05 Campaign", "06 Social Media", "07 Motion")}
    for f in folders.values():
        f.mkdir(exist_ok=True)

    logo_primary().save(folders["01 Logo"] / "butter-bean-logo-primary.png")
    logo_stacked().save(folders["01 Logo"] / "butter-bean-logo-alternative-stacked.png")
    monogram().save(folders["01 Logo"] / "butter-bean-monogram.png")
    logo_on_dark().save(folders["01 Logo"] / "logo-negative-on-espresso.jpg", quality=92)
    (folders["01 Logo"] / "monogram.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="400" height="400">'
        '<circle cx="200" cy="200" r="180" fill="none" stroke="#D9663F" stroke-width="12"/>'
        '<ellipse cx="200" cy="200" rx="70" ry="112" fill="#2E1F17"/>'
        '<path d="M200 100 C 225 150, 175 250, 200 300" stroke="#F4C95D" stroke-width="10" fill="none"/>'
        "</svg>",
        encoding="utf-8",
    )

    palette_sheet().save(folders["02 Brand Elements"] / "colour-palette.png")
    typography_sheet().save(folders["02 Brand Elements"] / "typography-specimen.png")
    pattern_sheet().save(folders["02 Brand Elements"] / "brand-pattern.png")

    topdown = photo_topdown()
    interior = photo_interior()
    croissants = photo_croissants()
    topdown.save(folders["03 Photography"] / "DSC_0142.jpg", quality=92)
    interior.save(folders["03 Photography"] / "DSC_0157 shop interior.jpg", quality=92)
    croissants.save(folders["03 Photography"] / "DSC_0163.jpg", quality=92)
    photo_beans().save(folders["03 Photography"] / "DSC_0171.jpg", quality=92)
    photo_window().save(folders["03 Photography"] / "DSC_0188.jpg", quality=92)

    packaging_bag().save(folders["04 Packaging"] / "coffee-bag-mockup.jpg", quality=92)
    packaging_cup().save(folders["04 Packaging"] / "takeaway-cups.jpg", quality=92)
    packaging_box().save(folders["04 Packaging"] / "pastry-box.jpg", quality=92)

    poster("Specialty\nCoffee.\nFreshly\nBaked.", BUTTER, ESPRESSO, topdown).save(folders["05 Campaign"] / "poster-specialty-coffee.jpg", quality=92)
    poster("Your New\nFavourite\nCorner.", TERRACOTTA, CREAM, interior).save(folders["05 Campaign"] / "poster-favourite-corner.jpg", quality=92)
    billboard(croissants).save(folders["05 Campaign"] / "billboard-48-sheet.jpg", quality=92)

    social_post(0, topdown).save(folders["06 Social Media"] / "instagram-post-01.jpg", quality=92)
    social_post(1, interior).save(folders["06 Social Media"] / "instagram-post-02.jpg", quality=92)
    social_post(2, croissants).save(folders["06 Social Media"] / "instagram-post-03.jpg", quality=92)
    social_post(3, topdown, size=(1080, 1080)).save(folders["06 Social Media"] / "instagram-post-04.jpg", quality=92)

    logo_gif(folders["07 Motion"] / "logo-animation.gif")
    if include_video:
        teaser_video(folders["07 Motion"] / "brand-teaser.mp4", interior)
    if include_brief:
        (target / "brief.txt").write_text(BRIEF, encoding="utf-8")
    return target


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    out = build_demo_assets(Path(sys.argv[1]), include_video="--no-video" not in sys.argv)
    print(f"Demo assets written to {out}")
