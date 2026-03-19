from __future__ import annotations

from typing import List

from .base import Fetcher


class BasketballReferenceFetcher(Fetcher):
    def planned_urls(self) -> List[str]:
        # Default deny until robots.txt is verified and paths are set.
        return []
