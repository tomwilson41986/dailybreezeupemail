"""Google Sheet ingestor — the primary catalogue source.

Reads a Google Sheet that has been shared with "anyone with the link can view"
by requesting the CSV export endpoint (no OAuth needed).

Expected columns (case-insensitive, flexible whitespace/order):
  Year, Sale, Lot, Sex, Sire, Dam, Vendor, Buyer, Price,
  OT Diff/M, OT Rank, SL 1F, SL GO, Breeze Rating, Precocity Rating
Optional: Horse (picked up when the user names the horse post-sale).

Rows are grouped by (Year, Sale) and each group becomes a `sales` row; each
data row becomes a `catalogue_entries` row keyed on (sale_id, lot).

Sale-name mapping lives in `SALE_MAPPING` below — a short identifier the user
uses in the "Sale" column gets mapped to the canonical sale record we create.
If a sheet row's Sale value has no mapping, ingestion raises so it's surfaced
rather than silently skipped.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Iterator
from urllib.parse import parse_qs, quote, urlparse

import requests

from dailybreezeup.models import RawLot, SaleDescriptor

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SaleMapping:
    id_prefix: str
    name: str
    vendor: str
    country: str
    default_currency: str


# Keys are lower-cased values the user puts in the sheet's "Sale" column.
SALE_MAPPING: dict[str, SaleMapping] = {
    "craven": SaleMapping("tatts-craven", "Tattersalls Craven Breeze Up Sale", "tattersalls", "GB", "GBP"),
    "guineas": SaleMapping("tatts-guineas", "Tattersalls Guineas Breeze Up Sale", "tattersalls", "GB", "GBP"),
    "goffs uk": SaleMapping("goffs-uk-breezeup", "Goffs UK Breeze Up Sale", "goffs-uk", "GB", "GBP"),
    "doncaster": SaleMapping("goffs-uk-breezeup", "Goffs UK Breeze Up Sale", "goffs-uk", "GB", "GBP"),
    "goffs ireland": SaleMapping("goffs-ie-breezeup", "Goffs Breeze Up Sale", "goffs-ie", "IE", "EUR"),
    "goffs ie": SaleMapping("goffs-ie-breezeup", "Goffs Breeze Up Sale", "goffs-ie", "IE", "EUR"),
    "goffs": SaleMapping("goffs-ie-breezeup", "Goffs Breeze Up Sale", "goffs-ie", "IE", "EUR"),
    "arqana": SaleMapping("arqana-breezeup", "Arqana Breeze Up", "arqana", "FR", "EUR"),
    "deauville": SaleMapping("arqana-breezeup", "Arqana Breeze Up", "arqana", "FR", "EUR"),
}


def extract_sheet_id(url: str) -> str:
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    if not m:
        raise ValueError(f"Not a Google Sheets URL: {url}")
    return m.group(1)


def extract_gid(url: str) -> str:
    p = urlparse(url)
    if p.fragment:
        qs = parse_qs(p.fragment)
        if "gid" in qs:
            return qs["gid"][0]
    qs = parse_qs(p.query)
    if "gid" in qs:
        return qs["gid"][0]
    return "0"


def csv_export_url(share_url: str) -> str:
    sheet_id = extract_sheet_id(share_url)
    gid = extract_gid(share_url)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def row_deeplink_url(share_url: str, row_number_1indexed: int) -> str:
    sheet_id = extract_sheet_id(share_url)
    gid = extract_gid(share_url)
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={gid}"
        f"&range=A{row_number_1indexed}"
    )


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower()).replace("/", " ").strip()


_PRICE_RE = re.compile(r"([0-9][0-9,]*)")


def _parse_price(raw: str, default_currency: str) -> tuple[int | None, str | None]:
    if not raw:
        return None, None
    currency = "GBP" if "£" in raw else "EUR" if "€" in raw else default_currency
    m = _PRICE_RE.search(raw)
    if not m:
        return None, currency
    return int(m.group(1).replace(",", "")), currency


def _get(row: dict[str, str], *names: str) -> str:
    for n in names:
        key = _norm_header(n)
        if key in row and row[key]:
            return row[key].strip()
    return ""


def _fetch_csv(url: str) -> str:
    r = requests.get(
        csv_export_url(url),
        headers={"User-Agent": "dailybreezeup/0.1"},
        timeout=60,
        allow_redirects=True,
    )
    r.raise_for_status()
    return r.text


def _read_rows(csv_text: str) -> Iterator[tuple[int, dict[str, str]]]:
    reader = csv.reader(io.StringIO(csv_text))
    header_row: list[str] | None = None
    for i, row in enumerate(reader, start=1):
        if not any(c.strip() for c in row):
            continue
        if header_row is None:
            header_row = [_norm_header(c) for c in row]
            continue
        padded = row + [""] * (len(header_row) - len(row))
        yield i, dict(zip(header_row, padded))


def iter_sales_and_lots(
    share_url: str,
    csv_text: str | None = None,
) -> Iterator[tuple[SaleDescriptor, RawLot]]:
    text = csv_text if csv_text is not None else _fetch_csv(share_url)
    seen_sales: dict[str, SaleDescriptor] = {}

    for row_number, row in _read_rows(text):
        sale_raw = _get(row, "sale")
        year_raw = _get(row, "year")
        lot_raw = _get(row, "lot")
        if not sale_raw or not year_raw:
            log.warning("skipping row %d: missing sale/year", row_number)
            continue

        try:
            year = int(year_raw)
        except ValueError:
            log.warning("skipping row %d: non-numeric year %r", row_number, year_raw)
            continue

        mapping = SALE_MAPPING.get(sale_raw.strip().lower())
        if mapping is None:
            log.warning(
                "skipping row %d: unknown sale %r (add to sheet.SALE_MAPPING)",
                row_number, sale_raw,
            )
            continue

        sale_id = f"{mapping.id_prefix}-{year}"
        if sale_id not in seen_sales:
            seen_sales[sale_id] = SaleDescriptor(
                id=sale_id,
                vendor=mapping.vendor,
                name=mapping.name,
                country=mapping.country,  # type: ignore[arg-type]
                year=year,
                source_url=share_url,
            )

        price, currency = _parse_price(_get(row, "price"), mapping.default_currency)

        yield seen_sales[sale_id], RawLot(
            sale_id=sale_id,
            lot=lot_raw or None,
            horse_name=_get(row, "horse", "horse name", "name"),
            year_foaled=year - 2,  # breeze-ups sell 2yos
            sex=_get(row, "sex") or None,
            sire=_get(row, "sire") or None,
            dam=_get(row, "dam") or None,
            consignor=_get(row, "vendor", "consignor") or None,
            buyer=_get(row, "buyer", "purchaser") or None,
            price=price,
            currency=currency,
            withdrawn=_get(row, "withdrawn") in ("y", "yes", "true", "1", "wd"),
            source_url=share_url,
            ot_diff_m=_get(row, "ot diff m", "ot diff/m") or None,
            ot_rank=_get(row, "ot rank") or None,
            sl_1f=_get(row, "sl 1f") or None,
            sl_go=_get(row, "sl go") or None,
            breeze_rating=_get(row, "breeze rating") or None,
            precocity_rating=_get(row, "precocity rating") or None,
            sheet_row_url=row_deeplink_url(share_url, row_number),
        )
