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
