"""Deliver the finished report by email.

Uses the same credentials as the rest of this repository, so one set of secrets
serves every daily job:

=======================  ======================================================
``GMAIL_USER``           account to authenticate as
``GMAIL_APP_PASSWORD``   its 16-character app password
``SMTP_HOST``            defaults to ``smtp.gmail.com``
``SMTP_PORT``            defaults to 587 (STARTTLS); 465 for implicit TLS
``EMAIL_FROM``           envelope sender (defaults to ``GMAIL_USER``)
``WATHNAN_EMAIL_TO``     recipients for this report specifically
``EMAIL_TO``             fallback recipient list shared with the other jobs
=======================  ======================================================

``SMTP_USER`` / ``SMTP_PASSWORD`` / ``MAIL_FROM`` / ``MAIL_TO`` are still read
as overrides, so a standalone deployment of this package alone keeps working.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .normalise import format_clock, format_day, format_long_date, qatar_time

LOG = logging.getLogger(__name__)

#: Who gets the report when nothing is configured. This report goes to the
#: Wathnan team rather than the breeze-up lists, so it has its own variable.
DEFAULT_RECIPIENTS = ("racingsquared@gmail.com", "sophie@wathnan-racing.com")

#: Checked in order; the first that is set wins.
RECIPIENT_VARS = ("WATHNAN_EMAIL_TO", "MAIL_TO", "EMAIL_TO")
USER_VARS = ("GMAIL_USER", "SMTP_USER")
PASSWORD_VARS = ("GMAIL_APP_PASSWORD", "SMTP_PASSWORD")
SENDER_VARS = ("EMAIL_FROM", "MAIL_FROM")


def _first_set(names: tuple[str, ...]) -> str:
    """Return the first of ``names`` that has a non-empty value.

    CI expands an unset ``${{ vars.X }}`` to an empty string, so "present but
    blank" has to count as unset or it clobbers the fallback.
    """
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


class MailError(RuntimeError):
    """Raised when the report could not be sent."""


def recipients() -> list[str]:
    configured = _first_set(RECIPIENT_VARS)
    people = [address.strip()
              for address in configured.replace(";", ",").split(",")
              if address.strip()]
    return people or list(DEFAULT_RECIPIENTS)


def build_message(summary, pdf: Path, sender: str, to: list[str]) -> EmailMessage:
    """Compose the morning email: a short digest with the PDF attached."""
    message = EmailMessage()
    message["Subject"] = (f"Wathnan Racing runners – "
                          f"{format_long_date(summary.config.tomorrow, upper=False)}")
    message["From"] = sender
    message["To"] = ", ".join(to)
    message.set_content(_plain_text(summary))
    message.add_alternative(_html(summary), subtype="html")

    data = Path(pdf).read_bytes()
    message.add_attachment(data, maintype="application", subtype="pdf",
                           filename=Path(pdf).name)
    return message


def send(summary, pdf: Path) -> list[str]:
    """Send the report, returning the addresses it went to."""
    host = _first_set(("SMTP_HOST",)) or "smtp.gmail.com"
    user = _first_set(USER_VARS)
    password = _first_set(PASSWORD_VARS)
    if not (user and password):
        raise MailError("set GMAIL_USER and GMAIL_APP_PASSWORD to send email")

    port = int(_first_set(("SMTP_PORT",)) or "587")
    sender = _first_set(SENDER_VARS) or user
    to = recipients()
    message = build_message(summary, pdf, sender, to)

    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=60) as server:
                server.login(user, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=60) as server:
                server.starttls(context=context)
                server.login(user, password)
                server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"could not send the report: {exc}") from exc

    LOG.info("emailed the report to %s", ", ".join(to))
    return to


# -- body ----------------------------------------------------------------------
def _headline(summary) -> str:
    runners = sum(len(race.runners) for race in summary.tomorrow)
    entries = sum(len(race.runners) for race in summary.entries)
    return (f"{runners} runner{'s' if runners != 1 else ''} declared for "
            f"{format_long_date(summary.config.tomorrow, upper=False)}, "
            f"and {entries} entr{'ies' if entries != 1 else 'y'} through "
            f"{format_long_date(summary.config.entries_until, upper=False)}.")


def _rows(summary) -> list[tuple[str, ...]]:
    rows = []
    for race in summary.tomorrow:
        uk = race.off_time_uk
        for runner in race.runners:
            rows.append((
                format_day(race.date), race.course, format_clock(uk),
                format_clock(qatar_time(uk, race.date)), runner.horse,
                runner.trainer, runner.display_jockey(),
            ))
    return rows


def _plain_text(summary) -> str:
    lines = [_headline(summary), ""]
    if summary.tomorrow:
        lines.append("TOMORROW'S RUNNERS")
        for _date, course, uk, qatar, horse, trainer, jockey in _rows(summary):
            lines.append(f"  {uk:>8} UK / {qatar:>8} QA  {course} - {horse} "
                         f"({trainer}, {jockey})")
    else:
        lines.append("No runners declared for tomorrow.")
    lines += ["", "The full report is attached."]
    for note in summary.notes():
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def _html(summary) -> str:
    rows = _rows(summary)
    if rows:
        cells = "".join(
            "<tr>"
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6e6e6">{course}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6e6e6">{uk}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6e6e6">{qatar}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6e6e6">'
            f'<strong>{horse}</strong></td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6e6e6">{trainer}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e6e6e6">{jockey}</td>'
            "</tr>"
            for _date, course, uk, qatar, horse, trainer, jockey in rows)
        table = (
            '<table cellspacing="0" cellpadding="0" '
            'style="border-collapse:collapse;font-size:14px;margin-top:14px">'
            '<thead><tr style="background:#9FC5E8;text-align:left">'
            + "".join(f'<th style="padding:6px 10px">{head}</th>' for head in
                      ("Course", "UK", "Qatar", "Horse", "Trainer", "Jockey"))
            + f"</tr></thead><tbody>{cells}</tbody></table>")
    else:
        table = "<p>No runners declared for tomorrow.</p>"

    notes = "".join(f'<p style="color:#8a6d3b;font-size:13px">{note}</p>'
                    for note in summary.notes())
    return (
        '<div style="font-family:Helvetica,Arial,sans-serif;color:#222">'
        f'<p style="font-size:15px">{_headline(summary)}</p>'
        f"{table}"
        '<p style="font-size:14px;margin-top:16px">The full report is attached.</p>'
        f"{notes}</div>")
