"""Magic Millions Online — the "MM Digital" timed online auctions, published on
a separate platform from the main (physical) sales calendar. The
``/sales-calendar`` page lists each digital sale as an ``.upcoming-sale`` block
with a day range, month, year, and an "Add to Calendar" link whose
``dates=YYYYMMDD.../YYYYMMDD...`` query gives unambiguous machine dates.

Lots: the platform is BidJS (Bidlogix). Its open ``v1/home`` lists the
auctions taking bids or lotting, each with its own dates; ``v3/auctions/<uuid>``
gives every listing, the horse in a URL-encoded JSON ``description`` (name,
sire, dam, damsire, sex, date of birth, colour, covering stallion, vendor).
An auction is matched to a calendar sale by its start date.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import date
from urllib.parse import unquote

import lxml.html

from salescatalogues.models import Lot, RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://magicmillions.digital/sales-calendar/"
BIDJS = "https://lancing.ap-southeast-2.bidjs.com/auction-007/api"
BIDJS_HEADERS = {"x-forwarded-client-id": "magicmillions", "Accept": "application/json"}
LOT_URL = "https://magicmillions.digital/current-auctions/#!/auctions/{auction}/listings/{item}"
# Machine dates Google-Calendar export embeds in each block's link.
_CAL_DATES_RE = re.compile(r"dates=(\d{8})T[\dZ]*/(\d{8})T[\dZ]*")


def _iso(stamp: str) -> date | None:
    try:
        return date(int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8]))
    except (ValueError, IndexError):
        return None


def parse_calendar(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[str] = set()
    for block in doc.cssselect(".upcoming-sale"):
        name_el = block.cssselect(".sale-name")
        name = squash(name_el[0].text_content()) if name_el else ""
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())

        # Prefer the exact dates from the calendar-export link; fall back to the
        # human "12-17 / JUN / 2026" cells if it's missing.
        start = end = None
        cal = block.cssselect("a.add-to-calendar")
        href = cal[0].get("href") if cal else ""
        m = _CAL_DATES_RE.search(href or "")
        if m:
            start, end = _iso(m.group(1)), _iso(m.group(2))
        if start is None:
            parts = [
                squash(block.cssselect(sel)[0].text_content())
                for sel in (".sale-date", ".sale-month", ".sale-year")
                if block.cssselect(sel)
            ]
            start, end = parse_date_range(" ".join(parts), ref, dayfirst=True)

        out.append(
            RawSale(
                house="Magic Millions",
                country="AUS",
                name=name,
                start_date=start,
                end_date=end if end != start else None,
                url=URL,
                online=True,
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("Magic Millions Online fetch failed: %s", exc)
        return []
    return parse_calendar(html, ref=ref)


def decode(desc: str) -> dict:
    """BidJS keeps the horse as JSON with its braces URL-encoded and its quotes
    as HTML entities: ``%7B&quot;sire&quot;:&quot;Wild Ruler (AUS)&quot;...%7D``."""
    try:
        data = json.loads(unquote(desc or "").replace("&quot;", '"'))
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: html.unescape(v) if isinstance(v, str) else v for k, v in data.items()}


def auctions(home: dict) -> list[dict]:
    """The open auctions on the BidJS home model: uuid, title, start date."""
    up = ((home or {}).get("models") or {}).get("HomePageModel", {}).get("upcomingModel") or {}
    out = []
    for a in (up.get("upcomingAuctions") or []) + (up.get("upcomingFeaturedAuctions") or []):
        meta = decode(a.get("description") or "")
        start = (meta.get("startDate") or "")[:10]
        out.append({"uuid": a.get("auctionUuid"), "id": a.get("auctionId"), "title": a.get("title") or "",
                    "start": date.fromisoformat(start) if start else None})
    return out


def parse_listings(body: dict) -> list[Lot]:
    info = (body or {}).get("information") or {}
    auction = (info.get("auction") or {}).get("uuid") or ""
    listings = info.get("listings") or {}
    rows = listings.values() if isinstance(listings, dict) else listings
    lots: list[Lot] = []
    for item in sorted(rows, key=lambda x: x.get("auctionIndex") or 0):
        d = decode(item.get("description") or "")
        if not d.get("sire") and not d.get("dam"):
            continue                    # "Dummy Lot" placeholders
        dob = str(d.get("dob") or "")
        name = (d.get("name") or "").strip()
        lots.append(
            Lot(
                lot_no=str(item.get("auctionIndex") or ""),
                horse_name="" if name.lower() == "unnamed" else name,
                sex=(d.get("sex") or "").strip(),
                colour=(d.get("colour") or "").strip(),
                sire=(d.get("sire") or "").strip(),
                dam=(d.get("dam") or "").strip(),
                dam_sire=(d.get("damSire") or "").strip(),
                vendor=(d.get("vendor") or "").strip(),
                yob=int(dob[:4]) if dob[:4].isdigit() else None,
                covering_sire=(d.get("coveringStallion") or "").strip(),
                # SH a part-share, SB a stallion breeding right; B broodmare, RF racing filly...
                lot_type=(d.get("category") or "").strip(),
                url=LOT_URL.format(auction=auction, item=item.get("uuid") or ""),
            )
        )
    return lots


def fetch_lots(raw: RawSale, session=None) -> list[Lot]:
    """The sale's lots once its auction is open on BidJS (lotting or bidding);
    [] before then."""
    session = session or make_session()
    try:
        home = session.get(f"{BIDJS}/v1/home", headers=BIDJS_HEADERS, timeout=30).json()
        match = next((a for a in auctions(home) if a["start"] and a["start"] == raw.start_date), None)
        if match is None:
            return []
        body = session.get(f"{BIDJS}/v3/auctions/{match['uuid']}", headers=BIDJS_HEADERS, timeout=60).json()
    except Exception as exc:  # noqa: BLE001
        log.warning("Magic Millions Online lot fetch failed (%s): %s", raw.name, exc)
        return []
    return parse_listings(body)
