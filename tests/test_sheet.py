from dailybreezeup.sheet import (
    count_by_sale,
    enrichment_fields,
    index_by_key,
    parse_sheet_csv,
    sale_short_name,
)

CSV_SAMPLE = (
    "Year,Sale,Lot,Sex,Sire,Dam,Vendor,Buyer,Price,"
    "OT Diff/M,OT Rank,SL 1F,SL GO,Breeze Rating,Precocity Rating\n"
    "2026,Craven,16,F,Havana Grey (GB),Hot Secret (GB),"
    "\"Yeomanstown Stud, Ireland\",Stroud Coleman Bloodstock,"
    "\"350,000\",-0.44,24,7.07,6.7,85.7,101.4\n"
    "2026,Craven,148,C,Mehmas (IRE),Bermuda (GB),Mark Grant Racing,"
    "Lot Withdrawn,\"150,000\",-0.25,49,6.95,6.56,45.2,43.6\n"
    "2026,Craven,9999,,,,,,,,,,,,\n"  # blank/zero rating fields tolerated
)


def test_parse_sheet_csv_keeps_typed_fields():
    rows = parse_sheet_csv(CSV_SAMPLE)
    assert len(rows) == 3
    by_key = index_by_key(rows)
    r = by_key[(2026, "Craven", 16)]
    assert r.sire == "Havana Grey (GB)"
    assert r.breeze_rating == 85.7
    assert r.precocity_rating == 101.4
    assert r.ot_rank == 24
    assert r.price == "350,000"


def test_parse_sheet_csv_handles_missing_numerics():
    rows = parse_sheet_csv(CSV_SAMPLE)
    blank = next(r for r in rows if r.lot == 9999)
    assert blank.breeze_rating is None
    assert blank.ot_rank is None


def test_sale_short_name_aliases():
    assert sale_short_name("Tattersalls Craven Breeze Up Sale 2026") == "Craven"
    assert sale_short_name("Goffs UK 2yo Breeze Up Sale 2026") == "Goffs"
    assert sale_short_name("Arqana May 2yo Breeze Up 2026") == "Arqana"
    # Must equal the gSheet's "Sale" label ("Ireland", not "Tattersalls
    # Ireland") or the (year, sale, lot) ratings join misses every Ireland row.
    assert sale_short_name("Tattersalls Ireland Breeze Up Sale 2026") == "Ireland"
    assert sale_short_name("Tattersalls Guineas Horses-in-Training Sale 2026") == "Guineas"
    assert sale_short_name("Some Other Sale") is None


def test_enrichment_fields_returns_subset():
    rows = parse_sheet_csv(CSV_SAMPLE)
    fields = enrichment_fields(rows[0])
    assert fields["sheet_breeze_rating"] == 85.7
    assert fields["sheet_sire"] == "Havana Grey (GB)"
    assert "sheet_buyer" in fields
    assert fields["sheet_sale_total"] is None  # default


def test_enrichment_fields_passes_sale_total_for_ot_denominator():
    rows = parse_sheet_csv(CSV_SAMPLE)
    fields = enrichment_fields(rows[0], sale_total=182)
    assert fields["sheet_sale_total"] == 182


def test_count_by_sale():
    rows = parse_sheet_csv(CSV_SAMPLE)
    totals = count_by_sale(rows)
    assert totals[(2026, "Craven")] == 3
