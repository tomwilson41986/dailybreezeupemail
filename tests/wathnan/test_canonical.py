"""Name standardisation across feeds."""

import datetime as dt

import pytest

from wathnan.canonical import canonical_jockey, canonical_trainer
from wathnan.enrich import canonicalise, missing_suffixes
from wathnan.models import Race, Runner


@pytest.mark.parametrize("variant,expected", [
    # Sporting Life abbreviates; the report spells the name out.
    ("W J Haggas", "William Haggas"),
    ("A M Balding", "Andrew Balding"),
    ("K R Burke", "Karl Burke"),
    ("R M Beckett", "Ralph Beckett"),
    ("H Al Jehani", "Hamad Al-Jehani"),
    ("A Watson", "Archie Watson"),
    ("E Bethell", "Ed Bethell"),
    ("G Boughey", "George Boughey"),
    # France Galop shouts and glues the initial to the surname.
    ("A.DE MIEULLE", "Alban de Mieulle"),
    ("A De Mieulle", "Alban de Mieulle"),
    # irishracing writes names as URL slugs.
    ("K-R-Burke", "Karl Burke"),
    ("H-Al-Jehani", "Hamad Al-Jehani"),
    # A bare surname resolves when only one canonical name carries it.
    ("Haggas", "William Haggas"),
    # Partnerships need an explicit alias.
    ("J & T Gosden", "John & Thady Gosden"),
    ("Richard and Peter Fahey", "Richard & Peter Fahey"),
    # Already canonical, and unknown people, both pass through.
    ("William Haggas", "William Haggas"),
    ("Brittany Russell", "Brittany Russell"),
    ("Some New Trainer", "Some New Trainer"),
])
def test_canonical_trainer(variant, expected):
    assert canonical_trainer(variant) == expected


@pytest.mark.parametrize("variant,expected", [
    ("D Tudhope", "Danny Tudhope"),
    ("M Guyon", "Maxime Guyon"),
    ("MAXIME GUYON", "Maxime Guyon"),
    ("F Bughanaim", "Faleh Bughanaim"),
    ("James Doyle", "James Doyle"),
    ("Y Lachhab", "Y Lachhab"),          # not in the registry, left alone
    ("", ""),
])
def test_canonical_jockey(variant, expected):
    assert canonical_jockey(variant) == expected


def test_an_ambiguous_surname_is_left_alone():
    """Two canonical names sharing a surname and initial must not be guessed."""
    from wathnan.canonical import Registry

    registry = Registry(["James Doyle", "Jack Doyle"], {})
    assert registry.resolve("J Doyle") == "J Doyle"
    assert registry.resolve("James Doyle") == "James Doyle"


def _race(runners):
    return Race(date=dt.date(2026, 8, 20), course="YORK", race_type="Nursery",
                runners=tuple(runners))


def test_canonicalise_fills_suffixes_and_names():
    race = _race([Runner("Old Is Gold", "Mehmas", "Lyons Lane", "A M Balding",
                         "Saffie Osborne")])
    runner = canonicalise([race])[0].runners[0]
    assert runner.horse == "OLD IS GOLD (IRE)"
    assert runner.trainer == "Andrew Balding"
    assert runner.jockey == "Saffie Osborne"


def test_an_existing_suffix_is_never_doubled():
    race = _race([Runner("SHARAH (FR)", trainer="JF Bernard")])
    assert canonicalise([race])[0].runners[0].horse == "SHARAH (FR)"


def test_an_unknown_horse_keeps_a_bare_name():
    race = _race([Runner("Some New Horse", trainer="W J Haggas")])
    runner = canonicalise([race])[0].runners[0]
    assert runner.horse == "SOME NEW HORSE"
    assert missing_suffixes([canonicalise([race])[0]]) == {"somenewhorse"}


def test_missing_suffixes_ignores_horses_that_have_one():
    race = _race([Runner("OLD IS GOLD (IRE)"), Runner("Naval Light")])
    assert missing_suffixes([race]) == {"navallight"}


def test_registry_files_are_well_formed():
    import json

    from wathnan.canonical import REGISTRY_PATH
    from wathnan.enrich import HORSES_PATH, load_horses

    people = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert people["trainers"] and people["jockeys"]
    assert all(isinstance(name, str) and name.strip() for name in people["trainers"])
    horses = json.loads(HORSES_PATH.read_text(encoding="utf-8"))["horses"]
    assert horses and all(country.isupper() and 2 <= len(country) <= 3
                          for country in horses.values())
    assert len(load_horses()) == len(horses), "registry keys collide once normalised"
