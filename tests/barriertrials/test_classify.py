from __future__ import annotations

from datetime import date, time

from barriertrials import daily
from barriertrials.racing.rp_results import ResultHit
from barriertrials.sheet import TrackedHorse, index_by_name
from dailybreezeup.racing.rp_racecards import RacecardEntry, normalize_name

TODAY = date(2026, 5, 1)
WINDOW_END = date(2026, 5, 4)


def _horse(name, ratings=None):
    return TrackedHorse(name=name, name_key=normalize_name(name), ratings=ratings or {"R": 80.0})


def _watchlist(*names):
    return index_by_name(_horse(n) for n in names)


def _entry(name, *, uid=None, race_date=TODAY, race_uid="1"):
    return RacecardEntry(
        horse_uid=uid, horse_slug="", horse_name=name, course_uid=1, course="Newmarket",
        race_date=race_date, off_time=time(14, 0), race_name="Maiden", race_url="u",
        race_uid=race_uid, silk_url=None,
    )


def _hit(name, *, uid, race_uid="1"):
    return ResultHit(
        horse_uid=uid, horse_slug="", horse_name=name, course="Newmarket",
        race_date=TODAY, off_time=time(14, 0), race_name="Maiden", finishing_position="1",
        sp="2/1", race_url="u", race_uid=race_uid, silk_url=None, total_runners=8, rpr=85,
    )


# ---------- entries ----------


def test_name_match_when_uid_unknown_and_learns_uid():
    by_name = _watchlist("Cosmic Mystery")
    res = daily.classify_entries(
        [_entry("Cosmic Mystery", uid=555)], by_name, learned={},
        today=TODAY, window_end=WINDOW_END,
    )
    assert [r["horse_key"] for r in res["rows"]] == ["cosmicmystery"]
    assert res["learns"] == [("cosmicmystery", 555)]
    assert res["conflicts"] == []


def test_uid_match_resolves_even_when_name_differs():
    # Learned uid points at the watchlist horse; RP shows a slightly different
    # name string but the uid join is authoritative.
    by_name = _watchlist("Cosmic Mystery")
    res = daily.classify_entries(
        [_entry("COSMIC MYSTERY (IRE)", uid=555)], by_name,
        learned={"cosmicmystery": 555}, today=TODAY, window_end=WINDOW_END,
    )
    assert [r["horse_key"] for r in res["rows"]] == ["cosmicmystery"]
    # Already learned, so no new learn request and no conflict.
    assert res["learns"] == []
    assert res["conflicts"] == []


def test_uid_conflict_is_flagged_not_overwritten():
    by_name = _watchlist("Cosmic Mystery")
    res = daily.classify_entries(
        [_entry("Cosmic Mystery", uid=999)], by_name,
        learned={"cosmicmystery": 555}, today=TODAY, window_end=WINDOW_END,
    )
    assert res["conflicts"] == [("cosmicmystery", 555, 999)]
    assert res["learns"] == []


def test_out_of_window_entry_dropped():
    by_name = _watchlist("Cosmic Mystery")
    res = daily.classify_entries(
        [_entry("Cosmic Mystery", uid=1, race_date=date(2026, 6, 1))], by_name,
        learned={}, today=TODAY, window_end=WINDOW_END,
    )
    assert res["rows"] == []


def test_not_on_watchlist_skipped():
    by_name = _watchlist("Cosmic Mystery")
    res = daily.classify_entries(
        [_entry("Some Other Horse", uid=7)], by_name, learned={},
        today=TODAY, window_end=WINDOW_END,
    )
    assert res["rows"] == []
    assert res["learns"] == []


def test_dedup_same_horse_same_race():
    by_name = _watchlist("Cosmic Mystery")
    res = daily.classify_entries(
        [_entry("Cosmic Mystery", uid=1, race_uid="9"),
         _entry("Cosmic Mystery", uid=1, race_uid="9")],
        by_name, learned={}, today=TODAY, window_end=WINDOW_END,
    )
    assert len(res["rows"]) == 1


# ---------- results ----------


def test_results_name_match_learns_uid_and_builds_row():
    by_name = _watchlist("Fighter's Spirit")
    res = daily.classify_results([_hit("Fighter's Spirit", uid=42)], by_name, learned={})
    assert len(res["rows"]) == 1
    row = res["rows"][0]
    assert row["horse_key"] == "fightersspirit"
    assert row["finishing_position"] == "1"
    assert row["season_year"] == TODAY.year
    assert row["ratings"] == {"R": 80.0}
    assert res["learns"] == [("fightersspirit", 42)]
