"""Sporting Life -- the racecard feed behind Sky Bet, with no bot wall.

Racing Post and Equibase both sit behind WAFs that reject data-centre IPs, but
the same declarations and entries flow through Sporting Life's public JSON API:
every GB and Irish card, the French cards, and a good share of the North
American tracks -- with the owner named on every ride.  The sweep scans every
racecard in the window for Wathnan owners and fills in sire and dam from the
horse endpoint.

Used three ways: as the automatic fallback inside the Racing Post adapter
(everything except North America), as the fallback inside the Equibase adapter
(North America only), and as the standalone ``sportinglife`` source.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from zoneinfo import ZoneInfo

from ..models import Breed, Race, Runner, Status
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

LOG = logging.getLogger(__name__)

BASE = "https://www.sportinglife.com/api/horse-racing"
DAY_URL = BASE + "/racing/racecards/{date}"
RACE_URL = BASE + "/race/{race_id}"
HORSE_URL = BASE + "/horse/{horse_id}"

ROSTER_PATH = Path(__file__).resolve().parents[1] / "data" / "roster.json"

ARABIAN_HINT = re.compile(r"\barab", re.I)
FEATURE_HINT = re.compile(r"group\s*\d|listed|heritage|guineas|derby|oaks|cup\b", re.I)

#: The API publishes post times in UTC, whatever the track.
UTC = ZoneInfo("UTC")
#: Country short names the feed uses for North America.
NORTH_AMERICA = frozenset({"USA", "CAN"})
#: North American tracks the feed carries, for entries that name only a course.
NORTH_AMERICAN_COURSES = frozenset({
    "AQUEDUCT", "ARLINGTON", "BELMONT AT THE BIG A", "BELMONT PARK",
    "CANTERBURY PARK", "CHARLES TOWN", "CHURCHILL DOWNS", "COLONIAL DOWNS",
    "DEL MAR", "DELAWARE PARK", "ELLIS PARK", "EMERALD DOWNS", "FAIR GROUNDS",
    "FINGER LAKES", "GOLDEN GATE FIELDS", "GULFSTREAM", "GULFSTREAM PARK",
    "HORSESHOE INDIANAPOLIS", "KEENELAND", "KENTUCKY DOWNS", "LAUREL PARK",
    "LONE STAR PARK", "LOS ALAMITOS", "LOUISIANA DOWNS", "MONMOUTH PARK",
    "MOUNTAINEER", "OAKLAWN PARK", "PARX", "PENN NATIONAL", "PIMLICO",
    "PRESQUE ISLE DOWNS", "REMINGTON PARK", "SANTA ANITA", "SARATOGA",
    "TAMPA BAY DOWNS", "THISTLEDOWN", "TURF PARADISE", "TURFWAY PARK",
    "WOODBINE",
})


class SportingLifeSource(Source):
    name = "sportinglife"
    label = "Sporting Life (GB & IRE)"
    home = "https://www.sportinglife.com/racing/racecards"

    def fetch(self, fetcher: Fetcher) -> list[Race]:
        return sweep(self, fetcher)


def sweep(source: Source, fetcher: Fetcher,
          countries: frozenset[str] | None = None,
          exclude: frozenset[str] | None = None) -> list[Race]:
    """Scan every racecard in the report window for the owner's runners.

    ``countries``/``exclude`` filter by the feed's country short names, so the
    Racing Post and Equibase fallbacks each cover their own jurisdictions
    without reporting the same race twice.
    """
    races: list[Race] = []
    pedigrees: dict[str, dict] = {}
    seen_races: set[int] = set()
    scanned = 0
    for date in source.config.dates():
        try:
            day = fetcher.get_json(DAY_URL.format(date=date.isoformat()))
        except FetchError as exc:
            LOG.warning("Sporting Life day %s unavailable: %s", date, exc)
            continue
        for race_id in _race_ids(day, countries, exclude):
            scanned += 1
            seen_races.add(race_id)
            race = _race(source, fetcher, race_id, pedigrees)
            if race is not None:
                races.append(race)

    # The sweep only sees cards the feed has published; ask the horses we know
    # about what else they are entered in.
    for race_id in _roster_races(source, fetcher, seen_races, countries, exclude):
        scanned += 1
        race = _race(source, fetcher, race_id, pedigrees)
        if race is not None:
            LOG.info("recovered %s at %s from the horse roster",
                     race.race_type, race.course)
            races.append(race)

    LOG.info("Sporting Life: scanned %d races, matched %d", scanned, len(races))
    return races


#: Wathnan horses met during this run, keyed by name -- merged into the roster
#: file by ``remember_roster`` when the CLI is asked to learn.
_SEEN: dict[str, int] = {}


def _note_horse(horse: dict) -> None:
    slug = horse.get("slug") or ""
    horse_id = slug.rsplit("/", 1)[-1]
    name = (horse.get("name") or "").strip()
    if name and horse_id.isdigit():
        _SEEN[name] = int(horse_id)


def remember_roster() -> int:
    """Fold this run's horses into the roster file; returns how many are new."""
    if not _SEEN:
        return 0
    try:
        data = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"horses": {}}
    horses = data.setdefault("horses", {})
    fresh = {name: value for name, value in _SEEN.items() if horses.get(name) != value}
    if not fresh:
        return 0
    horses.update(fresh)
    data["horses"] = {name: horses[name] for name in sorted(horses)}
    try:
        ROSTER_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
    except OSError as exc:
        LOG.warning("could not update the roster: %s", exc)
        return 0
    LOG.info("added %d horse(s) to the roster", len(fresh))
    return len(fresh)


def load_roster() -> dict[str, int]:
    """``{horse name: Sporting Life id}`` for the string we already know."""
    try:
        data = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # pragma: no cover - packaging error
        LOG.debug("roster unreadable: %s", exc)
        return {}
    return {name: int(value) for name, value in (data.get("horses") or {}).items()}


def _roster_races(source: Source, fetcher: Fetcher, seen: set[int],
                  countries: frozenset[str] | None,
                  exclude: frozenset[str] | None) -> Iterator[int]:
    """Race ids the day sweep missed, read off each known horse's entries."""
    window = set(source.config.dates())
    for name, horse_id in sorted(load_roster().items()):
        try:
            detail = fetcher.get_json(HORSE_URL.format(horse_id=horse_id))
        except FetchError as exc:
            LOG.debug("roster lookup failed for %s: %s", name, exc)
            continue
        for entry in (detail or {}).get("future_entries") or []:
            race_id = entry.get("race_id")
            date = _date(str(entry.get("date") or "")[:10])
            if not race_id or race_id in seen or date not in window:
                continue
            if not _in_scope(entry.get("course_name", ""), countries, exclude):
                continue
            seen.add(race_id)
            yield race_id


def _in_scope(course: str, countries: frozenset[str] | None,
              exclude: frozenset[str] | None) -> bool:
    """Keep each adapter to its own jurisdictions.

    ``future_entries`` names the course but not its country, so the split is
    made on the North American tracks the feed carries.
    """
    north_american = course.upper() in NORTH_AMERICAN_COURSES
    if countries is not None:
        return north_american if countries == NORTH_AMERICA else True
    if exclude is not None and exclude == NORTH_AMERICA:
        return not north_american
    return True


def _race_ids(day: object, countries: frozenset[str] | None,
              exclude: frozenset[str] | None) -> Iterator[int]:
    for meeting in day or []:
        country = (((meeting.get("meeting_summary") or {}).get("course") or {})
                   .get("country") or {}).get("short_name", "")
        if countries is not None and country not in countries:
            continue
        if exclude is not None and country in exclude:
            continue
        for race in meeting.get("races") or []:
            reference = (race.get("race_summary_reference") or {}).get("id")
            if reference:
                yield reference


def _race(source: Source, fetcher: Fetcher, race_id: int,
          pedigrees: dict[str, dict]) -> Race | None:
    try:
        payload = fetcher.get_json(RACE_URL.format(race_id=race_id))
    except FetchError as exc:
        LOG.debug("Sporting Life race %s unavailable: %s", race_id, exc)
        return None

    summary = payload.get("race_summary") or {}
    runners = []
    for ride in payload.get("rides") or []:
        if (ride.get("ride_status") or "").upper() == "NON_RUNNER":
            continue
        owner = (ride.get("owner") or {}).get("name", "")
        if not source.is_wathnan(owner):
            continue
        horse = ride.get("horse") or {}
        _note_horse(horse)
        pedigree = _pedigree(fetcher, horse, pedigrees)
        runners.append(Runner(
            horse=clean_horse_name(horse.get("name", "")),
            sire=clean_pedigree_name(pedigree.get("sire", "")),
            dam=clean_pedigree_name(pedigree.get("dam", "")),
            trainer=title_name((ride.get("trainer") or {}).get("name") or ""),
            jockey=title_name((ride.get("jockey") or {}).get("name") or ""),
        ))
    if not runners:
        return None

    date = _date(summary.get("date"))
    if date is None:
        return None
    name = collapse_space(summary.get("name", ""))
    return Race(
        date=date,
        course=title_course(summary.get("course_name", "")),
        race_type=_race_type(name, summary.get("race_class")),
        distance_furlongs=parse_distance(summary.get("distance")),
        # The feed publishes post times in UTC for every track.
        off_time_uk=to_uk_time(parse_time(summary.get("time")), date, tz=UTC),
        breed=Breed.ARABIAN if ARABIAN_HINT.search(name) else Breed.THOROUGHBRED,
        # GB and Irish declarations close the day before, so tomorrow's rides
        # are the declared field; everything later is an entry.
        status=Status.DECLARED if date == source.config.tomorrow else Status.ENTERED,
        runners=tuple(runners),
        source="sportinglife",
        source_url=f"https://www.sportinglife.com/racing/racecards/-/-/{race_id}",
    )


def _pedigree(fetcher: Fetcher, horse: dict, cache: dict[str, dict]) -> dict:
    """Sire and dam live on the horse endpoint; failures just leave them blank."""
    slug = horse.get("slug") or ""
    horse_id = slug.rsplit("/", 1)[-1] if "/" in slug else ""
    if not horse_id.isdigit():
        return {}
    if horse_id not in cache:
        try:
            detail = fetcher.get_json(HORSE_URL.format(horse_id=horse_id))
        except FetchError as exc:
            LOG.debug("Sporting Life horse %s unavailable: %s", horse_id, exc)
            detail = {}
        cache[horse_id] = {
            "sire": ((detail.get("sire") or {}).get("name") or ""),
            "dam": ((detail.get("dam") or {}).get("name") or ""),
        }
    return cache[horse_id]


def _race_type(name: str, race_class: object) -> str:
    """Reduce a sponsor-heavy race name to the wording the report uses.

    Feature races keep their name (``Sky Bet Lowther Stakes (Fillies' Group 2)``);
    everyday races collapse to the template's shorthand (``Class 5 Handicap``).
    """
    suffix = f"Class {race_class}" if str(race_class or "").strip() else ""
    lowered = name.lower()
    if FEATURE_HINT.search(name):
        return name
    if "nursery" in lowered:
        return collapse_space(f"{name} {suffix}")
    if "handicap" in lowered:
        return collapse_space(f"{suffix} Handicap") if suffix else name
    for plain in ("maiden", "novice", "selling", "claiming"):
        if plain in lowered:
            return plain.title() if plain != "claiming" else "Claimer"
    return collapse_space(f"{name} {suffix}") if suffix else name


def _date(value: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value or "")
    except ValueError:
        return None
