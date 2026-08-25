"""Header-driven table extraction.

Both Racing Post and Equibase render their owner pages as ordinary HTML tables
with stable *column headings* but volatile class names.  Reading the headings
instead of the markup keeps the adapters working across redesigns.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence

from bs4 import BeautifulSoup, Tag

from ..normalise import collapse_space


class Column:
    """A logical column and the headings that identify it."""

    def __init__(self, key: str, *aliases: str, required: bool = False) -> None:
        self.key = key
        self.aliases = tuple(alias.lower() for alias in aliases)
        self.required = required

    def matches(self, heading: str) -> bool:
        heading = heading.lower()
        return any(alias == heading or alias in heading for alias in self.aliases)


def find_tables(soup: BeautifulSoup, columns: Sequence[Column]) -> Iterator[tuple[Tag, dict]]:
    """Yield every table whose headings satisfy all required columns."""
    for table in soup.find_all("table"):
        mapping = map_columns(table, columns)
        if mapping is None:
            continue
        yield table, mapping


def map_columns(table: Tag, columns: Sequence[Column]) -> dict[str, int] | None:
    headings = _headings(table)
    if not headings:
        return None
    mapping: dict[str, int] = {}
    for column in columns:
        for index, heading in enumerate(headings):
            if column.matches(heading):
                mapping.setdefault(column.key, index)
                break
    if any(column.required and column.key not in mapping for column in columns):
        return None
    return mapping


def rows(table: Tag, mapping: dict[str, int]) -> Iterator[dict[str, str]]:
    """Yield each body row as ``{column key: cell text}``.

    Cells carried down from a previous row (a blank date under a date heading)
    are filled forward, which is how both feeds lay out grouped rows.
    """
    carried: dict[str, str] = {}
    body = table.find("tbody") or table
    for row in body.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if not cells or row.find("th") and not row.find("td"):
            continue
        record: dict[str, str] = {}
        for key, index in mapping.items():
            value = collapse_space(cells[index].get_text(" ")) if index < len(cells) else ""
            if value:
                carried[key] = value
            record[key] = value or carried.get(key, "")
        if any(record.values()):
            yield record


def _headings(table: Tag) -> list[str]:
    head = table.find("thead")
    cells: Iterable[Tag]
    if head is not None:
        cells = head.find_all(["th", "td"])
    else:
        first = table.find("tr")
        cells = first.find_all(["th", "td"]) if first is not None else []
    return [collapse_space(cell.get_text(" ")) for cell in cells]


def split_pedigree(value: str) -> tuple[str, str]:
    """Split ``Kingman - Ventoux`` / ``Kingman (Ventoux)`` into sire and dam."""
    value = collapse_space(value)
    if not value:
        return "", ""
    match = re.match(r"^(.*?)\s*[-–—]\s*(.*)$", value)
    if match:
        dam = re.sub(r"\(.*?\)$", "", match.group(2))
        return collapse_space(match.group(1)), collapse_space(dam)
    match = re.match(r"^(.*?)\s*\((.*?)\)$", value)
    if match:
        return collapse_space(match.group(1)), collapse_space(match.group(2))
    return value, ""
