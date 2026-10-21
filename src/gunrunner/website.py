"""The desk's own sale data on blandfordbloodstock.tech, matched to a lot by sire,
dam and year.

* Breeding-stock sales (``/data/bms/<sale>/``): AuctionEdge peak E, AEI, best win,
  earnings, R2 Rating, first cover / off the track, produce; the lot file adds
  her winning surfaces, her dam and second dam.
* Horses-in-training sales (``/data/hitsales/<sale>/``): Timeform peak (turf and
  AW), best distance, group and listed wins, prize.

The sales are configured (``GUNRUNNER_WEBSITE_SALES``), plus any more the site
repo's ``public/data`` listing shows when GitHub answers.
"""

from __future__ import annotations

import logging
import re

from gunrunner.cache import Cache
from gunrunner.names import key

log = logging.getLogger(__name__)

LISTING = "https://api.github.com/repos/Abiqb93/horses-website-deployed/contents/public/data/{kind}"


def _pair(sire: str, dam: str) -> str:
    return f"{key(sire)}|{key(dam)}"


class Website:
    def __init__(self, base: str, session, cache: Cache, sales: list[str] = ()):
        self.base, self.session, self.cache = base.rstrip("/"), session, cache
        self.configured = list(sales)
        self.bms: dict[str, list[dict]] = {}
        self.hit: dict[str, list[dict]] = {}

    def _json(self, url: str):
        resp = self.session.get(url, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _sales(self, kind: str) -> list[str]:
        out = [s.split(":", 1)[1] for s in self.configured if s.startswith(f"{kind}:")]
        try:
            items = self._json(LISTING.format(kind=kind))
            out += [i["name"] for i in items if i.get("type") == "dir" and i["name"] not in out]
        except Exception as exc:  # noqa: BLE001
            log.info("website %s listing unavailable (%s); configured sales only", kind, exc)
        return out

    def load(self) -> None:
        for kind, into in (("bms", self.bms), ("hitsales", self.hit)):
            for sale in self._sales(kind):
                try:
                    rows = (
                        self._json(f"{self.base}/data/{kind}/{sale}/index.json").get("rows") or []
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("website %s/%s failed: %s", kind, sale, exc)
                    continue
                for r in rows:
                    r["_sale"] = sale
                    if r.get("sire") and r.get("dam"):
                        into.setdefault(_pair(r["sire"], r["dam"]), []).append(r)
                log.info("website %s/%s: %d rows", kind, sale, len(rows))

    @staticmethod
    def _pick(rows: list[dict], yob: int | None) -> dict | None:
        if not rows:
            return None
        if yob:
            rows = [
                r
                for r in rows
                if (r.get("yob") or r.get("foaled")) in (yob, str(yob))
                or str(r.get("foaled") or "")[:4] == str(yob)
            ] or []
        # the newest sale's row first: two sales can catalogue the same horse
        return sorted(rows, key=lambda r: r["_sale"])[-1] if rows else None

    def bms_row(self, sire: str, dam: str, yob: int | None) -> dict | None:
        return self._pick(self.bms.get(_pair(sire, dam), []), yob)

    def hit_row(self, sire: str, dam: str, yob: int | None) -> dict | None:
        return self._pick(self.hit.get(_pair(sire, dam), []), yob)

    def bms_lot(self, row: dict) -> dict:
        """The lot file (AuctionEdge dam and second dam, produce), cached."""
        ck = f"{row['_sale']}:{row['lot']}"
        hit = self.cache.get("website-lot", ck)
        if hit is not None:
            return hit
        try:
            lot = self._json(f"{self.base}/data/bms/{row['_sale']}/lots/{row['lot']}.json")
        except Exception as exc:  # noqa: BLE001
            log.warning("website lot %s failed: %s", ck, exc)
            return {}
        keep = {k: lot.get(k) for k in ("auctionEdge", "runs", "urls", "produce")}
        self.cache.put("website-lot", ck, keep)
        return keep


_BEST_WIN = re.compile(r"(?P<purse>[\d.]+k)?\s*(?P<type>[^/]*)/(?P<track>[A-Z]+)/(?P<f>[\d.]+)f")


def parse_best_win(text: str | None) -> dict | None:
    """AuctionEdge's best-win text, "300k gr.II/SA/8.5f"."""
    m = _BEST_WIN.search(text or "")
    if not m:
        return None
    return {"type": m["type"].strip(), "track": m["track"], "furlongs": float(m["f"])}
