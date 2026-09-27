"""Negative control numbers (read-only, frozen engine): the Fredericton neighbourhood containing downtown, and suburban-
fringe neighbourhoods, named by nearest OSM place point and the road the worst sampled blockage sits on."""
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import geopandas as gpd  # noqa: E402
import osmnx as ox  # noqa: E402
from shapely.geometry import Point  # noqa: E402

from egress import config, engine  # noqa: E402

POINTS = {   # lon, lat
    "downtown (Queen St at Officers' Square)": (-66.6425, 45.9618),
    "downtown (King St / York St)": (-66.6445, 45.9594),
    "suburban fringe: Douglas": (-66.7425, 45.9815),
    "suburban fringe: New Maryland": (-66.6860, 45.8920),
    "suburban fringe: Hanwell": (-66.7400, 45.9080),
}


def main():
    a = engine.load_area("fredericton")
    res = engine.scan(a)
    places = gpd.read_file(config.DATA / "osm" / "new-brunswick.gpkg", layer="gis_osm_places_free")
    G = ox.load_graphml(config.roads_graphml("fredericton"))
    names = {}
    for u, v, d in G.edges(data=True):
        names.setdefault(frozenset((u, v)), d.get("name"))
    for label, ll in POINTS.items():
        p = Point(engine._TO_M(*ll))
        hit = [r for r in res if r["geometry"].contains(p)]
        if not hit:
            near = min(res, key=lambda r: r["geometry"].distance(p))
            hit = [near]
            note = f" (nearest, {near['geometry'].distance(p):.0f} m away)"
        else:
            note = ""
        r = hit[0]
        road = "-"
        if r["choke"] is not None:
            i = int(a.edge_tree.query_nearest(r["choke"])[0])
            e = a.edges[i]
            road = names.get(frozenset((e.u, e.v))) or "-"
        pl = places.to_crs(config.ANALYSIS_CRS)
        c = r["geometry"].centroid
        j = pl.geometry.distance(c).idxmin()
        print(f"{label}: nid {r['nid']}{note} | status {r['status']} | cohort {r['homes_osm']}/{r['homes_ms']} | worst sampled blockage "
              f"{r['worst_cut_osm']}/{r['worst_cut_ms']} (headline {r['worst_cut']}) | {r['gateways']} connections | "
              f"place {places.loc[j, 'name']} | blockage on {road}")


if __name__ == "__main__":
    main()
