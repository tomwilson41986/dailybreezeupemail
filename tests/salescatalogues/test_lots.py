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
