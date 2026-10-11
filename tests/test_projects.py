import json
from pathlib import Path

import pytest

from behance_studio.core.errors import ProjectError
from behance_studio.projects.library import ProjectLibrary
from behance_studio.projects.models import AssetRecord, VersionRecord, new_id
from behance_studio.projects.store import Project


def test_create_and_reopen(projects_dir: Path):
    project = Project.create(projects_dir, "Butter & Bean")
    assert project.root.name == "Butter & Bean"
    for sub in ("Assets", "Cache", "Versions", "Exports", "Trash"):
        assert (project.root / sub).is_dir()
    project.write_text("brief", "Warm and welcoming.")
    asset = AssetRecord(id=new_id(), media_type="image", filename="logo.png", rel_path="Assets/logo.png", width=10, height=5)
    project.save_asset(asset)

    reopened = Project.open(project.root)
    assert reopened.config.name == "Butter & Bean"
    assert reopened.config.id == project.config.id
    assert reopened.brief_text == "Warm and welcoming."
    assets = reopened.list_assets()
    assert len(assets) == 1 and assets[0].filename == "logo.png" and assets[0].aspect == 2.0


def test_create_requires_name(projects_dir: Path):
    with pytest.raises(ProjectError):
        Project.create(projects_dir, "   ")


def test_duplicate_names_get_unique_folders(projects_dir: Path):
    a = Project.create(projects_dir, "Same")
    b = Project.create(projects_dir, "Same")
    assert a.root != b.root


def test_rename_project(projects_dir: Path):
    project = Project.create(projects_dir, "Old Name")
    project.rename("Nova Marca Ção")
    assert project.root.name == "Nova Marca Ção"
    assert Project.open(project.root).config.name == "Nova Marca Ção"


def test_open_missing_folder(projects_dir: Path):
    with pytest.raises(ProjectError):
        Project.open(projects_dir / "does-not-exist")


def test_open_non_project_folder(projects_dir: Path):
    (projects_dir / "random").mkdir()
    with pytest.raises(ProjectError):
        Project.open(projects_dir / "random")


def test_damaged_project_json(projects_dir: Path):
    project = Project.create(projects_dir, "Damaged")
    (project.root / "project.json").write_text("{not json")
    with pytest.raises(ProjectError):
        Project.open(project.root)


def test_missing_project_json_is_recovered(projects_dir: Path):
    project = Project.create(projects_dir, "Recover")
    (project.root / "project.json").unlink()
    reopened = Project.open(project.root)
    assert reopened.config.name == "Recover"


def test_repair_rebuilds_versions_from_disk(projects_dir: Path):
    project = Project.create(projects_dir, "Repair")
    folder = project.versions_dir / "001"
    folder.mkdir()
    rec = VersionRecord(id=new_id(), number=1, name="Editorial", family="editorial", seed=1, folder="Versions/001")
    (folder / "proposal.json").write_text(json.dumps({"version": rec.to_dict()}))
    # Simulate a lost database.
    for p in project.root.glob("project.db*"):
        p.unlink()
    reopened = Project.open(project.root)
    versions = reopened.list_versions()
    assert [v.id for v in versions] == [rec.id]


def test_missing_asset_detection(projects_dir: Path, tmp_path: Path):
    project = Project.create(projects_dir, "Missing")
    f = project.assets_dir / "a.png"
    f.write_bytes(b"x")
    asset = AssetRecord(id=new_id(), media_type="image", filename="a.png", rel_path="Assets/a.png")
    project.save_asset(asset)
    f.unlink()
    changed = project.refresh_missing()
    assert changed and changed[0].status == "missing"


def test_library_recent(projects_dir: Path):
    lib = ProjectLibrary()
    p1 = Project.create(projects_dir, "One")
    p2 = Project.create(projects_dir, "Two")
    lib.register(p1)
    lib.register(p2)
    names = [e.name for e in lib.recent()]
    assert set(names) == {"One", "Two"}
    lib.forget(p1.root)
    assert [e.name for e in lib.recent()] == ["Two"]
