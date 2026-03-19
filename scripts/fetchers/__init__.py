from __future__ import annotations

from .base import Fetcher, SourceConfig
from .nba import NbaFetcher
from .espn import EspnFetcher
from .basketball_reference import BasketballReferenceFetcher
from .fanspo import FanspoFetcher
from .tankathon import TankathonFetcher
from .noceilings import NoCeilingsFetcher
from .barttorvik import BarttorvikFetcher
from .basketball_excel import BasketballExcelFetcher

FETCHER_REGISTRY = {
    "nba.com": NbaFetcher,
    "espn.com": EspnFetcher,
    "basketball-reference.com": BasketballReferenceFetcher,
    "fanspo.com": FanspoFetcher,
    "tankathon.com": TankathonFetcher,
    "noceilingsnba.com": NoCeilingsFetcher,
    "barttorvik.com": BarttorvikFetcher,
    "basketball-excel.com": BasketballExcelFetcher,
}

__all__ = [
    "Fetcher",
    "SourceConfig",
    "FETCHER_REGISTRY",
]
