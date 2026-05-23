"""Racing Post bloodstock sale-catalogue client.

Racing Post publishes a JSON feed for every sale at:

    /bloodstock/sales/catalogues/<venue_uid>/<YYYY-MM-DD>/data.json

Each row in that feed is one catalogued lot with an ``entered`` boolean and,
if entered, an ``entry_details`` object pointing at the race the horse is
declared/entered to run in.  That join is authoritative: RP does the
lot -> horse -> race linking for us, which is why this pipeline uses it
instead of scraping racecards and matching by name.

This module does two things:

* :func:`discover_sales` - fetch the bloodstock catalogues landing page and
  filter to breeze-up sales for the given year (no need to hardcode the
  calendar; RP lists them).
* :func:`fetch_lots` - paginate the data.json for a sale and yield
  :class:`SaleLot` records.

Parsers (``parse_catalogues_index_html``, ``parse_lots_page``) are pure so
tests can run them against captured fixtures.
"""
from __future__ import annotations

import json
import logging
import re
import time as wall
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

BASE = "https://www.racingpost.com"

_SALE_RECORD_RE = re.compile(
    r'"sale_date":"(?P<sale_date>[^"]*)",'
    r'"sale_name":"(?P<sale_name>[^"]*)",'
    r'"sale_co":"(?P<sale_co>[^"]*)",'
    r'"venue_uid":(?P<venue_uid>\d+),'
    r'"is_past":(?P<is_past>true|false),'
    r'"sale_raw_date":"(?P<sale_raw_date>\d{4}-\d{2}-\d{2})",'
    r'"sale_raw_end_date":"(?P<sale_raw_end_date>\d{4}-\d{2}-\d{2})"'
)

# Names that should count as "breeze-up" for our purposes.
_BREEZE_NAME = re.compile(r"breeze.?up", re.IGNORECASE)
# Tattersalls' Guineas Horses-in-Training Sale runs the day after Craven and
# contains the unsold/withdrawn breeze-up 2yos under Tatts' internal
# ``cat/breezeup2/`` catalogue. The sale also contains older HIT lots which
# are not breeze-up grads, so callers filter the fetched lots to age=2 — see
# ``_is_hit_sale``.
_TATTS_GUINEAS_HIT_NAME = re.compile(
    r"tattersalls\s+guineas\b.*\bhorses[\s-]in[\s-]training", re.IGNORECASE
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Header set patterned on a real Chrome 125 navigation, ordered to match what
# the browser sends. RP/Fastly fingerprints by header shape; missing client
# hints or sec-ch-ua values triggers the bot challenge.
_DOC_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "sec-ch-ua": '"Chromium";v="125", "Not:A-Brand";v="24", "Google Chrome";v="125"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Priority": "u=0, i",
    "Cache-Control": "max-age=0",
}
_XHR_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "sec-ch-ua": _DOC_HEADERS["sec-ch-ua"],
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}

# Hardcoded fallback for current-year breeze-up sales. Used only when the
# /bloodstock/sales/catalogues/ index page is blocked and we can't discover
# the list dynamically. Keep these up to date with each year's sale calendar;
# they only need to match the URL path the data.json endpoint expects.
_BREEZE_UP_FALLBACK: dict[int, list[tuple[int, str, str, str, str]]] = {
    2026: [
        (5,  "2026-04-14", "2026-04-15", "Tattersalls Craven Breeze Up Sale 2026",            "Tattersalls"),
        (44, "2026-04-22", "2026-04-22", "Goffs UK 2yo Breeze Up Sale 2026",                  "Goffs UK"),
        (5,  "2026-04-30", "2026-04-30", "Tattersalls Guineas Horses-in-Training Sale 2026",  "Tattersalls"),
        (36, "2026-05-09", "2026-05-09", "Arqana May 2yo Breeze Up 2026",                     "Arqana"),
        (4,  "2026-05-22", "2026-05-22", "Tattersalls Ireland Breeze Up Sale 2026",           "Tattersalls Ireland"),
    ],
}


@dataclass(frozen=True)
class Sale:
    venue_uid: int
    sale_date: date       # first day of the sale (used as the URL key)
    sale_end_date: date
    sale_name: str
    sale_co: str

    @property
    def sale_id(self) -> str:
        return f"rp-{self.venue_uid}-{self.sale_date.isoformat()}"

    @property
    def catalogue_url(self) -> str:
        return f"{BASE}/bloodstock/sales/catalogues/{self.venue_uid}/{self.sale_date.isoformat()}"

    @property
    def data_url(self) -> str:
        return f"{self.catalogue_url}/data.json"


@dataclass(frozen=True)
class EntryDetails:
    course_uid: int
    course_name: str
    race_date: date
    race_uid: int


@dataclass(frozen=True)
class SaleLot:
    sale: Sale
    lot_no: int
    lot_letter: str                 # "" or a suffix like "A"
    horse_uid: int | None           # populated only once RP has a horse record
    horse_name: str                 # "" when unnamed
    sire_uid: int | None
    sire_name: str
    dam_uid: int | None
    dam_name: str
    sire_of_dam_name: str
    sex: str | None                 # 'C', 'F', 'G' etc.
    age: int | None
    year_foaled: int | None         # sale_date.year - age (both 2yos at sale time)
    seller: str
    price_label: str | None
    buyer: str | None
    entered: bool
    entry: EntryDetails | None

    @property
    def lot_id(self) -> str:
        return f"{self.sale.sale_id}-{self.lot_no}{self.lot_letter.strip()}"

    @property
    def display_lot(self) -> str:
        return f"{self.lot_no}{self.lot_letter.strip()}"

    @property
    def display_pedigree(self) -> str:
        return f"{self.sire_name} x {self.dam_name}" if self.sire_name or self.dam_name else ""


# ---------- parsers (pure; take bytes/str, return dataclasses) ----------


def parse_catalogues_index_html(html_text: str) -> list[Sale]:
    """Return every sale record found in the RP catalogues landing page."""
    out: list[Sale] = []
    for m in _SALE_RECORD_RE.finditer(html_text):
        try:
            out.append(
                Sale(
                    venue_uid=int(m["venue_uid"]),
                    sale_date=date.fromisoformat(m["sale_raw_date"]),
                    sale_end_date=date.fromisoformat(m["sale_raw_end_date"]),
                    sale_name=m["sale_name"],
                    sale_co=m["sale_co"],
                )
            )
        except ValueError:
            continue
    return out


def filter_breeze_ups(sales: Iterable[Sale], year: int) -> list[Sale]:
    """Keep sales worth scraping for breeze-up graduates in ``year``.

    Matches dedicated breeze-up sales by name, plus the Tattersalls Guineas
    Horses-in-Training Sale (which carries the unsold-at-Craven 2yos under
    Tatts' internal ``breezeup2`` catalogue). The Guineas HIT also contains
    older HIT lots; ``fetch_lots`` filters those out via ``_is_hit_sale``.
    """
    return [
        s for s in sales
        if s.sale_date.year == year
        and (_BREEZE_NAME.search(s.sale_name) or _TATTS_GUINEAS_HIT_NAME.search(s.sale_name))
    ]


def _is_hit_sale(sale: Sale) -> bool:
    """True for HIT/mixed sales where only the 2yo subset is breeze-up grads."""
    return bool(_TATTS_GUINEAS_HIT_NAME.search(sale.sale_name))


def _coerce_entry(raw: Any) -> EntryDetails | None:
    if not isinstance(raw, dict):
        return None
    try:
        return EntryDetails(
            course_uid=int(raw["course_uid"]),
            course_name=str(raw.get("course_name") or ""),
            race_date=date.fromisoformat(str(raw["race_date"])),
            race_uid=int(raw["race_uid"]),
        )
    except (KeyError, ValueError, TypeError):
        return None


def _as_int(x: Any) -> int | None:
    try:
        return int(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def parse_lots_page(body: str, sale: Sale) -> tuple[list[SaleLot], int, int]:
    """Return ``(lots, current_page, total_pages)`` from one data.json response."""
    payload = json.loads(body)
    rows = payload.get("rows") or []
    pagination = payload.get("pagination") or {}
    current_page = int(pagination.get("currentPage") or 1)
    total_pages = int(pagination.get("totalPages") or 1)

    lots: list[SaleLot] = []
    for row in rows:
        age = _as_int(row.get("horse_age"))
        lot_no = _as_int(row.get("lot_no"))
        if lot_no is None:
            continue
        horse_name = (row.get("horse_style_name") or "").strip()
        # RP uses "00<dam-name>" as an internal sort key for unnamed horses.
        # Strip it so downstream display code gets an empty string instead
        # of rendering a misleading pseudo-name.
        if horse_name.lower().startswith("00"):
            horse_name = ""
        lots.append(
            SaleLot(
                sale=sale,
                lot_no=lot_no,
                lot_letter=(row.get("lot_letter") or "").strip(),
                horse_uid=_as_int(row.get("horse_uid")),
                horse_name=horse_name,
                sire_uid=_as_int(row.get("sire_uid")),
                sire_name=(row.get("sire_style_name") or "").strip(),
                dam_uid=_as_int(row.get("dam_uid")),
                dam_name=(row.get("dam_style_name") or "").strip(),
                sire_of_dam_name=(row.get("sire_of_dam_style_name") or "").strip(),
                sex=(row.get("horse_sex") or None),
                age=age,
                year_foaled=(sale.sale_date.year - age) if age is not None else None,
                seller=(row.get("seller_name") or "").strip(),
                price_label=(row.get("price_styled_long") or None),
                buyer=(row.get("buyer_detail") or None),
                entered=bool(row.get("entered")),
                entry=_coerce_entry(row.get("entry_details")),
            )
        )
    return lots, current_page, total_pages


# ---------- live fetchers ----------


def _make_session():
    """Build the HTTP session.

    Uses curl_cffi when available so the TLS/HTTP-2 fingerprint matches a
    real Chrome - essential for getting past Racing Post's Fastly bot
    challenge from cloud IPs (GitHub Actions, AWS, etc.). Falls back to
    plain requests if curl_cffi isn't importable for any reason; on a
    home/laptop IP that path normally still works.
    """
    try:
        from curl_cffi import requests as cffi_requests
        s = cffi_requests.Session(impersonate="chrome124")
    except ImportError:
        log.warning("curl_cffi not available; falling back to plain requests")
        s = requests.Session()
    s.headers.update(_DOC_HEADERS)
    return s


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def _get(session: requests.Session, url: str, headers: dict[str, str]) -> requests.Response:
    r = session.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r


def _fallback_sales(year: int) -> list[Sale]:
    """Return the hardcoded breeze-up sale list for ``year`` if known, else []."""
    rows = _BREEZE_UP_FALLBACK.get(year)
    if not rows:
        return []
    out: list[Sale] = []
    for venue_uid, raw_start, raw_end, name, co in rows:
        try:
            out.append(
                Sale(
                    venue_uid=venue_uid,
                    sale_date=date.fromisoformat(raw_start),
                    sale_end_date=date.fromisoformat(raw_end),
                    sale_name=name,
                    sale_co=co,
                )
            )
        except ValueError:
            continue
    return out


def _warm_up(s: requests.Session) -> None:
    """Walk a real Chrome navigation: home -> bloodstock. Each call swallows
    failures so a 503 on warm-up doesn't kill the job; the discover call
    will report any final failure itself."""
    for url, ref in (
        (f"{BASE}/", None),
        (f"{BASE}/bloodstock/", f"{BASE}/"),
    ):
        try:
            hdrs = dict(_DOC_HEADERS)
            if ref:
                hdrs["Referer"] = ref
                hdrs["Sec-Fetch-Site"] = "same-origin"
            s.get(url, headers=hdrs, timeout=20)
        except Exception as exc:  # noqa: BLE001
            log.debug("warm-up GET %s failed: %s", url, exc)
        wall.sleep(1.4)


def discover_sales(
    year: int,
    *,
    session: requests.Session | None = None,
) -> list[Sale]:
    """Fetch the catalogues landing page and return this year's breeze-up sales.

    Falls back to a hardcoded list of known sales (see ``_BREEZE_UP_FALLBACK``)
    when the index page is blocked. Returns [] only if both paths fail.
    """
    s = session or _make_session()
    _warm_up(s)
    try:
        r = _get(
            s,
            f"{BASE}/bloodstock/sales/catalogues/",
            headers=dict(
                _DOC_HEADERS,
                Referer=f"{BASE}/bloodstock/",
                **{"Sec-Fetch-Site": "same-origin"},
            ),
        )
        sales = filter_breeze_ups(parse_catalogues_index_html(r.text), year)
        if sales:
            return sales
        log.warning("RP catalogues index returned 0 breeze-up sales for %d; using fallback", year)
    except Exception as exc:  # noqa: BLE001
        log.warning("RP catalogues index fetch failed (%s); using fallback", exc)
    return _fallback_sales(year)


def demo_lots() -> list[SaleLot]:
    """Return the four real Craven 2026 lots that were flagged ``entered`` in
    Racing Post's catalogue at the time of capture.  Used by ``--demo`` to
    exercise the rendering and email pipeline without making any live RP
    requests (handy when the runner IP is bot-blocked)."""
    sale = Sale(
        venue_uid=5,
        sale_date=date(2026, 4, 14),
        sale_end_date=date(2026, 4, 15),
        sale_name="Tattersalls Craven Breeze Up Sale 2026",
        sale_co="Tattersalls",
    )
    common = dict(
        sale=sale,
        lot_letter="",
        horse_name="",
        age=2,
        year_foaled=2024,
        entered=True,
    )
    return [
        SaleLot(
            **common,
            lot_no=16,
            horse_uid=8688568,
            sire_uid=3095735, sire_name="Havana Grey",
            dam_uid=5746537, dam_name="Hot Secret",
            sire_of_dam_name="Sakhee's Secret",
            sex="F",
            seller="From Yeomanstown Stud, Ireland",
            price_label="GBG 350,000",
            buyer="Stroud Coleman Bloodstock",
            entry=EntryDetails(
                course_uid=38, course_name="NEWMARKET",
                race_date=date(2026, 10, 3), race_uid=910567,
            ),
        ),
        SaleLot(
            **common,
            lot_no=65,
            horse_uid=8688838,
            sire_uid=None, sire_name="Cotai Glory",
            dam_uid=None, dam_name="Oatmeal",
            sire_of_dam_name="Dalakhani",
            sex="C",
            seller="From Davis Bloodstock, Ireland",
            price_label=None,
            buyer="Withdrawn",
            entry=EntryDetails(
                course_uid=107, course_name="YORK",
                race_date=date(2026, 8, 20), race_uid=910568,
            ),
        ),
        SaleLot(
            **common,
            lot_no=73,
            horse_uid=8688656,
            sire_uid=None, sire_name="Blackbeard",
            dam_uid=None, dam_name="Pearl Chavez",
            sire_of_dam_name="Postponed",
            sex="F",
            seller="",
            price_label=None,
            buyer="Not Sold",
            entry=EntryDetails(
                course_uid=38, course_name="NEWMARKET",
                race_date=date(2026, 10, 3), race_uid=910567,
            ),
        ),
        SaleLot(
            **common,
            lot_no=178,
            horse_uid=None,
            sire_uid=None, sire_name="Harry Angel",
            dam_uid=None, dam_name="El Hadeeyah",
            sire_of_dam_name="",
            sex=None,
            seller="",
            price_label=None,
            buyer="Vendor",
            entry=EntryDetails(
                course_uid=15, course_name="DONCASTER",
                race_date=date(2026, 9, 10), race_uid=912529,
            ),
        ),
    ]


def fetch_lots(sale: Sale, *, session: requests.Session | None = None, sleep: float = 0.8) -> list[SaleLot]:
    """Paginate the data.json for a sale and return every relevant lot.

    For HIT sales (see :func:`_is_hit_sale`) only age-2 lots are kept — those
    are the breeze-up portion; the older HIT lots aren't graduates.
    """
    s = session or _make_session()
    # Warm-up: hit the HTML page first so the session carries the right cookies.
    try:
        s.get(sale.catalogue_url, headers=dict(_DOC_HEADERS, Referer=f"{BASE}/bloodstock/sales/catalogues/"),
              timeout=20)
    except Exception as exc:  # noqa: BLE001
        log.debug("warm-up GET %s failed: %s", sale.catalogue_url, exc)

    xhr = dict(_XHR_HEADERS, Referer=sale.catalogue_url)
    out: list[SaleLot] = []
    page = 1
    while True:
        url = sale.data_url + (f"?page={page}" if page > 1 else "")
        try:
            r = _get(s, url, headers=xhr)
        except Exception as exc:  # noqa: BLE001
            log.warning("RP sale data fetch failed (%s): %s", url, exc)
            break
        if "json" not in (r.headers.get("content-type") or ""):
            log.warning("RP sale returned non-JSON (%s, status=%s)", url, r.status_code)
            break
        lots, current, total = parse_lots_page(r.text, sale)
        out.extend(lots)
        if current >= total:
            break
        page = current + 1
        wall.sleep(sleep)
    if _is_hit_sale(sale):
        before = len(out)
        out = [lot for lot in out if lot.age == 2]
        log.info("  %s: HIT sale, kept %d/%d age-2 lots", sale.sale_name, len(out), before)
    return out
