from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration for the Daily Sales Catalogues job.

    Reuses the same Gmail SMTP secrets as the breeze-up job so the two can share
    a single set of GitHub Actions secrets.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gmail_user: str = ""
    gmail_app_password: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587

    email_from: str = ""
    # Recipients for the catalogues digest. Comma / semicolon / newline
    # separated. Kept distinct from the breeze-up EMAIL_TO so the two lists can
    # diverge; falls back to EMAIL_TO when unset.
    catalogues_email_to: str = ""
    email_to: str = ""

    # Send the digest even when there are no New or Active catalogues today.
    notify_on_empty: bool = False
    # Days before a sale's first day that it counts as "Active".
    active_lead_days: int = 2
    # Only sales starting within this many days ahead are listed (keeps the
    # digest to the imminent season rather than the whole forward calendar).
    horizon_days: int = 30

    db_path: Path = Field(default=Path("data/salescatalogues.sqlite"))

    @property
    def email_to_list(self) -> list[str]:
        raw = self.catalogues_email_to or self.email_to
        parts: list[str] = []
        seen: set[str] = set()
        for chunk in raw.replace(";", ",").replace("\n", ",").split(","):
            addr = chunk.strip()
            if addr and addr.lower() not in seen:
                seen.add(addr.lower())
                parts.append(addr)
        return parts


def load() -> Settings:
    return Settings()
