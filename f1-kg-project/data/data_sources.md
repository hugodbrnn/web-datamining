# Data Sources - Formula 1 KG Project

## Domain
This project focuses on Formula 1, with a knowledge graph centered on drivers, teams, seasons, Grand Prix races, circuits, and race results.

## Main Sources

### 1. Formula1.com
- URL: https://www.formula1.com/
- Type: semi-structured source
- Usage:
  - driver pages
  - team pages
  - race result pages
- Information targeted:
  - driver names
  - nationalities
  - teams
  - season participation
  - Grand Prix names
  - race winners
  - finishing positions
  - points

### 2. L'Équipe - Formule 1
- URL: https://www.lequipe.fr/Formule-1/
- Type: unstructured textual source
- Usage:
  - news articles
  - race summaries
  - driver and team news
- Information targeted:
  - contextual race information
  - textual mentions of drivers and teams
  - event descriptions
  - additional relations extracted from text

## Seasons Covered
- 2021
- 2022
- 2023

## Why two sources?
We use Formula1.com for structured or semi-structured factual data, and L'Équipe for unstructured textual data. This allows us to build a richer knowledge graph and demonstrate information extraction from different types of web sources.