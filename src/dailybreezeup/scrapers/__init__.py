from __future__ import annotations

from .arqana import ArqanaScraper
from .base import Scraper
from .goffs_ie import GoffsIEScraper
from .goffs_uk import GoffsUKScraper
from .tattersalls import TattersallsScraper

SCRAPERS: dict[str, type[Scraper]] = {
    "tattersalls": TattersallsScraper,
    "goffs-uk": GoffsUKScraper,
    "goffs-ie": GoffsIEScraper,
    "arqana": ArqanaScraper,
}

__all__ = [
    "Scraper",
    "SCRAPERS",
    "TattersallsScraper",
    "GoffsUKScraper",
    "GoffsIEScraper",
    "ArqanaScraper",
]
