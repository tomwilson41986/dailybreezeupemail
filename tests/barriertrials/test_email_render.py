from __future__ import annotations

from datetime import date, time

from barriertrials.emailer import render
from barriertrials.stats import build_tracker


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
        "ratings": {"Final Rating": 92.0, "TFig": 78.0},
        "fields": {
            "Batch": "1", "Trainer": "D. Dias",
            "Final Rating": "92.0", "Notes": "trial winner",
        },
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
        "Final Rating": 92.0,
        "TFig": 78.0,
        "ratings": {"Final Rating": 92.0, "TFig": 78.0},
        "fields": {"Batch": "1", "Trainer": "D. Dias", "Notes": "winner"},
    }
    base.update(over)
    return base


def test_morning_renders_entries_with_history():
    row = _entered_row()
    row["history"] = [
        {"race_date": date(2026, 4, 10), "course": "Naas", "race_name": "Maiden",
         "finishing_position": "2", "total_runners": 9, "sp": "5/2", "rpr": 80},
    ]
    payload = render(
        run_date=date(2026, 5, 1), entered=[row], ran_today=[], mode="morning",
    )
    assert "entries" in payload.subject.lower()
    assert "Cosmic Mystery" in payload.html
    # Rating tiles surface the configured ratings by their header label.
    assert "Final Rating" in payload.html and "TFig" in payload.html
    # Every sheet column is reported in the card (full row).
    assert "Trainer" in payload.html and "D. Dias" in payload.html
    assert "Notes" in payload.html and "trial winner" in payload.html
    assert "Trainer: D. Dias" in payload.text
    # Historic results-so-far block renders for the entry.
    assert "Results so far" in payload.html
    assert "Naas" in payload.html and "Naas" in payload.text
    # Morning never shows the results-only "Ran today" heading.
    assert "Ran today" not in payload.html


def test_evening_renders_results_and_historic_tracker():
    rows = [_ran_row()]
    tracker = build_tracker(rows, ["Final Rating", "TFig"])
    tracker["season_start"] = "01 Apr 2026"
    payload = render(
        run_date=date(2026, 5, 1), entered=[], ran_today=rows,
        mode="evening", season_summary=tracker,
    )
    assert "results" in payload.subject.lower()
    assert "Ran today" in payload.html
    assert "Historic results" in payload.html
    assert "Performance by Final Rating band" in payload.html
    # Per-horse tracker lists the horse and its runs.
    assert "Tracked horses" in payload.html
    assert "Cosmic Mystery" in payload.html


def test_evening_empty_shows_no_results_placeholder():
    payload = render(
        run_date=date(2026, 5, 1), entered=[], ran_today=[], mode="evening",
    )
    assert "No Results Today" in payload.html
    assert "No Results Today" in payload.subject


def test_build_tracker_none_when_empty():
    assert build_tracker([], ["Final Rating"]) is None


def test_build_tracker_groups_runs_per_horse():
    rows = [
        _ran_row(race_uid="1", race_date=date(2026, 4, 1), finishing_position="1"),
        _ran_row(race_uid="2", race_date=date(2026, 4, 20), finishing_position="3"),
    ]
    tracker = build_tracker(rows, ["Final Rating", "TFig"])
    assert tracker["total_runs"] == 2
    assert len(tracker["horses"]) == 1
    rec = tracker["horses"][0]
    assert rec.n_runs == 2 and rec.n_wins == 1 and rec.n_places == 1
    assert [r.race_date for r in rec.runs] == [date(2026, 4, 1), date(2026, 4, 20)]
