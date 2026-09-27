"""BATCH HELPER (read-only use of the frozen engine): scan one area and write its results as JSON.

    python scratch/nb_scan.py <area> '<[lon0,lat0,lon1,lat1]>' <out.json>

The area's study box is added to engine.STUDY_BBOX at run time (no change to egress/). Parameters are the frozen
ones: 50 m radius, 50 m sampling, 30+ mapped buildings, 40 m2 footprints, 150 m assignment, 2 km boundary rule.
"""
import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from shapely.geometry import box  # noqa: E402
from shapely.ops import transform  # noqa: E402

from egress import engine  # noqa: E402


def peak_mb():
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("Peak", ctypes.c_size_t),
                    ("WS", ctypes.c_size_t), *[(n, ctypes.c_size_t) for n in "abcdef"]]
    k, p = ctypes.windll.kernel32, ctypes.windll.psapi
    k.GetCurrentProcess.restype = wintypes.HANDLE
    p.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    c = PMC(cb=ctypes.sizeof(PMC)); p.GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.Peak / 1e6


def main(area, bbox, out):
    bbox = tuple(bbox)
    if area not in engine.STUDY_BBOX:
        engine.STUDY_BBOX[area] = bbox
    assert tuple(engine.STUDY_BBOX[area]) == tuple(round(v, 5) for v in bbox) or area in ("fredericton", "pointe_sapin", "tantallon"), \
        (engine.STUDY_BBOX[area], bbox)
    t0 = time.time()
    a = engine.load_area(area)
    t_load = time.time() - t0
    res = engine.scan(a)
    t_all = time.time() - t0
    study = transform(engine._TO_M, box(*engine.STUDY_BBOX[area]))
    counts = {}
    for r in res:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    nbs = []
    for r in res:
        ch = engine._TO_LL(r["choke"].x, r["choke"].y) if r["choke"] is not None else None
        nbs.append(dict(nid=r["nid"], status=r["status"], homes=r["homes"], homes_osm=r["homes_osm"], homes_ms=r["homes_ms"],
                        gateways=r["gateways"], worst_cut=r["worst_cut"], worst_cut_osm=r["worst_cut_osm"],
                        worst_cut_ms=r["worst_cut_ms"], rank=r["rank"],
                        choke=[round(ch[0], 6), round(ch[1], 6)] if ch else None))
    d = dict(area=area, bbox=list(engine.STUDY_BBOX[area]), box_km2=round(study.area / 1e6, 1),
             assessable_km2=round(a.assessable.area / 1e6, 1) if not a.assessable.is_empty else 0.0,
             buildings_osm=len(a.bld["osm"]["pts"]), buildings_ms=len(a.bld["ms"]["pts"]),
             road_segments=len(a.edges), counts=counts, n_neighbourhoods=len(res),
             runtime_load_s=round(t_load, 1), runtime_total_s=round(t_all, 1), peak_mb=round(peak_mb()),
             params=dict(block_radius_m=engine.BLOCK_RADIUS_M, sweep_spacing_m=engine.SWEEP_SPACING_M,
                         min_homes=engine.MIN_HOMES, min_footprint_m2=engine.MIN_HOME_M2,
                         max_assign_m=engine.MAX_ASSIGN_M, boundary_buffer_m=engine.BOUNDARY_BUFFER_M),
             neighbourhoods=nbs)
    Path(out).write_text(json.dumps(d, indent=1), encoding="utf-8")
    print(f"{area}: {d['buildings_osm']} OSM / {d['buildings_ms']} MS; {len(res)} nbs {counts}; "
          f"{t_all:.0f}s; peak {d['peak_mb']} MB")


if __name__ == "__main__":
    main(sys.argv[1], json.loads(sys.argv[2]), sys.argv[3])
