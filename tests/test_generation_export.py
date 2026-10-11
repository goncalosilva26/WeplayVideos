"""End-to-end: generate proposals, manage versions/trash, edit, export."""

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from behance_studio.assets.importer import import_paths
from behance_studio.core.errors import ProjectError, ScriptError
from behance_studio.core.qtsupport import ensure_gui_application
from behance_studio.export.exporter import ExportOptions, export_versions
from behance_studio.export.html_package import validate_html_package
from behance_studio.generation import editing
from behance_studio.generation.pipeline import STAGES, GenerationRequest, generate
from behance_studio.projects.store import Project
from behance_studio.projects.versions import VersionManager
from behance_studio.render.browser import browser_available

pytestmark = pytest.mark.skipif(not browser_available(), reason="needs a Chromium-based browser")


@pytest.fixture(scope="module")
def generated(tmp_path_factory, demo_assets_dir):
    ensure_gui_application()
    root = tmp_path_factory.mktemp("gen")
    project = Project.create(root, "Butter & Bean")
    events = []
    result = generate(project, GenerationRequest(seed=101, import_paths=[demo_assets_dir]), progress=events.append)
    return project, result, events


def test_generation_produces_six_complete_proposals(generated):
    project, result, events = generated
    assert len(result.versions) == 6 and not result.failures
    assert {v.family for v in result.versions} == {"editorial", "cinematic", "split", "posters", "gallery", "modular"}
    assert result.category == "brand_identity" and result.language == "en"
    manager = VersionManager(project)
    for record in result.versions:
        assert manager.thumb_path(record).exists() and manager.strip_path(record).exists()
        proposal = manager.load(record.id)
        assert proposal.quality.passed, [i.message for i in proposal.quality.errors]
        assert proposal.quality.metrics.get("rendered_check") == 1.0
        types = [s.type for s in proposal.presentation.sections]
        assert types[0] == "cover" and types[-1] == "closing"
        assert not any(s.meta.get("fallback") for s in proposal.presentation.sections), record.family
    # progress covered all ten stages with real, monotonic fractions
    stages = [e.stage for e in events]
    assert all(s in stages for s in STAGES)
    fractions = [e.fraction for e in events if e.fraction is not None]
    assert fractions == sorted(fractions) and fractions[-1] == pytest.approx(1.0)


def test_versions_survive_reopen(generated):
    project, result, _ = generated
    reopened = Project.open(project.root)
    ids = [v.id for v in VersionManager(reopened).list()]
    assert ids == [v.id for v in result.versions]


def test_generating_again_never_overwrites(generated):
    project, result, _ = generated
    before = {v.id: (VersionManager(project).folder(v) / "proposal.json").read_text() for v in result.versions}
    more = generate(project, GenerationRequest(seed=202, families=["gallery", "modular"], count=3, render_previews=False))
    assert len(more.versions) == 3
    assert [v.family for v in more.versions] == ["gallery", "modular", "gallery"]
    for vid, text in before.items():
        record = project.get_version(vid)
        assert (VersionManager(project).folder(record) / "proposal.json").read_text() == text
    VersionManager(project).trash([v.id for v in more.versions])


def test_trash_restore_delete_cycle(generated):
    project, result, _ = generated
    manager = VersionManager(project)
    a, b = result.versions[1], result.versions[2]
    assets_before = sorted(p.name for p in project.assets_dir.rglob("*") if p.is_file())
    assert manager.trash([a.id, b.id]) == 2
    active = {v.id for v in manager.list()}
    assert a.id not in active and b.id not in active
    assert (project.trash_dir / "002").exists()
    assert manager.restore([a.id]) == 1
    assert manager.load(a.id).spec.family == a.family
    with pytest.raises(ProjectError):
        manager.delete_permanently([a.id])  # must be trashed first
    assert manager.delete_permanently([b.id]) == 1
    assert project.get_version(b.id) is None
    assert sorted(p.name for p in project.assets_dir.rglob("*") if p.is_file()) == assets_before
    # other proposals intact
    for v in manager.list():
        assert manager.load(v.id).presentation.sections


def test_rename_favorite_preferred_duplicate(generated):
    project, result, _ = generated
    manager = VersionManager(project)
    rec = result.versions[0]
    manager.rename(rec.id, "Hero option")
    manager.set_favorite(rec.id, True)
    manager.set_preferred(rec.id)
    reopened = Project.open(project.root)
    m2 = VersionManager(reopened)
    assert m2.get(rec.id).name == "Hero option" and m2.get(rec.id).favorite
    assert m2.preferred().id == rec.id
    dup = m2.duplicate(rec.id)
    assert dup.id != rec.id and dup.parent_id == rec.id
    assert m2.load(dup.id).presentation.to_dict() == m2.load(rec.id).presentation.to_dict()


def test_editing_with_history_and_script_lock(generated, tmp_path):
    project, result, _ = generated
    manager = VersionManager(project)
    rec = result.versions[0]
    proposal = manager.load(rec.id)
    section = next(sp for sp in proposal.plan.sections if sp.type == "packaging")
    edited = editing.edit_section(project, proposal, section.id, {"title": "Our packaging", "background": "#EFE7DA", "spacing": 1.3})
    editing.save_and_preview(project, rec.id, edited, "Edit packaging")
    reloaded = manager.load(rec.id)
    sec = next(s for s in reloaded.presentation.sections if s.plan_id == section.id)
    assert any(b.text == "Our packaging" for b in sec.blocks)
    history = manager.history(rec.id)
    assert history and history[0][2] == "Edit packaging"
    restored = manager.restore_state(rec.id, history[0][0])
    assert not any(b.text == "Our packaging" for s in restored.presentation.sections for b in s.blocks)
    regenerated = editing.regenerate_section(project, reloaded, section.id)
    assert regenerated.spec.overrides[section.id]["variant_seed"] == 1
    # script-locked content requires explicit override
    locked = manager.load(rec.id)
    locked.plan.sections[1].locked = True
    with pytest.raises(ScriptError):
        editing.edit_section(project, locked, locked.plan.sections[1].id, {"body": "changed"})
    ok = editing.edit_section(project, locked, locked.plan.sections[1].id, {"body": "changed"}, allow_script_override=True)
    assert any("overridden" in n for n in ok.notes)


def test_apply_other_family_keeps_text(generated):
    project, result, _ = generated
    manager = VersionManager(project)
    proposal = manager.load(result.versions[0].id)
    other = editing.apply_family(project, proposal, "modular")
    assert other.presentation.family == "modular"
    assert other.quality.passed


def _export(project, ids, formats, out, **kw):
    return export_versions(project, ids, ExportOptions(formats=formats, destination=out, **kw))


def test_export_all_formats(generated, tmp_path):
    project, result, _ = generated
    rec = result.versions[3]
    out = tmp_path / "exports"
    report = _export(project, [rec.id], ["pdf", "pdf_a4", "jpg", "png", "webp", "tiff", "html", "zip", "text"], out)
    assert not report.failures, report.failures
    by_fmt = {o.format: o for _, o in report.outputs}
    assert set(by_fmt) == {"pdf", "pdf_a4", "jpg", "png", "webp", "tiff", "html", "zip", "text"}
    pdf = PdfReader(str(by_fmt["pdf"].paths[0]))
    assert len(pdf.pages) >= 1 and float(pdf.pages[0].mediabox.width) == pytest.approx(1050, abs=1)
    a4 = PdfReader(str(by_fmt["pdf_a4"].paths[0]))
    for page in a4.pages:
        assert float(page.mediabox.width) == pytest.approx(595.3, abs=1)
        assert float(page.mediabox.height) == pytest.approx(841.9, abs=1)
    proposal = VersionManager(project).load(rec.id)
    total = round(proposal.presentation.height)
    for fmt in ("jpg", "png", "tiff"):
        heights = 0
        for path in by_fmt[fmt].paths:
            with Image.open(path) as im:
                assert im.width == 1400
                heights += im.height
        assert abs(heights - total) <= 2 * len(by_fmt[fmt].paths)
    for path in by_fmt["webp"].paths:
        with Image.open(path) as im:
            assert im.height <= 16383
    html_dir = by_fmt["html"].paths[0]
    assert not validate_html_package(html_dir)
    index = (html_dir / "index.html").read_text()
    assert "file://" not in index and "Cache" not in index
    with zipfile.ZipFile(by_fmt["zip"].paths[0]) as zf:
        names = zf.namelist()
        assert zf.testzip() is None
        assert any("/PDF/" in n for n in names) and any("/HTML/" in n and n.endswith("index.html") for n in names)
    text = by_fmt["text"].paths[0].read_text()
    assert "Butter & Bean" in text
    # exports are recorded
    assert project.list_exports(rec.id)


def test_export_never_overwrites_and_custom_width(generated, tmp_path):
    project, result, _ = generated
    rec = result.versions[0]
    out = tmp_path / "x"
    first = _export(project, [rec.id], ["jpg"], out, width=700, long_image_mode="sections")
    second = _export(project, [rec.id], ["jpg"], out, width=700, long_image_mode="sections")
    a = set(first.files)
    b = set(second.files)
    assert a and b and not (a & b)
    for path in b:
        with Image.open(path) as im:
            assert im.width == 700


def test_export_selected_sections_and_segments(generated, tmp_path):
    project, result, _ = generated
    rec = result.versions[0]
    proposal = VersionManager(project).load(rec.id)
    chosen = [s.id for s in proposal.presentation.sections[:2]]
    report = _export(project, [rec.id], ["png", "pdf"], tmp_path, section_ids=chosen, long_image_mode="segments", segment_height=1200)
    assert not report.failures
    pngs = [p for _, o in report.outputs if o.format == "png" for p in o.paths]
    expected = sum(s.height for s in proposal.presentation.sections[:2])
    assert len(pngs) >= 2
    assert abs(sum(Image.open(p).height for p in pngs) - expected) <= 2 * len(pngs)
    names = [p.name for p in pngs]
    assert names == sorted(names) and names[0].endswith("_01.png")


def test_missing_script_reference_policy(tmp_path, demo_assets_dir, generated):
    project, _, _ = generated
    project.write_text("script", "## Cover\nTITLE: X\nIMAGES: does-not-exist.jpg\n## Closing\nTITLE: End\n")
    try:
        with pytest.raises(ScriptError):
            generate(project, GenerationRequest(seed=5, families=["editorial"], render_previews=False, missing_reference_policy="abort"))
        res = generate(project, GenerationRequest(seed=5, families=["editorial"], render_previews=False))
        assert any(i.code == "missing_ref" for i in res.script_issues)
        assert len(res.versions) == 1
        VersionManager(project).trash([v.id for v in res.versions])
    finally:
        project.write_text("script", "")
