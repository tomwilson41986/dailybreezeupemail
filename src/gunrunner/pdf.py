"""HTML to A4 PDF through headless Chromium (Playwright)."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def render(html: str, out: Path) -> Path:
    from playwright.sync_api import sync_playwright

    out.parent.mkdir(parents=True, exist_ok=True)
    src = out.with_suffix(".html")
    src.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(src.resolve().as_uri(), wait_until="networkidle", timeout=300_000)
        page.evaluate("document.fonts.ready")
        page.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True)
        browser.close()
    log.info("pdf %s: %.1f MB", out, out.stat().st_size / 1e6)
    return out
