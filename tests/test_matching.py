from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dailybreezeup.db import migrate
from dailybreezeup.matching import RunnerToMatch, horse_key, match, normalize_name


def test_normalize_strips_country_suffix():
    assert normalize_name("City Of Troy (IRE)") == "CITY OF TROY"
    assert normalize_name("City Of Troy(GB)") == "CITY OF TROY"
    assert normalize_name("Blue Point (USA)") == "BLUE POINT"


def test_normalize_handles_accents():
    assert normalize_name("Étoile Filante (FR)") == "ETOILE FILANTE"
    assert normalize_name("St. Léger") == "ST LEGER"


def test_normalize_collapses_whitespace_and_punctuation():
    assert normalize_name("  O'Brien's Pride ") == "O BRIEN S PRIDE"


def test_normalize_empty():
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


def test_horse_key():
    assert horse_key("CITY OF TROY", 2021) == "CITY OF TROY|2021"
    assert horse_key("CITY OF TROY", None) == "CITY OF TROY|?"


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    now = datetime.now(timezone.utc).isoformat()
    c.execute(
        "INSERT INTO sales (id, vendor, name, country, year, source_url, scraped_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("tatts-craven-2026", "tattersalls", "Tattersalls Craven Breeze Up Sale", "GB", 2026, "http://x", now),
    )
    c.execute(
        "INSERT INTO catalogue_entries (sale_id, lot, horse_name, normalized_name, year_foaled,"
        " sire, dam, price, currency, scraped_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("tatts-craven-2026", "12", "Test Colt (IRE)", "TEST COLT", 2024, "Frankel", "Example Mare", 200000, "GBP", now),
    )
    return c


def test_match_by_name_and_year(conn):
    m = match(conn, RunnerToMatch(name="Test Colt (IRE)", age=2, race_year=2026))
    assert m is not None
    assert m.sale_id == "tatts-craven-2026"
    assert m.lot == "12"


def test_match_by_sire_dam_fallback(conn):
    # Simulate a horse that was unnamed at sale and now has a race name
    m = match(
        conn,
        RunnerToMatch(name="Brand New Name", age=2, race_year=2026, sire="Frankel", dam="Example Mare"),
    )
    assert m is not None
    assert m.sale_id == "tatts-craven-2026"


def test_match_returns_none_for_unknown(conn):
    m = match(conn, RunnerToMatch(name="Nonexistent Horse", age=2, race_year=2026))
    assert m is None
