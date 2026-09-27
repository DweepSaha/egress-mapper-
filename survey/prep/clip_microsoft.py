"""DATA PREP (not project code): clip Microsoft Canadian building footprints to the study-area bboxes
and compare counts with the OSM clips. Streams each zipped GeoJSON one feature per line - never
loads a province into memory. Same selection rule as the OSM clip: intersects bbox, kept whole.
"""
import io
import json
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import pyogrio
from shapely.geometry import box, shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_areas import AREAS, bbox, peak_mb  # same bboxes as the OSM extracts

ROOT = Path(__file__).resolve().parent.parent
MS = ROOT / "data/buildings/microsoft"
PROVINCE_ZIP = {"new-brunswick": "NewBrunswick.zip", "nova-scotia": "NovaScotia.zip"}


def stream_features(zpath):
    """Yield one GeoJSON feature dict per line of the FeatureCollection inside the zip."""
    with zipfile.ZipFile(zpath) as z, z.open(z.namelist()[0]) as f:
        for line in io.TextIOWrapper(f, encoding="utf-8"):
            line = line.strip().rstrip(",")
            if line.startswith('{"type":"Feature"'):
                yield json.loads(line)


def clip_province(province, areas):
    boxes = {a: bbox(a) for a in areas}
    keep = {a: [] for a in areas}
    total = 0
    for feat in stream_features(MS / PROVINCE_ZIP[province]):
        total += 1
        ring = feat["geometry"]["coordinates"][0]
        xs, ys = [c[0] for c in ring], [c[1] for c in ring]
        for a, (x0, y0, x1, y1) in boxes.items():
            if max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1:
                continue  # entirely outside: cheap reject
            geom = shape(feat["geometry"])
            inside = min(xs) >= x0 and max(xs) <= x1 and min(ys) >= y0 and max(ys) <= y1
            if inside or geom.intersects(box(x0, y0, x1, y1)):
                keep[a].append(geom)
    print(f"{PROVINCE_ZIP[province]}: streamed {total:,} footprints")
    for a, geoms in keep.items():
        out = MS / f"{a}.gpkg"
        gpd.GeoDataFrame(geometry=geoms, crs="EPSG:4326").to_file(out, layer="buildings", driver="GPKG")
        n = pyogrio.read_info(out, layer="buildings")["features"]
        print(f"  [{'PASS' if n == len(geoms) else 'FAIL'}] {a}: {len(geoms):,} footprints -> "
              f"{out.relative_to(ROOT)} ({out.stat().st_size / 1e6:.1f} MB)")
    return total


if __name__ == "__main__":
    by_province = {}
    for a, cfg in AREAS.items():
        by_province.setdefault(cfg["province"], []).append(a)
    totals = {p: clip_province(p, areas) for p, areas in by_province.items()}

    print(f"\n{'area':<14}{'OSM':>9}{'Microsoft':>11}{'MS/OSM':>9}")
    for a in AREAS:
        osm = pyogrio.read_info(ROOT / "data/buildings" / f"{a}.gpkg", layer="buildings")["features"]
        ms = pyogrio.read_info(MS / f"{a}.gpkg", layer="buildings")["features"]
        print(f"{a:<14}{osm:>9,}{ms:>11,}{ms / osm:>8.1f}x")
    print(f"\nprovince totals streamed: {totals}; process peak memory {peak_mb():.0f} MB")
