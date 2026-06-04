from __future__ import annotations

from datetime import date, time

from barriertrials.emailer import render
from barriertrials.stats import build_summary


def _entered_row():
    return {
        "horse_key": "cosmicmystery",
        "horse_name": "Cosmic Mystery",
        "race_uid": "1",
        "race_date": date(2026, 5, 1),
        "off_time": time(14, 30),
        "course": "Newmarket",
        "race_name": "Maiden Stakes",
        "race_url": "https://www.racingpost.com/racecards/x",
        "silk_url": None,
        "ratings": {"Speed": 92.0, "Precocity": 78.0},
    }


def _ran_row(**over):
    base = {
        "horse_key": "cosmicmystery",
        "horse_name": "Cosmic Mystery",
        "horse_uid": 555,
        "race_uid": "1",
        "race_date": date(2026, 5, 1),
        "off_time": time(14, 30),
        "course": "Newmarket",
        "race_name": "Maiden Stakes",
        "finishing_position": "1",
        "total_runners": 8,
        "sp": "2/1",
        "rpr": 88,
        "race_url": "https://www.racingpost.com/results/x",
        "silk_url": None,
        "Speed": 92.0,
        "Precocity": 78.0,
        "ratings": {"Speed": 92.0, "Precocity": 78.0},
    }
    base.update(over)
    return base


def test_morning_renders_entries_only():
    payload = render(
        run_date=date(2026, 5, 1), entered=[_entered_row()], ran_today=[],
        mode="morning",
    )
    assert "entries" in payload.subject.lower()
    assert "Cosmic Mystery" in payload.html
    assert "Cosmic Mystery" in payload.text
    # Rating tiles surface both configured ratings by their header label.
    assert "Speed" in payload.html and "Precocity" in payload.html
    # Morning never shows the results-only "Ran today" heading.
    assert "Ran today" not in payload.html


def test_evening_renders_results_and_season_summary():
    rows = [_ran_row()]
    summary = build_summary(rows, ["Speed", "Precocity"])
    payload = render(
        run_date=date(2026, 5, 1), entered=[], ran_today=rows,
        mode="evening", season_summary=summary,
    )
    assert "results" in payload.subject.lower()
    assert "Ran today" in payload.html
    assert "Season to date" in payload.html
    assert "Form by Speed" in payload.html
    assert "Top 10 by Precocity" in payload.html


def test_evening_empty_shows_no_results_placeholder():
    payload = render(
        run_date=date(2026, 5, 1), entered=[], ran_today=[], mode="evening",
    )
    assert "No Results Today" in payload.html
    assert "No Results Today" in payload.subject


def test_build_summary_none_when_empty():
    assert build_summary([], ["Speed"]) is None
