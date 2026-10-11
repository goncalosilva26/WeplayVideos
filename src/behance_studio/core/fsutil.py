"""Safe filesystem helpers.

Every write of project state goes through ``atomic_write_*`` so that a crash or
power loss never leaves a half-written ``project.json`` or proposal file.
Names are sanitised for Windows (reserved device names, forbidden characters,
trailing dots/spaces) while preserving accents and other Unicode characters.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_filename(name: str, fallback: str = "untitled", max_length: int = 120) -> str:
    """Return a name that is valid on Windows, macOS and Linux.

    Unicode letters (accents, CJK, ...) are kept; only characters that are
    illegal in file names are replaced.
    """
    name = unicodedata.normalize("NFC", name or "")
    name = _FORBIDDEN.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    if not name:
        name = fallback
    stem = name.split(".")[0].upper()
    if stem in _RESERVED:
        name = f"_{name}"
    if len(name) > max_length:
        root, ext = os.path.splitext(name)
        if len(ext) > 12:
            root, ext = name, ""
        name = root[: max_length - len(ext)].rstrip(". ") + ext
    return name


def slugify(text: str, max_length: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:max_length].strip("-") or "item"


def unique_path(path: Path) -> Path:
    """Return ``path`` or ``name (2).ext``, ``name (3).ext``... if it exists."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    if path.is_dir() and not suffix:
        stem = path.name
    match = re.match(r"^(.*) \((\d+)\)$", stem)
    base = match.group(1) if match else stem
    counter = int(match.group(2)) + 1 if match else 2
    while True:
        candidate = path.with_name(f"{base} ({counter}){suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _fsync_dir(directory: Path) -> None:
    if os.name == "nt":  # Directory fsync is not supported on Windows.
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # os.replace is atomic on the same volume (also on Windows).
        for attempt in range(5):
            try:
                os.replace(tmp_name, path)
                break
            except PermissionError:
                # Windows: another process (antivirus, indexer) may briefly
                # hold the destination open.
                if attempt == 4:
                    raise
                import time

                time.sleep(0.05 * (attempt + 1))
        _fsync_dir(path.parent)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def atomic_write_json(path: Path, data: Any) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False, default=_json_default)
    atomic_write_text(path, text + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default


def read_text_file(path: Path) -> str:
    """Read a user text file, tolerating common Windows encodings."""
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            if encoding == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1252", errors="replace")


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(src: Path, dst: Path) -> Path:
    """Copy ``src`` to a non-existing ``dst`` (made unique). Source is untouched."""
    dst = unique_path(Path(dst))
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.partial")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)
    return dst


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024 or unit == "GB":
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"  # pragma: no cover


def iter_files(paths: Iterable[Path]) -> Iterable[tuple[Path, Path]]:
    """Yield ``(file, import_root)`` for files and recursively for folders.

    Hidden files/folders and OS metadata (Thumbs.db, .DS_Store) are skipped.
    """
    skip = {"thumbs.db", ".ds_store", "desktop.ini"}
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            if path.name.lower() not in skip:
                yield path, path.parent
        elif path.is_dir():
            for root, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if not d.startswith((".", "__MACOSX")))
                for name in sorted(files):
                    if name.startswith(".") or name.lower() in skip:
                        continue
                    yield Path(root) / name, path
