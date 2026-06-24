import asyncio
import json
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .base import BaseCrawler, make_id

MORNINGSTAR_LIST_URL = "https://www.morningstar.cn/op/ashx/news.ashx"
MORNINGSTAR_DETAIL_BASE = "https://www.morningstar.cn/articles/{}.html"


class MorningstarCrawler(BaseCrawler):
    source = "morningstar"
    rate = 1.0

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
        params = {
            "pageIndex": str(page_no),
            "pageSize": "20",
            "category": "news",
        }
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
