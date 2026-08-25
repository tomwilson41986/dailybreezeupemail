"""Runtime configuration for the report generator."""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
ASSETS = PACKAGE_ROOT / "assets"
DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_SNAPSHOT_DIR = Path("snapshots")

#: Owner names that identify a Wathnan horse in a runner list.  Feeds spell the
#: owner inconsistently, so matching is done on a normalised substring.
OWNER_ALIASES = (
    "wathnan racing",
    "wathnan",
    "al wathnan",
)

#: Home authorities first: when two feeds report the same race, the merge keeps
#: the first-seen post time, and the racing authority that stages the race is
#: the one to trust for it.  The broad Racing Post/Sporting Life sweep runs last.
DEFAULT_SOURCES = ("qrec", "deutscher_galopp", "france_galop", "equibase",
                   "racingpost")

#: Per-source identifiers for the Wathnan owner account.
SOURCE_IDS = {
    "racingpost": "325088",
    "equibase": "2304655",
    "france_galop": "YTZJc1NXbEhYRUFjT29zaGVLY2hUQT09",
}


@dataclass(frozen=True)
class Config:
    """Everything the pipeline needs to know to build one report."""

    #: The day the "TOMORROW'S RUNNERS" table covers.
    tomorrow: dt.date
    #: Inclusive last day of the "UPDATED ENTRIES" table.
    entries_until: dt.date
    sources: tuple[str, ...] = DEFAULT_SOURCES
    owner_aliases: tuple[str, ...] = OWNER_ALIASES
    source_ids: dict = field(default_factory=lambda: dict(SOURCE_IDS))
    output_dir: Path = DEFAULT_OUTPUT_DIR
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR
    #: Persist every fetched page so a run can be replayed or audited offline.
    save_snapshots: bool = True
    #: Use saved snapshots instead of the network.
    offline: bool = False
    #: Drive blocked sites through a real browser rather than plain HTTP.
    use_browser: bool = True
    #: Look up a country suffix for any horse the registry does not know.
    fill_suffixes: bool = True
    #: Write newly discovered suffixes back into wathnan/data/horses.json.
    learn_suffixes: bool = False
    request_timeout: int = 45
    #: Extra Chromium flags, e.g. for a TLS-terminating corporate proxy.
    browser_args: tuple[str, ...] = ()
    browser_proxy: str | None = None

    @property
    def entries_from(self) -> dt.date:
        return self.tomorrow + dt.timedelta(days=1)

    @property
    def first_date(self) -> dt.date:
        return self.tomorrow

    @property
    def last_date(self) -> dt.date:
        return max(self.entries_until, self.tomorrow)

    def dates(self) -> list[dt.date]:
        span = (self.last_date - self.first_date).days
        return [self.first_date + dt.timedelta(days=offset) for offset in range(span + 1)]

    def covers(self, date: dt.date) -> bool:
        return self.first_date <= date <= self.last_date

    def output_path(self) -> Path:
        stamp = self.tomorrow.strftime("%Y-%m-%d")
        return self.output_dir / f"wathnan-runners-{stamp}.pdf"


def build_config(today: dt.date | None = None, days_ahead: int = 5, **overrides) -> Config:
    """Default window: tomorrow, plus the following ``days_ahead`` days of entries."""
    today = today or dt.date.today()
    tomorrow = today + dt.timedelta(days=1)
    config = Config(tomorrow=tomorrow, entries_until=tomorrow + dt.timedelta(days=days_ahead))
    return replace(config, **overrides) if overrides else config


def load_env_overrides() -> dict:
    """Read the handful of settings that make sense to inject from CI."""
    overrides: dict = {}
    if os.environ.get("WATHNAN_BROWSER_ARGS"):
        overrides["browser_args"] = tuple(os.environ["WATHNAN_BROWSER_ARGS"].split())
    if os.environ.get("WATHNAN_BROWSER_PROXY"):
        overrides["browser_proxy"] = os.environ["WATHNAN_BROWSER_PROXY"]
    if os.environ.get("WATHNAN_SOURCE_IDS"):
        overrides["source_ids"] = {**SOURCE_IDS, **json.loads(os.environ["WATHNAN_SOURCE_IDS"])}
    return overrides
