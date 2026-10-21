"""Gun Runner Mare Prospects — the Friday email.

Every filly and mare catalogued worldwide for a sale in the next ten weeks,
scored out of 100 as a Gun Runner mate; the prospects in a Winchell-style PDF,
one page each, with the CSVs.

Usage:
  gunrunner-weekly                  # build and send
  gunrunner-weekly --dry-run        # build into data/gunrunner/out, don't send
  gunrunner-weekly --date 2026-10-23
  gunrunner-weekly --warm           # mid-week: fetch and cache the families and Equibase, no email
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from gunrunner import csvout, emailer, pdf, report, silks, worldwide
from gunrunner.cache import Cache
from gunrunner.collect import US, collect, could_have_raced
from gunrunner.config import load
from gunrunner.enrich import Enricher
from gunrunner.equibase import Equibase
from gunrunner.family import FamilyBuilder
from gunrunner.forecast import Forecaster
from gunrunner.score import FIT_MIN, TRIP, UNRACED_MIN, Assessment, assess
from gunrunner.website import Website

log = logging.getLogger("gunrunner.daily")
UK = ZoneInfo("Europe/London")
WORLDWIDE_MAX_AGE = 30 * 86400
PDF_LIMIT = 22_000_000  # Gmail takes 25 MB, encoded


def _worth_equibase(a: Assessment, include_unraced: bool) -> bool:
    """A US filly the Equibase lookup could put on the list."""
    p = a.p
    if not a.eligible or p.c.region != US:
        return False
    if a.track == "raced":
        return not p.runs and (p.trip is None or TRIP[0] - 1 <= p.trip <= TRIP[1])
    if not include_unraced:
        return False
    d = p.family.dam
    fit = p.forecast.fit if p.forecast else 0
    return (d is None or not d.dirt_known) and fit >= FIT_MIN and a.score >= UNRACED_MIN - 15


def run(
    *, run_date: date | None = None, dry_run: bool = False, no_pdf: bool = False, warm: bool = False
) -> int:
    st = load()
    today = run_date or datetime.now(UK).date()
    data = st.data_dir
    out = data / "out" / today.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    ww_path = data / "worldwide.sqlite"
    if not ww_path.exists() or time.time() - ww_path.stat().st_mtime > WORLDWIDE_MAX_AGE:
        log.info("building the worldwide file")
        worldwide.build(ww_path)
    ww = worldwide.Worldwide(ww_path)
    cache = Cache(data / "cache.sqlite")

    from salescatalogues.sources.base import make_session

    cands, meta = collect(
        today, horizon_days=st.gunrunner_horizon_days, data_dir=data, session=make_session()
    )

    plain = requests.Session()
    eq = (
        Equibase(
            st.parse_bot_api_key,
            cache,
            budget=st.gunrunner_equibase_credits,
            floor=st.gunrunner_equibase_floor,
        )
        if st.parse_bot_api_key
        else None
    )
    web = Website(st.website, plain, cache, st.website_sales)
    web.load()
    en = Enricher(ww, Forecaster(ww), web, FamilyBuilder(st.family_api, plain, cache, ww, eq), eq)
    if not st.gunrunner_include_unraced:
        cands = [c for c in cands if could_have_raced(c)]
        log.info("with a chance of race form: %d", len(cands))
    en.prefetch(cands)
    scored = [assess(en.profile(c)) for c in cands]
    log.info("scored %d in %.0fs", len(scored), time.time() - t0)

    # Equibase within the budget, the likeliest prospects first
    if eq is not None:
        spent_on = 0
        for i in sorted(
            (i for i, a in enumerate(scored) if _worth_equibase(a, st.gunrunner_include_unraced)),
            key=lambda i: -scored[i].score,
        ):
            if not eq.can_spend:
                break
            scored[i] = assess(en.profile(scored[i].p.c, spend=True))
            spent_on += 1
        log.info(
            "equibase: %d horses looked at, %d credits spent, balance %s",
            spent_on,
            eq.spent,
            eq.balance,
        )
    if warm:
        log.info("warm run: caches filled in %.0fs", time.time() - t0)
        return 0
    if not st.gunrunner_include_unraced:
        scored = [a for a in scored if a.track == "raced"]
        log.info("with race form: %d", len(scored))

    rows = sorted(
        (a for a in scored if a.qualifies), key=lambda a: (-a.score, a.p.c.sale_date or date.max)
    )
    new_ids = {a.lot_id for a in rows if cache.first_reported(a.lot_id) is None}
    # the HIT watch: fillies in training just below the main list
    watch = sorted((a for a in scored if a.watch), key=lambda a: -a.score)
    new_ids |= {a.lot_id for a in watch if cache.first_reported(a.lot_id) is None}
    log.info("prospects: %d, HIT watch: %d (%d new)", len(rows), len(watch), len(new_ids))

    stamp = today.isoformat()
    csv_p = out / f"Gun Runner Mare Prospects {stamp}.csv"
    csv_p.write_text(csvout.to_csv(rows, new_ids, ranked=True, watch=watch), encoding="utf-8")
    everyone = sorted(scored, key=lambda a: (-a.qualifies, -a.score))
    csv_all = out / f"Gun Runner all scored {stamp}.csv"
    csv_all.write_text(csvout.to_csv(everyone, new_ids, ranked=False), encoding="utf-8")

    attachments = []
    if not no_pdf:
        raced_us = [
            {"lot_id": a.lot_id, "name": a.p.c.name, "sire": a.p.c.sire, "dam": a.p.c.dam}
            for a in rows + watch
            if a.track == "raced" and a.p.c.region == US and a.p.c.named
        ]
        try:
            silk = silks.fetch(raced_us, cache)
        except Exception as exc:  # noqa: BLE001
            log.warning("silks failed: %s", exc)
            silk = {}
        for a in rows + watch:
            if silk.get(a.lot_id, {}).get("url"):
                a.p.links["hrn"] = silk[a.lot_id]["url"]
        html = report.build(
            rows,
            run_date=today,
            scored=len(scored),
            sales=meta["sales"],
            new_ids=new_ids,
            silks=silk,
            include_unraced=st.gunrunner_include_unraced,
            watch=watch,
        )
        pdf_p = pdf.render(html, out / f"Gun Runner Mare Prospects {stamp}.pdf")
        if pdf_p.stat().st_size <= PDF_LIMIT:
            attachments.append(pdf_p)
        else:
            log.warning(
                "PDF %.1f MB is over the email limit; sent without it", pdf_p.stat().st_size / 1e6
            )
    attachments += [csv_p, csv_all]

    mail = emailer.compose(
        rows,
        run_date=today,
        scored=len(scored),
        new_ids=new_ids,
        attachments=attachments,
        watch=watch,
        pool="fillies and mares" if st.gunrunner_include_unraced else "raced fillies and mares",
    )
    (out / "email.html").write_text(mail.html, encoding="utf-8")
    (out / "email.txt").write_text(mail.text, encoding="utf-8")
    summary = {
        "date": stamp,
        "fillies_and_mares": len(scored),
        "prospects": len(rows),
        "hit_watch": len(watch),
        "new": len(new_ids),
        "raced": sum(1 for a in rows if a.track == "raced"),
        "sales": meta["sales"],
        "sources": meta["sources"],
        "equibase_spent": eq.spent if eq else 0,
        "equibase_balance": eq.balance if eq else None,
        "seconds": round(time.time() - t0),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")

    if dry_run:
        log.info("dry run: not sent. Output in %s", out)
        return 0
    try:
        emailer.send(mail, st)
    except Exception as exc:  # noqa: BLE001
        log.exception("send failed: %s", exc)
        return 1
    for a in rows + watch:
        cache.mark_reported(a.lot_id, a.score, today)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gunrunner-weekly")
    ap.add_argument(
        "--date", type=date.fromisoformat, default=None, help="YYYY-MM-DD (default: today UK)"
    )
    ap.add_argument("--dry-run", action="store_true", help="build the PDF and CSVs, don't send")
    ap.add_argument("--no-pdf", action="store_true", help="skip silks and the PDF")
    ap.add_argument("--warm", action="store_true", help="fill the caches only (no PDF, no email)")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return run(run_date=args.date, dry_run=args.dry_run, no_pdf=args.no_pdf, warm=args.warm)


if __name__ == "__main__":
    sys.exit(main())
