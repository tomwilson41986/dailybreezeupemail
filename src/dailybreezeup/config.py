from datetime import date
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "12neJo7BsCsHg20m-es5ERkLJCevUzXyMDnvV9-ygrMk/export?format=csv"
)

# Recipients that always receive every email regardless of the configured
# EMAIL_TO env var. Merged with EMAIL_TO at send time, deduped case-
# insensitively, in this order followed by the env-configured addresses.
_ALWAYS_RECIPIENTS: tuple[str, ...] = (
    "stuart@blandfordbloodstock.com",
    "richard@blandfordbloodstock.com",
    "tom.biggs@blandfordbloodstock.com",
    "fred@blandfordbloodstock.com",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gmail_user: str = ""
    gmail_app_password: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587

    email_from: str = ""
    email_to: str = ""

    notify_on_empty: bool = False
    entries_window_days: int = 3
    # Forward horizon (days, inclusive) for the catalogue entry_details
    # fallback. The racecards scrape is capped at entries_window_days because
    # it's expensive and declarations only publish ~48h out; the catalogue,
    # by contrast, is fetched for free and knows about entries days ahead (UK
    # flat entries close at the 5-6 day stage). Capping the catalogue path at
    # the same 3 days silently dropped grads whose only engagement was 4+ days
    # out. 7 days covers the entry-closing stage without listing the months-out
    # long-range entries the catalogue also carries.
    catalogue_entries_window_days: int = 7
    db_path: Path = Field(default=Path("data/breezeup.sqlite"))

    # First result date the season-to-date summary should cover. The evening
    # run self-heals the archive back to this date (see daily._ensure_season_archive),
    # so graduates that ran before the results feature launched still count.
    season_start_date: date = Field(default=date(2026, 4, 1))

    sheet_csv_url: str = DEFAULT_SHEET_CSV_URL

    @field_validator("sheet_csv_url", mode="before")
    @classmethod
    def _empty_url_uses_default(cls, v: object) -> object:
        # GitHub Actions expands `${{ vars.SHEET_CSV_URL }}` to an empty
        # string when the variable is unset, which would otherwise clobber
        # the default and break sheet enrichment silently.
        if isinstance(v, str) and not v.strip():
            return DEFAULT_SHEET_CSV_URL
        return v

    @property
    def email_to_list(self) -> list[str]:
        configured = [x.strip() for x in self.email_to.split(",") if x.strip()]
        merged: list[str] = []
        seen: set[str] = set()
        for addr in (*_ALWAYS_RECIPIENTS, *configured):
            key = addr.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(addr)
        return merged


def load() -> Settings:
    return Settings()
