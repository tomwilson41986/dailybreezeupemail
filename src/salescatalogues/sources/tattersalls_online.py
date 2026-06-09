"""Tattersalls Online (UK) — the online auction platform. The homepage banner
exposes the current/next online sales as ``.home-header-online__main-sale``
blocks, each with a name, a date span, and a ``.tag`` ("Sale Live") when bidding
is open. Dates omit the year.
"""
from __future__ import annotations

import logging
from datetime import date

import lxml.html

from salescatalogues.models import RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://www.tattersallsonline.com/"


def parse_home(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[str] = set()
    for block in doc.cssselect(".home-header-online__main-sale"):
        header = block.cssselect(".home-header-online__main-sale-header, h1, h2, h3")
        name = squash(header[0].text_content()) if header else ""
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())

        date_el = block.cssselect(".home-header-online__main-sale-date")
        date_text = squash(date_el[0].text_content()) if date_el else ""
        start, end = parse_date_range(date_text, ref, dayfirst=True)

        tag = block.cssselect(".tag")
        tag_text = squash(tag[0].text_content()).lower() if tag else ""
        status = "live" if "live" in tag_text else "upcoming"

        link = block.cssselect("a")
        href = next((a.get("href") for a in link if a.get("href")), "") or URL
        out.append(
            RawSale(
                house="Tattersalls Online",
                country="UK",
                name=name,
                start_date=start,
                end_date=end,
                url=href,
                online=True,
                status_hint=status,
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("Tattersalls Online fetch failed: %s", exc)
        return []
    return parse_home(html, ref=ref)
