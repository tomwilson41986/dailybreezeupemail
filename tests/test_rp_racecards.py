"""Parser tests for racing.rp_racecards driven by captured RP fixtures."""
from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from dailybreezeup.racing import rp_racecards

FIX = Path(__file__).parent / "fixtures" / "racingpost"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "s,expected",
    [
        ("14:08", time(14, 8)),       # RP startTime is literal 24h
        ("11:30", time(11, 30)),
        ("12:00", time(12, 0)),
        ("20:45", time(20, 45)),
        ("9:30", time(9, 30)),
        ("", None),
        ("nonsense", None),
    ],
)
def test_parse_off_time(s, expected):
    assert rp_racecards._parse_off_time(s) == expected


def test_parse_racecards_index_extracts_race_urls():
    races = rp_racecards.parse_racecards_index_race_urls(
        _read("racecards_index.html"), date(2026, 5, 3)
    )
    assert len(races) >= 5
    keys = [(cu, ru) for cu, _, ru, _ in races]
    assert len(keys) == len(set(keys))  # deduped
    for course_uid, slug, race_uid, url in races:
        assert isinstance(course_uid, int) and course_uid > 0
        assert slug
        assert race_uid.isdigit()
        assert url.startswith("https://www.racingpost.com/racecards/")
    # Newmarket 4:10 (race 916544) is in scope on this fixture date
    assert (38, "newmarket", "916544",
            "https://www.racingpost.com/racecards/38/newmarket/2026-05-03/916544") in races


def test_parse_racecards_index_respects_date_filter():
    assert rp_racecards.parse_racecards_index_race_urls(
        _read("racecards_index.html"), date(1999, 1, 1)
    ) == []


def test_parse_racecard_page_entries_matches_target_uid():
    """Imperial Cult (uid 4552168) is a runner in the Windsor 14:08 fixture."""
    hits, off_time = rp_racecards.parse_racecard_page_entries(
        _read("racecards_race.html"),
        race_url="https://www.racingpost.com/racecards/93/windsor/2026-05-25/918919",
        race_uid="918919",
        course_uid=93,
        course="Windsor",
        race_date=date(2026, 5, 25),
        target_uids={4552168},
    )
    assert len(hits) == 1
    h = hits[0]
    assert h.horse_uid == 4552168
    assert h.horse_slug == "imperial-cult"
    assert h.horse_name == "Imperial Cult"
    assert h.off_time == time(14, 8)
    assert off_time == time(14, 8)
    assert h.race_name == "Fitzdares Handicap"
    assert h.course == "Windsor"
    assert h.race_uid == "918919"
    assert h.silk_url == "https://www.rp-assets.com/svg/8/1/4/326418.svg"


def test_parse_racecard_page_entries_matches_multiple_uids():
    """Several target uids in one race each yield a hit with their own silk."""
    hits, _ = rp_racecards.parse_racecard_page_entries(
        _read("racecards_race.html"),
        race_url="x",
        race_uid="918919",
        course_uid=93,
        course="Windsor",
        race_date=date(2026, 5, 25),
        target_uids={4552168, 7457904},
    )
    by_uid = {h.horse_uid: h for h in hits}
    assert set(by_uid) == {4552168, 7457904}
    assert by_uid[7457904].horse_name == "Opera Wave"
    assert by_uid[7457904].silk_url == "https://www.rp-assets.com/svg/9/3/0/343039.svg"


def test_parse_racecard_page_entries_ignores_unknown_uid():
    """A uid that is not one of the runners' horseId yields no hits."""
    hits, _ = rp_racecards.parse_racecard_page_entries(
        _read("racecards_race.html"),
        race_url="x",
        race_uid="918919",
        course_uid=93,
        course="Windsor",
        race_date=date(2026, 5, 25),
        target_uids={1371798},  # not a runner in this race
    )
    assert hits == []


def test_parse_racecard_page_entries_returns_off_time_with_empty_targets():
    """Even with no target uids, the page off-time must be returned so the
    morning email can backfill race times for catalogue-side entries whose
    horse_uid wasn't matched on any racecard."""
    hits, off_time = rp_racecards.parse_racecard_page_entries(
        _read("racecards_race.html"),
        race_url="x",
        race_uid="918919",
        course_uid=93,
        course="Windsor",
        race_date=date(2026, 5, 25),
        target_uids=set(),
    )
    assert hits == []
    assert off_time == time(14, 8)


def test_parse_racecard_page_entries_handles_missing_next_data():
    """A page without the __NEXT_DATA__ blob degrades gracefully."""
    hits, off_time = rp_racecards.parse_racecard_page_entries(
        "<html><body>no json here</body></html>",
        race_url="x",
        race_uid="918919",
        course_uid=93,
        course="Windsor",
        race_date=date(2026, 5, 25),
        target_uids={4552168},
    )
    assert hits == []
    assert off_time is None
