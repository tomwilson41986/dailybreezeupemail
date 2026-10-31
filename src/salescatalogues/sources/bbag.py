"""BBAG (Baden-Baden, Germany).

The English events page lists each sale as an ``h3.caption`` followed (further
down the DOM, not as a direct sibling) by paragraphs of detail. We walk the
document in order, attach each paragraph to the current sale, and take the
first paragraph carrying a month + year as the headline sale date.
"""
from __future__ import annotations

import logging
import re
from datetime import date

import lxml.html

from salescatalogues.models import Lot, RawSale
from salescatalogues.sources.base import get_json, get_text, make_session, parse_date_range, squash

log = logging.getLogger(__name__)

URL = "https://bbag-sales.de/events2026~en_GB"
# BBAG catalogues run on the 3forONE platform's open JSON API.
LOTS_API = (
    "https://backend.3forone.auction/api/v1/bbag-auction/auction/{slug}/auctionlots"
)
# Every auction on the platform, with its slug ("bbag-august-online-sale-2026")
AUCTIONS_API = "https://backend.3forone.auction/api/v1/bbag-auction/auction/"
# Online lots are named "01 - Aktivist"
_LOT_PREFIX_RE = re.compile(r"^\d+\s*-\s*")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

_DATEY_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*.*?20\d{2}", re.IGNORECASE
)


def parse_events(html: str, *, ref: date) -> list[RawSale]:
    doc = lxml.html.fromstring(html)
    sales: list[tuple[str, list[str]]] = []
    cur: list[str] | None = None
    for el in doc.iter():
        cls = el.get("class") or ""
        if el.tag == "h3" and "caption" in cls:
            name = squash(el.text_content())
            if name and "winner" not in name.lower():
                cur = []
                sales.append((name, cur))
            else:
                cur = None
        elif el.tag == "p" and cur is not None:
            txt = squash(el.text_content())
            if txt:
                cur.append(txt)

    out: list[RawSale] = []
    for name, lines in sales:
        date_line = next((ln for ln in lines if _DATEY_RE.search(ln)), "")
        start, end = parse_date_range(date_line, ref, dayfirst=True)
        out.append(
            RawSale(
                house="BBAG",
                country="DE",
                name=name.title(),
                start_date=start,
                end_date=end,
                url=URL,
                online="online" in name.lower(),
                description=date_line,
            )
        )
    return out


def fetch(session=None, *, ref: date | None = None) -> list[RawSale]:
    session = session or make_session()
    ref = ref or date.today()
    try:
        html = get_text(session, URL)
    except Exception as exc:  # noqa: BLE001
        log.warning("BBAG fetch failed: %s", exc)
        return []
    return parse_events(html, ref=ref)


def parse_lots(rows: list) -> list[Lot]:
    lots: list[Lot] = []
    for lot in rows or []:
        if not isinstance(lot, dict):
            continue
        rel = lot.get("rel") or {}
        ped = rel.get("pedigree") or {}
        year = _YEAR_RE.search(rel.get("birthday") or "")
        lots.append(
            Lot(
                lot_no=str(lot.get("number") or "").strip(),
                horse_name=_LOT_PREFIX_RE.sub("", (rel.get("name") or "").strip()),
                sex=(rel.get("sex") or "").strip(),
                colour=(rel.get("color") or "").strip().title(),
                sire=(ped.get("v") or "").strip(),
                dam=(ped.get("m") or "").strip(),
                dam_sire=(ped.get("mv") or "").strip(),
                vendor=(lot.get("vendor") or "").strip(),
                yob=int(year.group(0)) if year else None,
                covering_sire=(lot.get("inFoalTo") or "").strip(),
            )
        )
    return lots


def _words(name: str) -> set[str]:
    """A sale name's words, for matching: "Christmas Online-Sale 2026" and
    "BBAG CHRISTMAS ONLINE-SALE 2026" agree."""
    return set(re.findall(r"[a-z0-9]+", name.lower())) - {"bbag", "sale", "auction"}


def find_slug(auctions: list, name: str) -> str:
    """The platform's slug for a calendar sale, by its name's words; one name may
    carry a word the other lacks ("Hit Spring Sale 2026 Online")."""
    want = _words(name)
    for a in auctions or []:
        if not (isinstance(a, dict) and a.get("slug")):
            continue
        have = _words(a.get("name") or "")
        if have and (have <= want or want <= have):
            return a["slug"]
    return ""


def _candidate_slugs(name: str, year: int | None) -> list[str]:
    """Best-effort 3forONE auction slugs for a BBAG sale. BBAG names its
    catalogues e.g. "bbag-spring-auction-2026-online"; we slugify the sale name
    (mapping "sale" -> "auction") and try a couple of variants."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    base = base.replace("-sale", "-auction").replace("sales", "auction")
    yr = f"-{year}" if year else ""
    cands = [f"bbag-{base}", f"bbag-{base}{yr}", base]
    out: list[str] = []
    for c in cands:
        c = re.sub(r"-{2,}", "-", c).strip("-")
        if c not in out:
            out.append(c)
    return out


def fetch_lots(raw: RawSale, session=None) -> list[Lot]:
    """The sale's slug from the platform's auction list, matched by name; failing
    that, a few slug guesses against the open lots API. Returns [] if none
    resolve (the CSV falls back to a summary row; an online sale is listed once
    its catalogue is up)."""
    session = session or make_session()
    year = raw.start_date.year if raw.start_date else None
    try:
        listed = find_slug(get_json(session, AUCTIONS_API), raw.name)
    except Exception as exc:  # noqa: BLE001
        log.info("BBAG auction list unavailable: %s", exc)
        listed = ""
    for slug in ([listed] if listed else []) + _candidate_slugs(raw.name, year):
        try:
            rows = get_json(session, LOTS_API.format(slug=slug))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(rows, list) and rows:
            return parse_lots(rows)
    return []
