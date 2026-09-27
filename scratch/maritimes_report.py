"""Combined Maritimes report from out/nb_survey/*.json + out/maritimes/*.json (read-only).

Totals exclude the separate Tantallon validation run (the HRM box covers it). Westwood is located inside the HRM run by
its scan choke point; names come from the nearest OSM place point. Negative controls: Fredericton neighbourhoods found
by location with the frozen engine (read-only) and named the same way.
"""
import json
import math
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
OUT_NB, OUT_M = REPO / "out" / "nb_survey", REPO / "out" / "maritimes"
DATA = REPO.parent / "hackatlantic-prep" / "data" / "osm"
PROV = {}
for a in ["fredericton", "pointe_sapin", "moncton", "saint_john", "quispamsis", "miramichi", "bathurst", "edmundston",
          "campbellton", "woodstock", "grand_falls", "sussex", "shediac", "sackville", "st_stephen", "caraquet", "richibucto"]:
    PROV[a] = "NB"
for a in ["hrm", "cbrm", "truro", "new_glasgow", "kentville", "amherst", "bridgewater", "yarmouth", "antigonish", "chester"]:
    PROV[a] = "NS"
for a in ["charlottetown", "summerside", "montague"]:
    PROV[a] = "PEI"
WESTWOOD_CHOKE = (-63.878859695, 44.725371840)     # Westwood Hills worst sampled centre (Tantallon validation run)


def load():
    rows = {}
    for d in (OUT_NB, OUT_M):
        for f in d.glob("*.json"):
            rows[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return rows


def dist_m(a, b):
    kx = 111320 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * 110540)


_places = None


def place_name(ll):
    global _places
    if _places is None:
        import geopandas as gpd
        frames = []
        for p in ("new-brunswick", "nova-scotia", "prince-edward-island"):
            g = gpd.read_file(DATA / f"{p}.gpkg", layer="gis_osm_places_free")
            frames.append(g[g["fclass"].isin(["city", "town", "village", "suburb", "hamlet", "locality", "neighbourhood"])])
        import pandas as pd
        _places = pd.concat(frames, ignore_index=True)   # unique labels: idxmin must return ONE place
        _places["lon"], _places["lat"] = _places.geometry.x, _places.geometry.y
    d = ((_places["lon"] - ll[0]) * 111320 * math.cos(math.radians(ll[1]))) ** 2 + ((_places["lat"] - ll[1]) * 110540) ** 2
    r = _places.loc[d.idxmin()]
    return f"{r['name']} ({math.sqrt(d.min()) / 1000:.1f} km)"


def area_table(rows, names, P):
    P("| Area | Prov | Mapped bldgs OSM | Microsoft | MS/OSM | Nbhds (30+) | Assessed | Red | Amber | Green | Not assessed | NA share | Assessable/box km2 | Runtime s | Peak MB |")
    P("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|")
    T = dict(osm=0, ms=0, n=0, assessed=0, red=0, amber=0, green=0, na=0)
    for a in names:
        r = rows[a]; c = r["counts"]
        red, amber, green, na = (c.get(k, 0) for k in ("red", "amber", "green", "not_assessed"))
        n = r["n_neighbourhoods"]; assessed = n - na
        ratio = r["buildings_ms"] / max(r["buildings_osm"], 1)
        flag = " **>3x**" if ratio > 3 or ratio < 1 / 3 else ""
        P(f"| {a} | {PROV.get(a, '?')} | {r['buildings_osm']:,} | {r['buildings_ms']:,} | {ratio:.2f}{flag} | {n} | {assessed} | {red} | "
          f"{amber} | {green} | {na} | {(na / n if n else 0):.0%} | {r['assessable_km2']}/{r['box_km2']} | {r['runtime_total_s']:.0f} | {r['peak_mb']} |")
        for k, v in dict(osm=r["buildings_osm"], ms=r["buildings_ms"], n=n, assessed=assessed, red=red, amber=amber, green=green, na=na).items():
            T[k] += v
    return T


def total_row(label, T, P):
    P(f"| **{label}** | | **{T['osm']:,}** | **{T['ms']:,}** | {T['ms'] / max(T['osm'], 1):.2f} | **{T['n']}** | **{T['assessed']}** | "
      f"**{T['red']}** | **{T['amber']}** | **{T['green']}** | **{T['na']}** | {T['na'] / max(T['n'], 1):.0%} | | | |")


def main():
    rows = load()
    L = []; P = L.append
    included = [a for a in PROV if a in rows]
    missing = [a for a in PROV if a not in rows]
    P("# Maritimes survey: the frozen scan on New Brunswick, Nova Scotia and PEI\n")
    P("Frozen parameters everywhere: 50 m blockage radius, 50 m sampling, 30+ mapped buildings, footprints >= 40 m2, "
      "150 m road assignment, 2 km boundary exclusion. Counts: the higher of OSM and Microsoft, never their sum. "
      "The separate Tantallon validation run is NOT in the totals (the HRM box covers it).\n")
    if missing:
        P(f"**Not completed (skipped or failed): {', '.join(missing)}**\n")
    tot = {}
    for prov in ("NB", "NS", "PEI"):
        names = [a for a in included if PROV[a] == prov]
        if not names:
            continue
        P(f"## {prov}\n")
        T = area_table(rows, names, P)
        total_row(f"{prov} total ({len(names)} areas)", T, P)
        tot[prov] = T
        P("")
    G = {k: sum(t[k] for t in tot.values()) for k in next(iter(tot.values()))}
    P("## Maritimes combined\n")
    P("| Province | Areas | Mapped bldgs OSM | Microsoft | Nbhds (30+) | Assessed | Red | Amber | Not assessed |")
    P("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for prov, T in tot.items():
        P(f"| {prov} | {sum(1 for a in included if PROV[a] == prov)} | {T['osm']:,} | {T['ms']:,} | {T['n']} | {T['assessed']} | {T['red']} | {T['amber']} | {T['na']} |")
    P(f"| **Maritimes** | **{len(included)}** | **{G['osm']:,}** | **{G['ms']:,}** | **{G['n']}** | **{G['assessed']}** | **{G['red']}** | **{G['amber']}** | **{G['na']}** |\n")

    all_nbs = [dict(nb, area=a) for a in included for nb in rows[a]["neighbourhoods"]]
    ranked = sorted((n for n in all_nbs if n["status"] != "not_assessed" and n["worst_cut"] > 0), key=lambda n: -n["worst_cut"])
    P("## Top 10 neighbourhoods across the Maritimes (mapped buildings cut off by the worst sampled blockage)\n")
    P("| # | Area | nid | Near | Cut off (headline) | Cut off OSM / MS | Mapped bldgs OSM / MS | Connections | Choke (lon, lat) |")
    P("|---:|---|---:|---|---:|---|---|---:|---|")
    for i, n in enumerate(ranked[:10], 1):
        P(f"| {i} | {n['area']} | {n['nid']} | {place_name(n['choke'])} | {n['worst_cut']:,} | {n['worst_cut_osm']:,} / {n['worst_cut_ms']:,} | "
          f"{n['homes_osm']:,} / {n['homes_ms']:,} | {n['gateways']} | {n['choke']} |")
    P("")

    # ---- Westwood Hills inside the HRM run
    P("## Westwood Hills: typical or outlier?\n")
    if "hrm" in rows:
        hrm = rows["hrm"]["neighbourhoods"]
        cand = sorted((n for n in hrm if n["choke"]), key=lambda n: dist_m(n["choke"], WESTWOOD_CHOKE))
        ww = cand[0] if cand and dist_m(cand[0]["choke"], WESTWOOD_CHOKE) < 50 else None
        if ww is None:   # fall back: the HRM neighbourhood with the rehearsed cohort
            ww = next((n for n in hrm if n["homes_osm"] == 751 and n["homes_ms"] == 680), None)
        tan = rows.get("tantallon")
        twr = next((n for n in tan["neighbourhoods"] if n["nid"] == 99), None) if tan else None
        if twr:
            P(f"- Tantallon validation run (unchanged): nid 99, cohort {twr['homes_osm']}/{twr['homes_ms']}, worst sampled blockage "
              f"{twr['worst_cut_osm']}/{twr['worst_cut_ms']}, {twr['gateways']} connections, status {twr['status']}.")
        if ww:
            hr = sorted((n for n in hrm if n["status"] != "not_assessed" and n["worst_cut"] > 0), key=lambda n: -n["worst_cut"])
            r_hrm = next(i for i, n in enumerate(hr, 1) if n["nid"] == ww["nid"])
            r_all = next(i for i, n in enumerate(ranked, 1) if n["area"] == "hrm" and n["nid"] == ww["nid"])
            hrm_red = sum(1 for n in hrm if n["status"] == "red")
            P(f"- Same neighbourhood inside the HRM run: nid {ww['nid']}, cohort {ww['homes_osm']}/{ww['homes_ms']}, worst sampled blockage "
              f"{ww['worst_cut_osm']}/{ww['worst_cut_ms']} (headline {ww['worst_cut']}), {ww['gateways']} connections, status {ww['status']}, "
              f"choke {ww['choke']} ({dist_m(ww['choke'], WESTWOOD_CHOKE):.0f} m from the Tantallon run's).")
            P(f"- **Rank within HRM: {r_hrm} of {len(hr)}** assessed neighbourhoods with any cut-off ({hrm_red} red in HRM).")
            P(f"- **Rank across the Maritimes: {r_all} of {len(ranked)}** ({G['red']} red in total).")
            above = [n for n in ranked[:r_all - 1]]
            P(f"- Neighbourhoods ranked above it: " + "; ".join(f"{n['area']} nid {n['nid']} near {place_name(n['choke'])} ({n['worst_cut']})" for n in above[:12]) +
              (" ..." if len(above) > 12 else ""))
            pct = 100 * (1 - (r_all - 1) / max(len(ranked), 1))
            P(f"- Percentile among neighbourhoods with any cut-off: top {100 - pct + 100 / len(ranked):.1f}%.")
        else:
            P("- Westwood not matched in the HRM run (see candidates): " + "; ".join(
                f"nid {n['nid']} {n['homes_osm']}/{n['homes_ms']} cut {n['worst_cut']} at {dist_m(n['choke'], WESTWOOD_CHOKE):.0f} m" for n in cand[:5]))
    P("")

    # ---- source disagreement + not assessed
    P("## Coverage caveats\n")
    P("| Area | Prov | Box MS/OSM | Assessed nbhds with one source > 3x the other | Median nbhd MS/OSM | Not assessed |")
    P("|---|---|---:|---:|---:|---:|")
    for a in included:
        r = rows[a]
        ass = [n for n in r["neighbourhoods"] if n["status"] != "not_assessed"]
        big = [n for n in ass if max(n["homes_osm"], n["homes_ms"]) > 3 * max(min(n["homes_osm"], n["homes_ms"]), 1)]
        med = statistics.median([n["homes_ms"] / max(n["homes_osm"], 1) for n in ass]) if ass else float("nan")
        ratio = r["buildings_ms"] / max(r["buildings_osm"], 1)
        na = r["counts"].get("not_assessed", 0)
        P(f"| {a} | {PROV[a]} | {ratio:.2f}{' **>3x**' if ratio > 3 or ratio < 1 / 3 else ''} | {len(big)} of {len(ass)} | {med:.2f} | "
          f"{na} of {r['n_neighbourhoods']} ({(na / r['n_neighbourhoods'] if r['n_neighbourhoods'] else 0):.0%}) |")
    text = "\n".join(L)
    print(text)
    (OUT_M / "report.md").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
