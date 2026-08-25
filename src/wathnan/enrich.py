"""Reconcile names across sources once every feed has reported.

Two things the feeds disagree about are settled here, after de-duplication so
each horse is only decided once:

* **Horse suffixes.** The report prints ``OLD IS GOLD (IRE)``.  France Galop,
  Deutscher Galopp and QREC name the country; the GB/IRE racecard feed does
  not, so it comes from the registry, or from a lookup for a horse not yet
  listed.
* **Trainer and jockey names.** One feed says ``W J Haggas``, another
  ``William Haggas``.  Both resolve to the canonical spelling.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from .canonical import canonical_jockey, canonical_trainer
from .models import Race, Runner, normalise_key
from .normalise import COUNTRY_SUFFIX, clean_horse_name

LOG = logging.getLogger(__name__)

HORSES_PATH = Path(__file__).resolve().parent / "data" / "horses.json"


def load_horses() -> dict[str, str]:
    """``{normalised horse name: country}`` from the shipped registry."""
    try:
        data = json.loads(HORSES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # pragma: no cover - packaging error
        LOG.warning("horse registry unreadable (%s); suffixes will be looked up", exc)
        return {}
    return {normalise_key(name): country
            for name, country in (data.get("horses") or {}).items()}


def canonicalise(races: Sequence[Race], horses: dict[str, str] | None = None) -> list[Race]:
    """Apply the registries to every runner."""
    known = load_horses() if horses is None else horses
    return [replace(race, runners=tuple(_runner(runner, known) for runner in race.runners))
            for race in races]


def _runner(runner: Runner, horses: dict[str, str]) -> Runner:
    return replace(
        runner,
        horse=_with_suffix(runner.horse, horses),
        trainer=canonical_trainer(runner.trainer),
        jockey=canonical_jockey(runner.jockey),
    )


def _with_suffix(horse: str, horses: dict[str, str]) -> str:
    """Add the country in brackets when the feed left it off."""
    name = clean_horse_name(horse)
    if not name or COUNTRY_SUFFIX.search(name):
        return name
    country = horses.get(normalise_key(name))
    return f"{name} ({country})" if country else name


def missing_suffixes(races: Sequence[Race]) -> set[str]:
    """Normalised names of runners still printing without a country."""
    return {normalise_key(runner.horse)
            for race in races for runner in race.runners
            if runner.horse and not COUNTRY_SUFFIX.search(runner.horse)}


def fill_suffixes(races: Sequence[Race], fetcher, learn: bool = False) -> list[Race]:
    """Look up any suffix the registry does not know, and optionally record it."""
    from .sources import suffixes as lookup_source

    wanted = missing_suffixes(races)
    if not wanted:
        return list(races)

    covered = [race for race in races if lookup_source.covers(race.course)]
    if not covered:
        return list(races)

    try:
        found = lookup_source.lookup(fetcher, covered, wanted)
    except Exception as exc:  # noqa: BLE001 - a suffix is never worth a failed run
        LOG.warning("suffix lookup failed: %s", exc)
        return list(races)
    if not found:
        return list(races)

    LOG.info("looked up %d horse suffix(es): %s", len(found), ", ".join(sorted(found)))
    if learn:
        _remember(races, found)
    return canonicalise(races, {**load_horses(), **found})


def _remember(races: Sequence[Race], found: dict[str, str]) -> None:
    """Write newly discovered suffixes back into the shipped registry."""
    display = {normalise_key(runner.horse): clean_horse_name(runner.horse)
               for race in races for runner in race.runners}
    try:
        data = json.loads(HORSES_PATH.read_text(encoding="utf-8"))
        horses = data.setdefault("horses", {})
        for key, country in found.items():
            name = display.get(key)
            if name:
                horses[name.title()] = country
        data["horses"] = {name: horses[name] for name in sorted(horses)}
        HORSES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        LOG.info("recorded %d suffix(es) in %s", len(found), HORSES_PATH)
    except OSError as exc:
        LOG.warning("could not update the horse registry: %s", exc)
