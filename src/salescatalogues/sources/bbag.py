"""BBAG (Baden-Baden, Germany).

The English events page lists each sale as an ``h3.caption`` followed (further
down the DOM, not as a direct sibling) by paragraphs of detail. We walk the
document in order, attach each paragraph to the current sale, and take the
first paragraph carrying a month + year as the headline sale date.
"""
from __future__ import annotations

import logging
import re
from datetime import date

import lxml.html

from salescatalogues.models import RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://bbag-sales.de/events2026~en_GB"

_DATEY_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*.*?20\d{2}", re.IGNORECASE
)


def parse_events(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    sales: list[tuple[str, list[str]]] = []
    cur: list[str] | None = None
    for el in doc.iter():
        cls = el.get("class") or ""
        if el.tag == "h3" and "caption" in cls:
            name = squash(el.text_content())
            if name and "winner" not in name.lower():
                cur = []
                sales.append((name, cur))
            else:
                cur = None
        elif el.tag == "p" and cur is not None:
            txt = squash(el.text_content())
            if txt:
                cur.append(txt)

    out: list[RawSale] = []
    for name, lines in sales:
        date_line = next((ln for ln in lines if _DATEY_RE.search(ln)), "")
        start, end = parse_date_range(date_line, ref, dayfirst=True)
        out.append(
            RawSale(
                house="BBAG",
                country="DE",
                name=name.title(),
                start_date=start,
                end_date=end,
                url=URL,
                online="online" in name.lower(),
                description=date_line,
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("BBAG fetch failed: %s", exc)
        return []
    return parse_events(html, ref=ref)
