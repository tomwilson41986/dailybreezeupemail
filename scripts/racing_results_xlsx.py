"""One-shot report: racing results so far for the gSheet breeze-up cohort.

Thin CLI over :mod:`dailybreezeup.results_report`, which joins the ratings
gSheet to Racing Post's sale catalogues on (sale, lot), pulls each named
horse's form (RPR = ``rpPostmark``) and builds the xlsx. The Friday weekly
summary email attaches the same workbook — see ``daily --mode weekly``.

Usage:

    .venv/bin/pip install -e ".[xlsx]"
    .venv/bin/python scripts/racing_results_xlsx.py --out "data/racing_results.xlsx"

Needs live Racing Post access (same bot-filter caveats as the daily email;
see README). Behind a TLS-intercepting proxy set ``RP_IMPERSONATE=chrome110``
— Chrome 124's post-quantum ClientHello is rejected by some MITM stacks —
and point ``CURL_CA_BUNDLE`` at the proxy CA.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dailybreezeup import results_report  # noqa: E402
from dailybreezeup import sheet as gsheet
from dailybreezeup.racing import rp_sales  # noqa: E402
from dailybreezeup.racing.rp_sales import _DOC_HEADERS  # noqa: E402

log = logging.getLogger("racing_results_xlsx")


def make_session():
    """curl_cffi session; impersonation target and CA bundle overridable via env."""
    from curl_cffi import requests as cffi_requests

    impersonate = os.environ.get("RP_IMPERSONATE", "chrome124")
    verify = os.environ.get("CURL_CA_BUNDLE") or os.environ.get("REQUESTS_CA_BUNDLE")
    s = cffi_requests.Session(impersonate=impersonate, verify=verify or True)
    s.headers.update(_DOC_HEADERS)
    return s


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=Path("data/racing_results.xlsx"))
    ap.add_argument("--sheet-url", default=os.environ.get("SHEET_CSV_URL")
                    or gsheet.DEFAULT_SHEET_CSV_URL)
    ap.add_argument("--sleep", type=float, default=0.45,
                    help="pause between RP requests (politeness)")
    args = ap.parse_args()

    rows = gsheet.fetch_sheet(args.sheet_url)
    log.info("sheet: %d rows", len(rows))

    session = make_session()
    all_lots: list[rp_sales.SaleLot] = []
    for sale in rp_sales.discover_sales(args.year, session=session):
        label = results_report.sheet_label_for_sale(sale.sale_name)
        if label is None:
            log.info("skipping %s (no sheet label)", sale.sale_name)
            continue
        lots = rp_sales.fetch_lots(sale, session=session, sleep=args.sleep)
        log.info("%s (%s): %d lots", sale.sale_name, label, len(lots))
        all_lots.extend(lots)

    lot_map = results_report.lot_lookup(all_lots)
    stats_by_uid = results_report.collect_form_stats(all_lots, session, sleep=args.sleep)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(results_report.build_workbook_bytes(rows, lot_map, stats_by_uid))
    raced = sum(1 for s in stats_by_uid.values() if s.runs)
    log.info("saved %s (%d named, %d raced)", args.out, len(stats_by_uid), raced)


if __name__ == "__main__":
    main()
