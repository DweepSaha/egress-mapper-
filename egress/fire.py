"""Tantallon fire scenario: road access under a SUPPLIED affected area. This tool does not predict fire spread.

Two inputs, both treated as a given blockage area:
  * hypothetical: a circle at a user-chosen point with a user-chosen radius (NOT a predicted fire extent);
  * historical: the mapped 2023 Upper Tantallon fire perimeter (NRCan CWFIS NBAC, fire starting 2023-05-28).

Access reuses the audited machinery unchanged (flood.access_under_water, which is generic over the blocked area):
roads are impassable only on stretches inside the area; access-loss counts use the scan's eligibility (gateways,
30+ mapped buildings, assessed); "centre inside" covers every mapped building in the area. Bridges get no exemption
(an affected area reaches a bridge like any other road). No wind, weather, spread, traffic or timing modelling.
"""
from __future__ import annotations

import math
from functools import lru_cache
from threading import Lock

import geopandas as gpd
import shapely
from pyproj import Transformer
from shapely.geometry import Point, mapping
from shapely.ops import transform

from . import config, engine, flood

NBAC_PATH = config.DATA / "fire" / "tantallon_2023.gpkg"
NBAC_START = "2023-05-28"
MIN_RADIUS_M, MAX_RADIUS_M = 50.0, 3000.0
# Westwood Hills' two entrances on Hammonds Plains Road (measured; see DATA.md / research notes)
WESTWOOD_ENTRANCES = [(-63.855646, 44.704433), (-63.852344, 44.706056)]
_TO_M = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True).transform


@lru_cache(maxsize=1)
def mapped_perimeter():
    """The mapped 2023 fire perimeter (EPSG:2953) and its attributes."""
    g = gpd.read_file(NBAC_PATH, layer="nbac")
    g = g[g["hs_sdate"].astype(str).str.startswith(NBAC_START)]
    row = g.loc[g["poly_ha"].idxmax()]
    poly = gpd.GeoSeries([row.geometry], crs=g.crs).to_crs(config.ANALYSIS_CRS).iloc[0]
    return poly, dict(source="NRCan CWFIS National Burned Area Composite (NBAC)", start_date=NBAC_START,
                      mapped_ha=round(float(row["poly_ha"]), 1), cause=row.get("firecaus"))


def _result(area: engine.Area, zone, kind: str, extra: dict) -> dict:
    a = flood.access_under_water(area, zone, frozenset())          # no bridge exemption for fire
    to_ll, fc = engine._TO_LL, engine._fc
    counts = {cat: {s: len(ids[s]) for s in engine.SOURCES} for cat, ids in
              (("lose_access", a["cut"]), ("inside", a["inside"]), ("keep_access", a["retain"]))}
    return dict(
        kind=kind, zone_ha=round(zone.area / 1e4, 1), **extra,
        access_scope=f"assessed neighbourhoods of {engine.MIN_HOMES}+ mapped buildings (same as the scan)",
        inside_scope="every mapped building whose centre is inside the affected area",
        roads_affected_km=round(sum(f.length for f in a["flooded"]) / 1000, 2), road_segments_affected=len(a["flooded"]),
        neighbourhoods_losing_access=a["n_affected_nb"],
        counts=counts, headline={k: max(v.values()) for k, v in counts.items()},   # frozen higher-of-two rule
        ids={s: {k: sorted(int(i) for i in a[src][s]) for k, src in (("cut", "cut"), ("inside", "inside"), ("retain", "retain"))}
             for s in engine.SOURCES},
        zone=fc([dict(type="Feature", properties={}, geometry=mapping(transform(to_ll, zone.simplify(1))))]),
        roads_affected=fc([dict(type="Feature", properties={}, geometry=mapping(transform(to_ll, f))) for f in a["flooded"]]),
        cut_roads=fc([dict(type="Feature", properties={}, geometry=mapping(transform(to_ll, l))) for l in a["cut_lines"]]),
    )


_cache: dict = {}
_lock = Lock()


def hypothetical(area: engine.Area, lon: float, lat: float, radius_m: float) -> dict:
    """A supplied hypothetical affected area: a circle. The radius is an input, not a predicted fire spread.

    The validated inputs are used exactly, for the geometry, the cache identity and the returned metadata alike
    (no rounding on any side), so a result never depends on which requests came before it."""
    lon, lat, r = float(lon), float(lat), float(radius_m)
    if not all(math.isfinite(v) for v in (lon, lat, r)):
        raise ValueError("centre and radius must be finite numbers")
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("centre must be a longitude/latitude")
    if not MIN_RADIUS_M <= r <= MAX_RADIUS_M:
        raise ValueError(f"radius must be {MIN_RADIUS_M:.0f}-{MAX_RADIUS_M:.0f} m")
    key = ("hyp", area.name, lon, lat, r)
    with _lock:
        if key not in _cache:
            centre = Point(_TO_M(lon, lat))
            _cache[key] = _result(area, centre.buffer(r, 64), "hypothetical", dict(centre=[lon, lat], radius_m=r))
        return _cache[key]


def historical(area: engine.Area) -> dict:
    """The mapped 2023 Upper Tantallon fire perimeter, with each Westwood entrance's distance to it."""
    key = ("hist", area.name)
    with _lock:
        if key not in _cache:
            poly, meta = mapped_perimeter()
            ents = [dict(inside=bool(poly.contains(p)), distance_m=round(poly.distance(p)))   # 0 when inside
                    for p in (Point(_TO_M(*ll)) for ll in WESTWOOD_ENTRANCES)]
            _cache[key] = _result(area, poly, "historical", dict(perimeter=meta, westwood_entrances=ents))
        return _cache[key]
