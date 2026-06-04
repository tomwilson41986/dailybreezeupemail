from __future__ import annotations

from datetime import date

from barriertrials.config import (
    DEFAULT_HORSE_NAME_COLUMN,
    DEFAULT_RATING_COLUMNS,
    DEFAULT_SEASON_START_DATE,
    DEFAULT_SHEET_CSV_URL,
    Settings,
)


def test_blank_env_falls_back_to_defaults():
    # GitHub Actions expands unset `${{ vars.X }}` to "" — those must not
    # clobber the field defaults (and "" must not crash date parsing).
    s = Settings(
        season_start_date="",
        horse_name_column="",
        rating_columns="",
        sheet_csv_url="",
    )
    assert s.season_start_date == DEFAULT_SEASON_START_DATE
    assert s.horse_name_column == DEFAULT_HORSE_NAME_COLUMN
    assert s.rating_columns == DEFAULT_RATING_COLUMNS
    assert s.sheet_csv_url == DEFAULT_SHEET_CSV_URL


def test_explicit_values_are_respected():
    s = Settings(
        season_start_date="2025-03-15",
        horse_name_column="Name",
        rating_columns="A, B ,C",
    )
    assert s.season_start_date == date(2025, 3, 15)
    assert s.horse_name_column == "Name"
    assert s.rating_column_list == ["A", "B", "C"]


def test_email_to_list_dedups_case_insensitively():
    s = Settings(email_to="A@x.com, b@y.com, a@x.com")
    assert s.email_to_list == ["A@x.com", "b@y.com"]
