import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    schema = files("dailybreezeup").joinpath("schema.sql").read_text()
    conn.executescript(schema)
    _backfill_results_archive(conn)
    conn.commit()


def _backfill_results_archive(conn: sqlite3.Connection) -> None:
    """Replay every ``ran_today`` row from ``email_log`` into ``results_archive``.

    Runs once per database: skips on every subsequent call by checking whether
    the archive already has rows. RPR is left NULL for backfilled rows because
    older payloads predate RPR scraping; the avg-RPR aggregation handles that.
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


def upsert_result_row(
    conn: sqlite3.Connection,
    row: dict,
    *,
    recorded_at: str | None = None,
) -> bool:
    """Insert-or-update one (lot_id, race_uid) outing into ``results_archive``.

    Returns True when a row is written. The conflict clause refreshes every
    field except ``recorded_at`` so a later scrape (e.g. one that finally
    has RPR) supersedes an earlier sparse one.
    """
    if not row.get("lot_id") or not row.get("race_uid"):
        return False
    if not row.get("race_date"):
        return False
    sale_year = row.get("sale_year")
    if sale_year is None:
        return False
    recorded_at = recorded_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO results_archive (
            lot_id, race_uid, horse_uid, horse_name, sale_year, sale_short,
            sale_name, lot_no, race_date, course, off_time, race_name,
            finishing_position, total_runners, sp, rpr,
            sheet_breeze_rating, sheet_precocity_rating, recorded_at
        ) VALUES (
            :lot_id, :race_uid, :horse_uid, :horse_name, :sale_year, :sale_short,
            :sale_name, :lot_no, :race_date, :course, :off_time, :race_name,
            :finishing_position, :total_runners, :sp, :rpr,
            :sheet_breeze_rating, :sheet_precocity_rating, :recorded_at
        )
        ON CONFLICT(lot_id, race_uid) DO UPDATE SET
            horse_uid              = excluded.horse_uid,
            horse_name             = excluded.horse_name,
            sale_short             = excluded.sale_short,
            sale_name              = excluded.sale_name,
            lot_no                 = excluded.lot_no,
            race_date              = excluded.race_date,
            course                 = excluded.course,
            off_time               = excluded.off_time,
            race_name              = excluded.race_name,
            finishing_position     = excluded.finishing_position,
            total_runners          = excluded.total_runners,
            sp                     = excluded.sp,
            rpr                    = COALESCE(excluded.rpr, results_archive.rpr),
            sheet_breeze_rating    = COALESCE(excluded.sheet_breeze_rating, results_archive.sheet_breeze_rating),
            sheet_precocity_rating = COALESCE(excluded.sheet_precocity_rating, results_archive.sheet_precocity_rating)
        """,
        {
            "lot_id": row["lot_id"],
            "race_uid": str(row["race_uid"]) if row.get("race_uid") is not None else "",
            "horse_uid": row.get("horse_uid"),
            "horse_name": row.get("horse_name") or None,
            "sale_year": sale_year,
            "sale_short": row.get("sale_short"),
            "sale_name": row.get("sale_name"),
            "lot_no": row.get("lot_no"),
            "race_date": str(row["race_date"]),
            "course": row.get("course"),
            "off_time": str(row["off_time"]) if row.get("off_time") else None,
            "race_name": row.get("race_name"),
            "finishing_position": row.get("finishing_position"),
            "total_runners": row.get("total_runners"),
            "sp": row.get("sp"),
            "rpr": row.get("rpr"),
            "sheet_breeze_rating": row.get("sheet_breeze_rating"),
            "sheet_precocity_rating": row.get("sheet_precocity_rating"),
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
    scraped_at = scraped_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
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
