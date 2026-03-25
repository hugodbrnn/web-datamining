from pathlib import Path
from rdflib import Graph

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ttl_path = PROJECT_ROOT / "kg_artifacts" / "auto_kg.ttl"

print("Fichier chargé :", ttl_path)

g = Graph()
g.parse(ttl_path, format="turtle")

print("Nombre de triplets :", len(g))

query = """
PREFIX ex: <http://example.org/f1#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>

SELECT ?wd
WHERE {
    ex:MaxVerstappen owl:sameAs ?wd .
}
"""

results = g.query(query)

print("Wikidata alignment de Max Verstappen :")
for row in results:
    print("Wikidata URI :", row.wd)