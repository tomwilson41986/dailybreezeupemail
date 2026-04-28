"""Google Sheets enrichment.

The user maintains a Google Sheet of breeze-up sale lots with proprietary
analytics columns (Breeze Rating, Precocity Rating, OT Rank, etc.). Rows in
that sheet are the canonical cohort. We join RP catalogue rows to the sheet
on ``(year, sale_short, lot_no)`` so the email can surface those analytics
alongside the entry/result info that comes from RP.

The sheet is read as a CSV via the public ``/export?format=csv`` endpoint —
no auth, no service account. Set ``SHEET_CSV_URL`` to override the default.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from typing import Iterable

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

DEFAULT_SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "12neJo7BsCsHg20m-es5ERkLJCevUzXyMDnvV9-ygrMk/export?format=csv"
)

# Map RP's verbose sale name -> the short label used in the sheet's "Sale" column.
# Keep this list in sync with whatever the user types into the sheet.
_SALE_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"craven", re.I), "Craven"),
    (re.compile(r"goffs.*uk", re.I), "Goffs UK"),
    (re.compile(r"arqana", re.I), "Arqana"),
    (re.compile(r"tattersalls\s+ireland", re.I), "Tattersalls Ireland"),
)


def sale_short_name(sale_name: str) -> str | None:
    """Return the short sale label used in the sheet, or None if unknown."""
    for pat, short in _SALE_ALIASES:
        if pat.search(sale_name):
            return short
    return None


@dataclass(frozen=True)
class SheetRow:
    year: int
    sale: str
    lot: int
    sex: str
    sire: str
    dam: str
    vendor: str
    buyer: str
    price: str
    ot_diff_m: float | None
    ot_rank: int | None
    sl_1f: float | None
    sl_go: float | None
    breeze_rating: float | None
    precocity_rating: float | None

    @property
    def key(self) -> tuple[int, str, int]:
        return (self.year, self.sale, self.lot)


def _as_float(x: str) -> float | None:
    s = (x or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _as_int(x: str) -> int | None:
    s = (x or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_sheet_csv(text: str) -> list[SheetRow]:
    """Parse the CSV body returned by Google Sheets export."""
    reader = csv.DictReader(io.StringIO(text))
    rows: list[SheetRow] = []
    for raw in reader:
        year = _as_int(raw.get("Year") or "")
        lot = _as_int(raw.get("Lot") or "")
        sale = (raw.get("Sale") or "").strip()
        if year is None or lot is None or not sale:
            continue
        rows.append(
            SheetRow(
                year=year,
                sale=sale,
                lot=lot,
                sex=(raw.get("Sex") or "").strip(),
                sire=(raw.get("Sire") or "").strip(),
                dam=(raw.get("Dam") or "").strip(),
                vendor=(raw.get("Vendor") or "").strip(),
                buyer=(raw.get("Buyer") or "").strip(),
                price=(raw.get("Price") or "").strip(),
                ot_diff_m=_as_float(raw.get("OT Diff/M") or ""),
                ot_rank=_as_int(raw.get("OT Rank") or ""),
                sl_1f=_as_float(raw.get("SL 1F") or ""),
                sl_go=_as_float(raw.get("SL GO") or ""),
                breeze_rating=_as_float(raw.get("Breeze Rating") or ""),
                precocity_rating=_as_float(raw.get("Precocity Rating") or ""),
            )
        )
    return rows


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def fetch_sheet(url: str = DEFAULT_SHEET_CSV_URL) -> list[SheetRow]:
    # Google's CDN returns 503 to the default `python-requests/...` UA on
    # /export?format=csv even for public sheets; a browser UA is enough.
    # The redirect to googleusercontent.com occasionally 503s transiently,
    # which is what the retry covers.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/csv,text/plain,*/*",
    }
    r = requests.get(url, timeout=30, allow_redirects=True, headers=headers)
    r.raise_for_status()
    return parse_sheet_csv(r.text)


def index_by_key(rows: Iterable[SheetRow]) -> dict[tuple[int, str, int], SheetRow]:
    return {row.key: row for row in rows}


def count_by_sale(rows: Iterable[SheetRow]) -> dict[tuple[int, str], int]:
    """Total rows per (year, sale_short) — denominator for OT rank display."""
    out: dict[tuple[int, str], int] = {}
    for row in rows:
        out[(row.year, row.sale)] = out.get((row.year, row.sale), 0) + 1
    return out


def enrichment_fields(row: SheetRow, *, sale_total: int | None = None) -> dict[str, object]:
    """The subset of sheet columns we surface in the email."""
    return {
        "sheet_breeze_rating": row.breeze_rating,
        "sheet_precocity_rating": row.precocity_rating,
        "sheet_ot_rank": row.ot_rank,
        "sheet_ot_diff_m": row.ot_diff_m,
        "sheet_sl_1f": row.sl_1f,
        "sheet_sl_go": row.sl_go,
        "sheet_sale_total": sale_total,
        "sheet_sire": row.sire,
        "sheet_dam": row.dam,
        "sheet_vendor": row.vendor,
        "sheet_buyer": row.buyer,
        "sheet_price": row.price,
    }
