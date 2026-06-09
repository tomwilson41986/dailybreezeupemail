"""The ordered registry of source adapters the daily job runs.

Each entry pairs a human label with the module's ``fetch`` callable. The job
calls each in turn, isolating failures so one broken site never sinks the
whole digest.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from salescatalogues.models import Lot, RawSale
from salescatalogues.sources import (
    arqana,
    bbag,
    fasigtipton,
    gavelhouse,
    goffs,
    inglis,
    keeneland,
    magicmillions,
    nzb,
    obs,
    tattersalls,
    tattersalls_online,
)

FetchFn = Callable[..., list[RawSale]]
# (raw_sale, session) -> lots for that sale's published catalogue
LotFetchFn = Callable[..., list[Lot]]


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    fetch: FetchFn
    fetch_lots: LotFetchFn | None = None


def _lots(module: object) -> LotFetchFn | None:
    """A source's lot fetcher, if it implements one."""
    return getattr(module, "fetch_lots", None)


# Order roughly follows the country order of the digest. ``fetch_lots`` is wired
# per source as each house's catalogue lot endpoint is implemented; sources
# without one simply contribute a sale-level summary row to the CSV.
SOURCES: list[Source] = [
    Source("tattersalls", "Tattersalls (UK & IRE)", tattersalls.fetch, _lots(tattersalls)),
    Source("tattersalls_online", "Tattersalls Online", tattersalls_online.fetch,
           _lots(tattersalls_online)),
    Source("goffs", "Goffs (UK & IRE)", goffs.fetch, _lots(goffs)),
    Source("arqana", "Arqana", arqana.fetch, _lots(arqana)),
    Source("bbag", "BBAG", bbag.fetch, _lots(bbag)),
    Source("keeneland", "Keeneland", keeneland.fetch, _lots(keeneland)),
    Source("fasigtipton", "Fasig-Tipton", fasigtipton.fetch, _lots(fasigtipton)),
    Source("obs", "OBS", obs.fetch, _lots(obs)),
    Source("inglis", "Inglis", inglis.fetch, _lots(inglis)),
    Source("magicmillions", "Magic Millions", magicmillions.fetch, _lots(magicmillions)),
    Source("nzb", "NZB", nzb.fetch, _lots(nzb)),
    Source("gavelhouse", "Gavelhouse", gavelhouse.fetch, _lots(gavelhouse)),
]

SOURCES_BY_KEY: dict[str, Source] = {s.key: s for s in SOURCES}
