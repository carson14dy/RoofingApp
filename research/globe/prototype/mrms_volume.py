#!/usr/bin/env python3
"""MRMS 3D reflectivity volume: crop, threshold and write compact JSON (globe research, Phase 0).

Research prototype for research/globe/README.md section 6 (phase 3). Not part of the app: the
desktop app never imports this file. Source: the MergedReflectivityQC 3D product in the public
bucket noaa-mrms-pds (facts in validation-evidence/mrms.json).

Pipeline
  1. Choose the step. "latest" takes the newest step that every requested level has within 60 s.
     A UTC time is joined to the nearest file on each level within 60 s, because stamps jitter by
     about 2 s between levels. A level with no file in that window is listed in missing_levels_km.
  2. Download each level's .grib2.gz into --download-dir with S3 REST list-type=2. The object size
     from the listing must equal the bytes received. gunzip, then check the GRIB2 header against
     the grid facts: Ni, Nj, first point, increments, scan modes, heightAboveSea level in metres,
     and the reference date and HHMM against the object name. Any mismatch stops the run.
  3. Decode with eccodes. Crop with index arithmetic: flat index = row * Ni + col, row 0 is 54.995 N
     and runs south, column 0 is 129.995 W and runs east. No full-grid latitude or longitude arrays
     are built. Count sentinel and valid cells, and keep the voxels at or above the threshold.
  4. Write compact JSON with the source, valid and retrieved times, the grid, codes and provenance.

Evidence rules (AGENTS.md rule 5)
  dBZ values are radar estimates. -999 and -99 are "no radar data"; which one means no echo and
  which means no coverage is not verified, so neither becomes a voxel or 0 dBZ. No voxel is not
  clear. A failed request or an undecodable file stops the run with no output. A level with no file
  is flagged, and the output is marked incomplete.

Usage (run from research/globe/prototype; the script reads downloaded files, so use -I).
Use the --bbox=... form, because a value that starts with "-" is otherwise read as an option.
  python -I mrms_volume.py --time latest --out volume.json
  python -I mrms_volume.py --time 20250615-231241 --levels all --threshold 35 --out volume-all.json
  python -I mrms_volume.py --synthetic --bbox=-110.8,46.2,-109.6,47.5 --levels 0.5,3,6,10 --threshold 40 --out fixture.json

Exit codes: 0 complete; 1 usage error; 2 data unavailable or a request or decode failure;
3 partial (some requested levels had no file at the join; output written and flagged).
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import http.client
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

TOOL_VERSION = "0.1"
BUCKET = "noaa-mrms-pds"
BUCKET_URL = "https://noaa-mrms-pds.s3.amazonaws.com/"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
USER_AGENT = "globe-prototype-mrms-volume/0.1 (research)"
PRODUCT = "MergedReflectivityQC"
SOURCE = BUCKET
NOTES = ("radar estimate; -99 and -999 are no radar data (meanings unverified); "
         "no echo is not clear")
SYNTHETIC_LABEL = "synthetic: not weather"
VOXEL_FORMAT = ("[i,j,k,dbz]: i=column W->E, j=row N->S (lat=origin.lat-j*dy, lon=origin.lon+i*dx), "
                "k=index in levels_km; dbz nearest 0.5, ties up")
OBJECT_FIELDS = "objects: km -> [key, bytes, GRIB2 level m, LastModified]"
CHECKS_TEXT = "gzip; listing size; one GRIB2 message; grid, scan, level, time"
JOIN_TOLERANCE_S = 60.0
SENTINEL_TOL = 0.05          # |value - code| below this is the code (dBZ steps are 0.1)
INDEX_EPS = 1e-6             # tolerance for fractional grid indices
DEFAULT_BBOX = (-116.8, 43.6, -103.3, 49.75)   # Montana and border
DEFAULT_LEVELS_TEXT = "0.5,1,2,3,4,5,6,8,10,12,15"
ALL_LEVELS_KM = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0,
                 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0,
                 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0)
SYNTHETIC_TIME = datetime(2000, 1, 1, tzinfo=timezone.utc)
DEFAULT_DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), ".cache", "globe-prototype",
                                    "mrms-volume")
EXIT_OK, EXIT_USAGE, EXIT_UNAVAILABLE, EXIT_PARTIAL = 0, 1, 2, 3

# Object names: CONUS/MergedReflectivityQC_00.50/20250615/MRMS_MergedReflectivityQC_00.50_20250615-231241.grib2.gz
OBJECT_RE = re.compile(r"MRMS_MergedReflectivityQC_(\d{2}\.\d{2})_(\d{8})-(\d{6})\.grib2\.gz$")


class MrmsError(RuntimeError):
    """A request, listing, download or file could not be read. The run stops without output."""


# ---------------------------------------------------------------------------
# Grid and crop (pure arithmetic, no network)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GridSpec:
    """Regular lat/lon grid in the MRMS layout: row 0 is the northern edge, column 0 the western edge."""
    ni: int          # columns, west to east
    nj: int          # rows, north to south
    lat0: float      # latitude of row 0 (cell centre)
    lon0: float      # longitude of column 0 (cell centre), -180..180
    dx: float        # degrees per column
    dy: float        # degrees per row

    def lat_of_row(self, j: float) -> float:
        return self.lat0 - j * self.dy

    def lon_of_col(self, i: float) -> float:
        return self.lon0 + i * self.dx

    def flat_index(self, j: int, i: int) -> int:
        return j * self.ni + i


# Facts from validation-evidence/mrms.json (eccodes header decode, 2025-06-15 and 2026-10-17 files).
MRMS_GRID = GridSpec(ni=7000, nj=3500, lat0=54.995, lon0=-129.995, dx=0.01, dy=0.01)


@dataclass(frozen=True)
class Crop:
    """Inclusive index range of the full grid whose cell centres lie inside the requested box."""
    i0: int
    i1: int
    j0: int
    j1: int
    clipped: bool    # the requested box extends beyond the grid

    @property
    def nx(self) -> int:
        return self.i1 - self.i0 + 1

    @property
    def ny(self) -> int:
        return self.j1 - self.j0 + 1


def crop_for_bbox(bbox: Sequence[float], grid: GridSpec = MRMS_GRID) -> Crop:
    """Index range of cell centres inside bbox = (lon_min, lat_min, lon_max, lat_max).

    Column i has longitude lon0 + i*dx, so the columns are ceil((lon_min - lon0)/dx) .. floor((lon_max - lon0)/dx).
    Row j has latitude lat0 - j*dy, so the rows are ceil((lat0 - lat_max)/dy) .. floor((lat0 - lat_min)/dy).
    """
    lon_min, lat_min, lon_max, lat_max = (float(v) for v in bbox)
    if not (lon_min < lon_max and lat_min < lat_max):
        raise ValueError("bbox needs lon_min < lon_max and lat_min < lat_max")
    x_lo = (lon_min - grid.lon0) / grid.dx        # fractional column of the west edge
    x_hi = (lon_max - grid.lon0) / grid.dx        # fractional column of the east edge
    y_lo = (grid.lat0 - lat_max) / grid.dy        # fractional row of the north edge
    y_hi = (grid.lat0 - lat_min) / grid.dy        # fractional row of the south edge
    clipped = (x_lo < -INDEX_EPS or x_hi > grid.ni - 1 + INDEX_EPS
               or y_lo < -INDEX_EPS or y_hi > grid.nj - 1 + INDEX_EPS)
    i0 = max(0, math.ceil(x_lo - INDEX_EPS))
    i1 = min(grid.ni - 1, math.floor(x_hi + INDEX_EPS))
    j0 = max(0, math.ceil(y_lo - INDEX_EPS))
    j1 = min(grid.nj - 1, math.floor(y_hi + INDEX_EPS))
    if i0 > i1 or j0 > j1:
        raise ValueError("bbox contains no cells of the MRMS grid")
    return Crop(i0=i0, i1=i1, j0=j0, j1=j1, clipped=clipped)


# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------

def level_tag(km: float) -> str:
    """Bucket label for a level: 0.5 -> '00.50', 19 -> '19.00'."""
    return f"{km:05.2f}"


def km_key(km: float) -> str:
    """JSON key for a level: 0.5 -> '0.5', 10 -> '10'."""
    return f"{km:g}"


def parse_levels(text: str) -> Tuple[float, ...]:
    if text.strip().lower() == "all":
        return ALL_LEVELS_KM
    out: List[float] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = float(part)
        except ValueError as exc:
            raise ValueError(f"not a height in km: {part!r}") from exc
        match = [lv for lv in ALL_LEVELS_KM if abs(lv - value) < 1e-6]
        if not match:
            raise ValueError(f"{part} km is not an MRMS 3D level; the 33 levels run 0.5 to 19 km "
                             "(0.25 km steps to 3, 0.5 to 9, 1 km to 19)")
        out.append(match[0])
    if not out:
        raise ValueError("no levels given")
    return tuple(sorted(set(out)))


def parse_bbox(text: str) -> Tuple[float, float, float, float]:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox needs four numbers: lon_min,lat_min,lon_max,lat_max")
    try:
        lon_min, lat_min, lon_max, lat_max = (float(p) for p in parts)
    except ValueError as exc:
        raise ValueError("--bbox values must be numbers") from exc
    if not (-180 <= lon_min < lon_max <= 180 and -90 <= lat_min < lat_max <= 90):
        raise ValueError("--bbox needs lon_min < lon_max and lat_min < lat_max, within -180..180 and -90..90")
    return (lon_min, lat_min, lon_max, lat_max)


def parse_time(text: str) -> Optional[datetime]:
    value = text.strip()
    if value.lower() == "latest":
        return None
    try:
        when = datetime.strptime(value, "%Y%m%d-%H%M%S")
    except ValueError as exc:
        raise ValueError("--time must be 'latest' or YYYYMMDD-HHMMSS in UTC, for example 20250615-231241") from exc
    return when.replace(tzinfo=timezone.utc)


def validate_threshold(threshold: float) -> float:
    """A threshold must sit above the sentinel codes, so -99 and -999 can never pass it."""
    if not (isinstance(threshold, (int, float)) and math.isfinite(threshold) and threshold > -90):
        raise ValueError("threshold must be a finite dBZ value above -90")
    return float(threshold)


def iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def floor_hour(when: datetime) -> datetime:
    return when.replace(minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Object names and listing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Obj:
    """One listed object: a level at one valid time."""
    km: float
    key: str
    size: int
    time: datetime
    last_modified: str


def object_key(km: float, when: datetime) -> str:
    tag = level_tag(km)
    day = when.strftime("%Y%m%d")
    return (f"CONUS/MergedReflectivityQC_{tag}/{day}/"
            f"MRMS_MergedReflectivityQC_{tag}_{day}-{when.strftime('%H%M%S')}.grib2.gz")


def parse_object_key(key: str) -> Tuple[float, datetime]:
    match = OBJECT_RE.search(key)
    if not match:
        raise ValueError(f"not an MRMS MergedReflectivityQC object name: {key}")
    tag, day, hms = match.groups()
    when = datetime.strptime(day + hms, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    return float(tag), when


def hour_prefix(km: float, when: datetime) -> str:
    tag = level_tag(km)
    day = when.strftime("%Y%m%d")
    return f"CONUS/MergedReflectivityQC_{tag}/{day}/MRMS_MergedReflectivityQC_{tag}_{day}-{when.strftime('%H')}"


def _open(url: str, timeout: float):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    return True


def _http_bytes(url: str, timeout: float, attempts: int = 3) -> bytes:
    last: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            with _open(url, timeout) as response:
                return response.read()
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            last = exc
            if not _retryable(exc):
                break
        if attempt < attempts:
            time.sleep(2 ** attempt)
    raise MrmsError(f"GET {url} failed after {attempts} attempt(s): {last}")


def _download_to(url: str, dest: str, timeout: float, attempts: int = 3) -> int:
    last: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            with _open(url, timeout) as response, open(dest, "wb") as out:
                shutil.copyfileobj(response, out, 1 << 20)
            return os.path.getsize(dest)
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            last = exc
            if not _retryable(exc):
                break
        if attempt < attempts:
            time.sleep(2 ** attempt)
    raise MrmsError(f"download {url} failed after {attempts} attempt(s): {last}")


def list_objects(prefix: str, timeout: float) -> Tuple[List[Tuple[str, int, str]], int]:
    """All (key, size, LastModified) under prefix, following continuation tokens. Also returns listing bytes."""
    rows: List[Tuple[str, int, str]] = []
    listed = 0
    token: Optional[str] = None
    for _ in range(100):
        query = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            query["continuation-token"] = token
        body = _http_bytes(BUCKET_URL + "?" + urllib.parse.urlencode(query), timeout)
        listed += len(body)
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise MrmsError(f"listing {prefix!r} is not XML: {exc}") from exc
        if root.tag != S3_NS + "ListBucketResult":
            raise MrmsError(f"listing {prefix!r} has an unexpected XML root: {root.tag}")
        for node in root.findall(S3_NS + "Contents"):
            key = node.findtext(S3_NS + "Key")
            size = node.findtext(S3_NS + "Size")
            modified = node.findtext(S3_NS + "LastModified") or ""
            if not key or size is None:
                raise MrmsError(f"listing {prefix!r} has a row without Key or Size")
            rows.append((key, int(size), modified))
        if root.findtext(S3_NS + "IsTruncated", "false") != "true":
            return rows, listed
        token = root.findtext(S3_NS + "NextContinuationToken")
        if not token:
            raise MrmsError(f"listing {prefix!r} is truncated without a continuation token")
    raise MrmsError(f"listing {prefix!r} did not finish within 100 pages")


def objects_for_hours(km: float, hours: Sequence[datetime], timeout: float) -> Tuple[List[Obj], int]:
    """Objects for one level in the listed UTC hours, sorted by valid time. Also returns listing bytes."""
    found: Dict[str, Obj] = {}
    listed = 0
    for hour in sorted(set(hours)):
        rows, nbytes = list_objects(hour_prefix(km, hour), timeout)
        listed += nbytes
        for key, size, modified in rows:
            try:
                file_km, when = parse_object_key(key)
            except ValueError:
                continue
            if abs(file_km - km) > 1e-6:
                continue
            found[key] = Obj(km=km, key=key, size=size, time=when, last_modified=modified)
    return sorted(found.values(), key=lambda o: o.time), listed


# ---------------------------------------------------------------------------
# Joining levels in time
# ---------------------------------------------------------------------------

def nearest_within(objs: Sequence[Obj], target: datetime, tol_s: float = JOIN_TOLERANCE_S) -> Optional[Obj]:
    """Nearest object to target within tol_s seconds; a tie goes to the earlier file. None if none is that close."""
    best: Optional[Obj] = None
    best_gap = 0.0
    for obj in objs:
        gap = abs((obj.time - target).total_seconds())
        if gap > tol_s + 1e-9:
            continue
        if best is None or gap < best_gap or (gap == best_gap and obj.time < best.time):
            best, best_gap = obj, gap
    return best


def latest_common_step(per_level: Dict[float, Sequence[Obj]], levels: Sequence[float],
                       tol_s: float = JOIN_TOLERANCE_S, max_candidates: int = 6
                       ) -> Tuple[Optional[datetime], Dict[float, Obj]]:
    """Newest candidate time (from the lowest level) at which every level has a file within tol_s."""
    if not levels:
        return None, {}
    reference = levels[0]
    candidates = sorted({o.time for o in per_level[reference]}, reverse=True)
    for when in candidates[:max_candidates]:
        picks: Dict[float, Obj] = {}
        for km in levels:
            found = nearest_within(per_level[km], when, tol_s)
            if found is None:
                break
            picks[km] = found
        else:
            return when, picks
    return None, {}


# ---------------------------------------------------------------------------
# Download and file checks
# ---------------------------------------------------------------------------

def looks_like_gzip(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(2) == b"\x1f\x8b"
    except OSError:
        return False


def fetch_level(obj: Obj, download_dir: str, timeout: float) -> Tuple[str, int, bool]:
    """Download one object into download_dir. Returns (path, bytes received, from_cache)."""
    gz_path = os.path.join(download_dir, os.path.basename(obj.key))
    if os.path.isfile(gz_path) and os.path.getsize(gz_path) == obj.size and looks_like_gzip(gz_path):
        return gz_path, 0, True
    part = gz_path + ".part"
    got = _download_to(BUCKET_URL + urllib.parse.quote(obj.key), part, timeout)
    if got != obj.size:
        os.remove(part)
        raise MrmsError(f"{obj.key}: received {got} bytes, the listing says {obj.size}")
    if not looks_like_gzip(part):
        os.remove(part)
        raise MrmsError(f"{obj.key}: download is not gzip data")
    os.replace(part, gz_path)
    return gz_path, got, False


def gunzip(gz_path: str) -> str:
    out_path = gz_path[:-3] if gz_path.endswith(".gz") else gz_path + ".grib2"
    tmp = out_path + ".part"
    try:
        with gzip.open(gz_path, "rb") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise MrmsError(f"{gz_path}: gunzip failed: {exc}") from exc
    os.replace(tmp, out_path)
    return out_path


@contextlib.contextmanager
def _c_stderr_silenced():
    """Silence C-level stderr (fd 2) for one call.

    eccodes prints 'Truncating time: non-zero seconds ... ignored' on every MRMS file, because the
    GRIB2 header keeps HHMM only. The minute is checked instead, so the message is dropped here.
    """
    with contextlib.suppress(Exception):
        sys.stderr.flush()
    saved = os.dup(2)
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, 2)
            yield
        finally:
            os.dup2(saved, 2)
            os.close(devnull)
    finally:
        os.close(saved)


def _wrap_lon(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0


def _check_message(ecc, handle, obj: Obj, grid: GridSpec) -> dict:
    """Compare the GRIB2 header with the grid facts and the object name. Raises MrmsError on any mismatch."""
    get = lambda key: ecc.codes_get(handle, key)  # noqa: E731
    ni, nj = int(get("Ni")), int(get("Nj"))
    n_values = int(get("numberOfValues"))
    lat_first = float(get("latitudeOfFirstGridPointInDegrees"))
    lon_first = _wrap_lon(float(get("longitudeOfFirstGridPointInDegrees")))
    di = float(get("iDirectionIncrementInDegrees"))
    dj = float(get("jDirectionIncrementInDegrees"))
    j_pos = int(get("jScansPositively"))
    i_neg = int(get("iScansNegatively"))
    type_of_level = str(get("typeOfLevel"))
    level_m = int(get("level"))
    data_date = int(get("dataDate"))
    with _c_stderr_silenced():
        data_hhmm = int(get("dataTime"))
    checks = [
        ((ni, nj) == (grid.ni, grid.nj), f"grid {ni} x {nj}, expected {grid.ni} x {grid.nj}"),
        (n_values == grid.ni * grid.nj, f"numberOfValues {n_values}"),
        (abs(lat_first - grid.lat0) < 1e-6, f"first latitude {lat_first}"),
        (abs(lon_first - grid.lon0) < 1e-6, f"first longitude {lon_first}"),
        (abs(di - grid.dx) < 1e-6 and abs(dj - grid.dy) < 1e-6, f"increments {di}, {dj}"),
        (j_pos == 0 and i_neg == 0, f"scan modes jScansPositively={j_pos} iScansNegatively={i_neg}"),
        (type_of_level == "heightAboveSea" and level_m == int(round(obj.km * 1000)),
         f"level {type_of_level} {level_m} m, expected {obj.km:g} km"),
        (data_date == int(obj.time.strftime("%Y%m%d"))
         and data_hhmm == obj.time.hour * 100 + obj.time.minute,
         f"reference {data_date} {data_hhmm:04d}, object time {obj.time.strftime('%Y%m%d %H%M%S')}"),
    ]
    bad = [message for ok, message in checks if not ok]
    if bad:
        raise MrmsError(f"{obj.key}: GRIB2 header does not match the grid facts: " + "; ".join(bad))
    return {"grib_level_m": level_m, "reference_date": data_date, "reference_hhmm": data_hhmm}


def decode_message(fileobj, obj: Obj, grid: GridSpec, crop: Crop) -> Tuple[np.ndarray, dict]:
    """Decode the single GRIB2 message in a file and return (cropped dBZ array [ny, nx], meta).

    The array is indexed [row - j0, column - i0]; row 0 is the northern edge of the crop.
    """
    import eccodes  # imported here so the synthetic path and the unit tests do not need it

    handle = eccodes.codes_grib_new_from_file(fileobj)
    if handle is None:
        raise MrmsError(f"{obj.key}: no GRIB2 message in the file")
    try:
        extra = eccodes.codes_grib_new_from_file(fileobj)
        if extra is not None:
            eccodes.codes_release(extra)
            raise MrmsError(f"{obj.key}: more than one GRIB2 message in the file")
        meta = _check_message(eccodes, handle, obj, grid)
        values = eccodes.codes_get_double_array(handle, "values")
    finally:
        eccodes.codes_release(handle)
    flat = np.asarray(values, dtype=np.float64)
    if flat.size != grid.ni * grid.nj:
        raise MrmsError(f"{obj.key}: {flat.size} values, expected {grid.ni * grid.nj}")
    field = flat.reshape(grid.nj, grid.ni)                       # flat index = row * Ni + col
    cropped = field[crop.j0:crop.j1 + 1, crop.i0:crop.i1 + 1].copy()
    meta["first_flat_index"] = grid.flat_index(crop.j0, crop.i0)
    return cropped, meta


# ---------------------------------------------------------------------------
# Codes, threshold and voxels (pure numpy)
# ---------------------------------------------------------------------------

def classify(arr: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Boolean masks: (-999 code, -99 code, valid dBZ, non-finite). Sentinels are never valid."""
    finite = np.isfinite(arr)
    s999 = finite & (np.abs(arr + 999.0) < SENTINEL_TOL)
    s99 = finite & (np.abs(arr + 99.0) < SENTINEL_TOL)
    valid = finite & ~s999 & ~s99
    return s999, s99, valid, ~finite


def level_codes(arr: np.ndarray) -> dict:
    """Counts per level. A non-finite cell is an error, not a count: the field is not trusted."""
    s999, s99, valid, nonfinite = classify(arr)
    n_bad = int(np.count_nonzero(nonfinite))
    if n_bad:
        raise MrmsError(f"{n_bad} non-finite cells in the crop; the level is not trusted")
    vals = arr[valid]
    return {
        "-999": int(np.count_nonzero(s999)),
        "-99": int(np.count_nonzero(s99)),
        "valid": int(np.count_nonzero(valid)),
        "min_valid": None if vals.size == 0 else round(float(vals.min()), 1),
        "max_valid": None if vals.size == 0 else round(float(vals.max()), 1),
    }


def round_half_step(value: float) -> float:
    """Nearest 0.5 dBZ; exact ties round up (toward +infinity)."""
    return math.floor(value * 2.0 + 0.5) / 2.0


def _json_number(value: float):
    return int(value) if value == int(value) else value


def level_voxels(arr: np.ndarray, k: int, threshold: float) -> List[list]:
    """[i, j, k, dbz] for valid cells at or above the threshold (inclusive); selection uses the raw value."""
    validate_threshold(threshold)
    _, _, valid, _ = classify(arr)
    selected = valid & (arr >= threshold)
    jj, ii = np.nonzero(selected)
    rounded = np.floor(arr[jj, ii] * 2.0 + 0.5) / 2.0
    return [[i, j, k, _json_number(v)]
            for i, j, v in zip(ii.tolist(), jj.tolist(), rounded.tolist())]


# ---------------------------------------------------------------------------
# Synthetic grid (no network): a storm-shaped test field, labelled as not weather
# ---------------------------------------------------------------------------

SYN_CENTRE = (46.9, -110.2)     # lat, lon of the test core at 0 km
SYN_BACKGROUND_DBZ = -10.0      # valid weak background, well below any threshold used here


def synthetic_level(km: float, crop: Crop, grid: GridSpec = MRMS_GRID) -> np.ndarray:
    """Storm-shaped dBZ on the crop's cell centres (same lattice as the real grid), shape [ny, nx]."""
    rows = np.arange(crop.j0, crop.j1 + 1, dtype=np.float64)
    cols = np.arange(crop.i0, crop.i1 + 1, dtype=np.float64)
    lat = (grid.lat0 - rows * grid.dy)[:, None]
    lon = (grid.lon0 + cols * grid.dx)[None, :]
    c_lat = SYN_CENTRE[0] - 0.01 * km           # the test core leans north-west with height
    c_lon = SYN_CENTRE[1] - 0.03 * km
    sigma = 0.10 + 0.01 * km
    peak = 62.0 - 1.5 * km
    d2 = ((lat - c_lat) / sigma) ** 2 + ((lon - c_lon) / sigma) ** 2
    dbz = SYN_BACKGROUND_DBZ + (peak - SYN_BACKGROUND_DBZ) * np.exp(-0.5 * d2)
    dbz = np.array(dbz, dtype=np.float64)
    # Sentinel patches, so the no-data handling is visible: the east 15 % is -999, the north 5 % is -99.
    col_frac = np.arange(crop.nx) / max(crop.nx - 1, 1)
    row_frac = np.arange(crop.ny) / max(crop.ny - 1, 1)
    dbz[:, col_frac > 0.85] = -999.0
    dbz[row_frac < 0.05, :] = -99.0
    return dbz


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def grid_block(grid: GridSpec, crop: Crop, levels: Sequence[float], bbox: Sequence[float]) -> dict:
    """Crop description: origin = centre of cell [0, 0]; the other cell centres follow from dx, dy."""
    lat_top = grid.lat_of_row(crop.j0)
    lon_left = grid.lon_of_col(crop.i0)
    return {
        "origin": {"lat": round(lat_top, 6), "lon": round(lon_left, 6)},
        "dx": grid.dx,
        "dy": grid.dy,
        "nx": crop.nx,
        "ny": crop.ny,
        "bbox_requested": {"lon_min": bbox[0], "lat_min": bbox[1], "lon_max": bbox[2], "lat_max": bbox[3]},
        "full_grid_index": {"i0": crop.i0, "i1": crop.i1, "j0": crop.j0, "j1": crop.j1,
                            "ni": grid.ni, "nj": grid.nj},
        "clipped_to_grid": crop.clipped,
        "levels_km": [float(km) for km in levels],
        "level_reference": "heightAboveSea (MSL); km = GRIB2 metres / 1000",
    }


def build_output(*, levels, bbox, crop, grid, threshold, valid_times, join_time, join_spread_s,
                 retrieved, decoded, voxels, bytes_downloaded, timing, provenance, synthetic) -> dict:
    missing = [km for km in levels if valid_times.get(km) is None]
    out = {}
    if synthetic:
        out["label"] = SYNTHETIC_LABEL
    out["product"] = "synthetic" if synthetic else PRODUCT
    out["source"] = "synthetic" if synthetic else SOURCE
    out["join_time_utc"] = iso(join_time)
    out["join_spread_s"] = join_spread_s
    out["valid_time_utc"] = {km_key(km): (iso(valid_times[km]) if valid_times.get(km) else None)
                             for km in levels}
    out["retrieved_time_utc"] = iso(retrieved)
    out["complete"] = not missing
    out["missing_levels_km"] = [float(km) for km in missing]
    out["grid"] = grid_block(grid, crop, levels, bbox)
    out["threshold_dbz"] = threshold
    out["codes"] = {km_key(km): decoded[km] for km in levels if km in decoded}
    out["voxel_format"] = VOXEL_FORMAT
    out["voxels"] = voxels
    out["bytes_downloaded"] = bytes_downloaded
    out["timing_s"] = timing
    out["provenance"] = provenance
    out["notes"] = (SYNTHETIC_LABEL + "; " + NOTES) if synthetic else NOTES
    return out


def _sum_codes(codes: Dict[str, dict], key: str) -> int:
    return sum(int(entry[key]) for entry in codes.values())


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------

def run_synthetic(*, levels, bbox, crop, threshold, target, retrieved) -> dict:
    t_start = time.perf_counter()
    join = target or SYNTHETIC_TIME
    decoded: Dict[float, dict] = {}
    voxels: List[list] = []
    t_vox = 0.0
    for k, km in enumerate(levels):
        arr = synthetic_level(km, crop)
        t0 = time.perf_counter()
        decoded[km] = level_codes(arr)
        level_vox = level_voxels(arr, k, threshold)
        t_vox += time.perf_counter() - t0
        voxels.extend(level_vox)
    provenance = {
        "generator": "synthetic_level() in mrms_volume.py: storm-shaped test field, no network",
        "tool": f"mrms_volume.py {TOOL_VERSION}",
        "numpy": np.__version__,
        "time_mode": "requested" if target else "synthetic default time",
    }
    timing = {"generate_and_threshold": round(time.perf_counter() - t_start, 3),
              "voxels": round(t_vox, 3)}
    return build_output(levels=levels, bbox=bbox, crop=crop, grid=MRMS_GRID, threshold=threshold,
                        valid_times={km: join for km in levels}, join_time=join, join_spread_s=0,
                        retrieved=retrieved, decoded=decoded, voxels=voxels,
                        bytes_downloaded=0, timing=timing, provenance=provenance, synthetic=True)


def run_real(*, levels, bbox, crop, threshold, target, retrieved, download_dir, workers, timeout) -> dict:
    import eccodes  # only the real path needs it

    t_start = time.perf_counter()
    if target is None:
        hours = [floor_hour(retrieved - timedelta(hours=1)), floor_hour(retrieved)]
    else:
        hours = [floor_hour(target - timedelta(seconds=JOIN_TOLERANCE_S)),
                 floor_hour(target + timedelta(seconds=JOIN_TOLERANCE_S))]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        listed = list(pool.map(lambda km: objects_for_hours(km, hours, timeout), levels))
    per_level = {km: objs for km, (objs, _) in zip(levels, listed)}
    bytes_listed = sum(nbytes for _, nbytes in listed)
    if target is None:
        join, picks = latest_common_step(per_level, levels)
        if join is None:
            raise MrmsError("no step in the last two hours has a file within 60 s on every requested "
                            "level; no output written")
    else:
        join = target
        picks = {km: nearest_within(per_level[km], target) for km in levels}
        picks = {km: obj for km, obj in picks.items() if obj is not None}
        if not picks:
            raise MrmsError(f"no file within 60 s of {iso(target)} on any requested level; "
                            "no output written")
    t_list = time.perf_counter() - t_start

    present = [picks[km] for km in levels if km in picks]
    os.makedirs(download_dir, exist_ok=True)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda o: fetch_level(o, download_dir, timeout), present))
    t_download = time.perf_counter() - t0
    fetched = {obj.km: res for obj, res in zip(present, results)}
    bytes_downloaded = sum(n for _, n, _ in fetched.values())

    decoded: Dict[float, dict] = {}
    voxels: List[list] = []
    objects_info: Dict[str, list] = {}
    t_decode = 0.0
    t_vox = 0.0
    for k, km in enumerate(levels):
        if km not in picks:
            continue
        obj = picks[km]
        gz_path, _, _ = fetched[km]
        t0 = time.perf_counter()
        grib_path = gunzip(gz_path)
        with open(grib_path, "rb") as fh:
            arr, meta = decode_message(fh, obj, MRMS_GRID, crop)
        t_decode += time.perf_counter() - t0
        t0 = time.perf_counter()
        decoded[km] = level_codes(arr)
        level_vox = level_voxels(arr, k, threshold)
        t_vox += time.perf_counter() - t0
        voxels.extend(level_vox)
        modified = obj.last_modified.replace(".000Z", "Z")
        objects_info[km_key(km)] = [obj.key, obj.size, meta["grib_level_m"], modified]
    times = [picks[km].time for km in levels if km in picks]
    join_spread = int(round((max(times) - min(times)).total_seconds())) if times else 0
    provenance = {
        "bucket": BUCKET,
        "time_mode": "latest" if target is None else "requested",
        "join_tolerance_s": JOIN_TOLERANCE_S,
        "objects_fields": OBJECT_FIELDS,
        "objects": objects_info,
        "checks": CHECKS_TEXT,
        "tool": f"mrms_volume.py {TOOL_VERSION}",
        "eccodes": eccodes.__version__,
        "numpy": np.__version__,
    }
    timing = {"list": round(t_list, 3), "download": round(t_download, 3), "decode": round(t_decode, 3),
              "voxels": round(t_vox, 3), "bytes_listed": bytes_listed}
    return build_output(levels=levels, bbox=bbox, crop=crop, grid=MRMS_GRID, threshold=threshold,
                        valid_times={km: (picks[km].time if km in picks else None) for km in levels},
                        join_time=join, join_spread_s=join_spread, retrieved=retrieved, decoded=decoded,
                        voxels=voxels, bytes_downloaded=bytes_downloaded,
                        timing=timing, provenance=provenance, synthetic=False)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crop and threshold an MRMS MergedReflectivityQC 3D volume (research prototype).")
    parser.add_argument("--time", default="latest",
                        help="'latest' or YYYYMMDD-HHMMSS in UTC (levels joined to the nearest file within 60 s)")
    parser.add_argument("--levels", default=DEFAULT_LEVELS_TEXT,
                        help="'all' (33 levels) or a comma list of heights in km")
    parser.add_argument("--bbox", default=",".join(str(v) for v in DEFAULT_BBOX),
                        help="lon_min,lat_min,lon_max,lat_max (default: Montana and border); use --bbox=...")
    parser.add_argument("--threshold", type=float, default=20.0,
                        help="dBZ; voxels are at or above the threshold (inclusive)")
    parser.add_argument("--out", default="volume.json", help="output JSON path")
    parser.add_argument("--synthetic", action="store_true",
                        help="no network: built-in storm-shaped test grid, labelled as not weather")
    parser.add_argument("--download-dir", default=DEFAULT_DOWNLOAD_DIR,
                        help="directory for .grib2.gz downloads (use a fresh directory; never commit it)")
    parser.add_argument("--note", default="",
                        help="free text stored in provenance.note (used to describe a cut sample)")
    parser.add_argument("--workers", type=int, default=4, help="parallel listings and downloads")
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds per HTTP request")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        levels = parse_levels(args.levels)
        bbox = parse_bbox(args.bbox)
        target = parse_time(args.time)
        threshold = validate_threshold(args.threshold)
        crop = crop_for_bbox(bbox)
        if args.workers < 1:
            raise ValueError("--workers must be at least 1")
    except ValueError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    retrieved = datetime.now(timezone.utc).replace(microsecond=0)
    t_run = time.perf_counter()
    try:
        if args.synthetic:
            out = run_synthetic(levels=levels, bbox=bbox, crop=crop, threshold=threshold,
                                target=target, retrieved=retrieved)
        else:
            out = run_real(levels=levels, bbox=bbox, crop=crop, threshold=threshold, target=target,
                           retrieved=retrieved, download_dir=args.download_dir,
                           workers=args.workers, timeout=args.timeout)
    except MrmsError as exc:
        print(f"data unavailable: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    except (OSError, ValueError) as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    out["runtime_s"] = round(time.perf_counter() - t_run, 2)
    if args.note:
        out["provenance"]["note"] = args.note

    t_write = time.perf_counter()
    text = json.dumps(out, separators=(",", ":"), ensure_ascii=True)
    with open(args.out, "w", encoding="ascii") as fh:
        fh.write(text)
    output_bytes = os.path.getsize(args.out)
    write_s = time.perf_counter() - t_write

    codes = out["codes"]
    print("mrms_volume: join=%s levels=%d/%d threshold=%g dBZ voxels=%d -999=%d -99=%d valid=%d "
          "bytes_downloaded=%d output_bytes=%d runtime_s=%.2f (decode_s=%s voxels_s=%s write_s=%.3f) "
          "complete=%s%s" % (
              out["join_time_utc"], len(levels) - len(out["missing_levels_km"]), len(levels),
              threshold, len(out["voxels"]), _sum_codes(codes, "-999"), _sum_codes(codes, "-99"),
              _sum_codes(codes, "valid"), out["bytes_downloaded"], output_bytes, out["runtime_s"],
              out["timing_s"].get("decode", "n/a"), out["timing_s"].get("voxels", "n/a"), write_s,
              str(out["complete"]).lower(),
              (" missing_levels_km=" + ",".join(km_key(v) for v in out["missing_levels_km"]))
              if out["missing_levels_km"] else ""))
    return EXIT_OK if out["complete"] else EXIT_PARTIAL


if __name__ == "__main__":
    sys.exit(main())
