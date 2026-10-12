"""Safe extraction of ZIP deliveries for import.

Archives are extracted into the project cache (never next to the original,
which is not modified), with protection against path traversal ("zip
slip"), absolute paths, symbolic links, oversized or oversized-ratio
members ("zip bombs") and OS metadata. Folder names inside the archive are
kept, so they still inform asset classification.
"""

from __future__ import annotations

import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from behance_studio.core.errors import AssetError
from behance_studio.core.fsutil import safe_filename

MAX_FILES = 5000
MAX_TOTAL_BYTES = 6 * 1024**3
MAX_RATIO = 200  # uncompressed / compressed, per member
SKIP_PARTS = {"__MACOSX", ".DS_Store", "Thumbs.db", "desktop.ini"}


def extract_zip(archive: Path, destination_root: Path) -> Path:
    """Extract ``archive`` into a new folder under ``destination_root``."""
    archive = Path(archive)
    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise AssetError(f"'{archive.name}' is not a readable ZIP archive.", str(exc)) from exc
    target = destination_root / safe_filename(archive.stem)
    n = 2
    while target.exists():
        target = destination_root / f"{safe_filename(archive.stem)} ({n})"
        n += 1
    target.mkdir(parents=True)
    total = 0
    count = 0
    try:
        with zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                parts = PurePosixPath(name).parts
                if name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
                    raise AssetError(f"'{archive.name}' contains an unsafe path and was not imported.", info.filename)
                if not parts or any(p in SKIP_PARTS or p.startswith(".") for p in parts):
                    continue
                if stat.S_ISLNK(info.external_attr >> 16):
                    continue  # never follow links out of the archive
                count += 1
                total += info.file_size
                if count > MAX_FILES or total > MAX_TOTAL_BYTES:
                    raise AssetError(f"'{archive.name}' is too large to import in one go.", f"{count} files, {total} bytes")
                if info.compress_size and info.file_size / max(1, info.compress_size) > MAX_RATIO and info.file_size > 50 * 1024**2:
                    raise AssetError(f"'{archive.name}' contains a suspicious compressed member.", info.filename)
                out = target.joinpath(*[safe_filename(p) for p in parts])
                if not out.resolve().is_relative_to(target.resolve()):
                    raise AssetError(f"'{archive.name}' contains an unsafe path and was not imported.", info.filename)
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target
