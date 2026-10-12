"""Developer tool: generate the five 2.0 concepts for a project and render
them to PNG strips and contact sheets for visual review.

    python tools/render_concepts.py <project folder> <out dir> [seed] [concepts…]

Stale asset analysis is refreshed first. Prints each plan (modules and
assets), validator issues and timing.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from behance_studio.assets.analysis import ANALYSIS_VERSION  # noqa: E402
from behance_studio.assets.importer import analyze_assets  # noqa: E402
from behance_studio.brief.directives import build_directives  # noqa: E402
from behance_studio.core.qtsupport import ensure_gui_application  # noqa: E402
from behance_studio.design.direction import build_direction  # noqa: E402
from behance_studio.layout.engine import ProposalSpec, build_plan, compose  # noqa: E402
from behance_studio.layout.validate import validate_presentation  # noqa: E402
from behance_studio.planning.planner import PlanningContext  # noqa: E402
from behance_studio.projects.store import Project  # noqa: E402
from behance_studio.render.browser import BrowserSession  # noqa: E402
from behance_studio.render.project_render import write_html  # noqa: E402


def sheet(png: Path, out: Path, col_h: int = 1700, gap: int = 24) -> None:
    img = Image.open(png).convert("RGB")
    cols = (img.height + col_h - 1) // col_h
    canvas = Image.new("RGB", (cols * (img.width + gap) - gap, col_h), (52, 52, 52))
    for i in range(cols):
        part = img.crop((0, i * col_h, img.width, min(img.height, (i + 1) * col_h)))
        canvas.paste(part, (i * (img.width + gap), 0))
    canvas.save(out, quality=86)


def main() -> None:
    ensure_gui_application()
    project = Project.open(Path(sys.argv[1]))
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 7
    concepts = sys.argv[4:] or ["minimal", "bold", "photo", "layered", "story"]
    stale = [a for a in project.list_assets() if a.is_visual and (a.analysis or {}).get("version") != ANALYSIS_VERSION]
    if stale:
        t = time.time()
        analyze_assets(project, stale, workers=4)
        print(f"re-analysed {len(stale)} assets in {time.time() - t:.1f}s")
    assets = project.list_assets()
    by_id = {a.id: a for a in assets}
    d = build_directives(project.name, assets, project.brief_text, project.script_text)
    direction = build_direction(d.brief, assets, d.category)
    ctx = PlanningContext(project.name, assets, d, direction)
    with BrowserSession() as browser:
        for concept in concepts:
            t = time.time()
            spec = ProposalSpec(family=concept, seed=seed)
            plan = build_plan(ctx, spec)
            pres = compose(plan, by_id, direction, spec)
            report = validate_presentation(pres, by_id, plan)
            print(f"\n=== {concept}  ({len(pres.sections)} sections, {pres.height:.0f}px, {time.time() - t:.2f}s)")
            for sp, sec in zip([s for s in plan.sections if not s.meta.get("hidden")], pres.sections):
                names = [by_id[a].filename[:22] for a in sp.asset_ids if a in by_id]
                print(f"  {sec.meta.get('module', sec.pattern):16} h={sec.height:6.0f} bg={sec.background} {names}")
            for issue in report.issues:
                if issue.severity != "info":
                    print(f"  !! {issue.severity} {issue.code}: {issue.message}")
            html = out_dir / f"{concept}.html"
            write_html(project, pres, html, mode="static", scale=1.0, quality="standard")
            page = browser.open(html, pres.width, scale=0.5)
            issues = browser.layout_issues(page)
            if issues:
                print("  browser:", issues[:4])
            png = out_dir / f"{concept}.png"
            browser.capture(page, 0, pres.height, pres.width, 0.5, png)
            browser.close_page(page)
            sheet(png, out_dir / f"{concept}_sheet.jpg")


if __name__ == "__main__":
    main()
