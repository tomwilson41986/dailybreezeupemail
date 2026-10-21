"""The CSVs: the prospects (the main list, then the HIT watch), and every filly
and mare scored."""

from __future__ import annotations

import csv
import io

from gunrunner.family import label
from gunrunner.report import LEVEL_NAME
from gunrunner.score import RACED_MAX, UNRACED_MAX, Assessment

PARTS = list(RACED_MAX) + [k for k in UNRACED_MAX if k not in RACED_MAX]
HEADERS = [
    "Rank",
    "List",
    "Match",
    "Qualifies",
    "Why not",
    "New",
    "Track",
    "Status",
    "House",
    "Sale",
    "Sells",
    "Lot",
    "Horse",
    "Foaled",
    "Age",
    "Sex",
    "Colour",
    "Sire",
    "Sire line",
    "Dam",
    "Damsire",
    "Covered by",
    "Region",
    "Vendor",
    *[f"{p} /{RACED_MAX.get(p) or UNRACED_MAX.get(p)}" for p in PARTS],
    "Candy Ride -5",
    "GR x line SW/rnrs",
    "Peak E",
    "Timeform",
    "Thoro-Graph",
    "AEI",
    "R2 Rating",
    "Starts",
    "Wins",
    "Earned",
    "Stakes",
    "Dirt share",
    "Dirt from",
    "Trip (f)",
    "Trip from",
    "Dirt form in family",
    "Dirt runners",
    "8-10f fit",
    "Forecast median (f)",
    "Dam",
    "Dam record",
    "2nd dam",
    "2nd dam record",
    "3rd dam",
    "3rd dam record",
    "Dam runners",
    "Dam winners",
    "Dam black type",
    "Sources",
    "Lot page",
]


def row(i: int | str | None, a: Assessment, new: bool) -> list:
    p, c, o = a.p, a.p.c, a.p.own
    fam = p.family

    def lv(n: int) -> tuple[str, str]:
        x = fam.level(n)
        return x.dam, (label(x.dam_record) if x.dam_record else "")

    s1 = fam.level(1).summary()
    depth = a.dirt_depth
    dirt_names = "; ".join(m.name for m in fam.level(depth).dirt_members()[:5]) if depth else ""
    return [
        i,
        "Main" if a.qualifies else "HIT watch" if a.watch else "",
        a.score,
        "Yes" if a.qualifies else "",
        "; ".join(a.reasons),
        "Yes" if new else "",
        a.track,
        a.status,
        c.house,
        c.sale,
        c.sale_date.isoformat() if c.sale_date else "",
        c.lot_no,
        c.display_name,
        c.yob,
        c.age,
        {"F": "Filly", "M": "Mare"}.get(c.sex, c.sex),
        c.colour,
        c.sire,
        p.ped["line"],
        c.dam,
        c.damsire,
        c.covering_sire,
        c.region,
        c.vendor,
        *[a.parts.get(k, "") for k in PARTS],
        "Yes" if a.candy else "",
        round(p.ped["rate"], 3),
        o.e if o else "",
        o.rating if o else "",
        p.tg,
        p.aei,
        p.r2,
        o.runs if o else 0,
        o.wins if o else 0,
        p.earnings,
        p.stakes[1] if o else "",
        round(p.dirt_share, 2) if p.dirt_share is not None else "",
        p.dirt_from,
        p.trip,
        p.trip_from,
        LEVEL_NAME.get(depth, "") if depth else "",
        dirt_names,
        round(p.forecast.fit, 3) if p.forecast else "",
        p.forecast.median if p.forecast else "",
        *lv(1),
        *lv(2),
        *lv(3),
        s1["runners"],
        s1["winners"],
        s1["bt"],
        ", ".join(p.sources + fam.sources),
        c.url,
    ]


def to_csv(
    rows: list[Assessment], new_ids: set[str], *, ranked: bool, watch: list[Assessment] = ()
) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADERS)
    for i, a in enumerate(rows, 1):
        w.writerow(row(i if ranked else None, a, a.lot_id in new_ids))
    for i, a in enumerate(watch, 1):
        w.writerow(row(f"W{i}" if ranked else None, a, a.lot_id in new_ids))
    return buf.getvalue()
