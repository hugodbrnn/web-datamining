import requests
import json
import re
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXTRACTED_DIR = PROJECT_ROOT / "data" / "extracted"
OUTPUT_FILE = PROJECT_ROOT / "kg_artifacts" / "alignment_drivers.tsv"

WIKIDATA_API = "https://www.wikidata.org/w/api.php"

HEADERS = {
    "User-Agent": "f1-kg-project/1.0 (student project)"
}


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def clean_local_entity(name: str) -> str:
    name = normalize_name(name)
    return (
        name.replace(" ", "")
        .replace("-", "")
        .replace(".", "")
        .replace("'", "")
        .replace("/", "")
    )


def search_wikidata(name: str):
    params = {
        "action": "wbsearchentities",
        "search": name,
        "language": "en",
        "format": "json",
        "limit": 1
    }

    try:
        response = requests.get(
            WIKIDATA_API,
            params=params,
            headers=HEADERS,
            timeout=20
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "json" not in content_type.lower():
            print(f"[WARN] Réponse non JSON pour {name}")
            return None, None

        data = response.json()

        if "search" in data and len(data["search"]) > 0:
            result = data["search"][0]
            return result.get("id"), result.get("label")

    except requests.RequestException as e:
        print(f"[ERROR] Requête échouée pour {name}: {e}")
    except json.JSONDecodeError:
        print(f"[ERROR] JSON invalide pour {name}")
    except Exception as e:
        print(f"[ERROR] Problème inattendu pour {name}: {e}")

    return None, None


def main():
    seen = set()
    cache = {}
    rows_to_write = []

    for file in sorted(EXTRACTED_DIR.glob("drivers_*.json")):
        season = file.stem.split("_")[-1].strip()
        data = json.loads(file.read_text(encoding="utf-8"))

        for row in data:
            raw_name = row.get("name", "")
            name = normalize_name(raw_name)

            if not name:
                continue

            key = (season, name.casefold())
            if key in seen:
                continue
            seen.add(key)

            local_entity = clean_local_entity(name)

            # 🔥 cache + rate limiting
            if name in cache:
                wikidata_id, wikidata_label = cache[name]
            else:
                wikidata_id, wikidata_label = search_wikidata(name)
                cache[name] = (wikidata_id, wikidata_label)
                time.sleep(0.2)

            if wikidata_id:
                confidence = 1.0 if wikidata_label and name.casefold() == wikidata_label.casefold() else 0.8
                status = "auto"
            else:
                confidence = 0.0
                status = "not_found"
                wikidata_label = ""

            rows_to_write.append([
                local_entity,
                name,
                season,
                wikidata_id or "",
                wikidata_label,
                str(confidence),
                status
            ])

            print(f"{name} ({season}) -> {wikidata_id}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("local_entity\tlocal_name\tseason\tcandidate_wikidata_id\tcandidate_label\tconfidence\tstatus\n")
        for row in rows_to_write:
            f.write("\t".join(row) + "\n")

    print(f"\nNombre total de lignes alignées : {len(rows_to_write)}")
    print(f"Fichier écrit : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
    