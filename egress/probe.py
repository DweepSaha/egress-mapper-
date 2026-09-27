"""User-placed blockage ("probe") for one neighbourhood. NO NEW SCORING.

The vulnerability scan scores every 50 m sample point with engine.evaluate_block (engine._worst loops it). A probe calls
that same function once, at a road position the user chose, with the same frozen 50 m radius; building categories come
from viz.categories, which also calls evaluate_block. The only logic here is choosing the position:

  * eligible positions = the neighbourhood's OWN roads plus its connections to major roads (the major-road stretch
    within BLOCK_RADIUS_M of each of its gateways). Roads of other neighbourhoods are never eligible, even when close;
  * the release point (the raw cursor position) snaps to the nearest eligible road position, if that is within
    SNAP_TOL_M; otherwise it is rejected. This is the ONLY analytical snap (the browser preview is a suggestion).

A probe result is never a scan result: it is labelled as the user's placed blockage and never changes the scan,
the ranking or the neighbourhood's classification.
"""
from __future__ import annotations

import shapely
from shapely.geometry import Point, mapping
from shapely.ops import nearest_points, transform

from . import engine, viz

SNAP_TOL_M = 60.0
SCAN_RADIUS_M = engine.BLOCK_RADIUS_M           # the scan's fixed 50 m disc (frozen)
MIN_RADIUS_M, MAX_RADIUS_M = 25.0, 300.0        # user probe only; the scan never changes


def evaluate_at_radius(area: engine.Area, nb: engine.Neighbourhood, centre: Point, radius_m: float) -> dict:
    """engine.evaluate_block with the radius as a parameter - a line-for-line copy of its 7-line wrapper (build the
    circle, find the removed nodes and each covered road's blocked intervals) feeding the SAME engine.evaluate_blockage
    scorer. At the scan radius the engine's own evaluate_block is called instead (tests assert the two are identical)."""
    if radius_m == SCAN_RADIUS_M:
        return engine.evaluate_block(area, nb, centre)
    return _evaluate_circle(area, nb, centre, radius_m)


def _evaluate_circle(area: engine.Area, nb: engine.Neighbourhood, centre: Point, radius_m: float) -> dict:
    """The copy of engine.evaluate_block's wrapper (tested identical to it at the scan radius)."""
    circle = centre.buffer(radius_m)
    removed = {int(area.node_ids[i]) for i in area.node_tree.query(circle, predicate="intersects")}
    nb_edges = set(nb.edge_idx)
    blocked = {}
    for i in area.edge_tree.query(circle, predicate="intersects"):
        i = int(i)
        if i in nb_edges:
            blocked[i] = engine._blocked_intervals(area.edges[i].line, circle)
    return engine.evaluate_blockage(area, nb, removed, blocked, circle)


def categories_at_radius(area: engine.Area, nb: engine.Neighbourhood, ev: dict, centre: Point, radius_m: float) -> dict:
    """viz.categories' rule (cut = evaluate result; inside = cohort centroids inside the circle; retain = the rest)."""
    cohort = nb.cohort(area)
    circle = centre.buffer(radius_m)
    out = {}
    for s in engine.SOURCES:
        inside = set(area.bld[s]["tree"].query(circle, predicate="contains").tolist()) & cohort[s]
        cut = ev["cut_ids"][s]
        out[s] = dict(cut=sorted(int(i) for i in cut), inside=sorted(int(i) for i in inside),
                      retain=sorted(int(i) for i in cohort[s] - cut - inside))
    return out


_NBS: dict = {}


def _nb(area: engine.Area, nid: int) -> engine.Neighbourhood:
    """The engine's own neighbourhood object (engine.neighbourhoods, cached per loaded area object)."""
    key = (area.name, id(area))
    if key not in _NBS:
        _NBS[key] = {nb.nid: nb for nb in engine.neighbourhoods(area)}
    return _NBS[key][nid]


_ELIG: dict = {}


def eligible_roads(area: engine.Area, nb: engine.Neighbourhood):
    """Where a probe may be placed: the neighbourhood's own roads, plus each of its connections to a major road (the
    major-road edges meeting one of its gateways, within BLOCK_RADIUS_M of that gateway). Nothing else."""
    key = (area.name, id(area), nb.nid)
    if key not in _ELIG:
        lines = [area.edges[i].line for i in nb.edge_idx]
        for g in nb.gateways:
            disc = Point(area.node_xy[g]).buffer(engine.BLOCK_RADIUS_M)
            for i in area.edge_tree.query(disc, predicate="intersects"):
                e = area.edges[int(i)]
                if e.exit and g in (e.u, e.v):
                    lines.append(e.line.intersection(disc))
        _ELIG[key] = shapely.union_all(lines)
    return _ELIG[key]


def eligible_geojson(area: engine.Area, result: dict) -> dict:
    """The eligible roads in lon/lat, so the browser preview uses the same set the server enforces."""
    if result["status"] == "not_assessed":
        return dict(type="FeatureCollection", features=[])
    g = transform(engine._TO_LL, eligible_roads(area, _nb(area, result["nid"])))
    return dict(type="FeatureCollection", features=[dict(type="Feature", properties={}, geometry=mapping(g))])


def probe(area: engine.Area, result: dict, lon: float, lat: float, radius_m: float = SCAN_RADIUS_M) -> dict:
    """Evaluate the blockage the user placed near (lon, lat), with the user's radius, for the scan result's
    neighbourhood. A radius other than the scan's 50 m is a user experiment: not comparable with the scan finding."""
    radius_m = float(radius_m)
    if not (MIN_RADIUS_M <= radius_m <= MAX_RADIUS_M):
        return dict(ok=False, reason="bad_radius", message=f"Radius must be {MIN_RADIUS_M:.0f}-{MAX_RADIUS_M:.0f} m.")
    if result["status"] == "not_assessed":      # the scan does not assess it; neither does a probe
        return dict(ok=False, reason="not_assessed", message="This neighbourhood is not assessed (edge of road data).")
    nb = _nb(area, result["nid"])
    p = Point(engine._TO_M(lon, lat))
    roads = eligible_roads(area, nb)
    if roads.is_empty:
        return dict(ok=False, reason="no_road", message="No road here to block.")
    snapped = nearest_points(roads, p)[0]
    dist = p.distance(snapped)
    if dist > SNAP_TOL_M:
        return dict(ok=False, reason="too_far",
                    message=f"No road of this neighbourhood within {SNAP_TOL_M:.0f} m of that point.")
    if radius_m == SCAN_RADIUS_M:
        ev = engine.evaluate_block(area, nb, snapped)                     # the scan's own scoring function
        cats = viz.categories(area, dict(result, choke=snapped))           # same function, same centre
        ids = {s: {k: cats["sources"][s][k] for k in ("cut", "inside", "retain")} for s in engine.SOURCES}
    else:
        ev = evaluate_at_radius(area, nb, snapped, radius_m)               # same scorer, the user's circle
        ids = categories_at_radius(area, nb, ev, snapped, radius_m)
    assert all(len(ids[s]["cut"]) == len(ev["cut_ids"][s]) for s in engine.SOURCES)
    counts = {k: {s: len(ids[s][k]) for s in engine.SOURCES} for k in ("cut", "inside", "retain")}
    to_ll = engine._TO_LL
    disc = snapped.buffer(radius_m)                                        # the same circle that was evaluated
    cut_lines = shapely.union_all([area.edges[i].line for i in ev["cut_edges"]]) if ev["cut_edges"] else None
    feats = [dict(type="Feature", properties=dict(kind="disc"), geometry=mapping(transform(to_ll, disc))),
             dict(type="Feature", properties=dict(kind="centre"), geometry=mapping(transform(to_ll, snapped)))]
    if cut_lines is not None:
        feats.append(dict(type="Feature", properties=dict(kind="cut"), geometry=mapping(transform(to_ll, cut_lines))))
    c_lon, c_lat = to_ll(snapped.x, snapped.y)
    return dict(ok=True, nid=result["nid"], centre=[round(c_lon, 7), round(c_lat, 7)], snap_m=round(dist, 1),
                radius_m=radius_m, scan_radius_m=SCAN_RADIUS_M, comparable_with_scan=radius_m == SCAN_RADIUS_M, cut=ev["cut"], cut_osm=ev["cut_osm"], cut_ms=ev["cut_ms"],
                counts=counts, ids=ids, geo=dict(type="FeatureCollection", features=feats))
