"""Daily job: pull every current breeze-up catalogue from Racing Post, flag
any lot entered to run in the next 5 days, and any lot that ran today.

Usage:
  breezeup-daily                      # today UK, send
  breezeup-daily --dry-run            # render preview, no send
  breezeup-daily --date 2026-04-24    # force a date
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dailybreezeup.config import Settings, load as load_settings
from dailybreezeup.db import session
from dailybreezeup.emailer import EmailPayload, render, send
from dailybreezeup.racing import rp_results, rp_sales

log = logging.getLogger("dailybreezeup.daily")
UK = ZoneInfo("Europe/London")
PREVIEW_HTML = Path("data/last_preview.html")
PREVIEW_TXT = Path("data/last_preview.txt")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_default(o: Any) -> Any:
    if isinstance(o, (date, datetime, time)):
        return o.isoformat()
    raise TypeError(f"Unserialisable: {type(o)}")


def _lot_row(lot: rp_sales.SaleLot, *, race_uid: str | None) -> dict[str, Any]:
    """Flat dict used by both the email template and the dedup log."""
    return {
        "sale_name": lot.sale.sale_name,
        "sale_co": lot.sale.sale_co,
        "lot": lot.display_lot,
        "lot_id": lot.lot_id,
        "horse_uid": lot.horse_uid,
        "horse_name": lot.horse_name,
        "sire": lot.sire_name,
        "dam": lot.dam_name,
        "damsire": lot.sire_of_dam_name,
        "sex": lot.sex,
        "age": lot.age,
        "seller": lot.seller,
        "buyer": lot.buyer,
        "price": lot.price_label,
        "race_uid": race_uid,
    }


def _entered_row(lot: rp_sales.SaleLot) -> dict[str, Any]:
    entry = lot.entry
    assert entry is not None
    base = _lot_row(lot, race_uid=str(entry.race_uid))
    base.update({
        "course": entry.course_name.title(),
        "race_date": entry.race_date,
        "race_url": (
            f"https://www.racingpost.com/racecards/{entry.course_uid}/"
            f"{entry.course_name.lower().replace(' ', '-')}/"
            f"{entry.race_date.isoformat()}/{entry.race_uid}"
        ),
    })
    return base


def _ran_row(lot: rp_sales.SaleLot, hit: rp_results.ResultHit) -> dict[str, Any]:
    base = _lot_row(lot, race_uid=hit.race_uid)
    base.update({
        "course": hit.course,
        "race_date": hit.race_date,
        "off_time": hit.off_time,
        "race_name": hit.race_name,
        "finishing_position": hit.finishing_position,
        "sp": hit.sp,
        "race_url": hit.race_url,
        "horse_name": hit.horse_name or lot.horse_name,
    })
    return base


def _classify(
    today: date,
    lots: list[rp_sales.SaleLot],
    results: list[rp_results.ResultHit],
    *,
    entries_window_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    window_end = today + timedelta(days=entries_window_days)
    entered: list[dict[str, Any]] = []
    for lot in lots:
        if not (lot.entered and lot.entry):
            continue
        if not (today <= lot.entry.race_date <= window_end):
            continue
        entered.append(_entered_row(lot))

    by_uid: dict[int, rp_sales.SaleLot] = {
        lot.horse_uid: lot for lot in lots if lot.horse_uid is not None
    }
    ran: list[dict[str, Any]] = []
    for hit in results:
        lot = by_uid.get(hit.horse_uid)
        if lot is None:
            continue
        ran.append(_ran_row(lot, hit))

    entered.sort(key=lambda r: (r["race_date"], r.get("course") or "", r["lot"]))
    ran.sort(key=lambda r: (r.get("off_time") or time(0, 0), r.get("course") or "", r["lot"]))
    return entered, ran


def _filter_already_sent(
    conn: sqlite3.Connection,
    today: date,
    category: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fresh: list[dict[str, Any]] = []
    for row in rows:
        existing = conn.execute(
            "SELECT 1 FROM email_log WHERE run_date=? AND category=? AND lot_id=? AND race_uid=?",
            (today.isoformat(), category, row["lot_id"], row["race_uid"] or ""),
        ).fetchone()
        if existing is None:
            fresh.append(row)
    return fresh


def _log_send(
    conn: sqlite3.Connection,
    today: date,
    entered: list[dict[str, Any]],
    ran: list[dict[str, Any]],
) -> None:
    now = _utcnow()
    for category, rows in (("entered", entered), ("ran_today", ran)):
        for row in rows:
            conn.execute(
                """
                INSERT OR IGNORE INTO email_log
                    (run_date, category, lot_id, race_uid, payload_json, sent_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    today.isoformat(),
                    category,
                    row["lot_id"],
                    row["race_uid"] or "",
                    json.dumps(row, default=_json_default),
                    now,
                ),
            )


def _write_preview(payload: EmailPayload) -> None:
    PREVIEW_HTML.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_HTML.write_text(payload.html, encoding="utf-8")
    PREVIEW_TXT.write_text(payload.text, encoding="utf-8")


def run(
    *,
    run_date: date | None = None,
    dry_run: bool = False,
    no_send: bool = False,
) -> int:
    settings: Settings = load_settings()
    today = run_date or datetime.now(UK).date()

    with session(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO run_log (run_date, started_at, status) VALUES (?, ?, ?)",
            (today.isoformat(), _utcnow(), "running"),
        )
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        log.info("Discovering breeze-up sales for %d", today.year)
        sales = rp_sales.discover_sales(today.year)
        log.info("Sales found: %d", len(sales))
        for s in sales:
            log.info("  %s  (%s %s)", s.sale_name, s.sale_date.isoformat(), s.venue_uid)

        all_lots: list[rp_sales.SaleLot] = []
        for sale in sales:
            lots = rp_sales.fetch_lots(sale)
            log.info("  %s: %d lots (entered=%d)",
                     sale.sale_name, len(lots), sum(1 for lot in lots if lot.entered))
            all_lots.extend(lots)

        uids = {lot.horse_uid for lot in all_lots if lot.horse_uid is not None}
        log.info("Horse uids across all catalogues: %d", len(uids))

        hits: list[rp_results.ResultHit] = []
        if uids:
            hits = rp_results.fetch_hits_for_uids(today, uids)
            log.info("Result hits for today: %d", len(hits))

        entered, ran = _classify(
            today, all_lots, hits,
            entries_window_days=settings.entries_window_days,
        )
        log.info("entries window: today..+%d days", settings.entries_window_days)

        entered = _filter_already_sent(conn, today, "entered", entered)
        ran = _filter_already_sent(conn, today, "ran_today", ran)

        payload = render(
            run_date=today,
            entered=entered,
            ran_today=ran,
            entries_window_days=settings.entries_window_days,
        )
        _write_preview(payload)

        total = len(entered) + len(ran)
        summary = {
            "sales": len(sales),
            "lots": len(all_lots),
            "uids": len(uids),
            "entered_in_window": len(entered),
            "ran_today": len(ran),
        }
        log.info("summary: %s", summary)

        will_send = not (dry_run or no_send)
        if will_send and (total > 0 or settings.notify_on_empty):
            try:
                send(payload, settings)
                _log_send(conn, today, entered, ran)
                status = "ok"
            except Exception as exc:  # noqa: BLE001
                log.exception("email send failed: %s", exc)
                status = "failed"
        else:
            log.info("skipping send (dry_run=%s, no_send=%s, total=%d)",
                     dry_run, no_send, total)
            status = "dry_run" if (dry_run or no_send) else "ok"

        conn.execute(
            "UPDATE run_log SET finished_at=?, status=?, summary_json=? WHERE id=?",
            (_utcnow(), status, json.dumps(summary), run_id),
        )

    return 0 if status in ("ok", "dry_run") else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="breezeup-daily")
    ap.add_argument("--date", type=date.fromisoformat, default=None,
                    help="YYYY-MM-DD (default: today UK)")
    ap.add_argument("--dry-run", action="store_true", help="Render preview but don't send")
    ap.add_argument("--no-send", action="store_true", help="Alias for --dry-run")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return run(run_date=args.date, dry_run=args.dry_run, no_send=args.no_send)


if __name__ == "__main__":
    sys.exit(main())
