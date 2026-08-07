"""Tests for the morning/evening classification glue in dailybreezeup.daily."""
from __future__ import annotations

from datetime import date, datetime, time, timezone

from dailybreezeup import daily
from dailybreezeup import sheet as sheet_mod
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


def test_catalogue_entry_beyond_racecard_window_surfaces_within_catalogue_window():
    """Regression: a catalogue entry 4 days out (one day past the 3-day
    racecard window) must still surface via the wider catalogue horizon.

    This is the bug where breeze-up grads entered for a race 4+ days out were
    dropped from every morning email — the racecard scan can't see them yet
    (declarations publish ~48h out) and the catalogue fallback was capped at
    the same 3-day window. Mirrors the real Cosmic Mystery / Alta Regina miss
    (entered for Nottingham 4 days out)."""
    today = date(2026, 5, 30)
    entry = rp_sales.EntryDetails(
        course_uid=40,
        course_name="NOTTINGHAM",
        race_date=date(2026, 6, 3),  # today + 4 days: outside the 3-day window
        race_uid=919980,
    )
    lot = _lot(horse_uid=9312929, entry=entry)

    # With the catalogue horizon left at the racecard window, it's dropped.
    dropped, _ = daily._classify(
        today, [lot], results=[], racecard_entries=[],
        entries_window_days=3,
        catalogue_entries_window_days=3,
    )
    assert dropped == []

    # With the wider catalogue horizon it surfaces.
    surfaced, _ = daily._classify(
        today, [lot], results=[], racecard_entries=[],
        entries_window_days=3,
        catalogue_entries_window_days=7,
    )
    assert len(surfaced) == 1
    assert surfaced[0]["race_date"] == date(2026, 6, 3)


def test_catalogue_long_range_entry_excluded_by_catalogue_window():
    """The catalogue carries long-range entries (months out). The catalogue
    horizon must still cap those so the morning email isn't flooded with a
    horse entered for an October race every day until October."""
    today = date(2026, 5, 30)
    entry = rp_sales.EntryDetails(
        course_uid=38,
        course_name="NEWMARKET",
        race_date=date(2026, 10, 3),  # ~4 months out
        race_uid=910567,
    )
    lot = _lot(horse_uid=8688568, entry=entry)

    entered, _ = daily._classify(
        today, [lot], results=[], racecard_entries=[],
        entries_window_days=3,
        catalogue_entries_window_days=7,
    )
    assert entered == []


def test_catalogue_window_defaults_to_racecard_window_when_unset():
    """Back-compat: callers that don't pass catalogue_entries_window_days get
    the old behaviour (both paths share entries_window_days)."""
    today = date(2026, 5, 30)
    entry = rp_sales.EntryDetails(
        course_uid=40,
        course_name="NOTTINGHAM",
        race_date=date(2026, 6, 3),  # today + 4 days
        race_uid=919980,
    )
    lot = _lot(horse_uid=9312929, entry=entry)

    entered, _ = daily._classify(
        today, [lot], results=[], racecard_entries=[],
        entries_window_days=3,
    )
    assert entered == []


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


def test_morning_entries_ordered_by_race_time_earliest_first():
    """The morning email must list entries by race time, earliest to latest
    within each day. Build three racecard entries deliberately out of order —
    a later same-day race, an earlier same-day race, and a next-day race — and
    assert they come back ordered by (race_date, off_time)."""
    today = date(2026, 4, 24)

    def _rc(uid: int, *, race_date: date, off_time: time, race_uid: str) -> rp_racecards.RacecardEntry:
        return rp_racecards.RacecardEntry(
            horse_uid=uid,
            horse_slug=f"h{uid}",
            horse_name=f"Horse {uid}",
            course_uid=38,
            course="Newmarket",
            race_date=race_date,
            off_time=off_time,
            race_name="Maiden Stakes",
            race_url=f"https://www.racingpost.com/racecards/38/newmarket/{race_date.isoformat()}/{race_uid}",
            race_uid=race_uid,
            silk_url=None,
        )

    lots = [_lot(horse_uid=uid, entry=None) for uid in (1, 2, 3)]
    racecards = [
        _rc(1, race_date=date(2026, 4, 25), off_time=time(16, 5), race_uid="901"),
        _rc(2, race_date=date(2026, 4, 25), off_time=time(13, 40), race_uid="902"),
        _rc(3, race_date=date(2026, 4, 26), off_time=time(14, 0), race_uid="903"),
    ]

    entered, _ran = daily._classify(
        today, lots, results=[], racecard_entries=racecards,
        entries_window_days=3,
    )

    assert [r["off_time"] for r in entered] == [time(13, 40), time(16, 5), time(14, 0)]
    assert [r["race_date"] for r in entered] == [
        date(2026, 4, 25), date(2026, 4, 25), date(2026, 4, 26),
    ]


def test_racecard_name_fallback_resolves_lot_without_uid():
    """A grad whose catalogue lot has no horse_uid still surfaces: the racecard
    runner is matched by name (the runner carries its own real uid, which isn't
    in our catalogue), and _classify resolves it back to the named lot via the
    name index. Mirrors the catalogue-lag case the morning email must survive."""
    today = date(2026, 5, 30)
    # Catalogue lot: named, but RP hasn't linked a horse_uid to it yet.
    lot = rp_sales.SaleLot(
        sale=_sale(), lot_no=42, lot_letter="", horse_uid=None,
        horse_name="Phantom Lot", sire_uid=None, sire_name="Kodiac",
        dam_uid=None, dam_name="Spectre", sire_of_dam_name="", sex="F",
        age=2, year_foaled=2024, seller="", price_label=None, buyer=None,
        entered=False, entry=None,
    )
    # Racecard runner: declared today, carrying its own (catalogue-unknown) uid.
    rc = rp_racecards.RacecardEntry(
        horse_uid=8000001, horse_slug="phantom-lot", horse_name="Phantom Lot",
        course_uid=31, course="Lingfield", race_date=today, off_time=time(19, 12),
        race_name="Novice Stakes",
        race_url="https://www.racingpost.com/racecards/31/lingfield/2026-05-30/919050",
        race_uid="919050", silk_url=None,
    )

    entered, _ran = daily._classify(
        today, [lot], results=[], racecard_entries=[rc],
        entries_window_days=3,
    )
    assert len(entered) == 1
    assert entered[0]["lot_id"] == lot.lot_id
    assert entered[0]["race_date"] == today
    assert entered[0]["off_time"] == time(19, 12)


def test_resort_entered_keeps_race_time_order_over_breeze_rating():
    """After sheet enrichment the entries are resorted, but race time must stay
    the primary key — a later race with a higher Breeze Rating must not jump
    ahead of an earlier race. Rating only breaks ties within the same race."""
    rows = [
        {"race_date": date(2026, 4, 25), "off_time": time(16, 5),
         "course": "Newmarket", "sheet_breeze_rating": 99.0, "lot": 1},
        {"race_date": date(2026, 4, 25), "off_time": time(13, 40),
         "course": "Newmarket", "sheet_breeze_rating": 50.0, "lot": 2},
        {"race_date": date(2026, 4, 25), "off_time": time(13, 40),
         "course": "Newmarket", "sheet_breeze_rating": 80.0, "lot": 3},
    ]
    daily._resort_entered(rows)

    # Earliest race first, even though its horses rate lower; within the 13:40
    # race the higher Breeze Rating (lot 3) leads.
    assert [r["lot"] for r in rows] == [3, 2, 1]


def test_guineas_and_arqana_entered_lots_surface_via_entry_details():
    """Guineas HIT and Arqana grads reach the morning email through the
    catalogue's entry_details path — no horse_uid or racecard match required.
    Arqana in particular barely populates horse_uid, so the entry_details
    fallback is the only thing that surfaces its declared runners."""
    today = date(2026, 5, 23)

    def _sale_lot(sale, *, lot_no, horse_uid, name, entry):
        return rp_sales.SaleLot(
            sale=sale, lot_no=lot_no, lot_letter="",
            horse_uid=horse_uid, horse_name=name,
            sire_uid=None, sire_name="Sire", dam_uid=None, dam_name="Dam",
            sire_of_dam_name="", sex="F", age=2, year_foaled=2024,
            seller="", price_label=None, buyer=None,
            entered=True, entry=entry,
        )

    guineas = rp_sales.Sale(
        venue_uid=5, sale_date=date(2026, 4, 30), sale_end_date=date(2026, 4, 30),
        sale_name="Tattersalls Guineas Horses-in-Training Sale 2026", sale_co="Tattersalls",
    )
    arqana = rp_sales.Sale(
        venue_uid=36, sale_date=date(2026, 5, 9), sale_end_date=date(2026, 5, 9),
        sale_name="Arqana May 2yo Breeze Up 2026", sale_co="Arqana",
    )
    my_maria = _sale_lot(
        guineas, lot_no=176, horse_uid=9281137, name="My Maria",
        entry=rp_sales.EntryDetails(
            course_uid=47, course_name="REDCAR",
            race_date=date(2026, 5, 25), race_uid=918936),
    )
    # Arqana lot with NO horse_uid — only entry_details links it to a race.
    byzantine = _sale_lot(
        arqana, lot_no=47, horse_uid=None, name="Byzantine",
        entry=rp_sales.EntryDetails(
            course_uid=104, course_name="YARMOUTH",
            race_date=date(2026, 5, 25), race_uid=918989),
    )

    entered, _ran = daily._classify(
        today, [my_maria, byzantine], results=[], racecard_entries=[],
        entries_window_days=3,
    )
    surfaced = {(r["sale_co"], r["horse_name"]) for r in entered}
    assert ("Tattersalls", "My Maria") in surfaced
    assert ("Arqana", "Byzantine") in surfaced


def test_guineas_lot_gets_sheet_ratings_via_sale_alias():
    """A Guineas HIT lot must pick up its gSheet ratings. The sheet labels these
    rows "Guineas", so sale_short_name has to resolve the verbose RP name to that
    short label or _enrich_with_sheet skips the row (sale_short is None)."""
    guineas = rp_sales.Sale(
        venue_uid=5, sale_date=date(2026, 4, 30), sale_end_date=date(2026, 4, 30),
        sale_name="Tattersalls Guineas Horses-in-Training Sale 2026", sale_co="Tattersalls",
    )
    lot = rp_sales.SaleLot(
        sale=guineas, lot_no=176, lot_letter="",
        horse_uid=9281137, horse_name="My Maria",
        sire_uid=None, sire_name="Sire", dam_uid=None, dam_name="Dam",
        sire_of_dam_name="", sex="F", age=2, year_foaled=2024,
        seller="", price_label=None, buyer=None, entered=True, entry=None,
    )
    row = daily._lot_row(lot, race_uid=None)
    assert row["sale_short"] == "Guineas"

    sheet_row = sheet_mod.SheetRow(
        year=2026, sale="Guineas", lot=176, sex="F", sire="Sire", dam="Dam",
        vendor="", buyer="", price="", ot_diff_m=None, ot_rank=None,
        sl_1f=None, sl_go=None, breeze_rating=99.5, precocity_rating=88.0,
    )
    index = sheet_mod.index_by_key([sheet_row])
    matched, missing = daily._enrich_with_sheet([row], index)

    assert (matched, missing) == (1, 0)
    assert row["sheet_matched"] is True
    assert row["sheet_breeze_rating"] == 99.5
    assert row["sheet_precocity_rating"] == 88.0


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


# ── Season self-heal (evening auto-backfill) ───────────────────────────────


def test_ensure_season_archive_walks_unscraped_days_and_marks_today(tmp_path, monkeypatch):
    """The evening self-heal walks every result date from season_start up to
    (but not including) today, writes matching outcomes, and records each
    walked day plus today in results_scrape_log."""
    from dailybreezeup import db

    lot = _lot(horse_uid=1234, entry=None)
    by_uid = {1234: lot}

    walked: list[date] = []

    def fake_fetch_hits(on, uids):
        walked.append(on)
        if on == date(2026, 4, 2):
            return [_hit(1234, finishing_position="1", race_uid="555", race_date=on, rpr=90)]
        return []

    monkeypatch.setattr(daily.rp_results, "fetch_hits_for_uids", fake_fetch_hits)

    conn = db.connect(tmp_path / "season.db")
    db.migrate(conn)
    fill = daily._ensure_season_archive(
        conn,
        season_start=date(2026, 4, 1),
        today=date(2026, 4, 4),
        by_uid=by_uid,
        sheet_index={},
        sale_totals={},
    )

    # Today (04-04) is covered by the live results fetch, so it's not walked.
    assert walked == [date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3)]
    assert fill == {"days_scraped": 3, "rows_added": 1}

    archived = conn.execute(
        "SELECT race_uid, finishing_position FROM results_archive"
    ).fetchall()
    assert [(r["race_uid"], r["finishing_position"]) for r in archived] == [("555", "1")]

    # Walked days plus today are all recorded so we never re-scrape them.
    assert db.scraped_result_dates(conn) == {
        "2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04",
    }
    conn.close()


def test_ensure_season_archive_skips_already_scraped_days(tmp_path, monkeypatch):
    """Days already in results_scrape_log are never re-fetched — that's what
    keeps the steady-state evening run cheap (only today gets scraped)."""
    from dailybreezeup import db

    lot = _lot(horse_uid=1234, entry=None)
    by_uid = {1234: lot}

    walked: list[date] = []
    monkeypatch.setattr(
        daily.rp_results, "fetch_hits_for_uids",
        lambda on, uids: walked.append(on) or [],
    )

    conn = db.connect(tmp_path / "season.db")
    db.migrate(conn)
    for iso in ("2026-04-01", "2026-04-02"):
        db.mark_result_date_scraped(conn, iso)

    fill = daily._ensure_season_archive(
        conn,
        season_start=date(2026, 4, 1),
        today=date(2026, 4, 4),
        by_uid=by_uid,
        sheet_index={},
        sale_totals={},
    )

    # Only 04-03 was unscraped (04-01/04-02 pre-marked, 04-04 is today).
    assert walked == [date(2026, 4, 3)]
    assert fill["days_scraped"] == 1
    conn.close()


# ── Results run date anchoring (delayed cron) ──────────────────────────────


def _utc(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_evening_run_date_anchors_to_slot_when_cron_crosses_midnight():
    """The 6 Aug 2026 regression: the 21:00 UTC evening slot started at 00:58
    UTC on the 7th, so the wall clock said the 7th and the job asked RP for a
    day that hadn't been raced — the email went out as "No Results Today"
    while eight graduates had run on the 6th. The run date must follow the
    slot, not the clock."""
    got = daily._results_run_date(
        daily.EVENING_SLOT_UTC, now=_utc(2026, 8, 7, 0, 58)
    )
    assert got == date(2026, 8, 6)


def test_evening_run_date_is_today_when_cron_fires_on_time():
    """An on-time (or mildly late) evening run still reports on the day it
    fired — BST puts 21:00 UTC at 22:00 UK, comfortably before midnight."""
    got = daily._results_run_date(
        daily.EVENING_SLOT_UTC, now=_utc(2026, 8, 5, 22, 3)
    )
    assert got == date(2026, 8, 5)


def test_evening_run_date_anchors_in_winter_when_uk_is_on_gmt():
    """Outside BST the slot lands at 21:00 UK, so the anchoring has to survive
    the offset change rather than assuming a fixed +1."""
    assert daily._results_run_date(
        daily.EVENING_SLOT_UTC, now=_utc(2026, 1, 15, 21, 30)
    ) == date(2026, 1, 15)
    assert daily._results_run_date(
        daily.EVENING_SLOT_UTC, now=_utc(2026, 1, 16, 1, 0)
    ) == date(2026, 1, 15)


def test_evening_run_date_falls_back_to_wall_clock_outside_grace():
    """An ad-hoc run in the middle of the day is not a late cron, so it means
    today — reaching back to the previous slot would be wrong."""
    got = daily._results_run_date(
        daily.EVENING_SLOT_UTC, now=_utc(2026, 8, 7, 14, 0)
    )
    assert got == date(2026, 8, 7)


def test_weekly_run_date_anchors_to_friday_slot_after_midnight():
    """The Friday 21:30 UTC weekly slot has the same exposure: delayed into
    Saturday it would shift the whole 7-day window and scrape an unraced day."""
    got = daily._results_run_date(
        daily.WEEKLY_SLOT_UTC, now=_utc(2026, 8, 8, 1, 30)
    )
    assert got == date(2026, 8, 7)  # the Friday


def test_evening_run_reports_on_anchored_date_end_to_end(tmp_path, monkeypatch):
    """The anchored date has to reach the RP results fetch and the archive, not
    just the helper — that join is what broke. Simulates the delayed cron: the
    slot resolves to the 6th while the wall clock has rolled to the 7th."""
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "test.db"

    def fake_settings():
        return Settings(
            gmail_user="u", gmail_app_password="p", email_to="a@b",
            db_path=db_path, season_start_date=date(2026, 8, 6),
        )
    monkeypatch.setattr(daily, "load_settings", fake_settings)

    lot = _lot(horse_uid=1234, entry=None)
    monkeypatch.setattr(daily.rp_sales, "discover_sales", lambda year: [lot.sale])
    monkeypatch.setattr(daily.rp_sales, "fetch_lots", lambda sale: [lot])
    monkeypatch.setattr(daily.sheet_mod, "fetch_sheet", lambda url: [])
    monkeypatch.setattr(daily.sheet_mod, "index_by_key", lambda rows: {})
    monkeypatch.setattr(daily.sheet_mod, "count_by_sale", lambda rows: {})
    monkeypatch.setattr(
        daily, "_results_run_date", lambda slot, now=None: date(2026, 8, 6)
    )

    asked: list[date] = []

    def fake_fetch_hits(on, uids):
        asked.append(on)
        if on == date(2026, 8, 6):
            return [_hit(1234, finishing_position="1", race_uid="910567",
                         race_date=on, rpr=88)]
        return []

    monkeypatch.setattr(daily.rp_results, "fetch_hits_for_uids", fake_fetch_hits)

    rc = daily.run(mode="evening", dry_run=True)
    assert rc == 0
    # The live results fetch asked for the 6th, and the runner it found was
    # carried into the email body rather than dropped as "No Results Today".
    assert asked[0] == date(2026, 8, 6)
    assert "Horse 1234" in daily.PREVIEW_TXT.read_text(encoding="utf-8")

    import sqlite3
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT race_date FROM results_archive").fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["2026-08-06"]
