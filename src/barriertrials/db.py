"""SQLite persistence for the barrier-trial tracker.

Mirrors the breeze-up job's db layer (dedup log, run log, idempotent results
archive, per-day scrape log) but keyed on the watchlist's normalised horse name
(``horse_key``) instead of a sale lot id, plus a ``tracked_horses`` table that
stores the watchlist and the Racing Post uid we learn per horse.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    schema = files("barriertrials").joinpath("schema.sql").read_text()
    conn.executescript(schema)
    _backfill_results_archive(conn)
    conn.commit()


def _backfill_results_archive(conn: sqlite3.Connection) -> None:
    """Replay every ``ran_today`` row from ``email_log`` into ``results_archive``.

    Runs once per database (skips when the archive already has rows). Lets the
    season-to-date summary survive a DB cache eviction: the email_log payloads
    carry the full archive row, so we can rebuild the archive from them.
    """
    existing = conn.execute("SELECT COUNT(*) FROM results_archive").fetchone()[0]
    if existing:
        return
    cursor = conn.execute(
        "SELECT payload_json, sent_at FROM email_log WHERE category='ran_today'"
    )
    n = 0
    for payload_json, sent_at in cursor:
        try:
            row = json.loads(payload_json)
        except (TypeError, ValueError):
            continue
        if upsert_result_row(conn, row, recorded_at=sent_at):
            n += 1
    if n:
        log.info("results_archive backfilled with %d row(s) from email_log", n)


def upsert_tracked_horse(
    conn: sqlite3.Connection,
    *,
    name_key: str,
    display_name: str,
    ratings_json: str,
) -> None:
    """Insert or refresh a watchlist row, preserving any learned uid."""
    now = _utcnow()
    conn.execute(
        """
        INSERT INTO tracked_horses (name_key, display_name, ratings_json, first_seen, updated_at)
        VALUES (:name_key, :display_name, :ratings_json, :now, :now)
        ON CONFLICT(name_key) DO UPDATE SET
            display_name = excluded.display_name,
            ratings_json = excluded.ratings_json,
            updated_at   = excluded.updated_at
        """,
        {
            "name_key": name_key,
            "display_name": display_name,
            "ratings_json": ratings_json,
            "now": now,
        },
    )


def learned_uid_map(conn: sqlite3.Connection) -> dict[str, int]:
    """``{name_key: learned_uid}`` for every watchlist horse whose uid we know."""
    return {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT name_key, learned_uid FROM tracked_horses WHERE learned_uid IS NOT NULL"
        )
    }


def learn_uid(conn: sqlite3.Connection, name_key: str, uid: int) -> str:
    """Record the Racing Post uid for a watchlist horse.

    Returns one of:
      "learned"  — uid stored for the first time
      "exists"   — already stored, unchanged
      "conflict" — a *different* uid is already stored (left untouched; caller
                   should surface this — it usually means a name collision)
      "unknown"  — name_key isn't on the watchlist
    """
    row = conn.execute(
        "SELECT learned_uid FROM tracked_horses WHERE name_key = ?", (name_key,)
    ).fetchone()
    if row is None:
        return "unknown"
    current = row[0]
    if current is None:
        conn.execute(
            "UPDATE tracked_horses SET learned_uid = ?, updated_at = ? WHERE name_key = ?",
            (uid, _utcnow(), name_key),
        )
        return "learned"
    if int(current) == int(uid):
        return "exists"
    return "conflict"


def upsert_result_row(
    conn: sqlite3.Connection,
    row: dict,
    *,
    recorded_at: str | None = None,
) -> bool:
    """Insert-or-update one (horse_key, race_uid) outing into ``results_archive``.

    Returns True when a row is written. The conflict clause refreshes every field
    except ``recorded_at``, and COALESCEs ``rpr``/``ratings_json`` so a later
    scrape (e.g. one that finally has RPR) supersedes an earlier sparse one
    without dropping data already captured.
    """
    if not row.get("horse_key") or row.get("race_uid") in (None, ""):
        return False
    if not row.get("race_date"):
        return False
    race_date = str(row["race_date"])
    season_year = row.get("season_year")
    if season_year is None:
        try:
            season_year = int(race_date[:4])
        except (ValueError, TypeError):
            return False
    ratings_json = row.get("ratings_json")
    if ratings_json is None and row.get("ratings") is not None:
        ratings_json = json.dumps(row["ratings"])
    recorded_at = recorded_at or _utcnow()
    conn.execute(
        """
        INSERT INTO results_archive (
            horse_key, race_uid, horse_uid, horse_name, race_date, course,
            off_time, race_name, finishing_position, total_runners, sp, rpr,
            ratings_json, season_year, recorded_at
        ) VALUES (
            :horse_key, :race_uid, :horse_uid, :horse_name, :race_date, :course,
            :off_time, :race_name, :finishing_position, :total_runners, :sp, :rpr,
            :ratings_json, :season_year, :recorded_at
        )
        ON CONFLICT(horse_key, race_uid) DO UPDATE SET
            horse_uid          = excluded.horse_uid,
            horse_name         = excluded.horse_name,
            race_date          = excluded.race_date,
            course             = excluded.course,
            off_time           = excluded.off_time,
            race_name          = excluded.race_name,
            finishing_position = excluded.finishing_position,
            total_runners      = excluded.total_runners,
            sp                 = excluded.sp,
            rpr                = COALESCE(excluded.rpr, results_archive.rpr),
            ratings_json       = COALESCE(excluded.ratings_json, results_archive.ratings_json),
            season_year        = excluded.season_year
        """,
        {
            "horse_key": row["horse_key"],
            "race_uid": str(row["race_uid"]),
            "horse_uid": row.get("horse_uid"),
            "horse_name": row.get("horse_name") or None,
            "race_date": race_date,
            "course": row.get("course"),
            "off_time": str(row["off_time"]) if row.get("off_time") else None,
            "race_name": row.get("race_name"),
            "finishing_position": row.get("finishing_position"),
            "total_runners": row.get("total_runners"),
            "sp": row.get("sp"),
            "rpr": row.get("rpr"),
            "ratings_json": ratings_json,
            "season_year": season_year,
            "recorded_at": recorded_at,
        },
    )
    return True


def scraped_result_dates(conn: sqlite3.Connection) -> set[str]:
    """ISO dates already walked for the season archive (see results_scrape_log)."""
    return {r[0] for r in conn.execute("SELECT result_date FROM results_scrape_log")}


def mark_result_date_scraped(
    conn: sqlite3.Connection,
    day_iso: str,
    *,
    scraped_at: str | None = None,
) -> None:
    scraped_at = scraped_at or _utcnow()
    conn.execute(
        "INSERT OR REPLACE INTO results_scrape_log (result_date, scraped_at) VALUES (?, ?)",
        (day_iso, scraped_at),
    )


@contextmanager
def session(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()
