from __future__ import annotations

import json
from datetime import date

from barriertrials import db


def _row(**over):
    base = {
        "horse_key": "cosmicmystery",
        "race_uid": "916393",
        "horse_uid": 555,
        "horse_name": "Cosmic Mystery",
        "race_date": date(2026, 5, 1),
        "course": "Newmarket",
        "off_time": "14:30",
        "race_name": "Maiden",
        "finishing_position": "1",
        "total_runners": 8,
        "sp": "2/1",
        "rpr": 88,
        "ratings": {"Speed": 92.0},
        "season_year": 2026,
    }
    base.update(over)
    return base


def test_migrate_and_upsert_tracked_horse_preserves_learned_uid(tmp_path):
    with db.session(tmp_path / "bt.sqlite") as conn:
        db.upsert_tracked_horse(
            conn, name_key="cosmicmystery", display_name="Cosmic Mystery",
            ratings_json=json.dumps({"Speed": 92.0}),
        )
        assert db.learn_uid(conn, "cosmicmystery", 555) == "learned"
        # Re-upsert from the sheet (new ratings) must NOT wipe the learned uid.
        db.upsert_tracked_horse(
            conn, name_key="cosmicmystery", display_name="Cosmic Mystery",
            ratings_json=json.dumps({"Speed": 95.0}),
        )
        assert db.learned_uid_map(conn) == {"cosmicmystery": 555}


def test_learn_uid_states(tmp_path):
    with db.session(tmp_path / "bt.sqlite") as conn:
        assert db.learn_uid(conn, "ghost", 1) == "unknown"
        db.upsert_tracked_horse(conn, name_key="h", display_name="H", ratings_json="{}")
        assert db.learn_uid(conn, "h", 10) == "learned"
        assert db.learn_uid(conn, "h", 10) == "exists"
        assert db.learn_uid(conn, "h", 20) == "conflict"
        # Conflict left the original uid untouched.
        assert db.learned_uid_map(conn) == {"h": 10}


def test_upsert_result_row_idempotent_and_coalesces_rpr(tmp_path):
    with db.session(tmp_path / "bt.sqlite") as conn:
        assert db.upsert_result_row(conn, _row(rpr=None)) is True
        # Second scrape now has an RPR — it should fill in, not be lost.
        db.upsert_result_row(conn, _row(rpr=88))
        rows = conn.execute("SELECT * FROM results_archive").fetchall()
        assert len(rows) == 1
        assert rows[0]["rpr"] == 88
        # ratings_json was serialised from the row's ratings dict.
        assert json.loads(rows[0]["ratings_json"]) == {"Speed": 92.0}


def test_upsert_result_row_rejects_missing_keys(tmp_path):
    with db.session(tmp_path / "bt.sqlite") as conn:
        assert db.upsert_result_row(conn, _row(horse_key="")) is False
        assert db.upsert_result_row(conn, _row(race_uid="")) is False
        assert db.upsert_result_row(conn, _row(race_date=None)) is False


def test_backfill_replays_email_log_once(tmp_path):
    dbfile = tmp_path / "bt.sqlite"
    with db.session(dbfile) as conn:
        payload = _row()
        payload["race_date"] = "2026-05-01"  # JSON-style as stored in email_log
        conn.execute(
            "INSERT INTO email_log (run_date, category, horse_key, race_uid, payload_json, sent_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("2026-05-01", "ran_today", "cosmicmystery", "916393",
             json.dumps(payload), "2026-05-01T20:00:00+00:00"),
        )
    # Reopen: migrate() backfills the archive from the email_log row.
    with db.session(dbfile) as conn:
        rows = conn.execute("SELECT * FROM results_archive").fetchall()
        assert len(rows) == 1
        assert rows[0]["horse_key"] == "cosmicmystery"
