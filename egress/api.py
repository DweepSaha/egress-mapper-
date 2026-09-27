"""FastAPI backend: serves scan results and the static map. Run: python scripts/serve.py"""
import ctypes
import gc
import logging
import math
import sys
import time
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import areas as registry
from . import config, context, engine, fire, flood, probe, viz

log = logging.getLogger("uvicorn.error")

AREAS = registry.load()      # pinned first, then NB / NS / PEI; each carries its survey counts for the picker
# Scenario availability per area - the single source of truth for the API and the map.
#   fire_hyp  : a supplied circle; area-agnostic (fire.hypothetical needs only the loaded area).
#   fire_hist : the 2023 NBAC perimeter - the only mapped perimeter intersecting any study box (Tantallon).
#   flood     : Fredericton only - flood.py hardcodes the Fredericton gauge, datum offset and river seed.
UNAVAILABLE_WHY = {
    "flood": "Flood needs a terrain model and a calibrated river gauge; both are prepared for Fredericton only.",
    "fire_hist": "The only mapped fire perimeter in any study area is the 2023 Upper Tantallon fire.",
    "fire_hyp": "This area's road data is not available.",
}
SCENARIOS = {k: dict(flood=k == "fredericton" and v["available"], fire_hyp=v["available"],
                     fire_hist=k == "tantallon" and v["available"]) for k, v in AREAS.items()}
for _k, _v in AREAS.items():
    _v["scenarios"] = SCENARIOS[_k]
    _v["scenario_why"] = {s: UNAVAILABLE_WHY[s] for s, ok in SCENARIOS[_k].items() if not ok}

# ---------- area cache: pinned areas stay resident; at most ONE other area is loaded at a time ----------
# Opening an area (GET /scan) is the only request that may load it. Loads of non-pinned areas are serialized and the
# latest opened area wins: a queued load that is no longer the latest is skipped (409), and the previous non-pinned
# area - with every per-area cache - is freed BEFORE the next one loads, so peak memory is bounded by the pinned areas
# plus one. Other endpoints never trigger a load: they answer for the loaded area or refuse (409).
_cache: dict[str, dict] = {}
_lock = Lock()               # guards _cache / _wanted (held briefly, never during a non-pinned load)
_load_lock = Lock()          # serializes loads of non-pinned areas
_wanted: str | None = None   # the non-pinned area most recently opened


def _mem_mb() -> tuple[float, float]:
    """(working set, peak working set) of this process in MB; Windows only, (nan, nan) elsewhere."""
    if sys.platform != "win32":
        return float("nan"), float("nan")
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("Peak", ctypes.c_size_t),
                    ("WS", ctypes.c_size_t), *[(n, ctypes.c_size_t) for n in "abcdef"]]
    k, p = ctypes.windll.kernel32, ctypes.windll.psapi
    k.GetCurrentProcess.restype = wintypes.HANDLE
    p.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    c = PMC(cb=ctypes.sizeof(PMC))
    p.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.WS / 1e6, c.Peak / 1e6


def _check(area: str) -> None:
    if area not in AREAS:
        raise HTTPException(404, f"unknown area {area!r}")
    if not AREAS[area]["available"]:
        raise HTTPException(503, AREAS[area]["reason"])


def _build(area: str) -> dict:
    t0 = time.time()
    a = engine.load_area(area)
    results = engine.scan(a)
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    s = AREAS[area]["survey"]
    survey = {k: s[k] for k in ("red", "amber", "green", "not_assessed") if s[k]}
    if counts != survey:     # the picker shows the survey counts: they must be what the map shows
        log.error("area %s: live scan counts %s differ from the survey %s", area, counts, survey)
    ws, peak = _mem_mb()
    log.info("area %s loaded in %.0f s; memory %.0f MB (peak %.0f MB)", area, time.time() - t0, ws, peak)
    return dict(area=a, results=results, counts=counts, geo=engine.results_geojson(results),
                roads=engine.roads_geojson(a), boundary=engine.boundary_geojson(a))


def _evict(area: str) -> None:
    """Free a non-pinned area and everything cached for it (fire results, probe neighbourhoods/roads)."""
    with _lock:
        _cache.pop(area, None)
    with fire._lock:
        for k in [k for k in fire._cache if k[1] == area]:
            del fire._cache[k]
    for d in (probe._NBS, probe._ELIG):
        for k in [k for k in d if k[0] == area]:
            d.pop(k, None)
    gc.collect()
    ws, peak = _mem_mb()
    log.info("area %s freed; memory %.0f MB (peak %.0f MB)", area, ws, peak)


def open_area(area: str) -> dict:
    """Load (if needed) the area the user opened. Only GET /scan and startup call this."""
    global _wanted
    _check(area)
    with _lock:
        if area in _cache:
            if area not in registry.PINNED:
                _wanted = area
            return _cache[area]
        if area in registry.PINNED:          # preloaded at startup; only reached then (or if that failed)
            _cache[area] = _build(area)
            return _cache[area]
        _wanted = area
    with _load_lock:
        with _lock:
            if area in _cache:
                return _cache[area]
            if _wanted != area:
                raise HTTPException(409, f"superseded: {_wanted!r} was opened after {area!r}")
            old = [k for k in _cache if k not in registry.PINNED]
        for k in old:
            _evict(k)
        c = _build(area)
        with _lock:
            _cache[area] = c
        return c


def get(area: str) -> dict:
    """The loaded area, for every request except opening it. Never loads: an area that is being opened is waited for;
    one that is not loaded (freed, or never opened) is refused with 409 so a stale request cannot reload it."""
    _check(area)
    with _lock:
        if area in _cache:
            return _cache[area]
        pending = area == _wanted
    if pending:
        with _load_lock:                     # its load is queued or running: wait for it
            pass
        with _lock:
            if area in _cache:
                return _cache[area]
    raise HTTPException(409, f"area {area!r} is not loaded (open it first)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    for name in registry.PINNED:             # pre-compute the demo path so the first click is instant
        if not AREAS[name]["available"]:
            continue
        open_area(name)
        for src in engine.SOURCES:
            footprints(name, src)             # also verifies footprint ids match engine building ids
        water_bytes(name)
    yield


app = FastAPI(title="Egress mapper", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=2048)   # footprints are large but compress well


def footprints(area: str, src: str) -> bytes:
    c = get(area)
    key = ("fp", src)
    if key not in c:
        c[key] = viz.footprints(c["area"], src)
    return c[key]


def water_bytes(area: str) -> bytes:
    c = get(area)
    if "water" not in c:
        c["water"] = context.water_geojson(area, registry.PROVINCE_GPKG[AREAS[area]["province"]])
    return c["water"]


@app.get("/api/areas")
def areas():
    return AREAS


@app.get("/api/{area}/scan")
def scan(area: str):
    c = open_area(area)
    return dict(summary=dict(counts=c["counts"], block_radius_m=engine.BLOCK_RADIUS_M, min_homes=engine.MIN_HOMES),
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
    return Response(footprints(area, src), media_type="application/json")


@app.get("/api/{area}/water")
def water(area: str):
    """Mapped open water (OSM water/riverbank/reservoir) in the study box. Geographic context only: never analysed."""
    return Response(water_bytes(area), media_type="application/json")


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
