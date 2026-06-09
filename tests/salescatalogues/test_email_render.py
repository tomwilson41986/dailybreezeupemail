from datetime import date

from salescatalogues.classify import build_catalogue
from salescatalogues.csvout import HEADER, to_csv
from salescatalogues.emailer import render
from salescatalogues.models import RawSale

REF = date(2026, 6, 9)


def _cat(name, country, start, *, online=False, first_seen=None):
    raw = RawSale(house="H", country=country, name=name, start_date=start,
                  end_date=None, url="https://x", online=online)
    return build_catalogue(raw, REF, first_seen=first_seen)


def test_render_groups_and_flags():
    cats = [
        _cat("UK Active", "UK", date(2026, 6, 10), first_seen=date(2026, 1, 1)),
        _cat("NZ New Online", "NZ", date(2026, 8, 1), online=True, first_seen=None),
    ]
    payload = render(run_date=REF, catalogues=cats)
    assert "Daily Sales Catalogues" in payload.html
    assert "United Kingdom" in payload.html and "New Zealand" in payload.html
    assert "ACTIVE" in payload.html and "NEW" in payload.html and "ONLINE" in payload.html
    # subject reflects counts
    assert "1 active" in payload.subject and "1 new" in payload.subject
    # CSV attached content
    assert payload.csv_filename == "sales_catalogues_2026-06-09.csv"
    assert payload.csv_text.splitlines()[0] == ",".join(HEADER)


def test_render_empty():
    payload = render(run_date=REF, catalogues=[])
    assert "No New or Active" in payload.html
    assert payload.csv_text.strip() == ",".join(HEADER)


def test_csv_rows():
    cats = [_cat("Sale A", "FR", date(2026, 7, 1), first_seen=None)]
    text = to_csv(cats)
    lines = text.splitlines()
    assert lines[0] == ",".join(HEADER)
    assert "France" in lines[1] and "Sale A" in lines[1]
