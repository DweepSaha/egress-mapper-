"""Vulnerability scan engine.

Model
-----
* Roads: the prepared drivable network, projected to EPSG:2953, treated as undirected (one-way rules ignored).
* Exit roads: collector/arterial classes (EXIT_CLASSES). Reaching any exit road counts as "out".
* Neighbourhood: a connected cluster of local roads after removing exit roads. Its gateways are the points where
  those local roads meet an exit road.
* Homes: building footprints >= MIN_HOME_M2, OSM and Microsoft counted separately; every count uses the higher.
  Each footprint is attached to its nearest road (within MAX_ASSIGN_M).
* Sweep: a circle of BLOCK_RADIUS_M centred every SWEEP_SPACING_M along the roads. Roads are impassable only where
  the circle touches them. Homes whose route to every gateway is cut are "cut off"; homes inside the circle are
  counted separately as "in the blocked area".
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import shapely
from shapely.geometry import LineString, Point, box, mapping
from shapely.ops import transform
from pyproj import Transformer

from . import config

# ---- frozen parameters (do not tune to validation results) ----
BLOCK_RADIUS_M = 50.0
SWEEP_SPACING_M = 50.0
EXIT_CLASSES = {"tertiary", "tertiary_link", "secondary", "secondary_link", "primary", "primary_link",
                "trunk", "trunk_link", "motorway", "motorway_link"}
MIN_HOMES = 30            # neighbourhood threshold (California SB 99 practice)
RED_MIN_CUT = 30          # red: worst single blockage cuts off >= 30 homes
BOUNDARY_BUFFER_M = 2000  # not assessed within this distance of the study-box edge
MIN_HOME_M2 = 40.0        # footprints smaller than this are treated as sheds/garages
MAX_ASSIGN_M = 150.0      # footprints farther than this from any road are not attached

# study boxes (lon/lat) the road extracts were cut from; see DATA.md
STUDY_BBOX = {
    "fredericton": (-66.91630, 45.75717, -66.38280, 46.14033),
    "tantallon": (-63.92099, 44.64583, -63.68461, 44.81847),
    "pointe_sapin": (-65.08820, 46.74423, -64.77630, 47.07787),
}


def _classes(hw) -> set[str]:
    return set(hw) if isinstance(hw, list) else {hw}


@dataclass
class Edge:
    u: int
    v: int
    line: LineString          # oriented from u to v
    exit: bool                # qualifying class AND part of the through-road system (see _mark_spurs)
    qualifying: bool = False  # collector/arterial class, before the spur rule
    homes_t: dict = field(default_factory=lambda: {"osm": np.empty(0), "ms": np.empty(0)})  # positions along line


@dataclass
class Area:
    name: str
    edges: list[Edge]
    node_xy: dict[int, tuple[float, float]]
    exit_nodes: set[int]
    edge_tree: shapely.STRtree
    node_ids: np.ndarray
    node_tree: shapely.STRtree
    assessable: shapely.Geometry   # study box shrunk by BOUNDARY_BUFFER_M, EPSG:2953
    stats: dict


def load_area(name: str) -> Area:
    G = ox.load_graphml(config.roads_graphml(name))
    G = ox.project_graph(G, to_crs=config.ANALYSIS_CRS)
    U = ox.convert.to_undirected(G)
    node_xy = {n: (d["x"], d["y"]) for n, d in U.nodes(data=True)}

    edges = []
    for u, v, d in U.edges(data=True):
        line = d.get("geometry") or LineString([node_xy[u], node_xy[v]])
        if Point(line.coords[0]).distance(Point(node_xy[u])) > Point(line.coords[0]).distance(Point(node_xy[v])):
            line = LineString(line.coords[::-1])  # orient u -> v
        q = bool(_classes(d.get("highway")) & EXIT_CLASSES)
        edges.append(Edge(u, v, line, exit=q, qualifying=q))

    to_m = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True).transform
    study = transform(to_m, box(*STUDY_BBOX[name]))
    spur_stats = _mark_spurs(edges, node_xy, study)
    exit_nodes = {n for e in edges if e.exit for n in (e.u, e.v)}

    edge_tree = shapely.STRtree([e.line for e in edges])
    node_ids = np.array(list(node_xy))
    node_tree = shapely.STRtree([Point(node_xy[n]) for n in node_ids])
    assessable = study.buffer(-BOUNDARY_BUFFER_M)

    area = Area(name, edges, node_xy, exit_nodes, edge_tree, node_ids, node_tree, assessable, {"spurs": spur_stats})
    _attach_homes(area)
    return area


WORLD = "__outside_world__"


def _mark_spurs(edges: list[Edge], node_xy: dict, study) -> dict:
    """Spur rule: a qualifying road is a way out only if it gives onward access through the broader road system.

    The broader system is anchored where qualifying roads leave the study box (their points outside it all join a
    virtual WORLD node). Split the qualifying-road network into biconnected sections; a qualifying road counts as a
    way out only if its section contains WORLD. A branch attached to that system through a single point is a spur
    and is reclassified as local road.
    """
    X = nx.Graph()
    for e in edges:
        if e.qualifying and e.u != e.v:
            X.add_edge(e.u, e.v)
    for n in list(X.nodes):
        if not study.contains(Point(node_xy[n])):
            X.add_edge(n, WORLD)
    through = set()
    if WORLD in X:
        for block in nx.biconnected_component_edges(X):
            if any(WORLD in pair for pair in block):
                through.update(frozenset(p) for p in block)
    n_spur = 0
    for e in edges:
        if e.qualifying and frozenset((e.u, e.v)) not in through:
            e.exit = False
            n_spur += 1
    return dict(qualifying=sum(e.qualifying for e in edges), spur_reclassified=n_spur)


def _attach_homes(area: Area) -> None:
    lines = np.array([e.line for e in area.edges], dtype=object)
    for src, path in (("osm", config.buildings_osm(area.name)), ("ms", config.buildings_ms(area.name))):
        b = gpd.read_file(path).to_crs(config.ANALYSIS_CRS)
        n_all = len(b)
        b = b[b.geometry.area >= MIN_HOME_M2]
        pts = b.geometry.centroid.values
        (pi, ei), dist = area.edge_tree.query_nearest(pts, max_distance=MAX_ASSIGN_M, return_distance=True)
        _, first = np.unique(pi, return_index=True)          # ties: keep one edge per building
        pi, ei = pi[first], ei[first]
        t = shapely.line_locate_point(lines[ei], pts[pi])
        by_edge = defaultdict(list)
        for e_idx, tt in zip(ei, t):
            by_edge[e_idx].append(tt)
        for e_idx, ts in by_edge.items():
            area.edges[e_idx].homes_t[src] = np.array(ts)
        area.stats[src] = dict(footprints=n_all, homes=len(b), attached=len(pi),
                               on_exit_roads=int(sum(area.edges[i].exit for i in ei)))


@dataclass
class Neighbourhood:
    nid: int
    local_nodes: set[int]
    gateways: set[int]
    edge_idx: list[int]
    homes: dict            # {"osm": n, "ms": n}

    @property
    def n_homes(self) -> int:
        return max(self.homes["osm"], self.homes["ms"])


def neighbourhoods(area: Area) -> list[Neighbourhood]:
    """Connected clusters of local roads, split at exit-road nodes."""
    L = nx.Graph()
    for i, e in enumerate(area.edges):
        if not e.exit:
            for n in (e.u, e.v):
                if n not in area.exit_nodes:
                    L.add_node(n)
            if e.u not in area.exit_nodes and e.v not in area.exit_nodes:
                L.add_edge(e.u, e.v)
    comp_of = {}
    comps = list(nx.connected_components(L))
    for c, nodes in enumerate(comps):
        for n in nodes:
            comp_of[n] = c
    out = [Neighbourhood(c, set(nodes), set(), [], {"osm": 0, "ms": 0}) for c, nodes in enumerate(comps)]
    for i, e in enumerate(area.edges):
        if e.exit:
            continue
        c = comp_of.get(e.u, comp_of.get(e.v))
        if c is None:          # local edge directly between two exit nodes: no neighbourhood
            continue
        nb = out[c]
        nb.edge_idx.append(i)
        for n in (e.u, e.v):
            if n in area.exit_nodes:
                nb.gateways.add(n)
        for src in ("osm", "ms"):
            nb.homes[src] += len(e.homes_t[src])
    return out


def _blocked_interval(line: LineString, circle) -> tuple[float, float] | None:
    inter = line.intersection(circle)
    if inter.is_empty:
        return None
    ts = [line.project(Point(c)) for g in getattr(inter, "geoms", [inter]) for c in g.coords]
    return (min(ts), max(ts))


def evaluate_block(area: Area, nb: Neighbourhood, centre: Point) -> dict:
    """Homes in `nb` cut off from every gateway when a circle at `centre` is blocked."""
    circle = centre.buffer(BLOCK_RADIUS_M)
    removed = {int(area.node_ids[i]) for i in area.node_tree.query(circle, predicate="intersects")}
    nb_edges = set(nb.edge_idx)
    blocked = {int(i): _blocked_interval(area.edges[int(i)].line, circle)
               for i in area.edge_tree.query(circle, predicate="intersects") if int(i) in nb_edges}

    adj = defaultdict(list)
    for i in nb.edge_idx:
        if i in blocked:
            continue
        e = area.edges[i]
        adj[e.u].append(e.v)
        adj[e.v].append(e.u)
    reach = {g for g in nb.gateways if g not in removed}
    q = deque(reach)
    while q:
        n = q.popleft()
        for m in adj[n]:
            if m not in reach and m not in removed:
                reach.add(m)
                q.append(m)

    cut = {"osm": 0, "ms": 0}
    inside = {"osm": 0, "ms": 0}
    cut_edges = set()
    for i in nb.edge_idx:
        e = area.edges[i]
        iv = blocked.get(i)
        if iv is None and e.u not in reach and e.v not in reach:
            cut_edges.add(i)   # the whole road segment has lost its way out (with or without homes on it)
        for src in ("osm", "ms"):
            t = e.homes_t[src]
            if not len(t):
                continue
            if iv is None:
                if e.u not in reach and e.v not in reach:
                    cut[src] += len(t)
                continue
            a, b = iv
            before, after = t < a, t > b
            inside[src] += int((~before & ~after).sum())
            if e.u not in reach:
                cut[src] += int(before.sum())
            if e.v not in reach:
                cut[src] += int(after.sum())
    return dict(cut=max(cut.values()), cut_osm=cut["osm"], cut_ms=cut["ms"], inside=max(inside.values()),
                cut_edges=cut_edges)


def sample_points(area: Area) -> list[Point]:
    pts = []
    for e in area.edges:
        L = e.line.length
        for d in np.arange(0.0, L + 1e-9, SWEEP_SPACING_M):
            pts.append(e.line.interpolate(d))
        if L % SWEEP_SPACING_M:
            pts.append(Point(e.line.coords[-1]))
    return pts


def scan(area: Area, only_nodes: set[int] | None = None, min_homes: int = MIN_HOMES) -> list[dict]:
    """Vulnerability scan: worst single blockage per neighbourhood of MIN_HOMES+ homes.
    only_nodes: restrict to neighbourhoods containing any of these road nodes (used by the mitigation test)."""
    pts = sample_points(area)
    pt_tree = shapely.STRtree(pts)
    results = []
    for nb in neighbourhoods(area):
        if only_nodes is not None and not (only_nodes & (nb.local_nodes | nb.gateways)):
            continue
        if nb.n_homes < min_homes or not nb.gateways:
            continue
        lines = [area.edges[i].line for i in nb.edge_idx]
        footprint = shapely.union_all([l.buffer(40) for l in lines])   # display shape only
        # boundary rule applies to the roads themselves, not the 40 m display buffer
        assessed = area.assessable.contains(shapely.union_all(lines))
        worst = dict(cut=0, cut_osm=0, cut_ms=0, inside=0, cut_edges=set())
        worst_pt = None
        if assessed:
            reach_geom = shapely.union_all(lines + [Point(area.node_xy[g]) for g in nb.gateways])
            for j in pt_tree.query(reach_geom, predicate="dwithin", distance=BLOCK_RADIUS_M):
                r = evaluate_block(area, nb, pts[int(j)])
                if r["cut"] > worst["cut"]:
                    worst, worst_pt = r, pts[int(j)]
        status = ("not_assessed" if not assessed else
                  "red" if worst["cut"] >= RED_MIN_CUT else "amber" if worst["cut"] > 0 else "green")
        results.append(dict(nid=nb.nid, status=status, homes=nb.n_homes, homes_osm=nb.homes["osm"],
                            homes_ms=nb.homes["ms"], gateways=len(nb.gateways), worst_cut=worst["cut"],
                            worst_cut_osm=worst["cut_osm"], worst_cut_ms=worst["cut_ms"],
                            worst_inside=worst["inside"], choke=worst_pt, geometry=footprint,
                            streets=shapely.MultiLineString(lines),   # display only: the neighbourhood's roads
                            cut_lines=shapely.union_all([area.edges[i].line for i in worst["cut_edges"]])
                            if worst["cut_edges"] else None))
    # rank the assessed neighbourhoods by homes that could be cut off (1 = worst)
    ranked = sorted((r for r in results if r["worst_cut"] > 0), key=lambda r: -r["worst_cut"])
    for k, r in enumerate(ranked, 1):
        r["rank"] = k
    for r in results:
        r.setdefault("rank", None)
    return results


SNAP_MAX_M = 400.0
_TO_M = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True).transform


def _snap(area: Area, lonlat) -> int | None:
    p = Point(_TO_M(*lonlat))
    i, d = area.node_tree.query_nearest(p, return_distance=True)
    return int(area.node_ids[i[0]]) if len(i) and d[0] <= SNAP_MAX_M else None


def with_new_road(area: Area, a: int, b: int) -> tuple[Area, LineString]:
    """A temporary copy of the area with one proposed local road from node a to node b (cache untouched)."""
    line = LineString([area.node_xy[a], area.node_xy[b]])
    new = Edge(a, b, line, exit=False, qualifying=False)
    edges = area.edges + [new]
    copy = Area(area.name, edges, area.node_xy, area.exit_nodes, shapely.STRtree([e.line for e in edges]),
                area.node_ids, area.node_tree, area.assessable, area.stats)
    return copy, line


def _choke_cut(area: Area, nodes: set[int], centre: Point) -> dict:
    """Buildings cut off by a blockage at `centre`, within the neighbourhood that contains `nodes`."""
    for nb in neighbourhoods(area):
        if nodes & nb.local_nodes:
            return evaluate_block(area, nb, centre) if nb.gateways else dict(cut=nb.n_homes, cut_edges=set(nb.edge_idx))
    return dict(cut=0, cut_edges=set())


def mitigate(area: Area, a_ll, b_ll) -> dict:
    """Mitigation test: add a proposed road between the road points nearest two clicks and re-scan what it touches."""
    a, b = _snap(area, a_ll), _snap(area, b_ll)
    if a is None or b is None:
        return dict(ok=False, message=f"Each end must be within {SNAP_MAX_M:.0f} m of an existing road.")
    if a == b:
        return dict(ok=False, message="Both ends snapped to the same road point; draw a longer road.")
    touched = {a, b}
    before = scan(area, only_nodes=touched, min_homes=1)
    before = [r for r in before if r["status"] != "not_assessed" and r["worst_cut"] > 0]
    if not before:
        return dict(ok=False, message="This road doesn't connect to an assessed neighbourhood with a choke point.")
    worst = max(before, key=lambda r: r["worst_cut"])
    new_area, line = with_new_road(area, a, b)
    nb_nodes = next(nb.local_nodes for nb in neighbourhoods(area) if nb.nid == worst["nid"])
    same_block = _choke_cut(new_area, nb_nodes, worst["choke"])
    after = scan(new_area, only_nodes=nb_nodes | touched, min_homes=1)
    after = max(after, key=lambda r: r["homes"]) if after else None
    regained = max(0, worst["worst_cut"] - same_block["cut"])
    to_ll = _TO_LL
    return dict(
        ok=True,
        road=dict(type="Feature", properties=dict(length_m=round(line.length)), geometry=mapping(transform(to_ll, line))),
        length_m=round(line.length),
        before=dict(nid=worst["nid"], homes=worst["homes"], worst_cut=worst["worst_cut"], status=worst["status"]),
        same_block_cut=same_block["cut"],
        regained=regained,
        after=None if after is None else dict(homes=after["homes"], worst_cut=after["worst_cut"], status=after["status"],
                                              gateways=after["gateways"]),
        after_geo=results_geojson([after]) if after is not None else None,
    )


_TO_LL = Transformer.from_crs(config.ANALYSIS_CRS, "EPSG:4326", always_xy=True).transform
GEOM_KEYS = ("geometry", "choke", "cut_lines", "streets")


def _fc(feats):
    return dict(type="FeatureCollection", features=feats)


def results_geojson(results: list[dict]) -> dict:
    """Web-ready (lon/lat) feature collections: neighbourhoods, choke points (+ blocked circle), cut roads."""
    nb, streets, choke, circles, cut = [], [], [], [], []
    for r in results:
        props = {k: v for k, v in r.items() if k not in GEOM_KEYS}
        nb.append(dict(type="Feature", id=r["nid"], properties=props,
                       geometry=mapping(transform(_TO_LL, r["geometry"].simplify(5)))))
        streets.append(dict(type="Feature", id=r["nid"],
                            properties=dict(nid=r["nid"], status=r["status"], worst_cut=r["worst_cut"]),
                            geometry=mapping(transform(_TO_LL, r["streets"].simplify(2)))))
        if r["choke"] is not None:
            p = dict(nid=r["nid"], status=r["status"], worst_cut=r["worst_cut"], rank=r["rank"],
                     radius_m=BLOCK_RADIUS_M)
            choke.append(dict(type="Feature", properties=p, geometry=mapping(transform(_TO_LL, r["choke"]))))
            circles.append(dict(type="Feature", properties=p,
                                geometry=mapping(transform(_TO_LL, r["choke"].buffer(BLOCK_RADIUS_M, 24)))))
        if r["cut_lines"] is not None:
            cut.append(dict(type="Feature", properties=dict(nid=r["nid"]),
                            geometry=mapping(transform(_TO_LL, r["cut_lines"]))))
    return dict(neighbourhoods=_fc(nb), streets=_fc(streets), chokepoints=_fc(choke), blocked=_fc(circles),
                cut_roads=_fc(cut))


def roads_geojson(area: Area) -> dict:
    return _fc([dict(type="Feature", properties=dict(way_out=e.exit),
                     geometry=mapping(transform(_TO_LL, e.line.simplify(2)))) for e in area.edges])


def boundary_geojson(area: Area) -> dict:
    """The not-assessed band: study box minus the assessable interior."""
    study = area.assessable.buffer(BOUNDARY_BUFFER_M, join_style="mitre")
    return _fc([dict(type="Feature", properties={},
                     geometry=mapping(transform(_TO_LL, study.difference(area.assessable))))])


def to_geojson(results: list[dict], path_nb, path_choke) -> None:
    g = results_geojson(results)
    for path, fc in ((path_nb, g["neighbourhoods"]), (path_choke, g["chokepoints"])):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fc), encoding="utf-8")
