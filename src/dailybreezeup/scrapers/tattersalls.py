"""Tattersalls catalogue scraper (Newmarket, UK).

Covers:
  - Craven Breeze Up Sale  (April)
  - Guineas Breeze Up Sale (late April / early May)

Tattersalls publish catalogues on `www.tattersalls.com/sales/<slug>/` with lot
data rendered server-side and also accessible via their 4D-Server backend at
`secure.tattersalls.com/4DCGI/...`. The selectors below target the public
catalogue pages.

SELECTORS ARE UNVERIFIED: run `python -m dailybreezeup.seed --sale=tatts-craven-2026`
locally; if lot counts come back as 0 or fields look wrong, tweak the SELECTORS
dict below. Catalogue HTML for this vendor uses a tabular lot grid.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterable

from bs4 import BeautifulSoup

from dailybreezeup.models import RawLot, SaleDescriptor
from dailybreezeup.racing.common import get_text, make_session

log = logging.getLogger(__name__)

BASE = "https://www.tattersalls.com"
SLUGS = {
    "tatts-craven": "sales/craven-breeze-up-sale",
    "tatts-guineas": "sales/guineas-breeze-up-sale",
}

SELECTORS = {
    "catalogue_grid": "table.catalogue, div.lot-grid, div.catalogue-list",
    "lot_row": "tr.lot, li.lot, div.lot-item",
    "lot_number": ".lot-number, td.lot, .lot-no",
    "horse_name": ".horse-name, .name",
    "sire": ".sire",
    "dam": ".dam",
    "consignor": ".consignor, .vendor",
    "year_foaled": ".foaled, .year",
    "sex": ".sex",
    "country_bred": ".country",
    "buyer": ".buyer",
    "price": ".price, .sold-for",
    "withdrawn": ".withdrawn, .wd",
    "lot_link": "a.lot-link, a",
}

_MONEY = re.compile(r"[£€]?\s*([0-9][0-9,]*)")


def _parse_money(raw: str | None) -> tuple[int | None, str | None]:
    if not raw:
        return None, None
    currency = "GBP" if "£" in raw else ("EUR" if "€" in raw else None)
    m = _MONEY.search(raw)
    if not m:
        return None, currency
    return int(m.group(1).replace(",", "")), currency or "GBP"


def _text(node) -> str | None:  # noqa: ANN001
    return node.get_text(" ", strip=True) if node else None


class TattersallsScraper:
    vendor = "tattersalls"

    def list_sales(self, years: list[int]) -> list[SaleDescriptor]:
        out: list[SaleDescriptor] = []
        for slug_key, path in SLUGS.items():
            name = {
                "tatts-craven": "Tattersalls Craven Breeze Up Sale",
                "tatts-guineas": "Tattersalls Guineas Breeze Up Sale",
            }[slug_key]
            for year in years:
                out.append(
                    SaleDescriptor(
                        id=f"{slug_key}-{year}",
                        vendor=self.vendor,
                        name=name,
                        country="GB",
                        year=year,
                        source_url=f"{BASE}/{path}/",
                    )
                )
        return out

    def fetch_lots(self, sale_id: str) -> Iterable[RawLot]:
        slug_key = "-".join(sale_id.split("-")[:2])
        path = SLUGS.get(slug_key)
        if path is None:
            log.warning("tattersalls: unknown sale_id %s", sale_id)
            return
        url = f"{BASE}/{path}/catalogue"
        s = make_session()
        try:
            html = get_text(s, url)
        except Exception as exc:  # noqa: BLE001
            log.warning("tattersalls: fetch %s failed: %s", url, exc)
            return
        soup = BeautifulSoup(html, "lxml")

        rows = soup.select(SELECTORS["lot_row"])
        if not rows:
            log.warning("tattersalls: no lot rows for %s (selectors may need updating)", sale_id)
            return

        for row in rows:
            lot_no = _text(row.select_one(SELECTORS["lot_number"]))
            name = _text(row.select_one(SELECTORS["horse_name"])) or ""
            sire = _text(row.select_one(SELECTORS["sire"]))
            dam = _text(row.select_one(SELECTORS["dam"]))
            consignor = _text(row.select_one(SELECTORS["consignor"]))
            year_text = _text(row.select_one(SELECTORS["year_foaled"]))
            try:
                year_foaled = int(re.sub(r"\D", "", year_text)[-4:]) if year_text else None
            except ValueError:
                year_foaled = None
            price_raw = _text(row.select_one(SELECTORS["price"]))
            price, currency = _parse_money(price_raw)
            withdrawn = bool(row.select_one(SELECTORS["withdrawn"])) or (
                price_raw is not None and "WD" in price_raw.upper()
            )
            link = row.select_one(SELECTORS["lot_link"])
            lot_url = link["href"] if link and link.has_attr("href") else None
            if lot_url and lot_url.startswith("/"):
                lot_url = BASE + lot_url

            yield RawLot(
                sale_id=sale_id,
                lot=lot_no,
                horse_name=name,
                country_bred=_text(row.select_one(SELECTORS["country_bred"])),
                year_foaled=year_foaled,
                sire=sire,
                dam=dam,
                sex=_text(row.select_one(SELECTORS["sex"])),
                consignor=consignor,
                buyer=_text(row.select_one(SELECTORS["buyer"])),
                price=price,
                currency=currency,
                withdrawn=withdrawn,
                source_url=lot_url or url,
            )


__all__ = ["TattersallsScraper"]
