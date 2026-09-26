"""Fredericton flood scenario: road access under a USER-SUPPLIED river level. This is not a flood prediction.

Input: a river level as gauge height at Water Survey of Canada station 01AK003 (Saint John River at Fredericton),
published on "Geodetic Survey of Canada Datum" = CGVD28. The elevation model (NRCan HRDEM 2024, 5 m) is CGVD2013.
At the gauge, CGVD2013 = CGVD28 - 0.489 m (NRCan conversion grid; DATA.md / SOURCES.md). Every gauge height passes
through gauge_to_cgvd2013() before any comparison with elevation.

Water area: flat at the converted level (no river slope, flood defences or drainage), limited to low ground that is
connected (4-neighbour) to the river channel; isolated depressions below the level stay dry. NoData cells are masked
before any comparison and can never be water. Outside the elevation model's coverage (the river corridor) roads are
treated as dry. Bridges (OSM bridge tag) are treated as passable: the bare-earth model shows the river beneath them.

Road access reuses the core engine unchanged: roads are impassable only on the stretches inside the water area
(engine._blocked_intervals); access per neighbourhood via engine.evaluate_blockage, with gateways limited to major-road
junctions that still connect, around the water, to roads leaving the study area.
"""
from __future__ import annotations

from functools import lru_cache
from threading import Lock

import networkx as nx
import numpy as np
import osmnx as ox
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
RIVER_SEED_BELOW_M = 1.5        # CGVD2013; river-channel cells used as the "connected to the river" seed
RIVER_SEED_MIN_M2 = 200_000     # the channel is one large water body; ignores small low pockets
DEM_PATH = config.DATA / "elevation" / "fredericton_corridor_dtm_5m.tif"


def gauge_to_cgvd2013(gauge_m: float) -> float:
    return gauge_m + CGVD28_TO_CGVD2013_M


def valid_mask(dem: np.ndarray, nodata) -> np.ndarray:
    """Cells with a real elevation. NoData (and any non-finite value) is excluded BEFORE any comparison."""
    m = np.isfinite(dem)
    if nodata is not None:
        m &= dem != nodata
    return m


def _polys(mask: np.ndarray, tr):
    return [shape(g) for g, _ in shapes(mask.astype("uint8"), mask=mask, transform=tr, connectivity=4)]


def river_seed(dem: np.ndarray, nodata, tr):
    valid = valid_mask(dem, nodata)
    return shapely.union_all([p for p in _polys(valid & (dem < RIVER_SEED_BELOW_M), tr) if p.area > RIVER_SEED_MIN_M2])


def connected_water(dem: np.ndarray, nodata, tr, level: float, seed):
    """Area (raster CRS) of valid cells below `level` that are 4-connected to the river seed."""
    below = valid_mask(dem, nodata) & (dem < level)
    return shapely.union_all([p for p in _polys(below, tr) if p.intersects(seed)])


@lru_cache(maxsize=1)
def _dem():
    with rasterio.open(DEM_PATH) as s:
        dem, tr, nd, crs = s.read(1), s.transform, s.nodata, s.crs
    to_m = Transformer.from_crs(crs, config.ANALYSIS_CRS, always_xy=True).transform
    coverage = transform(to_m, shapely.union_all(_polys(valid_mask(dem, nd), tr)))
    return dem, tr, nd, to_m, river_seed(dem, nd, tr), coverage


@lru_cache(maxsize=128)
def water_polygon(gauge_m: float):
    """River-connected water area (EPSG:2953) for a supplied gauge height, and the CGVD2013 level used."""
    dem, tr, nd, to_m, seed, _ = _dem()
    level = gauge_to_cgvd2013(gauge_m)
    return transform(to_m, connected_water(dem, nd, tr, level, seed)), level


@lru_cache(maxsize=4)
def _bridge_pairs(area_name: str) -> frozenset:
    G = ox.load_graphml(config.roads_graphml(area_name))
    return frozenset(frozenset((u, v)) for u, v, d in G.edges(data=True) if d.get("bridge") not in (None, "no"))


def _onward_exit_nodes(area: engine.Area, flooded_exit: set[int], removed: set[int]) -> set[int]:
    """Major-road junctions that still connect, around the water, to roads leaving the study box."""
    study = area.assessable.buffer(engine.BOUNDARY_BUFFER_M, join_style="mitre")
    X = nx.Graph()
    for i, e in enumerate(area.edges):
        if e.exit and i not in flooded_exit and e.u not in removed and e.v not in removed:
            X.add_edge(e.u, e.v)
    for n in list(X.nodes):
        if not study.contains(Point(area.node_xy[n])):
            X.add_edge(n, engine.WORLD)
    return nx.node_connected_component(X, engine.WORLD) - {engine.WORLD} if engine.WORLD in X else set()


_cache: dict = {}
_lock = Lock()


def scenario(area: engine.Area, gauge_m: float) -> dict:
    g = round(float(gauge_m), 2)
    with _lock:
        key = (area.name, g)
        if key not in _cache:
            _cache[key] = _scenario(area, g)
        return _cache[key]


def _scenario(area: engine.Area, gauge_m: float) -> dict:
    water, level = water_polygon(gauge_m)
    bridges = _bridge_pairs(area.name)
    is_bridge = [frozenset((e.u, e.v)) in bridges for e in area.edges]
    incident = {}
    for i, e in enumerate(area.edges):
        for n in (e.u, e.v):
            incident.setdefault(n, []).append(i)

    # nodes in the water are impassable, except nodes that only carry bridges (decks sit above the water)
    removed = {int(area.node_ids[j]) for j in area.node_tree.query(water, predicate="intersects")}
    removed = {n for n in removed if not all(is_bridge[i] for i in incident.get(n, []))}
    hit = [int(i) for i in area.edge_tree.query(water, predicate="intersects") if not is_bridge[int(i)]]
    blocked = {i: engine._blocked_intervals(area.edges[i].line, water) for i in hit}
    blocked = {i: iv for i, iv in blocked.items() if iv}
    onward = _onward_exit_nodes(area, {i for i in blocked if area.edges[i].exit}, removed)

    # physically inside the water area: every analysed building, whatever its road
    inside = {s: set(area.bld[s]["tree"].query(water, predicate="contains").tolist()) for s in engine.SOURCES}
    cut = {s: set() for s in engine.SOURCES}
    retain = {s: set() for s in engine.SOURCES}
    cut_lines, n_affected_nb = [], 0
    for nb in engine.neighbourhoods(area):
        if not nb.gateways or nb.n_homes == 0 or not engine._assessed(area, nb):
            continue                                  # same eligibility as the scan (boundary rule)
        cohort = nb.cohort(area)
        nb_blocked = {i: blocked[i] for i in nb.edge_idx if i in blocked}
        nb_nodes = nb.local_nodes | nb.gateways
        if not nb_blocked and nb.gateways <= onward and not (removed & nb_nodes):
            for s in engine.SOURCES:                  # untouched by the water
                retain[s] |= cohort[s] - inside[s]
            continue
        r = engine.evaluate_blockage(area, nb, removed, nb_blocked, water, gateways=onward)
        if r["cut"]:
            n_affected_nb += 1
            cut_lines += [area.edges[i].line for i in r["cut_edges"]]
        for s in engine.SOURCES:
            cut[s] |= r["cut_ids"][s]
            retain[s] |= cohort[s] - r["cut_ids"][s] - inside[s]

    flooded = [area.edges[i].line.intersection(water) for i in blocked]
    flooded = [f for f in flooded if not f.is_empty]
    to_ll, fc = engine._TO_LL, engine._fc
    counts = {cat: {s: len(ids[s]) for s in engine.SOURCES} for cat, ids in
              (("lose_access", cut), ("inside", inside), ("keep_access", retain))}
    return dict(
        gauge_m=gauge_m, water_cgvd2013_m=round(level, 3), offset_m=CGVD28_TO_CGVD2013_M, gauge=GAUGE,
        roads_affected_km=round(sum(f.length for f in flooded) / 1000, 2), road_segments_affected=len(flooded),
        water_km2=round(water.area / 1e6, 2), neighbourhoods_losing_access=n_affected_nb,
        counts=counts, headline={k: max(v.values()) for k, v in counts.items()},   # frozen higher-of-two rule
        ids={s: {k: sorted(int(i) for i in v) for k, v in (("cut", cut[s]), ("inside", inside[s]), ("retain", retain[s]))}
             for s in engine.SOURCES},                                            # plain ints (JSON-safe)
        water=fc([dict(type="Feature", properties={}, geometry=mapping(transform(to_ll, water.simplify(3))))]),
        roads_affected=fc([dict(type="Feature", properties={}, geometry=mapping(transform(to_ll, f))) for f in flooded]),
        cut_roads=fc([dict(type="Feature", properties={}, geometry=mapping(transform(to_ll, l))) for l in cut_lines]),
    )


def coverage_geojson() -> dict:
    cov = _dem()[5]
    return engine._fc([dict(type="Feature", properties={},
                            geometry=mapping(transform(engine._TO_LL, cov.simplify(10))))])
