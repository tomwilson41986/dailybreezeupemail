"""Racing Post results client for the barrier-trial tracker.

This is a copy of ``dailybreezeup.racing.rp_results`` with one addition: a
**name-matching path**. The breeze-up version matches a runner only by its
Racing Post ``horse_uid`` (it always has uids, from the sale catalogue). Here the
watchlist is name-keyed and a horse's uid is unknown until we first see it, so a
result row also matches when its normalised horse name is on the watchlist —
that's how we catch a tracked horse's debut before its uid is learned.

We copy rather than edit so the two pipelines stay independent; keep the two
modules in step when RP changes shape under them.

RP serves result pages as a Next.js app: the runner and race data live in the
embedded ``__NEXT_DATA__`` JSON blob, **not** in HTML attributes. (RP migrated
/results away from the old ``rp-horseTable__mainRow`` markup in August 2026.
The old selectors matched nothing, so every race page yielded zero hits and the
evening email reported no results every day while trials went on being run.)

The parsers stay pure for fixture-driven tests.
"""
from __future__ import annotations

import json
import logging
import re
import time as wall
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

import requests
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

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
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


class ResultPayloadMissing(Exception):
    """A result page carried no readable ``raceResult`` payload.

    Raised rather than returning ``[]`` so an RP markup change can't masquerade
    as a day on which none of our horses ran.
    """


class RacePageGone(Exception):
    """RP's results index linked a race page that RP itself 404s.

    Its own index routinely carries a handful of these (abandoned or
    re-scheduled races). Permanent, so there is nothing to retry and nothing
    to alarm about.
    """


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


def _extract_result_data(html_text: str) -> dict[str, Any] | None:
    """Pull ``raceResult.data`` out of the page's ``__NEXT_DATA__`` JSON."""
    m = _NEXT_DATA_RE.search(html_text)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    try:
        race_data = data["props"]["pageProps"]["initialState"]["raceResult"]["data"]
    except (KeyError, TypeError):
        return None
    return race_data if isinstance(race_data, dict) else None


def _payload_off_time(payload: dict[str, Any]) -> time | None:
    """Off time in UK clock terms, which is what the email shows.

    ``raceDatetime`` is already expressed in UK time even for a foreign
    fixture (``localRaceDatetime`` carries the course's own clock — Deauville's
    14:18 CEST is the 1:18 the UK reader is looking for). Fall back to the
    header's display time, which needs the same 12-hour fixup as a page title.
    """
    iso = payload.get("raceDatetime")
    if isinstance(iso, str):
        try:
            return datetime.fromisoformat(iso).time().replace(second=0, microsecond=0)
        except ValueError:
            pass
    header = payload.get("header")
    if isinstance(header, dict):
        return _parse_off_time(header.get("raceTime") or "")
    return None


def _text(value: Any) -> str | None:
    """Collapse a JSON string field to a clean value, or None when blank."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _slug_from_url(url: Any) -> str:
    m = _PROFILE_RE.search(url) if isinstance(url, str) else None
    return m.group(2) if m else ""


def _parse_rating(s: Any) -> int | None:
    """Pull an integer rating out of a rating-column cell (dashes → None)."""
    digits = "".join(ch for ch in str(s or "") if ch.isdigit())
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
    """Emit a :class:`ResultHit` for every runner on our watchlist.

    A runner matches when its ``horseUid`` is in ``target_uids`` **or** its
    normalised name is a key of ``target_names`` (the name path the breeze-up
    module lacks). The returned hit always carries the runner's real profile
    uid — even when matched by name — so the caller can learn it. With neither
    target supplied, returns ``[]``.

    Raises :class:`ResultPayloadMissing` when the page carries no readable
    ``raceResult`` payload, so a markup change surfaces as a loud failure
    instead of a day that merely looks quiet.
    """
    target_names = target_names or {}
    if not target_uids and not target_names:
        return []
    payload = _extract_result_data(html_text)
    if payload is None:
        raise ResultPayloadMissing(
            f"no __NEXT_DATA__ raceResult payload on {race_url} "
            "— has RP changed the page shape again?"
        )

    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}

    off_time = _payload_off_time(payload)
    race_name = _text(header.get("raceTitle")) or ""
    # RP's own course name beats one reconstructed from the URL slug:
    # "Lingfield (AW)" rather than "Lingfield Aw".
    course_name = _text(payload.get("courseName")) or course

    runners = payload.get("runners")
    runners = runners if isinstance(runners, list) else []
    total_runners = details.get("numberOfRunners")
    if not isinstance(total_runners, int):
        total_runners = len(runners) or None

    hits: list[ResultHit] = []
    for runner in runners:
        if not isinstance(runner, dict):
            continue
        uid = runner.get("horseUid")
        uid = uid if isinstance(uid, int) else None
        horse_name = _text(runner.get("horseName")) or ""

        matched = uid is not None and uid in target_uids
        if not matched and horse_name:
            matched = normalize_name(horse_name) in target_names
        # A name-matched runner is only useful if RP also gave us its uid —
        # learning that uid is the point of the name path.
        if not matched or uid is None:
            continue

        # A disqualified runner keeps its finishing code in the feed, but it
        # did not win anything — the stats count "1" as a win, so say DSQ.
        pos = _text(runner.get("outcomeCode"))
        if runner.get("isDisqualified"):
            pos = "DSQ"

        hits.append(
            ResultHit(
                horse_uid=uid,
                horse_slug=_slug_from_url(runner.get("horseUrl")),
                horse_name=horse_name,
                course=course_name,
                race_date=race_date,
                off_time=off_time,
                race_name=race_name,
                finishing_position=pos,
                sp=_text(runner.get("odds")),
                race_url=race_url,
                race_uid=race_uid,
                silk_url=_text(runner.get("silkUrl")),
                total_runners=total_runners,
                rpr=_parse_rating(runner.get("rpRating")),
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


@retry(
    retry=retry_if_not_exception_type(RacePageGone),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
)
def _fetch(session: requests.Session, url: str) -> str:
    r = session.get(url, timeout=30)
    # A 404 is RP's final answer; retrying one three times with backoff just
    # spends a minute of the run on the stale links its own index publishes.
    if r.status_code == 404:
        raise RacePageGone(url)
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
    read = gone = failed = 0
    for i, (slug, race_uid, url) in enumerate(races):
        if i:
            wall.sleep(sleep)
        try:
            page = _fetch(s, url)
        except RacePageGone:
            gone += 1
            log.info("RP result page no longer published, skipping (%s)", url)
            continue
        except Exception as exc:  # noqa: BLE001
            failed += 1
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
            read += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            log.warning("RP result page parse failed (%s): %s", url, exc)

    log.info(
        "RP results %s: read %d/%d race pages (%d unreadable, %d no longer published)",
        on, read, len(races), failed, gone,
    )
    # Zero hits off a full read is a quiet day; zero hits because we couldn't
    # read the card is a broken scrape wearing a quiet day's clothes. The
    # caller can't tell them apart from the hit count, so shout here.
    if failed and not read:
        log.error(
            "RP results %s: every one of the %d readable race pages failed — "
            "treat today's result count as unknown, not zero", on, failed,
        )
    elif failed:
        log.warning(
            "RP results %s: %d of %d race pages unreadable; any tracked horse "
            "that ran in them is missing from today's email", on, failed, len(races),
        )
    return hits
