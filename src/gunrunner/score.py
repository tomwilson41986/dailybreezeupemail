"""Gun Runner match, out of 100, and who makes the list.

Raced (Gun Runner Mares Report, 441 foals 2019-24):
  Pedigree 25  her sire as broodmare sire with Gun Runner, else his line
  Class    25  peak Equibase figure; Timeform, black type and earnings for the rest
  Dirt     10  share of her form on dirt (else 6 for dirt in the family)
  Route    10  trip of her peak run or best win; 8-10f full marks
  Stakes   15  G1 win 15 .. stakes starter 3
  Earnings 10  $400k full marks
  Speed     5  best Thoro-Graph (when held; otherwise the rest is scaled to 100)

Unraced (foals, yearlings, unraced fillies and mares):
  Pedigree        25
  Family class    25  best of dam / second / third dam and their produce, weighted 1 / .6 / .35
  Family dirt     20  nearest dirt form, weighted 1 / .75 / .55
  Distance fit    20  forecast share at 8-10f: 20% nil, 45% full marks (all winners: 24%)
  Family produce  10  the dam's winners and stakes winners

Gun Runner's daughters are out; Candy Ride-line sires lose 5 (Candy Ride 2x3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gunrunner.collect import US
from gunrunner.config import COVER_SIRES
from gunrunner.enrich import Profile
from gunrunner.family import DIRT_WEIGHT, LEVEL_WEIGHT, class_points
from gunrunner.names import key
from gunrunner.sirelines import CANDY_RIDE

RACED_MAX = {
    "Pedigree": 25,
    "Class": 25,
    "Dirt": 10,
    "Route": 10,
    "Stakes": 15,
    "Earnings": 10,
    "Speed": 5,
}
UNRACED_MAX = {
    "Pedigree": 25,
    "Family class": 25,
    "Family dirt": 20,
    "Distance fit": 20,
    "Family produce": 10,
}
CLASS_MIN = 18  # E 97, or its equal
TRIP = (8.0, 10.0)
FIT_LO, FIT_HI = 0.20, 0.45
FIT_MIN = 0.33  # an unraced filly's forecast share at 8-10f: about the top fifth
UNRACED_MIN = 55
FIRST_FOAL_AGE = 6  # a covered mare with no produce known is taken as a first foal up to this age
_COVERS = {key(s) for s in COVER_SIRES}
_CANDY = {key(s) for s in CANDY_RIDE}


@dataclass
class Assessment:
    p: Profile
    status: str  # Foal, Yearling, 2yo, In training, Maiden, First foal; or why she's out
    eligible: bool
    track: str = ""  # raced / unraced
    parts: dict[str, float] = field(default_factory=dict)
    maxima: dict[str, int] = field(default_factory=dict)
    score: float = 0.0
    qualifies: bool = False
    reasons: list[str] = field(default_factory=list)  # why not, when not
    candy: bool = False
    class_pts: float = 0.0
    dirt_depth: int | None = None

    @property
    def lot_id(self) -> str:
        return self.p.c.lot_id


def status_of(p: Profile) -> tuple[str, bool]:
    c = p.c
    if key(c.sire) == key("Gun Runner"):
        return "By Gun Runner", False
    age = c.age
    covered = bool(c.covering_sire)
    has_produce = bool(p.produce) or p.first_cover is False
    if covered:
        if key(c.covering_sire) not in _COVERS:
            return f"Covered by {c.covering_sire}", False
        if has_produce:
            return "Experienced mare", False
        if p.first_cover is not True and age is not None and age > FIRST_FOAL_AGE:
            return "Experienced mare (age)", False
        return "First foal", True
    if has_produce:
        return "Experienced mare", False
    if age is not None and age <= 0:
        return "Foal", True
    if age == 1:
        return "Yearling", True
    if age == 2 and not p.raced:
        return "2yo", True
    lt = f"{c.lot_type} {c.sale_type}".lower()
    if p.raced and ("hit" in lt or "training" in lt or "racing" in lt):
        return "In training", True
    if c.sex == "M" and age is not None and age > FIRST_FOAL_AGE + 2 and not p.raced:
        return "Experienced mare (age)", False
    return "Maiden", True


def trip_points(f: float | None) -> float:
    if f is None:
        return 0
    if TRIP[0] <= f <= TRIP[1]:
        return 10
    if 7 <= f < 8:
        return 6.5
    if 6.5 <= f < 7:
        return 4.5
    if f > 10:
        return 5
    return 1.5


def earnings_points(v: int | None) -> float:
    v = v or 0
    return (
        10
        if v >= 400_000
        else 8.5
        if v >= 250_000
        else 7
        if v >= 180_000
        else 5
        if v >= 100_000
        else 3
        if v >= 50_000
        else 1
        if v > 0
        else 0
    )


def speed_points(tg: float | None) -> float | None:
    if tg is None:
        return None
    return (
        5
        if tg <= 3
        else 4
        if tg <= 5
        else 3
        if tg <= 7
        else 2
        if tg <= 9
        else 1
        if tg <= 12
        else 0.5
    )


def family_class(p: Profile) -> float:
    return max((LEVEL_WEIGHT[n] * p.family.level(n).best_class() for n in (1, 2, 3)), default=0.0)


def family_dirt(p: Profile) -> float:
    """0-1: the nearest, best dirt form in the family."""
    return max((DIRT_WEIGHT[n] * p.family.level(n).best_dirt() for n in (1, 2, 3)), default=0.0)


def produce_points(p: Profile) -> float:
    def one(n: int) -> float | None:
        s = p.family.level(n).summary()
        if s["bt"]:
            return 8 + (2 if s["group"] else 0)
        if s["runners"] >= 2:
            return 2 + 5 * s["winners"] / s["runners"]
        if s["runners"] == 1:
            return 2 + 3 * (s["winners"] > 0)
        return None

    d1, d2 = one(1), one(2)
    best = max(d1 if d1 is not None else 3.0, 0.6 * (d2 or 0))
    return round(min(10.0, best), 1)


def fit_points(fit: float | None) -> float:
    if fit is None:
        return 0
    return round(20 * max(0.0, min(1.0, (fit - FIT_LO) / (FIT_HI - FIT_LO))), 1)


def dirt_ok(p: Profile, depth: int | None) -> bool:
    """US: her own dirt form (raced) or the dam's branch. Europe and Australasia:
    anywhere to the third dam."""
    own = (p.dirt_share or 0) >= 0.5
    if p.c.region == US:
        return own if p.raced else depth == 1
    return own or depth is not None


def assess(p: Profile) -> Assessment:
    status, ok = status_of(p)
    a = Assessment(
        p=p,
        status=status,
        eligible=ok,
        candy=key(p.c.sire) in _CANDY,
        dirt_depth=p.family.dirt_depth(),
    )
    ped = p.ped["points"]
    if p.raced:
        a.track = "raced"
        a.class_pts = class_points(p.own)
        fam_dirt = family_dirt(p)
        dirt = max(10 * (p.dirt_share or 0), 6 * fam_dirt)
        spd = speed_points(p.tg)
        a.parts = {
            "Pedigree": ped,
            "Class": a.class_pts,
            "Dirt": round(dirt, 1),
            "Route": trip_points(p.trip),
            "Stakes": p.stakes[0],
            "Earnings": earnings_points(p.earnings),
            "Speed": spd or 0,
        }
        a.maxima = dict(RACED_MAX)
        total = sum(a.parts.values())
        if spd is None:  # no Thoro-Graph: the other 95 scaled to 100
            total *= 100 / 95
        if a.class_pts < CLASS_MIN:
            a.reasons.append("class below E 97")
        if p.trip is None or not TRIP[0] <= p.trip <= TRIP[1]:
            a.reasons.append("trip outside 8-10f" if p.trip else "trip not known")
    else:
        a.track = "unraced"
        fit = p.forecast.fit if p.forecast else None
        a.parts = {
            "Pedigree": ped,
            "Family class": round(family_class(p), 1),
            "Family dirt": round(20 * family_dirt(p), 1),
            "Distance fit": fit_points(fit),
            "Family produce": produce_points(p),
        }
        a.maxima = dict(UNRACED_MAX)
        total = sum(a.parts.values())
        if fit is None or fit < FIT_MIN:
            a.reasons.append(
                f"distance fit {fit:.0%} below {FIT_MIN:.0%}" if fit is not None else "no forecast"
            )
    if a.candy:
        total -= 5
    a.score = round(max(0.0, min(100.0, total)), 1)
    if a.track == "unraced" and a.score < UNRACED_MIN:
        a.reasons.append(f"score below {UNRACED_MIN}")
    if not dirt_ok(p, a.dirt_depth):
        a.reasons.append(
            "no dirt form" + (" (own or dam)" if p.c.region == US else " to the third dam")
        )
    if not ok:
        a.reasons.insert(0, status)
    a.qualifies = ok and not a.reasons
    return a
