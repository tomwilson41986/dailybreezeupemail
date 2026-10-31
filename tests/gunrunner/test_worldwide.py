from gunrunner.forecast import Forecaster, window_share
from gunrunner.names import display, key, split_suffix
from gunrunner.sirelines import pedigree
from gunrunner.worldwide import is_dirt, win_trip_f


def test_names():
    assert key("Quiet Giant (USA)") == key("QUIET GIANT") == "QUIETGIANT"
    assert split_suffix("Kind (IRE)") == ("Kind", "IRE")
    assert split_suffix("Gun Runner (US)") == ("Gun Runner", "USA")
    assert display("QUIET GIANT") == "Quiet Giant"
    assert display("Mixed Case") == "Mixed Case"
    assert display("POWERSCOURT (GB)") == "Powerscourt (GB)"
    assert display("MCKINZIE") == "McKinzie"
    assert display("WINCHELL THOROUGHBREDS LLC") == "Winchell Thoroughbreds LLC"


def test_dirt_rule():
    assert is_dirt("USA", 5, "FT")
    assert is_dirt("GB", 5, "SY")  # a British horse on a sloppy track raced on dirt
    assert not is_dirt("USA", 5, "ST")  # synthetic, wherever she was foaled
    assert not is_dirt("GB", 5, "")  # British AW is synthetic
    assert is_dirt("JPN", 5, "")
    assert not is_dirt("USA", 0, "FT")


def test_pedigree_points():
    assert pedigree("Malibu Moon")["points"] == 25
    assert pedigree("Bernardini")["exact"]
    assert 0 < pedigree("Curlin")["points"] < pedigree("Tapit")["points"]
    assert pedigree("Unheard Of Sire")["basis"]


def test_lookup_and_produce(ww):
    q = ww.horse("Route Queen (USA)")
    assert q["dirt"] == 1 and q["yob"] == 2016
    assert {r["name"] for r in ww.produce("Route Queen")} == {"QUEEN'S GIFT", "SPRINT BOY"}
    assert ww.horse("Poly Girl")["dirt"] == 0
    assert round(win_trip_f(q), 1) == 9.0
    s = ww.sire_stats("Tapit")
    assert s["winners"] == 31 and s["dirt_winner_share"] == 1.0


def test_forecast_favours_the_router(ww):
    fc = Forecaster(ww)
    route = fc.forecast(sire="Tapit", dam="Route Queen")
    sprint = fc.forecast(sire="Speedy", dam="Route Queen")
    assert route.fit > sprint.fit
    assert abs(sum(route.dist.values()) - 1) < 1e-6
    assert window_share(route.dist) == route.fit
    assert route.sources[0][0] == "Tapit progeny"
