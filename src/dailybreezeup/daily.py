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
from dailybreezeup import sheet as sheet_mod

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
        "sale_short": sheet_mod.sale_short_name(lot.sale.sale_name),
        "sale_year": lot.sale.sale_date.year,
        "lot": lot.display_lot,
        "lot_no": lot.lot_no,
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


def _enrich_with_sheet(
    rows: list[dict[str, Any]],
    sheet_index: dict[tuple[int, str, int], sheet_mod.SheetRow],
    sale_totals: dict[tuple[int, str], int] | None = None,
) -> tuple[int, int]:
    """Mutate rows in place, attaching sheet enrichment fields where the
    ``(year, sale_short, lot_no)`` key matches. Returns ``(matched, missing)``
    for logging."""
    sale_totals = sale_totals or {}
    matched = missing = 0
    for row in rows:
        short = row.get("sale_short")
        if not short:
            continue
        key = (row["sale_year"], short, row["lot_no"])
        sheet_row = sheet_index.get(key)
        if sheet_row is None:
            row["sheet_matched"] = False
            missing += 1
            continue
        row["sheet_matched"] = True
        sale_total = sale_totals.get((row["sale_year"], short))
        row.update(sheet_mod.enrichment_fields(sheet_row, sale_total=sale_total))
        matched += 1
    return matched, missing


def _resort_by_rating(rows: list[dict[str, Any]]) -> None:
    """Within each race day + course, surface the highest Breeze Rating first
    so the most interesting horses lead the section."""
    rows.sort(
        key=lambda r: (
            r.get("race_date"),
            r.get("course") or "",
            -(r.get("sheet_breeze_rating") or 0.0),
            r["lot"],
        )
    )


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
    demo: bool = False,
) -> int:
    settings: Settings = load_settings()
    today = run_date or datetime.now(UK).date()

    with session(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO run_log (run_date, started_at, status) VALUES (?, ?, ?)",
            (today.isoformat(), _utcnow(), "running"),
        )
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        all_lots: list[rp_sales.SaleLot]
        hits: list[rp_results.ResultHit] = []
        diagnostics: dict[str, Any] = {"mode": "demo" if demo else "live"}
        if demo:
            log.warning("DEMO MODE: using static fixture lots, no live RP fetch")
            all_lots = rp_sales.demo_lots()
            log.info("Demo lots: %d (entered=%d)",
                     len(all_lots), sum(1 for lot in all_lots if lot.entered))
        else:
            log.info("Discovering breeze-up sales for %d", today.year)
            sales = rp_sales.discover_sales(today.year)
            log.info("Sales found: %d", len(sales))
            for s in sales:
                log.info("  %s  (%s %s)", s.sale_name, s.sale_date.isoformat(), s.venue_uid)
            diagnostics["sales_found"] = len(sales)

            all_lots = []
            for sale in sales:
                lots = rp_sales.fetch_lots(sale)
                log.info("  %s: %d lots (entered=%d)",
                         sale.sale_name, len(lots), sum(1 for lot in lots if lot.entered))
                all_lots.extend(lots)
            diagnostics["lots_total"] = len(all_lots)
            diagnostics["lots_entered_any_date"] = sum(1 for lot in all_lots if lot.entered)

            uids = {lot.horse_uid for lot in all_lots if lot.horse_uid is not None}
            log.info("Horse uids across all catalogues: %d", len(uids))
            if uids:
                hits = rp_results.fetch_hits_for_uids(today, uids)
                log.info("Result hits for today: %d", len(hits))
            diagnostics["result_hits"] = len(hits)

        entries_window_days = settings.entries_window_days
        if demo:
            # Demo lots have static future race dates that may sit far outside
            # the production window. Force the window wide so --demo always
            # renders a populated body for layout verification.
            entries_window_days = 9999

        entered, ran = _classify(
            today, all_lots, hits,
            entries_window_days=entries_window_days,
        )
        log.info("entries window: today..+%d days", entries_window_days)

        sheet_status: str
        try:
            sheet_rows = sheet_mod.fetch_sheet(settings.sheet_csv_url)
            sheet_index = sheet_mod.index_by_key(sheet_rows)
            sale_totals = sheet_mod.count_by_sale(sheet_rows)
            log.info("Sheet rows loaded: %d", len(sheet_rows))
            sheet_status = f"{len(sheet_rows)} rows loaded"
        except Exception as exc:  # noqa: BLE001
            log.warning("Sheet fetch failed (%s): proceeding without enrichment", exc)
            sheet_index = {}
            sale_totals = {}
            sheet_status = f"fetch failed ({exc.__class__.__name__})"

        if sheet_index:
            em, mm = _enrich_with_sheet(entered, sheet_index, sale_totals)
            log.info("Sheet enrichment (entered): matched=%d, missing=%d", em, mm)
            rm, mr = _enrich_with_sheet(ran, sheet_index, sale_totals)
            log.info("Sheet enrichment (ran_today): matched=%d, missing=%d", rm, mr)
            sheet_status = (
                f"{len(sheet_rows)} rows loaded; "
                f"entered matched={em}/missing={mm}, "
                f"ran_today matched={rm}/missing={mr}"
            )
            _resort_by_rating(entered)
        diagnostics["sheet_status"] = sheet_status

        diagnostics["entered_in_window_pre_dedup"] = len(entered)
        diagnostics["ran_today_pre_dedup"] = len(ran)
        if demo:
            log.info("DEMO: skipping email_log dedup so the body always renders")
        else:
            pre_entered, pre_ran = len(entered), len(ran)
            entered = _filter_already_sent(conn, today, "entered", entered)
            ran = _filter_already_sent(conn, today, "ran_today", ran)
            if pre_entered != len(entered) or pre_ran != len(ran):
                dropped_entered = pre_entered - len(entered)
                dropped_ran = pre_ran - len(ran)
                log.info(
                    "dedup filtered %d entered and %d ran_today rows already sent today",
                    dropped_entered, dropped_ran,
                )
                diagnostics["dedup_dropped_entered"] = dropped_entered
                diagnostics["dedup_dropped_ran_today"] = dropped_ran
        diagnostics["entries_window_days"] = entries_window_days

        payload = render(
            run_date=today,
            entered=entered,
            ran_today=ran,
            entries_window_days=entries_window_days,
            diagnostics=diagnostics,
        )
        _write_preview(payload)

        total = len(entered) + len(ran)
        summary = {
            "demo": demo,
            "lots": len(all_lots),
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
    ap.add_argument("--demo", action="store_true",
                    help="Skip live RP fetch; render with the four real Craven 2026 entered lots")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return run(
        run_date=args.date, dry_run=args.dry_run, no_send=args.no_send, demo=args.demo,
    )


if __name__ == "__main__":
    sys.exit(main())
