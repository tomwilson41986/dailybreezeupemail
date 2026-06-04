"""Tests for the copied results scraper's added name-matching path.

Driven by the same captured Racing Post fixtures the breeze-up tests use, so we
verify the name path against real markup. The known winner at Beverley is
Fighter's Spirit (horse_uid=9129803).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from barriertrials.racing import rp_results
from dailybreezeup.racing.rp_racecards import normalize_name

FIX = Path(__file__).parent.parent / "fixtures" / "racingpost"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _hits(*, target_uids=frozenset(), target_names=None):
    return rp_results.parse_result_page_hits(
        _read("results_race.html"),
        race_url="https://www.racingpost.com/results/6/beverley/2026-04-23/916393",
        race_uid="916393",
        course="Beverley",
        race_date=date(2026, 4, 23),
        target_uids=set(target_uids),
        target_names=target_names,
    )


def test_uid_path_still_matches():
    hits = _hits(target_uids={9129803})
    assert len(hits) == 1
    assert hits[0].horse_uid == 9129803


def test_name_path_matches_without_uid():
    # No uids known yet (the watchlist's normal cold-start state): match by name.
    hits = _hits(target_names={normalize_name("Fighter's Spirit"): None})
    assert len(hits) == 1
    h = hits[0]
    # Still carries the real profile uid so the caller can learn it.
    assert h.horse_uid == 9129803
    assert h.horse_slug == "fighters-spirit"
    assert h.finishing_position == "1"
    assert h.sp == "11/4"


def test_no_targets_returns_empty():
    assert _hits() == []


def test_name_not_on_watchlist_skipped():
    assert _hits(target_names={"somethingelse": None}) == []
