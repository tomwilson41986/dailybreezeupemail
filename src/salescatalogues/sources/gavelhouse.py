"""Gavelhouse Plus (New Zealand) — a rolling online thoroughbred auction.

The browse UI is a SPA, but ``/api/currentcatalogue`` returns clean JSON for the
live auction (name, ``auctionStarts``/``auctionEnds``), which is all we need.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from salescatalogues.models import Lot, RawSale
from salescatalogues.sources.base import get_json, get_text, make_session

log = logging.getLogger(__name__)

API_URL = "https://gavelhouse.co.nz/api/currentcatalogue"
LOTS_API = "https://gavelhouse.co.nz/api/lots?catalogue={cat_id}&detail=2"
BROWSE_URL = "https://gavelhouse.co.nz/browse"

# Gavelhouse encodes sex/colour as integer enums (decoded from the site config).
_SEX = {2: "Colt", 3: "Filly", 4: "Gelding", 5: "Mare", 6: "Horse"}
_COLOUR = {3: "Bay", 4: "Bay or Grey", 6: "Brown", 10: "Chestnut"}


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_catalogue(body: str) -> list[RawSale]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    name = (data.get("name") or "").strip()
    if not name:
        return []
    start = _as_date(data.get("auctionStarts") or data.get("launches"))
    end = _as_date(data.get("auctionEnds"))
    return [
        RawSale(
            house="Gavelhouse",
            country="NZ",
            name=name,
            start_date=start,
            end_date=end,
            url=BROWSE_URL,
            online=True,
            status_hint="live" if (data.get("status") == 2) else "",
            catalogue_ref=str(data.get("id") or ""),
        )
    ]


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    try:
        body = get_text(session, API_URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("Gavelhouse fetch failed: %s", exc)
        return []
    return parse_catalogue(body)


def parse_lots(rows: list) -> list[Lot]:
    lots: list[Lot] = []
    for lot in rows or []:
        if not isinstance(lot, dict):
            continue
        name = (lot.get("horseName") or "").strip()
        if name.lower() == "unnamed":
            name = ""
        lots.append(
            Lot(
                lot_no=str(lot.get("lotNumber") or "").strip(),
                horse_name=name,
                sex=_SEX.get(lot.get("sex"), ""),
                colour=_COLOUR.get(lot.get("colour"), ""),
                sire=(lot.get("sireName") or "").strip(),
                dam=(lot.get("damName") or "").strip(),
                dam_sire=(lot.get("damSireName") or "").strip(),
                vendor=(lot.get("winnerName") or lot.get("userName") or "").strip(),
            )
        )
    return lots


def fetch_lots(raw: RawSale, session=None) -> list[Lot]:
    if not raw.catalogue_ref:
        return []
    session = session or make_session()
    try:
        rows = get_json(session, LOTS_API.format(cat_id=raw.catalogue_ref))
    except Exception as exc:  # noqa: BLE001
        log.warning("Gavelhouse lot fetch failed (cat %s): %s", raw.catalogue_ref, exc)
        return []
    return parse_lots(rows) if isinstance(rows, list) else []
