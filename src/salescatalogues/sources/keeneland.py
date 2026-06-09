"""Keeneland (Lexington, Kentucky, USA).

Each sale is an ``a`` (linking ``/sales/<year>/<n>/<slug>/``) wrapping an
``h3.card-title`` name plus a trailing date span ("Sept. 14 - 26, 2026"). The
date is the anchor text with the title prefix stripped, parsed month-first.
"""
from __future__ import annotations

import logging
from datetime import date

import lxml.html

from salescatalogues.models import RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://www.keeneland.com/sales/"
BASE = "https://www.keeneland.com"


def parse_sales(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[str] = set()
    for title_el in doc.cssselect("h3.card-title"):
        name = squash(title_el.text_content())
        if not name:
            continue
        # Climb to the enclosing anchor (carries href + the trailing date).
        anchor = title_el
        while anchor is not None and anchor.tag != "a":
            anchor = anchor.getparent()
        href = anchor.get("href") if anchor is not None else ""
        if not href or "/sales/" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)
        full = squash(anchor.text_content()) if anchor is not None else name
        date_text = full[len(name):] if full.startswith(name) else full
        start, end = parse_date_range(date_text, ref, dayfirst=False)
        url = href if href.startswith("http") else f"{BASE}{href}"
        out.append(
            RawSale(
                house="Keeneland",
                country="US",
                name=name,
                start_date=start,
                end_date=end,
                url=url,
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
        log.warning("Keeneland fetch failed: %s", exc)
        return []
    return parse_sales(html, ref=ref)
