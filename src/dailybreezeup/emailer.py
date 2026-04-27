from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from dailybreezeup.config import Settings

log = logging.getLogger(__name__)


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
    entered: list[dict[str, Any]],
    ran_today: list[dict[str, Any]],
    entries_window_days: int = 5,
    diagnostics: dict[str, Any] | None = None,
) -> EmailPayload:
    env = _env()
    total = len(entered) + len(ran_today)
    subject = (
        f"Breeze-up graduates — {run_date:%a %d %b %Y} "
        f"({total} horse{'' if total == 1 else 's'})"
    )
    context = {
        "run_date": run_date,
        "total": total,
        "entered": entered,
        "ran_today": ran_today,
        "entries_window_days": entries_window_days,
        "subject": subject,
        "diagnostics": diagnostics or {},
    }
    html = env.get_template("email.html.j2").render(**context)
    text = env.get_template("email.txt.j2").render(**context)
    return EmailPayload(subject=subject, html=html, text=text)


def _build_message(payload: EmailPayload, sender: str, recipients: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = payload.subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@", 1)[-1] if "@" in sender else "localhost")
    msg.set_content(payload.text)
    msg.add_alternative(payload.html, subtype="html")
    return msg


def send(payload: EmailPayload, settings: Settings) -> None:
    if not settings.gmail_user or not settings.gmail_app_password:
        raise RuntimeError("GMAIL_USER and GMAIL_APP_PASSWORD must be set")
    recipients = settings.email_to_list
    if not recipients:
        raise RuntimeError("EMAIL_TO must be set (comma-separated allowed)")

    sender = settings.email_from or settings.gmail_user
    msg = _build_message(payload, sender, recipients)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(settings.gmail_user, settings.gmail_app_password)
        smtp.send_message(msg, from_addr=sender, to_addrs=recipients)
    log.info("SMTP delivered email to %d recipient(s)", len(recipients))
