"""Verify the environment and that every prepared input file is reachable. Run: python scripts/check_setup.py"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from egress import config  # noqa: E402

ok = True
for pkg in ("geopandas", "shapely", "pyproj", "networkx", "osmnx", "rasterio", "fastapi", "uvicorn"):
    try:
        importlib.import_module(pkg)
    except ImportError as e:
        ok = False
        print(f"[FAIL] import {pkg}: {e}")

print(f"data dir: {config.DATA}")
for area in config.AREAS:
    for label, p in (("roads", config.roads_graphml(area)), ("OSM buildings", config.buildings_osm(area)),
                     ("MS buildings", config.buildings_ms(area))):
        exists = p.exists()
        ok &= exists
        print(f"[{'PASS' if exists else 'FAIL'}] {area:<13} {label:<14} {p}")

print("setup OK" if ok else "setup INCOMPLETE - see FAIL lines")
sys.exit(0 if ok else 1)
