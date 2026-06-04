"""Daily job: track a watchlist of barrier-trial horses on Racing Post.

Two modes, one per scheduled run:
  morning  - watchlist horses entered/declared to run in the next few days
  evening  - watchlist horses that ran today (results); always sent, even empty

The watchlist comes from a Google Sheet of horse names + ratings (no Racing Post
uids). Matching is name-first: a horse's RP ``horse_uid`` is learned the first
time it appears on a racecard or result and reused thereafter.

Usage:
  barriertrials-daily --mode morning      # entries email
  barriertrials-daily --mode evening      # results email
  barriertrials-daily --dry-run           # render preview, no send
  barriertrials-daily --demo              # render with synthetic rows, no fetch
  barriertrials-daily --date 2026-04-24   # force a date
  barriertrials-daily --backfill-from 2026-04-01   # seed the season archive
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from barriertrials import sheet as sheet_mod
from barriertrials import stats as stats_mod
from barriertrials.config import Settings
from barriertrials.config import load as load_settings
from barriertrials.db import (
    learn_uid,
    learned_uid_map,
    mark_result_date_scraped,
    scraped_result_dates,
    session,
    upsert_result_row,
    upsert_tracked_horse,
)
from barriertrials.emailer import EmailPayload, render, send
from barriertrials.names import horse_key
from barriertrials.racing import rp_results
from barriertrials.racing.rp_results import ResultHit
from barriertrials.sheet import TrackedHorse
from dailybreezeup.racing import rp_racecards
from dailybreezeup.racing.rp_racecards import RacecardEntry

log = logging.getLogger("barriertrials.daily")
UK = ZoneInfo("Europe/London")
PREVIEW_HTML = Path("data/bt_last_preview.html")
PREVIEW_TXT = Path("data/bt_last_preview.txt")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_default(o: Any) -> Any:
    if isinstance(o, (date, datetime, time)):
        return o.isoformat()
    raise TypeError(f"Unserialisable: {type(o)}")


# ---------- row builders ----------


def _entered_row_from_racecard(horse: TrackedHorse, entry: RacecardEntry) -> dict[str, Any]:
    return {
        "horse_key": horse.name_key,
        "horse_name": entry.horse_name or horse.name,
        "horse_uid": entry.horse_uid,
        "race_uid": entry.race_uid,
        "race_date": entry.race_date,
        "off_time": entry.off_time,
        "course": entry.course,
        "race_name": entry.race_name,
        "race_url": entry.race_url,
        "silk_url": entry.silk_url,
        "ratings": dict(horse.ratings),
        "fields": dict(horse.fields),
    }


def _ran_row(horse: TrackedHorse, hit: ResultHit) -> dict[str, Any]:
    return {
        "horse_key": horse.name_key,
        "horse_name": hit.horse_name or horse.name,
        "horse_uid": hit.horse_uid,
        "race_uid": hit.race_uid,
        "race_date": hit.race_date,
        "off_time": hit.off_time,
        "course": hit.course,
        "race_name": hit.race_name,
        "finishing_position": hit.finishing_position,
        "total_runners": hit.total_runners,
        "sp": hit.sp,
        "rpr": hit.rpr,
        "race_url": hit.race_url,
        "silk_url": hit.silk_url,
        "season_year": hit.race_date.year,
        "ratings": dict(horse.ratings),
        "fields": dict(horse.fields),
    }


# ---------- pure classification (uid-then-name join + uid learning) ----------


def _resolve_key(
    uid: int | None,
    horse_name: str,
    by_name: dict[str, TrackedHorse],
    uid_to_key: dict[int, str],
) -> str | None:
    """Resolve a runner to a watchlist ``name_key``: by learned uid first
    (authoritative), then by normalised name. None when not on the watchlist."""
    if uid is not None and uid in uid_to_key:
        return uid_to_key[uid]
    if horse_name:
        key = horse_key(horse_name)
        if key in by_name:
            return key
    return None


def _learn_event(
    name_key: str,
    uid: int | None,
    learned: dict[str, int],
    learns: list[tuple[str, int]],
    conflicts: list[tuple[str, int, int]],
) -> None:
    """Record a uid sighting for a resolved horse, flagging collisions where the
    same watchlist name already learned a *different* uid."""
    if uid is None:
        return
    existing = learned.get(name_key)
    if existing is None:
        learns.append((name_key, uid))
    elif existing != uid:
        conflicts.append((name_key, existing, uid))


def classify_entries(
    entries: list[RacecardEntry],
    by_name: dict[str, TrackedHorse],
    learned: dict[str, int],
    *,
    today: date,
    window_end: date,
) -> dict[str, Any]:
    """Join racecard entries to the watchlist. Returns rows + uid learn requests
    + collision flags. Rows are deduped on (horse_key, race_uid)."""
    uid_to_key = {uid: key for key, uid in learned.items()}
    rows: list[dict[str, Any]] = []
    learns: list[tuple[str, int]] = []
    conflicts: list[tuple[str, int, int]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if not (today <= entry.race_date <= window_end):
            continue
        key = _resolve_key(entry.horse_uid, entry.horse_name, by_name, uid_to_key)
        if key is None:
            continue
        _learn_event(key, entry.horse_uid, learned, learns, conflicts)
        dedup = (key, entry.race_uid or "")
        if dedup in seen:
            continue
        seen.add(dedup)
        rows.append(_entered_row_from_racecard(by_name[key], entry))
    rows.sort(key=lambda r: (
        r["race_date"], r.get("off_time") or time(0, 0), r.get("course") or "", r["horse_key"]
    ))
    return {"rows": rows, "learns": learns, "conflicts": conflicts}


def classify_results(
    hits: list[ResultHit],
    by_name: dict[str, TrackedHorse],
    learned: dict[str, int],
) -> dict[str, Any]:
    """Join result hits to the watchlist. Returns rows + uid learn requests +
    collision flags. Rows are deduped on (horse_key, race_uid)."""
    uid_to_key = {uid: key for key, uid in learned.items()}
    rows: list[dict[str, Any]] = []
    learns: list[tuple[str, int]] = []
    conflicts: list[tuple[str, int, int]] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = _resolve_key(hit.horse_uid, hit.horse_name, by_name, uid_to_key)
        if key is None:
            continue
        _learn_event(key, hit.horse_uid, learned, learns, conflicts)
        dedup = (key, hit.race_uid or "")
        if dedup in seen:
            continue
        seen.add(dedup)
        rows.append(_ran_row(by_name[key], hit))
    rows.sort(key=lambda r: (
        r.get("off_time") or time(0, 0), r.get("course") or "", r["horse_key"]
    ))
    return {"rows": rows, "learns": learns, "conflicts": conflicts}


def _apply_learns(
    conn: sqlite3.Connection,
    learns: list[tuple[str, int]],
    diagnostics: dict[str, Any],
) -> None:
    """Persist learned uids; tally conflicts the DB rejects (authoritative)."""
    learned_n = conflicts_n = 0
    for name_key, uid in learns:
        action = learn_uid(conn, name_key, uid)
        if action == "learned":
            learned_n += 1
        elif action == "conflict":
            conflicts_n += 1
            log.warning(
                "uid conflict for watchlist horse %r: already learned a different "
                "uid, ignoring %d (likely a name collision)", name_key, uid,
            )
    if learned_n:
        log.info("learned %d new horse uid(s)", learned_n)
    diagnostics["uids_learned"] = diagnostics.get("uids_learned", 0) + learned_n
    if conflicts_n:
        diagnostics["uid_conflicts"] = diagnostics.get("uid_conflicts", 0) + conflicts_n


# ---------- email log dedup ----------


def _filter_already_sent(
    conn: sqlite3.Connection,
    today: date,
    category: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fresh: list[dict[str, Any]] = []
    for row in rows:
        existing = conn.execute(
            "SELECT 1 FROM email_log "
            "WHERE run_date=? AND category=? AND horse_key=? AND race_uid=?",
            (today.isoformat(), category, row["horse_key"], row["race_uid"] or ""),
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
                    (run_date, category, horse_key, race_uid, payload_json, sent_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    today.isoformat(),
                    category,
                    row["horse_key"],
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
    now = now or datetime.now(UK)
    return "morning" if now.hour < 14 else "evening"


# ---------- demo fixtures (layout verification, no network) ----------


def _demo_watchlist(settings: Settings) -> list[TrackedHorse]:
    cols = settings.rating_column_list or ["Rating"]
    samples = [
        ("Golden Narrative (IRE)", [88.0, 86.5],
         {"Batch": "1", "Trainer": "D. Dias", "Notes": "Batch 1 winner"}),
        ("King's Fury (GB)", [85.0, 83.2],
         {"Batch": "1", "Trainer": "J.P. O'Brien", "Notes": ""}),
        ("Cashel Queen (IRE)", [46.0, 43.0],
         {"Batch": "4", "Trainer": "D. O'Brien", "Notes": "Slowest winner"}),
    ]
    horses: list[TrackedHorse] = []
    for name, values, extra in samples:
        ratings = {col: (values[i] if i < len(values) else None) for i, col in enumerate(cols)}
        tiles = {col: f"{ratings[col]:.1f}" for col in cols if ratings[col] is not None}
        fields = {**extra, **tiles}
        horses.append(
            TrackedHorse(name=name, name_key=horse_key(name), fields=fields, ratings=ratings)
        )
    return horses


def _demo_rows(settings: Settings, *, ran: bool) -> list[dict[str, Any]]:
    horses = _demo_watchlist(settings)
    rows: list[dict[str, Any]] = []
    for i, h in enumerate(horses):
        base = {
            "horse_key": h.name_key,
            "horse_name": h.name,
            "horse_uid": 1000 + i,
            "race_uid": str(900000 + i),
            "race_date": date.today() + (timedelta(days=0) if ran else timedelta(days=i)),
            "off_time": time(14 + i, 30),
            "course": ["Newmarket", "Ascot", "York"][i % 3],
            "race_name": "Demo Maiden Stakes",
            "race_url": "https://www.racingpost.com/",
            "silk_url": None,
            "ratings": dict(h.ratings),
            "fields": dict(h.fields),
        }
        if ran:
            base.update({
                "finishing_position": ["1", "3", "6"][i % 3],
                "total_runners": 8,
                "sp": ["11/4", "9/2", "16/1"][i % 3],
                "rpr": [88, 74, None][i % 3],
                "season_year": base["race_date"].year,
            })
        rows.append(base)
    return rows


# ---------- main run ----------


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

        diagnostics: dict[str, Any] = {"run_kind": "demo" if demo else "live", "mode": mode}
        entered: list[dict[str, Any]] = []
        ran: list[dict[str, Any]] = []
        by_name: dict[str, TrackedHorse] = {}
        sheet_status = ""

        if demo:
            log.warning("DEMO MODE: synthetic rows, no live fetch")
            by_name = sheet_mod.index_by_name(_demo_watchlist(settings))
            if mode == "morning":
                entered = _demo_rows(settings, ran=False)
            else:
                ran = _demo_rows(settings, ran=True)
            sheet_status = f"{len(by_name)} demo horses"
        else:
            # Load the watchlist from the sheet and refresh the tracked_horses table.
            try:
                horses = sheet_mod.fetch_sheet(
                    settings.sheet_csv_url,
                    name_column=settings.horse_name_column,
                    rating_columns=settings.rating_column_list,
                )
                by_name = sheet_mod.index_by_name(horses)
                for h in horses:
                    upsert_tracked_horse(
                        conn,
                        name_key=h.name_key,
                        display_name=h.name,
                        ratings_json=json.dumps(h.ratings),
                    )
                log.info("Watchlist horses: %d", len(by_name))
                sheet_status = f"{len(by_name)} horses loaded"
            except Exception as exc:  # noqa: BLE001
                log.warning("Watchlist fetch failed (%s): nothing to track", exc)
                sheet_status = f"fetch failed ({exc.__class__.__name__})"

            learned = learned_uid_map(conn)
            target_uids = set(learned.values())
            target_names = {key: None for key in by_name}
            diagnostics["watchlist"] = len(by_name)
            diagnostics["uids_known"] = len(target_uids)

            if by_name:
                if mode == "evening":
                    hits = rp_results.fetch_hits_for_uids(
                        today, target_uids, target_names=target_names
                    )
                    log.info("Result hits for today: %d", len(hits))
                    res = classify_results(hits, by_name, learned)
                    ran = res["rows"]
                    _apply_learns(conn, res["learns"], diagnostics)
                else:
                    window_end = today + timedelta(days=settings.entries_window_days)
                    entries: list[RacecardEntry] = []
                    for offset in range(settings.entries_window_days + 1):
                        on = today + timedelta(days=offset)
                        day_entries, _ = rp_racecards.fetch_entries_for_uids(
                            on, target_uids, target_names=target_names
                        )
                        log.info("Racecard hits for %s: %d", on, len(day_entries))
                        entries.extend(day_entries)
                    res = classify_entries(
                        entries, by_name, learned, today=today, window_end=window_end
                    )
                    entered = res["rows"]
                    _apply_learns(conn, res["learns"], diagnostics)

        diagnostics["sheet_status"] = sheet_status
        diagnostics["entered_pre_dedup"] = len(entered)
        diagnostics["ran_today_pre_dedup"] = len(ran)

        if not demo:
            entered = _filter_already_sent(conn, today, "entered", entered)
            ran = _filter_already_sent(conn, today, "ran_today", ran)

        # Persist today's results, then self-heal the season archive so the
        # summary covers horses that ran before tracking began (or before a CI
        # cache eviction). Idempotent on (horse_key, race_uid). Demo skips it.
        if mode == "evening" and not demo:
            for row in ran:
                upsert_result_row(conn, row)
            try:
                learned_now = learned_uid_map(conn)
                fill = _ensure_season_archive(
                    conn,
                    season_start=settings.season_start_date,
                    today=today,
                    by_name=by_name,
                    learned=learned_now,
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
            season_summary = _load_season_summary(conn, today.year, settings.rating_column_list)
            if season_summary:
                diagnostics["season_runs"] = season_summary["total_runs"]

        payload = render(
            run_date=today,
            entered=entered,
            ran_today=ran,
            entries_window_days=settings.entries_window_days,
            diagnostics=diagnostics,
            mode=mode,
            season_summary=season_summary,
        )
        _write_preview(payload)

        total = len(entered) + len(ran)
        summary = {
            "demo": demo,
            "mode": mode,
            "watchlist": len(by_name),
            "entered": len(entered),
            "ran_today": len(ran),
        }
        log.info("summary: %s", summary)

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
            log.info("skipping send (dry_run=%s, no_send=%s, total=%d)", dry_run, no_send, total)
            status = "dry_run" if (dry_run or no_send) else "ok"

        conn.execute(
            "UPDATE run_log SET finished_at=?, status=?, summary_json=? WHERE id=?",
            (_utcnow(), status, json.dumps(summary), run_id),
        )

    return 0 if status in ("ok", "dry_run") else 1


def _load_season_summary(
    conn: sqlite3.Connection, year: int, rating_columns: list[str]
) -> dict[str, Any] | None:
    """Read the season's archive rows and merge each row's ratings_json blob so
    stats can bucket by the (user-defined) rating column headers."""
    rows: list[dict[str, Any]] = []
    for r in conn.execute(
        "SELECT * FROM results_archive WHERE season_year = ?", (year,)
    ).fetchall():
        d = dict(r)
        try:
            d.update(json.loads(d.get("ratings_json") or "{}"))
        except (TypeError, ValueError):
            pass
        rows.append(d)
    return stats_mod.build_summary(rows, rating_columns)


# ---------- season archive backfill ----------


def _scrape_day_into_archive(
    conn: sqlite3.Connection,
    day: date,
    by_name: dict[str, TrackedHorse],
    learned: dict[str, int],
) -> int:
    """Scrape one day's RP results for the watchlist and upsert matches into
    ``results_archive``. Returns the number of outcomes written."""
    if not by_name:
        return 0
    target_uids = set(learned.values())
    target_names = {key: None for key in by_name}
    try:
        hits = rp_results.fetch_hits_for_uids(day, target_uids, target_names=target_names)
    except Exception as exc:  # noqa: BLE001
        log.warning("results fetch failed for %s: %s", day, exc)
        hits = []
    res = classify_results(hits, by_name, learned)
    for name_key, uid in res["learns"]:
        learn_uid(conn, name_key, uid)
        learned.setdefault(name_key, uid)
    n = 0
    for row in res["rows"]:
        if upsert_result_row(conn, row):
            n += 1
    return n


def _ensure_season_archive(
    conn: sqlite3.Connection,
    *,
    season_start: date,
    today: date,
    by_name: dict[str, TrackedHorse],
    learned: dict[str, int],
) -> dict[str, int]:
    """Walk every result date in ``[season_start, today)`` not yet recorded in
    ``results_scrape_log`` and write matching outcomes to ``results_archive``.

    Today is covered by the live evening fetch upstream, so it's marked scraped
    here without re-walking."""
    if season_start > today:
        return {"days_scraped": 0, "rows_added": 0}
    already = scraped_result_dates(conn)
    days_scraped = rows_added = 0
    day = season_start
    while day < today:
        iso = day.isoformat()
        if iso not in already:
            rows_added += _scrape_day_into_archive(conn, day, by_name, learned)
            mark_result_date_scraped(conn, iso)
            days_scraped += 1
        day += timedelta(days=1)
    mark_result_date_scraped(conn, today.isoformat())
    return {"days_scraped": days_scraped, "rows_added": rows_added}


def backfill_results(*, from_date: date, to_date: date | None = None) -> int:
    """Scrape RP results for every date in ``[from_date, to_date]`` and write
    matching watchlist outcomes to ``results_archive``. Doesn't send email.

    Use to seed the season-to-date table on a fresh DB (e.g. after a CI cache
    eviction). Re-running is safe — the upsert is idempotent on (horse_key, race_uid).
    """
    settings: Settings = load_settings()
    to_date = to_date or datetime.now(UK).date()
    if from_date > to_date:
        raise ValueError(f"--backfill-from {from_date} is after to-date {to_date}")
    log.info("Historical backfill: %s .. %s", from_date, to_date)

    with session(settings.db_path) as conn:
        horses = sheet_mod.fetch_sheet(
            settings.sheet_csv_url,
            name_column=settings.horse_name_column,
            rating_columns=settings.rating_column_list,
        )
        by_name = sheet_mod.index_by_name(horses)
        for h in horses:
            upsert_tracked_horse(
                conn, name_key=h.name_key, display_name=h.name,
                ratings_json=json.dumps(h.ratings),
            )
        log.info("Watchlist horses: %d", len(by_name))
        if not by_name:
            log.warning("Empty watchlist — nothing to backfill")
            return 0

        learned = learned_uid_map(conn)
        total_hits = 0
        day = from_date
        while day <= to_date:
            n = _scrape_day_into_archive(conn, day, by_name, learned)
            log.info("%s: %d result hit(s)", day, n)
            mark_result_date_scraped(conn, day.isoformat())
            total_hits += n
            day += timedelta(days=1)
        log.info("Backfill complete: %d outcome(s) written to results_archive", total_hits)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="barriertrials-daily")
    ap.add_argument("--date", type=date.fromisoformat, default=None,
                    help="YYYY-MM-DD (default: today UK)")
    ap.add_argument("--dry-run", action="store_true", help="Render preview but don't send")
    ap.add_argument("--no-send", action="store_true", help="Alias for --dry-run")
    ap.add_argument("--demo", action="store_true",
                    help="Skip live fetch; render synthetic rows for layout checks")
    ap.add_argument("--mode", choices=("morning", "evening"), default=None,
                    help="morning = entries/declarations; evening = results "
                         "(default: morning before 14:00 UK, evening after)")
    ap.add_argument("--backfill-from", type=date.fromisoformat, default=None,
                    metavar="YYYY-MM-DD",
                    help="One-shot historical scrape from this date through today "
                         "into results_archive. Doesn't send email.")
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
