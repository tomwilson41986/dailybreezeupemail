"""Tests for the morning/evening classification glue in dailybreezeup.daily."""
from __future__ import annotations

from datetime import date, time

from dailybreezeup import daily
from dailybreezeup.config import Settings
from dailybreezeup.racing import rp_racecards, rp_results, rp_sales


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


# ── Historical backfill CLI ────────────────────────────────────────────────


def _hit(uid: int, *, finishing_position: str, race_uid: str, race_date: date,
         rpr: int | None = None) -> rp_results.ResultHit:
    return rp_results.ResultHit(
        horse_uid=uid,
        horse_slug="x",
        horse_name=f"Horse {uid}",
        course="Newmarket",
        race_date=race_date,
        off_time=time(14, 30),
        race_name="Maiden Stakes",
        finishing_position=finishing_position,
        sp="5/1",
        race_url=f"https://example/{race_uid}",
        race_uid=race_uid,
        silk_url=None,
        total_runners=8,
        rpr=rpr,
    )


def test_backfill_results_walks_date_range_and_populates_archive(tmp_path, monkeypatch):
    """The --backfill-from CLI walks every date in [from_date, to_date],
    asks RP results for our uid set, and upserts each match into the archive.
    This is the recovery path when the SQLite DB has been wiped (ephemeral CI)."""
    db_path = tmp_path / "test.db"

    def fake_settings():
        return Settings(
            gmail_user="u", gmail_app_password="p", email_to="a@b",
            db_path=db_path,
        )
    monkeypatch.setattr(daily, "load_settings", fake_settings)

    lot = _lot(horse_uid=1234, entry=None)
    monkeypatch.setattr(daily.rp_sales, "discover_sales", lambda year: [lot.sale])
    monkeypatch.setattr(daily.rp_sales, "fetch_lots", lambda sale: [lot])

    calls: list[date] = []

    def fake_fetch_hits(on, uids):
        calls.append(on)
        # Return one hit only on the middle day, to assert per-date routing.
        if on == date(2026, 4, 25):
            return [_hit(1234, finishing_position="1", race_uid="910567",
                         race_date=on, rpr=88)]
        return []

    monkeypatch.setattr(daily.rp_results, "fetch_hits_for_uids", fake_fetch_hits)
    monkeypatch.setattr(daily.sheet_mod, "fetch_sheet", lambda url: [])
    monkeypatch.setattr(daily.sheet_mod, "index_by_key", lambda rows: {})
    monkeypatch.setattr(daily.sheet_mod, "count_by_sale", lambda rows: {})

    rc = daily.backfill_results(
        from_date=date(2026, 4, 24), to_date=date(2026, 4, 26),
    )
    assert rc == 0
    # Three dates were walked (inclusive both ends)
    assert calls == [date(2026, 4, 24), date(2026, 4, 25), date(2026, 4, 26)]

    # And the one hit landed in the archive with the right shape
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT lot_id, race_uid, horse_uid, finishing_position, rpr FROM results_archive"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["race_uid"] == "910567"
    assert rows[0]["horse_uid"] == 1234
    assert rows[0]["finishing_position"] == "1"
    assert rows[0]["rpr"] == 88


def test_backfill_results_idempotent_on_rerun(tmp_path, monkeypatch):
    """Re-running --backfill-from over the same window must not duplicate
    rows — the upsert keys on (lot_id, race_uid)."""
    db_path = tmp_path / "test.db"

    def fake_settings():
        return Settings(
            gmail_user="u", gmail_app_password="p", email_to="a@b",
            db_path=db_path,
        )
    monkeypatch.setattr(daily, "load_settings", fake_settings)

    lot = _lot(horse_uid=1234, entry=None)
    monkeypatch.setattr(daily.rp_sales, "discover_sales", lambda year: [lot.sale])
    monkeypatch.setattr(daily.rp_sales, "fetch_lots", lambda sale: [lot])
    monkeypatch.setattr(
        daily.rp_results, "fetch_hits_for_uids",
        lambda on, uids: [
            _hit(1234, finishing_position="2", race_uid="900", race_date=on)
        ] if on == date(2026, 4, 25) else [],
    )
    monkeypatch.setattr(daily.sheet_mod, "fetch_sheet", lambda url: [])
    monkeypatch.setattr(daily.sheet_mod, "index_by_key", lambda rows: {})
    monkeypatch.setattr(daily.sheet_mod, "count_by_sale", lambda rows: {})

    daily.backfill_results(from_date=date(2026, 4, 25), to_date=date(2026, 4, 25))
    daily.backfill_results(from_date=date(2026, 4, 25), to_date=date(2026, 4, 25))

    import sqlite3
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM results_archive").fetchone()[0]
    conn.close()
    assert n == 1
