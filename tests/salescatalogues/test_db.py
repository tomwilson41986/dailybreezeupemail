from datetime import date
from pathlib import Path

from salescatalogues import db


def test_first_seen_roundtrip(tmp_path: Path):
    dbp = tmp_path / "sc.sqlite"
    with db.session(dbp) as conn:
        assert db.get_first_seen(conn, "x|y|2026-06") is None
        db.record_seen(
            conn, catalogue_id="x|y|2026-06", house="H", country="UK",
            name="Y", start_date=date(2026, 6, 1), today=date(2026, 6, 9),
        )
    # New connection: first_seen is sticky; a later sighting only bumps last_seen.
    with db.session(dbp) as conn:
        assert db.get_first_seen(conn, "x|y|2026-06") == date(2026, 6, 9)
        db.record_seen(
            conn, catalogue_id="x|y|2026-06", house="H", country="UK",
            name="Y", start_date=date(2026, 6, 1), today=date(2026, 6, 10),
        )
    with db.session(dbp) as conn:
        row = conn.execute(
            "SELECT first_seen, last_seen FROM seen_catalogue WHERE catalogue_id=?",
            ("x|y|2026-06",),
        ).fetchone()
        assert row["first_seen"] == "2026-06-09"
        assert row["last_seen"] == "2026-06-10"
