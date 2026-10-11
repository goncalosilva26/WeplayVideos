"""Application-level catalogue of known projects (recent projects list)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from behance_studio.core.db import Database
from behance_studio.core.paths import user_data_dir
from behance_studio.projects.models import now_iso

LIBRARY_MIGRATIONS = [
    """
    CREATE TABLE projects (
        path TEXT PRIMARY KEY,
        project_id TEXT,
        name TEXT,
        created_at TEXT,
        last_opened TEXT,
        thumbnail TEXT,
        proposals INTEGER DEFAULT 0,
        pinned INTEGER DEFAULT 0
    )
    """,
]


@dataclass
class LibraryEntry:
    path: str
    project_id: str
    name: str
    created_at: str
    last_opened: str
    thumbnail: str
    proposals: int
    pinned: bool

    @property
    def exists(self) -> bool:
        return (Path(self.path) / "project.json").exists()


class ProjectLibrary:
    def __init__(self, path: Path | None = None) -> None:
        self.db = Database(path or (user_data_dir() / "library.db"), LIBRARY_MIGRATIONS)

    def register(self, project, thumbnail: str = "") -> None:  # project: Project
        path = str(Path(project.root).resolve())
        proposals = len(project.list_versions())
        existing = self.db.query_one("SELECT thumbnail, pinned FROM projects WHERE path = ?", (path,))
        if existing and not thumbnail:
            thumbnail = existing["thumbnail"] or ""
        self.db.execute(
            "INSERT OR REPLACE INTO projects (path, project_id, name, created_at, last_opened, thumbnail, proposals, pinned)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                path,
                project.config.id,
                project.config.name,
                project.config.created_at,
                now_iso(),
                thumbnail,
                proposals,
                int(existing["pinned"]) if existing else 0,
            ),
        )

    def update_path(self, old_path: Path, project) -> None:
        self.db.execute("DELETE FROM projects WHERE path = ?", (str(Path(old_path).resolve()),))
        self.register(project)

    def recent(self, limit: int = 50, include_missing: bool = False) -> list[LibraryEntry]:
        rows = self.db.query(
            "SELECT * FROM projects ORDER BY pinned DESC, last_opened DESC LIMIT ?", (limit,)
        )
        entries = [
            LibraryEntry(
                path=r["path"],
                project_id=r["project_id"] or "",
                name=r["name"] or Path(r["path"]).name,
                created_at=r["created_at"] or "",
                last_opened=r["last_opened"] or "",
                thumbnail=r["thumbnail"] or "",
                proposals=int(r["proposals"] or 0),
                pinned=bool(r["pinned"]),
            )
            for r in rows
        ]
        if not include_missing:
            entries = [e for e in entries if e.exists]
        return entries

    def forget(self, path: Path | str) -> None:
        self.db.execute("DELETE FROM projects WHERE path = ?", (str(Path(path).resolve()),))

    def set_pinned(self, path: Path | str, pinned: bool) -> None:
        self.db.execute(
            "UPDATE projects SET pinned = ? WHERE path = ?", (int(pinned), str(Path(path).resolve()))
        )
