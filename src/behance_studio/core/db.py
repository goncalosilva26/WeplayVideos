"""Thin, thread-safe SQLite wrapper with ordered schema migrations."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence


class Database:
    """Opens a short-lived connection per transaction.

    Short-lived connections avoid sharing a connection between threads and
    keep the file unlocked between operations (important when a project lives
    on a synced folder). WAL journaling keeps readers and the writer apart.
    """

    def __init__(self, path: Path, migrations: Sequence[str]) -> None:
        self.path = Path(path)
        self._migrations = list(migrations)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _migrate(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                try:
                    conn.execute("PRAGMA journal_mode = WAL")
                except sqlite3.DatabaseError:
                    pass
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                for index in range(version, len(self._migrations)):
                    conn.execute("BEGIN")
                    try:
                        for statement in _split_sql(self._migrations[index]):
                            conn.execute(statement)
                        conn.execute(f"PRAGMA user_version = {index + 1}")
                        conn.execute("COMMIT")
                    except Exception:
                        conn.execute("ROLLBACK")
                        raise
            finally:
                conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    yield conn
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                else:
                    conn.execute("COMMIT")
            finally:
                conn.close()

    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._connect()
            try:
                yield conn
            finally:
                conn.close()

    def execute(self, sql: str, params: Sequence | dict = ()) -> None:
        with self.transaction() as conn:
            conn.execute(sql, params)

    def query(self, sql: str, params: Sequence | dict = ()) -> list[sqlite3.Row]:
        with self.reader() as conn:
            return list(conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence | dict = ()) -> sqlite3.Row | None:
        with self.reader() as conn:
            return conn.execute(sql, params).fetchone()

    def integrity_ok(self) -> bool:
        try:
            row = self.query_one("PRAGMA integrity_check")
            return bool(row) and row[0] == "ok"
        except sqlite3.DatabaseError:
            return False


def _split_sql(script: str) -> list[str]:
    statements = []
    for part in script.split(";"):
        part = part.strip()
        if part:
            statements.append(part)
    return statements
