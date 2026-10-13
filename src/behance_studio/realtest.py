"""Real-world test: one command on the user's PC, with their own project.

``behance-studio real-test <folder>`` (or ``Teste_Real.bat``) imports the
folder into a new test project, generates the five concepts (with the local
vision model when Ollama is ready), exports a PDF and a Canva file per
proposal, measures what can be measured and writes a short report in
Portuguese plus a ZIP to send back for analysis.

The ZIP contains text reports and small contact sheets of the generated
proposals — never the original files. Nothing is sent anywhere by this
command.
"""

from __future__ import annotations

import contextlib
import io
import json
import platform
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from behance_studio import APP_NAME, __version__
from behance_studio.core.errors import UserFacingError
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class RealTestResult:
    folder: Path
    report: Path
    zip_path: Path
    ok: bool
    problems: list[str] = field(default_factory=list)


def default_output_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "Behance Studio Tests"


def _environment() -> str:
    from behance_studio import cli

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            cli.cmd_doctor(None)
        except Exception as exc:  # noqa: BLE001 - the report must still be written
            print(f"doctor failed: {exc}")
    return buf.getvalue()


def _contact_sheet(png: Path, out: Path, cols: int = 6, width: int = 300) -> None:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    with Image.open(png) as im:
        s = width / im.width
        im = im.convert("RGB").resize((width, max(1, int(im.height * s))))
    h = (im.height + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (width + 8), h), "#202020")
    for c in range(cols):
        sheet.paste(im.crop((0, c * h, width, (c + 1) * h)), (c * (width + 8), 0))
    sheet.save(out, "JPEG", quality=82)


def _proposal_metrics(data) -> dict:
    from behance_studio.planning.fit import placement_violations

    comps = []
    for s in data.plan.sections:
        if s.type in ("cover", "closing") or not s.meta.get("module"):
            continue
        p = s.meta.get("params") or {}
        comps.append((s.meta["module"], p.get("align", "center"), bool(p.get("rhythm_variant"))))
    rendered = {b.asset_id for s in data.presentation.sections for b in s.blocks if b.asset_id}
    planned = [a for s in data.plan.sections for a in s.asset_ids]
    return {
        "sections": len(data.plan.sections),
        "compositions": len({c[0] for c in comps}),
        "repeats_back_to_back": sum(1 for a, b in zip(comps, comps[1:]) if a == b and a[0] not in ("chapter", "statement")),
        "misplaced_images": len(placement_violations(data.plan, data.plan.asset_sections or {})),
        "planned_not_rendered": len([a for a in planned if a not in rendered]),
        "quality_errors": len(data.quality.errors),
        "quality_warnings": len(data.quality.warnings),
        "height_px": round(data.presentation.height),
    }


def run_real_test(folder: Path, out_root: Path, use_ai: bool = True, canva: bool = True, families: list[str] | None = None,
                  progress: Callable[[str], None] = print, settings=None) -> RealTestResult:
    from behance_studio.ai.service import local_ai_status, service_for_project
    from behance_studio.assets.importer import import_paths
    from behance_studio.canva.export import CanvaOptions, export_to_canva
    from behance_studio.core.settings import get_settings_store
    from behance_studio.export.exporter import ExportOptions, export_versions
    from behance_studio.generation.pipeline import GenerationRequest, generate
    from behance_studio.layout.families import CONCEPT_FAMILIES, family_info
    from behance_studio.projects.store import Project
    from behance_studio.projects.versions import VersionManager
    from behance_studio.render.browser import BrowserSession, browser_available
    from behance_studio.render.project_render import write_html

    folder = Path(folder)
    if not folder.is_dir():
        raise UserFacingError(f"A pasta não existe: {folder}")
    stamp = time.strftime("%Y%m%d-%H%M")
    out = Path(out_root) / f"Teste {folder.name} {stamp}"
    out.mkdir(parents=True, exist_ok=True)
    settings = settings or get_settings_store().settings
    times: dict[str, float] = {}
    problems: list[str] = []
    metrics: dict = {"app": f"{APP_NAME} {__version__}", "python": platform.python_version(), "os": platform.platform(),
                     "folder": folder.name}

    def timed(name: str):
        class T:
            def __enter__(self):
                progress(f"… {name}")
                self.t = time.time()

            def __exit__(self, *exc):
                times[name] = round(time.time() - self.t, 1)
        return T()

    (out / "ambiente.txt").write_text(_environment(), encoding="utf-8")

    ai = None
    ai_state = "desligada (pedido)"
    if use_ai:
        status = local_ai_status(settings)
        if status is not None and getattr(status, "ready", False):
            ai_state = f"Ollama pronto: {status.summary()}"
        else:
            ai_state = f"não disponível: {status.summary() if status is not None else 'fornecedor de IA não é o Ollama'}"
    metrics["ai"] = ai_state

    with timed("importar"):
        project = Project.create(out, "Projeto de teste")
        report = import_paths(project, [folder])
    assets = project.list_assets()
    metrics["files"] = {"imported": len(assets), "visual": sum(1 for a in assets if a.is_visual),
                        "errors": len(getattr(report, "errors", []) or []), "duplicates": len(getattr(report, "duplicates", []) or [])}
    if use_ai and ai_state.startswith("Ollama pronto"):
        ai = service_for_project(project, settings)

    fams = families or list(CONCEPT_FAMILIES)
    seed = int(time.time()) % 100000
    metrics["seed"] = seed
    last = [""]

    def generation_progress(event) -> None:
        message = (event.message or "")[:90]
        if message and message != last[0]:  # the first run with AI analyses every image: show that it is moving
            last[0] = message
            progress(f"    {message}")

    with timed("gerar propostas"):
        result = generate(project, GenerationRequest(families=fams, seed=seed, render_previews=False), ai_service=ai,
                          progress=generation_progress)
    metrics["generation_notes"] = list(result.notes)
    if getattr(result, "failures", None):
        problems += [f"Proposta não gerada: {f}" for f in result.failures]

    vm = VersionManager(project)
    proposals = []
    for rec in result.versions:
        data = vm.load(rec.id)
        m = _proposal_metrics(data)
        m["name"] = rec.name
        m["family"] = family_info(rec.family).name
        proposals.append(m)
        if m["misplaced_images"]:
            problems.append(f"{rec.name}: {m['misplaced_images']} imagem(ns) fora da secção da sua pasta")
        if m["planned_not_rendered"]:
            problems.append(f"{rec.name}: {m['planned_not_rendered']} imagem(ns) planeada(s) mas não mostrada(s)")
        if m["repeats_back_to_back"]:
            problems.append(f"{rec.name}: {m['repeats_back_to_back']} composição(ões) repetida(s) seguida(s)")
    metrics["proposals"] = proposals

    sheets = out / "Folhas de contacto"
    sheets.mkdir(exist_ok=True)

    def stage(name: str, work: Callable[[], None]) -> None:
        """One failing stage is reported; the others and the report still run."""
        try:
            with timed(name):
                work()
        except Exception as exc:  # noqa: BLE001 - the report must still be written
            log.exception("real test: %s failed", name)
            problems.append(f"Falhou a etapa «{name}»: {exc}")

    def previews() -> None:
        with BrowserSession(settings.browser_path) as browser:
            for rec in result.versions:
                pres = vm.load(rec.id).presentation
                html = write_html(project, pres, out / f".tmp-{rec.id}.html")
                page = browser.open(html, pres.width, scale=0.25)
                png = out / f".tmp-{rec.id}.png"
                try:
                    BrowserSession.capture(page, 0, pres.height, pres.width, 0.25, png)
                    _contact_sheet(png, sheets / f"{rec.number:02d} {family_info(rec.family).name}.jpg")
                finally:
                    BrowserSession.close_page(page)
                    png.unlink(missing_ok=True)
                    html.unlink(missing_ok=True)

    def pdf() -> None:
        report = export_versions(project, [r.id for r in result.versions],
                                 ExportOptions(formats=["pdf"], destination=out / "PDF", browser_path=settings.browser_path))
        problems.extend(f"PDF {n}: {msg}" for n, _f, msg in report.failures)

    def canva_export() -> None:
        cv = export_to_canva(project, [r.id for r in result.versions], CanvaOptions(destination=out / "Canva", browser_path=settings.browser_path))
        metrics["canva"] = [{"name": d.name, "pages": d.pages, "page_size": d.page_size, "mb": round(d.size_bytes / 1e6, 1),
                             "conversion_check": round(d.similarity * 100, 1) if d.similarity is not None else None} for d in cv.designs]
        problems.extend(f"Canva {n}: {msg}" for n, msg in cv.failures)

    if browser_available(settings.browser_path):
        stage("pré-visualizações", previews)
        stage("exportar PDF", pdf)
    else:
        problems.append("Não foi encontrado um browser Chromium/Edge: sem pré-visualizações nem PDF.")
    if canva:
        stage("exportar Canva", canva_export)

    metrics["times_s"] = times
    diag = project.root / "Diagnostics" / "latest.txt"
    if diag.exists():
        (out / "relatorio-secoes.txt").write_text(diag.read_text(encoding="utf-8"), encoding="utf-8")
    (out / "medicoes.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [f"Behance Studio — teste real — {time.strftime('%Y-%m-%d %H:%M')}", f"Pasta: {folder}", f"Versão: {APP_NAME} {__version__}",
             f"IA local: {ai_state}", "",
             f"Ficheiros importados: {metrics['files']['imported']} ({metrics['files']['visual']} imagens/vídeos, "
             f"{metrics['files']['errors']} com erro, {metrics['files']['duplicates']} duplicados)", ""]
    lines += ["Tempos: " + ", ".join(f"{k} {v:.0f}s" for k, v in times.items()), ""]
    lines.append("PROPOSTAS")
    for m in proposals:
        lines.append(f"  {m['name']} ({m['family']}): {m['sections']} secções, {m['compositions']} composições diferentes, "
                     f"{m['repeats_back_to_back']} repetições seguidas, {m['misplaced_images']} imagens fora da pasta, "
                     f"{m['quality_errors']} erros / {m['quality_warnings']} avisos técnicos")
    if canva and metrics.get("canva"):
        lines += ["", "CANVA (ficheiros na pasta Canva)"]
        for d in metrics["canva"]:
            check = f", verificação da conversão {d['conversion_check']}%" if d["conversion_check"] is not None else ""
            lines.append(f"  {d['name']}: {d['pages']} páginas de {d['page_size'][0]}×{d['page_size'][1]} px, {d['mb']} MB{check}")
    lines += ["", "PROBLEMAS DETETADOS AUTOMATICAMENTE"]
    lines += [f"  • {p}" for p in problems] or ["  • nenhum"]
    lines += ["", "O QUE FALTA AVALIAR (por si)",
              "  1. Abra as folhas de contacto e os PDF: alguma imagem está numa secção errada? Alguma composição parece fraca?",
              "  2. Importe um .pptx da pasta Canva no canva.com e compare com o PDF (ver docs/TESTES_REAIS.md, passo 5).",
              "", "Envie o ficheiro ZIP criado ao lado desta pasta (só contém relatórios e folhas de contacto — imagens reduzidas das propostas —, nunca os seus ficheiros originais)."]
    report_path = out / "RELATORIO.txt"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    zip_path = out.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in [report_path, out / "medicoes.json", out / "ambiente.txt", out / "relatorio-secoes.txt"]:
            if f.exists():
                z.write(f, f.name)
        for f in sorted(sheets.glob("*.jpg")):
            z.write(f, f"Folhas de contacto/{f.name}")
        for f in sorted((out / "Canva").glob("* - Canva report.txt")) if canva else []:
            z.write(f, f"Canva/{f.name}")
    return RealTestResult(out, report_path, zip_path, not problems, problems)
