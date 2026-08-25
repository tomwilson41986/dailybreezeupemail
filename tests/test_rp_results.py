"""Parser tests for racing.rp_results driven by captured Racing Post fixtures.

RP serves result pages as a Next.js app, so the runner/race data is read from
the page's ``__NEXT_DATA__`` JSON. ``results_race.next.html`` is a trimmed
fixture mirroring that real structure; ``results_index.html`` is a captured
index page (the index still embeds the per-race URLs we regex out).
"""
from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from dailybreezeup.racing import rp_results

FIX = Path(__file__).parent / "fixtures" / "racingpost"

RACE_URL = "https://www.racingpost.com/results/16/musselburgh/2026-08-25/925679"

# The three fixture runners that belong to a breeze-up catalogue.
INNS_AND_OUT = 9322120
BASMAAH = 9645600
DIPLOMACY = 9577014
SAVOY_BLUE = 9472275


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _hits(target_uids):
    return rp_results.parse_result_page_hits(
        _read("results_race.next.html"),
        race_url=RACE_URL,
        race_uid="925679",
        course="Musselburgh",
        race_date=date(2026, 8, 25),
        target_uids=set(target_uids),
    )


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
    hits = _hits({INNS_AND_OUT})
    assert len(hits) == 1
    h = hits[0]
    assert h.horse_uid == INNS_AND_OUT
    assert h.horse_slug == "inns-and-out"
    assert h.horse_name == "Inns And Out"
    assert h.finishing_position == "1"
    assert h.sp == "7/1"
    assert h.rpr == 82
    assert h.off_time == time(14, 15)
    assert "Maiden Stakes" in h.race_name
    assert h.silk_url == "https://www.rp-assets.com/svg/4/5/9/374954.svg"
    assert h.total_runners == 5
    assert h.race_url == RACE_URL
    assert h.race_uid == "925679"
    assert h.race_date == date(2026, 8, 25)


def test_parse_result_page_hits_reads_connections():
    hits = _hits({INNS_AND_OUT})
    assert hits[0].trainer == "Tim Easterby"
    assert hits[0].jockey == "Jason Hart"


def test_parse_result_page_hits_returns_every_match():
    hits = _hits({INNS_AND_OUT, BASMAAH, SAVOY_BLUE})
    assert {h.horse_name for h in hits} == {"Inns And Out", "Basmaah", "Savoy Blue"}


def test_parse_result_page_hits_unrated_race_gives_no_rpr():
    """RP posts ratings for a 2yo maiden late, so the dash means None."""
    (basmaah,) = _hits({BASMAAH})
    assert basmaah.rpr is None
    assert basmaah.finishing_position == "8"
    assert basmaah.sp == "80/1"


def test_parse_result_page_hits_marks_a_disqualified_runner():
    """Diplomacy passed the post first and lost it in the stewards' room.

    The stats count ``finishing_position == "1"`` as a win, so a disqualified
    runner must not come back carrying its original code.
    """
    (dq,) = _hits({DIPLOMACY})
    assert dq.finishing_position == "DSQ"


def test_parse_result_page_hits_tolerates_missing_fields():
    """A pulled-up runner RP linked no connections, silk or price for."""
    (pu,) = _hits({SAVOY_BLUE})
    assert pu.finishing_position == "PU"
    assert pu.sp is None
    assert pu.silk_url is None
    assert pu.rpr is None
    assert pu.trainer is None
    assert pu.jockey is None
    assert pu.horse_name == "Savoy Blue"


def test_parse_result_page_hits_prefers_rp_course_name():
    """RP's own name beats one rebuilt from the URL slug ("Lingfield Aw")."""
    hits = rp_results.parse_result_page_hits(
        _read("results_race.next.html"),
        race_url=RACE_URL,
        race_uid="925679",
        course="Musselburgh Slugified",
        race_date=date(2026, 8, 25),
        target_uids={INNS_AND_OUT},
    )
    assert hits[0].course == "Musselburgh"


@pytest.mark.parametrize(
    "s,expected",
    [
        ("82", 82),
        ("  46  ", 46),
        ("108", 108),
        (108, 108),
        ("–", None),    # en-dash
        ("—", None),    # em-dash
        ("", None),
        (None, None),
    ],
)
def test_parse_rating_handles_dashes_and_digits(s, expected):
    assert rp_results._parse_rating(s) == expected


def test_parse_result_page_hits_empty_when_uid_not_in_target():
    assert _hits({111111}) == []


def test_parse_result_page_hits_empty_target_short_circuits():
    # With an empty uid set we shouldn't even bother parsing; empty list out.
    assert _hits(set()) == []


def test_parse_result_page_hits_raises_when_payload_missing():
    """A markup change must fail loudly, not read as a day nothing ran.

    Returning ``[]`` here is what let RP's August 2026 /results migration go
    unnoticed: every page yielded zero hits and the email said "No Results
    Today" for weeks.
    """
    with pytest.raises(rp_results.ResultPayloadMissing):
        rp_results.parse_result_page_hits(
            "<html><body>no next data here</body></html>",
            race_url=RACE_URL,
            race_uid="925679",
            course="Musselburgh",
            race_date=date(2026, 8, 25),
            target_uids={INNS_AND_OUT},
        )
