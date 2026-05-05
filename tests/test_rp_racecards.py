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
        ("4:10 Newmarket | Standard Racecard | 3 May 2026 | Racing Post", time(16, 10)),
        ("11:30 Sandown | ...", time(11, 30)),
        ("12:00 Sandown | ...", time(12, 0)),
        ("8:45 Wolverhampton | ...", time(20, 45)),
        ("4:10", time(16, 10)),
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
    """Efsixteen (uid 9175073) is a confirmed runner in Newmarket 4:10."""
    hits = rp_racecards.parse_racecard_page_entries(
        _read("racecards_race.html"),
        race_url="https://www.racingpost.com/racecards/38/newmarket/2026-05-03/916544",
        race_uid="916544",
        course_uid=38,
        course="Newmarket",
        race_date=date(2026, 5, 3),
        target_uids={9175073},
    )
    assert len(hits) == 1
    h = hits[0]
    assert h.horse_uid == 9175073
    assert h.horse_slug == "efsixteen"
    assert "Efsixteen" in h.horse_name
    assert h.off_time == time(16, 10)
    assert "Tattersalls" in h.race_name or "Novice" in h.race_name
    assert h.course == "Newmarket"
    assert h.race_uid == "916544"
    assert h.silk_url == "https://www.rp-assets.com/svg/d/1/5/361251d.svg"


def test_parse_racecard_page_entries_does_not_false_match_pedigree_links():
    """Sire/dam/damsire profile links must not be mistaken for runners.

    Efsixteen's sire (1371798 Havana Grey) and dam (805506 Hot Secret) appear
    inside the runner row as /profile/horse/<uid> links, but the runner uid
    is the data-ugc-runnerid attribute. Asking for the sire's uid should
    return zero hits — it isn't a runner here.
    """
    hits = rp_racecards.parse_racecard_page_entries(
        _read("racecards_race.html"),
        race_url="x",
        race_uid="916544",
        course_uid=38,
        course="Newmarket",
        race_date=date(2026, 5, 3),
        target_uids={1371798},  # Havana Grey, the sire
    )
    assert hits == []


def test_parse_racecard_page_entries_empty_target_short_circuits():
    assert rp_racecards.parse_racecard_page_entries(
        _read("racecards_race.html"),
        race_url="x",
        race_uid="916544",
        course_uid=38,
        course="Newmarket",
        race_date=date(2026, 5, 3),
        target_uids=set(),
    ) == []
