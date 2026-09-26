"""FastAPI backend: serves scan results and the static map. Run: python scripts/serve.py"""
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, engine, flood

AREAS = {
    "tantallon": dict(label="Upper Tantallon, NS", center=[-63.862, 44.715], zoom=13.2),
    "fredericton": dict(label="Fredericton, NB", center=[-66.645, 45.958], zoom=12.5),
}

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
    yield


app = FastAPI(title="Egress mapper", lifespan=lifespan)


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


@app.get("/api/fredericton/flood")
def flood_scenario(gauge: float):
    """River level scenario: `gauge` is the user-supplied gauge height (m, CGVD28) at WSC 01AK003."""
    if not 3.0 <= gauge <= 11.0:
        raise HTTPException(400, "gauge must be between 3 and 11 m")
    return flood.scenario(get("fredericton")["area"], gauge)


@app.get("/api/fredericton/flood/info")
def flood_info():
    return dict(gauge=flood.GAUGE, offset_m=flood.CGVD28_TO_CGVD2013_M, flood_stage_gauge_m=flood.FLOOD_STAGE_GAUGE_M,
                peak_2008_gauge_m=flood.PEAK_2008_GAUGE_M,
                peak_2008_cgvd2013_m=round(flood.gauge_to_cgvd2013(flood.PEAK_2008_GAUGE_M), 2),
                coverage=flood.coverage_geojson())


class Proposal(BaseModel):
    a: tuple[float, float]   # lon, lat of first click
    b: tuple[float, float]


@app.post("/api/{area}/mitigate")
def mitigate(area: str, p: Proposal):
    return engine.mitigate(get(area)["area"], p.a, p.b)


app.mount("/", StaticFiles(directory=config.REPO / "web", html=True), name="web")
