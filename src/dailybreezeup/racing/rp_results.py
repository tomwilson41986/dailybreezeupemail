"""Racing Post results client, scoped to uid-matching.

Given a set of ``horse_uid`` values, fetch today's results index from
Racing Post, walk each race page, and emit one :class:`ResultHit` per
matched runner.  No name-based matching: we join on the uid embedded in
the profile/horse/<uid> anchor, which is authoritative.

The parsers are pure so tests can drive them against captured fixtures.
"""
from __future__ import annotations

import logging
import os
import re
import time as wall
from dataclasses import dataclass
from datetime import date, time
from typing import Iterable, Sequence

import requests
from lxml import html as lxml_html
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

BASE = "https://www.racingpost.com"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Match the rp_sales.py header set so both modules look identical to RP's
# bot filter. See rp_sales.py for rationale.
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

_RESULT_PATH_RE = re.compile(r"/results/\d+/([a-z][a-z0-9-]*)/(\d{4}-\d{2}-\d{2})/(\d+)")
_PROFILE_RE = re.compile(r"/profile/horse/(\d+)/([a-z0-9-]+)")
_TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})")
_RAN_RE = re.compile(r"(\d+)\s+ran\b", re.IGNORECASE)


@dataclass(frozen=True)
class ResultHit:
    horse_uid: int
    horse_slug: str
    horse_name: str
    course: str
    race_date: date
    off_time: time | None
    race_name: str
    finishing_position: str | None
    sp: str | None
    race_url: str
    race_uid: str
    silk_url: str | None
    total_runners: int | None
    rpr: int | None


def _course_display(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.split("-"))


def _parse_off_time(title: str) -> time | None:
    m = _TIME_RE.search(title or "")
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    if 1 <= hh <= 10:
        hh += 12
    return time(hh, mm)


def _parse_rating(s: str) -> int | None:
    """Pull an integer rating out of a rating-column cell.

    RP renders ratings as either a digit string or an en-dash entity
    (&#8211;) / em-dash for missing values; sometimes there's leading
    whitespace from the surrounding markup."""
    digits = "".join(ch for ch in (s or "") if ch.isdigit())
    return int(digits) if digits else None


def parse_results_index_race_urls(html_text: str, on: date) -> list[tuple[str, str, str]]:
    """Return ``[(course_slug, race_uid, race_url), ...]`` for each race on the date."""
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for m in _RESULT_PATH_RE.finditer(html_text):
        slug, d_str, race_id = m.groups()
        if d_str != on.isoformat():
            continue
        if race_id in seen:
            continue
        seen.add(race_id)
        out.append((slug, race_id, f"{BASE}{m.group(0)}"))
    return out


def parse_result_page_hits(
    html_text: str,
    *,
    race_url: str,
    race_uid: str,
    course: str,
    race_date: date,
    target_uids: set[int],
) -> list[ResultHit]:
    """Scan a race page for profile/horse/<uid> where uid is in ``target_uids``."""
    if not target_uids:
        return []
    doc = lxml_html.fromstring(html_text)
    title_nodes = doc.xpath("//title/text()")
    off_time = _parse_off_time(title_nodes[0]) if title_nodes else None
    race_name_nodes = doc.xpath(
        '//*[contains(@class,"rp-raceTimeCourseName__title")]//text()'
    )
    race_name = " ".join("".join(race_name_nodes).split()) if race_name_nodes else ""

    # "X ran" is published in the post-race info strip; fall back to the row
    # count if the markup ever changes shape.
    total_runners: int | None = None
    for txt in doc.xpath(
        '//*[contains(@class,"rp-raceInfo__value_black")]//text()'
    ):
        m = _RAN_RE.search(txt)
        if m:
            total_runners = int(m.group(1))
            break
    main_rows = doc.xpath('//tr[contains(@class,"rp-horseTable__mainRow")]')
    if total_runners is None and main_rows:
        total_runners = len(main_rows)

    hits: list[ResultHit] = []
    for row in main_rows:
        anchors = row.xpath('.//a[contains(@href,"/profile/horse/")]/@href')
        uid_match: tuple[int, str] | None = None
        for href in anchors:
            m = _PROFILE_RE.search(href)
            if not m:
                continue
            uid = int(m.group(1))
            if uid in target_uids:
                uid_match = (uid, m.group(2))
                break
        if uid_match is None:
            continue

        uid, slug = uid_match
        horse_el = row.xpath('.//*[contains(@class,"rp-horseTable__horse__name")]')
        horse_name = " ".join(horse_el[0].text_content().split()) if horse_el else ""
        pos_el = row.xpath('.//*[contains(@class,"rp-horseTable__pos__number")]/text()')
        pos = pos_el[0].strip().split()[0] if pos_el and pos_el[0].strip() else None
        sp_el = row.xpath('.//*[contains(@class,"rp-horseTable__horse__price")]/text()')
        sp = " ".join("".join(sp_el).split()) or None
        silk_src = row.xpath('.//img[contains(@class,"rp-horseTable__silk")]/@src')
        silk_url = silk_src[0] if silk_src else None
        rpr_text = "".join(row.xpath('.//td[@data-ending="RPR"]//text()'))
        rpr = _parse_rating(rpr_text)

        hits.append(
            ResultHit(
                horse_uid=uid,
                horse_slug=slug,
                horse_name=horse_name,
                course=course,
                race_date=race_date,
                off_time=off_time,
                race_name=race_name,
                finishing_position=pos,
                sp=sp,
                race_url=race_url,
                race_uid=race_uid,
                silk_url=silk_url,
                total_runners=total_runners,
                rpr=rpr,
            )
        )
    return hits


# ---------- live fetcher ----------


def _make_session():
    """See dailybreezeup.racing.rp_sales._make_session for rationale."""
    try:
        from curl_cffi import requests as cffi_requests
        impersonate = os.environ.get("RP_IMPERSONATE", "chrome124")
        verify = os.environ.get("CURL_CA_BUNDLE") or os.environ.get("REQUESTS_CA_BUNDLE")
        s = cffi_requests.Session(impersonate=impersonate, verify=verify or True)
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


def fetch_hits_for_uids(
    on: date,
    target_uids: Iterable[int],
    *,
    sleep: float = 1.2,
    session: requests.Session | None = None,
) -> list[ResultHit]:
    """Scrape today's RP results index and emit hits for any uid we care about."""
    uids: set[int] = set(int(u) for u in target_uids)
    if not uids:
        return []
    s = session or _make_session()
    try:
        index_html = _fetch(s, f"{BASE}/results/{on.isoformat()}")
    except Exception as exc:  # noqa: BLE001
        log.warning("RP results index fetch failed (%s): %s", on, exc)
        return []

    races = parse_results_index_race_urls(index_html, on)
    if not races:
        log.info("RP results: no races on %s", on)
        return []

    hits: list[ResultHit] = []
    for i, (slug, race_uid, url) in enumerate(races):
        if i:
            wall.sleep(sleep)
        try:
            page = _fetch(s, url)
        except Exception as exc:  # noqa: BLE001
            log.warning("RP result page fetch failed (%s): %s", url, exc)
            continue
        try:
            hits.extend(
                parse_result_page_hits(
                    page,
                    race_url=url,
                    race_uid=race_uid,
                    course=_course_display(slug),
                    race_date=on,
                    target_uids=uids,
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("RP result page parse failed (%s): %s", url, exc)
    return hits
