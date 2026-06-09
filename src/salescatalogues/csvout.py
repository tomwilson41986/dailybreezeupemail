"""Render the digest's catalogues to CSV bytes for the email attachment."""
from __future__ import annotations

import csv
import io

from salescatalogues.models import COUNTRIES, Catalogue

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
    "URL",
]


def _country_name(code: str) -> str:
    c = COUNTRIES.get(code)
    return c.name if c else code


def to_csv(catalogues: list[Catalogue]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADER)
    for cat in catalogues:
        writer.writerow(
            [
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
        )
    return buf.getvalue()
