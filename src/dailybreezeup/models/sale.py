from datetime import date
from typing import Literal

from pydantic import BaseModel

Country = Literal["GB", "IE", "FR"]


class SaleDescriptor(BaseModel):
    id: str
    vendor: str
    name: str
    country: Country
    year: int
    start_date: date | None = None
    source_url: str | None = None


class RawLot(BaseModel):
    sale_id: str
    lot: str | None = None
    horse_name: str = ""
    country_bred: str | None = None
    year_foaled: int | None = None
    sire: str | None = None
    dam: str | None = None
    damsire: str | None = None
    sex: str | None = None
    consignor: str | None = None
    buyer: str | None = None
    price: int | None = None
    currency: str | None = None
    withdrawn: bool = False
    source_url: str | None = None

    # User-provided analytics
    ot_diff_m: str | None = None
    ot_rank: str | None = None
    sl_1f: str | None = None
    sl_go: str | None = None
    breeze_rating: str | None = None
    precocity_rating: str | None = None
    sheet_row_url: str | None = None
