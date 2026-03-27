"""
crawl_race_results.py — Scrape individual race result pages (formula1.com)
==========================================================================
For each season in the rolling window (default 5 seasons), this script:

  1. Visits /en/results/{year}/races to discover per-race URLs.
  2. Visits each /en/results/{year}/races/{id}/{slug}/race-result page.
  3. Saves the raw inner_text of each results table as JSON.

Output layout:
  data/raw/formula1/{year}/race_results/{slug}.json
    {"season": year, "race": slug, "source": url, "raw_text": "..."}

Caching: existing files are skipped (safe to re-run).
Politeness: 1.5 s delay between pages, explicit User-Agent.

Usage:
  python src/crawl/crawl_race_results.py          # all seasons in window
  python src/crawl/crawl_race_results.py --year 2024
"""

import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from seasons import season_window

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "formula1"
DELAY   = 1.5   # seconds between page loads


async def get_race_links(page, year: int) -> list[dict]:
    """
    Visit the season races list and return a list of
    {'slug': str, 'url': str} dicts for each race-result page.
    """
    list_url = f"https://www.formula1.com/en/results/{year}/races"
    await page.goto(list_url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(2_500)

    # Extract all hrefs pointing to a race-result sub-page
    links = await page.eval_on_selector_all(
        "a[href*='race-result']",
        "els => els.map(e => e.href)"
    )

    seen, result = set(), []
    for href in links:
        href = href.strip()
        if href in seen:
            continue
        seen.add(href)
        # URL shape: .../results/{year}/races/{id}/{slug}/race-result
        parts = [p for p in href.split("/") if p]
        if len(parts) >= 2:
            slug = parts[-2]          # one segment before "race-result"
        else:
            slug = href.rsplit("/", 2)[-2]
        result.append({"slug": slug, "url": href})

    return result


async def fetch_race_result(page, url: str) -> str:
    """Return the inner_text of the race result page."""
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(2_500)
    return await page.locator("body").inner_text()


async def crawl_year(page, year: int) -> None:
    out_dir = RAW_DIR / str(year) / "race_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[{year}] Discovering race URLs …")
    try:
        races = await get_race_links(page, year)
    except Exception as exc:
        print(f"  [ERROR] Could not load race list for {year}: {exc}")
        return

    print(f"  Found {len(races)} race(s)")

    for race in races:
        slug = race["slug"]
        url  = race["url"]
        dest = out_dir / f"{slug}.json"

        if dest.exists():
            print(f"  [skip] {slug} (already cached)")
            continue

        print(f"  Fetching {slug} …", end=" ", flush=True)
        try:
            raw_text = await fetch_race_result(page, url)
            payload  = {
                "season":   year,
                "race":     slug,
                "source":   url,
                "raw_text": raw_text,
            }
            dest.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print("OK")
        except Exception as exc:
            print(f"ERROR: {exc}")

        await asyncio.sleep(DELAY)


async def main(years: list[int]) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (compatible; f1-kg-project/3.0; "
                "educational use; github.com)"
            )
        )
        page = await context.new_page()

        for year in sorted(years):
            await crawl_year(page, year)

        await browser.close()

    print("\nDone. Run extract_race_results.py to parse the raw files.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None,
                        help="Crawl a single season (e.g. 2024)")
    parser.add_argument("--keep", type=int, default=10,
                        help="Number of seasons to crawl (default: 10)")
    args = parser.parse_args()
    if args.year:
        years_to_crawl = [args.year]
    else:
        years_to_crawl = season_window(keep=args.keep)
    asyncio.run(main(years_to_crawl))
