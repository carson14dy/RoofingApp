"""Live hail swath layers for the map page (B4; the decisions are in the B4 brief, D1 to D6).

NOAA's MRMS MESH swath products give, for each 0.01 degree cell of the CONUS grid, the largest hail size the radar
estimated over a window: the last 60 minutes (a file every 2 minutes, parameter 30) or the last 1,440 minutes (a file
every 30 minutes, parameter 34). This module takes the newest file of each product and draws it as one palette PNG on
the map's image box (gridded.IMAGE_BOUNDS), with one picture column per grid column and more picture rows than grid
rows (Mercator), and writes the cells at or above 0.25 in, and the no-coverage cells, as small per-tile JSON files in
the folder of the frame's valid time (hail/live/<window>/<YYYYMMDDHHMM>/<tile>.json, D14), so a click reads its value
without a second decode.

A RADAR ESTIMATE. It is not observed hail, not a measurement at the ground and not damage. Uncoloured means no estimate
of 0.25 in or more, never "no hail". -1 (missing) is uncoloured; -3 (no coverage) is hatched. Units and codes are
NOAA's MRMS GRIB2 user table: millimetres; -1 missing; -3 no coverage. The header's own units and name read "unknown"
to pygrib, so a file is identified by its discipline (209), category (3) and parameter number (30 or 34).

    frames, files, states = collect(now, None, out_dir, towns)                      # live: NOAA buckets on S3 (the site build)
    frames, files, states = collect(now, cache_dir, out_dir, towns, sample=True)    # invented field, no network
    frames, files, states = collect(now, cache_dir, out_dir, towns, offline=True)   # the newest cached files only
    blocks = map_data_swath(frames)                       # data/map.json "hail_60" and "hail_1440"
    lines = describe(frames["hail_60"], now, towns)       # the List view and the no-JavaScript panel
    words = sheet_line(60, tenths, valid, state, state_line)  # the sheet's line for one clicked cell

`get(url, headers=None) -> (bytes | None, error | None)` defaults to the site's Fetcher.binary (its user agent and
retries). Every request is recorded in the layer's ledger ("requests"). Nothing here raises to the build: a failed
listing, download, header check or decode is an unavailable layer with its reason in plain words. pygrib is imported
only where a file is decoded, so the tests run without it. Feed details: sources.CONTRACTS "hail_swath".
"""
from __future__ import annotations

import argparse
import gzip
import html
import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

import numpy as np

from . import gridded
from . import hail as hs
from . import sample as sample_data
from . import sources as src

UTC = timezone.utc
MT = gridded.MT
HERE = Path(__file__).resolve().parent

BUCKET = "https://noaa-mrms-pds.s3.amazonaws.com/"
ROOT = "CONUS"                              # the bucket folder of the CONUS grid
STYLE = "hail_swath"                        # gridded.STYLE: the B1 size classes as bands of colour
WIDTH = 1750                                # one picture column per grid column: 0.01 degree across the box
LIVE_DIR = "hail/live"                      # under the site root: hail/live/<window>/<YYYYMMDDHHMM>/<tile>.json (D14)
LIVE_FORMAT = "hail-live-v1"
LABEL = "Hail swath (radar estimate)"       # the build's status label
DISCIPLINE, CATEGORY = 209, 3               # NOAA MRMS (the user table's discipline and category)
NI, NJ = 7000, 3500                         # the B1 grid: 7,000 columns by 3,500 rows
FIRST_LAT, FIRST_LON = 54.995, 230.005      # the first point (row 0, column 0); longitudes are stored 0 to 360
LAST_LAT, LAST_LON = 20.005, 299.995
STEP_DEG = 0.01
FUTURE_TOLERANCE = timedelta(minutes=5)     # a file stamped this far after the build's clock is not used
EARTH_MILES = 3958.8
LARGE_TENTHS = hs.NOTE_TENTHS                # 4.00 in: the review note (B1)
CLASS_MINS = np.array([c["min_tenths"] for c in hs.CLASSES], dtype=np.int64)


class SwathError(ValueError):
    """A file or a request that cannot be used. The message is the plain reason the layer shows; it has no full stop.
    detail, when given, is the technical reason (a GRIB number, an exception name): it goes to the layer's record and
    never to the page."""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.detail = detail


class Product(NamedTuple):
    key: str            # the layer key in data/map.json
    window: int         # minutes
    folder: str         # the bucket folder, and the product name in the file names
    parameter: int      # the GRIB parameter number (D2): 30 is 60 minutes, 34 is 1,440 minutes
    every: timedelta    # the file cadence
    fresh: timedelta    # D6: fresh within this age of the valid time
    stale: timedelta    # D6: stale up to this age; unavailable beyond it
    window_word: str    # "hour" or "24 hours", as the words say it
    span: str           # "the last hour" or "the last 24 hours", for the reasons
    title: str          # "Hail, last hour" or "Hail, last 24 hours"


PRODUCTS = (
    Product("hail_60", 60, "MESH_Max_60min_00.50", 30, timedelta(minutes=2), timedelta(minutes=20),
            timedelta(minutes=60), "hour", "the last hour", "Hail, last hour"),
    Product("hail_1440", 1440, "MESH_Max_1440min_00.50", 34, timedelta(minutes=30), timedelta(minutes=60),
            timedelta(minutes=120), "24 hours", "the last 24 hours", "Hail, last 24 hours"),
)
PRODUCT_BY_KEY = {p.key: p for p in PRODUCTS}
PARAMETER_WINDOW = {p.parameter: p.window for p in PRODUCTS}

# Every sentence and template the swath layers show. Placeholders are in braces. Dates and times are Montana time
# (valid_text); sizes are inches to the hundredth, rounded down, with the millimetres exact (hail.inches, mm_text).
WORDS_SWATH = {
    "legend_note": ("Radar estimate of the largest hail in the last {window}, in inches (NOAA MRMS MESH). An estimate, "
                    "not observed hail and not damage."),
    "sample_legend_note": ("Sample: invented field, not NOAA MRMS MESH. Radar estimate of the largest hail in the last "
                           "{window}, in inches. An estimate, not observed hail and not damage."),
    "uncoloured": ("Uncoloured: no radar hail estimate of 0.25 in or more in the last {window}, or no value; NOAA's data "
                   "does not tell the two apart."),
    "hatched": "Hatched: no radar coverage.",
    "outside": ("Outside this map's area, which covers {south} to {north} degrees north and {west} to {east} degrees "
                "west. Nothing is drawn here, so no estimate is shown."),
    "outside_montana_live": "Outside Montana: no radar estimate is shown for this spot.",
    "live_line": ("In the last {window}: {in} in ({mm} mm), {class}, the largest radar estimate for the period ending "
                  "{valid}."),
    "no_estimate": "No radar hail estimate of 0.25 in or more in the last {window} here (as of {valid}).",
    "no_coverage": "No radar coverage at this point in the product.",
    "fresh": "Valid {valid}, {age} min ago.",
    "timeline_fresh": "Radar estimate, {age} min ago.",                 # the timeline's line: no clock time of its own
    "stale": ("Valid {valid}, {age} min ago. That is more than {limit} minutes old, so it may be out of date. "
              "This is not an all-clear."),
    "timeline_stale": ("Radar estimate, {age} min ago, more than {limit} minutes old, so it may be out of date. "
                       "This is not an all-clear."),
    "unavailable": "{title} is unavailable: {problem}. This is not an all-clear.",
    "all_clear": "This is not an all-clear.",
    "age_out": "the newest file is {age} min old, more than {limit} min",
    "sample_state": "SAMPLE: invented field, valid {valid}.",
    "sample_sheet": "SAMPLE: invented values, not NOAA data.",
    "lead_largest": ("Largest radar estimate in Montana: {in} in ({mm} mm), {class}. It is at {where}, "
                     "{miles} miles from {town}."),
    "lead_largest_no_town": "Largest radar estimate in Montana: {in} in ({mm} mm), {class}. It is at {where}.",
    "lead_none": ("No cell in Montana has a radar hail estimate of 0.25 in or more in the last {window}. That "
                  "is not the same as no hail."),
    # D15, D19, D21: the box reaches into Canada, so each count and largest value the words give is Montana's; the
    # one sentence about a larger value outside Montana names this map's area (DECISIONS D37).
    "montana_count": "Cells with a radar estimate of 0.25 in or more in Montana: {n}.",
    "montana_outside": "The largest value in this map's area, {in} in, is outside Montana.",
    "large_note": "Unusually large for a radar estimate; treat with care.",
    "what_this_is": ("MESH (maximum estimated size of hail) is a radar estimate at the grid cell, about 0.7 miles north "
                     "to south and 0.5 miles east to west. It is not a measurement at the ground, not observed hail and "
                     "not damage."),
    "source": "Source: NOAA MRMS MESH, {folder}, CONUS grid, NOAA Open Data on AWS. Valid {valid}.",
    "sample_source": "SAMPLE: invented radar estimate, not NOAA data.",
    "as_of_build": "As of the build at {time}.",
}


# ---------------------------------------------------------------- the picture window and its palette

class Window(NamedTuple):
    r0: int
    r1: int
    c0: int
    c1: int
    rows: np.ndarray    # picture row -> grid row (absolute)
    cols: np.ndarray    # picture column -> grid column (absolute)
    lats: np.ndarray    # picture row centres, degrees north
    lons: np.ndarray    # picture column centres, degrees east


@lru_cache(maxsize=2)
def picture_window(width: int = WIDTH) -> Window:
    """The grid rows and columns the picture covers (gridded.IMAGE_BOUNDS). For each picture row and column, the grid
    row and column of the cell that holds its centre come from hail.cell_for, B1's exact arithmetic."""
    lats, lons = gridded.pixel_centers(width)
    rows = np.array([hs.cell_for(float(la), -110.0)[0] for la in lats], dtype=np.int64)
    cols = np.array([hs.cell_for(45.0, float(lo))[1] for lo in lons], dtype=np.int64)
    r0, r1, c0, c1 = int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max())
    if not (hs.in_grid(r0, c0) and hs.in_grid(r1, c1)):
        raise AssertionError("the picture box lies outside the MRMS grid")
    return Window(r0, r1, c0, c1, rows, cols, lats, lons)


@lru_cache(maxsize=1)
def class_palette() -> np.ndarray:
    """The palette index of each B1 size class: the middle level of its band in gridded.STYLE["hail_swath"]. Every
    level in a band has the band's colour, so each picture colour is one class."""
    _stops, _log, n = gridded.STYLE[STYLE]
    index = []
    for lo, hi, _colour, _alpha in gridded.HAIL_SWATH_BANDS:
        levels = [k for k in range(n) if lo - 1e-9 <= gridded.level_value(STYLE, k) <= hi + 1e-9]
        if not levels:
            raise AssertionError(f"no palette level falls in the band {lo} to {hi} mm")
        index.append(2 + levels[len(levels) // 2])
    return np.array(index, dtype=np.uint8)


@lru_cache(maxsize=1)
def montana_cells() -> tuple[np.ndarray, np.ndarray]:
    """Grid rows and columns of the Montana cells (B1's strict state mask)."""
    mesh = hs.montana_mesh()
    return mesh.rows, mesh.cols


# ---------------------------------------------------------------- decoding one file

class Decoded(NamedTuple):
    valid: datetime
    header: dict         # what the header said, for the record
    tenths: np.ndarray   # int32 over the picture window (grid rows r0..r1, columns c0..c1), tenths of a mm
    nocov: np.ndarray    # bool over the same window: -3, no radar coverage
    r0: int              # the window's first grid row
    c0: int              # the window's first grid column
    packed: dict         # hail.pack_tenths counts over the window


def _header(msg, name: str):
    try:
        return msg[name]
    except Exception:  # noqa: BLE001 - a missing key is a header problem, reported in plain words
        raise SwathError(f"the file's header has no {name}") from None


def _optional(msg, name: str):
    try:
        value = msg[name]
    except Exception:  # noqa: BLE001 - recorded only, never checked
        return None
    return value.strip() if isinstance(value, str) else value


def decode_message(msg, product: Product, expected: datetime) -> Decoded:
    """One GRIB2 message (a pygrib message, or a stand-in with the same keys) -> the picture window's values. The
    checks are D2's: discipline 209, category 3, the parameter for the product's folder, the B1 grid, and the header's
    valid time (dataDate and dataTime) equal to the file name's time. Raises SwathError with the reason."""
    discipline, category = _header(msg, "discipline"), _header(msg, "parameterCategory")
    parameter = _header(msg, "parameterNumber")
    if (discipline, category) != (DISCIPLINE, CATEGORY):
        raise SwathError("the file is not NOAA's MRMS radar product",
                         detail=f"discipline {discipline}, category {category} (expected {DISCIPLINE}, {CATEGORY})")
    if parameter != product.parameter:
        detail = f"parameter {parameter} in folder {product.folder} (parameter {product.parameter} expected)"
        other = next((p for p in PRODUCTS if p.parameter == parameter), None)
        if other is not None:                  # the other hail product: say which window the file covers (C9)
            raise SwathError(f"NOAA's file covers {other.span}, not {product.span}", detail=detail)
        raise SwathError(f"the file is not NOAA's hail product for {product.span}", detail=detail)
    if _header(msg, "gridType") != "regular_ll":
        raise SwathError("the file's grid is not a regular latitude and longitude grid")
    if (_header(msg, "Ni"), _header(msg, "Nj")) != (NI, NJ):
        raise SwathError(f"the file's grid is not {NI:,} by {NJ:,} points")
    for name, want in (("latitudeOfFirstGridPointInDegrees", FIRST_LAT),
                       ("longitudeOfFirstGridPointInDegrees", FIRST_LON),
                       ("latitudeOfLastGridPointInDegrees", LAST_LAT),
                       ("longitudeOfLastGridPointInDegrees", LAST_LON),
                       ("iDirectionIncrementInDegrees", STEP_DEG), ("jDirectionIncrementInDegrees", STEP_DEG)):
        got = float(_header(msg, name))
        if abs(got - want) > 1e-4:
            raise SwathError(f"the file's grid has {name} {got:g}, not {want:g}")
    if int(_header(msg, "jScansPositively")) != 0 or int(_header(msg, "iScansNegatively")) != 0:
        raise SwathError("the file's grid is not scanned from the north-west corner, as the B1 grid is")
    date_value, time_value = _header(msg, "dataDate"), _header(msg, "dataTime")
    try:
        date_value, time_value = int(date_value), int(time_value)
        valid = datetime(date_value // 10000, date_value // 100 % 100, date_value % 100,
                         time_value // 100, time_value % 100, tzinfo=UTC)
    except (TypeError, ValueError):
        raise SwathError("the file's date and time were not readable") from None
    if valid != expected:                      # C10: Montana time, as the page shows every other time
        raise SwathError(f"the file's time ({valid_text(valid)}) does not match the time in its name "
                         f"({valid_text(expected)})")
    header = {"discipline": discipline, "parameterCategory": category, "parameterNumber": parameter,
              "centre": _optional(msg, "centre"), "generatingProcessIdentifier": _optional(msg, "generatingProcessIdentifier"),
              "productDefinitionTemplateNumber": _optional(msg, "productDefinitionTemplateNumber"),
              "dataDate": date_value, "dataTime": time_value, "pygrib_name": _optional(msg, "name"),
              "pygrib_units": _optional(msg, "units"), "grid": [NI, NJ], "first": [FIRST_LAT, FIRST_LON],
              "last": [LAST_LAT, LAST_LON], "step_deg": STEP_DEG}
    win = picture_window()
    try:
        values = msg.values                     # pygrib decodes the whole grid on each access: read it once
    except Exception as e:  # noqa: BLE001
        raise SwathError("the file's values could not be read", detail=gridded._problem(e)) from None
    shape = tuple(getattr(values, "shape", ()))
    if shape and shape != (NJ, NI):
        raise SwathError("the file's values don't match its grid")
    raw = np.ma.filled(np.ma.asarray(values[win.r0:win.r1 + 1, win.c0:win.c1 + 1], dtype=np.float64), np.nan)
    finite = np.isfinite(raw)
    codes = finite & (raw < 0)
    stray = codes & (raw != -1.0) & (raw != -3.0)
    if stray.any():
        raise SwathError("the file holds a code the NOAA table does not list",
                         detail=f"{float(raw[stray][0]):g}")
    positive = finite & (raw > 0)
    if (positive & (np.abs(raw * 10.0 - np.rint(raw * 10.0)) > 1e-3)).any():
        raise SwathError("the file's values are not in tenths of a millimetre, as the NOAA table says")
    try:
        tenths, packed = hs.pack_tenths(raw)
    except ValueError as e:
        raise SwathError(str(e)) from None
    return Decoded(valid, header, tenths.astype(np.int32), raw == -3.0, win.r0, win.c0, packed)


def decode_bytes(data: bytes, product: Product, expected: datetime) -> Decoded:
    """A downloaded file (gzip, or GRIB2 as it is) -> Decoded. pygrib is imported here and nowhere else."""
    try:
        raw = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else bytes(data)
    except (OSError, EOFError):
        raise SwathError("the download was not a readable gzip file") from None
    try:
        message = gridded.grib_message(raw)
    except ValueError as e:
        if "not a GRIB" in str(e):             # gridded's own words for a download that is not GRIB2
            raise SwathError("NOAA's download was not a readable radar file", detail=str(e)) from None
        raise SwathError(str(e), detail=str(e)) from None
    try:
        import pygrib                           # only the live decode reads GRIB files
    except ImportError as e:
        raise SwathError("the file could not be read on this build", detail=gridded._problem(e)) from None
    try:
        msg = pygrib.fromstring(message)
    except Exception as e:  # noqa: BLE001
        raise SwathError("the file could not be read", detail=gridded._problem(e)) from None
    return decode_message(msg, product, expected)


# ---------------------------------------------------------------- listing, download and cache

KEY_PATTERN = {p.key: re.compile(rf"^{ROOT}/{re.escape(p.folder)}/(\d{{8}})/MRMS_{re.escape(p.folder)}_(\d{{8}})-(\d{{6}})"
                                 rf"\.grib2\.gz$") for p in PRODUCTS}
CACHED_PATTERN = {p.key: re.compile(rf"^MRMS_{re.escape(p.folder)}_(\d{{8}})-(\d{{6}})\.grib2(\.gz)?$") for p in PRODUCTS}


def list_url(product: Product, day) -> str:
    return f"{BUCKET}?list-type=2&prefix={quote(f'{ROOT}/{product.folder}/{day:%Y%m%d}/')}"


def parse_listing(data, product: Product) -> list[tuple[datetime, str]]:
    """S3 ListObjectsV2 XML -> [(valid time, key)] of one product's files for one day, oldest first. A listing cut
    short by paging is refused, because the newest key could be on the missing page."""
    text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data or "")
    if "<ListBucketResult" not in text:
        raise SwathError(f"the file list for {product.span} was not readable")
    if re.search(r"<IsTruncated>\s*true\s*</IsTruncated>", text):
        raise SwathError(f"the file list for {product.span} was cut short (more than one page)")
    found = []
    for key in re.findall(r"<Key>([^<]+)</Key>", text):
        key = html.unescape(key)
        m = KEY_PATTERN[product.key].match(key)
        if not m:
            continue
        if m.group(1) != m.group(2):
            raise SwathError(f"the file list for {product.span} has a file in the wrong day's folder")
        found.append((datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M%S").replace(tzinfo=UTC), key))
    return sorted(found)


def _entry(kind: str, what: str, ok: bool, nbytes: int, seconds: float, error=None, **extra) -> dict:
    return {"kind": kind, "what": what, "ok": ok, "bytes": int(nbytes), "seconds": round(seconds, 3),
            "error": error, **extra}


# Why a NOAA request failed, in plain words. The raw reason stays in the layer's ledger. The names are the exception
# classes sources.Fetcher.binary records as its last error, and the forms it writes for an HTTP answer.
REQUEST_WORDS = {
    "ReadTimeout": "NOAA did not answer in time",
    "Timeout": "NOAA did not answer in time",
    "ConnectTimeout": "NOAA did not answer in time",
    "ConnectionError": "NOAA could not be reached",
    "ProxyError": "NOAA could not be reached",
    "SSLError": "the connection to NOAA could not be made secure",
    "ChunkedEncodingError": "NOAA's answer was cut short",
}
REQUEST_GENERIC = "NOAA did not give a usable answer"


def request_words(err) -> str:
    """The plain words for a failed request's reason: a bare exception name (or the 'unexpected error (name)' that
    gridded._problem writes for one), an HTTP answer, or anything else, which reads as no usable answer. The page never
    shows a class name, a code or an address."""
    text = "" if err is None else str(err).strip()
    named = re.fullmatch(r"unexpected error \((\w+)\)", text)
    name = named.group(1) if named else text
    if name in REQUEST_WORDS:
        return REQUEST_WORDS[name]
    if text in ("not published (HTTP 404)", "HTTP 404"):
        return "NOAA did not have that file"
    if re.fullmatch(r"server error \(HTTP 5\d\d\)|HTTP 5\d\d", text):
        return "NOAA's server had an error"
    if re.fullmatch(r"HTTP \d{3}", text):
        return "NOAA did not accept the request"
    if "timed out" in text.lower():
        return "NOAA did not answer in time"
    return REQUEST_GENERIC


def _request(get, url: str, kind: str, ledger: list):
    """One request through the build's getter; a raised exception is a reason, not a crash. Returns the bytes."""
    t0 = time.perf_counter()
    try:
        data, err = get(url)
    except Exception as e:  # noqa: BLE001 - recorded in the ledger
        data, err = None, gridded._problem(e)
    seconds = time.perf_counter() - t0
    if err or data is None:
        ledger.append(_entry(kind, url, False, 0, seconds, err or "no data"))
        return None, err or "no data"
    ledger.append(_entry(kind, url, True, len(data), seconds))
    return data, None


def list_day(product: Product, day, get, ledger: list) -> list[tuple[datetime, str]]:
    """One listing for one day's folder: [(valid, key)] oldest first. A failed request is a SwathError."""
    url = list_url(product, day)
    data, err = _request(get, url, "list", ledger)
    if err:
        raise SwathError(f"the file list for {product.span} didn't load: {request_words(err)}", detail=err)
    items = parse_listing(data, product)
    ledger[-1]["files"] = len(items)
    return items


def newest_file(product: Product, now: datetime, get, ledger: list) -> tuple[datetime, str]:
    """The newest key: today's folder, or yesterday's when today's is empty (just after 00:00 UTC). D3."""
    for day in (now.date(), now.date() - timedelta(days=1)):
        items = list_day(product, day, get, ledger)
        if items:
            return items[-1]
    raise SwathError(f"the file list for {product.span} has no file for today or yesterday")


def cache_names(key: str) -> tuple[str, str]:
    name = key.rsplit("/", 1)[1]
    return name, name[:-3] if name.endswith(".gz") else name


def read_cache(cache_dir, key: str) -> bytes | None:
    """The cached copy of a key: its .gz as downloaded, or a plain .grib2 placed in the cache by hand."""
    for name in cache_names(key):
        path = Path(cache_dir) / name
        if path.is_file():
            return path.read_bytes()
    return None


def write_cache(cache_dir, key: str, data: bytes) -> None:
    """Store a download under its key's name (the .gz as it came), written whole or not at all."""
    path = Path(cache_dir) / cache_names(key)[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)


def fetch_file(product: Product, key: str, cache_dir, get, ledger: list, *, use_cache: bool = True):
    """(bytes, from_cache) for one key: the cache when it holds the key, else one download, which is then cached."""
    if use_cache and cache_dir is not None:
        cached = read_cache(cache_dir, key)
        if cached is not None:
            ledger.append(_entry("cache", key.rsplit("/", 1)[1], True, len(cached), 0.0, cache="hit"))
            return cached, True
    data, err = _request(get, BUCKET + key, "file", ledger)
    if err:
        raise SwathError(f"the newest file for {product.span} didn't load: {request_words(err)}", detail=err)
    if not data:
        raise SwathError(f"the newest file for {product.span} was empty")
    if cache_dir is not None:
        write_cache(cache_dir, key, data)
        ledger[-1]["cache"] = "stored"
    return data, False


def cached_newest(product: Product, cache_dir) -> tuple[datetime, str]:
    """The newest file of one product in the cache folder (offline builds). The key is the file name, as a bucket key
    would name it, so the decode checks the same things it checks live."""
    folder = Path(cache_dir)
    if not folder.is_dir():
        raise SwathError("the cache folder does not exist")
    found = []
    for path in folder.iterdir():
        m = CACHED_PATTERN[product.key].match(path.name)
        if m:
            found.append((datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=UTC),
                          f"{ROOT}/{product.folder}/{m.group(1)}/{path.name}"))
    if not found:
        raise SwathError(f"the cache folder holds no file for {product.span}")
    return max(found)


# ---------------------------------------------------------------- the picture, the live files and the cell counts

def sample_decoded(product: Product, valid: datetime) -> Decoded:
    """The SAMPLE field for one product as a Decoded, through the same pack and window as a live file."""
    win = picture_window()
    lats = (hs.ROW0_LAT_E3 - 10 * np.arange(win.r0, win.r1 + 1, dtype=np.int64)) / 1000.0
    lons = (hs.COL0_LON_E3 + 10 * np.arange(win.c0, win.c1 + 1, dtype=np.int64)) / 1000.0
    raw = sample_data.swath_field(lats, lons, product.window)
    tenths, packed = hs.pack_tenths(raw)
    return Decoded(valid, {"sample": True, "window": product.window}, tenths.astype(np.int32), raw == -3.0,
                   win.r0, win.c0, packed)


def picture_index(dec: Decoded) -> tuple[np.ndarray, bool]:
    """Palette indices over the picture: 0 uncoloured (no estimate, or below 0.25 in), 1 hatched (no coverage), 2 and up
    the class colours. Returns the indices and whether any cell is hatched."""
    win = picture_window()
    rr, cc = win.rows - dec.r0, win.cols - dec.c0
    tenths = dec.tenths[np.ix_(rr, cc)]
    nocov = dec.nocov[np.ix_(rr, cc)]
    cls = np.searchsorted(CLASS_MINS, tenths, side="right") - 1
    cls = np.where(tenths >= hs.FLOOR_TENTHS, cls, -1)
    index = np.zeros(tenths.shape, dtype=np.uint8)
    on = cls >= 0
    index[on] = class_palette()[cls[on]]
    index[nocov & gridded.hatch_mask(tenths.shape, tenths.shape[1])] = 1
    return index, bool(nocov.any())


def stamp_of(valid: datetime) -> str:
    """The frame's valid time as the live folder and the frame picture's name carry it: YYYYMMDDHHMM (D14)."""
    return valid.strftime("%Y%m%d%H%M")


def live_pattern(window: int, stamp: str) -> str:
    """The browser's tile path for one frame: hail/live/<window>/<stamp>/<tile>.json (D14). The valid time is in the
    path, not in a query string, so a cached tile from an earlier build can never be read beside this layer."""
    return f"{LIVE_DIR}/{window}/{stamp}/{{tile}}.json"


def live_files(dec: Decoded, window: int, sample: bool = False) -> dict:
    """The per-tile live files (D4, D13): tile name -> JSON text, for each tile with a cell at or above the floor or
    with a no-coverage (-3) cell. "cells" lists the decoded tenths at or above the floor, sorted by row and column;
    cells below the floor are not written, so a tile with only -3 cells has an empty list. "nocov" lists the tile's
    -3 cells (D9) when it has any. A sample build's tiles carry "sample": true. A tile with neither kind of cell has
    no file (D4), so its cells read as no estimate."""
    rr, cc = np.nonzero(dec.tenths >= hs.FLOOR_TENTHS)
    nr, nc = np.nonzero(dec.nocov)
    if rr.size == 0 and nr.size == 0:
        return {}
    stamp = dec.valid.strftime("%Y-%m-%dT%H:%M:%SZ")
    cells: dict = {}
    for row, col, value in zip((rr + dec.r0).tolist(), (cc + dec.c0).tolist(), dec.tenths[rr, cc].tolist()):
        cells.setdefault(hs.tile_name(row // hs.TILE, col // hs.TILE), []).append([row, col, value])
    holes: dict = {}
    for row, col in zip((nr + dec.r0).tolist(), (nc + dec.c0).tolist()):
        holes.setdefault(hs.tile_name(row // hs.TILE, col // hs.TILE), []).append([row, col])
    out = {}
    for name in sorted(set(cells) | set(holes)):
        doc = {"f": LIVE_FORMAT, "window": window, "valid": stamp, "cells": cells.get(name, [])}
        if name in holes:
            doc["nocov"] = holes[name]
        if sample:
            doc["sample"] = True
        out[name] = json.dumps(doc, separators=(",", ":"))
    return out


def cell_stats(dec: Decoded) -> dict:
    """The largest value in the picture window and in Montana, with its cell, and the counts at the floor (the words
    give the Montana count only, D19)."""
    t = dec.tenths
    out = {"cells_ge_floor": int((t >= hs.FLOOR_TENTHS).sum()),
           "largest_tenths": 0, "largest_cell": None, "montana_largest_tenths": 0, "montana_cell": None,
           "montana_cells_ge_floor": 0}
    if out["cells_ge_floor"]:
        r, c = divmod(int(np.argmax(t)), t.shape[1])
        out["largest_tenths"], out["largest_cell"] = int(t[r, c]), [r + dec.r0, c + dec.c0]
    rows, cols = montana_cells()
    inside = (rows >= dec.r0) & (rows < dec.r0 + t.shape[0]) & (cols >= dec.c0) & (cols < dec.c0 + t.shape[1])
    vals = t[rows[inside] - dec.r0, cols[inside] - dec.c0]
    out["montana_cells_ge_floor"] = int((vals >= hs.FLOOR_TENTHS).sum())
    if vals.size and int(vals.max()) >= hs.FLOOR_TENTHS:
        k = int(np.argmax(vals))
        out["montana_largest_tenths"] = int(vals[k])
        out["montana_cell"] = [int(rows[inside][k]), int(cols[inside][k])]
    return out


def freshness(product: Product, valid: datetime, now: datetime) -> tuple[str, timedelta, str | None]:
    """(state, age, problem) from the valid time against the build's now (D6)."""
    age = now - valid
    if age < -FUTURE_TOLERANCE:
        return "unavailable", age, f"the newest file is stamped {valid_text(valid)}, newer than this build's time"
    if age <= product.fresh:
        return "fresh", age, None
    if age <= product.stale:
        return "stale", age, None
    minutes, limit = math.ceil(age.total_seconds() / 60), int(product.stale.total_seconds() // 60)
    return "unavailable", age, WORDS_SWATH["age_out"].format(age=minutes, limit=limit)


# ---------------------------------------------------------------- words helpers

def valid_text(valid: datetime) -> str:
    """A valid time in Montana time, as the words show it: "Oct 18, 8:44 pm MDT"."""
    local = valid.astimezone(MT)
    return f"{hs.MONTHS[local.month - 1]} {local.day}, {gridded._hm(valid)} {local.tzname()}"


def _where(lat: float, lon: float) -> str:
    return f"{lat:.3f} degrees north, {abs(lon):.3f} degrees west"


def _miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_MILES * math.asin(math.sqrt(min(1.0, a)))


def nearest_town(towns: list, lat: float, lon: float) -> tuple[str, float]:
    """The nearest town in towns.json (its name, and the distance in miles)."""
    best = min(towns, key=lambda t: _miles(lat, lon, t["lat"], t["lon"]))
    return best["name"], _miles(lat, lon, best["lat"], best["lon"])


def _size(tenths: int) -> tuple[str, str]:
    return hs.inches(tenths), hs.mm_text(tenths)


def sheet_line(window: int, tenths: int, valid: datetime | None, state: str, state_line: str | None,
               sample: bool = False, nocov: bool = False) -> str:
    """The sheet's line for one clicked cell (D4, D5, D9): its value in the last window, or the no-estimate words.
    An unavailable layer, or a state this code does not know, returns the layer's state line alone: no cell value is
    read from it (AGENTS rule 5). A stale layer's line ends with the all-clear sentence (D6). nocov: the clicked cell
    is a -3 cell that its tile lists. sample: a sample build's line begins with the sample label."""
    if state not in ("fresh", "stale"):
        return state_line
    product = next(p for p in PRODUCTS if p.window == window)
    if nocov:
        line = WORDS_SWATH["no_coverage"]
    elif tenths >= hs.FLOOR_TENTHS:
        inch, mm = _size(tenths)
        line = WORDS_SWATH["live_line"].format(window=product.window_word, **{"in": inch, "mm": mm},
                                               **{"class": hs.class_for(tenths)["word"]}, valid=valid_text(valid))
        if tenths >= LARGE_TENTHS:
            line += " " + WORDS_SWATH["large_note"]
    else:
        line = WORDS_SWATH["no_estimate"].format(window=product.window_word, valid=valid_text(valid))
    if sample:
        line = WORDS_SWATH["sample_sheet"] + " " + line
    if state == "stale":
        line += " " + WORDS_SWATH["all_clear"]
    return line


# ---------------------------------------------------------------- one layer

def _unavailable(product: Product, problem: str, valid=None, timing=None, sample: bool = False) -> dict:
    line = WORDS_SWATH["unavailable"].format(title=product.title, problem=problem)
    return {"key": product.key, "window": product.window, "state": "unavailable", "ok": False, "problem": problem,
            "state_line": line, "valid": valid.strftime("%Y-%m-%dT%H:%M:%SZ") if valid else None,
            "valid_text": valid_text(valid) if valid else None, "age_min": None, "src": None, "sample": sample,
            "timing": timing or {}}


def _acquire(product: Product, now: datetime, cache_dir, get, sample: bool, offline: bool, ledger: list,
             timing: dict) -> Decoded:
    """The decoded newest file of one product: from the sample field, from the cache, or from the bucket."""
    if sample:
        valid = gridded.floor_time(now - product.every, int(product.every.total_seconds() // 60))
        t0 = time.perf_counter()
        dec = sample_decoded(product, valid)
        timing["decode_s"] = round(time.perf_counter() - t0, 3)
        return dec
    if offline:
        valid, key = cached_newest(product, cache_dir)
        t0 = time.perf_counter()
        data, _from = fetch_file(product, key, cache_dir, None, ledger, use_cache=True)
        dec = decode_bytes(data, product, valid)
        timing["decode_s"] = round(time.perf_counter() - t0, 3)
        return dec
    t0 = time.perf_counter()
    valid, key = newest_file(product, now, get, ledger)
    timing["list_s"] = round(time.perf_counter() - t0, 3)
    t0 = time.perf_counter()
    data, from_cache = fetch_file(product, key, cache_dir, get, ledger)
    timing["download_s"] = round(time.perf_counter() - t0, 3)
    t0 = time.perf_counter()
    try:
        dec = decode_bytes(data, product, valid)
    except SwathError:
        if not from_cache:
            raise
        data, _from = fetch_file(product, key, cache_dir, get, ledger, use_cache=False)   # a bad cached copy: once more
        dec = decode_bytes(data, product, valid)
    timing["decode_s"] = round(time.perf_counter() - t0, 3)
    return dec


def _layer(product: Product, now: datetime, cache_dir, out_dir, get, sample: bool, offline: bool,
           towns: list) -> tuple[dict, list, dict]:
    ledger: list = []
    timing: dict = {}
    valid = None
    try:
        dec = _acquire(product, now, cache_dir, get, sample, offline, ledger, timing)
        valid = dec.valid
        state, age, problem = freshness(product, valid, now)
        if state == "unavailable":
            frame = _unavailable(product, problem, valid, timing, sample)
            return frame, [], _state_record(frame, ledger, timing)
        t0 = time.perf_counter()
        index, hatched = picture_index(dec)
        png = gridded.png_bytes(index, STYLE)
        tiles = live_files(dec, product.window, sample)
        stats = cell_stats(dec)
        timing["draw_s"] = round(time.perf_counter() - t0, 3)
        frame = _drawn(product, dec, now, state, age, png, tiles, stats, hatched, towns, sample)
        written = _write(out_dir, frame, tiles, product)
        timing["write_s"] = round(time.perf_counter() - t0 - timing["draw_s"], 3)
        return frame, written, _state_record(frame, ledger, timing)
    except SwathError as e:
        frame = _unavailable(product, str(e), valid, timing, sample)
        return frame, [], _state_record(frame, ledger, timing, e.detail)
    except Exception as e:  # noqa: BLE001 - a bug or an odd file is an unavailable layer, never a crash of the build
        frame = _unavailable(product, "the map could not be drawn", valid, timing, sample)
        return frame, [], _state_record(frame, ledger, timing, gridded._problem(e))


def _drawn(product: Product, dec: Decoded, now: datetime, state: str, age: timedelta, png: bytes, tiles: dict,
           stats: dict, hatched: bool, towns: list, sample: bool) -> dict:
    age_min = max(0, int(age.total_seconds() // 60))     # a file a minute or two ahead of the clock reads as 0
    valid_str = dec.valid.strftime("%Y-%m-%dT%H:%M:%SZ")
    vt = valid_text(dec.valid)
    fresh_min = int(product.fresh.total_seconds() // 60)
    if sample:
        line = WORDS_SWATH["sample_state"].format(valid=vt)
    elif state == "stale":
        line = WORDS_SWATH["stale"].format(valid=vt, age=age_min, limit=fresh_min)
    else:
        line = WORDS_SWATH["fresh"].format(valid=vt, age=age_min)
    stamp = stamp_of(dec.valid)
    name = f"hail-{product.window}-{stamp}.png"
    frame = {"key": product.key, "window": product.window, "state": state, "ok": state == "fresh" or sample,
             "problem": None, "state_line": line, "valid": valid_str, "valid_text": vt, "stamp": stamp,
             "age_min": age_min,
             "product": product.folder, "file": None if sample else f"MRMS_{product.folder}_{dec.valid:%Y%m%d-%H%M%S}.grib2",
             "src": f"{gridded.FRAME_DIR}/{name}",
             "source": (WORDS_SWATH["sample_source"] if sample else
                        f"NOAA MRMS MESH, {product.folder}, CONUS grid, NOAA Open Data on AWS"),
             "bounds": [list(gridded.IMAGE_BOUNDS[0]), list(gridded.IMAGE_BOUNDS[1])], "nodata": hatched,
             "sample": sample, "header": dec.header, "pack": {k: int(v) if isinstance(v, (int, np.integer)) else v
                                                              for k, v in dec.packed.items()},
             "live": {"files": len(tiles), "bytes": sum(len(v.encode("utf-8")) for v in tiles.values()),
                      "pattern": live_pattern(product.window, stamp)},
             "png_bytes": len(png), "_png": png}
    frame.update({k: v for k, v in stats.items()})
    # D15: the words name Montana first. The town and its distance come from the largest cell inside Montana only;
    # the picture's own largest cell gets its centre and no town, so no nearest-town line is made for a cell outside.
    frame["largest_in"], frame["largest_mm"] = _size(stats["largest_tenths"]) if stats["largest_tenths"] else (None, None)
    frame["largest_class"] = hs.class_for(stats["largest_tenths"])["word"] if stats["largest_tenths"] else None
    frame["montana_largest_in"], frame["montana_largest_mm"] = (
        _size(stats["montana_largest_tenths"]) if stats["montana_largest_tenths"] else (None, None))
    frame["montana_largest_class"] = (hs.class_for(stats["montana_largest_tenths"])["word"]
                                      if stats["montana_largest_tenths"] else None)
    frame.update({"largest_centre": None, "montana_centre": None, "montana_nearest_town": None,
                  "montana_nearest_town_miles": None})
    if stats["largest_cell"]:
        r, c = stats["largest_cell"]
        lat, lon = hs.cell_centre(r, c)
        frame["largest_centre"] = [round(lat, 3), round(lon, 3)]
    if stats["montana_cell"]:
        r, c = stats["montana_cell"]
        lat, lon = hs.cell_centre(r, c)
        frame["montana_centre"] = [round(lat, 3), round(lon, 3)]
        if towns:
            town, miles = nearest_town(towns, lat, lon)
            frame.update({"montana_nearest_town": town, "montana_nearest_town_miles": round(miles, 1)})
    return frame


def _write(out_dir, frame: dict, tiles: dict, product: Product) -> list:
    """Writes the picture and the live files under out_dir (the site root); returns their paths, relative to it. The
    live files go in the folder of this frame's valid time (D14), the only live folder a build writes."""
    root = Path(out_dir)
    written = []
    gridded._write(root, [{"src": frame["src"], "_png": frame["_png"]}])
    written.append(frame["src"])
    folder = f"{LIVE_DIR}/{product.window}/{frame['stamp']}"
    live_dir = root / folder
    if tiles:
        live_dir.mkdir(parents=True, exist_ok=True)
    for name, text in tiles.items():
        (live_dir / f"{name}.json").write_text(text, encoding="utf-8")
        written.append(f"{folder}/{name}.json")
    return written


def _state_record(frame: dict, ledger: list, timing: dict, error: str | None = None) -> dict:
    """The layer's record. "error" is the technical reason (an exception name, a GRIB number) that the page does not
    show; "detail" is the page's own line."""
    return {"key": frame["key"], "window": frame["window"], "state": frame["state"], "ok": frame["ok"],
            "detail": frame["state_line"], "problem": frame["problem"], "valid": frame["valid"],
            "valid_text": frame.get("valid_text"), "age_min": frame.get("age_min"), "label": LABEL,
            "live": frame.get("live"), "png_bytes": frame.get("png_bytes"), "requests": ledger, "timing": timing,
            "error": error}


def collect(now: datetime, cache_dir, out_dir, towns: list, get=None, sample: bool = False,
            offline: bool = False) -> tuple[dict, list, dict]:
    """Both swath layers. Returns (frames, files, states): frames maps "hail_60" and "hail_1440" to a frame dict (its
    "state" is fresh, stale or unavailable; an unavailable frame has no picture); files lists the paths written under
    out_dir; states maps each key to its status record (label, ok, detail, requests and timings)."""
    now = (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(UTC)
    if get is None and not (sample or offline):
        get = src.Fetcher(timeout=60, attempts=3).binary
    frames, files, states = {}, [], {}
    for product in PRODUCTS:
        frame, written, state = _layer(product, now, cache_dir, out_dir, get, sample, offline, towns)
        frames[product.key] = frame
        files.extend(written)
        states[product.key] = state
    return frames, files, states


# ---------------------------------------------------------------- words for the page and the map

def describe(frame: dict, now: datetime, towns: list) -> list:
    """The plain-words lines for one layer: the List view and the no-JavaScript panel. The first line is the state
    line (with "This is not an all-clear." when it is stale or unavailable); the second says when the build made it,
    because the panel does not update (D7). Montana comes first (D15): the lead is the largest value inside Montana,
    then the count of Montana cells at the floor, then, when the largest value in this map's area lies outside Montana,
    that value with its note (the note follows the value it describes). No count of the whole area is given (D19)."""
    built = WORDS_SWATH["as_of_build"].format(time=valid_text(now))
    if frame.get("state") == "unavailable" or not frame.get("src"):
        return [frame["state_line"], built]
    product = PRODUCT_BY_KEY[frame["key"]]
    lines = [frame["state_line"], built]
    if frame["montana_largest_tenths"]:
        values = {"in": frame["montana_largest_in"], "mm": frame["montana_largest_mm"],
                  "class": frame["montana_largest_class"]}
        lat, lon = frame["montana_centre"]
        if frame["montana_nearest_town"]:
            lines.append(WORDS_SWATH["lead_largest"].format(**values, where=_where(lat, lon),
                                                            miles=frame["montana_nearest_town_miles"],
                                                            town=frame["montana_nearest_town"]))
        else:
            lines.append(WORDS_SWATH["lead_largest_no_town"].format(**values, where=_where(lat, lon)))
        if frame["montana_largest_tenths"] >= LARGE_TENTHS:
            lines.append(WORDS_SWATH["large_note"])
    else:
        lines.append(WORDS_SWATH["lead_none"].format(window=product.window_word))
    lines.append(WORDS_SWATH["montana_count"].format(n=frame["montana_cells_ge_floor"]))
    if frame["largest_tenths"] > frame["montana_largest_tenths"]:
        outside = WORDS_SWATH["montana_outside"].format(**{"in": frame["largest_in"]})
        if frame["largest_tenths"] >= LARGE_TENTHS:
            outside += " " + WORDS_SWATH["large_note"]
        lines.append(outside)
    lines.append(WORDS_SWATH["uncoloured"].format(window=product.window_word))
    if frame["nodata"]:
        lines.append(WORDS_SWATH["hatched"])
    lines.append(WORDS_SWATH["what_this_is"])
    lines.append(WORDS_SWATH["sample_source"] if frame.get("sample") else
                 WORDS_SWATH["source"].format(folder=product.folder, valid=frame["valid_text"]))
    return lines


def map_data_swath(frames: dict) -> dict:
    """The two layers' blocks for data/map.json ("hail_60", "hail_1440"): one frame each, as the satellite layer is,
    with its bounds, the legend (colours and class words), the state and its words, the valid time, the freshness
    minutes (fresh_min, stale_min; D7), the live file pattern (the valid time's folder, D14; null while the layer has
    no frame) and the floor, and the templates the browser fills."""
    legend, gradient = gridded.legend(STYLE)
    blocks = {}
    for product in PRODUCTS:
        frame = frames.get(product.key) or {}
        drawn = bool(frame.get("src")) and frame.get("state") != "unavailable"
        stamp = frame.get("stamp")   # D14: the frame's valid time, as the picture's name carries it
        sample = bool(frame.get("sample"))
        note = WORDS_SWATH["sample_legend_note" if sample else "legend_note"].format(window=product.window_word)
        south, west = gridded.IMAGE_BOUNDS[0]
        north, east = gridded.IMAGE_BOUNDS[1]
        outside = WORDS_SWATH["outside"].format(south=f"{south:.1f}", north=f"{north:.1f}",
                                                west=f"{abs(west):.1f}", east=f"{abs(east):.1f}")
        blocks[product.key] = {
            "title": product.title, "unit": "in", "window": product.window, "product": product.folder,
            "label": LABEL, "legend_note": note, "legend": legend, "gradient": gradient,
            "state": frame.get("state", "unavailable"), "ok": bool(frame.get("ok")),
            "state_line": frame.get("state_line"), "problem": frame.get("problem"),
            "valid": frame.get("valid"), "valid_text": frame.get("valid_text"), "age_min": frame.get("age_min"),
            "fresh_min": int(product.fresh.total_seconds() // 60),
            "stale_min": int(product.stale.total_seconds() // 60), "sample": sample,
            "frames": [{"time": frame["valid"], "kind": "hail_swath", "src": frame["src"],
                        "source": frame["source"], "nodata": frame["nodata"]}] if drawn else [],
            "modes": {"12h": [0] if drawn else []}, "now_index": {"12h": 0},
            "bounds": [list(gridded.IMAGE_BOUNDS[0]), list(gridded.IMAGE_BOUNDS[1])],
            "live": {"pattern": live_pattern(product.window, stamp) if drawn and stamp else None,
                     "tile_cells": hs.TILE,
                     "tile_name": "r{r:04d}_c{c:04d}", "format": LIVE_FORMAT, "floor_tenths": hs.FLOOR_TENTHS,
                     "floor_in": hs.FLOOR_IN, "tenths_per_inch": hs.TENTHS_PER_INCH,
                     "large_note_tenths": LARGE_TENTHS},
            "words": {**WORDS_SWATH, "outside": outside, "legend_note": note},
        }
    return blocks


# ---------------------------------------------------------------- command line

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m website.swath",
                                 description="Build the hail swath layers into a folder (the site root) and print a record.")
    ap.add_argument("--out", required=True, help="the site root to write the pictures and live files under")
    ap.add_argument("--cache", required=True, help="the download cache folder")
    ap.add_argument("--offline", action="store_true", help="use the newest cached files, no network")
    ap.add_argument("--sample", action="store_true", help="invented fields, no network")
    ap.add_argument("--now", help="the build's time in UTC, ISO 8601 (default: the current time)")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(UTC)
    towns = json.loads((HERE / "towns.json").read_text(encoding="utf-8"))
    frames, files, states = collect(now, a.cache, a.out, towns, sample=a.sample, offline=a.offline)
    record = {"now": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "files": files, "layers": {}}
    for key, state in states.items():
        frame = frames[key]
        record["layers"][key] = {**{k: v for k, v in state.items() if k != "requests"},
                                 "requests": state["requests"], "lines": describe(frame, now, towns),
                                 "bounds": frame.get("bounds"), "src": frame.get("src"),
                                 "largest": {k: frame.get(k) for k in ("largest_in", "largest_mm", "largest_class",
                                                                       "largest_centre", "montana_nearest_town",
                                                                       "montana_nearest_town_miles",
                                                                       "montana_cells_ge_floor", "cells_ge_floor",
                                                                       "montana_largest_tenths",
                                                                       "montana_cell", "largest_cell")},
                                 "header": frame.get("header"), "pack": frame.get("pack")}
    print(json.dumps(record, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
