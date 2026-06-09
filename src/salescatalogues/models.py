"""Core data types for the Daily Sales Catalogues digest.

Two records flow through the pipeline:

* :class:`RawSale` is what each source adapter (``sources/*.py``) returns — a
  thin scrape of an auction house's calendar entry, with as much as the page
  exposes (name, date span, url, whether it's an online sale, plus a free-text
  ``status_hint``/``description`` the classifier can lean on).
* :class:`Catalogue` is the enriched record the email and CSV render — a
  ``RawSale`` plus a normalised :data:`sale_type`, the ``is_new`` / ``is_active``
  flags, and a stable ``catalogue_id`` used to remember which catalogues we've
  already seen.

Both are intentionally plain dataclasses so the pure parsers stay trivially
testable against captured fixtures.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

# ---------------------------------------------------------------------------
# Country metadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Country:
    code: str        # internal key, e.g. "UK", "IRE"
    name: str        # display name, e.g. "United Kingdom"
    flag: str        # emoji flag for the section heading
    sort: int        # display order across the email


# Display order follows the brief: UK, Ireland, France, Germany, US,
# Australia, New Zealand.
COUNTRIES: dict[str, Country] = {
    "UK":  Country("UK",  "United Kingdom", "\U0001F1EC\U0001F1E7", 1),  # 🇬🇧
    "IRE": Country("IRE", "Ireland",        "\U0001F1EE\U0001F1EA", 2),  # 🇮🇪
    "FR":  Country("FR",  "France",         "\U0001F1EB\U0001F1F7", 3),  # 🇫🇷
    "DE":  Country("DE",  "Germany",        "\U0001F1E9\U0001F1EA", 4),  # 🇩🇪
    "US":  Country("US",  "United States",  "\U0001F1FA\U0001F1F8", 5),  # 🇺🇸
    "AUS": Country("AUS", "Australia",      "\U0001F1E6\U0001F1FA", 6),  # 🇦🇺
    "NZ":  Country("NZ",  "New Zealand",    "\U0001F1F3\U0001F1FF", 7),  # 🇳🇿
}


# ---------------------------------------------------------------------------
# Sale types
# ---------------------------------------------------------------------------

# Normalised sale-type buckets and the icon shown beside each. "Breeze Up"
# covers the European breeze-up and the antipodean "Ready to Run" 2yo sales;
# "HIT" covers Horses in Training / Horses of Racing Age. See
# ``classify.classify_sale_type``.
SALE_TYPE_ICONS: dict[str, str] = {
    "Yearling":         "\U0001F40E",  # 🐎
    "Foal / Weanling":  "\U0001F37C",  # 🍼
    "Broodmare":        "♀️",  # ♀️
    "HIT":              "\U0001F3C7",  # 🏇
    "Breeze Up":        "⏱️",  # ⏱️
    "Mixed":            "\U0001F500",  # 🔀
}
DEFAULT_SALE_TYPE = "Mixed"


def _slug(text: str) -> str:
    """ASCII, lower-case, alnum-only key for stable identity/dedup."""
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")


@dataclass
class RawSale:
    """A single calendar entry as scraped from one auction house."""

    house: str                       # e.g. "Tattersalls", "Goffs"
    country: str                     # COUNTRIES key, e.g. "UK"
    name: str                        # sale name as published
    start_date: date | None          # first day of the sale, if known
    end_date: date | None            # last day; None for single-day sales
    url: str                         # link to the sale / catalogue
    online: bool = False             # True for online / digital sales
    description: str = ""            # free text used for non-TB filtering
    status_hint: str = ""           # source-side status, e.g. "catalogue", "live"
    type_hint: str = ""             # source-side sale-type hint, if any
    source_key: str = ""            # registry key of the source that produced it
    catalogue_ref: str = ""         # source-internal id used to fetch the lots

    def effective_end(self) -> date | None:
        return self.end_date or self.start_date


@dataclass
class Lot:
    """One catalogued lot (horse) within a sale. Populated by a source's
    ``fetch_lots`` once the sale's catalogue is published; sales without a
    published catalogue have no lots and render as a single summary CSV row."""

    lot_no: str                      # "123", "123A", or a house hip number
    horse_name: str = ""            # "" when the lot is unnamed
    sex: str = ""                   # colt/filly/gelding/mare or C/F/G/M
    colour: str = ""                # bay, chestnut, etc. (when published)
    sire: str = ""
    dam: str = ""
    dam_sire: str = ""              # sire of dam (damsire)
    vendor: str = ""                # consignor / vendor / seller


@dataclass
class Catalogue:
    """A ``RawSale`` enriched with sale type and the New / Active flags."""

    raw: RawSale
    sale_type: str
    is_new: bool = False
    is_active: bool = False
    status_label: str = ""           # human-friendly status for display
    first_seen: date | None = None   # when we first observed this catalogue

    # Convenience pass-throughs ------------------------------------------------
    @property
    def house(self) -> str:
        return self.raw.house

    @property
    def country(self) -> str:
        return self.raw.country

    @property
    def name(self) -> str:
        return self.raw.name

    @property
    def start_date(self) -> date | None:
        return self.raw.start_date

    @property
    def end_date(self) -> date | None:
        return self.raw.end_date

    @property
    def url(self) -> str:
        return self.raw.url

    @property
    def online(self) -> bool:
        return self.raw.online

    @property
    def catalogue_id(self) -> str:
        """Stable identity for new-detection / dedup.

        Keyed on house + name + start month so the same sale tracks across days
        even if a source nudges the exact start day, but two genuinely different
        sales (e.g. October Book 1 vs Book 2) stay distinct.
        """
        start = self.raw.start_date
        month_key = f"{start.year}-{start.month:02d}" if start else "nd"
        return f"{_slug(self.raw.house)}|{_slug(self.raw.name)}|{month_key}"

    @property
    def type_icon(self) -> str:
        return SALE_TYPE_ICONS.get(self.sale_type, SALE_TYPE_ICONS[DEFAULT_SALE_TYPE])

    def date_label(self) -> str:
        """Human date span, e.g. "6 – 8 Oct 2026" or "2 Sep 2026"."""
        start, end = self.raw.start_date, self.raw.end_date
        if start is None:
            return "Date TBC"
        if end is None or end == start:
            return start.strftime("%-d %b %Y")
        if (start.month, start.year) == (end.month, end.year):
            return f"{start.strftime('%-d')} – {end.strftime('%-d %b %Y')}"
        if start.year == end.year:
            return f"{start.strftime('%-d %b')} – {end.strftime('%-d %b %Y')}"
        return f"{start.strftime('%-d %b %Y')} – {end.strftime('%-d %b %Y')}"
