from dataclasses import dataclass
from datetime import date, timedelta

from dailybreezeup.models import RaceCard, RaceResult

from . import francegalop, theracingapi


@dataclass
class GatheredRaces:
    declarations: list[RaceCard]
    entries: list[RaceCard]
    results: list[RaceResult]


def gather(today: date, *, entries_days: int = 7) -> GatheredRaces:
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    entries_end = today + timedelta(days=entries_days)

    decls: list[RaceCard] = []
    entries: list[RaceCard] = []
    results: list[RaceResult] = []

    for d in (today, tomorrow):
        decls.extend(theracingapi.fetch_declarations(d))
        decls.extend(francegalop.fetch_declarations(d))

    cursor = tomorrow + timedelta(days=1)
    while cursor <= entries_end:
        entries.extend(theracingapi.fetch_entries(cursor))
        entries.extend(francegalop.fetch_entries(cursor))
        cursor += timedelta(days=1)

    results.extend(theracingapi.fetch_results(yesterday))
    results.extend(francegalop.fetch_results(yesterday))

    return GatheredRaces(declarations=decls, entries=entries, results=results)
