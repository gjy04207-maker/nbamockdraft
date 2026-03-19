from __future__ import annotations

import time
from typing import List

from .base import Fetcher


class EspnFetcher(Fetcher):
    def planned_urls(self) -> List[str]:
        return [
            f"{self.config.base_url}/nba",
        ]

    def fetch(self):
        items = []
        for url in self.planned_urls():
            html = self.get(url)
            items.append(
                {
                    "url": url,
                    "title": self.extract_title(html),
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "length": len(html),
                }
            )
            time.sleep(1.5)
        return {
            "source": self.config.name,
            "type": self.config.type,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "items": items,
            "notes": self.config.notes,
            "status": "ok",
        }
