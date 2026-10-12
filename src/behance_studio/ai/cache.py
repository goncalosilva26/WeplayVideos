"""Content-addressed cache for AI image analysis, shared by all projects.

An image is analysed once per *content* and *analysis configuration*: the
key covers the image's SHA-256, the provider and model, the prompt version
and the context the prompt includes (file name and folder). Re-importing the
same file, opening it in another project or generating again never sends it
to the model again; changing the image, the model or the prompt does.

Entries are small JSON files in ``<app data>/ai-cache/<xx>/<key>.json``
(no images, no keys). A per-key lock makes concurrent callers (e.g. the
automatic analysis after import and a generation started meanwhile) wait for
the first request instead of repeating it.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from behance_studio.core.fsutil import atomic_write_json, read_json
from behance_studio.core.logging_setup import get_logger

log = get_logger(__name__)


class AnalysisCache:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    @property
    def root(self) -> Path:
        if self._root is None:
            from behance_studio.core.paths import user_data_dir

            return user_data_dir() / "ai-cache"  # resolved per call: tests redirect the data folder
        return self._root

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = read_json(path)
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        try:
            atomic_write_json(self._path(key), value)
        except OSError as exc:  # a cache must never break analysis
            log.warning("Could not cache an AI analysis: %s", exc)

    @contextmanager
    def lock(self, key: str) -> Iterator[None]:
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            yield


ANALYSIS_CACHE = AnalysisCache()
