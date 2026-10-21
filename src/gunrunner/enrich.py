"""Everything known about one filly or mare: her own racing, her family to the
third dam, her own produce, and (unraced) the forecast of her trip.

Her own record, best source first: the desk's sale data on the website
(AuctionEdge for the US breeding-stock sales, Timeform for the HIT sales), then
Equibase (US, within the budget), then the backend results table and the
worldwide file.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from gunrunner.collect import US, Candidate
from gunrunner.equibase import Equibase
from gunrunner.family import (
    Family,
    FamilyBuilder,
    Runner,
    _from_backend,
    from_equibase,
    from_worldwide,
)
from gunrunner.forecast import Forecast, Forecaster
from gunrunner.names import key
from gunrunner.sirelines import pedigree
from gunrunner.website import Website, parse_best_win
from gunrunner.worldwide import Worldwide

log = logging.getLogger(__name__)

GBP_USD = 1.27
EUR_USD = 1.08
_GRADE = {"gr.I": 1, "gr.II": 2, "gr.III": 3}


@dataclass
class Profile:
    c: Candidate
    ped: dict
    family: Family
    own: Runner | None = None
    forecast: Forecast | None = None
    runs: list[dict] = field(default_factory=list)  # Equibase runs, newest first
    last_runs: list[str] = field(default_factory=list)  # HIT: last three, as text
    produce: int | None = None  # her own foals of racing age / recorded
    first_cover: bool | None = None
    trip: float | None = None
    trip_from: str = ""
    dirt_share: float | None = None
    dirt_from: str = ""
    earnings: int | None = None
    tg: float | None = None
    aei: float | None = None
    r2: float | None = None
    best_win: str = ""
    stakes: tuple[float, str] = (0.0, "No stakes form")
    eq_ref: str = ""
    trainer: str = ""
    links: dict = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)

    @property
    def raced(self) -> bool:
        return bool(self.own and self.own.runs)


def stakes_from(
    own: Runner | None, runs: list[dict], hit: dict | None, bms: dict | None
) -> tuple[float, str]:
    best = (0.0, "No stakes form")

    def consider(pts: float, lab: str) -> None:
        nonlocal best
        if pts > best[0]:
            best = (pts, lab)

    for r in runs:
        g, st, fin = r.get("grade"), r.get("stakes"), r.get("finish")
        if not (g or st):
            continue
        if fin == 1:
            consider(
                {1: 15, 2: 13.5, 3: 12}.get(g, 10),
                {1: "G1 winner", 2: "G2 winner", 3: "G3 winner"}.get(g, "Stakes winner"),
            )
        elif fin in (2, 3):
            consider(8 if g else 6, f"G{g} placed" if g else "Stakes placed")
        else:
            consider(3, "Stakes starter")
    if hit:
        for g, pts in ((1, 15), (2, 13.5), (3, 12)):
            if hit.get(f"g{g}Wins"):
                consider(pts, f"G{g} winner")
            elif hit.get(f"g{g}Runs") and (hit.get("btRuns") or 0) > (hit.get("btWins") or 0):
                consider(3, "Stakes starter")
        if hit.get("listedWins"):
            consider(10, "Listed winner")
        if hit.get("btRuns") and not hit.get("btWins"):
            consider(3, "Stakes starter")
    if bms:
        t = str(bms.get("aeBestType") or "")
        g = _GRADE.get(t)
        if g:
            consider({1: 15, 2: 13.5, 3: 12}[g], f"G{g} winner")
        elif re.search(r"stk|LR|\bL\b", t):
            consider(10, "Stakes winner")
        if bms.get("aeBlackType"):
            consider(6, "Black-type placed")
    if own:
        if own.g1_wins:
            consider(15, "G1 winner")
        elif own.group_wins:
            consider(12, "Group/graded winner")
        elif own.stakes_wins:
            consider(10, "Stakes winner")
        elif own.bt_places:
            consider(6, "Black-type placed")
    return best


class Enricher:
    def __init__(
        self, ww: Worldwide, fc: Forecaster, web: Website, fam: FamilyBuilder, eq: Equibase | None
    ):
        self.ww, self.fc, self.web, self.fam, self.eq = ww, fc, web, fam, eq

    def prefetch(self, cands: list[Candidate]) -> None:
        """The backend family pages for every dam, and for every named filly or
        mare (her own record and produce), fetched in parallel."""
        pairs = [(c.dam, c.damsire) for c in cands] + [(c.name, c.sire) for c in cands if c.named]
        self.fam.prefetch(pairs)

    def profile(self, c: Candidate, *, spend: bool = False) -> Profile:
        p = Profile(
            c=c,
            ped=pedigree(c.sire),
            family=self.fam.build(
                dam=c.dam,
                damsire=c.damsire,
                exclude=c.name,
                us=c.region == US,
                spend_equibase=spend,
            ),
        )
        bms = self.web.bms_row(c.sire, c.dam, c.yob)
        hit = self.web.hit_row(c.sire, c.dam, c.yob)
        own = Runner(name=c.display_name, yob=c.yob, sex=c.sex, sire=c.sire)

        # her own page on the backend: her record and her produce
        if c.named:
            b = self.fam.backend(c.name, c.sire)
            mare = b.get("mare")
            if mare and (not c.yob or not mare.get("foalingYear") or mare["foalingYear"] == c.yob):
                r = _from_backend(mare)
                if r:
                    own.merge(r)
                    p.sources.append("results")
                kids = [h for h in (b.get("produce") or {}).get("horses") or []] + [
                    h for h in (b.get("worldwide") or {}).get("produce") or []
                ]
                p.produce = len({key(h["name"]) for h in kids if h.get("name")})
        # the worldwide file
        w = self.ww.horse(c.name, yob=c.yob, sire=c.sire) if c.named else None
        if w and (not c.sire or key(w.get("sire") or "") == key(c.sire)):
            own.merge(from_worldwide(w))
            p.sources.append("worldwide")
            if own.runs and (w.get("runs") or 0):
                p.dirt_share, p.dirt_from = own.dirt_runs / max(1, w["runs"]), "worldwide file"
                if own.trip_f:
                    p.trip, p.trip_from = own.trip_f, "winning trips"
            kids = [
                h
                for h in self.ww.produce(c.name)
                if c.yob and h.get("yob") and h["yob"] >= c.yob + 3
            ]
            if kids:
                p.produce = max(p.produce or 0, len(kids))

        # the website: US breeding-stock sales
        if bms:
            p.sources.append("AuctionEdge")
            if bms.get("aeE"):
                own.e = max(own.e or 0, int(bms["aeE"]))
            own.runs = max(own.runs, bms.get("starts") or 0)
            own.wins = max(own.wins, bms.get("wins") or 0)
            p.earnings = bms.get("earnings") or p.earnings
            p.tg, p.aei, p.r2 = bms.get("aeTg"), bms.get("aeCpi"), bms.get("rating")
            p.best_win = bms.get("aeBestWin") or ""
            bw = parse_best_win(p.best_win)
            if bms.get("awd"):
                p.trip, p.trip_from = float(bms["awd"]), bms.get("awdFrom") or "best win"
            elif bw:
                p.trip, p.trip_from = bw["furlongs"], "best win"
            if bms.get("produceCount") is not None:
                p.produce = max(p.produce or 0, bms["produceCount"] or 0, bms.get("aeProduce") or 0)
            p.first_cover = bms.get("firstCover")
            p.links.update({k: v for k, v in (bms.get("urls") or {}).items() if v})
            p.trainer = bms.get("trainer") or ""
            if own.runs:
                lot = self.web.bms_lot(bms)
                surf = (
                    ((lot.get("auctionEdge") or {}).get("horse") or {}).get("record") or {}
                ).get("surfaces")
                if bms.get("aeTurfOnly"):
                    p.dirt_share, p.dirt_from = 0.0, "AuctionEdge: turf only"
                elif surf:
                    p.dirt_share = 1.0 if set(surf) == {"D"} else 0.5 if "D" in surf else 0.0
                    p.dirt_from = "AuctionEdge winning surfaces"
        # the website: horses-in-training sales (Timeform)
        if hit:
            p.sources.append("Timeform")
            if hit.get("tfMax"):
                own.rating = max(own.rating or 0, float(hit["tfMax"]))
            own.runs = max(own.runs, hit.get("runs") or 0)
            own.wins = max(own.wins, hit.get("wins") or 0)
            if hit.get("prize"):
                p.earnings = max(p.earnings or 0, int(hit["prize"] * GBP_USD))
            if hit.get("awd") or hit.get("distBest"):
                p.trip = float(hit.get("awd") or hit.get("distBest"))
                p.trip_from = "winning trips" if hit.get("awd") else "best run"
            if p.dirt_share is None and own.runs:
                p.dirt_share, p.dirt_from = 0.0, "turf / synthetic"
            p.trainer = hit.get("trainer") or p.trainer
            p.last_runs = [
                f"{hit[f'lr{i}Race']}: {hit.get(f'lr{i}Pos')}/{hit.get(f'lr{i}Ran')}"
                for i in (1, 2, 3)
                if hit.get(f"lr{i}Race")
            ]
            if hit.get("lotUrl"):
                p.links["house"] = hit["lotUrl"]
            if hit.get("videoUrl"):
                p.links["replays"] = hit["videoUrl"]

        # Equibase (US): her runs, figures, surfaces
        cached = self._equibase(
            c, spend=spend, raced_hint=own.runs > 0 or bool(bms and bms.get("raced"))
        )
        if cached:
            p.runs = cached.get("runs") or []
            p.eq_ref = str(cached.get("refNo") or "")
            if p.runs:
                own.merge(from_equibase(c.display_name, cached))
                p.sources.append("Equibase")
                if p.dirt_share is None or p.dirt_from in ("worldwide file", "turf / synthetic"):
                    p.dirt_share = sum(1 for x in p.runs if not x.get("turf")) / len(p.runs)
                    p.dirt_from = "Equibase runs"

        if own.runs and p.trip is None and own.trip_f:
            p.trip, p.trip_from = own.trip_f, "best run"
        if p.earnings is None and own.prize_usd:
            p.earnings = own.prize_usd
        p.own = own if own.runs else None
        p.stakes = stakes_from(p.own, p.runs, hit, bms)
        if not p.raced:
            p.forecast = self.fc.forecast(sire=c.sire, dam=c.dam, damsire=c.damsire)
        return p

    def _equibase(self, c: Candidate, *, spend: bool, raced_hint: bool) -> dict | None:
        if self.eq is None or c.region != US or not c.named:
            return None
        ck = f"{key(c.name)}:{c.yob or ''}:{key(c.dam)}"
        rec = self.eq.cache.get("equibase", ck)
        if rec is not None:
            return rec or None
        if spend and raced_hint:
            return self.eq.lookup(c.name, yob=c.yob, dam=c.dam)
        return None
