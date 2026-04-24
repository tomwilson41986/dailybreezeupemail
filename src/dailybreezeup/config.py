from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    the_racing_api_user: str = ""
    the_racing_api_pass: str = ""

    gmail_user: str = ""
    gmail_app_password: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587

    email_from: str = ""
    email_to: str = ""

    sheet_url: str = ""

    notify_on_empty: bool = False
    db_path: Path = Field(default=Path("data/breezeup.sqlite"))

    @property
    def email_to_list(self) -> list[str]:
        return [x.strip() for x in self.email_to.split(",") if x.strip()]


def load() -> Settings:
    return Settings()
