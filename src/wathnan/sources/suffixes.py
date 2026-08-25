"""Look up a horse's country of foaling for the report's name suffix.

The GB and Irish racecard feed prints bare horse names, but the report shows
``OLD IS GOLD (IRE)``.  irishracing.com links every runner as
``/horse/Old-Is-Gold-IRE/1184426``, so the suffix can be read straight off a
meeting's race pages.

Most horses are already in ``wathnan/data/horses.json``; this is only consulted
for ones that are not, and every failure is silent -- a missing suffix costs a
pair of brackets, never the run.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Iterable

from ..models import Race, normalise_key
from ..normalise import ordinal
from .base import Fetcher, FetchError

LOG = logging.getLogger(__name__)

BASE = "https://www.irishracing.com"
DAY_URL = BASE + "/racecards/{day}"

HORSE_LINK = re.compile(r'href="/horse/([^"/]+)/\d+"')
#: Only pages for the meeting we asked about, so one fetch per race.
RACE_LINK = r'href="(/racecards/{day}/([^"/]+)/(\d{{3,4}}))"'

#: Courses this source covers; anything else is left to its own feed.
BRITISH_AND_IRISH = frozenset({
    "AINTREE", "ASCOT", "AYR", "BANGOR", "BATH", "BEVERLEY", "BRIGHTON",
    "CARLISLE", "CARTMEL", "CATTERICK", "CHELMSFORD CITY", "CHELTENHAM",
    "CHEPSTOW", "CHESTER", "DONCASTER", "EPSOM", "EPSOM DOWNS", "EXETER",
    "FAKENHAM", "FFOS LAS", "FONTWELL", "GOODWOOD", "HAMILTON", "HAYDOCK",
    "HEREFORD", "HEXHAM", "HUNTINGDON", "KELSO", "KEMPTON", "LEICESTER",
    "LINGFIELD", "LUDLOW", "MARKET RASEN", "MUSSELBURGH", "NEWBURY",
    "NEWCASTLE", "NEWMARKET", "NEWTON ABBOT", "NOTTINGHAM", "PERTH",
    "PLUMPTON", "PONTEFRACT", "REDCAR", "RIPON", "SALISBURY", "SANDOWN",
    "SEDGEFIELD", "SOUTHWELL", "STRATFORD", "TAUNTON", "THIRSK", "UTTOXETER",
    "WARWICK", "WETHERBY", "WINCANTON", "WINDSOR", "WOLVERHAMPTON",
    "WORCESTER", "YARMOUTH", "YORK",
    "BALLINROBE", "BELLEWSTOWN", "CORK", "CURRAGH", "DOWN ROYAL",
    "DOWNPATRICK", "DUNDALK", "FAIRYHOUSE", "GALWAY", "GOWRAN PARK",
    "KILBEGGAN", "KILLARNEY", "LAYTOWN", "LEOPARDSTOWN", "LIMERICK",
    "LISTOWEL", "NAAS", "NAVAN", "PUNCHESTOWN", "ROSCOMMON", "SLIGO",
    "THURLES", "TIPPERARY", "TRAMORE", "WEXFORD",
})


def covers(course: str) -> bool:
    return (course or "").upper() in BRITISH_AND_IRISH


def lookup(fetcher: Fetcher, races: Iterable[Race],
           wanted: set[str]) -> dict[str, str]:
    """Return ``{horse key: country}`` for the horses still missing a suffix.

    Only meetings that actually stage one of ``races`` are fetched, and the
    sweep stops as soon as every wanted horse is accounted for.
    """
    found: dict[str, str] = {}
    meetings = _meetings(races)
    for date, courses in sorted(meetings.items()):
        if not wanted - set(found):
            break
        day = _day_slug(date)
        try:
            index = fetcher.get(DAY_URL.format(day=day))
        except FetchError as exc:
            LOG.debug("irishracing day %s unavailable: %s", day, exc)
            continue
        pattern = re.compile(RACE_LINK.format(day=re.escape(day)))
        for path, course, _time in sorted(set(pattern.findall(index))):
            if normalise_key(course) not in courses:
                continue
            if not wanted - set(found):
                break
            try:
                page = fetcher.get(BASE + path)
            except FetchError as exc:
                LOG.debug("irishracing race %s unavailable: %s", path, exc)
                continue
            found.update(_suffixes(page))
    return {key: value for key, value in found.items() if key in wanted}


def _meetings(races: Iterable[Race]) -> dict[dt.date, set[str]]:
    meetings: dict[dt.date, set[str]] = {}
    for race in races:
        if covers(race.course):
            meetings.setdefault(race.date, set()).add(normalise_key(race.course))
    return meetings


def _suffixes(page: str) -> dict[str, str]:
    """Read ``/horse/Old-Is-Gold-IRE/1184426`` into ``{"oldisgold": "IRE"}``."""
    found: dict[str, str] = {}
    for slug in set(HORSE_LINK.findall(page)):
        name, _, country = slug.rpartition("-")
        if not name or not country.isalpha() or country != country.upper():
            continue
        found[normalise_key(name.replace("-", " "))] = country
    return found


def _day_slug(date: dt.date) -> str:
    """``Thu-20th-Aug-2026`` -- the form irishracing uses in its URLs."""
    return f"{date:%a}-{ordinal(date.day).lower()}-{date:%b}-{date.year}"
