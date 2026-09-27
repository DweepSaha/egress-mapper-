"""Build (and optionally verify) the disk cache of prepared areas, so opening one is a read instead of a scan.

    python scripts/build_area_cache.py hrm moncton          # these areas
    python scripts/build_area_cache.py --all                # every non-pinned area
    python scripts/build_area_cache.py --verify hrm         # also prove the cache is exact (costs a second scan)

The cache holds engine.load_area's Area and engine.scan's results, unchanged (see egress/areacache.py). --verify
re-scans the UNPICKLED area and requires identical results (every field, geometries as exact WKB), checks the status
counts against the committed survey, and for HRM runs the exact Westwood mitigation on the fresh and the unpickled
area. One area at a time, with a free-RAM guard (the machine runs other applications).
"""
import ctypes
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from egress import areacache, engine  # noqa: E402
from egress import areas as registry  # noqa: E402

MIN_FREE_MB = 900
WESTWOOD = ((-63.87399, 44.72806), (-63.85501, 44.70479))   # the rehearsed mitigation proposal


def free_mb() -> float:
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), *[(n, ctypes.c_ulonglong) for n in "abcde"]]
    m = MS(dwLength=ctypes.sizeof(MS))
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 1e6


def counts(results):
    c = {}
    for r in results:
        c[r["status"]] = c.get(r["status"], 0) + 1
    return c


def main(argv):
    verify = "--verify" in argv
    reg = registry.load()
    names = [a for a in argv if not a.startswith("--")]
    if "--all" in argv:
        names = [k for k, v in reg.items() if not v["pinned"] and v["available"]]
    bad = 0
    for name in names:
        if name in registry.PINNED:
            print(f"{name}: pinned (always computed live), skipped"); continue
        if free_mb() < MIN_FREE_MB:
            print(f"STOP before {name}: {free_mb():.0f} MB free (< {MIN_FREE_MB})"); return 2
        t0 = time.time()
        a = engine.load_area(name)
        res = engine.scan(a)
        t_scan = time.time() - t0
        p = areacache.save(name, a, res)
        t1 = time.time(); ca, cres = areacache.load(name); t_read = time.time() - t1
        s = reg[name]["survey"]
        survey = {k: s[k] for k in ("red", "amber", "green", "not_assessed") if s[k]}
        line = (f"{name}: scanned in {t_scan:.0f} s; saved {p.stat().st_size / 1e6:.0f} MB; read back in {t_read:.1f} s; "
                f"counts {'= survey' if counts(cres) == survey else f'{counts(cres)} != survey {survey}'}")
        ok = counts(cres) == survey
        if verify:
            diff = areacache.same_results(res, cres) or areacache.same_results(res, engine.scan(ca))
            line += f"; re-scan of the unpickled area {'IDENTICAL' if diff is None else 'DIFFERS: ' + diff}"
            ok = ok and diff is None
            if name == "hrm":
                m1, m2 = engine.mitigate(a, *WESTWOOD), engine.mitigate(ca, *WESTWOOD)
                keys = [k for k in m1 if isinstance(m1[k], (int, float, str, bool))]
                same = json.dumps(m1, sort_keys=True, default=str) == json.dumps(m2, sort_keys=True, default=str)   # whole response
                line += f"; Westwood mitigation fresh vs unpickled {'IDENTICAL' if same else 'DIFFERS'} " \
                        f"({', '.join(f'{k}={m1[k]}' for k in keys[:8])})"
                ok = ok and same
        print(line, flush=True)
        bad += not ok
        del a, res, ca, cres
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
