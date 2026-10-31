"""Inglis (Australia) — calendar table with SALE / DATE / LOCATION / ENTRY
CLOSING columns. Online sales sit at "Inglis Digital AUS" and link
inglisdigital.com; physical sales link inglis.com.au/sale/. Dates omit the
year (inferred as the nearest upcoming).

Inglis Digital runs on Ardex's Pegasus platform. Its open endpoints give the
workspace for the site's domain, the workspace's auctions, and each auction's
catalogue as JSON (name, birth date, sex, sire, dam, covering stallion, vendor,
lot status). A calendar sale is matched to an auction by name.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urlparse

import lxml.html

from salescatalogues.models import Lot, RawSale
from salescatalogues.sources.base import get_json, get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://inglis.com.au/calendar"
PEGASUS = "https://pegasus-prod01-backend.ardex.net.au/private"
DIGITAL_HOST = "www.inglisdigital.com"


def parse_calendar(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[tuple[str, str]] = set()
    for row in doc.cssselect("tr"):
        cells = row.cssselect("td")
        if len(cells) < 2:
            continue
        name = squash(cells[0].text_content())
        date_text = squash(cells[1].text_content())
        location = squash(cells[2].text_content()) if len(cells) > 2 else ""
        if not name or name.upper() == "SALE":
            continue
        key = (name.lower(), date_text)
        if key in seen:
            continue
        seen.add(key)
        start, end = parse_date_range(date_text, ref, dayfirst=True)

        link = row.cssselect("a")
        href = next((a.get("href") for a in link if a.get("href")), "") or URL
        online = "digital" in location.lower() or "inglisdigital" in href.lower()
        out.append(
            RawSale(
                house="Inglis",
                country="AUS",
                name=name,
                start_date=start,
                end_date=end,
                url=href,
                online=online,
                description=location,
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("Inglis fetch failed: %s", exc)
        return []
    return parse_calendar(html, ref=ref)


def _cell_value(cells, idx: int) -> str:
    if idx >= len(cells):
        return ""
    return (cells[idx].get("data-value") or squash(cells[idx].text_content())).strip()


def parse_lots(html: str) -> list[Lot]:
    """The ``?tab=index`` table has one ``tr#lot_<n>`` per lot, cells carrying a
    ``data-value`` in the order: lot, media, colour, sex, sire, dam, vendor,
    purchaser, sold, ts. Damsire isn't published on this view."""
    doc = lxml.html.fromstring(html)
    lots: list[Lot] = []
    for row in doc.cssselect('tr[id^="lot_"]'):
        cells = row.cssselect("td")
        if not cells:
            continue
        lot_no = _cell_value(cells, 0)
        if not lot_no:
            continue
        # Vendor: the visible link text is the clean name (data-value is a slug).
        vendor = squash(cells[6].text_content()) if len(cells) > 6 else ""
        lots.append(
            Lot(
                lot_no=lot_no,
                sex=_cell_value(cells, 3),
                colour=_cell_value(cells, 2),
                sire=_cell_value(cells, 4),
                dam=_cell_value(cells, 5),
                vendor=vendor,
            )
        )
    return lots


def _words(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", name.lower())) - {"sale", "inglis", "digital"}


def find_auction(auctions: list, raw: RawSale) -> dict | None:
    """The digital auction for a calendar sale: "November (Early) Online Sale"
    is "2026 November (Early) Online Sale". The year settles repeats."""
    want = _words(raw.name)
    year = str(raw.start_date.year) if raw.start_date else ""
    hits = [a for a in auctions or [] if isinstance(a, dict) and want and want <= _words(a.get("auctionName") or "")]
    if year:
        hits = [a for a in hits if year in (a.get("auctionName") or "")] or [
            a for a in hits if (a.get("catalogueReleaseDate") or "").startswith(year)]
    return hits[0] if len(hits) == 1 else None


def parse_digital(rows: list, slug: str, host: str = DIGITAL_HOST) -> list[Lot]:
    lots: list[Lot] = []
    for r in rows or []:
        if not isinstance(r, dict) or r.get("lotNumber") is None:
            continue
        born = str(r.get("animalBirthDate") or "")
        lots.append(
            Lot(
                lot_no=str(r["lotNumber"]),
                horse_name=(r.get("animalName") or "").strip(),
                sex=(r.get("animalGender") or r.get("animalGenderCode") or "").strip(),
                sire=(r.get("sireName") or "").strip(),
                dam=(r.get("damName") or "").strip(),
                vendor=(r.get("vendorName") or "").strip(),
                yob=int(born[:4]) if born[:4].isdigit() else None,
                covering_sire=(r.get("coveringStallionName") or "").strip(),
                # RS / SH are shares; B broodmare, RF racing filly or mare...
                lot_type=(r.get("categoryCode") or "").strip(),
                withdrawn=(r.get("lotStatus") or "") == "Withdrawn",
                url=f"https://{host}/catalogue/auction/{slug}/lot/{r['lotNumber']}" if slug else "",
            )
        )
    return lots


def fetch_digital_lots(raw: RawSale, session) -> list[Lot]:
    host = urlparse(raw.url).netloc or DIGITAL_HOST
    if "inglisdigital" not in host:
        host = DIGITAL_HOST
    host = host if host.startswith("www.") else f"www.{host}"
    try:
        ws = get_json(session, f"{PEGASUS}/guest/workspaceByDomain/{host}")["workspaceId"]
        auction = find_auction(get_json(session, f"{PEGASUS}/workspaces/{ws}/auctions/auction-list"), raw)
        if auction is None:
            return []
        rows = get_json(session, f"{PEGASUS}/workspaces/{ws}/auctions/{auction['auctionId']}/catalogue", timeout=60)
    except Exception as exc:  # noqa: BLE001
        log.warning("Inglis Digital lot fetch failed (%s): %s", raw.name, exc)
        return []
    return parse_digital(rows, auction.get("sanitisedAuctionName") or "", host)


def fetch_lots(raw: RawSale, session=None) -> list[Lot]:
    session = session or make_session()
    if raw.online or "inglisdigital" in raw.url:
        return fetch_digital_lots(raw, session)
    if "inglis.com.au/sale/" not in raw.url:
        return []
    sep = "&" if "?" in raw.url else "?"
    try:
        html = get_text(session, f"{raw.url}{sep}tab=index")
    except Exception as exc:  # noqa: BLE001
        log.warning("Inglis lot fetch failed (%s): %s", raw.url, exc)
        return []
    return parse_lots(html)
