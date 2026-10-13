"""Command-line interface (automation, testing, headless use).

    behance-studio create  "Name" --assets <folder> [--brief brief.txt] [--script GUIAO_PROJETO.txt]
    behance-studio import  <project> <files or folders>...
    behance-studio generate <project> [--families editorial,gallery] [--count 6] [--seed 42]
    behance-studio list    <project>
    behance-studio export  <project> --version all|preferred|<number> --formats pdf,jpg,html --out <folder>
    behance-studio trash / restore / purge <project> <number>...
    behance-studio demo    <folder>          create the Butter & Bean demo project and generate it
    behance-studio doctor                    check the environment
    behance-studio canva-export <project> [--version all|preferred|<number>] [--out <folder>] [--upload] [--combine]
    behance-studio canva-connect / canva-status / canva-disconnect   link Behance Studio to your Canva account
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

COMMANDS = {"create", "import", "generate", "list", "export", "trash", "restore", "purge", "demo", "doctor", "ai-check", "diagnose",
            "canva-export", "canva-connect", "canva-status", "canva-disconnect", "canva-verify", "real-test"}


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
    if getattr(args, "sections", None) and args.sections != project.config.section_source:
        project.config.section_source = args.sections
        project.save_config()
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
            elif est.needs_confirmation and not getattr(args, "allow_paid_ai", False):
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
    if result.diagnostics:
        print(f"Section diagnostics: {result.diagnostics}")
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


def cmd_canva_export(args) -> int:
    from behance_studio.canva.connect import CanvaConnect
    from behance_studio.canva.export import CanvaOptions, export_to_canva

    project = _open(args.project)
    settings = get_settings_store().settings
    ids = _select_versions(project, args.version)
    client = None
    if args.upload:
        client = CanvaConnect.from_settings(settings)
        if not client.connected:
            print("Not connected to Canva: run 'canva-connect' first (the file is still created).", file=sys.stderr)
            client = None
    options = CanvaOptions(
        destination=Path(args.out) if args.out else project.exports_dir,
        page_height=args.page_height or settings.canva.page_height or None,
        mode="editable" if args.editable else settings.canva.mode,
        quality=args.quality or settings.canva.quality,
        combine=args.combine, upload=client is not None, check=not args.no_check,
        check_with_libreoffice=args.libreoffice, browser_path=settings.browser_path,
    )
    report = export_to_canva(project, ids, options, client=client, progress=lambda f, m: _progress(ProgressEvent("canva", f, m)))
    print()
    for d in report.designs:
        check = f", check {d.similarity * 100:.1f}%" if d.similarity is not None else ""
        office = f", LibreOffice {d.office_similarity * 100:.1f}%" if d.office_similarity is not None else ""
        print(f"  {d.name}: {d.pptx} ({d.pages} pages of {d.page_size[0]}x{d.page_size[1]} px, {d.size_bytes / 1e6:.1f} MB{check}{office})")
        print(f"      report: {d.report}")
        if d.edit_url:
            print(f"      open in Canva: {d.edit_url}")
    for name, msg in report.failures:
        print(f"  PROBLEM {name}: {msg}")
    print(report.summary())
    return 0 if report.designs and not report.failures else 2


def cmd_canva_connect(args) -> int:
    from behance_studio.canva.connect import CanvaConnect

    store = get_settings_store()
    s = store.settings.canva
    if args.client_id:
        s.client_id = args.client_id.strip()
    if args.port:
        s.redirect_port = args.port
    if args.client_secret:
        CanvaConnect.store_client_secret(args.client_secret)
    store.save()
    client = CanvaConnect.from_settings(store.settings)
    print(f"Redirect URL to add to your Canva integration: {client.redirect_uri}")

    def show(url: str) -> None:
        import webbrowser

        print(f"Opening Canva to approve access (if no browser opens, visit):\n  {url}")
        webbrowser.open(url)

    name = client.authorize(open_url=show)
    s.account_name = name
    store.save()
    print(f"Connected to Canva{' as ' + name if name else ''}.")
    return 0


def cmd_canva_status(args) -> int:
    from behance_studio.canva.connect import CanvaConnect

    settings = get_settings_store().settings
    client = CanvaConnect.from_settings(settings)
    print(f"Client ID:     {client.client_id or '(not set)'}")
    print(f"Client secret: {'stored' if client.client_secret else '(not set)'}")
    print(f"Redirect URL:  {client.redirect_uri}")
    if not client.connected:
        print("Status:        not connected (run canva-connect)")
        return 1
    try:
        name = client.profile_name()
        print(f"Status:        connected{' as ' + name if name else ''}")
        return 0
    except UserFacingError as exc:
        print(f"Status:        {exc.message}")
        return 2


def cmd_canva_disconnect(args) -> int:
    from behance_studio.canva.connect import CanvaConnect

    store = get_settings_store()
    CanvaConnect.from_settings(store.settings).disconnect()
    store.settings.canva.account_name = ""
    store.save()
    print("Disconnected from Canva (the Client ID and secret are kept; designs in Canva are not affected).")
    return 0


def cmd_canva_verify(args) -> int:
    """Compare the pages Canva renders (downloaded from canva.com) with the original."""
    from behance_studio.canva.verify import verify_canva

    settings = get_settings_store().settings
    result = verify_canva(Path(args.design), Path(args.canva_pages), Path(args.out) if args.out else None,
                          Path(args.project) if args.project else None, settings.browser_path, progress=lambda m: print(f"  … {m}"))
    print(result.report.read_text(encoding="utf-8"))
    print(f"Results: {result.out_dir}")
    return 0 if result.ok else 2


def cmd_real_test(args) -> int:
    """Test with a real project on this computer: import, generate, export, measure, report."""
    from behance_studio.realtest import default_output_dir, run_real_test

    families = [f.strip() for f in args.families.split(",")] if args.families else None
    out = Path(args.out) if args.out else default_output_dir()
    result = run_real_test(Path(args.folder), out, use_ai=not args.no_ai, canva=not args.no_canva, families=families,
                           progress=lambda m: print(f"  {m}", flush=True))
    print()
    print(result.report.read_text(encoding="utf-8"))
    print(f"Pasta do teste: {result.folder}")
    print(f"Ficheiro para enviar: {result.zip_path}")
    return 0 if result.ok else 2


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
    return cmd_generate(argparse.Namespace(project=entry.path, families=None, count=0, seed=args.seed, creativity=None, no_previews=False,
                                           strict=False, allow_paid_ai=False, sections=None))


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


def cmd_diagnose(args) -> int:
    """Show why every image is in its section (latest generation, or the current assignment)."""
    project = _open(args.project)
    latest = project.root / "Diagnostics" / "latest.txt"
    if latest.exists() and not args.now:
        print(latest.read_text(encoding="utf-8"))
        return 0
    from behance_studio.generation.diagnostics import build_report, render_text
    from behance_studio.planning.assignment import assign_sections

    from behance_studio.assets.folders import backfill_source_folders

    assets = project.list_assets()
    backfill_source_folders([a for a in assets if a.is_visual])  # as generation will do
    assignment = assign_sections(assets, project.config.section_source)
    print(render_text(build_report(project, assets, assignment, [], "(no generation yet: current assignment only)")))
    return 0


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
    p.add_argument("--sections", choices=["auto", "folders", "content"],
                   help="auto (default): follow the section folders when the files are organised in them; "
                        "content: let AI/heuristics regroup the images (saved for the project)")
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
    p = sub.add_parser("canva-export", help="create Canva-editable PowerPoint files (and upload them to Canva with --upload)")
    p.add_argument("project")
    p.add_argument("--version", default="preferred")
    p.add_argument("--out")
    p.add_argument("--page-height", type=int, help="page height in px (default: chosen automatically)")
    p.add_argument("--editable", action="store_true", help="keep masks and gradients as PowerPoint properties instead of drawing them")
    p.add_argument("--quality", choices=["standard", "high", "maximum"])
    p.add_argument("--combine", action="store_true", help="all chosen proposals in one Canva design")
    p.add_argument("--upload", action="store_true", help="import into your Canva account (after canva-connect)")
    p.add_argument("--no-check", action="store_true", help="skip the comparison with the original")
    p.add_argument("--libreoffice", action="store_true", help="also render the .pptx with LibreOffice (when installed) and compare")
    p.set_defaults(func=cmd_canva_export)
    p = sub.add_parser("canva-connect", help="connect your Canva account (Canva Connect API integration)")
    p.add_argument("--client-id")
    p.add_argument("--client-secret")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_canva_connect)
    p = sub.add_parser("canva-status")
    p.set_defaults(func=cmd_canva_status)
    p = sub.add_parser("canva-disconnect")
    p.set_defaults(func=cmd_canva_disconnect)
    p = sub.add_parser("canva-verify", help="compare the pages Canva shows (downloaded from canva.com as PNG/ZIP/PDF) with the original")
    p.add_argument("design", help="the .pptx (or .canva.json) written by canva-export")
    p.add_argument("canva_pages", help="what you downloaded from Canva: ZIP or folder of PNG pages, or a PDF")
    p.add_argument("--project", help="the project folder, if it was moved since the export")
    p.add_argument("--out", help="where to write the comparison (default: next to the download)")
    p.set_defaults(func=cmd_canva_verify)
    p = sub.add_parser("real-test", help="test with one of your projects: import, five proposals, PDF + Canva export, report and ZIP")
    p.add_argument("folder", help="the project folder (with its section sub-folders)")
    p.add_argument("--out", help="where to create the test (default: Documents/Behance Studio Tests)")
    p.add_argument("--no-ai", action="store_true", help="do not use the local vision model even if Ollama is ready")
    p.add_argument("--no-canva", action="store_true", help="skip the Canva export")
    p.add_argument("--families", help="comma-separated concept families (default: the five concepts)")
    p.set_defaults(func=cmd_real_test)
    for name in ("trash", "restore", "purge"):
        p = sub.add_parser(name)
        p.add_argument("project")
        p.add_argument("numbers", nargs="+")
        p.set_defaults(func=cmd_trash)
    p = sub.add_parser("demo")
    p.add_argument("folder")
    p.add_argument("--seed", type=int, default=2026)
    p.set_defaults(func=cmd_demo)
    p = sub.add_parser("diagnose", help="show where each image comes from, what AI said and which section it is in")
    p.add_argument("project")
    p.add_argument("--now", action="store_true", help="compute the current assignment instead of showing the last generation's report")
    p.set_defaults(func=cmd_diagnose)
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
