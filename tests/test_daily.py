"""Tests for the morning/evening classification glue in dailybreezeup.daily."""
from __future__ import annotations

from datetime import date, time

from dailybreezeup import daily
from dailybreezeup.racing import rp_racecards, rp_sales


def _sale() -> rp_sales.Sale:
    return rp_sales.Sale(
        venue_uid=5,
        sale_date=date(2026, 4, 14),
        sale_end_date=date(2026, 4, 15),
        sale_name="Tattersalls Craven Breeze Up Sale 2026",
        sale_co="Tattersalls",
    )


def _lot(*, horse_uid: int | None, entry: rp_sales.EntryDetails | None) -> rp_sales.SaleLot:
    return rp_sales.SaleLot(
        sale=_sale(),
        lot_no=16,
        lot_letter="",
        horse_uid=horse_uid,
        horse_name="",
        sire_uid=None,
        sire_name="Havana Grey",
        dam_uid=None,
        dam_name="Hot Secret",
        sire_of_dam_name="",
        sex="F",
        age=2,
        year_foaled=2024,
        seller="From Yeomanstown Stud, Ireland",
        price_label="GBG 350,000",
        buyer="Stroud Coleman Bloodstock",
        entered=entry is not None,
        entry=entry,
    )


def test_catalogue_side_entry_gets_off_time_from_race_off_times():
    """When the catalogue's entry_details has no off_time (it never does),
    the morning email must still surface the race time by looking it up in
    the race_off_times map collected during the racecard scan. This covers
    unnamed lots (no horse_uid to match on racecards) and the lag case
    where a uid is in the catalogue but not yet on the racecard."""
    today = date(2026, 4, 24)
    entry = rp_sales.EntryDetails(
        course_uid=38,
        course_name="NEWMARKET",
        race_date=date(2026, 4, 25),
        race_uid=910567,
    )
    # horse_uid=None means racecard uid-matching can't find this lot.
    lot = _lot(horse_uid=None, entry=entry)

    entered, _ran = daily._classify(
        today, [lot], results=[], racecard_entries=[],
        entries_window_days=3,
        race_off_times={"910567": time(14, 30)},
    )

    assert len(entered) == 1
    assert entered[0]["off_time"] == time(14, 30)


def test_catalogue_side_entry_off_time_missing_when_race_not_scanned():
    """If no racecard off-time was collected for the entry's race, the row
    still renders (without off_time). The template guards on truthy
    off_time, so the morning email simply omits the time for that row."""
    today = date(2026, 4, 24)
    entry = rp_sales.EntryDetails(
        course_uid=38,
        course_name="NEWMARKET",
        race_date=date(2026, 4, 25),
        race_uid=910567,
    )
    lot = _lot(horse_uid=None, entry=entry)

    entered, _ran = daily._classify(
        today, [lot], results=[], racecard_entries=[],
        entries_window_days=3,
        race_off_times={},
    )

    assert len(entered) == 1
    assert entered[0]["off_time"] is None


def test_racecard_side_entry_wins_when_lot_matches_both_paths():
    """When a lot is matched by both racecards and the catalogue, the
    racecard-derived row (with its own off_time, race_name, silk_url) must
    win — the catalogue path is a fallback only."""
    today = date(2026, 4, 24)
    entry = rp_sales.EntryDetails(
        course_uid=38,
        course_name="NEWMARKET",
        race_date=date(2026, 4, 25),
        race_uid=910567,
    )
    lot = _lot(horse_uid=8688568, entry=entry)
    rc = rp_racecards.RacecardEntry(
        horse_uid=8688568,
        horse_slug="havana-grey-f",
        horse_name="Hot Havana",
        course_uid=38,
        course="Newmarket",
        race_date=date(2026, 4, 25),
        off_time=time(15, 10),
        race_name="Maiden Stakes",
        race_url="https://www.racingpost.com/racecards/38/newmarket/2026-04-25/910567",
        race_uid="910567",
        silk_url="https://www.rp-assets.com/svg/x/y/z/abc.svg",
    )

    entered, _ran = daily._classify(
        today, [lot], results=[], racecard_entries=[rc],
        entries_window_days=3,
        race_off_times={"910567": time(14, 30)},  # would lose to racecard's 15:10
    )

    assert len(entered) == 1
    assert entered[0]["off_time"] == time(15, 10)
    assert entered[0]["race_name"] == "Maiden Stakes"
    assert entered[0]["horse_name"] == "Hot Havana"
