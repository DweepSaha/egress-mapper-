"""READ-ONLY validation: mapped-building counts vs each province's civic address points. Changes nothing.

Civic addresses are NOT buildings (vacant serviced lots can carry one, a multi-unit building may carry one, outbuildings
carry none). NS and NB maintain their files independently; they are not one series.

Two per-neighbourhood assignments are reported:
  * attach  - each address point attached to its nearest road segment within engine.MAX_ASSIGN_M (150 m), i.e. the
              same rule the engine uses for mapped buildings -> like-for-like with the OSM/Microsoft cohort counts;
  * footprint - points inside the engine's neighbourhood geometry (the 40 m road buffer it produces for display).
Neighbourhoods are the frozen engine's own (engine.scan); nothing is re-derived.
Run: python scratch/civic_address_check.py [ns|nb|all]
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyogrio
import shapely
from pyproj import Transformer

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from egress import config, engine  # noqa: E402

CIVIC = config.DATA / "civic"
NS_FILE = CIVIC / "nscaf_tantallon_bbox.geojson"
NB_ZIP = CIVIC / "geonb_anb_fgdb.zip"
TO_M = Transformer.from_crs("EPSG:4326", config.ANALYSIS_CRS, always_xy=True).transform
FEATURED = {"tantallon": 99}      # Westwood Hills


def study_box_m(name):
    lon0, lat0, lon1, lat1 = engine.STUDY_BBOX[name]
    xs, ys = zip(*[TO_M(x, y) for x, y in ((lon0, lat0), (lon0, lat1), (lon1, lat0), (lon1, lat1))])
    return shapely.box(min(xs), min(ys), max(xs), max(ys)), shapely.Polygon(
        [TO_M(lon0, lat0), TO_M(lon1, lat0), TO_M(lon1, lat1), TO_M(lon0, lat1)])


def load_ns():
    g = gpd.read_file(NS_FILE).to_crs(config.ANALYSIS_CRS)            # portal export is WGS84 -> EPSG:2953
    g["kind"] = g["add_loc"].fillna("(not tagged)")
    return {"tantallon": g}


def nb_layer():
    path = f"/vsizip/{NB_ZIP.as_posix()}/geonb_anb.gdb"
    layers = pyogrio.list_layers(path)
    return path, layers


def load_nb():
    path, layers = nb_layer()
    layer = "geonb_anb_addresses"          # civic addresses (units are in geonb_anb_subaddresses, not counted here)
    out = {}
    for name in ("fredericton", "pointe_sapin"):
        env, _ = study_box_m(name)
        info = pyogrio.read_info(path, layer=layer)
        crs = info.get("crs")
        bbox = env.bounds
        if crs and "2953" not in str(crs):
            lon0, lat0, lon1, lat1 = engine.STUDY_BBOX[name]
            bbox = (lon0, lat0, lon1, lat1)
        g = gpd.read_file(path, layer=layer, bbox=bbox)
        out[name] = g.to_crs(config.ANALYSIS_CRS) if g.crs else g.set_crs(config.ANALYSIS_CRS)
    return out, layer


def compare(name, civ: gpd.GeoDataFrame, P, kind_col=None, resid_mask=None):
    area = engine.load_area(name)
    results = engine.scan(area)
    nbs = {nb.nid: nb for nb in engine.neighbourhoods(area)}
    _, study = study_box_m(name)
    civ = civ[civ.geometry.within(study)].copy()
    P(f"- Civic points inside the study box: **{len(civ):,}** "
      f"(mapped buildings >= {engine.MIN_HOME_M2:.0f} m2 in the same box: OSM {len(area.bld['osm']['pts']):,}, "
      f"Microsoft {len(area.bld['ms']['pts']):,})")
    if kind_col:
        P(f"- By `{kind_col}`: " + ", ".join(f"{k} {v:,}" for k, v in Counter(civ[kind_col]).most_common()))
    # like-for-like attachment: nearest road segment within 150 m (same rule as buildings)
    pts = np.array(civ.geometry.values)
    ei, di = area.edge_tree.query_nearest(pts, max_distance=engine.MAX_ASSIGN_M, return_distance=True)
    edge_of = np.full(len(pts), -1)
    edge_of[ei[0]] = ei[1]
    nb_of_edge = {i: nid for nid, nb in nbs.items() for i in nb.edge_idx}
    civ["nid"] = [nb_of_edge.get(int(e), -1) if e >= 0 else -1 for e in edge_of]
    P(f"- Attached to a road within {engine.MAX_ASSIGN_M:.0f} m: {int((edge_of >= 0).sum()):,}; "
      f"not attached (>150 m from any road): {int((edge_of < 0).sum()):,}")
    rows = []
    for r in results:
        foot = r["geometry"]
        inside = civ[civ.geometry.within(foot)]
        att = civ[civ["nid"] == r["nid"]]
        row = dict(nid=r["nid"], status=r["status"], osm=r["homes_osm"], ms=r["homes_ms"], att=len(att), foot=len(inside))
        if resid_mask is not None:
            row["att_res"] = int(resid_mask(att).sum())
        if kind_col:
            row["att_kind"] = Counter(att[kind_col])
        rows.append(row)
    return area, results, rows, civ


def fmt_row(r, resid):
    s = (f"| {r['nid']} | {r['status']} | {r['osm']:,} | {r['ms']:,} | **{r['att']:,}** | {r['foot']:,} |")
    if resid:
        s += f" {r['att_res']:,} |"
    return s


def table(rows, P, resid=False, top=15):
    hdr = "| nid | status | OSM mapped bldgs | Microsoft mapped bldgs | civic (attach, like-for-like) | civic (in 40 m footprint) |"
    P(hdr + (" civic residential (attach) |" if resid else ""))
    P("|" + "---|" * (6 + (1 if resid else 0)))
    for r in sorted(rows, key=lambda r: -max(r["osm"], r["ms"]))[:top]:
        P(fmt_row(r, resid))


def ratios(rows, P):
    a = [r for r in rows if r["status"] != "not_assessed" and max(r["osm"], r["ms"]) >= 30]
    if not a:
        return
    osm = np.array([r["osm"] for r in a]); ms = np.array([r["ms"] for r in a]); cv = np.array([r["att"] for r in a])
    P(f"- Across {len(a)} assessed neighbourhoods: civic/OSM median {np.median(cv / np.maximum(osm, 1)):.2f}, "
      f"civic/Microsoft median {np.median(cv / np.maximum(ms, 1)):.2f}; civic between OSM and Microsoft in "
      f"{int(((cv >= np.minimum(osm, ms)) & (cv <= np.maximum(osm, ms))).sum())} of {len(a)}")


def main(which):
    out = ["# Civic address cross-check (read-only validation)", "",
           "Mapped-building counts compared with each province's own civic address points. Addresses are not buildings; "
           "NS and NB files are maintained independently and are not one series. Neighbourhoods are the frozen engine's own.", ""]
    P = out.append
    if which in ("ns", "all"):
        P("## Nova Scotia - NSCAF Civic Points (Upper Tantallon)")
        P("Source: Service Nova Scotia, *Nova Scotia Civic Address File - Civic Points* (data.novascotia.ca tntn-er5g), "
          "rows updated 2026-09-05 (monthly), Nova Scotia Open Government Licence. Exported WGS84; reprojected to EPSG:2953. "
          "Downloaded with the portal's within_box filter on the study box.")
        P("Attributes: pntid, segid, civicnum, civsuffix, unit_num, add_loc, strprefix/strname/strsuffix/strdir, comm_id, comm, "
          "mun, county, lat, long. **No residential/commercial (land-use) attribute.** `add_loc` records how the point was "
          "placed (building centroid vs approximate parcel location, utility, fire water source ...).")
        civ = load_ns()["tantallon"]
        is_bld = lambda g: g["kind"].isin(["Building Centroid", "Building Entrance", "Address Location for Multi-Unit"])
        area, results, rows, civ = compare("tantallon", civ, P, kind_col="kind", resid_mask=None)
        P(f"- unit_num populated: {int(civ['unit_num'].notna().sum())} (one point per civic number; units are not listed)")
        ww = next(r for r in rows if r["nid"] == 99)
        wb = int(is_bld(civ[civ["nid"] == 99]).sum())
        P("")
        P("### WESTWOOD HILLS (nid 99)")
        P(f"- **OSM 751 | Microsoft 680 | NS civic addresses {ww['att']:,}** (attached like-for-like; "
          f"{wb:,} of them placed at a building centroid/entrance) | inside the 40 m footprint: {ww['foot']:,}")
        P(f"- By placement: " + ", ".join(f"{k} {v}" for k, v in ww["att_kind"].most_common()))
        lo, hi = min(ww["osm"], ww["ms"]), max(ww["osm"], ww["ms"])
        pos = "between Microsoft and OSM" if lo <= ww["att"] <= hi else ("above both" if ww["att"] > hi else "below both")
        P(f"- The province's count falls **{pos}**.")
        P("")
        P("### Largest Tantallon neighbourhoods")
        table(rows, P)
        ratios(rows, P)
        P("")
    if which in ("nb", "all"):
        P("## New Brunswick - Address NB Civic Address Database (Fredericton, Pointe-Sapin)")
        try:
            data, layer = load_nb()
        except Exception as ex:
            P(f"NOT COMPLETED: {type(ex).__name__}: {ex}")
            data = {}
        if data:
            g0 = next(iter(data.values()))
            P("Source: Service New Brunswick / GeoNB, *Address NB Civic Address Database* (geonb_anb.gdb; source: Department "
              "of Public Safety), file readme dated 2024-04-23, GeoNB / NB Open Government Licence. Native EPSG:2953 (no "
              "reprojection). Read with a study-box bbox filter; the province was never loaded.")
            P(f"Layer `{layer}` (civic addresses; a separate `geonb_anb_subaddresses` layer lists units). Attributes: "
              f"{', '.join(c for c in g0.columns if c != 'geometry')}")
            P("**Residential vs commercial: yes** - `STRUCT_E` (structure type: Residence, Cottage / Camp, Commercial / "
              "Business, Non-Commercial, Tower Site ...). Residential-only counts below use STRUCT_E = 'Residence'; "
              "cottages/camps are reported separately (seasonal).")
            for name, label in (("pointe_sapin", "Pointe-Sapin"), ("fredericton", "Fredericton")):
                P(f"\n### {label}")
                civ = data[name]
                civ["kind"] = civ["STRUCT_E"].fillna("(not tagged)")
                res = lambda g: g["kind"] == "Residence"
                area, results, rows, civ = compare(name, civ, P, kind_col="kind", resid_mask=res)
                sub = civ["SUB_COUNT"].apply(lambda v: int(v) if str(v).strip().isdigit() else 0)
                mod = civ["MODIFIED"].astype(str).str[:10]
                P(f"- Address type (ADD_TYPE_E): " + ", ".join(f"{k} {v:,}" for k, v in Counter(civ["ADD_TYPE_E"].fillna("(not tagged)")).most_common()))
                P(f"- Multi-unit: {int((sub > 0).sum()):,} addresses carry sub-addresses (units), {int(sub.sum()):,} units in total "
                  f"(counted once here, as one civic address each). Latest record MODIFIED date in the box: {mod.max()}")
                P(f"- Residential (STRUCT_E = Residence): **{int(res(civ).sum()):,}**; Cottage / Camp: {int((civ['kind'] == 'Cottage / Camp').sum()):,}")
                if name == "pointe_sapin":
                    P(f"- **POINTE-SAPIN (whole study box): OSM {len(area.bld['osm']['pts']):,} | Microsoft "
                      f"{len(area.bld['ms']['pts']):,} | NB civic addresses {len(civ):,} "
                      f"(Residence {int(res(civ).sum()):,}; Residence + Cottage/Camp "
                      f"{int(civ['kind'].isin(['Residence', 'Cottage / Camp']).sum()):,})**")
                    P("- The documented 160 / 1,737 are ALL footprints in the Pointe-Sapin files; the engine analyses footprints "
                      ">= 40 m2, which is 147 / 1,540 in the same box. Both comparisons are shown.")
                table(rows, P, resid=True, top=10 if name == "pointe_sapin" else 15)
                ratios(rows, P)
    text = "\n".join(out)
    print(text)
    (REPO / "scratch" / "civic_address_check.md").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
