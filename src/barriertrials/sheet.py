"""Watchlist sheet ingestion for the barrier-trial tracker.

The user maintains a Google Sheet of horses that ran in barrier trials. Each row
is one horse with a name column, a set of analytics/rating columns, and free-text
notes. Those rows are the canonical cohort — unlike the breeze-up job there is no
sale catalogue handing us a Racing Post ``horse_uid``, so the watchlist is keyed
purely on the **normalised horse name** (country suffix stripped, see
``names.horse_key``) and the uid is learned later, the first time the horse
appears on a racecard or result (see ``daily.py``).

We surface *every* column of the matched row in the email (``fields``), and parse
the configured rating columns to numbers (``ratings``) for the rating tiles and
the season-to-date band/leaderboard tables.

The sheet is read as CSV via the public ``/export?format=csv`` endpoint — no auth.
"""
from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from barriertrials.names import horse_key

log = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Candidate headers tried when the configured name column is absent, so a sheet
# labelled "Name" or "Horse Name" still parses without reconfiguration.
_NAME_COLUMN_FALLBACKS: tuple[str, ...] = ("Horse", "Horse Name", "Name")


@dataclass(frozen=True)
class TrackedHorse:
    name: str                          # display name exactly as typed in the sheet
    name_key: str                      # normalised join key (see names.horse_key)
    # Every non-name column, in sheet order, as raw strings — shown verbatim in
    # the email so the recipient sees the full table row next to the entry/result.
    fields: dict[str, str] = field(default_factory=dict)
    # The configured rating columns parsed to floats (None when blank/non-numeric)
    # — drives the rating tiles and the season-to-date aggregations.
    ratings: dict[str, float | None] = field(default_factory=dict)


def _as_float(x: str | None) -> float | None:
    s = (x or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _resolve_name_column(fieldnames: Sequence[str] | None, preferred: str) -> str | None:
    """Pick the horse-name column: the configured header if present, else a
    common fallback. Returns None when the sheet has no recognisable name column."""
    names = list(fieldnames or [])
    if preferred in names:
        return preferred
    for cand in _NAME_COLUMN_FALLBACKS:
        if cand in names:
            return cand
    return None


def parse_sheet_csv(
    text: str,
    *,
    name_column: str,
    rating_columns: Sequence[str],
) -> list[TrackedHorse]:
    """Parse the CSV body into one ``TrackedHorse`` per named row.

    Rows with a blank name are skipped; duplicate names collapse to the first row.
    ``fields`` keeps every column except the name column, in sheet order. Rating
    cells that are blank or non-numeric become ``None``.
    """
    reader = csv.DictReader(io.StringIO(text))
    name_col = _resolve_name_column(reader.fieldnames, name_column)
    if name_col is None:
        log.warning(
            "watchlist sheet has no name column (looked for %r and %s); 0 horses",
            name_column, list(_NAME_COLUMN_FALLBACKS),
        )
        return []
    # Column order for the per-horse field grid: every header except the name
    # column (and any stray empty header csv emits for trailing commas).
    display_cols = [c for c in (reader.fieldnames or []) if c and c != name_col]

    horses: list[TrackedHorse] = []
    seen: set[str] = set()
    for raw in reader:
        name = (raw.get(name_col) or "").strip()
        if not name:
            continue
        key = horse_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        fields = {col: (raw.get(col) or "").strip() for col in display_cols}
        ratings = {col: _as_float(raw.get(col)) for col in rating_columns}
        horses.append(TrackedHorse(name=name, name_key=key, fields=fields, ratings=ratings))
    return horses


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def fetch_sheet(
    url: str,
    *,
    name_column: str,
    rating_columns: Sequence[str],
) -> list[TrackedHorse]:
    # Google's CDN returns 503 to the default `python-requests/...` UA on
    # /export?format=csv even for public sheets; a browser UA is enough. The
    # redirect to googleusercontent.com occasionally 503s transiently — that's
    # what the retry covers.
    headers = {"User-Agent": _USER_AGENT, "Accept": "text/csv,text/plain,*/*"}
    r = requests.get(url, timeout=30, allow_redirects=True, headers=headers)
    r.raise_for_status()
    return parse_sheet_csv(r.text, name_column=name_column, rating_columns=rating_columns)


def index_by_name(horses: Iterable[TrackedHorse]) -> dict[str, TrackedHorse]:
    return {h.name_key: h for h in horses}
