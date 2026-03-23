# Knowledge Graph Design

We created an RDF knowledge graph representing a small e-commerce domain.

The ontology contains three main classes:
- Customer
- Shop
- Product

We defined relationships such as:
- sells (Shop → Product)
- soldBy (Product → Shop)

We also added datatype properties:
- name
- email

The graph is stored in Turtle format and includes several instances used for evaluation.