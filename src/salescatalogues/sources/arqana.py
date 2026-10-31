"""Arqana (France) — physical and online sales share one
``catalogues_results.html`` page of ``.bloc_vente`` blocks.

Each block has an ``h2`` name and a ``.description_info`` line carrying the date
span (with year) and venue. Past sales additionally expose results/Excel links;
we don't need to special-case them because the pipeline drops anything whose
end date is already in the past.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date

import lxml.html

from salescatalogues.models import Lot, RawSale
from salescatalogues.sources.base import get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://www.arqana.com/catalogues_results.html"
BASE = "https://www.arqana.com/"

# Trailing numeric sale id in a catalogue/lots URL, e.g. ".../.../407".
_SALE_ID_RE = re.compile(r"/(?:catalogue|lots)/[^/]+/(\d+)")
# Arqana sex codes: Mâle / Femelle / Hongre.
_SEX = {"M.": "Colt", "F.": "Filly", "H.": "Gelding", "M": "Colt", "F": "Filly", "H": "Gelding"}


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
        m = _SALE_ID_RE.search(url)
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
                catalogue_ref=m.group(1) if m else "",
            )
        )
    return out


def _lot_field(item, data_c: str) -> str:
    el = item.cssselect(f'span[data-c="{data_c}"]')
    return (el[0].get("data-v") or "").strip() if el else ""


def parse_lots(html: str) -> list[Lot]:
    doc = lxml.html.fromstring(html)
    lots: list[Lot] = []
    for item in doc.cssselect(".tab_item"):
        lot_el = item.cssselect('div[data-label="Lot"] p')
        lot_no = squash(lot_el[0].text_content()).lstrip("0") if lot_el else ""
        name_el = item.cssselect('div[data-label="Nom"] a, div[data-label="Nom"] p')
        name = squash(name_el[0].text_content()) if name_el else ""
        # Unnamed lots render as "N(DAM YYYY)"; blank them.
        if name.upper().startswith("N(") or name.upper() == "UNNAMED":
            name = ""
        cells = _cells(item)
        dam = cells.get("mere", "")
        sex_raw = _lot_field(item, "lot_sexe")
        link = item.cssselect('div[data-label="Lot"] a')
        href = link[0].get("href") if link else ""
        lots.append(
            Lot(
                lot_no=lot_no,
                horse_name=name,
                sex=_SEX.get(sex_raw, sex_raw),
                sire=_lot_field(item, "lot_pere"),
                dam=dam,
                vendor=_lot_field(item, "lot_vendeur"),
                covering_sire=cells.get("pleine de", ""),
                # the product: Maiden, Poulinière, Foal, Yearling, Cheval à l'entraînement...
                lot_type=_lot_field(item, "lot_prod") or cells.get("produit", ""),
                url=f"https://www.arqana.com/{href.lstrip('/')}" if href and not href.startswith("http") else href,
            )
        )
    return lots


def _fold(s: str) -> str:
    """"Mère" -> "mere": labels compared without accents or case."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower().strip()


def _cells(item) -> dict[str, str]:
    """Each grid cell by its folded ``data-label``, read from the cell's ``title``
    (the full text) or its text."""
    out: dict[str, str] = {}
    for div in item.cssselect("div[data-label]"):
        p = div.cssselect("p")
        val = (p[0].get("title") if p and p[0].get("title") is not None else div.text_content()) or ""
        out[_fold(div.get("data-label") or "")] = squash(val)
    return out


def fetch_lots(raw: RawSale, session=None) -> list[Lot]:
    """Fetch the lot grid for an Arqana sale whose catalogue is published.
    Returns [] when the sale has no catalogue page yet (``catalogue_ref`` unset).
    """
    if not raw.catalogue_ref or "/catalogue/" not in raw.url and "/lots/" not in raw.url:
        return []
    session = session or make_session()
    try:
        html = get_text(session, raw.url)
    except Exception as exc:  # noqa: BLE001
        log.warning("Arqana lot fetch failed (%s): %s", raw.url, exc)
        return []
    return parse_lots(html)


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("Arqana fetch failed: %s", exc)
        return []
    return parse_catalogues(html, ref=ref)
