"""Horse-name matching key for the watchlist join.

The watchlist sheet lists names with a country suffix — ``GOLDEN NARRATIVE
(IRE)``, ``KING'S FURY (GB)`` — but Racing Post's racecard/result runner names
don't carry it. So the match key strips a trailing ``(XXX)`` country code before
applying the same lowercase/alphanumeric normalisation the breeze-up matcher uses.

This keeps both sides aligned: ``horse_key("GOLDEN NARRATIVE (IRE)")`` equals
``normalize_name("Golden Narrative")``, which is what RP's (suffix-less) names
reduce to — so the racecards scraper's internal ``normalize_name`` lookups hit
our ``target_names`` keys.
"""
from __future__ import annotations

import re

from dailybreezeup.racing.rp_racecards import normalize_name

# A trailing country code in parens, e.g. " (IRE)", "(GB)", "(USA)". RP uses
# 2-3 letter ISO-ish codes; we only strip when it's at the very end.
_COUNTRY_SUFFIX_RE = re.compile(r"\s*\([A-Za-z]{2,3}\)\s*$")


def strip_country(name: str | None) -> str:
    return _COUNTRY_SUFFIX_RE.sub("", name or "").strip()


def horse_key(name: str | None) -> str:
    """Normalised match key: country suffix stripped, then alphanumerics only."""
    return normalize_name(strip_country(name))
