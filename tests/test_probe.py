"""User-placed blockage ("probe") tests. The probe must reuse the scan's scoring exactly, snap only onto the selected
neighbourhood's own roads / major-road connections, and snap exactly once (server-side, from the raw cursor).
Run: python tests/test_probe.py
"""
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import Point, box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from egress import config, engine, probe, viz  # noqa: E402

STUDY = box(0, 0, 10000, 10000)


def _pts(coords):
    return np.array([Point(c) for c in coords], dtype=object)


def synthetic_parallel():
    """Arterial y=5000 (ends outside the study box). Neighbourhood A: road x=4000 from the arterial north to y=5800.
    Neighbourhood B: a separate road x=4040 (40 m east), from its own arterial junction north to y=5800."""
    node_xy = {100: (-500.0, 5000.0), 101: (4000.0, 5000.0), 102: (4040.0, 5000.0), 103: (10500.0, 5000.0),
               1: (4000.0, 5800.0), 2: (4040.0, 5800.0)}
    roads = [(100, 101, None, "primary"), (101, 102, None, "primary"), (102, 103, None, "primary"),
             (101, 1, None, "residential"), (102, 2, None, "residential")]
    osm = [(3992, 5100 + 20 * k) for k in range(35)] + [(4048, 5100 + 20 * k) for k in range(35)]
    area = engine.build_area("syn", roads, node_xy, STUDY, {"osm": _pts(osm), "ms": _pts([])})
    res = engine.scan(area)
    nb_a = next(nb for nb in engine.neighbourhoods(area) if any({area.edges[i].u, area.edges[i].v} == {101, 1} for i in nb.edge_idx))
    r_a = next(r for r in res if r["nid"] == nb_a.nid)
    return area, r_a


def ll(x, y):
    return engine._TO_LL(x, y)


def centre_xy(d):
    x, y = engine._TO_M(*d["centre"])
    return x, y


def test_synthetic():
    area, r_a = synthetic_parallel()
    # 1. releasing ON the neighbouring road (B, 40 m away) must not snap onto it: it snaps to A's own road (x=4000)
    d = probe.probe(area, r_a, *ll(4040, 5500))
    x, y = centre_xy(d)
    assert d["ok"] and abs(x - 4000) < 0.05 and abs(y - 5500) < 0.05 and abs(d["snap_m"] - 40) < 0.05, (d.get("reason"), x, y)
    # 2. boundary: <= 60 m from an eligible road accepted, > 60 m rejected
    ok = probe.probe(area, r_a, *ll(4059.5, 5500))
    no = probe.probe(area, r_a, *ll(4060.5, 5500))
    assert ok["ok"] and not no["ok"] and no["reason"] == "too_far", (ok.get("snap_m"), no)
    # 3. exact double-snap reproduction: raw cursor 90 m from A, 50 m from B. Old flow: the browser snapped to B
    #    (x=4040), 40 m from A, and the server accepted. The raw cursor is now what is sent -> rejected.
    raw = probe.probe(area, r_a, *ll(4090, 5500))
    assert not raw["ok"] and raw["reason"] == "too_far", raw
    # 4. B's road is not in A's eligible set (except the shared arterial stub near A's gateway)
    elig = probe.eligible_roads(area, probe._nb(area, r_a["nid"]))
    assert elig.distance(Point(4040, 5500)) > 39.9, elig.distance(Point(4040, 5500))
    # 5. returned metadata = the analysed centre: re-evaluating the scan function there gives the same result
    nb = probe._nb(area, r_a["nid"])
    ev = engine.evaluate_block(area, nb, Point(*centre_xy(d)))
    assert (ev["cut_osm"], ev["cut_ms"]) == (d["cut_osm"], d["cut_ms"]), (ev["cut_osm"], d["cut_osm"])
    disc = [f for f in d["geo"]["features"] if f["properties"]["kind"] == "disc"][0]
    ring = np.array([engine._TO_M(*c) for c in disc["geometry"]["coordinates"][0][:-1]])   # drop the closing vertex
    assert abs(ring[:, 0].mean() - centre_xy(d)[0]) < 0.5 and abs(ring[:, 1].mean() - centre_xy(d)[1]) < 0.5
    print("PASS synthetic: neighbouring road never eligible; 60 m boundary; raw-cursor double-snap rejected; "
          "returned centre = analysed centre")


def test_data():
    a = engine.load_area("tantallon")
    res = engine.scan(a)
    before = {r["nid"]: (r["status"], r["worst_cut"], r["worst_cut_osm"], r["worst_cut_ms"]) for r in res}
    r = next(x for x in res if x["nid"] == 99)

    # frozen worst-point equivalence: 234/194 lose, 0/0 inside, 517/486 retain, identical id sets
    d = probe.probe(a, r, *ll(r["choke"].x, r["choke"].y))
    assert d["ok"] and d["snap_m"] < 0.01, d
    assert d["counts"] == {"cut": {"osm": 234, "ms": 194}, "inside": {"osm": 0, "ms": 0},
                           "retain": {"osm": 517, "ms": 486}}, d["counts"]
    cats = viz.categories(a, r)
    for s in engine.SOURCES:
        assert d["ids"][s] == {k: cats["sources"][s][k] for k in ("cut", "inside", "retain")}, s
    print("PASS frozen Westwood worst point: 234/194 lose, 0/0 inside, 517/486 retain, identical building ids")

    nb = probe._nb(a, 99)
    q = a.edges[nb.edge_idx[0]].line.interpolate(0.5, normalized=True)
    d2 = probe.probe(a, r, *ll(q.x + 20, q.y + 15))
    assert d2["ok"] and 0 < d2["snap_m"] <= probe.SNAP_TOL_M, d2
    assert probe.eligible_roads(a, nb).distance(Point(*centre_xy(d2))) < 0.05      # snapped onto an eligible road
    far = probe.probe(a, r, -63.80, 44.80)
    assert not far["ok"] and far["reason"] == "too_far", far
    na = next(x for x in res if x["status"] == "not_assessed")
    assert probe.probe(a, na, *ll(r["choke"].x, r["choke"].y))["reason"] == "not_assessed"
    for s in engine.SOURCES:
        c, i, k = (set(d2["ids"][s][x]) for x in ("cut", "inside", "retain"))
        assert not (c & i or c & k or i & k) and c | i | k == nb.cohort(a)[s], s
    after = {x["nid"]: (x["status"], x["worst_cut"], x["worst_cut_osm"], x["worst_cut_ms"]) for x in engine.scan(a)}
    assert after == before, "scan changed"
    print("PASS data: snaps onto eligible roads; far and not-assessed rejected; disjoint categories; scan unchanged")


if __name__ == "__main__":
    try:
        test_synthetic()
        if config.roads_graphml("tantallon").exists():
            test_data()
        else:
            print("SKIP data tests (prepared data not found)")
        print("ALL PASS")
    except AssertionError as e:
        print(f"FAIL: {e}"); sys.exit(1)
