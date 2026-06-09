"""The ordered registry of source adapters the daily job runs.

Each entry pairs a human label with the module's ``fetch`` callable. The job
calls each in turn, isolating failures so one broken site never sinks the
whole digest.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from salescatalogues.models import RawSale
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


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    fetch: FetchFn


# Order roughly follows the country order of the digest.
SOURCES: list[Source] = [
    Source("tattersalls", "Tattersalls (UK & IRE)", tattersalls.fetch),
    Source("tattersalls_online", "Tattersalls Online", tattersalls_online.fetch),
    Source("goffs", "Goffs (UK & IRE)", goffs.fetch),
    Source("arqana", "Arqana", arqana.fetch),
    Source("bbag", "BBAG", bbag.fetch),
    Source("keeneland", "Keeneland", keeneland.fetch),
    Source("fasigtipton", "Fasig-Tipton", fasigtipton.fetch),
    Source("obs", "OBS", obs.fetch),
    Source("inglis", "Inglis", inglis.fetch),
    Source("magicmillions", "Magic Millions", magicmillions.fetch),
    Source("nzb", "NZB", nzb.fetch),
    Source("gavelhouse", "Gavelhouse", gavelhouse.fetch),
]
