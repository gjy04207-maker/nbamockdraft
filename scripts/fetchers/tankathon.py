from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List

from .base import Fetcher

ROOT = Path(__file__).resolve().parents[2]
MANUAL_DIR = ROOT / "data" / "ingest" / "manual"


class TankathonFetcher(Fetcher):
    def planned_urls(self) -> List[str]:
        return [f"{self.config.base_url}/mock_draft"]

    def fetch(self):
        manual_path = MANUAL_DIR / "tankathon.json"
        if manual_path.exists():
            payload = json.loads(manual_path.read_text(encoding="utf-8"))
            items = payload.get("items", payload) if isinstance(payload, dict) else payload
            return {
                "source": self.config.name,
                "type": self.config.type,
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "items": items,
                "notes": "Loaded from manual snapshot.",
                "status": "manual",
            }
        return {
            "source": self.config.name,
            "type": self.config.type,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "items": [],
            "notes": "Manual snapshot missing: data/ingest/manual/tankathon.json",
            "status": "manual_missing",
        }
