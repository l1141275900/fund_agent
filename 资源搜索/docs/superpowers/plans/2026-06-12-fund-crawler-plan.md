# Fund Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-source crawler that collects Chinese mutual fund research reports, market analysis, and fund manager commentary as JSONL for downstream RAG use, with a 1GB total size cap.

**Architecture:** Async Python crawler with httpx + BeautifulSoup. A base class provides rate limiting, retry, UA rotation, and dedup across all crawlers. Four source-specific crawlers (EastMoney research, Tiantian fund news, Morningstar CN, AMAC) feed into a unified JSONL storage layer. A CLI orchestrator supports full and incremental modes.

**Tech Stack:** Python 3.11+, httpx (async HTTP), beautifulsoup4 + lxml (HTML parsing), Playwright (JS fallback for Morningstar), asyncio (concurrency)

---

## File Map

| File | Responsibility |
|---|---|
| `requirements.txt` | Python dependencies |
| `src/__init__.py` | Package marker |
| `src/crawlers/__init__.py` | Crawler registry |
| `src/crawlers/base.py` | RateLimiter, BaseCrawler (retry, UA, dedup, size cap) |
| `src/crawlers/eastmoney_research.py` | EastMoney research report listing + content |
| `src/crawlers/eastmoney_fund.py` | Tiantian fund news + fund manager articles |
| `src/crawlers/morningstar.py` | Morningstar CN articles (HTTP + Playwright) |
| `src/crawlers/amac.py` | AMAC research/publications (HTML scrape) |
| `src/storage.py` | JSONL writer with dedup, size tracking, state persistence |
| `src/pipeline.py` | Orchestrator: sequential sources, concurrent within source |
| `run.py` | CLI entry: argparse, --source, --incremental |

---

### Task 1: Project setup and dependencies

**Files:**
- Create: `requirements.txt`
- Create: `src/__init__.py`
- Create: `src/crawlers/__init__.py`

- [ ] **Step 1: Write requirements.txt**

```text
httpx>=0.27.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
playwright>=1.40.0
tqdm>=4.66.0
```

- [ ] **Step 2: Create package markers**

`src/__init__.py` — empty file

`src/crawlers/__init__.py` — empty file

- [ ] **Step 3: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: All packages install successfully

- [ ] **Step 4: Install Playwright browser**

Run: `playwright install chromium`
Expected: Chromium browser downloaded

- [ ] **Step 5: Verify imports**

```python
python -c "import httpx; import bs4; import lxml; print('OK')"
```
Expected: `OK`

---

### Task 2: Base crawler (rate limiter, retry, UA, dedup)

**Files:**
- Create: `src/crawlers/base.py`

- [ ] **Step 1: Write `src/crawlers/base.py`**

```python
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
            self._last_fill[domain] = now
            if self._tokens[domain] < 1.0:
                wait = (1.0 - self._tokens[domain]) / self.rate
                await asyncio.sleep(wait)
                self._tokens[domain] = 0.0
            else:
                self._tokens[domain] -= 1.0


class BaseCrawler:
    source: str = "base"
    rate: float = 2.0
    max_retries: int = 3
    base_delay: float = 1.0

    def __init__(self):
        self._limiter = RateLimiter(self.rate)
        self._seen: set[str] = set()
        self._seen_file = STATE_DIR / f"{self.source}_seen.txt"
        self._checkpoint_file = STATE_DIR / f"{self.source}_checkpoint.txt"
        self._robot_checked: dict[str, bool] = {}
        self._total_bytes = 0
        self._load_state()

    def _load_state(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if self._seen_file.exists():
            with open(self._seen_file, "r", encoding="utf-8") as f:
                self._seen = set(line.strip() for line in f if line.strip())

    def _save_seen(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(self._seen_file, "w", encoding="utf-8") as f:
            for url in self._seen:
                f.write(url + "\n")

    def _save_checkpoint(self, value: str):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
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

    async def fetch(self, client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response | None:
        domain = domain_key(url)
        for attempt in range(self.max_retries):
            try:
                await self._limiter.acquire(domain)
                headers = kwargs.pop("headers", {})
                headers.setdefault("User-Agent", self._random_ua())
                resp = await client.get(url, headers=headers, follow_redirects=True, **kwargs)
                if resp.status_code >= 500:
                    wait = self.base_delay * (2 ** attempt)
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code == 429:
                    wait = self.base_delay * (4 ** attempt)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException):
                if attempt < self.max_retries - 1:
                    wait = self.base_delay * (2 ** attempt)
                    await asyncio.sleep(wait)
        return None

    async def crawl(self) -> list[dict]:
        raise NotImplementedError
```

- [ ] **Step 2: Verify base module imports**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from crawlers.base import BaseCrawler, RateLimiter; print('OK')"`
Expected: `OK`

---

### Task 3: Storage layer

**Files:**
- Create: `src/storage.py`

- [ ] **Step 1: Write `src/storage.py`**

```python
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent / "data"


class JsonlWriter:
    """Append-only JSONL writer with size tracking and dedup."""

    def __init__(self, source: str, max_bytes: int = 1 * 1024 * 1024 * 1024):
        self.source = source
        self.max_bytes = max_bytes
        self._path = DATA_DIR / f"{source}.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._written_ids: set[str] = set()
        self._total_bytes = 0
        self._load_existing()

    def _load_existing(self):
        if not self._path.exists():
            return
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    self._written_ids.add(record.get("id", ""))
                except json.JSONDecodeError:
                    continue
        self._total_bytes = self._path.stat().st_size

    def write(self, record: dict) -> bool:
        """Write a record if not duplicate and within size limit. Returns True if written."""
        rid = record.get("id", hashlib.md5(f"{self.source}:{record.get('url','')}".encode()).hexdigest())
        if rid in self._written_ids:
            return False
        record["id"] = rid
        record.setdefault("crawled_at", datetime.now(timezone.utc).isoformat())
        record.setdefault("source", self.source)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        line_bytes = len(line.encode("utf-8"))
        if self._total_bytes + line_bytes > self.max_bytes:
            return False
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line)
        self._written_ids.add(rid)
        self._total_bytes += line_bytes
        return True

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def count(self) -> int:
        return len(self._written_ids)

    def size_exceeded(self) -> bool:
        return self._total_bytes >= self.max_bytes


def merge_all(output_path: str | None = None):
    """Merge all per-source JSONL files into one, deduplicating by id."""
    output_path = Path(output_path or DATA_DIR / "all.jsonl")
    seen = set()
    count = 0
    with open(output_path, "w", encoding="utf-8") as out:
        for jsonl_file in sorted(DATA_DIR.glob("*.jsonl")):
            if jsonl_file.name == "all.jsonl":
                continue
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rid = record.get("id", "")
                    if rid in seen:
                        continue
                    seen.add(rid)
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1
    print(f"Merged {count} records -> {output_path}")
```

- [ ] **Step 2: Verify storage module imports**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from storage import JsonlWriter; print('OK')"`
Expected: `OK`

---

### Task 4: EastMoney research reports crawler

**Files:**
- Create: `src/crawlers/eastmoney_research.py`

- [ ] **Step 1: Write `src/crawlers/eastmoney_research.py`**

```python
import asyncio
import json
import re
import time
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .base import BaseCrawler, make_id

# API for EastMoney research report list
REPORT_LIST_URL = "https://reportapi.eastmoney.com/report/list"
# Detail page base (content page, not PDF)
REPORT_DETAIL_URL = "https://data.eastmoney.com/report/zw/{}.html"


class EastMoneyResearchCrawler(BaseCrawler):
    source = "eastmoney_research"
    rate = 1.5  # slightly slower to be polite

    async def _fetch_page(self, client: httpx.AsyncClient, page_no: int, page_size: int = 50) -> list[dict]:
        params = {
            "industryCode": "all",
            "pageSize": str(page_size),
            "pageNo": str(page_no),
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "rcode": "",
            "beginTime": "",
            "endTime": "",
            "sort": "publishDate",
            "sortType": "1",
        }
        resp = await self.fetch(client, REPORT_LIST_URL, params=params)
        if resp is None:
            return []
        text = resp.text
        # response is JSONP: callback_name({...})
        match = re.search(r'\((.*)\)', text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []
        if not data.get("success"):
            return []
        items = data.get("data", [])
        reports = []
        for item in items:
            reports.append({
                "title": item.get("title", ""),
                "author": item.get("orgName", ""),
                "publish_date": item.get("publishDate", ""),
                "encode_url": item.get("encodeUrl", ""),
                "info_code": item.get("infoCode", ""),
                "industry_name": item.get("industryName", ""),
                "stock_name": item.get("stockName", ""),
                "org_name": item.get("orgName", ""),
            })
        return reports

    async def _fetch_detail(self, client: httpx.AsyncClient, info_code: str) -> str:
        """Fetch report abstract/summary from detail page."""
        url = REPORT_DETAIL_URL.format(info_code)
        resp = await self.fetch(client, url)
        if resp is None:
            return ""
        soup = BeautifulSoup(resp.text, "lxml")
        content_div = soup.select_one(".report-content, .ctx-content, .article-content")
        if content_div:
            return content_div.get_text("\n", strip=True)
        return ""

    async def crawl(self) -> list[dict]:
        results = []
        async with httpx.AsyncClient(timeout=30) as client:
            page = 1
            while True:
                if self.size_exceeded():
                    break
                reports = await self._fetch_page(client, page)
                if not reports:
                    break
                for r in reports:
                    if self.size_exceeded():
                        break
                    url = REPORT_DETAIL_URL.format(r["info_code"])
                    if self.is_seen(url):
                        continue
                    # fetch detail content
                    content = await self._fetch_detail(client, r["info_code"])
                    if not content:
                        content = r.get("title", "")
                    record = {
                        "id": make_id(self.source, url),
                        "source": self.source,
                        "url": url,
                        "title": r["title"],
                        "author": r["author"],
                        "published_at": r["publish_date"],
                        "content": content,
                        "tags": [r.get("industry_name", ""), r.get("stock_name", "")],
                        "category": "研报",
                    }
                    record_len = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
                    self.add_bytes(record_len)
                    self.mark_seen(url)
                    results.append(record)
                page += 1
                if page > 200:
                    break
                await asyncio.sleep(0.5)
        return results
```

- [ ] **Step 2: Verify the crawler module**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from crawlers.eastmoney_research import EastMoneyResearchCrawler; print('OK')"`
Expected: `OK`

---

### Task 5: EastMoney fund news (Tiantian) crawler

**Files:**
- Create: `src/crawlers/eastmoney_fund.py`

- [ ] **Step 1: Write `src/crawlers/eastmoney_fund.py`**

```python
import asyncio
import json
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .base import BaseCrawler, make_id

# Tiantian fund news listing - EastMoney fund news API
FUND_NEWS_API = "https://fund.eastmoney.com/api/News/NewsList"
FUND_NEWS_DETAIL_BASE = "https://fund.eastmoney.com/a/{}.html"


class EastMoneyFundCrawler(BaseCrawler):
    source = "eastmoney_fund"
    rate = 1.5

    async def _fetch_news_page(self, client: httpx.AsyncClient, page_no: int, page_size: int = 50) -> list[dict]:
        params = {
            "pageIndex": str(page_no),
            "pageSize": str(page_size),
            "type": "",
        }
        resp = await self.fetch(client, FUND_NEWS_API, params=params)
        if resp is None:
            return []
        text = resp.text
        match = re.search(r"var apidata=\{.*?\}", text, re.DOTALL)
        if not match:
            # try direct JSON
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return []
        else:
            # extract JSON from var declaration
            json_str = match.group(0).replace("var apidata=", "")
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                return []
        items = data.get("Data", []) if isinstance(data, dict) else []
        if not items:
            return []
        news_list = []
        for item in items:
            news_list.append({
                "title": item.get("Title", ""),
                "url_id": str(item.get("Id", "")),
                "publish_date": item.get("ShowDate", ""),
                "source_name": item.get("Source", ""),
                "summary": item.get("Summary", ""),
            })
        return news_list

    async def _fetch_detail(self, client: httpx.AsyncClient, url_id: str) -> str:
        url = FUND_NEWS_DETAIL_BASE.format(url_id)
        resp = await self.fetch(client, url)
        if resp is None:
            return ""
        soup = BeautifulSoup(resp.text, "lxml")
        # try common content selectors
        content_el = soup.select_one("#ContentBody, .article-content, .newsContent, .content")
        if content_el:
            # remove scripts and styles
            for tag in content_el.find_all(["script", "style"]):
                tag.decompose()
            return content_el.get_text("\n", strip=True)
        return ""

    async def crawl(self) -> list[dict]:
        results = []
        async with httpx.AsyncClient(timeout=30) as client:
            page = 1
            while True:
                if self.size_exceeded():
                    break
                news_list = await self._fetch_news_page(client, page)
                if not news_list:
                    break
                for n in news_list:
                    if self.size_exceeded():
                        break
                    url = FUND_NEWS_DETAIL_BASE.format(n["url_id"])
                    if self.is_seen(url):
                        continue
                    content = await self._fetch_detail(client, n["url_id"])
                    if not content:
                        content = n.get("summary", n.get("title", ""))
                    record = {
                        "id": make_id(self.source, url),
                        "source": self.source,
                        "url": url,
                        "title": n["title"],
                        "author": n.get("source_name", ""),
                        "published_at": n.get("publish_date", ""),
                        "content": content,
                        "tags": ["基金资讯"],
                        "category": "新闻",
                    }
                    record_len = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
                    self.add_bytes(record_len)
                    self.mark_seen(url)
                    results.append(record)
                page += 1
                if page > 200:
                    break
                await asyncio.sleep(0.5)
        return results
```

- [ ] **Step 2: Verify module import**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from crawlers.eastmoney_fund import EastMoneyFundCrawler; print('OK')"`
Expected: `OK`

---

### Task 6: Morningstar CN crawler

**Files:**
- Create: `src/crawlers/morningstar.py`

- [ ] **Step 1: Write `src/crawlers/morningstar.py`**

```python
import asyncio
import json
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .base import BaseCrawler, make_id

# Morningstar China article listing
MORNINGSTAR_LIST_URL = "https://www.morningstar.cn/op/ashx/news.ashx"
MORNINGSTAR_DETAIL_BASE = "https://www.morningstar.cn/articles/{}.html"


class MorningstarCrawler(BaseCrawler):
    source = "morningstar"
    rate = 1.0  # slowest - most sensitive to scraping

    async def _try_playwright(self, url: str) -> str:
        """Fallback: use Playwright for JS-rendered pages."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return ""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            html = await page.content()
            await browser.close()
            return html
        return ""

    async def _fetch_article_list(self, client: httpx.AsyncClient, page_no: int) -> list[dict]:
        """Fetch article list from Morningstar CN."""
        params = {
            "pageIndex": str(page_no),
            "pageSize": "20",
            "category": "news",
        }
        # Try API first
        resp = await self.fetch(client, MORNINGSTAR_LIST_URL, params=params)
        if resp is None:
            return []
        try:
            data = resp.json()
        except Exception:
            return []
        items = data if isinstance(data, list) else data.get("items", [])
        articles = []
        for item in items:
            articles.append({
                "title": item.get("Title", item.get("title", "")),
                "url": item.get("Url", item.get("url", "")),
                "publish_date": item.get("PublishDate", item.get("publishDate", "")),
                "summary": item.get("Summary", item.get("summary", "")),
                "author": item.get("Author", item.get("author", "")),
            })
        return articles

    async def _fetch_detail(self, client: httpx.AsyncClient, url: str) -> str:
        resp = await self.fetch(client, url)
        html = resp.text if resp else ""
        if not html or len(html) < 500:
            html = await self._try_playwright(url)
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")
        for sel in [".article-body", ".article-content", ".entry-content", "article"]:
            el = soup.select_one(sel)
            if el:
                for tag in el.find_all(["script", "style", "nav"]):
                    tag.decompose()
                return el.get_text("\n", strip=True)
        return ""

    async def crawl(self) -> list[dict]:
        results = []
        async with httpx.AsyncClient(timeout=30) as client:
            page = 1
            while True:
                if self.size_exceeded():
                    break
                articles = await self._fetch_article_list(client, page)
                if not articles:
                    break
                for a in articles:
                    if self.size_exceeded():
                        break
                    detail_url = a["url"]
                    if not detail_url:
                        continue
                    if self.is_seen(detail_url):
                        continue
                    content = await self._fetch_detail(client, detail_url)
                    if not content:
                        content = a.get("summary", a.get("title", ""))
                    record = {
                        "id": make_id(self.source, detail_url),
                        "source": self.source,
                        "url": detail_url,
                        "title": a["title"],
                        "author": a.get("author", "Morningstar"),
                        "published_at": a.get("publish_date", ""),
                        "content": content,
                        "tags": ["基金研究", "晨星"],
                        "category": "研究",
                    }
                    record_len = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
                    self.add_bytes(record_len)
                    self.mark_seen(detail_url)
                    results.append(record)
                page += 1
                if page > 100:
                    break
                await asyncio.sleep(1.0)
        return results
```

- [ ] **Step 2: Verify module import and Playwright availability**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from crawlers.morningstar import MorningstarCrawler; from playwright.async_api import async_playwright; print('OK')"`
Expected: `OK`

---

### Task 7: AMAC crawler (中国证券投资基金业协会)

**Files:**
- Create: `src/crawlers/amac.py`

- [ ] **Step 1: Write `src/crawlers/amac.py`**

```python
import asyncio
import json
from datetime import datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .base import BaseCrawler, make_id

AMAC_BASE = "https://www.amac.org.cn"
AMAC_RESEARCH_LIST = "https://www.amac.org.cn/researchstatistics/research/"
AMAC_PUBLICATION_LIST = "https://www.amac.org.cn/researchstatistics/publication/"


class AmacCrawler(BaseCrawler):
    source = "amac"
    rate = 2.0

    async def _fetch_list_page(self, client: httpx.AsyncClient, url: str, page_no: int) -> list[dict]:
        if page_no == 1:
            page_url = url
        else:
            page_url = f"{url.rstrip('/')}/index_{page_no}.html"
        resp = await self.fetch(client, page_url)
        if resp is None:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        articles = []
        # AMAC list items are usually in <li> or <div> with class containing "list"
        for item in soup.select("ul.list-con li, .news-list li, ul.list li"):
            link = item.find("a")
            if not link:
                continue
            href = link.get("href", "")
            title = link.get_text(strip=True)
            full_url = urljoin(AMAC_BASE, href)
            date_el = item.select_one("span.date, .time, em")
            date_str = date_el.get_text(strip=True) if date_el else ""
            articles.append({
                "title": title,
                "url": full_url,
                "publish_date": date_str,
            })
        return articles

    async def _fetch_detail(self, client: httpx.AsyncClient, url: str) -> str:
        resp = await self.fetch(client, url)
        if resp is None:
            return ""
        soup = BeautifulSoup(resp.text, "lxml")
        for sel in [".txt-content", ".article-content", ".content", "#zoom"]:
            el = soup.select_one(sel)
            if el:
                for tag in el.find_all(["script", "style"]):
                    tag.decompose()
                return el.get_text("\n", strip=True)
        return ""

    async def _crawl_section(self, client: httpx.AsyncClient, list_url: str, category: str) -> list[dict]:
        results = []
        page = 1
        while True:
            if self.size_exceeded():
                break
            articles = await self._fetch_list_page(client, list_url, page)
            if not articles:
                break
            for a in articles:
                if self.size_exceeded():
                    break
                if self.is_seen(a["url"]):
                    continue
                content = await self._fetch_detail(client, a["url"])
                if not content:
                    content = a.get("title", "")
                record = {
                    "id": make_id(self.source, a["url"]),
                    "source": self.source,
                    "url": a["url"],
                    "title": a["title"],
                    "author": "中国证券投资基金业协会",
                    "published_at": a.get("publish_date", ""),
                    "content": content,
                    "tags": ["协会研究", "行业数据"],
                    "category": category,
                }
                record_len = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
                self.add_bytes(record_len)
                self.mark_seen(a["url"])
                results.append(record)
            page += 1
            if page > 50:
                break
            await asyncio.sleep(0.5)
        return results

    async def crawl(self) -> list[dict]:
        results = []
        async with httpx.AsyncClient(timeout=30) as client:
            results += await self._crawl_section(client, AMAC_RESEARCH_LIST, "研究报告")
            results += await self._crawl_section(client, AMAC_PUBLICATION_LIST, "出版物")
        return results
```

- [ ] **Step 2: Verify module import**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from crawlers.amac import AmacCrawler; print('OK')"`
Expected: `OK`

---

### Task 8: Pipeline orchestrator

**Files:**
- Create: `src/pipeline.py`

- [ ] **Step 1: Write `src/pipeline.py`**

```python
import asyncio
import time
from tqdm import tqdm

from .storage import JsonlWriter, MAX_SIZE_BYTES

# Register all crawlers
from .crawlers.eastmoney_research import EastMoneyResearchCrawler
from .crawlers.eastmoney_fund import EastMoneyFundCrawler
from .crawlers.morningstar import MorningstarCrawler
from .crawlers.amac import AmacCrawler

CRAWLER_REGISTRY = {
    "eastmoney_research": EastMoneyResearchCrawler,
    "eastmoney_fund": EastMoneyFundCrawler,
    "morningstar": MorningstarCrawler,
    "amac": AmacCrawler,
}


async def run_crawler(name: str, incremental: bool = False) -> dict:
    """Run a single crawler and write results to JSONL. Returns stats."""
    crawler_cls = CRAWLER_REGISTRY[name]
    crawler = crawler_cls()
    writer = JsonlWriter(name, MAX_SIZE_BYTES)

    print(f"\n[{name}] Starting crawl...")
    if writer.size_exceeded():
        print(f"[{name}] Already at 1GB limit, skipping")
        return {"source": name, "total": 0, "new": 0, "bytes": writer.total_bytes}

    t0 = time.monotonic()
    records = await crawler.crawl()
    elapsed = time.monotonic() - t0

    written = 0
    for record in records:
        if writer.size_exceeded():
            print(f"[{name}] 1GB size limit reached, stopping")
            break
        if writer.write(record):
            written += 1

    crawler._save_seen()
    print(f"[{name}] Done: {written} new / {len(records)} fetched, "
          f"{writer.total_bytes / 1024 / 1024:.1f}MB total, {elapsed:.0f}s")

    return {
        "source": name,
        "total": len(records),
        "new": written,
        "bytes": writer.total_bytes,
        "elapsed": elapsed,
    }


async def run_all(sources: list[str] | None = None, incremental: bool = False):
    """Run all registered crawlers sequentially."""
    if sources is None:
        sources = list(CRAWLER_REGISTRY.keys())

    print(f"{'Incremental' if incremental else 'Full'} crawl for: {sources}")
    print(f"1GB size limit, per-source JSONL files -> data/*.jsonl\n")

    all_stats = []
    for name in sources:
        if name not in CRAWLER_REGISTRY:
            print(f"Unknown source: {name}, skipping")
            continue
        stats = await run_crawler(name, incremental)
        all_stats.append(stats)

    print("\n" + "=" * 50)
    total_new = sum(s["new"] for s in all_stats)
    total_bytes = sum(s["bytes"] for s in all_stats)
    print(f"All done. {total_new} new records, {total_bytes / 1024 / 1024:.1f}MB total")
    return all_stats
```

- [ ] **Step 2: Verify pipeline import**

Run: `python -c "import sys; sys.path.insert(0, 'src'); from pipeline import run_all, CRAWLER_REGISTRY; print(f'OK: {list(CRAWLER_REGISTRY.keys())}')"`
Expected: `OK: ['eastmoney_research', 'eastmoney_fund', 'morningstar', 'amac']`

---

### Task 9: CLI entry point

**Files:**
- Create: `run.py`

- [ ] **Step 1: Write `run.py`**

```python
"""Fund investment research crawler.

Usage:
    python run.py                          # Full crawl, all sources
    python run.py --source eastmoney_fund  # Single source
    python run.py --incremental            # Incremental update
    python run.py --list                   # List available sources
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from pipeline import run_all, CRAWLER_REGISTRY


def main():
    parser = argparse.ArgumentParser(description="Fund investment research crawler")
    parser.add_argument("--source", type=str, help="Crawl a single source")
    parser.add_argument("--incremental", action="store_true", help="Incremental crawl (skip already-seen URLs)")
    parser.add_argument("--list", action="store_true", help="List available sources")
    args = parser.parse_args()

    if args.list:
        print("Available sources:")
        for name, cls in CRAWLER_REGISTRY.items():
            print(f"  {name}: {cls.__doc__ or cls.__name__}")
        return

    sources = [args.source] if args.source else None
    asyncio.run(run_all(sources, args.incremental))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test CLI help**

Run: `python run.py --help`
Expected: Usage text with --source, --incremental, --list options

- [ ] **Step 3: Test --list**

Run: `python run.py --list`
Expected: Lists all 4 sources

---

### Task 10: End-to-end smoke test

- [ ] **Step 1: Run a single-source crawl for AMAC (simplest source)**

Run: `python run.py --source amac`
Expected: Crawler runs, creates `data/amac.jsonl`, prints stats (may have 0 records if network blocked, but should not crash)

- [ ] **Step 2: Verify JSONL output format**

Run: `python -c "import json; [print(json.loads(line)['source']) for line in open('data/amac.jsonl', encoding='utf-8')[:3]]"`
Expected: Prints `amac` for each record

- [ ] **Step 3: Run EastMoney research crawl**

Run: `python run.py --source eastmoney_research`
Expected: Creates `data/eastmoney_research.jsonl` with research report records

- [ ] **Step 4: Check total data size**

Run: `python -c "from pathlib import Path; total=sum(f.stat().st_size for f in Path('data').glob('*.jsonl')); print(f'{total/1024/1024:.1f}MB')"`
Expected: Reports size < 1024MB
