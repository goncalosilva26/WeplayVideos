"""On-disk project format.

::

    <Project Name>/
        project.json          portable configuration (atomic writes)
        project.db            SQLite index: assets, analysis, versions, exports
        brief.txt             optional creative brief
        GUIAO_PROJETO.txt     optional detailed project script
        Assets/               imported originals (never modified)
        Cache/                thumbnails, derivatives, previews (disposable)
        Versions/001/ ...     one folder per generated proposal
        Exports/              default export destination
        Trash/                trashed proposals and removed assets

``Cache/`` can be deleted at any time; everything else is project state.
If ``project.db`` is lost or corrupted it can be rebuilt from ``Assets/`` and
``Versions/*/proposal.json`` with :meth:`Project.repair`.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any, Iterable

from behance_studio import __version__
from behance_studio.core.db import Database
from behance_studio.core.errors import ProjectError
from behance_studio.core.fsutil import (
    atomic_write_json,
    atomic_write_text,
    read_json,
    read_text_file,
    safe_filename,
    unique_path,
)
from behance_studio.core.logging_setup import get_logger
from behance_studio.projects.models import (
    PROJECT_SCHEMA_VERSION,
    AssetRecord,
    ExportRecord,
    ProjectConfig,
    VersionRecord,
    new_id,
    now_iso,
)

log = get_logger(__name__)

PROJECT_FILE = "project.json"
DB_FILE = "project.db"

PROJECT_MIGRATIONS = [
    # v1
    """
    CREATE TABLE assets (
        id TEXT PRIMARY KEY,
        sha256 TEXT,
        media_type TEXT NOT NULL,
        kind TEXT,
        status TEXT,
        excluded INTEGER DEFAULT 0,
        ord INTEGER DEFAULT 0,
        data TEXT NOT NULL
    );
    CREATE INDEX idx_assets_sha ON assets(sha256);
    CREATE TABLE versions (
        id TEXT PRIMARY KEY,
        number INTEGER NOT NULL,
        status TEXT NOT NULL,
        family TEXT,
        created_at TEXT,
        data TEXT NOT NULL
    );
    CREATE TABLE exports (
        id TEXT PRIMARY KEY,
        version_id TEXT,
        format TEXT,
        path TEXT,
        created_at TEXT,
        status TEXT,
        details TEXT
    );
    CREATE TABLE kv (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """,
]


def _migrate_config(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade older ``project.json`` payloads to the current schema."""
    version = int(data.get("schema_version", 1))
    # Future migrations go here: ``if version < 2: ...; version = 2``.
    data["schema_version"] = max(version, PROJECT_SCHEMA_VERSION)
    return data


class Project:
    """An open project. Thread-safe for concurrent reads and writes."""

    def __init__(self, root: Path, config: ProjectConfig) -> None:
        self.root = Path(root)
        self.config = config
        self._lock = threading.RLock()
        self.db = Database(self.root / DB_FILE, PROJECT_MIGRATIONS)

    # ------------------------------------------------------------------ paths
    @property
    def assets_dir(self) -> Path:
        return self.root / "Assets"

    @property
    def cache_dir(self) -> Path:
        return self.root / "Cache"

    @property
    def versions_dir(self) -> Path:
        return self.root / "Versions"

    @property
    def exports_dir(self) -> Path:
        return self.root / "Exports"

    @property
    def trash_dir(self) -> Path:
        return self.root / "Trash"

    def cache_subdir(self, name: str) -> Path:
        path = self.cache_dir / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def name(self) -> str:
        return self.config.name

    # -------------------------------------------------------------- lifecycle
    @classmethod
    def create(cls, parent_dir: Path, name: str, copy_assets: bool = True) -> "Project":
        name = (name or "").strip()
        if not name:
            raise ProjectError("Please enter a project name.")
        parent_dir = Path(parent_dir)
        try:
            parent_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ProjectError(
                f"The projects folder could not be created:\n{parent_dir}", str(exc)
            ) from exc
        root = unique_path(parent_dir / safe_filename(name, fallback="Project"))
        root.mkdir(parents=True)
        for sub in ("Assets", "Cache", "Versions", "Exports", "Trash"):
            (root / sub).mkdir(exist_ok=True)
        config = ProjectConfig(id=new_id(), name=name, app_version=__version__, copy_assets=copy_assets)
        atomic_write_json(root / PROJECT_FILE, config.to_dict())
        project = cls(root, config)
        log.info("Created project %r at %s", name, root)
        return project

    @classmethod
    def open(cls, root: Path) -> "Project":
        root = Path(root)
        if root.is_file() and root.name == PROJECT_FILE:
            root = root.parent
        config_path = root / PROJECT_FILE
        if not root.is_dir():
            raise ProjectError(f"The project folder no longer exists:\n{root}")
        if not config_path.exists():
            if (root / DB_FILE).exists() or (root / "Versions").is_dir():
                log.warning("project.json missing in %s; recreating", root)
                config = ProjectConfig(id=new_id(), name=root.name, app_version=__version__)
                atomic_write_json(config_path, config.to_dict())
            else:
                raise ProjectError(f"This folder is not a Behance Studio project:\n{root}")
        try:
            data = read_json(config_path, default={})
            if not isinstance(data, dict):
                raise ValueError("project.json is not an object")
            config = ProjectConfig.from_dict(_migrate_config(data))
        except (ValueError, TypeError) as exc:
            raise ProjectError(
                "The project file is damaged and could not be read.", str(exc)
            ) from exc
        for sub in ("Assets", "Cache", "Versions", "Exports", "Trash"):
            (root / sub).mkdir(exist_ok=True)
        project = cls(root, config)
        if not project.db.integrity_ok():
            log.error("project.db failed integrity check; rebuilding index")
            project.repair(rebuild_db=True)
        elif not project.list_versions(include_trashed=True) and any(project.versions_dir.glob("*/proposal.json")):
            project.repair()
        return project

    def save_config(self) -> None:
        with self._lock:
            self.config.modified_at = now_iso()
            self.config.app_version = __version__
            atomic_write_json(self.root / PROJECT_FILE, self.config.to_dict())

    def rename(self, new_name: str, rename_folder: bool = True) -> None:
        new_name = (new_name or "").strip()
        if not new_name:
            raise ProjectError("The project name cannot be empty.")
        with self._lock:
            self.config.name = new_name
            self.save_config()
            if rename_folder:
                target = self.root.parent / safe_filename(new_name, fallback="Project")
                if target != self.root and not target.exists():
                    try:
                        os.rename(self.root, target)
                    except OSError as exc:
                        log.warning("Could not rename project folder: %s", exc)
                        return
                    self.root = target
                    self.db = Database(self.root / DB_FILE, PROJECT_MIGRATIONS)

    # ------------------------------------------------------ brief and script
    def _text_path(self, kind: str) -> Path:
        name = self.config.brief_file if kind == "brief" else self.config.script_file
        return self.root / name

    def read_text(self, kind: str) -> str:
        path = self._text_path(kind)
        if not path.exists():
            return ""
        try:
            return read_text_file(path)
        except OSError as exc:
            log.warning("Could not read %s: %s", path, exc)
            return ""

    def write_text(self, kind: str, text: str) -> None:
        path = self._text_path(kind)
        if text.strip():
            atomic_write_text(path, text)
        elif path.exists():
            # Keep a recoverable copy instead of deleting user-authored text.
            self.trash_dir.mkdir(exist_ok=True)
            shutil.move(str(path), str(unique_path(self.trash_dir / path.name)))

    @property
    def brief_text(self) -> str:
        return self.read_text("brief")

    @property
    def script_text(self) -> str:
        return self.read_text("script")

    # ----------------------------------------------------------------- assets
    def resolve_asset_path(self, asset: AssetRecord) -> Path:
        path = Path(asset.rel_path)
        if not path.is_absolute():
            path = self.root / path
        return path

    def asset_exists(self, asset: AssetRecord) -> bool:
        return self.resolve_asset_path(asset).exists()

    def save_asset(self, asset: AssetRecord) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO assets (id, sha256, media_type, kind, status, excluded, ord, data)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    asset.id,
                    asset.sha256,
                    asset.media_type,
                    asset.effective_kind,
                    asset.status,
                    int(asset.excluded),
                    asset.order,
                    json.dumps(asset.to_dict(), ensure_ascii=False),
                ),
            )

    def save_assets(self, assets: Iterable[AssetRecord]) -> None:
        rows = [
            (
                a.id,
                a.sha256,
                a.media_type,
                a.effective_kind,
                a.status,
                int(a.excluded),
                a.order,
                json.dumps(a.to_dict(), ensure_ascii=False),
            )
            for a in assets
        ]
        if not rows:
            return
        with self.db.transaction() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO assets (id, sha256, media_type, kind, status, excluded, ord, data)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def get_asset(self, asset_id: str) -> AssetRecord | None:
        row = self.db.query_one("SELECT data FROM assets WHERE id = ?", (asset_id,))
        return AssetRecord.from_dict(json.loads(row["data"])) if row else None

    def list_assets(self, include_excluded: bool = True, visual_only: bool = False) -> list[AssetRecord]:
        rows = self.db.query("SELECT data FROM assets ORDER BY ord, rowid")
        assets = [AssetRecord.from_dict(json.loads(r["data"])) for r in rows]
        if not include_excluded:
            assets = [a for a in assets if not a.excluded]
        if visual_only:
            assets = [a for a in assets if a.is_visual]
        return assets

    def find_asset_by_hash(self, sha256: str) -> AssetRecord | None:
        row = self.db.query_one("SELECT data FROM assets WHERE sha256 = ? LIMIT 1", (sha256,))
        return AssetRecord.from_dict(json.loads(row["data"])) if row else None

    def next_asset_order(self) -> int:
        row = self.db.query_one("SELECT COALESCE(MAX(ord), -1) + 1 AS n FROM assets")
        return int(row["n"]) if row else 0

    def remove_assets(self, asset_ids: Iterable[str]) -> int:
        """Remove assets from the project.

        Copies inside ``Assets/`` are moved to ``Trash/Assets`` (recoverable);
        referenced external originals are never touched.
        """
        removed = 0
        for asset_id in list(asset_ids):
            asset = self.get_asset(asset_id)
            if not asset:
                continue
            path = self.resolve_asset_path(asset)
            try:
                inside = path.resolve().is_relative_to(self.assets_dir.resolve())
            except (OSError, ValueError):
                inside = False
            if inside and path.exists():
                dest = unique_path(self.trash_dir / "Assets" / path.name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(dest))
            self.db.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
            removed += 1
        return removed

    def refresh_missing(self) -> list[AssetRecord]:
        """Mark assets whose files disappeared as missing (and back to ok)."""
        changed = []
        for asset in self.list_assets():
            exists = self.asset_exists(asset)
            if not exists and asset.status != "missing":
                asset.status = "missing"
                changed.append(asset)
            elif exists and asset.status == "missing":
                asset.status = "ok"
                changed.append(asset)
        self.save_assets(changed)
        return changed

    def relink_asset(self, asset_id: str, new_path: Path) -> AssetRecord:
        asset = self.get_asset(asset_id)
        if asset is None:
            raise ProjectError("Asset not found.")
        new_path = Path(new_path)
        if not new_path.exists():
            raise ProjectError(f"File not found:\n{new_path}")
        try:
            rel = new_path.resolve().relative_to(self.root.resolve())
            asset.rel_path = rel.as_posix()
        except ValueError:
            asset.rel_path = str(new_path.resolve())
        asset.status = "ok"
        self.save_asset(asset)
        return asset

    # --------------------------------------------------------------- versions
    def save_version(self, record: VersionRecord) -> None:
        record.modified_at = now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO versions (id, number, status, family, created_at, data)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.number,
                    record.status,
                    record.family,
                    record.created_at,
                    json.dumps(record.to_dict(), ensure_ascii=False),
                ),
            )

    def get_version(self, version_id: str) -> VersionRecord | None:
        row = self.db.query_one("SELECT data FROM versions WHERE id = ?", (version_id,))
        return VersionRecord.from_dict(json.loads(row["data"])) if row else None

    def list_versions(self, include_trashed: bool = False, only_trashed: bool = False) -> list[VersionRecord]:
        rows = self.db.query("SELECT data FROM versions ORDER BY number")
        records = [VersionRecord.from_dict(json.loads(r["data"])) for r in rows]
        if only_trashed:
            return [r for r in records if r.status == "trashed"]
        if not include_trashed:
            records = [r for r in records if r.status != "trashed"]
        return records

    def delete_version_row(self, version_id: str) -> None:
        self.db.execute("DELETE FROM versions WHERE id = ?", (version_id,))

    def next_version_number(self) -> int:
        row = self.db.query_one("SELECT COALESCE(MAX(number), 0) + 1 AS n FROM versions")
        number = int(row["n"]) if row else 1
        # Never reuse a folder number that still exists on disk (e.g. in Trash).
        while (self.versions_dir / f"{number:03d}").exists() or (self.trash_dir / f"{number:03d}").exists():
            number += 1
        return number

    # ---------------------------------------------------------------- exports
    def record_export(self, record: ExportRecord) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO exports (id, version_id, format, path, created_at, status, details)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.version_id,
                record.format,
                record.path,
                record.created_at,
                record.status,
                json.dumps(record.details, ensure_ascii=False),
            ),
        )

    def list_exports(self, version_id: str | None = None) -> list[ExportRecord]:
        if version_id:
            rows = self.db.query(
                "SELECT * FROM exports WHERE version_id = ? ORDER BY created_at DESC", (version_id,)
            )
        else:
            rows = self.db.query("SELECT * FROM exports ORDER BY created_at DESC")
        return [
            ExportRecord(
                id=r["id"],
                version_id=r["version_id"],
                format=r["format"],
                path=r["path"],
                created_at=r["created_at"],
                status=r["status"],
                details=json.loads(r["details"] or "{}"),
            )
            for r in rows
        ]

    # --------------------------------------------------------------- kv store
    def get_value(self, key: str, default: Any = None) -> Any:
        row = self.db.query_one("SELECT value FROM kv WHERE key = ?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except ValueError:
            return default

    def set_value(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    # ----------------------------------------------------------------- repair
    def repair(self, rebuild_db: bool = False) -> dict[str, int]:
        """Rebuild the version index from proposal files on disk.

        Asset rows are rebuilt by re-importing ``Assets/`` (see the importer)
        when the database had to be recreated.
        """
        if rebuild_db:
            db_path = self.root / DB_FILE
            backup = unique_path(db_path.with_suffix(".damaged.db"))
            try:
                for suffix in ("", "-wal", "-shm"):
                    p = Path(str(db_path) + suffix)
                    if p.exists():
                        if suffix:
                            p.unlink()
                        else:
                            p.replace(backup)
            except OSError as exc:
                log.error("Could not move damaged database: %s", exc)
            self.db = Database(db_path, PROJECT_MIGRATIONS)
        known = {v.id for v in self.list_versions(include_trashed=True)}
        restored = 0
        for status, base in (("active", self.versions_dir), ("trashed", self.trash_dir)):
            for proposal_file in sorted(base.glob("*/proposal.json")):
                try:
                    data = read_json(proposal_file, default={}) or {}
                    meta = data.get("version") or {}
                    if not meta.get("id") or meta["id"] in known:
                        continue
                    record = VersionRecord.from_dict(meta)
                    record.status = status
                    record.folder = proposal_file.parent.relative_to(self.root).as_posix()
                    self.save_version(record)
                    known.add(record.id)
                    restored += 1
                except Exception as exc:  # noqa: BLE001 - keep repairing others
                    log.warning("Skipping unreadable proposal %s: %s", proposal_file, exc)
        if rebuild_db:
            self.set_value("needs_asset_reindex", True)
        return {"versions_restored": restored}
