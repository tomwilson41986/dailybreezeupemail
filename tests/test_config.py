import pytest

from dailybreezeup.config import DEFAULT_SHEET_CSV_URL, Settings


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


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    # Stop a developer's real .env from leaking into these assertions.
    monkeypatch.chdir(tmp_path)
