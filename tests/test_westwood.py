"""Data-backed regression: the independently verified Westwood Hills result (Codex Phase 3 audit).
Needs the prepared data (EGRESS_DATA); skipped otherwise. Run: python tests/test_westwood.py

Exact demo proposal (unchanged): road=-63.87399,44.72806,-63.85501,44.70479
(snaps to nodes 845467323 -> 5546361430).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from egress import config, engine  # noqa: E402

A, B = (-63.87399, 44.72806), (-63.85501, 44.70479)


def test_westwood_verified_result():
    area = engine.load_area("tantallon")
    ww = next(r for r in engine.scan(area) if r["nid"] == 99)
    assert (ww["homes_osm"], ww["homes_ms"]) == (751, 680), ww
    assert (ww["worst_cut_osm"], ww["worst_cut_ms"]) == (234, 194), ww
    assert ww["status"] == "red" and ww["gateways"] == 2
    assert (engine._snap(area, A), engine._snap(area, B)) == (845467323, 5546361430)
    r = engine.mitigate(area, A, B)
    assert r["ok"] and not r["unavailable"], r
    assert r["before_cut_src"] == {"osm": 234, "ms": 194}, r["before_cut_src"]
    assert r["same_block_cut_src"] == {"osm": 1, "ms": 1}, r["same_block_cut_src"]
    assert r["regained_src"] == {"osm": 233, "ms": 193} and r["regained"] == 233, r["regained_src"]
    assert r["after"]["worst_cut_src"] == {"osm": 53, "ms": 35} and r["after"]["worst_cut"] == 53, r["after"]
    props = r["after_geo"]["neighbourhoods"]["features"][0]["properties"]
    assert (props["homes_osm"], props["homes_ms"], props["worst_cut_osm"], props["worst_cut_ms"]) == (751, 680, 53, 35), props


if __name__ == "__main__":
    if not config.roads_graphml("tantallon").exists():
        print("SKIP test_westwood_verified_result (prepared data not found)")
        sys.exit(0)
    try:
        test_westwood_verified_result()
        print("PASS test_westwood_verified_result")
    except AssertionError as e:
        print(f"FAIL test_westwood_verified_result: {e}")
        sys.exit(1)
