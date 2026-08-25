"""Equibase -- North American racing, read from the Wathnan owner profile.

Equibase is fronted by Imperva, which blocks data-centre traffic; the adapter
therefore follows the same escalation as Racing Post (plain HTTP, then a
browser, then a saved snapshot) and honours the five second crawl delay the
site's robots.txt asks for.

Equibase publishes *entries* and *results* on the owner page.  Only future
dates are kept, and North American distances (``Six Furlongs``, ``1 1/16
Miles``) and local post times are converted to the report's units.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Iterator

from bs4 import BeautifulSoup

from ..models import Breed, Race, Runner, Status, normalise_key
from ..normalise import (
    COURSE_TIMEZONES,
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

BASE = "https://www.equibase.com"
OWNER_URL = BASE + "/profiles/Results.cfm?type=People&searchType=O&eID={owner_id}"

COLUMNS = (
    Column("date", "date", required=True),
    Column("course", "track", "course", required=True),
    Column("race", "race", "race type", "conditions"),
    Column("distance", "distance", "dist"),
    Column("time", "post time", "time"),
    Column("horse", "horse", required=True),
    Column("pedigree", "pedigree", "sire/dam", "breeding"),
    Column("sire", "sire"),
    Column("dam", "dam"),
    Column("trainer", "trainer"),
    Column("jockey", "jockey"),
)

#: Equibase writes dates in US order.
DATE_PATTERNS = ("%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d")


class EquibaseSource(Source):
    name = "equibase"
    label = "Equibase (North America)"
    home = "https://www.equibase.com/profiles/Results.cfm?type=People&searchType=O&eID=2304655"

    def fetch(self, fetcher: Fetcher) -> list[Race]:
        """The owner profile when reachable, otherwise the Sporting Life feed.

        The fallback carries the major North American tracks with owners named
        on every ride; smaller US tracks are outside its coverage, so the
        native profile stays the preferred route wherever the runner's IP is
        acceptable to Equibase's WAF.
        """
        try:
            return self._from_equibase(fetcher)
        except Exception as exc:  # noqa: BLE001 - swap feeds, keep the data
            LOG.warning("Equibase unreachable (%s); using the Sporting Life "
                        "feed for North America instead", exc)
            from .sportinglife import NORTH_AMERICA, sweep
            return sweep(self, fetcher, countries=NORTH_AMERICA)

    def _from_equibase(self, fetcher: Fetcher) -> list[Race]:
        url = OWNER_URL.format(owner_id=self.config.source_ids.get("equibase", "2304655"))
        soup = BeautifulSoup(self._load(fetcher, url), "lxml")
        records = list(self._records(soup))
        if not records:
            raise FetchError(
                "no runners found on the Equibase owner page -- Imperva may have served "
                "a challenge; retry with --browser or save the page into snapshots/ and "
                "run with --offline")
        return list(_group(records, url, self.name))

    def _load(self, fetcher: Fetcher, url: str) -> str:
        try:
            body = fetcher.get(url)
            if not _looks_blocked(body):
                return body
            # Never keep a challenge page: it would poison later --offline runs.
            fetcher.discard(url)
            LOG.info("Equibase served a challenge page; retrying in a browser")
        except FetchError as exc:
            LOG.info("Equibase plain fetch failed (%s); retrying in a browser", exc)
        return fetcher.get(url, browser=True, refresh=True)

    def _records(self, soup: BeautifulSoup) -> Iterator[dict]:
        for table, mapping in find_tables(soup, COLUMNS):
            for record in rows(table, mapping):
                date = _parse_date(record.get("date"))
                if date is None or not self.config.covers(date):
                    continue
                sire, dam = record.get("sire", ""), record.get("dam", "")
                if not sire and record.get("pedigree"):
                    sire, dam = split_pedigree(record["pedigree"])
                yield {**record, "date": date, "sire": sire, "dam": dam}


def _group(records: list[dict], url: str, source: str) -> Iterator[Race]:
    grouped: dict[tuple, dict] = {}
    for record in records:
        course = title_course(record.get("course", ""))
        local_time = parse_time(record.get("time"))
        race_type = collapse_space(record.get("race", ""))
        key = (record["date"], normalise_key(course), race_type, local_time)
        bucket = grouped.setdefault(key, {
            "date": record["date"], "course": course, "race": race_type,
            "distance": parse_distance(record.get("distance")),
            "time": local_time, "runners": [],
        })
        bucket["runners"].append(Runner(
            horse=clean_horse_name(record.get("horse", "")),
            sire=clean_pedigree_name(record.get("sire", "")),
            dam=clean_pedigree_name(record.get("dam", "")),
            trainer=title_name(record.get("trainer", "")),
            jockey=title_name(record.get("jockey", "")),
        ))

    for bucket in grouped.values():
        tz = COURSE_TIMEZONES.get(bucket["course"].upper())
        yield Race(
            date=bucket["date"],
            course=bucket["course"],
            race_type=bucket["race"],
            distance_furlongs=bucket["distance"],
            off_time_uk=to_uk_time(bucket["time"], bucket["date"], tz=tz, country="US"),
            breed=Breed.THOROUGHBRED,
            status=Status.ENTERED,
            runners=tuple(bucket["runners"]),
            source=source,
            source_url=url,
        )


def _looks_blocked(body: str) -> bool:
    lowered = (body or "")[:6000].lower()
    return "pardon our interruption" in lowered or "imperva" in lowered


def _parse_date(value: str | None) -> dt.date | None:
    text = collapse_space(value or "")
    if not text:
        return None
    match = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}|\w+ \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2}", text)
    if match:
        text = match.group(0)
    for pattern in DATE_PATTERNS:
        try:
            return dt.datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None
