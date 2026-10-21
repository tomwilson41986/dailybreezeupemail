"""Horse names as keys: "Quiet Giant", "QUIET GIANT (USA)" and "Quiet Giant (US)"
all become ``QUIETGIANT``. Country suffixes are dropped for the key and kept
separately, since the catalogues print them inconsistently."""

from __future__ import annotations

import re
import unicodedata

_SUFFIX_RE = re.compile(r"\s*\(([A-Za-z]{2,4})\)\s*$")
# the catalogues' spellings of a country, to the worldwide file's codes
_COUNTRY = {
    "US": "USA",
    "GB": "GB",
    "IRE": "IRE",
    "IR": "IRE",
    "FR": "FR",
    "FRA": "FR",
    "GER": "GER",
    "AUS": "AUS",
    "NZ": "NZ",
    "JPN": "JPN",
    "JAP": "JPN",
    "ARG": "ARG",
    "BRZ": "BRZ",
    "CAN": "CAN",
    "CHI": "CHI",
    "SAF": "SAF",
    "ITY": "ITY",
    "SWE": "SWE",
    "URU": "URU",
    "PER": "PER",
}


def fold(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)
    )


def split_suffix(name: str) -> tuple[str, str]:
    """ "Quiet Giant (USA)" -> ("Quiet Giant", "USA")."""
    m = _SUFFIX_RE.search(name or "")
    if not m:
        return (name or "").strip(), ""
    code = m.group(1).upper()
    return (name[: m.start()].strip(), _COUNTRY.get(code, code))


def key(name: str) -> str:
    base, _ = split_suffix(name)
    return re.sub(r"[^A-Z0-9]", "", fold(base).upper())


def display(name: str) -> str:
    """ "QUIET GIANT" -> "Quiet Giant"; mixed case is left alone."""
    base = (name or "").strip()
    if base.isupper():
        base = re.sub(r"(^|[\s(-])([a-z])", lambda m: m.group(1) + m.group(2).upper(), base.lower())
        base = re.sub(r"\b(O|D|L)'([a-z])", lambda m: f"{m.group(1)}'{m.group(2).upper()}", base)
        base = re.sub(r"\(([a-z]{2,4})\)", lambda m: f"({m.group(1).upper()})", base)
    return base
