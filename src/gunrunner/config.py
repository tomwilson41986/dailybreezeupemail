"""Environment for the Gun Runner weekly (pydantic-settings, as the other jobs)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_RECIPIENTS = ("racingsquared@gmail.com", "greg@p2bloodstock.com")
# The covering sires a first-foal mare may carry to make the list
COVER_SIRES = (
    "Into Mischief",
    "Not This Time",
    "Gun Runner",
    "Curlin",
    "Vekoma",
    "Epicenter",
    "Gunite",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gmail_user: str = ""
    gmail_app_password: str = ""
    email_from: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    # comma-separated; empty means the default pair
    gunrunner_email_to: str = ""

    parse_bot_api_key: str = ""
    # parse.bot credits one run may spend on Equibase lookups (each horse is fetched once, ever)
    gunrunner_equibase_credits: int = 1500
    gunrunner_equibase_floor: int = 50

    # sales selling within this many days are covered
    gunrunner_horizon_days: int = 70
    website: str = "https://www.blandfordbloodstock.tech"
    # the site's sale data folders, kind:slug, comma-separated
    gunrunner_website_sales: str = (
        "bms:keeneland-nov-2026,bms:fasig-nov-2026,"
        "hitsales:tatts-autumn-hit-2026,hitsales:arc-sale-2026,hitsales:tatts-july-2026"
    )
    family_api: str = "https://horseracesbackend-production.up.railway.app/api/breeding/family"
    data_dir: Path = Field(default=Path("data/gunrunner"))

    @property
    def website_sales(self) -> list[str]:
        return [s.strip() for s in self.gunrunner_website_sales.split(",") if ":" in s]

    @property
    def recipients(self) -> list[str]:
        raw = self.gunrunner_email_to.replace(";", ",").split(",")
        out = [a.strip() for a in raw if a.strip()]
        return out or list(DEFAULT_RECIPIENTS)


def load() -> Settings:
    return Settings()
