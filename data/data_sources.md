# Data Sources — Formula 1 KG Project

## Domain
This project focuses on Formula 1, with a knowledge graph centred on drivers, teams, seasons, Grand Prix races, circuits, and race results.

## Seasons Covered
The project maintains a **rolling 5-season window**: the current season plus the four previous ones. When a new season begins, the oldest season's raw data is automatically purged by `src/crawl/crawl_formula1.py` (via `purge_old_seasons()`).

Current window: **2022 · 2023 · 2024 · 2025 · 2026**

## Main Sources

### 1. Formula1.com
- **URL:** https://www.formula1.com/
- **Type:** Semi-structured (JavaScript-rendered pages, scraped with Playwright)
- **Data targeted:**
  - Driver standings: name, nationality, team, season points & position
  - Team (constructor) standings: team name, season points & position
  - Race calendar: Grand Prix names, round numbers
- **Scripts:** `src/crawl/crawl_formula1.py`, `src/ie/extract_drivers.py`, `src/ie/extract_teams.py`

### 2. L'Équipe — Formule 1
- **URL:** https://www.lequipe.fr/Formule-1/
- **Type:** Unstructured text (news articles)
- **Data targeted:**
  - Contextual race information
  - Textual mentions of drivers and teams
  - Event descriptions and additional relations extracted from text
- **Script:** `src/crawl/collect_news.py`

## Why Two Sources?
Formula1.com provides structured factual data (standings, results). L'Équipe provides unstructured textual data, allowing us to demonstrate information extraction from two different source types and enrich the knowledge graph with contextual relations.

## Crawling Ethics
- A `User-Agent` header identifying the project is sent with every request.
- A polite delay (`wait_for_timeout(2500 ms)`) is applied between page loads.
- `robots.txt` is respected for both sources.
- Raw data is stored locally and **not redistributed**.
