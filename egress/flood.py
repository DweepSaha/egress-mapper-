"""Fredericton river-level scenario (hazard INPUT, not a flood forecast).

The user supplies a river level as gauge height at Water Survey of Canada station 01AK003 (Saint John River at
Fredericton), published on "Geodetic Survey of Canada Datum" = CGVD28. The elevation model (NRCan HRDEM 2024, 5 m)
is CGVD2013. At the gauge, CGVD2013 = CGVD28 - 0.489 m (NRCan conversion grid; see DATA.md). Gauge heights are
converted with gauge_to_cgvd2013() before ANY comparison with elevation.

Water surface: flat at the converted level (no slope, no flood defences, no drainage), limited to low ground that is
connected to the river channel. NoData cells are masked out before comparison. Outside the elevation model's
coverage (the river corridor) roads are treated as unaffected.
"""
from __future__ import annotations

from functools import lru_cache

import networkx as nx
import numpy as np
import rasterio
import shapely
from pyproj import Transformer
from rasterio.features import shapes
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform

from . import config, engine

GAUGE = "Saint John River at Fredericton (WSC 01AK003), CGVD28"
CGVD28_TO_CGVD2013_M = -0.489   # at the gauge; NRCan conversion grid (DATA.md)
FLOOD_STAGE_GAUGE_M = 6.5
PEAK_2008_GAUGE_M = 8.36
RIVER_SEED_BELOW_M = 1.5        # CGVD2013; channel cells used as the "connected to the river" seed
RIVER_SEED_MIN_M2 = 200_000
DEM_PATH = config.DATA / "elevation" / "fredericton_corridor_dtm_5m.tif"


def gauge_to_cgvd2013(gauge_m: float) -> float:
    return gauge_m + CGVD28_TO_CGVD2013_M


@lru_cache(maxsize=1)
def _dem():
    with rasterio.open(DEM_PATH) as s:
        dem, tr, nd, crs = s.read(1), s.transform, s.nodata, s.crs
    valid = dem != nd                       # explicit NoData mask, applied before any comparison
    to_m = Transformer.from_crs(crs, config.ANALYSIS_CRS, always_xy=True).transform

    def polys(mask):
        return [shape(g) for g, _ in shapes(mask.astype("uint8"), mask=mask, transform=tr, connectivity=4)]

    river = shapely.union_all([p for p in polys(valid & (dem < RIVER_SEED_BELOW_M)) if p.area > RIVER_SEED_MIN_M2])
    coverage = shapely.union_all(polys(valid))
    return dem, valid, polys, river, to_m, transform(to_m, coverage)


@lru_cache(maxsize=64)
def water_polygon(gauge_m: float):
    """River-connected area below the converted level, in EPSG:2953."""
    dem, valid, polys, river, to_m, _ = _dem()
    level = gauge_to_cgvd2013(gauge_m)
    below = valid & (dem < level)
    connected = [p for p in polys(below) if p.intersects(river)]
    return transform(to_m, shapely.union_all(connected)), level


def _onward_exit_nodes(area: engine.Area, flooded_edges: set[int], removed: set[int]) -> set[int]:
    """Exit-road nodes that still connect, around the water, to roads leaving the study box."""
    study = area.assessable.buffer(engine.BOUNDARY_BUFFER_M, join_style="mitre")
    X = nx.Graph()
    for i, e in enumerate(area.edges):
        if e.exit and i not in flooded_edges and e.u not in removed and e.v not in removed:
            X.add_edge(e.u, e.v)
    for n in list(X.nodes):
        if not study.contains(Point(area.node_xy[n])):
            X.add_edge(n, engine.WORLD)
    return nx.node_connected_component(X, engine.WORLD) - {engine.WORLD} if engine.WORLD in X else set()


def scenario(area: engine.Area, gauge_m: float) -> dict:
    water, level = water_polygon(round(gauge_m, 2))
    prepared = shapely.prepared.prep(water)
    removed = {int(area.node_ids[i]) for i in area.node_tree.query(water, predicate="intersects")}
    # bridge decks are above the water (the bare-earth model shows the river beneath them); approaches still flood
    hit = [int(i) for i in area.edge_tree.query(water, predicate="intersects") if not area.edges[int(i)].bridge]
    blocked = {i: engine._blocked_interval(area.edges[i].line, water) for i in hit}
    flooded_exit = {i for i in hit if area.edges[i].exit}
    onward = _onward_exit_nodes(area, flooded_exit, removed)

    rows, cut_lines = [], []
    tot = dict(cut=0, cut_osm=0, cut_ms=0, inside=0, neighbourhoods=0)
    for nb in engine.neighbourhoods(area):
        if not nb.gateways or nb.n_homes == 0:
            continue
        lines = [area.edges[i].line for i in nb.edge_idx]
        if not area.assessable.contains(shapely.union_all(lines)):
            continue                        # same boundary rule as the scan
        if not any(i in blocked for i in nb.edge_idx) and nb.gateways <= onward:
            continue                        # untouched by the water
        r = engine.evaluate_blockage(area, nb, removed, {i: blocked[i] for i in nb.edge_idx if i in blocked}, onward)
        if r["cut"] == 0 and r["inside"] == 0:
            continue
        tot["cut"] += r["cut"]; tot["cut_osm"] += r["cut_osm"]; tot["cut_ms"] += r["cut_ms"]
        tot["inside"] += r["inside"]; tot["neighbourhoods"] += r["cut"] > 0
        rows.append(dict(nid=nb.nid, buildings=nb.n_homes, cut=r["cut"], inside=r["inside"]))
        cut_lines += [area.edges[i].line for i in r["cut_edges"]]

    to_ll = engine._TO_LL
    flooded_roads = [area.edges[i].line.intersection(water) for i in hit]
    km = sum(g.length for g in flooded_roads) / 1000
    fc = engine._fc
    return dict(
        gauge_m=round(gauge_m, 2), water_cgvd2013_m=round(level, 2), offset_m=CGVD28_TO_CGVD2013_M, gauge=GAUGE,
        flooded_road_km=round(km, 1), totals=tot, neighbourhoods=sorted(rows, key=lambda r: -r["cut"]),
        water=fc([dict(type="Feature", properties={}, geometry=mapping(transform(to_ll, water.simplify(4))))]),
        flooded_roads=fc([dict(type="Feature", properties={}, geometry=mapping(transform(to_ll, g)))
                          for g in flooded_roads if not g.is_empty]),
        cut_roads=fc([dict(type="Feature", properties={}, geometry=mapping(transform(to_ll, g))) for g in cut_lines]),
    )


def coverage_geojson() -> dict:
    cov = _dem()[5]
    return engine._fc([dict(type="Feature", properties={}, geometry=mapping(transform(engine._TO_LL, cov.simplify(10))))])
