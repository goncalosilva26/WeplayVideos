"""Asset import: validation, de-duplication, copying, metadata and analysis.

Original files are never modified. By default they are *copied* into the
project's ``Assets`` folder (keeping the relative folder structure, which is
also a useful classification hint); optionally they can be referenced in place.
"""

from __future__ import annotations

import io
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image, ImageCms

from behance_studio.assets import media
from behance_studio.assets.analysis import ANALYSIS_VERSION, analyze_image, phash
from behance_studio.assets.classify import classify
from behance_studio.assets.derivatives import THUMB_SIZE, ensure_thumbnail, load_visual
from behance_studio.assets.formats import (
    classify_text_file,
    media_type_for,
    sniff_media_type,
)
from behance_studio.assets.roles import detect_before_after, infer_roles, near_duplicate_clusters
from behance_studio.core.errors import AssetError, OperationCancelled
from behance_studio.core.fsutil import (
    atomic_write_json,
    copy_file,
    iter_files,
    read_json,
    read_text_file,
    safe_filename,
    sha256_file,
)
from behance_studio.core.logging_setup import get_logger
from behance_studio.core.tasks import CancelToken
from behance_studio.projects.models import (
    MEDIA_DOCUMENT,
    MEDIA_GIF,
    MEDIA_IMAGE,
    MEDIA_SVG,
    MEDIA_VIDEO,
    AssetRecord,
    new_id,
)

log = get_logger(__name__)

ProgressFn = Callable[[float, str], None]


def _noop(_f: float, _m: str = "") -> None:
    return None


@dataclass
class ImportReport:
    added: list[AssetRecord] = field(default_factory=list)
    duplicates: list[tuple[str, str]] = field(default_factory=list)  # (path, existing asset name)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (path, message)
    brief_imported: str | None = None
    script_imported: str | None = None
    project_texts_ignored: list[str] = field(default_factory=list)
    near_duplicates: list[list[str]] = field(default_factory=list)
    cancelled: bool = False

    def summary(self) -> str:
        parts = [f"{len(self.added)} asset(s) imported"]
        if self.duplicates:
            parts.append(f"{len(self.duplicates)} duplicate(s) skipped")
        if self.skipped:
            parts.append(f"{len(self.skipped)} unsupported file(s) ignored")
        if self.errors:
            parts.append(f"{len(self.errors)} damaged/unreadable file(s)")
        if self.brief_imported:
            parts.append("creative brief detected")
        if self.script_imported:
            parts.append("project script detected")
        if self.cancelled:
            parts.append("import cancelled")
        return ", ".join(parts)


def _is_srgb_profile(icc: bytes) -> bool:
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        description = ImageCms.getProfileDescription(profile) or ""
        return "srgb" in description.lower()
    except Exception:  # noqa: BLE001
        return False


def _image_metadata(path: Path, record: AssetRecord) -> None:
    media.verify_image(path)
    header = media.image_header(path)
    record.width, record.height = header["width"], header["height"]
    browser_safe = header["format"] in {"JPEG", "PNG", "WEBP", "BMP", "GIF"} and header["mode"] in {
        "RGB", "RGBA", "L", "LA", "P", "1",
    }
    if browser_safe and header.get("has_icc"):
        with Image.open(path) as img:
            icc = img.info.get("icc_profile")
        browser_safe = bool(icc) and _is_srgb_profile(icc)
    record.analysis["browser_safe"] = browser_safe
    record.analysis["format"] = header["format"]
    record.analysis["exif_orientation"] = header["exif_orientation"]
    if header.get("dpi"):
        record.analysis["dpi"] = header["dpi"]


def read_metadata(path: Path, media_type: str, record: AssetRecord) -> None:
    """Fill dimensions/duration/etc. Raises AssetError for damaged files."""
    if media_type == MEDIA_IMAGE:
        _image_metadata(path, record)
    elif media_type == MEDIA_GIF:
        media.verify_image(path)
        info = media.gif_info(path)
        record.width, record.height = info["width"], info["height"]
        record.animated = info["animated"]
        record.frame_count = info["frames"]
        record.duration = info["duration"]
        record.analysis["browser_safe"] = True
    elif media_type == MEDIA_SVG:
        w, h = media.svg_size(path)
        record.width, record.height = int(round(w)), int(round(h))
        record.analysis["browser_safe"] = True
    elif media_type == MEDIA_VIDEO:
        info = media.video_info(path)
        record.width, record.height = info["width"], info["height"]
        record.duration = info["duration"]
        record.fps = info["fps"]
        record.frame_count = info["frame_count"]
        record.animated = True
        record.analysis["codec"] = info["codec"]
        record.analysis["has_audio"] = info["has_audio"]
    elif media_type == MEDIA_DOCUMENT:
        if path.suffix.lower() == ".pdf":
            with open(path, "rb") as handle:
                if not handle.read(5).startswith(b"%PDF"):
                    raise AssetError(f"The PDF file is damaged: {path.name}")
        elif path.suffix.lower() == ".json":
            try:
                json.loads(read_text_file(path))
            except ValueError as exc:
                raise AssetError(f"The JSON file is not valid: {path.name}", str(exc)) from exc
        else:
            read_text_file(path)


def _analysis_cache_path(project, sha: str) -> Path:
    return project.cache_subdir("analysis") / f"{sha}.json"


def analyze_asset(project, asset: AssetRecord, force: bool = False) -> AssetRecord:
    """Thumbnail + visual analysis + heuristic classification + roles."""
    if not asset.is_visual:
        return asset
    cache_file = _analysis_cache_path(project, asset.sha256) if asset.sha256 else None
    cached = None
    if cache_file and not force:
        try:
            cached = read_json(cache_file)
        except (ValueError, OSError):
            cached = None
    keep = {k: asset.analysis[k] for k in ("browser_safe", "format", "exif_orientation", "dpi", "codec", "has_audio") if k in asset.analysis}
    image = None
    if cached and cached.get("version") == ANALYSIS_VERSION:
        analysis = cached["analysis"]
        asset.phash = cached.get("phash", asset.phash)
    else:
        image, has_alpha = load_visual(project, asset, max_size=768)
        if asset.media_type == MEDIA_IMAGE:
            asset.has_alpha = has_alpha
        analysis = analyze_image(image)
        asset.phash = phash(image)
        if cache_file:
            atomic_write_json(cache_file, {"version": ANALYSIS_VERSION, "analysis": analysis, "phash": asset.phash})
    if asset.media_type in (MEDIA_SVG,) or (asset.media_type == MEDIA_GIF and analysis.get("transparent_fraction", 0) > 0.05):
        asset.has_alpha = analysis.get("transparent_fraction", 0) > 0.01
    if asset.media_type == MEDIA_IMAGE and analysis.get("transparent_fraction", 0) > 0.01:
        asset.has_alpha = True
    analysis.update(keep)
    asset.analysis = analysis
    try:
        ensure_thumbnail(project, asset, image if image is not None and max(image.size) >= THUMB_SIZE else None)
    except AssetError as exc:
        log.warning("Thumbnail failed for %s: %s", asset.filename, exc.detail or exc)

    if asset.kind_source != "ai" or force:
        result = classify(
            asset.filename,
            asset.import_group,
            asset.media_type,
            asset.width,
            asset.height,
            asset.has_alpha,
            analysis,
            animated=asset.animated,
        )
        asset.kind = result.kind
        asset.kind_confidence = result.confidence
        asset.kind_source = "heuristic"
        asset.analysis["classification"] = {
            "reasons": result.reasons,
            "scores": result.scores,
            "pair_role": result.pair_role,
        }
    asset.roles = infer_roles(asset)
    return asset


def analyze_assets(
    project,
    assets: Iterable[AssetRecord],
    token: CancelToken | None = None,
    progress: ProgressFn = _noop,
    workers: int = 4,
    force: bool = False,
) -> list[AssetRecord]:
    """Analyse many assets in parallel (thread pool; decoders release the GIL)."""
    items = [a for a in assets if a.is_visual]
    done: list[AssetRecord] = []
    if not items:
        progress(1.0, "Nothing to analyse")
        return done
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="analyze") as pool:
        futures = {pool.submit(analyze_asset, project, a, force): a for a in items}
        for index, future in enumerate(as_completed(futures), start=1):
            asset = futures[future]
            if token and token.cancelled:
                for f in futures:
                    f.cancel()
                raise OperationCancelled("Analysis cancelled")
            try:
                done.append(future.result())
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
                log.warning("Analysis failed for %s: %s", asset.filename, exc)
                asset.error = f"Analysis failed: {getattr(exc, 'message', exc)}"
                done.append(asset)
            progress(index / len(items), f"Analysed {asset.filename}")
    finalize_relationships(project, done)
    project.save_assets(done)
    return done


def finalize_relationships(project, changed: list[AssetRecord]) -> None:
    """Cross-asset logic: before/after pairing and near-duplicate flags."""
    all_assets = {a.id: a for a in project.list_assets()}
    for a in changed:
        all_assets[a.id] = a
    assets = list(all_assets.values())
    pairs = detect_before_after(assets)
    paired = {}
    for before_id, after_id in pairs:
        paired[before_id] = ("before", after_id)
        paired[after_id] = ("after", before_id)
    for asset in assets:
        cls = asset.analysis.get("classification", {})
        if asset.id in paired and asset.kind_source == "heuristic":
            role, partner = paired[asset.id]
            asset.kind = "before_after"
            asset.analysis["pair"] = {"role": role, "partner": partner}
        elif asset.kind == "before_after" and asset.kind_source == "heuristic":
            # Name looked like before/after but no counterpart exists: demote.
            scores = {k: v for k, v in (cls.get("scores") or {}).items() if k != "before_after"}
            asset.kind = max(scores, key=scores.get) if scores else "photo"
            asset.analysis.pop("pair", None)
    clusters = near_duplicate_clusters(assets)
    dup_of: dict[str, list[str]] = {}
    for cluster in clusters:
        for aid in cluster:
            dup_of[aid] = [x for x in cluster if x != aid]
    for asset in assets:
        if asset.id in dup_of:
            asset.analysis["near_duplicates"] = dup_of[asset.id]
        else:
            asset.analysis.pop("near_duplicates", None)
        asset.roles = infer_roles(asset)
    project.save_assets(assets)


def _import_with_archives(project, paths, archives, copy, token, progress, workers, analyze, adopt_project_texts) -> ImportReport:
    """Extract archives to the cache, import everything, remove the extraction."""
    import shutil

    from behance_studio.assets.archive import extract_zip

    report = ImportReport()
    others = [p for p in paths if p not in archives]
    groups: list[tuple[list[Path], bool | None]] = [(others, copy)] if others else []
    extracted: list[Path] = []
    try:
        for archive in archives:
            try:
                folder = extract_zip(archive, project.cache_subdir("unzip"))
            except AssetError as exc:
                report.errors.append((str(archive), exc.message))
                continue
            extracted.append(folder)
            groups.append(([folder], True))  # extracted files live in the cache: always copy them
        for i, (group, group_copy) in enumerate(groups):
            sub = import_paths(project, group, copy=group_copy, token=token,
                               progress=lambda f, m, i=i: progress((i + f) / len(groups), m), workers=workers,
                               analyze=analyze, adopt_project_texts=adopt_project_texts)
            report.added += sub.added
            report.duplicates += sub.duplicates
            report.skipped += sub.skipped
            report.errors += sub.errors
            report.near_duplicates += sub.near_duplicates
            report.project_texts_ignored += sub.project_texts_ignored
            report.brief_imported = report.brief_imported or sub.brief_imported
            report.script_imported = report.script_imported or sub.script_imported
            if sub.cancelled:
                report.cancelled = True
                break
    finally:
        for folder in extracted:
            shutil.rmtree(folder, ignore_errors=True)
    return report


def import_paths(
    project,
    paths: Iterable[Path | str],
    copy: bool | None = None,
    token: CancelToken | None = None,
    progress: ProgressFn = _noop,
    workers: int = 4,
    analyze: bool = True,
    adopt_project_texts: bool = True,
) -> ImportReport:
    """Import files, folders (recursively) and ZIP archives into ``project``."""
    paths = [Path(p) for p in paths]
    archives = [p for p in paths if p.is_file() and p.suffix.lower() == ".zip"]
    if archives:
        return _import_with_archives(project, paths, archives, copy, token, progress, workers, analyze, adopt_project_texts)
    report = ImportReport()
    copy = project.config.copy_assets if copy is None else copy
    files = list(iter_files(Path(p) for p in paths))
    total = max(1, len(files))
    existing_hashes = {a.sha256: a.filename for a in project.list_assets() if a.sha256}
    batch_hashes: dict[str, str] = {}
    candidates: list[tuple[Path, Path, str, str]] = []

    progress(0.0, f"Scanning {len(files)} file(s)")
    for index, (path, root) in enumerate(files, start=1):
        if token and token.cancelled:
            report.cancelled = True
            return report
        doc_kind = classify_text_file(path)
        if doc_kind and adopt_project_texts:
            current = project.read_text(doc_kind)
            if not current.strip():
                try:
                    project.write_text(doc_kind, read_text_file(path))
                    if doc_kind == "brief":
                        report.brief_imported = str(path)
                    else:
                        report.script_imported = str(path)
                except OSError as exc:
                    report.errors.append((str(path), f"Could not read: {exc}"))
            else:
                report.project_texts_ignored.append(str(path))
            continue
        media_type = media_type_for(path)
        sniffed = sniff_media_type(path)
        if media_type is None:
            if sniffed in (MEDIA_IMAGE, MEDIA_GIF, MEDIA_VIDEO):
                media_type = sniffed
            else:
                report.skipped.append((str(path), "Unsupported file type"))
                continue
        elif sniffed and sniffed != media_type and media_type != MEDIA_DOCUMENT:
            # Extension lies (e.g. a PNG named .jpg): trust the content.
            media_type = sniffed
        try:
            sha = sha256_file(path)
        except OSError as exc:
            report.errors.append((str(path), f"Could not read the file: {exc}"))
            continue
        if sha in existing_hashes:
            report.duplicates.append((str(path), existing_hashes[sha]))
            continue
        if sha in batch_hashes:
            report.duplicates.append((str(path), batch_hashes[sha]))
            continue
        batch_hashes[sha] = path.name
        try:
            rel_group = path.parent.relative_to(root).as_posix()
        except ValueError:
            rel_group = ""
        if rel_group == ".":
            rel_group = ""
        candidates.append((path, Path(rel_group), media_type, sha))
        progress(0.15 * index / total, f"Scanning {path.name}")

    order = project.next_asset_order()

    def process(item: tuple[Path, Path, str, str], position: int) -> AssetRecord:
        path, rel_group, media_type, sha = item
        record = AssetRecord(
            id=new_id(),
            media_type=media_type,
            filename=path.name,
            rel_path="",
            source_path=str(path.resolve()),
            import_group=rel_group.as_posix() if str(rel_group) not in ("", ".") else "",
            size_bytes=path.stat().st_size,
            sha256=sha,
            order=position,
        )
        read_metadata(path, media_type, record)
        if copy:
            sub = Path(*[safe_filename(p) for p in Path(record.import_group).parts]) if record.import_group else Path()
            dest = copy_file(path, project.assets_dir / sub / safe_filename(path.name))
            record.rel_path = dest.relative_to(project.root).as_posix()
        else:
            record.rel_path = str(path.resolve())
        return record

    records: list[AssetRecord] = []
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="import") as pool:
        futures = {pool.submit(process, item, order + i): item for i, item in enumerate(candidates)}
        for index, future in enumerate(as_completed(futures), start=1):
            path = futures[future][0]
            if token and token.cancelled:
                for f in futures:
                    f.cancel()
                report.cancelled = True
                break
            try:
                records.append(future.result())
            except AssetError as exc:
                report.errors.append((str(path), exc.message))
                log.info("Rejected %s: %s", path, exc.detail or exc.message)
            except Exception as exc:  # noqa: BLE001
                report.errors.append((str(path), f"Unexpected error: {exc}"))
                log.exception("Import failed for %s", path)
            progress(0.15 + 0.35 * index / max(1, len(candidates)), f"Imported {path.name}")

    records.sort(key=lambda r: r.order)
    project.save_assets(records)
    report.added = records
    if report.cancelled:
        return report
    if analyze and records:
        try:
            analyze_assets(
                project,
                records,
                token=token,
                progress=lambda f, m: progress(0.5 + 0.5 * f, m),
                workers=workers,
            )
            report.added = [project.get_asset(r.id) or r for r in records]
        except OperationCancelled:
            report.cancelled = True
    clusters = near_duplicate_clusters(project.list_assets())
    report.near_duplicates = clusters
    progress(1.0, report.summary())
    log.info("Import into %s: %s", project.name, report.summary())
    return report
