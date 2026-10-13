"""The real-world test kit: ``real-test`` and ``canva-verify``.

These tests check the tools themselves. The "Canva download" used here is a
stand-in (the .pptx rendered by LibreOffice, saved as PNG pages the way
Canva names them): it proves the comparison works, not that Canva renders
the file correctly — that needs the user's real Canva account
(docs/TESTES_REAIS.md).
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from organized_fixture import build_organized_pt
from behance_studio.canva.check import libreoffice
from behance_studio.canva.verify import _ordered, load_canva_pages
from behance_studio.render.browser import browser_available

HAS_BROWSER = browser_available()


@pytest.fixture(scope="module")
def pt_dir(tmp_path_factory, demo_assets_dir):
    return build_organized_pt(demo_assets_dir, tmp_path_factory.mktemp("pt"))


@pytest.mark.slow
@pytest.mark.skipif(not HAS_BROWSER, reason="needs a Chromium-based browser")
def test_real_test_writes_a_report_and_a_zip_without_the_originals(pt_dir, tmp_path):
    from behance_studio.realtest import run_real_test

    result = run_real_test(pt_dir, tmp_path, use_ai=False, canva=True, families=["minimal"], progress=lambda m: None)
    assert result.ok, result.problems
    text = result.report.read_text(encoding="utf-8")
    assert "0 imagens fora da pasta" in text and "PROBLEMAS DETETADOS AUTOMATICAMENTE" in text
    metrics = json.loads((result.folder / "medicoes.json").read_text(encoding="utf-8"))
    assert metrics["files"]["imported"] > 10 and metrics["proposals"][0]["misplaced_images"] == 0
    assert metrics["proposals"][0]["repeats_back_to_back"] == 0
    assert list((result.folder / "PDF").rglob("*.pdf")) and list((result.folder / "Canva").glob("*.pptx"))
    names = zipfile.ZipFile(result.zip_path).namelist()
    assert "RELATORIO.txt" in names and any(n.startswith("Folhas de contacto/") for n in names)
    originals = {p.name for p in pt_dir.rglob("*") if p.is_file()}
    assert not originals & {Path(n).name for n in names}  # never the user's files
    assert not any(n.endswith((".pptx", ".pdf", ".png")) for n in names)


@pytest.mark.slow
def test_real_test_uses_the_local_vision_model_when_ollama_is_ready(pt_dir, tmp_path):
    """With Ollama ready (here: the local stand-in), the test runs with the vision model and the
    section report says what the model changed in the layouts."""
    from ollama_mock import MockOllama
    from behance_studio.core.settings import AppSettings
    from behance_studio.realtest import run_real_test

    server = MockOllama()
    try:
        settings = AppSettings()
        settings.ai.provider, settings.ai.base_url = "ollama", server.url
        result = run_real_test(pt_dir, tmp_path, use_ai=True, canva=False, families=["photo"], progress=lambda m: None, settings=settings)
    finally:
        server.close()
    metrics = json.loads((result.folder / "medicoes.json").read_text(encoding="utf-8"))
    assert metrics["ai"].startswith("Ollama pronto"), metrics["ai"]
    assert "AI influence on the layouts:" in (result.folder / "relatorio-secoes.txt").read_text(encoding="utf-8")
    assert metrics["proposals"][0]["misplaced_images"] == 0


def test_canva_download_pages_are_read_in_order(tmp_path):
    names = ["Café 2026 (2).png", "Café 2026.png", "Café 2026 (1).png"]
    assert [p.name for p in _ordered([Path(n) for n in names])] == ["Café 2026.png", "Café 2026 (1).png", "Café 2026 (2).png"]
    assert [p.name for p in _ordered([Path(n) for n in ["10.png", "2.png", "1.png"]])] == ["1.png", "2.png", "10.png"]
    with zipfile.ZipFile(tmp_path / "canva.zip", "w") as z:
        for i, color in enumerate(["#FF0000", "#00FF00", "#0000FF"], 1):
            img = tmp_path / f"{i}.png"
            Image.new("RGBA", (20, 30), color).save(img)
            z.write(img, f"Design/{i}.png")
    pages = load_canva_pages(tmp_path / "canva.zip", tmp_path)
    assert [p.getpixel((1, 1)) for p in pages] == [(255, 0, 0), (0, 255, 0), (0, 0, 255)]


@pytest.mark.slow
@pytest.mark.skipif(not (HAS_BROWSER and libreoffice() and shutil.which("pdftoppm")), reason="needs Chromium, LibreOffice and pdftoppm")
def test_canva_verify_compares_downloaded_pages_with_the_original(projects_dir, pt_dir, tmp_path):
    from behance_studio.assets.importer import import_paths
    from behance_studio.canva.check import render_pptx_pages
    from behance_studio.canva.export import CanvaOptions, export_to_canva
    from behance_studio.canva.verify import verify_canva
    from behance_studio.generation.pipeline import GenerationRequest, generate
    from behance_studio.projects.store import Project

    project = Project.create(projects_dir, "Verify")
    import_paths(project, [pt_dir])
    versions = generate(project, GenerationRequest(families=["minimal", "bold"], seed=4, render_previews=False)).versions
    report = export_to_canva(project, [v.id for v in versions], CanvaOptions(destination=tmp_path / "out", check=False, combine=True))
    combined = next(d for d in report.designs if len(d.version_ids) == 2)
    data = json.loads(combined.scene_json.read_text(encoding="utf-8"))
    parts = data["source"]["parts"]
    assert [p["version_id"] for p in parts] == [v.id for v in versions] and sum(p["pages"] for p in parts) == len(data["pages"])

    # the stand-in for "Share → Download → PNG" in Canva
    pages = render_pptx_pages(combined.pptx, tmp_path)
    download = tmp_path / "download"
    download.mkdir()
    for i, page in enumerate(pages):
        page.save(download / (f"{project.name}.png" if i == 0 else f"{project.name} ({i}).png"))
    good = verify_canva(combined.pptx, download, tmp_path / "v-good")
    assert good.ok and good.canva_pages == good.expected_pages and good.average > 0.95, [round(p.similarity, 3) for p in good.pages]
    assert "RESULTADO: o Canva mostra o design como o original." in good.report.read_text(encoding="utf-8")

    # a page Canva lost and a page drawn wrongly are both reported, with a side-by-side image
    (download / f"{project.name} (1).png").unlink()
    Image.new("RGB", pages[3].size, "#FFFFFF").save(download / f"{project.name} (3).png")
    bad = verify_canva(combined.pptx, download, tmp_path / "v-bad")
    assert not bad.ok and bad.canva_pages == bad.expected_pages - 1
    assert any(p.image is not None and p.image.exists() for p in bad.pages)
    assert "páginas" in " ".join(bad.notes)
