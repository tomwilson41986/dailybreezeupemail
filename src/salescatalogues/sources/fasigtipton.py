"""Fasig-Tipton (USA) — calendar page of ``.sales-event-calendar-list-item``
rows. Each has start/end date fields, a name + link, and a ``<strong>`` that
reads "Online" for the digital sales (otherwise the venue).
"""
from __future__ import annotations

import logging
import re
from datetime import date

import lxml.html

from salescatalogues.models import Lot, RawSale
from salescatalogues.sources.base import get_json, get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://www.fasigtipton.com/calendar/2026"
BASE = "https://www.fasigtipton.com"
SALES_API = "https://www.fasigtipton.com/django/api/sales/?sale_identifier={code}"
HORSES_API = "https://www.fasigtipton.com/django/api/horses/?sale={sale_id}"

# The sale's catalogue code, embedded in the sale page's drupalSettings.
_IDENTIFIER_RE = re.compile(r'"sale_identifier"\s*:\s*"([^"]+)"')


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


def parse_lots(rows: list) -> list[Lot]:
    lots: list[Lot] = []
    for h in rows or []:
        if not isinstance(h, dict):
            continue
        name = (h.get("name") or "").strip()
        # Unnamed weanlings/2yos publish a "YYYY-DAMNAME" placeholder; blank it.
        if re.match(r"^\d{4}-", name):
            name = ""
        lots.append(
            Lot(
                lot_no=str(h.get("hip") or "").strip(),
                horse_name=name,
                sex=(h.get("sex") or "").strip(),
                colour=(h.get("color") or "").strip(),
                sire=(h.get("sire") or "").strip(),
                dam=(h.get("dam") or "").strip(),
                dam_sire=(h.get("sire_of_dam") or "").strip(),
                vendor=(h.get("consignor_name") or h.get("consignor") or "").strip(),
            )
        )
    return lots


def fetch_lots(raw: RawSale, session=None) -> list[Lot]:
    """Two-step: read the sale's catalogue code off its page, resolve it to the
    API's numeric sale id, then pull all hips. The separate digital platform
    (digital.fasigtipton.com) isn't covered."""
    if "fasigtipton.com" not in raw.url or "digital." in raw.url:
        return []
    session = session or make_session()
    try:
        page = get_text(session, raw.url)
        m = _IDENTIFIER_RE.search(page)
        if not m:
            return []
        sales = get_json(session, SALES_API.format(code=m.group(1)))
        if not sales or not isinstance(sales, list):
            return []
        sale_id = sales[0].get("id")
        if sale_id is None:
            return []
        rows = get_json(session, HORSES_API.format(sale_id=sale_id))
    except Exception as exc:  # noqa: BLE001
        log.warning("Fasig-Tipton lot fetch failed (%s): %s", raw.url, exc)
        return []
    return parse_lots(rows) if isinstance(rows, list) else []
