"""DATA PREP + BATCH (not project code): the EXISTING frozen scan on Nova Scotia and PEI communities.

Same stages as scratch/nb_batch.py (extract_areas: complete_ways cut, OSMnx 'drive' XML, GraphML; OSM buildings from
the province GeoPackage; Microsoft footprints streamed from the zipped GeoJSON), then egress-mapper/scratch/nb_scan.py
(engine.load_area + engine.scan, study box added to engine.STUDY_BBOX at run time; nothing in egress/ changes).
One area / one stage per process, resumable, logged, free-RAM guard with headroom for open browsers.

    python scratch/maritimes_batch.py          # everything
    python scratch/maritimes_batch.py plan     # boxes + overlap check only
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scratch"))
import extract_areas as X  # noqa: E402

REPO = ROOT.parent / "egress-mapper"
OUT = REPO / "out" / "maritimes"
LOG = OUT / "progress.log"
PY = sys.executable
MIN_FREE_MB = 1800            # headroom: browsers stay open
WAIT_TRIES = 20               # x 30 s = up to 10 min before skipping an area

NS, PEI = "nova-scotia", "prince-edward-island"
# centre (lon, lat) from OSM place points (province GeoPackage gis_osm_places_free) +/- km, or an explicit box.
NEW = {
    "hrm":           dict(prov=NS, box=(-63.97, 44.58, -63.42, 44.86),
                          kind="Halifax core + Dartmouth/Cole Harbour + Bedford + Sackville + Hammonds Plains + Tantallon"),
    "cbrm":          dict(prov=NS, c=(-60.080, 46.180), km=12, kind="Sydney + Sydney Mines + Glace Bay (CBRM)"),
    "truro":         dict(prov=NS, c=(-63.287, 45.366), km=6, kind="town"),
    "new_glasgow":   dict(prov=NS, c=(-62.650, 45.575), km=6, kind="New Glasgow + Stellarton + Trenton"),
    "kentville":     dict(prov=NS, c=(-64.440, 45.085), km=7, kind="Kentville + Wolfville"),
    "amherst":       dict(prov=NS, c=(-64.204, 45.829), km=5, kind="town"),
    "bridgewater":   dict(prov=NS, c=(-64.519, 44.377), km=5, kind="town"),
    "yarmouth":      dict(prov=NS, c=(-66.116, 43.837), km=5, kind="town"),
    "antigonish":    dict(prov=NS, c=(-61.991, 45.621), km=5, kind="town (eastern mainland)"),
    "chester":       dict(prov=NS, c=(-64.241, 44.541), km=5, kind="rural South Shore"),
    "charlottetown": dict(prov=PEI, c=(-63.130, 46.235), km=7, kind="Charlottetown + Stratford + Cornwall"),
    "summerside":    dict(prov=PEI, c=(-63.789, 46.394), km=5, kind="city"),
    "montague":      dict(prov=PEI, c=(-62.654, 46.171), km=5, kind="rural eastern PEI"),
}
for k, v in NEW.items():
    if "box" in v:
        X.AREAS[k] = dict(province=v["prov"], base=v["box"], buffer_km=0, desc=f"{k}: {v['kind']}")
    else:
        X.AREAS[k] = dict(province=v["prov"], base=(v["c"][0], v["c"][1], v["c"][0], v["c"][1]), buffer_km=v["km"],
                          desc=f"{k}: {v['kind']}, OSM place point +/- {v['km']} km")
# every other study box in the survey (existing + NB batch), for the overlap check
OTHER = {"tantallon": (-63.92099, 44.64583, -63.68461, 44.81847)}
nb_dir = REPO / "out" / "nb_survey"
for f in nb_dir.glob("*.json"):
    OTHER[f.stem] = tuple(json.loads(f.read_text(encoding="utf-8"))["bbox"])
INTENDED_OVERLAP = {("hrm", "tantallon")}   # HRM deliberately covers Tantallon; totals use HRM, not the Tantallon run


def boxes():
    return {k: X.bbox(k) for k in NEW}


def overlaps():
    b = {**OTHER, **boxes()}
    names, out = list(b), []
    for i, p in enumerate(names):
        for q in names[i + 1:]:
            if p not in NEW and q not in NEW:
                continue
            x0, y0, x1, y1 = b[p]; u0, v0, u1, v1 = b[q]
            if x0 < u1 and u0 < x1 and y0 < v1 and v0 < y1 and (p, q) not in INTENDED_OVERLAP and (q, p) not in INTENDED_OVERLAP:
                out.append((p, q))
    return out


def log(msg):
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def wait_for_ram(what):
    for i in range(WAIT_TRIES):
        free = X.free_ram_mb()
        if free >= MIN_FREE_MB:
            return True
        if i % 4 == 0:
            log(f"  low RAM before {what}: {free:.0f} MB free (< {MIN_FREE_MB}); waiting")
        time.sleep(30)
    log(f"  SKIP {what}: RAM stayed below {MIN_FREE_MB} MB for {WAIT_TRIES * 30 // 60} min")
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
    if name in ("extract", "graph", "buildings"):
        return X.STAGES[name](area)
    if name == "msclip":
        import clip_microsoft as C
        C.PROVINCE_ZIP[PEI] = "PrinceEdwardIsland.zip"
        C.AREAS[area] = X.AREAS[area]
        C.bbox = X.bbox
        C.clip_province(X.AREAS[area]["province"], [area])
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
    b, ov = boxes(), overlaps()
    if len(sys.argv) >= 2 and sys.argv[1] == "plan":
        for k, v in b.items():
            print(f"{k:<14} {NEW[k]['prov']:<22} {v}")
        print("unintended overlaps:", ov or "none", "| intended:", INTENDED_OVERLAP)
        return
    if ov:
        log(f"ABORT: overlapping study boxes {ov}")
        sys.exit(2)
    log(f"=== Maritimes batch start: {len(NEW)} areas (NS + PEI) + Tantallon reference scan; free RAM {X.free_ram_mb():.0f} MB ===")
    log("[tantallon] existing validation area: scan only (reference; excluded from totals, HRM covers it)")
    scan("tantallon", OTHER["tantallon"])
    for area in NEW:
        t0 = time.time()
        log(f"[{area}] start; box {b[area]}")
        ok = (stage(area, "extract", X.EXTRACTS / f"{area}-drive.osm")
              and stage(area, "graph", X.ROADS / f"{area}.graphml")
              and stage(area, "buildings", X.BUILDINGS / f"{area}.gpkg")
              and stage(area, "msclip", X.BUILDINGS / "microsoft" / f"{area}.gpkg")
              and scan(area, b[area]))
        log(f"[{area}] {'DONE' if ok else 'SKIPPED/FAILED'} in {time.time() - t0:.0f}s")
    log("=== Maritimes batch end ===")


if __name__ == "__main__":
    main()
