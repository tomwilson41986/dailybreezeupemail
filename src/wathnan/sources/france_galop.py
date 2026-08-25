"""France Galop -- French flat racing.

Two ways in:

* The public day pages (``/fr/courses/aujourdhui`` and ``/fr/courses/demain``)
  list every meeting, and each race page carries the full declaration with the
  ``Propriétaire`` column.  This needs no account and is what runs by default.
* The owner area (the ``/en/owner/<token>`` link) covers the whole entry window
  but sits behind France Galop's single sign-on.  Set ``FRANCE_GALOP_USER`` and
  ``FRANCE_GALOP_PASSWORD`` to enable it; without them the adapter quietly falls
  back to the public pages.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
from collections.abc import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..models import Breed, Race, Runner, Status
from ..normalise import (
    clean_horse_name,
    clean_pedigree_name,
    collapse_space,
    furlongs_from_metres,
    parse_distance,
    parse_time,
    title_course,
    title_name,
    to_uk_time,
)
from .base import Fetcher, FetchError, Source

LOG = logging.getLogger(__name__)

BASE = "https://www.france-galop.com"
PUBLIC_DAY_PAGES = ("/fr/courses/aujourdhui", "/fr/courses/demain")
OWNER_URL = BASE + "/en/owner/{token}"

REUNION_LINK = re.compile(r"/fr/courses/reunion/(\d{8})/([^\"'#?]+)")
COURSE_LINK = re.compile(r"/fr/course/detail/(\d{4})/([A-Z]+)/([^\"'#?]+)")
HEADER_LINE = re.compile(
    r"(?P<number>\d+)\s*(?:ème|ere|er|re)?\s*\((?P<speciality>[A-Z]+)\s*/\s*\d+\)\s*,?\s*"
    r"(?P<category>[^—\-]*)[—\-]\s*(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<time>\d{1,2}h\d{2})\s*,\s*"
    r"(?P<course>.+)")
PEDIGREE = re.compile(r"Par\s*:\s*(?P<sire>.+?)\s+et\s+(?P<dam>.+?)\s*(?:\(|$)", re.I)
#: A supplementary entry is flagged after the name: "URGENCE F.AR. 3 a. ... (Sup.)".
ENTRY_MARKER = re.compile(r"\s*\.{2,}\s*\((?:sup|supp|forfait|f)\.?\)\s*$", re.I)
#: "FIRE BULLET IRE M.PS. 2 a." -- sex, breed code and age trail the horse name.
HORSE_TAIL = re.compile(r"\s+[MFH]\.?(?P<breed>PS|AR|AQPS)\.?\s*\d*\s*a\.?\s*$", re.I)
#: France Galop appends a rider's licensing country: "JAMES WILLIAM DOYLE (GBR)".
RIDER_COUNTRY = re.compile(r"\s*\([A-Za-z]{2,3}\)\s*$")
#: France Galop only prints a country code for foreign-bred horses.
DEFAULT_COUNTRY = "FR"

ARABIAN_SPECIALITIES = {"PA", "A", "AR"}
ARABIAN_HINT = re.compile(r"(pur[- ]sang arabe|arabian|\bP\.?A\.?\b)", re.I)
#: The conditions block opens with the category in bold.
CATEGORY_PATTERNS = (
    (re.compile(r"groupe\s*I{3}\b", re.I), "Group 3"),
    (re.compile(r"groupe\s*I{2}\b", re.I), "Group 2"),
    (re.compile(r"groupe\s*I\b", re.I), "Group 1"),
    (re.compile(r"\blisted\b", re.I), "Listed Race"),
    (re.compile(r"\bhandicap\b", re.I), "Handicap"),
    (re.compile(r"r[ée]clamer", re.I), "Claimer"),
)


class FranceGalopSource(Source):
    name = "france_galop"
    label = "France Galop (France)"
    home = "https://www.france-galop.com/fr/courses/demain"

    def fetch(self, fetcher: Fetcher) -> list[Race]:
        races: list[Race] = []
        seen: set[str] = set()
        for url in self._race_urls(fetcher):
            if url in seen:
                continue
            seen.add(url)
            race = self._race_from_page(fetcher, url)
            if race is not None:
                races.append(race)
        return races

    # -- discovery -------------------------------------------------------------
    def _race_urls(self, fetcher: Fetcher) -> Iterable[str]:
        yield from self._public_race_urls(fetcher)
        yield from self._owner_race_urls(fetcher)

    def _public_race_urls(self, fetcher: Fetcher) -> Iterable[str]:
        for page in PUBLIC_DAY_PAGES:
            try:
                body = fetcher.get(urljoin(BASE, page))
            except FetchError as exc:
                LOG.warning("France Galop %s unavailable: %s", page, exc)
                continue
            for date_text, token in set(REUNION_LINK.findall(body)):
                date = _compact_date(date_text)
                if date is None or not self.config.covers(date):
                    continue
                yield from self._reunion_race_urls(
                    fetcher, f"{BASE}/fr/courses/reunion/{date_text}/{token}")

    def _reunion_race_urls(self, fetcher: Fetcher, url: str) -> Iterable[str]:
        try:
            body = fetcher.get(url)
        except FetchError as exc:
            LOG.warning("France Galop meeting %s unavailable: %s", url, exc)
            return
        for year, speciality, token in set(COURSE_LINK.findall(body)):
            yield f"{BASE}/fr/course/detail/{year}/{speciality}/{token}"

    def _owner_race_urls(self, fetcher: Fetcher) -> Iterable[str]:
        """Follow the owner area when credentials are configured."""
        user = os.environ.get("FRANCE_GALOP_USER")
        password = os.environ.get("FRANCE_GALOP_PASSWORD")
        token = self.config.source_ids.get("france_galop")
        if not (user and password and token):
            return
        try:
            body = self._owner_page(user, password, OWNER_URL.format(token=token))
        except Exception as exc:  # noqa: BLE001 - the public pages still work
            LOG.warning("France Galop owner area unavailable: %s", exc)
            return
        for year, speciality, race_token in set(COURSE_LINK.findall(body)):
            yield f"{BASE}/fr/course/detail/{year}/{speciality}/{race_token}"

    def _owner_page(self, user: str, password: str, url: str) -> str:
        """Sign in through France Galop's SSO and return the owner page HTML."""
        from playwright.sync_api import sync_playwright

        launch: dict = {"args": ["--no-sandbox", *self.config.browser_args]}
        if self.config.browser_proxy:
            launch["proxy"] = {"server": self.config.browser_proxy}
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**launch)
            try:
                page = browser.new_context(locale="en-GB").new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                if "ciamlogin.com" in page.url or "login" in page.url:
                    page.fill("input[type='email'], input[name='loginfmt']", user)
                    page.click("input[type='submit'], button[type='submit']")
                    page.wait_for_timeout(2000)
                    page.fill("input[type='password'], input[name='passwd']", password)
                    page.click("input[type='submit'], button[type='submit']")
                    page.wait_for_load_state("networkidle", timeout=60000)
                    if "ciamlogin.com" in page.url:
                        raise FetchError("France Galop sign-in did not complete")
                    page.goto(url, wait_until="networkidle", timeout=60000)
                return page.content()
            finally:
                browser.close()

    # -- parsing ---------------------------------------------------------------
    def _race_from_page(self, fetcher: Fetcher, url: str) -> Race | None:
        try:
            soup = BeautifulSoup(fetcher.get(url), "lxml")
        except FetchError as exc:
            LOG.warning("France Galop race %s unavailable: %s", url, exc)
            return None

        header = _header(soup)
        if header is None or not self.config.covers(header["date"]):
            return None
        runners, breed_codes = self._wathnan_runners(soup)
        if not runners:
            return None

        name = _text(soup.select_one("h1.page-header")) or _text(soup.select_one("h1"))
        category = header["category"] or _conditions_category(soup)
        arabian = ("AR" in breed_codes
                   or header["speciality"] in ARABIAN_SPECIALITIES
                   or bool(ARABIAN_HINT.search(f"{name} {category}")))
        return Race(
            date=header["date"],
            course=title_course(header["course"]),
            race_type=_race_type(name, category, arabian),
            distance_furlongs=_distance(soup),
            off_time_uk=to_uk_time(header["time"], header["date"], country="FR"),
            breed=Breed.ARABIAN if arabian else Breed.THOROUGHBRED,
            status=Status.DECLARED if _has_declarations(soup) else Status.ENTERED,
            runners=tuple(runners),
            source=self.name,
            source_url=url,
        )

    def _wathnan_runners(self, soup: BeautifulSoup) -> tuple[list[Runner], set[str]]:
        """Return the Wathnan runners plus the breed codes seen against them."""
        runners: list[Runner] = []
        breed_codes: set[str] = set()
        for table in soup.find_all("table"):
            columns = _column_index(table)
            if columns.get("owner") is None or columns.get("horse") is None:
                continue
            for row in table.select("tbody tr"):
                cells = row.find_all("td")
                if len(cells) <= columns["owner"]:
                    continue
                if not self.is_wathnan(_text(cells[columns["owner"]])):
                    continue
                raw_name = ENTRY_MARKER.sub("", _cell(cells, columns["horse"]))
                tail = HORSE_TAIL.search(raw_name)
                if tail:
                    breed_codes.add(tail.group("breed").upper())
                sire, dam = _pedigree(_cell(cells, columns.get("pedigree")))
                runners.append(Runner(
                    horse=_horse_name(HORSE_TAIL.sub("", raw_name)),
                    sire=clean_pedigree_name(sire),
                    dam=clean_pedigree_name(dam),
                    trainer=title_name(_strip_marker(_cell(cells, columns.get("trainer")))),
                    jockey=_rider(_cell(cells, columns.get("jockey"))),
                ))
        return runners, breed_codes


# -- helpers -------------------------------------------------------------------
def _column_index(table: Tag) -> dict[str, int | None]:
    headings = [collapse_space(th.get_text(" ")).lower() for th in table.select("th")]
    def find(*names: str) -> int | None:
        for index, heading in enumerate(headings):
            if any(heading.startswith(name) for name in names):
                return index
        return None
    return {"horse": find("cheval"), "pedigree": find("père", "pere"),
            "owner": find("propriétaire", "proprietaire"),
            "trainer": find("entraineur", "entraîneur"), "jockey": find("jockey")}


def _cell(cells: list[Tag], index: int | None) -> str:
    if index is None or index >= len(cells):
        return ""
    return _text(cells[index])


def _header(soup: BeautifulSoup) -> dict | None:
    """Read ``4ème(P/ 5451), Maiden — 19/08/2026 13h28, VICHY``."""
    container = soup.select_one(".course-detail") or soup
    for paragraph in container.find_all("p"):
        match = HEADER_LINE.search(_text(paragraph))
        if not match:
            continue
        date = _slash_date(match.group("date"))
        if date is None:
            continue
        return {
            "date": date,
            "time": parse_time(match.group("time")),
            "course": collapse_space(match.group("course")).split(",")[0],
            "category": collapse_space(match.group("category")),
            "speciality": match.group("speciality").upper(),
        }
    return None


def _distance(soup: BeautifulSoup) -> float | None:
    container = soup.select_one(".course-detail") or soup
    for strong in container.find_all("strong"):
        match = re.search(r"([\d.]+)\s*m(?:è|e)tres", _text(strong), re.I)
        if match:
            return furlongs_from_metres(float(match.group(1).replace(".", "")))
    return parse_distance(_text(container.find("strong")))


def _has_declarations(soup: BeautifulSoup) -> bool:
    return "partants définitifs" in _text(soup.select_one(".course-detail") or soup).lower()


def _horse_name(name: str) -> str:
    """Add the implicit ``(FR)`` France Galop leaves off home-bred horses."""
    cleaned = clean_horse_name(name)
    if cleaned and not cleaned.endswith(")"):
        return f"{cleaned} ({DEFAULT_COUNTRY})"
    return cleaned


def _conditions_category(soup: BeautifulSoup) -> str:
    """``GROUPE III PA`` opens the conditions paragraph in bold."""
    container = soup.select_one(".course-detail") or soup
    for strong in container.find_all("strong"):
        text = _text(strong)
        if re.search(r"m(?:è|e)tres", text, re.I) or "propriétaire" in text.lower():
            continue
        if re.search(r"groupe|listed|handicap|r[ée]clamer", text, re.I):
            return text
    return ""


def _race_type(name: str, category: str, arabian: bool) -> str:
    """``Prix Nevadour Group 3 PA`` -- the shape used on the circulated report."""
    parts = [collapse_space(name).title() if name.isupper() else collapse_space(name)]
    category = collapse_space(category)
    if category and category.lower() not in parts[0].lower():
        parts.append(_category_label(category))
    if arabian:
        parts.append("PA")
    return " ".join(part for part in parts if part)


def _category_label(category: str) -> str:
    for pattern, label in CATEGORY_PATTERNS:
        if pattern.search(category):
            return label
    return collapse_space(category).title() if category.isupper() else collapse_space(category)


def _pedigree(text: str) -> tuple[str, str]:
    match = PEDIGREE.search(text or "")
    if not match:
        return "", ""
    return collapse_space(match.group("sire")), collapse_space(match.group("dam"))


def _rider(value: str) -> str:
    """``JAMES WILLIAM DOYLE (GBR)`` -- drop the licensing country."""
    return title_name(RIDER_COUNTRY.sub("", collapse_space(value)))


def _strip_marker(value: str) -> str:
    """France Galop suffixes trainers with ``(S)`` for a stable licence."""
    return collapse_space(re.sub(r"\s*\([A-Z]\)\s*$", "", value or ""))


def _slash_date(value: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return None


def _compact_date(value: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _text(node: Tag | None) -> str:
    return collapse_space(node.get_text(" ")) if node is not None else ""
