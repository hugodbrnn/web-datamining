import json
from pathlib import Path
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, OWL, XSD

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXTRACTED_DIR = PROJECT_ROOT / "data" / "extracted"
ONTOLOGY_FILE = PROJECT_ROOT / "ontology" / "f1_ontology.ttl"
OUTPUT_FILE = PROJECT_ROOT / "kg_artifacts" / "auto_kg.ttl"

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
    # drivers_2024.json -> 2024
    return file_path.stem.split("_")[-1]


def add_if_not_exists(g: Graph, s, p, o):
    if (s, p, o) not in g:
        g.add((s, p, o))


def main():
    g = Graph()
    g.bind("ex", EX)

    # Charger l'ontologie de base si elle existe
    if ONTOLOGY_FILE.exists():
        g.parse(ONTOLOGY_FILE, format="turtle")

    for file in sorted(EXTRACTED_DIR.glob("drivers_*.json")):
        year = season_from_filename(file)
        season_uri = EX[f"Season{year}"]

        # Déclare la saison
        add_if_not_exists(g, season_uri, RDF.type, EX.Season)
        add_if_not_exists(g, season_uri, EX.seasonYear, Literal(int(year), datatype=XSD.int))

        data = json.loads(file.read_text(encoding="utf-8"))

        for row in data:
            driver_name = row["name"]
            team_name = row["team"]
            position = row.get("position")
            points = row.get("points")
            nationality_code = row.get("nationality_code")

            driver_uri = EX[clean_uri(driver_name)]
            team_uri = EX[clean_uri(team_name)]
            standing_uri = EX[f"Standing_{year}_{clean_uri(driver_name)}"]

            # Déclare pilote
            add_if_not_exists(g, driver_uri, RDF.type, EX.Driver)
            add_if_not_exists(g, driver_uri, EX.name, Literal(driver_name))

            if nationality_code:
                add_if_not_exists(g, driver_uri, EX.nationality, Literal(nationality_code))

            # Déclare équipe
            add_if_not_exists(g, team_uri, RDF.type, EX.Team)
            add_if_not_exists(g, team_uri, EX.name, Literal(team_name))

            # Relations stables
            add_if_not_exists(g, driver_uri, EX.drivesFor, team_uri)
            add_if_not_exists(g, driver_uri, EX.competesInSeason, season_uri)

            # Standing saisonnier
            add_if_not_exists(g, standing_uri, RDF.type, EX.DriverStanding)
            add_if_not_exists(g, standing_uri, EX.forDriver, driver_uri)
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

            add_if_not_exists(g, driver_uri, EX.hasStanding, standing_uri)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    g.serialize(destination=OUTPUT_FILE, format="turtle")

    print(f"KG généré : {OUTPUT_FILE}")
    print(f"Nombre total de triplets : {len(g)}")


if __name__ == "__main__":
    main()