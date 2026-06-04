"""Season-to-date aggregations for the barrier-trial emails.

Pure functions over rows from the ``results_archive`` table. Produces two views:

* **per-rating bands** — strike-rate / avg-RPR bucketed by each rating column,
  reusing ``dailybreezeup.stats.aggregate_by_band`` (already keyed on an
  arbitrary ``rating_key``);
* **per-horse records** — every tracked horse that has run, with its individual
  runs and a small summary, for the "historic results tracker".

Rows must expose each rating under its column-header key (the daily job merges
``ratings_json`` into the archive row before calling in).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from dailybreezeup.stats import LOW_N_THRESHOLD, aggregate_by_band

_PLACED_POSITIONS = frozenset({"2", "3"})


@dataclass(frozen=True)
class HorseRun:
    race_date: date | None
    course: str
    race_name: str
    finishing_position: str | None
    total_runners: int | None
    sp: str | None
    rpr: int | None


@dataclass(frozen=True)
class HorseRecord:
    horse_key: str
    horse_name: str
    ratings: dict[str, float | None]
    n_runs: int
    n_wins: int
    n_places: int
    peak_rpr: int | None
    status_label: str
    status_kind: str  # "won" | "placed" | "ran" | "none"
    runs: list[HorseRun]


def _get(row: Mapping[str, Any], key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _to_date(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _status(runs: list[Mapping[str, Any]]) -> tuple[str, str]:
    wins = sum(1 for r in runs if _get(r, "finishing_position") == "1")
    placed = sum(1 for r in runs if _get(r, "finishing_position") in _PLACED_POSITIONS)
    finished = sum(
        1 for r in runs
        if (pos := _get(r, "finishing_position")) and str(pos).isdigit()
    )
    if wins:
        return (f"WON × {wins}" if wins > 1 else "WON", "won")
    if placed:
        return ("PLACED", "placed")
    if finished:
        return (f"RAN × {finished}" if finished > 1 else "RAN", "ran")
    return ("—", "none")


def _record(runs: list[Mapping[str, Any]], rating_columns: Sequence[str]) -> HorseRecord:
    rprs = [_get(r, "rpr") for r in runs if _get(r, "rpr") is not None]
    peak_rpr = max(rprs) if rprs else None
    wins = sum(1 for r in runs if _get(r, "finishing_position") == "1")
    placed = sum(1 for r in runs if _get(r, "finishing_position") in _PLACED_POSITIONS)
    status_label, status_kind = _status(runs)
    ordered = sorted(runs, key=lambda r: str(_get(r, "race_date") or ""))
    latest = ordered[-1]
    horse_name = _get(latest, "horse_name") or "(unknown)"
    ratings = {col: _get(latest, col) for col in rating_columns}
    run_objs = [
        HorseRun(
            race_date=_to_date(_get(r, "race_date")),
            course=_get(r, "course") or "",
            race_name=_get(r, "race_name") or "",
            finishing_position=_get(r, "finishing_position"),
            total_runners=_get(r, "total_runners"),
            sp=_get(r, "sp"),
            rpr=_get(r, "rpr"),
        )
        for r in ordered
    ]
    return HorseRecord(
        horse_key=str(_get(latest, "horse_key") or ""),
        horse_name=horse_name,
        ratings=ratings,
        n_runs=len(runs),
        n_wins=wins,
        n_places=placed,
        peak_rpr=peak_rpr,
        status_label=status_label,
        status_kind=status_kind,
        runs=run_objs,
    )


def horse_records(
    rows: Iterable[Mapping[str, Any]],
    rating_columns: Sequence[str],
) -> list[HorseRecord]:
    """One ``HorseRecord`` per tracked horse that has run, sorted by the primary
    rating (first column) descending, then name."""
    by_horse: dict[Any, list[Mapping[str, Any]]] = {}
    for row in rows:
        uid = _get(row, "horse_uid")
        key = ("uid", int(uid)) if uid is not None else ("key", _get(row, "horse_key"))
        by_horse.setdefault(key, []).append(row)
    records = [_record(runs, rating_columns) for runs in by_horse.values()]
    primary = rating_columns[0] if rating_columns else None

    def sort_key(rec: HorseRecord) -> tuple[float, str]:
        rating = rec.ratings.get(primary) if primary else None
        return (-(rating or 0.0), rec.horse_name)

    records.sort(key=sort_key)
    return records


def build_tracker(
    rows: Iterable[Mapping[str, Any]],
    rating_columns: Sequence[str],
) -> dict[str, Any] | None:
    """Assemble the season-to-date tracker: per-rating bands + per-horse records.

    Returns ``None`` when there are no rows so the template can gate the block.
    """
    rows = list(rows)
    if not rows:
        return None
    by_rating = [
        {"label": col, "bands": aggregate_by_band(rows, col)}
        for col in rating_columns
    ]
    return {
        "total_runs": len(rows),
        "low_n_threshold": LOW_N_THRESHOLD,
        "by_rating": by_rating,
        "horses": horse_records(rows, rating_columns),
    }
