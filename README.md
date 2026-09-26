# Egress mapper

Buildings are designed with separate ways out, so one incident can't block everyone. Neighbourhood road
layouts are not held to the same standard: hundreds of homes can depend on a single road.

This tool finds neighbourhoods where blocking one road area could cut many homes off from the main road
network, and lets you test where a new road would give them a separate way out.

Built at Hack Atlantic 2026 (UNB Fredericton).

## What it computes

1. **Vulnerability scan** — no hazard input. A hypothetical blocked area is swept along the roads; at each
   position we count homes that can no longer reach a collector or arterial road. Output per neighbourhood:
   worst-case homes cut off, the choke point, and a green / amber / red status.
2. **Hazard scenarios** — the blockage is *supplied*: a fire circle, a river level, or a mapped historical
   fire perimeter. Output: homes cut off under that scenario.
3. **Mitigation test** — draw a proposed road; the affected neighbourhood is recalculated to show how many homes
   regain a separate way out.

It does **not** predict hazards, predict which roads will be blocked, model traffic, or estimate evacuation time.

## Method (fixed choices)

- "Getting out" = reaching a collector or arterial road (OSM `tertiary` and above).
- A neighbourhood is flagged only if it has **30+ homes** (threshold from California SB 99 practice).
- Home counts use the higher of OpenStreetMap and Microsoft footprint counts; both are kept.
- Anything within ~2 km of the road-data boundary is marked **not assessed** (artificial dead ends).
- Analysis runs in EPSG:2953 (NB Stereographic); all distances are metres.

## Run

Python 3.11. Data is prepared separately — see [DATA.md](DATA.md).

```powershell
pip install --only-binary=:all: -r requirements.txt   # or reuse the prepared venv
python scripts/check_setup.py                          # confirms packages and data paths
```

## Validation cases

- **Upper Tantallon / Westwood Hills (NS):** should be flagged highly vulnerable — its two entrances are ~318 m
  apart on the same road, so the subdivision effectively has one way out. (In the May 2023 fire the entrances
  were not burned; the problem was a single evacuation route.)
- **Downtown Fredericton:** a well-connected control; it should not be flagged severe.
