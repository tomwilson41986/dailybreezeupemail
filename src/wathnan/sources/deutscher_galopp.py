"""Deutscher Galopp -- German flat racing.

The public race calendar embeds every fixture for the next fortnight, so one
request gives us the race list; each race page is then checked for a Wathnan
owned runner.  Owner, trainer, jockey and pedigree all come from the entry
table (``#nennungen``) or the declared runner table (``#starter``).
"""

from __future__ import annotations

import datetime as dt
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
    parse_time,
    title_course,
    title_name,
    to_uk_time,
)
from .base import Fetcher, Source

BASE = "https://www.deutscher-galopp.de"
CALENDAR = f"{BASE}/gr/renntage/rennkalender.php"

GERMAN_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
RACE_LINK = re.compile(r"/gr/renntage/rennen\.php\?id=(\d+)&(?:amp;)?d=(\d{8})")
PEDIGREE = re.compile(r"Abstammung:\s*v\.?\s*(.+?)\s+-\s+(.+?)(?:<br\s*/?>|$)", re.I)
#: Deutscher Galopp only prints a country code for foreign-bred horses.
DEFAULT_COUNTRY = "GER"
#: "Am." marks an amateur rider, "Azb." an apprentice.
RIDER_PREFIX = re.compile(r"^(am|azb|azubi|lehrl)\.\s*", re.I)
DISTANCE = re.compile(r"([\d.]+)\s*m\b")

#: German race categories mapped to the wording the report uses.
CATEGORY_LABELS = {
    "gruppe i": "Group 1",
    "gruppe ii": "Group 2",
    "gruppe iii": "Group 3",
    "listenrennen": "Listed Race",
    "ausgleich i": "Handicap (Ausgleich I)",
    "ausgleich ii": "Handicap (Ausgleich II)",
    "ausgleich iii": "Handicap (Ausgleich III)",
    "ausgleich iv": "Handicap (Ausgleich IV)",
    "ebf-rennen": "EBF Maiden",
    "verkaufsrennen": "Selling Race",
    "zuchtrennen": "Breeders Race",
}


class DeutscherGaloppSource(Source):
    name = "deutscher_galopp"
    label = "Deutscher Galopp (Germany)"
    home = "https://www.deutscher-galopp.de/gr/renntage/rennkalender.php"

    def fetch(self, fetcher: Fetcher) -> list[Race]:
        calendar = BeautifulSoup(fetcher.get(CALENDAR), "lxml")
        races: list[Race] = []
        for listing in self._calendar_races(calendar):
            if not self.config.covers(listing["date"]):
                continue
            race = self._race_from_page(fetcher, listing)
            if race is not None:
                races.append(race)
        return races

    # -- calendar --------------------------------------------------------------
    def _calendar_races(self, soup: BeautifulSoup) -> Iterable[dict]:
        """Walk the calendar, tracking the date and course headings in document order."""
        date: dt.date | None = None
        course = ""
        for node in soup.find_all(["div", "h3", "a"]):
            classes = node.get("class") or []
            if "suchergebnisse-header" in classes:
                date = _german_date(node.get_text())
            elif node.name == "h3" and node.find("a", href=re.compile(r"/gr/renntage/\d+")):
                course = title_course(node.find("a").get_text().split("\n")[0])
            elif node.name == "a" and "rennenOuter" in classes:
                link = node.get("href") or ""
                match = RACE_LINK.search(link)
                if not match:
                    continue
                link_date = _compact_date(match.group(2)) or date
                if link_date is None:
                    continue
                yield {
                    "date": link_date,
                    "course": course,
                    "url": urljoin(BASE, link.replace("&amp;", "&")),
                    "name": _text(node.select_one(".rennen-headline")),
                    "category": _text(node.select_one(".rennen-kategorie")),
                    "time": _clock(node),
                    "distance": _distance(node),
                }

    # -- race page -------------------------------------------------------------
    def _race_from_page(self, fetcher: Fetcher, listing: dict) -> Race | None:
        soup = BeautifulSoup(fetcher.get(listing["url"]), "lxml")
        runners = list(self._wathnan_runners(soup))
        if not runners:
            return None

        course = listing["course"] or title_course(_text(soup.select_one(".racetrack")))
        name = listing["name"] or _text(soup.select_one(".racetitle"))
        if re.fullmatch(r"\d+\.\s*Rennen", name or "", flags=re.I):
            # Unnamed races are listed by number; the category reads better.
            name = ""
        declared = soup.select_one("#starter") is not None
        return Race(
            date=listing["date"],
            course=course,
            race_type=_race_type(name, listing["category"]),
            distance_furlongs=listing["distance"] or _page_distance(soup),
            off_time_uk=to_uk_time(listing["time"], listing["date"], country="DE"),
            breed=Breed.THOROUGHBRED,
            status=Status.DECLARED if declared else Status.ENTERED,
            runners=tuple(runners),
            source=self.name,
            source_url=listing["url"],
        )

    def _wathnan_runners(self, soup: BeautifulSoup) -> Iterable[Runner]:
        table = soup.select_one("table#starter") or soup.select_one("table#nennungen")
        if table is None:
            return
        columns = _column_index(table)
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            owner = _text(cells[columns["owner"]]) if columns.get("owner") is not None else ""
            tooltip = _tooltip(row)
            owner = owner or _from_tooltip(tooltip, "Besitzer")
            if not self.is_wathnan(owner):
                continue
            sire, dam = _pedigree(tooltip)
            yield Runner(
                horse=_german_horse(_horse_name(cells)),
                sire=clean_pedigree_name(sire),
                dam=clean_pedigree_name(dam),
                trainer=title_name(_cell(cells, columns.get("trainer"))
                                   or _from_tooltip(tooltip, "Trainer")),
                jockey=_rider(_cell(cells, columns.get("jockey"))
                              or _from_tooltip(tooltip, "Reiter")),
            )


# -- helpers -------------------------------------------------------------------
def _column_index(table: Tag) -> dict[str, int | None]:
    """Locate the German column headings so a layout change does not break us."""
    headings = [collapse_space(th.get_text()).lower() for th in table.select("thead th")]
    def find(*names: str) -> int | None:
        for index, heading in enumerate(headings):
            if any(heading.startswith(name) for name in names):
                return index
        return None
    return {"horse": find("name"), "owner": find("besitzer"),
            "trainer": find("trainer"), "jockey": find("reiter", "jockey")}


def _cell(cells: list[Tag], index: int | None) -> str:
    if index is None or index >= len(cells):
        return ""
    return _text(cells[index])


def _german_horse(name: str) -> str:
    """Add the implicit ``(GER)`` Deutscher Galopp leaves off home-bred horses."""
    cleaned = clean_horse_name(name)
    if cleaned and not cleaned.endswith(")"):
        return f"{cleaned} ({DEFAULT_COUNTRY})"
    return cleaned


def _rider(value: str) -> str:
    return title_name(RIDER_PREFIX.sub("", collapse_space(value)))


def _horse_name(cells: list[Tag]) -> str:
    for cell in cells:
        name = cell.select_one("span.name")
        if name is not None:
            return _text(name)
    return _text(cells[1]) if len(cells) > 1 else ""


def _tooltip(row: Tag) -> str:
    node = row.select_one("span.name[title]") or row.select_one("[title]")
    return (node.get("title") or "") if node is not None else ""


def _from_tooltip(tooltip: str, label: str) -> str:
    match = re.search(rf"{label}:\s*(.+?)(?:<br\s*/?>|$)", tooltip or "", re.I)
    return collapse_space(match.group(1)) if match else ""


def _pedigree(tooltip: str) -> tuple[str, str]:
    match = PEDIGREE.search(tooltip or "")
    if not match:
        return "", ""
    return collapse_space(match.group(1)), collapse_space(match.group(2))


def _race_type(name: str, category: str) -> str:
    """``Group 3`` on its own, or ``Grosser Preis (Group 3)`` when the race is named."""
    label = CATEGORY_LABELS.get((category or "").strip().lower(), collapse_space(category))
    name = collapse_space(name)
    if name and label:
        return f"{name} {label}" if label.startswith("Group") else f"{name} ({label})"
    return name or label


def _german_date(text: str) -> dt.date | None:
    match = GERMAN_DATE.search(text or "")
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _compact_date(value: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(value, "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


def _clock(node: Tag) -> dt.time | None:
    for cell in node.select(".rennen-daten .col-small"):
        if cell.select_one(".icon-clock") is not None:
            return parse_time(_text(cell))
    return None


def _distance(node: Tag) -> float | None:
    for cell in node.select(".rennen-daten .col-small"):
        match = DISTANCE.search(_text(cell))
        if match:
            return furlongs_from_metres(float(match.group(1).replace(".", "")))
    return None


def _page_distance(soup: BeautifulSoup) -> float | None:
    for span in soup.select(".container-racefacts .header-right, .racefacts"):
        match = DISTANCE.search(_text(span))
        if match:
            return furlongs_from_metres(float(match.group(1).replace(".", "")))
    return None


def _text(node: Tag | None) -> str:
    return collapse_space(node.get_text(" ")) if node is not None else ""
