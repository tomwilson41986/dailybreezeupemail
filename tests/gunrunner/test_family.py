import json
from pathlib import Path

from gunrunner.cache import Cache
from gunrunner.family import FamilyBuilder, Runner, class_points, dirt_form, label

FX = Path(__file__).resolve().parents[1] / "fixtures" / "gunrunner"


class FakeResp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return FakeResp(self.pages.get((params or {}).get("dam"), {}))


def builder(ww, tmp_path, pages):
    return FamilyBuilder(
        "http://backend/family", FakeSession(pages), Cache(tmp_path / "c.sqlite"), ww
    )


def test_class_and_dirt_points():
    g1 = Runner(
        "A", runs=5, wins=3, g1_wins=1, group_wins=1, stakes_wins=1, dirt_runs=5, dirt_wins=3
    )
    assert class_points(g1) == 25 and dirt_form(g1) == 1.0 and label(g1) == "G1 winner on dirt"
    tf = Runner("B", runs=4, wins=1, rating=101)
    assert class_points(tf) == 18 and dirt_form(tf) == 0
    assert class_points(Runner("C")) == 0 and label(Runner("C")) == "Unraced"
    assert dirt_form(Runner("D", runs=3, dirt_runs=3)) == 0.25


def test_backend_family_three_levels(ww, tmp_path):
    page = json.loads((FX / "family_sara_dream.json").read_text())
    fb = builder(ww, tmp_path, {"Sara Dream": page})
    fam = fb.build(dam="Sara Dream", exclude="Caitlin G")
    assert fam.level(1).dam == "Sara Dream" and fam.level(2).dam == "Kenouska"
    assert fam.dam.rating == 73
    names = {r.name for r in fam.level(1).produce}
    assert "Caitlin G" not in names and "Sara Mischief" in names
    # a Japanese dirt winner under the dam
    assert fam.dirt_depth() == 1
    assert fam.level(2).dam_record.rating == 104
    # cached: a second build doesn't call the backend again
    fb.build(dam="Sara Dream")
    assert len(fb.session.calls) == 1


def test_worldwide_family_without_backend(ww, tmp_path):
    fam = builder(ww, tmp_path, {}).build(dam="Route Queen", damsire="Tapit")
    assert fam.dam.dirt_wins == 3 and fam.level(2).dam == "Old Queen"
    gift = next(r for r in fam.level(1).produce if r.name == "Queen's Gift")
    assert class_points(gift) == 22 and dirt_form(gift) == 1.0
    assert fam.level(1).best_dirt() == 1.0


def test_synthetic_family_has_no_dirt(ww, tmp_path):
    fam = builder(ww, tmp_path, {}).build(dam="Poly Girl")
    assert fam.dam.raced and fam.dirt_depth() is None
