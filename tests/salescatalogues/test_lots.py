"""Lot-parser tests against trimmed real catalogue snapshots, so a site/API
change that breaks lot extraction fails here rather than silently emptying the
CSV's lot rows.
"""
import json
from pathlib import Path

from salescatalogues.sources import (
    arqana,
    bbag,
    fasigtipton,
    gavelhouse,
    goffs,
    inglis,
    keeneland,
    magicmillions,
    nzb,
    obs,
    tattersalls,
    thoroughbid,
)

FX = Path(__file__).resolve().parents[1] / "fixtures" / "salescatalogues"


def _read(name: str, *, encoding: str = "utf-8") -> str:
    return (FX / name).read_text(encoding=encoding, errors="replace")


def _json(name: str):
    return json.loads(_read(name))


# --- HTML lot tables -------------------------------------------------------

def test_tattersalls_lots():
    lots = tattersalls.parse_lots(_read("tattersalls_lots.html"))
    assert len(lots) == 3
    first = lots[0]
    assert first.lot_no == "1"
    assert first.horse_name == "Author Dora (TUR)"
    assert first.sire == "Authorized (IRE)" and first.dam == "Lavin (TUR)"
    assert first.sex == "Mare" and first.colour == "Bay"
    assert first.vendor == "Gary Downie"


def test_goffs_lots_unnamed_youngstock():
    lots = goffs.parse_lots(_read("goffs_lots.html"))
    assert len(lots) == 3
    first = lots[0]
    assert first.lot_no == "1"
    assert first.horse_name == ""  # breeze-up youngstock are unnamed
    assert first.sire == "Palace Pier (GB)" and first.dam == "Flora Danica (IRE)"
    assert first.sex == "Colt" and first.colour == "Chestnut"
    assert first.vendor == "The Bloodstock Connection"


def test_inglis_lots():
    lots = inglis.parse_lots(_read("inglis_lots.html"))
    assert len(lots) == 3
    assert lots[0].lot_no == "1"
    assert lots[0].sire == "Hitotsu" and lots[0].dam == "Saavoya (NZ)"
    assert lots[0].sex == "Filly"
    assert lots[0].vendor == "Sledmere Stud"


def test_magicmillions_lots_have_damsire():
    lots = magicmillions.parse_lots(_read("magicmillions_lots.html"))
    assert len(lots) >= 3
    lot1 = next(x for x in lots if x.lot_no == "1")
    assert lot1.sire == "Gingerbread Man (AUS)"
    assert lot1.dam == "Ofcourse She Does (AUS)"
    assert lot1.dam_sire == "Murtajill (AUS)"
    assert lot1.vendor == "Yarradale Stud"


def test_arqana_lots():
    lots = arqana.parse_lots(_read("arqana_lots.html"))
    assert len(lots) == 3
    assert lots[0].lot_no == "1"
    assert lots[0].sire == "BLUE POINT"
    assert lots[0].sex == "Colt"
    assert lots[0].vendor == "Knockanglass Stables"


def test_nzb_lots_from_embedded_blob():
    lots = nzb.parse_lots(_read("nzb_lots.html"))
    assert len(lots) == 3
    assert lots[0].lot_no == "1"
    assert lots[0].sire == "Redwood"
    assert lots[0].sex == "Filly" and lots[0].colour == "Bay"
    assert lots[0].vendor == "Westbury Stud"


# --- JSON APIs -------------------------------------------------------------

def test_obs_lots():
    lots = obs.parse_lots(_json("obs_lots.json"))
    assert len(lots) == 3
    by_hip = {x.lot_no: x for x in lots}
    assert "1" in by_hip
    assert by_hip["1"].dam_sire  # damsire populated
    assert by_hip["1"].vendor


def test_keeneland_lots():
    lots = keeneland.parse_lots(_json("keeneland_lots.json"))
    assert lots, "expected at least one hip"
    assert lots[0].lot_no
    assert lots[0].sire and lots[0].dam


def test_fasigtipton_lots_blank_placeholder_name():
    lots = fasigtipton.parse_lots(_json("fasigtipton_lots.json"))
    assert len(lots) == 3
    # "YYYY-DAMNAME" placeholder names are blanked.
    assert all(not (lot.horse_name[:4].isdigit() and "-" in lot.horse_name[:5])
               for lot in lots)
    assert lots[0].sire and lots[0].dam_sire


def test_gavelhouse_lots_enum_decode():
    lots = gavelhouse.parse_lots(_json("gavelhouse_lots.json"))
    assert lots
    assert lots[0].sex in {"Colt", "Filly", "Gelding", "Mare", "Horse"}
    assert lots[0].colour  # decoded from the integer enum


def test_thoroughbid_lots():
    lots = thoroughbid.parse_lots(_read("thoroughbid_lots.html"))
    assert len(lots) == 3
    # Unnamed youngstock are listed as "\'24 Sire ex Dam" — a placeholder, not
    # a name — but the pedigree line still gives sire and dam.
    assert lots[0].lot_no == "1" and lots[0].horse_name == ""
    assert lots[0].sire == "Blue Point (IRE)" and lots[0].dam == "Golden Pearl (GB)"
    assert lots[0].sex == "Colt"  # spelled out from the cell's tooltip, not "C"
    assert lots[0].vendor == "Landfall Stables"
    named = lots[2]
    assert named.lot_no == "7" and named.horse_name == "Harpers Frontier (IRE)"
    assert named.sire == "Sans Frontieres (IRE)" and named.dam == "Daveoin (IRE)"
    assert named.sex == "Gelding" and named.vendor == "Gordon Elliott Racing"


def test_bbag_lots():
    lots = bbag.parse_lots(_json("bbag_lots.json"))
    assert len(lots) == 3
    assert lots[0].sire and lots[0].dam
    assert lots[0].vendor


# --- catalogue_ref capture in the discovery parsers ------------------------

def test_tattersalls_captures_sale_code():
    rows = tattersalls.parse_saledates(
        _read("tattersalls_saledates_nmt.html"),
        country="UK", house="Tattersalls", ref=__import__("datetime").date(2026, 6, 9),
    )
    assert any(r.catalogue_ref for r in rows), "expected a 4D sale code captured"


def test_thoroughbid_captures_collection_id():
    rows = thoroughbid.parse_collections(
        _read("thoroughbid_collections.html"),
        ref=__import__("datetime").date(2026, 7, 29),
    )
    assert any(r.catalogue_ref for r in rows), "expected a collection id captured"


def test_empty_inputs_return_no_lots():
    assert obs.parse_lots({}) == []
    assert keeneland.parse_lots({}) == []
    assert fasigtipton.parse_lots([]) == []
    assert tattersalls.parse_lots("<html></html>") == []
    assert thoroughbid.parse_lots("<html></html>") == []


# --- formats the Gun Runner weekly relies on (trimmed from live pages, Oct 2026) ---

def test_tattersalls_foal_rows_split_sire_and_dam():
    lots = tattersalls.parse_lots(_read("tattersalls_foal_lots.html"))
    assert [lot.lot_no for lot in lots] == ["201", "202", "203"]
    filly = lots[1]
    assert filly.horse_name == ""
    assert filly.sire == "Bradsell (GB)" and filly.dam == "Swan Band (GB)"
    assert filly.sex == "Filly" and filly.colour == "Bay"
    assert filly.vendor == "Paere Dansk Ltd."


def test_goffs_breeding_stock_reads_lot_attributes():
    lots = goffs.parse_lots(_read("goffs_breeding_stock_lots.html"))
    mare = lots[0]
    assert mare.horse_name == "Morning Jewel (IRE)"
    assert mare.sire == "Dalakhani (IRE)" and mare.dam == "Morning Welcome (IRE)"
    assert mare.dam_sire == "Be My Guest (USA)"
    assert mare.covering_sire == "Naval Crown (GB)"
    assert mare.yob == 2012 and mare.sex == "Mare" and mare.lot_type == "MAR"
    assert mare.vendor == "Middlelane Farm" and mare.colour == "Grey"


def test_arqana_breeding_lots_dam_cover_and_product():
    lots = arqana.parse_lots(_read("arqana_breeding_lots.html"))
    foal, maiden, mare = lots
    assert foal.dam == "FRENCH SPIRIT" and foal.lot_type == "Foal"
    assert maiden.horse_name == "GHOSTED" and maiden.lot_type == "Maiden" and maiden.covering_sire == ""
    assert mare.covering_sire == "METROPOLITAN" and mare.lot_type == "Jument"


def test_keeneland_sale_data_feed():
    import json
    lots = {lot.lot_no: lot for lot in keeneland.parse_lots(json.loads(_read("keeneland_sale_data.json")))}
    assert lots["1"].horse_name == "" and lots["1"].yob == 2026 and lots["1"].lot_type == "Weanling"
    caviar = lots["4"]
    assert caviar.horse_name == "American Caviar" and caviar.yob == 2019
    assert caviar.covering_sire == "Nyquist" and caviar.breeding_status == "PR"
    assert lots["21"].breeding_status == "NP"


# --- online sales (trimmed from the live platforms, Oct 2026) ---------------

def test_goffsgo_cards_one_lot_each():
    lots = goffs.parse_lots(_read("goffsgo_lots.html"))
    # a lot shown as a card and again in the table counts once
    assert [lot.lot_no for lot in lots] == ["1", "22", "4", "58"]
    filly = lots[0]
    assert filly.horse_name == "" and filly.sex == "Filly" and filly.yob == 2025
    assert filly.colour == "Bay" and filly.lot_type == "YRL"
    assert filly.url == "https://www.goffs.com/sale/GoffsGo/GoffsGo-October-Sale/lots/1"
    assert lots[1].horse_name == "Back Down Under (IRE)" and lots[1].sex == "Mare"


def test_goffsgo_sales_dated_and_linked():
    from datetime import date

    rows = goffs.parse_upcoming(_read("goffsgo_upcoming.html"), ref=date(2026, 10, 21))
    nov = rows[0]
    assert nov.name == "GoffsGo November Sale" and nov.online
    assert nov.start_date == date(2026, 11, 25)      # not the "£49" in the same line
    assert nov.url == "https://www.goffs.com/sale/GoffsGo/GoffsGo-November-Sale"


def test_bbag_online_lots():
    lots = bbag.parse_lots(_json("bbag_online_lots.json"))
    # the "01 - " lot prefix dropped
    assert [lot.horse_name for lot in lots] == ["Aktivist", "Divina Gloria (FR)", "La Santa Monica"]
    mare = lots[1]
    assert mare.sex == "Broodmare" and mare.yob == 2017
    assert mare.sire == "Dabirsim (FR)" and mare.dam_sire == "Exceed and Excel"
    assert lots[2].covering_sire == "Isfahan (GER)"


def test_bbag_finds_the_platform_slug():
    auctions = _json("bbag_auctions.json")
    assert bbag.find_slug(auctions, "August Online-Sale 2026") == "bbag-august-online-sale-2026"
    assert bbag.find_slug(auctions, "Hit Spring Sale 2026 Online") == "bbag-spring-auction-2026-online"
    assert bbag.find_slug(auctions, "Christmas Online Sale 2025") == "bbag-christmas-online-sale-2025"
    assert bbag.find_slug(auctions, "Christmas Online Sale 2026") == ""     # not up yet


def test_magicmillions_digital_listings():
    from datetime import date

    from salescatalogues.sources import magicmillions_online

    found = magicmillions_online.auctions(_json("mm_digital_home.json"))
    assert found[0]["start"] == date(2026, 10, 9) and found[0]["uuid"]
    lots = magicmillions_online.parse_listings(_json("mm_digital_auction.json"))
    assert all(lot.sire and lot.dam for lot in lots)          # the dummy lot is skipped
    by_type = {lot.lot_type: lot for lot in lots}
    assert set(by_type) == {"SH", "B", "RF", "U"}
    mare = by_type["B"]
    assert mare.covering_sire and mare.sex == "M" and mare.yob and mare.dam_sire
    assert by_type["U"].horse_name == ""                      # "Unnamed"
    assert mare.url.startswith("https://magicmillions.digital/current-auctions/#!/auctions/")


def test_magicmillions_digital_decode():
    from salescatalogues.sources import magicmillions_online

    d = magicmillions_online.decode("%7B&quot;name&quot;:&quot;Dad&rsquo;s Rules&quot;,&quot;age&quot;:3%7D")
    assert d == {"name": "Dad’s Rules", "age": 3}
    assert magicmillions_online.decode("not json") == {}


def test_inglis_digital_catalogue():
    from datetime import date

    from salescatalogues.models import RawSale

    auctions = _json("inglis_digital_auctions.json")
    raw = RawSale("Inglis", "AUS", "October (Late) Online Sale", date(2026, 10, 16), None,
                  "https://inglisdigital.com/", online=True)
    found = inglis.find_auction(auctions, raw)
    assert found["auctionName"] == "2026 October (Late) Online Sale"
    early = RawSale("Inglis", "AUS", "October (Early) Online Sale", date(2026, 10, 2), None, "u", online=True)
    assert inglis.find_auction(auctions, early)["auctionName"] == "2026 October (Early) Online Sale"

    lots = inglis.parse_digital(_json("inglis_digital_catalogue.json"), found["sanitisedAuctionName"])
    assert len(lots) == 13
    covered = next(lot for lot in lots if lot.covering_sire)
    assert covered.lot_type == "B" and covered.yob and covered.sire and covered.dam
    assert sum(lot.withdrawn for lot in lots) == 4
    assert lots[0].url == f"https://www.inglisdigital.com/catalogue/auction/{found['sanitisedAuctionName']}/lot/{lots[0].lot_no}"


def test_thoroughbid_lots_2026_markup():
    lots = thoroughbid.parse_lots(_read("thoroughbid_lots_2026.html"))
    assert [lot.lot_no for lot in lots] == ["1", "8", "14"]
    filly = lots[0]
    assert filly.horse_name == "" and filly.sex == "Filly" and filly.yob == 2025
    assert filly.sire == "Frontiersman (GB)" and filly.dam == "Perfect Promise (IRE)"
    assert filly.lot_type == "Yearling" and filly.url == "https://www.thoroughbid.co.uk/auction/-2267"
    assert lots[1].withdrawn and not lots[2].withdrawn
    assert lots[2].horse_name == "Harrys Hope (IRE)" and lots[2].sex == "Mare" and lots[2].yob == 2018
