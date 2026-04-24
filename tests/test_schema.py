import sqlite3

from dailybreezeup.db import migrate


def test_migrate_creates_tables():
    c = sqlite3.connect(":memory:")
    migrate(c)
    tables = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sales", "catalogue_entries", "email_log", "run_log"}.issubset(tables)


def test_catalogue_unique_sale_lot():
    c = sqlite3.connect(":memory:")
    migrate(c)
    c.execute(
        "INSERT INTO sales (id, vendor, name, country, year, scraped_at) VALUES (?,?,?,?,?,?)",
        ("s1", "x", "X", "GB", 2026, "2026-01-01"),
    )
    c.execute(
        "INSERT INTO catalogue_entries (sale_id, lot, horse_name, normalized_name, scraped_at)"
        " VALUES (?,?,?,?,?)",
        ("s1", "1", "A", "A", "2026-01-01"),
    )
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        c.execute(
            "INSERT INTO catalogue_entries (sale_id, lot, horse_name, normalized_name, scraped_at)"
            " VALUES (?,?,?,?,?)",
            ("s1", "1", "B", "B", "2026-01-01"),
        )
