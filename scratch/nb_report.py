"""Aggregate out/nb_survey/<area>.json into a provincial report (stdout + out/nb_survey/report.md). Read-only."""
import json
import statistics
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "out" / "nb_survey"
ORDER = ["fredericton", "pointe_sapin", "moncton", "saint_john", "quispamsis", "miramichi", "bathurst", "edmundston",
         "campbellton", "woodstock", "grand_falls", "sussex", "shediac", "sackville", "st_stephen", "caraquet", "richibucto"]


def main():
    rows = []
    for a in ORDER:
        f = OUT / f"{a}.json"
        if f.exists():
            rows.append(json.loads(f.read_text(encoding="utf-8")))
    L = []
    P = L.append
    P("# New Brunswick survey: frozen scan on more communities\n")
    P("Parameters (frozen, identical everywhere): 50 m blockage radius, 50 m sampling, neighbourhoods of 30+ mapped "
      "buildings, footprints >= 40 m2, buildings attached to roads within 150 m, not assessed within 2 km of the study-box edge. "
      "Counts are the higher of the OSM and Microsoft estimates (never their sum).\n")
    P("| Area | Mapped bldgs OSM | Microsoft | MS/OSM | Nbhds (30+) | Assessed | Red | Amber | Green | Not assessed | NA share | Box km2 | Assessable km2 | Runtime s | Peak MB |")
    P("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    T = dict(osm=0, ms=0, n=0, assessed=0, red=0, amber=0, green=0, na=0)
    all_nbs = []
    for r in rows:
        c = r["counts"]; red, amber, green, na = (c.get(k, 0) for k in ("red", "amber", "green", "not_assessed"))
        n = r["n_neighbourhoods"]; assessed = n - na
        ratio = r["buildings_ms"] / r["buildings_osm"] if r["buildings_osm"] else float("inf")
        P(f"| {r['area']} | {r['buildings_osm']:,} | {r['buildings_ms']:,} | {ratio:.2f} | {n} | {assessed} | {red} | {amber} | "
          f"{green} | {na} | {na / n:.0%} | {r['box_km2']} | {r['assessable_km2']} | {r['runtime_total_s']:.0f} | {r['peak_mb']} |"
          if n else f"| {r['area']} | {r['buildings_osm']:,} | {r['buildings_ms']:,} | {ratio:.2f} | 0 | 0 | 0 | 0 | 0 | 0 | - | "
          f"{r['box_km2']} | {r['assessable_km2']} | {r['runtime_total_s']:.0f} | {r['peak_mb']} |")
        for k, v in dict(osm=r["buildings_osm"], ms=r["buildings_ms"], n=n, assessed=assessed, red=red, amber=amber,
                         green=green, na=na).items():
            T[k] += v
        for nb in r["neighbourhoods"]:
            all_nbs.append(dict(nb, area=r["area"]))
    P(f"| **Total ({len(rows)} areas)** | **{T['osm']:,}** | **{T['ms']:,}** | {T['ms'] / max(T['osm'], 1):.2f} | **{T['n']}** | "
      f"**{T['assessed']}** | **{T['red']}** | **{T['amber']}** | **{T['green']}** | **{T['na']}** | {T['na'] / max(T['n'], 1):.0%} | | | | |")
    P("")
    P("## Top 10 neighbourhoods province-wide (mapped buildings cut off by the worst sampled blockage)\n")
    P("| # | Area | nid | Status | Cut off (headline) | Cut off OSM / MS | Mapped bldgs OSM / MS | Connections | Choke (lon, lat) |")
    P("|---:|---|---:|---|---:|---|---|---:|---|")
    top = sorted((n for n in all_nbs if n["status"] != "not_assessed"), key=lambda n: -n["worst_cut"])[:10]
    for i, n in enumerate(top, 1):
        P(f"| {i} | {n['area']} | {n['nid']} | {n['status']} | {n['worst_cut']:,} | {n['worst_cut_osm']:,} / {n['worst_cut_ms']:,} | "
          f"{n['homes_osm']:,} / {n['homes_ms']:,} | {n['gateways']} | {n['choke']} |")
    P("")
    P("## Source disagreement (OSM vs Microsoft)\n")
    P("| Area | Box MS/OSM | Assessed nbhds with one source > 3x the other | Median nbhd MS/OSM (assessed) |")
    P("|---|---:|---:|---:|")
    for r in rows:
        ass = [n for n in r["neighbourhoods"] if n["status"] != "not_assessed"]
        big = [n for n in ass if max(n["homes_osm"], n["homes_ms"]) > 3 * max(min(n["homes_osm"], n["homes_ms"]), 1)]
        med = statistics.median([n["homes_ms"] / max(n["homes_osm"], 1) for n in ass]) if ass else float("nan")
        ratio = r["buildings_ms"] / max(r["buildings_osm"], 1)
        flag = " **(>3x)**" if ratio > 3 or ratio < 1 / 3 else ""
        P(f"| {r['area']} | {ratio:.2f}{flag} | {len(big)} of {len(ass)} | {med:.2f} |")
    text = "\n".join(L)
    print(text)
    (OUT / "report.md").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
