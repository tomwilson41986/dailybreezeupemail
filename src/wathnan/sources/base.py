"""Shared plumbing for the source adapters: fetching, caching and owner matching."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from ..config import Config
from ..models import Race, normalise_key
from ..normalise import strip_owner_prefix

LOG = logging.getLogger(__name__)

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

DEFAULT_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

#: Politeness gap between requests to the same host (Equibase asks for 5s;
#: Sporting Life's JSON API is swept a few hundred URLs at a time).
HOST_DELAYS = {"www.equibase.com": 5.0, "www.sportinglife.com": 0.25}
DEFAULT_DELAY = 1.0


class FetchError(RuntimeError):
    """Raised when a page could not be retrieved."""


@dataclass
class SourceResult:
    """What one adapter produced, including anything that went wrong."""

    source: str
    races: list[Race] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def runner_count(self) -> int:
        return sum(len(race.runners) for race in self.races)


class Fetcher:
    """Fetches pages over HTTP, through a browser, or from a saved snapshot.

    Snapshots serve three purposes: they make runs reproducible, they give the
    tests real input, and they let a blocked source be filled in by hand -- drop
    the page you saved in your own browser into the snapshot directory and run
    with ``--offline``.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._last_request: dict[str, float] = {}
        self._browser_pages: dict[str, str] = {}

    # -- snapshots -------------------------------------------------------------
    def snapshot_path(self, url: str, suffix: str = ".html") -> Path:
        parts = urlsplit(url)
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{parts.netloc}{parts.path}").strip("-")
        return self.config.snapshot_dir / f"{stem[:80]}-{digest}{suffix}"

    def _read_snapshot(self, url: str, suffix: str) -> str | None:
        path = self.snapshot_path(url, suffix)
        if path.exists():
            LOG.debug("snapshot hit %s", path)
            return path.read_text(encoding="utf-8", errors="replace")
        return None

    def _write_snapshot(self, url: str, body: str, suffix: str) -> None:
        if not self.config.save_snapshots:
            return
        path = self.snapshot_path(url, suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    # -- fetching --------------------------------------------------------------
    def get(self, url: str, *, browser: bool = False, impersonate: bool = False,
            params: dict | None = None, headers: dict | None = None,
            suffix: str = ".html", refresh: bool = False) -> str:
        """Return the body of ``url``, using cache/snapshot/browser as configured.

        ``refresh`` skips the snapshot, which is what a retry needs -- otherwise
        it would be handed the challenge page the plain fetch just cached.
        ``impersonate`` swaps in a Chrome TLS fingerprint for hosts that reject
        Python's.
        """
        full_url = _with_params(url, params)
        cached = None if (refresh and not self.config.offline) else \
            self._read_snapshot(full_url, suffix)
        fresh = self.config.offline or _is_fresh(self.snapshot_path(full_url, suffix))
        if cached is not None and fresh:
            return cached
        if self.config.offline:
            raise FetchError(f"offline and no snapshot for {full_url}")

        if browser and self.config.use_browser:
            body = self._get_with_browser(full_url)
        elif impersonate:
            body = self._get_with_impersonation(full_url, headers)
        else:
            body = self._get_with_requests(full_url, headers)
        self._write_snapshot(full_url, body, suffix)
        return body

    def discard(self, url: str, params: dict | None = None, suffix: str = ".html") -> None:
        """Drop a snapshot that turned out to be a challenge page.

        Caching one would poison later ``--offline`` runs.
        """
        self.snapshot_path(_with_params(url, params), suffix).unlink(missing_ok=True)

    def get_json(self, url: str, *, params: dict | None = None,
                 headers: dict | None = None, method: str = "GET",
                 data: Any = None) -> Any:
        full_url = _with_params(url, params)
        if method == "GET":
            cached = self._read_snapshot(full_url, ".json")
            fresh = self.config.offline or _is_fresh(self.snapshot_path(full_url, ".json"))
            if cached is not None and fresh:
                return json.loads(cached)
            if self.config.offline:
                raise FetchError(f"offline and no snapshot for {full_url}")
        self._respect_delay(full_url)
        response = self.session.request(method, full_url, headers=headers, data=data,
                                        timeout=self.config.request_timeout)
        if response.status_code >= 400:
            raise FetchError(f"{response.status_code} from {full_url}")
        if method == "GET":
            self._write_snapshot(full_url, response.text, ".json")
        return response.json()

    def _get_with_impersonation(self, url: str, headers: dict | None) -> str:
        """Fetch with a real Chrome TLS/HTTP-2 fingerprint.

        Racing Post's Fastly filter rejects Python's TLS handshake from cloud
        IPs -- it is a fingerprint check, not an IP block -- so curl_cffi
        impersonating Chrome walks straight through where plain requests gets
        a 406. This is the same approach the rest of this repository uses.

        ``RP_IMPERSONATE`` picks the Chrome version. Newer ones send a
        post-quantum ClientHello that some corporate egress proxies reset, so
        an older profile is sometimes the one that works.
        """
        from curl_cffi import requests as cffi_requests  # noqa: PLC0415

        self._respect_delay(url)
        profile = os.environ.get("RP_IMPERSONATE", "chrome110")
        verify = os.environ.get("CURL_CA_BUNDLE") or True
        session = cffi_requests.Session(impersonate=profile, verify=verify)
        response = session.get(url, headers=headers or DEFAULT_HEADERS,
                               timeout=self.config.request_timeout)
        if response.status_code >= 400:
            raise FetchError(f"{response.status_code} from {url} (impersonating {profile})")
        return response.text

    def _get_with_requests(self, url: str, headers: dict | None) -> str:
        self._respect_delay(url)
        response = self.session.get(url, headers=headers, timeout=self.config.request_timeout)
        if response.status_code >= 400:
            raise FetchError(
                f"{response.status_code} from {url}"
                + (" (bot protection -- try --browser or supply a snapshot)"
                   if response.status_code in (403, 406, 429) else "")
            )
        return response.text

    def _get_with_browser(self, url: str) -> str:
        """Render ``url`` in headless Chromium, which clears most bot checks."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise FetchError("browser mode needs `pip install playwright` "
                             "and `playwright install chromium`") from exc

        self._respect_delay(url)
        launch: dict = {"args": ["--no-sandbox", *self.config.browser_args]}
        # Chromium does not read proxy environment variables on its own, so a
        # proxied environment (corporate egress, CI) is passed through here.
        proxy = self.config.browser_proxy or os.environ.get("HTTPS_PROXY") \
            or os.environ.get("https_proxy")
        if proxy:
            launch["proxy"] = {"server": proxy}
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**launch)
            try:
                context = browser.new_context(user_agent=BROWSER_UA, locale="en-GB",
                                              viewport={"width": 1440, "height": 900})
                page = context.new_page()
                response = page.goto(url, wait_until="domcontentloaded",
                                     timeout=self.config.request_timeout * 1000)
                page.wait_for_timeout(4000)
                if response is not None and response.status >= 400:
                    raise FetchError(f"{response.status} from {url} (browser)")
                return page.content()
            finally:
                browser.close()

    def _respect_delay(self, url: str) -> None:
        host = urlsplit(url).netloc
        gap = HOST_DELAYS.get(host, DEFAULT_DELAY)
        previous = self._last_request.get(host)
        if previous is not None:
            wait = gap - (time.monotonic() - previous)
            if wait > 0:
                time.sleep(wait)
        self._last_request[host] = time.monotonic()


def _with_params(url: str, params: dict | None) -> str:
    if not params:
        return url
    from urllib.parse import urlencode
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _is_fresh(path: Path, max_age_seconds: int = 3600) -> bool:
    """Snapshots are reused within the hour so a re-run does not re-crawl."""
    try:
        return (time.time() - path.stat().st_mtime) < max_age_seconds
    except OSError:
        return False


class Source:
    """Base class for a racing authority adapter."""

    #: Command-line/config name.
    name: str = ""
    #: Human readable label used in the run summary.
    label: str = ""
    #: Where the data comes from, shown in the README and run summary.
    home: str = ""

    def __init__(self, config: Config) -> None:
        self.config = config

    def collect(self, fetcher: Fetcher) -> SourceResult:
        """Fetch and parse, converting any failure into a reportable result."""
        result = SourceResult(source=self.name)
        try:
            result.races = [race for race in self.fetch(fetcher)
                            if self.config.covers(race.date)]
        except Exception as exc:  # noqa: BLE001 - one bad feed must not sink the run
            LOG.warning("%s failed: %s", self.name, exc)
            result.error = f"{type(exc).__name__}: {exc}"
        return result

    def fetch(self, fetcher: Fetcher) -> list[Race]:  # pragma: no cover - interface
        raise NotImplementedError

    # -- helpers shared by the adapters ---------------------------------------
    def is_wathnan(self, owner: str | None) -> bool:
        """Does this owner string identify the Wathnan Racing account?"""
        if not owner:
            return False
        key = normalise_key(strip_owner_prefix(owner))
        return any(normalise_key(alias) in key for alias in self.config.owner_aliases)

    def wanted_dates(self) -> Sequence[dt.date]:
        return self.config.dates()
