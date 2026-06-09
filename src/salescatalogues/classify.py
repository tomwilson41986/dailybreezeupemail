"""Turn raw scraped sales into the enriched :class:`Catalogue` records the
digest renders.

Three jobs:

* :func:`is_excluded` — drop Jumps / National Hunt / store sales and any
  non-thoroughbred sale (Arabians, point-to-point, etc.), per the brief.
* :func:`classify_sale_type` — bucket a sale into Yearling / Foal-Weanling /
  Broodmare / HIT / Breeze Up / Mixed from its name (and any source hint).
* :func:`is_active` — flag a sale Active from ``ACTIVE_LEAD_DAYS`` before its
  first day through its last day.

All pure functions of their inputs so they test cleanly.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from salescatalogues.models import (
    COUNTRIES,
    DEFAULT_SALE_TYPE,
    Catalogue,
    Country,
    RawSale,
)

# How many days before a sale's first day it counts as "Active". The brief asks
# for "2 days before and during" the sale.
ACTIVE_LEAD_DAYS = 2


# ---------------------------------------------------------------------------
# Non-thoroughbred / National Hunt exclusion
# ---------------------------------------------------------------------------

# Matched against the lower-cased "name + description". Store sales are the NH
# pipeline (unraced jumps-bred stores), so they're excluded alongside explicit
# Jumps / National Hunt sales and non-thoroughbred breeds.
_EXCLUDE_PATTERNS = [
    r"national hunt",
    r"\bn\.?h\.?\b",
    r"\bjump(s|ing)?\b",
    r"steeple",
    r"\bstore(s)?\b",
    r"point[\s-]?to[\s-]?point",
    r"\bp2p\b",
    r"\baqps\b",
    r"arab",
    r"\bpony\b|\bponies\b",
    r"trotting|harness|standardbred",
    r"land rover",   # Goffs UK store sale brand
]
_EXCLUDE_RE = re.compile("|".join(_EXCLUDE_PATTERNS), re.IGNORECASE)

# Well-known National Hunt / store sales whose source listing carries no
# "store"/"NH" description for the keyword filter to catch. Matched as a
# substring on the sale name. Keep this list tight and house-specific.
_EXCLUDE_NAMES = (
    "derby sale",        # Tattersalls Ireland — premier NH store sale
    "land rover",        # Goffs UK store sale
    "arkle",             # Goffs Ireland store sale
    "sportsmans",        # Goffs UK NH/store sale
)

# A flat-bred sale name can legitimately contain a trip word that would
# otherwise trip the filter; none currently do, but keep this hook for
# whitelisting if a future sale name collides.
_EXCLUDE_OVERRIDE_RE = re.compile(r"(?!x)x")  # matches nothing


def is_excluded(raw: RawSale) -> bool:
    """True if this sale should be dropped (Jumps / NH / store / non-TB)."""
    hay = f"{raw.name} {raw.description} {raw.type_hint}".lower()
    if _EXCLUDE_OVERRIDE_RE.search(hay):
        return False
    if any(known in raw.name.lower() for known in _EXCLUDE_NAMES):
        return True
    return bool(_EXCLUDE_RE.search(hay))


# ---------------------------------------------------------------------------
# Sale type
# ---------------------------------------------------------------------------

# Ordered most-specific first: the first pattern that matches wins, so e.g.
# "Breeding Stock" resolves to Broodmare before the looser "stock" ideas, and
# "Horses of Racing Age" resolves to HIT before anything else.
_TYPE_RULES: list[tuple[str, str]] = [
    ("Breeze Up",        r"breeze[\s-]?up"),
    ("Breeze Up",        r"ready[\s-]?to[\s-]?run|\brtr\b"),
    ("HIT",              r"horses?\s+in\s+training|horses?\s+of\s+racing\s+age"),
    ("HIT",              r"\bhit\b|\bhra\b|horses?\s+of\s+all\s+ages|\bhoa[a]?\b"),
    ("HIT",              r"horses?\s+of\s+racing|racing\s+age"),
    ("Foal / Weanling",  r"weanling|\bfoal"),
    ("Broodmare",        r"broodmare|breeding\s+stock|\bmares?\b|in[\s-]?foal"),
    ("Yearling",         r"yearling"),
    ("Mixed",            r"\bmixed\b|breeding\s+&|breeding\s+and"),
]
_TYPE_RULES_RE = [(label, re.compile(pat, re.IGNORECASE)) for label, pat in _TYPE_RULES]


def classify_sale_type(raw: RawSale) -> str:
    """Bucket a sale into one of the normalised sale types."""
    if raw.type_hint:
        # A source may already know the type (e.g. a calendar category). Trust
        # it only when it names one of our buckets.
        for label in (
            "Breeze Up", "HIT", "Foal / Weanling", "Broodmare", "Yearling", "Mixed",
        ):
            if label.split(" ")[0].lower() in raw.type_hint.lower():
                return label
    hay = f"{raw.name} {raw.description}"
    for label, rx in _TYPE_RULES_RE:
        if rx.search(hay):
            return label
    return DEFAULT_SALE_TYPE


# ---------------------------------------------------------------------------
# Active / status
# ---------------------------------------------------------------------------

def is_active(raw: RawSale, today: date, *, lead_days: int = ACTIVE_LEAD_DAYS) -> bool:
    """True from ``lead_days`` before the first day through the last day."""
    start = raw.start_date
    if start is None:
        # No date but the source says it's live (rolling online auctions).
        return raw.status_hint.lower() in {"live", "bidding-open", "open"}
    end = raw.effective_end() or start
    return (start - timedelta(days=lead_days)) <= today <= end


def status_label(cat_is_new: bool, cat_is_active: bool, raw: RawSale) -> str:
    """Short human status for the row, combining flags with the source hint."""
    bits: list[str] = []
    if cat_is_active:
        bits.append("Active")
    if cat_is_new:
        bits.append("New")
    if not bits:
        hint = (raw.status_hint or "").replace("-", " ").strip().title()
        if hint:
            bits.append(hint)
        else:
            bits.append("Upcoming")
    return " · ".join(bits)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_catalogue(
    raw: RawSale,
    today: date,
    *,
    first_seen: date | None,
    lead_days: int = ACTIVE_LEAD_DAYS,
) -> Catalogue:
    """Enrich a single raw sale. ``first_seen`` is the date we first observed
    this catalogue (``None`` if never seen before — i.e. it's new today)."""
    sale_type = classify_sale_type(raw)
    active = is_active(raw, today, lead_days=lead_days)
    is_new = first_seen is None or first_seen == today
    cat = Catalogue(
        raw=raw,
        sale_type=sale_type,
        is_new=is_new,
        is_active=active,
        first_seen=first_seen,
    )
    cat.status_label = status_label(is_new, active, raw)
    return cat


def order_by_date(catalogues: list[Catalogue]) -> list[Catalogue]:
    """Order the digest by sale date, nearest first. Undated sales (rolling
    online auctions with no published date) sort to the end."""
    return sorted(
        catalogues,
        key=lambda c: (c.start_date or date.max, c.country, c.name.lower()),
    )


def group_by_country(
    catalogues: list[Catalogue],
) -> list[tuple[Country, list[Catalogue]]]:
    """Group catalogues into ordered (country, sorted-rows) sections.

    Active sales lead each section, then New, then by date. Sales for an unknown
    country code are bucketed last under a synthetic 'Other' country.
    """
    buckets: dict[str, list[Catalogue]] = {}
    for cat in catalogues:
        buckets.setdefault(cat.country, []).append(cat)

    def row_sort_key(c: Catalogue) -> tuple:
        return (
            0 if c.is_active else 1,
            0 if c.is_new else 1,
            c.start_date or date.max,
            c.name.lower(),
        )

    out: list[tuple[Country, list[Catalogue]]] = []
    known = sorted(
        (code for code in buckets if code in COUNTRIES),
        key=lambda code: COUNTRIES[code].sort,
    )
    for code in known:
        rows = sorted(buckets[code], key=row_sort_key)
        out.append((COUNTRIES[code], rows))
    # Any unknown codes (shouldn't happen, but never silently drop a sale).
    unknown = [code for code in buckets if code not in COUNTRIES]
    if unknown:
        other = Country("OTHER", "Other", "\U0001F30D", 99)
        rows = sorted(
            (c for code in unknown for c in buckets[code]), key=row_sort_key
        )
        out.append((other, rows))
    return out
