"""Gavelhouse Plus (New Zealand) — a rolling online thoroughbred auction.

The browse UI is a SPA, but ``/api/currentcatalogue`` returns clean JSON for the
live auction (name, ``auctionStarts``/``auctionEnds``), which is all we need.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from salescatalogues.models import RawSale
from salescatalogues.sources.base import get_text, make_session

log = logging.getLogger(__name__)

API_URL = "https://gavelhouse.co.nz/api/currentcatalogue"
BROWSE_URL = "https://gavelhouse.co.nz/browse"


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
