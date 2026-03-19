from __future__ import annotations

import re
import time
import urllib.request
import urllib.robotparser as robotparser
from dataclasses import dataclass
from typing import Dict, List

DEFAULT_USER_AGENT = "NBAWriterBot/0.1 (+local dev)"


@dataclass
class SourceConfig:
    name: str
    type: str
    priority: int
    cadence_minutes: int
    base_url: str
    robots_url: str
    allowed_paths: List[str]
    notes: str


class RobotsGate:
    def __init__(self, robots_url: str, user_agent: str = DEFAULT_USER_AGENT):
        self.robots_url = robots_url
        self.user_agent = user_agent
        self.parser = robotparser.RobotFileParser()

    def load(self) -> None:
        self.parser.set_url(self.robots_url)
        self.parser.read()

    def allowed(self, url: str) -> bool:
        return self.parser.can_fetch(self.user_agent, url)


class Fetcher:
    def __init__(self, config: SourceConfig, user_agent: str = DEFAULT_USER_AGENT):
        self.config = config
        self.user_agent = user_agent
        self.robots = RobotsGate(config.robots_url, user_agent)

    def planned_urls(self) -> List[str]:
        # Override in subclass to list real URLs.
        return []

    def validate_robots(self) -> Dict[str, bool]:
        self.robots.load()
        results = {}
        for url in self.planned_urls():
            results[url] = self.robots.allowed(url)
        return results

    def fetch(self) -> Dict:
        # Override in subclass. Default: no-op.
        return {
            "source": self.config.name,
            "type": self.config.type,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "items": [],
            "notes": self.config.notes,
            "status": "not_implemented",
        }

    def get(self, url: str, timeout: int = 15) -> str:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read()
            try:
                text = body.decode("utf-8", errors="ignore")
            except Exception:
                text = body.decode("latin-1", errors="ignore")
        return text

    @staticmethod
    def extract_title(html: str) -> str:
        match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        title = re.sub(r"\s+", " ", match.group(1)).strip()
        return title
