"""
extract_race_results.py — Parse crawled race result pages
==========================================================
Reads data/raw/formula1/{year}/race_results/*.json (produced by
crawl_race_results.py) and writes structured records to
data/interim/race_results_{year}.json.

Output record shape:
  {"season": int, "race": str, "position": int, "number": int,
   "driver": str, "team": str, "laps": int,
   "time_retired": str, "points": int}

Usage:
  python src/ie/extract_race_results.py
"""

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR      = PROJECT_ROOT / "data" / "raw" / "formula1"
OUTPUT_DIR   = PROJECT_ROOT / "data" / "interim"

# ── Team name normalisation ───────────────────────────────────────────────────
# Ordered longest-first so "Red Bull Racing" is matched before "Red Bull".
KNOWN_TEAMS = [
    "Red Bull Racing", "Aston Martin", "Haas F1 Team", "Kick Sauber",
    "Racing Bulls", "McLaren", "Mercedes", "Ferrari", "Alpine", "Williams",
    "AlphaTauri", "Alpha Tauri", "Alfa Romeo", "Haas", "RB", "Sauber",
    "Toro Rosso", "Force India", "Renault", "Lotus", "Audi", "Cadillac",
]
ENGINE_SUFFIXES = [
    "Honda RBPT", "Mercedes", "Ferrari", "Renault", "Ford", "RBPT", "Aramco",
    "Peugeot", "BMW", "Cosworth",
]
STOP_MARKERS = {"OUR PARTNERS", "DOWNLOAD THE OFFICIAL F1 APP", "Cookie Preferences"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_lines(text: str) -> list[str]:
    lines = []
    for raw in text.split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def is_driver_name(s: str) -> bool:
    """True if s looks like 'Firstname Lastname' (2–3 capitalised words, no digits)."""
    if re.search(r"\d", s):
        return False
    parts = s.split()
    return 2 <= len(parts) <= 4 and all(p[0].isupper() for p in parts if p)


def is_time_or_status(s: str) -> bool:
    """Match winner time, delta, lapped, or DNF/DNS/DSQ variants."""
    return bool(re.match(
        r"^(\d+:\d+:\d+\.\d+|\+\d+:\d+\.\d+|\+\d+\.\d+s|\+\d+ laps?|"
        r"DNF|DNS|DSQ|NC|W/D|DQ|EX|Accident|Engine|Gearbox|Hydraulics|"
        r"Brake|Tyre|Power|Suspension|Collision|Electrical|Mechanical|"
        r"Spin|Clutch|Driveshaft|Fuel|Oil|Water|Damage|Retired)",
        s, re.IGNORECASE
    ))


def clean_team(raw: str) -> str:
    """Return the canonical short team name from a raw car/team string."""
    raw = raw.strip()
    for team in sorted(KNOWN_TEAMS, key=len, reverse=True):
        if raw.startswith(team):
            return team
    for suffix in ENGINE_SUFFIXES:
        if suffix in raw:
            candidate = raw[: raw.index(suffix)].strip().rstrip(",- ")
            if candidate:
                return candidate
    return raw


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_race_result(lines: list[str]) -> list[dict]:
    """
    Extract finisher records from normalised inner_text lines.

    Tries two strategies:
      A — tab-delimited rows ("1\t33\tMax Verstappen\tRed Bull…\t57\t1:23:45\t25")
      B — one field per line  (the multiline format Playwright often produces)
    """
    results: list[dict] = []
    seen: set[str] = set()

    # ── Strategy A: tab-delimited ─────────────────────────────────────────────
    for line in lines:
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) < 5:
            continue
        try:
            pos  = int(parts[0])
            _no  = int(parts[1]) if re.match(r"^\d{1,2}$", parts[1]) else 0
            base = 2 if _no else 1
            name = parts[base]
            team = clean_team(parts[base + 1])
            laps = int(parts[base + 2]) if base + 2 < len(parts) else 0
            time_ret = parts[base + 3] if base + 3 < len(parts) else ""
            pts  = int(parts[base + 4]) if base + 4 < len(parts) else 0
        except (ValueError, IndexError):
            continue
        if not (1 <= pos <= 30 and is_driver_name(name)):
            continue
        if name not in seen:
            results.append({
                "position": pos, "number": _no, "driver": name,
                "team": team, "laps": laps,
                "time_retired": time_ret, "points": pts,
            })
            seen.add(name)

    if results:
        return sorted(results, key=lambda r: r["position"])

    # ── Strategy C: "pos num" / driver / "team laps time pts" (current f1.com) ─
    # Formula1.com now renders: "1 1" / "Max Verstappen" / "Red Bull Racing Honda RBPT 57 1:31:44.742 26"
    i = 0
    while i < len(lines) - 2:
        if lines[i] in STOP_MARKERS:
            break
        m_pos = re.match(r'^(\d{1,2})\s+(\d{1,2})$', lines[i])
        if not m_pos:
            i += 1
            continue
        pos    = int(m_pos.group(1))
        number = int(m_pos.group(2))
        if not (1 <= pos <= 30):
            i += 1
            continue
        if i + 1 >= len(lines) or not is_driver_name(lines[i + 1]):
            i += 1
            continue
        driver = lines[i + 1]
        if i + 2 >= len(lines):
            i += 1
            continue
        rest = lines[i + 2]
        # Parse "team... laps time pts" — laps is the first 2-3 digit number,
        # time may contain spaces ("+1 lap"), pts is the trailing integer.
        m_rest = re.match(r'^(.+?)\s+(\d{2,3})\s+(.+?)\s+(\d{1,2})\s*$', rest)
        if not m_rest:
            i += 1
            continue
        team     = clean_team(m_rest.group(1))
        laps     = int(m_rest.group(2))
        time_ret = m_rest.group(3)
        pts      = int(m_rest.group(4))
        if driver not in seen and laps > 0:
            results.append({
                "position": pos, "number": number, "driver": driver,
                "team": team, "laps": laps,
                "time_retired": time_ret, "points": pts,
            })
            seen.add(driver)
            i += 3
        else:
            i += 1

    if results:
        return sorted(results, key=lambda r: r["position"])

    # ── Strategy B: one field per line ────────────────────────────────────────
    i = 0
    while i < len(lines) - 3:
        if lines[i] in STOP_MARKERS:
            break
        if not re.match(r"^\d{1,2}$", lines[i]):
            i += 1
            continue
        pos = int(lines[i])
        if not (1 <= pos <= 30):
            i += 1
            continue

        j = i + 1
        # Optional driver number
        number = 0
        if j < len(lines) and re.match(r"^\d{1,2}$", lines[j]):
            number = int(lines[j])
            j += 1
        # Driver name
        if j >= len(lines) or not is_driver_name(lines[j]):
            i += 1
            continue
        driver = lines[j]; j += 1
        # Team
        if j >= len(lines):
            i += 1; continue
        team = clean_team(lines[j]); j += 1
        # Laps
        laps = 0
        if j < len(lines) and re.match(r"^\d{2,3}$", lines[j]):
            laps = int(lines[j]); j += 1
        # Time / retired status
        time_ret = ""
        if j < len(lines) and is_time_or_status(lines[j]):
            time_ret = lines[j]; j += 1
        # Points
        pts = 0
        if j < len(lines) and re.match(r"^\d{1,2}$", lines[j]):
            pts = int(lines[j]); j += 1

        if driver not in seen and laps > 0:
            results.append({
                "position": pos, "number": number, "driver": driver,
                "team": team, "laps": laps,
                "time_retired": time_ret, "points": pts,
            })
            seen.add(driver)
            i = j
        else:
            i += 1

    return sorted(results, key=lambda r: r["position"])


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    grand_total = 0

    for year_dir in sorted(RAW_DIR.iterdir()):
        if not year_dir.is_dir():
            continue
        try:
            year = int(year_dir.name)
        except ValueError:
            continue

        results_dir = year_dir / "race_results"
        if not results_dir.exists():
            print(f"[{year}] No race_results/ directory — run crawl_race_results.py first")
            continue

        all_results: list[dict] = []
        race_files  = sorted(results_dir.glob("*.json"))

        if not race_files:
            print(f"[{year}] race_results/ is empty")
            continue

        for rf in race_files:
            payload  = json.loads(rf.read_text(encoding="utf-8"))
            raw_text = payload.get("raw_text", "")
            slug     = payload.get("race", rf.stem)
            lines    = normalize_lines(raw_text)
            records  = parse_race_result(lines)

            for rec in records:
                rec["season"] = year
                rec["race"]   = slug

            all_results.extend(records)
            print(f"  [{year}] {slug}: {len(records)} finishers")

        out_file = OUTPUT_DIR / f"race_results_{year}.json"
        out_file.write_text(
            json.dumps(all_results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[{year}] → {len(all_results)} records  →  {out_file}")
        grand_total += len(all_results)

    print(f"\nTotal race result records: {grand_total:,}")
    if grand_total == 0:
        print("Run crawl_race_results.py first to download raw pages.")


if __name__ == "__main__":
    main()
