import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
import sys
from pathlib import Path

from seasons import season_window

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"

async def fetch_text(page, url: str) -> str:
    await page.goto(url, wait_until="networkidle")
    return await page.locator("body").inner_text()

async def main():
    years = season_window(keep=5)

    news_dir = RAW_DIR / "news"
    news_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        f1_news_url = "https://www.formula1.com/en/latest.html"
        lequipe_url = "https://www.lequipe.fr/Formule-1/"

        f1_text = await fetch_text(page, f1_news_url)
        lequipe_text = await fetch_text(page, lequipe_url)

        payload = {
            "season_window": years,
            "formula1_news": {
                "url": f1_news_url,
                "raw_text": f1_text,
            },
            "lequipe_news": {
                "url": lequipe_url,
                "raw_text": lequipe_text,
            },
        }

        (news_dir / "current_news.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())