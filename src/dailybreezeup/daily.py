"""Daily job: gather races, match breeze-up graduates, send email.

Usage:
  python -m dailybreezeup.daily                      # today UK, send
  python -m dailybreezeup.daily --dry-run            # render only, no send
  python -m dailybreezeup.daily --date 2026-04-24    # force a date
  python -m dailybreezeup.daily --no-send            # skip send (same as --dry-run but still logs)
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dailybreezeup.config import Settings, load as load_settings
from dailybreezeup.db import session
from dailybreezeup.emailer import EmailPayload, render, send
from dailybreezeup.matching import MatchedHorse, RunnerToMatch, horse_key, match, normalize_name
from dailybreezeup.models import RaceCard, RaceResult, Runner
from dailybreezeup.racing import gather

log = logging.getLogger("dailybreezeup.daily")
UK = ZoneInfo("Europe/London")
PREVIEW_HTML = Path("data/last_preview.html")
PREVIEW_TXT = Path("data/last_preview.txt")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_payload(card: RaceCard | RaceResult, runner: Runner, matched: MatchedHorse) -> dict[str, Any]:
    return {
        "horse": runner.horse,
        "bred": runner.bred,
        "sale_id": matched.sale_id,
        "sale_name": matched.sale_name,
        "vendor": matched.vendor,
        "lot": matched.lot,
        "year_foaled": matched.year_foaled,
        "race_id": card.race_id,
        "breeze_rating": matched.breeze_rating,
        "precocity_rating": matched.precocity_rating,
        "ot_rank": matched.ot_rank,
        "ot_diff_m": matched.ot_diff_m,
        "sl_1f": matched.sl_1f,
        "sl_go": matched.sl_go,
        "sheet_row_url": matched.sheet_row_url,
        "price": matched.price,
        "currency": matched.currency,
        "withdrawn": matched.withdrawn,
        "course": card.course,
        "race_name": card.race_name,
        "race_date": card.race_date,
        "off_time": card.off_time,
        "trainer": runner.trainer,
        "jockey": runner.jockey,
        "draw": runner.draw,
        "finishing_position": runner.finishing_position,
        "sp": runner.sp,
        "race_url": card.url,
    }


def _json_default(o: Any) -> Any:
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(f"Unserialisable: {type(o)}")


def _classify(
    conn: sqlite3.Connection,
    today: date,
    gathered,
) -> tuple[list[dict], list[dict], list[dict]]:
    ran: list[dict] = []
    declared: list[dict] = []
    entered: list[dict] = []

    seen: set[tuple[str, str, str]] = set()  # (category, horse_key, race_id)

    def _match_card(card: RaceCard | RaceResult, bucket: list[dict], category: str) -> None:
        for runner in card.runners:
            to_match = RunnerToMatch(
                name=runner.horse,
                age=runner.age,
                race_year=card.race_date.year,
                sire=runner.sire,
                dam=runner.dam,
            )
            matched = match(conn, to_match)
            if not matched:
                continue
            key = horse_key(normalize_name(runner.horse), matched.year_foaled)
            k = (category, key, card.race_id)
            if k in seen:
                continue
            seen.add(k)
            bucket.append(_row_payload(card, runner, matched))

    for card in gathered.results:
        _match_card(card, ran, "ran_yesterday")
    for card in gathered.declarations:
        _match_card(card, declared, "declared")
    for card in gathered.entries:
        _match_card(card, entered, "entered")

    declared_keys = {(r["sale_id"], r["horse"], r["race_date"], r["off_time"]) for r in declared}
    entered = [
        r for r in entered
        if (r["sale_id"], r["horse"], r["race_date"], r["off_time"]) not in declared_keys
    ]

    return ran, declared, entered


def _filter_already_sent(
    conn: sqlite3.Connection, run_date: date, category: str, rows: list[dict]
) -> list[dict]:
    fresh: list[dict] = []
    for row in rows:
        key = horse_key(normalize_name(row["horse"]), row.get("year_foaled"))
        race_id = row["race_id"]
        existing = conn.execute(
            "SELECT 1 FROM email_log WHERE run_date=? AND category=? AND horse_key=? AND race_id=?",
            (run_date.isoformat(), category, key, race_id),
        ).fetchone()
        if existing is None:
            fresh.append(row)
    return fresh


def _log_send(
    conn: sqlite3.Connection,
    run_date: date,
    categorised: dict[str, list[dict]],
) -> None:
    now = _utcnow()
    for category, rows in categorised.items():
        for row in rows:
            key = horse_key(normalize_name(row["horse"]), row.get("year_foaled"))
            conn.execute(
                """
                INSERT OR IGNORE INTO email_log (run_date, category, horse_key, race_id, payload_json, sent_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_date.isoformat(), category, key, row["race_id"], json.dumps(row, default=_json_default), now),
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

        catalogue_count = conn.execute("SELECT COUNT(*) FROM catalogue_entries").fetchone()[0]
        if catalogue_count == 0:
            log.warning("Catalogue is empty. Run `python -m dailybreezeup.seed --all --years %d` first.", today.year)

        gathered = gather(today)
        ran, declared, entered = _classify(conn, today, gathered)

        ran = _filter_already_sent(conn, today, "ran_yesterday", ran)
        declared = _filter_already_sent(conn, today, "declared", declared)
        entered = _filter_already_sent(conn, today, "entered", entered)

        payload = render(
            run_date=today,
            ran_yesterday=ran,
            declared=declared,
            entered=entered,
        )
        _write_preview(payload)

        summary = {
            "catalogue_count": catalogue_count,
            "ran_yesterday": len(ran),
            "declared": len(declared),
            "entered": len(entered),
            "races_declared": len(gathered.declarations),
            "races_entered": len(gathered.entries),
            "races_results": len(gathered.results),
        }
        log.info("summary: %s", summary)

        total = len(ran) + len(declared) + len(entered)
        will_send = not (dry_run or no_send)
        if will_send and (total > 0 or settings.notify_on_empty):
            try:
                send(payload, settings)
                _log_send(conn, today, {"ran_yesterday": ran, "declared": declared, "entered": entered})
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="breezeup-daily")
    ap.add_argument("--date", type=date.fromisoformat, default=None, help="YYYY-MM-DD (default: today UK)")
    ap.add_argument("--dry-run", action="store_true", help="Render preview but don't send")
    ap.add_argument("--no-send", action="store_true", help="Alias for --dry-run (kept separate for scripting)")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return run(run_date=args.date, dry_run=args.dry_run, no_send=args.no_send)


if __name__ == "__main__":
    sys.exit(main())
