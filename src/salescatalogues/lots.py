"""Orchestrates per-sale lot fetching for the CSV.

For each in-scope catalogue we look up the source that produced it and, if that
source implements ``fetch_lots``, pull the lots for its published catalogue.
Failures and not-yet-published catalogues yield an empty list, so the CSV simply
falls back to a sale-level summary row for that sale.
"""
from __future__ import annotations

import logging

from salescatalogues.models import Catalogue, Lot
from salescatalogues.sources.registry import SOURCES_BY_KEY

log = logging.getLogger(__name__)


def collect_lots(
    catalogues: list[Catalogue], session
) -> tuple[dict[str, list[Lot]], dict[str, int]]:
    """Return ``(lots_by_catalogue_id, per_source_lot_counts)``.

    Each source's lot fetcher is isolated so one failing catalogue can't sink
    the run. Only catalogues whose source implements ``fetch_lots`` are tried.
    """
    lots_by_id: dict[str, list[Lot]] = {}
    counts: dict[str, int] = {}
    for cat in catalogues:
        src = SOURCES_BY_KEY.get(cat.raw.source_key)
        if src is None or src.fetch_lots is None:
            continue
        try:
            lots = src.fetch_lots(cat.raw, session) or []
        except Exception as exc:  # noqa: BLE001
            log.warning("lot fetch failed for %s (%s): %s", cat.name, src.key, exc)
            continue
        if lots:
            lots_by_id[cat.catalogue_id] = lots
            counts[src.key] = counts.get(src.key, 0) + len(lots)
            log.info("  %s: %d lot(s)", cat.name, len(lots))
    return lots_by_id, counts
