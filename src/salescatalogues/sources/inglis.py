"""Inglis (Australia) — calendar table with SALE / DATE / LOCATION / ENTRY
CLOSING columns. Online sales sit at "Inglis Digital AUS" and link
inglisdigital.com; physical sales link inglis.com.au/sale/. Dates omit the
year (inferred as the nearest upcoming).
"""
from __future__ import annotations

import logging
from datetime import date

import lxml.html

from salescatalogues.models import RawSale
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
