"""Parser tests against captured fixtures. These assert each adapter pulls the
expected sales out of a real page snapshot, so a site redesign that breaks a
selector fails loudly here rather than silently emptying the digest.
"""
from datetime import date
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
    tattersalls_online,
)

REF = date(2026, 6, 9)
FX = Path(__file__).resolve().parents[1] / "fixtures" / "salescatalogues"


def _read(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8", errors="replace")


def _find(rows, substr):
    return next((r for r in rows if substr.lower() in r.name.lower()), None)


def test_tattersalls_uk():
    rows = tattersalls.parse_saledates(
        _read("tattersalls_saledates_nmt.html"),
        country="UK", house="Tattersalls", ref=REF,
    )
    assert len(rows) >= 8
    book1 = _find(rows, "October Yearling Sale Book 1")
    assert book1 is not None
    assert book1.start_date == date(2026, 10, 6)
    assert book1.end_date == date(2026, 10, 8)
    assert all(r.country == "UK" for r in rows)


def test_goffs_splits_country_and_excludable_store():
    rows = goffs.parse_upcoming(_read("goffs_upcoming.html"), ref=REF)
    bu = _find(rows, "Classic Breeze Up")
    assert bu is not None and bu.country == "IRE"
    london = _find(rows, "London Sale")
    assert london is not None and london.country == "UK"
    arkle = _find(rows, "Arkle Sale Part 1")
    assert arkle is not None
    assert "store" in arkle.description.lower()  # used by the NH exclusion


def test_arqana_dates_and_online():
    rows = arqana.parse_catalogues(_read("arqana_catalogues.html"), ref=REF)
    aug = _find(rows, "The August Sale")
    assert aug is not None and aug.start_date == date(2026, 8, 15)
    v2 = _find(rows, "v.2 Yearling Sale")
    # The "v.2" in the name must not leak a stray day into the date.
    assert v2 is not None and v2.start_date == date(2026, 8, 19)
    online = _find(rows, "December ARQANA Online")
    assert online is not None and online.online is True


def test_bbag_events():
    rows = bbag.parse_events(_read("bbag_events.html"), ref=REF)
    premier = _find(rows, "Premier Yearling Sale")
    assert premier is not None and premier.start_date == date(2026, 9, 4)
    assert premier.country == "DE"


def test_keeneland():
    rows = keeneland.parse_sales(_read("keeneland_sales.html"), ref=REF)
    sept = _find(rows, "September Yearling Sale")
    assert sept is not None
    assert sept.start_date == date(2026, 9, 14)
    assert sept.end_date == date(2026, 9, 26)


def test_fasigtipton_online_flag():
    rows = fasigtipton.parse_calendar(_read("fasigtipton_calendar.html"), ref=REF)
    digital = _find(rows, "June Digital Sale")
    assert digital is not None and digital.online is True
    hora = _find(rows, "July Selected Horses of Racing Age")
    assert hora is not None and hora.online is False


def test_obs():
    rows = obs.parse_home(_read("obs_home.html"), ref=REF)
    june = _find(rows, "June Two-Year-Olds")
    assert june is not None and june.start_date == date(2026, 6, 16)


def test_inglis_online_split():
    rows = inglis.parse_calendar(_read("inglis_calendar.html"), ref=REF)
    classic = _find(rows, "Classic Yearling Sale")
    assert classic is not None and classic.online is False
    online = _find(rows, "January Online Sale")
    assert online is not None and online.online is True


def test_magicmillions_year_from_name():
    rows = magicmillions.parse_upcoming(_read("magicmillions_upcoming.html"), ref=REF)
    gc = _find(rows, "Gold Coast Yearling")
    assert gc is not None and gc.start_date == date(2027, 1, 13)


def test_nzb_dates_and_online():
    rows = nzb.parse_upcoming(_read("nzb_upcoming.html"), ref=REF)
    rtr = _find(rows, "Ready to Run")
    assert rtr is not None and rtr.start_date == date(2026, 11, 18)
    book1 = _find(rows, "Karaka 2027 - Book 1")
    assert book1 is not None and book1.start_date == date(2027, 1, 24)
    online = _find(rows, "National Online Breeding Stock")
    assert online is not None and online.online is True


def test_tattersalls_online():
    rows = tattersalls_online.parse_home(_read("tattersalls_online.html"), ref=REF)
    assert rows, "expected at least one online sale"
    assert all(r.online for r in rows)


def test_gavelhouse_json():
    rows = gavelhouse.parse_catalogue(_read("gavelhouse_currentcatalogue.json"))
    assert len(rows) == 1
    assert rows[0].start_date == date(2026, 6, 16)
    assert rows[0].end_date == date(2026, 6, 22)
    assert rows[0].online is True
