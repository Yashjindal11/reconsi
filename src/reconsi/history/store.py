"""Optional local run history in SQLite (parameterised queries only)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from reconsi.core.errors import ReconsiError

if TYPE_CHECKING:
    from reconsi.core.result import ReconciliationResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    status TEXT NOT NULL,
    match_percentage REAL,
    mismatch_percentage REAL,
    missing_records INTEGER,
    value_mismatch_records INTEGER,
    left_digest TEXT,
    right_digest TEXT,
    config_hash TEXT,
    reconsi_version TEXT,
    git_commit TEXT,
    document TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_name_started ON runs (name, started_at);
"""


class HistoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con:
            con.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def record(self, result: ReconciliationResult) -> str:
        doc = result.to_dict()
        meta, s = doc["metadata"], doc["summary"]
        row = (
            meta["run_id"],
            doc["name"],
            meta["started_at"],
            doc["status"],
            s["match_percentage"],
            s["mismatch_percentage"],
            s["missing_records"],
            s["value_mismatch_records"],
            (meta.get("left_fingerprint") or {}).get("digest"),
            (meta.get("right_fingerprint") or {}).get("digest"),
            meta.get("config_hash"),
            meta.get("reconsi_version"),
            meta.get("git_commit"),
            json.dumps(doc, allow_nan=False),
        )
        with closing(self._connect()) as con, con:
            con.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                row,
            )
        return str(meta["run_id"])

    def runs(self, name: str | None = None, limit: int = 20) -> pd.DataFrame:
        query = (
            "SELECT run_id, name, started_at, status, match_percentage, mismatch_percentage, "
            "missing_records, value_mismatch_records, left_digest, right_digest, config_hash, "
            "git_commit FROM runs"
        )
        params: list[Any] = []
        if name is not None:
            query += " WHERE name = ?"
            params.append(name)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(int(limit))
        with closing(self._connect()) as con:
            rows = con.execute(query, params).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def get(self, run_id: str) -> dict[str, Any]:
        with closing(self._connect()) as con:
            row = con.execute("SELECT document FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise ReconsiError(f"no run with id {run_id!r} in {self.path}")
        doc = json.loads(row["document"])
        assert isinstance(doc, dict)
        return doc

    def previous(self, name: str, before: str) -> dict[str, Any] | None:
        with closing(self._connect()) as con:
            row = con.execute(
                "SELECT document FROM runs WHERE name = ? AND started_at < ? "
                "ORDER BY started_at DESC LIMIT 1",
                (name, before),
            ).fetchone()
        if row is None:
            return None
        doc = json.loads(row["document"])
        assert isinstance(doc, dict)
        return doc
