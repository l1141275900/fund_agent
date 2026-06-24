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
