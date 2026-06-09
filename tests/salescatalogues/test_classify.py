from datetime import date

import pytest

from salescatalogues.classify import (
    build_catalogue,
    classify_sale_type,
    group_by_country,
    is_active,
    is_excluded,
)
from salescatalogues.models import RawSale

REF = date(2026, 6, 9)


def _raw(name, country="UK", start=None, end=None, online=False, desc="", status=""):
    return RawSale(
        house="H", country=country, name=name, start_date=start, end_date=end,
        url="u", online=online, description=desc, status_hint=status,
    )


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Craven Breeze Up Sale", "Breeze Up"),
        ("Ready to Run Sale", "Breeze Up"),
        ("November Horses of Racing Age Sale", "HIT"),
        ("Autumn Horses in Training Sale", "HIT"),
        ("January Horses of All Ages Sale", "HIT"),
        ("National Weanling Sale", "Foal / Weanling"),
        ("December Foal Sale", "Foal / Weanling"),
        ("November Breeding Stock Sale", "Broodmare"),
        ("October Yearling Sale Book 1", "Yearling"),
        ("February Mixed Sale", "Mixed"),
        ("The London Sale", "Mixed"),
    ],
)
def test_sale_type(name, expected):
    assert classify_sale_type(_raw(name)) == expected


@pytest.mark.parametrize(
    "name,desc,excluded",
    [
        ("Arkle Sale Part 1", "Ireland's market-leading store sale", True),
        ("Land Rover Sale", "", True),
        ("Derby Sale", "", True),  # Tatts IRE NH store, no description
        ("February National Hunt Sale", "", True),
        ("Grand Steeple Sale", "", True),
        ("Purebred Arabian Sale", "", True),
        ("October Yearling Sale", "flat yearlings", False),
        ("Craven Breeze Up Sale", "", False),
    ],
)
def test_exclusion(name, desc, excluded):
    assert is_excluded(_raw(name, desc=desc)) is excluded


def test_active_window():
    # Sale 11-12 June; today 9 June; lead 2 days -> active from the 9th.
    sale = _raw("X", start=date(2026, 6, 11), end=date(2026, 6, 12))
    assert is_active(sale, date(2026, 6, 9), lead_days=2) is True
    assert is_active(sale, date(2026, 6, 8), lead_days=2) is False
    assert is_active(sale, date(2026, 6, 12), lead_days=2) is True  # last day
    assert is_active(sale, date(2026, 6, 13), lead_days=2) is False  # finished


def test_active_undated_live():
    assert is_active(_raw("X", status="live"), REF) is True
    assert is_active(_raw("X", status=""), REF) is False


def test_build_catalogue_new_flag():
    sale = _raw("X", start=date(2026, 7, 1))
    never = build_catalogue(sale, REF, first_seen=None)
    assert never.is_new is True
    seen_today = build_catalogue(sale, REF, first_seen=REF)
    assert seen_today.is_new is True
    seen_before = build_catalogue(sale, REF, first_seen=date(2026, 6, 1))
    assert seen_before.is_new is False


def test_group_by_country_order_and_sort():
    cats = [
        build_catalogue(_raw("Late", "FR", start=date(2026, 9, 1)), REF,
                        first_seen=date(2026, 1, 1)),
        build_catalogue(_raw("ActiveOne", "UK", start=date(2026, 6, 10)), REF,
                        first_seen=date(2026, 1, 1)),
        build_catalogue(_raw("NewOne", "UK", start=date(2026, 8, 1)), REF,
                        first_seen=None),
    ]
    sections = group_by_country(cats)
    # UK before France
    assert [c.code for c, _ in sections] == ["UK", "FR"]
    uk_rows = sections[0][1]
    # Active leads, then New
    assert uk_rows[0].name == "ActiveOne"
    assert uk_rows[1].name == "NewOne"
