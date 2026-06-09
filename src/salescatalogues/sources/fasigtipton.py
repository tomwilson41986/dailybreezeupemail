"""Fasig-Tipton (USA) — calendar page of ``.sales-event-calendar-list-item``
rows. Each has start/end date fields, a name + link, and a ``<strong>`` that
reads "Online" for the digital sales (otherwise the venue).
"""
from __future__ import annotations

import logging
from datetime import date

import lxml.html

from salescatalogues.models import RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://www.fasigtipton.com/calendar/2026"
BASE = "https://www.fasigtipton.com"


def parse_calendar(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[str] = set()
    for row in doc.cssselect(".sales-event-calendar-list-item"):
        title = row.cssselect(".sales-description h3 a")
        if not title:
            continue
        name = squash(title[0].text_content())
        href = title[0].get("href") or ""
        if not name or href in seen:
            continue
        seen.add(href)

        start_f = row.cssselect(".field--name-field-sale-start-date")
        end_f = row.cssselect(".field--name-field-sale-end-date")
        start_txt = squash(start_f[0].text_content()) if start_f else ""
        end_txt = squash(end_f[0].text_content()) if end_f else ""
        date_text = f"{start_txt} - {end_txt}" if end_txt else start_txt
        start, end = parse_date_range(date_text, ref, dayfirst=False)

        strong = row.cssselect(".event-dates strong")
        marker = squash(strong[0].text_content()).lower() if strong else ""
        online = "online" in marker or "digital" in href.lower()

        url = href if href.startswith("http") else f"{BASE}{href}"
        out.append(
            RawSale(
                house="Fasig-Tipton",
                country="US",
                name=name,
                start_date=start,
                end_date=end,
                url=url,
                online=online,
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("Fasig-Tipton fetch failed: %s", exc)
        return []
    return parse_calendar(html, ref=ref)
