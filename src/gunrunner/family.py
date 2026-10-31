"""The female family to the third dam: each dam and her produce, with every
runner's class and dirt form.

Three sources, merged by name:

* the backend's ``/api/breeding/family`` (results table, Timeform-scale ``best``,
  stakes and group wins, any crop): the dam, second and third dam by name, their
  own records, produce, the dam's siblings and the third dam's produce;
* the worldwide file (2014 crops on, any country): surfaces, so dirt;
* Equibase, for a US dam the others can't place (bought within the budget).

Level 1 is the dam and her produce (the lot's siblings), level 2 the second dam
and hers, level 3 the third dam and hers.
"""

from __future__ import annotations

import logging
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field

from gunrunner.cache import Cache
from gunrunner.names import display, key
from gunrunner.worldwide import (
    DIRT_COUNTRIES,
    DIRT_GOINGS,
    METRES_PER_FURLONG,
    Worldwide,
    win_trip_f,
)

log = logging.getLogger(__name__)

FAMILY_MAX_AGE = (
    28  # days a cached family answer is trusted (plus up to a fortnight, spread by name)
)
LEVEL_WEIGHT = {1: 1.0, 2: 0.6, 3: 0.35}  # class
DIRT_WEIGHT = {1: 1.0, 2: 0.75, 3: 0.55}  # dirt form deeper is worth less


@dataclass
class Runner:
    name: str
    yob: int | None = None
    sex: str = ""
    country: str = ""
    sire: str = ""
    runs: int = 0
    wins: int = 0
    rating: float | None = None  # best on the Timeform scale (backend)
    e: int | None = None  # peak Equibase figure
    stakes_wins: int = 0  # black-type wins (group included)
    group_wins: int = 0
    g1_wins: int = 0
    bt_places: int = 0
    dirt_runs: int = 0
    dirt_wins: int = 0
    turf_runs: int = 0
    prize_usd: int = 0
    trip_f: float | None = None
    dirt_known: bool = False  # surfaces known (worldwide file / Equibase)

    @property
    def raced(self) -> bool:
        return self.runs > 0

    def merge(self, o: Runner) -> None:
        for f in ("yob", "rating", "e", "trip_f"):
            if getattr(self, f) is None and getattr(o, f) is not None:
                setattr(self, f, getattr(o, f))
        for f in ("sex", "country", "sire"):
            if not getattr(self, f) and getattr(o, f):
                setattr(self, f, getattr(o, f))
        for f in (
            "runs",
            "wins",
            "stakes_wins",
            "group_wins",
            "g1_wins",
            "bt_places",
            "dirt_runs",
            "dirt_wins",
            "turf_runs",
            "prize_usd",
        ):
            setattr(self, f, max(getattr(self, f) or 0, getattr(o, f) or 0))
        if o.rating is not None and self.rating is not None:
            self.rating = max(self.rating, o.rating)
        if o.e is not None and self.e is not None:
            self.e = max(self.e, o.e)
        self.dirt_known = self.dirt_known or o.dirt_known


def class_points(r: Runner | None) -> float:
    """Her class on the 25-point scale: the best of her rating, figure and black type."""
    if r is None or not r.raced:
        return 0.0
    pts = 1.0
    if r.rating is not None:
        t = r.rating
        pts = max(
            pts,
            25
            if t >= 115
            else 22
            if t >= 108
            else 18
            if t >= 100
            else 13
            if t >= 92
            else 8
            if t >= 85
            else 4
            if t >= 75
            else 1,
        )
    if r.e is not None:
        e = r.e
        pts = max(
            pts,
            25
            if e >= 105
            else 22
            if e >= 100
            else 18
            if e >= 97
            else 13
            if e >= 93
            else 8
            if e >= 88
            else 4
            if e >= 80
            else 1,
        )
    if r.g1_wins:
        pts = 25
    elif r.group_wins:
        pts = max(pts, 22)
    elif r.stakes_wins:
        pts = max(pts, 18)
    elif r.bt_places:
        pts = max(pts, 13)
    elif r.wins:
        pts = max(pts, 4)
    if r.prize_usd >= 200_000:
        pts = max(pts, 13)
    elif r.prize_usd >= 100_000:
        pts = max(pts, 8)
    return float(pts)


def dirt_form(r: Runner | None) -> float:
    """0-1: dirt black-type winner 1, dirt winner of class 0.85, dirt winner 0.7,
    dirt runner 0.25."""
    if r is None or not r.dirt_runs:
        return 0.0
    if r.dirt_wins and (r.stakes_wins or r.group_wins) and r.dirt_wins >= r.wins / 2:
        return 1.0
    if r.dirt_wins:
        return 0.85 if class_points(r) >= 13 else 0.7
    return 0.25


def label(r: Runner) -> str:
    """ "G1 winner on dirt", "Black-type placed", "Unraced"..."""
    if not r.raced:
        return "Unraced"
    d = " on dirt" if r.dirt_wins else ""
    if r.g1_wins:
        return "G1 winner" + d
    if r.group_wins:
        return "Group/graded winner" + d
    if r.stakes_wins:
        return "Black-type winner" + d
    if r.bt_places:
        return "Black-type placed"
    if r.wins:
        return "Winner" + d
    return "Raced"


@dataclass
class Level:
    n: int
    dam: str = ""
    dam_record: Runner | None = None
    produce: list[Runner] = field(default_factory=list)

    @property
    def members(self) -> list[Runner]:
        return ([self.dam_record] if self.dam_record else []) + self.produce

    def best_class(self) -> float:
        return max((class_points(m) for m in self.members), default=0.0)

    def best_dirt(self) -> float:
        return max((dirt_form(m) for m in self.members), default=0.0)

    def dirt_members(self) -> list[Runner]:
        return [m for m in self.members if m.dirt_wins]

    def summary(self) -> dict:
        p = [x for x in self.produce if x.raced]
        return {
            "runners": len(p),
            "winners": sum(1 for x in p if x.wins),
            "bt": sum(1 for x in p if x.stakes_wins),
            "group": sum(1 for x in p if x.group_wins),
        }


@dataclass
class Family:
    levels: dict[int, Level]
    sources: list[str] = field(default_factory=list)

    def level(self, n: int) -> Level:
        return self.levels.setdefault(n, Level(n))

    @property
    def dam(self) -> Runner | None:
        return self.level(1).dam_record

    def dirt_depth(self) -> int | None:
        """The nearest level with a dirt winner (1 dam, 2 second dam, 3 third dam)."""
        for n in (1, 2, 3):
            if self.level(n).dirt_members():
                return n
        return None

    def to_json(self) -> dict:
        return {
            "sources": self.sources,
            "levels": {
                n: {
                    "dam": lv.dam,
                    "dam_record": asdict(lv.dam_record) if lv.dam_record else None,
                    "produce": [asdict(x) for x in lv.produce],
                }
                for n, lv in self.levels.items()
            },
        }


# --- sources ---------------------------------------------------------------------


def _from_backend(row: dict | None) -> Runner | None:
    if not row or not row.get("name"):
        return None
    best = row.get("best")
    return Runner(
        name=display(row["name"]),
        yob=row.get("foalingYear"),
        sex=(row.get("sex") or "").upper()[:1],
        country=(row.get("country") or "").upper(),
        sire=display(row.get("sire") or ""),
        runs=row.get("runs") or 0,
        wins=row.get("wins") or 0,
        rating=float(best) if isinstance(best, (int, float)) and best > 0 else None,
        stakes_wins=row.get("stakesWins") or 0,
        group_wins=row.get("groupWins") or 0,
        g1_wins=row.get("group1Wins") or 0,
        bt_places=row.get("blackTypePlaces") or 0,
        prize_usd=int(row.get("prizeUsd") or 0),
    )


def _from_backend_ww(row: dict) -> Runner:
    """A backend ``worldwide`` row: surfaces through the best run's going."""
    r = _from_backend(row) or Runner(name=display(row.get("name") or ""))
    aw = row.get("awRuns") or 0
    going = (row.get("bestGoing") or "").upper()
    dirt = aw > 0 and (
        going in DIRT_GOINGS or (going not in ("ST", "STS") and r.country in DIRT_COUNTRIES)
    )
    r.turf_runs = row.get("turfRuns") or 0
    if dirt:
        r.dirt_runs = aw
        # wins aren't split by surface: on dirt when she raced mostly there
        r.dirt_wins = r.wins if aw >= r.turf_runs else 0
    r.dirt_known = True
    if row.get("bestDistance"):
        r.trip_f = round(row["bestDistance"] / METRES_PER_FURLONG, 2)
    return r


def from_worldwide(h: dict) -> Runner:
    dirt = bool(h.get("dirt"))
    return Runner(
        name=display(h["name"]),
        yob=h.get("yob"),
        sex=h.get("sex") or "",
        country=h.get("country") or "",
        sire=display(h.get("sire") or ""),
        runs=h.get("runs") or 0,
        wins=(h.get("turf_wins") or 0) + (h.get("aw_wins") or 0),
        stakes_wins=h.get("s_wins") or 0,
        group_wins=h.get("g_wins") or 0,
        g1_wins=h.get("g1_wins") or 0,
        bt_places=max(0, (h.get("s_top3") or 0) - (h.get("s_wins") or 0)),
        dirt_runs=(h.get("aw_runs") or 0) if dirt else 0,
        dirt_wins=(h.get("aw_wins") or 0) if dirt else 0,
        turf_runs=h.get("turf_runs") or 0,
        prize_usd=(h.get("turf_prize") or 0) + (h.get("aw_prize") or 0),
        trip_f=win_trip_f(h),
        dirt_known=True,
    )


def from_equibase(name: str, rec: dict) -> Runner:
    runs = rec.get("runs") or []
    dirt = [x for x in runs if not x.get("turf")]
    figs = [x["fig"] for x in runs if x.get("fig") is not None]
    return Runner(
        name=display(name),
        yob=rec.get("yob"),
        country="USA",
        runs=len(runs),
        wins=sum(1 for x in runs if x.get("finish") == 1),
        e=max(figs) if figs else None,
        stakes_wins=sum(
            1 for x in runs if x.get("finish") == 1 and (x.get("grade") or x.get("stakes"))
        ),
        group_wins=sum(1 for x in runs if x.get("finish") == 1 and x.get("grade")),
        g1_wins=sum(1 for x in runs if x.get("finish") == 1 and x.get("grade") == 1),
        bt_places=sum(
            1 for x in runs if x.get("finish") in (2, 3) and (x.get("grade") or x.get("stakes"))
        ),
        dirt_runs=len(dirt),
        dirt_wins=sum(1 for x in dirt if x.get("finish") == 1),
        turf_runs=len(runs) - len(dirt),
        dirt_known=bool(runs),
    )


class FamilyBuilder:
    def __init__(self, api: str, session, cache: Cache, ww: Worldwide, equibase=None):
        self.api, self.session, self.cache, self.ww, self.equibase = (
            api,
            session,
            cache,
            ww,
            equibase,
        )

    # backend answers, fetched in parallel and cached for four weeks
    def _ck(self, dam: str, damsire: str) -> str:
        return f"{key(dam)}|{key(damsire)}"

    @staticmethod
    def _age(ck: str) -> int:
        # spread the refreshes so the whole cache doesn't fall due in one week
        return FAMILY_MAX_AGE + zlib.crc32(ck.encode()) % 14

    def _fetch(self, dam: str, damsire: str):
        params = {"dam": dam}
        if damsire:
            params["sire"] = damsire
        try:
            resp = self.session.get(self.api, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("family %s: %s", dam, exc)
            return None

    def prefetch(self, pairs: list[tuple[str, str]], workers: int = 8) -> None:
        todo = sorted(
            {
                (d, s)
                for d, s in pairs
                if d
                and not self.cache.has("family", ck := self._ck(d, s), max_age_days=self._age(ck))
            }
        )
        if not todo:
            return
        log.info("family: fetching %d dams", len(todo))
        with ThreadPoolExecutor(workers) as pool:
            for (d, s), body in zip(todo, pool.map(lambda p: self._fetch(*p), todo), strict=True):
                if body is not None:
                    self.cache.put("family", self._ck(d, s), body)

    def backend(self, dam: str, damsire: str = "") -> dict:
        ck = self._ck(dam, damsire)
        body = self.cache.get("family", ck, max_age_days=self._age(ck))
        if body is None:
            body = self._fetch(dam, damsire)
            if body is not None:
                self.cache.put("family", ck, body)
        return body or {}

    # assembly -----------------------------------------------------------------------
    def build(
        self,
        *,
        dam: str,
        damsire: str = "",
        exclude: str = "",
        us: bool = False,
        spend_equibase: bool = False,
    ) -> Family:
        fam = Family(levels={})
        b = self.backend(dam, damsire) if dam else {}
        if b.get("mare"):
            fam.sources.append("results")
        lv1, lv2, lv3 = fam.level(1), fam.level(2), fam.level(3)
        lv1.dam = display(dam)
        lv2.dam = display(b.get("secondDam") or "")
        lv3.dam = display(b.get("thirdDam") or "")

        people: dict[tuple[int, str], Runner] = {}

        def add(level: int, r: Runner | None, *, is_dam: bool = False) -> None:
            if r is None or not r.name or key(r.name) == key(exclude):
                return
            # the dam above is in her own dam's produce: she belongs to her level
            if not is_dam and level > 1 and key(r.name) == key(fam.level(level - 1).dam):
                return
            k = (level, key(r.name))
            if k in people:
                people[k].merge(r)
            else:
                people[k] = r
                lv = fam.level(level)
                if is_dam:
                    lv.dam_record = r
                else:
                    lv.produce.append(r)

        add(1, _from_backend(b.get("mare")), is_dam=True)
        add(2, _from_backend(b.get("secondDamOwn")), is_dam=True)
        add(3, _from_backend(b.get("thirdDamOwn")), is_dam=True)
        for lvl, part in ((1, "produce"), (2, "siblings"), (3, "thirdDamProduce")):
            for row in (b.get(part) or {}).get("horses") or []:
                add(lvl, _from_backend(row))
            for row in (b.get("worldwide") or {}).get(part) or []:
                add(lvl, _from_backend_ww(row))

        # the worldwide file: the dam herself (2014 crops on), and every level's produce
        own = self.ww.horse(dam, sire=damsire) if dam else None
        if own:
            fam.sources.append("worldwide")
            add(1, from_worldwide(own), is_dam=True)
            if not lv2.dam and own.get("dam"):
                lv2.dam = display(own["dam"])
        if lv2.dam and not lv3.dam:
            d2 = self.ww.horse(lv2.dam)
            if d2 and d2.get("dam"):
                lv3.dam = display(d2["dam"])
            if d2:
                add(2, from_worldwide(d2), is_dam=True)
        for lv in (lv1, lv2, lv3):
            if lv.dam:
                for h in self.ww.produce(lv.dam):
                    add(lv.n, from_worldwide(h))

        # Equibase for a US dam nobody else can place
        if us and spend_equibase and self.equibase is not None and dam:
            d = lv1.dam_record
            if d is None or not d.dirt_known:
                rec = self.equibase.lookup(dam)
                if rec:
                    fam.sources.append("equibase")
                    add(1, from_equibase(dam, rec), is_dam=True)
                    if not lv2.dam and rec.get("dam"):
                        lv2.dam = display(rec["dam"])
        return fam
