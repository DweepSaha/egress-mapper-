"""Display-only helpers: building footprints for the map, and per-neighbourhood building categories.

Reads the same footprint files with the same filter and order as engine.load_area, so a polygon's position is the
engine's building id. That alignment is verified on load. Nothing here changes any count.
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import shapely

from . import config, engine

SOURCE_FILES = {"osm": config.buildings_osm, "ms": config.buildings_ms}


def footprints_json(area_name: str, src: str, n_expected: int, check_xy: tuple) -> bytes:
    """GeoJSON (lon/lat) of the analysed footprints for one source; feature id = engine building id.
    Not cached here: the API keeps it with the loaded area, so it is freed with it."""
    b = gpd.read_file(SOURCE_FILES[src](area_name)).to_crs(config.ANALYSIS_CRS)
    b = b[b.geometry.area >= engine.MIN_HOME_M2].reset_index(drop=True)   # identical filter/order to the engine
    if len(b) != n_expected:
        raise RuntimeError(f"{area_name}/{src}: {len(b)} footprints vs {n_expected} engine buildings")
    for i, (x, y) in check_xy:                                            # spot-check id alignment
        c = b.geometry.iloc[i].centroid
        if abs(c.x - x) > 1e-6 or abs(c.y - y) > 1e-6:
            raise RuntimeError(f"{area_name}/{src}: footprint {i} does not match engine building {i}")
    g = shapely.set_precision(b.to_crs(4326).geometry.values, 1e-6)         # ~0.1 m, trims payload
    feats = [dict(type="Feature", id=i, properties={}, geometry=json.loads(shapely.to_geojson(geom)))
             for i, geom in enumerate(g)]
    return json.dumps(dict(type="FeatureCollection", features=feats), separators=(",", ":")).encode()


def footprints(area: engine.Area, src: str) -> bytes:
    pts = area.bld[src]["pts"]
    idx = np.linspace(0, len(pts) - 1, 5).astype(int) if len(pts) else []
    check = tuple((int(i), (pts[i].x, pts[i].y)) for i in idx)
    return footprints_json(area.name, src, len(pts), check)


def categories(area: engine.Area, result: dict) -> dict:
    """Building ids per source for a neighbourhood's worst blockage: lose access / inside the blocked area / retain.
    Uses the engine's own evaluate_block (read-only) and its centroid-in-circle definition of "inside"."""
    nb = next(n for n in engine.neighbourhoods(area) if n.nid == result["nid"])
    cohort = nb.cohort(area)
    out = dict(nid=result["nid"], choke=result["choke"] is not None, sources={})
    if result["choke"] is None:
        for s in engine.SOURCES:
            out["sources"][s] = dict(cut=[], inside=[], retain=sorted(int(i) for i in cohort[s]))
        return out
    ev = engine.evaluate_block(area, nb, result["choke"])
    circle = result["choke"].buffer(engine.BLOCK_RADIUS_M)
    for s in engine.SOURCES:
        inside = set(area.bld[s]["tree"].query(circle, predicate="contains").tolist()) & cohort[s]
        cut = ev["cut_ids"][s]
        out["sources"][s] = dict(cut=sorted(int(i) for i in cut), inside=sorted(int(i) for i in inside),
                                 retain=sorted(int(i) for i in cohort[s] - cut - inside))
    # consistency with the scan (display must agree with the engine, never the other way round)
    out["matches_scan"] = (len(ev["cut_ids"]["osm"]) == result["worst_cut_osm"]
                           and len(ev["cut_ids"]["ms"]) == result["worst_cut_ms"])
    return out
