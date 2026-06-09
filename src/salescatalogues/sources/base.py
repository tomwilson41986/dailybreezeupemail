"""Shared scraping helpers for the source adapters: an HTTP session that
impersonates Chrome (so cloud-IP runs aren't bot-blocked) and a tolerant
date-range parser that copes with the dozen date formats the auction houses
publish.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}


def make_session() -> requests.Session:
    """Build an HTTP session, impersonating Chrome's TLS fingerprint via
    curl_cffi when available (matches the rest of this repo's scrapers and gets
    past Fastly/Cloudflare bot challenges from cloud IPs). Falls back to plain
    requests."""
    try:
        from curl_cffi import requests as cffi_requests

        s = cffi_requests.Session(impersonate="chrome124")
    except ImportError:
        log.warning("curl_cffi not available; falling back to plain requests")
        s = requests.Session()
    s.headers.update(_HEADERS)
    return s


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def get_text(session: requests.Session, url: str, *, timeout: int = 30) -> str:
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def get_json(session: requests.Session, url: str, *, timeout: int = 30):
    """GET a URL and parse JSON. Returns ``None`` on an empty body (some
    catalogue APIs return 200 + empty when a sale isn't published yet)."""
    import json as _json

    r = session.get(url, headers={"Accept": "application/json"}, timeout=timeout)
    r.raise_for_status()
    body = r.text.strip()
    if not body:
        return None
    return _json.loads(body)


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ALT = r"jan|feb|mar|apr|may|jun|jul|aug|sept|sep|oct|nov|dec"
# Single token scan: a month word OR a 1-2 digit day number.
_TOKEN_RE = re.compile(rf"(?P<mon>{_MONTH_ALT})[a-z.]*|(?P<day>\d{{1,2}})", re.IGNORECASE)
_WEEKDAY_RE = re.compile(
    r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b\.?,?", re.IGNORECASE
)
_ORDINAL_RE = re.compile(r"(\d{1,2})(st|nd|rd|th)\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _norm(text: str) -> str:
    s = text.strip().lower()
    s = s.replace("–", "-").replace("—", "-").replace("&", "-")
    s = re.sub(r"\b(to|and)\b", "-", s)
    s = _WEEKDAY_RE.sub(" ", s)
    s = _ORDINAL_RE.sub(r"\1", s)
    # Drop a leading "from "/"the " and "part N:" style prefixes the day scan
    # would otherwise mistake for a day-of-month.
    s = re.sub(r"\bpart\s*\d+\s*[:\-]?", " ", s)
    s = re.sub(r"\b(book|day)\s*\d+\s*[:\-]?", " ", s)
    return s


def parse_date_range(
    text: str, ref: date, *, dayfirst: bool = True
) -> tuple[date | None, date | None]:
    """Parse a published date string into ``(start, end)``.

    Handles day-first (UK/IRE/FR/DE/AUS/NZ) and month-first (US) orderings,
    single days, in-month ranges ("6 - 8 Oct"), cross-month ranges
    ("30 January - 4 February"), and missing years (inferred as the nearest
    upcoming occurrence relative to ``ref``). Returns ``(None, None)`` when no
    month can be found.
    """
    if not text:
        return None, None
    s = _norm(text)
    ym = _YEAR_RE.search(s)
    year = int(ym.group(1)) if ym else None
    if ym:
        s = s[: ym.start()] + s[ym.end():]

    tokens = [
        ("m", _MONTHS[m.group("mon").lower()[:3]])
        if m.group("mon")
        else ("d", int(m.group("day")))
        for m in _TOKEN_RE.finditer(s)
    ]
    months = [v for k, v in tokens if k == "m"]
    if not months:
        return None, None

    pairs: list[tuple[int, int]] = []  # (day, month)
    first_is_month = next((k for k, _ in tokens), "d") == "m"
    if dayfirst and not first_is_month:
        pending: list[int] = []
        for kind, val in tokens:
            if kind == "d":
                pending.append(val)
            else:
                pairs.extend((d, val) for d in pending)
                pending = []
        if pending:  # trailing days with no following month -> use last month
            pairs.extend((d, months[-1]) for d in pending)
    else:  # month-first (US), or string opens with a month
        cur = months[0]
        for kind, val in tokens:
            if kind == "m":
                cur = val
            else:
                pairs.append((val, cur))
        if not pairs:  # month(s) but no day, e.g. just "December 2026"
            pairs = [(1, m) for m in months]

    if not pairs:
        return None, None
    start_day, start_month = pairs[0]
    end_day, end_month = pairs[-1]

    yr = year if year is not None else ref.year
    try:
        start = date(yr, start_month, start_day)
        end_year = yr + 1 if end_month < start_month else yr
        end = date(end_year, end_month, end_day)
    except ValueError:
        return None, None

    # Infer the nearest upcoming year when none was published: if the parsed
    # span already finished well in the past, roll it forward a year. A 60-day
    # grace keeps a just-finished sale in the current year so it can still show
    # as recently active.
    if year is None and end < ref - timedelta(days=60):
        try:
            start = start.replace(year=start.year + 1)
            end = end.replace(year=end.year + 1)
        except ValueError:
            pass

    return start, (end if end != start else None)


def squash(text: str) -> str:
    """Collapse whitespace in scraped text."""
    return " ".join((text or "").split())


_SEX_CODE = {"C": "Colt", "F": "Filly", "G": "Gelding", "H": "Horse", "M": "Mare"}
_COLOUR_CODE = {
    "B": "Bay", "CH": "Chestnut", "GR": "Grey", "BR": "Brown",
    "BL": "Black", "RO": "Roan", "DKB": "Dark Bay",
}


def split_sex_colour(token: str) -> tuple[str, str]:
    """Split a UK/IRE colour+sex token like "B.F." or "Ch.C" into
    ``(sex, colour)`` in readable form. The trailing letter is the sex code
    (C/F/G/H/M); the leading part is the colour (B, Ch, Gr, Br, Bl, Ro)."""
    parts = [p for p in token.replace(" ", "").split(".") if p]
    if not parts:
        return "", ""
    sex = _SEX_CODE.get(parts[-1].upper(), "")
    colour = ""
    if len(parts) >= 2:
        colour = _COLOUR_CODE.get(parts[0].upper(), parts[0])
    return sex, colour
