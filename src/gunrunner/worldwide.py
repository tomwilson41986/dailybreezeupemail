"""The worldwide file: every horse of the 2014-2024 crops that raced anywhere
(463k horses), with its turf and all-weather record, best distances and black
type. Published in the HorseRacesBackend repo as ``breeding/data/horses-<year>
.csv.gz``; downloaded once and indexed into SQLite.

Dirt: the file folds dirt into "AW". A horse's AW running is dirt when the
going of her best AW run is a dirt going (FT fast, SY sloppy, MY muddy, WF wet
fast, SL slow) or she was foaled where AW racing is dirt (USA, Canada, Japan,
South America). Britain, Ireland, France, Australia and South Africa's AW is
synthetic (ST standard, STS standard to slow) and is not dirt.
"""

from __future__ import annotations

import csv
import gzip
import io
import logging
import sqlite3
from pathlib import Path

from gunrunner.names import key, split_suffix

log = logging.getLogger(__name__)

SOURCE = "https://raw.githubusercontent.com/Abiqb93/HorseRacesBackend/main/breeding/data/horses-{year}.csv.gz"
YEARS = range(2014, 2025)
DIRT_GOINGS = {"FT", "SY", "MY", "WF", "SL"}
SYNTHETIC_GOINGS = {"ST", "STS"}
DIRT_COUNTRIES = {
    "USA",
    "CAN",
    "JPN",
    "ARG",
    "BRZ",
    "CHI",
    "URU",
    "PER",
    "MEX",
    "PAN",
    "VEN",
    "PR",
    "KSA",
}
METRES_PER_FURLONG = 201.168

_COLS = """name_key TEXT, name TEXT, country TEXT, yob INTEGER, sex TEXT, sire_key TEXT, sire TEXT,
dam_key TEXT, dam TEXT, runs INTEGER, ls_wins INTEGER, s_wins INTEGER, s_top3 INTEGER, g_wins INTEGER,
g_top3 INTEGER, g1_wins INTEGER, turf_runs INTEGER, turf_wins INTEGER, turf_best_m INTEGER,
turf_min_win_m INTEGER, turf_max_win_m INTEGER, turf_prize INTEGER, aw_runs INTEGER, aw_wins INTEGER,
aw_best_m INTEGER, aw_min_win_m INTEGER, aw_max_win_m INTEGER, aw_prize INTEGER, aw_going TEXT,
dirt INTEGER"""


def _int(v: str) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def is_dirt(country: str, aw_runs: int | None, aw_going: str | None) -> bool:
    if not aw_runs:
        return False
    g = (aw_going or "").upper()
    if g in DIRT_GOINGS:
        return True
    if g in SYNTHETIC_GOINGS:
        return False
    return (country or "").upper() in DIRT_COUNTRIES


def _row(r: dict) -> tuple:
    country = (r.get("FoalingCountry") or "").upper()
    aw_runs = _int(r.get("AWRuns"))
    aw_going = (r.get("AWBestGoing") or "").replace("NULL", "")
    return (
        key(r["HorseName"]),
        r["HorseName"],
        country,
        _int(r.get("FoalingYear")),
        (r.get("Sex") or "").upper(),
        key(r.get("Sire") or ""),
        r.get("Sire") or "",
        key(r.get("Dam") or ""),
        r.get("Dam") or "",
        _int(r.get("AllRuns")),
        _int(r.get("LSWins")),
        _int(r.get("SWins")),
        _int(r.get("STop3")),
        _int(r.get("GWins")),
        _int(r.get("GTop3")),
        _int(r.get("G1Wins")),
        _int(r.get("TurfRuns")),
        _int(r.get("TurfWins")),
        _int(r.get("TurfBestDistance")),
        _int(r.get("TurfMinWinDist")),
        _int(r.get("TurfMaxWinDist")),
        _int(r.get("TurfPrizemoneyUSD")),
        aw_runs,
        _int(r.get("AWWins")),
        _int(r.get("AWBestDistance")),
        _int(r.get("AWMinWinDist")),
        _int(r.get("AWMaxWinDist")),
        _int(r.get("AWPrizemoneyUSD")),
        aw_going,
        1 if is_dirt(country, aw_runs, aw_going) else 0,
    )


def build(db_path: Path, session=None, *, sources: list[Path] | None = None) -> None:
    """Download (or read ``sources``) and index the file. Rebuilt only when missing."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.execute(f"CREATE TABLE horses ({_COLS})")
    total = 0
    blobs = []
    if sources:
        blobs = [p.read_bytes() for p in sources]
    else:
        import requests

        sess = session or requests.Session()
        for y in YEARS:
            resp = sess.get(SOURCE.format(year=y), timeout=120)
            resp.raise_for_status()
            blobs.append(resp.content)
    for blob in blobs:
        reader = csv.DictReader(
            io.TextIOWrapper(
                gzip.GzipFile(fileobj=io.BytesIO(blob)), encoding="utf-8", errors="replace"
            )
        )
        rows = [_row(r) for r in reader if r.get("HorseName")]
        conn.executemany(f"INSERT INTO horses VALUES ({','.join('?' * 30)})", rows)
        total += len(rows)
    for col in ("name_key", "sire_key", "dam_key"):
        conn.execute(f"CREATE INDEX idx_{col} ON horses({col})")
    conn.commit()
    conn.close()
    tmp.replace(db_path)
    log.info("worldwide file indexed: %d horses", total)


class Worldwide:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._sire_cache: dict[str, dict] = {}

    # --- single horses -----------------------------------------------------
    def horse(self, name: str, *, yob: int | None = None, sire: str = "") -> dict | None:
        """The horse by name; a suffix in the name, the year or the sire settles a namesake."""
        base, country = split_suffix(name)
        rows = [
            dict(r)
            for r in self.conn.execute("SELECT * FROM horses WHERE name_key=?", (key(base),))
        ]
        if not rows:
            return None
        if country:
            rows = [r for r in rows if r["country"] == country] or rows
        if yob:
            rows = [r for r in rows if r["yob"] == yob] or ([] if len(rows) > 1 else rows)
        if sire and len(rows) > 1:
            rows = [r for r in rows if r["sire_key"] == key(sire)] or rows
        return rows[0] if len(rows) == 1 else None

    def produce(self, dam: str) -> list[dict]:
        return [
            dict(r) for r in self.conn.execute("SELECT * FROM horses WHERE dam_key=?", (key(dam),))
        ]

    # --- sires -----------------------------------------------------------------
    def sire_stats(self, sire: str) -> dict:
        """His progeny in the file: runners, winners, stakes winners, the share of
        his winners' best form on dirt, and his winners' trips (furlongs)."""
        k = key(sire)
        if k in self._sire_cache:
            return self._sire_cache[k]
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM horses WHERE sire_key=?", (k,))]
        out = progeny_stats(rows)
        self._sire_cache[k] = out
        return out

    def damsire_produce(self, damsire: str, limit: int = 4000) -> list[dict]:
        """Runners out of the damsire's daughters (his record as a broodmare sire)."""
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT p.* FROM horses p JOIN horses d ON p.dam_key = d.name_key "
                "WHERE d.sire_key = ? AND d.sex IN ('F','M') LIMIT ?",
                (key(damsire), limit),
            )
        ]


def win_trip_f(h: dict) -> float | None:
    """A winner's trip in furlongs: the middle of her winning range on the surface she won more on."""
    tw, aw = h.get("turf_wins") or 0, h.get("aw_wins") or 0
    if not tw and not aw:
        return None
    if aw >= tw:
        lo, hi, best = h.get("aw_min_win_m"), h.get("aw_max_win_m"), h.get("aw_best_m")
    else:
        lo, hi, best = h.get("turf_min_win_m"), h.get("turf_max_win_m"), h.get("turf_best_m")
    m = (lo + hi) / 2 if lo and hi else best
    return round(m / METRES_PER_FURLONG, 2) if m else None


def best_trip_f(h: dict) -> float | None:
    """The trip of her best run on her main surface (for a non-winner too)."""
    m = (
        h.get("aw_best_m")
        if (h.get("aw_runs") or 0) >= (h.get("turf_runs") or 0)
        else h.get("turf_best_m")
    )
    return round(m / METRES_PER_FURLONG, 2) if m else None


def progeny_stats(rows: list[dict]) -> dict:
    runners = [r for r in rows if (r.get("runs") or 0) > 0]
    winners = [r for r in runners if (r.get("turf_wins") or 0) + (r.get("aw_wins") or 0) > 0]
    sw = [r for r in runners if (r.get("s_wins") or 0) + (r.get("g_wins") or 0) > 0]
    dirt_w = [
        r for r in winners if r.get("dirt") and (r.get("aw_wins") or 0) >= (r.get("turf_wins") or 0)
    ]
    trips = [t for t in (win_trip_f(r) for r in winners) if t]
    return {
        "foals": len(rows),
        "runners": len(runners),
        "winners": len(winners),
        "sw": len(sw),
        "dirt_winner_share": (len(dirt_w) / len(winners)) if winners else None,
        "trips": trips,
    }
