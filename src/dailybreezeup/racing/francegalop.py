"""Scraper for france-galop.com daily race programmes.

WARNING: the HTML selectors below are based on the public site's layout as of
April 2026. France Galop change the site occasionally and these patterns WILL
need tweaking. Each selector lives in the SELECTORS block at the top so it's
easy to patch.

Strategy:
  1. GET the programme index for the date from PROGRAMME_URL
  2. Find each meeting link (<a class=...> pointing at /en/race/card/<id>)
  3. For each meeting, parse each race block's runners for entries/declarations,
     or parse the arrivee (results) tab for yesterday's results.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from dailybreezeup.models import RaceCard, RaceResult, Runner

from .common import get_text, make_session

BASE_URL = "https://www.france-galop.com"
PROGRAMME_URL = BASE_URL + "/en/race/programme/{date}"

SELECTORS: dict[str, str] = {
    "meeting_link": "a.programme__meeting-link, a[href*='/en/race/card/']",
    "race_block": "section.race, div.race-card",
    "race_name": "h2, .race-title",
    "race_time": ".race-time, time",
    "runner_row": "table.runners tr, .runner-row",
    "runner_name": ".horse-name, td.name",
    "runner_age": ".age",
    "runner_sire": ".sire",
    "runner_dam": ".dam",
    "runner_trainer": ".trainer",
    "runner_jockey": ".jockey",
    "runner_position": ".position, .rank",
    "runner_sp": ".sp, .cote",
}

log = logging.getLogger(__name__)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _text(node: Any) -> str | None:
    if node is None:
        return None
    t = node.get_text(" ", strip=True)
    return t or None


def _parse_meeting(html: str, on: date, *, with_results: bool = False) -> list[RaceCard | RaceResult]:
    soup = _soup(html)
    out: list[RaceCard | RaceResult] = []
    course = _text(soup.select_one("h1, .meeting__title")) or ""
    for race_el in soup.select(SELECTORS["race_block"]):
        race_id = race_el.get("id") or race_el.get("data-race-id") or ""
        runners: list[Runner] = []
        for row in race_el.select(SELECTORS["runner_row"]):
            name = _text(row.select_one(SELECTORS["runner_name"]))
            if not name:
                continue
            age_raw = _text(row.select_one(SELECTORS["runner_age"]))
            try:
                age = int(age_raw) if age_raw else None
            except ValueError:
                age = None
            runner = Runner(
                horse=name,
                age=age,
                sire=_text(row.select_one(SELECTORS["runner_sire"])),
                dam=_text(row.select_one(SELECTORS["runner_dam"])),
                trainer=_text(row.select_one(SELECTORS["runner_trainer"])),
                jockey=_text(row.select_one(SELECTORS["runner_jockey"])),
                finishing_position=_text(row.select_one(SELECTORS["runner_position"]))
                if with_results else None,
                sp=_text(row.select_one(SELECTORS["runner_sp"])) if with_results else None,
            )
            runners.append(runner)
        card_kw = dict(
            race_id=str(race_id or f"fr-{course}-{on.isoformat()}-{len(out)}"),
            country="FR",
            course=course,
            race_date=on,
            race_name=_text(race_el.select_one(SELECTORS["race_name"])) or "",
            runners=runners,
        )
        out.append(RaceResult(**card_kw) if with_results else RaceCard(**card_kw))
    return out


def _fetch_programme(on: date, *, with_results: bool) -> list[RaceCard | RaceResult]:
    s = make_session()
    try:
        index_html = get_text(s, PROGRAMME_URL.format(date=on.isoformat()))
    except Exception as exc:  # noqa: BLE001
        log.warning("France Galop programme fetch failed for %s: %s", on, exc)
        return []

    soup = _soup(index_html)
    links = {
        a["href"] if a["href"].startswith("http") else BASE_URL + a["href"]
        for a in soup.select(SELECTORS["meeting_link"])
        if a.get("href")
    }
    cards: list[RaceCard | RaceResult] = []
    for url in links:
        try:
            html = get_text(s, url)
        except Exception as exc:  # noqa: BLE001
            log.warning("France Galop meeting fetch failed for %s: %s", url, exc)
            continue
        cards.extend(_parse_meeting(html, on, with_results=with_results))
    return cards


def fetch_declarations(on: date) -> list[RaceCard]:
    return [c for c in _fetch_programme(on, with_results=False) if isinstance(c, RaceCard)]


def fetch_entries(on: date) -> list[RaceCard]:
    return fetch_declarations(on)


def fetch_results(on: date) -> list[RaceResult]:
    return [c for c in _fetch_programme(on, with_results=True) if isinstance(c, RaceResult)]
