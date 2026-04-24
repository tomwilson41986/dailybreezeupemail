from dailybreezeup.sheet import (
    csv_export_url,
    extract_gid,
    extract_sheet_id,
    iter_sales_and_lots,
    row_deeplink_url,
)

SAMPLE_URL = "https://docs.google.com/spreadsheets/d/ABC123xyz_-/edit?usp=sharing"

SAMPLE_CSV = """Year,Sale,Lot,Sex,Sire,Dam,Vendor,Buyer,Price,OT Diff/M,OT Rank,SL 1F,SL GO,Breeze Rating,Precocity Rating
2026,Craven,1,F,Starman (GB),Fast Dandy (IRE),Ballybush Stables,Dan Astbury,"18,000",+0.12,32,10.34,Good,B+,85
2026,Craven,2,C,Havana Grey (GB),Favourite Child (GB),Drummona House,George Scott Racing,"130,000",-0.18,1,10.02,Good,A,92
2026,Goffs UK,5,C,Mehmas (IRE),Example Mare (IRE),Vendor Ltd,Stroud Coleman,"880,000",-0.45,1,9.85,Good Firm,A+,96
"""


def test_extract_sheet_id():
    assert extract_sheet_id(SAMPLE_URL) == "ABC123xyz_-"


def test_extract_gid_default_zero():
    assert extract_gid(SAMPLE_URL) == "0"


def test_extract_gid_from_fragment():
    assert extract_gid("https://docs.google.com/spreadsheets/d/X/edit#gid=42") == "42"


def test_csv_export_url():
    u = csv_export_url(SAMPLE_URL)
    assert u.startswith("https://docs.google.com/spreadsheets/d/ABC123xyz_-/export")
    assert "format=csv" in u
    assert "gid=0" in u


def test_row_deeplink_url():
    u = row_deeplink_url(SAMPLE_URL, 5)
    assert "range=A5" in u
    assert "ABC123xyz_-" in u


def test_iter_sales_and_lots_parses_three_sales_two_ids():
    pairs = list(iter_sales_and_lots(SAMPLE_URL, csv_text=SAMPLE_CSV))
    assert len(pairs) == 3
    sale_ids = {s.id for s, _ in pairs}
    assert sale_ids == {"tatts-craven-2026", "goffs-uk-breezeup-2026"}

    lots_by_id = {(s.id, lot.lot): lot for s, lot in pairs}
    craven_1 = lots_by_id[("tatts-craven-2026", "1")]
    assert craven_1.sire == "Starman (GB)"
    assert craven_1.dam == "Fast Dandy (IRE)"
    assert craven_1.price == 18000
    assert craven_1.currency == "GBP"
    assert craven_1.breeze_rating == "B+"
    assert craven_1.precocity_rating == "85"
    assert craven_1.sheet_row_url and "range=A2" in craven_1.sheet_row_url
    assert craven_1.year_foaled == 2024

    goffs_5 = lots_by_id[("goffs-uk-breezeup-2026", "5")]
    assert goffs_5.price == 880000
    assert goffs_5.currency == "GBP"
