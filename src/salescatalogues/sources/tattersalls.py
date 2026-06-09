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

from salescatalogues.models import Lot, RawSale
from salescatalogues.sources.base import (
    get_text,
    make_session,
    parse_date_range,
    split_sex_colour,
    squash,
)

log = logging.getLogger(__name__)

UK_URL = "https://secure.tattersalls.com/4DCGI/Sale/SaleDates?site=NMT"
IE_URL = "https://secure.tattersalls.ie/4DCGI/Sale/SaleDates"
# Per-country host serving the 4D lot listing.
_LOT_HOST = {"UK": "secure.tattersalls.com", "IRE": "secure.tattersalls.ie"}

_STATUS_RE = re.compile(r"sale-card--status-([a-z-]+)")
# Internal sale code embedded in the heading/overview link, e.g. /4DCGI/Sale/JUL26/.
_CODE_RE = re.compile(r"/4DCGI/Sale/([A-Za-z0-9]+)")
# "2023 Ch.F." -> capture the colour+sex token after the year of birth.
_COLSEX_RE = re.compile(r"\b\d{4}\s+([A-Za-z.]+)")


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
        code_m = _CODE_RE.search(url)
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
                catalogue_ref=code_m.group(1) if code_m else "",
            )
        )
    return out


def parse_lots(html: str) -> list[Lot]:
    """Parse the 4D lot-listing table. Each lot row has ``td.lot a.ll`` (number)
    and ``td.tdh`` (name, year/colour/sex token, BY=sire, EX=dam); the consignor
    is the ``td`` after ``td.col2type``. Damsire isn't published in this view."""
    doc = lxml.html.fromstring(html)
    lots: list[Lot] = []
    for tr in doc.cssselect("tr"):
        lot_cell = tr.cssselect("td.lot a.ll")
        tdh = tr.cssselect("td.tdh")
        if not lot_cell or not tdh:
            continue
        lot_no = squash(lot_cell[0].text_content())
        name_el = tdh[0].cssselect("a.hn")
        name = squash(name_el[0].text_content()) if name_el else ""

        smalls = tdh[0].cssselect("span.small")
        sire = dam = ""
        for s in smalls:
            label = (s.text or "").strip().upper()
            if label == "BY":
                sire = (s.tail or "").strip()
            elif label == "EX":
                dam = (s.tail or "").strip()

        ht = tdh[0].cssselect("span.ht")
        token = squash(ht[0].tail) if ht and ht[0].tail else squash(tdh[0].text_content())
        cm = _COLSEX_RE.search(token)
        sex, colour = split_sex_colour(cm.group(1)) if cm else ("", "")

        col2 = tr.cssselect("td.col2type")
        vendor = ""
        if col2:
            nxt = col2[0].getnext()
            vendor = squash(nxt.text_content()) if nxt is not None else ""

        lots.append(
            Lot(
                lot_no=lot_no,
                horse_name=name,
                sex=sex,
                colour=colour,
                sire=sire,
                dam=dam,
                vendor=vendor,
            )
        )
    return lots


def fetch_lots(raw: RawSale, session=None) -> list[Lot]:
    """Seed the 4D session cookie via the sale's Overview page, then fetch and
    parse the lot listing. Returns [] when the catalogue code is unknown."""
    code = raw.catalogue_ref
    host = _LOT_HOST.get(raw.country)
    if not code or not host:
        return []
    session = session or make_session()
    base = f"https://{host}/4DCGI/Sale/{code}"
    try:
        session.get(f"{base}/Main/Overview", timeout=30)  # seed cookies
        html = get_text(session, base)
    except Exception as exc:  # noqa: BLE001
        log.warning("Tattersalls lot fetch failed (%s): %s", code, exc)
        return []
    return parse_lots(html)


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
