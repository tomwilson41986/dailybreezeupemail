"""Magic Millions Online — the "MM Digital" timed online auctions, published on
a separate platform from the main (physical) sales calendar. The
``/sales-calendar`` page lists each digital sale as an ``.upcoming-sale`` block
with a day range, month, year, and an "Add to Calendar" link whose
``dates=YYYYMMDD.../YYYYMMDD...`` query gives unambiguous machine dates.
"""
from __future__ import annotations

import logging
import re
from datetime import date

import lxml.html

from salescatalogues.models import RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://magicmillions.digital/sales-calendar/"
# Machine dates Google-Calendar export embeds in each block's link.
_CAL_DATES_RE = re.compile(r"dates=(\d{8})T[\dZ]*/(\d{8})T[\dZ]*")


def _iso(stamp: str) -> date | None:
    try:
        return date(int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8]))
    except (ValueError, IndexError):
        return None


def parse_calendar(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[str] = set()
    for block in doc.cssselect(".upcoming-sale"):
        name_el = block.cssselect(".sale-name")
        name = squash(name_el[0].text_content()) if name_el else ""
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())

        # Prefer the exact dates from the calendar-export link; fall back to the
        # human "12-17 / JUN / 2026" cells if it's missing.
        start = end = None
        cal = block.cssselect("a.add-to-calendar")
        href = cal[0].get("href") if cal else ""
        m = _CAL_DATES_RE.search(href or "")
        if m:
            start, end = _iso(m.group(1)), _iso(m.group(2))
        if start is None:
            parts = [
                squash(block.cssselect(sel)[0].text_content())
                for sel in (".sale-date", ".sale-month", ".sale-year")
                if block.cssselect(sel)
            ]
            start, end = parse_date_range(" ".join(parts), ref, dayfirst=True)

        out.append(
            RawSale(
                house="Magic Millions",
                country="AUS",
                name=name,
                start_date=start,
                end_date=end if end != start else None,
                url=URL,
                online=True,
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("Magic Millions Online fetch failed: %s", exc)
        return []
    return parse_calendar(html, ref=ref)
