"""Keeneland (Lexington, Kentucky, USA).

Each sale is an ``a`` (linking ``/sales/<year>/<n>/<slug>/``) wrapping an
``h3.card-title`` name plus a trailing date span ("Sept. 14 - 26, 2026"). The
date is the anchor text with the title prefix stripped, parsed month-first.
"""
from __future__ import annotations

import logging
import re
from datetime import date

import lxml.html

from salescatalogues.models import Lot, RawSale
from salescatalogues.sources.base import get_json, get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://www.keeneland.com/sales/"
BASE = "https://www.keeneland.com"
LOTS_API = "https://www.keeneland.com/json/sale_api/get/catalog/{sale_id}"

# Numeric sale id in a Keeneland sale path: /sales/<year>/<id>/<slug>/.
_SALE_ID_RE = re.compile(r"/sales/\d{4}/(\d+)/")


def parse_sales(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    out: list[RawSale] = []
    seen: set[str] = set()
    for title_el in doc.cssselect("h3.card-title"):
        name = squash(title_el.text_content())
        if not name:
            continue
        # Climb to the enclosing anchor (carries href + the trailing date).
        anchor = title_el
        while anchor is not None and anchor.tag != "a":
            anchor = anchor.getparent()
        href = anchor.get("href") if anchor is not None else ""
        if not href or "/sales/" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)
        full = squash(anchor.text_content()) if anchor is not None else name
        date_text = full[len(name):] if full.startswith(name) else full
        start, end = parse_date_range(date_text, ref, dayfirst=False)
        url = href if href.startswith("http") else f"{BASE}{href}"
        m = _SALE_ID_RE.search(href)
        out.append(
            RawSale(
                house="Keeneland",
                country="US",
                name=name,
                start_date=start,
                end_date=end,
                url=url,
                online=False,
                catalogue_ref=m.group(1) if m else "",
            )
        )
    return out


def parse_lots(data: dict) -> list[Lot]:
    """Keeneland serves the catalogue as a JSON object keyed by node id; each
    value is a hip. The first entry is often a blank placeholder row."""
    lots: list[Lot] = []
    for hip in (data or {}).values():
        if not isinstance(hip, dict):
            continue
        hip_no = (hip.get("field_hip_number") or "").lstrip("0")
        alpha = (hip.get("field_hip_alpha") or "").strip()
        if not hip_no and not alpha:
            continue
        lots.append(
            Lot(
                lot_no=f"{hip_no}{alpha}",
                horse_name=(hip.get("title") or "").strip(),
                sex=(hip.get("field_sex") or "").strip(),
                colour=(hip.get("field_color") or "").strip(),
                sire=(hip.get("field_sire") or "").strip(),
                dam=(hip.get("field_dam") or "").strip(),
                dam_sire=(hip.get("field_broodmare_sire") or "").strip(),
                vendor=(
                    hip.get("field_consignor_name") or hip.get("field_consignor") or ""
                ).strip(),
            )
        )
    return lots


def fetch_lots(raw: RawSale, session=None) -> list[Lot]:
    if not raw.catalogue_ref:
        return []
    session = session or make_session()
    try:
        data = get_json(session, LOTS_API.format(sale_id=raw.catalogue_ref))
    except Exception as exc:  # noqa: BLE001
        log.warning("Keeneland lot fetch failed (sale %s): %s", raw.catalogue_ref, exc)
        return []
    # Empty body (200 + "") means the catalogue isn't published yet.
    return parse_lots(data) if isinstance(data, dict) else []


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("Keeneland fetch failed: %s", exc)
        return []
    return parse_sales(html, ref=ref)
