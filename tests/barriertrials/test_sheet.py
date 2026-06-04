from __future__ import annotations

from barriertrials import sheet

# Mirrors the real watchlist layout: a name column, analytics columns, notes.
CSV = """Batch,Number,Horse,Sex,Age,Trainer,TFig,Final Rating,Notes
1,4,GOLDEN NARRATIVE (IRE),C,2,D. Dias,86.5,88.0,Batch 1 winner
1,7,KING'S FURY (GB),C,2,J.P. O'Brien,83.2,85.0,
4,5,CASHEL QUEEN (IRE),F,2,D. O'Brien,not-a-number,46,Slowest winner
,,,,,,,,blank name skipped
1,4,GOLDEN NARRATIVE (IRE),C,2,D. Dias,86.5,88.0,duplicate collapses
"""


def _parse(text=CSV, rating_columns=("Final Rating", "TFig")):
    return sheet.parse_sheet_csv(text, name_column="Horse", rating_columns=rating_columns)


def test_parses_named_rows_and_strips_country_for_key():
    horses = _parse()
    assert [h.name for h in horses] == [
        "GOLDEN NARRATIVE (IRE)", "KING'S FURY (GB)", "CASHEL QUEEN (IRE)"
    ]
    # Match key drops the country suffix.
    assert horses[0].name_key == "goldennarrative"
    assert horses[1].name_key == "kingsfury"


def test_fields_capture_every_non_name_column_in_order():
    h = _parse()[0]
    assert list(h.fields.keys()) == [
        "Batch", "Number", "Sex", "Age", "Trainer", "TFig", "Final Rating", "Notes"
    ]
    assert h.fields["Trainer"] == "D. Dias"
    assert h.fields["Notes"] == "Batch 1 winner"
    # The name column itself is not duplicated into fields.
    assert "Horse" not in h.fields


def test_ratings_parsed_numeric_with_none_for_blank_or_nonnumeric():
    by = {h.name_key: h for h in _parse()}
    assert by["goldennarrative"].ratings == {"Final Rating": 88.0, "TFig": 86.5}
    # "not-a-number" TFig -> None; Final Rating still parses.
    assert by["cashelqueen"].ratings == {"Final Rating": 46.0, "TFig": None}


def test_duplicate_name_collapses_to_first():
    horses = _parse()
    assert sum(1 for h in horses if h.name_key == "goldennarrative") == 1


def test_no_name_column_returns_empty():
    assert sheet.parse_sheet_csv("Foo,Bar\n1,2\n", name_column="Horse",
                                 rating_columns=("TFig",)) == []
