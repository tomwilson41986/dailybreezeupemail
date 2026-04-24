"""Catalogue seeding CLI.

Primary source is a Google Sheet you maintain (columns: Year, Sale, Lot, Sex,
Sire, Dam, Vendor, Buyer, Price, OT Diff/M, OT Rank, SL 1F, SL GO,
Breeze Rating, Precocity Rating). Pass the shared link with `--sheet`.

Examples:
  python -m dailybreezeup.seed --sheet "https://docs.google.com/spreadsheets/d/<ID>/edit"
  python -m dailybreezeup.seed --all --years 2026                # vendor scrapers (fallback)
  python -m dailybreezeup.seed --sale tatts-craven-2026
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Iterable

from dailybreezeup import sheet as sheet_ingest
from dailybreezeup.config import load as load_settings
from dailybreezeup.db import session
from dailybreezeup.matching import normalize_name
from dailybreezeup.models import RawLot, SaleDescriptor
from dailybreezeup.scrapers import SCRAPERS, Scraper

log = logging.getLogger("dailybreezeup.seed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _upsert_sale(conn, sale: SaleDescriptor) -> None:  # noqa: ANN001
    conn.execute(
        """
        INSERT INTO sales (id, vendor, name, country, year, start_date, source_url, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          vendor=excluded.vendor, name=excluded.name, country=excluded.country,
          year=excluded.year, start_date=excluded.start_date,
          source_url=excluded.source_url, scraped_at=excluded.scraped_at
        """,
        (
            sale.id, sale.vendor, sale.name, sale.country, sale.year,
            sale.start_date.isoformat() if sale.start_date else None,
            sale.source_url, _now(),
        ),
    )


def _upsert_lot(conn, lot: RawLot) -> None:  # noqa: ANN001
    conn.execute(
        """
        INSERT INTO catalogue_entries (
          sale_id, lot, horse_name, normalized_name, country_bred, year_foaled,
          sire, dam, damsire, sex, consignor, buyer, price, currency, withdrawn,
          source_url, scraped_at,
          ot_diff_m, ot_rank, sl_1f, sl_go, breeze_rating, precocity_rating, sheet_row_url
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,  ?,?,?,?,?,?,?)
        ON CONFLICT(sale_id, lot) DO UPDATE SET
          horse_name=excluded.horse_name,
          normalized_name=excluded.normalized_name,
          country_bred=excluded.country_bred,
          year_foaled=excluded.year_foaled,
          sire=excluded.sire, dam=excluded.dam, damsire=excluded.damsire,
          sex=excluded.sex, consignor=excluded.consignor, buyer=excluded.buyer,
          price=excluded.price, currency=excluded.currency,
          withdrawn=excluded.withdrawn, source_url=excluded.source_url,
          scraped_at=excluded.scraped_at,
          ot_diff_m=excluded.ot_diff_m, ot_rank=excluded.ot_rank,
          sl_1f=excluded.sl_1f, sl_go=excluded.sl_go,
          breeze_rating=excluded.breeze_rating,
          precocity_rating=excluded.precocity_rating,
          sheet_row_url=excluded.sheet_row_url
        """,
        (
            lot.sale_id, lot.lot, lot.horse_name,
            normalize_name(lot.horse_name),
            lot.country_bred, lot.year_foaled,
            lot.sire, lot.dam, lot.damsire, lot.sex,
            lot.consignor, lot.buyer, lot.price, lot.currency,
            1 if lot.withdrawn else 0, lot.source_url, _now(),
            lot.ot_diff_m, lot.ot_rank, lot.sl_1f, lot.sl_go,
            lot.breeze_rating, lot.precocity_rating, lot.sheet_row_url,
        ),
    )


def _ingest_sale(conn, scraper: Scraper, sale: SaleDescriptor) -> int:  # noqa: ANN001
    _upsert_sale(conn, sale)
    n = 0
    for lot in scraper.fetch_lots(sale.id):
        _upsert_lot(conn, lot)
        n += 1
    return n


def _iter_targets(
    *,
    all_: bool,
    vendor: str | None,
    sale_id: str | None,
    years: list[int],
) -> Iterable[tuple[Scraper, SaleDescriptor]]:
    if sale_id:
        vendor_key = next((v for v in SCRAPERS if sale_id.startswith(v) or sale_id.startswith("tatts")), None)
        if sale_id.startswith("tatts"):
            vendor_key = "tattersalls"
        if vendor_key is None:
            raise SystemExit(f"Could not infer vendor from sale_id={sale_id!r}")
        scraper = SCRAPERS[vendor_key]()
        for s in scraper.list_sales(years):
            if s.id == sale_id:
                yield scraper, s
                return
        year = int(sale_id.rsplit("-", 1)[-1])
        for s in scraper.list_sales([year]):
            if s.id == sale_id:
                yield scraper, s
                return
        raise SystemExit(f"Scraper {vendor_key} does not recognise sale_id={sale_id!r}")

    vendors = [vendor] if vendor else list(SCRAPERS.keys()) if all_ else []
    if not vendors:
        raise SystemExit("Pass --all, --vendor, or --sale")

    for v in vendors:
        if v not in SCRAPERS:
            raise SystemExit(f"Unknown vendor: {v}. Known: {sorted(SCRAPERS)}")
        scraper = SCRAPERS[v]()
        for s in scraper.list_sales(years):
            yield scraper, s


def _seed_from_sheet(conn, share_url: str) -> dict[str, int]:  # noqa: ANN001
    totals: dict[str, int] = {}
    seen_sales: set[str] = set()
    for sale, lot in sheet_ingest.iter_sales_and_lots(share_url):
        if sale.id not in seen_sales:
            _upsert_sale(conn, sale)
            seen_sales.add(sale.id)
        _upsert_lot(conn, lot)
        totals[sale.id] = totals.get(sale.id, 0) + 1
    return totals


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="breezeup-seed")
    ap.add_argument("--sheet", help="Google Sheet share URL (overrides vendor scrapers)")
    ap.add_argument("--all", action="store_true", help="Seed all configured vendors")
    ap.add_argument("--vendor", choices=sorted(SCRAPERS), help="Seed a single vendor")
    ap.add_argument("--sale", help="Seed a single sale by id, e.g. tatts-craven-2026")
    ap.add_argument("--years", type=int, nargs="+", default=[datetime.now().year])
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    settings = load_settings()
    totals: dict[str, int] = {}

    sheet_url = args.sheet or os.environ.get("SHEET_URL", "")

    with session(settings.db_path) as conn:
        if sheet_url:
            totals = _seed_from_sheet(conn, sheet_url)
            for sid, n in totals.items():
                log.info("seeded %s: %d lots (sheet)", sid, n)
        else:
            for scraper, sale in _iter_targets(
                all_=args.all, vendor=args.vendor, sale_id=args.sale, years=args.years,
            ):
                n = _ingest_sale(conn, scraper, sale)
                totals[sale.id] = n
                log.info("seeded %s: %d lots", sale.id, n)

    if not totals:
        log.warning("No sales ingested.")
        return 1

    print("\nSeed summary")
    print("-" * 52)
    for sale_id, n in sorted(totals.items()):
        print(f"  {sale_id:<36} {n:>5} lots")
    return 0


if __name__ == "__main__":
    sys.exit(main())
