# Extraction Schema - Formula 1

## Entities
- Driver
- Team
- Season
- GrandPrix
- Circuit
- RaceResult

## Relationships

### Driver & Team
- Driver — drivesFor — Team
- Driver — teammateOf — Driver

### Driver & Season
- Driver — competesIn — Season

### Races
- GrandPrix — heldAt — Circuit
- Season — hasRace — GrandPrix

### Results
- Driver — wonRace — GrandPrix
- RaceResult — forDriver — Driver
- RaceResult — position — value
- RaceResult — points — value

### Team
- Team — scoredPoints — value
- Team — competesIn — Season