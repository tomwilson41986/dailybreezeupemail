from datetime import date
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Recipients that always receive the Sales Catalogues digest regardless of the
# CATALOGUES_EMAIL_TO / EMAIL_TO env vars. Merged with the configured list at
# send time, deduped case-insensitively, in this order first.
_ALWAYS_RECIPIENTS: tuple[str, ...] = (
    "racingsquared@gmail.com",
    "stuart@blandfordbloodstock.com",
    "richard@blandfordbloodstock.com",
    "fred@blandfordbloodstock.com",
)

# Recipients who only get the digest on a Friday (they opted out of the
# dailies but still want one edition a week). Appended after the always-on
# list when the run date is a Friday.
_FRIDAY_ONLY_RECIPIENTS: tuple[str, ...] = (
    "tom.biggs@blandfordbloodstock.com",
)

_FRIDAY = 4  # date.weekday() value


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
        configured = raw.replace(";", ",").replace("\n", ",").split(",")
        parts: list[str] = []
        seen: set[str] = set()
        # Always-on recipients first, then any env-configured addresses.
        for chunk in (*_ALWAYS_RECIPIENTS, *configured):
            addr = chunk.strip()
            if addr and addr.lower() not in seen:
                seen.add(addr.lower())
                parts.append(addr)
        return parts

    def recipients_for(self, run_date: date) -> list[str]:
        """The digest recipients for a given run date: the always-on +
        env-configured list, plus the Friday-only subscribers when the run
        date is a Friday."""
        parts = self.email_to_list
        if run_date.weekday() != _FRIDAY:
            return parts
        seen = {addr.lower() for addr in parts}
        return parts + [a for a in _FRIDAY_ONLY_RECIPIENTS if a.lower() not in seen]


def load() -> Settings:
    return Settings()
