import asyncio
import json

import httpx

from .base import BaseCrawler, make_id

# API for EastMoney research report list
REPORT_LIST_URL = "https://reportapi.eastmoney.com/report/list"
# Detail page base (content page, not PDF)
REPORT_DETAIL_URL = "https://data.eastmoney.com/report/zw/{}.html"


class EastMoneyResearchCrawler(BaseCrawler):
    source = "eastmoney_research"
    rate = 1.5

    PAGE_LIMIT = 500  # max pages to crawl (500 * 50 = 25000 reports)

    async def _fetch_page(self, client: httpx.AsyncClient, page_no: int, page_size: int = 50) -> list[dict]:
        params = {
            "pageSize": str(page_size),
            "pageNo": str(page_no),
            "qType": "1",
            "beginTime": "",
            "endTime": "",
        }
        resp = await self.fetch(client, REPORT_LIST_URL, params=params)
        if resp is None:
            return []
        try:
            data = resp.json()
        except json.JSONDecodeError:
            return []
        if not data.get("data"):
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
                "researcher": item.get("researcher", ""),
                "report_type": item.get("reportType", ""),
                "attach_pages": item.get("attachPages", ""),
                "em_rating_name": item.get("emRatingName", ""),
            })
        return reports

    async def crawl(self) -> list[dict]:
        results = []
        async with httpx.AsyncClient(timeout=30) as client:
            page = 1
            while page <= self.PAGE_LIMIT:
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
                    # Use metadata as content — full report is PDF, handled separately
                    content_parts = [r["title"]]
                    if r.get("researcher"):
                        content_parts.append(f"研究员: {r['researcher']}")
                    if r.get("org_name"):
                        content_parts.append(f"机构: {r['org_name']}")
                    if r.get("industry_name"):
                        content_parts.append(f"行业: {r['industry_name']}")
                    content = "\n".join(content_parts)
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
                        "extra": {
                            "researcher": r.get("researcher", ""),
                            "report_type": r.get("report_type", ""),
                            "attach_pages": r.get("attach_pages", ""),
                            "em_rating_name": r.get("em_rating_name", ""),
                            "encode_url": r.get("encode_url", ""),
                        },
                    }
                    record_len = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
                    self.add_bytes(record_len)
                    self.mark_seen(url)
                    results.append(record)
                page += 1
                await asyncio.sleep(0.5)
        return results
