"""DATA PREP + BATCH (not project code): run the EXISTING, frozen scan on more New Brunswick communities.

Same pipeline as the original three areas (scratch/extract_areas.py stages: complete_ways cut, OSMnx 'drive' XML,
GraphML; OSM buildings from the NB GeoPackage; Microsoft footprints streamed from the zipped GeoJSON), then
egress-mapper/scratch/nb_scan.py runs engine.load_area + engine.scan with the frozen parameters. Nothing in egress/
is modified: each new area's study box is added to engine.STUDY_BBOX at run time inside the scan process.

Unattended: one area and one stage at a time, each in its own process (memory freed between them), results written
per area, resumable (finished stages are skipped), progress logged, and a free-RAM guard before every stage.

    python scratch/nb_batch.py            # everything
    python scratch/nb_batch.py plan       # print boxes + overlap check only
"""
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scratch"))
import extract_areas as X  # noqa: E402

REPO = ROOT.parent / "egress-mapper"
OUT = REPO / "out" / "nb_survey"
LOG = OUT / "progress.log"
PY = sys.executable
MIN_FREE_MB = 1500

# centre (lon, lat) from OSM place points (data/osm/new-brunswick.gpkg gis_osm_places_free); half-width in km.
# Oromocto is NOT added: it lies inside the existing Fredericton study box (already scanned there).
NEW = {
    "moncton":      dict(c=(-64.770, 46.090), km=10, kind="city (Moncton + Dieppe + Riverview)"),
    "saint_john":   dict(c=(-66.060, 45.280), km=9,  kind="city"),
    "quispamsis":   dict(c=(-65.975, 45.410), km=5,  kind="suburban (Quispamsis + Rothesay)"),
    "miramichi":    dict(c=(-65.500, 47.010), km=7,  kind="small city along the river"),
    "bathurst":     dict(c=(-65.654, 47.610), km=6,  kind="small city"),
    "edmundston":   dict(c=(-68.329, 47.364), km=6,  kind="small city"),
    "campbellton":  dict(c=(-66.677, 48.004), km=5,  kind="town (north)"),
    "woodstock":    dict(c=(-67.574, 46.150), km=5,  kind="town"),
    "grand_falls":  dict(c=(-67.741, 47.048), km=5,  kind="town"),
    "sussex":       dict(c=(-65.505, 45.720), km=5,  kind="town"),
    "shediac":      dict(c=(-64.540, 46.220), km=5,  kind="town / coastal"),
    "sackville":    dict(c=(-64.366, 45.905), km=5,  kind="town"),
    "st_stephen":   dict(c=(-67.276, 45.193), km=5,  kind="town (border)"),
    "caraquet":     dict(c=(-64.939, 47.790), km=5,  kind="rural coastal (Acadian Peninsula)"),
    "richibucto":   dict(c=(-64.867, 46.670), km=5,  kind="rural (Kent County)"),
}
for k, v in NEW.items():
    X.AREAS[k] = dict(province="new-brunswick", base=(v["c"][0], v["c"][1], v["c"][0], v["c"][1]), buffer_km=v["km"],
                      desc=f"{k}: {v['kind']}, OSM place point +/- {v['km']} km")
EXISTING_NB = {"fredericton": (-66.91630, 45.75717, -66.38280, 46.14033),
               "pointe_sapin": (-65.08820, 46.74423, -64.77630, 47.07787)}


def boxes():
    b = dict(EXISTING_NB)
    b.update({k: X.bbox(k) for k in NEW})
    return b


def overlaps():
    b, names, out = boxes(), list(boxes()), []
    for i, p in enumerate(names):
        for q in names[i + 1:]:
            x0, y0, x1, y1 = b[p]; u0, v0, u1, v1 = b[q]
            if x0 < u1 and u0 < x1 and y0 < v1 and v0 < y1:
                out.append((p, q))
    return out


def log(msg):
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def wait_for_ram(what):
    for _ in range(10):                            # up to ~5 min for memory to come back
        free = X.free_ram_mb()
        if free >= MIN_FREE_MB:
            return True
        log(f"  low RAM before {what}: {free:.0f} MB free (< {MIN_FREE_MB}); waiting 30 s")
        time.sleep(30)
    log(f"  SKIP {what}: RAM stayed below {MIN_FREE_MB} MB")
    return False


def stage(area, name, done_path):
    if done_path.exists():
        log(f"  {name}: already done ({done_path.name})")
        return True
    if not wait_for_ram(f"{name} {area}"):
        return False
    t0 = time.time()
    r = subprocess.run([PY, "-u", __file__, "stage", name, area], capture_output=True, text=True, encoding="utf-8")
    tail = (r.stdout or "").strip().splitlines()[-2:] + (r.stderr or "").strip().splitlines()[-3:]
    log(f"  {name}: rc={r.returncode} in {time.time() - t0:.0f}s :: " + " | ".join(tail)[-400:])
    return r.returncode == 0 and done_path.exists()


def run_stage(name, area):
    """Runs inside a child process."""
    if name in ("extract", "graph", "buildings"):
        return X.STAGES[name](area)
    if name == "msclip":                           # Microsoft footprints for ONE area (streams the zipped GeoJSON)
        import clip_microsoft as C
        C.AREAS[area] = X.AREAS[area]
        C.bbox = X.bbox
        C.clip_province("new-brunswick", [area])
        return True
    raise SystemExit(f"unknown stage {name}")


def scan(area, box):
    out = OUT / f"{area}.json"
    if out.exists():
        log(f"  scan: already done ({out.name})")
        return True
    if not wait_for_ram(f"scan {area}"):
        return False
    t0 = time.time()
    r = subprocess.run([PY, "-u", str(REPO / "scratch" / "nb_scan.py"), area, json.dumps(box), str(out)],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(REPO))
    tail = (r.stdout or "").strip().splitlines()[-1:] + (r.stderr or "").strip().splitlines()[-3:]
    log(f"  scan: rc={r.returncode} in {time.time() - t0:.0f}s :: " + " | ".join(tail)[-400:])
    return r.returncode == 0 and out.exists()


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "stage":
        rc = run_stage(sys.argv[2], sys.argv[3])
        sys.exit(1 if rc is False else 0)
    b = boxes()
    ov = overlaps()
    if len(sys.argv) >= 2 and sys.argv[1] == "plan":
        for k, v in b.items():
            print(f"{k:<14} {v}")
        print("overlaps:", ov or "none")
        return
    if ov:
        log(f"ABORT: overlapping study boxes {ov}")
        sys.exit(2)
    log(f"=== NB batch start: {len(NEW)} new areas + existing fredericton, pointe_sapin; free RAM {X.free_ram_mb():.0f} MB ===")
    # existing NB areas: scan only (their data are untouched)
    for area in EXISTING_NB:
        log(f"[{area}] existing area: scan only")
        scan(area, EXISTING_NB[area])
    for area in NEW:
        t0 = time.time()
        log(f"[{area}] start; box {b[area]}")
        ok = (stage(area, "extract", X.EXTRACTS / f"{area}-drive.osm")
              and stage(area, "graph", X.ROADS / f"{area}.graphml")
              and stage(area, "buildings", X.BUILDINGS / f"{area}.gpkg")
              and stage(area, "msclip", X.BUILDINGS / "microsoft" / f"{area}.gpkg")
              and scan(area, b[area]))
        log(f"[{area}] {'DONE' if ok else 'SKIPPED/FAILED'} in {time.time() - t0:.0f}s")
    log("=== NB batch end ===")


if __name__ == "__main__":
    main()
