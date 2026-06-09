"""OBS — Ocala Breeders' Sales (Florida, USA).

The homepage surfaces upcoming sales as ``h4.p-title`` headings inside a
``.slide-content`` block, with the sale date as the first following paragraph
("June 16 - 18, 2026"). Under-Tack / Closing paragraphs are ignored.
"""
from __future__ import annotations

import logging
import re
from datetime import date

import lxml.html

from salescatalogues.models import RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://obssales.com/"
BASE = "https://obssales.com"

_DATEY_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*.*?20\d{2}", re.IGNORECASE
)


def parse_home(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[str] = set()
    for block in doc.cssselect(".slide-content"):
        title = block.cssselect("h4.p-title a, .p-title a")
        if not title:
            continue
        name = squash(title[0].text_content())
        if not name or "sale" not in name.lower():
            continue
        if name.lower() in seen:
            continue
        # First paragraph that looks like a sale date (skip Under Tack / Closing).
        date_text = ""
        for p in block.cssselect("p"):
            txt = squash(p.text_content())
            low = txt.lower()
            if _DATEY_RE.search(txt) and "under tack" not in low and "clos" not in low:
                date_text = txt
                break
        start, end = parse_date_range(date_text, ref, dayfirst=False)
        if start is None:
            continue
        seen.add(name.lower())
        href = title[0].get("href") or ""
        url = href if href.startswith("http") else f"{BASE}{href}" if href else URL
        out.append(
            RawSale(
                house="OBS",
                country="US",
                name=name,
                start_date=start,
                end_date=end,
                url=url,
                online="online" in name.lower(),
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("OBS fetch failed: %s", exc)
        return []
    return parse_home(html, ref=ref)
