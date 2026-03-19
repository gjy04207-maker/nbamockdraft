from __future__ import annotations

from typing import List

from .base import Fetcher


class BasketballExcelFetcher(Fetcher):
    def planned_urls(self) -> List[str]:
        return []
