"""User-placed blockage ("probe") tests (Tantallon data). The probe must reuse the scan's scoring exactly.
Run: python tests/test_probe.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from egress import config, engine, probe, viz  # noqa: E402


def main():
    a = engine.load_area("tantallon")
    res = engine.scan(a)
    before = {r["nid"]: (r["status"], r["worst_cut"], r["worst_cut_osm"], r["worst_cut_ms"]) for r in res}
    r = next(x for x in res if x["nid"] == 99)

    # 1. at the scan's own worst sampled centre the probe reproduces the frozen worst result, ids included
    lon, lat = engine._TO_LL(r["choke"].x, r["choke"].y)
    d = probe.probe(a, r, lon, lat)
    assert d["ok"] and d["snap_m"] < 0.01, d
    assert (d["cut_osm"], d["cut_ms"]) == (234, 194) == (r["worst_cut_osm"], r["worst_cut_ms"]), d
    cats = viz.categories(a, r)
    for s in engine.SOURCES:
        assert d["ids"][s] == {k: cats["sources"][s][k] for k in ("cut", "inside", "retain")}, s
    print("PASS probe at worst sampled centre = scan result (234/194, identical building ids)")

    # 2. a release point off the road snaps onto the neighbourhood's road; far away is rejected, never moved
    nb = probe._nb(a, 99)
    q = a.edges[nb.edge_idx[0]].line.interpolate(0.5, normalized=True)
    d2 = probe.probe(a, r, *engine._TO_LL(q.x + 20, q.y + 15))
    assert d2["ok"] and 0 < d2["snap_m"] <= probe.SNAP_TOL_M, d2
    far = probe.probe(a, r, -63.80, 44.80)
    assert not far["ok"] and far["reason"] == "too_far", far
    na = next(x for x in res if x["status"] == "not_assessed")
    assert probe.probe(a, na, lon, lat)["reason"] == "not_assessed"
    print("PASS snapping onto the neighbourhood's roads; far and not-assessed rejected")

    # 3. categories are disjoint and cover the cohort; the probe changes nothing in the scan
    for s in engine.SOURCES:
        c, i, k = (set(d2["ids"][s][x]) for x in ("cut", "inside", "retain"))
        assert not (c & i or c & k or i & k) and c | i | k == nb.cohort(a)[s], s
    after = {x["nid"]: (x["status"], x["worst_cut"], x["worst_cut_osm"], x["worst_cut_ms"]) for x in engine.scan(a)}
    assert after == before, "scan changed"
    print("PASS disjoint categories covering the cohort; scan unchanged")


if __name__ == "__main__":
    if not config.roads_graphml("tantallon").exists():
        print("SKIP (prepared data not found)"); sys.exit(0)
    try:
        main(); print("ALL PASS")
    except AssertionError as e:
        print(f"FAIL: {e}"); sys.exit(1)
