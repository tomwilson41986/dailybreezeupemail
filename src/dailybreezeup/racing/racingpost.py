"""Racing Post scraper for GB/IRE racecards, entries and results.

Two-step scrape per category:
  1. GET /racecards/<YYYY-MM-DD>  or  /results/<YYYY-MM-DD>  -> list of per-race URLs
  2. GET each per-race page -> extract runners

Parsers are pure (HTML str -> dataclass) so they can be exercised against
fixtures in tests without network I/O.

Only GB + IRE courses (slugs in the hardcoded sets below) are followed; other
countries are skipped. France is covered separately by `francegalop.py`.
"""
from __future__ import annotations

import logging
import re
import time as wall
from dataclasses import dataclass
from datetime import date, time
from typing import Optional

import requests
from lxml import html as lxml_html
from tenacity import retry, stop_after_attempt, wait_exponential

from dailybreezeup.models import RaceCard, RaceResult, Runner

log = logging.getLogger(__name__)

BASE = "https://www.racingpost.com"
DEFAULT_REGIONS: tuple[str, ...] = ("GB", "IE")

# Racing Post course slugs for GB + Ireland. Any slug not in these sets is
# skipped by the index parser. Extend if RP adds a new track.
_GB_COURSES = {
    "aintree", "ascot", "ayr", "bangor", "bangor-on-dee", "bath", "beverley",
    "brighton", "carlisle", "cartmel", "catterick", "chelmsford",
    "chelmsford-city", "cheltenham", "chepstow", "chester", "doncaster",
    "epsom", "epsom-downs", "exeter", "fakenham", "ffos-las", "fontwell",
    "goodwood", "hamilton", "haydock", "hereford", "hexham", "huntingdon",
    "kelso", "kempton", "leicester", "lingfield", "ludlow", "market-rasen",
    "musselburgh", "newbury", "newcastle", "newmarket", "newton-abbot",
    "nottingham", "perth", "plumpton", "pontefract", "redcar", "ripon",
    "salisbury", "sandown", "sedgefield", "southwell", "stratford", "taunton",
    "thirsk", "towcester", "uttoxeter", "warwick", "wetherby", "wincanton",
    "windsor", "wolverhampton", "worcester", "yarmouth", "york",
}
_IRE_COURSES = {
    "ballinrobe", "bellewstown", "clonmel", "cork", "curragh", "downpatrick",
    "down-royal", "dundalk", "fairyhouse", "galway", "gowran-park",
    "kilbeggan", "killarney", "laytown", "leopardstown", "limerick",
    "listowel", "naas", "navan", "punchestown", "roscommon", "sligo",
    "thurles", "tipperary", "tramore", "wexford",
}

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_RACE_PATH = re.compile(r"^/racecards/(\d+)/([a-z][a-z0-9-]*)/(\d{4}-\d{2}-\d{2})/(\d+)$")
_RESULT_PATH = re.compile(r"^/results/(\d+)/([a-z][a-z0-9-]*)/(\d{4}-\d{2}-\d{2})/(\d+)$")
_TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})")
_COUNTRY_SUFFIX_RE = re.compile(r"\s*\(([A-Z]{2,3})\)\s*$")


@dataclass(frozen=True)
class _RaceMeta:
    race_id: str
    race_url: str
    course: str
    course_slug: str
    country: str
    race_date: date


def _country_for_slug(slug: str) -> Optional[str]:
    if slug in _GB_COURSES:
        return "GB"
    if slug in _IRE_COURSES:
        return "IE"
    return None


def _course_display(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.split("-"))


def _parse_off_time(title: str) -> time | None:
    """Racing Post titles embed the off-time: '3:00 Sandown | ...' or
    'Full Result 1.52 Beverley | ...'. Returns None if not parseable."""
    m = _TIME_RE.search(title)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    if 1 <= hh <= 10:
        hh += 12
    return time(hh, mm)


def _text(el) -> str:
    return " ".join(el.text_content().split())


def _first_text(doc, xpath: str) -> str | None:
    nodes = doc.xpath(xpath)
    if not nodes:
        return None
    t = _text(nodes[0])
    return t or None


def _strip_country_suffix(name: str | None) -> tuple[str | None, str | None]:
    """'Muhaarar (GB)' -> ('Muhaarar', 'GB'). Returns (name, country) or (name, None)."""
    if not name:
        return None, None
    m = _COUNTRY_SUFFIX_RE.search(name)
    if not m:
        return name.strip() or None, None
    return _COUNTRY_SUFFIX_RE.sub("", name).strip() or None, m.group(1)


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_BROWSER_HEADERS)
    return s


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def _fetch(session: requests.Session, url: str) -> str:
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def _index_metas(
    html_text: str,
    on: date,
    regions: tuple[str, ...],
    *,
    path_re: re.Pattern[str],
    url_prefix: str,
) -> list[_RaceMeta]:
    doc = lxml_html.fromstring(html_text)
    out: dict[str, _RaceMeta] = {}
    for href in doc.xpath("//a/@href"):
        clean = href.split("#", 1)[0]
        m = path_re.match(clean)
        if not m:
            continue
        _cid, slug, d_str, race_id = m.groups()
        if d_str != on.isoformat():
            continue
        country = _country_for_slug(slug)
        if country is None or country not in regions:
            continue
        if race_id in out:
            continue
        out[race_id] = _RaceMeta(
            race_id=race_id,
            race_url=f"{BASE}{clean}",
            course=_course_display(slug),
            course_slug=slug,
            country=country,
            race_date=on,
        )
    return list(out.values())


def parse_racecards_index(
    html_text: str, on: date, regions: tuple[str, ...] = DEFAULT_REGIONS
) -> list[_RaceMeta]:
    return _index_metas(html_text, on, regions, path_re=_RACE_PATH, url_prefix="/racecards/")


def parse_results_index(
    html_text: str, on: date, regions: tuple[str, ...] = DEFAULT_REGIONS
) -> list[_RaceMeta]:
    return _index_metas(html_text, on, regions, path_re=_RESULT_PATH, url_prefix="/results/")


def parse_racecard_page(html_text: str, meta: _RaceMeta) -> RaceCard:
    doc = lxml_html.fromstring(html_text)
    title_nodes = doc.xpath("//title/text()")
    off_time = _parse_off_time(title_nodes[0]) if title_nodes else None
    race_name = _first_text(doc, '//*[@data-test-selector="RC-header__raceInstanceTitle"]') or ""

    runners: list[Runner] = []
    rows = doc.xpath(
        '//div[contains(concat(" ", normalize-space(@class), " "), " js-RC-runnerRow ") '
        'and not(contains(@class, "Wrapper"))]'
    )
    for row in rows:
        def sel(name: str) -> str | None:
            return _first_text(row, f'.//*[@data-test-selector="{name}"]')

        name = sel("RC-cardPage-runnerName")
        if not name:
            continue
        age_raw = sel("RC-cardPage-runnerAge")
        try:
            age = int(age_raw) if age_raw else None
        except ValueError:
            age = None
        draw_raw = sel("RC-cardPage-runnerNumber-draw")
        draw = re.sub(r"[^\d]", "", draw_raw) if draw_raw else None
        sire, sire_country = _strip_country_suffix(sel("RC-pedigree__sire"))
        dam, _ = _strip_country_suffix(sel("RC-pedigree__dam"))
        sex_color = sel("RC-pedigree__color-sex")
        sex = sex_color.split()[-1] if sex_color else None

        runners.append(
            Runner(
                horse=name,
                age=age,
                sex=sex,
                trainer=sel("RC-cardPage-runnerTrainer-name"),
                jockey=sel("RC-cardPage-runnerJockey-name"),
                owner=sel("RC-cardPage-runnerOwner-name"),
                draw=draw or None,
                number=sel("RC-cardPage-runnerNumber-no"),
                weight=sel("RC-cardPage-runnerWgt-carried"),
                form=sel("RC-cardPage-runnerForm"),
                sire=sire,
                dam=dam,
                bred=sire_country,
            )
        )

    return RaceCard(
        race_id=meta.race_id,
        country=meta.country,  # type: ignore[arg-type]
        course=meta.course,
        race_date=meta.race_date,
        off_time=off_time,
        race_name=race_name,
        runners=runners,
        url=meta.race_url,
    )


def parse_result_page(html_text: str, meta: _RaceMeta) -> RaceResult:
    doc = lxml_html.fromstring(html_text)
    title_nodes = doc.xpath("//title/text()")
    off_time = _parse_off_time(title_nodes[0]) if title_nodes else None
    race_name = _first_text(doc, '//*[contains(@class,"rp-raceTimeCourseName__title")]') or ""

    runners: list[Runner] = []
    for row in doc.xpath('//tr[contains(@class,"rp-horseTable__mainRow")]'):
        name = _first_text(row, './/*[contains(@class,"rp-horseTable__horse__name")]')
        if not name:
            continue

        pos_raw = _first_text(row, './/*[contains(@class,"rp-horseTable__pos__number")]')
        position = pos_raw.split()[0] if pos_raw else None
        draw_raw = _first_text(row, './/*[contains(@class,"rp-horseTable__pos__draw")]')
        draw = re.sub(r"[^\d]", "", draw_raw) if draw_raw else None
        age_raw = _first_text(row, './/*[contains(@class,"rp-horseTable__spanNarrow_age")]')
        try:
            age = int(age_raw) if age_raw else None
        except ValueError:
            age = None
        price = _first_text(row, './/*[contains(@class,"rp-horseTable__horse__price")]')
        country_tag = _first_text(row, './/*[contains(@class,"rp-horseTable__horse__country")]')
        bred = country_tag.strip("()") if country_tag else None
        saddle = _first_text(row, './/*[contains(@class,"rp-horseTable__saddleClothNo")]')

        people = [
            _text(h)
            for h in row.xpath('.//*[contains(@class,"rp-horseTable__human__wrapper")]')
        ]
        people = [p for p in people if p]
        # Row order: jockey first, trainer second.
        jockey = people[0] if len(people) >= 1 else None
        trainer = people[1] if len(people) >= 2 else None

        runners.append(
            Runner(
                horse=name,
                age=age,
                trainer=trainer,
                jockey=jockey,
                draw=draw or None,
                number=saddle,
                bred=bred,
                finishing_position=position,
                sp=price,
            )
        )

    return RaceResult(
        race_id=meta.race_id,
        country=meta.country,  # type: ignore[arg-type]
        course=meta.course,
        race_date=meta.race_date,
        off_time=off_time,
        race_name=race_name,
        runners=runners,
        url=meta.race_url,
    )


def _collect(
    index_url: str,
    on: date,
    regions: tuple[str, ...],
    *,
    is_results: bool,
    sleep: float,
) -> list[RaceCard] | list[RaceResult]:
    s = _make_session()
    try:
        index_html = _fetch(s, index_url)
    except Exception as exc:  # noqa: BLE001
        log.warning("Racing Post index fetch failed (%s): %s", index_url, exc)
        return []

    metas = (
        parse_results_index(index_html, on, regions)
        if is_results
        else parse_racecards_index(index_html, on, regions)
    )
    if not metas:
        log.info("Racing Post %s: no %s meetings on %s", index_url, regions, on)
        return []

    collected: list = []
    for i, meta in enumerate(metas):
        if i:
            wall.sleep(sleep)
        try:
            page = _fetch(s, meta.race_url)
        except Exception as exc:  # noqa: BLE001
            log.warning("Racing Post race fetch failed (%s): %s", meta.race_url, exc)
            continue
        try:
            collected.append(
                parse_result_page(page, meta) if is_results else parse_racecard_page(page, meta)
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Racing Post parse failed (%s): %s", meta.race_url, exc)
    return collected


def fetch_declarations(
    on: date, regions: tuple[str, ...] = DEFAULT_REGIONS, *, sleep: float = 1.2
) -> list[RaceCard]:
    return _collect(
        f"{BASE}/racecards/{on.isoformat()}", on, regions, is_results=False, sleep=sleep
    )


def fetch_entries(
    on: date, regions: tuple[str, ...] = DEFAULT_REGIONS, *, sleep: float = 1.2
) -> list[RaceCard]:
    # Racing Post serves both "entries" and "declarations" off the same URL;
    # pages further out just have fewer runner fields populated.
    return _collect(
        f"{BASE}/racecards/{on.isoformat()}", on, regions, is_results=False, sleep=sleep
    )


def fetch_results(
    on: date, regions: tuple[str, ...] = DEFAULT_REGIONS, *, sleep: float = 1.2
) -> list[RaceResult]:
    return _collect(
        f"{BASE}/results/{on.isoformat()}", on, regions, is_results=True, sleep=sleep
    )
