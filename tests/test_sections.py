"""Regression tests: images stay in their intended sections.

Covers the pipeline end to end — import (folder paths preserved), folder →
section assignment, heuristic and AI classification (including wrong AI
answers), every layout family, the AI Creative Director, caching and the
diagnostics report. AI answers come from a local stand-in for Ollama's API
(``tests/ollama_mock.py``); the fixture is the synthetic Butter & Bean set
re-organised like a professional project (``tests/organized_fixture.py``).
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from ollama_mock import MockOllama
from organized_fixture import EXPECTED, ROOT_NAME, build_organized, expected_section
from behance_studio.ai.service import service_for_project
from behance_studio.assets.folders import build_folder_map, clean_name
from behance_studio.assets.importer import analyze_asset, import_paths
from behance_studio.core.settings import AppSettings
from behance_studio.generation.pipeline import GenerationRequest, generate, understand
from behance_studio.layout.engine import ProposalSpec, build_plan, compose
from behance_studio.layout.families import CONCEPT_FAMILIES, available_families
from behance_studio.layout.validate import layout_distance, validate_presentation
from behance_studio.planning.assignment import assign_sections
from behance_studio.planning.fit import enforce_section_fit, placement_violations
from behance_studio.planning.planner import PlanningContext
from behance_studio.projects.store import Project
from behance_studio.projects.versions import VersionManager


@pytest.fixture(scope="module")
def organized_dir(tmp_path_factory, demo_assets_dir):
    return build_organized(demo_assets_dir, tmp_path_factory.mktemp("organized"))


@pytest.fixture
def mock():
    server = MockOllama()
    yield server
    server.close()


def _settings(mock) -> AppSettings:
    s = AppSettings()
    s.ai.base_url = mock.url
    return s


def _project(projects_dir, paths, name="Butter & Bean") -> Project:
    project = Project.create(projects_dir, name)
    import_paths(project, paths)
    return project


def _check_proposal(data, by_id) -> None:
    """Every image is in a section of its own folder, and is rendered."""
    rendered = {b.asset_id for s in data.presentation.sections for b in s.blocks if b.asset_id}
    for sp in data.plan.sections:
        if sp.type in ("cover", "closing"):
            continue
        folders = {expected_section(by_id[a]) for a in sp.asset_ids if a in by_id}
        assert len(folders) <= 1, (data.spec.family, sp.title, sp.meta.get("module"), folders)
        for a in sp.asset_ids:
            assert a in rendered, (data.spec.family, by_id[a].filename, sp.meta.get("module"))
    assert not placement_violations(data.plan, data.plan.asset_sections)
    assert not [i for i in data.quality.issues if i.code == "section_mismatch"]
    shown = {a for s in data.plan.sections if s.type != "cover" for a in s.asset_ids}
    assert {expected_section(by_id[a]) for a in shown if a in by_id} >= {f.split("/")[0] for f in EXPECTED.values()}


# ------------------------------------------------------------------ folders
def test_folder_map_handles_real_world_structures():
    def m(*folders):
        return build_folder_map([SimpleNamespace(id=str(i), source_folder=f, import_group="") for i, f in enumerate(folders)])

    nested = m("P/01 Brand Identity/Typography", "P/01 Brand Identity/Logo", "P/01 Brand Identity/Colour", "P/02 Packaging/Cups",
               "P/02 Packaging/Bags/JPG", "P/03 Campaign/Posters", "P/03 Campaign/Outdoor", "P")
    assert nested.organized and nested.root == "P"
    assert [(s.title, s.type, s.chapter) for s in nested.sections] == [
        ("Logo", "logo", "Brand Identity"), ("Colour", "palette", "Brand Identity"), ("Typography", "typography", "Brand Identity"),
        ("Packaging", "packaging", ""), ("Campaign", "campaign", "")]
    assert nested.subgroup["3"] == "Cups" and nested.subgroup["4"] == "Bags" and "7" not in nested.by_asset  # root file: no folder
    assert m("03 Packaging", "03 Packaging").organized  # one section folder dropped on its own
    assert not m("Butter & Bean - Brand Identity", "Butter & Bean - Brand Identity").organized  # a flat project folder
    assert not m("", "").organized
    unknown = m("P/Brand in Use", "P/Behind the Scenes")
    assert unknown.organized and {s.title for s in unknown.sections} == {"Brand in Use", "Behind the Scenes"}
    assert [s.title for s in m("P/Social", "P/Packaging", "P/Logo").sections] == ["Logo", "Packaging", "Social"]
    assert clean_name("05_social-media") == "Social Media" and clean_name("1. Packaging") == "Packaging"


def test_import_preserves_folders_however_they_are_dropped(projects_dir, organized_dir, tmp_path):
    whole = _project(projects_dir, [organized_dir], "Whole")
    paths = {f"{a.source_folder}/{a.filename}" for a in whole.list_assets()}
    assert f"{ROOT_NAME}/03 Packaging/Boxes/JPG/logo-on-box.jpg" in paths and f"{ROOT_NAME}/04 Campaign/Outdoor/01.jpg" in paths

    # Section folders selected and dropped together keep their own names.
    separate = _project(projects_dir, [organized_dir / "03 Packaging", organized_dir / "05 Social Media"], "Separate")
    assert {a.source_folder.split("/")[0] for a in separate.list_assets()} == {"03 Packaging", "05 Social Media"}
    assert assign_sections(separate.list_assets()).by_folders

    # A ZIP of the organised project.
    archive = tmp_path / "Butter & Bean.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for f in organized_dir.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(organized_dir.parent))
    zipped = _project(projects_dir, [archive], "Zipped")
    asg = assign_sections(zipped.list_assets())
    assert asg.by_folders and [s.title for s in asg.folder_map.sections] == ["Logo", "Brand Elements", "Packaging", "Campaign",
                                                                                 "Social Media", "Photography"]

    # Files dropped one by one have no folder organisation.
    loose = _project(projects_dir, [organized_dir / "01 Logo" / "primary.png"], "Loose")
    assert [a.source_folder for a in loose.list_assets()] == [""]


def test_section_folders_beat_misleading_file_names(projects_dir, organized_dir):
    project = _project(projects_dir, [organized_dir])
    kinds = {f"{a.source_folder.split('/', 1)[1]}/{a.filename}": a.effective_kind for a in project.list_assets()}
    assert kinds["03 Packaging/IMG_4021.jpg"] == "packaging"  # camera name ("IMG" = photo) no longer wins
    assert kinds["03 Packaging/Boxes/JPG/logo-on-box.jpg"] in ("packaging", "product", "mockup")  # "logo" in the name
    assert kinds["06 Photography/IMG_5001.jpg"] == "photo"
    asg = assign_sections(project.list_assets())
    for a in project.list_assets():
        assert asg.placements[a.id].source == "folder" and asg.placements[a.id].key.split("/")[0] == expected_section(a)


# --------------------------------------------------------------- planning
def test_every_layout_family_keeps_images_in_their_folder_sections(projects_dir, organized_dir):
    project = _project(projects_dir, [organized_dir])
    assets = project.list_assets()
    by_id = {a.id: a for a in assets}
    directives, direction = understand(project, assets)
    asg = assign_sections(assets, "auto", directives.language)
    ctx = PlanningContext(project.name, assets, directives, direction, sections=asg)
    presentations = {}
    for family in available_families():
        spec = ProposalSpec(family=family, seed=11)
        plan = build_plan(ctx, spec)
        report = enforce_section_fit(plan, by_id, asg)
        assert not report.moved, (family, report.moved)  # right by construction, not by repair
        plan.asset_sections = asg.to_plan()
        pres = compose(plan, by_id, direction, spec)
        quality = validate_presentation(pres, by_id, plan)
        assert quality.errors == [], (family, [i.message for i in quality.errors])
        _check_proposal(SimpleNamespace(spec=spec, plan=plan, presentation=pres, quality=quality), by_id)
        order = [asg.order_of(s.meta["folder_section"]) for s in plan.sections if s.meta.get("folder_section")]
        assert order == sorted(order), family  # sections follow the folder order
        presentations[family] = pres
    for a in CONCEPT_FAMILIES:  # still five genuinely different presentations
        for b in CONCEPT_FAMILIES:
            if a < b:
                assert layout_distance(presentations[a], presentations[b]) > 0.25, (a, b)


def test_ai_storyboard_cannot_mix_or_drop_sections(mock, projects_dir, organized_dir):
    """An AI director that mixes folders and skips a whole section is corrected."""
    def mixing(text: str) -> dict:
        sections: dict[str, list[str]] = {}
        for handle, section in re.findall(r"^(A\d+) · SECTION “([^”]+)”", text, flags=re.M):
            sections.setdefault(section, []).append(handle)
        names = list(sections)
        mixed = [{"module": "duo", "assets": [sections[a][0], sections[b][0]], "chapter": "none", "message": -1, "why": "contrast"}
                 for a, b in zip(names, names[1:])]
        return {"idea": "Mix everything.", "cover": {"module": "cover_logo", "assets": [], "message": -1}, "sections": mixed[:-1],
                "closing_message": -1, "left_out": []}

    import ollama_mock

    original = mock.answer

    def answer(body):
        text = ollama_mock._texts(body)
        return json.dumps(mixing(text)) if "CONCEPT TO DEVELOP" in text else original(body)

    mock.answer = answer
    project = _project(projects_dir, [organized_dir])
    result = generate(project, GenerationRequest(families=["minimal", "layered"], seed=3, render_previews=False),
                      ai_service=service_for_project(project, _settings(mock)))
    by_id = {a.id: a for a in project.list_assets()}
    vm = VersionManager(project)
    for record in result.versions:
        data = vm.load(record.id)
        assert data.sources["director"] == "ai"
        _check_proposal(data, by_id)
        assert any("Section check" in n for n in data.notes)  # the corrections are reported


# ------------------------------------------------------------ AI decisions
def test_wrong_ai_answers_never_move_images_end_to_end(mock, projects_dir, organized_dir):
    mock.overrides.update({"img_4021.jpg": ("photo", "photograph"), "primary.png": ("social", "flat_artwork"),
                           "img_5001.jpg": ("packaging", "photographed_scene"), "sheet-1.png": ("palette", "document_sheet")})
    project = _project(projects_dir, [organized_dir])
    families = list(CONCEPT_FAMILIES) + ["editorial", "gallery"]
    result = generate(project, GenerationRequest(families=families, seed=5, render_previews=True),
                      ai_service=service_for_project(project, _settings(mock)))
    assert len(result.versions) == len(families) and not result.failures
    assets = {a.id: a for a in project.list_assets()}
    by_name = {f"{a.source_folder.split('/', 1)[1]}/{a.filename}": a for a in assets.values()}
    # The model saw the image itself (base64 pixels, not only names).
    assert all(b["messages"][1]["images"] and len(b["messages"][1]["images"][0]) > 1000 for b in mock.chats("Allowed kinds"))
    # Wrong types inside section folders are refused, with the reason recorded.
    pkg = by_name["03 Packaging/IMG_4021.jpg"]
    assert pkg.effective_kind == "packaging" and "contradicts the folder" in pkg.analysis["ai"]["decision"]
    assert by_name["01 Logo/primary.png"].effective_kind == "logo"
    # A refinement within the section is applied (pattern sheet → palette in Brand Elements).
    sheet = by_name["02 Brand Elements/sheet-1.png"]
    assert sheet.effective_kind == "palette" and sheet.analysis["ai"]["applied"] and sheet.kind_source == "ai"
    # Every asset stores its intended section.
    for a in assets.values():
        assert a.analysis["section"]["source"] == "folder" and a.analysis["section"]["title"]
    vm = VersionManager(project)
    for record in result.versions:
        _check_proposal(vm.load(record.id), assets)

    # Diagnostics: path, folder section, AI result, final section, placement, AI or fallback, reasons.
    report = json.loads((project.root / "Diagnostics" / "latest.json").read_text(encoding="utf-8"))
    row = next(r for r in report["assets"] if r["file"].endswith("03 Packaging/IMG_4021.jpg"))
    assert row["folder_section"]["title"] == "Packaging" and row["ai"]["kind"] == "photo" and row["ai"]["applied"] is False
    assert row["final_type"] == "packaging" and row["type_source"].startswith("measured")
    assert row["intended_section"]["title"] == "Packaging" and row["intended_section"]["source"] == "folder"
    body = [p for p in row["placements"] if p["section_type"] not in ("cover", "closing")]  # a cover image may reappear there
    assert len(body) >= len(families) and all(p["section"] == "Packaging" and p["rendered"] for p in body), json.dumps(body)
    assert all(not run["violations"] and not run["planned_but_not_rendered"] for run in report["proposals"])
    text = (project.root / "Diagnostics" / "latest.txt").read_text(encoding="utf-8")
    assert "contradicts the folder" in text and "all images in their intended sections" in text


def test_unorganised_project_is_grouped_by_ai(mock, projects_dir, demo_assets_dir, tmp_path):
    flat = tmp_path / "flat"
    flat.mkdir()
    for f in ("04 Packaging/coffee-bag-mockup.jpg", "06 Social Media/instagram-post-01.jpg", "03 Photography/DSC_0142.jpg",
              "01 Logo/butter-bean-logo-primary.png", "06 Social Media/instagram-post-02.jpg"):
        shutil.copy(demo_assets_dir / f, flat / Path(f).name)
    project = Project.create(projects_dir, "Loose")
    import_paths(project, sorted(flat.iterdir()))  # files, not a folder
    service = service_for_project(project, _settings(mock))
    service.classify_assets(project, project.list_assets())
    asg = assign_sections(project.list_assets())
    assert not asg.by_folders
    sources = {project.get_asset(a).filename: p for a, p in asg.placements.items()}
    assert sources["coffee-bag-mockup.jpg"].type == "packaging" and sources["coffee-bag-mockup.jpg"].source == "ai"
    assert sources["instagram-post-01.jpg"].key == sources["instagram-post-02.jpg"].key == "kind:social"


def test_content_mode_lets_ai_reorganise_when_asked(mock, projects_dir, organized_dir):
    mock.overrides["img_4021.jpg"] = ("photo", "photograph")
    project = _project(projects_dir, [organized_dir])
    project.config.section_source = "content"
    project.save_config()
    service = service_for_project(project, _settings(mock))
    service.classify_assets(project, project.list_assets())
    pkg = next(a for a in project.list_assets() if a.filename == "IMG_4021.jpg")
    assert pkg.effective_kind == "photo"  # the user asked for content-based organisation
    asg = assign_sections(project.list_assets(), "content")
    assert not asg.by_folders and asg.placements[pkg.id].type == "photography"


# ------------------------------------------------------- metadata & names
def test_missing_metadata_and_root_level_files(projects_dir, organized_dir, demo_assets_dir):
    project = _project(projects_dir, [organized_dir])
    assets = project.list_assets()
    # A project imported by an older version: no source_folder, only import_group.
    for a in assets:
        a.source_folder = ""
    legacy = assign_sections(assets)
    assert legacy.by_folders and {s.title for s in legacy.folder_map.sections} >= {"Logo", "Packaging", "Social Media"}
    # Missing analysis must not break assignment.
    assets[0].analysis = {}
    assert assign_sections(assets).placements[assets[0].id]
    # A loose file next to the folders joins the folder section of its type.
    from PIL import Image

    with Image.open(demo_assets_dir / "04 Packaging" / "pastry-box.jpg") as im:
        im.rotate(90, expand=True).save(projects_dir / "IMG_9001.jpg", quality=90)  # new content: not a duplicate
    import_paths(project, [projects_dir / "IMG_9001.jpg"])
    loose = next(a for a in project.list_assets() if a.filename == "IMG_9001.jpg")
    assert loose.source_folder == ""
    loose.user_kind = "packaging"
    asg = assign_sections([a for a in project.list_assets() if a.id != loose.id] + [loose])
    assert asg.placements[loose.id].title == "Packaging" and asg.placements[loose.id].source == "user"


def test_duplicate_and_similar_file_names(projects_dir, organized_dir):
    project = _project(projects_dir, [organized_dir])
    named_01 = [a for a in project.list_assets() if a.filename == "01.jpg"]
    assert len(named_01) == 3  # Posters/01.jpg, Outdoor/01.jpg, Social Media/01.jpg
    asg = assign_sections(project.list_assets())
    assert {asg.placements[a.id].title for a in named_01} == {"Campaign", "Social Media"}
    box = next(a for a in project.list_assets() if a.filename == "logo-on-box.jpg")
    assert asg.placements[box.id].title == "Packaging"  # "logo" in the name does not move it to Logo
    result = generate(project, GenerationRequest(families=["minimal", "story"], seed=2, render_previews=False))
    by_id = {a.id: a for a in project.list_assets()}
    for record in result.versions:
        _check_proposal(VersionManager(project).load(record.id), by_id)


# ---------------------------------------------------------------- caching
def test_analysis_is_cached_by_content(mock, projects_dir, organized_dir, tmp_path):
    settings = _settings(mock)
    project = _project(projects_dir, [organized_dir], "First")
    stills = len([a for a in project.list_assets() if a.is_visual])
    service_for_project(project, settings).classify_assets(project, project.list_assets())
    first = len(mock.chats("Allowed kinds"))
    assert first == stills
    # Generating again, and importing the same files into another project: nothing is re-analysed.
    generate(project, GenerationRequest(families=["minimal"], render_previews=False), ai_service=service_for_project(project, settings))
    other = _project(projects_dir, [organized_dir], "Second")
    service_for_project(other, settings).classify_assets(other, other.list_assets())
    assert len(mock.chats("Allowed kinds")) == first
    # Re-analysing an image (e.g. after an update) keeps its AI result and section.
    asset = next(a for a in project.list_assets() if a.filename == "IMG_4021.jpg")
    asset.analysis["section"] = {"title": "Packaging"}
    analyze_asset(project, asset, force=True)
    assert asset.analysis.get("ai") and asset.analysis["section"]["title"] == "Packaging"
    # A later failed attempt (e.g. Ollama not running) never discards an earlier answer about the same image.
    from behance_studio.ai.orchestrator import AIService

    before = dict(asset.analysis["ai"])
    AIService._record_unanalysed(asset, "not run: Ollama is not running")
    assert asset.analysis["ai"]["kind"] == before["kind"] and asset.analysis["ai"]["decision"] == before["decision"]
    assert asset.analysis["ai"]["last_attempt"] == "not run: Ollama is not running"
    # A changed image is analysed again — only that one.
    changed_dir = tmp_path / "changed" / "03 Packaging"
    changed_dir.mkdir(parents=True)
    from PIL import Image

    with Image.open(organized_dir / "03 Packaging" / "IMG_4021.jpg") as im:
        im.rotate(180).save(changed_dir / "IMG_4021.jpg", quality=90)
    third = _project(projects_dir, [changed_dir], "Third")
    service_for_project(third, settings).classify_assets(third, third.list_assets())
    assert len(mock.chats("Allowed kinds")) == first + 1
    # Another model is another analysis configuration.
    mock.models.append("qwen3-vl:4b")
    settings.ai.model = "qwen3-vl:4b"
    service_for_project(third, settings).classify_assets(third, third.list_assets())
    assert len(mock.chats("Allowed kinds")) == first + 2


def test_cli_diagnose(projects_dir, organized_dir, capsys):
    from behance_studio import cli

    project = _project(projects_dir, [organized_dir])
    assert cli.main(["diagnose", str(project.root), "--now"]) == 0
    out = capsys.readouterr().out
    assert "Sections from: your folders" in out and "03 Packaging/IMG_4021.jpg" in out and "Packaging (folder)" in out
