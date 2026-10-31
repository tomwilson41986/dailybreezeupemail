"""A small worldwide file, built through the real indexer."""

import csv
import gzip
import io

import pytest

from gunrunner import worldwide

COLS = [
    "HorseName",
    "FoalingCountry",
    "FoalingYear",
    "Sex",
    "Sire",
    "Dam",
    "AllRuns",
    "LSWins",
    "SWins",
    "STop3",
    "GWins",
    "GTop3",
    "G1Wins",
    "TurfRuns",
    "TurfWins",
    "TurfBestDistance",
    "TurfMinWinDist",
    "TurfMaxWinDist",
    "TurfPrizemoneyUSD",
    "AWRuns",
    "AWWins",
    "AWBestDistance",
    "AWMinWinDist",
    "AWMaxWinDist",
    "AWPrizemoneyUSD",
    "AWBestGoing",
]


def horse(
    name,
    country,
    yob,
    sex,
    sire,
    dam,
    *,
    runs=0,
    turf=(0, 0, 0),
    aw=(0, 0, 0),
    going="",
    sw=0,
    gw=0,
    g1=0,
    top3=0,
    prize=0,
):
    """turf / aw: (runs, wins, winning trip in metres)."""
    return {
        "HorseName": name,
        "FoalingCountry": country,
        "FoalingYear": yob,
        "Sex": sex,
        "Sire": sire,
        "Dam": dam,
        "AllRuns": runs or turf[0] + aw[0],
        "LSWins": 0,
        "SWins": sw,
        "STop3": top3 or sw,
        "GWins": gw,
        "GTop3": gw,
        "G1Wins": g1,
        "TurfRuns": turf[0],
        "TurfWins": turf[1],
        "TurfBestDistance": turf[2] or "",
        "TurfMinWinDist": turf[2] if turf[1] else "",
        "TurfMaxWinDist": turf[2] if turf[1] else "",
        "TurfPrizemoneyUSD": prize if turf[0] >= aw[0] else 0,
        "AWRuns": aw[0],
        "AWWins": aw[1],
        "AWBestDistance": aw[2] or "",
        "AWMinWinDist": aw[2] if aw[1] else "",
        "AWMaxWinDist": aw[2] if aw[1] else "",
        "AWPrizemoneyUSD": prize if aw[0] > turf[0] else 0,
        "AWBestGoing": going,
    }


ROWS = [
    # a US dirt family: Route Queen (dam), her dirt stakes-winning daughter, her own dam
    horse(
        "ROUTE QUEEN",
        "USA",
        2016,
        "F",
        "TAPIT",
        "OLD QUEEN",
        aw=(12, 3, 1810),
        going="FT",
        sw=1,
        top3=2,
        prize=250000,
    ),
    horse(
        "QUEEN'S GIFT",
        "USA",
        2020,
        "F",
        "CURLIN",
        "ROUTE QUEEN",
        aw=(8, 3, 1810),
        going="FT",
        sw=1,
        gw=1,
        prize=400000,
    ),
    horse(
        "SPRINT BOY", "USA", 2021, "C", "INTO MISCHIEF", "ROUTE QUEEN", aw=(5, 2, 1207), going="FT"
    ),
    # a British synthetic family: no dirt
    horse(
        "POLY GIRL",
        "GB",
        2017,
        "F",
        "FRANKEL",
        "POLY MUM",
        turf=(6, 2, 2012),
        aw=(3, 1, 2012),
        going="ST",
    ),
    horse("POLY SON", "GB", 2021, "C", "DUBAWI", "POLY GIRL", turf=(4, 1, 2414)),
    # sires' progeny, for the forecast
    *[
        horse(
            f"TAPIT ROUTER {i}", "USA", 2018, "C", "TAPIT", f"MARE {i}", aw=(6, 2, 1810), going="FT"
        )
        for i in range(30)
    ],
    *[
        horse(f"FAST ONE {i}", "USA", 2018, "F", "SPEEDY", f"DAM {i}", aw=(6, 2, 1207), going="FT")
        for i in range(30)
    ],
]


@pytest.fixture(scope="session")
def ww_path(tmp_path_factory):
    d = tmp_path_factory.mktemp("ww")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLS)
    w.writeheader()
    w.writerows(ROWS)
    src = d / "horses-2018.csv.gz"
    src.write_bytes(gzip.compress(buf.getvalue().encode()))
    db = d / "worldwide.sqlite"
    worldwide.build(db, sources=[src])
    return db


@pytest.fixture
def ww(ww_path):
    return worldwide.Worldwide(ww_path)
