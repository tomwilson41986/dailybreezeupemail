"""Equibase, through the desk's parse.bot API over equibase.com: a horse's North
American runs, one line each (date, track, race and grade, finish, E figure).

Two calls: ``search_horse`` by name (1 credit) finds the reference number,
matched on year of birth and dam; ``get_past_performances`` (1 credit) gives
the runs. Every answer is cached, so a horse is paid for once. A run stops
spending at the configured budget, or when the account's balance (returned on
every response) falls to the floor.
"""

from __future__ import annotations

import logging
import re

import requests

from gunrunner.cache import Cache
from gunrunner.names import key, split_suffix

log = logging.getLogger(__name__)

API = "https://api.parse.bot/scraper/b5c51fc1-f1bd-41cd-9ed0-68a494eb2cd7"
# tracks that race only on turf: a run there is not dirt
TURF_TRACKS = {"KD", "CNL"}


class Equibase:
    def __init__(self, api_key: str, cache: Cache, *, budget: int, floor: int):
        self.api_key, self.cache, self.budget, self.floor = api_key, cache, budget, floor
        self.spent = 0
        self.balance: int | None = None
        self.session = requests.Session()

    @property
    def can_spend(self) -> bool:
        if not self.api_key:
            return False
        if self.spent >= self.budget:
            return False
        return self.balance is None or self.balance > self.floor

    def _call(self, endpoint: str, **params):
        resp = self.session.get(
            f"{API}/{endpoint}", params=params, headers={"X-API-Key": self.api_key}, timeout=300
        )
        left = resp.headers.get("x-credits-remaining")
        charged = resp.headers.get("x-credits-charged")
        if left and left.isdigit():
            self.balance = int(left)
        self.spent += int(charged) if charged and charged.isdigit() else 1
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "success":
            raise RuntimeError(f"{endpoint}: {str(body)[:200]}")
        return body["data"]

    def lookup(self, name: str, *, yob: int | None = None, dam: str = "") -> dict | None:
        """The horse's record, or None when she can't be found (or the budget is spent)."""
        if not name:
            return None
        ck = f"{key(name)}:{yob or ''}:{key(dam)}"
        cached = self.cache.get("equibase", ck)
        if cached is not None or self.cache.has("equibase", ck):
            return cached or None
        if not self.can_spend:
            return None
        try:
            found = self._call("search_horse", name=split_suffix(name)[0])
            hit = match_horse(found.get("items") or [], name=name, yob=yob, dam=dam)
            if not hit:
                self.cache.put("equibase", ck, {})
                return None
            pp = self._call("get_past_performances", ref_no=str(hit["refNo"]))
        except Exception as exc:  # noqa: BLE001
            log.warning("equibase lookup failed for %s: %s", name, exc)
            return None
        rec = {
            "refNo": hit["refNo"],
            "yob": hit.get("yob"),
            "dam": hit.get("damName"),
            "damYob": hit.get("damYob"),
            "sire": hit.get("sireName"),
            "runs": runs_from(pp.get("races") or []),
        }
        self.cache.put("equibase", ck, rec)
        return rec


def match_horse(items: list[dict], *, name: str, yob: int | None, dam: str) -> dict | None:
    """The search result that is this horse: same name, foaled the same year, out of
    the same dam; without the dam, the year must leave exactly one."""
    k = key(name)
    same = [
        h
        for h in items
        if key(h.get("horseName") or h.get("compressedName") or "") == k
        and (not yob or not h.get("yob") or int(h["yob"]) == int(yob))
    ]
    if dam:
        by_dam = [h for h in same if h.get("damName") and key(h["damName"]) == key(dam)]
        if len(by_dam) == 1:
            return by_dam[0]
        if by_dam:
            return None
    return same[0] if len(same) == 1 else None


def runs_from(races: list[dict]) -> list[dict]:
    out = []
    for r in races:
        m = re.match(r"(\d+)/(\d+)/(\d{4})", r.get("date") or "")
        if not m:
            continue
        name = re.sub(r"\s+", " ", r.get("race_type") or "").strip()
        g = re.search(r"\(Gr\.?\s*([123])\)", name)
        fin = str(r.get("finish_position") or "").strip()
        fig = str(r.get("speed_figure") or "").strip()
        out.append(
            {
                "date": f"{m[3]}-{int(m[1]):02d}-{int(m[2]):02d}",
                "track": r.get("track"),
                "race": name,
                "grade": int(g[1]) if g else None,
                "stakes": bool(re.search(r"stakes|handicap|\(Gr\.|black type|listed", name, re.I)),
                "finish": int(fin) if fin.isdigit() else None,
                "fig": int(fig) if fig.isdigit() else None,
                "turf": bool(re.search(r"\bturf\b", name, re.I)) or (r.get("track") in TURF_TRACKS),
            }
        )
    return sorted(out, key=lambda x: x["date"], reverse=True)
