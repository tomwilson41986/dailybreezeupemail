"""Watchlist sheet ingestion for the barrier-trial tracker.

The user maintains a Google Sheet of horses that ran in barrier trials, with a
horse-name column and one or more proprietary rating columns. Those rows are the
canonical cohort — unlike the breeze-up job there is no sale catalogue handing us
a Racing Post ``horse_uid``, so the watchlist is keyed purely on the **normalised
horse name** and the uid is learned later, the first time the horse appears on a
racecard or result (see ``daily.py``).

The sheet is read as CSV via the public ``/export?format=csv`` endpoint — no auth,
no service account. Set ``SHEET_CSV_URL`` to point at the watchlist.
"""
from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from dailybreezeup.racing.rp_racecards import normalize_name

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
    name: str                         # display name exactly as typed in the sheet
    name_key: str                     # normalised join key (see normalize_name)
    ratings: dict[str, float | None]  # {rating column header: value}, ordered


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

    Rows with a blank name are skipped. Rating cells that are blank or
    non-numeric become ``None`` (rendered as a dash, excluded from averages).
    """
    reader = csv.DictReader(io.StringIO(text))
    name_col = _resolve_name_column(reader.fieldnames, name_column)
    if name_col is None:
        log.warning(
            "watchlist sheet has no name column (looked for %r and %s); 0 horses",
            name_column, list(_NAME_COLUMN_FALLBACKS),
        )
        return []

    horses: list[TrackedHorse] = []
    seen: set[str] = set()
    for raw in reader:
        name = (raw.get(name_col) or "").strip()
        if not name:
            continue
        key = normalize_name(name)
        if not key or key in seen:
            # Duplicate names collapse to the first row — a watchlist shouldn't
            # list the same horse twice, and a stable key keeps matching sane.
            continue
        seen.add(key)
        ratings = {col: _as_float(raw.get(col)) for col in rating_columns}
        horses.append(TrackedHorse(name=name, name_key=key, ratings=ratings))
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
