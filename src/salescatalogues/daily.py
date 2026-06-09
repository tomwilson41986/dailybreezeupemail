"""Daily Sales Catalogues — entrypoint.

Runs every source, enriches each scraped sale (sale type, New / Active flags),
drops Jumps / National Hunt / store and non-thoroughbred sales and anything
already finished or beyond the horizon, then emails a country-grouped digest
with the full list attached as CSV.

Usage:
  salescatalogues-daily              # build + send today's digest
  salescatalogues-daily --dry-run    # render preview to data/, don't send
  salescatalogues-daily --date 2026-06-09
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from salescatalogues import db
from salescatalogues.classify import build_catalogue, is_excluded
from salescatalogues.config import Settings
from salescatalogues.config import load as load_settings
from salescatalogues.emailer import EmailPayload, render, send
from salescatalogues.lots import collect_lots
from salescatalogues.models import Catalogue, RawSale
from salescatalogues.sources.base import make_session
from salescatalogues.sources.registry import SOURCES

log = logging.getLogger("salescatalogues.daily")
UK = ZoneInfo("Europe/London")
PREVIEW_HTML = Path("data/catalogues_preview.html")
PREVIEW_TXT = Path("data/catalogues_preview.txt")
PREVIEW_CSV = Path("data/catalogues_preview.csv")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def collect_raw(session, today: date) -> tuple[list[RawSale], dict[str, str]]:
    """Run every source, isolating failures. Returns the raw sales plus a
    per-source status string for diagnostics."""
    raws: list[RawSale] = []
    status: dict[str, str] = {}
    for src in SOURCES:
        try:
            rows = src.fetch(session, ref=today)
            for r in rows:
                r.source_key = src.key
            raws.extend(rows)
            status[src.key] = f"{len(rows)}"
            log.info("%-22s %d sale(s)", src.label, len(rows))
        except Exception as exc:  # noqa: BLE001
            status[src.key] = f"ERR:{exc.__class__.__name__}"
            log.warning("%s failed: %s", src.label, exc)
    return raws, status


def _in_scope(raw: RawSale, today: date, horizon_days: int) -> bool:
    """Keep upcoming / active thoroughbred sales; drop excluded, finished, and
    far-future entries. Undated sales are kept (rolling online auctions)."""
    if is_excluded(raw):
        return False
    end = raw.effective_end()
    start = raw.start_date
    finished = end is not None and end < today
    beyond = start is not None and start > today + timedelta(days=horizon_days)
    return not (finished or beyond)


def build_catalogues(
    raws: list[RawSale], conn, today: date, settings: Settings
) -> list[Catalogue]:
    """Filter to in-scope sales, enrich each, and persist the seen-ledger."""
    cats: list[Catalogue] = []
    seen_ids: set[str] = set()
    for raw in raws:
        if not _in_scope(raw, today, settings.horizon_days):
            continue
        first_seen = None
        cat = build_catalogue(raw, today, first_seen=None,
                              lead_days=settings.active_lead_days)
        if cat.catalogue_id in seen_ids:
            continue  # two sources / dupes for the same sale
        seen_ids.add(cat.catalogue_id)

        first_seen = db.get_first_seen(conn, cat.catalogue_id)
        # Rebuild with the real first_seen so is_new / status_label are correct.
        cat = build_catalogue(raw, today, first_seen=first_seen,
                              lead_days=settings.active_lead_days)
        cats.append(cat)
        db.record_seen(
            conn,
            catalogue_id=cat.catalogue_id,
            house=cat.house,
            country=cat.country,
            name=cat.name,
            start_date=cat.start_date,
            today=today,
        )
    return cats


def _write_preview(payload: EmailPayload) -> None:
    PREVIEW_HTML.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_HTML.write_text(payload.html, encoding="utf-8")
    PREVIEW_TXT.write_text(payload.text, encoding="utf-8")
    PREVIEW_CSV.write_text(payload.csv_text, encoding="utf-8")


def run(*, run_date: date | None = None, dry_run: bool = False) -> int:
    settings = load_settings()
    today = run_date or datetime.now(UK).date()

    with db.session(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO run_log (run_date, started_at, status) VALUES (?, ?, ?)",
            (today.isoformat(), _utcnow(), "running"),
        )
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        session = make_session()
        raws, source_status = collect_raw(session, today)
        log.info("Collected %d raw sale(s) across %d sources", len(raws), len(SOURCES))

        catalogues = build_catalogues(raws, conn, today, settings)
        active = sum(1 for c in catalogues if c.is_active)
        new = sum(1 for c in catalogues if c.is_new)
        log.info("In scope: %d (active=%d, new=%d)", len(catalogues), active, new)

        log.info("Fetching lots for published catalogues...")
        lots_by_id, lot_counts = collect_lots(catalogues, session)
        total_lots = sum(len(v) for v in lots_by_id.values())
        log.info("Lots fetched: %d across %d catalogue(s)", total_lots, len(lots_by_id))

        diagnostics = {
            "source_status": ", ".join(
                f"{k}={v}" for k, v in sorted(source_status.items())
            ),
        }
        payload = render(
            run_date=today,
            catalogues=catalogues,
            lots_by_id=lots_by_id,
            diagnostics=diagnostics,
        )
        _write_preview(payload)

        summary = {
            "total": len(catalogues),
            "active": active,
            "new": new,
            "lots": total_lots,
            "lots_by_source": lot_counts,
            "sources": source_status,
        }
        log.info("summary: %s", summary)

        will_send = not dry_run
        send_when_empty = settings.notify_on_empty
        if will_send and (catalogues or send_when_empty):
            try:
                send(payload, settings)
                status = "ok"
            except Exception as exc:  # noqa: BLE001
                log.exception("email send failed: %s", exc)
                status = "failed"
        else:
            log.info("skipping send (dry_run=%s, total=%d)", dry_run, len(catalogues))
            status = "dry_run" if dry_run else "ok"

        conn.execute(
            "UPDATE run_log SET finished_at=?, status=?, summary_json=? WHERE id=?",
            (_utcnow(), status, json.dumps(summary), run_id),
        )

    return 0 if status in ("ok", "dry_run") else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="salescatalogues-daily")
    ap.add_argument("--date", type=date.fromisoformat, default=None,
                    help="YYYY-MM-DD (default: today UK)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Render preview to data/ but don't send")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return run(run_date=args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
