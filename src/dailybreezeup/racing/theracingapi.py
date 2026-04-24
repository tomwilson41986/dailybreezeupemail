"""Client for https://theracingapi.com.

Endpoints used (see https://theracingapi.com/documentation):
  GET /v1/racecards/pro?date=YYYY-MM-DD&region_codes=gb,ire
  GET /v1/results?start_date=&end_date=&region_codes=gb,ire

Auth is HTTP Basic. Credentials from Settings.the_racing_api_user/pass.

Regions returned by the API: `gb`, `ire`. The `region` field from the API
is mapped to our own country code: gb -> GB, ire -> IE.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any, Iterable

from requests.auth import HTTPBasicAuth

from dailybreezeup.config import load as load_settings
from dailybreezeup.models import RaceCard, RaceResult, Runner

from .common import get_json, make_session

BASE_URL = "https://api.theracingapi.com"
DEFAULT_REGIONS = ("gb", "ire")

log = logging.getLogger(__name__)


def _auth() -> HTTPBasicAuth:
    s = load_settings()
    return HTTPBasicAuth(s.the_racing_api_user, s.the_racing_api_pass)


def _parse_time(raw: str | None) -> time | None:
    if not raw:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def _country(region: str | None) -> str:
    if not region:
        return "GB"
    r = region.lower()
    if r in ("gb", "uk"):
        return "GB"
    if r in ("ire", "ie"):
        return "IE"
    if r in ("fr", "fra"):
        return "FR"
    return "GB"


def _runner_from_card(raw: dict[str, Any]) -> Runner:
    return Runner(
        horse=raw.get("horse") or raw.get("name") or "",
        age=raw.get("age"),
        sex=raw.get("sex_code") or raw.get("sex"),
        trainer=raw.get("trainer"),
        jockey=raw.get("jockey"),
        owner=raw.get("owner"),
        draw=str(raw["draw"]) if raw.get("draw") is not None else None,
        number=str(raw["number"]) if raw.get("number") is not None else None,
        weight=raw.get("lbs") or raw.get("weight"),
        form=raw.get("form"),
        sire=raw.get("sire"),
        dam=raw.get("dam"),
        bred=raw.get("region") or raw.get("bred"),
    )


def _runner_from_result(raw: dict[str, Any]) -> Runner:
    r = _runner_from_card(raw)
    return r.model_copy(update={
        "finishing_position": str(raw.get("position")) if raw.get("position") is not None else None,
        "sp": raw.get("sp") or raw.get("sp_dec"),
        "beaten_lengths": str(raw.get("btn")) if raw.get("btn") is not None else None,
    })


def _card_from_payload(raw: dict[str, Any], on: date) -> RaceCard:
    runners = [_runner_from_card(r) for r in (raw.get("runners") or [])]
    return RaceCard(
        race_id=str(raw.get("race_id") or raw.get("id") or f"{raw.get('course')}-{raw.get('off_time')}"),
        country=_country(raw.get("region")),  # type: ignore[arg-type]
        course=raw.get("course") or "",
        race_date=on,
        off_time=_parse_time(raw.get("off_time")),
        race_name=raw.get("race_name") or raw.get("title") or "",
        runners=runners,
        url=raw.get("url"),
    )


def _result_from_payload(raw: dict[str, Any]) -> RaceResult:
    on = date.fromisoformat(raw["date"]) if raw.get("date") else date.today()
    runners = [_runner_from_result(r) for r in (raw.get("runners") or [])]
    return RaceResult(
        race_id=str(raw.get("race_id") or raw.get("id") or f"{raw.get('course')}-{raw.get('off_time')}"),
        country=_country(raw.get("region")),  # type: ignore[arg-type]
        course=raw.get("course") or "",
        race_date=on,
        off_time=_parse_time(raw.get("off_time")),
        race_name=raw.get("race_name") or raw.get("title") or "",
        runners=runners,
        url=raw.get("url"),
    )


def _paged(endpoint: str, params: dict[str, Any]) -> Iterable[dict[str, Any]]:
    s = make_session()
    auth = _auth()
    next_url: str | None = f"{BASE_URL}{endpoint}"
    next_params: dict[str, Any] | None = params
    while next_url:
        try:
            payload = get_json(s, next_url, params=next_params, auth=auth)
        except Exception as exc:  # noqa: BLE001
            log.warning("Racing API %s failed: %s", next_url, exc)
            return
        for item in payload.get("racecards") or payload.get("results") or []:
            yield item
        next_cursor = payload.get("next_cursor") or payload.get("next")
        if not next_cursor:
            return
        next_url = next_cursor if next_cursor.startswith("http") else f"{BASE_URL}{next_cursor}"
        next_params = None


def _fetch_cards(on: date, regions: tuple[str, ...]) -> list[RaceCard]:
    for endpoint in ("/v1/racecards/pro", "/v1/racecards/standard"):
        cards: list[RaceCard] = []
        hit = False
        for item in _paged(endpoint, {"date": on.isoformat(), "region_codes": ",".join(regions)}):
            hit = True
            cards.append(_card_from_payload(item, on))
        if hit:
            return cards
    return []


def fetch_declarations(on: date, regions: tuple[str, ...] = DEFAULT_REGIONS) -> list[RaceCard]:
    return _fetch_cards(on, regions)


def fetch_entries(on: date, regions: tuple[str, ...] = DEFAULT_REGIONS) -> list[RaceCard]:
    return _fetch_cards(on, regions)


def fetch_results(on: date, regions: tuple[str, ...] = DEFAULT_REGIONS) -> list[RaceResult]:
    out: list[RaceResult] = []
    for item in _paged("/v1/results", {
        "start_date": on.isoformat(),
        "end_date": on.isoformat(),
        "region_codes": ",".join(regions),
    }):
        out.append(_result_from_payload(item))
    return out
