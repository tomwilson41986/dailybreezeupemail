"""Parser tests for racing.rp_racecards driven by captured RP fixtures.

RP serves racecards as a Next.js app, so the runner/race data is read from the
page's ``__NEXT_DATA__`` JSON. ``racecards_race.next.html`` is a trimmed fixture
mirroring that real structure; ``racecards_index.html`` is a captured index page
(the index still embeds the per-race URLs we regex out)."""
from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from dailybreezeup.racing import rp_racecards

FIX = Path(__file__).parent / "fixtures" / "racingpost"

RACE_URL = "https://www.racingpost.com/racecards/31/lingfield/2026-05-30/919050"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _entries(target_uids, target_names=None):
    return rp_racecards.parse_racecard_page_entries(
        _read("racecards_race.next.html"),
        race_url=RACE_URL,
        race_uid="919050",
        course_uid=31,
        course="Lingfield",
        race_date=date(2026, 5, 30),
        target_uids=set(target_uids),
        target_names=target_names,
    )


@pytest.mark.parametrize(
    "s,expected",
    [
        ("19:12", time(19, 12)),       # JSON startTime is already 24-hour
        ("16:20", time(16, 20)),
        ("09:30", time(9, 30)),
        ("04:28", time(4, 28)),
        ("", None),
        (None, None),
        ("nonsense", None),
    ],
)
def test_parse_start_time(s, expected):
    assert rp_racecards._parse_start_time(s) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Cosmic Mystery", "cosmicmystery"),
        ("  Alta   Regina ", "altaregina"),
        ("O'Reilly", "oreilly"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_name(raw, expected):
    assert rp_racecards.normalize_name(raw) == expected


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


def test_parse_racecards_index_respects_date_filter():
    assert rp_racecards.parse_racecards_index_race_urls(
        _read("racecards_index.html"), date(1999, 1, 1)
    ) == []


def test_parse_racecard_page_entries_matches_target_uid():
    """Alta Regina (uid 9312938) is a confirmed runner at Lingfield 19:12."""
    hits, off_time = _entries({9312938})
    assert len(hits) == 1
    h = hits[0]
    assert h.horse_uid == 9312938
    assert h.horse_slug == "alta-regina"
    assert h.horse_name == "Alta Regina"
    assert h.off_time == time(19, 12)
    assert "Novice" in h.race_name
    assert h.course == "Lingfield"
    assert h.race_uid == "919050"
    assert h.silk_url == "https://www.rp-assets.com/svg/8/8/0/325088.svg"
    assert off_time == time(19, 12)


def test_parse_racecard_page_entries_skips_non_runners():
    """A uid we want (Glamorize, 9312940) that is flagged nonRunner must not be
    emitted — declared-then-withdrawn horses aren't running today."""
    hits, _ = _entries({9312940})
    assert hits == []


def test_name_fallback_matches_lot_without_uid():
    """A lot RP hasn't linked a uid to is matched by name. Phantom Lot has no
    catalogue uid; we pass its normalized name with the expected age, and the
    runner's real uid is backfilled onto the entry."""
    hits, _ = _entries(set(), {rp_racecards.normalize_name("Phantom Lot"): 2})
    assert len(hits) == 1
    assert hits[0].horse_name == "Phantom Lot"
    assert hits[0].horse_uid == 8000001


def test_name_fallback_with_no_age_guard_matches_regardless_of_age():
    """A None expected-age disables the guard (match on name alone)."""
    hits, _ = _entries(set(), {rp_racecards.normalize_name("Old Timer"): None})
    assert [h.horse_name for h in hits] == ["Old Timer"]


def test_name_fallback_age_guard_rejects_collision():
    """Old Timer is age 5; asking for the name with expected age 2 must not
    match — guards against a 2yo sharing a name with an older horse."""
    hits, _ = _entries(set(), {rp_racecards.normalize_name("Old Timer"): 2})
    assert hits == []


def test_unrelated_runner_not_matched_but_off_time_returned():
    """A uid that isn't on the card matches nothing, but the page off-time is
    still returned for off-time backfill on catalogue-side entries."""
    hits, off_time = _entries({1234567})  # not present on this card
    assert hits == []
    assert off_time == time(19, 12)


def test_off_time_returned_with_empty_targets():
    hits, off_time = _entries(set())
    assert hits == []
    assert off_time == time(19, 12)


def test_non_next_page_yields_nothing():
    """A page without __NEXT_DATA__ (e.g. a bot-challenge interstitial) yields
    no hits and no off-time rather than raising."""
    hits, off_time = rp_racecards.parse_racecard_page_entries(
        "<html><body>Just a moment...</body></html>",
        race_url=RACE_URL,
        race_uid="919050",
        course_uid=31,
        course="Lingfield",
        race_date=date(2026, 5, 30),
        target_uids={9312938},
    )
    assert hits == []
    assert off_time is None
