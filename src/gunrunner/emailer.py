"""The Friday email: a short note with the top ten, the PDF and the CSVs attached."""

from __future__ import annotations

import html
import logging
import smtplib
from dataclasses import dataclass, field
from datetime import date
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from gunrunner.config import Settings
from gunrunner.report import MAROON, PAPER, peak_text
from gunrunner.score import Assessment

log = logging.getLogger(__name__)
e = html.escape


@dataclass
class Email:
    subject: str
    text: str
    html: str
    attachments: list[Path] = field(default_factory=list)


def compose(
    rows: list[Assessment],
    *,
    run_date: date,
    scored: int,
    new_ids: set[str],
    attachments: list[Path],
    pool: str = "fillies and mares",
    watch: list[Assessment] = (),
) -> Email:
    watch = list(watch)
    n_new = sum(1 for r in rows + watch if r.lot_id in new_ids)
    counted = f"{len(rows)} + {len(watch)} HIT watch" if watch else f"{len(rows)}"
    subject = f"Gun Runner Mare Prospects — {run_date:%a %-d %b %Y} ({counted}, {n_new} new)"
    top = rows[:10]
    lines = [
        f"GUN RUNNER MARE PROSPECTS — {run_date:%A %-d %B %Y}",
        f"{len(rows)} prospects{f' and {len(watch)} on the HIT watch' if watch else ''} from "
        f"{scored:,} {pool}. {n_new} new this week.",
        "",
        "Top 10",
    ]
    for i, r in enumerate(top, 1):
        c = r.p.c
        lines.append(
            f"{i:>2}. {r.score:>3.0f}  {c.display_name} — {c.house} lot {c.lot_no}, {r.status}, "
            f"by {c.sire}, {peak_text(r)}"
        )
    if watch:
        lines += ["", "HIT watch (below the main bar)"]
        for i, r in enumerate(watch, 1):
            c = r.p.c
            lines.append(
                f"W{i}. {r.score:>3.0f}  {c.display_name} — {c.house} lot {c.lot_no}, "
                f"by {c.sire}, {peak_text(r)}"
            )
    lines += ["", "Attached: " + ", ".join(p.name for p in attachments)]
    td = "padding:4px 6px;border-bottom:1px solid #E4DFD8;font-size:13px"

    def cell(v: str, style: str = "") -> str:
        return f"<td style='{td};{style}'>{v}</td>"

    def tr(n: int, label: str, r: Assessment) -> str:
        return (
            f"<tr style='background:{PAPER if n % 2 == 0 else '#fff'}'>"
            + cell(label)
            + cell(f"{r.score:.0f}", f"color:{MAROON};font-weight:600")
            + cell(e(r.p.c.display_name) + (" ●" if r.lot_id in new_ids else ""), "font-weight:600")
            + cell(f"{e(r.p.c.house)} {e(r.p.c.lot_no)}")
            + cell(e(r.status))
            + cell(e(r.p.c.sire))
            + cell(e(peak_text(r)))
            + "</tr>"
        )

    head = (
        f"<tr style='background:{MAROON};color:#fff;font-size:12px;text-align:left'>"
        "<th style='padding:4px 6px'>#</th><th>Match</th><th>Horse</th><th>Lot</th><th>Status</th>"
        "<th>Sire</th><th>Peak / fit</th></tr>"
    )
    trs = "".join(tr(i, str(i), r) for i, r in enumerate(top, 1))
    watch_html = (
        "<p style='font-size:14px;margin-top:18px'><b>HIT watch</b> · fillies in training below the main bar</p>"
        f"<table style='border-collapse:collapse;width:100%'>{head}"
        + "".join(tr(i, f"W{i}", r) for i, r in enumerate(watch, 1))
        + "</table>"
        if watch
        else ""
    )
    body = f"""<div style="font-family:Arial,sans-serif;color:#1D1D1F;max-width:720px">
<div style="background:{MAROON};color:#fff;padding:14px 18px"><div style="font-size:11px;letter-spacing:.18em;text-transform:uppercase;opacity:.85">Weekly · {run_date:%-d %B %Y}</div>
<div style="font-size:24px;font-weight:600">Gun Runner Mare Prospects</div></div>
<p style="font-size:14px">{len(rows)} prospects{f" and {len(watch)} on the HIT watch" if watch else ""} from {scored:,} {pool}. {n_new} new this week.</p>
<table style="border-collapse:collapse;width:100%">
{head}
{trs}
</table>
{watch_html}
<p style="font-size:12px;color:#6B6B6B">● new this week. One page per prospect in the PDF; every filly and mare scored in the CSV.</p>
</div>"""
    return Email(subject=subject, text="\n".join(lines) + "\n", html=body, attachments=attachments)


_TYPES = {".pdf": ("application", "pdf"), ".csv": ("text", "csv")}


def build_message(mail: Email, sender: str, recipients: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = mail.subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(
        domain=sender.split("@", 1)[-1] if "@" in sender else "localhost"
    )
    msg.set_content(mail.text)
    msg.add_alternative(mail.html, subtype="html")
    for path in mail.attachments:
        maintype, subtype = _TYPES.get(path.suffix.lower(), ("application", "octet-stream"))
        msg.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
        )
    return msg


def send(mail: Email, settings: Settings) -> None:
    if not settings.gmail_user or not settings.gmail_app_password:
        raise RuntimeError("GMAIL_USER and GMAIL_APP_PASSWORD must be set")
    sender = settings.email_from or settings.gmail_user
    recipients = settings.recipients
    msg = build_message(mail, sender, recipients)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=60) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(settings.gmail_user, settings.gmail_app_password)
        smtp.send_message(msg, from_addr=sender, to_addrs=recipients)
    log.info("sent to %d recipient(s)", len(recipients))
