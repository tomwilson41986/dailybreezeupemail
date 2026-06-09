"""Magic Millions (Australia) — The Events Calendar grid of
``.type-tribe_events`` blocks. Title (with a leading year) sits in the event
``h2 a``; the date ("21 June", year omitted) in ``.tribe-events-event-meta``.
The leading year from the name is folded into the date string to pin it.
"""
from __future__ import annotations

import logging
import re
from datetime import date

import lxml.html

from salescatalogues.models import RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://www.magicmillions.com.au/sales/?upcoming=true"
_LEADING_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def parse_upcoming(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[str] = set()
    for ev in doc.cssselect(".type-tribe_events"):
        title = ev.cssselect("h2 a, .tribe-events-list-event-title a")
        if not title:
            title = [a for a in ev.cssselect("a.url") if squash(a.text_content()) and
                     squash(a.text_content()).lower() != "read more"]
        if not title:
            continue
        name = squash(title[0].text_content())
        href = title[0].get("href") or URL
        if not name or href in seen:
            continue
        seen.add(href)

        meta = ev.cssselect(".tribe-events-event-meta")
        date_text = squash(meta[0].text_content()) if meta else ""
        ym = _LEADING_YEAR_RE.search(name)
        if ym and not _LEADING_YEAR_RE.search(date_text):
            date_text = f"{date_text} {ym.group(1)}"
        start, end = parse_date_range(date_text, ref, dayfirst=True)

        out.append(
            RawSale(
                house="Magic Millions",
                country="AUS",
                name=name,
                start_date=start,
                end_date=end,
                url=href,
                online=False,
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("Magic Millions fetch failed: %s", exc)
        return []
    return parse_upcoming(html, ref=ref)
