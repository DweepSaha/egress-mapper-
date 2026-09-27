"""Fire scenario tests (Tantallon, needs the prepared data). The scenario is a SUPPLIED area, not a spread prediction.
Run: python tests/test_fire.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from egress import config, engine, fire  # noqa: E402

WESTWOOD = 99


def disjoint(s):
    for src in engine.SOURCES:
        c, i, r = (set(s["ids"][src][k]) for k in ("cut", "inside", "retain"))
        assert not (c & i or c & r or i & r), f"{src}: categories overlap"
        assert [len(x) for x in (c, i, r)] == [s["counts"][k][src] for k in ("lose_access", "inside", "keep_access")]


def independent(a, lon, lat, r):
    """The scenario evaluated with an empty cache (no request history)."""
    fire._cache.clear()
    return fire.hypothetical(a, lon, lat, r)


def cache_identity(a):
    """Codex: distinct supplied inputs must never share a cached result; identical inputs must hit the cache."""
    C = (-63.854000, 44.705200)
    # A: radius 300 then 300.49 (and reverse): each equals its independent evaluation
    ind = {r: independent(a, *C, r) for r in (300, 300.49)}
    assert ind[300.49]["radius_m"] == 300.49 and ind[300]["radius_m"] == 300
    for order in ((300, 300.49), (300.49, 300)):
        fire._cache.clear()
        got = {r: fire.hypothetical(a, *C, r) for r in order}
        for r in order:
            assert got[r] == ind[r], f"A order {order}: radius {r} differs from its independent result"
    differs_a = ind[300] != ind[300.49]
    # B: radius 300 at two centres 0.000004 deg apart (and reverse)
    P1, P2 = (-63.854004, 44.705200), (-63.854000, 44.705200)
    ind = {P: independent(a, *P, 300) for P in (P1, P2)}
    assert ind[P1]["centre"] == list(P1) and ind[P2]["centre"] == list(P2)
    for order in ((P1, P2), (P2, P1)):
        fire._cache.clear()
        got = {P: fire.hypothetical(a, *P, 300) for P in order}
        for P in order:
            assert got[P] == ind[P], f"B order {order}: centre {P} differs from its independent result"
    differs_b = ind[P1] != ind[P2]
    # identical requests hit the cache: same object, identical response
    fire._cache.clear()
    n0 = len(fire._cache)
    x, y = fire.hypothetical(a, *C, 300), fire.hypothetical(a, *C, 300)
    assert x is y and len(fire._cache) == n0 + 1, "identical request missed the cache"
    # out-of-range / non-finite inputs are rejected, never silently adjusted
    for bad in ((C[0], C[1], 49.9), (C[0], C[1], 3000.1), (float("nan"), C[1], 300), (C[0], C[1], float("inf"))):
        try:
            fire.hypothetical(a, *bad); raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass
    return differs_a, differs_b


def main():
    a = engine.load_area("tantallon")
    before = {r["nid"]: (r["status"], r["worst_cut"]) for r in engine.scan(a)}

    h = fire.historical(a)
    assert abs(h["zone_ha"] - h["perimeter"]["mapped_ha"]) < 5, (h["zone_ha"], h["perimeter"]["mapped_ha"])
    ents = h["westwood_entrances"]
    assert all(not e["inside"] for e in ents), "entrances must lie outside the mapped perimeter"
    assert sorted(e["distance_m"] for e in ents) == [955, 1220] or all(900 < e["distance_m"] < 1300 for e in ents), ents
    assert h["roads_affected_km"] > 0 and h["counts"]["inside"]["osm"] > 0
    disjoint(h)
    print(f"PASS historical: {h['zone_ha']} ha; entrances {[e['distance_m'] for e in ents]} m outside; "
          f"roads {h['roads_affected_km']} km; lose {h['counts']['lose_access']}; inside {h['counts']['inside']}")

    # tiny area far from any road: nothing affected
    far = fire.hypothetical(a, -63.80, 44.80, 50)
    assert far["counts"]["lose_access"] == {"osm": 0, "ms": 0}, far["counts"]
    # growing circles at one point: roads affected and inside counts never shrink
    prev = None
    for r in (100, 300, 600, 1200):
        s = fire.hypothetical(a, -63.8545, 44.7052, r)
        disjoint(s)
        if prev:
            assert s["roads_affected_km"] >= prev["roads_affected_km"]
            assert all(s["counts"]["inside"][k] >= prev["counts"]["inside"][k] for k in engine.SOURCES)
        prev = s
    # a circle on Westwood's shared entrance area cuts the subdivision off (buildings outside the circle lose access)
    s = fire.hypothetical(a, -63.8540, 44.7052, 300)
    assert s["headline"]["lose_access"] >= 30, s["counts"]
    print(f"PASS hypothetical: monotonic growth, disjoint categories; 300 m at the entrances -> lose {s['counts']['lose_access']}")

    da, db = cache_identity(a)
    print(f"PASS cache identity: A (300 vs 300.49 m, both orders) and B (centres 0.000004 deg apart, both orders) "
          f"equal their independent results; independent results differ: A={da}, B={db}; identical requests hit cache")

    after = {r["nid"]: (r["status"], r["worst_cut"]) for r in engine.scan(a)}
    assert before == after, "baseline scan changed"
    assert before[WESTWOOD][0] == "red"
    print("PASS baseline scan unchanged (Westwood still red)")


def fredericton_hypothetical(tan):
    """Hypothetical fire is area-agnostic: Fredericton at Codex's reference point, never mixed with Tantallon."""
    fr = engine.load_area("fredericton")
    f = fire.hypothetical(fr, -66.645, 45.958, 500)
    t = fire.hypothetical(tan, -66.645, 45.958, 500)            # same inputs, other area: must be its own result
    disjoint(f)
    assert f["roads_affected_km"] > 0 and f["counts"]["inside"]["osm"] > 0, f["counts"]
    assert t["roads_affected_km"] == 0 and t is not f, (t["roads_affected_km"],)
    print(f"PASS Fredericton hypothetical r=500 m at [-66.645, 45.958]: roads {f['roads_affected_km']} km, "
          f"lose {f['counts']['lose_access']}, inside {f['counts']['inside']}; same inputs in Tantallon -> 0 km (no cross-area mixing)")


if __name__ == "__main__":
    if not config.roads_graphml("tantallon").exists() or not fire.NBAC_PATH.exists():
        print("SKIP (prepared data not found)"); sys.exit(0)
    try:
        main()
        if config.roads_graphml("fredericton").exists():
            fredericton_hypothetical(engine.load_area("tantallon"))
        print("ALL PASS")
    except AssertionError as e:
        print(f"FAIL: {e}"); sys.exit(1)
