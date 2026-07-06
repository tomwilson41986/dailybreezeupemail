"""Render the digest (HTML + plain text) and send it via Gmail SMTP with the
CSV of all listed catalogues attached.
"""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from salescatalogues.classify import order_by_date
from salescatalogues.config import Settings
from salescatalogues.csvout import to_csv
from salescatalogues.models import Catalogue, Lot

log = logging.getLogger(__name__)


@dataclass
class EmailPayload:
    subject: str
    html: str
    text: str
    csv_text: str
    csv_filename: str


def _env() -> Environment:
    return Environment(
        loader=PackageLoader("salescatalogues", "templates"),
        autoescape=select_autoescape(
            enabled_extensions=("html", "html.j2"), default_for_string=False
        ),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _render_text(
    run_date: date,
    catalogues: list[Catalogue],
    *,
    active_count: int,
    new_count: int,
    total: int,
) -> str:
    lines = [
        f"DAILY SALES CATALOGUES — {run_date:%A %d %B %Y}",
        f"{active_count} Active · {new_count} New · {total} catalogues",
        "",
    ]
    if not catalogues:
        lines.append("No New or Active thoroughbred sales catalogues today.")
        return "\n".join(lines) + "\n"
    for r in catalogues:
        flags = []
        if r.is_active:
            flags.append("ACTIVE")
        if r.is_new:
            flags.append("NEW")
        if r.online:
            flags.append("ONLINE")
        flag_str = f"  [{' · '.join(flags)}]" if flags else ""
        lines.append(f"  {r.date_label()} · {r.country_name} · {r.house}{flag_str}")
        lines.append(f"     {r.name} ({r.sale_type})")
        lines.append(f"     Sale & catalogue: {r.url}")
        if r.house_url:
            lines.append(f"     {r.house} website: {r.house_url}")
        lines.append("")
    lines.append(f"Full list attached: sales_catalogues_{run_date.isoformat()}.csv")
    return "\n".join(lines) + "\n"


def render(
    *,
    run_date: date,
    catalogues: list[Catalogue],
    lots_by_id: dict[str, list[Lot]] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> EmailPayload:
    diagnostics = diagnostics or {}
    ordered = order_by_date(catalogues)
    active_count = sum(1 for c in catalogues if c.is_active)
    new_count = sum(1 for c in catalogues if c.is_new)
    total = len(catalogues)

    subject = (
        f"Sales Catalogues — {run_date:%a %d %b %Y} "
        f"({active_count} active, {new_count} new)"
    )
    env = _env()
    html = env.get_template("email.html.j2").render(
        subject=subject,
        run_date=run_date,
        catalogues=ordered,
        active_count=active_count,
        new_count=new_count,
        total=total,
        diagnostics=diagnostics,
    )
    text = _render_text(
        run_date, ordered,
        active_count=active_count, new_count=new_count, total=total,
    )
    return EmailPayload(
        subject=subject,
        html=html,
        text=text,
        csv_text=to_csv(ordered, lots_by_id),
        csv_filename=f"sales_catalogues_{run_date.isoformat()}.csv",
    )


def _build_message(payload: EmailPayload, sender: str, recipients: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = payload.subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(
        domain=sender.split("@", 1)[-1] if "@" in sender else "localhost"
    )
    msg.set_content(payload.text)
    msg.add_alternative(payload.html, subtype="html")
    msg.add_attachment(
        payload.csv_text.encode("utf-8"),
        maintype="text",
        subtype="csv",
        filename=payload.csv_filename,
    )
    return msg


def send(
    payload: EmailPayload,
    settings: Settings,
    *,
    recipients: list[str] | None = None,
) -> None:
    if not settings.gmail_user or not settings.gmail_app_password:
        raise RuntimeError("GMAIL_USER and GMAIL_APP_PASSWORD must be set")
    # Callers pass the date-aware list (config.recipients_for) so Friday-only
    # subscribers get their weekly edition; the plain property is the fallback.
    if recipients is None:
        recipients = settings.email_to_list
    if not recipients:
        raise RuntimeError("CATALOGUES_EMAIL_TO (or EMAIL_TO) must be set")

    sender = settings.email_from or settings.gmail_user
    msg = _build_message(payload, sender, recipients)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(settings.gmail_user, settings.gmail_app_password)
        smtp.send_message(msg, from_addr=sender, to_addrs=recipients)
    log.info("SMTP delivered catalogues digest to %d recipient(s)", len(recipients))
