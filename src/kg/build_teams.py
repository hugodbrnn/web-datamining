import json
from pathlib import Path
from rdflib import Graph, Namespace, Literal
from rdflib.namespace import RDF, XSD

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXTRACTED_DIR = PROJECT_ROOT / "data" / "extracted"
KG_FILE = PROJECT_ROOT / "kg_artifacts" / "auto_kg.ttl"

EX = Namespace("http://example.org/f1#")

def clean_uri(text: str) -> str:
    return (
        text.replace(" ", "")
        .replace("-", "")
        .replace(".", "")
        .replace("'", "")
        .replace("/", "")
    )

def season_from_filename(file_path: Path) -> str:
    return file_path.stem.split("_")[-1]

def add_if_not_exists(g: Graph, s, p, o):
    if (s, p, o) not in g:
        g.add((s, p, o))

def main():
    g = Graph()
    g.parse(KG_FILE, format="turtle")
    g.bind("ex", EX)

    for file in sorted(EXTRACTED_DIR.glob("teams_*.json")):
        year = season_from_filename(file)
        season_uri = EX[f"Season{year}"]

        data = json.loads(file.read_text(encoding="utf-8"))

        for row in data:
            team_name = row["team"]
            position = row.get("position")
            points = row.get("points")

            team_uri = EX[clean_uri(team_name)]
            standing_uri = EX[f"TeamStanding_{year}_{clean_uri(team_name)}"]

            add_if_not_exists(g, team_uri, RDF.type, EX.Team)
            add_if_not_exists(g, team_uri, EX.name, Literal(team_name))

            add_if_not_exists(g, standing_uri, RDF.type, EX.TeamStanding)
            add_if_not_exists(g, standing_uri, EX.forTeam, team_uri)
            add_if_not_exists(g, standing_uri, EX.forSeason, season_uri)

            if position is not None:
                add_if_not_exists(
                    g,
                    standing_uri,
                    EX.standingPosition,
                    Literal(int(position), datatype=XSD.int)
                )

            if points is not None:
                add_if_not_exists(
                    g,
                    standing_uri,
                    EX.standingPoints,
                    Literal(float(points), datatype=XSD.decimal)
                )

    g.serialize(destination=KG_FILE, format="turtle")

    print(f"KG mis à jour : {KG_FILE}")
    print(f"Nombre total de triplets : {len(g)}")

if __name__ == "__main__":
    main()