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
    exit: bool
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

    edges, exit_nodes = [], set()
    for u, v, d in U.edges(data=True):
        line = d.get("geometry") or LineString([node_xy[u], node_xy[v]])
        if Point(line.coords[0]).distance(Point(node_xy[u])) > Point(line.coords[0]).distance(Point(node_xy[v])):
            line = LineString(line.coords[::-1])  # orient u -> v
        is_exit = bool(_classes(d.get("highway")) & EXIT_CLASSES)
        edges.append(Edge(u, v, line, is_exit))
        if is_exit:
            exit_nodes.update((u, v))

    edge_tree = shapely.STRtree([e.line for e in edges])
    node_ids = np.array(list(node_xy))
    node_tree = shapely.STRtree([Point(node_xy[n]) for n in node_ids])

    to_m = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True).transform
    assessable = transform(to_m, box(*STUDY_BBOX[name])).buffer(-BOUNDARY_BUFFER_M)

    area = Area(name, edges, node_xy, exit_nodes, edge_tree, node_ids, node_tree, assessable, {})
    _attach_homes(area)
    return area


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
    for i in nb.edge_idx:
        e = area.edges[i]
        iv = blocked.get(i)
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
    return dict(cut=max(cut.values()), cut_osm=cut["osm"], cut_ms=cut["ms"], inside=max(inside.values()))


def sample_points(area: Area) -> list[Point]:
    pts = []
    for e in area.edges:
        L = e.line.length
        for d in np.arange(0.0, L + 1e-9, SWEEP_SPACING_M):
            pts.append(e.line.interpolate(d))
        if L % SWEEP_SPACING_M:
            pts.append(Point(e.line.coords[-1]))
    return pts


def scan(area: Area) -> list[dict]:
    """Vulnerability scan: worst single blockage per neighbourhood of MIN_HOMES+ homes."""
    pts = sample_points(area)
    pt_tree = shapely.STRtree(pts)
    results = []
    for nb in neighbourhoods(area):
        if nb.n_homes < MIN_HOMES or not nb.gateways:
            continue
        lines = [area.edges[i].line for i in nb.edge_idx]
        footprint = shapely.union_all([l.buffer(40) for l in lines])
        assessed = area.assessable.contains(footprint)
        worst = dict(cut=0, cut_osm=0, cut_ms=0, inside=0)
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
                            worst_inside=worst["inside"], choke=worst_pt, geometry=footprint))
    return results


def to_geojson(results: list[dict], path_nb, path_choke) -> None:
    to_ll = Transformer.from_crs(config.ANALYSIS_CRS, "EPSG:4326", always_xy=True).transform
    nb_feats, choke_feats = [], []
    for r in results:
        props = {k: v for k, v in r.items() if k not in ("geometry", "choke")}
        nb_feats.append(dict(type="Feature", properties=props,
                             geometry=mapping(transform(to_ll, r["geometry"].simplify(5)))))
        if r["choke"] is not None:
            choke_feats.append(dict(type="Feature", properties=dict(nid=r["nid"], status=r["status"],
                                                                    worst_cut=r["worst_cut"],
                                                                    radius_m=BLOCK_RADIUS_M),
                                    geometry=mapping(transform(to_ll, r["choke"]))))
    for path, feats in ((path_nb, nb_feats), (path_choke, choke_feats)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(type="FeatureCollection", features=feats)), encoding="utf-8")
