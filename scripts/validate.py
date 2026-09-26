"""Phase 1 validation gate: Westwood Hills (Tantallon) and downtown Fredericton control.
Neighbourhoods are matched by location only (OSM Westwood Hills boundary; a fixed downtown box), never by result.
Usage: python scripts/validate.py
"""
import sys
from collections import Counter
from pathlib import Path

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import Point, box
from shapely.ops import transform

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from egress import config, engine  # noqa: E402

to_m = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True).transform
ENTRANCES = [(-63.855646, 44.704433), (-63.852344, 44.706056)]  # Westwood Hills mouths on Hammonds Plains Rd
DOWNTOWN = box(-66.6500, 45.9540, -66.6300, 45.9650)            # downtown Fredericton, river to Brunswick St


def show(r, extra=""):
    print(f"   nid {r['nid']:>5} {r['status']:<13} homes {r['homes']:>4} (osm {r['homes_osm']}, ms {r['homes_ms']}) "
          f"gateways {r['gateways']:>2} worst cut {r['worst_cut']:>4} {extra}")


print("=== Tantallon / Westwood Hills")
area = engine.load_area("tantallon")
res = engine.scan(area)
ww = gpd.read_file(config.DATA / "osm/nova-scotia.gpkg", layer="gis_osm_adminareas_a_free",
                   where="name = 'Westwood Hills'").to_crs(config.ANALYSIS_CRS).union_all()
ents = [Point(to_m(*p)) for p in ENTRANCES]
print(f"   scan summary: {dict(Counter(r['status'] for r in res))}")
hits = sorted([r for r in res if r["geometry"].intersects(ww)], key=lambda r: -r["geometry"].intersection(ww).area)
for r in hits:
    share = r["geometry"].intersection(ww).area / r["geometry"].area
    d = min(e.distance(r["geometry"]) for e in ents)
    choke = f"choke at {r['choke'].distance(ents[0]):.0f}/{r['choke'].distance(ents[1]):.0f} m from entrances" \
        if r["choke"] is not None else ""
    show(r, f"| {share:.0%} of it inside Westwood Hills, {d:.0f} m to nearest entrance {choke}")

print("\n=== Fredericton downtown control")
area = engine.load_area("fredericton")
res = engine.scan(area)
dt = transform(to_m, DOWNTOWN)
print(f"   scan summary: {dict(Counter(r['status'] for r in res))}")
for r in sorted([r for r in res if r["geometry"].intersects(dt)], key=lambda r: -r["homes"]):
    show(r, f"| {r['geometry'].intersection(dt).area / dt.area:.0%} of downtown box")
