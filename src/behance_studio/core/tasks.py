"""Cancellation and progress reporting primitives shared by all long jobs.

They are deliberately independent of Qt so that the core engine can run from
the command line and from tests; the UI adapts them to Qt signals.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Protocol

from behance_studio.core.errors import OperationCancelled


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OperationCancelled("Operation cancelled by the user")


@dataclass
class ProgressEvent:
    stage: str
    fraction: float | None  # 0..1 for measurable work, None for indeterminate
    message: str = ""
    stage_index: int | None = None
    stage_count: int | None = None


class ProgressCallback(Protocol):
    def __call__(self, event: ProgressEvent) -> None: ...


def null_progress(event: ProgressEvent) -> None:  # pragma: no cover - trivial
    return None


@dataclass
class StageTracker:
    """Reports progress for a fixed list of named stages.

    Each stage reports its own measurable fraction; the overall fraction is
    computed from completed stages plus the fraction of the current one, so
    the displayed percentage always reflects real work done.
    """

    stages: list[str]
    callback: Callable[[ProgressEvent], None] = null_progress
    weights: dict[str, float] = field(default_factory=dict)
    _current: int = -1
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _weight(self, name: str) -> float:
        return self.weights.get(name, 1.0)

    def start(self, name: str, message: str = "") -> None:
        with self._lock:
            self._current = self.stages.index(name)
        self.update(0.0, message)

    def update(self, fraction: float | None, message: str = "") -> None:
        if self._current < 0:
            return
        name = self.stages[self._current]
        total = sum(self._weight(s) for s in self.stages)
        done = sum(self._weight(s) for s in self.stages[: self._current])
        overall = None
        if fraction is not None:
            fraction = max(0.0, min(1.0, fraction))
            overall = round((done + self._weight(name) * fraction) / total, 6)
        self.callback(
            ProgressEvent(
                stage=name,
                fraction=overall,
                message=message,
                stage_index=self._current,
                stage_count=len(self.stages),
            )
        )

    def sub(self, start: float, end: float) -> Callable[[float, str], None]:
        """Return a reporter mapping 0..1 onto [start, end] of the current stage."""

        def report(fraction: float, message: str = "") -> None:
            self.update(start + (end - start) * max(0.0, min(1.0, fraction)), message)

        return report
