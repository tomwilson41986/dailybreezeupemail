"""Racing Post racecards client, scoped to uid-matching.

Mirrors rp_results: given a set of ``horse_uid`` values and a date, fetch
that day's racecards index, walk each race page, and emit one
:class:`RacecardEntry` per matched runner. The join is by uid embedded in
each runner row's ``data-ugc-runnerid`` attribute (authoritative).

Why this exists: the bloodstock catalogue's ``entry_details`` field carries
at most one entry per lot, and is sometimes stale or points at a future
race instead of an imminent one. For the morning entries email we cannot
rely on it alone — we must also walk the racecards over the entries
window and uid-join them against our catalogue lots.
"""
from __future__ import annotations

import json
import logging
import re
import time as wall
from dataclasses import dataclass
from datetime import date, time
from typing import Any, Iterable

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

BASE = "https://www.racingpost.com"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_DOC_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "sec-ch-ua": '"Chromium";v="125", "Not:A-Brand";v="24", "Google Chrome";v="125"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Priority": "u=0, i",
}

_RACECARD_PATH_RE = re.compile(
    r"/racecards/(\d+)/([a-z][a-z0-9-]*)/(\d{4}-\d{2}-\d{2})/(\d+)"
)
_PROFILE_RE = re.compile(r"/profile/horse/(\d+)/([a-z0-9-]+)")
_TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})")
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


@dataclass(frozen=True)
class RacecardEntry:
    horse_uid: int
    horse_slug: str
    horse_name: str
    course_uid: int
    course: str
    race_date: date
    off_time: time | None
    race_name: str
    race_url: str
    race_uid: str
    silk_url: str | None


def _course_display(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.split("-"))


def _parse_off_time(s: str) -> time | None:
    """Parse an off time from RP's ``race.startTime`` field, which is a
    literal 24h ``HH:MM`` string (e.g. ``"14:08"``, ``"20:45"``)."""
    m = _TIME_RE.search(s or "")
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return time(hh, mm)


def _extract_next_data(html_text: str) -> dict[str, Any] | None:
    """Pull the ``__NEXT_DATA__`` JSON blob RP embeds in every racecard page.
    Returns ``None`` if it's absent or not valid JSON."""
    m = _NEXT_DATA_RE.search(html_text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except (ValueError, TypeError):
        return None


def _race_page_data(data: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return data["props"]["pageProps"]["initialState"]["racePage"]["data"]
    except (KeyError, TypeError):
        return None


def parse_racecards_index_race_urls(
    html_text: str, on: date
) -> list[tuple[int, str, str, str]]:
    """Return ``[(course_uid, course_slug, race_uid, race_url), ...]`` for the date."""
    seen: set[tuple[int, str]] = set()
    out: list[tuple[int, str, str, str]] = []
    for m in _RACECARD_PATH_RE.finditer(html_text):
        course_uid = int(m.group(1))
        slug = m.group(2)
        d_str = m.group(3)
        race_uid = m.group(4)
        if d_str != on.isoformat():
            continue
        key = (course_uid, race_uid)
        if key in seen:
            continue
        seen.add(key)
        out.append((course_uid, slug, race_uid, f"{BASE}{m.group(0)}"))
    return out


def parse_racecard_page_entries(
    html_text: str,
    *,
    race_url: str,
    race_uid: str,
    course_uid: int,
    course: str,
    race_date: date,
    target_uids: set[int],
) -> tuple[list[RacecardEntry], time | None]:
    """Scan a racecard page for runners whose uid is in ``target_uids``.

    Returns ``(matched_entries, page_off_time)``. The off_time is extracted
    regardless of whether any uid matched, so callers can build a
    race_uid → off_time map covering every race scanned (the morning email
    uses this to attach race times to catalogue-side entries whose horse_uid
    was not found in the racecard).

    Racing Post serves racecards as a Next.js app: runner and race data live
    in the ``__NEXT_DATA__`` JSON blob (``racePage.data``), not in scrapeable
    HTML. Each runner's ``horseId`` is the authoritative join key, and
    ``silkImage`` carries the silk SVG URL.
    """
    data = _extract_next_data(html_text)
    rp = _race_page_data(data) if data else None
    if rp is None:
        log.warning("racecard page missing __NEXT_DATA__ racePage data (%s)", race_url)
        return [], None

    race = rp.get("race") or {}
    off_time = _parse_off_time(race.get("startTime") or "")
    race_name = (race.get("raceTitle") or "").strip()

    if not target_uids:
        return [], off_time

    hits: list[RacecardEntry] = []
    for runner in rp.get("runners") or []:
        try:
            uid = int(runner.get("horseId"))
        except (TypeError, ValueError):
            continue
        if uid not in target_uids:
            continue
        slug = ""
        m = _PROFILE_RE.search(runner.get("horseUrl") or "")
        if m:
            slug = m.group(2)
        horse_name = (runner.get("horseName") or "").strip()
        silk_url = runner.get("silkImage") or None
        hits.append(
            RacecardEntry(
                horse_uid=uid,
                horse_slug=slug,
                horse_name=horse_name,
                course_uid=course_uid,
                course=course,
                race_date=race_date,
                off_time=off_time,
                race_name=race_name,
                race_url=race_url,
                race_uid=race_uid,
                silk_url=silk_url,
            )
        )
    return hits, off_time


# ---------- live fetcher ----------


def _make_session():
    """See dailybreezeup.racing.rp_sales._make_session for rationale."""
    try:
        from curl_cffi import requests as cffi_requests
        s = cffi_requests.Session(impersonate="chrome124")
    except ImportError:
        log.warning("curl_cffi not available; falling back to plain requests")
        s = requests.Session()
    s.headers.update(_DOC_HEADERS)
    return s


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def _fetch(session: requests.Session, url: str) -> str:
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def fetch_entries_for_uids(
    on: date,
    target_uids: Iterable[int],
    *,
    sleep: float = 1.2,
    session: requests.Session | None = None,
) -> tuple[list[RacecardEntry], dict[str, time]]:
    """Scrape RP's racecards index for ``on`` and emit entries for any uid in scope.

    Returns ``(entries, off_times)`` where ``off_times`` maps ``race_uid`` to
    the page's off-time for every race scanned (not just the ones with a
    matched runner). The morning email uses this to attach race times to
    catalogue-side entries whose horse_uid did not match any racecard runner.
    """
    uids: set[int] = {int(u) for u in target_uids}
    if not uids:
        return [], {}
    s = session or _make_session()
    try:
        index_html = _fetch(s, f"{BASE}/racecards/{on.isoformat()}")
    except Exception as exc:  # noqa: BLE001
        log.warning("RP racecards index fetch failed (%s): %s", on, exc)
        return [], {}

    races = parse_racecards_index_race_urls(index_html, on)
    if not races:
        log.info("RP racecards: no races on %s", on)
        return [], {}

    hits: list[RacecardEntry] = []
    off_times: dict[str, time] = {}
    for i, (course_uid, slug, race_uid, url) in enumerate(races):
        if i:
            wall.sleep(sleep)
        try:
            page = _fetch(s, url)
        except Exception as exc:  # noqa: BLE001
            log.warning("RP racecard fetch failed (%s): %s", url, exc)
            continue
        try:
            page_hits, page_off = parse_racecard_page_entries(
                page,
                race_url=url,
                race_uid=race_uid,
                course_uid=course_uid,
                course=_course_display(slug),
                race_date=on,
                target_uids=uids,
            )
            hits.extend(page_hits)
            if page_off is not None:
                off_times[race_uid] = page_off
        except Exception as exc:  # noqa: BLE001
            log.warning("RP racecard parse failed (%s): %s", url, exc)
    return hits, off_times
