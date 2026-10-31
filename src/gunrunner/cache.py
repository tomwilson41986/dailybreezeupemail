"""A small SQLite key-value cache for everything fetched about a horse (Equibase
runs, the website's records): fetched once, kept across weekly runs by the
Actions cache, so a horse costs credits once. Also the ledger of lots already
reported, for the "new this week" flag."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path


class Cache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (ns TEXT, k TEXT, v TEXT, at TEXT, PRIMARY KEY (ns, k))"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS reported (lot_id TEXT PRIMARY KEY, first_reported TEXT, score REAL)"
        )

    def get(self, ns: str, k: str, *, max_age_days: int | None = None):
        row = self.conn.execute("SELECT v, at FROM kv WHERE ns=? AND k=?", (ns, k)).fetchone()
        if not row:
            return None
        if (
            max_age_days is not None
            and row[1] < (date.today() - timedelta(days=max_age_days)).isoformat()
        ):
            return None
        return json.loads(row[0])

    def put(self, ns: str, k: str, v) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO kv VALUES (?,?,?,?)",
            (ns, k, json.dumps(v), date.today().isoformat()),
        )
        self.conn.commit()

    def has(self, ns: str, k: str, *, max_age_days: int | None = None) -> bool:
        row = self.conn.execute("SELECT at FROM kv WHERE ns=? AND k=?", (ns, k)).fetchone()
        if not row:
            return False
        return (
            max_age_days is None
            or row[0] >= (date.today() - timedelta(days=max_age_days)).isoformat()
        )

    def first_reported(self, lot_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT first_reported FROM reported WHERE lot_id=?", (lot_id,)
        ).fetchone()
        return row[0] if row else None

    def mark_reported(self, lot_id: str, score: float, today: date) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO reported VALUES (?,?,?)", (lot_id, today.isoformat(), score)
        )
        self.conn.commit()
