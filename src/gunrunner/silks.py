"""Silks, last owner and trainer from Horse Racing Nation, for the raced US
prospects. A page is hers when its sire and dam match. Cached by lot."""

from __future__ import annotations

import base64
import logging
import re

from gunrunner.cache import Cache
from gunrunner.names import key, split_suffix

log = logging.getLogger(__name__)

HRN = "https://www.horseracingnation.com/horse/{slug}"
_SIRED = re.compile(r"sired by (.+?) out of the (.+?) mare (.+?)\.")


def slug(name: str) -> str:
    base = split_suffix(name)[0]
    return re.sub(r"\s+", "_", re.sub(r"['’.,]", "", base).strip())


def _norm(s: str) -> str:
    return key(re.sub(r"\s*\([A-Za-z]{2,4}\)", "", s or ""))


def fetch(horses: list[dict], cache: Cache) -> dict[str, dict]:
    """``horses``: {lot_id, name, sire, dam}. Returns lot_id -> {url, owner, trainer, png}."""
    out: dict[str, dict] = {}
    todo = []
    for h in horses:
        hit = cache.get("hrn", h["lot_id"], max_age_days=60)
        if hit is not None:
            if hit:
                out[h["lot_id"]] = hit
        else:
            todo.append(h)
    if not todo:
        return out
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        ctx.route(
            "**/*",
            lambda r: (
                r.abort()
                if r.request.resource_type in ("image", "media", "font")
                and "Image.aspx" not in r.request.url
                else r.continue_()
            ),
        )
        page = ctx.new_page()
        for h in todo:
            rec: dict = {}
            base = slug(h["name"])
            for t in (base, *(f"{base}_{i}" for i in range(1, 5))):
                url = HRN.format(slug=t)
                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    if not resp or resp.status == 404:
                        continue
                    page.wait_for_function(
                        "() => /sired by|not found/i.test(document.body.innerText)", timeout=30_000
                    )
                    txt = page.inner_text("body")
                except Exception:  # noqa: BLE001
                    continue
                m = _SIRED.search(txt)
                if not (
                    m
                    and _norm(m[1]) == _norm(h["sire"])
                    and (_norm(m[3]) == _norm(h["dam"]) or "login to add" in m[3].lower())
                ):
                    continue
                owner = re.search(r"Owner\(s\):\s*\n?([^\n]+)", txt)
                trainer = re.search(r"Trainer:\s*\n?([^\n]+)", txt)
                rec = {
                    "url": url,
                    "owner": owner[1].strip() if owner else None,
                    "trainer": trainer[1].strip() if trainer else None,
                }
                for k in ("owner", "trainer"):
                    if (rec[k] or "").startswith(("[", "Trainer")):
                        rec[k] = None
                src = page.eval_on_selector_all(
                    "img",
                    "els => (els.find(e => /^Silk for/i.test(e.alt || '')) || {}).src || null",
                )
                if src:
                    r = ctx.request.get(src.replace("type=thumb", "type=large"))
                    if r.ok:
                        rec["png"] = "data:image/png;base64," + base64.b64encode(r.body()).decode()
                break
            cache.put("hrn", h["lot_id"], rec)
            if rec:
                out[h["lot_id"]] = rec
            log.info("hrn %s: %s", h["name"], "found" if rec else "not found")
        browser.close()
    return out
