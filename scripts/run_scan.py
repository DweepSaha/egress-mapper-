"""Run the vulnerability scan for one area and write GeoJSON to out/.  Usage: python scripts/run_scan.py tantallon"""
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from egress import config, engine  # noqa: E402

area_name = sys.argv[1] if len(sys.argv) > 1 else "tantallon"
t0 = time.time()
area = engine.load_area(area_name)
t1 = time.time()
print(f"[{area_name}] loaded {len(area.edges):,} road segments ({sum(e.exit for e in area.edges):,} exit), "
      f"{len(area.exit_nodes):,} exit nodes in {t1 - t0:.1f}s")
for src, s in area.stats.items():
    print(f"  {src}: {s['footprints']:,} footprints, {s['homes']:,} >= {engine.MIN_HOME_M2:.0f} m2, "
          f"{s['attached']:,} attached to a road ({s['on_exit_roads']:,} on exit roads)")

results = engine.scan(area)
t2 = time.time()
print(f"  scan: {len(results)} neighbourhoods with {engine.MIN_HOMES}+ homes in {t2 - t1:.1f}s -> "
      f"{dict(Counter(r['status'] for r in results))}")
for r in sorted(results, key=lambda r: -r["worst_cut"])[:12]:
    print(f"  nid {r['nid']:>5} {r['status']:<13} homes {r['homes']:>5} (osm {r['homes_osm']}, ms {r['homes_ms']})"
          f"  gateways {r['gateways']:>2}  worst cut {r['worst_cut']:>4} (osm {r['worst_cut_osm']}, "
          f"ms {r['worst_cut_ms']})  in-block {r['worst_inside']}")

engine.to_geojson(results, config.OUT / f"{area_name}_neighbourhoods.geojson",
                  config.OUT / f"{area_name}_chokepoints.geojson")
print(f"  wrote out/{area_name}_neighbourhoods.geojson, out/{area_name}_chokepoints.geojson")
