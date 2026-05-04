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

import logging
import re
import time as wall
from dataclasses import dataclass
from datetime import date, time
from typing import Iterable

import requests
from lxml import html as lxml_html
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
    """Parse an off time from a title string or RC-courseHeader__time text.
    UK racecards use 12h clock without am/pm; 1..10 are PM, 11/12 are AM,
    matching the rp_results convention."""
    m = _TIME_RE.search(s or "")
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    if 1 <= hh <= 10:
        hh += 12
    return time(hh, mm)


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
) -> list[RacecardEntry]:
    """Scan a racecard page for runners whose uid is in ``target_uids``.

    Each runner is a node tagged with ``data-ugc-runnerid="<horse_uid>"``.
    That attribute is the authoritative join key — anchors inside the row
    also include sire/dam profile links, so we cannot rely on
    /profile/horse/<uid> matches alone.
    """
    if not target_uids:
        return []
    doc = lxml_html.fromstring(html_text)

    title_nodes = doc.xpath("//title/text()")
    off_time = _parse_off_time(title_nodes[0]) if title_nodes else None
    if off_time is None:
        time_nodes = doc.xpath('//*[contains(@class,"RC-courseHeader__time")]/text()')
        if time_nodes:
            off_time = _parse_off_time(time_nodes[0])

    race_name_nodes = doc.xpath(
        '//*[@data-test-selector="RC-header__raceInstanceTitle"]'
    )
    race_name = (
        " ".join(race_name_nodes[0].text_content().split())
        if race_name_nodes else ""
    )

    hits: list[RacecardEntry] = []
    for row in doc.xpath('//*[@data-ugc-runnerid]'):
        try:
            uid = int(row.get("data-ugc-runnerid"))
        except (TypeError, ValueError):
            continue
        if uid not in target_uids:
            continue
        slug = ""
        for href in row.xpath('.//a/@href'):
            m = _PROFILE_RE.search(href)
            if m and int(m.group(1)) == uid:
                slug = m.group(2)
                break
        name_el = row.xpath('.//*[contains(@class,"RC-runnerName")]')
        horse_name = " ".join(name_el[0].text_content().split()) if name_el else ""
        silk_src = row.xpath('.//img[contains(@class,"RC-runnerJacket__image")]/@src')
        silk_url = silk_src[0] if silk_src else None
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
    return hits


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
) -> list[RacecardEntry]:
    """Scrape RP's racecards index for ``on`` and emit entries for any uid in scope."""
    uids: set[int] = {int(u) for u in target_uids}
    if not uids:
        return []
    s = session or _make_session()
    try:
        index_html = _fetch(s, f"{BASE}/racecards/{on.isoformat()}")
    except Exception as exc:  # noqa: BLE001
        log.warning("RP racecards index fetch failed (%s): %s", on, exc)
        return []

    races = parse_racecards_index_race_urls(index_html, on)
    if not races:
        log.info("RP racecards: no races on %s", on)
        return []

    hits: list[RacecardEntry] = []
    for i, (course_uid, slug, race_uid, url) in enumerate(races):
        if i:
            wall.sleep(sleep)
        try:
            page = _fetch(s, url)
        except Exception as exc:  # noqa: BLE001
            log.warning("RP racecard fetch failed (%s): %s", url, exc)
            continue
        try:
            hits.extend(
                parse_racecard_page_entries(
                    page,
                    race_url=url,
                    race_uid=race_uid,
                    course_uid=course_uid,
                    course=_course_display(slug),
                    race_date=on,
                    target_uids=uids,
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("RP racecard parse failed (%s): %s", url, exc)
    return hits
