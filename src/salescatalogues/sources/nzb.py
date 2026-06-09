"""New Zealand Bloodstock (NZB) — ``/sales/upcoming`` lists each sale as a
single heading link, e.g. "National Weanling Sale 25 June 2026 at Karaka" or
"National Online Breeding Stock Sale 8 July 2026 on Gavelhouse Plus". The date
(with year) is split out of the heading; online sales are flagged off the name
or a Gavelhouse Plus venue.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

import lxml.html

from salescatalogues.models import Lot, RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://www.nzb.co.nz/sales/upcoming"
BASE = "https://www.nzb.co.nz"

# Captures the date span: day(s) + month + year, e.g. "25 June 2026",
# "18 & 19 November 2026", "25 & 26 January 2026". Requiring the month + year to
# follow the day stops a stray "Book 1" digit in the name from being grabbed.
_DATE_RE = re.compile(
    r"\b\d{1,2}(?:\s*(?:&|-|–|and|to)\s*\d{1,2})?\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+20\d{2}",
    re.IGNORECASE,
)


def parse_upcoming(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[str] = set()
    for a in doc.cssselect("a[class*=text-modern-header], a[class*=text-modern-heading]"):
        text = squash(a.text_content())
        href = a.get("href") or ""
        if not text or "/sales/" not in href or href in seen:
            continue
        m = _DATE_RE.search(text)
        if not m:
            continue
        seen.add(href)
        name = text[: m.start()].strip(" -–—")
        date_text = m.group(0)
        start, end = parse_date_range(date_text, ref, dayfirst=True)
        url = href if href.startswith("http") else f"{BASE}{href}"
        online = "online" in name.lower() or "gavelhouse" in text.lower()
        out.append(
            RawSale(
                house="NZB",
                country="NZ",
                name=name,
                start_date=start,
                end_date=end,
                url=url,
                online=online,
                description=text,
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("NZB fetch failed: %s", exc)
        return []
    return parse_upcoming(html, ref=ref)


def parse_lots(html: str) -> list[Lot]:
    """The sale page embeds the full catalogue JSON in the
    ``#js-sale-table[data-initial-table-data]`` attribute."""
    doc = lxml.html.fromstring(html)
    el = doc.cssselect("#js-sale-table")
    if not el:
        return []
    raw = el[0].get("data-initial-table-data") or ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    lots: list[Lot] = []
    for lot in (data.get("lots") if isinstance(data, dict) else data) or []:
        if not isinstance(lot, dict):
            continue
        lots.append(
            Lot(
                lot_no=str(lot.get("lot") or "").strip(),
                horse_name=(lot.get("horsename") or "").strip(),
                sex=(lot.get("sex") or "").strip(),
                colour=(lot.get("colour") or "").strip(),
                sire=(lot.get("sire") or "").strip(),
                dam=(lot.get("dam") or "").strip(),
                dam_sire=(lot.get("dam_sire") or "").strip(),
                vendor=(lot.get("vendor") or "").strip(),
            )
        )
    return lots


def fetch_lots(raw: RawSale, session=None) -> list[Lot]:
    # Online (Gavelhouse-hosted) NZB sales don't carry this table.
    if raw.online or "/sales/" not in raw.url:
        return []
    session = session or make_session()
    try:
        html = get_text(session, raw.url)
    except Exception as exc:  # noqa: BLE001
        log.warning("NZB lot fetch failed (%s): %s", raw.url, exc)
        return []
    return parse_lots(html)
