"""Tattersalls (Newmarket, UK) and Tattersalls Ireland.

Both run the same backend, which serves a clean, server-rendered list of
``.sale-card`` blocks at ``/4DCGI/Sale/SaleDates`` — each carrying the sale
name, date span, and a status class (``entries-open`` / ``entries-closed`` /
``catalogue-available``). We read that status as the source hint so a freshly
published catalogue surfaces as such.
"""
from __future__ import annotations

import logging
import re
from datetime import date

import lxml.html

from salescatalogues.models import RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

UK_URL = "https://secure.tattersalls.com/4DCGI/Sale/SaleDates?site=NMT"
IE_URL = "https://secure.tattersalls.ie/4DCGI/Sale/SaleDates"

_STATUS_RE = re.compile(r"sale-card--status-([a-z-]+)")


def parse_saledates(
    html: str, *, country: str, house: str, ref: date
) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    for card in doc.cssselect(".sale-card"):
        heading = card.cssselect(".sale-card__heading a")
        if not heading:
            continue
        name = squash(heading[0].text_content())
        if not name:
            continue
        url = heading[0].get("href") or ""
        meta = card.cssselect(".sale-card__meta-item-text")
        date_text = squash(meta[0].text_content()) if meta else ""
        start, end = parse_date_range(date_text, ref, dayfirst=True)

        status = ""
        m = _STATUS_RE.search(card.get("class") or "")
        if m:
            status = m.group(1).replace("-", " ")
        out.append(
            RawSale(
                house=house,
                country=country,
                name=name,
                start_date=start,
                end_date=end,
                url=url,
                online=False,
                status_hint=status,
            )
        )
    return out


def _fetch_one(session, url: str, *, country: str, house: str, ref: date) -> list[RawSale]:
    try:
        html = get_text(session, url)
    except Exception as exc:  # noqa: BLE001
        log.warning("Tattersalls fetch failed (%s): %s", url, exc)
        return []
    return parse_saledates(html, country=country, house=house, ref=ref)


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    out = _fetch_one(session, UK_URL, country="UK", house="Tattersalls", ref=ref)
    out += _fetch_one(session, IE_URL, country="IRE", house="Tattersalls Ireland", ref=ref)
    return out
