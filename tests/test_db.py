"""Tests for the SQLite migration + results-archive backfill in dailybreezeup.db."""
from __future__ import annotations

import json
from pathlib import Path

from dailybreezeup import db


def _seed_email_log_row(conn, lot_id, race_uid, payload):
    conn.execute(
        """
        INSERT INTO email_log (run_date, category, lot_id, race_uid, payload_json, sent_at)
        VALUES (?, 'ran_today', ?, ?, ?, '2026-05-01T20:00:00+00:00')
        """,
        (payload["race_date"], lot_id, race_uid, json.dumps(payload)),
    )


def _payload(**over):
    base = {
        "lot_id": "rp-5-2026-04-14-16",
        "race_uid": "910567",
        "horse_uid": 8688568,
        "horse_name": "Hot Havana",
        "sale_year": 2026,
        "sale_short": "Craven",
        "sale_name": "Tattersalls Craven Breeze Up Sale 2026",
        "lot_no": 16,
        "race_date": "2026-05-01",
        "course": "Newmarket",
        "race_name": "Maiden Stakes",
        "finishing_position": "1",
        "total_runners": 8,
        "sp": "11/4",
        "sheet_breeze_rating": 88.5,
        "sheet_precocity_rating": 80.0,
        # no rpr — historical rows predate RPR scraping
    }
    base.update(over)
    return base


def test_backfill_replays_email_log_into_archive(tmp_path: Path):
    db_path = tmp_path / "test.db"
    # First open: schema runs, but email_log is empty so archive stays empty.
    with db.session(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM results_archive").fetchone()[0] == 0
        _seed_email_log_row(conn, "rp-5-2026-04-14-16", "910567", _payload())
        _seed_email_log_row(
            conn, "rp-5-2026-04-14-17", "910568",
            _payload(lot_id="rp-5-2026-04-14-17", race_uid="910568",
                     horse_uid=8688569, horse_name="Other Horse"),
        )

    # Second open: results_archive is still empty, so migrate's backfill
    # should pick up the two seeded email_log rows.
    with db.session(db_path) as conn:
        rows = conn.execute(
            "SELECT lot_id, horse_name, rpr FROM results_archive ORDER BY lot_id"
        ).fetchall()
    assert [r["lot_id"] for r in rows] == ["rp-5-2026-04-14-16", "rp-5-2026-04-14-17"]
    assert [r["horse_name"] for r in rows] == ["Hot Havana", "Other Horse"]
    # Historical rows have no RPR — that's expected and the avg-RPR
    # aggregation handles nulls.
    assert all(r["rpr"] is None for r in rows)


def test_backfill_is_idempotent_after_archive_populated(tmp_path: Path):
    db_path = tmp_path / "test.db"
    with db.session(db_path) as conn:
        _seed_email_log_row(conn, "rp-5-2026-04-14-16", "910567", _payload())

    # First reopen: backfills one row.
    with db.session(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM results_archive").fetchone()[0] == 1

    # Add another email_log entry — but the archive is now non-empty, so
    # migrate's backfill should skip entirely (idempotent).
    with db.session(db_path) as conn:
        _seed_email_log_row(
            conn, "rp-5-2026-04-14-99", "910599",
            _payload(lot_id="rp-5-2026-04-14-99", race_uid="910599"),
        )

    with db.session(db_path) as conn:
        # Archive untouched — backfill didn't run again.
        assert conn.execute("SELECT COUNT(*) FROM results_archive").fetchone()[0] == 1


def test_upsert_result_row_writes_and_updates_in_place(tmp_path: Path):
    db_path = tmp_path / "test.db"
    with db.session(db_path) as conn:
        # First write: RPR not yet known.
        wrote = db.upsert_result_row(conn, _payload())
        assert wrote
        row = conn.execute("SELECT rpr, finishing_position FROM results_archive").fetchone()
        assert row["rpr"] is None
        assert row["finishing_position"] == "1"

        # Re-upsert with RPR now populated — should fill in, not duplicate.
        db.upsert_result_row(conn, _payload(rpr=88, finishing_position="1"))
        assert conn.execute("SELECT COUNT(*) FROM results_archive").fetchone()[0] == 1
        row = conn.execute("SELECT rpr FROM results_archive").fetchone()
        assert row["rpr"] == 88

        # A subsequent upsert without RPR must NOT clobber the previously
        # stored value — COALESCE keeps the existing one.
        db.upsert_result_row(conn, _payload(rpr=None, finishing_position="1"))
        row = conn.execute("SELECT rpr FROM results_archive").fetchone()
        assert row["rpr"] == 88


def test_upsert_skips_rows_missing_required_keys(tmp_path: Path):
    db_path = tmp_path / "test.db"
    with db.session(db_path) as conn:
        assert db.upsert_result_row(conn, {"lot_id": "x"}) is False
        assert db.upsert_result_row(conn, _payload(lot_id="")) is False
        assert db.upsert_result_row(conn, _payload(race_date=None)) is False
        assert conn.execute("SELECT COUNT(*) FROM results_archive").fetchone()[0] == 0


def test_migrate_normalises_old_tatts_ireland_sale_label(tmp_path: Path):
    """Rows archived before Jul 2026 carry sale_short='Tattersalls Ireland';
    the label changed to 'Ireland' to match the gSheet, and migrate() rewrites
    the old rows so the by-sale aggregation doesn't split into two groups."""
    db_path = tmp_path / "db.sqlite"
    with db.session(db_path) as conn:
        db.upsert_result_row(conn, _payload(
            lot_id="rp-4-2026-05-22-9",
            sale_short="Tattersalls Ireland",
            sale_name="Tattersalls Ireland Breeze Up Sale 2026",
        ))
    with db.session(db_path) as conn:  # session() runs migrate()
        labels = {
            r[0] for r in conn.execute("SELECT sale_short FROM results_archive")
        }
    assert "Tattersalls Ireland" not in labels
    assert "Ireland" in labels
