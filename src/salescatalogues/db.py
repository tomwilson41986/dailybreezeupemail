"""SQLite persistence: connection helper + the ``seen_catalogue`` ledger that
powers New-detection.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from importlib import resources
from pathlib import Path


def _schema_sql() -> str:
    return resources.files("salescatalogues").joinpath("schema.sql").read_text()


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(_schema_sql())
    conn.commit()


@contextmanager
def session(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_first_seen(conn: sqlite3.Connection, catalogue_id: str) -> date | None:
    """Return when a catalogue was first observed, or ``None`` if never."""
    row = conn.execute(
        "SELECT first_seen FROM seen_catalogue WHERE catalogue_id = ?",
        (catalogue_id,),
    ).fetchone()
    if row is None:
        return None
    return date.fromisoformat(row["first_seen"])


def record_seen(
    conn: sqlite3.Connection,
    *,
    catalogue_id: str,
    house: str,
    country: str,
    name: str,
    start_date: date | None,
    today: date,
) -> None:
    """Upsert a catalogue: insert with ``first_seen=today`` the first time,
    otherwise just bump ``last_seen``."""
    conn.execute(
        """
        INSERT INTO seen_catalogue
            (catalogue_id, house, country, name, start_date, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(catalogue_id) DO UPDATE SET last_seen = excluded.last_seen
        """,
        (
            catalogue_id,
            house,
            country,
            name,
            start_date.isoformat() if start_date else None,
            today.isoformat(),
            today.isoformat(),
        ),
    )
