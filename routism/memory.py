"""P1.D — pluggable persistent shared memory.

Two scopes of memory:
- per-query (in-process): steps of the current workflow, keyed by int index.
- cross-query (persistent, optional): outputs kept across requests so a later
  workflow can reference an earlier result. Keyed by a scope id + index.

The executor uses an int `access_list` entry for the current query and a string
`"scope:<id>:s:<idx>"` entry to pull a cross-query output. The persistent
backend is selected by config (`memory.backend`: inprocess|file|sqlite).
"""

from __future__ import annotations

import json
import re
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path

# "scope:<scope_id>:s:<step_idx>"  e.g. "scope:projA:s:3"
_SCOPE_RE = re.compile(r"^scope:(?P<scope>[^:]+):s:(?P<idx>\d+)$")


def parse_scope_ref(ref: str) -> tuple[str, int] | None:
    """Parse a cross-query access ref; return (scope, idx) or None if not one."""
    m = _SCOPE_RE.match(ref)
    if not m:
        return None
    return m.group("scope"), int(m.group("idx"))


def is_scope_ref(ref) -> bool:
    return isinstance(ref, str) and _SCOPE_RE.match(ref) is not None


class MemoryStore(ABC):
    """Key-value store of step outputs, keyed by (scope, step_idx)."""

    @abstractmethod
    def put(self, scope: str, idx: int, text: str) -> None: ...

    @abstractmethod
    def get(self, scope: str, idx: int) -> str | None: ...

    @abstractmethod
    def list_scopes(self) -> list[str]: ...


class InProcessStore(MemoryStore):
    def __init__(self) -> None:
        self._data: dict[tuple[str, int], str] = {}

    def put(self, scope: str, idx: int, text: str) -> None:
        self._data[(scope, idx)] = text

    def get(self, scope: str, idx: int) -> str | None:
        return self._data.get((scope, idx))

    def list_scopes(self) -> list[str]:
        return sorted({s for (s, _) in self._data})


class FileStore(MemoryStore):
    """JSONL append log; reloads on every read so it survives restarts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("")

    def _load(self) -> list[dict]:
        rows: list[dict] = []
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows

    def put(self, scope: str, idx: int, text: str) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps({"scope": scope, "idx": idx, "text": text}) + "\n")

    def get(self, scope: str, idx: int) -> str | None:
        best: str | None = None
        for row in self._load():
            if row["scope"] == scope and row["idx"] == idx:
                best = row["text"]  # last write wins
        return best

    def list_scopes(self) -> list[str]:
        return sorted({r["scope"] for r in self._load()})


class SqliteStore(MemoryStore):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(self.path))
        self._con.execute(
            "CREATE TABLE IF NOT EXISTS memory ("
            "scope TEXT, idx INTEGER, text TEXT, "
            "PRIMARY KEY (scope, idx))"
        )
        self._con.commit()

    def put(self, scope: str, idx: int, text: str) -> None:
        self._con.execute(
            "INSERT OR REPLACE INTO memory (scope, idx, text) VALUES (?, ?, ?)",
            (scope, idx, text),
        )
        self._con.commit()

    def get(self, scope: str, idx: int) -> str | None:
        cur = self._con.execute(
            "SELECT text FROM memory WHERE scope=? AND idx=?", (scope, idx)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def list_scopes(self) -> list[str]:
        cur = self._con.execute("SELECT DISTINCT scope FROM memory")
        return sorted(r[0] for r in cur.fetchall())


def make_store(backend: str = "inprocess", path: str | None = None) -> MemoryStore:
    backend = (backend or "inprocess").lower()
    if backend == "inprocess":
        return InProcessStore()
    if backend == "file":
        return FileStore(path or "routism_memory.jsonl")
    if backend == "sqlite":
        return SqliteStore(path or "routism_memory.db")
    raise ValueError(f"unknown memory.backend: {backend!r}")
