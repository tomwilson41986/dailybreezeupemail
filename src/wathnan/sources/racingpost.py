"""Racing Post -- the owner entries page, which covers GB and Irish racing.

Racing Post sits behind a Signal Sciences WAF that rejects data-centre IPs
outright, so this adapter tries three ways in, in order:

1. ``requests`` with browser-like headers -- works from an ordinary connection;
2. headless Chromium (``--browser``), which clears most challenges;
3. a saved snapshot, so a blocked runner can still be fed the page you saved
   from your own browser (see ``--offline`` and ``snapshots/``).

Parsing is deliberately structural rather than class-name based: the page's
embedded state is used when present, otherwise the entry tables are read by
their column headings.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections.abc import Iterable, Iterator
from typing import Any

from bs4 import BeautifulSoup, Tag

from ..models import Breed, Race, Runner, Status, normalise_key
from ..normalise import (
    clean_horse_name,
    clean_pedigree_name,
    collapse_space,
    parse_distance,
    parse_time,
    title_course,
    title_name,
    to_uk_time,
)
from .base import Fetcher, FetchError, Source
from .tables import Column, find_tables, rows, split_pedigree

LOG = logging.getLogger(__name__)

BASE = "https://www.racingpost.com"
ENTRIES_URL = BASE + "/profile/owner/{owner_id}/wathnan-racing/entries/"

COLUMNS = (
    Column("date", "date", required=False),
    Column("course", "course", "meeting", "track", required=False),
    Column("race", "race", "race type", "race name", required=False),
    Column("distance", "distance", "dist"),
    Column("time", "time", "off time"),
    Column("horse", "horse", required=True),
    Column("sire", "sire"),
    Column("dam", "dam"),
    Column("pedigree", "pedigree", "breeding"),
    Column("trainer", "trainer", required=True),
    Column("jockey", "jockey"),
)

STATE_KEYS = ("__PRELOADED_STATE__", "__NEXT_DATA__", "__INITIAL_STATE__")
DATE_PATTERNS = ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y", "%a %d %b %Y")


class RacingPostSource(Source):
    name = "racingpost"
    label = "Racing Post (GB & IRE)"
    home = "https://www.racingpost.com/profile/owner/325088/wathnan-racing/entries/"

    def fetch(self, fetcher: Fetcher) -> list[Race]:
        """Both feeds, merged -- they answer different halves of the question.

        The owner page is the authoritative list of what Wathnan is entered in,
        and reaches further ahead than any racecard sweep, but it carries no
        pedigree and names a trainer or jockey only once a race is declared.
        The racecard feed has all of that and no owner page. Neither alone is
        the report, so both run and de-duplication merges them, preferring
        whichever feed actually filled a field.

        If the owner page is unreachable the sweep still stands on its own.
        """
        from .sportinglife import NORTH_AMERICA, sweep

        races: list[Race] = []
        try:
            races.extend(self._from_racingpost(fetcher))
        except Exception as exc:  # noqa: BLE001 - the sweep still has the data
            LOG.warning("Racing Post owner page unavailable (%s); relying on the "
                        "racecard feed for GB & IRE", exc)
        races.extend(sweep(self, fetcher, exclude=NORTH_AMERICA))
        return races

    def _from_racingpost(self, fetcher: Fetcher) -> list[Race]:
        url = ENTRIES_URL.format(owner_id=self.config.source_ids.get("racingpost", "325088"))
        body = self._load(fetcher, url)
        soup = BeautifulSoup(body, "lxml")

        records = list(self._from_state(body)) or list(self._from_tables(soup))
        if not records:
            raise FetchError(
                "no entries found on the Racing Post owner page -- the page may have "
                "been served as a bot challenge; retry with --browser or save the page "
                "into snapshots/ and run with --offline")
        return list(_group_records(records, url, self.name))

    def _load(self, fetcher: Fetcher, url: str) -> str:
        """Plain HTTP, then a Chrome fingerprint, then a real browser.

        The middle step is the one that usually works: Racing Post's filter
        objects to Python's TLS handshake rather than to the IP, so a
        curl_cffi session impersonating Chrome is served the real page.
        """
        try:
            body = fetcher.get(url)
            if not _looks_blocked(body):
                return body
            # Never keep a challenge page: it would poison later --offline runs.
            fetcher.discard(url)
            LOG.info("Racing Post served a challenge page; retrying as Chrome")
        except FetchError as exc:
            LOG.info("Racing Post plain fetch failed (%s); retrying as Chrome", exc)

        try:
            body = fetcher.get(url, impersonate=True, refresh=True)
            if not _looks_blocked(body):
                return body
            fetcher.discard(url)
            LOG.info("Racing Post still challenged us; retrying in a browser")
        except (FetchError, ImportError) as exc:
            LOG.info("Racing Post impersonated fetch failed (%s); retrying in a browser", exc)

        return fetcher.get(url, browser=True, refresh=True)

    # -- embedded state --------------------------------------------------------
    def _from_state(self, body: str) -> Iterator[dict]:
        for payload in _state_payloads(body):
            for entry in _walk_entries(payload):
                if entry.get("owner") and not self.is_wathnan(entry["owner"]):
                    continue
                yield entry

    # -- rendered tables -------------------------------------------------------
    def _from_tables(self, soup: BeautifulSoup) -> Iterator[dict]:
        context = _heading_dates(soup)
        for table, mapping in find_tables(soup, COLUMNS):
            fallback_date = context.get(id(table))
            for record in rows(table, mapping):
                owner = record.get("owner")
                if owner and not self.is_wathnan(owner):
                    continue
                sire, dam = record.get("sire", ""), record.get("dam", "")
                if not sire and record.get("pedigree"):
                    sire, dam = split_pedigree(record["pedigree"])
                yield {
                    "date": _parse_date(record.get("date")) or fallback_date,
                    "course": record.get("course", ""),
                    "race": record.get("race", ""),
                    "distance": record.get("distance", ""),
                    "time": record.get("time", ""),
                    "horse": record.get("horse", ""),
                    "sire": sire,
                    "dam": dam,
                    "trainer": record.get("trainer", ""),
                    "jockey": record.get("jockey", ""),
                }


# -- shared record handling ----------------------------------------------------
def _group_records(records: Iterable[dict], url: str, source: str) -> Iterator[Race]:
    """Fold flat runner records into races keyed by day, course and off time."""
    grouped: dict[tuple, dict] = {}
    for record in records:
        date = record.get("date")
        if not isinstance(date, dt.date):
            date = _parse_date(str(date or ""))
        if date is None or not record.get("horse"):
            continue
        course = _clean_course(record.get("course", ""))
        local_time = parse_time(record.get("time"))
        key = (date, normalise_key(course), collapse_space(record.get("race", "")), local_time)
        bucket = grouped.setdefault(key, {
            "date": date, "course": course,
            "race": collapse_space(record.get("race", "")),
            "distance": parse_distance(record.get("distance")),
            "time": local_time, "runners": [],
        })
        bucket["runners"].append(Runner(
            horse=clean_horse_name(record.get("horse", "")),
            sire=clean_pedigree_name(record.get("sire", "")),
            dam=clean_pedigree_name(record.get("dam", "")),
            trainer=title_name(collapse_space(record.get("trainer", ""))),
            jockey=title_name(collapse_space(record.get("jockey", ""))),
        ))

    for bucket in grouped.values():
        country = "IE" if _is_irish(bucket["course"]) else "GB"
        yield Race(
            date=bucket["date"],
            course=bucket["course"],
            race_type=bucket["race"],
            distance_furlongs=bucket["distance"],
            off_time_uk=to_uk_time(bucket["time"], bucket["date"], country=country),
            breed=Breed.THOROUGHBRED,
            status=Status.ENTERED,
            runners=tuple(bucket["runners"]),
            source=source,
            source_url=url,
        )


#: Racing Post marks the surface on the course name: "Kempton (AW)".
SURFACE_SUFFIX = re.compile(r"\s*\((?:AW|A\.W\.|ALL[- ]WEATHER|TAPETA|POLYTRACK)\)\s*$", re.I)


def _clean_course(name: str) -> str:
    """``Kempton (AW)`` -> ``KEMPTON``, so it matches the same course elsewhere."""
    return title_course(SURFACE_SUFFIX.sub("", collapse_space(name)))


IRISH_COURSES = {
    "CURRAGH", "LEOPARDSTOWN", "NAAS", "FAIRYHOUSE", "GOWRAN PARK", "DUNDALK",
    "GALWAY", "KILLARNEY", "TIPPERARY", "NAVAN", "ROSCOMMON", "BALLINROBE",
    "BELLEWSTOWN", "CORK", "DOWN ROYAL", "DOWNPATRICK", "LAYTOWN", "LIMERICK",
    "LISTOWEL", "PUNCHESTOWN", "SLIGO", "THURLES", "TRAMORE", "WEXFORD",
}


def _is_irish(course: str) -> bool:
    return course.upper() in IRISH_COURSES


def _looks_blocked(body: str) -> bool:
    lowered = (body or "")[:6000].lower()
    return ("sigsci" in lowered or "not acceptable" in lowered
            or "our website is currently not available" in lowered
            or "pardon our interruption" in lowered)


def _state_payloads(body: str) -> Iterator[Any]:
    """Yield any JSON blob the page ships its data in."""
    for key in STATE_KEYS:
        for match in re.finditer(re.escape(key) + r"\s*=\s*", body):
            payload = _json_after(body, match.end())
            if payload is not None:
                yield payload
    for match in re.finditer(r'<script[^>]+type="application/json"[^>]*>(.*?)</script>',
                             body, re.S):
        try:
            yield json.loads(match.group(1))
        except ValueError:
            continue


def _json_after(body: str, start: int) -> Any:
    """Read one balanced JSON object starting at ``start``."""
    while start < len(body) and body[start] in " \t\r\n":
        start += 1
    if start >= len(body) or body[start] not in "{[":
        return None
    decoder = json.JSONDecoder()
    try:
        payload, _ = decoder.raw_decode(body, start)
    except ValueError:
        return None
    return payload


HORSE_KEYS = ("horsename", "horse", "name")
OWNER_KEYS = ("ownername", "owner")
TRAINER_KEYS = ("trainername", "trainer")
JOCKEY_KEYS = ("jockeyname", "jockey")
COURSE_KEYS = ("coursename", "course", "meetingname", "track", "racecoursename")
DATE_KEYS = ("racedate", "date", "meetingdate", "raceday")
TIME_KEYS = ("racetime", "offtime", "time", "racetimeuk")
RACE_KEYS = ("racename", "racetitle", "race", "racetype")
DISTANCE_KEYS = ("distance", "racedistance", "distancef")
SIRE_KEYS = ("sirename", "sire")
DAM_KEYS = ("damname", "dam")


def _walk_entries(payload: Any) -> Iterator[dict]:
    """Recursively pull runner-shaped dicts out of an arbitrary state tree."""
    if isinstance(payload, dict):
        entry = _as_entry(payload)
        if entry is not None:
            yield entry
        for value in payload.values():
            yield from _walk_entries(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _walk_entries(value)


def _as_entry(node: dict) -> dict | None:
    lowered = {str(key).lower(): value for key, value in node.items()}
    horse = _first(lowered, HORSE_KEYS)
    course = _first(lowered, COURSE_KEYS)
    date = _first(lowered, DATE_KEYS)
    if not (horse and course and date):
        return None
    if not isinstance(horse, str) or not isinstance(course, str):
        return None
    return {
        "date": _parse_date(str(date)),
        "course": course,
        "race": str(_first(lowered, RACE_KEYS) or ""),
        "distance": str(_first(lowered, DISTANCE_KEYS) or ""),
        "time": str(_first(lowered, TIME_KEYS) or ""),
        "horse": horse,
        "sire": str(_first(lowered, SIRE_KEYS) or ""),
        "dam": str(_first(lowered, DAM_KEYS) or ""),
        "trainer": str(_first(lowered, TRAINER_KEYS) or ""),
        "jockey": str(_first(lowered, JOCKEY_KEYS) or ""),
        "owner": str(_first(lowered, OWNER_KEYS) or ""),
    }


def _first(node: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = node.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return value
        if isinstance(value, dict):
            for inner in ("name", "value", "text"):
                if isinstance(value.get(inner), str) and value[inner].strip():
                    return value[inner]
    return None


def _heading_dates(soup: BeautifulSoup) -> dict[int, dt.date]:
    """Map each table to the most recent date heading above it."""
    context: dict[int, dt.date] = {}
    current: dt.date | None = None
    for node in soup.find_all(["h1", "h2", "h3", "h4", "div", "table"]):
        if node.name == "table":
            if current is not None:
                context[id(node)] = current
            continue
        text = collapse_space(node.get_text(" "))[:60]
        parsed = _parse_date(text)
        if parsed is not None:
            current = parsed
    return context


def _parse_date(value: str | dt.date | None) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    text = collapse_space(str(value or ""))
    if not text:
        return None
    match = re.search(r"\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}", text)
    if match:
        text = match.group(0)
    for pattern in DATE_PATTERNS:
        try:
            return dt.datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    try:  # ISO timestamps such as 2026-08-14T16:25:00Z
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _text(node: Tag | None) -> str:
    return collapse_space(node.get_text(" ")) if node is not None else ""
