"""Render the digest's catalogues to CSV bytes for the email attachment.

The CSV is lot-level: one row per catalogued lot (horse), repeating the sale
columns. Sales whose catalogue isn't published yet (so we can't fetch lots)
contribute a single summary row with the lot columns left blank, so every sale
still appears.
"""
from __future__ import annotations

import csv
import io

from salescatalogues.models import COUNTRIES, Catalogue, Lot

HEADER = [
    "Country",
    "Sale House",
    "Sale Name",
    "Sale Type",
    "Start Date",
    "End Date",
    "Online",
    "New",
    "Active",
    "Status",
    "Sale URL",
    "Lot No",
    "Horse Name",
    "Sex",
    "Colour",
    "Sire",
    "Dam",
    "Dam Sire",
    "Vendor",
]


def _country_name(code: str) -> str:
    c = COUNTRIES.get(code)
    return c.name if c else code


def _sale_cols(cat: Catalogue) -> list[str]:
    return [
        _country_name(cat.country),
        cat.house,
        cat.name,
        cat.sale_type,
        cat.start_date.isoformat() if cat.start_date else "",
        cat.end_date.isoformat() if cat.end_date else "",
        "Yes" if cat.online else "No",
        "Yes" if cat.is_new else "No",
        "Yes" if cat.is_active else "No",
        cat.status_label,
        cat.url,
    ]


_EMPTY_LOT_COLS = [""] * 8


def to_csv(
    catalogues: list[Catalogue],
    lots_by_id: dict[str, list[Lot]] | None = None,
) -> str:
    """One row per lot. ``lots_by_id`` maps ``catalogue_id`` to its lots; a
    catalogue with no lots gets a single summary row (blank lot columns)."""
    lots_by_id = lots_by_id or {}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADER)
    for cat in catalogues:
        sale_cols = _sale_cols(cat)
        lots = lots_by_id.get(cat.catalogue_id) or []
        if not lots:
            writer.writerow(sale_cols + _EMPTY_LOT_COLS)
            continue
        for lot in lots:
            writer.writerow(
                sale_cols
                + [
                    lot.lot_no,
                    lot.horse_name,
                    lot.sex,
                    lot.colour,
                    lot.sire,
                    lot.dam,
                    lot.dam_sire,
                    lot.vendor,
                ]
            )
    return buf.getvalue()
