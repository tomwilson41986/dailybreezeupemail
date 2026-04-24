import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Optional

_COUNTRY_SUFFIX = re.compile(
    r"\s*\((?:IRE|GB|FR|USA|GER|ITY|JPN|AUS|NZ|BRZ|ARG|CAN|SAF|UAE|TUR|"
    r"POL|HUN|CZE|SWE|NOR|DEN|FIN|CHI|URU|PER|RSA|HOL|BEL|SPA|SUI|SLO)\)\s*$",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^A-Z0-9 ]+")
_WS = re.compile(r"\s+")


def normalize_name(raw: str | None) -> str:
    if not raw:
        return ""
    decomposed = unicodedata.normalize("NFKD", raw)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    upper = ascii_only.upper()
    no_country = _COUNTRY_SUFFIX.sub("", upper)
    cleaned = _NON_ALNUM.sub(" ", no_country)
    return _WS.sub(" ", cleaned).strip()


def horse_key(normalized_name: str, year_foaled: Optional[int]) -> str:
    return f"{normalized_name}|{year_foaled if year_foaled is not None else '?'}"


@dataclass(frozen=True)
class MatchedHorse:
    sale_id: str
    sale_name: str
    vendor: str
    country: str
    lot: str | None
    horse_name: str
    year_foaled: int | None
    sire: str | None
    dam: str | None
    price: int | None
    currency: str | None
    withdrawn: bool
    source_url: str | None
    # User-provided analytics (from the Google Sheet)
    ot_diff_m: str | None = None
    ot_rank: str | None = None
    sl_1f: str | None = None
    sl_go: str | None = None
    breeze_rating: str | None = None
    precocity_rating: str | None = None
    sheet_row_url: str | None = None


@dataclass(frozen=True)
class RunnerToMatch:
    name: str
    age: int | None
    race_year: int
    sire: str | None = None
    dam: str | None = None


def _row_to_match(row: sqlite3.Row) -> MatchedHorse:
    def _opt(key: str) -> str | None:
        try:
            return row[key]
        except (IndexError, KeyError):
            return None

    return MatchedHorse(
        sale_id=row["sale_id"],
        sale_name=row["sale_name"],
        vendor=row["vendor"],
        country=row["country"],
        lot=row["lot"],
        horse_name=row["horse_name"],
        year_foaled=row["year_foaled"],
        sire=row["sire"],
        dam=row["dam"],
        price=row["price"],
        currency=row["currency"],
        withdrawn=bool(row["withdrawn"]),
        source_url=row["source_url"],
        ot_diff_m=_opt("ot_diff_m"),
        ot_rank=_opt("ot_rank"),
        sl_1f=_opt("sl_1f"),
        sl_go=_opt("sl_go"),
        breeze_rating=_opt("breeze_rating"),
        precocity_rating=_opt("precocity_rating"),
        sheet_row_url=_opt("sheet_row_url"),
    )


_SELECT = """
    SELECT c.sale_id, s.name AS sale_name, s.vendor, s.country,
           c.lot, c.horse_name, c.year_foaled, c.sire, c.dam,
           c.price, c.currency, c.withdrawn, c.source_url,
           c.ot_diff_m, c.ot_rank, c.sl_1f, c.sl_go,
           c.breeze_rating, c.precocity_rating, c.sheet_row_url
      FROM catalogue_entries c
      JOIN sales s ON s.id = c.sale_id
"""


def match(conn: sqlite3.Connection, runner: RunnerToMatch) -> MatchedHorse | None:
    normalized = normalize_name(runner.name)
    if not normalized:
        return None

    year_foaled = runner.race_year - runner.age if runner.age else None

    if year_foaled is not None:
        row = conn.execute(
            _SELECT + " WHERE c.normalized_name = ? AND c.year_foaled = ? LIMIT 1",
            (normalized, year_foaled),
        ).fetchone()
        if row:
            return _row_to_match(row)

    rows = conn.execute(
        _SELECT + " WHERE c.normalized_name = ?",
        (normalized,),
    ).fetchall()
    if len(rows) == 1:
        return _row_to_match(rows[0])
    if len(rows) > 1 and year_foaled is not None:
        for r in rows:
            if r["year_foaled"] == year_foaled:
                return _row_to_match(r)

    if runner.sire and runner.dam and year_foaled is not None:
        sire_n = normalize_name(runner.sire)
        dam_n = normalize_name(runner.dam)
        candidates = conn.execute(
            _SELECT + " WHERE c.year_foaled = ? AND c.sire IS NOT NULL AND c.dam IS NOT NULL",
            (year_foaled,),
        ).fetchall()
        for cand in candidates:
            if normalize_name(cand["sire"]) == sire_n and normalize_name(cand["dam"]) == dam_n:
                return _row_to_match(cand)

    return None
