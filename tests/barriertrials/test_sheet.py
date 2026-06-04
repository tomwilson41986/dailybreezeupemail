from __future__ import annotations

from barriertrials import sheet

CSV = """Horse,Speed,Precocity,Note
Cosmic Mystery,92.5,78,trial winner
O'Reilly,71,,
,50,50,blank name skipped
Cosmic Mystery,1,1,duplicate name collapses
Quiet Reflection,not-a-number,55,
"""


def _parse(text=CSV, name_column="Horse", rating_columns=("Speed", "Precocity")):
    return sheet.parse_sheet_csv(text, name_column=name_column, rating_columns=rating_columns)


def test_parses_named_rows_with_ratings():
    horses = _parse()
    names = [h.name for h in horses]
    assert names == ["Cosmic Mystery", "O'Reilly", "Quiet Reflection"]
    cosmic = horses[0]
    assert cosmic.ratings == {"Speed": 92.5, "Precocity": 78.0}


def test_blank_and_nonnumeric_ratings_become_none():
    horses = {h.name: h for h in _parse()}
    assert horses["O'Reilly"].ratings == {"Speed": 71.0, "Precocity": None}
    # "not-a-number" in Speed -> None, Precocity parses
    assert horses["Quiet Reflection"].ratings == {"Speed": None, "Precocity": 55.0}


def test_name_key_normalised_and_duplicates_collapsed():
    horses = _parse()
    assert horses[0].name_key == "cosmicmystery"
    assert horses[1].name_key == "oreilly"
    # The duplicate "Cosmic Mystery" row is dropped (first wins).
    assert sum(1 for h in horses if h.name_key == "cosmicmystery") == 1


def test_name_column_fallback_when_configured_header_absent():
    # Configured column "Horse" missing; "Name" fallback is used.
    text = "Name,Speed\nFlying Start,80\n"
    horses = sheet.parse_sheet_csv(text, name_column="Horse", rating_columns=("Speed",))
    assert [h.name for h in horses] == ["Flying Start"]


def test_no_name_column_returns_empty():
    text = "Foo,Bar\n1,2\n"
    assert sheet.parse_sheet_csv(text, name_column="Horse", rating_columns=("Speed",)) == []


def test_index_by_name():
    idx = sheet.index_by_name(_parse())
    assert set(idx) == {"cosmicmystery", "oreilly", "quietreflection"}
    assert idx["oreilly"].name == "O'Reilly"
