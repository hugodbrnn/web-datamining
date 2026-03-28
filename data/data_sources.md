# Data Sources — Formula 1 KG Project

## Domain
This project focuses on Formula 1, with a knowledge graph centred on drivers, teams, seasons, Grand Prix races, circuits, and race results.

## Seasons Covered
The project maintains a **rolling 12-season window**: the current season plus the eleventh previous ones. When a new season begins, the oldest season's raw data is automatically purged by `src/crawl/crawl_formula1.py` (via `purge_old_seasons()`).

Current window: **2015 to 2026**

## Main Source

### 1. Formula1.com
- **URL:** https://www.formula1.com/
- **Type:** Semi-structured (JavaScript-rendered pages, scraped with Playwright)
- **Data targeted:**
  - Driver standings: name, nationality, team, season points & position
  - Team (constructor) standings: team name, season points & position
  - Race calendar: Grand Prix names, round numbers
- **Scripts:** `src/crawl/crawl_formula1.py`, `src/ie/extract_drivers.py`, `src/ie/extract_teams.py`

Formula1.com provides structured factual data (standings, results). 

## Crawling Ethics
- A `User-Agent` header identifying the project is sent with every request.
- A polite delay (`wait_for_timeout(2500 ms)`) is applied between page loads.
- `robots.txt` is respected for both sources.
- Raw data crawled from publicly accessible pages is included in the repository for reproducibility purposes. No paywalled, login-protected, or personally identifiable data is collected or redistributed.
