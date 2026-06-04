from datetime import date
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The barrier-trials watchlist. Defaults to the user's sheet; override per
# deployment via SHEET_CSV_URL (the public /export?format=csv endpoint).
DEFAULT_SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1hb7HzyEdZKKmVXtu3p1idPj0ktdo4s67IwAVCZ5njA0/export?format=csv"
)

# Default sheet column headers, matching the watchlist above. Overridable for a
# different layout via HORSE_NAME_COLUMN / RATING_COLUMNS. The full row is always
# reported in the email; RATING_COLUMNS only selects which numeric columns get a
# tile and drive the season-to-date band/leaderboard tables.
DEFAULT_HORSE_NAME_COLUMN = "Horse"
DEFAULT_RATING_COLUMNS = "Final Rating,TFig"


class Settings(BaseSettings):
    """Configuration for the barrier-trial horse tracker.

    Env var names mirror the breeze-up job (GMAIL_USER, EMAIL_TO, …) so the
    GitHub Actions secrets can be shared; the two run as separate jobs with
    isolated environments. Only the defaults differ — notably ``db_path`` and
    the sheet/column settings, which are this cohort's own.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gmail_user: str = ""
    gmail_app_password: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587

    email_from: str = ""
    email_to: str = ""

    notify_on_empty: bool = False
    # Forward horizon (days, inclusive) for the racecard entries scan. Matches
    # the breeze-up job's default — declarations publish ~48h out and the scan
    # is one request per race, so a tight window keeps it cheap.
    entries_window_days: int = 3
    db_path: Path = Field(default=Path("data/barriertrials.sqlite"))

    # First result date the season-to-date summary should cover. The evening run
    # self-heals the archive back to this date (see daily._ensure_season_archive),
    # so horses that ran before tracking began still count.
    season_start_date: date = Field(default=date(2026, 4, 1))

    sheet_csv_url: str = DEFAULT_SHEET_CSV_URL
    # The sheet's horse-name column header. The watchlist key is the normalised
    # value of this column.
    horse_name_column: str = DEFAULT_HORSE_NAME_COLUMN
    # Comma-separated list of the sheet's rating column headers. Each is surfaced
    # as a tile in the email and gets its own season-to-date band/leaderboard.
    rating_columns: str = DEFAULT_RATING_COLUMNS

    @field_validator("horse_name_column", mode="before")
    @classmethod
    def _name_col_default(cls, v: object) -> object:
        # GitHub Actions expands an unset `${{ vars.HORSE_NAME_COLUMN }}` to "",
        # which would otherwise clobber the default; restore it.
        if isinstance(v, str) and not v.strip():
            return DEFAULT_HORSE_NAME_COLUMN
        return v

    @field_validator("rating_columns", mode="before")
    @classmethod
    def _rating_cols_default(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return DEFAULT_RATING_COLUMNS
        return v

    @property
    def rating_column_list(self) -> list[str]:
        return [c.strip() for c in self.rating_columns.split(",") if c.strip()]

    @property
    def email_to_list(self) -> list[str]:
        configured = [x.strip() for x in self.email_to.split(",") if x.strip()]
        merged: list[str] = []
        seen: set[str] = set()
        for addr in configured:
            key = addr.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(addr)
        return merged


def load() -> Settings:
    return Settings()
