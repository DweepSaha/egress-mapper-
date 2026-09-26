"""Geographic context layers for the map. DISPLAY ONLY: nothing here feeds any calculation.

Mapped water: open-water polygons (water / riverbank / reservoir) from the local Geofabrik OSM GeoPackage, clipped to
the area's study box. Wetland classes are excluded (not open water), and the prepared data has lost OSM's intermittent
tag, so the audience wording is "mapped water", not verified permanent water. The flood scenario never uses this layer
(its river seed and inundation come from the elevation model in flood.py).
"""
from __future__ import annotations

import json
from functools import lru_cache

import geopandas as gpd
from shapely.geometry import box, mapping

from . import config, engine

WATER_CLASSES = ("water", "riverbank", "reservoir")
PROVINCE_GPKG = {"fredericton": "new-brunswick.gpkg", "tantallon": "nova-scotia.gpkg",
                 "pointe_sapin": "new-brunswick.gpkg"}
SIMPLIFY_M = 3.0          # display simplification; the layer is context only


@lru_cache(maxsize=None)
def water_geojson(area: str) -> bytes:
    """Mapped open water in the study box as a compact GeoJSON FeatureCollection (EPSG:4326, 6-decimal coordinates)."""
    bbox = engine.STUDY_BBOX[area]
    g = gpd.read_file(config.DATA / "osm" / PROVINCE_GPKG[area], layer="gis_osm_water_a_free", bbox=bbox)
    g = g[g["fclass"].isin(WATER_CLASSES)]
    g = g.to_crs(4326).clip(box(*bbox))
    g = g[~g.geometry.is_empty]
    geom = g.to_crs(config.ANALYSIS_CRS).geometry.simplify(SIMPLIFY_M).to_crs(4326)
    feats = []
    for (_, row), shp in zip(g.iterrows(), geom):
        if shp.is_empty:
            continue
        feats.append({"type": "Feature", "properties": {"fclass": row["fclass"]},
                      "geometry": _round(mapping(shp))})
    return json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")).encode()


def _round(geo: dict) -> dict:
    def r(c):
        return [round(c[0], 6), round(c[1], 6)] if isinstance(c[0], float) else [r(x) for x in c]
    return {"type": geo["type"], "coordinates": r(geo["coordinates"])}
