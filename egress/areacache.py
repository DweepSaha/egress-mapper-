"""Disk cache of a prepared area: the engine's own Area object and engine.scan's own result list, pickled.

This changes WHEN the scan runs, never WHAT it computes: a cache entry is the exact output of engine.load_area +
engine.scan for exactly these inputs, saved so opening the area is a read instead of a recompute. The key covers
every input: the engine and config source, the study box, the three data files (size + modification time) and the
library versions; any change gives a new key and the scan runs again. scripts/build_area_cache.py builds entries and
verifies them (the unpickled area re-scanned gives identical results). Pinned demo areas are never cached (always
computed live at startup). Cache files live with the data, outside the repository.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import platform
import sys
from pathlib import Path

import geopandas
import networkx
import numpy
import osmnx
import pyproj
import shapely

from . import config, engine

CACHE_DIR = config.DATA / "cache" / "areas"
_CODE = [Path(engine.__file__), Path(config.__file__)]


def key(name: str) -> str:
    h = hashlib.sha256()
    for p in _CODE:
        h.update(p.read_bytes())
    h.update(repr(tuple(round(v, 6) for v in engine.STUDY_BBOX[name])).encode())
    for p in (config.roads_graphml(name), config.buildings_osm(name), config.buildings_ms(name)):
        st = p.stat()
        h.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns}".encode())
    h.update(repr((sys.version_info[:3], platform.machine(), shapely.__version__, osmnx.__version__, geopandas.__version__,
                   numpy.__version__, pyproj.__version__, networkx.__version__)).encode())
    return h.hexdigest()


def path(name: str) -> Path:
    return CACHE_DIR / f"{name}-{key(name)[:20]}.pkl"


def exists(name: str) -> bool:
    try:
        return path(name).exists()
    except OSError:          # a data file is missing: nothing can be cached
        return False


def load(name: str):
    """(area, results) from a valid cache entry, or None."""
    p = path(name)
    if not p.exists():
        return None
    with open(p, "rb") as f:
        d = pickle.load(f)
    if d.get("key") != key(name):
        return None
    return d["area"], d["results"]


def save(name: str, area, results) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = path(name)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(dict(key=key(name), area=area, results=results), f, protocol=5)
    os.replace(tmp, p)                                   # never a half-written entry
    for old in CACHE_DIR.glob(f"{name}-*.pkl"):          # entries for older inputs can never be read again
        if old != p:
            old.unlink(missing_ok=True)
    return p


_GEOM = ("geometry", "streets", "choke", "cut_lines")


def same_results(a: list[dict], b: list[dict]) -> str | None:
    """None if identical (every field; geometries compared as exact WKB bytes), else the first difference."""
    if len(a) != len(b):
        return f"{len(a)} vs {len(b)} neighbourhoods"
    for x, y in zip(a, b):
        if x.keys() != y.keys():
            return f"nid {x.get('nid')}: keys differ"
        for k in x:
            if k in _GEOM:
                gx, gy = x[k], y[k]
                if (gx is None) != (gy is None) or (gx is not None and shapely.to_wkb(gx) != shapely.to_wkb(gy)):
                    return f"nid {x['nid']}: {k} differs"
            elif x[k] != y[k]:
                return f"nid {x['nid']}: {k} {x[k]!r} vs {y[k]!r}"
    return None
