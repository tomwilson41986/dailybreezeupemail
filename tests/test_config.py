import pytest

from dailybreezeup.config import _ALWAYS_RECIPIENTS, DEFAULT_SHEET_CSV_URL, Settings


def test_empty_sheet_csv_url_falls_back_to_default(monkeypatch):
    # GitHub Actions sets `SHEET_CSV_URL: ${{ vars.SHEET_CSV_URL }}` which
    # expands to an empty string when the var is unset; pydantic-settings
    # would otherwise load that empty string and silently break enrichment.
    monkeypatch.setenv("SHEET_CSV_URL", "")
    s = Settings()
    assert s.sheet_csv_url == DEFAULT_SHEET_CSV_URL


def test_whitespace_only_sheet_csv_url_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("SHEET_CSV_URL", "   ")
    s = Settings()
    assert s.sheet_csv_url == DEFAULT_SHEET_CSV_URL


def test_explicit_sheet_csv_url_overrides(monkeypatch):
    monkeypatch.setenv("SHEET_CSV_URL", "https://example.com/foo.csv")
    s = Settings()
    assert s.sheet_csv_url == "https://example.com/foo.csv"


def test_window_defaults_decouple_racecard_from_catalogue(monkeypatch):
    # The catalogue entry_details horizon is wider than the racecard scrape
    # window so entries known days ahead aren't dropped from the morning email.
    monkeypatch.delenv("ENTRIES_WINDOW_DAYS", raising=False)
    monkeypatch.delenv("CATALOGUE_ENTRIES_WINDOW_DAYS", raising=False)
    s = Settings()
    assert s.entries_window_days == 3
    assert s.catalogue_entries_window_days == 7


def test_catalogue_window_overridable(monkeypatch):
    monkeypatch.setenv("CATALOGUE_ENTRIES_WINDOW_DAYS", "10")
    s = Settings()
    assert s.catalogue_entries_window_days == 10


def test_email_to_list_always_includes_baked_recipients(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "")
    s = Settings()
    assert s.email_to_list == list(_ALWAYS_RECIPIENTS)


def test_fred_is_a_baked_recipient(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "")
    s = Settings()
    assert "fred@blandfordbloodstock.com" in s.email_to_list


def test_email_to_list_merges_configured_after_baked(monkeypatch):
    monkeypatch.setenv("EMAIL_TO", "extra@example.com, another@example.com")
    s = Settings()
    assert s.email_to_list == [
        *_ALWAYS_RECIPIENTS,
        "extra@example.com",
        "another@example.com",
    ]


def test_email_to_list_dedups_case_insensitively(monkeypatch):
    # If a configured address collides with a baked-in one (any case), the
    # baked-in entry wins and the duplicate is dropped.
    dup = _ALWAYS_RECIPIENTS[0].upper()
    monkeypatch.setenv("EMAIL_TO", f"{dup}, fresh@example.com")
    s = Settings()
    assert s.email_to_list == [*_ALWAYS_RECIPIENTS, "fresh@example.com"]


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    # Stop a developer's real .env from leaking into these assertions.
    monkeypatch.chdir(tmp_path)
