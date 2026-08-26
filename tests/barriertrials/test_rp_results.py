"""Tests for the copied results scraper's added name-matching path.

Driven by the same ``__NEXT_DATA__`` fixture the breeze-up tests use, so the
name path is verified against RP's real payload shape. Inns And Out
(horse_uid=9322120) is the fixture race's winner.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from barriertrials.racing import rp_results
from dailybreezeup.racing.rp_racecards import normalize_name

FIX = Path(__file__).parent.parent / "fixtures" / "racingpost"

RACE_URL = "https://www.racingpost.com/results/16/musselburgh/2026-08-25/925679"
INNS_AND_OUT = 9322120


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _hits(*, target_uids=frozenset(), target_names=None):
    return rp_results.parse_result_page_hits(
        _read("results_race.next.html"),
        race_url=RACE_URL,
        race_uid="925679",
        course="Musselburgh",
        race_date=date(2026, 8, 25),
        target_uids=set(target_uids),
        target_names=target_names,
    )


def test_uid_path_still_matches():
    hits = _hits(target_uids={INNS_AND_OUT})
    assert len(hits) == 1
    assert hits[0].horse_uid == INNS_AND_OUT


def test_name_path_matches_without_uid():
    # No uids known yet (the watchlist's normal cold-start state): match by name.
    hits = _hits(target_names={normalize_name("Inns And Out"): None})
    assert len(hits) == 1
    h = hits[0]
    # Still carries the real profile uid so the caller can learn it.
    assert h.horse_uid == INNS_AND_OUT
    assert h.horse_slug == "inns-and-out"
    assert h.finishing_position == "1"
    assert h.sp == "7/1"
    assert h.rpr == 82


def test_no_targets_returns_empty():
    assert _hits() == []


def test_name_not_on_watchlist_skipped():
    assert _hits(target_names={"somethingelse": None}) == []


def test_payload_missing_raises():
    """Same tripwire as the breeze-up module: a markup change must be loud."""
    with pytest.raises(rp_results.ResultPayloadMissing):
        rp_results.parse_result_page_hits(
            "<html><body>no next data here</body></html>",
            race_url=RACE_URL,
            race_uid="925679",
            course="Musselburgh",
            race_date=date(2026, 8, 25),
            target_uids={INNS_AND_OUT},
        )
