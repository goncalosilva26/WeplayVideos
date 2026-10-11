import hashlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from behance_studio.assets import media
from behance_studio.assets.analysis import analyze_image, hamming, phash
from behance_studio.assets.derivatives import render_source, still_frame_path, thumbnail_path
from behance_studio.assets.importer import import_paths
from behance_studio.core.qtsupport import ensure_gui_application
from behance_studio.projects.store import Project


@pytest.fixture(scope="module", autouse=True)
def _gui():
    ensure_gui_application()


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def demo_project(projects_dir, demo_assets_dir):
    project = Project.create(projects_dir, "Butter & Bean")
    report = import_paths(project, [demo_assets_dir], workers=4)
    return project, report


def test_import_demo_folder_preserves_originals(projects_dir, demo_assets_dir):
    before = _hash_tree(demo_assets_dir)
    project = Project.create(projects_dir, "Preserve")
    report = import_paths(project, [demo_assets_dir], workers=4)
    assert _hash_tree(demo_assets_dir) == before, "source files must never be modified"
    assert len(report.added) >= 24
    assert not report.errors
    assert report.brief_imported
    assert "Butter & Bean" in project.brief_text
    for asset in project.list_assets():
        assert project.resolve_asset_path(asset).exists()
        assert asset.rel_path.startswith("Assets/")
        assert asset.sha256 and asset.width > 0 and asset.height > 0
        assert thumbnail_path(project, asset) is not None


def test_reimport_detects_duplicates(demo_project, demo_assets_dir):
    project, first = demo_project
    second = import_paths(project, [demo_assets_dir], workers=2)
    assert not second.added
    assert len(second.duplicates) == len(first.added)


def test_classification_of_demo_assets(demo_project):
    project, _ = demo_project
    kinds = {a.filename: a.effective_kind for a in project.list_assets()}
    assert kinds["butter-bean-logo-primary.png"] == "logo"
    assert kinds["butter-bean-monogram.png"] in {"monogram", "logo"}
    assert kinds["colour-palette.png"] == "palette"
    assert kinds["typography-specimen.png"] == "typography"
    assert kinds["poster-specialty-coffee.jpg"] == "poster"
    assert kinds["billboard-48-sheet.jpg"] == "outdoor"
    assert kinds["instagram-post-01.jpg"] == "social"
    assert kinds["coffee-bag-mockup.jpg"] == "packaging"
    assert kinds["DSC_0142.jpg"] in {"photo", "product", "lifestyle"}
    assert kinds["brand-teaser.mp4"] == "video"
    assert kinds["logo-animation.gif"] == "motion"
    for asset in project.list_assets():
        assert 0 <= asset.kind_confidence <= 1
        assert asset.kind_source == "heuristic"


def test_media_metadata(demo_project):
    project, _ = demo_project
    by_name = {a.filename: a for a in project.list_assets()}
    video = by_name["brand-teaser.mp4"]
    assert video.width == 1280 and video.height == 720
    assert 1.5 < video.duration < 3.0
    gif = by_name["logo-animation.gif"]
    assert gif.animated and gif.frame_count == 16
    assert by_name["butter-bean-logo-primary.png"].has_alpha
    assert not by_name["DSC_0142.jpg"].has_alpha
    svg = by_name["monogram.svg"]
    assert svg.media_type == "svg" and svg.width == 400
    # still frames for motion assets
    assert still_frame_path(project, video).exists()
    assert still_frame_path(project, gif).exists()


def test_corrupted_and_unsupported_files(projects_dir, tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    good = Image.new("RGB", (300, 200), (200, 50, 50))
    good.save(src / "good.jpg")
    data = (src / "good.jpg").read_bytes()
    (src / "truncated.jpg").write_bytes(data[: len(data) // 3])
    (src / "garbage.png").write_bytes(b"this is not an image at all" * 10)
    (src / "notes.xyz").write_text("unsupported")
    project = Project.create(projects_dir, "Corrupt")
    report = import_paths(project, [src], workers=2)
    names = {a.filename for a in report.added}
    assert names == {"good.jpg"}
    error_names = {Path(p).name for p, _ in report.errors}
    assert {"truncated.jpg", "garbage.png"} <= error_names
    assert any(Path(p).name == "notes.xyz" for p, _ in report.skipped)


def test_unicode_and_extension_mismatch(projects_dir, tmp_path):
    src = tmp_path / "Ação & Café (final)"
    src.mkdir()
    Image.new("RGBA", (120, 80), (0, 0, 0, 0)).save(src / "logótipo çáé – v2.png")
    Image.new("RGB", (150, 100), (0, 100, 0)).save(src / "actually-png.jpg", format="PNG")
    project = Project.create(projects_dir, "Unicode")
    report = import_paths(project, [src], workers=2)
    assert not report.errors, report.errors
    names = {a.filename for a in report.added}
    assert "logótipo çáé – v2.png" in names
    mismatch = next(a for a in report.added if a.filename == "actually-png.jpg")
    assert mismatch.width == 150


def test_nested_folders_keep_groups(projects_dir, tmp_path):
    src = tmp_path / "Delivery"
    (src / "Social" / "Stories").mkdir(parents=True)
    Image.new("RGB", (1080, 1920), (240, 200, 90)).save(src / "Social" / "Stories" / "story.jpg")
    project = Project.create(projects_dir, "Nested")
    report = import_paths(project, [src], workers=1)
    asset = report.added[0]
    assert asset.import_group == "Social/Stories"
    assert asset.rel_path == "Assets/Social/Stories/story.jpg"


def test_near_duplicates_and_before_after(projects_dir, tmp_path):
    src = tmp_path / "retouch"
    src.mkdir()
    rng = np.random.default_rng(0)
    base = (rng.random((600, 800, 3)) * 255).astype(np.uint8)
    base = np.asarray(Image.fromarray(base).resize((80, 60)).resize((800, 600), Image.Resampling.BICUBIC))
    img = Image.fromarray(base)
    img.save(src / "portrait_03_before.jpg", quality=95)
    Image.fromarray(np.clip(base.astype(int) + 12, 0, 255).astype(np.uint8)).save(src / "portrait_03_after.jpg", quality=95)
    img.resize((400, 300)).save(src / "copy-small.jpg", quality=80)
    project = Project.create(projects_dir, "Retouch")
    report = import_paths(project, [src], workers=2)
    by_name = {a.filename: a for a in project.list_assets()}
    assert by_name["portrait_03_before.jpg"].kind == "before_after"
    assert by_name["portrait_03_before.jpg"].analysis["pair"]["role"] == "before"
    assert by_name["portrait_03_after.jpg"].analysis["pair"]["partner"] == by_name["portrait_03_before.jpg"].id
    assert any(len(c) >= 2 for c in report.near_duplicates)


def test_phash_robust_to_resize():
    rng = np.random.default_rng(1)
    arr = (rng.random((64, 64, 3)) * 255).astype(np.uint8)
    img = Image.fromarray(arr).resize((640, 640), Image.Resampling.BICUBIC)
    assert hamming(phash(img), phash(img.resize((200, 200)))) <= 4
    other = Image.fromarray((rng.random((64, 64, 3)) * 255).astype(np.uint8)).resize((640, 640))
    assert hamming(phash(img), phash(other)) > 12


def test_analysis_features():
    img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    from PIL import ImageDraw

    ImageDraw.Draw(img).ellipse([150, 150, 250, 250], fill=(200, 30, 30, 255))
    a = analyze_image(img)
    assert a["background"] == "transparent"
    assert a["transparent_fraction"] > 0.8
    assert 0.2 < a["content_bbox"][0] < 0.45
    assert a["colors"][0]["hex"].startswith("#")


def test_exif_orientation_is_applied(projects_dir, tmp_path):
    src = tmp_path / "exif"
    src.mkdir()
    img = Image.new("RGB", (400, 200), (10, 120, 200))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW on display
    img.save(src / "rotated.jpg", exif=exif.tobytes())
    project = Project.create(projects_dir, "Exif")
    report = import_paths(project, [src], workers=1)
    asset = report.added[0]
    assert (asset.width, asset.height) == (200, 400)
    path = render_source(project, asset, 300, static=True)
    with Image.open(path) as out:
        # either the original (browser applies EXIF) or an upright derivative
        if path.suffix.lower() == ".jpg" and "derived" in str(path):
            assert out.size[1] > out.size[0]


def test_missing_file_after_import(demo_project):
    project, _ = demo_project
    asset = project.list_assets()[0]
    project.resolve_asset_path(asset).unlink()
    changed = project.refresh_missing()
    assert any(a.id == asset.id and a.status == "missing" for a in changed)


def test_video_info_and_frame(demo_assets_dir):
    video = next(demo_assets_dir.rglob("*.mp4"))
    info = media.video_info(video)
    assert info["width"] == 1280
    frame = media.video_frame(video, 0.5)
    assert frame.size == (1280, 720)
