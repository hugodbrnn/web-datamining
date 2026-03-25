import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "formula1"
OUTPUT_DIR = PROJECT_ROOT / "data" / "extracted"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ENGINE_WORDS = {
    "Honda", "RBPT", "Mercedes", "Ferrari", "Renault", "Aramco"
}

STOP_MARKERS = {
    "OUR PARTNERS",
    "View all",
    "DOWNLOAD THE OFFICIAL F1 APP"
}

def normalize_lines(text: str) -> list[str]:
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines

def clean_team(raw_team: str) -> str:
    raw_team = raw_team.strip()

    exact_teams = [
        "Mercedes",
        "Ferrari",
        "McLaren",
        "Williams",
        "Alpine",
        "Audi",
        "Cadillac",
        "Kick Sauber",
        "Sauber",
        "RB",
        "Racing Bulls",
        "Haas",
        "Haas F1 Team",
        "Red Bull Racing",
        "Aston Martin",
    ]

    for team in sorted(exact_teams, key=len, reverse=True):
        if raw_team.startswith(team):
            return team

    tokens = raw_team.split()
    cleaned = []

    for tok in tokens:
        if tok in ENGINE_WORDS:
            break
        cleaned.append(tok)

    return " ".join(cleaned).strip()

def parse_team_standings(lines: list[str]) -> list[dict]:
    teams = []
    i = 0

    while i < len(lines):
        if lines[i] in STOP_MARKERS:
            break

        # FORMAT A: une seule ligne -> "1 McLaren Mercedes 666"
        m1 = re.match(r"^(\d+)\s+(.+?)\s+(\d+)$", lines[i])
        if m1:
            position = int(m1.group(1))
            raw_team = m1.group(2).strip()
            points = int(m1.group(3))
            team = clean_team(raw_team)

            if team:
                teams.append({
                    "position": position,
                    "team": team,
                    "points": points
                })
            i += 1
            continue

        # FORMAT B: deux lignes -> "1" puis "McLaren 833"
        if i + 1 < len(lines) and lines[i].isdigit():
            position = int(lines[i])
            m2 = re.match(r"^(.+?)\s+(\d+)$", lines[i + 1])
            if m2:
                raw_team = m2.group(1).strip()
                points = int(m2.group(2))
                team = clean_team(raw_team)

                if team:
                    teams.append({
                        "position": position,
                        "team": team,
                        "points": points
                    })
                i += 2
                continue

        i += 1

    return teams

def main():
    total = 0

    for year_dir in sorted(RAW_DIR.iterdir()):
        if not year_dir.is_dir():
            continue

        teams_file = year_dir / "teams.json"
        if not teams_file.exists():
            continue

        data = json.loads(teams_file.read_text(encoding="utf-8"))
        raw_text = data.get("raw_text", "")

        lines = normalize_lines(raw_text)
        teams = parse_team_standings(lines)

        out_file = OUTPUT_DIR / f"teams_{year_dir.name}.json"
        out_file.write_text(
            json.dumps(teams, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        print(f"{year_dir.name} → {len(teams)} teams extraites")
        total += len(teams)

    print(f"Total extrait : {total}")

if __name__ == "__main__":
    main()