# Data provenance

All inputs were acquired and verified before the event and live **outside this repository**
(default `../hackatlantic-prep/data`, override with the `EGRESS_DATA` environment variable).
The full per-file record — URLs, byte sizes, checksums, download dates, and verification notes — is
`hackatlantic-prep/data/SOURCES.md`. This file summarises what the code uses and what must be credited.

## Sources

| Data | Source | Licence | Attribution to display |
|---|---|---|---|
| Roads, OSM buildings | OpenStreetMap via Geofabrik extracts (OSM timestamp 2026-09-21T20:21:51Z) | ODbL 1.0 | © OpenStreetMap contributors |
| Microsoft building footprints | microsoft/CanadianBuildingFootprints (v2, June 2019 release; imagery date unknown, pre-2019) | ODbL | Building footprints © Microsoft, licensed under ODbL |
| Elevation (Fredericton) | NRCan HRDEM, CanElevation series — 2024 Fredericton LiDAR DTM, 1 m and 5 m clips | Open Government Licence – Canada | Contains information licensed under the Open Government Licence – Canada |
| Fire perimeters | NRCan CWFIS — NBAC (Tantallon 2023), M3 estimates (Oldfield Road 2025) | Probably OGL – Canada (**unconfirmed**) | Canadian Wildland Fire Information System, Natural Resources Canada |
| River levels | Water Survey of Canada station 01AK003 (Saint John River at Fredericton) | Open Government Licence – Canada | Environment and Climate Change Canada |
| Basemap (online) | OpenFreeMap dark style | free, attribution required | OpenFreeMap © OpenMapTiles Data from OpenStreetMap |

## Prepared study areas

| Area | Road network (drivable, simplified) | OSM buildings | Microsoft buildings |
|---|---|---|---|
| Fredericton | 5,078 nodes / 12,149 edges | 30,459 | 35,286 |
| Upper Tantallon / Hammonds Plains | 2,038 / 4,607 | 25,177 | 20,274 |
| Pointe-Sapin + Route 117 | 174 / 376 | 160 | 1,737 |

Road extracts use a complete-ways cut, so roads crossing the study box keep all their points — but every road
leaving the extract still ends artificially. Results near the extract boundary are reported as NOT ASSESSED.

## Vertical datum

- HRDEM elevations are **CGVD2013** metres.
- Fredericton river levels (station 01AK003) are published on "Geodetic Survey of Canada Datum" = **CGVD28**.
- At the gauge, CGVD2013 = CGVD28 − 0.489 m (NRCan conversion grid). 2008 peak 8.36 m gauge ≈ 7.87 m CGVD2013.
- Gauge height and CGVD2013 elevation are never mixed in code without this conversion.

## Known data limitations

- Building footprints are not dwelling units; counts are a proxy.
- Rural OSM building coverage is very thin (Pointe-Sapin: 160 OSM vs 1,737 Microsoft), so the higher of the two
  counts is used and both are shown.
- The elevation model covers the Fredericton river corridor only; NoData (−32767) is masked explicitly.

## Saved scans (`cache/areas/`, generated)

Opening a surveyed area that is not pinned reads its saved scan instead of re-running it (HRM: ~4 s instead of
60-100 s). Each file is the pickled output of `engine.load_area` + `engine.scan` for exactly the current inputs; the
file name carries a key over the engine and config source, the study box, the three input files (size + time) and the
library versions, so any change makes the app scan again. Not committed; rebuild and verify with
`python scripts/build_area_cache.py --all --verify` (re-scans each unpickled area and requires identical results,
and matching survey counts). Tantallon and Fredericton are never cached: they are computed live at startup.
