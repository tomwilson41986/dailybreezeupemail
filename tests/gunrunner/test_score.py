import pytest

from gunrunner.cache import Cache
from gunrunner.enrich import Enricher, Profile
from gunrunner.family import Family, FamilyBuilder, Runner
from gunrunner.forecast import Forecaster
from gunrunner.score import assess, dirt_ok, fit_points, status_of, trip_points
from gunrunner.sirelines import pedigree
from gunrunner.website import Website

from .helpers import cand
from .test_family import FakeSession


def prof(**kw) -> Profile:
    extra = {k: kw.pop(k) for k in ("produce", "first_cover", "own", "dirt_share") if k in kw}
    c = cand(**kw)
    return Profile(c=c, ped=pedigree(c.sire), family=Family(levels={}), **extra)


@pytest.mark.parametrize(
    "kw,status,ok",
    [
        (dict(sire="Gun Runner"), "By Gun Runner", False),
        (dict(yob=2026), "Foal", True),
        (dict(yob=2025), "Yearling", True),
        (dict(yob=2022, sex="M", covering_sire="Curlin", name="Some Mare"), "First foal", True),
        (
            dict(yob=2022, sex="M", covering_sire="Nyquist", name="Some Mare"),
            "Covered by Nyquist",
            False,
        ),
        (
            dict(yob=2022, sex="M", covering_sire="CURLIN", name="Some Mare", produce=1),
            "Experienced mare",
            False,
        ),
        (
            dict(yob=2016, sex="M", covering_sire="Into Mischief", name="Old Mare"),
            "Experienced mare (age)",
            False,
        ),
        (
            dict(
                yob=2016, sex="M", covering_sire="Into Mischief", name="Old Mare", first_cover=True
            ),
            "First foal",
            True,
        ),
        (dict(yob=2022, sex="M", name="Fresh Mare"), "Maiden", True),
    # off the track, not covered: the website's firstCover=False isn't produce
    (dict(yob=2022, sex="M", name="Fresh Mare", first_cover=False), "Maiden", True),
    (dict(yob=2021, sex="M", covering_sire="Curlin", name="Mum", first_cover=False), "Experienced mare", False),
    ],
)
def test_status(kw, status, ok):
    assert status_of(prof(**kw)) == (status, ok)


def test_trip_and_fit_points():
    assert (
        trip_points(9) == 10
        and trip_points(7.5) == 6.5
        and trip_points(12) == 5
        and trip_points(None) == 0
    )
    assert fit_points(0.20) == 0 and fit_points(0.45) == 20 and fit_points(0.6) == 20


def test_dirt_rule_by_region():
    us = prof()
    assert dirt_ok(us, 1) and not dirt_ok(us, 2)
    eu = prof(sale_country="IRE")
    assert dirt_ok(eu, 3) and not dirt_ok(eu, None)
    raced_us = prof(own=Runner("X", runs=6), dirt_share=0.3)
    assert not dirt_ok(raced_us, 1)


@pytest.fixture
def enricher(ww, tmp_path):
    cache = Cache(tmp_path / "c.sqlite")
    sess = FakeSession({})
    web = Website("http://site", sess, cache)
    return Enricher(ww, Forecaster(ww), web, FamilyBuilder("http://b", sess, cache, ww), None)


def test_unraced_yearling_out_of_a_dirt_family(enricher):
    a = assess(enricher.profile(cand(sire="Tapit", dam="Route Queen", yob=2025)))
    assert a.track == "unraced" and a.status == "Yearling"
    assert a.parts["Family dirt"] == 20 and a.parts["Family class"] == 22
    assert a.dirt_depth == 1
    assert set(a.parts) == set(a.maxima)


def test_candy_ride_line_loses_five(enricher):
    base = assess(enricher.profile(cand(sire="Tapit", dam="Route Queen")))
    candy = assess(enricher.profile(cand(sire="Vekoma", dam="Route Queen")))
    assert candy.candy and not base.candy
    assert candy.score == pytest.approx(sum(candy.parts.values()) - 5, abs=0.1)


def test_raced_filly_needs_class_and_trip(enricher):
    a = assess(
        enricher.profile(
            cand(name="Queen's Gift", sire="Curlin", dam="Route Queen", yob=2020, sex="M")
        )
    )
    assert a.track == "raced"
    assert a.p.trip == pytest.approx(9.0, abs=0.01) and a.p.dirt_share == 1.0
    assert a.class_pts == 22 and a.qualifies, a.reasons
    sprint = assess(
        enricher.profile(cand(name="Sprint Boy", sire="Into Mischief", dam="Route Queen", yob=2021))
    )
    assert "trip outside 8-10f" in sprint.reasons and not sprint.qualifies


def test_backend_namesakes_are_not_hers():
    from gunrunner.enrich import _same_mare

    syracuse = cand(name="Syracuse", sire="Ribchester (IRE)", yob=2019)
    colt = {"name": "SYRACUSE", "sire": None, "sex": "c", "foalingYear": None, "best": 111}
    assert not _same_mare(colt, syracuse)
    assert not _same_mare({"sex": "f", "foalingYear": 2013, "sire": "RIBCHESTER"}, syracuse)
    assert _same_mare({"sex": "f", "foalingYear": 2019, "sire": None}, syracuse)
    assert _same_mare({"sex": "f", "foalingYear": None, "sire": "RIBCHESTER"}, syracuse)
