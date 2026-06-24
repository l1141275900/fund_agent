import asyncio
import time

from storage import JsonlWriter
from crawlers.base import MAX_SIZE_BYTES
from crawlers.eastmoney_research import EastMoneyResearchCrawler
from crawlers.eastmoney_fund import EastMoneyFundCrawler
from crawlers.morningstar import MorningstarCrawler
from crawlers.amac import AmacCrawler

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
