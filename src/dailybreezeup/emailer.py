from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests
from jinja2 import Environment, PackageLoader, select_autoescape

from dailybreezeup.config import Settings

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


@dataclass
class EmailPayload:
    subject: str
    html: str
    text: str


def _env() -> Environment:
    return Environment(
        loader=PackageLoader("dailybreezeup", "templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "html.j2"), default_for_string=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render(
    *,
    run_date: date,
    ran_yesterday: list[dict[str, Any]],
    declared: list[dict[str, Any]],
    entered: list[dict[str, Any]],
) -> EmailPayload:
    env = _env()
    total = len(ran_yesterday) + len(declared) + len(entered)
    subject = f"Breeze-up graduates — {run_date:%a %d %b %Y} ({total} horse{'' if total == 1 else 's'})"
    context = {
        "run_date": run_date,
        "total": total,
        "ran_yesterday": ran_yesterday,
        "declared": declared,
        "entered": entered,
        "subject": subject,
    }
    html = env.get_template("email.html.j2").render(**context)
    text = env.get_template("email.txt.j2").render(**context)
    return EmailPayload(subject=subject, html=html, text=text)


def send(payload: EmailPayload, settings: Settings) -> None:
    if not settings.resend_api_key:
        raise RuntimeError("RESEND_API_KEY is not set")
    if not settings.email_from or not settings.email_to_list:
        raise RuntimeError("EMAIL_FROM / EMAIL_TO must be set")

    body = {
        "from": settings.email_from,
        "to": settings.email_to_list,
        "subject": payload.subject,
        "html": payload.html,
        "text": payload.text,
    }
    r = requests.post(
        RESEND_URL,
        json=body,
        headers={
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    r.raise_for_status()
    log.info("Resend accepted email: %s", r.json().get("id", "?"))
