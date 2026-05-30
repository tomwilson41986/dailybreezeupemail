"""Racing Post racecards client, scoped to uid/name-matching.

Given a set of catalogue lots and a date, fetch that day's racecards index,
walk each race page, and emit one :class:`RacecardEntry` per declared runner
that belongs to our cohort.

RP serves racecards as a Next.js app: the runner and race data live in the
embedded ``__NEXT_DATA__`` JSON blob, **not** in HTML attributes. (RP migrated
away from the old ``data-ugc-runnerid`` / ``RC-runnerName`` markup the previous
version of this module scraped — that markup is gone from the live pages, so
the old selectors matched nothing and the racecard join silently returned zero
hits. The /results pages still use the old HTML, so rp_results is unaffected.)

We read each race's ``runners`` array from the JSON and match a runner to our
catalogue two ways:

* **by ``horseId``** (authoritative) — equals the catalogue's ``horse_uid``;
* **by horse name** — a fallback for lots RP hasn't yet linked a ``horse_uid``
  to (catalogue lag). Guarded on age so a name shared with an older horse can't
  produce a false match.

Why this exists: the bloodstock catalogue's ``entry_details`` field carries at
most one entry per lot and is often stale (it points at a future engagement,
not the imminent declared run). For the morning email we must also walk the
racecards over the entries window and join them against our catalogue lots —
otherwise a grad declared to run *today* is missed whenever its catalogue
entry happens to point elsewhere.

Parsers (``parse_racecards_index_race_urls``, ``parse_racecard_page_entries``)
are pure so tests can run them against captured fixtures.
"""
from __future__ import annotations

import json
import logging
import re
import time as wall
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, time
from typing import Any

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
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
_START_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")

# Sentinel so a name mapped to ``None`` (no age guard) is distinguishable from
# a name that simply isn't in target_names.
_MISSING: Any = object()


@dataclass(frozen=True)
class RacecardEntry:
    horse_uid: int | None
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


def normalize_name(name: str | None) -> str:
    """Collapse a horse name to a comparison key: lowercase, alphanumerics only.

    Used for the name-based fallback join. Strips spaces, apostrophes and
    punctuation so "O'Reilly" / "Cosmic  Mystery" compare cleanly against the
    catalogue's ``horse_style_name``."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _as_int(x: Any) -> int | None:
    try:
        return int(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _parse_start_time(s: str | None) -> time | None:
    """Parse a 24-hour ``HH:MM`` off time from the racecard JSON ``startTime``.

    Unlike the old HTML title (a 12-hour clock with no am/pm), the Next.js
    payload already exposes the off time in 24-hour form (e.g. "19:12"), so we
    take it verbatim — no PM heuristic."""
    m = _START_TIME_RE.search(s or "")
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return time(hh, mm)
    return None


def _slug_from_url(url: str | None) -> str:
    m = _PROFILE_RE.search(url or "")
    return m.group(2) if m else ""


def parse_racecards_index_race_urls(
    html_text: str, on: date
) -> list[tuple[int, str, str, str]]:
    """Return ``[(course_uid, course_slug, race_uid, race_url), ...]`` for the date.

    The index still embeds full ``/racecards/<cu>/<slug>/<date>/<ru>`` links
    (in the Next.js payload), so a regex sweep over the raw text continues to
    work without parsing the JSON."""
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


def _extract_race_data(html_text: str) -> dict[str, Any] | None:
    """Pull ``racePage.data`` out of the page's ``__NEXT_DATA__`` JSON."""
    m = _NEXT_DATA_RE.search(html_text)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    try:
        race_data = data["props"]["pageProps"]["initialState"]["racePage"]["data"]
    except (KeyError, TypeError):
        return None
    return race_data if isinstance(race_data, dict) else None


def parse_racecard_page_entries(
    html_text: str,
    *,
    race_url: str,
    race_uid: str,
    course_uid: int,
    course: str,
    race_date: date,
    target_uids: set[int],
    target_names: Mapping[str, int | None] | None = None,
) -> tuple[list[RacecardEntry], time | None]:
    """Scan a racecard page for runners that belong to our cohort.

    Returns ``(matched_entries, page_off_time)``. The off_time is read from the
    JSON race block regardless of whether any runner matched, so callers can
    build a ``race_uid → off_time`` map covering every race scanned (the
    morning email uses this to attach race times to catalogue-side entries
    whose horse_uid was not found in any racecard).

    A runner matches when its ``horseId`` is in ``target_uids`` (authoritative)
    or its normalized name is a key of ``target_names`` (fallback for lots with
    no linked uid). For name matches, when the mapped value is a non-None age
    the runner's age must equal it — a cheap guard against name collisions with
    older horses. Non-runners (``nonRunner: true``) are skipped.
    """
    payload = _extract_race_data(html_text)
    if payload is None:
        return [], None

    race = payload.get("race") or {}
    off_time = _parse_start_time(race.get("startTime"))
    race_name = (race.get("raceTitle") or "").strip()

    target_names = target_names or {}
    if not target_uids and not target_names:
        return [], off_time

    hits: list[RacecardEntry] = []
    for runner in payload.get("runners") or []:
        if not isinstance(runner, dict) or runner.get("nonRunner"):
            continue
        uid = _as_int(runner.get("horseId"))
        name = (runner.get("horseName") or "").strip()

        matched = uid is not None and uid in target_uids
        if not matched and name:
            expected_age = target_names.get(normalize_name(name), _MISSING)
            if expected_age is not _MISSING:
                runner_age = _as_int(runner.get("age"))
                matched = expected_age is None or runner_age == expected_age
        if not matched:
            continue

        hits.append(
            RacecardEntry(
                horse_uid=uid,
                horse_slug=_slug_from_url(runner.get("horseUrl")),
                horse_name=name,
                course_uid=course_uid,
                course=course,
                race_date=race_date,
                off_time=off_time,
                race_name=race_name,
                race_url=race_url,
                race_uid=race_uid,
                silk_url=(runner.get("silkImage") or None),
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
    target_names: Mapping[str, int | None] | None = None,
    sleep: float = 1.2,
    session: requests.Session | None = None,
) -> tuple[list[RacecardEntry], dict[str, time]]:
    """Scrape RP's racecards index for ``on`` and emit entries for our cohort.

    ``target_uids`` are catalogue horse_uids (authoritative join). ``target_names``
    maps normalized horse names to an expected age (or None) for the name-based
    fallback — used for lots RP hasn't linked a uid to yet.

    Returns ``(entries, off_times)`` where ``off_times`` maps ``race_uid`` to
    the page's off-time for every race scanned (not just the ones with a matched
    runner). The morning email uses this to attach race times to catalogue-side
    entries whose horse_uid did not match any racecard runner.
    """
    uids: set[int] = {int(u) for u in target_uids}
    names = dict(target_names or {})
    if not uids and not names:
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
                target_names=names,
            )
            hits.extend(page_hits)
            if page_off is not None:
                off_times[race_uid] = page_off
        except Exception as exc:  # noqa: BLE001
            log.warning("RP racecard parse failed (%s): %s", url, exc)
    return hits, off_times
