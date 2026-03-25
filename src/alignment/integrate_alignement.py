import csv
from pathlib import Path
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
KG_FILE = PROJECT_ROOT / "kg_artifacts" / "auto_kg.ttl"
DRIVERS_TSV = PROJECT_ROOT / "kg_artifacts" / "alignment_drivers.tsv"
TEAMS_TSV = PROJECT_ROOT / "kg_artifacts" / "alignment_teams.tsv"

EX = Namespace("http://example.org/f1#")
WD = Namespace("http://www.wikidata.org/entity/")

def integrate_tsv(g: Graph, tsv_path: Path):
    with open(tsv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row["status"] != "auto":
                continue
            wikidata_id = row["candidate_wikidata_id"].strip()
            local_entity = row["local_entity"].strip()

            if not wikidata_id or not local_entity:
                continue

            local_uri = EX[local_entity]
            wd_uri = WD[wikidata_id]

            g.add((local_uri, OWL.sameAs, wd_uri))

def main():
    g = Graph()
    g.parse(KG_FILE, format="turtle")
    g.bind("ex", EX)
    g.bind("wd", WD)
    g.bind("owl", OWL)

    integrate_tsv(g, DRIVERS_TSV)
    integrate_tsv(g, TEAMS_TSV)

    g.serialize(destination=KG_FILE, format="turtle")

    print(f"KG mis à jour avec les alignments : {KG_FILE}")
    print(f"Nombre total de triplets : {len(g)}")

if __name__ == "__main__":
    main()