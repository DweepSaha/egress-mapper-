"""Regression tests for the Codex audit failures (engine-v1-audit). Synthetic networks, no data files needed.
Run: python tests/test_engine.py   (or: python -m pytest tests)

Layout used throughout (EPSG:2953-like metres): study box 0..10000 x 0..10000, assessable interior 2000..8000.
A through arterial runs along y=5000 from x=-500 to x=10500 (both ends outside the study box, so the spur rule keeps
it as a genuine way out). Local roads hang off arterial junctions.
"""
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, Point, box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from egress import engine  # noqa: E402

STUDY = box(0, 0, 10000, 10000)


def arterial(xs):
    """Arterial nodes along y=5000 at the given x positions (ids 100, 101, ...); returns (node_xy, roads)."""
    node_xy = {100 + i: (x, 5000.0) for i, x in enumerate(xs)}
    ids = list(node_xy)
    roads = [(a, b, None, "primary") for a, b in zip(ids, ids[1:])]
    return node_xy, roads


def pts(coords):
    return np.array([Point(c) for c in coords], dtype=object)


def nb_with_edge(area, u, v):
    return next(nb for nb in engine.neighbourhoods(area)
                if any({area.edges[i].u, area.edges[i].v} == {u, v} for i in nb.edge_idx))


# ------------------------------------------------------------------ Codex failure 1: mitigation comparison
def test_mitigation_uses_original_cohort_and_source_specific_counts():
    """Before the fix: regained = max(before) - max(after) mixed sources (40 - 40 = 0) although 30 Microsoft
    buildings regain access; and the reported neighbourhood was the largest touched one, not the original."""
    node_xy, roads = arterial([-500, 4000, 6000, 10500])       # 101 = G1 (4000), 102 = G2 (6000)
    node_xy.update({1: (4000, 5400), 2: (4000, 5800), 3: (4400, 5400)})   # J, K (dead end), E (dead end)
    roads += [(101, 1, None, "residential"), (1, 2, None, "residential"), (1, 3, None, "residential")]
    # a big unrelated neighbourhood also hanging off G2 (must never be reported as the mitigation result)
    node_xy.update({4: (6000, 4400)})
    roads += [(102, 4, None, "residential")]
    osm = [(3980, 5450 + 8 * k) for k in range(40)]                        # 40 on J-K
    ms = [(4070 + 10 * k, 5420) for k in range(30)] + [(3980, 5500 + 50 * k) for k in range(5)]   # 30 on J-E, 5 on J-K
    ms += [(6020, 4450 + 5 * k) for k in range(100)]                       # 100 on G2-4 (unrelated)
    area = engine.build_area("t", roads, node_xy, STUDY, {"osm": pts(osm), "ms": pts(ms)})

    r = engine.mitigate_nodes(area, 3, 102, choke=Point(4000, 5400))      # new road E -> G2; block at J
    assert r["ok"] and not r["unavailable"], r
    assert r["before_cut_src"] == {"osm": 40, "ms": 35}, r["before_cut_src"]
    assert r["same_block_cut_src"] == {"osm": 40, "ms": 5}, r["same_block_cut_src"]
    assert r["regained_src"] == {"osm": 0, "ms": 30}, r["regained_src"]
    assert r["regained"] == 30, r["regained"]                              # old code: 40 - 40 = 0
    assert r["before"]["homes"] == 40                                      # the original neighbourhood, not the 100


def test_mitigation_unavailable_when_result_not_assessed():
    """If the proposed road merges the neighbourhood with roads outside the assessable interior, report unavailable
    (old code would silently report a number)."""
    node_xy, roads = arterial([-500, 4000, 10500])
    node_xy.update({1: (4000, 5600), 2: (1500, 5600), 3: (1500, 5900)})    # 2, 3 lie in the 2 km boundary band
    roads += [(101, 1, None, "residential"), (2, 3, None, "residential")]
    osm = [(3980, 5100 + 12 * k) for k in range(40)]
    area = engine.build_area("t", roads, node_xy, STUDY, {"osm": pts(osm), "ms": pts([])})
    r = engine.mitigate_nodes(area, 1, 2)
    assert r["ok"] and r["unavailable"] is True, r
    assert "regained" not in r


# ------------------------------------------------------------------ Codex failure 2: physical incident membership
def test_in_block_is_physical_centroid_in_circle():
    node_xy, roads = arterial([-500, 4000, 10500])
    node_xy.update({1: (4000, 5600)})
    roads += [(101, 1, None, "residential")]
    # A: 120 m from the road, attached inside the blocked stretch, centroid OUTSIDE the circle -> cut off
    # B: centroid inside a circle that does not touch the road -> in the blocked area, not cut off
    area = engine.build_area("t", roads, node_xy, STUDY, {"osm": pts([(4120, 5300), (4040, 5100)]), "ms": pts([])})
    nb = nb_with_edge(area, 101, 1)
    ra = engine.evaluate_block(area, nb, Point(4000, 5300))
    assert ra["cut_osm"] == 1 and ra["inside"] == 0, ra                  # old code: A counted "inside", not cut
    rb = engine.evaluate_block(area, nb, Point(4075, 5100))
    assert rb["cut_osm"] == 0 and rb["inside"] == 1, rb                  # old code: inside = 0


# ------------------------------------------------------------------ Codex failure 3: winding road, several stretches
def test_winding_road_keeps_separate_blocked_intervals():
    node_xy, roads = arterial([-500, 4000, 4080, 10500])                 # 101 = G1, 102 = K
    u_road = LineString([(4000, 5000), (4000, 5600), (4080, 5600), (4080, 5000)])
    roads += [(101, 102, u_road, "residential")]
    circle = Point(4040, 5300).buffer(engine.BLOCK_RADIUS_M)
    ivs = engine._blocked_intervals(u_road, circle)
    assert len(ivs) == 2, ivs                                            # old code: one min->max interval
    # M on the top of the U (between the two blocked stretches) -> trapped; W and Z reach G1 / K
    osm = [(4040, 5620), (3980, 5100), (4100, 5150)]
    area = engine.build_area("t", roads, node_xy, STUDY, {"osm": pts(osm), "ms": pts([])})
    r = engine.evaluate_block(area, nb_with_edge(area, 101, 102), Point(4040, 5300))
    assert r["cut_osm"] == 1 and r["cut_ids"]["osm"] == {0}, r           # old code: M counted "inside", cut = 0


def test_retraced_road_gets_each_traversal_position():
    """Codex adversarial case: a road that goes out and retraces the same physical stretch. line.project() returns
    only the first pass, so the second traversal's blocked stretch was mislocated."""
    # G1 (4000,5000) -> up to (4000,5600) -> back down the SAME line to (4000,5300) -> east to (4400,5300)
    line = LineString([(4000, 5000), (4000, 5600), (4000, 5300), (4400, 5300)])
    circle = Point(4000, 5450).buffer(engine.BLOCK_RADIUS_M)
    ivs = [(round(a), round(b)) for a, b in engine._blocked_intervals(line, circle)]
    assert ivs == [(400, 500), (700, 800)], ivs                          # old code: [(400, 500)] only


# ------------------------------------------------------------------ Codex failure 4: roads between two junctions
def test_local_roads_between_junctions_and_loops_are_kept():
    node_xy, roads = arterial([-500, 4000, 4200, 6000, 10500])           # 101, 102 junctions; 103 = G3
    roads += [(101, 102, LineString([(4000, 5000), (4000, 5300), (4200, 5300), (4200, 5000)]), "residential")]
    loop = LineString([(6000, 5000), (6000, 5300), (6150, 5300), (6150, 5150), (6000, 5000)])
    roads += [(103, 103, loop, "residential")]
    osm = [(4100, 5320 + 0 * k) for k in range(1)] + [(3980, 5100 + 40 * k) for k in range(4)]   # 5 on the U
    osm += [(6170, 5200 + 20 * k) for k in range(3)]                                             # 3 on the loop
    area = engine.build_area("t", roads, node_xy, STUDY, {"osm": pts(osm), "ms": pts([])})
    nbs = engine.neighbourhoods(area)
    counted = sum(nb.homes["osm"] for nb in nbs)
    assert counted == 8 == area.stats["osm"]["attached"] - area.stats["osm"]["on_exit_roads"], counted
    loop_nb = nb_with_edge(area, 103, 103)
    assert loop_nb.gateways == {103}
    # the loop attaches at one junction only: blocking it cuts off all 3 loop buildings
    r = engine.evaluate_block(area, loop_nb, Point(6000, 5000))
    assert r["cut_osm"] == 3, r


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    print(f"{'ALL PASS' if not fails else f'{fails} FAILED'}")
    sys.exit(1 if fails else 0)
