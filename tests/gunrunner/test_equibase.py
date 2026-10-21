from gunrunner.cache import Cache
from gunrunner.equibase import Equibase, match_horse, runs_from


class Resp:
    def __init__(self, body, credits_left):
        self.body, self.headers = (
            body,
            {"x-credits-remaining": str(credits_left), "x-credits-charged": "1"},
        )

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeApi:
    def __init__(self):
        self.calls = []
        self.left = 100

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url.rsplit("/", 1)[1])
        self.left -= 1
        if url.endswith("search_horse"):
            return Resp(
                {
                    "status": "success",
                    "data": {
                        "items": [
                            {
                                "refNo": 1,
                                "horseName": "Route Queen",
                                "yob": 2016,
                                "damName": "Old Queen",
                            },
                            {
                                "refNo": 2,
                                "horseName": "Route Queen",
                                "yob": 2001,
                                "damName": "Someone",
                            },
                        ]
                    },
                },
                self.left,
            )
        return Resp(
            {
                "status": "success",
                "data": {
                    "races": [
                        {
                            "date": "5/4/2019",
                            "track": "CD",
                            "race_type": "Allowance",
                            "finish_position": "1",
                            "speed_figure": "97",
                        },
                        {
                            "date": "6/1/2019",
                            "track": "BEL",
                            "race_type": "Turf Stakes (Gr. 2)",
                            "finish_position": "2",
                            "speed_figure": "101",
                        },
                    ]
                },
            },
            self.left,
        )


def test_match_horse():
    items = [
        {"refNo": 1, "horseName": "Kind", "yob": 2001, "damName": "Rainbow Lake"},
        {"refNo": 2, "horseName": "Kind", "yob": 2001, "damName": "Other"},
    ]
    assert match_horse(items, name="Kind (IRE)", yob=2001, dam="Rainbow Lake")["refNo"] == 1
    assert match_horse(items, name="Kind", yob=2001, dam="") is None  # two of them: can't tell
    assert match_horse(items, name="Kind", yob=1999, dam="") is None


def test_runs_from():
    runs = runs_from(
        [
            {
                "date": "6/1/2019",
                "track": "BEL",
                "race_type": "Ogden Phipps Stakes (Gr. 1)",
                "finish_position": "1",
                "speed_figure": "104",
            },
            {
                "date": "5/4/2019",
                "track": "KD",
                "race_type": "Maiden",
                "finish_position": "3",
                "speed_figure": "",
            },
        ]
    )
    assert (
        runs[0]["grade"] == 1
        and runs[0]["stakes"]
        and not runs[0]["turf"]
        and runs[0]["fig"] == 104
    )
    assert runs[1]["turf"] and runs[1]["fig"] is None and runs[1]["date"] == "2019-05-04"


def test_lookup_is_cached_and_budgeted(tmp_path):
    eq = Equibase("k", Cache(tmp_path / "c.sqlite"), budget=2, floor=10)
    eq.session = FakeApi()
    rec = eq.lookup("Route Queen", yob=2016, dam="Old Queen")
    assert rec["refNo"] == 1 and len(rec["runs"]) == 2 and rec["runs"][0]["turf"]
    assert eq.spent == 2 and eq.balance == 98 and not eq.can_spend
    assert eq.lookup("Route Queen", yob=2016, dam="Old Queen") == rec  # from the cache, no spend
    assert eq.session.calls == ["search_horse", "get_past_performances"]
    assert eq.lookup("Another", yob=2016) is None  # budget spent


def test_no_key_no_spend(tmp_path):
    assert not Equibase("", Cache(tmp_path / "c.sqlite"), budget=10, floor=0).can_spend
