"""Long Behance canvas → pages of one size (Canva designs and PowerPoint
files have a single page size).

Pages are consecutive strips of the continuous presentation, so pages
downloaded from Canva and uploaded to Behance one after another rebuild the
original without seams.

* A cut never goes through text, rotated or masked elements: it moves up to
  just above them and the rest of that page continues the background
  ("filler"), so nothing is cut.
* Backgrounds and pictures that cross a cut are split into two pieces that
  meet exactly (pictures keep their crop, so each piece is still a picture).
* The page height is chosen automatically to need the fewest splits and
  fillers, or set by the user.
"""

from __future__ import annotations

import copy
import dataclasses
from dataclasses import dataclass

from behance_studio.canva.build import clip_vertical
from behance_studio.canva.model import Element, PagedScene, Scene, ScenePage, Solid

AUTO_RANGE = (1000, 2600)  # px; well inside Canva's 8000 px per side
MAX_PAGES = 100  # Canva's documented PowerPoint import limit


@dataclass
class _Plan:
    height: int
    ranges: list[tuple[float, float]]
    forced: int
    fillers: float
    split_images: int
    cost: float


def _blockers(scene: Scene) -> list[tuple[float, float]]:
    out = []
    for e in scene.elements:
        if e.role == "background" or e.splittable:
            continue
        _x0, y0, _x1, y1 = e.bounds()
        out.append((y0, y1))
    return sorted(out)


def _plan(scene: Scene, height: int, blockers: list[tuple[float, float]], images: list[tuple[float, float]]) -> _Plan:
    T = scene.height
    y = 0.0
    ranges: list[tuple[float, float]] = []
    forced = 0
    fillers = 0.0
    while T - y > height + 0.5:
        cut = y + height
        while True:
            crossing = [top for top, bottom in blockers if top < cut - 0.5 and bottom > cut + 0.5]
            if not crossing or any(top <= y + 1.0 for top in crossing):
                break  # nothing in the way, or an element taller than the page
            cut = min(crossing)  # just above the element
        if cut - y < height * 0.4:  # would leave most of the page empty: cut through instead
            cut = y + height
        forced += sum(1 for top, bottom in blockers if top < cut - 0.5 and bottom > cut + 0.5)
        fillers += (y + height) - cut
        ranges.append((y, cut))
        y = cut
        if len(ranges) > MAX_PAGES * 2:
            break
    ranges.append((y, T))
    cuts = [b for _a, b in ranges[:-1]]
    split_images = sum(1 for c in cuts for top, bottom in images if top < c - 0.5 and bottom > c + 0.5)
    last_empty = (height - (T - y)) / height
    cost = (30.0 * fillers / height + 2.0 * sum(1 for a, b in ranges[:-1] if b - a < height - 0.5) + 50.0 * forced
            + 2.0 * split_images + 20.0 * last_empty + 0.3 * len(ranges) + abs(height - 1800) / 1800
            + (1000.0 if len(ranges) > MAX_PAGES else 0.0))
    return _Plan(height, ranges, forced, fillers, split_images, cost)


def choose_height(scene: Scene, page_height: int | None = None) -> _Plan:
    blockers = _blockers(scene)
    images = [(e.y, e.bottom) for e in scene.elements if e.kind == "image" and e.role != "background" and e.splittable]
    if page_height:
        return _plan(scene, int(page_height), blockers, images)
    if scene.height <= AUTO_RANGE[1]:  # short presentation: one page
        return _plan(scene, int(round(scene.height)), blockers, images)
    best = None
    for h in range(AUTO_RANGE[0], AUTO_RANGE[1] + 1, 10):
        p = _plan(scene, h, blockers, images)
        if best is None or p.cost < best.cost:
            best = p
    assert best is not None
    return best


def _background_at(scene: Scene, y: float) -> str:
    for s in scene.sections:
        if s.y <= y < s.y + s.height:
            return s.background
    return scene.sections[-1].background if scene.sections else "#FFFFFF"


def paginate(scene: Scene, page_height: int | None = None) -> PagedScene:
    plan = choose_height(scene, page_height)
    H = plan.height
    pages: list[ScenePage] = []
    split_images: set[int] = set()
    split_shapes: set[int] = set()
    notes: list[str] = []
    for index, (y0, y1) in enumerate(plan.ranges):
        els: list[Element] = []
        content = y1 - y0
        if content < H - 0.5:
            filler_color = _background_at(scene, y1 - 0.5)  # the background the cut runs through
            els.append(Element("rect", 0.0, content, float(scene.width), H - content, name=f"Page {index + 1} · background continued",
                               fill=Solid(filler_color), role="filler"))
        sections = []
        for e in scene.elements:
            bx0, by0, bx1, by1 = e.bounds()
            if by1 <= y0 + 0.01 or by0 >= y1 - 0.01 or e.h <= 0.01:
                continue
            if e.section not in sections:
                sections.append(e.section)
            c = copy.deepcopy(e)
            if by0 < y0 - 0.5 or by1 > y1 + 0.5:
                if e.splittable:
                    clip_vertical(c, max(c.y, y0), min(c.bottom, y1))
                    if c.h <= 0.01:
                        continue
                    if e.role != "background":
                        (split_images if e.kind == "image" else split_shapes).add(id(e))
                else:
                    c.notes.append("continues across the page edge (shown on both pages)")
            c.y -= y0
            els.append(c)
        pages.append(ScenePage(index, y0, y1, els, max(0.0, H - content), sections))
    filled = [p for p in pages[:-1] if p.filler > 0.5]
    if filled:
        notes.append(f"{len(filled)} page(s) end with extra background (up to {max(p.filler for p in filled):.0f} px) so that no text or masked "
                     "element is cut")
    if pages and pages[-1].filler > 0.5:
        notes.append(f"the last page ends with {pages[-1].filler:.0f} px of background (all pages have one size)")
    if plan.forced:
        notes.append(f"{plan.forced} element(s) taller than a page continue across a page edge")
    return PagedScene(scene, H, pages, len(split_images), len(split_shapes), notes)


def paginate_many(scenes: list[Scene], page_height: int | None = None) -> list[PagedScene]:
    """Several presentations with one common page size (one combined design)."""
    if page_height or len(scenes) < 2:
        return [paginate(s, page_height) for s in scenes]
    prepared = [(s, _blockers(s), [(e.y, e.bottom) for e in s.elements if e.kind == "image" and e.role != "background" and e.splittable])
                for s in scenes]
    best_h, best_cost = AUTO_RANGE[0], float("inf")
    for h in range(AUTO_RANGE[0], AUTO_RANGE[1] + 1, 10):
        cost = sum(_plan(s, h, b, i).cost for s, b, i in prepared)
        if cost < best_cost:
            best_h, best_cost = h, cost
    return [paginate(s, best_h) for s in scenes]


def combine(paged: list[PagedScene], title: str, labels: list[str] | None = None) -> PagedScene:
    """Pages of several presentations in one file (same width and page height)."""
    first = paged[0]
    pages, sections, fonts, notes = [], [], {}, []
    offset = 0.0
    index_base = 0
    for n, p in enumerate(paged):
        label = labels[n] if labels and n < len(labels) else ""
        for page in p.pages:
            pages.append(ScenePage(len(pages), page.y0 + offset, page.y1 + offset, page.elements, page.filler,
                                   [i + index_base for i in page.sections], label))
        for s in p.scene.sections:
            sections.append(dataclasses.replace(s, index=s.index + index_base))
        index_base += len(p.scene.sections)
        for k, v in p.scene.fonts.items():
            fonts.setdefault(k, set()).update(v)
        notes += p.notes
        offset += p.scene.height
    scene = Scene(first.scene.width, offset, title, [], sections, fonts, [])
    return PagedScene(scene, first.page_height, pages, sum(p.split_images for p in paged), sum(p.split_shapes for p in paged),
                      list(dict.fromkeys(notes)))
