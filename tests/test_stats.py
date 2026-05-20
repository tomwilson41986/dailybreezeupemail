"""Tests for the season-to-date aggregation helpers in dailybreezeup.stats."""
from __future__ import annotations

import pytest

from dailybreezeup import stats


def _row(**over):
    """A single archive-shaped row. Defaults cover a typical sheet-matched
    Newmarket maiden runner — override fields to construct test cases."""
    base = {
        "lot_id": "rp-5-2026-04-14-16",
        "race_uid": "910567",
        "horse_uid": 8688568,
        "horse_name": "",
        "sale_year": 2026,
        "sale_short": "Craven",
        "sale_name": "Tattersalls Craven Breeze Up Sale 2026",
        "lot_no": 16,
        "race_date": "2026-05-01",
        "course": "Newmarket",
        "off_time": "14:30",
        "race_name": "Maiden Stakes",
        "finishing_position": "4",
        "total_runners": 10,
        "sp": "5/1",
        "rpr": 72,
        "sheet_breeze_rating": 88.5,
        "sheet_precocity_rating": 80.0,
        "recorded_at": "2026-05-01T20:00:00+00:00",
    }
    base.update(over)
    return base


@pytest.mark.parametrize(
    "rating,expected",
    [
        (None, "unrated"),
        (89.9, "70–89"),
        (90.0, "≥90"),
        (90.1, "≥90"),
        (70.0, "70–89"),
        (69.9, "50–69"),
        (50.0, "50–69"),
        (49.9, "<50"),
        (0.0, "<50"),
    ],
)
def test_band_for_thresholds(rating, expected):
    assert stats.band_for(rating) == expected


def test_aggregate_by_band_counts_runners_winners_and_avg_rpr():
    rows = [
        _row(sheet_breeze_rating=92.0, finishing_position="1", rpr=85),
        _row(sheet_breeze_rating=91.0, finishing_position="3", rpr=75),
        _row(sheet_breeze_rating=80.0, finishing_position="2", rpr=70),
        _row(sheet_breeze_rating=80.0, finishing_position="5", rpr=None),
        _row(sheet_breeze_rating=None, finishing_position="1", rpr=60),
    ]
    bands = stats.aggregate_by_band(rows, "sheet_breeze_rating")
    by_label = {b.label: b for b in bands}
    assert set(by_label) == {"≥90", "70–89", "unrated"}
    assert by_label["≥90"].n_runners == 2
    assert by_label["≥90"].n_winners == 1
    assert by_label["≥90"].strike_rate == pytest.approx(0.5)
    assert by_label["≥90"].avg_rpr == pytest.approx(80.0)
    # 70–89 band: 2 runners (one with no RPR), 0 wins; avg RPR skips the None
    assert by_label["70–89"].n_runners == 2
    assert by_label["70–89"].n_winners == 0
    assert by_label["70–89"].avg_rpr == pytest.approx(70.0)
    assert by_label["unrated"].n_winners == 1


def test_aggregate_by_band_marks_low_n_below_threshold():
    rows = [_row(sheet_breeze_rating=92.0)]
    [band] = stats.aggregate_by_band(rows, "sheet_breeze_rating")
    assert band.n_runners == 1
    assert band.low_n is True


def test_aggregate_by_band_clears_low_n_above_threshold():
    rows = [_row(sheet_breeze_rating=92.0) for _ in range(stats.LOW_N_THRESHOLD)]
    [band] = stats.aggregate_by_band(rows, "sheet_breeze_rating")
    assert band.n_runners == stats.LOW_N_THRESHOLD
    assert band.low_n is False


def test_aggregate_by_sale_groups_and_sorts_by_strike_rate():
    rows = [
        _row(sale_short="Craven", sale_year=2026, finishing_position="1", rpr=80),
        _row(sale_short="Craven", sale_year=2026, finishing_position="3", rpr=70),
        _row(sale_short="Goffs",  sale_year=2026, finishing_position="4", rpr=60),
        _row(sale_short="Goffs",  sale_year=2026, finishing_position="5", rpr=None),
    ]
    sales = stats.aggregate_by_sale(rows)
    labels = [s.sale_label for s in sales]
    # Craven (1/2 = 50%) comes before Goffs (0/2 = 0%)
    assert labels == ["Craven 2026", "Goffs 2026"]
    assert sales[0].n_winners == 1
    assert sales[0].strike_rate == pytest.approx(0.5)
    assert sales[1].avg_rpr == pytest.approx(60.0)


def test_top_rated_groups_by_horse_picks_peak_rpr_and_status():
    """A horse with multiple runs collapses into one summary row showing
    its win count and peak RPR across all outings."""
    rows = [
        # Horse A: ran twice, won once, peak RPR 90
        _row(horse_uid=1, horse_name="Alpha", sheet_breeze_rating=92.0,
             finishing_position="1", rpr=90, race_date="2026-05-10"),
        _row(horse_uid=1, horse_name="Alpha", sheet_breeze_rating=92.0,
             finishing_position="5", rpr=82, race_date="2026-05-20"),
        # Horse B: placed once
        _row(horse_uid=2, horse_name="Bravo", sheet_breeze_rating=85.0,
             finishing_position="2", rpr=80, race_date="2026-05-15"),
        # Horse C: unrated, should be excluded from the top list
        _row(horse_uid=3, horse_name="Cee", sheet_breeze_rating=None,
             finishing_position="1", rpr=70, race_date="2026-05-15"),
    ]
    top = stats.top_rated(rows, "sheet_breeze_rating", limit=10)
    names = [h.horse_name for h in top]
    assert "Cee" not in names  # unrated excluded
    assert names[0] == "Alpha"  # higher rating wins
    a = top[0]
    assert a.n_runs == 2
    assert a.n_wins == 1
    assert a.peak_rpr == 90
    assert a.status_kind == "won"
    assert a.status_label == "WON"
    b = top[1]
    assert b.status_kind == "placed"
    assert b.status_label == "PLACED"


def test_status_label_pluralises_multiple_wins():
    rows = [
        _row(horse_uid=9, finishing_position="1", race_date="2026-05-01"),
        _row(horse_uid=9, finishing_position="1", race_date="2026-05-08"),
    ]
    [summary] = stats.top_rated(rows, "sheet_breeze_rating", limit=10)
    assert summary.n_wins == 2
    assert summary.status_label == "WON × 2"


def test_top_rated_falls_back_to_lot_id_when_uid_missing():
    """Unnamed lots have horse_uid=None — they're keyed by lot_id instead so
    a single anonymous lot doesn't collide with other anonymous lots."""
    rows = [
        _row(horse_uid=None, lot_id="rp-5-2026-04-14-178",
             sheet_breeze_rating=92.0, finishing_position="3"),
        _row(horse_uid=None, lot_id="rp-5-2026-04-14-200",
             sheet_breeze_rating=88.0, finishing_position="1"),
    ]
    top = stats.top_rated(rows, "sheet_breeze_rating", limit=10)
    assert len(top) == 2  # two separate anonymous horses, not merged


def test_build_summary_returns_none_for_empty_input():
    assert stats.build_summary([]) is None


def test_build_summary_assembles_every_section():
    rows = [
        _row(sheet_breeze_rating=92.0, sheet_precocity_rating=85.0,
             finishing_position="1", rpr=90),
        _row(sheet_breeze_rating=80.0, sheet_precocity_rating=60.0,
             horse_uid=2, finishing_position="4", rpr=70),
    ]
    summary = stats.build_summary(rows)
    assert summary["total_runs"] == 2
    assert summary["low_n_threshold"] == stats.LOW_N_THRESHOLD
    assert summary["by_breeze_band"]
    assert summary["by_precocity_band"]
    assert summary["by_sale"]
    assert summary["top_breeze"]
    assert summary["top_precocity"]
