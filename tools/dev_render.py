"""Developer tool: compose a project with one family and render a PNG strip.

    python tools/dev_render.py <project folder> <family> [seed] [out.png] [scale]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from behance_studio.brief.directives import build_directives  # noqa: E402
from behance_studio.core.qtsupport import ensure_gui_application  # noqa: E402
from behance_studio.design.direction import build_direction  # noqa: E402
from behance_studio.layout.engine import ProposalSpec, build_plan, compose  # noqa: E402
from behance_studio.planning.planner import PlanningContext, describe_plan  # noqa: E402
from behance_studio.projects.store import Project  # noqa: E402
from behance_studio.render.browser import BrowserSession  # noqa: E402
from behance_studio.render.project_render import write_html  # noqa: E402


def main() -> None:
    ensure_gui_application()
    project = Project.open(Path(sys.argv[1]))
    family = sys.argv[2]
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    out = Path(sys.argv[4]) if len(sys.argv) > 4 else Path(f"{family}-{seed}.png")
    view_scale = float(sys.argv[5]) if len(sys.argv) > 5 else 0.5
    assets = project.list_assets()
    d = build_directives(project.name, assets, project.brief_text, project.script_text)
    direction = build_direction(d.brief, assets, d.category)
    ctx = PlanningContext(project.name, assets, d, direction)
    spec = ProposalSpec(family=family, seed=seed)
    plan = build_plan(ctx, spec)
    print(describe_plan(plan))
    pres = compose(plan, {a.id: a for a in assets}, direction, spec)
    from behance_studio.layout.validate import validate_presentation

    report = validate_presentation(pres, {a.id: a for a in assets}, plan)
    print("scores", report.scores)
    for issue in report.issues:
        if issue.severity != "info":
            print("  ", issue.severity, issue.code, issue.message)
    print("height", round(pres.height), "sections", [(s.type, s.pattern, round(s.height)) for s in pres.sections])
    html_path = out.with_suffix(".html")
    write_html(project, pres, html_path, mode="static", scale=1.0, quality="standard")
    with BrowserSession() as browser:
        page = browser.open(html_path, pres.width, scale=view_scale)
        issues = browser.layout_issues(page)
        print("browser issues:", issues[:5])
        browser.capture(page, 0, pres.height, pres.width, view_scale, out)
        browser.close_page(page)
    img = Image.open(out)
    print("png", img.size)


if __name__ == "__main__":
    main()
