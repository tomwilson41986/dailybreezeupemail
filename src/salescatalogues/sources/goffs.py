"""Goffs — covers both Goffs (Ireland) and Goffs UK off a single
``/upcoming-sales`` page of ``.sale-tile`` blocks.

Each tile carries the country via its pin image (``IRE``/``UK``), a date span
(year omitted), a short description (used to spot store/NH sales), and a link
whose label hints status: "Catalogue >" (catalogue available), "View Sales Day
Live >" (in progress), or "Sale Info >" / "More Info >" (upcoming).
"""
from __future__ import annotations

import logging
from datetime import date

import lxml.html

from salescatalogues.models import RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://www.goffs.com/upcoming-sales"
BASE = "https://www.goffs.com"


def _country_from_tile(tile) -> str:
    pin = tile.cssselect(".sale-tile__pin")
    src = (pin[0].get("src") if pin else "") or ""
    if "UK" in src.upper():
        return "UK"
    # default to Ireland (Goffs' home market) when the pin is IRE or absent
    return "IRE"


def parse_upcoming(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    for tile in doc.cssselect(".sale-tile"):
        title_el = tile.cssselect(".sale-tile__title")
        if not title_el:
            continue
        name = squash(title_el[0].text_content())
        if not name:
            continue
        country = "UK" if _country_from_tile(tile) == "UK" else "IRE"
        house = "Goffs UK" if country == "UK" else "Goffs"

        date_el = tile.cssselect(".sale-tile__date-description")
        date_text = squash(date_el[0].text_content()) if date_el else ""
        start, end = parse_date_range(date_text, ref, dayfirst=True)

        desc_el = tile.cssselect(".sale-tile__short-description")
        description = squash(desc_el[0].text_content()) if desc_el else ""

        link = tile.cssselect("a.sale-tile__link")
        href = link[0].get("href") if link else ""
        url = href if href.startswith("http") else f"{BASE}{href}" if href else URL
        label = squash(link[0].text_content()).lower() if link else ""
        if "live" in label or "live" in (tile.get("class") or "").lower():
            status = "live"
        elif "catalogue" in label:
            status = "catalogue available"
        else:
            status = "upcoming"

        out.append(
            RawSale(
                house=house,
                country=country,
                name=name,
                start_date=start,
                end_date=end,
                url=url,
                online=False,
                description=description,
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
        log.warning("Goffs fetch failed: %s", exc)
        return []
    return parse_upcoming(html, ref=ref)
