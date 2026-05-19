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


def test_fallback_sales_returns_known_2026_breezeups():
    """When the index page is blocked, the hardcoded fallback list keeps the
    pipeline running for the four 2026 breeze-up sales we care about."""
    sales = rp_sales._fallback_sales(2026)
    by_uid = {s.venue_uid: s for s in sales}
    assert set(by_uid) == {5, 44, 36, 4}
    assert by_uid[5].sale_date == date(2026, 4, 14)
    assert by_uid[5].sale_name.startswith("Tattersalls Craven")


def test_fallback_sales_unknown_year_returns_empty():
    assert rp_sales._fallback_sales(2099) == []


def test_extra_sales_includes_tattersalls_guineas_2026():
    """The Tattersalls Guineas Breeze Up is the tail of a Horses-in-Training
    sale on RP, so its name doesn't match /breeze.?up/i. It has to be merged
    in explicitly via the _EXTRA_SALES table."""
    extras = rp_sales._extra_sales(2026)
    assert len(extras) == 1
    sale = extras[0]
    assert sale.venue_uid == 5
    assert sale.sale_date == date(2026, 4, 30)
    assert "Guineas" in sale.sale_name
    # Breeze-up section starts after lot 161 (lots 162+).
    assert sale.min_lot_no == 162
    # Distinct URL from the Craven sale at the same venue.
    assert sale.sale_id == "rp-5-2026-04-30"


def test_merge_sales_dedupes_by_sale_id_and_preserves_order():
    a = rp_sales.Sale(venue_uid=5, sale_date=date(2026, 4, 14),
                      sale_end_date=date(2026, 4, 15),
                      sale_name="A", sale_co="X")
    b = rp_sales.Sale(venue_uid=5, sale_date=date(2026, 4, 30),
                      sale_end_date=date(2026, 5, 1),
                      sale_name="B", sale_co="X", min_lot_no=162)
    dup_a = rp_sales.Sale(venue_uid=5, sale_date=date(2026, 4, 14),
                          sale_end_date=date(2026, 4, 15),
                          sale_name="A again", sale_co="X")
    merged = rp_sales._merge_sales([a], [b, dup_a])
    assert [s.sale_name for s in merged] == ["A", "B"]


def test_parse_lots_page_respects_min_lot_no_via_filter():
    """``parse_lots_page`` itself is unfiltered (it returns every row in the
    page so callers can paginate), but ``fetch_lots`` applies the
    ``Sale.min_lot_no`` cutoff after collecting all pages. Simulate that here
    by parsing the Craven fixture against a Guineas-shaped sale."""
    sale = rp_sales.Sale(
        venue_uid=5,
        sale_date=date(2026, 4, 30),
        sale_end_date=date(2026, 5, 1),
        sale_name="Tattersalls Guineas Breeze Up Sale 2026",
        sale_co="Tattersalls",
        min_lot_no=162,
    )
    lots, _, _ = rp_sales.parse_lots_page(
        _read("sale_catalogue_craven_2026_p4.json"), sale
    )
    # parse_lots_page must not pre-filter — that would break pagination logic.
    assert any(lot.lot_no < 162 for lot in lots)
    # The post-fetch filter (mirrored from fetch_lots) drops the early lots.
    kept = [lot for lot in lots if lot.lot_no >= sale.min_lot_no]
    assert kept
    assert all(lot.lot_no >= 162 for lot in kept)


def test_demo_lots_returns_four_entered_craven_lots():
    lots = rp_sales.demo_lots()
    assert len(lots) == 4
    assert all(lot.entered for lot in lots)
    assert all(lot.entry is not None for lot in lots)
    by_lot = {lot.lot_no: lot for lot in lots}
    assert set(by_lot) == {16, 65, 73, 178}
    assert by_lot[16].sire_name == "Havana Grey"
    assert by_lot[16].entry.course_name == "NEWMARKET"
    assert by_lot[16].entry.race_date == date(2026, 10, 3)
    # Three of the four have horse_uid; lot 178 is unregistered so uid=None
    assert by_lot[178].horse_uid is None
