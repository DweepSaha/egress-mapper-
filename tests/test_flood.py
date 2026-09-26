"""Flood scenario tests. Synthetic-raster tests always run; data-backed tests need the prepared data.
Run: python tests/test_flood.py
"""
import sys
from pathlib import Path

import numpy as np
import shapely
from rasterio.transform import Affine
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from egress import config, flood  # noqa: E402

ND = -32767.0
TR = Affine(100, 0, 0, 0, -100, 1000)          # 10 x 10 grid of 100 m cells; row 0 at the top


def cell(r, c):
    return box(c * 100, 1000 - (r + 1) * 100, (c + 1) * 100, 1000 - r * 100)


def synthetic():
    dem = np.full((10, 10), 20.0, dtype="float32")   # high ground
    dem[:, 0:3] = 0.5                                 # river channel, 3 columns (300,000 m2 > seed minimum)
    return dem


# ------------------------------------------------------------------ synthetic raster tests
def test_nodata_never_becomes_water():
    dem = synthetic()
    dem[2:5, 3:6] = ND                                # NoData right beside the river
    seed = flood.river_seed(dem, ND, TR)
    water = flood.connected_water(dem, ND, TR, 10.0, seed)   # level above all real low ground
    for r in range(2, 5):
        for c in range(3, 6):
            assert water.intersection(cell(r, c)).area < 1e-6, (r, c)


def test_nodata_cannot_connect_an_isolated_pocket():
    dem = synthetic()
    dem[3, 3:6] = ND                                  # a NoData strip from the river...
    dem[3, 6] = 1.0                                   # ...to a low pocket otherwise enclosed by high ground
    seed = flood.river_seed(dem, ND, TR)
    water = flood.connected_water(dem, ND, TR, 10.0, seed)
    assert water.intersection(cell(3, 6)).area < 1e-6


def test_isolated_depression_stays_dry():
    dem = synthetic()
    dem[6, 7] = 1.0                                   # low pocket below the level but not connected to the river
    dem[5, 3] = 1.0                                   # low cell touching the river: floods
    seed = flood.river_seed(dem, ND, TR)
    water = flood.connected_water(dem, ND, TR, 5.0, seed)
    assert water.intersection(cell(6, 7)).area < 1e-6
    assert water.intersection(cell(5, 3)).area > 0.99 * 100 * 100


def test_valid_mask_excludes_nodata_and_nonfinite():
    dem = np.array([[1.0, ND, np.nan, np.inf]], dtype="float32")
    assert flood.valid_mask(dem, ND).tolist() == [[True, False, False, False]]


# ------------------------------------------------------------------ data-backed tests
def data_tests():
    from egress import engine
    area = engine.load_area("fredericton")
    base = {r["nid"]: (r["status"], r["worst_cut"], r["worst_cut_osm"], r["worst_cut_ms"]) for r in engine.scan(area)}

    low = flood.scenario(area, 5.0)
    assert low["roads_affected_km"] < 0.1, low["roads_affected_km"]                       # 2. little/no road effect

    w = [flood.water_polygon(g)[0] for g in (6.5, 7.5, 8.36, 9.0)]
    for a, b in zip(w, w[1:]):
        assert a.difference(b).area < 1.0, a.difference(b).area                         # 3. monotonic water area

    s = flood.scenario(area, 8.36)
    water = flood.water_polygon(8.36)[0].buffer(0.5)
    geoms = [shapely.geometry.shape(f["geometry"]) for f in s["roads_affected"]["features"]]
    to_m = flood._dem()[3]                                                              # 4. roads match water
    from pyproj import Transformer
    from shapely.ops import transform
    to_2953 = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True).transform
    outside = sum(transform(to_2953, g).difference(water).length for g in geoms)
    assert outside < 1.0, outside
    for src in ("osm", "ms"):                                                            # categories never overlap
        ids = s["ids"][src]
        assert not set(ids["cut"]) & set(ids["inside"])
        assert not set(ids["retain"]) & (set(ids["cut"]) | set(ids["inside"]))
    assert base == {r["nid"]: (r["status"], r["worst_cut"], r["worst_cut_osm"], r["worst_cut_ms"])
                    for r in engine.scan(area)}                                         # 8. baseline unchanged
    return s


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS {name}")
            except AssertionError as e:
                fails += 1; print(f"FAIL {name}: {e}")
    if config.roads_graphml("fredericton").exists() and flood.DEM_PATH.exists():
        try:
            s = data_tests()
            print("PASS data: low level ~no roads; monotonic water; roads inside water; categories disjoint; baseline unchanged")
            print(f"     2008 reference (8.36 m gauge = {s['water_cgvd2013_m']} m CGVD2013): {s['roads_affected_km']} km roads "
                  f"affected; lose access {s['counts']['lose_access']}; inside {s['counts']['inside']}")
        except AssertionError as e:
            fails += 1; print(f"FAIL data tests: {e}")
    else:
        print("SKIP data tests (prepared data not found)")
    print("ALL PASS" if not fails else f"{fails} FAILED")
    sys.exit(1 if fails else 0)
