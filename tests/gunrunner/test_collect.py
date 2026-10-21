from datetime import date

from gunrunner.collect import from_lots, infer_yob, is_female
from salescatalogues.models import Catalogue, Lot, RawSale


def _cat(name, country="UK", start=date(2026, 11, 24), sale_type="Foal / Weanling"):
    return Catalogue(
        raw=RawSale(
            house="H", country=country, name=name, start_date=start, end_date=None, url="u"
        ),
        sale_type=sale_type,
    )


def test_is_female():
    assert is_female("Filly") == "F" and is_female("M") == "M" and is_female("Mare") == "M"
    assert is_female("Colt") == "" and is_female("") == "" and is_female("G") == ""
    assert is_female("Broodmare") == "M"                  # BBAG


def test_infer_yob():
    assert infer_yob(Lot("1"), _cat("December Foal Sale")) == 2026
    assert infer_yob(Lot("1"), _cat("October Yearling Sale", sale_type="Yearling")) == 2025
    assert (
        infer_yob(Lot("1"), _cat("Gold Coast Yearling Sale", "AUS", date(2027, 1, 12), "Yearling"))
        == 2025
    )
    assert (
        infer_yob(Lot("1"), _cat("Ready to Run Sale", "NZ", date(2026, 11, 18), "Breeze Up"))
        == 2024
    )
    assert infer_yob(Lot("1", yob=2019), _cat("Mares")) == 2019
    assert infer_yob(Lot("1"), _cat("December Mares Sale", sale_type="Broodmare")) is None


def test_from_lots_keeps_fillies_and_mares_once():
    a, b = _cat("Foal Sale"), _cat("Second Sale", start=date(2026, 12, 1))
    lots = {
        a.catalogue_id: [
            Lot("1", sex="Filly", sire="Tapit", dam="Route Queen"),
            Lot("2", sex="Colt", sire="Tapit", dam="Other"),
            Lot("3", sex="Filly", sire="Tapit", dam="Gone", withdrawn=True),
            Lot("4", sex="Filly", sire="Tapit", dam=""),
            # part-shares on the online platforms aren't horses to buy
            Lot("5", sex="M", sire="Tapit", dam="Shared", lot_type="SH"),
            Lot("6", sex="F", sire="Tapit", dam="Racing Share", lot_type="RS"),
        ],
        b.catalogue_id: [Lot("9", sex="F", sire="Tapit", dam="Route Queen")],
    }
    out = from_lots([a, b], lots)
    assert [c.lot_no for c in out] == ["1"]
    assert (
        out[0].yob == 2026
        and out[0].display_name == "Tapit – Route Queen"
        and out[0].region == "EU"
    )
