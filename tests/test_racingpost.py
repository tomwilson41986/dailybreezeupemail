"""Parser tests for racing.racingpost, driven by fixtures captured from the live site.

Fixtures live under tests/fixtures/racingpost/ and were pulled from:
  - https://www.racingpost.com/racecards/2026-04-24
  - https://www.racingpost.com/racecards/54/sandown/2026-04-24/916397
  - https://www.racingpost.com/results/2026-04-23
  - https://www.racingpost.com/results/6/beverley/2026-04-23/916393

These tests exercise the parsers only; no network calls.
"""
from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from dailybreezeup.racing import racingpost as rp

FIX = Path(__file__).parent / "fixtures" / "racingpost"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# ---------- unit helpers ----------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("3:00 Sandown | Standard Racecard | 24 April 2026 | Racing Post", time(15, 0)),
        ("Full Result 1.52 Beverley | 23 April 2026 | Racing Post", time(13, 52)),
        ("11:30 Sandown | ...", time(11, 30)),
        ("12:00 Sandown | ...", time(12, 0)),
        ("8:45 Wolverhampton | ...", time(20, 45)),
        ("Nonsense no time here", None),
    ],
)
def test_parse_off_time(title, expected):
    assert rp._parse_off_time(title) == expected


@pytest.mark.parametrize(
    "raw,name,country",
    [
        ("Muhaarar (GB)", "Muhaarar", "GB"),
        ("Galileo (IRE)", "Galileo", "IRE"),
        ("No Nay Never", "No Nay Never", None),
        (None, None, None),
        ("  Sea The Stars (IRE)  ", "Sea The Stars", "IRE"),
    ],
)
def test_strip_country_suffix(raw, name, country):
    assert rp._strip_country_suffix(raw) == (name, country)


def test_country_for_slug():
    assert rp._country_for_slug("sandown") == "GB"
    assert rp._country_for_slug("cork") == "IE"
    assert rp._country_for_slug("hong-kong") is None


# ---------- index parsers ----------


def test_parse_racecards_index_extracts_gb_ire_only():
    on = date(2026, 4, 24)
    metas = rp.parse_racecards_index(_read("racecards_index.html"), on)
    assert len(metas) > 0
    # Every meta should be GB or IE, dated correctly, with URL pointing to a race
    for m in metas:
        assert m.country in ("GB", "IE")
        assert m.race_date == on
        assert m.race_url.startswith("https://www.racingpost.com/racecards/")
        assert f"/{on.isoformat()}/" in m.race_url
    # Sandown is GB, Cork is IE — both must be present in the sample
    slugs = {m.course_slug for m in metas}
    assert "sandown" in slugs
    assert "cork" in slugs
    # Results ids are unique
    assert len({m.race_id for m in metas}) == len(metas)


def test_parse_racecards_index_respects_regions_filter():
    on = date(2026, 4, 24)
    gb_only = rp.parse_racecards_index(_read("racecards_index.html"), on, regions=("GB",))
    assert gb_only
    assert {m.country for m in gb_only} == {"GB"}


def test_parse_results_index_extracts_gb_ire_only():
    on = date(2026, 4, 23)
    metas = rp.parse_results_index(_read("results_index.html"), on)
    assert len(metas) > 0
    for m in metas:
        assert m.country in ("GB", "IE")
        assert m.race_url.startswith("https://www.racingpost.com/results/")
    # Dedup of per-race links worked
    assert len({m.race_id for m in metas}) == len(metas)


# ---------- race page parsers ----------


def _sandown_meta() -> rp._RaceMeta:
    return rp._RaceMeta(
        race_id="916397",
        race_url="https://www.racingpost.com/racecards/54/sandown/2026-04-24/916397",
        course="Sandown",
        course_slug="sandown",
        country="GB",
        race_date=date(2026, 4, 24),
    )


def _beverley_meta() -> rp._RaceMeta:
    return rp._RaceMeta(
        race_id="916393",
        race_url="https://www.racingpost.com/results/6/beverley/2026-04-23/916393",
        course="Beverley",
        course_slug="beverley",
        country="GB",
        race_date=date(2026, 4, 23),
    )


def test_parse_racecard_page_extracts_runners_and_meta():
    card = rp.parse_racecard_page(_read("racecard_race.html"), _sandown_meta())
    assert card.country == "GB"
    assert card.course == "Sandown"
    assert card.race_date == date(2026, 4, 24)
    assert card.off_time == time(15, 0)
    assert "bet365 Mile" in card.race_name
    assert len(card.runners) == 6

    # First row we mapped by hand: Cicero's Gift, age 6, Muhaarar out of Terentia
    first = next(r for r in card.runners if r.horse.lower().startswith("cicero"))
    assert first.age == 6
    assert first.trainer == "Charles Hills"
    assert first.jockey == "Jason Watson"
    assert first.owner == "Rosehill Racing"
    assert first.sire == "Muhaarar"
    assert first.dam == "Terentia"
    assert first.bred == "GB"  # from sire country suffix
    assert first.draw == "5"
    assert first.number == "1"
    assert first.weight == "9 8"


def test_parse_result_page_extracts_finishing_positions():
    result = rp.parse_result_page(_read("results_race.html"), _beverley_meta())
    assert result.country == "GB"
    assert result.course == "Beverley"
    assert result.race_date == date(2026, 4, 23)
    assert result.off_time == time(13, 52)
    assert "Maiden" in result.race_name
    assert len(result.runners) == 8

    winner = next(r for r in result.runners if r.finishing_position == "1")
    assert winner.horse == "Fighter's Spirit"
    assert winner.jockey == "Oisin Orr"
    assert winner.trainer == "Saeed bin Suroor"
    assert winner.sp == "11/4"
    assert winner.draw == "7"
    assert winner.age == 3
    assert winner.bred == "IRE"


def test_parse_racecard_page_empty_html_returns_empty_card():
    """Defensive: a broken page shouldn't raise."""
    meta = _sandown_meta()
    card = rp.parse_racecard_page("<html><head><title></title></head><body></body></html>", meta)
    assert card.runners == []
    assert card.race_id == meta.race_id
