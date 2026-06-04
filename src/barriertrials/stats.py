"""Season-to-date aggregations for the evening results email.

Pure functions over rows from the ``results_archive`` table. The per-rating band
buckets reuse ``dailybreezeup.stats.aggregate_by_band`` (which is already keyed on
an arbitrary ``rating_key``); only the per-horse leaderboard is reimplemented here
because this cohort has no sale/lot identity — a horse is keyed by its learned uid
or, failing that, its watchlist ``horse_key``.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dailybreezeup.stats import LOW_N_THRESHOLD, aggregate_by_band

_PLACED_POSITIONS = frozenset({"2", "3"})


@dataclass(frozen=True)
class HorseSummary:
    horse_name: str
    rating: float | None
    peak_rpr: int | None
    n_runs: int
    n_wins: int
    n_placed: int
    status_label: str
    status_kind: str  # "won" | "placed" | "ran" | "none"


def _get(row: Mapping[str, Any], key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
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


def _summarize_horse(runs: list[Mapping[str, Any]], rating_key: str) -> HorseSummary:
    ratings = [_get(r, rating_key) for r in runs if _get(r, rating_key) is not None]
    rating = max(ratings) if ratings else None
    rprs = [_get(r, "rpr") for r in runs if _get(r, "rpr") is not None]
    peak_rpr = max(rprs) if rprs else None
    wins = sum(1 for r in runs if _get(r, "finishing_position") == "1")
    placed = sum(1 for r in runs if _get(r, "finishing_position") in _PLACED_POSITIONS)
    status_label, status_kind = _status(runs)
    latest = max(runs, key=lambda r: str(_get(r, "race_date") or ""))
    horse_name = _get(latest, "horse_name") or "(unknown)"
    return HorseSummary(
        horse_name=horse_name,
        rating=float(rating) if rating is not None else None,
        peak_rpr=peak_rpr,
        n_runs=len(runs),
        n_wins=wins,
        n_placed=placed,
        status_label=status_label,
        status_kind=status_kind,
    )


def top_rated(
    rows: Iterable[Mapping[str, Any]],
    rating_key: str,
    *,
    limit: int = 10,
) -> list[HorseSummary]:
    """Top-N horses by ``rating_key``. Unrated horses are dropped.

    Ties break by peak RPR (higher first), then run count, then name.
    """
    by_horse: dict[Any, list[Mapping[str, Any]]] = {}
    for row in rows:
        uid = _get(row, "horse_uid")
        key = ("uid", int(uid)) if uid is not None else ("key", _get(row, "horse_key"))
        by_horse.setdefault(key, []).append(row)
    summaries = [_summarize_horse(runs, rating_key) for runs in by_horse.values()]
    summaries = [s for s in summaries if s.rating is not None]
    summaries.sort(
        key=lambda s: (-(s.rating or 0.0), -(s.peak_rpr or 0), -s.n_runs, s.horse_name)
    )
    return summaries[:limit]


def build_summary(
    rows: Iterable[Mapping[str, Any]],
    rating_columns: Sequence[str],
) -> dict[str, Any] | None:
    """Assemble per-rating bands and leaderboards for the evening email.

    Returns ``None`` when there are no rows so the template can gate the whole
    block. ``rows`` must expose each rating under its column-header key (the
    daily job merges ``ratings_json`` into the archive row before calling this).
    """
    rows = list(rows)
    if not rows:
        return None
    by_rating = [
        {
            "label": col,
            "bands": aggregate_by_band(rows, col),
            "top": top_rated(rows, col),
        }
        for col in rating_columns
    ]
    return {
        "total_runs": len(rows),
        "low_n_threshold": LOW_N_THRESHOLD,
        "by_rating": by_rating,
    }
