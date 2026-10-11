"""Background work for the UI.

Long operations (import, analysis, generation, rendering, export) run on a
thread pool; their progress and results come back to the GUI thread through
Qt signals, so the interface never freezes.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QImageReader, QPixmap

from behance_studio.core.errors import OperationCancelled
from behance_studio.core.logging_setup import get_logger
from behance_studio.core.tasks import CancelToken, ProgressEvent

log = get_logger(__name__)


class TaskSignals(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(object)
    cancelled = Signal()


class Task(QRunnable):
    """Runs ``fn(token=..., progress=...)`` in the pool."""

    def __init__(self, fn: Callable[..., Any], name: str = "task") -> None:
        super().__init__()
        self.fn = fn
        self.name = name
        self.token = CancelToken()
        self.signals = TaskSignals()
        self.setAutoDelete(False)

    def cancel(self) -> None:
        self.token.cancel()

    def _progress(self, *args: Any) -> None:
        if len(args) == 1 and isinstance(args[0], ProgressEvent):
            self.signals.progress.emit(args[0])
        elif len(args) >= 1:
            fraction = args[0]
            message = args[1] if len(args) > 1 else ""
            self.signals.progress.emit(ProgressEvent(self.name, fraction, message))

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(token=self.token, progress=self._progress)
        except OperationCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            log.error("Task %s failed: %s\n%s", self.name, exc, traceback.format_exc())
            self.signals.failed.emit(exc)
        else:
            self.signals.finished.emit(result)


class TaskRunner(QObject):
    busy_changed = Signal(bool)

    def __init__(self, max_threads: int = 4) -> None:
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(max(2, max_threads))
        self._active: set[Task] = set()

    def start(
        self,
        fn: Callable[..., Any],
        name: str = "task",
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_progress: Callable[[ProgressEvent], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> Task:
        task = Task(fn, name)
        self._active.add(task)
        if on_progress:
            task.signals.progress.connect(on_progress)

        def finish(*_a: Any) -> None:
            self._active.discard(task)
            self.busy_changed.emit(bool(self._active))

        task.signals.finished.connect(lambda r: (on_done(r) if on_done else None, finish()))
        task.signals.failed.connect(lambda e: (on_error(e) if on_error else None, finish()))
        task.signals.cancelled.connect(lambda: (on_cancel() if on_cancel else None, finish()))
        self.busy_changed.emit(True)
        self.pool.start(task)
        return task

    def cancel_all(self) -> None:
        for task in list(self._active):
            task.cancel()

    def wait(self, ms: int = 30000) -> bool:
        return self.pool.waitForDone(ms)

    @property
    def busy(self) -> bool:
        return bool(self._active)


# ---------------------------------------------------------- image loading
class _ImageSignals(QObject):
    loaded = Signal(str, QImage)


class _ImageJob(QRunnable):
    def __init__(self, key: str, path: str, size: QSize, signals: _ImageSignals) -> None:
        super().__init__()
        self.key, self.path, self.size, self.signals = key, path, size, signals

    def run(self) -> None:
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        original = reader.size()
        if original.isValid() and self.size.isValid():
            scaled = original.scaled(self.size, Qt.AspectRatioMode.KeepAspectRatio)
            if scaled.width() < original.width():
                reader.setScaledSize(scaled)
        image = reader.read()
        self.signals.loaded.emit(self.key, image)


class ImageLoader(QObject):
    """Decodes thumbnails off the GUI thread and caches the pixmaps."""

    def __init__(self) -> None:
        super().__init__()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(3)
        self.signals = _ImageSignals()
        self.signals.loaded.connect(self._on_loaded)
        self._cache: dict[str, QPixmap] = {}
        self._waiting: dict[str, list[Callable[[QPixmap], None]]] = {}

    def load(self, path: Path | str | None, size: QSize, callback: Callable[[QPixmap], None]) -> None:
        if not path:
            return
        path = str(path)
        try:
            mtime = Path(path).stat().st_mtime_ns
        except OSError:
            return
        key = f"{path}|{mtime}|{size.width()}x{size.height()}"
        if key in self._cache:
            callback(self._cache[key])
            return
        if key in self._waiting:
            self._waiting[key].append(callback)
            return
        self._waiting[key] = [callback]
        self.pool.start(_ImageJob(key, path, size, self.signals))

    def _on_loaded(self, key: str, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        if len(self._cache) > 600:
            self._cache.clear()
        self._cache[key] = pixmap
        for cb in self._waiting.pop(key, []):
            try:
                cb(pixmap)
            except RuntimeError:  # the receiving widget was deleted
                pass

    def invalidate(self, path: Path | str) -> None:
        prefix = f"{path}|"
        for key in [k for k in self._cache if k.startswith(prefix)]:
            del self._cache[key]


_loader: ImageLoader | None = None


def image_loader() -> ImageLoader:
    global _loader
    if _loader is None:
        _loader = ImageLoader()
    return _loader
