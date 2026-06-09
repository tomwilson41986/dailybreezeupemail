"""Inglis (Australia) — calendar table with SALE / DATE / LOCATION / ENTRY
CLOSING columns. Online sales sit at "Inglis Digital AUS" and link
inglisdigital.com; physical sales link inglis.com.au/sale/. Dates omit the
year (inferred as the nearest upcoming).
"""
from __future__ import annotations

import logging
from datetime import date

import lxml.html

from salescatalogues.models import Lot, RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://inglis.com.au/calendar"


def parse_calendar(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[tuple[str, str]] = set()
    for row in doc.cssselect("tr"):
        cells = row.cssselect("td")
        if len(cells) < 2:
            continue
        name = squash(cells[0].text_content())
        date_text = squash(cells[1].text_content())
        location = squash(cells[2].text_content()) if len(cells) > 2 else ""
        if not name or name.upper() == "SALE":
            continue
        key = (name.lower(), date_text)
        if key in seen:
            continue
        seen.add(key)
        start, end = parse_date_range(date_text, ref, dayfirst=True)

        link = row.cssselect("a")
        href = next((a.get("href") for a in link if a.get("href")), "") or URL
        online = "digital" in location.lower() or "inglisdigital" in href.lower()
        out.append(
            RawSale(
                house="Inglis",
                country="AUS",
                name=name,
                start_date=start,
                end_date=end,
                url=href,
                online=online,
                description=location,
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("Inglis fetch failed: %s", exc)
        return []
    return parse_calendar(html, ref=ref)


def _cell_value(cells, idx: int) -> str:
    if idx >= len(cells):
        return ""
    return (cells[idx].get("data-value") or squash(cells[idx].text_content())).strip()


def parse_lots(html: str) -> list[Lot]:
    """The ``?tab=index`` table has one ``tr#lot_<n>`` per lot, cells carrying a
    ``data-value`` in the order: lot, media, colour, sex, sire, dam, vendor,
    purchaser, sold, ts. Damsire isn't published on this view."""
    doc = lxml.html.fromstring(html)
    lots: list[Lot] = []
    for row in doc.cssselect('tr[id^="lot_"]'):
        cells = row.cssselect("td")
        if not cells:
            continue
        lot_no = _cell_value(cells, 0)
        if not lot_no:
            continue
        # Vendor: the visible link text is the clean name (data-value is a slug).
        vendor = squash(cells[6].text_content()) if len(cells) > 6 else ""
        lots.append(
            Lot(
                lot_no=lot_no,
                sex=_cell_value(cells, 3),
                colour=_cell_value(cells, 2),
                sire=_cell_value(cells, 4),
                dam=_cell_value(cells, 5),
                vendor=vendor,
            )
        )
    return lots


def fetch_lots(raw: RawSale, session=None) -> list[Lot]:
    # Inglis Digital (online) lots are behind an auth0-gated API; skip them.
    if raw.online or "inglis.com.au/sale/" not in raw.url:
        return []
    session = session or make_session()
    sep = "&" if "?" in raw.url else "?"
    try:
        html = get_text(session, f"{raw.url}{sep}tab=index")
    except Exception as exc:  # noqa: BLE001
        log.warning("Inglis lot fetch failed (%s): %s", raw.url, exc)
        return []
    return parse_lots(html)
