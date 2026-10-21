"""Forecast distance fit for a horse that has not run: the trips she should want,
from her sire and her dam, as the site's ``aptitude.blend()`` does it.

Half the weight is the sire's side: his winners' trips, trusted n/(n+40) of the
way, the rest the population. Half is the dam's side, in order: her produce
(n/(n+8)), her own racing (1/5), then her sire as a broodmare sire (n/(n+40)),
the remainder the population. The fit is the forecast's share at 8-10f, the
window Gun Runner's stakes horses win in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gunrunner.worldwide import Worldwide, best_trip_f, progeny_stats, win_trip_f

BINS = [x / 2 for x in range(9, 33)]  # 4.5f .. 16f in half furlongs
WINDOW = (8.0, 10.0)
K_SIRE, K_PRODUCE, K_DAM_SELF, K_DAMSIRE = 40, 8, 4, 40


def _bin(t: float) -> float:
    return min(BINS[-1], max(BINS[0], round(t * 2) / 2))


def histogram(trips: list[float]) -> dict[float, float]:
    h = {b: 0.0 for b in BINS}
    for t in trips:
        h[_bin(t)] += 1
    n = sum(h.values())
    return {b: v / n for b, v in h.items()} if n else h


def _mix(parts: list[tuple[float, dict[float, float]]]) -> dict[float, float]:
    out = {b: 0.0 for b in BINS}
    for w, h in parts:
        for b in BINS:
            out[b] += w * h.get(b, 0.0)
    return out


@dataclass
class Forecast:
    dist: dict[float, float]
    fit: float  # share of the forecast at 8-10f
    median: float | None
    sources: list[tuple[str, float, int]] = field(default_factory=list)  # (label, weight, n)


def window_share(dist: dict[float, float], lo: float = WINDOW[0], hi: float = WINDOW[1]) -> float:
    return sum(v for b, v in dist.items() if lo <= b <= hi)


def _median(dist: dict[float, float]) -> float | None:
    acc = 0.0
    for b in BINS:
        acc += dist[b]
        if acc >= 0.5:
            return b
    return None


class Forecaster:
    def __init__(self, ww: Worldwide):
        self.ww = ww
        rows = [
            dict(r)
            for r in ww.conn.execute(
                "SELECT * FROM horses WHERE (turf_wins > 0 OR aw_wins > 0) AND abs(random()) % 10 = 0"
            )
        ]
        self.population = histogram([t for t in (win_trip_f(r) for r in rows) if t])
        self.population_fit = window_share(self.population)
        self._damsire: dict[str, list[float]] = {}

    def damsire_trips(self, damsire: str) -> list[float]:
        if damsire not in self._damsire:
            rows = self.ww.damsire_produce(damsire)
            self._damsire[damsire] = progeny_stats(rows)["trips"]
        return self._damsire[damsire]

    def forecast(self, *, sire: str, dam: str, damsire: str = "") -> Forecast:
        pop = self.population
        sources: list[tuple[str, float, int]] = []
        # sire's side (0.5)
        st = self.ww.sire_stats(sire)["trips"] if sire else []
        ws = len(st) / (len(st) + K_SIRE) if st else 0.0
        sire_side = [(ws, histogram(st)), (1 - ws, pop)]
        sources.append((f"{sire} progeny", 0.5 * ws, len(st)))
        # dam's side (0.5): produce, then her own racing, then her sire's runners out of mares
        produce = [t for t in (win_trip_f(r) for r in self.ww.produce(dam)) if t] if dam else []
        left = 1.0
        dam_side: list[tuple[float, dict]] = []
        if produce:
            w = len(produce) / (len(produce) + K_PRODUCE) * left
            dam_side.append((w, histogram(produce)))
            sources.append((f"{dam} produce", 0.5 * w, len(produce)))
            left -= w
        own = self.ww.horse(dam) if dam else None
        own_t = (win_trip_f(own) or best_trip_f(own)) if own else None
        if own_t:
            w = 1 / (1 + K_DAM_SELF) * left
            dam_side.append((w, histogram([own_t])))
            sources.append((f"{dam} herself", 0.5 * w, 1))
            left -= w
        ds = self.damsire_trips(damsire) if damsire else []
        if ds:
            w = len(ds) / (len(ds) + K_DAMSIRE) * left
            dam_side.append((w, histogram(ds)))
            sources.append((f"{damsire} as broodmare sire", 0.5 * w, len(ds)))
            left -= w
        dam_side.append((left, pop))
        dist = _mix([(0.5, _mix(sire_side)), (0.5, _mix(dam_side))])
        return Forecast(dist=dist, fit=window_share(dist), median=_median(dist), sources=sources)
