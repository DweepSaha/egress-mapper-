"""User-placed blockage ("probe") for one neighbourhood. NO NEW SCORING.

The vulnerability scan scores every 50 m sample point with engine.evaluate_block (engine._worst loops it). A probe calls
that same function once, at a road position the user chose, with the same frozen 50 m radius; building categories come
from viz.categories, which also calls evaluate_block. The only logic here is choosing the position:

  * eligible positions = road within BLOCK_RADIUS_M of the neighbourhood's roads or its connections to major roads —
    the same region the scan searches (engine._worst: sample points "dwithin" that geometry);
  * the release point snaps to the nearest eligible road position, if that is within SNAP_TOL_M; otherwise rejected.

A probe result is never a scan result: it is labelled as the user's placed blockage and never changes the scan,
the ranking or the neighbourhood's classification.
"""
from __future__ import annotations

import shapely
from shapely.geometry import Point, mapping
from shapely.ops import nearest_points, transform

from . import engine, viz

SNAP_TOL_M = 60.0


_NBS: dict = {}


def _nb(area: engine.Area, nid: int) -> engine.Neighbourhood:
    """The engine's own neighbourhood object (engine.neighbourhoods, cached per loaded area object)."""
    key = (area.name, id(area))
    if key not in _NBS:
        _NBS[key] = {nb.nid: nb for nb in engine.neighbourhoods(area)}
    return _NBS[key][nid]


def _region(area: engine.Area, nb: engine.Neighbourhood):
    """The scan's search region for this neighbourhood (see engine._worst) and the road lines inside it."""
    reach = shapely.union_all([area.edges[i].line for i in nb.edge_idx] + [Point(area.node_xy[g]) for g in nb.gateways])
    region = reach.buffer(engine.BLOCK_RADIUS_M)
    idx = area.edge_tree.query(region, predicate="intersects")
    roads = shapely.union_all([area.edges[int(i)].line.intersection(region) for i in idx])
    return region, roads


def probe(area: engine.Area, result: dict, lon: float, lat: float) -> dict:
    """Evaluate the blockage the user placed near (lon, lat) for the scan result's neighbourhood."""
    if result["status"] == "not_assessed":      # the scan does not assess it; neither does a probe
        return dict(ok=False, reason="not_assessed", message="This neighbourhood is not assessed (edge of road data).")
    nb = _nb(area, result["nid"])
    p = Point(engine._TO_M(lon, lat))
    region, roads = _region(area, nb)
    if roads.is_empty:
        return dict(ok=False, reason="no_road", message="No road here to block.")
    snapped = nearest_points(roads, p)[0]
    dist = p.distance(snapped)
    if dist > SNAP_TOL_M:
        return dict(ok=False, reason="too_far",
                    message=f"No road of this neighbourhood within {SNAP_TOL_M:.0f} m of that point.")
    ev = engine.evaluate_block(area, nb, snapped)                         # the scan's own scoring function
    cats = viz.categories(area, dict(result, choke=snapped))               # same function, same centre
    ids = {s: {k: cats["sources"][s][k] for k in ("cut", "inside", "retain")} for s in engine.SOURCES}
    assert all(len(ids[s]["cut"]) == len(ev["cut_ids"][s]) for s in engine.SOURCES)
    counts = {k: {s: len(ids[s][k]) for s in engine.SOURCES} for k in ("cut", "inside", "retain")}
    to_ll = engine._TO_LL
    disc = snapped.buffer(engine.BLOCK_RADIUS_M)                           # the same circle evaluate_block used
    cut_lines = shapely.union_all([area.edges[i].line for i in ev["cut_edges"]]) if ev["cut_edges"] else None
    feats = [dict(type="Feature", properties=dict(kind="disc"), geometry=mapping(transform(to_ll, disc))),
             dict(type="Feature", properties=dict(kind="centre"), geometry=mapping(transform(to_ll, snapped)))]
    if cut_lines is not None:
        feats.append(dict(type="Feature", properties=dict(kind="cut"), geometry=mapping(transform(to_ll, cut_lines))))
    c_lon, c_lat = to_ll(snapped.x, snapped.y)
    return dict(ok=True, nid=result["nid"], centre=[round(c_lon, 7), round(c_lat, 7)], snap_m=round(dist, 1),
                radius_m=engine.BLOCK_RADIUS_M, cut=ev["cut"], cut_osm=ev["cut_osm"], cut_ms=ev["cut_ms"],
                counts=counts, ids=ids, geo=dict(type="FeatureCollection", features=feats))
