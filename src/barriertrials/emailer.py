from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from barriertrials.config import Settings
from dailybreezeup import silks

log = logging.getLogger(__name__)

_DIVIDER = "─" * 60


@dataclass
class EmailPayload:
    subject: str
    html: str
    text: str


def _env() -> Environment:
    return Environment(
        loader=PackageLoader("barriertrials", "templates"),
        autoescape=select_autoescape(
            enabled_extensions=("html", "html.j2"), default_for_string=False
        ),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _fmt_ratings(ratings: dict[str, Any] | None) -> str:
    if not ratings:
        return ""
    parts = []
    for label, value in ratings.items():
        parts.append(f"{label} {value:.1f}" if value is not None else f"{label} —")
    return "  ·  ".join(parts)


def _fmt_fields(fields: dict[str, Any] | None) -> list[str]:
    """One ``Label: value`` per non-empty column, wrapped a few per line."""
    if not fields:
        return []
    pairs = [f"{label}: {value}" for label, value in fields.items() if value not in (None, "")]
    out: list[str] = []
    for i in range(0, len(pairs), 3):
        out.append("    " + "   ".join(pairs[i:i + 3]))
    return out


def _fmt_card(row: dict[str, Any], *, ran: bool) -> list[str]:
    horse_label = row.get("horse_name") or "(unnamed)"
    lines: list[str] = [_DIVIDER, horse_label]

    ratings_line = _fmt_ratings(row.get("ratings"))
    if ratings_line:
        lines.append(f"    {ratings_line}")

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

    lines.extend(_fmt_fields(row.get("fields")))
    # Entries email: the horse's results so far this season, under the entry.
    history = row.get("history") if not ran else None
    if history:
        lines.append(f"    Results so far · {len(history)}:")
        lines.extend(_fmt_runs(history))
    lines.append(f"    {row['race_url']}")
    return lines


def _fmt_runs(runs: list[Any]) -> list[str]:
    """Compact one-line-per-run form list (accepts dicts or HorseRun objects)."""
    out: list[str] = []
    for run in runs:
        rd = _run_attr(run, "race_date")
        d = rd.strftime("%d %b") if rd else "—"
        course = _run_attr(run, "course") or ""
        race_name = _run_attr(run, "race_name") or ""
        pos = _run_attr(run, "finishing_position") or "—"
        total = _run_attr(run, "total_runners")
        pos_label = f"{pos}/{total}" if total else pos
        sp = _run_attr(run, "sp") or "—"
        rpr = _run_attr(run, "rpr")
        rpr_label = f"RPR {rpr}" if rpr is not None else "RPR —"
        suffix = f" {race_name}" if race_name else ""
        out.append(f"        {d:>6}  {pos_label:>6}  {course}{suffix}  SP {sp}  {rpr_label}")
    return out


def _run_attr(run: Any, key: str) -> Any:
    if isinstance(run, dict):
        return run.get(key)
    return getattr(run, key, None)


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _fmt_rpr(x: float | None) -> str:
    return f"{x:.0f}" if x is not None else "—"


def _fmt_band_table(title: str, rows: list[Any]) -> list[str]:
    out = [title, f"  {'Band':<8} {'n':>4} {'W':>4} {'SR':>5} {'avgRPR':>7}"]
    for r in rows:
        flag = "  *" if r.low_n else "   "
        out.append(
            f"{flag}{r.label:<8} {r.n_runners:>4} {r.n_winners:>4} "
            f"{_fmt_pct(r.strike_rate):>5} {_fmt_rpr(r.avg_rpr):>7}"
        )
    return out


def _render_text(
    *,
    run_date: date,
    entered: list[dict[str, Any]],
    ran_today: list[dict[str, Any]],
    entries_window_days: int,
    total: int,
    diagnostics: dict[str, Any],
    mode: str,
    season_summary: dict[str, Any] | None = None,
) -> str:
    plural = "" if total == 1 else "s"
    parts: list[str] = [
        f"Barrier-trial watchlist — {run_date:%A %d %B %Y}",
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
        if season_summary:
            parts.append("")
            parts.append(
                f"═══ HISTORIC RESULTS · since {season_summary.get('season_start', '')} · "
                f"{season_summary['total_runs']} runs ═══"
            )
            for rating in season_summary["by_rating"]:
                if rating["bands"]:
                    parts.append("")
                    parts.extend(
                        _fmt_band_table(
                            f"PERFORMANCE BY {rating['label'].upper()} BAND", rating["bands"]
                        )
                    )
            parts.append("")
            parts.append(f"  * = small sample (n<{season_summary['low_n_threshold']})")
            if season_summary.get("horses"):
                parts.append("")
                parts.append(f"─── TRACKED HORSES & RESULTS · {len(season_summary['horses'])} ───")
                for rec in season_summary["horses"]:
                    parts.append("")
                    ratings = "  ·  ".join(
                        f"{label} {value:.1f}" if value is not None else f"{label} —"
                        for label, value in rec.ratings.items()
                    )
                    parts.append(f"{rec.horse_name}  [{ratings}]  {rec.status_label}")
                    parts.extend(_fmt_runs(rec.runs))
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
                f"No watchlist horses entered in the next "
                f"{entries_window_days} day{'' if entries_window_days == 1 else 's'}."
            )
    sheet_status = diagnostics.get("sheet_status")
    if sheet_status and total > 0:
        parts.append("")
        parts.append(f"Watchlist: {sheet_status}.")
    return "\n".join(parts) + "\n"


def render(
    *,
    run_date: date,
    entered: list[dict[str, Any]],
    ran_today: list[dict[str, Any]],
    entries_window_days: int = 3,
    diagnostics: dict[str, Any] | None = None,
    mode: str = "morning",
    season_summary: dict[str, Any] | None = None,
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
            subject = f"Barrier-trial results — {run_date:%a %d %b %Y} · No Results Today"
        else:
            subject = (
                f"Barrier-trial results — {run_date:%a %d %b %Y} "
                f"({total} horse{'' if total == 1 else 's'})"
            )
    else:
        subject = (
            f"Barrier-trial entries — {run_date:%a %d %b %Y} "
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
        "season_summary": season_summary if mode == "evening" else None,
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
        season_summary=season_summary if mode == "evening" else None,
    )
    return EmailPayload(subject=subject, html=html, text=text)


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
