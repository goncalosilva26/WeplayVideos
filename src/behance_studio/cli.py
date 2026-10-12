"""Command-line interface (automation, testing, headless use).

    behance-studio create  "Name" --assets <folder> [--brief brief.txt] [--script GUIAO_PROJETO.txt]
    behance-studio import  <project> <files or folders>...
    behance-studio generate <project> [--families editorial,gallery] [--count 6] [--seed 42]
    behance-studio list    <project>
    behance-studio export  <project> --version all|preferred|<number> --formats pdf,jpg,html --out <folder>
    behance-studio trash / restore / purge <project> <number>...
    behance-studio demo    <folder>          create the Butter & Bean demo project and generate it
    behance-studio doctor                    check the environment
"""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

from behance_studio import APP_NAME, __version__
from behance_studio.core.errors import BehanceStudioError, UserFacingError
from behance_studio.core.logging_setup import setup_logging
from behance_studio.core.qtsupport import ensure_gui_application
from behance_studio.core.settings import get_settings_store
from behance_studio.core.tasks import ProgressEvent

COMMANDS = {"create", "import", "generate", "list", "export", "trash", "restore", "purge", "demo", "doctor", "ai-check"}


def _progress(event: ProgressEvent) -> None:
    pct = f"{event.fraction * 100:5.1f}%" if event.fraction is not None else "  ... "
    stage = f"[{(event.stage_index or 0) + 1}/{event.stage_count}] " if event.stage_count else ""
    print(f"\r{pct} {stage}{event.message[:70]:<70}", end="", flush=True)


def _open(path: str):
    from behance_studio.projects.store import Project

    return Project.open(Path(path))


def _select_versions(project, spec: str) -> list[str]:
    from behance_studio.projects.versions import VersionManager

    manager = VersionManager(project)
    versions = manager.list()
    if spec == "all":
        return [v.id for v in versions]
    if spec == "preferred":
        pref = manager.preferred()
        if pref is None:
            raise UserFacingError("No preferred proposal is set.")
        return [pref.id]
    wanted = {s.strip() for s in spec.split(",")}
    out = [v.id for v in versions if str(v.number) in wanted or f"{v.number:03d}" in wanted or v.id in wanted]
    if not out:
        raise UserFacingError(f"No proposal matches '{spec}'.")
    return out


def cmd_create(args) -> int:
    from behance_studio.assets.importer import import_paths
    from behance_studio.core.fsutil import read_text_file
    from behance_studio.projects.library import ProjectLibrary
    from behance_studio.projects.store import Project

    settings = get_settings_store().settings
    parent = Path(args.dir) if args.dir else settings.resolved_projects_dir()
    project = Project.create(parent, args.name)
    if args.brief:
        project.write_text("brief", read_text_file(Path(args.brief)))
    if args.script:
        project.write_text("script", read_text_file(Path(args.script)))
    if args.assets:
        report = import_paths(project, [Path(a) for a in args.assets], progress=lambda f, m: _progress(ProgressEvent("import", f, m)), workers=settings.worker_count())
        print()
        print(report.summary())
        for path, msg in report.errors:
            print(f"  ! {Path(path).name}: {msg}")
    ProjectLibrary().register(project)
    print(project.root)
    return 0


def cmd_import(args) -> int:
    from behance_studio.assets.importer import import_paths

    project = _open(args.project)
    report = import_paths(project, [Path(p) for p in args.paths], progress=lambda f, m: _progress(ProgressEvent("import", f, m)))
    print()
    print(report.summary())
    return 0


def cmd_generate(args) -> int:
    from behance_studio.ai.service import service_for_project
    from behance_studio.generation.pipeline import GenerationRequest, generate

    project = _open(args.project)
    settings = get_settings_store().settings
    request = GenerationRequest(
        families=[f.strip() for f in args.families.split(",")] if args.families else list(settings.families),
        count=args.count or 0,
        creativity=args.creativity if args.creativity is not None else settings.creativity,
        width=settings.design_width,
        seed=args.seed,
        render_previews=not args.no_previews,
        browser_path=settings.browser_path,
        workers=settings.worker_count(),
        missing_reference_policy="abort" if args.strict else "continue",
    )
    ai = service_for_project(project, settings)
    if ai is not None and ai.content_allowed:
        est = ai.estimate_generation(project, request.families, request.render_previews)
        if est.requests:
            print(est.summary())
            if est.blocked_reason:
                print(f"AI not used: {est.blocked_reason}")
                ai = None
            elif est.needs_confirmation and not args.allow_paid_ai:
                print("AI not used: this provider may bill your account. Re-run with --allow-paid-ai to use it.")
                ai = None
    result = generate(project, request, progress=_progress, ai_service=ai)
    print()
    for issue in result.script_issues:
        print(f"  script {issue.severity}: {issue.message}")
    for note in result.notes:
        print(f"  note: {note}")
    for record in result.versions:
        print(f"  {record.number:03d}  {record.name:<28} quality {record.quality:.2f}  issues {record.issues}")
    for family, seed, msg in result.failures:
        print(f"  FAILED {family} (seed {seed}): {msg}")
    print(f"{len(result.versions)} proposal(s) in {result.elapsed:.1f}s")
    return 0 if result.versions else 1


def cmd_list(args) -> int:
    from behance_studio.projects.versions import VersionManager

    project = _open(args.project)
    manager = VersionManager(project)
    pref = project.config.preferred_version_id
    for v in manager.list(include_trashed=True):
        flags = ("★" if v.favorite else " ") + ("P" if v.id == pref else " ") + ("T" if v.status == "trashed" else " ")
        print(f"{v.number:03d} {flags} {v.name:<30} {v.family:<10} seed={v.seed:<7} quality={v.quality:.2f} {v.created_at}")
    return 0


def cmd_export(args) -> int:
    from behance_studio.export.exporter import ExportOptions, export_versions

    project = _open(args.project)
    settings = get_settings_store().settings
    ids = _select_versions(project, args.version)
    options = ExportOptions(
        formats=[f.strip() for f in args.formats.split(",")],
        destination=Path(args.out) if args.out else project.exports_dir,
        width=args.width or settings.export.width,
        quality=args.quality or settings.export.quality,
        long_image_mode=args.long_images or settings.export.long_image_mode,
        segment_height=settings.export.segment_height,
        jpeg_quality=settings.export.jpeg_quality,
        a4_margins=args.a4_margins,
        browser_path=settings.browser_path,
    )
    report = export_versions(project, ids, options, progress=lambda f, m: _progress(ProgressEvent("export", f, m)))
    print()
    for name, out in report.outputs:
        for p in out.paths:
            print(f"  {out.format:<7} {p}")
    for name, fmt, msg in report.failures:
        print(f"  FAILED {name} {fmt}: {msg}")
    print(report.summary())
    return 0 if not report.failures else 2


def cmd_trash(args) -> int:
    from behance_studio.projects.versions import VersionManager

    project = _open(args.project)
    manager = VersionManager(project)
    ids = _select_versions_any(project, args.numbers)
    if args.command == "trash":
        print(f"{manager.trash(ids)} moved to Trash")
    elif args.command == "restore":
        print(f"{manager.restore(ids)} restored")
    else:
        print(f"{manager.delete_permanently(ids)} permanently deleted")
    return 0


def _select_versions_any(project, numbers: list[str]) -> list[str]:
    versions = project.list_versions(include_trashed=True)
    wanted = set(numbers)
    return [v.id for v in versions if str(v.number) in wanted or f"{v.number:03d}" in wanted or v.id in wanted]


def cmd_demo(args) -> int:
    from behance_studio.core.paths import tools_dir

    sys.path.insert(0, str(tools_dir()))
    try:
        from make_demo_assets import build_demo_assets
    except ImportError:
        print("The demo asset generator (tools/make_demo_assets.py) is not available.")
        return 1
    target = Path(args.folder)
    assets = build_demo_assets(target / "Butter & Bean assets")
    ns = argparse.Namespace(name="Butter & Bean", dir=str(target), assets=[str(assets)], brief=None, script=None)
    cmd_create(ns)
    from behance_studio.projects.library import ProjectLibrary

    entry = ProjectLibrary().recent(limit=1)[0]
    return cmd_generate(argparse.Namespace(project=entry.path, families=None, count=0, seed=args.seed, creativity=None, no_previews=False, strict=False))


def cmd_doctor(args) -> int:
    from behance_studio.assets.media import ffmpeg_exe
    from behance_studio.core.paths import FONTS_DIR, logs_dir, user_data_dir
    from behance_studio.render.browser import find_browser

    print(f"{APP_NAME} {__version__}")
    print(f"Python      {sys.version.split()[0]} ({platform.platform()})")
    try:
        from PySide6 import __version__ as qt_version

        print(f"PySide6     {qt_version}")
    except Exception as exc:  # noqa: BLE001
        print(f"PySide6     MISSING ({exc})")
    try:
        print(f"FFmpeg      {ffmpeg_exe()}")
    except BehanceStudioError as exc:
        print(f"FFmpeg      MISSING ({exc})")
    browser = find_browser(get_settings_store().settings.browser_path)
    print(f"Browser     {browser or 'NOT FOUND — exports and previews will not work'}")
    print(f"Fonts       {len(list(FONTS_DIR.glob('*.ttf')))} bundled")
    ai = get_settings_store().settings.ai
    if ai.provider == "ollama":
        from behance_studio.ai.ollama import DEFAULT_MODEL, DEFAULT_URL, detect, setup_steps

        status = detect(ai.base_url or DEFAULT_URL, ai.model or DEFAULT_MODEL)
        print(f"AI          local (Ollama, free) · {status.summary()}")
        for i, step in enumerate(setup_steps(status, cli=True), 1):
            print(f"            {i}. {step}")
    elif ai.provider in ("", "none"):
        print("AI          off (offline heuristics)")
    else:
        from behance_studio.ai.credentials import has_api_key

        key = "key stored" if has_api_key(ai.provider) else "no key"
        print(f"AI          {ai.provider} · {ai.model or 'default model'} · {key}")
    print(f"Data        {user_data_dir()}")
    print(f"Logs        {logs_dir()}")
    return 0 if browser else 1


def cmd_ai_check(args) -> int:
    """Check local AI (Ollama); optionally download the model and test it for real."""
    from behance_studio.ai.ollama import DEFAULT_MODEL, DEFAULT_URL, detect, pull_model, setup_steps

    settings = get_settings_store().settings
    if args.model:
        settings.ai.model = args.model
    if settings.ai.provider != "ollama":
        print(f"The AI provider is “{settings.ai.provider}”. Using Ollama for this check (Settings → AI assistance to switch).")
        settings.ai.provider = "ollama"
        settings.ai.base_url = ""
    url, model = settings.ai.base_url or DEFAULT_URL, settings.ai.model or DEFAULT_MODEL
    status = detect(url, model, timeout=5.0)
    print(status.summary())
    if status.state == "model_missing" and args.pull:
        print(f"Downloading {model} through Ollama (once)…")
        last = [-1]

        def show(fraction: float, message: str) -> None:
            pct = int(fraction * 100)
            if pct != last[0]:
                last[0] = pct
                print(f"\r  {pct:3d}%  {message[:70]:<70}", end="", flush=True)

        try:
            pull_model(url, model, progress=show)
        except (RuntimeError, OSError) as exc:
            print(f"\nDownload failed: {exc}")
            return 1
        print()
        status = detect(url, model, timeout=5.0)
        print(status.summary())
    if not status.ready:
        for i, step in enumerate(setup_steps(status, cli=True), 1):
            print(f"  {i}. {step}")
        return 1
    if not args.test:
        print("Run with --test to measure recognition accuracy, speed, GPU use and creative direction with this model.")
        return 0
    from behance_studio.ai.verify import verify_local_ai

    report = verify_local_ai(settings, Path(args.folder) if args.folder else None, hide_names=not args.show_names,
                             director=not args.no_director, progress=lambda m: print(f"  … {m}"))
    print()
    for line in report.lines():
        print(line)
    if report.failures and report.failures == len(report.images):
        return 1
    return 0 if (report.accuracy is None or report.accuracy >= 0.6) else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="behance-studio", description=f"{APP_NAME} command line")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create")
    p.add_argument("name")
    p.add_argument("--dir")
    p.add_argument("--assets", nargs="*")
    p.add_argument("--brief")
    p.add_argument("--script")
    p.set_defaults(func=cmd_create)
    p = sub.add_parser("import")
    p.add_argument("project")
    p.add_argument("paths", nargs="+")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("generate")
    p.add_argument("project")
    p.add_argument("--families")
    p.add_argument("--count", type=int)
    p.add_argument("--seed", type=int)
    p.add_argument("--creativity", type=float)
    p.add_argument("--no-previews", action="store_true")
    p.add_argument("--strict", action="store_true", help="abort if the script references missing files")
    p.add_argument("--allow-paid-ai", action="store_true",
                   help="allow requests to a paid AI provider (the cost estimate is printed first; limits in Settings apply)")
    p.set_defaults(func=cmd_generate)
    p = sub.add_parser("list")
    p.add_argument("project")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("export")
    p.add_argument("project")
    p.add_argument("--version", default="preferred")
    p.add_argument("--formats", default="pdf")
    p.add_argument("--out")
    p.add_argument("--width", type=int)
    p.add_argument("--quality", choices=["standard", "high", "maximum"])
    p.add_argument("--long-images", choices=["auto", "continuous", "segments", "sections"])
    p.add_argument("--a4-margins", action="store_true")
    p.set_defaults(func=cmd_export)
    for name in ("trash", "restore", "purge"):
        p = sub.add_parser(name)
        p.add_argument("project")
        p.add_argument("numbers", nargs="+")
        p.set_defaults(func=cmd_trash)
    p = sub.add_parser("demo")
    p.add_argument("folder")
    p.add_argument("--seed", type=int, default=2026)
    p.set_defaults(func=cmd_demo)
    p = sub.add_parser("ai-check", help="check free local AI (Ollama); --pull downloads the model, --test runs it for real")
    p.add_argument("--model", help="Ollama model to check (default: the one in Settings, else qwen3-vl:8b)")
    p.add_argument("--pull", action="store_true", help="download the model through Ollama if it is missing")
    p.add_argument("--test", action="store_true", help="run the real model on test images and one creative-direction request")
    p.add_argument("--folder", help="test on your own images instead of the bundled test images")
    p.add_argument("--show-names", action="store_true", help="let the model see file names (hidden by default)")
    p.add_argument("--no-director", action="store_true", help="skip the creative-direction test")
    p.set_defaults(func=cmd_ai_check)
    p = sub.add_parser("doctor")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging(console=False)
    ensure_gui_application()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except UserFacingError as exc:
        print(f"\nError: {exc.message}", file=sys.stderr)
        if exc.detail:
            print(f"  ({exc.detail.splitlines()[0][:200]})", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
