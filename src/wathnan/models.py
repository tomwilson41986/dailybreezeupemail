"""Normalised domain model shared by every source adapter."""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum


class Breed(StrEnum):
    """Breed of the race. Arabian races are rendered in italics on the report."""

    THOROUGHBRED = "thoroughbred"
    ARABIAN = "arabian"


class Status(StrEnum):
    """How firm a runner is.

    ``DECLARED`` runners have passed the declaration stage and have a confirmed
    time and (usually) a jockey.  ``ENTERED`` horses are still at the entry
    stage and may not run.
    """

    DECLARED = "declared"
    ENTERED = "entered"


TBC = "TBC"


@dataclass(frozen=True)
class Runner:
    """A single Wathnan-owned horse in a single race."""

    horse: str
    sire: str = ""
    dam: str = ""
    trainer: str = ""
    jockey: str = ""

    def display_jockey(self) -> str:
        """Feeds write an unfilled ride as blank, ``-`` or ``TBC``; print ``TBC``."""
        jockey = (self.jockey or "").strip()
        return TBC if jockey in ("", "-", "\u2013", "\u2014", "--") else jockey


@dataclass(frozen=True)
class Race:
    """A race containing at least one Wathnan runner."""

    date: dt.date
    course: str
    race_type: str
    distance_furlongs: float | None = None
    off_time_uk: dt.time | None = None
    breed: Breed = Breed.THOROUGHBRED
    status: Status = Status.ENTERED
    runners: tuple[Runner, ...] = field(default_factory=tuple)
    source: str = ""
    source_url: str = ""

    # -- derived display values -------------------------------------------------
    @property
    def key(self) -> tuple:
        """Identity used for de-duplicating the same race across two sources."""
        return (self.date, normalise_key(self.course), round(self.distance_furlongs or -1, 1),
                self.off_time_uk)

    def merged_with(self, other: Race) -> Race:
        """Combine two views of the same race, preferring the richer values."""
        runners: dict[str, Runner] = {}
        for runner in (*self.runners, *other.runners):
            existing = runners.get(horse_key(runner.horse))
            runners[horse_key(runner.horse)] = (
                _richer_runner(existing, runner) if existing else runner
            )
        return replace(
            self,
            race_type=_longer(self.race_type, other.race_type),
            distance_furlongs=self.distance_furlongs or other.distance_furlongs,
            off_time_uk=self.off_time_uk or other.off_time_uk,
            # A declaration always beats an entry.
            status=Status.DECLARED
            if Status.DECLARED in (self.status, other.status)
            else Status.ENTERED,
            runners=tuple(runners.values()),
            source=_longer(self.source, other.source),
        )


def _longer(a: str, b: str) -> str:
    """Prefer the value that actually carries information."""
    a, b = (a or "").strip(), (b or "").strip()
    if not a:
        return b
    if not b:
        return a
    return a if len(a) >= len(b) else b


def _richer_runner(a: Runner, b: Runner) -> Runner:
    return Runner(
        horse=_longer(a.horse, b.horse),
        sire=_longer(a.sire, b.sire),
        dam=_longer(a.dam, b.dam),
        trainer=_longer(a.trainer, b.trainer),
        # A named jockey beats a blank or a "TBC".
        jockey=_prefer_named(a.jockey, b.jockey),
    )


def _prefer_named(a: str, b: str) -> str:
    a, b = (a or "").strip(), (b or "").strip()
    for value in (a, b):
        if value and value.upper() != TBC:
            return value
    return a or b


def horse_key(name: str) -> str:
    """Horse identity for cross-source matching.

    Some feeds omit the country suffix (``SHARAH`` vs ``SHARAH (FR)``), so it
    is ignored when deciding whether two rows are the same horse.
    """
    return normalise_key(re.sub(r"\s*\([A-Z]{2,3}\)\s*$", "", name or "", flags=re.I))


def normalise_key(value: str) -> str:
    """Casefolded, accent-stripped, punctuation-free key for fuzzy matching."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", stripped.lower())


def dedupe_races(races: Iterable[Race]) -> list[Race]:
    """Merge races that two sources both reported.

    Sources overlap heavily -- a French Wathnan runner shows up on both Racing
    Post and France Galop -- so identical races are merged rather than listed
    twice.
    """
    merged: dict[tuple, Race] = {}
    for race in races:
        key = race.key
        horses = {horse_key(r.horse) for r in race.runners}
        match = merged.get(key)
        if match is None:
            # Fall back to a horse-based match when the feeds disagree about a
            # post time or distance: the same course on the same day with a
            # shared runner is the same race.
            for existing_key, existing in merged.items():
                if (existing.date == race.date
                        and normalise_key(existing.course) == normalise_key(race.course)
                        and horses & {horse_key(r.horse) for r in existing.runners}):
                    match, key = existing, existing_key
                    break
        merged[key] = match.merged_with(race) if match else race
    return sorted(merged.values(), key=_race_sort_key)


def _race_sort_key(race: Race) -> tuple:
    return (
        race.date,
        race.course.upper(),
        race.off_time_uk or dt.time(23, 59),
        race.race_type.upper(),
    )


def group_rows(races: Sequence[Race]) -> Iterator[tuple[Race, Runner, dict[str, bool]]]:
    """Yield one row per runner, flagging which grouped cells to print.

    The report only prints the date once per day and the course once per course
    within that day, exactly like the source spreadsheet.
    """
    last_date: dt.date | None = None
    last_course: str | None = None
    for race in races:
        show_date = race.date != last_date
        show_course = show_date or normalise_key(race.course) != (last_course or "")
        for index, runner in enumerate(race.runners):
            yield race, runner, {
                "date": show_date and index == 0,
                "course": show_course and index == 0,
                "race": index == 0,
            }
        last_date = race.date
        last_course = normalise_key(race.course)
