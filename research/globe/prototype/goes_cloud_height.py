#!/usr/bin/env python3
"""Crop a GOES ABI cloud-top height (ABI-L2-ACHAC, variable HT) or band 13 brightness temperature
(ABI-L2-CMIPC C13, variable CMI) to a regular 0.02 degree lat/lon grid for a globe drape.

Research prototype under research/globe/prototype. Not part of the app and not a payload module.

Pipeline
  1. S3 REST listing (ListObjectsV2) of one hour of the NOAA GOES bucket. The newest file for the
     product is picked by the scan start time in its name. --time latest walks back up to 6 hours.
  2. Download that one object and open it with netCDF4. Run this script with python -I.
  3. Read the data variable raw (HT uint16 or CMI int16) with the file's own _FillValue,
     valid_range, scale_factor and add_offset, and the DQF variable when the file has one.
  4. Compute latitude and longitude of the native pixels in the bbox window with the fixed-grid
     equations below. Classify every pixel. Resample to the 0.02 degree grid by nearest neighbour.
  5. Write a 16-bit grayscale PNG (0 = no data) and a JSON sidecar with provenance and statistics.

Fixed-grid equations. Source: the GOES-R Series Product Definition and Users' Guide, ABI fixed-grid
navigation (fixed grid to latitude and longitude). The same geometry is PROJ +proj=geos +sweep=x.
The test file checks this module against pyproj. Scan angles x (east-west) and y (north-south) are
in radians. a = semi_major_axis, b = semi_minor_axis, H = perspective_point_height + a,
lon0 = longitude_of_projection_origin.
    A  = sin^2 x + cos^2 x (cos^2 y + (a/b)^2 sin^2 y)
    B  = -2 H cos x cos y
    C  = H^2 - a^2
    rs = (-B - sqrt(B^2 - 4 A C)) / (2 A)     no real root means the ray misses the Earth (NaN)
    sx = rs cos x cos y,  sy = -rs sin x,  sz = rs cos x sin y
    lat = atan((a/b)^2 sz / sqrt((H - sx)^2 + sy^2))
    lon = lon0 - atan(sy / (H - sx))
Inverse (latitude and longitude to scan angles), with e^2 = 1 - (b/a)^2:
    phi_c = atan((b/a)^2 tan lat)
    rc    = b / sqrt(1 - e^2 cos^2 phi_c)
    sx = H - rc cos phi_c cos(lon - lon0),  sy = -rc cos phi_c sin(lon - lon0),  sz = rc sin phi_c
    visible when sx (H - sx) >= sy^2 + (a/b)^2 sz^2  (the surface normal faces the satellite)
    x = asin(-sy / sqrt(sx^2 + sy^2 + sz^2)),  y = atan(sz / sx)

Resampling. Each target cell centre is mapped to scan angles with the inverse equations and given
the nearest native pixel centre in scan-angle space. A 0.02 degree cell is about 2.2 km north-south
and 1.5 km east-west at 47 N. A 2 km band 13 pixel is 4 to 5 km long along the view tilt over
Montana, and the 10 km ACHAC pixel is about twice that. The 0.02 degree cell is therefore finer
than the native pixel along the tilt, and the drape shows native pixels as blocks. It is for a
globe drape, not for measurement.

Validity policy. A value is "good" when it is not the file's fill, lies in the file's valid_range
and its DQF is 0. A value with DQF 1 to 3 is "flagged". Flagged values are reported separately and
are drawn in the PNG only with --include-flagged. Fill is "no retrieval". Anything else is out of
range or has an invalid DQF. Missing data is never written as a height, so 0 in the PNG always
means no data.

Heights are satellite retrieval estimates of cloud top. They are not cloud base, not damage, not
hail and not a probability.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

SCHEMA = "goes-cloud-height/1"
USER_AGENT = "roofingapp-globe-research/1 (goes_cloud_height.py)"
BUCKETS = {"east": "noaa-goes19", "west": "noaa-goes18"}
EXPECTED_PLATFORM = {"east": "G19", "west": "G18"}
PRODUCTS = {
    "ACHAC": {"bucket_prefix": "ABI-L2-ACHAC", "band": None, "variable": "HT",
              "quantity": "cloud_top_height", "units": "m"},
    "CMIPC13": {"bucket_prefix": "ABI-L2-CMIPC", "band": "C13", "variable": "CMI",
                "quantity": "brightness_temperature", "units": "K"},
}
DEFAULT_BBOX = (-116.8, 43.6, -103.3, 49.75)     # lon_min, lat_min, lon_max, lat_max
GRID_DEG = 0.02
NOTE_ACHA = "satellite estimate (retrieval), cloud top only, not cloud base"
NOTE_BT = "satellite observation (band 13 brightness temperature): not a height and not cloud base"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FILE_RE = re.compile(
    r"^OR_(?P<product>ABI-L2-[A-Z0-9]+)-M(?P<mode>\d)(?P<band>C\d{2})?_G(?P<platform>\d+)"
    r"_s(?P<start>\d{14})_e(?P<end>\d{14})_c(?P<created>\d{14})\.nc$")

# Pixel classes. Code 0 is used only for target cells with no native pixel under them.
CODE_OUTSIDE, CODE_GOOD, CODE_FLAGGED, CODE_DQF_INVALID, CODE_OUT_OF_RANGE, CODE_NO_RETRIEVAL = range(6)
CODE_LABELS = ["outside_native_grid", "good", "flagged_with_value", "dqf_invalid_with_value",
               "out_of_range", "no_retrieval"]
PNG_SHOWN_LABEL = "good"

REQUIRED_JSON_KEYS = [
    "schema", "synthetic", "product", "satellite", "satellite_name", "satellite_longitude_deg",
    "perspective_point_height_m", "semi_major_axis_m", "semi_minor_axis_m", "sweep_angle_axis",
    "time_coverage_start", "time_coverage_end", "bbox", "grid", "native_grid", "units", "quantity",
    "scale", "offset", "fill_raw", "valid_range_raw", "dqf", "native_pixels_in_bbox",
    "native_pixels_full_grid", "percent_native_bbox", "target_grid_counts", "percent_target_grid",
    "stats", "height_reference", "height_reference_statements", "bytes_downloaded", "runtime_s",
    "timings_s", "latency_s", "note", "output", "limits", "include_flagged_in_png",
    "centre_check", "dqf_file_percent_attributes", "dqf_good_check", "nominal_satellite_subpoint_lon_deg",
]


# ----------------------------------------------------------------------------------------------
# Fixed-grid geometry
# ----------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Geos:
    """Geostationary fixed-grid parameters, as stored in goes_imager_projection."""
    lon0_deg: float        # longitude_of_projection_origin
    height_m: float        # perspective_point_height (above the ellipsoid, at the equator)
    req_m: float           # semi_major_axis
    rpol_m: float          # semi_minor_axis
    sweep: str = "x"       # sweep_angle_axis; only "x" is implemented (GOES-R ABI)

    @property
    def H(self) -> float:
        return self.height_m + self.req_m

    @property
    def ratio(self) -> float:
        """(a/b)^2."""
        return (self.req_m / self.rpol_m) ** 2

    @property
    def e2(self) -> float:
        """First eccentricity squared."""
        return 1.0 - (self.rpol_m / self.req_m) ** 2


def _require_x_sweep(g: Geos) -> None:
    if g.sweep != "x":
        raise NotImplementedError(f"sweep_angle_axis {g.sweep!r} is not implemented (ABI uses 'x')")


def scan_to_latlon(x, y, g: Geos):
    """Fixed-grid scan angles (radians) to geodetic latitude and longitude (degrees).

    Returns (lat, lon) arrays. Rays that miss the Earth give NaN. Longitude is returned in
    [-180, 180). Equations: see the module docstring.
    """
    _require_x_sweep(g)
    x, y = np.broadcast_arrays(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))
    H = g.H
    a = g.req_m
    ratio = g.ratio
    cx, sx_ = np.cos(x), np.sin(x)
    cy, sy_ = np.cos(y), np.sin(y)
    A = sx_ * sx_ + cx * cx * (cy * cy + ratio * sy_ * sy_)
    B = -2.0 * H * cx * cy
    C = H * H - a * a
    disc = B * B - 4.0 * A * C
    ok = disc >= 0.0
    rs = (-B - np.sqrt(np.where(ok, disc, 0.0))) / (2.0 * A)
    sX = rs * cx * cy
    sY = -rs * sx_
    sZ = rs * cx * sy_
    D = H - sX
    lat = np.degrees(np.arctan2(ratio * sZ, np.sqrt(D * D + sY * sY)))
    lon = g.lon0_deg - np.degrees(np.arctan2(sY, D))
    lon = (lon + 180.0) % 360.0 - 180.0
    return np.where(ok, lat, np.nan), np.where(ok, lon, np.nan)


def latlon_to_scan(lat, lon, g: Geos):
    """Geodetic latitude and longitude (degrees) to fixed-grid scan angles (radians).

    Returns (x, y, visible). visible is False where the point is over the horizon of the satellite.
    Equations: see the module docstring.
    """
    _require_x_sweep(g)
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    H = g.H
    a = g.req_m
    b = g.rpol_m
    ratio = g.ratio
    phi = np.radians(lat)
    lam = np.radians(lon - g.lon0_deg)
    phi_c = np.arctan((b / a) ** 2 * np.tan(phi))
    rc = b / np.sqrt(1.0 - g.e2 * np.cos(phi_c) ** 2)
    sX = H - rc * np.cos(phi_c) * np.cos(lam)
    sY = -rc * np.cos(phi_c) * np.sin(lam)
    sZ = rc * np.sin(phi_c)
    visible = sX * (H - sX) >= sY * sY + ratio * sZ * sZ
    norm = np.sqrt(sX * sX + sY * sY + sZ * sZ)
    x = np.arcsin(np.clip(-sY / norm, -1.0, 1.0))
    y = np.arctan2(sZ, sX)
    return x, y, visible


def native_spacing_km(g: Geos, dx_rad: float, dy_rad: float) -> dict:
    """Nadir pixel size: perspective_point_height times the scan step (the ABI definition)."""
    return {"nadir_dx_km": abs(g.height_m * dx_rad) / 1000.0,
            "nadir_dy_km": abs(g.height_m * dy_rad) / 1000.0}


def footprint_km(g: Geos, x, y, i: int, j: int) -> dict:
    """Ground size of native pixel (column i, row j): singular values of its two side vectors."""
    i2 = min(i + 1, x.size - 1)
    j2 = min(j + 1, y.size - 1)
    la0, lo0 = scan_to_latlon(x[i], y[j], g)
    la1, lo1 = scan_to_latlon(x[i2], y[j], g)
    la2, lo2 = scan_to_latlon(x[i], y[j2], g)
    la0, lo0 = float(la0), float(lo0)
    phi = math.radians(la0)
    m_lat = 111132.954 - 559.822 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi)
    m_lon = 111412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi)

    def east_north(la, lo):
        dlon = ((float(lo) - lo0 + 180.0) % 360.0) - 180.0
        return dlon * m_lon, (float(la) - la0) * m_lat

    e1, n1 = east_north(la1, lo1)
    e2, n2 = east_north(la2, lo2)
    s = np.linalg.svd(np.array([[e1, e2], [n1, n2]]), compute_uv=False)
    return {"pixel_long_km": float(s[0]) / 1000.0, "pixel_short_km": float(s[1]) / 1000.0,
            "centre_lat": la0, "centre_lon": lo0, "index_col_row": [int(i), int(j)]}


def window_indices(bbox, x, y, g: Geos, pad: int = 10):
    """Native index window (i0, i1, j0, j1) that covers the bbox, padded by pad pixels."""
    lon_min, lat_min, lon_max, lat_max = bbox
    t = np.linspace(0.0, 1.0, 201)
    lo = lon_min + t * (lon_max - lon_min)
    la = lat_min + t * (lat_max - lat_min)
    lons = np.concatenate([lo, lo, np.full_like(t, lon_min), np.full_like(t, lon_max)])
    lats = np.concatenate([np.full_like(t, lat_min), np.full_like(t, lat_max), la, la])
    xs, ys, vis = latlon_to_scan(lats, lons, g)
    if not bool(np.all(vis)):
        raise ValueError("bbox is not entirely visible from this satellite")
    fi = (xs - x[0]) / (x[1] - x[0])
    fj = (ys - y[0]) / (y[1] - y[0])
    i0 = max(0, int(np.floor(fi.min())) - pad)
    i1 = min(x.size, int(np.ceil(fi.max())) + pad + 1)
    j0 = max(0, int(np.floor(fj.min())) - pad)
    j1 = min(y.size, int(np.ceil(fj.max())) + pad + 1)
    if i1 <= i0 or j1 <= j0:
        raise ValueError("bbox does not overlap the native grid")
    return i0, i1, j0, j1


def target_axes(bbox):
    """Cell-centre longitudes (west to east) and latitudes (north to south) of the 0.02 degree grid.

    The grid starts at the north-west corner of the bbox. It is ceil(extent / 0.02) cells in each
    direction, so the last row or column can reach up to 0.02 degree beyond the bbox edge.
    """
    lon_min, lat_min, lon_max, lat_max = bbox
    nx = int(math.ceil((lon_max - lon_min) / GRID_DEG - 1e-9))
    ny = int(math.ceil((lat_max - lat_min) / GRID_DEG - 1e-9))
    lon = lon_min + (np.arange(nx) + 0.5) * GRID_DEG
    lat = lat_max - (np.arange(ny) + 0.5) * GRID_DEG
    return lon, lat


def resample_nearest(lat, lon, g: Geos, x, y):
    """Nearest native pixel for each target point. Returns (col, row, inside).

    inside is False where the point is over the horizon or outside the native grid.
    """
    xs, ys, vis = latlon_to_scan(lat, lon, g)
    with np.errstate(invalid="ignore"):
        fi = np.rint((xs - x[0]) / (x[1] - x[0]))
        fj = np.rint((ys - y[0]) / (y[1] - y[0]))
    good = vis & np.isfinite(fi) & np.isfinite(fj)
    ii = np.where(good, fi, -1.0).astype(np.int64)
    jj = np.where(good, fj, -1.0).astype(np.int64)
    inside = good & (ii >= 0) & (ii < x.size) & (jj >= 0) & (jj < y.size)
    return np.where(inside, ii, 0), np.where(inside, jj, 0), inside


# ----------------------------------------------------------------------------------------------
# Classification and processing
# ----------------------------------------------------------------------------------------------

def classify(raw, fill: int, vlo: int, vhi: int, dqf, dqf_fill: int, dqf_lo: int, dqf_hi: int):
    """Per-pixel class code (uint8). The DQF argument may be None when the file has no DQF."""
    raw = np.asarray(raw)
    is_fill = raw == fill
    in_range = (raw >= vlo) & (raw <= vhi)
    value_ok = in_range & ~is_fill
    code = np.full(raw.shape, CODE_NO_RETRIEVAL, dtype=np.uint8)
    code[~is_fill & ~in_range] = CODE_OUT_OF_RANGE
    if dqf is None:
        code[value_ok] = CODE_GOOD
        return code
    dqf = np.asarray(dqf)
    dqf_good = dqf == 0
    dqf_in_range = (dqf >= dqf_lo) & (dqf <= dqf_hi) & (dqf != dqf_fill)
    code[value_ok] = CODE_DQF_INVALID
    code[value_ok & dqf_in_range & ~dqf_good] = CODE_FLAGGED
    code[value_ok & dqf_good] = CODE_GOOD
    return code


def _counts(codes) -> list:
    """Counts for codes 1..5 (good, flagged, dqf invalid, out of range, no retrieval)."""
    return [int(v) for v in np.bincount(np.asarray(codes, dtype=np.intp).ravel(), minlength=6)[1:6]]


def _count_dict(counts: list) -> dict:
    return {CODE_LABELS[k + 1]: counts[k] for k in range(5)}


def _pct(n: float, d: float) -> Optional[float]:
    return None if d <= 0 else round(100.0 * n / d, 4)


def _stats(values, unit: str) -> dict:
    if values.size == 0:
        return {"n": 0, "p10": None, "p50": None, "p90": None, "min": None, "max": None, "unit": unit}
    p10, p50, p90 = np.percentile(values, [10, 50, 90])
    return {"n": int(values.size), "p10": float(p10), "p50": float(p50), "p90": float(p90),
            "min": float(values.min()), "max": float(values.max()), "unit": unit}


def encode_png_values(values, units: str):
    """Physical value to uint16 PNG value. Heights in metres (rounded, minimum 1 so that 0 stays
    'no data'). Brightness temperature in 0.1 K steps. Callers pass only drawable pixels."""
    if units == "m":
        return np.clip(np.rint(values), 1, 65535).astype(np.uint16)
    return np.clip(np.rint(values * 10.0), 1, 65535).astype(np.uint16)


def process_dataset(data: dict, bbox, *, product_key: str, include_flagged: bool = False, pad: int = 10):
    """Classify, resample and summarise one dataset. Returns (png_uint16_array, result_dict).

    data keys: proj (Geos), x, y (float64 radians), raw (2-D integer array), scale, offset, fill,
    valid_range (lo, hi), dqf (2-D uint8 array or None), dqf_fill, dqf_valid_range (lo, hi).
    """
    cfg = PRODUCTS[product_key]
    g = data["proj"]
    x = np.asarray(data["x"], dtype=np.float64)
    y = np.asarray(data["y"], dtype=np.float64)
    raw = np.asarray(data["raw"])
    ny, nx = raw.shape
    if x.size != nx or y.size != ny:
        raise ValueError("coordinate sizes do not match the data array")
    dx = float(x[1] - x[0])
    dy = float(y[1] - y[0])
    if not (np.allclose(np.diff(x), dx, rtol=1e-6, atol=0.0) and np.allclose(np.diff(y), dy, rtol=1e-6, atol=0.0)):
        raise ValueError("native x/y grid is not regular")
    scale = float(data["scale"])
    offset = float(data["offset"])
    fill = int(data["fill"])
    vlo, vhi = (int(v) for v in data["valid_range"])
    dqf = data.get("dqf")
    dqf_fill = int(data.get("dqf_fill", 255))
    dqf_lo, dqf_hi = (int(v) for v in data.get("dqf_valid_range", (0, 255)))

    code = classify(raw, fill, vlo, vhi, dqf, dqf_fill, dqf_lo, dqf_hi)

    # Native pixels in the bbox window. Lat/lon are computed here for every pixel in the window.
    i0, i1, j0, j1 = window_indices(bbox, x, y, g, pad=pad)
    XX, YY = np.meshgrid(x[i0:i1], y[j0:j1])
    lat_w, lon_w = scan_to_latlon(XX, YY, g)
    lon_min, lat_min, lon_max, lat_max = bbox
    inside_w = (lat_w >= lat_min) & (lat_w <= lat_max) & (lon_w >= lon_min) & (lon_w <= lon_max)
    code_w = code[j0:j1, i0:i1]
    vals_w = raw[j0:j1, i0:i1].astype(np.float64) * scale + offset
    native_bbox = _counts(code_w[inside_w])
    native_bbox_total = int(inside_w.sum())
    native_full = _counts(code)
    native_full_total = int(code.size)
    good_vals = vals_w[inside_w & (code_w == CODE_GOOD)]
    flagged_vals = vals_w[inside_w & (code_w == CODE_FLAGGED)]

    dqf_block = {"present": dqf is not None, "variable": "DQF" if dqf is not None else None}
    if dqf is not None:
        dq = np.asarray(dqf)
        in_rng_full = (dq >= dqf_lo) & (dq <= dqf_hi) & (dq != dqf_fill)
        values, counts = np.unique(dq, return_counts=True)
        dqf_block["fill"] = dqf_fill
        dqf_block["valid_range"] = [dqf_lo, dqf_hi]
        dqf_block["value_counts_full_grid"] = {str(int(v)): int(c) for v, c in zip(values, counts)}
        dqf_block["full_grid"] = _dqf_share(dq, in_rng_full, dqf_fill)
        dq_w = dq[j0:j1, i0:i1]
        in_rng_w = (dq_w >= dqf_lo) & (dq_w <= dqf_hi) & (dq_w != dqf_fill)
        dqf_block["bbox_native"] = _dqf_share(dq_w[inside_w], in_rng_w[inside_w], dqf_fill)

    # Footprint at the bbox centre.
    lat_c = 0.5 * (lat_min + lat_max)
    lon_c = 0.5 * (lon_min + lon_max)
    xc, yc, vis_c = latlon_to_scan(lat_c, lon_c, g)
    ic = int(np.clip(round(float(xc - x[0]) / dx), 0, nx - 1))
    jc = int(np.clip(round(float(yc - y[0]) / dy), 0, ny - 1))
    foot = footprint_km(g, x, y, ic, jc)
    spacing = native_spacing_km(g, dx, dy)

    # Nearest-neighbour resampling onto the 0.02 degree grid.
    lon_t, lat_t = target_axes(bbox)
    LON, LAT = np.meshgrid(lon_t, lat_t)
    ii, jj, inside_native = resample_nearest(LAT, LON, g, x, y)
    tcode = np.zeros(LON.shape, dtype=np.uint8)
    tcode[inside_native] = code[jj[inside_native], ii[inside_native]]
    target_counts = np.bincount(tcode.ravel().astype(np.intp), minlength=6)
    target_cells = int(LON.size)
    shown = (tcode == CODE_GOOD) | (include_flagged & (tcode == CODE_FLAGGED))
    val_t = raw[jj, ii].astype(np.float64) * scale + offset
    png = np.zeros(LON.shape, dtype=np.uint16)
    png[shown] = encode_png_values(val_t[shown], cfg["units"])

    counts_target = {"cells": target_cells, "outside_native_grid": int(target_counts[0])}
    counts_target.update(_count_dict([int(v) for v in target_counts[1:6]]))

    stats = {"unit": cfg["units"],
             "good": _stats(good_vals, cfg["units"]),
             "flagged_with_value": _stats(flagged_vals, cfg["units"])}
    if cfg["units"] == "K":
        stats["note"] = "stats are brightness temperatures in K; PNG holds 0.1 K steps"

    result = {
        "native_grid": {
            "nx": nx, "ny": ny, "x_step_rad": dx, "y_step_rad": dy,
            "x_first_rad": float(x[0]), "y_first_rad": float(y[0]),
            "nadir_dx_km": spacing["nadir_dx_km"], "nadir_dy_km": spacing["nadir_dy_km"],
            "window_col_row": [i0, i1, j0, j1],
            "footprint_at_bbox_centre": {k: foot[k] for k in ("pixel_long_km", "pixel_short_km", "index_col_row")},
        },
        "native_pixels_in_bbox": {"total": native_bbox_total, **_count_dict(native_bbox)},
        "native_pixels_full_grid": {"total": native_full_total, **_count_dict(native_full)},
        "percent_native_bbox": {k: _pct(v, native_bbox_total) for k, v in
                                zip(CODE_LABELS[1:6], native_bbox)},
        "target_grid_counts": counts_target,
        "percent_target_grid": {
            "good": _pct(target_counts[CODE_GOOD], target_cells),
            "flagged_with_value": _pct(target_counts[CODE_FLAGGED], target_cells),
            "drawn_in_png": _pct(int(shown.sum()), target_cells),
        },
        "stats": stats,
        "dqf": dqf_block,
        "png_cells_with_value": int(np.count_nonzero(png)),
        "_target_codes": tcode,  # kept for tests; removed before JSON output
        "_target_native_index": (ii, jj, inside_native),
    }
    return png, result


def _dqf_share(dq, in_range, dqf_fill: int) -> dict:
    non_fill = int(np.count_nonzero(dq != dqf_fill))
    good = int(np.count_nonzero(dq == 0))
    flagged = int(np.count_nonzero(in_range & (dq != 0)))
    invalid = int(dq.size) - non_fill
    return {"total": int(dq.size), "non_fill": non_fill, "good_dqf0": good, "flagged": flagged,
            "invalid_or_fill": invalid + int(np.count_nonzero((dq != dqf_fill) & ~in_range)),
            "good_pct_of_non_fill": _pct(good, non_fill),
            "flagged_pct_of_non_fill": _pct(flagged, non_fill)}


# ----------------------------------------------------------------------------------------------
# PNG (16-bit grayscale, stdlib zlib only) and a reader used by the tests
# ----------------------------------------------------------------------------------------------

def _png_chunk(tag: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)


def encode_png16(arr) -> bytes:
    """Encode a 2-D uint16 array as a 16-bit grayscale PNG. Each row picks the filter (none, sub, up)
    with the smallest sum of signed byte magnitudes, the usual heuristic."""
    arr = np.asarray(arr)
    if arr.dtype != np.uint16 or arr.ndim != 2:
        raise ValueError("encode_png16 needs a 2-D uint16 array")
    h, w = arr.shape
    rows = arr.astype(">u2").view(np.uint8).reshape(h, 2 * w)
    bpp = 2
    sub = rows.copy()
    sub[:, bpp:] = (rows[:, bpp:].astype(np.int16) - rows[:, :-bpp].astype(np.int16)) & 0xFF
    up = np.zeros_like(rows)
    up[0] = rows[0]
    up[1:] = (rows[1:].astype(np.int16) - rows[:-1].astype(np.int16)) & 0xFF

    def cost(f):
        s = f.astype(np.int16)
        return np.minimum(s, 256 - s).sum(axis=1)

    costs = np.stack([cost(rows), cost(sub), cost(up)])
    choice = np.argmin(costs, axis=0).astype(np.uint8)
    chosen = np.where((choice == 1)[:, None], sub, np.where((choice == 2)[:, None], up, rows))
    stream = np.empty((h, 1 + 2 * w), dtype=np.uint8)
    stream[:, 0] = choice
    stream[:, 1:] = chosen
    ihdr = struct.pack(">IIBBBBB", w, h, 16, 0, 0, 0, 0)
    text = b"Software\x00goes_cloud_height.py (research prototype)"
    return (PNG_SIGNATURE + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"tEXt", text)
            + _png_chunk(b"IDAT", zlib.compress(stream.tobytes(), 9)) + _png_chunk(b"IEND", b""))


def decode_png16(data: bytes) -> np.ndarray:
    """Decode a 16-bit grayscale PNG written by encode_png16 (filters 0, 1 and 2)."""
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("not a PNG")
    pos = 8
    idat = []
    w = h = None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        crc = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
        if zlib.crc32(tag + body) & 0xFFFFFFFF != crc:
            raise ValueError(f"bad CRC in {tag!r}")
        if tag == b"IHDR":
            w, h, depth, ctype, _c, _f, interlace = struct.unpack(">IIBBBBB", body)
            if (depth, ctype, interlace) != (16, 0, 0):
                raise ValueError("only 16-bit grayscale, non-interlaced PNG is supported")
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
        pos += 12 + length
    raw = zlib.decompress(b"".join(idat))
    stride = 2 * w
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int64)
    for r in range(h):
        base = r * (stride + 1)
        ft = raw[base]
        line = np.frombuffer(raw, dtype=np.uint8, count=stride, offset=base + 1).astype(np.int64)
        if ft == 0:
            rec = line
        elif ft == 2:
            rec = (line + prev) & 0xFF
        elif ft == 1:
            rec = np.empty(stride, dtype=np.int64)
            for k in range(2):
                rec[k::2] = np.cumsum(line[k::2]) & 0xFF
        else:
            raise ValueError(f"filter type {ft} not supported by this reader")
        out[r] = rec.astype(np.uint8)
        prev = rec
    return out.reshape(h, stride).view(">u2").astype(np.uint16).reshape(h, w)


def _atomic_write(path: str, data: bytes) -> None:
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


# ----------------------------------------------------------------------------------------------
# Time, bucket listing and selection
# ----------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Entry:
    key: str
    last_modified: dt.datetime
    size: int


@dataclass(frozen=True)
class Pick:
    key: str
    size: int
    last_modified: dt.datetime
    scan_start: dt.datetime
    scan_end: dt.datetime
    platform: str
    product_token: str
    band: Optional[str]


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_utc(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{d.microsecond // 100000}Z"


def parse_iso(s: str) -> dt.datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def parse_scan_stamp(stamp: str) -> dt.datetime:
    """sYYYYDDDHHMMSSt (14 digits, tenths of a second last) to a UTC datetime."""
    year, doy = int(stamp[0:4]), int(stamp[4:7])
    hh, mm, ss, tenth = int(stamp[7:9]), int(stamp[9:11]), int(stamp[11:13]), int(stamp[13])
    base = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc)
    return base + dt.timedelta(days=doy - 1, hours=hh, minutes=mm, seconds=ss, milliseconds=100 * tenth)


def parse_bbox(text: str) -> tuple:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox needs four numbers: lon_min,lat_min,lon_max,lat_max")
    lon_min, lat_min, lon_max, lat_max = (float(p) for p in parts)
    if not (-180 <= lon_min < lon_max <= 180 and -90 <= lat_min < lat_max <= 90):
        raise ValueError("--bbox must have lon_min < lon_max within [-180, 180] and lat_min < lat_max within [-90, 90]")
    return lon_min, lat_min, lon_max, lat_max


def parse_time_arg(text: str) -> Optional[tuple]:
    """'latest' gives None. 'YYYY-DDD-HH' gives (year, day_of_year, hour)."""
    if text == "latest":
        return None
    m = re.fullmatch(r"(\d{4})-(\d{3})-(\d{2})", text)
    if not m:
        raise ValueError("--time must be 'latest' or YYYY-DDD-HH (UTC, day of year, hour)")
    year, doy, hour = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not 0 <= hour <= 23:
        raise ValueError("--time hour must be 00 to 23")
    try:
        when = dt.datetime(year, 1, 1) + dt.timedelta(days=doy - 1)
    except OverflowError as exc:
        raise ValueError("--time day of year is out of range") from exc
    if when.year != year or not 1 <= doy <= 366:
        raise ValueError("--time day of year does not exist in that year")
    return year, doy, hour


def _plain(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, np.ndarray):
        if value.size == 1:
            return _plain(value.reshape(-1)[0])
        return [_plain(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    return value


def parse_listing(body: bytes):
    """ListObjectsV2 XML to (entries, is_truncated, next_continuation_token)."""
    root = ET.fromstring(body)

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    entries = []
    truncated = False
    token = None
    for el in root:
        name = local(el.tag)
        if name == "Contents":
            fields = {local(c.tag): (c.text or "") for c in el}
            entries.append(Entry(key=fields["Key"], last_modified=parse_iso(fields["LastModified"]),
                                 size=int(fields["Size"])))
        elif name == "IsTruncated":
            truncated = (el.text or "").strip().lower() == "true"
        elif name == "NextContinuationToken":
            token = (el.text or "").strip() or None
    return entries, truncated, token


def http_get(url: str, timeout: float = 60.0, attempts: int = 3) -> bytes:
    last: Optional[BaseException] = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"request failed after {attempts} attempts: {url}: {last}")


def download(url: str, dest: str, expected_size: Optional[int], timeout: float = 180.0,
             attempts: int = 3) -> int:
    """Stream url to dest and return the byte count. The count must match the listing size."""
    last: Optional[BaseException] = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            total = 0
            tmp = dest + ".part"
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    total += len(chunk)
            if expected_size is not None and total != expected_size:
                raise RuntimeError(f"size mismatch for {url}: got {total}, listing said {expected_size}")
            os.replace(tmp, dest)
            return total
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"download failed after {attempts} attempts: {url}: {last}")


def match_product(key: str, cfg: dict) -> Optional["re.Match"]:
    m = FILE_RE.match(key.rsplit("/", 1)[-1])
    if m is None or m.group("product") != cfg["bucket_prefix"]:
        return None
    if (m.group("band") or None) != cfg["band"]:
        return None
    return m


def _pick_from_entry(e: Entry, m) -> Pick:
    return Pick(key=e.key, size=e.size, last_modified=e.last_modified,
                scan_start=parse_scan_stamp(m.group("start")),
                scan_end=parse_scan_stamp(m.group("end")),
                platform="G" + m.group("platform"), product_token=m.group("product"),
                band=m.group("band"))


def newest_pick(entries, cfg: dict) -> Optional[Pick]:
    """Newest matching file: greatest scan start, ties broken by upload time."""
    best = None
    for e in entries:
        m = match_product(e.key, cfg)
        if m is None:
            continue
        k = (parse_scan_stamp(m.group("start")), e.last_modified)
        if best is None or k > best[0]:
            best = (k, e, m)
    return None if best is None else _pick_from_entry(best[1], best[2])


def hour_prefix(cfg: dict, when: dt.datetime) -> str:
    return f"{cfg['bucket_prefix']}/{when.year:04d}/{when.timetuple().tm_yday:03d}/{when.hour:02d}/"


def list_prefix(bucket: str, prefix: str, fetch: Callable[[str], bytes]):
    entries: list = []
    nbytes = 0
    token = None
    for _page in range(20):
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        url = f"https://{bucket}.s3.amazonaws.com/?{urllib.parse.urlencode(params)}"
        body = fetch(url)
        nbytes += len(body)
        page, truncated, token = parse_listing(body)
        entries.extend(page)
        if not truncated or not token:
            break
    return entries, nbytes


def find_latest(bucket: str, cfg: dict, now: dt.datetime, fetch, max_hours: int = 6):
    """Walk back hour by hour from now until a matching file is found."""
    hour0 = now.replace(minute=0, second=0, microsecond=0)
    list_bytes = 0
    checked = []
    for back in range(max_hours):
        when = hour0 - dt.timedelta(hours=back)
        prefix = hour_prefix(cfg, when)
        entries, nbytes = list_prefix(bucket, prefix, fetch)
        list_bytes += nbytes
        checked.append(prefix)
        pick = newest_pick(entries, cfg)
        if pick is not None:
            return pick, list_bytes, checked
    raise RuntimeError(f"no {cfg['bucket_prefix']} file in the last {max_hours} hours under {bucket}")


def find_hour(bucket: str, cfg: dict, year: int, doy: int, hour: int, fetch):
    when = dt.datetime(year, 1, 1, hour, tzinfo=dt.timezone.utc) + dt.timedelta(days=doy - 1)
    prefix = hour_prefix(cfg, when)
    entries, nbytes = list_prefix(bucket, prefix, fetch)
    pick = newest_pick(entries, cfg)
    if pick is None:
        raise RuntimeError(f"no {cfg['bucket_prefix']} file under s3://{bucket}/{prefix}")
    return pick, nbytes


def find_key(bucket: str, cfg: dict, key: str, fetch):
    prefix = key.rsplit("/", 1)[0] + "/"
    entries, nbytes = list_prefix(bucket, prefix, fetch)
    for e in entries:
        if e.key == key:
            m = match_product(key, cfg)
            if m is None:
                raise RuntimeError(f"{key} is not a {cfg['bucket_prefix']} file for this product option")
            return _pick_from_entry(e, m), nbytes
    raise RuntimeError(f"key not found in listing of {prefix}: {key}")


# ----------------------------------------------------------------------------------------------
# netCDF input (netCDF4 is imported lazily so the numeric code and the tests do not need it)
# ----------------------------------------------------------------------------------------------

GLOBAL_ATTRS_KEEP = ("time_coverage_start", "time_coverage_end", "platform_ID", "orbital_slot",
                     "instrument_type", "scene_id", "spatial_resolution", "percent_good_quality_qf",
                     "license", "title", "production_site", "geospatial_lat_center",
                     "geospatial_lon_center", "dataset_name", "project")
HEIGHT_REF_KEYWORDS = ("ellipsoid", "sea level", "mean sea", "geoid", "geopotential", "ground", "terrain",
                       "surface", "datum", "reference", "above")
# What the CF standard-name table says the name means (cfconventions.org current table, read on
# 2026-10-17: geopotential is relative to the geoid, and geopotential height is not relative to the
# surface). Used only to label the file's own standard_name; the file text does not restate it.
CF_HEIGHT_REFERENCE = {
    "geopotential_height_at_cloud_top": "relative to the geoid (sea level), not to the surface, by the "
                                        "CF meaning of the standard_name",
}
HEIGHT_REF_SKIP = {"grid_mapping", "coordinates", "ancillary_variables", "_FillValue", "valid_range",
                   "flag_meanings", "flag_values", "cell_methods"}


def height_reference_statements(attrs: dict) -> list:
    out = []
    for k, v in attrs.items():
        if k in HEIGHT_REF_SKIP:
            continue
        text = str(v)
        low = text.lower()
        if any(word in low for word in HEIGHT_REF_KEYWORDS):
            out.append(f"{k}: {text[:300]}")
    return out


def _scaled_coord(var) -> np.ndarray:
    var.set_auto_maskandscale(False)
    raw = np.asarray(var[:])
    scale = float(_plain(var.getncattr("scale_factor"))) if "scale_factor" in var.ncattrs() else 1.0
    offset = float(_plain(var.getncattr("add_offset"))) if "add_offset" in var.ncattrs() else 0.0
    return raw.astype(np.float64) * scale + offset


def read_netcdf(path: str, product_key: str) -> dict:
    """Open one ABI L2 file and return the raw arrays and the attributes the report needs."""
    import netCDF4  # imported here: only the file reader needs it

    cfg = PRODUCTS[product_key]
    ds = netCDF4.Dataset(path, mode="r")
    try:
        gattrs = {k: _plain(ds.getncattr(k)) for k in ds.ncattrs()}
        pv = ds.variables["goes_imager_projection"]
        pa = {k: _plain(pv.getncattr(k)) for k in pv.ncattrs()}
        geos = Geos(lon0_deg=float(pa["longitude_of_projection_origin"]),
                    height_m=float(pa["perspective_point_height"]),
                    req_m=float(pa["semi_major_axis"]), rpol_m=float(pa["semi_minor_axis"]),
                    sweep=str(pa["sweep_angle_axis"]).strip().lower())
        x = _scaled_coord(ds.variables["x"])
        y = _scaled_coord(ds.variables["y"])
        dv = ds.variables[cfg["variable"]]
        dv.set_auto_maskandscale(False)
        raw = np.asarray(dv[:])
        dattrs = {k: _plain(dv.getncattr(k)) for k in dv.ncattrs()}
        for need in ("_FillValue", "valid_range"):
            if need not in dattrs:
                raise ValueError(f"{cfg['variable']} has no {need}; refusing to guess")
        scale = float(dattrs.get("scale_factor", 1.0))
        offset = float(dattrs.get("add_offset", 0.0))
        dqf = None
        dqf_attrs = {}
        dqf_fill = 255
        dqf_range = (0, 255)
        if "DQF" in ds.variables:
            qv = ds.variables["DQF"]
            qv.set_auto_maskandscale(False)
            dqf = np.asarray(qv[:])
            dqf_attrs = {k: _plain(qv.getncattr(k)) for k in qv.ncattrs()}
            dqf_fill = int(dqf_attrs.get("_FillValue", 255))
            dqf_range = tuple(int(v) for v in dqf_attrs.get("valid_range", [0, 255]))
        geo_ref = {"geospatial_lat_lon_extent": {}, "nominal_satellite_subpoint_lon_deg": None}
        if "geospatial_lat_lon_extent" in ds.variables:
            gv = ds.variables["geospatial_lat_lon_extent"]
            geo_ref["geospatial_lat_lon_extent"] = {k: _plain(gv.getncattr(k)) for k in gv.ncattrs()}
        if "nominal_satellite_subpoint_lon" in ds.variables:
            nv = ds.variables["nominal_satellite_subpoint_lon"]
            nv.set_auto_maskandscale(False)
            geo_ref["nominal_satellite_subpoint_lon_deg"] = float(np.asarray(nv[:]).reshape(-1)[0])
    finally:
        ds.close()
    return {
        "geo_ref": geo_ref,
        "proj": geos, "x": x, "y": y, "raw": raw, "scale": scale, "offset": offset,
        "fill": int(dattrs["_FillValue"]),
        "valid_range": tuple(int(v) for v in dattrs["valid_range"]),
        "dqf": dqf, "dqf_fill": dqf_fill, "dqf_valid_range": dqf_range,
        "data_attrs": {k: (v[:300] if isinstance(v, str) else v) for k, v in dattrs.items()},
        "dqf_attrs": {k: (v[:300] if isinstance(v, str) else v) for k, v in dqf_attrs.items()},
        "global_attrs": {k: gattrs[k] for k in GLOBAL_ATTRS_KEEP if k in gattrs},
        "projection_attrs": pa,
    }


# ----------------------------------------------------------------------------------------------
# Synthetic field (labelled synthetic everywhere; used by --synthetic and the tests)
# ----------------------------------------------------------------------------------------------

def synthetic_dataset(product_key: str, satellite: str, bbox=DEFAULT_BBOX,
                      nx: Optional[int] = None, ny: Optional[int] = None) -> dict:
    """A smooth cloud-top field on a GOES-like fixed grid centred on the bbox. Not NOAA data.

    Includes good, flagged (DQF 1), invalid-DQF (255), out-of-range and no-retrieval pixels so the
    classification and reporting paths are all exercised.
    """
    lon0 = -75.2 if satellite == "east" else -137.0
    g = Geos(lon0_deg=lon0, height_m=35786023.0, req_m=6378137.0, rpol_m=6356752.31414, sweep="x")
    if product_key == "ACHAC":
        nx, ny, step = nx or 500, ny or 300, 0.00028
    else:
        nx, ny, step = nx or 2500, ny or 1500, 0.000056
    lat_c = 0.5 * (bbox[1] + bbox[3])
    lon_c = 0.5 * (bbox[0] + bbox[2])
    xc, yc, _ = latlon_to_scan(lat_c, lon_c, g)
    x = float(xc) + (np.arange(nx) - (nx - 1) / 2.0) * step
    y = float(yc) - (np.arange(ny) - (ny - 1) / 2.0) * step
    XX, YY = np.meshgrid(x, y)
    lat, lon = scan_to_latlon(XX, YY, g)
    lat = np.nan_to_num(lat, nan=-90.0)
    lon = np.nan_to_num(lon, nan=0.0)
    d1 = (lat - 47.3) ** 2 + ((lon + 110.5) * math.cos(math.radians(47.0))) ** 2
    d2 = (lat - 45.4) ** 2 + ((lon + 107.0) * math.cos(math.radians(46.0))) ** 2
    height = 1500.0 + 11000.0 * np.exp(-d1 / 1.2 ** 2) + 6000.0 * np.exp(-d2 / 0.8 ** 2)
    no_ret = (lat > 49.3) | (lon < -115.8)
    dqf = np.zeros(height.shape, dtype=np.uint8)
    band = np.abs(lon + 112.0) < 0.12
    dqf[band] = 1
    dqf[(lat < 44.0) & (lon < -110.0)] = 255
    if product_key == "ACHAC":
        scale, offset, fill, vrange = 0.3052037, 0.0, 65535, (0, 65530)
        raw = np.clip(np.rint(height / scale), 0, 65530).astype(np.uint16)
        raw[no_ret] = 65535
        raw[(lon > -106.0) & (lon < -105.0) & (lat > 44.0) & (lat < 44.6)] = 65531
        units, dqf_fill_v = "m", 255
    else:
        scale, offset, fill, vrange = 0.06145332, 89.62, -1, (0, 4095)
        temp = np.clip(290.0 - 0.0065 * height, 200.0, 320.0)
        raw = np.clip(np.rint((temp - offset) / scale), 0, 4095).astype(np.int16)
        raw[no_ret] = -1
        units, dqf_fill_v = "K", 255
    gattrs = {"time_coverage_start": "2026-10-17T00:00:00.0Z", "time_coverage_end": "2026-10-17T00:00:00.0Z",
              "platform_ID": "G19" if satellite == "east" else "G18",
              "orbital_slot": "GOES-East (synthetic)" if satellite == "east" else "GOES-West (synthetic)",
              "license": "SYNTHETIC test field; not NOAA data"}
    return {
        "proj": g, "x": x, "y": y, "raw": raw, "scale": scale, "offset": offset, "fill": fill,
        "valid_range": vrange, "dqf": dqf, "dqf_fill": dqf_fill_v, "dqf_valid_range": (0, 3),
        "data_attrs": {"units": units, "_FillValue": fill, "valid_range": list(vrange),
                       "scale_factor": scale, "add_offset": offset, "long_name": "synthetic test field"},
        "dqf_attrs": {"_FillValue": dqf_fill_v, "valid_range": [0, 3], "flag_values": [0, 1, 2, 3],
                      "flag_meanings": "synthetic"},
        "global_attrs": gattrs, "projection_attrs": {"synthetic": True},
    }


# ----------------------------------------------------------------------------------------------
# Run and report
# ----------------------------------------------------------------------------------------------

def _clean(obj):
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _clean(obj.tolist())
    if isinstance(obj, np.generic):
        return _clean(obj.item())
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def run(args, *, bbox, time_req, fetch: Optional[Callable[[str], bytes]] = None,
        now: Optional[dt.datetime] = None, download_dir: Optional[str] = None) -> dict:
    """Run one crop. Returns the JSON sidecar dict and writes the PNG and JSON files."""
    fetch = fetch or http_get
    t_start = time.monotonic()
    cfg = PRODUCTS[args.product]
    timings: dict = {}
    bytes_listing = 0
    bytes_object = 0
    pick: Optional[Pick] = None
    start_now = now or utcnow()
    checked_at = start_now
    bucket = None
    object_url = None
    time_request = "synthetic"

    if args.synthetic:
        t0 = time.monotonic()
        data = synthetic_dataset(args.product, args.satellite, bbox)
        timings["synthetic_build"] = round(time.monotonic() - t0, 3)
    else:
        bucket = BUCKETS[args.satellite]
        t0 = time.monotonic()
        if args.key:
            pick, bytes_listing = find_key(bucket, cfg, args.key, fetch)
            time_request = f"key:{args.key}"
        elif time_req is None:
            pick, bytes_listing, _checked = find_latest(bucket, cfg, start_now, fetch)
            time_request = "latest"
        else:
            year, doy, hour = time_req
            pick, bytes_listing = find_hour(bucket, cfg, year, doy, hour, fetch)
            time_request = f"{year}-{doy:03d}-{hour:02d}"
        checked_at = now or utcnow()
        timings["list"] = round(time.monotonic() - t0, 3)
        if pick.platform != EXPECTED_PLATFORM[args.satellite]:
            raise RuntimeError(f"file platform {pick.platform} does not match --satellite {args.satellite}")
        object_url = f"https://{bucket}.s3.amazonaws.com/{pick.key}"
        ddir = download_dir or tempfile.mkdtemp(prefix="goes-cloud-height-")
        os.makedirs(ddir, exist_ok=True)
        dest = os.path.join(ddir, os.path.basename(pick.key))
        t0 = time.monotonic()
        bytes_object = download(object_url, dest, pick.size)
        timings["download"] = round(time.monotonic() - t0, 3)
        t0 = time.monotonic()
        data = read_netcdf(dest, args.product)
        timings["read_netcdf"] = round(time.monotonic() - t0, 3)
        if not args.keep_download:
            os.remove(dest)

    t0 = time.monotonic()
    png, res = process_dataset(data, bbox, product_key=args.product,
                               include_flagged=bool(args.include_flagged))
    timings["classify_resample"] = round(time.monotonic() - t0, 3)

    g = data["proj"]
    ga = data["global_attrs"]
    t_start_attr = ga.get("time_coverage_start")
    t_end_attr = ga.get("time_coverage_end")
    scan_start = parse_iso(t_start_attr) if t_start_attr else None
    scan_end = parse_iso(t_end_attr) if t_end_attr else None
    if pick is not None and scan_start is not None:
        if abs((scan_start - pick.scan_start).total_seconds()) > 0.2:
            raise RuntimeError("time_coverage_start does not match the scan start in the file name")
    latency = None
    if pick is not None and scan_end is not None:
        latency = {"checked_at_utc": iso_utc(checked_at),
                   "age_at_check_s": round((checked_at - scan_end).total_seconds(), 1),
                   "upload_minus_scan_end_s": round((pick.last_modified - scan_end).total_seconds(), 1)}

    reference = height_reference_statements(data["data_attrs"]) if args.product == "ACHAC" else []
    std_name = data["data_attrs"].get("standard_name")
    if args.product != "ACHAC":
        href = "not applicable (brightness temperature)"
    elif std_name in CF_HEIGHT_REFERENCE:
        href = f"{std_name}: {CF_HEIGHT_REFERENCE[std_name]}; the file text does not restate the datum"
    elif reference:
        href = "; ".join(reference)
    else:
        href = "unverified (no reference statement in the file's HT attributes)"

    geo_ref = data.get("geo_ref") or {}
    gl = geo_ref.get("geospatial_lat_lon_extent") or {}
    centre_check = None
    if gl:
        xm = 0.5 * (data["x"][0] + data["x"][-1])
        ym = 0.5 * (data["y"][0] + data["y"][-1])
        la_c, lo_c = scan_to_latlon(xm, ym, g)
        centre_check = {
            "file_lat_center": gl.get("geospatial_lat_center"),
            "file_lon_center": gl.get("geospatial_lon_center"),
            "file_lon_nadir": gl.get("geospatial_lon_nadir"),
            "computed_lat_center": round(float(la_c), 6),
            "computed_lon_center": round(float(lo_c), 6),
            "computed_with_lon0_deg": g.lon0_deg,
            "note": "centre of the grid from the middle of the first and last pixel centres",
        }
    dqf_file_percent = {k: v for k, v in data["dqf_attrs"].items() if str(k).startswith("percent_")}
    dqf_good_check = None
    fg = res["dqf"].get("full_grid") if res["dqf"].get("present") else None
    if dqf_file_percent and fg and fg["non_fill"]:
        key = "percent_good_quality_qf" if "percent_good_quality_qf" in dqf_file_percent else "percent_good_pixel_qf"
        if key in dqf_file_percent:
            computed = fg["good_dqf0"] / fg["non_fill"]
            dqf_good_check = {"file_attribute": key, "file_fraction": dqf_file_percent[key],
                              "computed_fraction_of_non_fill": round(computed, 9),
                              "difference": round(float(dqf_file_percent[key]) - computed, 9),
                              "note": "file values are float32 fractions, not percent"}

    out_png = os.path.abspath(args.out)
    out_json = os.path.splitext(out_png)[0] + ".json"
    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
    png_bytes = encode_png16(png)
    _atomic_write(out_png, png_bytes)
    runtime = time.monotonic() - t_start
    dx_deg, dy_deg = GRID_DEG, GRID_DEG
    lon_t, lat_t = target_axes(bbox)
    nx_t, ny_t = lon_t.size, lat_t.size
    proj_attrs = data["projection_attrs"]
    platform = pick.platform if pick else EXPECTED_PLATFORM[args.satellite]
    sat_name = {"G19": "GOES-19", "G18": "GOES-18"}.get(platform, platform)
    out = {
        "schema": SCHEMA,
        "script": "goes_cloud_height.py",
        "synthetic": bool(args.synthetic),
        "product": cfg["bucket_prefix"],
        "product_option": args.product,
        "variable": cfg["variable"],
        "satellite": args.satellite,
        "satellite_name": ("synthetic " + sat_name) if args.synthetic else sat_name,
        "bucket": bucket,
        "object_key": pick.key if pick else None,
        "object_url": object_url,
        "time_request": time_request,
        "file_scan_start_from_name": iso_utc(pick.scan_start) if pick else None,
        "satellite_longitude_deg": float(g.lon0_deg),
        "satellite_longitude_source": "goes_imager_projection longitude_of_projection_origin (the grid used "
                                      "for geolocation)",
        "nominal_satellite_subpoint_lon_deg": geo_ref.get("nominal_satellite_subpoint_lon_deg"),
        "perspective_point_height_m": float(g.height_m),
        "semi_major_axis_m": float(g.req_m),
        "semi_minor_axis_m": float(g.rpol_m),
        "sweep_angle_axis": g.sweep,
        "orbital_slot": ga.get("orbital_slot"),
        "time_coverage_start": t_start_attr,
        "time_coverage_end": t_end_attr,
        "bbox": {"lon_min": bbox[0], "lat_min": bbox[1], "lon_max": bbox[2], "lat_max": bbox[3]},
        "grid": {"dx_deg": dx_deg, "dy_deg": dy_deg, "nx": nx_t, "ny": ny_t,
                 "extent_lon": [round(bbox[0], 6), round(bbox[0] + nx_t * dx_deg, 6)],
                 "extent_lat": [round(bbox[3] - ny_t * dy_deg, 6), round(bbox[3], 6)],
                 "row_order": "north_to_south", "col_order": "west_to_east",
                 "resampling": "nearest neighbour in scan-angle space; cell centres",
                 "note": "0.02 degree cells are finer than the native pixel along the view tilt"},
        "native_grid": res["native_grid"],
        "units": cfg["units"],
        "quantity": cfg["quantity"],
        "scale": data["scale"],
        "offset": data["offset"],
        "fill_raw": data["fill"],
        "valid_range_raw": list(data["valid_range"]),
        "dqf": res["dqf"],
        "native_pixels_in_bbox": res["native_pixels_in_bbox"],
        "native_pixels_full_grid": res["native_pixels_full_grid"],
        "percent_native_bbox": res["percent_native_bbox"],
        "target_grid_counts": res["target_grid_counts"],
        "percent_target_grid": res["percent_target_grid"],
        "stats": res["stats"],
        "height_reference": href,
        "height_reference_statements": reference,
        "license_attribute": ga.get("license"),
        "centre_check": centre_check,
        "dqf_file_percent_attributes": dqf_file_percent,
        "dqf_good_check": dqf_good_check,
        "bytes_downloaded": {"listing": bytes_listing, "object": bytes_object,
                             "total": bytes_listing + bytes_object},
        "runtime_s": None,
        "timings_s": timings,
        "latency_s": latency,
        "note": NOTE_ACHA if args.product == "ACHAC" else NOTE_BT,
        "output": {"png": out_png, "json": out_json, "png_bytes": len(png_bytes),
                   "png_cells_with_value": res["png_cells_with_value"],
                   "png_value_encoding": ("height in metres, rounded, minimum 1; 0 = no data"
                                          if cfg["units"] == "m" else
                                          "brightness temperature in 0.1 K steps; 0 = no data")},
        "include_flagged_in_png": bool(args.include_flagged),
        "png_shows": PNG_SHOWN_LABEL + (" and flagged_with_value" if args.include_flagged else " only"),
        "projection_attrs_checked": {"sweep_angle_axis": g.sweep,
                                     "grid_mapping_name": proj_attrs.get("grid_mapping_name")},
        "data_attrs": {k: v for k, v in data["data_attrs"].items()
                       if k not in ("valid_range", "_FillValue", "scale_factor", "add_offset")},
        "dqf_attrs": {k: v for k, v in data["dqf_attrs"].items()},
        "limits": [
            "Satellite retrieval (cloud top height) or radiance-derived brightness temperature; not cloud base.",
            "Single scan; no time merge across scans; latency is measured for this file only.",
            "Nearest-neighbour resampling from a coarser native grid; blocks are native pixels.",
            "DQF-flagged values are reported separately and are not drawn unless --include-flagged.",
            "Not damage, not hail, not a probability, not an insurance or eligibility statement.",
        ],
    }
    out["runtime_s"] = round(runtime, 3)
    if args.synthetic:
        out["latency_s"] = None
        out["bytes_downloaded"] = {"listing": 0, "object": 0, "total": 0}
    _atomic_write(out_json, json.dumps(_clean(out), indent=2, allow_nan=False).encode("utf-8") + b"\n")
    out["_tcodes"] = res["_target_codes"]  # internal, not written
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Crop GOES ABI cloud-top height (ACHAC) or band 13 brightness temperature (CMIPC13) "
                    "to a 0.02 degree grid as a 16-bit PNG with a JSON sidecar. Run with python -I.")
    p.add_argument("--satellite", choices=sorted(BUCKETS), default="east",
                   help="east = GOES-19 (noaa-goes19), west = GOES-18 (noaa-goes18)")
    p.add_argument("--product", choices=sorted(PRODUCTS), default="ACHAC",
                   help="ACHAC = cloud-top height (HT, m); CMIPC13 = band 13 brightness temperature (CMI, K)")
    p.add_argument("--time", default="latest",
                   help="'latest', or YYYY-DDD-HH (UTC year, day of year, hour)")
    p.add_argument("--key", default=None, help="exact object key; overrides --time")
    p.add_argument("--bbox", default=",".join(str(v) for v in DEFAULT_BBOX),
                   help="lon_min,lat_min,lon_max,lat_max in degrees (default: Montana and border)")
    p.add_argument("--out", default="height.png", help="PNG path; the JSON sidecar gets the same stem")
    p.add_argument("--download-dir", default=None,
                   help="directory for the downloaded object (default: a new temporary directory)")
    p.add_argument("--keep-download", action="store_true", help="keep the downloaded .nc file")
    p.add_argument("--include-flagged", action="store_true",
                   help="also draw DQF-flagged values that carry a value (they are reported either way)")
    p.add_argument("--synthetic", action="store_true",
                   help="no network: a synthetic field on the GOES fixed grid, labelled synthetic")
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        bbox = parse_bbox(args.bbox)
        time_req = None if args.key else parse_time_arg(args.time)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        out = run(args, bbox=bbox, time_req=time_req, download_dir=args.download_dir)
    except (RuntimeError, ValueError, OSError, NotImplementedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    native = out["native_pixels_in_bbox"]
    print(f"{out['product']} {out['satellite_name']} {out['time_coverage_end'] or 'synthetic'}: "
          f"good {out['percent_native_bbox']['good']}% of native pixels in bbox, "
          f"flagged {native['flagged_with_value']} pixels, runtime {out['runtime_s']} s")
    print(f"PNG  {out['output']['png']}")
    print(f"JSON {out['output']['json']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
