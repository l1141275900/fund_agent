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
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return []
        else:
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
        content_el = soup.select_one("#ContentBody, .article-content, .newsContent, .content")
        if content_el:
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
