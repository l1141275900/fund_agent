import asyncio
import hashlib
import re
import time
import random
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from collections import defaultdict

import httpx

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

MAX_SIZE_BYTES = 1 * 1024 * 1024 * 1024  # 1GB
DATA_DIR = Path(__file__).parent.parent.parent / "data"
STATE_DIR = DATA_DIR / "state"


def domain_key(url: str) -> str:
    return urlparse(url).netloc


def make_id(source: str, url: str) -> str:
    return hashlib.md5(f"{source}:{url}".encode()).hexdigest()


class RateLimiter:
    """Token bucket per domain."""

    def __init__(self, rate: float = 2.0):
        self.rate = rate
        self._tokens: dict[str, float] = defaultdict(lambda: rate)
        self._last_fill: dict[str, float] = defaultdict(time.monotonic)
        self._lock = asyncio.Lock()

    async def acquire(self, domain: str):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_fill[domain]
            self._tokens[domain] = min(self.rate, self._tokens[domain] + elapsed * self.rate)
            if self._tokens[domain] < 1.0:
                wait = (1.0 - self._tokens[domain]) / self.rate
                await asyncio.sleep(wait)
                self._tokens[domain] = 0.0
                self._last_fill[domain] = time.monotonic()
            else:
                self._tokens[domain] -= 1.0
                self._last_fill[domain] = now


class BaseCrawler:
    source: str = "base"
    rate: float = 2.0
    max_retries: int = 3
    base_delay: float = 1.0

    def __init__(self):
        self._limiter = RateLimiter(self.rate)
        self._seen: set[str] = set()
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._seen_file = STATE_DIR / f"{self.source}_seen.txt"
        self._checkpoint_file = STATE_DIR / f"{self.source}_checkpoint.txt"
        self._robot_checked: dict[str, bool] = {}
        self._total_bytes = 0
        self._load_state()

    def _load_state(self):
        if self._seen_file.exists():
            with open(self._seen_file, "r", encoding="utf-8") as f:
                self._seen = set(line.strip() for line in f if line.strip())

    def _save_seen(self):
        with open(self._seen_file, "w", encoding="utf-8") as f:
            for url in self._seen:
                f.write(url + "\n")

    def _save_checkpoint(self, value: str):
        with open(self._checkpoint_file, "w", encoding="utf-8") as f:
            f.write(value)

    def _load_checkpoint(self) -> str | None:
        if self._checkpoint_file.exists():
            return self._checkpoint_file.read_text(encoding="utf-8").strip()
        return None

    def is_seen(self, url: str) -> bool:
        return url in self._seen

    def mark_seen(self, url: str):
        self._seen.add(url)

    def add_bytes(self, n: int):
        self._total_bytes += n

    def size_exceeded(self) -> bool:
        return self._total_bytes >= MAX_SIZE_BYTES

    async def check_robots(self, url: str) -> bool:
        """Check robots.txt for the given URL. Returns True if allowed."""
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base in self._robot_checked:
            return self._robot_checked[base]
        try:
            rp = RobotFileParser()
            rp.set_url(f"{base}/robots.txt")
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{base}/robots.txt", follow_redirects=True)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    rp.allow_all = True
            allowed = rp.can_fetch(USER_AGENTS[0], url)
            self._robot_checked[base] = allowed
            return allowed
        except Exception:
            self._robot_checked[base] = True
            return True

    def _random_ua(self) -> str:
        return random.choice(USER_AGENTS)

    def _backoff(self, attempt: int, status: int | None = None) -> float:
        multiplier = 4 if status == 429 else 2
        return self.base_delay * (multiplier ** attempt)

    async def fetch(self, client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response | None:
        domain = domain_key(url)
        headers = {}
        if "headers" in kwargs:
            headers = dict(kwargs.pop("headers"))
        for attempt in range(self.max_retries):
            try:
                await self._limiter.acquire(domain)
                headers.setdefault("User-Agent", self._random_ua())
                resp = await client.get(url, headers=headers, follow_redirects=True, **kwargs)
                if resp.status_code >= 500:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                if resp.status_code == 429:
                    await asyncio.sleep(self._backoff(attempt, status=429))
                    continue
                resp.raise_for_status()
                return resp
            except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException):
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self._backoff(attempt))
        return None

    async def crawl(self) -> list[dict]:
        raise NotImplementedError
