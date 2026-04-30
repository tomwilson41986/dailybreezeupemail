from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "12neJo7BsCsHg20m-es5ERkLJCevUzXyMDnvV9-ygrMk/export?format=csv"
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
    db_path: Path = Field(default=Path("data/breezeup.sqlite"))

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
        return [x.strip() for x in self.email_to.split(",") if x.strip()]


def load() -> Settings:
    return Settings()
