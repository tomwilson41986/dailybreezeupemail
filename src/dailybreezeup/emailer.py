from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from dailybreezeup import silks
from dailybreezeup.config import Settings

log = logging.getLogger(__name__)

_DIVIDER = "─" * 60


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


def _fmt_card(row: dict[str, Any], *, ran: bool) -> list[str]:
    sire = row.get("sheet_sire") or row.get("sire") or ""
    dam = row.get("sheet_dam") or row.get("dam") or ""
    damsire = row.get("damsire") or ""
    price = row.get("sheet_price") or row.get("price") or ""
    buyer = row.get("sheet_buyer") or row.get("buyer") or ""
    vendor = row.get("sheet_vendor") or row.get("seller") or ""
    short_sale = (
        f"{row['sale_short']} {row['sale_year']}"
        if row.get("sale_short")
        else row.get("sale_name", "")
    )
    horse_label = row.get("horse_name") or f"Lot {row['lot']} (unnamed)"

    lines: list[str] = [_DIVIDER, f"LOT {row['lot']} · {short_sale}", horse_label]
    if sire or dam:
        ped = f"{sire or '?'} × {dam or '?'}"
        if damsire:
            ped += f" (by {damsire})"
        lines.append(f"    {ped}")

    if ran:
        finish = row.get("finishing_position") or "—"
        total = row.get("total_runners")
        finish_label = f"{finish} / {total}" if total else finish
        sp = row.get("sp") or "—"
        off = row.get("off_time")
        race_name = row.get("race_name") or ""
        time_prefix = f"{off.strftime('%H:%M')} " if off else ""
        race_suffix = f" · {race_name}" if race_name else ""
        lines.append(f"    ► Finish {finish_label}  ·  SP {sp}")
        lines.append(f"    ► {time_prefix}{row['course']}{race_suffix}")
    else:
        off = row.get("off_time")
        time_prefix = f"{off.strftime('%H:%M')} " if off else ""
        race_name = row.get("race_name") or ""
        race_suffix = f" · {race_name}" if race_name else ""
        lines.append(
            f"    ► {row['race_date']:%a %d %b} · {time_prefix}{row['course']}{race_suffix}"
        )

    if row.get("sheet_matched"):
        br = row.get("sheet_breeze_rating")
        pr = row.get("sheet_precocity_rating")
        if br is not None or pr is not None:
            br_s = f"{br:.1f}" if br is not None else "—"
            pr_s = f"{pr:.1f}" if pr is not None else "—"
            lines.append(f"    Breeze {br_s}  ·  Precocity {pr_s}")

        ot_rank = row.get("sheet_ot_rank")
        ot_diff = row.get("sheet_ot_diff_m")
        sl_1f = row.get("sheet_sl_1f")
        sl_go = row.get("sheet_sl_go")
        if ot_rank is not None or sl_1f is not None or sl_go is not None:
            ot_total = row.get("sheet_sale_total")
            ot_part = f"OT #{ot_rank if ot_rank is not None else '—'}"
            if ot_total:
                ot_part += f"/{ot_total}"
            if ot_diff is not None:
                ot_part += f" ({ot_diff:+.2f}s)"
            sl_part = (
                f"SL 1F {sl_1f:.2f}" if sl_1f is not None else "SL 1F —"
            ) + (
                f"  ·  SL GO {sl_go:.2f}" if sl_go is not None else "  ·  SL GO —"
            )
            lines.append(f"    {ot_part}  ·  {sl_part}")

    if price or buyer or vendor:
        commercial = " · ".join(p for p in (price, buyer, vendor) if p)
        lines.append(f"    {commercial}")

    lines.append(f"    {row['race_url']}")
    return lines


def _render_text(
    *,
    run_date: date,
    entered: list[dict[str, Any]],
    ran_today: list[dict[str, Any]],
    entries_window_days: int,
    total: int,
    diagnostics: dict[str, Any],
    mode: str,
) -> str:
    plural = "" if total == 1 else "s"
    parts: list[str] = [
        f"Breeze-up graduates — {run_date:%A %d %B %Y}",
        f"{total} horse{plural}",
        "",
    ]
    if mode == "evening":
        if ran_today:
            parts.append(f"═══ RAN TODAY · {len(ran_today)} ═══")
            for row in ran_today:
                parts.extend(_fmt_card(row, ran=True))
                parts.append("")
        else:
            parts.append("No Results Today")
    else:  # morning
        if entered:
            win_plural = "" if entries_window_days == 1 else "S"
            parts.append(
                f"═══ ENTRIES & DECLARATIONS · NEXT {entries_window_days} DAY{win_plural} "
                f"· {len(entered)} ═══"
            )
            for row in entered:
                parts.extend(_fmt_card(row, ran=False))
                parts.append("")
        else:
            parts.append(
                f"No breeze-up graduates entered in the next "
                f"{entries_window_days} day{'' if entries_window_days == 1 else 's'}."
            )
    sheet_status = diagnostics.get("sheet_status")
    if sheet_status and total > 0:
        parts.append("")
        parts.append(f"Sheet enrichment: {sheet_status}.")
    return "\n".join(parts) + "\n"


def render(
    *,
    run_date: date,
    entered: list[dict[str, Any]],
    ran_today: list[dict[str, Any]],
    entries_window_days: int = 3,
    diagnostics: dict[str, Any] | None = None,
    mode: str = "morning",
) -> EmailPayload:
    diagnostics = diagnostics or {}
    if mode not in ("morning", "evening"):
        raise ValueError(f"mode must be 'morning' or 'evening', got {mode!r}")
    silks.assign_silk_cids(entered)
    silks.assign_silk_cids(ran_today)
    env = _env()
    # Each mode owns one section; the other list is ignored even if populated.
    total = len(ran_today) if mode == "evening" else len(entered)
    if mode == "evening":
        if total == 0:
            subject = f"Breeze-up results — {run_date:%a %d %b %Y} · No Results Today"
        else:
            subject = (
                f"Breeze-up results — {run_date:%a %d %b %Y} "
                f"({total} horse{'' if total == 1 else 's'})"
            )
    else:
        subject = (
            f"Breeze-up entries — {run_date:%a %d %b %Y} "
            f"({total} horse{'' if total == 1 else 's'})"
        )
    context = {
        "run_date": run_date,
        "total": total,
        "entered": entered,
        "ran_today": ran_today,
        "entries_window_days": entries_window_days,
        "subject": subject,
        "diagnostics": diagnostics,
        "mode": mode,
    }
    html = env.get_template("email.html.j2").render(**context)
    text = _render_text(
        run_date=run_date,
        entered=entered,
        ran_today=ran_today,
        entries_window_days=entries_window_days,
        total=total,
        diagnostics=diagnostics,
        mode=mode,
    )
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


def send(
    payload: EmailPayload,
    settings: Settings,
    *,
    silk_rows: list[dict[str, Any]] | None = None,
) -> None:
    if not settings.gmail_user or not settings.gmail_app_password:
        raise RuntimeError("GMAIL_USER and GMAIL_APP_PASSWORD must be set")
    recipients = settings.email_to_list
    if not recipients:
        raise RuntimeError("EMAIL_TO must be set (comma-separated allowed)")

    sender = settings.email_from or settings.gmail_user
    msg = _build_message(payload, sender, recipients)
    if silk_rows:
        attached = silks.attach_silks(msg, silk_rows)
        if attached:
            log.info("attached %d silk image(s) inline", attached)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(settings.gmail_user, settings.gmail_app_password)
        smtp.send_message(msg, from_addr=sender, to_addrs=recipients)
    log.info("SMTP delivered email to %d recipient(s)", len(recipients))
