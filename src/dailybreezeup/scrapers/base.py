from __future__ import annotations

from typing import Iterable, Protocol

from dailybreezeup.models import RawLot, SaleDescriptor


class Scraper(Protocol):
    vendor: str

    def list_sales(self, years: list[int]) -> list[SaleDescriptor]: ...
    def fetch_lots(self, sale_id: str) -> Iterable[RawLot]: ...
