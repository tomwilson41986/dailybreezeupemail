"""Parser tests for racing.rp_results driven by captured Racing Post fixtures."""
from __future__ import annotations

import re
from datetime import date, time
from pathlib import Path

import pytest

from dailybreezeup.racing import rp_results

FIX = Path(__file__).parent / "fixtures" / "racingpost"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Full Result 1.52 Beverley | 23 April 2026 | Racing Post", time(13, 52)),
        ("3:00 Sandown | 24 April 2026 | Racing Post", time(15, 0)),
        ("11:30 Sandown | ...", time(11, 30)),
        ("12:00 Sandown | ...", time(12, 0)),
        ("8:45 Wolverhampton | ...", time(20, 45)),
        ("Nonsense no time here", None),
    ],
)
def test_parse_off_time(title, expected):
    assert rp_results._parse_off_time(title) == expected


def test_parse_results_index_extracts_race_urls():
    races = rp_results.parse_results_index_race_urls(_read("results_index.html"), date(2026, 4, 23))
    # At least a handful of real races, deduped
    assert len(races) >= 5
    race_ids = [r[1] for r in races]
    assert len(race_ids) == len(set(race_ids))  # no duplicate race_uids
    for slug, race_uid, url in races:
        assert slug  # non-empty course slug
        assert race_uid.isdigit()
        assert url.startswith("https://www.racingpost.com/results/")


def test_parse_results_index_respects_date_filter():
    # Wrong date: zero races should be returned
    assert rp_results.parse_results_index_race_urls(
        _read("results_index.html"), date(1999, 1, 1)
    ) == []


def test_parse_result_page_hits_matches_uid_in_target_set():
    """Fighter's Spirit (horse_uid=9129803) is the known winner at Beverley."""
    hits = rp_results.parse_result_page_hits(
        _read("results_race.html"),
        race_url="https://www.racingpost.com/results/6/beverley/2026-04-23/916393",
        race_uid="916393",
        course="Beverley",
        race_date=date(2026, 4, 23),
        target_uids={9129803},
    )
    assert len(hits) == 1
    h = hits[0]
    assert h.horse_uid == 9129803
    assert h.horse_slug == "fighters-spirit"
    assert "Fighter" in h.horse_name
    assert h.finishing_position == "1"
    assert h.sp == "11/4"
    assert h.off_time == time(13, 52)
    assert "Maiden" in h.race_name


def test_parse_result_page_hits_empty_when_uid_not_in_target():
    hits = rp_results.parse_result_page_hits(
        _read("results_race.html"),
        race_url="x",
        race_uid="1",
        course="Beverley",
        race_date=date(2026, 4, 23),
        target_uids={111111},
    )
    assert hits == []


def test_parse_result_page_hits_empty_target_short_circuits():
    # With an empty uid set we shouldn't even bother parsing; empty list out.
    assert rp_results.parse_result_page_hits(
        _read("results_race.html"),
        race_url="x",
        race_uid="1",
        course="Beverley",
        race_date=date(2026, 4, 23),
        target_uids=set(),
    ) == []
