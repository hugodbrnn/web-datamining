# Extraction Plan - Formula 1

## Driver Pages
Extract:
- name
- nationality
- team
- seasons

Triples:
- Driver — name — value
- Driver — nationality — value
- Driver — drivesFor — Team
- Driver — competesInSeason — Season

## Team Pages
Extract:
- team name
- drivers

Triples:
- Team — name — value
- Driver — drivesFor — Team

## Race Results Pages
Extract:
- Grand Prix name
- drivers
- positions
- points

Triples:
- GrandPrix — hasResult — RaceResult
- RaceResult — forDriver — Driver
- RaceResult — finishPosition — value
- RaceResult — points — value