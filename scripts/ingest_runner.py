from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import sys

from fetchers import FETCHER_REGISTRY, SourceConfig

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "scripts" / "ingest_config.json"
OUT_DIR = ROOT / "data" / "ingest" / "raw"
STATE_PATH = ROOT / "data" / "ingest" / "state.json"

OUT_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_config() -> List[SourceConfig]:
    config = json.loads(CONFIG_PATH.read_text())
    return [SourceConfig(**s) for s in config.get("sources", [])]


def load_state() -> Dict[str, float]:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text())


def save_state(state: Dict[str, float]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def should_run(source: Source, state: Dict[str, float]) -> bool:
    last = state.get(source.name, 0)
    return (time.time() - last) >= source.cadence_minutes * 60


def fetch_with_compliance(source: SourceConfig) -> Dict:
    fetcher_cls = FETCHER_REGISTRY.get(source.name)
    if not fetcher_cls:
        return {
            "source": source.name,
            "type": source.type,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "items": [],
            "notes": f"Missing fetcher for {source.name}",
            "status": "skipped",
        }

    fetcher = fetcher_cls(source)
    try:
        robots = fetcher.validate_robots()
    except Exception as exc:
        return {
            "source": source.name,
            "type": source.type,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "items": [],
            "notes": f"Robots.txt check failed: {exc}",
            "status": "robots_check_failed",
        }
    if any(allowed is False for allowed in robots.values()):
        return {
            "source": source.name,
            "type": source.type,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "items": [],
            "notes": "Robots.txt disallows one or more planned URLs.",
            "status": "blocked_by_robots",
            "robots": robots,
        }

    try:
        payload = fetcher.fetch()
    except Exception as exc:
        return {
            "source": source.name,
            "type": source.type,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "items": [],
            "notes": f"Fetch failed: {exc}",
            "status": "fetch_failed",
            "robots": robots,
        }
    payload["robots"] = robots
    return payload


def write_snapshot(source: Source, payload: Dict) -> None:
    ts = payload["fetched_at"].replace(":", "").replace("-", "")
    filename = f"{source.name.replace(' ', '_')}_{ts}.json"
    (OUT_DIR / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def run():
    sources = load_config()
    state = load_state()

    for source in sorted(sources, key=lambda s: s.priority):
        if not should_run(source, state):
            continue
        payload = fetch_with_compliance(source)
        write_snapshot(source, payload)
        state[source.name] = time.time()

    save_state(state)


if __name__ == "__main__":
    run()
