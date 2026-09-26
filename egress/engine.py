"""Vulnerability scan engine.

Model
-----
* Roads: the prepared drivable network, projected to EPSG:2953, treated as undirected (one-way rules ignored).
* Exit roads: collector/arterial classes (EXIT_CLASSES) that pass the spur rule. Reaching any exit road counts as "out".
* Neighbourhood: a connected cluster of local roads after removing exit roads; its gateways are the points where those
  local roads meet an exit road. A local road whose ends are both exit-road junctions (or a local loop on one junction)
  is its own neighbourhood, so its buildings are never dropped.
* Homes (shown as "mapped buildings"): footprints >= MIN_HOME_M2, OSM and Microsoft counted separately; every reported
  count uses the higher. Each building keeps an id, its centroid, and its attachment position on its nearest road
  (within MAX_ASSIGN_M).
* Sweep: a circle of BLOCK_RADIUS_M centred every SWEEP_SPACING_M along the roads. Roads are impassable only on the
  stretches the circle covers (a winding road can have several). A building whose centroid lies inside the circle is
  "in the blocked area"; any other building that can no longer reach a usable gateway is "cut off".
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

SOURCES = ("osm", "ms")

# study boxes (lon/lat) the road extracts were cut from; see DATA.md
STUDY_BBOX = {
    "fredericton": (-66.91630, 45.75717, -66.38280, 46.14033),
    "tantallon": (-63.92099, 44.64583, -63.68461, 44.81847),
    "pointe_sapin": (-65.08820, 46.74423, -64.77630, 47.07787),
}


def _classes(hw) -> set[str]:
    return set(hw) if isinstance(hw, list) else {hw}


def _empty_src():
    return {s: np.empty(0) for s in SOURCES}


@dataclass
class Edge:
    u: int
    v: int
    line: LineString          # oriented from u to v
    exit: bool                # qualifying class AND part of the through-road system (see _mark_spurs)
    qualifying: bool = False  # collector/arterial class, before the spur rule
    homes_t: dict = field(default_factory=_empty_src)   # attachment position along line, per source
    homes_id: dict = field(default_factory=_empty_src)  # building ids (index into Area.bld[src]["pts"]), per source


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
    bld: dict = field(default_factory=dict)   # src -> {"pts": centroids (EPSG:2953), "tree": STRtree}


def load_area(name: str) -> Area:
    G = ox.load_graphml(config.roads_graphml(name))
    G = ox.project_graph(G, to_crs=config.ANALYSIS_CRS)
    U = ox.convert.to_undirected(G)
    node_xy = {n: (d["x"], d["y"]) for n, d in U.nodes(data=True)}
    roads = [(u, v, d.get("geometry"), d.get("highway")) for u, v, d in U.edges(data=True)]
    to_m = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True).transform
    study = transform(to_m, box(*STUDY_BBOX[name]))
    buildings, bstats = {}, {}
    for src, path in (("osm", config.buildings_osm(name)), ("ms", config.buildings_ms(name))):
        b = gpd.read_file(path).to_crs(config.ANALYSIS_CRS)
        n_all = len(b)
        b = b[b.geometry.area >= MIN_HOME_M2]
        buildings[src] = b.geometry.centroid.values
        bstats[src] = dict(footprints=n_all, homes=len(b))
    area = build_area(name, roads, node_xy, study, buildings)
    for src in SOURCES:
        area.stats[src].update(bstats[src])
    return area


def build_area(name: str, roads, node_xy: dict, study, buildings: dict) -> Area:
    """Build an Area from roads [(u, v, geometry|None, highway)], node coordinates, the study box polygon and building
    centroids {src: array of shapely Points}, all in EPSG:2953. Used by load_area and by the regression tests."""
    edges = []
    for u, v, geom, hw in roads:
        line = geom or LineString([node_xy[u], node_xy[v]])
        if Point(line.coords[0]).distance(Point(node_xy[u])) > Point(line.coords[0]).distance(Point(node_xy[v])):
            line = LineString(line.coords[::-1])  # orient u -> v
        q = bool(_classes(hw) & EXIT_CLASSES)
        edges.append(Edge(u, v, line, exit=q, qualifying=q))
    spur_stats = _mark_spurs(edges, node_xy, study)
    exit_nodes = {n for e in edges if e.exit for n in (e.u, e.v)}
    node_ids = np.array(list(node_xy))
    area = Area(name, edges, node_xy, exit_nodes, shapely.STRtree([e.line for e in edges]), node_ids,
                shapely.STRtree([Point(node_xy[n]) for n in node_ids]), study.buffer(-BOUNDARY_BUFFER_M),
                {"spurs": spur_stats})
    _attach_homes(area, buildings)
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


def _attach_homes(area: Area, buildings: dict) -> None:
    lines = np.array([e.line for e in area.edges], dtype=object)
    for src in SOURCES:
        pts = np.asarray(buildings.get(src, []), dtype=object)
        area.bld[src] = dict(pts=pts, tree=shapely.STRtree(pts))
        if not len(pts):
            area.stats[src] = dict(attached=0, on_exit_roads=0)
            continue
        (pi, ei), _ = area.edge_tree.query_nearest(pts, max_distance=MAX_ASSIGN_M, return_distance=True)
        _, first = np.unique(pi, return_index=True)          # ties: keep one edge per building
        pi, ei = pi[first], ei[first]
        t = shapely.line_locate_point(lines[ei], pts[pi])
        by_edge = defaultdict(lambda: ([], []))
        for b_id, e_idx, tt in zip(pi, ei, t):
            by_edge[e_idx][0].append(tt)
            by_edge[e_idx][1].append(b_id)
        for e_idx, (ts, ids) in by_edge.items():
            area.edges[e_idx].homes_t[src] = np.array(ts)
            area.edges[e_idx].homes_id[src] = np.array(ids, dtype=int)
        area.stats[src] = dict(attached=len(pi), on_exit_roads=int(sum(area.edges[i].exit for i in ei)))


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

    def cohort(self, area: Area) -> dict:
        """The building ids attached to this neighbourhood's roads, per source."""
        return {s: set(np.concatenate([area.edges[i].homes_id[s] for i in self.edge_idx] or [np.empty(0)]).astype(int))
                for s in SOURCES}


def neighbourhoods(area: Area) -> list[Neighbourhood]:
    """Connected clusters of local roads, split at exit-road nodes. A local road whose ends are both exit-road nodes
    (including a local loop on a single exit node) becomes its own neighbourhood."""
    L = nx.Graph()
    for e in area.edges:
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
        if c is None:          # both ends are exit-road junctions: the road's interior is its own neighbourhood
            out.append(Neighbourhood(len(out), set(), set(), [], {"osm": 0, "ms": 0}))
            c = len(out) - 1
        nb = out[c]
        nb.edge_idx.append(i)
        for n in (e.u, e.v):
            if n in area.exit_nodes:
                nb.gateways.add(n)
        for src in SOURCES:
            nb.homes[src] += len(e.homes_t[src])
    return out


def _blocked_intervals(line: LineString, geom) -> list[tuple[float, float]]:
    """Separate stretches of `line` covered by `geom`, as sorted, merged (start, end) positions along the line.

    Computed segment by segment while accumulating the distance travelled, so a road that retraces the same physical
    stretch gets each traversal's own position (line.project would return only the first pass)."""
    coords = list(line.coords)
    ivs, run = [], 0.0
    for p, q in zip(coords, coords[1:]):
        seg = LineString([p, q])
        L = seg.length
        if L > 0 and seg.intersects(geom):
            inter = seg.intersection(geom)
            for g in getattr(inter, "geoms", [inter]):
                if g.is_empty:
                    continue
                ts = [Point(p).distance(Point(c)) for c in g.coords]   # distance along this straight segment
                ivs.append((run + min(ts), run + max(ts)))
        run += L
    if not ivs:
        return []
    ivs.sort()
    merged = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [tuple(m) for m in merged]


def _member(ids: np.ndarray, s: set) -> np.ndarray:
    """Boolean mask: which ids are in set s (small per-segment arrays; faster than np.isin here)."""
    if not s:
        return np.zeros(len(ids), dtype=bool)
    return np.fromiter((int(i) in s for i in ids), dtype=bool, count=len(ids))


def evaluate_blockage(area: Area, nb: Neighbourhood, removed: set, blocked: dict, zone,
                      gateways: set | None = None, cohort: dict | None = None) -> dict:
    """Buildings in `nb` cut off from every usable gateway.

    removed: road nodes inside the blocked zone; blocked: edge index -> list of blocked intervals; zone: the blocked
    geometry (a building whose centroid is inside it is "in the blocked area", not "cut off"); gateways: optionally
    restrict to gateways still connected onward; cohort: optionally count only these building ids per source."""
    usable = nb.gateways if gateways is None else nb.gateways & gateways
    adj = defaultdict(list)
    for i in nb.edge_idx:
        if i in blocked:
            continue
        e = area.edges[i]
        adj[e.u].append(e.v)
        adj[e.v].append(e.u)
    reach = {g for g in usable if g not in removed}
    q = deque(reach)
    while q:
        n = q.popleft()
        for m in adj[n]:
            if m not in reach and m not in removed:
                reach.add(m)
                q.append(m)

    inzone = {s: set(area.bld[s]["tree"].query(zone, predicate="contains").tolist()) for s in SOURCES}
    cut_ids = {s: set() for s in SOURCES}
    in_block_ids = {s: set() for s in SOURCES}
    cut_edges = set()
    for i in nb.edge_idx:
        e = area.edges[i]
        ivs = blocked.get(i)
        u_ok, v_ok = e.u in reach, e.v in reach
        if not ivs and not u_ok and not v_ok:
            cut_edges.add(i)   # the whole road segment has lost its way out (with or without homes on it)
        for s in SOURCES:
            t, ids = e.homes_t[s], e.homes_id[s]
            if not len(t):
                continue
            if cohort is not None:
                keep = _member(ids, cohort[s])
                t, ids = t[keep], ids[keep]
                if not len(t):
                    continue
            if ivs:   # before the first blocked stretch -> via u; after the last -> via v; between -> trapped
                ok = ((t < ivs[0][0]) & u_ok) | ((t > ivs[-1][1]) & v_ok)
            else:
                ok = np.full(len(t), u_ok or v_ok)
            phys = _member(ids, inzone[s])
            in_block_ids[s].update(ids[phys].tolist())
            cut_ids[s].update(ids[~ok & ~phys].tolist())
    cut = {s: len(cut_ids[s]) for s in SOURCES}
    inside = {s: len(in_block_ids[s]) for s in SOURCES}
    return dict(cut=max(cut.values()), cut_osm=cut["osm"], cut_ms=cut["ms"], inside=max(inside.values()),
                cut_edges=cut_edges, cut_ids=cut_ids)


def evaluate_block(area: Area, nb: Neighbourhood, centre: Point, cohort: dict | None = None) -> dict:
    """Buildings in `nb` cut off from every gateway when a circle at `centre` is blocked."""
    circle = centre.buffer(BLOCK_RADIUS_M)
    removed = {int(area.node_ids[i]) for i in area.node_tree.query(circle, predicate="intersects")}
    nb_edges = set(nb.edge_idx)
    blocked = {}
    for i in area.edge_tree.query(circle, predicate="intersects"):
        i = int(i)
        if i in nb_edges:
            blocked[i] = _blocked_intervals(area.edges[i].line, circle)
    return evaluate_blockage(area, nb, removed, blocked, circle, cohort=cohort)


def sample_points(area: Area) -> list[Point]:
    pts = []
    for e in area.edges:
        L = e.line.length
        for d in np.arange(0.0, L + 1e-9, SWEEP_SPACING_M):
            pts.append(e.line.interpolate(d))
        if L % SWEEP_SPACING_M:
            pts.append(Point(e.line.coords[-1]))
    return pts


def _worst(area: Area, nb: Neighbourhood, pts, pt_tree, cohort: dict | None = None):
    """Worst single blockage for `nb` over all sweep centres near it: (result, centre)."""
    lines = [area.edges[i].line for i in nb.edge_idx]
    reach_geom = shapely.union_all(lines + [Point(area.node_xy[g]) for g in nb.gateways])
    worst = dict(cut=0, cut_osm=0, cut_ms=0, inside=0, cut_edges=set(), cut_ids={s: set() for s in SOURCES})
    worst_pt = None
    for j in pt_tree.query(reach_geom, predicate="dwithin", distance=BLOCK_RADIUS_M):
        r = evaluate_block(area, nb, pts[int(j)], cohort)
        if r["cut"] > worst["cut"]:
            worst, worst_pt = r, pts[int(j)]
    return worst, worst_pt


def _assessed(area: Area, nb: Neighbourhood) -> bool:
    # boundary rule applies to the roads themselves, not the 40 m display buffer
    return area.assessable.contains(shapely.union_all([area.edges[i].line for i in nb.edge_idx]))


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
        assessed = _assessed(area, nb)
        worst, worst_pt = _worst(area, nb, pts, pt_tree) if assessed else (
            dict(cut=0, cut_osm=0, cut_ms=0, inside=0, cut_edges=set()), None)
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
    """Nearest existing road node (junction or road end) within SNAP_MAX_M; roads are not split mid-segment."""
    p = Point(_TO_M(*lonlat))
    i, d = area.node_tree.query_nearest(p, return_distance=True)
    return int(area.node_ids[i[0]]) if len(i) and d[0] <= SNAP_MAX_M else None


def with_new_road(area: Area, a: int, b: int) -> tuple[Area, LineString]:
    """A temporary copy of the area with one proposed local road from node a to node b (cache untouched).
    Existing edge indices are preserved; the new road is appended last."""
    line = LineString([area.node_xy[a], area.node_xy[b]])
    edges = area.edges + [Edge(a, b, line, exit=False, qualifying=False)]
    copy = Area(area.name, edges, area.node_xy, area.exit_nodes, shapely.STRtree([e.line for e in edges]),
                area.node_ids, area.node_tree, area.assessable, area.stats, area.bld)
    return copy, line


def mitigate_nodes(area: Area, a: int, b: int, choke: Point | None = None) -> dict:
    """Mitigation test between two existing road nodes. Compares the ORIGINAL neighbourhood's building cohort under
    its original worst blockage, before vs. after adding the proposed road.
    choke: override the blockage location (regression tests only; normally the neighbourhood's worst blockage)."""
    if a == b:
        return dict(ok=False, message="Both ends joined the same road point; draw a longer road.")
    touched = {a, b}
    # only neighbourhoods whose LOCAL roads the proposed road starts from are being mitigated; neighbourhoods that
    # merely share a major-road junction with an endpoint are unaffected by it
    own = {nb.nid for nb in neighbourhoods(area) if touched & nb.local_nodes}
    before = [r for r in scan(area, only_nodes=touched, min_homes=1)
              if r["nid"] in own and r["status"] != "not_assessed" and r["worst_cut"] > 0]
    if not before:
        return dict(ok=False, message="This road doesn't start from the streets of an assessed neighbourhood "
                    "with a choke point.")
    worst = max(before, key=lambda r: r["worst_cut"])
    if choke is not None:
        worst = dict(worst, choke=choke)
    nb0 = next(nb for nb in neighbourhoods(area) if nb.nid == worst["nid"])
    cohort = nb0.cohort(area)
    r0 = evaluate_block(area, nb0, worst["choke"], cohort)
    worst["worst_cut"] = r0["cut"]

    new_area, line = with_new_road(area, a, b)
    orig_edges = set(nb0.edge_idx)
    # the resulting neighbourhood is the one containing the original neighbourhood's roads - never the largest
    nb1 = next(nb for nb in neighbourhoods(new_area) if orig_edges <= set(nb.edge_idx))
    road = dict(type="Feature", properties=dict(length_m=round(line.length)), geometry=mapping(transform(_TO_LL, line)))
    base = dict(ok=True, road=road, length_m=round(line.length),
                before=dict(nid=worst["nid"], homes=worst["homes"], worst_cut=worst["worst_cut"], status=worst["status"]))
    if not _assessed(new_area, nb1):
        return dict(base, unavailable=True, message="With this road the neighbourhood reaches the edge of our road "
                    "data, so the result can't be assessed fairly.")

    r1 = evaluate_block(new_area, nb1, worst["choke"], cohort)
    regained_src = {s: len(r0["cut_ids"][s] - r1["cut_ids"][s]) for s in SOURCES}
    pts = sample_points(new_area)
    new_worst, new_pt = _worst(new_area, nb1, pts, shapely.STRtree(pts), cohort)
    after = dict(worst_cut=new_worst["cut"], gateways=len(nb1.gateways),
                 worst_cut_src={"osm": new_worst["cut_osm"], "ms": new_worst["cut_ms"]},
                 status="red" if new_worst["cut"] >= RED_MIN_CUT else "amber" if new_worst["cut"] > 0 else "green")
    # values describe the ORIGINAL cohort evaluated on the augmented network (no placeholder zeros)
    after_geo = results_geojson([dict(nid=nb1.nid, status=after["status"], homes=worst["homes"],
                                      homes_osm=len(cohort["osm"]), homes_ms=len(cohort["ms"]),
                                      gateways=after["gateways"], worst_cut=new_worst["cut"],
                                      worst_cut_osm=new_worst["cut_osm"], worst_cut_ms=new_worst["cut_ms"],
                                      worst_inside=new_worst["inside"], rank=None, choke=new_pt,
                                      geometry=shapely.union_all([new_area.edges[i].line.buffer(40) for i in nb1.edge_idx]),
                                      streets=shapely.MultiLineString([new_area.edges[i].line for i in nb1.edge_idx]),
                                      cut_lines=shapely.union_all([new_area.edges[i].line for i in new_worst["cut_edges"]])
                                      if new_worst["cut_edges"] else None)])
    return dict(base, unavailable=False,
                before_cut_src={s: len(r0["cut_ids"][s]) for s in SOURCES},
                same_block_cut_src={s: len(r1["cut_ids"][s]) for s in SOURCES},
                regained_src=regained_src,
                regained=max(regained_src.values()),          # frozen higher-of-two reporting rule
                same_block_cut=r1["cut"], after=after, after_geo=after_geo)


def mitigate(area: Area, a_ll, b_ll) -> dict:
    """Mitigation test from two clicks: each end joins the nearest existing road node (within SNAP_MAX_M)."""
    a, b = _snap(area, a_ll), _snap(area, b_ll)
    if a is None or b is None:
        return dict(ok=False, message=f"Each end must be within {SNAP_MAX_M:.0f} m of an existing road junction or road end.")
    return mitigate_nodes(area, a, b)


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
