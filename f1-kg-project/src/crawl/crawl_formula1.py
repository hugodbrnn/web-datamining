import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
from seasons import season_window

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "formula1"

def ensure_dirs(years: list[int]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for y in years:
        (RAW_DIR / str(y)).mkdir(parents=True, exist_ok=True)

def purge_old_seasons(valid_years: list[int]) -> None:
    if not RAW_DIR.exists():
        return
    for child in RAW_DIR.iterdir():
        if child.is_dir():
            try:
                y = int(child.name)
                if y not in valid_years:
                    for sub in child.rglob("*"):
                        if sub.is_file():
                            sub.unlink()
                    for sub in sorted(child.rglob("*"), reverse=True):
                        if sub.is_dir():
                            sub.rmdir()
                    child.rmdir()
            except ValueError:
                continue

async def fetch_page_text(page, url: str) -> str:
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(2500)
    return await page.locator("body").inner_text()

async def collect_drivers(page, year: int) -> dict:
    url = f"https://www.formula1.com/en/results/{year}/drivers"
    try:
        text = await fetch_page_text(page, url)
    except Exception as e:
        text = f"ERROR: {str(e)}"
    return {"season": year, "source": url, "raw_text": text}

async def collect_teams(page, year: int) -> dict:
    url = f"https://www.formula1.com/en/results/{year}/team"
    try:
        text = await fetch_page_text(page, url)
    except Exception as e:
        text = f"ERROR: {str(e)}"
    return {"season": year, "source": url, "raw_text": text}

async def collect_races(page, year: int) -> dict:
    url = f"https://www.formula1.com/en/results/{year}/races"
    try:
        text = await fetch_page_text(page, url)
    except Exception as e:
        text = f"ERROR: {str(e)}"
    return {"season": year, "source": url, "raw_text": text}

async def main():
    years = season_window(keep=5)
    ensure_dirs(years)
    purge_old_seasons(years)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for year in years:
            out_dir = RAW_DIR / str(year)

            drivers = await collect_drivers(page, year)
            teams = await collect_teams(page, year)
            races = await collect_races(page, year)

            (out_dir / "drivers.json").write_text(
                json.dumps(drivers, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            (out_dir / "teams.json").write_text(
                json.dumps(teams, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            (out_dir / "races.json").write_text(
                json.dumps(races, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            print(f"{year} OK")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())