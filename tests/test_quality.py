"""Quality and reliability of generated projects (phase-1 improvements).

* folder names as designers really write them (Portuguese, plurals, numbered
  sections with sub-folders) and projects imported without folder paths;
* the vision model's answer changes crops, image ranking and the cover —
  measurably, and reported in the diagnostics;
* no proposal repeats the same composition back to back;
* the interface fixes (continued sections listed once, legible transparent
  thumbnails).

AI answers come from the local stand-in for Ollama (``tests/ollama_mock.py``):
these tests prove the app *uses* the answers, not how good a real model is.
"""

from __future__ import annotations

import pytest

from ollama_mock import MockOllama
from organized_fixture import PT_SECTIONS, build_organized_pt, pt_section
from behance_studio.assets.folders import backfill_source_folders, build_folder_map, is_numbered, section_type_for
from behance_studio.assets.importer import import_paths
from behance_studio.core.settings import AppSettings
from behance_studio.generation.pipeline import GenerationRequest, generate
from behance_studio.layout.families import CONCEPT_FAMILIES
from behance_studio.planning.fit import placement_violations
from behance_studio.projects.store import Project
from behance_studio.projects.versions import VersionManager


@pytest.fixture(scope="module")
def pt_dir(tmp_path_factory, demo_assets_dir):
    return build_organized_pt(demo_assets_dir, tmp_path_factory.mktemp("pt"))


@pytest.fixture
def mock():
    server = MockOllama()
    yield server
    server.close()


def _check_folders(project, versions) -> None:
    by_id = {a.id: a for a in project.list_assets()}
    vm = VersionManager(project)
    for rec in versions:
        data = vm.load(rec.id)
        rendered = {b.asset_id for s in data.presentation.sections for b in s.blocks if b.asset_id}
        for sp in data.plan.sections:
            if sp.type in ("cover", "closing"):
                continue
            folders = {pt_section(by_id[a]) for a in sp.asset_ids if a in by_id}
            assert len(folders) <= 1, (rec.family, sp.title, folders)
            assert all(a in rendered for a in sp.asset_ids), (rec.family, sp.title)
        assert not placement_violations(data.plan, data.plan.asset_sections)


# ------------------------------------------------------------- folders
@pytest.mark.parametrize("name, kind", [
    ("Logos", "logo"), ("Logotipos", "logo"), ("Outdoors", "outdoor"), ("Videos", "video"), ("Padrão", "visual_language"),
    ("Pattern", "visual_language"), ("Ícones", "visual_language"), ("Rótulos", "packaging"), ("Cartões de visita", "applications"),
    ("Estacionário", "applications"), ("Merchandising", "applications"), ("Brochura", "editorial"), ("Ementa", "editorial"),
    ("Manual de marca", "editorial"), ("Brand Guidelines", "editorial"), ("Redes Sociais", "social"), ("Fotografia", "photography"),
])
def test_real_folder_names_are_recognised(name, kind):
    assert section_type_for(name) == kind


def test_numbered_section_keeps_its_sub_folders_together():
    from types import SimpleNamespace

    fm = build_folder_map([SimpleNamespace(id=str(i), source_folder=f, import_group="") for i, f in enumerate([
        "P/1. Logos/PNG", "P/1. Logos/Versões", "P/2. Embalagens/Rótulos", "P/2. Embalagens/Copos/Final", "P/02 Brand Identity/Logo"])])
    titles = [s.title for s in fm.sections]
    assert titles.count("Logos") == 1 and "Versões" not in titles and titles.count("Embalagens") == 1
    assert fm.subgroup["1"] == "Versões" and fm.subgroup["3"] == "Copos"
    assert is_numbered("01 Logo") and is_numbered("1. Cores") and not is_numbered("2026 campanha") and not is_numbered("Logo")


def test_portuguese_project_keeps_every_image_in_its_folder(projects_dir, pt_dir):
    project = Project.create(projects_dir, "Café Lusitano")
    import_paths(project, [pt_dir])
    result = generate(project, GenerationRequest(families=list(CONCEPT_FAMILIES) + ["editorial", "gallery"], seed=7, render_previews=False))
    _check_folders(project, result.versions)
    titles = [s.title for s in build_folder_map(project.list_assets()).sections]
    assert titles == PT_SECTIONS


def test_projects_imported_without_folders_recover_them(projects_dir, pt_dir):
    """Older projects (or folders dropped one by one) have no folder path:
    it comes back from each file's original location."""
    project = Project.create(projects_dir, "Old project")
    import_paths(project, [pt_dir])
    assets = project.list_assets()
    for a in assets:
        a.source_folder, a.import_group = "", ""
    project.save_assets(assets)
    result = generate(project, GenerationRequest(families=["minimal", "story"], seed=3, render_previews=False))
    assert any("recovered from the original file paths" in n for n in result.notes)
    assert all(pt_section(a) for a in project.list_assets() if a.is_visual)
    _check_folders(project, result.versions)
    # Windows paths too
    from types import SimpleNamespace

    win = [SimpleNamespace(id=str(i), source_folder="", import_group="", source_path=p) for i, p in enumerate([
        r"C:\Users\Ana\Desktop\Cliente\01 Logo\a.png", r"C:\Users\Ana\Desktop\Cliente\02 Packaging\Cups\c.jpg"])]
    assert [a.source_folder for a in backfill_source_folders(win)] == ["Cliente/01 Logo", "Cliente/02 Packaging/Cups"]


def test_script_extras_follow_the_folders(projects_dir, pt_dir):
    project = Project.create(projects_dir, "Scripted")
    import_paths(project, [pt_dir])
    project.write_text("script", "PROJECT: Café Lusitano\nSTRICT: no\n\n## Logo\nIMAGES:\n- logo-principal.png\n\n## Closing\nTITLE: Obrigado\n")
    result = generate(project, GenerationRequest(families=["minimal", "editorial"], seed=5, render_previews=False))
    vm = VersionManager(project)
    by_id = {a.id: a for a in project.list_assets()}
    for rec in result.versions:
        for sp in vm.load(rec.id).plan.sections:
            if sp.source == "script" or sp.type in ("cover", "closing"):
                continue
            assert len({pt_section(by_id[a]) for a in sp.asset_ids if a in by_id}) <= 1, (rec.family, sp.title)


# ---------------------------------------------------------- vision model
def test_vision_answers_steer_crops_ranking_and_cover(mock, projects_dir, pt_dir):
    from behance_studio.ai.service import service_for_project
    from behance_studio.ai.vision import cover_score, subject_box
    from behance_studio.layout.fitting import choose_fit, focal_point

    mock.cover_scores.update({"img_5004.jpg": 0.97, "img_5001.jpg": 0.2, "img_5002.jpg": 0.3, "img_5003.jpg": 0.25, "img_5005.jpg": 0.2})
    mock.boxes["img_5003.jpg"] = [0, 300, 260, 700]  # subject at the far left edge
    s = AppSettings()
    s.ai.base_url = mock.url
    project = Project.create(projects_dir, "AI steered")
    import_paths(project, [pt_dir])
    result = generate(project, GenerationRequest(families=["photo", "story"], seed=2, render_previews=False),
                      ai_service=service_for_project(project, s))
    assets = {a.filename: a for a in project.list_assets()}
    lead, left = assets["IMG_5004.jpg"], assets["IMG_5003.jpg"]
    assert cover_score(lead) == pytest.approx(0.97) and subject_box(left) == [0.0, 0.3, 0.26, 0.7]
    # the crop follows the model's subject and never cuts it
    assert focal_point(left)[0] == pytest.approx(0.13)
    fit = choose_fit(left, 1600, 400)  # a very wide frame: the subject must stay whole
    if fit.mode == "cover":
        x0, y0, x1, y1 = fit.visible
        assert x0 <= 0.01 and y0 <= 0.31 and y1 >= 0.69
    # the model's favourite photograph opens the photographic concepts
    vm = VersionManager(project)
    covers = [next(s.asset_ids[0] for s in vm.load(r.id).plan.sections if s.type == "cover" and s.asset_ids) for r in result.versions]
    assert lead.id in covers
    text = (project.root / "Diagnostics" / "latest.txt").read_text(encoding="utf-8")
    assert "AI influence on the layouts:" in text and "crop focus" in text and "ranking (cover / lead images)" in text


# --------------------------------------------------------------- variety
@pytest.mark.parametrize("organised", [True, False])
def test_no_composition_repeats_back_to_back(projects_dir, pt_dir, demo_assets_dir, organised):
    project = Project.create(projects_dir, "Rhythm")
    import_paths(project, [pt_dir if organised else demo_assets_dir])
    result = generate(project, GenerationRequest(families=list(CONCEPT_FAMILIES), seed=7, render_previews=False))
    vm = VersionManager(project)
    for rec in result.versions:
        data = vm.load(rec.id)
        comps = []
        for s in data.plan.sections:
            if s.type in ("cover", "closing") or not s.meta.get("module"):
                continue
            p = s.meta.get("params") or {}
            comps.append((s.meta["module"], p.get("align", "center"), bool(p.get("rhythm_variant"))))
        repeats = [(a, b) for a, b in zip(comps, comps[1:]) if a == b and a[0] not in ("chapter", "statement")]
        assert not repeats, (rec.family, repeats)
        assert len({c[0] for c in comps}) >= 7, rec.family
        rendered = {b.asset_id for s in data.presentation.sections for b in s.blocks if b.asset_id}
        assert all(a in rendered for s in data.plan.sections for a in s.asset_ids), rec.family
        assert not placement_violations(data.plan, data.plan.asset_sections)


# -------------------------------------------------------------- interface
@pytest.mark.gui
def test_transparent_thumbnails_get_a_contrasting_ground(qapp):
    from PySide6.QtGui import QColor, QImage, QPixmap

    from behance_studio.ui.widgets.common import _transparent_backdrop

    def mark(color: str) -> QPixmap:
        img = QImage(60, 60, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))
        for y in range(20, 40):
            for x in range(20, 40):
                img.setPixelColor(x, y, QColor(color))
        return QPixmap.fromImage(img)

    assert _transparent_backdrop(mark("#2E2017")).lightness() > 200  # dark logo → light ground
    assert _transparent_backdrop(mark("#FFFFFF")).lightness() < 80  # white logo → dark ground
    opaque = QImage(20, 20, QImage.Format.Format_RGB32)
    opaque.fill(QColor("#888888"))
    assert _transparent_backdrop(QPixmap.fromImage(opaque)) is None
