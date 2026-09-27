"""DATA PREP (not project code): cut study-area extracts from Geofabrik PBFs, verify OSMnx loads them,
clip building footprints. Each stage runs in its own process so memory is freed between them.

    python scratch/extract_areas.py [area ...]         # all (or the named) areas, all stages
    python scratch/extract_areas.py <stage> <area>     # one stage (extract | graph | bridge | buildings)
"""
import ctypes
import json
import math
import re
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OSM, EXTRACTS = ROOT / "data/osm", ROOT / "data/osm/extracts"
ROADS, BUILDINGS = ROOT / "data/roads", ROOT / "data/buildings"
XML_LIMIT_MB = 200

# base extents (lon/lat) derived from OSM admin boundaries + Route 117 geometry; buffer in km
AREAS = {
    "pointe_sapin": dict(province="new-brunswick", base=(-65.0619, 46.7622, -64.8026, 47.0599), buffer_km=2,
                         desc="Pointe-Sapin boundary + Route 117 (NB 117) within Kent County, + 2 km"),
    "tantallon": dict(province="nova-scotia", base=(-63.8957, 44.6638, -63.7099, 44.8005), buffer_km=2,
                      desc="Upper Tantallon + Hammonds Plains boundaries (incl. Westwood Hills), + 2 km"),
    "fredericton": dict(province="new-brunswick", base=(-66.7871, 45.8470, -66.5120, 46.0505), buffer_km=10,
                        desc="Fredericton city boundary + 10 km"),
}

# OSMnx 2.1.1 network_type="drive" filter (osmnx/_overpass.py), as unanchored regexes like Overpass
DRIVE_EXCLUDE = {
    "area": "yes", "access": "private", "motor_vehicle": "no", "motorcar": "no",
    "highway": "abandoned|bridleway|bus_guideway|construction|corridor|cycleway|elevator|escalator|"
               "footway|no|path|pedestrian|planned|platform|proposed|raceway|razed|rest_area|service|"
               "services|steps|track",
    "service": "alley|driveway|emergency_access|parking|parking_aisle|private",
}


def bbox(area):
    x0, y0, x1, y1 = AREAS[area]["base"]
    km = AREAS[area]["buffer_km"]
    dlat = km / 111.32
    dlon = km / (111.32 * math.cos(math.radians((y0 + y1) / 2)))
    return tuple(round(v, 5) for v in (x0 - dlon, y0 - dlat, x1 + dlon, y1 + dlat))


def is_drive(tags):
    if "highway" not in tags:
        return False
    return not any(k in tags and re.search(p, tags[k]) for k, p in DRIVE_EXCLUDE.items())


# ---------- memory helpers (Windows) ----------
class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                *[(n, ctypes.c_size_t) for n in ("a", "b", "c", "d", "PagefileUsage", "PeakPagefileUsage")]]


class MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                *[(n, ctypes.c_ulonglong) for n in ("total", "avail", "tpf", "apf", "tv", "av", "aev")]]


def peak_mb():
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    c = PMC(cb=ctypes.sizeof(PMC))
    if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        raise ctypes.WinError()
    return c.PeakWorkingSetSize / 1e6


def free_ram_mb():
    m = MEMSTAT(dwLength=ctypes.sizeof(MEMSTAT))
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.avail / 1e6


def mb(p):
    return p.stat().st_size / 1e6


def record(area, key, value):
    """Accumulate results in scratch/extract_results.json for the summary and SOURCES.md."""
    f = ROOT / "scratch/extract_results.json"
    d = json.loads(f.read_text()) if f.exists() else {}
    d.setdefault(area, {})[key] = value
    f.write_text(json.dumps(d, indent=2))


# ---------- stage 1: complete_ways cut + drivable XML ----------
def stage_extract(area):
    import osmium
    src = OSM / f"{AREAS[area]['province']}-latest.osm.pbf"
    x0, y0, x1, y1 = bbox(area)
    EXTRACTS.mkdir(parents=True, exist_ok=True)
    full_pbf, drive_xml = EXTRACTS / f"{area}.osm.pbf", EXTRACTS / f"{area}-drive.osm"
    t0 = time.time()

    # complete_ways: nodes in bbox -> every way using any of them -> ALL nodes of those ways.
    # Plain Python sets, NOT osmium.IdTracker: IdTracker's dense bitsets allocate ~2.4 MB per
    # scattered id block (measured: 500 spread node ids = 1.2 GB), which hit 3 GB on Tantallon.
    bbox_nodes = {n.id for n in osmium.FileProcessor(str(src), osmium.osm.NODE)
                  if n.location.valid() and x0 <= n.lon <= x1 and y0 <= n.lat <= y1}
    in_bbox = len(bbox_nodes)
    keep_ways, keep_nodes = set(), set(bbox_nodes)
    for wy in osmium.FileProcessor(str(src), osmium.osm.WAY):
        refs = [nd.ref for nd in wy.nodes]
        if not bbox_nodes.isdisjoint(refs):
            keep_ways.add(wy.id)
            keep_nodes.update(refs)  # the whole way, including nodes outside the bbox
    del bbox_nodes
    counts = {"node": 0, "way": 0, "relation": 0}
    with osmium.SimpleWriter(str(full_pbf), overwrite=True) as w:
        for o in osmium.FileProcessor(str(src)):
            if o.is_node():
                keep = o.id in keep_nodes
            elif o.is_way():
                keep = o.id in keep_ways
            else:  # relations referencing kept objects (members not completed, as in osmium extract)
                keep = any((m.type == "n" and m.ref in keep_nodes) or (m.type == "w" and m.ref in keep_ways)
                           for m in o.members)
            if keep:
                counts[{"n": "node", "w": "way", "r": "relation"}[o.type_str()]] += 1
                w.add(o)
    outside = counts["node"] - in_bbox
    del keep_nodes, keep_ways
    print(f"[{area}] full cut {full_pbf.name}: {counts['node']:,} nodes ({in_bbox:,} in bbox + "
          f"{outside:,} outside, kept to complete boundary-crossing ways), {counts['way']:,} ways, "
          f"{counts['relation']:,} relations, {mb(full_pbf):.1f} MB")

    # drivable subset of the cut, with all nodes of each selected way
    drive_ways, drive_nodes = set(), set()
    n_refs = n_tags = 0
    for wy in osmium.FileProcessor(str(full_pbf), osmium.osm.WAY):
        tags = dict(wy.tags)
        if is_drive(tags):
            drive_ways.add(wy.id)
            drive_nodes.update(nd.ref for nd in wy.nodes)
            n_refs += len(wy.nodes)
            n_tags += len(tags)
    n_nodes, n_ways = len(drive_nodes), len(drive_ways)
    est = (n_nodes * 190 + n_ways * 150 + n_refs * 25 + n_tags * 45) / 1e6
    print(f"[{area}] drivable subset: {n_ways:,} ways, {n_nodes:,} nodes; estimated XML {est:.0f} MB")
    if est > XML_LIMIT_MB:
        print(f"[{area}] STOP: estimated XML exceeds {XML_LIMIT_MB} MB - not writing it")
        sys.exit(2)
    with osmium.SimpleWriter(str(drive_xml), overwrite=True) as w:
        for o in osmium.FileProcessor(str(full_pbf), osmium.osm.NODE | osmium.osm.WAY):
            if (o.is_node() and o.id in drive_nodes) or (o.is_way() and o.id in drive_ways):
                w.add(o)
    print(f"[{area}] wrote {drive_xml.name}: {mb(drive_xml):.1f} MB  "
          f"({time.time() - t0:.0f}s, peak {peak_mb():.0f} MB)")
    record(area, "extract", dict(bbox=[x0, y0, x1, y1], desc=AREAS[area]["desc"], source=src.name,
                                 full_pbf_mb=round(mb(full_pbf), 2), full_counts=counts,
                                 nodes_in_bbox=in_bbox, nodes_outside_completed=outside,
                                 drive_xml_mb=round(mb(drive_xml), 2), drive_ways=n_ways,
                                 drive_nodes=n_nodes))


# ---------- stage 2: OSMnx graph from XML, save/reload GraphML ----------
def stage_graph(area):
    import networkx as nx
    import osmnx as ox
    xml = EXTRACTS / f"{area}-drive.osm"
    t0 = time.time()
    G = ox.graph_from_xml(xml, retain_all=True, simplify=True)
    load_s = time.time() - t0
    pk = peak_mb()
    n, e = G.number_of_nodes(), G.number_of_edges()
    xs = [d["x"] for _, d in G.nodes(data=True)]
    ys = [d["y"] for _, d in G.nodes(data=True)]
    bb = [round(min(xs), 5), round(min(ys), 5), round(max(xs), 5), round(max(ys), 5)]
    with_geom = sum(1 for *_, d in G.edges(data=True) if "geometry" in d)
    print(f"[{area}] graph: {n:,} nodes, {e:,} edges, bbox {bb}, loaded in {load_s:.1f}s, "
          f"peak {pk:.0f} MB, CRS {G.graph['crs']}")
    print(f"[{area}] directed={G.is_directed()} ({type(G).__name__}); edges with geometry attr: "
          f"{with_geom:,}/{e:,} (the rest are straight 2-node segments; OSMnx stores no geometry for those)")

    wcc = sorted((len(c) for c in nx.weakly_connected_components(G)), reverse=True)
    print(f"[{area}] weakly connected components: {len(wcc)}; largest {wcc[0]:,} nodes "
          f"({wcc[0] / n:.1%}); next: {wcc[1:8]}")

    ROADS.mkdir(parents=True, exist_ok=True)
    gml = ROADS / f"{area}.graphml"
    ox.save_graphml(G, gml)
    H = ox.load_graphml(gml)
    ok = (H.number_of_nodes(), H.number_of_edges()) == (n, e) and set(H.nodes) == set(G.nodes)
    print(f"[{'PASS' if ok else 'FAIL'}] [{area}] GraphML {gml.name} ({mb(gml):.1f} MB) reloaded: "
          f"{H.number_of_nodes():,} nodes, {H.number_of_edges():,} edges")
    record(area, "graph", dict(nodes=n, edges=e, bbox=bb, load_s=round(load_s, 1), peak_mb=round(pk),
                               directed=G.is_directed(), edges_with_geometry=with_geom,
                               components=len(wcc), largest_component=wcc[0], component_sizes_top=wcc[:8],
                               graphml_mb=round(mb(gml), 2), reload_ok=ok))
    return ok


# ---------- stage 3: Westmorland Street Bridge must not share nodes with what passes under it ----------
def stage_bridge(area):
    import osmium
    import osmnx as ox
    from shapely.geometry import LineString, box
    full_pbf = EXTRACTS / f"{area}.osm.pbf"
    near = box(-66.66, 45.95, -66.62, 45.98)  # downtown Fredericton around the bridge
    ways = []  # every highway way in the full cut near the bridge, with node ids + geometry
    # nodes must be read too, so the location cache can give way nodes their coordinates
    for wy in osmium.FileProcessor(str(full_pbf), osmium.osm.NODE | osmium.osm.WAY).with_locations():
        if not wy.is_way() or "highway" not in wy.tags:
            continue
        coords = [(nd.lon, nd.lat) for nd in wy.nodes]
        if len(coords) < 2 or not LineString(coords).intersects(near):
            continue
        ways.append(dict(id=wy.id, name=wy.tags.get("name", ""), hw=wy.tags["highway"],
                         bridge=wy.tags.get("bridge", ""), layer=wy.tags.get("layer", "0"),
                         nodes=[nd.ref for nd in wy.nodes], geom=LineString(coords)))
    bridge = [w for w in ways if "Westmorland" in w["name"] and w["bridge"] not in ("", "no")]
    if not bridge:
        print(f"[FAIL] [{area}] no way named Westmorland with a bridge tag found")
        return False
    b_nodes = set().union(*(w["nodes"] for w in bridge))
    print(f"[{area}] Westmorland St Bridge: {len(bridge)} way(s) {[w['id'] for w in bridge]}, "
          f"bridge={bridge[0]['bridge']}, layer={bridge[0]['layer']}, {len(b_nodes)} nodes")

    b_ids = {w["id"] for w in bridge}
    crossing = [w for w in ways if w["id"] not in b_ids and any(w["geom"].crosses(b["geom"]) for b in bridge)]
    ok = bool(crossing)
    for w in crossing:
        shared = b_nodes & set(w["nodes"])
        ok &= not shared
        print(f"  crosses under/over: way {w['id']} {w['name'] or '(unnamed)'} [{w['hw']}, layer={w['layer']}]"
              f" -> shared nodes with bridge: {sorted(shared) or 'none'}")
    if not crossing:
        print("  nothing crosses the bridge geometrically - check inconclusive")

    # same check in the OSMnx graph (node ids are OSM node ids)
    G = ox.load_graphml(ROADS / f"{area}.graphml")
    def osmids(d):  # an edge's osmid is an int, or a list after simplification merged ways
        v = d.get("osmid")
        return set(v) if isinstance(v, list) else {v}
    g_bridge_nodes = {n for u, v, d in G.edges(data=True) if osmids(d) & b_ids for n in (u, v)}
    drive_crossing = [w for w in crossing if w["hw"] in {"primary", "secondary", "tertiary", "residential",
                                                         "trunk", "unclassified", "motorway"}]
    for w in drive_crossing:
        in_graph = {n for n in w["nodes"] if n in G}
        print(f"  graph: {w['name']} nodes in graph shared with bridge edges: "
              f"{sorted(in_graph & g_bridge_nodes) or 'none'}")
        ok &= not (in_graph & g_bridge_nodes)
    print(f"[{'PASS' if ok else 'FAIL'}] [{area}] bridge shares no nodes with anything crossing it")
    record(area, "bridge", dict(bridge_ways=sorted(b_ids), crossing=[(w["id"], w["name"], w["hw"]) for w in crossing],
                                ok=ok))
    return ok


# ---------- stage 4: building footprints ----------
def stage_buildings(area):
    import geopandas as gpd
    src = OSM / f"{AREAS[area]['province']}.gpkg"
    gdf = gpd.read_file(src, layer="gis_osm_buildings_a_free", bbox=bbox(area))
    BUILDINGS.mkdir(parents=True, exist_ok=True)
    out = BUILDINGS / f"{area}.gpkg"
    gdf.to_file(out, layer="buildings", driver="GPKG")
    import pyogrio
    n = pyogrio.read_info(out, layer="buildings")["features"]
    ok = n == len(gdf) and n > 0
    print(f"[{'PASS' if ok else 'FAIL'}] [{area}] buildings: {len(gdf):,} footprints -> {out.name} "
          f"({mb(out):.1f} MB, reread {n:,}), peak {peak_mb():.0f} MB")
    record(area, "buildings", dict(count=len(gdf), gpkg_mb=round(mb(out), 2)))
    return ok


STAGES = {"extract": stage_extract, "graph": stage_graph, "bridge": stage_bridge, "buildings": stage_buildings}

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in STAGES:
        stage, area = sys.argv[1:]
        free = free_ram_mb()
        if free < 1000:
            print(f"[{area}] STOP before {stage}: only {free:.0f} MB RAM free")
            sys.exit(3)
        print(f"--- {stage} {area} (free RAM {free:.0f} MB, bbox {bbox(area)}) ---", flush=True)
        r = STAGES[stage](area)
        sys.exit(1 if r is False else 0)
    for area in sys.argv[1:] or AREAS:  # optional: run only the named areas
        for stage in ["extract", "graph", "buildings"] + (["bridge"] if area == "fredericton" else []):
            rc = subprocess.run([sys.executable, "-u", __file__, stage, area]).returncode
            if rc:
                print(f"stopping: {stage} {area} exited {rc}")
                sys.exit(rc)
