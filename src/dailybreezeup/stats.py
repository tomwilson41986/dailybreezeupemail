"""Season-to-date aggregations for the evening results email.

Pure functions over rows from the ``results_archive`` table. The bands
mirror the thresholds in the email template's ``rating_tile`` macro
(``templates/email.html.j2``) so the summary tables and the per-horse
tiles agree on what counts as a "high breeze" or "high precocity" horse.

Confidence cue: cells with fewer than :data:`LOW_N_THRESHOLD` runners are
flagged ``low_n=True``; the template renders those rows in muted/italic
style so a 1-from-2 strike rate doesn't visually dominate a 38-from-150.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

LOW_N_THRESHOLD = 10

BANDS: tuple[str, ...] = ("≥90", "70–89", "50–69", "<50", "unrated")

_PLACED_POSITIONS = frozenset({"2", "3"})


@dataclass(frozen=True)
class BandStat:
    label: str
    n_runners: int
    n_winners: int
    strike_rate: float
    avg_rpr: float | None
    low_n: bool


@dataclass(frozen=True)
class SaleStat:
    sale_label: str
    sale_short: str | None
    sale_year: int
    n_runners: int
    n_winners: int
    strike_rate: float
    avg_rpr: float | None
    low_n: bool


@dataclass(frozen=True)
class HorseSummary:
    horse_name: str
    lot_label: str
    sale_label: str
    rating: float | None
    peak_rpr: int | None
    n_runs: int
    n_wins: int
    n_placed: int
    status_label: str
    status_kind: str  # "won" | "placed" | "ran" | "none"


def band_for(rating: float | None) -> str:
    if rating is None:
        return "unrated"
    if rating >= 90:
        return "≥90"
    if rating >= 70:
        return "70–89"
    if rating >= 50:
        return "50–69"
    return "<50"


def _get(row: Mapping[str, Any], key: str) -> Any:
    # Accepts both dicts and sqlite3.Row (which raises KeyError on missing keys).
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _sale_label(sale_short: str | None, sale_year: int, sale_name: str | None) -> str:
    if sale_short:
        return f"{sale_short} {sale_year}"
    return sale_name or f"Sale {sale_year}"


def _make_band_stat(label: str, group: list[Mapping[str, Any]]) -> BandStat:
    n = len(group)
    wins = sum(1 for r in group if _get(r, "finishing_position") == "1")
    rprs = [_get(r, "rpr") for r in group if _get(r, "rpr") is not None]
    avg = sum(rprs) / len(rprs) if rprs else None
    sr = wins / n if n else 0.0
    return BandStat(
        label=label,
        n_runners=n,
        n_winners=wins,
        strike_rate=sr,
        avg_rpr=avg,
        low_n=n < LOW_N_THRESHOLD,
    )


def aggregate_by_band(rows: Iterable[Mapping[str, Any]], rating_key: str) -> list[BandStat]:
    """Bucket rows by rating band and aggregate (preserves band order)."""
    bucket: dict[str, list[Mapping[str, Any]]] = {b: [] for b in BANDS}
    for row in rows:
        bucket[band_for(_get(row, rating_key))].append(row)
    return [_make_band_stat(label, bucket[label]) for label in BANDS if bucket[label]]


def aggregate_by_sale(rows: Iterable[Mapping[str, Any]]) -> list[SaleStat]:
    """One row per ``(sale_short, sale_year)``, sorted by strongest strike
    rate first (with low-n sales still listed but flagged)."""
    bucket: dict[tuple[str | None, int], list[Mapping[str, Any]]] = {}
    for row in rows:
        year = _get(row, "sale_year")
        if year is None:
            continue
        key = (_get(row, "sale_short"), int(year))
        bucket.setdefault(key, []).append(row)
    out: list[SaleStat] = []
    for (sale_short, sale_year), group in bucket.items():
        n = len(group)
        wins = sum(1 for r in group if _get(r, "finishing_position") == "1")
        rprs = [_get(r, "rpr") for r in group if _get(r, "rpr") is not None]
        avg = sum(rprs) / len(rprs) if rprs else None
        sale_name = next((_get(r, "sale_name") for r in group if _get(r, "sale_name")), None)
        out.append(
            SaleStat(
                sale_label=_sale_label(sale_short, sale_year, sale_name),
                sale_short=sale_short,
                sale_year=sale_year,
                n_runners=n,
                n_winners=wins,
                strike_rate=wins / n if n else 0.0,
                avg_rpr=avg,
                low_n=n < LOW_N_THRESHOLD,
            )
        )
    out.sort(key=lambda s: (-s.strike_rate, -s.n_runners, s.sale_label))
    return out


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


def _summarize_horse(
    runs: list[Mapping[str, Any]], rating_key: str
) -> HorseSummary:
    ratings = [_get(r, rating_key) for r in runs if _get(r, rating_key) is not None]
    rating = max(ratings) if ratings else None
    rprs = [_get(r, "rpr") for r in runs if _get(r, "rpr") is not None]
    peak_rpr = max(rprs) if rprs else None
    wins = sum(1 for r in runs if _get(r, "finishing_position") == "1")
    placed = sum(1 for r in runs if _get(r, "finishing_position") in _PLACED_POSITIONS)
    status_label, status_kind = _status(runs)
    # Pick representative horse / lot / sale labels from the most recent run
    # (archive rows carry the snapshot the email was sent with, so any of
    # them is fine — recent feels right when names update).
    latest = max(runs, key=lambda r: str(_get(r, "race_date") or ""))
    horse_name = _get(latest, "horse_name") or ""
    lot_no = _get(latest, "lot_no")
    lot_label = f"Lot {lot_no}" if lot_no is not None else ""
    sale_label = _sale_label(
        _get(latest, "sale_short"),
        int(_get(latest, "sale_year") or 0),
        _get(latest, "sale_name"),
    )
    if not horse_name:
        horse_name = f"{lot_label} (unnamed)" if lot_label else "(unnamed)"
    return HorseSummary(
        horse_name=horse_name,
        lot_label=lot_label,
        sale_label=sale_label,
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
    """Top-N horses by ``rating_key``. Unrated horses are dropped from this list.

    Ties are broken by peak RPR (higher first), then run count, then name.
    """
    by_horse: dict[Any, list[Mapping[str, Any]]] = {}
    for row in rows:
        uid = _get(row, "horse_uid")
        key = ("uid", int(uid)) if uid is not None else ("lot", _get(row, "lot_id"))
        by_horse.setdefault(key, []).append(row)
    summaries = [_summarize_horse(runs, rating_key) for runs in by_horse.values()]
    summaries = [s for s in summaries if s.rating is not None]
    summaries.sort(
        key=lambda s: (-(s.rating or 0.0), -(s.peak_rpr or 0), -s.n_runs, s.horse_name)
    )
    return summaries[:limit]


def build_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Assemble every aggregation the email template needs.

    Returns ``None`` when there are no rows — the template gates the whole
    section on truthy ``season_summary`` so a quiet season just doesn't
    render the block.
    """
    rows = list(rows)
    if not rows:
        return None
    return {
        "total_runs": len(rows),
        "low_n_threshold": LOW_N_THRESHOLD,
        "by_breeze_band": aggregate_by_band(rows, "sheet_breeze_rating"),
        "by_precocity_band": aggregate_by_band(rows, "sheet_precocity_rating"),
        "by_sale": aggregate_by_sale(rows),
        "top_breeze": top_rated(rows, "sheet_breeze_rating"),
        "top_precocity": top_rated(rows, "sheet_precocity_rating"),
    }
