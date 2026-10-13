"""Verify a design as Canva itself renders it.

The checks run during export (``check.py``) measure the file Canva receives;
they cannot show what Canva does with it. This module closes that gap with
the user's real Canva account, without any API: after importing the .pptx
into canva.com, the user downloads the design (Share → Download → PNG, all
pages, or PDF) and runs::

    behance-studio canva-verify "<design>.pptx" "<download from Canva>"

The original pages are rebuilt from the project (the ``.canva.json`` written
next to the .pptx records which project and proposal they come from) and
compared page by page with Canva's pages. The result — per-page similarity,
page count and page size checks, and side-by-side images of the pages that
differ — is written to a folder next to the download.

Only this comparison is evidence of compatibility with Canva; tests with
simulated APIs are not.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from behance_studio.canva.check import compare
from behance_studio.core.errors import UserFacingError
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
GOOD = 0.95  # pages above this match the original closely
FAIR = 0.85  # below this a page needs a look


@dataclass
class PageResult:
    page: int  # 1-based
    similarity: float
    aspect_delta: float  # relative difference of width/height ratio
    image: Path | None = None  # side-by-side comparison, when written


@dataclass
class VerifyResult:
    design: str
    expected_pages: int
    canva_pages: int
    pages: list[PageResult] = field(default_factory=list)
    out_dir: Path | None = None
    report: Path | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def average(self) -> float | None:
        return sum(p.similarity for p in self.pages) / len(self.pages) if self.pages else None

    @property
    def ok(self) -> bool:
        return (self.expected_pages == self.canva_pages and bool(self.pages)
                and all(p.similarity >= FAIR and p.aspect_delta < 0.02 for p in self.pages))


def _ordered(files: list[Path], name=lambda p: p.stem) -> list[Path]:
    """Page order from the file names: "1.png", "2.png"… or "Design.png", "Design (1).png"… (the common
    part of the names is ignored, so a year in the design name does not count as a page number)."""
    stems = [name(p) for p in files]
    prefix = os.path.commonprefix(stems) if len(stems) > 1 else ""
    while prefix and prefix[-1].isdigit() and any(st[len(prefix):len(prefix) + 1].isdigit() for st in stems):
        prefix = prefix[:-1]  # "Page 1" / "Page 10": the page number is not part of the common name

    def key(p: Path) -> tuple[int, str]:
        found = re.findall(r"\d+", name(p)[len(prefix):])
        return (int(found[-1]) if found else 0, p.name.lower())
    return sorted(files, key=key)


def load_canva_pages(source: Path, tmp: Path) -> list[Image.Image]:
    """Pages downloaded from Canva: a folder of PNG/JPG, the ZIP Canva gives for several pages, or a PDF."""
    source = Path(source)
    files: list[Path] = []
    if source.is_dir():
        files = [p for p in source.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES]
    elif source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as z:
            for info in z.infolist():
                name = Path(info.filename)
                if info.is_dir() or name.suffix.lower() not in IMAGE_SUFFIXES or name.name.startswith("."):
                    continue
                target = tmp / "zip" / f"{len(files):04d}-{name.name}"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(info))
                files.append(target)
        return [_load(p) for p in _ordered(files, lambda p: Path(p.name.split("-", 1)[1]).stem)]
    elif source.suffix.lower() == ".pdf":
        pdftoppm = shutil.which("pdftoppm")
        if pdftoppm is None:
            raise UserFacingError("To compare a PDF, download the design from Canva as PNG instead (Share → Download → PNG, all pages).",
                                  "pdftoppm (Poppler) is not installed")
        subprocess.run([pdftoppm, "-r", "96", "-png", str(source), str(tmp / "page")], timeout=600, capture_output=True, check=False)
        files = list(tmp.glob("page*.png"))
    elif source.suffix.lower() in IMAGE_SUFFIXES:
        files = [source]
    if not files:
        raise UserFacingError(f"No pages found in {source}.", "Expected a folder or ZIP of PNG/JPG pages, or a PDF downloaded from Canva.")
    return [_load(p) for p in _ordered(files)]


def _load(path: Path) -> Image.Image:
    with Image.open(path) as img:
        img.load()
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            ground = Image.new("RGB", rgba.size, "#FFFFFF")
            ground.paste(rgba, mask=rgba.getchannel("A"))
            return ground
        return img.convert("RGB")


def scene_file(path: Path) -> Path:
    """The ``.canva.json`` for a .pptx (or the file itself)."""
    path = Path(path)
    candidate = path if path.name.endswith(".canva.json") else path.with_suffix(".canva.json")
    if not candidate.exists():
        raise UserFacingError(f"The file {candidate.name} was not found next to the PowerPoint file.",
                              "It is written by Behance Studio's Canva export; export again if it was deleted.")
    return candidate


def side_by_side(original: Image.Image, canva: Image.Image, similarity: float, page: int, out: Path, width: int = 700) -> Path:
    def fit(img: Image.Image) -> Image.Image:
        s = width / img.width
        return img.resize((width, max(1, int(img.height * s))), Image.Resampling.LANCZOS)

    a, b = fit(original), fit(canva)
    head = 34
    sheet = Image.new("RGB", (width * 2 + 24, max(a.height, b.height) + head + 8), "#1E1E1E")
    sheet.paste(a, (8, head))
    sheet.paste(b, (width + 16, head))
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 10), f"Pagina {page} - original (Behance Studio)", fill="#FFFFFF")
    draw.text((width + 18, 10), f"Canva - {similarity * 100:.1f}% da pagina coincide", fill="#FFFFFF")
    sheet.save(out, "JPEG", quality=85)
    return out


def verify_canva(design_file: Path, canva_source: Path, out_dir: Path | None = None, project_root: Path | None = None,
                 browser_path: str = "", progress=lambda m: None) -> VerifyResult:
    from behance_studio.canva.check import reference_ranges
    from behance_studio.projects.store import Project
    from behance_studio.projects.versions import VersionManager
    from behance_studio.render.browser import BrowserSession, browser_available

    data = json.loads(scene_file(design_file).read_text(encoding="utf-8"))
    source = data.get("source") or {}
    if not source.get("parts"):
        raise UserFacingError("This Canva file was exported by an older version of Behance Studio.",
                              "Export the proposal to Canva again, import the new .pptx into Canva and download it again.")
    root = Path(project_root) if project_root else Path(source.get("project_root", ""))
    if not (root / "project.json").exists():
        raise UserFacingError(f"The project was not found at {root}.", "Pass the project folder with --project if it was moved.")
    project = Project.open(root)
    manager = VersionManager(project)
    title = data.get("title") or Path(design_file).stem
    pages = data.get("pages") or []
    width, page_height = int(data["width"]), int(data["page_height"])

    out = Path(out_dir) if out_dir else Path(canva_source).with_name(f"Verificacao Canva - {Path(design_file).stem} {time.strftime('%Y%m%d-%H%M')}")
    out.mkdir(parents=True, exist_ok=True)
    result = VerifyResult(title, len(pages), 0, out_dir=out)

    if not browser_available(browser_path):
        raise UserFacingError("Chromium/Edge was not found: the original pages cannot be rebuilt for the comparison.")
    with tempfile.TemporaryDirectory(prefix="bs-canva-verify-") as name:
        tmp = Path(name)
        progress("Reading the pages downloaded from Canva")
        canva = load_canva_pages(Path(canva_source), tmp)
        result.canva_pages = len(canva)
        progress("Rebuilding the original pages")
        reference: list[Image.Image] = []
        with BrowserSession(browser_path) as browser:
            for k, part in enumerate(source["parts"]):
                pres = manager.load(part["version_id"]).presentation
                first, offset = int(part["first_page"]), float(part.get("offset", 0.0))
                ranges = []
                for p in pages[first:first + int(part["pages"])]:
                    filler = next((e.get("fill", {}).get("color") for e in p.get("elements", [])
                                   if e.get("role") == "filler" and isinstance(e.get("fill"), dict) and e["fill"].get("color")), None)
                    ranges.append((float(p["y0"]) - offset, float(p["y1"]) - offset, filler or "#FFFFFF"))
                (tmp / f"part{k}").mkdir()
                reference += reference_ranges(project, pres, width, page_height, ranges, browser, tmp / f"part{k}", source.get("section_ids"))
        progress("Comparing page by page")
        ratio = width / page_height
        for i, (a, b) in enumerate(zip(reference, canva), 1):
            diff = compare(a, b, i)
            delta = abs((b.width / b.height) - ratio) / ratio
            pr = PageResult(i, diff.similarity, delta)
            if diff.similarity < GOOD or delta >= 0.02:
                pr.image = side_by_side(a, b, diff.similarity, i, out / f"pagina-{i:02d}.jpg")
            result.pages.append(pr)
    if result.canva_pages != result.expected_pages:
        result.notes.append(f"O Canva tem {result.canva_pages} páginas; o ficheiro exportado tem {result.expected_pages}. "
                            "Confirme que descarregou todas as páginas (Partilhar → Transferir → PNG, todas as páginas).")
    result.report = out / "Verificacao Canva.txt"
    result.report.write_text(report_text(result, width, page_height), encoding="utf-8")
    return result


def report_text(r: VerifyResult, width: int, page_height: int) -> str:
    lines = [f"Verificação no Canva real — {r.design}", time.strftime("%Y-%m-%d %H:%M"), "",
             f"Páginas: {r.canva_pages} no Canva, {r.expected_pages} no ficheiro exportado"
             + ("" if r.canva_pages == r.expected_pages else "  ← DIFERENTE"),
             f"Tamanho esperado de página: {width}×{page_height} px (proporção {width / page_height:.3f})"]
    if r.average is not None:
        lines.append(f"Semelhança média com o original: {r.average * 100:.1f}%")
    lines += ["", "POR PÁGINA (≥95% muito próximo · 85–95% diferenças pequenas, p. ex. tipos de letra · <85% verificar)"]
    for p in r.pages:
        verdict = "muito próximo" if p.similarity >= GOOD else "diferenças pequenas" if p.similarity >= FAIR else "VERIFICAR"
        extra = f", proporção diferente em {p.aspect_delta * 100:.1f}%" if p.aspect_delta >= 0.02 else ""
        image = f"  → {p.image.name}" if p.image else ""
        lines.append(f"  Página {p.page:3d}: {p.similarity * 100:5.1f}%  {verdict}{extra}{image}")
    lines += [""] + [f"Nota: {n}" for n in r.notes]
    lines += ["", "RESULTADO: " + ("o Canva mostra o design como o original." if r.ok else
                                    "há diferenças — veja as imagens lado a lado nesta pasta e envie-as com este relatório."),
              "", "Como ler: a percentagem é a parte da página que coincide visualmente com o original (Chromium).",
              "Diferenças típicas do Canva: tipos de letra substituídos (texto com largura diferente), sombras e cantos",
              "arredondados ligeiramente diferentes. Imagens em falta ou deslocadas baixam muito a percentagem."]
    return "\n".join(lines) + "\n"
