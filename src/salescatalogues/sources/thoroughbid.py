"""ThoroughBid (UK) — an online-only auction house running a monthly timed
bloodstock sale plus the occasional bespoke/dispersal sale.

``/collections-bloodstock`` is the bloodstock calendar (the sister
``/collections-sport`` page is sport horses, which we don't want). Each sale is
a ``.card-collection`` block carrying the sale name, a machine-ish bidding-start
stamp ("Jul 30, 2026, 9:00 AM"), a lot count, and — once the catalogue is
published — a ``/collection/{id}`` link to the lot table. Sales still being
entered render the same card with a "Coming soon" button and no link.

Note we deliberately don't feed the card's marketing blurb into
``RawSale.description``: it's boilerplate that names the Point2Rules bonus and
NH store lots on *every* sale, which the non-thoroughbred filter would read as
grounds to drop the sale. These are mixed sales (horses in training, flat
youngstock and NH stores in one catalogue), so the name alone is the honest
signal for classification.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

import lxml.html

from salescatalogues.models import Lot, RawSale
from salescatalogues.sources.base import (
    get_text,
    make_session,
    parse_date_range,
    squash,
)

log = logging.getLogger(__name__)

BASE = "https://www.thoroughbid.co.uk"
URL = f"{BASE}/collections-bloodstock"

# "Bidding starts: Jul 30, 2026, 9:00 AM" — the unambiguous stamp on each card.
_STAMP_RE = re.compile(r"([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})")
# Collection id in the card's link, e.g. /collection/76.
_COLLECTION_RE = re.compile(r"/collection/(\d+)")
# Unnamed youngstock are listed as "'24 Blue Point (IRE) ex Golden Pearl (GB)".
_UNNAMED_RE = re.compile(r"^['’]\d{2}\b")
# The "(Sire x dam)" pedigree line under the horse name.
_PEDIGREE_SPLIT_RE = re.compile(r"\s+x\s+", re.IGNORECASE)


def _pretty(name: str) -> str:
    """ThoroughBid shouts its sale names ("JULY 26 SALE"). Title-case those so
    they sit alongside the other houses' sales; leave mixed-case names alone."""
    return name.title() if name and not any(c.islower() for c in name) else name


def _stamp_date(text: str, ref: date) -> date | None:
    m = _STAMP_RE.search(text or "")
    if m:
        month, day, year = m.group(1)[:3], m.group(2), m.group(3)
        try:
            return datetime.strptime(f"{month} {day} {year}", "%b %d %Y").date()
        except ValueError:
            pass
    # Fall back to the tolerant parser if the stamp format ever changes. The
    # sale names carry a two-digit year ("JULY 26 SALE"), so never parse those.
    start, _ = parse_date_range(text, ref, dayfirst=False)
    return start


def parse_collections(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[str] = set()
    for card in doc.cssselect(".card-collection"):
        title = card.cssselect(".card-title")
        name = _pretty(squash(title[0].text_content())) if title else ""
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())

        time_el = card.cssselect("p.time")
        start = _stamp_date(squash(time_el[0].text_content()), ref) if time_el else None

        # The catalogue link only appears once the lots are published; without
        # it the sale is still taking entries.
        hrefs = (a.get("href") or "" for a in card.cssselect("a"))
        href = next((h for h in hrefs if _COLLECTION_RE.search(h)), "")
        ref_m = _COLLECTION_RE.search(href or "")
        out.append(
            RawSale(
                house="ThoroughBid",
                country="UK",
                name=name,
                start_date=start,
                end_date=None,  # timed sales all finish on the bidding day
                url=f"{BASE}{href}" if href.startswith("/") else (href or URL),
                online=True,
                status_hint="catalogue" if ref_m else "upcoming",
                catalogue_ref=ref_m.group(1) if ref_m else "",
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("ThoroughBid fetch failed: %s", exc)
        return []
    return parse_collections(html, ref=ref)


def _cell(cells: dict, header: str) -> str:
    td = cells.get(header)
    return squash(td.text_content()) if td is not None else ""


def parse_lots(html: str) -> list[Lot]:
    """Parse the lot table on a ``/collection/{id}`` page.

    Every row is rendered twice — once for mobile, once for desktop — so we read
    only the ``scope="row-desktop"`` cells, keyed by their ``data-header`` where
    the site provides one. Colour and damsire aren't published.
    """
    doc = lxml.html.fromstring(html)
    lots: list[Lot] = []
    for row in doc.cssselect("table.table-collectie tr"):
        tds = row.cssselect('td[scope="row-desktop"]')
        if len(tds) < 4:
            continue
        lot_no = squash(tds[0].text_content())
        if not lot_no:
            continue
        cells = {td.get("data-header"): td for td in tds if td.get("data-header")}

        name_td = next((td for td in tds if td.cssselect("span.font-weight-bold")), None)
        name = sire = dam = ""
        if name_td is not None:
            strong = name_td.cssselect("span.font-weight-bold")[0]
            name = squash(strong.text_content())
            # The "(Sire x dam)" line sits after a <br>, so it's the tail of the
            # name span's following siblings rather than of the span itself.
            pedigree = squash(
                "".join([strong.tail or ""] + [el.tail or "" for el in strong.itersiblings()])
            )
            if pedigree:
                parts = _PEDIGREE_SPLIT_RE.split(pedigree, maxsplit=1)
                sire = parts[0].strip()
                dam = parts[1].strip() if len(parts) > 1 else ""
        if _UNNAMED_RE.match(name):
            name = ""  # "'24 Sire ex Dam" is a placeholder, not a horse name

        # The desktop sex cell shows the code ("C"); its tooltip spells it out.
        sex_td = cells.get("Sex")
        sex = squash(sex_td.get("title") or "") if sex_td is not None else ""
        if not sex:
            sex = _cell(cells, "Sex")

        lots.append(
            Lot(
                lot_no=lot_no,
                horse_name=name,
                sex=sex,
                sire=sire,
                dam=dam,
                vendor=_cell(cells, "Consignor"),
            )
        )
    return lots


def fetch_lots(raw: RawSale, session=None) -> list[Lot]:
    """Fetch the sale's lot table. Returns [] until the catalogue is published
    (no ``/collection/{id}`` link on the calendar card)."""
    if not raw.catalogue_ref:
        return []
    session = session or make_session()
    try:
        html = get_text(session, f"{BASE}/collection/{raw.catalogue_ref}")
    except Exception as exc:  # noqa: BLE001
        log.warning("ThoroughBid lot fetch failed (%s): %s", raw.catalogue_ref, exc)
        return []
    return parse_lots(html)
