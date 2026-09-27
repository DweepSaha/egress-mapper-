# Survey data-prep scripts (read-only analysis, not app code)

Copies of the batch scripts that built and scanned the NB / NS / PEI survey areas. They run from
`hackatlantic-prep/scratch/` (next to the data; that folder is not a git repository), so their paths resolve there.

- `extract_areas.py` - the original data-prep stages (complete_ways cut, OSMnx drive XML, GraphML, OSM building clip).
- `clip_microsoft.py` - Microsoft footprint clip (streams the zipped provincial GeoJSON).
- `nb_batch.py`, `maritimes_batch.py` - unattended batches reusing those stages, then `scratch/nb_scan.py` (frozen
  engine, study box added at run time; nothing in `egress/` changes).

Results: `out/nb_survey/`, `out/maritimes/` (per-area JSON, `progress.log`, `report.md`).
