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

    after = {r["nid"]: (r["status"], r["worst_cut"]) for r in engine.scan(a)}
    assert before == after, "baseline scan changed"
    assert before[WESTWOOD][0] == "red"
    print("PASS baseline scan unchanged (Westwood still red)")


if __name__ == "__main__":
    if not config.roads_graphml("tantallon").exists() or not fire.NBAC_PATH.exists():
        print("SKIP (prepared data not found)"); sys.exit(0)
    try:
        main(); print("ALL PASS")
    except AssertionError as e:
        print(f"FAIL: {e}"); sys.exit(1)
