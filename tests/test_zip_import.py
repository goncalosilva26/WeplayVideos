"""ZIP deliveries: imported like folders, safely."""

import zipfile

import pytest

from behance_studio.assets.importer import import_paths
from behance_studio.projects.store import Project


def test_zip_import_keeps_folders_and_cleans_up(projects_dir, demo_assets_dir, tmp_path):
    archive = tmp_path / "Butter & Bean delivery.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in sorted(demo_assets_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".txt"):
                zf.write(path, f"Delivery/{path.relative_to(demo_assets_dir).as_posix()}")
        zf.writestr("__MACOSX/._junk.png", b"junk")
    before = archive.read_bytes()
    project = Project.create(projects_dir, "Zip")
    report = import_paths(project, [archive], copy=False)
    assert len(report.added) >= 15 and not report.errors
    assert report.brief_imported  # brief.txt inside the archive was adopted
    assert all(project.resolve_asset_path(a).exists() for a in project.list_assets())
    assert any("01 Logo" in (a.import_group or "") for a in project.list_assets())
    assert not any((project.cache_dir / "unzip").iterdir())  # extraction removed
    assert archive.read_bytes() == before  # original untouched


def test_malicious_zip_is_rejected(projects_dir, tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ok.png", b"not really")
        zf.writestr("../../outside.txt", b"escape")
    project = Project.create(projects_dir, "Evil")
    report = import_paths(project, [archive])
    assert report.errors and "unsafe path" in report.errors[0][1]
    assert not (tmp_path / "outside.txt").exists()
    assert not (projects_dir / "outside.txt").exists()
    assert project.list_assets() == []


def test_corrupt_zip_reports_an_error(projects_dir, tmp_path):
    archive = tmp_path / "broken.zip"
    archive.write_bytes(b"PK\x03\x04 definitely not a zip")
    project = Project.create(projects_dir, "Broken")
    report = import_paths(project, [archive])
    assert report.errors and "not a readable ZIP" in report.errors[0][1]
