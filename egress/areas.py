"""Registry of prepared study areas: the committed survey results (out/nb_survey, out/maritimes) plus display metadata.

Nothing here computes anything. Each area's study box, status counts and survey runtime are read from its survey JSON
(written by scratch/nb_scan.py with the frozen engine). Boxes not already in engine.STUDY_BBOX are added at import, as
the survey did, so engine.load_area can find them; engine.py itself is unchanged. The live scan the app runs when an
area is opened uses the same engine, parameters and data, so its counts equal the survey's (checked on load in api.py).
"""
from __future__ import annotations

import json
import math

from . import config, engine

PINNED = ("tantallon", "fredericton")        # the rehearsed demo path: always first, always resident on the server
PROVINCES = {"NB": "New Brunswick", "NS": "Nova Scotia", "PEI": "Prince Edward Island"}
PROVINCE_GPKG = {"NB": "new-brunswick.gpkg", "NS": "nova-scotia.gpkg", "PEI": "prince-edward-island.gpkg"}

# key: (label, province, short description). Descriptions come from the survey batch definitions.
META = {
    "tantallon": ("Upper Tantallon, NS", "NS", "Westwood Hills validation area"),
    "fredericton": ("Fredericton, NB", "NB", "city + surrounding road network"),
    "pointe_sapin": ("Pointe-Sapin, NB", "NB", "rural coastal"),
    "moncton": ("Moncton, NB", "NB", "Moncton + Dieppe + Riverview"),
    "saint_john": ("Saint John, NB", "NB", "city"),
    "quispamsis": ("Quispamsis, NB", "NB", "Quispamsis + Rothesay"),
    "miramichi": ("Miramichi, NB", "NB", "small city"),
    "bathurst": ("Bathurst, NB", "NB", "small city"),
    "edmundston": ("Edmundston, NB", "NB", "small city"),
    "campbellton": ("Campbellton, NB", "NB", "town"),
    "woodstock": ("Woodstock, NB", "NB", "town"),
    "grand_falls": ("Grand Falls, NB", "NB", "town"),
    "sussex": ("Sussex, NB", "NB", "town"),
    "shediac": ("Shediac, NB", "NB", "coastal town"),
    "sackville": ("Sackville, NB", "NB", "town"),
    "st_stephen": ("St. Stephen, NB", "NB", "border town"),
    "caraquet": ("Caraquet, NB", "NB", "rural coastal"),
    "richibucto": ("Richibucto, NB", "NB", "rural"),
    "hrm": ("Halifax Regional Municipality, NS", "NS", "Halifax, Dartmouth, Bedford, Sackville, Hammonds Plains, Tantallon"),
    "cbrm": ("Cape Breton (Sydney), NS", "NS", "Sydney, Sydney Mines, Glace Bay"),
    "truro": ("Truro, NS", "NS", "town"),
    "new_glasgow": ("New Glasgow, NS", "NS", "New Glasgow, Stellarton, Trenton"),
    "kentville": ("Kentville / Wolfville, NS", "NS", "Kentville + Wolfville"),
    "amherst": ("Amherst, NS", "NS", "town"),
    "bridgewater": ("Bridgewater, NS", "NS", "town"),
    "yarmouth": ("Yarmouth, NS", "NS", "town"),
    "antigonish": ("Antigonish, NS", "NS", "town"),
    "chester": ("Chester, NS", "NS", "rural South Shore"),
    "charlottetown": ("Charlottetown, PE", "PEI", "Charlottetown, Stratford, Cornwall"),
    "summerside": ("Summerside, PE", "PEI", "city"),
    "montague": ("Montague, PE", "PEI", "rural"),
}
# Rehearsed camera framing kept exactly; every other area is framed to its study box.
VIEW = {"tantallon": ([-63.862, 44.715], 13.2), "fredericton": ([-66.645, 45.958], 12.5)}
NOTES = {
    "tantallon": "Focused subset of the Halifax Regional Municipality box. Not counted separately in any total.",
    "hrm": "Contains the Upper Tantallon study area (counted once, here).",
}
SURVEY_DIRS = (config.OUT / "nb_survey", config.OUT / "maritimes")


def _fit(bbox, width_px=900, height_px=760):
    """Centre and a web-mercator zoom that fits the study box in a map of roughly this size."""
    x0, y0, x1, y1 = bbox
    merc = lambda lat: math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    zx = math.log2(width_px * 360 / (256 * (x1 - x0)))
    zy = math.log2(height_px * 2 * math.pi / (256 * (merc(y1) - merc(y0))))
    return [round((x0 + x1) / 2, 5), round((y0 + y1) / 2, 5)], round(min(zx, zy) - 0.2, 2)


def _missing(name: str) -> list[str]:
    return [label for label, p in (("roads", config.roads_graphml(name)), ("OSM buildings", config.buildings_osm(name)),
                                   ("Microsoft buildings", config.buildings_ms(name))) if not p.exists()]


def load() -> dict:
    """Ordered registry: pinned areas first, then by province (NB, NS, PEI) and label."""
    survey = {}
    for d in SURVEY_DIRS:
        for f in d.glob("*.json"):
            survey[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    reg = {}
    for key, (label, prov, desc) in META.items():
        s = survey.get(key)
        entry = dict(label=label, province=prov, desc=desc, pinned=key in PINNED, note=NOTES.get(key))
        if s is None:
            entry.update(available=False, reason="Survey results for this area were not generated.")
        else:
            bbox = tuple(s["bbox"])
            if key not in engine.STUDY_BBOX:
                engine.STUDY_BBOX[key] = bbox
            elif tuple(round(v, 5) for v in engine.STUDY_BBOX[key]) != tuple(round(v, 5) for v in bbox):
                raise RuntimeError(f"{key}: survey box {bbox} differs from engine.STUDY_BBOX {engine.STUDY_BBOX[key]}")
            c = s["counts"]
            centre, zoom = VIEW.get(key) or _fit(bbox)
            missing = _missing(key)
            entry.update(center=centre, zoom=zoom, bbox=list(bbox),
                         survey=dict(red=c.get("red", 0), amber=c.get("amber", 0), green=c.get("green", 0),
                                     not_assessed=c.get("not_assessed", 0), neighbourhoods=s["n_neighbourhoods"]),
                         prep_s=round(s["runtime_total_s"]), available=not missing,
                         reason=f"Prepared data missing: {', '.join(missing)}." if missing else None)
        reg[key] = entry
    order = sorted(reg, key=lambda k: (k not in PINNED, PINNED.index(k) if k in PINNED else 0,
                                       list(PROVINCES).index(reg[k]["province"]), reg[k]["label"]))
    return {k: reg[k] for k in order}
