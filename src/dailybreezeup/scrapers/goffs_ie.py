"""Goffs Ireland catalogue scraper (Kildare).

Covers:
  - Goffs Breeze Up Sale (April/May, Kildare)

URL pattern: https://www.goffs.com/sale/IRE/breeze-up-sale-<year>

SELECTORS ARE UNVERIFIED: iterate locally if lot counts are 0.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from bs4 import BeautifulSoup

from dailybreezeup.models import RawLot, SaleDescriptor
from dailybreezeup.racing.common import get_text, make_session

log = logging.getLogger(__name__)

BASE = "https://www.goffs.com"
SALE_PATH_TEMPLATE = "/sale/IRE/breeze-up-sale-{year}"

SELECTORS = {
    "lot_row": "div.catalogue-lot, li.lot, tr.lot-row",
    "lot_number": ".lot-number, .lot-no, td.lot",
    "horse_name": ".horse-name, .name",
    "sire": ".sire",
    "dam": ".dam",
    "consignor": ".consignor, .vendor",
    "sex": ".sex",
    "year_foaled": ".foaled, .year",
    "country_bred": ".country",
    "buyer": ".buyer, .purchaser",
    "price": ".price, .sold-for",
    "withdrawn": ".withdrawn, .wd",
    "lot_link": "a",
}

_MONEY = re.compile(r"[£€]?\s*([0-9][0-9,]*)")


def _parse_money(raw: str | None) -> tuple[int | None, str | None]:
    if not raw:
        return None, None
    currency = "EUR" if "€" in raw else ("GBP" if "£" in raw else "EUR")
    m = _MONEY.search(raw)
    return (int(m.group(1).replace(",", "")), currency) if m else (None, currency)


def _text(node) -> str | None:  # noqa: ANN001
    return node.get_text(" ", strip=True) if node else None


class GoffsIEScraper:
    vendor = "goffs-ie"

    def list_sales(self, years: list[int]) -> list[SaleDescriptor]:
        return [
            SaleDescriptor(
                id=f"goffs-ie-breezeup-{y}",
                vendor=self.vendor,
                name="Goffs Breeze Up Sale",
                country="IE",
                year=y,
                source_url=BASE + SALE_PATH_TEMPLATE.format(year=y),
            )
            for y in years
        ]

    def fetch_lots(self, sale_id: str) -> Iterable[RawLot]:
        year = int(sale_id.rsplit("-", 1)[-1])
        url = BASE + SALE_PATH_TEMPLATE.format(year=year) + "/catalogue"
        s = make_session()
        try:
            html = get_text(s, url)
        except Exception as exc:  # noqa: BLE001
            log.warning("goffs-ie: fetch %s failed: %s", url, exc)
            return

        soup = BeautifulSoup(html, "lxml")
        rows = soup.select(SELECTORS["lot_row"])
        if not rows:
            log.warning("goffs-ie: no lot rows for %s (selectors may need updating)", sale_id)
            return

        for row in rows:
            price_raw = _text(row.select_one(SELECTORS["price"]))
            price, currency = _parse_money(price_raw)
            year_text = _text(row.select_one(SELECTORS["year_foaled"]))
            try:
                year_foaled = int(re.sub(r"\D", "", year_text)[-4:]) if year_text else None
            except ValueError:
                year_foaled = None
            link = row.select_one(SELECTORS["lot_link"])
            lot_url = link["href"] if link and link.has_attr("href") else None
            if lot_url and lot_url.startswith("/"):
                lot_url = BASE + lot_url

            yield RawLot(
                sale_id=sale_id,
                lot=_text(row.select_one(SELECTORS["lot_number"])),
                horse_name=_text(row.select_one(SELECTORS["horse_name"])) or "",
                country_bred=_text(row.select_one(SELECTORS["country_bred"])),
                year_foaled=year_foaled,
                sire=_text(row.select_one(SELECTORS["sire"])),
                dam=_text(row.select_one(SELECTORS["dam"])),
                sex=_text(row.select_one(SELECTORS["sex"])),
                consignor=_text(row.select_one(SELECTORS["consignor"])),
                buyer=_text(row.select_one(SELECTORS["buyer"])),
                price=price,
                currency=currency or "EUR",
                withdrawn=bool(row.select_one(SELECTORS["withdrawn"])),
                source_url=lot_url or url,
            )


__all__ = ["GoffsIEScraper"]
