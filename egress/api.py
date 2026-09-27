"""FastAPI backend: serves scan results and the static map. Run: python scripts/serve.py"""
import math
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, context, engine, fire, flood, probe, viz

AREAS = {
    "tantallon": dict(label="Upper Tantallon, NS", center=[-63.862, 44.715], zoom=13.2),
    "fredericton": dict(label="Fredericton, NB", center=[-66.645, 45.958], zoom=12.5),
}
# Scenario availability per area - the single source of truth for the API and the map.
#   fire_hyp  : a supplied circle; area-agnostic (fire.hypothetical needs only the loaded area).
#   fire_hist : the 2023 NBAC perimeter - the only mapped perimeter intersecting any study box (Tantallon).
#   flood     : Fredericton only - flood.py hardcodes the Fredericton gauge, datum offset and river seed.
SCENARIOS = {"tantallon": dict(flood=False, fire_hyp=True, fire_hist=True),
             "fredericton": dict(flood=True, fire_hyp=True, fire_hist=False)}
for _k, _v in AREAS.items():
    _v["scenarios"] = SCENARIOS[_k]

_cache: dict[str, dict] = {}
_lock = Lock()


def get(area: str) -> dict:
    if area not in AREAS:
        raise HTTPException(404, f"unknown area {area!r}")
    with _lock:
        if area not in _cache:
            a = engine.load_area(area)
            results = engine.scan(a)
            _cache[area] = dict(area=a, results=results, geo=engine.results_geojson(results),
                                roads=engine.roads_geojson(a), boundary=engine.boundary_geojson(a))
        return _cache[area]


@asynccontextmanager
async def lifespan(app: FastAPI):
    for name in AREAS:          # pre-compute so the first click is instant
        get(name)
        for src in engine.SOURCES:
            viz.footprints(get(name)["area"], src)   # also verifies footprint ids match engine building ids
        context.water_geojson(name)
    yield


app = FastAPI(title="Egress mapper", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2048)   # footprints are large but compress well


@app.get("/api/areas")
def areas():
    return AREAS


@app.get("/api/{area}/scan")
def scan(area: str):
    c = get(area)
    counts = {}
    for r in c["results"]:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return dict(summary=dict(counts=counts, block_radius_m=engine.BLOCK_RADIUS_M, min_homes=engine.MIN_HOMES),
                **c["geo"])


@app.get("/api/{area}/roads")
def roads(area: str):
    return get(area)["roads"]


@app.get("/api/{area}/boundary")
def boundary(area: str):
    return get(area)["boundary"]


@app.get("/api/{area}/buildings/{src}")
def buildings(area: str, src: str):
    """Analysed footprints (>= 40 m2) for one source; feature id = engine building id. Display only."""
    if src not in engine.SOURCES:
        raise HTTPException(404, "source must be osm or ms")
    return Response(viz.footprints(get(area)["area"], src), media_type="application/json")


@app.get("/api/{area}/water")
def water(area: str):
    """Mapped open water (OSM water/riverbank/reservoir) in the study box. Geographic context only: never analysed."""
    get(area)
    return Response(context.water_geojson(area), media_type="application/json")


@app.get("/api/{area}/nb/{nid}/buildings")
def nb_buildings(area: str, nid: int):
    """Building ids per source for this neighbourhood's worst blockage: cut / inside / retain. Display only."""
    c = get(area)
    r = next((r for r in c["results"] if r["nid"] == nid), None)
    if r is None:
        raise HTTPException(404, f"no neighbourhood {nid}")
    key = ("cat", area, nid)
    if key not in c:
        c[key] = viz.categories(c["area"], r)
    return c[key]


@app.get("/api/fredericton/flood/info")
def flood_info():
    """Reference values (gauge heights, CGVD28) with their CGVD2013 equivalents, and elevation-model coverage."""
    return dict(gauge=flood.GAUGE, offset_m=flood.CGVD28_TO_CGVD2013_M,
                flood_stage_gauge_m=flood.FLOOD_STAGE_GAUGE_M,
                flood_stage_cgvd2013_m=round(flood.gauge_to_cgvd2013(flood.FLOOD_STAGE_GAUGE_M), 2),
                peak_2008_gauge_m=flood.PEAK_2008_GAUGE_M,
                peak_2008_cgvd2013_m=round(flood.gauge_to_cgvd2013(flood.PEAK_2008_GAUGE_M), 2),
                coverage=flood.coverage_geojson())


@app.get("/api/fredericton/flood")
def flood_scenario(gauge: float):
    """Road access under a USER-SUPPLIED river level: `gauge` = gauge height (m, CGVD28) at WSC 01AK003."""
    if not 3.0 <= gauge <= 11.0:
        raise HTTPException(400, "gauge must be between 3 and 11 m")
    return flood.scenario(get("fredericton")["area"], gauge)


@app.get("/api/tantallon/fire/historical")
def fire_historical():
    """Road access under the MAPPED 2023 Upper Tantallon fire perimeter (NBAC). Not a fire-spread prediction.
    Tantallon only: no other mapped perimeter intersects a study box."""
    return {**fire.historical(get("tantallon")["area"]), "area": "tantallon"}


@app.get("/api/{area}/fire/hypothetical")
def fire_hypothetical(area: str, lon: float, lat: float, radius: float):
    """Road access under a SUPPLIED hypothetical circular area in the REQUESTED study area. The radius is an input, not
    predicted spread. The response carries the area it was computed for, so a client can reject a mismatch."""
    if area not in AREAS or not SCENARIOS[area]["fire_hyp"]:
        raise HTTPException(404, f"hypothetical fire is not available for {area!r}")
    try:
        return {**fire.hypothetical(get(area)["area"], lon, lat, radius), "area": area}
    except ValueError as e:                     # non-finite / out-of-range centre or radius
        raise HTTPException(400, str(e))


class ProbePoint(BaseModel):
    lon: float
    lat: float
    radius: float = probe.SCAN_RADIUS_M      # user probe only; default = the scan's fixed 50 m


@app.post("/api/{area}/nb/{nid}/probe")
def nb_probe(area: str, nid: int, p: ProbePoint):
    """A blockage the USER placed (snapped to this neighbourhood's roads): the scan's own evaluate_block at that point.
    Never a scan result; does not change the scan, ranking or classification."""
    c = get(area)
    r = next((r for r in c["results"] if r["nid"] == nid), None)
    if r is None:
        raise HTTPException(404, f"no neighbourhood {nid}")
    if not (math.isfinite(p.lon) and math.isfinite(p.lat) and math.isfinite(p.radius)):
        raise HTTPException(400, "lon/lat/radius must be finite")
    return probe.probe(c["area"], r, p.lon, p.lat, p.radius)


@app.get("/api/{area}/nb/{nid}/probe-roads")
def nb_probe_roads(area: str, nid: int):
    """Roads where a blockage may be placed for this neighbourhood (its own roads + connections to major roads)."""
    c = get(area)
    r = next((r for r in c["results"] if r["nid"] == nid), None)
    if r is None:
        raise HTTPException(404, f"no neighbourhood {nid}")
    return probe.eligible_geojson(c["area"], r)


class Proposal(BaseModel):
    a: tuple[float, float]   # lon, lat of first click
    b: tuple[float, float]


@app.post("/api/{area}/mitigate")
def mitigate(area: str, p: Proposal):
    return engine.mitigate(get(area)["area"], p.a, p.b)


app.mount("/", StaticFiles(directory=config.REPO / "web", html=True), name="web")
