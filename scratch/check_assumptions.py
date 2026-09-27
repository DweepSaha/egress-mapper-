"""DIAGNOSTIC ONLY - read-only check of method assumptions against the OSM data on disk. Changes nothing.

For each study area: access restrictions and barriers on qualifying roads (and whether any is used as a way out by a
scanned neighbourhood), surface/seasonal quality, one-way coverage, and vulnerable occupancies in RED neighbourhoods.
Run: python scratch/check_assumptions.py   (writes scratch/assumptions_report.md too)
"""
from __future__ import annotations

import ast
import sys
from collections import Counter, defaultdict
from pathlib import Path

import osmium
import osmnx as ox
import shapely
from pyproj import Transformer
from shapely.geometry import Point

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from egress import config, engine  # noqa: E402

AREAS = [("fredericton", "Fredericton, NB"), ("tantallon", "Upper Tantallon, NS"), ("pointe_sapin", "Pointe-Sapin, NB")]
TO_M = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True).transform

# ---- exact tag queries (cited in the report)
ACCESS_BAD = {"private", "no", "permit", "customers", "destination"}
MV_BAD = {"no", "private"}
BARRIERS = {"gate", "bollard", "lift_gate", "block"}
SURF_BAD = {"unpaved", "gravel", "dirt", "ground"}
SURF_OTHER_UNPAVED = {"compacted", "fine_gravel", "earth", "mud", "sand", "grass", "pebblestone", "rock"}
SMOOTH_BAD = {"bad", "very_bad", "horrible", "very_horrible", "impassable"}
TRACK_BAD = {"grade3", "grade4", "grade5"}
ONEWAY_YES = {"yes", "1", "true", "-1", "reversible"}
AMENITY = {"school", "kindergarten", "hospital", "clinic", "social_facility", "nursing_home"}
QUERIES = f"""
- Access restriction (way tag): access ∈ {sorted(ACCESS_BAD)}, or motor_vehicle ∈ {sorted(MV_BAD)}
- Barrier (node tag, node is part of the way and lies on the engine road segment, ≤ 2 m): barrier ∈ {sorted(BARRIERS)}
- Surface: surface ∈ {sorted(SURF_BAD)} (reported separately: other unpaved values {sorted(SURF_OTHER_UNPAVED)})
- smoothness ∈ {sorted(SMOOTH_BAD)}; tracktype ∈ {sorted(TRACK_BAD)}; seasonal=yes; highway=track
- One-way: oneway ∈ {sorted(ONEWAY_YES)} on any OSM way making up the segment
- Vulnerable occupancy: amenity ∈ {sorted(AMENITY)} (nodes and polygons), attached to the nearest road segment
  within {engine.MAX_ASSIGN_M:.0f} m (the same rule used for mapped buildings)
- "Qualifying road segment": an engine road segment whose highway class is in the qualifying classes
  {sorted(engine.EXIT_CLASSES)} (before the spur rule). "Way out": a qualifying segment the engine keeps as a way out
  after the spur rule (Edge.exit). "Used as a way out by a scanned neighbourhood": a way-out segment that meets one of
  the connection points (gateways) of a neighbourhood in the scan results (30+ mapped buildings).
""".strip()


class OSMReader(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.ways = {}          # highway way id -> (tags, node ids)
        self.barriers = {}      # node id -> (barrier value, lon, lat)
        self.amen = []          # (kind, name, lon, lat, osm ref)

    def node(self, n):
        t = n.tags
        b = t.get("barrier")
        if b:
            self.barriers[n.id] = (b, n.location.lon, n.location.lat)
        a = t.get("amenity")
        if a in AMENITY:
            self.amen.append((a + (f" ({t.get('social_facility')})" if t.get("social_facility") else ""), t.get("name", "(unnamed)"),
                              n.location.lon, n.location.lat, f"node/{n.id}"))

    def way(self, w):
        if "highway" in w.tags:
            self.ways[w.id] = ({k: v for k, v in w.tags}, [nd.ref for nd in w.nodes])

    def area(self, a):
        t = a.tags
        am = t.get("amenity")
        if am not in AMENITY:
            return
        try:
            pts = [(n.lon, n.lat) for ring in a.outer_rings() for n in ring]
        except Exception:
            return
        if not pts:
            return
        lon, lat = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        ref = f"{'way' if a.from_way() else 'relation'}/{a.orig_id()}"
        self.amen.append((am + (f" ({t.get('social_facility')})" if t.get("social_facility") else ""), t.get("name", "(unnamed)"),
                          lon, lat, ref))


def osmids(d) -> list[int]:
    v = d.get("osmid")
    if isinstance(v, (list, tuple)):
        return [int(x) for x in v]
    if isinstance(v, str) and v.startswith("["):
        return [int(x) for x in ast.literal_eval(v)]
    return [int(v)]


def analyse(name: str, label: str, out: list):
    P = out.append
    area = engine.load_area(name)
    # align engine edges with the graph edges they were built from (same order as engine.load_area)
    G = ox.project_graph(ox.load_graphml(config.roads_graphml(name)), to_crs=config.ANALYSIS_CRS)
    U = ox.convert.to_undirected(G)
    gedges = list(U.edges(data=True))
    assert len(gedges) == len(area.edges) and all({u, v} == {e.u, e.v} for (u, v, _), e in zip(gedges, area.edges))
    ids_of = [osmids(d) for _, _, d in gedges]

    rd = OSMReader()
    rd.apply_file(str(config.DATA / "osm" / "extracts" / f"{name}.osm.pbf"), locations=True)

    results = engine.scan(area)
    nbs = {nb.nid: nb for nb in engine.neighbourhoods(area)}
    res_by_nid = {r["nid"]: r for r in results}
    gate_nbs = defaultdict(list)                 # gateway node -> scanned neighbourhoods using it
    for r in results:
        for g in nbs[r["nid"]].gateways:
            gate_nbs[g].append(r["nid"])

    P(f"\n## {label}\n")
    n_edges = len(area.edges)
    qual = [i for i, e in enumerate(area.edges) if e.qualifying]
    exits = [i for i in qual if area.edges[i].exit]
    missing_ways = sum(1 for ids in ids_of for w in ids if w not in rd.ways)
    P(f"Road segments: {n_edges} (qualifying {len(qual)}, of which kept as ways out {len(exits)}). "
      f"Scanned neighbourhoods: {len(results)}. OSM ways not found in the extract: {missing_ways}.")

    # ---------- 1. access restrictions and barriers
    def restriction(i):
        e, hits = area.edges[i], []
        for w in ids_of[i]:
            tags, refs = rd.ways.get(w, ({}, []))
            if tags.get("access") in ACCESS_BAD:
                hits.append(f"access={tags['access']} (way/{w})")
            if tags.get("motor_vehicle") in MV_BAD:
                hits.append(f"motor_vehicle={tags['motor_vehicle']} (way/{w})")
            for nref in refs:
                if nref in rd.barriers and rd.barriers[nref][0] in BARRIERS:
                    b, lon, lat = rd.barriers[nref]
                    if e.line.distance(Point(TO_M(lon, lat))) <= 2.0:
                        hits.append(f"barrier={b} (node/{nref})")
        return sorted(set(hits))

    restricted = {i: h for i in qual if (h := restriction(i))}
    P("### 1. Access restrictions / barriers on qualifying roads")
    P(f"- Qualifying segments with any restriction or barrier: **{len(restricted)}** of {len(qual)}")
    kinds = Counter(h.split(" (")[0] for hs in restricted.values() for h in hs)
    if kinds:
        P(f"- Tag counts: {dict(kinds)}")
    used = []
    for i, hs in restricted.items():
        e = area.edges[i]
        users = sorted({nid for g in (e.u, e.v) for nid in gate_nbs.get(g, [])}) if e.exit else []
        tags0 = rd.ways.get(ids_of[i][0], ({}, []))[0]
        line = (f"  - {tags0.get('highway')} '{tags0.get('name', '(unnamed)')}' ({e.line.length:.0f} m): {', '.join(hs)}; "
                f"way out: {'yes' if e.exit else 'no (spur rule)'}")
        if users:
            line += "; meets the connection point of scanned neighbourhood(s) " + ", ".join(
                f"nid {n} ({res_by_nid[n]['status']}, {res_by_nid[n]['homes']} mapped buildings)" for n in users)
            used.append((i, users))
        P(line)
    P(f"- **Restricted qualifying segments used as a way out at a scanned neighbourhood's connection point: {len(used)}**")
    for nid in sorted({n for _, us in used for n in us}):
        nb, r = nbs[nid], res_by_nid[nid]
        bad_g = {g for i, us in used if nid in us for g in (area.edges[i].u, area.edges[i].v) if g in nb.gateways}
        c = shapely.union_all([area.edges[i].line for i in nb.edge_idx]).centroid
        lon, lat = Transformer.from_crs(config.ANALYSIS_CRS, "EPSG:4326", always_xy=True).transform(c.x, c.y)
        P(f"  - nid {nid} ({r['status']}, {r['homes']} mapped buildings, worst sampled blockage {r['worst_cut']}): "
          f"{len(bad_g)} of its {len(nb.gateways)} connection point(s) sit on a restricted road; centre ≈ {lat:.5f}, {lon:.5f}")
    in_exit = [i for i in restricted if area.edges[i].exit]
    P(f"- Restricted segments kept as ways out anywhere in the network (not necessarily at a connection point): {len(in_exit)}")
    # restrictions on local roads INSIDE scanned neighbourhoods (treated as passable internal roads)
    local_hits = []
    for nid in res_by_nid:
        for i in nbs[nid].edge_idx:
            if not area.edges[i].qualifying and (h := restriction(i)):
                local_hits.append((nid, h))
    P(f"- (Context) Local roads inside scanned neighbourhoods with a restriction/barrier: {len(local_hits)}"
      + (" - " + "; ".join(f"nid {n}: {', '.join(h)}" for n, h in local_hits[:8]) + (" …" if len(local_hits) > 8 else "") if local_hits else ""))
    notag = sum(1 for i in qual if all("access" not in rd.ways.get(w, ({}, []))[0] for w in ids_of[i]))
    P(f"- Not tagged: {notag} of {len(qual)} qualifying segments have no access tag at all (absence ≠ confirmed public).")

    # ---------- 2. surface and seasonal quality
    P("\n### 2. Surface and seasonal quality (qualifying roads only)")
    cnt, flagged = Counter(), {}
    for i in qual:
        why = []
        for w in ids_of[i]:
            t = rd.ways.get(w, ({}, []))[0]
            if t.get("surface") in SURF_BAD: why.append(f"surface={t['surface']}")
            if t.get("surface") in SURF_OTHER_UNPAVED: why.append(f"surface={t['surface']} (other unpaved)")
            if t.get("smoothness") in SMOOTH_BAD: why.append(f"smoothness={t['smoothness']}")
            if t.get("tracktype") in TRACK_BAD: why.append(f"tracktype={t['tracktype']}")
            if t.get("seasonal") == "yes": why.append("seasonal=yes")
            if t.get("highway") == "track": why.append("highway=track")
        why = sorted(set(why))
        for wy in why:
            cnt[wy.split(" (")[0].split("=")[0] + ("=" + wy.split("=")[1].split(" ")[0] if "=" in wy else "")] += 1
        if why:
            flagged[i] = why
    P(f"- Qualifying segments with any flag: **{len(flagged)}** of {len(qual)}; tag counts: {dict(cnt) if cnt else 'none'}")
    used2 = []
    for i, why in flagged.items():
        e = area.edges[i]
        users = sorted({nid for g in (e.u, e.v) for nid in gate_nbs.get(g, [])}) if e.exit else []
        if users:
            used2.append((i, users, why))
    for i, users, why in used2:
        t = rd.ways.get(ids_of[i][0], ({}, []))[0]
        P(f"  - used as a way out: {t.get('highway')} '{t.get('name', '(unnamed)')}' ({area.edges[i].line.length:.0f} m) {why}; "
          + ", ".join(f"nid {n} ({res_by_nid[n]['status']})" for n in users))
    P(f"- **Flagged qualifying segments used as a way out at a scanned neighbourhood's connection point: {len(used2)}**")
    nosurf = sum(1 for i in qual if all("surface" not in rd.ways.get(w, ({}, []))[0] for w in ids_of[i]))
    P(f"- Not tagged: {nosurf} of {len(qual)} qualifying segments have no surface tag; smoothness/tracktype/seasonal are "
      f"rarely tagged at all. highway=track is excluded upstream by the OSMnx 'drive' filter, so it is 0 by construction.")

    # ---------- 3. one-way coverage
    ow = [i for i in range(n_edges) if any(rd.ways.get(w, ({}, []))[0].get("oneway") in ONEWAY_YES for w in ids_of[i])]
    L = sum(e.line.length for e in area.edges)
    Low = sum(area.edges[i].line.length for i in ow)
    owq = [i for i in ow if area.edges[i].qualifying]
    P("\n### 3. One-way coverage (all road segments)")
    P(f"- oneway on {len(ow)} of {n_edges} segments ({100 * len(ow) / n_edges:.1f}%), {Low / 1000:.1f} of {L / 1000:.1f} km "
      f"({100 * Low / L:.1f}% of length); on qualifying roads: {len(owq)} of {len(qual)} segments. "
      f"Mostly divided carriageways / ramps expected; the analysis treats every road as two-way.")

    # ---------- 4. vulnerable occupancies in RED neighbourhoods
    P("\n### 4. Vulnerable occupancies in RED neighbourhoods (display-only finding)")
    red_hits, all_att = [], 0
    for kind, nm, lon, lat, ref in rd.amen:
        p = Point(TO_M(lon, lat))
        j, d = area.edge_tree.query_nearest(p, return_distance=True)
        if not len(j) or d[0] > engine.MAX_ASSIGN_M:
            continue
        all_att += 1
        i = int(j[0])
        nid = next((n for n, nb in nbs.items() if i in nb.edge_idx and n in res_by_nid), None)
        if nid is None or res_by_nid[nid]["status"] != "red":
            continue
        r = res_by_nid[nid]
        # read-only: the engine's own answer at the scan's worst sampled centre (is this road among the cut-off roads?)
        stranded = r["choke"] is not None and i in engine.evaluate_block(area, nbs[nid], r["choke"])["cut_edges"]
        red_hits.append((nid, kind, nm, ref, r, stranded, d[0]))
    P(f"- Amenity features found: {len(rd.amen)}; attached to a road within {engine.MAX_ASSIGN_M:.0f} m: {all_att}; "
      f"in RED neighbourhoods: **{len(red_hits)}**")
    for nid, kind, nm, ref, r, stranded, d in sorted(red_hits):
        P(f"  - nid {nid} (RED, {r['homes']} mapped buildings, worst sampled blockage cuts off {r['worst_cut']}): "
          f"{kind} '{nm}' [{ref}], {d:.0f} m from its road; "
          f"{'on a street stranded by the worst sampled blockage' if stranded else 'not on a stranded street under the worst sampled blockage'}")
    return dict(restricted=len(restricted), used=len(used), flagged=len(flagged), used2=len(used2), red_amen=len(red_hits))


def main():
    out = ["# Method-assumption check (diagnostic only)", "",
           "Read-only analysis of the OSM data on disk. Nothing in the app, scan or mitigation logic was changed.", "",
           "**Upstream filter (important context):** the road graphs were built from ways matching OSMnx 2.1.1's "
           "`network_type=\"drive\"` filter, which already EXCLUDES `access=private`, `motor_vehicle=no`, `motorcar=no`, "
           "`highway=track|service|...` and `service=emergency_access|driveway|parking|private`. Such roads are not in the "
           "network at all, so they cannot be counted as ways out. The checks below look for restrictions that pass that filter.",
           "", "Exact queries:", QUERIES]
    summary = {}
    for name, label in AREAS:
        try:
            summary[name] = analyse(name, label, out)
        except Exception as ex:          # timebox: report partial results rather than fail
            out.append(f"\n## {label}\n\nNOT COMPLETED: {type(ex).__name__}: {ex}")
    out.append("\n## Summary")
    for name, label in AREAS:
        s = summary.get(name)
        if s:
            out.append(f"- {label}: restricted qualifying segments {s['restricted']} (used as a way out at a scanned "
                       f"neighbourhood's connection point: {s['used']}); surface/seasonal-flagged {s['flagged']} (used: "
                       f"{s['used2']}); vulnerable occupancies in RED neighbourhoods {s['red_amen']}")
    text = "\n".join(out)
    print(text)
    (REPO / "scratch" / "assumptions_report.md").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
