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
    # The four dedicated breeze-up sales plus the Tatts Guineas HIT (carries
    # the unsold-at-Craven 2yos, filtered to age=2 by fetch_lots).
    breeze_2026 = rp_sales.filter_breeze_ups(sales, year=2026)
    by_uid_date = {(s.venue_uid, s.sale_date.isoformat()): s for s in breeze_2026}
    assert (5, "2026-04-14") in by_uid_date and by_uid_date[(5, "2026-04-14")].sale_name.startswith("Tattersalls Craven")
    assert (44, "2026-04-22") in by_uid_date and "Goffs UK" in by_uid_date[(44, "2026-04-22")].sale_name
    assert (5, "2026-04-30") in by_uid_date and "Guineas Horses-in-Training" in by_uid_date[(5, "2026-04-30")].sale_name
    assert (36, "2026-05-09") in by_uid_date and "Arqana" in by_uid_date[(36, "2026-05-09")].sale_name
    assert (4, "2026-05-22") in by_uid_date and "Tattersalls Ireland" in by_uid_date[(4, "2026-05-22")].sale_name
    assert len(breeze_2026) == 5


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


def test_parse_lots_page_blanks_arqana_unnamed_placeholder():
    """Arqana's feed uses the literal string "Unnamed" for not-yet-named lots
    (vs Tatts/Goffs' "00<dam>" sort key). Both must blank to "" so the email
    falls back to "Lot N" rather than printing "Unnamed"."""
    sale = rp_sales.Sale(
        venue_uid=36,
        sale_date=date(2026, 5, 9),
        sale_end_date=date(2026, 5, 9),
        sale_name="Arqana May 2yo Breeze Up 2026",
        sale_co="Arqana",
    )
    body = (
        '{"rows": ['
        '{"lot_no": 1, "horse_style_name": "Unnamed", "horse_age": 2, "entered": false},'
        '{"lot_no": 2, "horse_style_name": "UNNAMED", "horse_age": 2, "entered": false},'
        '{"lot_no": 47, "horse_style_name": "Byzantine", "horse_age": 2, "entered": true}'
        '], "pagination": {"currentPage": 1, "totalPages": 1}}'
    )
    lots, _, _ = rp_sales.parse_lots_page(body, sale)
    by_lot = {lot.lot_no: lot for lot in lots}
    assert by_lot[1].horse_name == ""
    assert by_lot[2].horse_name == ""
    assert by_lot[47].horse_name == "Byzantine"


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
    pipeline running for the 2026 breeze-up sales we care about — including
    the Tatts Guineas HIT which carries unsold-at-Craven 2yos."""
    sales = rp_sales._fallback_sales(2026)
    by_uid_date = {(s.venue_uid, s.sale_date.isoformat()): s for s in sales}
    assert (5, "2026-04-14") in by_uid_date
    assert by_uid_date[(5, "2026-04-14")].sale_name.startswith("Tattersalls Craven")
    assert (5, "2026-04-30") in by_uid_date
    assert "Guineas Horses-in-Training" in by_uid_date[(5, "2026-04-30")].sale_name
    assert (44, "2026-04-22") in by_uid_date
    assert (36, "2026-05-09") in by_uid_date
    assert (4, "2026-05-22") in by_uid_date


def test_is_hit_sale_distinguishes_guineas_hit_from_pure_breezeups():
    craven = _craven_sale()
    guineas = rp_sales.Sale(
        venue_uid=5,
        sale_date=date(2026, 4, 30),
        sale_end_date=date(2026, 4, 30),
        sale_name="Tattersalls Guineas Horses-in-Training Sale 2026",
        sale_co="Tattersalls",
    )
    assert rp_sales._is_hit_sale(craven) is False
    assert rp_sales._is_hit_sale(guineas) is True


def test_fallback_sales_unknown_year_returns_empty():
    assert rp_sales._fallback_sales(2099) == []


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


# ── Sale attribution (withdrawn-then-sold dedup) ───────────────────────────


def _lot(sale: rp_sales.Sale, *, horse_uid, buyer) -> rp_sales.SaleLot:
    return rp_sales.SaleLot(
        sale=sale, lot_no=47, lot_letter="",
        horse_uid=horse_uid, horse_name="Byzantine",
        sire_uid=None, sire_name="Sire", dam_uid=None, dam_name="Dam",
        sire_of_dam_name="", sex="C", age=2, year_foaled=2024,
        seller="", price_label=None, buyer=buyer, entered=False, entry=None,
    )


def _arqana_sale() -> rp_sales.Sale:
    return rp_sales.Sale(
        venue_uid=36, sale_date=date(2026, 5, 9), sale_end_date=date(2026, 5, 9),
        sale_name="Arqana May 2yo Breeze Up 2026", sale_co="Arqana",
    )


def test_lot_was_sold_distinguishes_real_buyer_from_placeholders():
    sale = _craven_sale()
    assert rp_sales.lot_was_sold(_lot(sale, horse_uid=1, buyer="Stroud Coleman Bloodstock"))
    for marker in ("Withdrawn", "Not Sold", "Vendor", "(Bought Back)", "Unsold", None, ""):
        assert not rp_sales.lot_was_sold(_lot(sale, horse_uid=1, buyer=marker)), marker


def test_index_lots_by_uid_attributes_horse_to_sale_it_sold_at():
    """Byzantine is withdrawn at Craven and sold at Arqana under the same uid.
    The canonical lot must be the Arqana one (the sale it actually sold at)."""
    craven = _lot(_craven_sale(), horse_uid=8688568, buyer="Withdrawn")
    arqana = _lot(_arqana_sale(), horse_uid=8688568, buyer="Haras de Saint Pair")

    # Order must not matter: sold beats withdrawn either way.
    for lots in ([craven, arqana], [arqana, craven]):
        by_uid = rp_sales.index_lots_by_uid(lots)
        assert by_uid[8688568].sale.sale_co == "Arqana"


def test_index_lots_by_uid_skips_unnamed_lots():
    assert rp_sales.index_lots_by_uid([_lot(_arqana_sale(), horse_uid=None, buyer="X")]) == {}


def test_index_lots_by_uid_prefers_later_sale_when_neither_sold():
    """Withdrawn at both sales: keep the later (re-offered) sale deterministically."""
    craven = _lot(_craven_sale(), horse_uid=42, buyer="Withdrawn")
    arqana = _lot(_arqana_sale(), horse_uid=42, buyer="Not Sold")
    by_uid = rp_sales.index_lots_by_uid([arqana, craven])
    assert by_uid[42].sale.sale_co == "Arqana"
