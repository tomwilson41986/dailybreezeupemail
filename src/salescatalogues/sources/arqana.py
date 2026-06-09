"""Arqana (France) — physical and online sales share one
``catalogues_results.html`` page of ``.bloc_vente`` blocks.

Each block has an ``h2`` name and a ``.description_info`` line carrying the date
span (with year) and venue. Past sales additionally expose results/Excel links;
we don't need to special-case them because the pipeline drops anything whose
end date is already in the past.
"""
from __future__ import annotations

import logging
from datetime import date

import lxml.html

from salescatalogues.models import RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://www.arqana.com/catalogues_results.html"
BASE = "https://www.arqana.com/"


def parse_catalogues(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[tuple[str, date | None]] = set()
    for bloc in doc.cssselect(".bloc_vente, .infos_vente"):
        h2 = bloc.cssselect("h2")
        if not h2:
            continue
        name = squash(h2[0].text_content())
        if not name:
            continue
        desc_el = bloc.cssselect(".description_info")
        if desc_el:
            date_text = squash(desc_el[0].text_content())
        else:
            # No dedicated date node: fall back to the block text but drop the
            # name prefix first, so a "v.2" in the name can't leak a stray day.
            full = squash(bloc.text_content())
            date_text = full[len(name):].strip() if full.startswith(name) else full
        start, end = parse_date_range(date_text, ref, dayfirst=True)
        key = (name.lower(), start)
        if key in seen:
            continue
        seen.add(key)

        link = bloc.cssselect("a")
        href = next((a.get("href") for a in link if a.get("href")), "")
        url = href if href.startswith("http") else f"{BASE}{href}" if href else URL
        out.append(
            RawSale(
                house="Arqana",
                country="FR",
                name=name,
                start_date=start,
                end_date=end,
                url=url,
                online="online" in name.lower(),
                description=date_text,
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("Arqana fetch failed: %s", exc)
        return []
    return parse_catalogues(html, ref=ref)
