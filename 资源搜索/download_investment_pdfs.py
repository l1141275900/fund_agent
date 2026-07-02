"""Download investment methodology PDFs for 5 investment masters.

Supported sources:
  - Buffett: Berkshire Hathaway official letters (HTML saved as text)
  - Soros: Direct PDF links from finance forums
  - Bogle: Vanguard official PDFs
  - 段永平: Direct PDF links + baidu pan references
  - 范勇宏: Direct links from book sites
"""

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

OUTPUT_DIR = Path(__file__).parent / "data" / "investment_masters"

MASTERS = {
    "Buffett_Warren": {
        "name_cn": "沃伦·巴菲特",
        "pdf_urls": [
            # Berkshire official letters page — we scrape all year links
            "https://www.berkshirehathaway.com/letters/letters.html",
        ],
        "direct_links": [
            # Direct PDF links if available
        ],
        "notes": "巴菲特致股东信（1977-2024），官方HTML页面，脚本会下载为文本文件",
    },
    "Soros_George": {
        "name_cn": "乔治·索罗斯",
        "pdf_urls": [
            # Edelweiss book summary (free, legal, 3-page summary)
            "https://www.edelweissmf.com/Files/Insigths/booksummary/pdf/EdelweissMF-BookSummary-Alchemyoffinance.pdf",
        ],
        "direct_links": [
            "https://down.pinggu.org/html/20091013/2081.html",
            "https://down.pinggu.org/html/20090915/222.html",
        ],
        "notes": "《金融炼金术》Edelweiss摘要PDF已下载(免费)，完整版需经管之家注册",
    },
    "Bogle_John": {
        "name_cn": "约翰·博格尔",
        "pdf_urls": [
            "https://corporate.vanguard.com/content/dam/corp/research/pdf/vanguards_principles_for_investing_success.pdf",
            "https://corporate.vanguard.com/content/dam/corp/research/pdf/ISGTRF_112021_Online.pdf",
        ],
        "direct_links": [
            # Internet Archive — legal, borrowable digital copy
            "https://archive.org/details/littlebookofcomm0000bogl_o5f9",
        ],
        "notes": "Vanguard官方PDF(已下载) + Internet Archive可借阅THE LITTLE BOOK OF COMMON SENSE INVESTING",
    },
    "Duan_Yongping": {
        "name_cn": "段永平",
        "pdf_urls": [],
        "direct_links": [],
        "cloud_links": [
            {
                "url": "https://pan.baidu.com/s/1tFiRwPTU79fKNjDPxwlhsA",
                "code": "g743",
                "desc": "段永平投资系列合集（含问答录+演讲合集+博客文章+传记）",
            },
        ],
        "notes": "雪球有免费专刊PDF可直接下载，百度网盘合集(提取码g743)需手动下载",
    },
    "Fan_Yonghong": {
        "name_cn": "范勇宏",
        "pdf_urls": [],
        "direct_links": [
            "https://tstrs.me/book/d1d8486a53f",
        ],
        "notes": "《基金长青》EPUB/MOBI格式（非PDF），记录华夏基金15年投资历程",
    },
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


async def download_file(client: httpx.AsyncClient, url: str, dest: Path) -> bool:
    """Download a single file. Returns True on success."""
    if dest.exists():
        print(f"  [skip] already exists: {dest.name}")
        return False
    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        size_kb = len(resp.content) / 1024
        print(f"  [ok] {dest.name} ({size_kb:.0f}KB)")
        return True
    except Exception as e:
        print(f"  [fail] {url}: {e}")
        return False


async def scrape_berkshire_letters(client: httpx.AsyncClient, url: str, dest_dir: Path):
    """Scrape all Buffett letters from the Berkshire letters page + PDF letters 2004+."""
    print(f"\n  Fetching letters index: {url}")
    resp = await client.get(url, headers={"User-Agent": USER_AGENT})
    if resp.status_code != 200:
        print(f"  Failed: {resp.status_code}")
        return
    soup = BeautifulSoup(resp.text, "lxml")
    downloaded = 0
    for link in soup.find_all("a"):
        href = link.get("href", "")
        if re.match(r"\d{4}\.html?", href) or re.match(r"\d{4}\.pdf", href):
            full_url = urljoin(url, href)
            dest = dest_dir / href
            if await download_file(client, full_url, dest):
                downloaded += 1
            await asyncio.sleep(0.3)
    print(f"  Downloaded {downloaded} HTML letters")

    # Download PDF letters (2004-2024)
    print(f"  Downloading PDF letters (2004-2024)...")
    pdf_downloaded = 0
    for year in range(2004, 2025):
        pdf_url = f"https://www.berkshirehathaway.com/letters/{year}ltr.pdf"
        dest = dest_dir / f"{year}ltr.pdf"
        if await download_file(client, pdf_url, dest):
            pdf_downloaded += 1
        await asyncio.sleep(0.3)
    print(f"  Downloaded {pdf_downloaded} PDF letters")


async def scrape_page_for_pdfs(client: httpx.AsyncClient, page_url: str, dest_dir: Path):
    """Scrape a page looking for PDF links."""
    print(f"\n  Scanning for PDFs: {page_url}")
    try:
        resp = await client.get(page_url, headers={"User-Agent": USER_AGENT}, timeout=15)
        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code}")
            return
    except Exception as e:
        print(f"  Error: {e}")
        return
    soup = BeautifulSoup(resp.text, "lxml")
    count = 0
    for link in soup.find_all("a", href=re.compile(r"\.pdf$", re.I)):
        href = link["href"]
        full_url = urljoin(page_url, href)
        name = Path(urlparse(full_url).path).name
        dest = dest_dir / name
        if await download_file(client, full_url, dest):
            count += 1
        await asyncio.sleep(0.3)
    if count == 0:
        print(f"  No PDF links found on this page")
    else:
        print(f"  Downloaded {count} PDFs")


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for key, info in MASTERS.items():
            dest_dir = OUTPUT_DIR / key
            dest_dir.mkdir(parents=True, exist_ok=True)
            print(f"\n{'=' * 60}")
            print(f"  {info['name_cn']} ({key})")
            print(f"  {info['notes']}")
            print(f"{'=' * 60}")

            # Download direct PDF links
            for url in info["direct_links"]:
                print(f"\n  Direct URL: {url}")
                if url.endswith(".pdf"):
                    name = Path(urlparse(url).path).name
                    await download_file(client, url, dest_dir / name)
                elif "letters.html" in url and key == "Buffett_Warren":
                    await scrape_berkshire_letters(client, url, dest_dir)
                else:
                    await scrape_page_for_pdfs(client, url, dest_dir)
                await asyncio.sleep(0.5)

            # Try to scrape PDF list pages
            for url in info["pdf_urls"]:
                if url.endswith(".pdf"):
                    name = Path(urlparse(url).path).name
                    await download_file(client, url, dest_dir / name)
                elif "letters" in url and key == "Buffett_Warren":
                    await scrape_berkshire_letters(client, url, dest_dir)
                else:
                    await scrape_page_for_pdfs(client, url, dest_dir)
                await asyncio.sleep(0.5)

            # Record cloud storage links for manual download
            if "cloud_links" in info:
                notes_file = dest_dir / "_manual_download_links.json"
                with open(notes_file, "w", encoding="utf-8") as f:
                    json.dump(info["cloud_links"], f, ensure_ascii=False, indent=2)
                print(f"\n  Cloud links saved to: {notes_file}")

    print(f"\n{'=' * 60}")
    print("All done!")
    print(f"Files saved to: {OUTPUT_DIR}")
    print("Check _manual_download_links.json files for baidu pan links")


if __name__ == "__main__":
    asyncio.run(main())
