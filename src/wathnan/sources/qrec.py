"""Qatar Racing and Equestrian Club (QREC).

QREC's website is a thin client over a public JSON API.  The API needs a short
lived token minted from the credentials the public web client ships with; both
can be overridden through the environment if QREC ever rotates them.
"""

from __future__ import annotations

import base64
import datetime as dt
import logging
import os
import re
from collections.abc import Iterable
from typing import Any

from ..models import Breed, Race, Runner, Status
from ..normalise import (
    QATAR,
    clean_horse_name,
    clean_pedigree_name,
    collapse_space,
    furlongs_from_metres,
    parse_time,
    title_name,
    to_uk_time,
)
from .base import Fetcher, FetchError, Source

LOG = logging.getLogger(__name__)

API_ROOT = "https://api.qrec.gov.qa/v1/qrec"
TOKEN_URL = f"{API_ROOT}/token/generate"
DATA_URL = f"{API_ROOT}/race/data"

#: Credentials published in QREC's own browser bundle -- they identify the
#: public portal client, not a user account.
PUBLIC_API_KEY = "MPwVEGVQlP0DDoR1oL3zQ88QGKuqg6oiZClL5yNVjsEVQ65B"
PUBLIC_API_SECRET = "1k7xAoyYYLpoPVlRa21L0hkMjn5LlUhdFpq7awYYMfny7OxJhMZ1rD6LTeLgBq4y"

#: QREC racecourses, matched against the meeting name.
COURSES = ("Al Rayyan", "Al Uqda", "Doha")

ARABIAN_HINT = re.compile(r"\b(arab|purebred|pa\b|p\.a\.)", re.I)


class QrecSource(Source):
    name = "qrec"
    label = "QREC (Qatar)"
    home = "https://qrec.gov.qa/#calendar"

    def fetch(self, fetcher: Fetcher) -> list[Race]:
        token = self._token(fetcher)
        meetings = self._get(fetcher, token, pageaction="jsonmeetings",
                             startdate=self.config.first_date.isoformat(),
                             endate=self.config.last_date.isoformat())
        races: list[Race] = []
        horse_cache: dict[str, dict] = {}
        for meeting in meetings or []:
            date = _parse_date(meeting.get("date"))
            if date is None:
                continue
            course = _course_from_meeting(meeting.get("meetingName", ""))
            for entry in meeting.get("races") or []:
                race = self._build_race(fetcher, token, meeting, entry, date, course,
                                        horse_cache)
                if race is not None:
                    races.append(race)
        return races

    # -- API ------------------------------------------------------------------
    def _token(self, fetcher: Fetcher) -> str:
        key = os.environ.get("QREC_API_KEY", PUBLIC_API_KEY)
        secret = os.environ.get("QREC_API_SECRET", PUBLIC_API_SECRET)
        basic = base64.b64encode(f"{key}:{secret}".encode()).decode()
        payload = fetcher.get_json(
            TOKEN_URL, method="POST", data={"grant_type": "client_credentials"},
            headers={"apikey": key, "authorization": f"Basic {basic}",
                     "channel": "Portal", "language": "en",
                     "content-type": "application/x-www-form-urlencoded"},
        )
        token = (payload or {}).get("access_token")
        if not token:
            raise FetchError("QREC did not return an access token")
        return token

    def _get(self, fetcher: Fetcher, token: str, **params) -> Any:
        key = os.environ.get("QREC_API_KEY", PUBLIC_API_KEY)
        payload = fetcher.get_json(
            DATA_URL, params={**params, "lang": "en"},
            headers={"apikey": key, "apitoken": token, "channel": "Portal",
                     "language": "en", "accept": "application/json"},
        )
        return (payload or {}).get("data")

    # -- parsing --------------------------------------------------------------
    def _build_race(self, fetcher: Fetcher, token: str, meeting: dict, entry: dict,
                    date: dt.date, course: str, horse_cache: dict) -> Race | None:
        race_id = entry.get("raceid")
        if race_id is None:
            return None
        detail = self._get(fetcher, token, pageaction="jsonracetab", raceid=race_id)
        runners = list(self._wathnan_runners(fetcher, token, detail, horse_cache))
        if not runners:
            return None

        local_time = parse_time(entry.get("postTime") or meeting.get("postTime"))
        race_name = collapse_space(entry.get("name", ""))
        return Race(
            date=date,
            course=course,
            race_type=_title_race(race_name),
            distance_furlongs=furlongs_from_metres(entry.get("distance")),
            off_time_uk=to_uk_time(local_time, date, tz=QATAR),
            breed=Breed.ARABIAN if ARABIAN_HINT.search(race_name) else Breed.THOROUGHBRED,
            status=Status.DECLARED if (entry.get("phase") or "").lower() in
            ("racecard", "results", "form guide") else Status.ENTERED,
            runners=tuple(runners),
            source=self.name,
            source_url=f"https://qrec.gov.qa/race-card?raceid={race_id}",
        )

    def _wathnan_runners(self, fetcher: Fetcher, token: str, detail: Any,
                         horse_cache: dict) -> Iterable[Runner]:
        for row in _runner_rows(detail):
            if not self.is_wathnan(row.get("ownerName")):
                continue
            horse_id = str(row.get("horseId") or "")
            pedigree = self._pedigree(fetcher, token, horse_id, horse_cache)
            yield Runner(
                horse=clean_horse_name(row.get("horseName", "")),
                sire=clean_pedigree_name(pedigree.get("sire", "")),
                dam=clean_pedigree_name(pedigree.get("dam", "")),
                trainer=title_name(row.get("trainerName", "")),
                jockey=_clean_jockey(row.get("jockeyName", "")),
            )

    def _pedigree(self, fetcher: Fetcher, token: str, horse_id: str,
                  cache: dict) -> dict:
        if not horse_id:
            return {}
        if horse_id not in cache:
            try:
                detail = self._get(fetcher, token, pageaction="jsonhorse", horseid=horse_id)
            except Exception as exc:  # noqa: BLE001 - pedigree is a nice-to-have
                LOG.debug("QREC pedigree lookup failed for %s: %s", horse_id, exc)
                detail = None
            cache[horse_id] = {
                "sire": (detail or {}).get("sire", ""),
                "dam": (detail or {}).get("dam", ""),
            }
        return cache[horse_id]


def _runner_rows(detail: Any) -> list[dict]:
    """The runner list is called ``result`` for a run race and ``entries`` before."""
    if not isinstance(detail, dict):
        return []
    for key in ("result", "entries", "runners", "racecard"):
        rows = detail.get(key)
        if isinstance(rows, list) and rows:
            return [row for row in rows if isinstance(row, dict)]
    return []


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _course_from_meeting(name: str) -> str:
    for course in COURSES:
        if course.lower() in (name or "").lower():
            return course.upper()
    return "AL RAYYAN"


def _title_race(name: str) -> str:
    """``THOROUGHBRED HANDICAP 45-65 (Class 6)`` reads better in title case."""
    name = collapse_space(name)
    if name and name == name.upper():
        return name.title().replace("Pa ", "PA ")
    return name


def _clean_jockey(value: str) -> str:
    """Drop the claim QREC appends: ``Salman Al-Hajri* (-2.5kg)``."""
    return title_name(re.sub(r"\*?\s*\(-?[\d.]+\s*kg\)\s*$", "", collapse_space(value)))
