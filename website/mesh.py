"""Hail footprints from NOAA MRMS MESH: outlines of the grid cells at or above each size.

MESH (Maximum Estimated Size of Hail) is a RADAR ESTIMATE, built from the Severe Hail Index (radar)
and a model's temperature profile (NSSL's WDTD page). It is not hail measured on the ground, not
verified hail and not damage. An outline says the estimate reached that size in those cells, in
that window. Cells outside every outline are not drawn, which is not the same as no hail, and
missing cells are never drawn as calm or dry.

    footprint(grid, valid_time, sizes_in, window_minutes=30) -> GeoJSON FeatureCollection

grid: a 2-D list or numpy array of millimetres, row 0 at the NORTH edge (MRMS order). Missing: NaN,
None, infinities, any negative value (MRMS uses -1 for missing and -3 for no radar coverage) and any
value in `nodata`. Missing cells never count as hail.

Outlines: cells joined along an edge form one group; cells that touch only at a corner stay apart.
Each group and size gives one feature: a Polygon with its holes as interior rings, or a MultiPolygon
when the group has more than one outer ring. Coordinates are lon/lat with outer rings
counter-clockwise and holes clockwise (RFC 7946). A group that reaches the grid's edge stops there:
the grid's edge is where the data ends, not where hail ended.

Sizes are inches, compared in millimetres (1 in = 25.4 mm). A cell counts at or above the size,
with a 0.0001 mm tolerance for float32 rounding (MRMS values sit on 0.1 mm steps). The MRMS CONUS
grid is 0.01 degree; the defaults below place its first cell's outer edges at 55.0 N and 130.0 W.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

MM_PER_INCH = 25.4
MRMS_NODATA = (-1.0, -3.0)        # MRMS: -1 missing, -3 no radar coverage (NSSL table, MESH rows 28-34)
MRMS_NORTH = 55.0                 # north edge of row 0 (its centre is 54.995 N)
MRMS_WEST = -130.0                # west edge of column 0 (its centre is 230.005 E, 129.995 W)
MRMS_CELL_DEG = 0.01
TOLERANCE_MM = 1e-4
KIND = "radar estimate"
SOURCE = "NOAA MRMS MESH, a radar estimate of the largest hail size. Not verified hail, not damage."


def footprint(grid, valid_time: datetime, sizes_in, *, window_minutes: int | None = None,
              nodata=MRMS_NODATA, north: float = MRMS_NORTH, west: float = MRMS_WEST,
              cell_deg: float = MRMS_CELL_DEG) -> dict:
    """One GeoJSON feature per connected group of cells at or above each size in inches.

    valid_time must be timezone-aware; it is written in UTC. window_minutes, when given, is
    recorded on each feature (the swath length is in the MRMS product name, not in the GRIB).
    Raises ValueError for inputs the caller got wrong; missing data is never an error.
    """
    stamp = _utc(valid_time).strftime("%Y-%m-%dT%H:%M:%SZ")
    values = _grid(grid)
    sizes = _sizes(sizes_in)
    if window_minutes is not None:
        window_minutes = int(window_minutes)
        if window_minutes < 1:
            raise ValueError("window_minutes must be a positive number of minutes")
    if not (math.isfinite(cell_deg) and cell_deg > 0):
        raise ValueError("cell_deg must be a positive number of degrees")
    missing = _missing(values, nodata)
    features = []
    for inches in sizes:
        mm = inches * MM_PER_INCH
        hail = ~missing & (values >= mm - TOLERANCE_MM)
        for cells in _groups(hail):
            props = {"kind": KIND, "threshold_in": inches, "threshold_mm": round(mm, 6),
                     "valid_time": stamp, "resolution_deg": cell_deg, "cells": len(cells)}
            if window_minutes is not None:
                props["window_minutes"] = window_minutes
            features.append({"type": "Feature", "properties": props,
                             "geometry": _geometry(cells, north, west, cell_deg)})
    return {"type": "FeatureCollection", "source": SOURCE, "valid_time": stamp, "features": features}


# ---------------------------------------------------------------- inputs

def _utc(valid_time) -> datetime:
    if not isinstance(valid_time, datetime) or valid_time.utcoffset() is None:
        raise ValueError("valid_time must be a timezone-aware datetime")
    return valid_time.astimezone(timezone.utc)


def _grid(grid) -> np.ndarray:
    if isinstance(grid, np.ndarray):
        values = np.array(grid, dtype=np.float64)
    else:
        rows = [[np.nan if v is None else v for v in row] for row in grid]
        if len({len(row) for row in rows}) > 1:
            raise ValueError("every row of the grid needs the same number of cells")
        values = np.array(rows, dtype=np.float64).reshape(len(rows), len(rows[0]) if rows else 0)
    if values.ndim != 2:
        raise ValueError("the grid must be two-dimensional (rows of cells)")
    return values


def _sizes(sizes_in) -> list[float]:
    try:
        sizes = [float(s) for s in sizes_in]
    except (TypeError, ValueError):
        raise ValueError("sizes_in must be a list of hail sizes in inches") from None
    for s in sizes:
        if not (math.isfinite(s) and s > 0):
            raise ValueError(f"hail size {s} in is not a positive number of inches")
    return sizes


def _missing(values: np.ndarray, nodata) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        missing = ~np.isfinite(values) | (values < 0)
    for flag in nodata:
        missing |= values == float(flag)
    return missing


# ---------------------------------------------------------------- groups of cells

def _groups(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    """Groups of True cells joined along an edge (4-connected), each a list of (row, col)."""
    rows, cols = mask.shape
    label = np.zeros(mask.shape, dtype=np.int32)
    groups: list[list[tuple[int, int]]] = []
    for r0, c0 in zip(*np.nonzero(mask)):
        r0, c0 = int(r0), int(c0)
        if label[r0, c0]:
            continue
        gid = len(groups) + 1
        label[r0, c0] = gid
        stack = [(r0, c0)]
        cells: list[tuple[int, int]] = []
        while stack:
            r, c = stack.pop()
            cells.append((r, c))
            for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if 0 <= nr < rows and 0 <= nc < cols and mask[nr, nc] and not label[nr, nc]:
                    label[nr, nc] = gid
                    stack.append((nr, nc))
        groups.append(cells)
    return groups


# ---------------------------------------------------------------- outlines

def _geometry(cells, north: float, west: float, cell_deg: float) -> dict:
    """Polygon (or MultiPolygon) for one group. Vertices are (x, y) = (column edge, -row edge),
    so y grows northward and the cell lies on the LEFT of every boundary edge."""
    loops = _loops(_edges(cells))
    outers = [loop for loop in loops if _twice_area(loop) > 0]
    holes = [loop for loop in loops if _twice_area(loop) < 0]
    polygons = [[outer] for outer in outers]
    for hole in holes:
        px, py = _background_point(hole)
        parent = None
        for k, outer in enumerate(outers):
            if _contains(outer, px, py) and (
                    parent is None or abs(_twice_area(outer)) < abs(_twice_area(outers[parent]))):
                parent = k
        if parent is None:
            raise RuntimeError("internal: a hole has no outer ring around it")
        polygons[parent].append(hole)
    shaped = [[_lonlat_ring(ring, north, west, cell_deg) for ring in polygon] for polygon in polygons]
    if len(shaped) == 1:
        return {"type": "Polygon", "coordinates": shaped[0]}
    return {"type": "MultiPolygon", "coordinates": shaped}


def _edges(cells) -> dict:
    """Directed boundary edges of a group, each with a cell of the group on its left."""
    inside = set(cells)
    out: dict[tuple[int, int], list[tuple[int, int]]] = {}

    def add(a, b):
        out.setdefault(a, []).append(b)

    for r, c in cells:
        if (r + 1, c) not in inside:
            add((c, -r - 1), (c + 1, -r - 1))
        if (r, c + 1) not in inside:
            add((c + 1, -r - 1), (c + 1, -r))
        if (r - 1, c) not in inside:
            add((c + 1, -r), (c, -r))
        if (r, c - 1) not in inside:
            add((c, -r), (c, -r - 1))
    return out


def _loops(out: dict) -> list[list[tuple[int, int]]]:
    """Closed loops from the directed edges. A loop never repeats a vertex: where two loops meet at
    a corner the walk splits them. At a corner with two ways on, it takes the left-most turn, which
    keeps cells that touch only diagonally apart. Consumes `out`."""
    loops: list[list[tuple[int, int]]] = []
    for start in list(out):
        if not out.get(start):
            continue
        path = [start]
        pos = {start: 0}
        while out.get(path[-1]):
            cur = path[-1]
            prev = path[-2] if len(path) > 1 else None
            nxt = _turn(prev, cur, out[cur])
            out[cur].remove(nxt)
            if nxt in pos:
                i = pos[nxt]
                loops.append(path[i:])
                for v in path[i + 1:]:
                    del pos[v]
                del path[i + 1:]
            else:
                pos[nxt] = len(path)
                path.append(nxt)
    return loops


def _turn(prev, cur, ends: list) -> tuple[int, int]:
    if prev is None or len(ends) == 1:
        return ends[0]
    dx, dy = cur[0] - prev[0], cur[1] - prev[1]
    return max(ends, key=lambda e: dx * (e[1] - cur[1]) - dy * (e[0] - cur[0]))


def _twice_area(loop) -> int:
    """Twice the signed area in cell units: positive for counter-clockwise (an outer ring)."""
    total = 0
    n = len(loop)
    for i in range(n):
        x1, y1 = loop[i]
        x2, y2 = loop[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total


def _background_point(loop) -> tuple[float, float]:
    """Centre of the non-group cell on the right of the loop's first edge: inside a hole."""
    (x1, y1), (x2, y2) = loop[0], loop[1]
    dx, dy = x2 - x1, y2 - y1
    return (x1 + x2) / 2 + 0.5 * dy, (y1 + y2) / 2 - 0.5 * dx


def _contains(ring, px: float, py: float) -> bool:
    """Ray casting. Points are cell centres (half-integers), so they never sit on a ring's edge."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > py) != (y2 > py) and px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _corners(loop) -> list[tuple[int, int]]:
    """The loop without its straight-run vertices: only the corners where the outline turns."""
    n = len(loop)
    keep = []
    for i in range(n):
        (px, py), (cx, cy), (qx, qy) = loop[i - 1], loop[i], loop[(i + 1) % n]
        if (cx - px) * (qy - cy) - (cy - py) * (qx - cx) != 0:
            keep.append((cx, cy))
    return keep


def _lonlat_ring(loop, north: float, west: float, cell_deg: float) -> list[list[float]]:
    pts = [[round(west + x * cell_deg, 6), round(north + y * cell_deg, 6)] for x, y in _corners(loop)]
    return pts + [pts[0]]
