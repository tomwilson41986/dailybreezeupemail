"""Every filly and mare catalogued for a sale in the next ten weeks, worldwide,
through the Sales Catalogues email's house adapters."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from gunrunner.names import display, key, split_suffix
from salescatalogues import db
from salescatalogues.config import load as load_catalogue_settings
from salescatalogues.daily import build_catalogues, collect_raw
from salescatalogues.lots import collect_lots
from salescatalogues.models import Catalogue, Lot

log = logging.getLogger(__name__)

US, EU, AUS = "US", "EU", "AUS"
REGION = {"US": US, "AUS": AUS, "NZ": AUS}
FEMALE = {"F", "M", "FILLY", "MARE", "FILLIES", "JUMENT", "POULICHE", "PF", "STUTE", "BROODMARE"}
# part-shares and breeding rights (the online sales): not a horse to buy
SHARE_TYPES = {"SH", "SB", "RS", "SHARE"}


@dataclass
class Candidate:
    lot_id: str
    sale: str
    house: str
    sale_country: str
    sale_type: str
    sale_date: date | None
    sale_url: str
    lot_no: str
    name: str
    sex: str  # F filly / M mare
    colour: str
    yob: int | None
    sire: str
    dam: str
    damsire: str
    vendor: str
    covering_sire: str
    lot_type: str
    breeding_status: str
    ref: str
    url: str

    @property
    def region(self) -> str:
        return REGION.get(self.sale_country, EU)

    @property
    def age(self) -> int | None:
        if not self.yob:
            return None
        ref = self.sale_date or date.today()
        return ref.year - self.yob

    @property
    def display_name(self) -> str:
        if self.name:
            return display(self.name)
        return f"{display(self.sire)} – {display(self.dam)}"

    @property
    def named(self) -> bool:
        return bool(self.name)


def is_female(sex: str) -> str:
    s = (sex or "").strip().upper()
    if s in FEMALE or s.startswith(("FILL", "MARE", "BROODMARE")):
        return "M" if s.startswith(("M", "BROODMARE")) or s == "JUMENT" else "F"
    return ""


def infer_yob(lot: Lot, cat: Catalogue) -> int | None:
    """The year she was foaled where the house doesn't say: from the lot or sale type."""
    if lot.yob:
        return lot.yob
    start = cat.start_date or date.today()
    t = f"{lot.lot_type} {cat.sale_type} {cat.name}".lower()
    southern = cat.country in ("AUS", "NZ")
    if re.search(r"\bfoal|weanling|\bw\b", t):
        return start.year - (1 if southern and start.month < 8 else 0)
    if "yearling" in t or lot.lot_type.upper() in ("Y", "YRL"):
        return start.year - (2 if southern and start.month < 8 else 1)
    if "breeze" in t or "ready to run" in t or "2yo" in t:
        return start.year - (3 if southern and start.month < 8 else 2)
    return None


def from_lots(catalogues: list[Catalogue], lots_by_id: dict[str, list[Lot]]) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[str] = set()
    for cat in catalogues:
        for lot in lots_by_id.get(cat.catalogue_id, []):
            sex = is_female(lot.sex)
            if not sex or lot.withdrawn or not (lot.sire and lot.dam) or lot.lot_type.upper() in SHARE_TYPES:
                continue
            yob = infer_yob(lot, cat)
            # one horse in two sales: keep the first (the sooner sale)
            ident = f"{key(lot.sire)}|{key(lot.dam)}|{yob or ''}"
            if ident in seen:
                continue
            seen.add(ident)
            out.append(
                Candidate(
                    lot_id=f"{cat.catalogue_id}:{lot.lot_no}",
                    sale=cat.name,
                    house=cat.house,
                    sale_country=cat.country,
                    sale_type=cat.sale_type,
                    sale_date=cat.start_date,
                    sale_url=cat.url,
                    lot_no=lot.lot_no,
                    # some houses print names in capitals: tidied once, here
                    name=display(split_suffix(lot.horse_name)[0]) if lot.horse_name else "",
                    sex=sex,
                    colour=lot.colour,
                    yob=yob,
                    sire=display(lot.sire),
                    dam=display(lot.dam),
                    damsire=display(lot.dam_sire),
                    vendor=display(lot.vendor),
                    covering_sire=display(lot.covering_sire),
                    lot_type=lot.lot_type,
                    breeding_status=lot.breeding_status,
                    ref=lot.ref,
                    url=lot.url or cat.url,
                )
            )
    return out


def collect(
    today: date, *, horizon_days: int, data_dir: Path, session
) -> tuple[list[Candidate], dict]:
    """The sales in range and their fillies and mares."""
    cs = load_catalogue_settings()
    cs.horizon_days = horizon_days
    raws, status = collect_raw(session, today)
    # this job keeps its own seen-ledger, apart from the daily email's
    with db.session(data_dir / "catalogues.sqlite") as conn:
        cats = build_catalogues(raws, conn, today, cs)
    cats.sort(key=lambda c: (c.start_date or date.max, c.house, c.name))
    lots, counts = collect_lots(cats, session)
    cands = from_lots(cats, lots)
    sales = [
        {
            "house": c.house,
            "name": c.name,
            "country": c.country,
            "start": c.start_date,
            "type": c.sale_type,
            "url": c.url,
            "lots": len(lots.get(c.catalogue_id, [])),
            "females": sum(1 for x in cands if x.lot_id.startswith(c.catalogue_id + ":")),
        }
        for c in cats
    ]
    log.info(
        "sales in range: %d, with lots: %d, fillies and mares: %d", len(cats), len(lots), len(cands)
    )
    return cands, {"sales": sales, "sources": status, "lots_by_source": counts}
