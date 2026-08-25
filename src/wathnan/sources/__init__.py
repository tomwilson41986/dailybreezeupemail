"""Source adapters, one per racing authority feed."""

from __future__ import annotations

from .base import Fetcher, Source, SourceResult
from .deutscher_galopp import DeutscherGaloppSource
from .equibase import EquibaseSource
from .france_galop import FranceGalopSource
from .qrec import QrecSource
from .racingpost import RacingPostSource
from .sportinglife import SportingLifeSource

#: Registry keyed by the name used on the command line and in ``Config.sources``.
SOURCES: dict[str, type[Source]] = {
    source.name: source
    for source in (RacingPostSource, DeutscherGaloppSource, FranceGalopSource,
                   EquibaseSource, QrecSource, SportingLifeSource)
}

__all__ = ["Fetcher", "Source", "SourceResult", "SOURCES"]
