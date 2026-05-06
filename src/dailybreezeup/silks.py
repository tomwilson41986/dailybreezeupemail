"""Fetch silk SVGs from Racing Post and rasterise them as white-backed PNGs
for inline (cid:) email attachment.

Why rasterise at send time instead of hot-linking? Gmail (the primary
recipient) blocks remote SVG and most email clients sanitise <img src>
to disk-cached versions. CID-attached PNG is the only path that renders
reliably across Gmail web/iOS, Apple Mail and Outlook.

We render with resvg-py rather than cairosvg because cairosvg requires
the Cairo C library to be installed system-wide — a known pain on
Windows, where the production cron lives. resvg-py ships statically
linked binary wheels for every platform we target, so a plain
``pip install`` is enough.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Iterable

import requests

log = logging.getLogger(__name__)

# RP silks are exported with viewBox "0 0 98.45 70.53" (landscape, ~1.4:1).
# Render at 2x the email display size so retina screens stay crisp; the
# template displays at SILK_DISPLAY_W x SILK_DISPLAY_H below.
_SILK_RENDER_W = 80
_SILK_RENDER_H = 57          # 80 * 70.53 / 98.45, rounded
SILK_DISPLAY_W = 56
SILK_DISPLAY_H = 40          # 56 * 70.53 / 98.45, rounded
_FETCH_TIMEOUT = 15
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Racing Post silks declare width/height in points (e.g. width="98.45pt").
# resvg 0.3 rejects unit-suffixed dims with "SVG has an invalid size";
# stripping those attributes lets resvg fall back to viewBox + the explicit
# render-time width/height we pass in.
_PT_DIM_RE = re.compile(r'\s(width|height)="[\d\.]+pt"')


@dataclass(frozen=True)
class _RenderedSilk:
    cid: str         # bare Content-ID value (no angle brackets)
    png: bytes


def _cid_for_url(url: str) -> str:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"silk-{h}"


def _fetch_svg(url: str, *, session: requests.Session | None = None) -> bytes | None:
    s = session or requests
    try:
        r = s.get(url, timeout=_FETCH_TIMEOUT, headers={"User-Agent": _USER_AGENT})
        r.raise_for_status()
        return r.content
    except Exception as exc:  # noqa: BLE001
        log.warning("silk fetch failed (%s): %s", url, exc)
        return None


def _sanitise_svg(svg: bytes) -> str:
    text = svg.decode("utf-8", errors="replace")
    return _PT_DIM_RE.sub("", text)


def _svg_to_png(svg: bytes) -> bytes | None:
    try:
        import resvg_py  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "resvg_py unavailable; skipping silk rasterisation "
            "(pip install resvg-py): %s", exc,
        )
        return None
    try:
        png = resvg_py.svg_to_bytes(
            svg_string=_sanitise_svg(svg),
            width=_SILK_RENDER_W,
            height=_SILK_RENDER_H,
            background="white",
        )
        return bytes(png)
    except Exception as exc:  # noqa: BLE001
        log.warning("resvg render failed: %s", exc)
        return None


def assign_silk_cids(rows: Iterable[dict[str, Any]]) -> None:
    """Mutate rows in place: set ``silk_cid`` for any row that has a
    ``silk_url``. Idempotent — derives the CID deterministically from the
    URL so the template can reference it before silks are actually
    fetched/attached.
    """
    for row in rows:
        url = row.get("silk_url")
        if url:
            row["silk_cid"] = _cid_for_url(url)


def attach_silks(
    msg: EmailMessage,
    rows: Iterable[dict[str, Any]],
    *,
    session: requests.Session | None = None,
) -> int:
    """Fetch + rasterise each unique silk URL referenced in ``rows`` and
    attach the resulting PNG inline against the HTML alternative. Returns
    the number of silks successfully attached.

    Rows without a ``silk_url`` are skipped silently. Fetch/render failures
    are logged and skipped — the corresponding <img cid:...> simply renders
    as alt text in the email.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for row in rows:
        url = row.get("silk_url")
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)

    if not urls:
        return 0

    html_part = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            html_part = part
            break
    if html_part is None:
        log.warning("no text/html part found; cannot attach silks")
        return 0

    attached = 0
    for url in urls:
        svg = _fetch_svg(url, session=session)
        if not svg:
            continue
        png = _svg_to_png(svg)
        if not png:
            continue
        cid = _cid_for_url(url)
        html_part.add_related(
            png, maintype="image", subtype="png", cid=f"<{cid}>"
        )
        attached += 1
    return attached
