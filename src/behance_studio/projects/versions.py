"""Proposal versions: create, load, edit history, favourites, trash.

Each proposal lives in its own folder (``Versions/001``) with
``proposal.json`` (full data), preview thumbnails and an edit history. A new
generation never overwrites an existing version. Trashing moves the folder to
``Trash/`` (restorable); permanent deletion only removes that proposal's own
folder — shared source assets are never touched.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from behance_studio.core.errors import ProjectError
from behance_studio.core.fsutil import atomic_write_json, read_json, unique_path
from behance_studio.core.logging_setup import get_logger
from behance_studio.projects.models import VersionRecord, new_id, now_iso

if TYPE_CHECKING:  # pragma: no cover
    from behance_studio.generation.proposal import ProposalData
    from behance_studio.projects.store import Project

log = get_logger(__name__)

PROPOSAL_FILE = "proposal.json"
HISTORY_LIMIT = 40


class VersionManager:
    def __init__(self, project: "Project") -> None:
        self.project = project

    # ---------------------------------------------------------------- paths
    def folder(self, record: VersionRecord) -> Path:
        return self.project.root / record.folder

    def thumb_path(self, record: VersionRecord) -> Path:
        return self.folder(record) / "thumb.jpg"

    def strip_path(self, record: VersionRecord) -> Path:
        return self.folder(record) / "strip.jpg"

    # -------------------------------------------------------------- create
    def create(self, proposal: "ProposalData", name: str | None = None, parent_id: str | None = None) -> VersionRecord:
        from behance_studio.layout.families import family_info

        with self.project._lock:
            number = self.project.next_version_number()
            folder = self.project.versions_dir / f"{number:03d}"
            folder.mkdir(parents=True, exist_ok=False)
            info = family_info(proposal.spec.family)
            record = VersionRecord(
                id=new_id(),
                number=number,
                name=name or f"{info.name} {number:02d}",
                family=proposal.spec.family,
                seed=proposal.spec.seed,
                folder=folder.relative_to(self.project.root).as_posix(),
                quality=proposal.quality.overall,
                parent_id=parent_id,
                issues=len(proposal.quality.errors),
            )
            self._write(record, proposal)
            self.project.save_version(record)
        log.info("Saved proposal %s (%s) in %s", record.name, record.family, record.folder)
        return record

    def _write(self, record: VersionRecord, proposal: "ProposalData") -> None:
        data = proposal.to_dict()
        data["version"] = record.to_dict()
        atomic_write_json(self.folder(record) / PROPOSAL_FILE, data)

    # ---------------------------------------------------------------- load
    def get(self, version_id: str) -> VersionRecord:
        record = self.project.get_version(version_id)
        if record is None:
            raise ProjectError("This proposal no longer exists.")
        return record

    def load(self, version_id: str) -> "ProposalData":
        from behance_studio.generation.proposal import ProposalData

        record = self.get(version_id)
        path = self.folder(record) / PROPOSAL_FILE
        try:
            data = read_json(path)
        except (OSError, ValueError) as exc:
            raise ProjectError(f"The proposal '{record.name}' could not be read.", str(exc)) from exc
        if not data:
            raise ProjectError(f"The proposal file for '{record.name}' is missing.")
        return ProposalData.from_dict(data)

    def list(self, include_trashed: bool = False) -> list[VersionRecord]:
        return self.project.list_versions(include_trashed=include_trashed)

    def trashed(self) -> list[VersionRecord]:
        return self.project.list_versions(only_trashed=True)

    # ---------------------------------------------------------------- edit
    def save(self, version_id: str, proposal: "ProposalData", label: str = "Edit") -> VersionRecord:
        """Replace a version's content, keeping the previous state in history."""
        record = self.get(version_id)
        current = self.folder(record) / PROPOSAL_FILE
        history = self.folder(record) / "history"
        history.mkdir(exist_ok=True)
        if current.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            snapshot = read_json(current) or {}
            snapshot["history_label"] = label
            atomic_write_json(history / f"{stamp}.json", snapshot)
            states = sorted(history.glob("*.json"))
            for old in states[:-HISTORY_LIMIT]:
                old.unlink(missing_ok=True)
        record.quality = proposal.quality.overall
        record.issues = len(proposal.quality.errors)
        record.family = proposal.spec.family
        self._write(record, proposal)
        self.project.save_version(record)
        return record

    def history(self, version_id: str) -> list[tuple[str, str, str]]:
        """(state id, timestamp ISO, label), newest first."""
        record = self.get(version_id)
        out = []
        for path in sorted((self.folder(record) / "history").glob("*.json"), reverse=True):
            stamp = path.stem
            try:
                ts = datetime.strptime(stamp, "%Y%m%dT%H%M%S%f").replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                ts = stamp
            label = (read_json(path) or {}).get("history_label", "Edit")
            out.append((stamp, ts, label))
        return out

    def restore_state(self, version_id: str, state_id: str) -> "ProposalData":
        from behance_studio.generation.proposal import ProposalData

        record = self.get(version_id)
        path = self.folder(record) / "history" / f"{state_id}.json"
        data = read_json(path)
        if not data:
            raise ProjectError("That earlier state is no longer available.")
        proposal = ProposalData.from_dict(data)
        self.save(version_id, proposal, label="Before restore")
        return proposal

    def rename(self, version_id: str, name: str) -> VersionRecord:
        name = (name or "").strip()
        if not name:
            raise ProjectError("The proposal name cannot be empty.")
        record = self.get(version_id)
        record.name = name
        self.project.save_version(record)
        self._touch_meta(record)
        return record

    def set_favorite(self, version_id: str, favorite: bool) -> VersionRecord:
        record = self.get(version_id)
        record.favorite = favorite
        self.project.save_version(record)
        self._touch_meta(record)
        return record

    def set_preferred(self, version_id: str | None) -> None:
        if version_id is not None:
            self.get(version_id)
        self.project.config.preferred_version_id = version_id
        self.project.save_config()

    def preferred(self) -> VersionRecord | None:
        vid = self.project.config.preferred_version_id
        if not vid:
            return None
        record = self.project.get_version(vid)
        return record if record and record.status == "active" else None

    def _touch_meta(self, record: VersionRecord) -> None:
        path = self.folder(record) / PROPOSAL_FILE
        data = read_json(path)
        if data:
            data["version"] = record.to_dict()
            atomic_write_json(path, data)

    def duplicate(self, version_id: str) -> VersionRecord:
        record = self.get(version_id)
        proposal = self.load(version_id)
        copy = self.create(proposal, name=f"{record.name} (copy)", parent_id=record.id)
        for name in ("thumb.jpg", "strip.jpg"):
            src = self.folder(record) / name
            if src.exists():
                shutil.copy2(src, self.folder(copy) / name)
        return copy

    # --------------------------------------------------------------- trash
    def trash(self, version_ids: list[str]) -> int:
        moved = 0
        for vid in version_ids:
            record = self.project.get_version(vid)
            if record is None or record.status == "trashed":
                continue
            src = self.folder(record)
            dest = unique_path(self.project.trash_dir / src.name)
            self.project.trash_dir.mkdir(exist_ok=True)
            if src.exists():
                shutil.move(str(src), str(dest))
            record.status = "trashed"
            record.trashed_at = now_iso()
            record.folder = dest.relative_to(self.project.root).as_posix()
            self.project.save_version(record)
            self._touch_meta(record)
            if self.project.config.preferred_version_id == vid:
                self.project.config.preferred_version_id = None
                self.project.save_config()
            moved += 1
        return moved

    def restore(self, version_ids: list[str]) -> int:
        restored = 0
        for vid in version_ids:
            record = self.project.get_version(vid)
            if record is None or record.status != "trashed":
                continue
            src = self.folder(record)
            dest = self.project.versions_dir / src.name
            if dest.exists():
                dest = self.project.versions_dir / f"{self.project.next_version_number():03d}"
            if src.exists():
                shutil.move(str(src), str(dest))
            record.status = "active"
            record.trashed_at = None
            record.folder = dest.relative_to(self.project.root).as_posix()
            self.project.save_version(record)
            self._touch_meta(record)
            restored += 1
        return restored

    def delete_permanently(self, version_ids: list[str]) -> int:
        """Irreversible: removes the proposal folder (only trashed proposals)."""
        deleted = 0
        for vid in version_ids:
            record = self.project.get_version(vid)
            if record is None:
                continue
            if record.status != "trashed":
                raise ProjectError("Move the proposal to the Trash before deleting it permanently.")
            folder = self.folder(record)
            trash_root = self.project.trash_dir.resolve()
            if folder.exists():
                if not folder.resolve().is_relative_to(trash_root):
                    raise ProjectError("Refusing to delete a folder outside the project Trash.")
                shutil.rmtree(folder)
            self.project.delete_version_row(vid)
            deleted += 1
        return deleted

    def empty_trash(self) -> int:
        return self.delete_permanently([r.id for r in self.trashed()])
