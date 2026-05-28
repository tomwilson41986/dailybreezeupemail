"""Daily job: pull every current breeze-up catalogue from Racing Post.

Two modes, one per scheduled run:
  morning  - lots entered to run in the next 3 days (entries + declarations)
  evening  - lots that ran today (results); always sent, even when empty

Usage:
  breezeup-daily --mode morning       # today UK, send entries email
  breezeup-daily --mode evening       # today UK, send results email
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
from dailybreezeup.db import (
    mark_result_date_scraped,
    scraped_result_dates,
    session,
    upsert_result_row,
)
from dailybreezeup.emailer import EmailPayload, render, send
from dailybreezeup.racing import rp_racecards, rp_results, rp_sales
from dailybreezeup import sheet as sheet_mod
from dailybreezeup import stats as stats_mod

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


def _entered_row(
    lot: rp_sales.SaleLot,
    *,
    race_off_times: dict[str, time] | None = None,
) -> dict[str, Any]:
    entry = lot.entry
    assert entry is not None
    race_uid = str(entry.race_uid)
    base = _lot_row(lot, race_uid=race_uid)
    # The catalogue's entry_details does not carry an off-time, so backfill
    # from the racecard off-times we collected for the entries window. This
    # lets the morning email always show race time when known, even for
    # lots whose uid wasn't matched on a racecard (unnamed lots, RP lag).
    off_time = (race_off_times or {}).get(race_uid)
    base.update({
        "course": entry.course_name.title(),
        "race_date": entry.race_date,
        "off_time": off_time,
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
        "total_runners": hit.total_runners,
        "sp": hit.sp,
        "rpr": hit.rpr,
        "race_url": hit.race_url,
        "horse_name": hit.horse_name or lot.horse_name,
        "silk_url": hit.silk_url,
    })
    return base


def _entered_row_from_racecard(
    lot: rp_sales.SaleLot, entry: rp_racecards.RacecardEntry
) -> dict[str, Any]:
    base = _lot_row(lot, race_uid=entry.race_uid)
    base.update({
        "course": entry.course,
        "race_date": entry.race_date,
        "off_time": entry.off_time,
        "race_name": entry.race_name,
        "race_url": entry.race_url,
        "horse_name": entry.horse_name or lot.horse_name,
        "silk_url": entry.silk_url,
    })
    return base


def _classify(
    today: date,
    lots: list[rp_sales.SaleLot],
    results: list[rp_results.ResultHit],
    racecard_entries: list[rp_racecards.RacecardEntry] | None = None,
    *,
    entries_window_days: int,
    race_off_times: dict[str, time] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    window_end = today + timedelta(days=entries_window_days)
    by_uid: dict[int, rp_sales.SaleLot] = {
        lot.horse_uid: lot for lot in lots if lot.horse_uid is not None
    }

    entered: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _push(row: dict[str, Any]) -> None:
        key = (row["lot_id"], row.get("race_uid") or "")
        if key in seen:
            return
        seen.add(key)
        entered.append(row)

    # Racecard-side join first — it carries silk URLs and live race metadata
    # (off_time, race_name) that the catalogue's entry_details omits, and
    # also covers lots whose entry_details points at a different (often
    # later) race or is missing. Catalogue-derived rows below act as a
    # fallback for lots not seen via racecards.
    for rc in racecard_entries or []:
        if not (today <= rc.race_date <= window_end):
            continue
        lot = by_uid.get(rc.horse_uid)
        if lot is None:
            continue
        _push(_entered_row_from_racecard(lot, rc))

    for lot in lots:
        if not (lot.entered and lot.entry):
            continue
        if not (today <= lot.entry.race_date <= window_end):
            continue
        _push(_entered_row(lot, race_off_times=race_off_times))

    ran: list[dict[str, Any]] = []
    for hit in results:
        lot = by_uid.get(hit.horse_uid)
        if lot is None:
            continue
        ran.append(_ran_row(lot, hit))

    entered.sort(key=lambda r: (
        r["race_date"], r.get("off_time") or time(0, 0), r.get("course") or "", r["lot"]
    ))
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


def _resort_entered(rows: list[dict[str, Any]]) -> None:
    """Order the morning entries by race time, earliest to latest within each
    day. Breeze Rating only breaks ties between horses in the same race, so the
    most interesting runner leads its race without disturbing the time order."""
    rows.sort(
        key=lambda r: (
            r.get("race_date"),
            r.get("off_time") or time(0, 0),
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


def _default_mode(now: datetime | None = None) -> str:
    """Pick morning vs evening based on UK local hour when --mode isn't given.

    The schedulers (Task Scheduler, GitHub Actions) pass --mode explicitly, so
    this is only a sensible fallback for ad-hoc CLI runs."""
    now = now or datetime.now(UK)
    return "morning" if now.hour < 14 else "evening"


def run(
    *,
    run_date: date | None = None,
    dry_run: bool = False,
    no_send: bool = False,
    demo: bool = False,
    mode: str | None = None,
) -> int:
    settings: Settings = load_settings()
    today = run_date or datetime.now(UK).date()
    mode = mode or _default_mode()
    if mode not in ("morning", "evening"):
        raise ValueError(f"mode must be 'morning' or 'evening', got {mode!r}")

    with session(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO run_log (run_date, started_at, status) VALUES (?, ?, ?)",
            (today.isoformat(), _utcnow(), "running"),
        )
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        all_lots: list[rp_sales.SaleLot]
        hits: list[rp_results.ResultHit] = []
        racecard_entries: list[rp_racecards.RacecardEntry] = []
        race_off_times: dict[str, time] = {}
        diagnostics: dict[str, Any] = {
            "run_kind": "demo" if demo else "live",
            "mode": mode,
        }
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

            if mode == "evening":
                uids = {lot.horse_uid for lot in all_lots if lot.horse_uid is not None}
                log.info("Horse uids across all catalogues: %d", len(uids))
                if uids:
                    hits = rp_results.fetch_hits_for_uids(today, uids)
                    log.info("Result hits for today: %d", len(hits))
                diagnostics["result_hits"] = len(hits)
            else:
                log.info("morning mode: skipping results fetch")
                uids = {lot.horse_uid for lot in all_lots if lot.horse_uid is not None}
                log.info("Horse uids across all catalogues: %d", len(uids))
                if uids:
                    for offset in range(settings.entries_window_days + 1):
                        on = today + timedelta(days=offset)
                        day_entries, day_off_times = (
                            rp_racecards.fetch_entries_for_uids(on, uids)
                        )
                        log.info("Racecard hits for %s: %d", on, len(day_entries))
                        racecard_entries.extend(day_entries)
                        race_off_times.update(day_off_times)
                diagnostics["racecard_hits"] = len(racecard_entries)

        entries_window_days = settings.entries_window_days
        if demo:
            # Demo lots have static future race dates that may sit far outside
            # the production window. Force the window wide so --demo always
            # renders a populated body for layout verification.
            entries_window_days = 9999

        entered, ran = _classify(
            today, all_lots, hits, racecard_entries,
            entries_window_days=entries_window_days,
            race_off_times=race_off_times,
        )
        log.info("entries window: today..+%d days", entries_window_days)

        # The two emails own disjoint sections: the morning email is for
        # entries/declarations only, the evening email is for results only.
        if mode == "morning":
            ran = []
        elif mode == "evening":
            entered = []

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
            _resort_entered(entered)
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

        # Persist today's result hits before we render so the season-to-date
        # summary at the bottom of the evening email includes them. The
        # archive upsert is idempotent on (lot_id, race_uid) so re-runs are
        # safe — and demo mode skips it to keep the demo DB clean.
        if mode == "evening" and not demo:
            for row in ran:
                upsert_result_row(conn, row)
            # Self-heal the archive back to the season start so graduates that
            # ran before the results feature launched still show in the summary.
            # Tracked per-day, so this only scrapes historical dates once (and
            # re-fills after a cache eviction). Never let it block the email.
            by_uid = {
                lot.horse_uid: lot for lot in all_lots if lot.horse_uid is not None
            }
            try:
                fill = _ensure_season_archive(
                    conn,
                    season_start=settings.season_start_date,
                    today=today,
                    by_uid=by_uid,
                    sheet_index=sheet_index,
                    sale_totals=sale_totals,
                )
                if fill["days_scraped"]:
                    log.info(
                        "season backfill: scraped %d historical day(s), +%d archive row(s)",
                        fill["days_scraped"], fill["rows_added"],
                    )
                diagnostics["season_backfill_days"] = fill["days_scraped"]
                diagnostics["season_backfill_rows"] = fill["rows_added"]
            except Exception as exc:  # noqa: BLE001
                log.warning("season backfill failed (%s): summary may be incomplete", exc)

        season_summary = None
        if mode == "evening":
            archive_rows = conn.execute(
                "SELECT * FROM results_archive WHERE sale_year = ?", (today.year,)
            ).fetchall()
            season_summary = stats_mod.build_summary(archive_rows)
            if season_summary:
                diagnostics["season_runs"] = season_summary["total_runs"]

        payload = render(
            run_date=today,
            entered=entered,
            ran_today=ran,
            entries_window_days=entries_window_days,
            diagnostics=diagnostics,
            mode=mode,
            season_summary=season_summary,
        )
        _write_preview(payload)

        total = len(entered) + len(ran)
        summary = {
            "demo": demo,
            "mode": mode,
            "lots": len(all_lots),
            "entered_in_window": len(entered),
            "ran_today": len(ran),
        }
        log.info("summary: %s", summary)

        # Evening always sends — even an empty results day still gets a
        # "No Results Today" notice. Morning falls back to notify_on_empty.
        send_when_empty = mode == "evening" or settings.notify_on_empty
        will_send = not (dry_run or no_send)
        if will_send and (total > 0 or send_when_empty):
            try:
                send(payload, settings, silk_rows=entered + ran)
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


def _scrape_day_into_archive(
    conn: sqlite3.Connection,
    day: date,
    by_uid: dict[int, rp_sales.SaleLot],
    sheet_index: dict[tuple[int, str, int], sheet_mod.SheetRow],
    sale_totals: dict[tuple[int, str], int],
) -> int:
    """Scrape one day's RP results for our uid set and upsert matches into
    ``results_archive``. Returns the number of outcomes written."""
    uids = set(by_uid.keys())
    if not uids:
        return 0
    try:
        hits = rp_results.fetch_hits_for_uids(day, uids)
    except Exception as exc:  # noqa: BLE001
        log.warning("results fetch failed for %s: %s", day, exc)
        hits = []
    n = 0
    for hit in hits:
        lot = by_uid.get(hit.horse_uid)
        if lot is None:
            continue
        row = _ran_row(lot, hit)
        if sheet_index:
            _enrich_with_sheet([row], sheet_index, sale_totals)
        upsert_result_row(conn, row)
        n += 1
    return n


def _ensure_season_archive(
    conn: sqlite3.Connection,
    *,
    season_start: date,
    today: date,
    by_uid: dict[int, rp_sales.SaleLot],
    sheet_index: dict[tuple[int, str, int], sheet_mod.SheetRow],
    sale_totals: dict[tuple[int, str], int],
) -> dict[str, int]:
    """Walk every result date in ``[season_start, today)`` not yet recorded in
    ``results_scrape_log`` and write matching outcomes to ``results_archive``.

    This is what makes the season-to-date summary cover graduates that ran
    before the results feature launched: on the first evening run (or the first
    after a CI cache eviction wipes the DB) it self-heals the whole season,
    then tracks each day so subsequent runs only ever scrape today. ``today``
    itself is covered by the live evening results fetch upstream, so it's marked
    scraped here without re-walking it."""
    if season_start > today:
        return {"days_scraped": 0, "rows_added": 0}
    already = scraped_result_dates(conn)
    days_scraped = rows_added = 0
    day = season_start
    while day < today:
        iso = day.isoformat()
        if iso not in already:
            rows_added += _scrape_day_into_archive(
                conn, day, by_uid, sheet_index, sale_totals
            )
            mark_result_date_scraped(conn, iso)
            days_scraped += 1
        day += timedelta(days=1)
    mark_result_date_scraped(conn, today.isoformat())
    return {"days_scraped": days_scraped, "rows_added": rows_added}


def backfill_results(*, from_date: date, to_date: date | None = None) -> int:
    """Scrape RP results for every date in ``[from_date, to_date]`` and write
    matching breeze-up graduate outcomes to ``results_archive``.

    Doesn't send email or touch ``email_log``. The cron's evening run handles
    the live email; this command exists to recover historical data after the
    SQLite DB has been wiped (e.g. ephemeral CI runners with no cache).
    Re-running is safe — the archive upsert is idempotent on (lot_id, race_uid).
    """
    settings: Settings = load_settings()
    to_date = to_date or datetime.now(UK).date()
    if from_date > to_date:
        raise ValueError(f"--backfill-from {from_date} is after to-date {to_date}")
    log.info("Historical backfill: %s .. %s", from_date, to_date)

    with session(settings.db_path) as conn:
        log.info("Discovering breeze-up sales for %d", to_date.year)
        sales = rp_sales.discover_sales(to_date.year)
        log.info("Sales found: %d", len(sales))
        all_lots: list[rp_sales.SaleLot] = []
        for sale in sales:
            lots = rp_sales.fetch_lots(sale)
            log.info("  %s: %d lots", sale.sale_name, len(lots))
            all_lots.extend(lots)
        by_uid: dict[int, rp_sales.SaleLot] = {
            lot.horse_uid: lot for lot in all_lots if lot.horse_uid is not None
        }
        uids = set(by_uid.keys())
        log.info("Horse uids in scope: %d", len(uids))
        if not uids:
            log.warning("No uids — nothing to backfill")
            return 0

        sheet_index: dict[tuple[int, str, int], sheet_mod.SheetRow] = {}
        sale_totals: dict[tuple[int, str], int] = {}
        try:
            sheet_rows = sheet_mod.fetch_sheet(settings.sheet_csv_url)
            sheet_index = sheet_mod.index_by_key(sheet_rows)
            sale_totals = sheet_mod.count_by_sale(sheet_rows)
            log.info("Sheet rows loaded: %d", len(sheet_rows))
        except Exception as exc:  # noqa: BLE001
            log.warning("Sheet fetch failed (%s): proceeding without enrichment", exc)

        total_hits = 0
        day = from_date
        while day <= to_date:
            n = _scrape_day_into_archive(conn, day, by_uid, sheet_index, sale_totals)
            log.info("%s: %d result hit(s)", day, n)
            mark_result_date_scraped(conn, day.isoformat())
            total_hits += n
            day += timedelta(days=1)
        log.info("Backfill complete: %d outcome(s) written to results_archive", total_hits)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="breezeup-daily")
    ap.add_argument("--date", type=date.fromisoformat, default=None,
                    help="YYYY-MM-DD (default: today UK)")
    ap.add_argument("--dry-run", action="store_true", help="Render preview but don't send")
    ap.add_argument("--no-send", action="store_true", help="Alias for --dry-run")
    ap.add_argument("--demo", action="store_true",
                    help="Skip live RP fetch; render with the four real Craven 2026 entered lots")
    ap.add_argument("--mode", choices=("morning", "evening"), default=None,
                    help="morning = entries/declarations only; evening = results only "
                         "(default: morning before 14:00 UK, evening after)")
    ap.add_argument("--backfill-from", type=date.fromisoformat, default=None,
                    metavar="YYYY-MM-DD",
                    help="One-shot historical scrape: walk RP results from this date "
                         "through today and write matching outcomes to results_archive. "
                         "Doesn't send email. Use to seed the season-to-date table on "
                         "a fresh DB (e.g. after a CI cache eviction).")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.backfill_from is not None:
        return backfill_results(from_date=args.backfill_from, to_date=args.date)
    return run(
        run_date=args.date, dry_run=args.dry_run, no_send=args.no_send, demo=args.demo,
        mode=args.mode,
    )


if __name__ == "__main__":
    sys.exit(main())
