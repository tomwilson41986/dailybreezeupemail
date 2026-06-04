"""Racing Post results client for the barrier-trial tracker.

This is a copy of ``dailybreezeup.racing.rp_results`` with one addition: a
**name-matching path**. The breeze-up version matches a runner only by its
Racing Post ``horse_uid`` (it always has uids, from the sale catalogue). Here the
watchlist is name-keyed and a horse's uid is unknown until we first see it, so a
result row also matches when its normalised horse name is on the watchlist —
that's how we catch a tracked horse's debut before its uid is learned.

The breeze-up module is deliberately left untouched; we copy rather than edit so
the live pipeline is unaffected. The parsers stay pure for fixture-driven tests.
"""
from __future__ import annotations

import logging
import re
import time as wall
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, time

import requests
from lxml import html as lxml_html
from tenacity import retry, stop_after_attempt, wait_exponential

from dailybreezeup.racing.rp_racecards import normalize_name

log = logging.getLogger(__name__)

BASE = "https://www.racingpost.com"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Match the rp_sales.py header set so we look identical to RP's bot filter.
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
    """Pull an integer rating out of a rating-column cell (dashes → None)."""
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
    target_names: Mapping[str, int | None] | None = None,
) -> list[ResultHit]:
    """Scan a race page for runners on our watchlist.

    A row matches when its profile uid is in ``target_uids`` **or** its normalised
    horse name is a key of ``target_names`` (the name path the breeze-up module
    lacks). The returned ``ResultHit`` always carries the runner's real profile
    uid — even when matched by name — so the caller can learn it. Non-matching
    rows are skipped. With neither target supplied, returns ``[]``.
    """
    target_names = target_names or {}
    if not target_uids and not target_names:
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
    for txt in doc.xpath('//*[contains(@class,"rp-raceInfo__value_black")]//text()'):
        m = _RAN_RE.search(txt)
        if m:
            total_runners = int(m.group(1))
            break
    main_rows = doc.xpath('//tr[contains(@class,"rp-horseTable__mainRow")]')
    if total_runners is None and main_rows:
        total_runners = len(main_rows)

    hits: list[ResultHit] = []
    for row in main_rows:
        # Resolve the row's horse identity (first profile link wins) and name
        # up front, then decide whether it's one of ours by uid or by name.
        uid: int | None = None
        slug = ""
        for href in row.xpath('.//a[contains(@href,"/profile/horse/")]/@href'):
            m = _PROFILE_RE.search(href)
            if m:
                uid, slug = int(m.group(1)), m.group(2)
                break
        horse_el = row.xpath('.//*[contains(@class,"rp-horseTable__horse__name")]')
        horse_name = " ".join(horse_el[0].text_content().split()) if horse_el else ""

        matched = uid is not None and uid in target_uids
        if not matched and horse_name:
            matched = normalize_name(horse_name) in target_names
        if not matched or uid is None:
            continue

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


def fetch_hits_for_uids(
    on: date,
    target_uids: Iterable[int],
    *,
    target_names: Mapping[str, int | None] | None = None,
    sleep: float = 1.2,
    session: requests.Session | None = None,
) -> list[ResultHit]:
    """Scrape ``on``'s RP results index and emit hits for any watchlist horse.

    ``target_uids`` are learned Racing Post uids (authoritative join);
    ``target_names`` maps normalised horse names to an optional expected value
    for the name path (the value is unused here — presence is the match).
    """
    uids: set[int] = {int(u) for u in target_uids}
    names = dict(target_names or {})
    if not uids and not names:
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
                    target_names=names,
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("RP result page parse failed (%s): %s", url, exc)
    return hits
