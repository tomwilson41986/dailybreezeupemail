"""The evening results run must report on its cron slot's day, not on the wall
clock when the runner happens to start.

GitHub Actions cron is best-effort. On 6 Aug 2026 the 21:00 UTC slot started at
00:58 UTC on the 7th, so the wall clock had already rolled over and the job
asked Racing Post for a day that hadn't been raced.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from barriertrials import daily


def _utc(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_run_date_anchors_to_slot_when_cron_crosses_midnight():
    got = daily._results_run_date(
        daily.EVENING_SLOT_UTC, now=_utc(2026, 8, 7, 0, 58)
    )
    assert got == date(2026, 8, 6)


def test_run_date_is_today_when_cron_fires_on_time():
    got = daily._results_run_date(
        daily.EVENING_SLOT_UTC, now=_utc(2026, 8, 5, 22, 2)
    )
    assert got == date(2026, 8, 5)


def test_run_date_anchors_in_winter_when_uk_is_on_gmt():
    """Outside BST the slot lands at 21:00 UK, so the anchoring has to survive
    the offset change rather than assuming a fixed +1."""
    assert daily._results_run_date(
        daily.EVENING_SLOT_UTC, now=_utc(2026, 1, 15, 21, 30)
    ) == date(2026, 1, 15)
    assert daily._results_run_date(
        daily.EVENING_SLOT_UTC, now=_utc(2026, 1, 16, 1, 0)
    ) == date(2026, 1, 15)


def test_run_date_falls_back_to_wall_clock_outside_grace():
    """An ad-hoc run in the middle of the day is not a late cron, so it means
    today — reaching back to the previous slot would be wrong."""
    got = daily._results_run_date(
        daily.EVENING_SLOT_UTC, now=_utc(2026, 8, 7, 14, 0)
    )
    assert got == date(2026, 8, 7)
