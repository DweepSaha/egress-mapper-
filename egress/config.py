"""Paths and project-wide constants. Data lives outside the repo; point EGRESS_DATA at it."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("EGRESS_DATA", REPO.parent / "hackatlantic-prep" / "data"))
OUT = REPO / "out"

AREAS = ("tantallon", "fredericton", "pointe_sapin")
ANALYSIS_CRS = "EPSG:2953"  # NAD83(CSRS) / New Brunswick Stereographic; all distances in metres


def roads_graphml(area: str) -> Path:
    return DATA / "roads" / f"{area}.graphml"


def buildings_osm(area: str) -> Path:
    return DATA / "buildings" / f"{area}.gpkg"


def buildings_ms(area: str) -> Path:
    return DATA / "buildings" / "microsoft" / f"{area}.gpkg"
