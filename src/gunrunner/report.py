"""The weekly PDF's HTML, Winchell Thoroughbreds style: a cover, the rules, the
ranked list, then one page per filly or mare."""

from __future__ import annotations

import base64
import html
import math
from datetime import date
from importlib import resources

from gunrunner.config import COVER_SIRES
from gunrunner.family import LEVEL_WEIGHT, Runner, class_points, label
from gunrunner.forecast import BINS, WINDOW
from gunrunner.score import CLASS_MIN, FIT_MIN, UNRACED_MIN, Assessment

MAROON, MAROON_D, INK, GREY, PAPER, LINE = (
    "#932E32",
    "#6E2226",
    "#1D1D1F",
    "#6B6B6B",
    "#F5F3EF",
    "#E4DFD8",
)
SEX = {"M": "mare", "F": "filly"}
LEVEL_NAME = {1: "Dam", 2: "2nd dam", 3: "3rd dam"}
e = html.escape


def _asset(name: str) -> str:
    data = resources.files("gunrunner").joinpath("assets", name).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode()


def png_uri(data: bytes | None) -> str | None:
    return "data:image/png;base64," + base64.b64encode(data).decode() if data else None


def money(v) -> str:
    return f"${v:,.0f}" if v else "–"


def money_short(v) -> str:
    if not v:
        return "–"
    return f"${v / 1e6:.2f}m" if v >= 1e6 else f"${v / 1e3:.0f}k" if v >= 1e4 else f"${v:,.0f}"


# the radar's spoke labels, short enough not to clip
SHORT = {
    "Family class": "Fam. class",
    "Family dirt": "Fam. dirt",
    "Distance fit": "Fit",
    "Family produce": "Produce",
}


def fdate(d) -> str:
    if not d:
        return "–"
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return d.strftime("%-d %b %y")


def pct(v: float | None) -> str:
    return f"{v * 100:.0f}%" if v is not None else "–"


# --- charts --------------------------------------------------------------------------


def radar(parts: dict[str, float], maxima: dict[str, int], size: int = 250) -> str:
    names = list(parts)
    cx = cy = size / 2
    rad = size / 2 - 52
    n = len(names)

    def pt(i: int, f: float) -> tuple[float, float]:
        return cx + rad * f * math.sin(2 * math.pi * i / n), cy - rad * f * math.cos(
            2 * math.pi * i / n
        )

    rings = "".join(
        f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, f) for i in range(n)))}" '
        f'fill="none" stroke="{LINE}" stroke-width="1"/>'
        for f in (0.25, 0.5, 0.75, 1.0)
    )
    spokes = "".join(
        f'<line x1="{cx}" y1="{cy}" x2="{pt(i, 1)[0]:.1f}" y2="{pt(i, 1)[1]:.1f}" '
        f'stroke="{LINE}" stroke-width="1"/>'
        for i in range(n)
    )
    vals = [max(0.0, min(1.0, parts[p] / maxima[p])) for p in names]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, v) for i, v in enumerate(vals)))
    dots = "".join(
        f'<circle cx="{pt(i, v)[0]:.1f}" cy="{pt(i, v)[1]:.1f}" r="2.6" fill="{MAROON}"/>'
        for i, v in enumerate(vals)
    )
    labels = ""
    for i, p in enumerate(names):
        x, y = pt(i, 1.2)
        anchor = "middle" if abs(x - cx) < 8 else ("start" if x > cx else "end")
        labels += f'<text x="{x:.1f}" y="{y + 3:.1f}" text-anchor="{anchor}" class="rl">{e(SHORT.get(p, p))}</text>'
    return (
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">{rings}{spokes}'
        f'<polygon points="{poly}" fill="{MAROON}" fill-opacity=".18" stroke="{MAROON}" stroke-width="1.8"/>'
        f"{dots}{labels}</svg>"
    )


def formline(runs: list[dict], w: int = 330, h: int = 86) -> str:
    pts = [
        (r["date"], r["fig"], r.get("finish"), r.get("grade"), r.get("stakes"))
        for r in reversed(runs)
        if r.get("fig") is not None
    ]
    if len(pts) < 2:
        return '<div class="muted small">Too few figures to plot.</div>'
    es = [p[1] for p in pts]
    lo, hi = min(min(es), 80) - 4, max(max(es), 100) + 4

    def X(i: int) -> float:
        return 18 + i * (w - 30) / (len(pts) - 1)

    def Y(v: float) -> float:
        return h - 14 - (v - lo) / (hi - lo) * (h - 26)

    ref = "".join(
        f'<line x1="14" x2="{w - 6}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{LINE}" stroke-dasharray="3 3"/>'
        f'<text x="{w - 4}" y="{Y(v) + 3:.1f}" class="ax" text-anchor="end">{v}</text>'
        for v in (90, 100)
        if lo < v < hi
    )
    path = " ".join(f"{'M' if i == 0 else 'L'}{X(i):.1f},{Y(p[1]):.1f}" for i, p in enumerate(pts))
    dots, yrs, seen = "", "", set()
    for i, (d, v, fin, g, st) in enumerate(pts):
        fill = MAROON if fin == 1 else "#fff"
        dots += (
            f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="{3.6 if (g or st) else 2.6}" fill="{fill}" '
            f'stroke="{MAROON}" stroke-width="1.4"/>'
        )
        if d[:4] not in seen:
            seen.add(d[:4])
            yrs += f'<text x="{min(X(i), w - 22):.1f}" y="{h - 1}" class="ax">{d[:4]}</text>'
    return (
        f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">{ref}'
        f'<path d="{path}" fill="none" stroke="{MAROON}" stroke-width="1.6"/>{dots}{yrs}</svg>'
    )


def forecast_chart(dist: dict[float, float], w: int = 340, h: int = 110) -> str:
    top = max(dist.values()) or 1
    bw = (w - 20) / len(BINS)
    bars, ticks = "", ""
    for i, b in enumerate(BINS):
        x = 10 + i * bw
        bh = (h - 26) * dist[b] / top
        inside = WINDOW[0] <= b <= WINDOW[1]
        bars += (
            f'<rect x="{x + 0.6:.1f}" y="{h - 16 - bh:.1f}" width="{bw - 1.2:.1f}" height="{bh:.1f}" '
            f'fill="{MAROON if inside else "#D6C9C7"}"/>'
        )
        if b == int(b) and int(b) % 2 == 0:
            ticks += f'<text x="{x + bw / 2:.1f}" y="{h - 4}" class="ax" text-anchor="middle">{int(b)}f</text>'
    x0 = 10 + BINS.index(WINDOW[0]) * bw
    x1 = 10 + (BINS.index(WINDOW[1]) + 1) * bw
    band = (
        f'<rect x="{x0:.1f}" y="2" width="{x1 - x0:.1f}" height="{h - 18}" fill="{MAROON}" fill-opacity=".06"/>'
        f'<text x="{(x0 + x1) / 2:.1f}" y="10" class="ax" text-anchor="middle">8–10f</text>'
    )
    return f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">{band}{bars}{ticks}</svg>'


def bands(rows: list[Assessment]) -> str:
    edges = [(90, 101), (80, 90), (70, 80), (60, 70), (50, 60), (0, 50)]
    counts = [sum(1 for r in rows if lo <= r.score < hi) for lo, hi in edges]
    w, bh, left = 640, 24, 70
    mx = max(counts) or 1
    out = ""
    for i, ((lo, _), c) in enumerate(zip(edges, counts, strict=True)):
        y = 6 + i * bh
        lab = f"{lo}s" if lo else "<50"
        bar = (w - left - 50) * c / mx
        out += (
            f'<text x="{left - 8}" y="{y + 14}" text-anchor="end" class="bl" style="font-size:10px">{lab}</text>'
            f'<rect x="{left}" y="{y}" width="{bar:.1f}" height="{bh - 8}" fill="{MAROON}"/>'
            f'<text x="{left + bar + 6:.1f}" y="{y + 14}" class="bv" style="font-size:10px">{c}</text>'
        )
    return f'<svg viewBox="0 0 {w} {len(edges) * bh + 10}" width="100%">{out}</svg>'


# --- text ---------------------------------------------------------------------------


def peak_text(a: Assessment) -> str:
    o = a.p.own
    if not o:
        return f"Fit {pct(a.p.forecast.fit)}" if a.p.forecast else "–"
    bits = []
    if o.e:
        bits.append(f"E {o.e}")
    if o.rating:
        bits.append(f"TF {o.rating:.0f}")
    return " · ".join(bits) or "–"


def short_label(r: Runner) -> str:
    return (
        label(r)
        .replace("Black-type", "BT")
        .replace("Group/graded", "Graded")
        .replace(" on dirt", " (D)")
    )


def runner_line(r: Runner) -> str:
    bits = [label(r)]
    if r.raced:
        bits.append(f"{r.wins}/{r.runs}")
    if r.rating:
        bits.append(f"TF {r.rating:.0f}")
    if r.e:
        bits.append(f"E {r.e}")
    if r.prize_usd:
        bits.append(money(r.prize_usd))
    return " · ".join(bits)


def case(a: Assessment) -> list[str]:
    """Her case in short lines."""
    p = a.p
    out = [
        f"By {p.c.sire}. {p.ped['line']} line, {p.ped['rate'] * 100:.0f}% SW/runners with Gun Runner."
    ]
    if p.raced:
        o = p.own
        if o.e:
            out.append(f"Peak E {o.e}.")
        if o.rating:
            out.append(f"Timeform {o.rating:.0f}.")
        surf = (
            "Dirt"
            if (p.dirt_share or 0) >= 0.75
            else "Dirt and turf"
            if (p.dirt_share or 0) >= 0.35
            else "Turf / synthetic"
        )
        if p.trip:
            out.append(f"{surf}. {p.trip_from.capitalize()} {p.trip:g}f.")
        out.append(f"{p.stakes[1]}. {money(p.earnings)}.")
    elif p.forecast:
        out.append(f"Forecast {pct(p.forecast.fit)} at 8–10f, median {p.forecast.median:g}f.")
    depth = a.dirt_depth
    if depth:
        lv = p.family.level(depth)
        names = ", ".join(m.name for m in lv.dirt_members()[:3])
        out.append(f"Dirt form under the {LEVEL_NAME[depth].lower()}: {names}.")
    d = p.family.dam
    if d and d.raced:
        out.append(f"Dam {d.name}: {runner_line(d)}.")
    if p.c.covering_sire:
        out.append(f"Covered by {p.c.covering_sire}.")
    if a.candy:
        out.append("Candy Ride 2x3 in the foal: −5.")
    return out


def family_panel(a: Assessment) -> str:
    out = ""
    for n in (1, 2, 3):
        lv = a.p.family.level(n)
        if not lv.dam:
            continue
        rec = runner_line(lv.dam_record) if lv.dam_record else "Record not held"
        kids = sorted(
            [k for k in lv.produce if k.raced],
            key=lambda k: (-class_points(k), -(k.dirt_wins or 0)),
        )[:4]
        s = lv.summary()
        rows = "".join(
            f"<tr><td>{e(k.name)}{' <b class=d>D</b>' if k.dirt_wins else ''}</td><td>{e(runner_line(k))}</td></tr>"
            for k in kids
        )
        out += (
            f'<div class="lvl"><div class="lh"><span>{LEVEL_NAME[n]}</span> {e(lv.dam)}'
            f'<span class="muted"> · {e(rec)}</span></div>'
            f'<div class="small muted">{s["runners"]} runners, {s["winners"]} winners, {s["bt"]} black type'
            f"{' · weight ' + format(LEVEL_WEIGHT[n], 'g') if n > 1 else ''}</div>"
            f"{'<table class=fam>' + rows + '</table>' if rows else ''}</div>"
        )
    return out or '<div class="muted small">Family not held.</div>'


def links(a: Assessment) -> str:
    p = a.p
    u = p.links
    out = []
    if p.c.url:
        out.append(f'<a href="{e(p.c.url)}">{e(p.c.house)}</a>')
    for k, lab in (("pedigreePdf", "Catalogue page"), ("ppPdf", "Past performances")):
        if u.get(k):
            out.append(f'<a href="{e(u[k])}">{lab}</a>')
    rep = u.get("replays")
    if rep:
        out.append(f'<a href="{e(rep[0] if isinstance(rep, list) else rep)}">Replays</a>')
    if u.get("equibase"):
        out.append(f'<a href="{e(u["equibase"])}">Equibase</a>')
    elif p.eq_ref:
        out.append(
            f'<a href="https://www.equibase.com/profiles/Results.cfm?type=Horse&refno={e(p.eq_ref)}'
            f'&registry=T">Equibase</a>'
        )
    if u.get("hrn"):
        out.append(f'<a href="{e(u["hrn"])}">Profile</a>')
    return " · ".join(out)


def runs_table(p) -> str:
    if p.runs:
        rows = "".join(
            f"<tr><td>{fdate(x['date'])}</td><td>{e(x.get('track') or '')}</td><td>{'Turf' if x.get('turf') else 'Dirt'}</td>"
            f"<td>{e(x.get('race') or '')}</td><td class=c>{x.get('fig') if x.get('fig') is not None else '–'}</td>"
            f"<td class='c {'w' if x.get('finish') == 1 else ''}'>{x.get('finish') or '–'}</td></tr>"
            for x in p.runs[:10]
        )
        return (
            f'<table class="runs"><tr><th>Date</th><th>Trk</th><th>Surf</th><th>Race</th><th class=c>E</th>'
            f"<th class=c>Fin</th></tr>{rows}</table>"
        )
    if p.last_runs:
        return "<ul class=why>" + "".join(f"<li>{e(x)}</li>" for x in p.last_runs) + "</ul>"
    return '<div class="muted small">No run lines held.</div>'


# --- pages ----------------------------------------------------------------------------


def _header(i: int, a: Assessment, new: bool) -> str:
    c = a.p.c
    sale = f"{c.house} {c.sale} · Lot {c.lot_no} · {fdate(c.sale_date)}"
    sub2 = [f'<b style="color:{MAROON}">{e(a.status)}</b>']
    if c.covering_sire and not a.status.startswith("Covered"):
        sub2.append(f"Covered by {e(c.covering_sire)}")
    if c.vendor:
        sub2.append(f"Consigned by {e(c.vendor)}")
    if new:
        sub2.append('<b class="new">New this week</b>')
    yob = f"{c.yob} " if c.yob else ""
    colour = f"{c.colour.lower()} " if c.colour and c.colour.isalpha() else ""
    return f"""
  <header class="hh">
    <div class="rank">{i}</div>
    <div class="hn">
      <div class="eyebrow">{e(sale)}</div>
      <h2>{e(c.display_name)}</h2>
      <div class="sub">{yob}{e(colour)}{SEX.get(c.sex, "")} · {e(c.sire)} – {e(c.dam)}{", by " + e(c.damsire) if c.damsire else ""}</div>
      <div class="sub">{" · ".join(sub2)}</div>
    </div>
    <div class="score"><div class="sv">{a.score:.0f}</div><div class="sl">Gun Runner match</div></div>
  </header>"""


def _parts_table(a: Assessment) -> str:
    return "".join(
        f'<tr><td>{e(k)}</td><td class="bar"><div style="width:{v / a.maxima[k] * 100:.0f}%"></div></td>'
        f'<td class="r">{v:g}<span>/{a.maxima[k]}</span></td></tr>'
        for k, v in a.parts.items()
    )


def _tiles(tiles: list[tuple[str, object, str]]) -> str:
    return "".join(
        f'<div class="tile"><div class="tl">{a}</div><div class="tv">{b}<span>{c}</span></div></div>'
        for a, b, c in tiles
    )


def raced_page(i: int, a: Assessment, new: bool, silk: dict | None) -> str:
    p = a.p
    o = p.own
    silk = silk or {}
    img = (
        f'<img class="silk" src="{silk["png"]}">'
        if silk.get("png")
        else '<div class="silk nosilk">Silks<br>not held</div>'
    )
    tiles = [
        ("Match", f"{a.score:.0f}", "/100"),
        ("Peak E", o.e or "–", ""),
        ("Timeform", f"{o.rating:.0f}" if o.rating else "–", ""),
        ("Thoro-Graph", p.tg if p.tg is not None else "–", ""),
        ("AEI", f"{p.aei:.2f}" if p.aei else "–", ""),
        ("Record", f"{o.runs}-{o.wins}", ""),
        ("Earned", money_short(p.earnings), ""),
        ("R2 Rating", p.r2 if p.r2 is not None else "–", ""),
    ]
    figs = [x for x in p.runs if x.get("fig") is not None]
    last3 = " · ".join(str(x["fig"]) for x in figs[:3]) or "–"
    form = ""
    if figs:
        form = (
            f'<h3>Form <span class="muted small">E figure by run · filled = win · large = stakes</span></h3>'
            f'{formline(p.runs)}<div class="small">Last three: <b>{last3}</b> · Last run {fdate(p.runs[0]["date"])}'
            f" · {e(p.stakes[1])}</div>"
        )
    owner = silk.get("owner") or "–"
    trainer = silk.get("trainer") or p.trainer or "–"
    return f"""
<section class="page horse">{_header(i, a, new)}
  <div class="tiles">{_tiles(tiles)}</div>
  <div class="grid">
    <div class="col">
      <h3>Match</h3>
      <div class="radarwrap">{radar(a.parts, a.maxima)}</div>
      <table class="parts">{_parts_table(a)}</table>
      <h3>The case</h3>
      <ul class="why">{"".join(f"<li>{e(x)}</li>" for x in case(a))}</ul>
    </div>
    <div class="col">
      <div class="silkrow">{img}<div><div class="tl">Last raced for</div><div class="own">{e(owner)}</div>
        <div class="tl">Trainer</div><div class="own">{e(trainer)}</div></div></div>
      <h3>Family</h3>
      {family_panel(a)}
      {form}
      <h3>Runs</h3>
      {runs_table(p)}
      <div class="links">{links(a)}</div>
    </div>
  </div>
</section>"""


def unraced_page(i: int, a: Assessment, new: bool) -> str:
    p = a.p
    f = p.forecast
    s1 = p.family.level(1).summary()
    depth = a.dirt_depth
    tiles = [
        ("Match", f"{a.score:.0f}", "/100"),
        ("8–10f fit", pct(f.fit) if f else "–", ""),
        ("Median trip", f"{f.median:g}" if f and f.median else "–", "f"),
        ("Dirt form", LEVEL_NAME[depth] if depth else "–", ""),
        ("Dam", short_label(p.family.dam) if p.family.dam else "–", ""),
        ("Dam's winners", f"{s1['winners']}/{s1['runners']}", ""),
        ("Black type", s1["bt"], " foals"),
    ]
    src = ""
    if f:
        src = " · ".join(f"{e(lab)} {w * 100:.0f}% (n={n})" for lab, w, n in f.sources if w > 0.005)
    return f"""
<section class="page horse">{_header(i, a, new)}
  <div class="tiles t7">{_tiles(tiles)}</div>
  <div class="grid">
    <div class="col">
      <h3>Match</h3>
      <div class="radarwrap">{radar(a.parts, a.maxima)}</div>
      <table class="parts">{_parts_table(a)}</table>
      <h3>The case</h3>
      <ul class="why">{"".join(f"<li>{e(x)}</li>" for x in case(a))}</ul>
    </div>
    <div class="col">
      <h3>Forecast distance fit <span class="muted small">share of wins by trip</span></h3>
      {forecast_chart(f.dist) if f else '<div class="muted small">No forecast.</div>'}
      <div class="small muted">{src}{" · rest: all winners" if src else ""}</div>
      <h3>Pedigree</h3>
      <table class="kv">
        <tr><td>Sire</td><td>{e(p.c.sire)} <span class="muted">· {e(p.ped["line"])}</span></td></tr>
        <tr><td>With Gun Runner</td><td>{p.ped["rate"] * 100:.0f}% SW/runners{" (exact cross)" if p.ped["exact"] else " (line)"}</td></tr>
        <tr><td>Damsire</td><td>{e(p.c.damsire or "–")}</td></tr>
      </table>
      <h3>Family <span class="muted small"><b class=d>D</b> = won on dirt</span></h3>
      {family_panel(a)}
      <div class="links">{links(a)}</div>
    </div>
  </div>
</section>"""


CSS = f"""
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: 'Lexend', 'Inter', sans-serif; color: {INK}; font-size: 9.6pt; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
.page {{ width: 210mm; height: 297mm; padding: 14mm 14mm 12mm; page-break-after: always; position: relative; overflow: hidden; }}
.page:last-child {{ page-break-after: auto; }}
.page::after {{ content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 5mm; background: {MAROON}; }}
h1 {{ font-weight: 600; font-size: 34pt; line-height: 1.05; margin: 0; letter-spacing: -.01em; }}
h2 {{ font-weight: 600; font-size: 20pt; margin: 2px 0 3px; letter-spacing: -.01em; }}
h3 {{ font-size: 8.4pt; font-weight: 600; text-transform: uppercase; letter-spacing: .12em; color: {MAROON}; margin: 11px 0 6px; border-bottom: 1px solid {LINE}; padding-bottom: 3px; }}
.muted {{ color: {GREY}; }} .small {{ font-size: 8pt; }}
a {{ color: {MAROON}; text-decoration: none; font-weight: 500; }}
.cover {{ background: {MAROON}; color: #fff; display: flex; flex-direction: column; justify-content: space-between; }}
.cover::after {{ background: #fff; height: 2mm; }}
.cover .top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
.cover .mark {{ width: 44mm; background: #fff; border-radius: 50%; padding: 6mm; }}
.cover .kick {{ font-size: 10pt; letter-spacing: .2em; text-transform: uppercase; opacity: .85; }}
.cover .lede {{ font-size: 13pt; font-weight: 300; max-width: 150mm; line-height: 1.45; margin-top: 8mm; }}
.cover .foot {{ display: flex; gap: 12mm; font-size: 9pt; }}
.cover .foot b {{ display: block; font-size: 20pt; font-weight: 600; }}
.model td {{ padding: 5px 8px; border-bottom: 1px solid {LINE}; vertical-align: top; font-size: 9pt; }}
.model td:first-child {{ font-weight: 600; width: 34mm; }} .model td.w {{ color: {MAROON}; font-weight: 600; width: 14mm; text-align: right; }}
table {{ border-collapse: collapse; width: 100%; }}
.rank50 th {{ background: {MAROON}; color: #fff; font-weight: 500; font-size: 7.2pt; text-align: left; padding: 4px 4px; }}
.rank50 td {{ font-size: 7pt; padding: 2.3px 4px; border-bottom: 1px solid {LINE}; white-space: nowrap; max-width: 34mm; overflow: hidden; text-overflow: ellipsis; }}
.rank50 tr:nth-child(even) td {{ background: {PAPER}; }}
.rank50 .sc {{ font-weight: 600; color: {MAROON}; }} .rank50 .nm {{ font-weight: 600; }}
.bl {{ font-size: 7.4px; fill: {INK}; font-family: Lexend; }} .bv {{ font-size: 7.6px; font-weight: 600; fill: {MAROON}; font-family: Lexend; }}
.hh {{ display: flex; gap: 6mm; align-items: flex-start; border-bottom: 2px solid {MAROON}; padding-bottom: 4mm; }}
.rank {{ font-size: 28pt; font-weight: 600; color: {MAROON}; line-height: 1; min-width: 14mm; }}
.hn {{ flex: 1; }} .eyebrow {{ font-size: 7.4pt; letter-spacing: .12em; text-transform: uppercase; color: {GREY}; }}
.sub {{ font-size: 8.6pt; color: #333; margin-top: 1px; }}
.new {{ background: {MAROON}; color: #fff; padding: 0 4px; font-weight: 500; white-space: nowrap; }}
.score {{ background: {MAROON}; color: #fff; text-align: center; padding: 3mm 5mm; border-radius: 3px; min-width: 30mm; }}
.score .sv {{ font-size: 30pt; font-weight: 600; line-height: 1; }} .score .sl {{ font-size: 6.8pt; text-transform: uppercase; letter-spacing: .12em; margin-top: 2px; }}
.tiles {{ display: grid; grid-template-columns: repeat(8, 1fr); gap: 2mm; margin: 4mm 0 1mm; }}
.tiles.t7 {{ grid-template-columns: repeat(7, 1fr); }}
.tile {{ background: {PAPER}; padding: 2.4mm 2.6mm; border-top: 2px solid {MAROON}; overflow: hidden; }}
.tl {{ font-size: 6.4pt; text-transform: uppercase; letter-spacing: .1em; color: {GREY}; }}
.tv {{ font-size: 11pt; font-weight: 600; margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }} .tv span {{ font-size: 7pt; color: {GREY}; font-weight: 400; }}
.grid {{ display: grid; grid-template-columns: 74mm 1fr; gap: 8mm; }}
.radarwrap {{ display: flex; justify-content: center; }}
.rl {{ font-size: 8.2px; fill: {INK}; font-family: Lexend; }}
.parts td {{ font-size: 8pt; padding: 2px 0; }} .parts td.bar {{ width: 38%; padding: 0 6px; }}
.parts td.bar div {{ height: 6px; background: {MAROON}; }} .parts td.r {{ text-align: right; font-weight: 600; white-space: nowrap; }} .parts td.r span {{ color: {GREY}; font-weight: 400; }}
.why {{ margin: 0; padding-left: 14px; }} .why li {{ margin: 0 0 3px; line-height: 1.4; }}
.silkrow {{ display: flex; gap: 5mm; align-items: center; background: {PAPER}; padding: 3mm; }}
.silk {{ width: 24mm; height: 24mm; object-fit: contain; }}
.nosilk {{ display: flex; align-items: center; justify-content: center; text-align: center; border: 1px dashed #bbb; font-size: 7pt; color: {GREY}; }}
.own {{ font-size: 9pt; font-weight: 500; margin-bottom: 2mm; }}
.kv td {{ padding: 2.2px 0; font-size: 8.4pt; vertical-align: top; }} .kv td:first-child {{ color: {GREY}; width: 27mm; }}
.lvl {{ margin-bottom: 5px; }} .lh {{ font-size: 8.6pt; font-weight: 600; }} .lh span:first-child {{ color: {MAROON}; text-transform: uppercase; font-size: 7pt; letter-spacing: .1em; margin-right: 4px; }}
.fam td {{ font-size: 7.6pt; padding: 1.4px 0; border-bottom: 1px solid {LINE}; }} .fam td:first-child {{ width: 40%; font-weight: 500; }}
.d {{ color: #fff; background: {MAROON}; font-size: 6pt; padding: 0 2px; border-radius: 2px; }}
.ax {{ font-size: 7px; fill: {GREY}; font-family: Lexend; }}
.runs th {{ font-size: 7pt; text-align: left; color: {GREY}; font-weight: 500; border-bottom: 1px solid {INK}; padding: 2px 4px; }}
.runs td {{ font-size: 7.4pt; padding: 2px 4px; border-bottom: 1px solid {LINE}; }}
.runs td:first-child {{ white-space: nowrap; }}
.runs .c {{ text-align: center; }} .runs td.w {{ color: {MAROON}; font-weight: 700; }}
.links {{ margin-top: 3mm; font-size: 8.4pt; }}
"""


def build(
    rows: list[Assessment],
    *,
    run_date: date,
    scored: int,
    sales: list[dict],
    new_ids: set[str],
    silks: dict[str, dict],
) -> str:
    raced = sum(1 for r in rows if r.track == "raced")
    n_new = sum(1 for r in rows if r.lot_id in new_ids)
    houses = sorted({s["house"] for s in sales if s.get("females")})
    cover = f"""
<section class="page cover">
  <div class="top"><div class="kick">Gun Runner · Weekly · {run_date:%-d %B %Y}</div><img class="mark" src="{_asset("winchell_silk.png")}"></div>
  <div>
    <h1>Gun Runner<br>Mare Prospects</h1>
    <div class="lede">Fillies and mares catalogued worldwide in the next ten weeks that best fit Gun Runner. {e(", ".join(houses))}.</div>
  </div>
  <div class="foot"><div><b>{scored:,}</b>fillies and mares scored</div><div><b>{len(rows)}</b>prospects</div>
    <div><b>{raced} · {len(rows) - raced}</b>raced · unraced</div><div><b>{n_new}</b>new this week</div></div>
</section>"""
    intro = f"""
<section class="page intro">
  <h2>Gun Runner match</h2>
  <h3>Raced</h3>
  <table class="model">
    <tr><td>Pedigree</td><td class=w>25</td><td>Her sire as broodmare sire with Gun Runner, else his line.</td></tr>
    <tr><td>Class</td><td class=w>25</td><td>Peak Equibase figure: 105+ full marks, 100+ 22, 97+ 18. Timeform 115+ / 108+ / 100+ the same. Black type and earnings for the rest.</td></tr>
    <tr><td>Dirt</td><td class=w>10</td><td>Share of her form on dirt. Dirt in the family: up to 6.</td></tr>
    <tr><td>Route</td><td class=w>10</td><td>Trip of her best win or peak run. 8–10f full marks.</td></tr>
    <tr><td>Stakes</td><td class=w>15</td><td>G1 winner 15, G2 13.5, G3 12, stakes winner 10, graded placed 8, stakes placed 6.</td></tr>
    <tr><td>Earnings</td><td class=w>10</td><td>$400k+ full marks.</td></tr>
    <tr><td>Speed</td><td class=w>5</td><td>Best Thoro-Graph. Not held: the rest scaled to 100.</td></tr>
  </table>
  <h3>Unraced</h3>
  <table class="model">
    <tr><td>Pedigree</td><td class=w>25</td><td>As raced.</td></tr>
    <tr><td>Family class</td><td class=w>25</td><td>Best runner under the dam, 2nd dam, 3rd dam. Weighted 1 / 0.6 / 0.35.</td></tr>
    <tr><td>Family dirt</td><td class=w>20</td><td>Nearest dirt form. Dirt black-type winner full marks. Weighted 1 / 0.75 / 0.55.</td></tr>
    <tr><td>Distance fit</td><td class=w>20</td><td>Forecast share of wins at 8–10f, from sire and dam. 20% nil, 45% full marks; all winners 24%.</td></tr>
    <tr><td>Family produce</td><td class=w>10</td><td>Dam's winners and stakes winners.</td></tr>
  </table>
  <h3>To qualify</h3>
  <table class="model">
    <tr><td>Raced</td><td class=w></td><td>Class {CLASS_MIN}/25 or better (E 97). Best win or peak run 8–10f.</td></tr>
    <tr><td>Unraced</td><td class=w></td><td>Distance fit {FIT_MIN:.0%}+. Match {UNRACED_MIN}+.</td></tr>
    <tr><td>Dirt</td><td class=w></td><td>US: her own dirt form, or the dam's (unraced). Europe and Australasia: dirt form anywhere to the 3rd dam.</td></tr>
    <tr><td>Status</td><td class=w></td><td>Foals, yearlings, 2yos, fillies in training, maidens: all. Covered: first foal only, by {e(", ".join(COVER_SIRES))}. No experienced mares.</td></tr>
    <tr><td>Out</td><td class=w></td><td>Gun Runner's daughters. Candy Ride-line sires lose 5.</td></tr>
  </table>
  <h3>Match scores</h3>
  {bands(rows)}
</section>"""
    trs = [
        f"<tr><td>{i}</td><td class=sc>{r.score:.0f}</td><td>{e(r.p.c.house)}</td><td>{e(r.p.c.lot_no)}</td>"
        f"<td class=nm>{e(r.p.c.display_name)}{' ●' if r.lot_id in new_ids else ''}</td><td>{r.p.c.age if r.p.c.age is not None else ''}</td>"
        f"<td>{e(r.status)}</td><td>{e(r.p.c.sire)}</td><td>{e(peak_text(r))}</td>"
        f"<td>{LEVEL_NAME.get(r.dirt_depth, '–') if r.dirt_depth else ('Own' if (r.p.dirt_share or 0) >= 0.5 else '–')}</td>"
        f"<td>{fdate(r.p.c.sale_date)}</td></tr>"
        for i, r in enumerate(rows, 1)
    ]
    head = (
        "<tr><th>#</th><th>Match</th><th>House</th><th>Lot</th><th>Horse</th><th>Age</th><th>Status</th>"
        "<th>Sire</th><th>Peak / fit</th><th>Dirt</th><th>Sells</th></tr>"
    )
    table = "".join(
        f"""
<section class="page">
  <h2>Ranked {k + 1}–{min(k + 55, len(trs))} <span class="muted small">● new this week</span></h2>
  <table class="rank50">{head}{"".join(trs[k : k + 55])}</table>
</section>"""
        for k in range(0, len(trs), 55)
    )
    pages = "".join(
        raced_page(i, r, r.lot_id in new_ids, silks.get(r.lot_id))
        if r.track == "raced"
        else unraced_page(i, r, r.lot_id in new_ids)
        for i, r in enumerate(rows, 1)
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Gun Runner Mare Prospects</title>
<link href="https://fonts.googleapis.com/css2?family=Lexend:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>{cover}{intro}{table}{pages}</body></html>"""
