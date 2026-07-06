"""Offline test for the Friday weekly summary (daily.run_weekly)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from dailybreezeup import daily, db
from dailybreezeup import sheet as sheet_mod
from dailybreezeup.config import Settings
from dailybreezeup.racing import rp_sales
from dailybreezeup.results_report import HorseStats


def _sale() -> rp_sales.Sale:
    return rp_sales.Sale(
        venue_uid=5,
        sale_date=date(2026, 4, 14),
        sale_end_date=date(2026, 4, 15),
        sale_name="Tattersalls Craven Breeze Up Sale 2026",
        sale_co="Tattersalls",
    )


def _lot() -> rp_sales.SaleLot:
    return rp_sales.SaleLot(
        sale=_sale(),
        lot_no=16,
        lot_letter="",
        horse_uid=9175073,
        horse_name="Efsixteen",
        sire_uid=None,
        sire_name="Havana Grey",
        dam_uid=None,
        dam_name="Hot Secret",
        sire_of_dam_name="Sakhee's Secret",
        sex="F",
        age=2,
        year_foaled=2024,
        seller="From Yeomanstown Stud, Ireland",
        price_label="GBG 350,000",
        buyer="Stroud Coleman Bloodstock",
        entered=False,
        entry=None,
    )


def _archive_row(race_date: str) -> dict:
    return {
        "lot_id": _lot().lot_id,
        "race_uid": "912345",
        "horse_uid": 9175073,
        "horse_name": "Efsixteen",
        "sale_year": 2026,
        "sale_short": "Craven",
        "sale_name": "Tattersalls Craven Breeze Up Sale 2026",
        "lot_no": 16,
        "race_date": race_date,
        "course": "Newmarket",
        "off_time": "16:10:00",
        "race_name": "EBF Fillies' Novice Stakes",
        "finishing_position": "1",
        "total_runners": 8,
        "sp": "11/4",
        "rpr": 89,
    }


def test_run_weekly_renders_week_from_archive(monkeypatch, tmp_path):
    friday = date(2026, 7, 10)
    db_path = tmp_path / "breezeup.sqlite"
    monkeypatch.chdir(tmp_path)  # previews write to ./data/

    # Archive: one run inside the week, one before it.
    with db.session(db_path) as conn:
        assert db.upsert_result_row(conn, _archive_row("2026-07-07"))
        old = _archive_row("2026-06-01")
        old["race_uid"] = "900001"
        assert db.upsert_result_row(conn, old)

    monkeypatch.setattr(
        daily, "load_settings",
        lambda: Settings(db_path=db_path, email_to="", season_start_date=date(2026, 7, 1)),
    )
    monkeypatch.setattr(daily.rp_sales, "discover_sales", lambda year: [_sale()])
    monkeypatch.setattr(daily.rp_sales, "fetch_lots", lambda sale: [_lot()])
    # No live results scrapes: today + backfilled days all return no hits.
    monkeypatch.setattr(daily.rp_results, "fetch_hits_for_uids", lambda on, uids: [])
    monkeypatch.setattr(
        daily.sheet_mod, "fetch_sheet",
        lambda url: [sheet_mod.SheetRow(
            year=2026, sale="Craven", lot=16, sex="F", sire="Havana Grey (GB)",
            dam="Hot Secret (GB)", vendor="Yeomanstown Stud", buyer="Stroud Coleman",
            price="350,000", ot_diff_m=-0.44, ot_rank=24, sl_1f=7.07, sl_go=6.7,
            breeze_rating=85.7, precocity_rating=101.4,
        )],
    )
    import dailybreezeup.results_report as rr
    monkeypatch.setattr(
        rr, "collect_form_stats",
        lambda lots, session, **kw: {9175073: HorseStats(runs=1, fto_rpr=89, peak_rpr=89)},
    )
    monkeypatch.setattr(
        rr, "build_workbook_bytes", lambda rows, lot_map, stats: b"xlsx-bytes"
    )

    assert daily.run_weekly(run_date=friday, dry_run=True) == 0

    text = Path("data/last_preview.txt").read_text(encoding="utf-8")
    assert "RAN THIS WEEK · 1" in text
    assert "Efsixteen" in text
    assert "Tue 07 Jul" in text
    assert "RPR 89" in text
    assert "workbook attached" in text
    # season summary covers the archive, not just the week
    assert "SEASON TO DATE" in Path("data/last_preview.txt").read_text(encoding="utf-8")

    with db.session(db_path) as conn:
        status = conn.execute(
            "SELECT status FROM run_log ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert status == "dry_run"
