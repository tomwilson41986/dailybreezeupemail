"""Parser tests for racing.rp_sales driven by captured Racing Post fixtures."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from dailybreezeup.racing import rp_sales

FIX = Path(__file__).parent / "fixtures" / "racingpost"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _craven_sale() -> rp_sales.Sale:
    return rp_sales.Sale(
        venue_uid=5,
        sale_date=date(2026, 4, 14),
        sale_end_date=date(2026, 4, 15),
        sale_name="Tattersalls Craven Breeze Up Sale 2026",
        sale_co="Tattersalls",
    )


def test_parse_catalogues_index_extracts_sales():
    sales = rp_sales.parse_catalogues_index_html(_read("bloodstock_catalogues_index.html"))
    # Ensure we found the four 2026 breeze-up sales we care about
    breeze_2026 = rp_sales.filter_breeze_ups(sales, year=2026)
    assert len(breeze_2026) == 4
    by_uid = {s.venue_uid: s for s in breeze_2026}
    assert 5 in by_uid and by_uid[5].sale_name.startswith("Tattersalls Craven")
    assert 44 in by_uid and "Goffs UK" in by_uid[44].sale_name
    assert 36 in by_uid and "Arqana" in by_uid[36].sale_name
    assert 4 in by_uid and "Tattersalls Ireland" in by_uid[4].sale_name


def test_filter_breeze_ups_isolates_year_and_name():
    sales = rp_sales.parse_catalogues_index_html(_read("bloodstock_catalogues_index.html"))
    # Non-breeze-up sales must be filtered out (e.g. Tattersalls Cheltenham April)
    assert not any(
        "Cheltenham" in s.sale_name
        for s in rp_sales.filter_breeze_ups(sales, year=2026)
    )
    # Wrong year returns empty
    assert rp_sales.filter_breeze_ups(sales, year=2099) == []


def test_parse_lots_page_extracts_rows_with_entry_flag():
    sale = _craven_sale()
    lots_p1, current, total = rp_sales.parse_lots_page(
        _read("sale_catalogue_craven_2026_p1.json"), sale
    )
    assert current == 1
    assert total == 4
    assert len(lots_p1) == 50

    # Lot 16 is the confirmed known-entered row (Havana Grey x Hot Secret)
    lot16 = next(lot for lot in lots_p1 if lot.lot_no == 16)
    assert lot16.entered is True
    assert lot16.entry is not None
    assert lot16.entry.course_name.upper() == "NEWMARKET"
    assert lot16.entry.race_date == date(2026, 10, 3)
    assert lot16.entry.race_uid == 910567
    assert lot16.sire_name == "Havana Grey"
    assert lot16.dam_name == "Hot Secret"
    assert lot16.buyer == "Stroud Coleman Bloodstock"
    assert lot16.price_label == "GBG 350,000"
    assert lot16.age == 2
    assert lot16.year_foaled == 2024  # 2026 - 2
    assert lot16.horse_uid is not None


def test_parse_lots_page_blanks_pseudo_name_for_unnamed_lots():
    sale = _craven_sale()
    lots, _, _ = rp_sales.parse_lots_page(
        _read("sale_catalogue_craven_2026_p1.json"), sale
    )
    # All the entered lots in this fixture are unnamed; RP fills horse_style_name
    # with a "00<damname>" sort key. The parser must strip that so downstream
    # display logic sees an empty name (and falls back to "Lot N").
    lot16 = next(lot for lot in lots if lot.lot_no == 16)
    assert lot16.horse_name == ""


def test_parse_lots_page_all_pages_total_182():
    sale = _craven_sale()
    total_lots: list[rp_sales.SaleLot] = []
    last_total = None
    for p in (1, 2, 3, 4):
        rows, current, total = rp_sales.parse_lots_page(
            _read(f"sale_catalogue_craven_2026_p{p}.json"), sale
        )
        assert current == p
        last_total = total
        total_lots.extend(rows)
    assert last_total == 4
    assert len(total_lots) == 182
    entered = [lot for lot in total_lots if lot.entered]
    assert len(entered) == 4

    # Spot-check one from a later page too: lot 178 (Harry Angel x El Hadeeyah)
    lot178 = next(lot for lot in total_lots if lot.lot_no == 178)
    assert lot178.entered is True
    assert lot178.sire_name == "Harry Angel"
    assert lot178.dam_name == "El Hadeeyah"
    assert lot178.entry is not None
    assert lot178.entry.course_name.upper() == "DONCASTER"
    assert lot178.entry.race_date == date(2026, 9, 10)


def test_sale_urls_match_racing_post_shape():
    sale = _craven_sale()
    assert sale.sale_id == "rp-5-2026-04-14"
    assert sale.catalogue_url == (
        "https://www.racingpost.com/bloodstock/sales/catalogues/5/2026-04-14"
    )
    assert sale.data_url.endswith("/data.json")
