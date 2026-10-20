"""Climate grid (B5 Source 1, builder 1): NOAA nClimGrid-Daily temperature and rain for every Montana grid cell.

What it is. Daily precipitation, highest and lowest temperature on NOAA's 1/24 degree grid, read from the NOAA
nClimGrid-Daily files, reduced to one record per land cell (July to June seasons, the partial season, calendar
years and water years), and written as site files under hail/c/ beside the radar history. Every value is a grid
estimate about 4.6 km across, not a reading at the address. A station reading is a separate row (B5 stations).

Source and terms (quoted from the records; research/temperature-rain-grid.json and its refuter):
- Bucket: noaa-nclimgrid-daily-pds (AWS Open Data, anonymous HTTPS). Files: access/grids/YYYY/
  ncdd-YYYYMM-grd-scaled.nc (scaled to the monthly product) and ncdd-YYYYMM-grd-prelim.nc (not scaled; only where no
  scaled file exists). Variables prcp (millimetres), tmax and tmin (degrees Celsius), float64, one chunk per day.
- File attribute, quoted: "license = no restrictions". Registry, quoted: "NOAA requests attribution for the use or
  dissemination of unaltered NOAA data. However, it is not permissible to state or imply endorsement by or
  affiliation with NOAA. If you modify NOAA data, you may not state or imply that it is original, unaltered NOAA data."
  The registry's licence paragraph opens with: "NOAA data disseminated through NODD are open to the public and can be
  used as desired." No NOAA page checked says "public domain" for these grids (refuter), so the page says "US
  government data; NOAA declares no restrictions; attribution requested", and the About text must not say "public
  domain" unless the owner accepts that basis (17 U.S.C. 105 and 101 are the basis to cite if so).
- Grid: 596 rows by 1,385 columns; lat 24.5625 + i/24 (ascending), lon -124.6875 + j/24 (ascending). Cell size
  4.63 km north to south and 4.21 km (south) to 3.02 km (north) east to west (the file's own comments; the refuter's
  correction). The stored float32 lat and lon arrays agree with the nominal grid to 1.3e-6 degree (checked).
  Cell rule (website.hail.cell_for's rule, in exact decimal arithmetic): lat in (south edge, north edge], lon in
  [west edge, east edge). In 1/48 degree units the centres are 1179 + 2i (lat) and -5985 + 2j (lon).
- Mask: a cell is a Montana cell when its centre is strictly inside the Montana land polygon in
  website/static/map/basemap.json (the same even-odd test as website.hail's strict mask): 25,973 cells. Of these,
  25,902 have values on some day ("land") and 71 have no value on any day of any month ("water"; the words say
  "No land value for this grid cell").
- Timing: a daily value covers the 24 hours ending in the early morning of its date (the file's comment). Scaled
  months appear 4 to 68 days after month end (median 66; research measurement on 21 months, 2025-01 to 2026-09; the
  2026-09 scaled file was created 2026-10-06 and modified 2026-10-14). Prelim days: valid through 2 to 3 days before
  the build (research: 2026-10 prelim valid to 2026-10-15 on 2026-10-18). Revisions: scaled files were rewritten on
  2026-10-19 (2026-06 to 2026-08), so the job compares listing ETags (the MD5 of each file) every run.
- Missing values: NaN (non-land points) and -999.99 (prelim days not yet available) are missing; values outside the
  file's valid_min and valid_max (prcp 0 to 2000 mm; temperatures -100 to 100 C) are missing. A day with any missing
  input for a cell is a missing day for that cell and is counted. A missing value is never summed and never zero.
  The valid mask excludes the fill before any sum; tests/test_climate.py (Fill and FileRead) asserts it.
- Precision: the file's comment says "Values should be rounded to the nearest hundredth." The stored values are
  binary-quantised (multiples of 1/256 in the June 2025 file; least_significant_digit 2), so the hundredth is taken
  from the stored value. Rounding is half up toward plus infinity; any value within 1e-7 of a tie is rounded with
  exact decimal arithmetic (never by float rounding).

Rules the build applies (B5 D1 to D4 and D16; docs/DECISIONS.md, the B5 brief):
- Precipitation: each daily value is rounded to 0.01 mm and summed in hundredths of a mm; the period total is then
  converted to hundredths of an inch by round half up (10 x hundredths of a mm / 254). Largest one-day rain is the
  largest rounded daily value and its date (the first such day).
- Temperature (D19, the one rounding rule): each daily value is rounded to the hundredth of a degree C (the step the
  file's precision allows: 32.15 C is 3215 hundredths), and that hundredth is then rounded half up to the tenth
  (3215 gives 322; 3214 gives 321). Every temperature rule compares the tenth, which is the unit of the GHCN station
  files. Fahrenheit in tenths is round half up of 1.8 x tenths-C + 320, so each Fahrenheit value is the Fahrenheit of
  the stored tenth.
- Thresholds (D1 and D19, stated once on the page, in THRESHOLDS): a day at or above 90 F has a high of at least 32.2 C
  in tenths, which is a hundredth of 32.15 C or more: 32.15 C shows as 32.2 C and 90 F, and 32.14 C (32.1 C) does not
  count. A freeze-thaw day has a high above 0 C and a low below 0 C; a day with a low below 32 F has a low below 0 C;
  a day at or below 0 F has a low of -17.8 C or colder in tenths. The counts and the displayed Fahrenheit values agree
  for every value (checked by the tests).
- Periods (sums of months): seasons July to June (2021-22 to 2025-26, and the partial 2026-27), calendar years
  (2021 has July to December only; 2026 has January to the newest day) and water years (October to September; 2021 has
  July to September only; 2027 is the partial October 2026 onward). The "f" record is the five seasons together.
- Each period record carries `days` (the days of the period the store covers: a month that did not load adds
  its days to `days` and to `missing`; a month after the newest grid day adds nothing) and `missing` (the days
  with no valid value, never zero for a missing day). The valid days are days minus missing; every total and
  count on the page is over the valid days (D2).
- Windows: the store starts July 1, 2021 (63 scaled months July 2021 to September 2026, B5 D3). Months with no file
  are "not loaded": they count as missing days and set the state to partial, with the months named (D16).
- Failures (B5 D16, job-F7): each request is retried (RETRY_ATTEMPTS tries, with a pause), and a failure that
  remains is recorded, not raised. The ledger's "failures" and the run record name the listing or the month and
  the reason: the exception's name, "HTTP nnn", "CheckFailed" or "OSError". build_store sets the state from that
  record. A failed listing makes the part unavailable (no tile files; the sentence is B2 D20's). A failed or missing
  month makes it partial, with one coverage line that names each month and its reason. With no month loaded, the
  part is unavailable. The update exits 0 when it records a failure, so the job packs and publishes the store,
  which says what did not load.

Store layout (format hail-climate-v1): hail/c/rRRRR_cCCCC.json, one per B1 tile (website.hail.TILE) that holds a
climate cell whose centre lies in Montana. A cell belongs to the tile of its centre, by website.hail.cell_for on the
centre. Each tile file: {"f", "r", "c", "state": sorted in-tile keys of every Montana climate cell in the tile,
"cells": {key: {"i", "j", "f": five seasons, "s": six seasons, "c": six calendar years, "w": seven water years}}}.
Each period is a list of 13 integers (null where no day has a value): [days, missing, rain hundredths of an inch,
largest one-day rain hundredths of an inch, its date yyyymmdd, highest tenths of a degree F, its date, lowest tenths
of F, its date, days at or above 90 F, days at or below 0 F, freeze-thaw days, days with a low below 32 F].
The in-tile key is website.hail.cell_key of the centre's B1 cell (unique: two climate centres never share a B1 cell).
Water cells are in "state" and not in "cells": a state key with no record is "no land value".

Units and kinds for the page: inches (two decimals), degrees F (one decimal), days (whole), dates as "Jun 15, 2025"
(website.hail.fmt_date). Kind word on every row: "Grid estimate".

Command line (run from the repository root):
    python -m website.climate backfill --cache DIR [--today YYYY-MM-DD]   read every planned month once; cache aggregates
    python -m website.climate update   --cache DIR [--today YYYY-MM-DD]   new scaled files and the prelim days by Range
    python -m website.climate build    --store DIR --cache DIR            write hail/c/, the index block and manifest
    python -m website.climate verify   --store DIR --cache DIR [--independent]   check the store (and re-read the source)

Measured on 2026-10-19 (this machine; research and refuter counts reproduced): one scaled month (June 2025,
56,872,702 bytes) downloaded whole in 1.03 s (56 MB/s) and read with h5py in about 3 s; the same three variables
read by HTTP Range (1 MB blocks) took 40 requests, 41,943,040 bytes and 9.35 s. The backfill and the monthly update
therefore download whole files (each deleted once its aggregates are written). The daily update reads, by Range with
256 KB blocks, the prelim days that are new or may still change (the days from the last valid day minus one to the end of
the month): measured 2.9 MB for two valid days and 5.8 MB for 18 days (22 requests); 1 MB blocks read 9.4 MB for the same
18 days, so the smaller block is used. Measured run times: the whole backfill 222 s for 63 months and the prelim month
(3.72 GB); a daily update with no new scaled file 7 to 8 s.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import io
import json
import math
import os
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path

from . import hail
from . import stations

FORMAT = "hail-climate-v1"             # the tile files under hail/c/
AGG_FORMAT = "climate-aggregates-v1"   # the per-month aggregate files in the cache
LEDGER_FORMAT = "climate-ledger-v1"
BUCKET = "https://noaa-nclimgrid-daily-pds.s3.amazonaws.com"
REPO_URL = f"https://github.com/{hail.REPO}"   # the repository address, from hail.REPO (one definition)
USER_AGENT = f"montana-hail-watch-climate/1 (+{REPO_URL})"
RETRY_ATTEMPTS = 3                     # tries per request before the failure is recorded (the update goes on)
RETRY_PAUSE_S = 2.0                    # the pause before try n + 1 is RETRY_PAUSE_S times n (tests set it to 0)
LICENSE_ATTRIBUTE = "no restrictions"   # the file's global attribute license = no restrictions
ATTRIBUTION = ("Source: NOAA nClimGrid-Daily (NOAA National Centers for Environmental Information). US government data; "
               "NOAA declares no restrictions; attribution requested. Values here are rounded and converted, not "
               "unaltered NOAA data, and no endorsement by NOAA is implied.")
ROWS = 596
COLS = 1385
UNITS_PER_DEG = 48                     # the grid in 1/48 degree units
LAT_CENTRE0 = 1179                     # lat centre of row i is (1179 + 2i) / 48 = 24.5625 + i / 24
LON_CENTRE0 = -5985                    # lon centre of column j is (-5985 + 2j) / 48 = -124.6875 + j / 24
LAT_EDGE = 1180                        # row i holds lat in (1178 + 2i, 1180 + 2i] (units of 1/48 degree)
LON_EDGE = 5986                        # column j holds lon in [-5986 + 2j, -5984 + 2j)
NOMINAL_TOLERANCE_DEG = 1e-5
PRCP_RANGE = (0.0, 2000.0)             # the files' valid_min and valid_max (checked against the attributes)
TEMP_RANGE = (-100.0, 100.0)
FILL_LIMIT = -900.0                    # -999.99 and any value this low is the prelim fill (counted, never summed)
FIRST_MONTH = (2021, 7)                # the store starts on July 1, 2021 (B5 D3)
FIVE_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26")
SEASONS = FIVE_SEASONS + ("2026-27",)  # the sixth season is the partial 2026-27 season
CALENDAR_YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
WATER_YEARS = (2021, 2022, 2023, 2024, 2025, 2026, 2027)
HOT_TENTHS = 322                       # a high of 32.2 C in tenths (90 F): D1
COLD_TENTHS = -178                     # a low of -17.8 C in tenths (0 F or colder)
NF = 13                                # fields per month and per period record
EXPECTED_MASK_CELLS = 25973            # the Montana centre test on the 1/24 degree grid (research; re-checked by verify)
EXPECTED_LAND_CELLS = 25902            # cells with a value on some day; the other 71 read "no land value"
PERIOD_FIELDS = ("days", "missing", "rain_hin", "rain_max_hin", "rain_max_date", "tmax_tenths_f", "tmax_date",
                 "tmin_tenths_f", "tmin_date", "hot90", "cold0", "freeze_thaw", "below32")
MONTH_FIELDS = ("days", "missing", "rain_cmm", "rain_max_cmm", "rain_max_day", "tmax_tenths_c", "tmax_day",
                "tmin_tenths_c", "tmin_day", "hot90", "cold0", "freeze_thaw", "below32")
MAX_NONE = -9999                       # the sentinels in month fields (never a real value)
MIN_NONE = 9999
RAIN_NONE = -1
DAYS_STALE = 5                         # the newest day older than this many days shows the stale line
BLOCK_BYTES = 1 << 20                  # the Range reader's default block size (the whole-file path does not use it)
PRELIM_BLOCK_BYTES = 1 << 18           # the daily prelim read: 256 KB blocks read 5.8 MB for 18 days, 1 MB blocks 9.4 MB
THRESHOLDS = {
    "hot_day": {"tenths_c": HOT_TENTHS, "f": 90,
                "text": ("a high of 90 F or more, where the high rounded to the hundredth of a degree C and then to the "
                         "tenth is at least 32.2 C (a high of 32.15 C or more)")},
    "freeze_thaw": {"text": "a high above 0 C and a low below 0 C (a high above 32 F and a low below 32 F)"},
    "below_32": {"tenths_c": 0, "f": 32, "text": "a low below 32 F (a low below 0 C)"},
    "at_or_below_0F": {"tenths_c": COLD_TENTHS, "f": 0, "text": "a low at or below 0 F (-17.8 C or colder, in tenths)"},
    "rounding": ("each daily temperature is rounded to the hundredth of a degree C, then to the tenth, half up (32.15 C "
                 "shows as 32.2 C); precipitation is rounded to the hundredth of a mm before it is summed"),
}


class ClimateError(Exception):
    """A climate source or store that cannot be used. The message is the plain words shown as the problem, in lower
    case, with no full stop, because the templates add it."""


class SourceError(ClimateError):
    """A source that did not give what was asked: a request that timed out or was dropped, a status other than the
    one asked for, a listing or a file that could not be read. ``reason`` is the exception's name or "HTTP nnn"; the
    ledger keeps it, and the page says it in words (WORDS_CLIMATE["reasons"]). ``what`` names the request."""

    def __init__(self, what: str, reason: str, detail: str = ""):
        self.what = what
        self.reason = reason
        self.detail = detail
        super().__init__(f"{what} did not load ({reason})" + (f": {detail}" if detail else ""))


def _retryable_status(code: int) -> bool:
    return code == 429 or code >= 500


def _send_with_retries(what: str, send):
    """Call send() until it returns a response that is not a timeout, a dropped connection or a 429 or 5xx status,
    with at most RETRY_ATTEMPTS tries and a pause that grows with each try. Returns that response; when every try
    fails, raises SourceError naming the last exception (or status)."""
    import requests
    reason, detail = "", ""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            response = send()
        except requests.RequestException as exc:
            reason, detail = type(exc).__name__, str(exc)[:200]
        else:
            if not _retryable_status(response.status_code):
                return response
            reason, detail = f"HTTP {response.status_code}", ""
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_PAUSE_S * attempt)
    raise SourceError(what, reason, detail)


# ---------------------------------------------------------------- grid, cells and tiles

def _np():
    import numpy
    return numpy


def _exact(value) -> Decimal:
    """The shortest decimal form of a float, as an exact Decimal (the rule website.hail.cell_for uses)."""
    number = float(value)
    if not math.isfinite(number):
        raise ClimateError("a grid coordinate is not a finite number")
    return Decimal(repr(number))


def climate_cell_for(lat, lon):
    """(i, j) of the grid cell that holds (lat, lon), or None when the point is off the grid.

    The half-open rule of website.hail.cell_for: a point on a cell edge goes to the cell to the south (larger lat
    edge belongs to the cell whose north edge it is) and to the east. Latitude is (south edge, north edge] and
    longitude is [west edge, east edge), computed in exact decimal arithmetic in units of 1/48 degree, where every
    edge is an integer: row i covers (1178 + 2i, 1180 + 2i] and column j covers [-5986 + 2j, -5984 + 2j)."""
    lat_units = _exact(lat) * UNITS_PER_DEG
    lon_units = _exact(lon) * UNITS_PER_DEG
    i = int(((lat_units - LAT_EDGE) / 2).to_integral_value(rounding=ROUND_CEILING))
    j = int(((lon_units + LON_EDGE) / 2).to_integral_value(rounding=ROUND_FLOOR))
    if 0 <= i < ROWS and 0 <= j < COLS:
        return i, j
    return None


def climate_centre(i: int, j: int) -> tuple[float, float]:
    """(lat, lon) of the centre of grid cell (i, j), each the nearest float to its exact value."""
    lat = float(Decimal(LAT_CENTRE0 + 2 * int(i)) / UNITS_PER_DEG)
    lon = float(Decimal(LON_CENTRE0 + 2 * int(j)) / UNITS_PER_DEG)
    return lat, lon


def climate_tile(i: int, j: int) -> tuple[int, int, int]:
    """(tile row, tile column, in-tile key) of grid cell (i, j): the B1 tile and key of the B1 cell that holds the
    cell's centre (website.hail.cell_for on the centre)."""
    lat, lon = climate_centre(i, j)
    row, col = hail.cell_for(lat, lon)
    return row // hail.TILE, col // hail.TILE, hail.cell_key(row, col)


def climate_tile_name(i: int, j: int) -> str:
    tr, tc, _key = climate_tile(i, j)
    return hail.tile_name(tr, tc)


def climate_tile_for_cell(row: int, col: int) -> str:
    """The name of the climate tile that holds the grid cell which holds the centre of B1 cell (row, col). This is
    the tile a page must fetch for that spot (it can differ from the B1 tile of the cell)."""
    cell = climate_cell_for(*hail.cell_centre(row, col))
    if cell is None:
        raise ClimateError("the spot is off the climate grid")
    return climate_tile_name(*cell)


def montana_cells(basemap_path=None):
    """The grid cells whose centres lie strictly inside the Montana land polygon: (i, j) int64 arrays in row-major
    order. The polygon is website/static/map/basemap.json's Montana feature (website.hail._montana_ring), and the
    test is the even-odd rule with a centre on an edge counted outside, as website.hail's strict mask does."""
    np = _np()
    ring = hail._montana_ring() if basemap_path is None else hail._montana_ring(basemap_path)
    lats = [y for _x, y in ring]
    lons = [x for x, _y in ring]
    i0 = max(0, math.floor((min(lats) - 24.5625) * 24) - 1)
    i1 = min(ROWS - 1, math.ceil((max(lats) - 24.5625) * 24) + 1)
    j0 = max(0, math.floor((min(lons) + 124.6875) * 24) - 1)
    j1 = min(COLS - 1, math.ceil((max(lons) + 124.6875) * 24) + 1)
    ii = np.arange(i0, i1 + 1)
    jj = np.arange(j0, j1 + 1)
    Y = ((LAT_CENTRE0 + 2 * ii).astype(np.float64) / 48.0)[:, None]
    X = ((LON_CENTRE0 + 2 * jj).astype(np.float64) / 48.0)[None, :]
    inside = np.zeros((ii.size, jj.size), dtype=bool)
    on_edge = np.zeros((ii.size, jj.size), dtype=bool)
    n = len(ring)
    for k in range(n):
        x1, y1 = ring[k]
        x2, y2 = ring[(k + 1) % n]
        if y1 == y2:
            continue
        cross = (y1 > Y) != (y2 > Y)
        if not cross.any():
            continue
        xi = x1 + (Y - y1) * ((x2 - x1) / (y2 - y1))
        inside ^= cross & (X < xi)
        on_edge |= cross & (X == xi)
    flat = np.flatnonzero(inside & ~on_edge)
    return (i0 + flat // jj.size).astype(np.int64), (j0 + flat % jj.size).astype(np.int64)


def mask_digest(ci, cj) -> str:
    np = _np()
    h = hashlib.sha256()
    h.update(np.asarray(ci, dtype="<i8").tobytes())
    h.update(np.asarray(cj, dtype="<i8").tobytes())
    return h.hexdigest()


# ---------------------------------------------------------------- rounding, daily arrays and month fields

def _decimal_centi(value) -> int:
    """Hundredths of a value by exact decimal arithmetic, half up toward plus infinity (the reference rule)."""
    return int((_exact(value) * 100 + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))


def _centi(np, values):
    """Hundredths (int64) of a float array, half up. The float rule is floor(100 x value + 1/2); a value within
    1e-7 of a tie is rounded with exact decimal arithmetic instead."""
    arr = np.asarray(values, dtype=np.float64)
    flat = arr.ravel()
    x = flat * 100.0
    out = np.floor(x + 0.5)
    frac = x - np.floor(x)
    for k in np.flatnonzero(np.abs(frac - 0.5) < 1e-7):
        out[k] = _decimal_centi(flat[k])
    return out.astype(np.int64).reshape(arr.shape)


def daily_arrays(np, prcp, tmax, tmin):
    """Daily values for float64 arrays shaped (days, cells).

    Returns (valid, cmm, tx, tn, fill): valid is True where all three inputs are real numbers inside the file's
    valid range; cmm is precipitation in hundredths of a mm; tx and tn are the high and the low in tenths of a degree
    C (the value rounded to the hundredth, then to the tenth, half up); all three are 0 where not valid. fill marks
    the prelim fill (-999.99 and anything at or below FILL_LIMIT), which is never valid."""
    with np.errstate(invalid="ignore"):
        ok_p = np.isfinite(prcp) & (prcp >= PRCP_RANGE[0]) & (prcp <= PRCP_RANGE[1])
        ok_x = np.isfinite(tmax) & (tmax >= TEMP_RANGE[0]) & (tmax <= TEMP_RANGE[1])
        ok_n = np.isfinite(tmin) & (tmin >= TEMP_RANGE[0]) & (tmin <= TEMP_RANGE[1])
        fill = (prcp <= FILL_LIMIT) | (tmax <= FILL_LIMIT) | (tmin <= FILL_LIMIT)
    valid = ok_p & ok_x & ok_n
    cmm = _centi(np, np.where(valid, prcp, 0.0))
    tx = (_centi(np, np.where(valid, tmax, 0.0)) + 5) // 10
    tn = (_centi(np, np.where(valid, tmin, 0.0)) + 5) // 10
    cmm = np.where(valid, cmm, 0).astype(np.int64)
    tx = np.where(valid, tx, 0).astype(np.int64)
    tn = np.where(valid, tn, 0).astype(np.int64)
    return valid, cmm, tx, tn, fill


def month_fields(np, valid, cmm, tx, tn, avail: int):
    """The 13 month fields per cell (int64 array (cells, NF)) from daily arrays, using days 1 to avail only.

    Fields (MONTH_FIELDS): days available, missing days (an available day with an invalid input), rain total in
    hundredths of a mm, largest rain in hundredths of a mm (-1 when none) and its day, highest and lowest tenths of
    C (sentinels when none) and their days (0 when none), and the counts of hot, at-or-below-0 F, freeze-thaw and
    below-32 F days. The first day with a maximum or minimum is the one kept."""
    days = valid.shape[0]
    cells = valid.shape[1]
    dayno = np.arange(1, days + 1, dtype=np.int64)[:, None]
    in_avail = dayno <= avail
    inpm = in_avail & valid
    any_valid = inpm.any(axis=0)
    missing = (in_avail & ~valid).sum(axis=0)
    rain = np.where(inpm, cmm, 0).sum(axis=0)
    rsrc = np.where(inpm, cmm, RAIN_NONE)
    rmax = rsrc.max(axis=0)
    rday = np.where(rmax >= 0, rsrc.argmax(axis=0) + 1, 0)
    xsrc = np.where(inpm, tx, MAX_NONE)
    xmax = xsrc.max(axis=0)
    xday = np.where(any_valid, xsrc.argmax(axis=0) + 1, 0)
    nsrc = np.where(inpm, tn, MIN_NONE)
    nmin = nsrc.min(axis=0)
    nday = np.where(any_valid, nsrc.argmin(axis=0) + 1, 0)
    hot = (inpm & (tx >= HOT_TENTHS)).sum(axis=0)
    cold0 = (inpm & (tn <= COLD_TENTHS)).sum(axis=0)
    frz = (inpm & (tx > 0) & (tn < 0)).sum(axis=0)
    below = (inpm & (tn < 0)).sum(axis=0)
    out = np.stack([np.full(cells, avail, dtype=np.int64), missing, rain, rmax, rday, xmax, xday, nmin, nday,
                    hot, cold0, frz, below], axis=1)
    return out.astype(np.int64)


def combine(np, parts, years, months):
    """Period records for one period from its months (parts: the month field arrays in order; years and months: the
    calendar year and month of each part). Returns one list of NF values per cell: the period fields
    (PERIOD_FIELDS), with None for a missing extreme. Rain is summed in hundredths of a mm and converted once."""
    M = np.stack(parts, axis=0)
    n = M.shape[1]
    cols = np.arange(n)
    yr = np.asarray(years, dtype=np.int64)
    mo = np.asarray(months, dtype=np.int64)
    days = M[:, :, 0].sum(axis=0)
    missing = M[:, :, 1].sum(axis=0)
    rain = M[:, :, 2].sum(axis=0)
    ir = M[:, :, 3].argmax(axis=0)
    rmax = M[:, :, 3].max(axis=0)
    rmax_date = yr[ir] * 10000 + mo[ir] * 100 + M[ir, cols, 4]
    it = M[:, :, 5].argmax(axis=0)
    tmax = M[:, :, 5].max(axis=0)
    tmax_date = yr[it] * 10000 + mo[it] * 100 + M[it, cols, 6]
    inn = M[:, :, 7].argmin(axis=0)
    tmin = M[:, :, 7].min(axis=0)
    tmin_date = yr[inn] * 10000 + mo[inn] * 100 + M[inn, cols, 8]
    hot = M[:, :, 9].sum(axis=0)
    cold0 = M[:, :, 10].sum(axis=0)
    frz = M[:, :, 11].sum(axis=0)
    below = M[:, :, 12].sum(axis=0)
    rain_hin = (10 * rain + 127) // 254
    rmax_hin = (10 * rmax + 127) // 254
    tmax_f = (18 * tmax + 3205) // 10
    tmin_f = (18 * tmin + 3205) // 10
    lists = [days.tolist(), missing.tolist(), rain_hin.tolist(), rmax_hin.tolist(), rmax_date.tolist(),
             tmax_f.tolist(), tmax_date.tolist(), tmin_f.tolist(), tmin_date.tolist(), hot.tolist(),
             cold0.tolist(), frz.tolist(), below.tolist()]
    valid = (days - missing).tolist()
    rmax_l = rmax.tolist()
    out = []
    for c in range(n):
        row = [lists[q][c] for q in range(NF)]
        if rmax_l[c] < 0:
            row[3] = None
            row[4] = None
        if valid[c] <= 0:
            row[5] = row[6] = row[7] = row[8] = None
        out.append(row)
    return out


def period_members(label_or_year, kind: str):
    """The (year, month) pairs of a period: kind "season" (label "2021-22"), "calendar" (year) or "water" (year)."""
    if kind == "season":
        first = int(label_or_year[:4])
        return ([(first, m) for m in range(7, 13)] + [(first + 1, m) for m in range(1, 7)])
    if kind == "calendar":
        y = int(label_or_year)
        return [(y, m) for m in range(1, 13)]
    if kind == "water":
        y = int(label_or_year)
        return [(y - 1, m) for m in range(10, 13)] + [(y, m) for m in range(1, 10)]
    raise ValueError(kind)


def months_between(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    out = []
    y, m = first
    while (y, m) <= last:
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def days_in(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


# ---------------------------------------------------------------- the Range reader and the files

class RangeFile:
    """A read-only file object over HTTP Range requests (1 MB blocks, cached), for h5py.File(fileobj).

    Requests and bytes are counted so that the run record can say what was read. A block that cannot be read (a
    timeout after RETRY_ATTEMPTS tries, a short answer) raises SourceError. The first such failure is also kept in
    ``failure`` as plain data (what, reason, detail): an exception object kept on the reader would make a reference
    cycle, and h5py then crashes the interpreter at exit (found with the prelim test, not a guess). The caller
    re-raises a new SourceError from the data."""

    def __init__(self, url: str, size: int, block: int = BLOCK_BYTES, session=None):
        import requests
        self.url = url
        self.size = int(size)
        self.block = int(block)
        self.pos = 0
        self.cache: dict[int, bytes] = {}
        self.requests = 0
        self.bytes = 0
        self.failure: dict | None = None
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        else:
            self.pos = self.size + offset
        return self.pos

    def _fetch(self, b: int) -> bytes:
        if b not in self.cache:
            start = b * self.block
            end = min(self.size, start + self.block) - 1
            what = f"the read of bytes {start} to {end} of {Path(self.url).name}"
            r = _send_with_retries(what, lambda: self.session.get(
                self.url, headers={"Range": f"bytes={start}-{end}"}, timeout=300))
            if r.status_code != 206:
                raise SourceError(what, f"HTTP {r.status_code}")
            if len(r.content) != end - start + 1:
                raise SourceError(what, "ShortRead", f"{len(r.content)} of {end - start + 1} bytes")
            self.requests += 1
            self.bytes += len(r.content)
            self.cache[b] = r.content
        return self.cache[b]

    def _read(self, n=-1) -> bytes:
        if n is None or n < 0:
            n = self.size - self.pos
        out = bytearray()
        while n > 0 and self.pos < self.size:
            b = self.pos // self.block
            off = self.pos - b * self.block
            piece = self._fetch(b)[off:off + n]
            if not piece:
                break
            out += piece
            self.pos += len(piece)
            n -= len(piece)
        return bytes(out)

    def read(self, n=-1):
        try:
            return self._read(n)
        except SourceError as exc:
            if self.failure is None:
                self.failure = {"what": exc.what, "reason": exc.reason, "detail": exc.detail}
            raise

    def readinto(self, buf):
        data = self.read(len(buf))
        buf[:len(data)] = data
        return len(data)


def _attr_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if hasattr(value, "tolist") and not isinstance(value, str):
        value = value.tolist()
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
    return str(value)


def check_file(f, year: int, month: int) -> dict:
    """The facts a month file must have before it is read: the license attribute, the coordinates against the
    nominal grid, the time axis (the month's days, in order), the three variables' shapes and the valid ranges.
    Raises ClimateError when any of them differs; returns what was checked."""
    np = _np()
    license_text = _attr_text(f.attrs.get("license", ""))
    if license_text != LICENSE_ATTRIBUTE:
        raise ClimateError(f"the file's license attribute is not {LICENSE_ATTRIBUTE!r}")
    lat = np.asarray(f["lat"][:], dtype=np.float64)
    lon = np.asarray(f["lon"][:], dtype=np.float64)
    if lat.size != ROWS or lon.size != COLS:
        raise ClimateError("the grid is not 596 by 1,385 cells")
    dev_lat = float(np.abs(lat - (LAT_CENTRE0 + 2 * np.arange(ROWS)) / 48.0).max())
    dev_lon = float(np.abs(lon - (LON_CENTRE0 + 2 * np.arange(COLS)) / 48.0).max())
    if dev_lat > NOMINAL_TOLERANCE_DEG or dev_lon > NOMINAL_TOLERANCE_DEG:
        raise ClimateError("the grid coordinates do not match the nominal 1/24 degree grid")
    times = np.asarray(f["time"][:], dtype=np.int64)
    dim = days_in(year, month)
    first = date(1800, 1, 1) + timedelta(days=int(times[0])) if times.size else None
    if times.size != dim or first != date(year, month, 1) or not np.all(np.diff(times) == 1):
        raise ClimateError(f"the file's time axis is not the days of {year}-{month:02d}")
    ranges = {}
    for name, expect in (("prcp", PRCP_RANGE), ("tmax", TEMP_RANGE), ("tmin", TEMP_RANGE)):
        ds = f[name]
        if ds.shape != (dim, ROWS, COLS) or ds.dtype.kind != "f":
            raise ClimateError(f"{name} does not have the shape and type of the grid")
        lo = float(np.asarray(ds.attrs["valid_min"]).ravel()[0])
        hi = float(np.asarray(ds.attrs["valid_max"]).ravel()[0])
        if (lo, hi) != expect:
            raise ClimateError(f"{name} has valid range {lo} to {hi}, not {expect[0]} to {expect[1]}")
        ranges[name] = [lo, hi]
    return {"license": f"license = {license_text}", "lat_max_dev_deg": dev_lat, "lon_max_dev_deg": dev_lon,
            "days": dim, "valid_ranges": ranges}


def read_box(f, box, days=None) -> dict:
    """The three variables for the box (i0, i1, j0, j1) (end exclusive) and, optionally, the days (d0, d1) as
    0-based slices. Returns float64 arrays shaped (days, rows, cols)."""
    np = _np()
    i0, i1, j0, j1 = box
    dsl = slice(None) if days is None else slice(days[0], days[1])
    sl = (dsl, slice(i0, i1), slice(j0, j1))
    return {name: np.asarray(f[name][sl], dtype=np.float64) for name in ("prcp", "tmax", "tmin")}


def mask_box(ci, cj):
    """The bounding box (i0, i1, j0, j1), end exclusive, of the mask cells."""
    return int(ci.min()), int(ci.max()) + 1, int(cj.min()), int(cj.max()) + 1


def select_cells(values: dict, box, ci, cj) -> dict:
    """The mask cells' values from box arrays: (days, cells) float64 arrays."""
    i0, _i1, j0, _j1 = box
    ri = ci - i0
    rj = cj - j0
    return {name: arr[:, ri, rj] for name, arr in values.items()}


def _url(ym: str, kind: str, year: int | None = None) -> str:
    year = int(ym[:4]) if year is None else year
    return f"{BUCKET}/access/grids/{year}/ncdd-{ym.replace('-', '')}-grd-{kind}.nc"


def list_year(year: int, session=None) -> dict:
    """The objects under access/grids/YYYY/ with their size, ETag and last-modified time (ListObjectsV2, paged). A
    page that cannot be read raises SourceError (after RETRY_ATTEMPTS tries for a timeout, a dropped connection or a
    5xx or 429 status), so that the update can record the listing as the failure."""
    import requests
    ns = "{http://s3.amazonaws.com/doc/2006-03-01/}"
    sess = session or requests.Session()
    sess.headers["User-Agent"] = USER_AGENT
    what = f"the NOAA file list for {year}"
    objects = {}
    token = None
    while True:
        params = {"list-type": "2", "prefix": f"access/grids/{year}/", "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        r = _send_with_retries(what, lambda: sess.get(BUCKET + "/", params=params, timeout=120))
        if r.status_code != 200:
            raise SourceError(what, f"HTTP {r.status_code}")
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError as exc:
            raise SourceError(what, "ParseError", str(exc)[:200]) from None
        if not root.tag.endswith("ListBucketResult"):
            raise SourceError(what, "NotAListing")
        try:
            for item in root.findall(f"{ns}Contents"):
                key = item.findtext(f"{ns}Key")
                objects[key] = {"size": int(item.findtext(f"{ns}Size")),
                                "etag": (item.findtext(f"{ns}ETag") or "").strip('"'),
                                "last_modified": item.findtext(f"{ns}LastModified")}
        except (TypeError, ValueError) as exc:
            raise SourceError(what, "BadListing", str(exc)[:200]) from None
        if (root.findtext(f"{ns}IsTruncated") or "false").lower() != "true":
            break
        token = root.findtext(f"{ns}NextContinuationToken")
        if not token:
            raise SourceError(what, "BadListing", "truncated without a token")
    return objects


def plan_months(objects: dict, today: date) -> list[dict]:
    """The months from July 2021 to the newest month with a file, each with the file it uses.

    A scaled file is used when it exists. A prelim file is used only when no scaled file exists for that month
    (kind "prelim"; the index names these months). A month with neither is "missing" and makes the state partial.
    Months after today, and months after the newest file, are not planned."""
    scaled, prelim = {}, {}
    for key, meta in objects.items():
        parts = key.split("/")
        if len(parts) != 4 or not parts[3].startswith("ncdd-") or not parts[3].endswith(".nc"):
            continue
        name = parts[3]
        ym = name[5:11]
        kind = "scaled" if name.endswith("-grd-scaled.nc") else "prelim" if name.endswith("-grd-prelim.nc") else None
        if kind is None or not ym.isdigit():
            continue
        month = (int(ym[:4]), int(ym[4:]))
        (scaled if kind == "scaled" else prelim)[month] = {"key": key, **meta}
    present = set(scaled) | set(prelim)
    limit = (today.year, today.month)
    newest = max((m for m in present if m <= limit), default=None)
    plan = []
    if newest is None:
        return plan
    for (y, m) in months_between(FIRST_MONTH, newest):
        ym = f"{y:04d}-{m:02d}"
        if (y, m) in scaled:
            kind, entry = "scaled", scaled[(y, m)]
        elif (y, m) in prelim:
            kind, entry = "prelim", prelim[(y, m)]
        else:
            kind, entry = "missing", None
        plan.append({"month": ym, "kind": kind, "days": days_in(y, m),
                     "key": entry["key"] if entry else None,
                     "size": entry["size"] if entry else None,
                     "etag": entry["etag"] if entry else None,
                     "last_modified": entry["last_modified"] if entry else None})
    return plan


def _download_once(url: str, part: Path, sess) -> tuple:
    """One download attempt into ``part``. Returns (info, None) when the body arrived, or (None, status) when the
    source answered with another status. A download that fails in the middle (a timeout, a dropped connection) raises.
    In every case that does not return the body, ``part`` is removed first."""
    md5 = hashlib.md5()
    sha = hashlib.sha256()
    total = 0
    started = time.time()
    try:
        with sess.get(url, stream=True, timeout=600) as r:
            if r.status_code != 200:
                part.unlink(missing_ok=True)
                return None, r.status_code
            with open(part, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
                    md5.update(chunk)
                    sha.update(chunk)
                    total += len(chunk)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    seconds = time.time() - started
    return ({"bytes": total, "md5": md5.hexdigest(), "sha256": sha.hexdigest(), "seconds": round(seconds, 3),
             "mb_per_s": round(total / 1e6 / seconds, 2) if seconds > 0 else None}, None)


def fetch_whole(url: str, dest: Path, expect_size: int, session=None) -> dict:
    """Download a whole file to dest (through a .part name, then renamed). A download that is cut short, times out
    or gets a 5xx or 429 status is tried again (RETRY_ATTEMPTS tries). The .part file is removed on every exit that
    does not rename it. Raises SourceError when the download keeps failing and ClimateError when the bytes are not an
    HDF5 file. Returns the bytes, MD5, SHA-256 and seconds."""
    import requests
    sess = session or requests.Session()
    sess.headers["User-Agent"] = USER_AGENT
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    what = f"the download of {dest.name}"
    reason, detail = "", ""
    info = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            info, status = _download_once(url, part, sess)
        except requests.RequestException as exc:
            info, status = None, None
            reason, detail = type(exc).__name__, str(exc)[:200]
        else:
            if status is None and info["bytes"] == expect_size:
                break
            if status is not None and not _retryable_status(status):
                raise SourceError(what, f"HTTP {status}")
            if status is not None:
                reason, detail = f"HTTP {status}", ""
            else:
                part.unlink(missing_ok=True)
                reason, detail = "ShortDownload", f"{info['bytes']} of {expect_size} bytes"
            info = None
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_PAUSE_S * attempt)
    else:
        raise SourceError(what, reason, detail)
    with open(part, "rb") as fh:
        head = fh.read(8)
    if head != b"\x89HDF\r\n\x1a\n":
        part.unlink(missing_ok=True)
        raise ClimateError(f"{dest.name} is not an HDF5 file")
    os.replace(part, dest)
    return info


# ---------------------------------------------------------------- the cache

def _cache_paths(cache: Path) -> dict:
    return {"root": cache, "agg": cache / "aggregates", "days": cache / "days", "months": cache / "months",
            "ledger": cache / "ledger.json", "runs": cache / "runs.jsonl", "listings": cache / "listings"}


def _ensure(paths: dict) -> None:
    for key in ("root", "agg", "days", "months", "listings"):
        paths[key].mkdir(parents=True, exist_ok=True)


def _load_ledger(paths: dict) -> dict:
    if paths["ledger"].exists():
        doc = json.loads(paths["ledger"].read_text(encoding="utf-8"))
        if doc.get("format") != LEDGER_FORMAT:
            raise ClimateError("the climate ledger in the cache is not in the expected format")
        return doc
    return {"format": LEDGER_FORMAT, "plan": [], "months": {}, "requests": 0}


def _save_ledger(paths: dict, ledger: dict) -> None:
    tmp = paths["ledger"].with_name("ledger.json.tmp")
    tmp.write_text(json.dumps(ledger, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, paths["ledger"])


def _append_run(paths: dict, record: dict) -> None:
    with open(paths["runs"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _save_npz(path: Path, **arrays) -> None:
    np = _np()
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        np.savez_compressed(fh, **arrays)
    os.replace(tmp, path)


def _meta_array(meta: dict):
    np = _np()
    return np.array(json.dumps(meta, sort_keys=True))


def _load_npz(path: Path) -> dict:
    np = _np()
    with np.load(path, allow_pickle=False) as z:
        out = {k: z[k] for k in z.files}
    out["meta"] = json.loads(str(out["meta"]))
    return out


def aggregate_path(paths: dict, ym: str) -> Path:
    return paths["agg"] / f"{ym}.npz"


def _month_record_from_file(np, file_path: Path, ym: str, kind: str, entry: dict, ci, cj, box, digest: str,
                            facts_store: dict) -> dict:
    """Aggregate one whole month file (scaled or prelim) for the mask cells; the caller deletes the file."""
    year, month = int(ym[:4]), int(ym[5:])
    import h5py
    t0 = time.time()
    with h5py.File(file_path, "r") as f:
        facts = check_file(f, year, month)
        raw = read_box(f, box)
    cells = select_cells(raw, box, ci, cj)
    t1 = time.time()
    valid, cmm, tx, tn, fill = daily_arrays(np, cells["prcp"], cells["tmax"], cells["tmin"])
    dim = days_in(year, month)
    if kind == "scaled":
        avail = dim
    else:
        has_day = valid.any(axis=1)
        avail = int(np.flatnonzero(has_day)[-1] + 1) if has_day.any() else 0
    dayno = np.arange(1, dim + 1)
    fill_in_avail = int((fill & (dayno[:, None] <= avail)).sum())
    fill_seen = int(fill.sum())
    fields = month_fields(np, valid, cmm, tx, tn, avail)
    has_value = (valid & (np.arange(1, dim + 1)[:, None] <= avail)).any(axis=0)
    through = f"{ym}-{avail:02d}" if avail else None
    meta = {"format": AGG_FORMAT, "month": ym, "kind": kind, "avail_days": avail, "days_in_month": dim,
            "through": (date(year, month, avail).isoformat() if avail else None),
            "file": entry.get("key"), "etag": entry.get("etag"), "bytes": entry.get("bytes"),
            "md5": entry.get("md5"), "sha256": entry.get("sha256"), "mask_cells": int(ci.size),
            "mask_sha256": digest, "fill_values_seen": fill_seen, "fill_values_in_available_days": fill_in_avail,
            "valid_cell_days": int(valid[:avail].sum()) if avail else 0,
            "read_seconds": round(t1 - t0, 3), "facts": facts, "through_text": through}
    facts_store.update({"ym": ym})
    return {"fields": fields, "has_value": has_value, "meta": meta, "valid": valid, "cmm": cmm, "tx": tx, "tn": tn,
            "fill": fill}


def save_month_aggregate(paths: dict, ym: str, rec: dict) -> None:
    np = _np()
    meta = dict(rec["meta"])
    _save_npz(aggregate_path(paths, ym), fields=rec["fields"].astype(np.int32),
              has_value=rec["has_value"].astype(np.bool_), meta=_meta_array(meta))


def _load_aggregate(paths: dict, ym: str):
    path = aggregate_path(paths, ym)
    if not path.exists():
        return None
    doc = _load_npz(path)
    if doc["meta"].get("format") != AGG_FORMAT:
        raise ClimateError(f"the aggregate for {ym} is not in the expected format")
    return {"fields": doc["fields"].astype(_np().int64), "has_value": doc["has_value"].astype(bool),
            "meta": doc["meta"]}


# ---------------------------------------------------------------- the daily cache (prelim months)

def _days_path(paths: dict, ym: str) -> Path:
    return paths["days"] / f"{ym}.npz"


def update_prelim(paths: dict, plan_entry: dict, ci, cj, box, digest: str, session=None, log=None) -> dict:
    """Bring a prelim month's per-day arrays up to date by Range reads of the days that are new or that may still
    be revised (the last two valid days and every day after them), then aggregate the month."""
    np = _np()
    import h5py
    ym = plan_entry["month"]
    year, month = int(ym[:4]), int(ym[5:])
    dim = days_in(year, month)
    cells = int(ci.size)
    path = _days_path(paths, ym)
    if path.exists():
        cache = _load_npz(path)
        if cache["meta"].get("mask_sha256") != digest or cache["valid"].shape != (dim, cells):
            cache = None
    else:
        cache = None
    if cache is None:
        cache = {"valid": np.zeros((dim, cells), dtype=bool), "cmm": np.zeros((dim, cells), dtype=np.int64),
                 "tx": np.zeros((dim, cells), dtype=np.int64), "tn": np.zeros((dim, cells), dtype=np.int64),
                 "fill": np.zeros((dim, cells), dtype=bool), "read": np.zeros(dim, dtype=bool),
                 "meta": {"mask_sha256": digest, "month": ym}}
    else:
        for name in ("cmm", "tx", "tn"):
            cache[name] = cache[name].astype(np.int64)
    read_flags = cache["read"].copy()
    has_day = cache["valid"].any(axis=1)
    through_prev = int(np.flatnonzero(has_day)[-1] + 1) if has_day.any() else 0
    wanted = [d for d in range(1, dim + 1)
              if (not read_flags[d - 1]) or d >= max(1, through_prev - 1)]
    rf = RangeFile(_url(ym, "prelim"), plan_entry["size"], block=PRELIM_BLOCK_BYTES, session=session)
    t0 = time.time()
    try:
        with h5py.File(rf, "r") as f:
            facts = check_file(f, year, month)
            for d in wanted:
                raw = read_box(f, box, days=(d - 1, d))
                cells_raw = select_cells(raw, box, ci, cj)
                v, cmm, tx, tn, fill = daily_arrays(np, cells_raw["prcp"], cells_raw["tmax"], cells_raw["tmin"])
                cache["valid"][d - 1] = v[0]
                cache["cmm"][d - 1] = cmm[0]
                cache["tx"][d - 1] = tx[0]
                cache["tn"][d - 1] = tn[0]
                cache["fill"][d - 1] = fill[0]
                cache["read"][d - 1] = True
    except Exception:
        if rf.failure is not None:
            raise SourceError(rf.failure["what"], rf.failure["reason"], rf.failure["detail"]) from None
        raise
    seconds = time.time() - t0
    has_day = cache["valid"].any(axis=1)
    avail = int(np.flatnonzero(has_day)[-1] + 1) if has_day.any() else 0
    meta = dict(cache["meta"])
    meta.update({"through_day": avail, "days_read": [int(d) for d in wanted], "requests": rf.requests,
                 "bytes": rf.bytes, "read_seconds": round(seconds, 3), "etag": plan_entry.get("etag"),
                 "file": plan_entry.get("key"), "size": plan_entry.get("size"), "facts": facts})
    _save_npz(path, valid=cache["valid"], cmm=cache["cmm"].astype(np.int32), tx=cache["tx"].astype(np.int32),
              tn=cache["tn"].astype(np.int32), fill=cache["fill"], read=cache["read"],
              meta=_meta_array(meta))
    if log:
        log(f"  prelim {ym}: read days {wanted[0] if wanted else '-'}..{wanted[-1] if wanted else '-'} "
            f"({len(wanted)} days), {rf.requests} requests, {rf.bytes} bytes, {round(seconds, 2)} s; through {avail}")
    fields = month_fields(np, cache["valid"], cache["cmm"], cache["tx"], cache["tn"], avail)
    has_value = (cache["valid"] & (np.arange(1, dim + 1)[:, None] <= avail)).any(axis=0)
    fill_seen = int(cache["fill"].sum())
    fill_in_avail = int((cache["fill"] & (np.arange(1, dim + 1)[:, None] <= avail)).sum())
    agg_meta = {"format": AGG_FORMAT, "month": ym, "kind": "prelim", "avail_days": avail, "days_in_month": dim,
                "through": (date(year, month, avail).isoformat() if avail else None),
                "file": plan_entry.get("key"), "etag": plan_entry.get("etag"), "bytes": plan_entry.get("size"),
                "md5": None, "sha256": None, "mask_cells": cells, "mask_sha256": digest,
                "fill_values_seen": fill_seen, "fill_values_in_available_days": fill_in_avail,
                "valid_cell_days": int(cache["valid"][:avail].sum()) if avail else 0,
                "read_seconds": round(seconds, 3), "facts": facts, "through_text": None,
                "days_read": [int(d) for d in wanted], "requests": rf.requests, "range_bytes": rf.bytes}
    return {"fields": fields, "has_value": has_value, "meta": agg_meta}


# ---------------------------------------------------------------- update and backfill

def _mask_and_box(basemap_path=None):
    ci, cj = montana_cells(basemap_path)
    return ci, cj, mask_box(ci, cj), mask_digest(ci, cj)


def _failure(exc: BaseException) -> dict:
    """One failed request or file as the ledger keeps it. The reason is the exception's name (or "HTTP nnn"), or
    "CheckFailed" for a file that does not pass its checks, or "OSError"; the page turns it into words."""
    if isinstance(exc, SourceError):
        reason, what, detail = exc.reason, exc.what, exc.detail
    elif isinstance(exc, ClimateError):
        reason, what, detail = "CheckFailed", "the file", str(exc)
    elif isinstance(exc, OSError):
        reason, what, detail = "OSError", "the file", str(exc)
    else:
        reason, what, detail = type(exc).__name__, "the file", str(exc)
    return {"reason": reason, "what": what, "detail": str(detail)[:300],
            "when": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _finish_update(paths: dict, ledger: dict, failures: dict, *, backfill: bool, today: date, started: float,
                   planned: int, fetched: int, fetched_bytes: int, kinds: dict) -> dict:
    """Write the ledger, with this run's failures (build_store reads them), and the run record."""
    ledger["failures"] = failures
    _save_ledger(paths, ledger)
    run = {"action": "backfill" if backfill else "update", "today": today.isoformat(),
           "months_planned": planned, "scaled_fetched": fetched, "bytes_fetched": fetched_bytes,
           "seconds": round(time.time() - started, 2), "finished_utc": datetime.now(timezone.utc).isoformat(),
           "kinds": kinds, "failures": failures, "months_failed": sorted(failures["months"])}
    _append_run(paths, run)
    return run


def run_update(cache: Path, today: date, *, backfill: bool = False, session=None, log=print,
               basemap_path=None) -> dict:
    """Plan the months from the bucket listing, aggregate every scaled month whose file is new or changed (a backfill
    does all of them), keep prelim months current by Range, and write the ledger and a run record. Each scaled file
    is downloaded whole, aggregated and deleted; the month's aggregate is kept.

    A source failure does not stop the update (B5 D16). A listing that fails leaves the last plan in the ledger and
    records the listing as failed. A month whose request or file fails is recorded as failed, and the other months
    go on. Both go into the ledger ("failures") and the run record, and build_store turns them into the state."""
    paths = _cache_paths(Path(cache))
    _ensure(paths)
    ledger = _load_ledger(paths)
    started = time.time()
    failures: dict = {"listing": None, "months": {}}
    objects: dict = {}
    try:
        for year in range(FIRST_MONTH[0], today.year + 1):
            listing = list_year(year, session=session)
            objects.update(listing)
            (paths["listings"] / f"{year}.json").write_text(json.dumps(listing, indent=1, sort_keys=True) + "\n",
                                                            encoding="utf-8")
        plan = plan_months(objects, today)
        if not plan:
            raise SourceError("the NOAA file list", "EmptyListing")
    except ClimateError as exc:
        failures["listing"] = _failure(exc)
        log(f"the NOAA file list did not load ({failures['listing']['reason']}); the last planned months are kept")
        return _finish_update(paths, ledger, failures, backfill=backfill, today=today, started=started,
                              planned=len(ledger.get("plan", [])), fetched=0, fetched_bytes=0, kinds={})
    np = _np()
    ci, cj, box, digest = _mask_and_box(basemap_path)
    ledger["plan"] = plan
    log(f"planned {len(plan)} months: " + ", ".join(f"{p['month']} {p['kind']}" for p in plan if p["kind"] != "scaled")
        + f"; scaled {sum(1 for p in plan if p['kind'] == 'scaled')}")
    fetched = 0
    fetched_bytes = 0
    for entry in plan:
        ym = entry["month"]
        if entry["kind"] == "missing":
            ledger["months"][ym] = {"kind": "missing", "note": "no file in the bucket for this month"}
            continue
        try:
            existing = _load_aggregate(paths, ym)
            if entry["kind"] == "scaled":
                if (existing and existing["meta"].get("kind") == "scaled"
                        and existing["meta"].get("etag") == entry["etag"]):
                    continue
                url = _url(ym, "scaled")
                dest = paths["months"] / f"{ym}-scaled.nc"
                info = fetch_whole(url, dest, entry["size"], session=session)
                fetched += 1
                fetched_bytes += info["bytes"]
                info.update({"etag_listing": entry["etag"], "etag_matches_md5": info["md5"] == entry["etag"]})
                try:
                    rec = _month_record_from_file(np, dest, ym, "scaled", {**entry, "key": entry["key"], **{
                        "bytes": info["bytes"], "md5": info["md5"], "sha256": info["sha256"]}}, ci, cj, box, digest,
                        {})
                finally:
                    dest.unlink(missing_ok=True)
                rec["meta"]["download"] = info
                save_month_aggregate(paths, ym, rec)
                _drop_days(paths, ym)
                ledger["months"][ym] = {"kind": "scaled", "etag": entry["etag"], "bytes": info["bytes"],
                                        "seconds": info["seconds"], "mb_per_s": info["mb_per_s"],
                                        "read_seconds": rec["meta"]["read_seconds"],
                                        "fill_values_in_available_days": rec["meta"]["fill_values_in_available_days"],
                                        "valid_cell_days": rec["meta"]["valid_cell_days"],
                                        "through": rec["meta"]["through"], "md5": info["md5"],
                                        "etag_matches_md5": info["md5"] == entry["etag"]}
                log(f"  scaled {ym}: {info['bytes']} bytes in {info['seconds']} s, read {rec['meta']['read_seconds']} s, "
                    f"fill in days {rec['meta']['fill_values_in_available_days']}")
            elif entry["kind"] == "prelim":
                rec = update_prelim(paths, entry, ci, cj, box, digest, session=session, log=log)
                save_month_aggregate(paths, ym, rec)
                ledger["months"][ym] = {"kind": "prelim", "etag": entry["etag"], "through": rec["meta"]["through"],
                                        "days_read": rec["meta"]["days_read"], "requests": rec["meta"]["requests"],
                                        "range_bytes": rec["meta"]["range_bytes"]}
        except (ClimateError, OSError, KeyError) as exc:
            failures["months"][ym] = _failure(exc)
            log(f"  {ym} did not load ({failures['months'][ym]['reason']}); the other months are kept")
    return _finish_update(paths, ledger, failures, backfill=backfill, today=today, started=started,
                          planned=len(plan), fetched=fetched, fetched_bytes=fetched_bytes,
                          kinds={k: sum(1 for p in plan if p["kind"] == k) for k in ("scaled", "prelim", "missing")})


def _drop_days(paths: dict, ym: str) -> None:
    path = _days_path(paths, ym)
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------- the store

def _load_month_arrays(paths: dict, ledger: dict, n: int, digest: str):
    """Month field arrays for every planned month, placeholders for months without an aggregate; plus the
    loaded set and the through day."""
    plan = ledger.get("plan", [])
    months = {}
    loaded = {}
    through = None
    last_loaded = None
    np = _np()
    for entry in plan:
        ym = entry["month"]
        y, m = int(ym[:4]), int(ym[5:])
        agg = _load_aggregate(paths, ym)
        if agg is not None:
            if agg["meta"].get("mask_sha256") != digest or agg["fields"].shape != (n, NF):
                raise ClimateError(f"the aggregate for {ym} was built for another mask")
            loaded[(y, m)] = agg["meta"]
            months[(y, m)] = agg["fields"]
            if agg["meta"].get("through"):
                through = max(through, agg["meta"]["through"]) if through else agg["meta"]["through"]
            last_loaded = (y, m)
    for entry in plan:
        ym = entry["month"]
        y, m = int(ym[:4]), int(ym[5:])
        if (y, m) in months:
            continue
        dim = days_in(y, m)
        avail = dim if (last_loaded is None or (y, m) < last_loaded) else 0
        placeholder = np.zeros((n, NF), dtype=np.int64)
        placeholder[:, 0] = avail
        placeholder[:, 1] = avail
        placeholder[:, 3] = RAIN_NONE
        placeholder[:, 5] = MAX_NONE
        placeholder[:, 7] = MIN_NONE
        months[(y, m)] = placeholder
    return months, loaded, through, plan


def build_store(store: Path, cache: Path, *, log=print, basemap_path=None) -> dict:
    """Write hail/c/ and the climate block of hail/index.json, and list the new files in hail/manifest.json. The
    store must already hold hail/ (the B1 and B2 store). Everything comes from the cache, so two builds from the same
    cache give byte-identical tile files.

    The state comes from the cache's ledger as well as from its aggregates. A failure that the last update recorded
    (ledger "failures") makes the part partial or unavailable even when older aggregates are cached (B5 D16). An
    unavailable part writes no tile files, so the page cannot show older figures as this update's."""
    np = _np()
    store = Path(store)
    paths = _cache_paths(Path(cache))
    ledger = _load_ledger(paths)
    failures = ledger.get("failures") or {}
    listing_failure = failures.get("listing")
    failed_months = failures.get("months") or {}
    plan = ledger.get("plan") or []
    if not plan and listing_failure is None:
        raise ClimateError("the cache holds no planned months; run backfill first")
    ci, cj, _box, digest = _mask_and_box(basemap_path)
    n = int(ci.size)
    months, loaded, through, plan = _load_month_arrays(paths, ledger, n, digest)
    planned = [e["month"] for e in plan]
    loaded_names = {f"{y:04d}-{m:02d}" for (y, m) in loaded}
    missing = [ym for ym in planned if ym not in loaded_names]
    problems = {ym: "no_file" for ym in missing}
    for ym in planned:
        if ym in failed_months:
            problems[ym] = failed_months[ym].get("reason") or "SourceError"
    prelim = sorted(e["month"] for e in plan if e["kind"] == "prelim")
    last_scaled = max((e["month"] for e in plan if e["kind"] == "scaled"), default=None)
    through_date = date.fromisoformat(through) if through else None
    if listing_failure is not None:
        state = "unavailable"
        problem = f"the NOAA file list did not load: {_plain_reason(listing_failure.get('reason') or '')}"
    elif not loaded:
        state = "unavailable"
        problem = "no month of the climate grid has loaded"
    elif problems:
        state = "partial"
        problem = f"{len(problems)} months did not load in this update"
    else:
        state = "loaded"
        problem = None
    c_dir = store / "hail" / "c"
    if c_dir.exists():
        shutil.rmtree(c_dir)
    c_dir.mkdir(parents=True)
    tile_names: list = []
    c_files: list = []
    total_bytes = 0
    records = 0
    land_count = None
    water_count = None
    if state != "unavailable":
        has_value = np.zeros(n, dtype=bool)
        for (y, m) in loaded:
            agg = _load_aggregate(paths, f"{y:04d}-{m:02d}")
            has_value |= agg["has_value"]
        land = has_value
        land_count = int(land.sum())
        water_count = n - land_count

        def period_rows(members):
            members = [k for k in members if k in months]
            if not members:
                return [[0, 0, 0, None, None, None, None, None, None, 0, 0, 0, 0] for _ in range(n)]
            return combine(np, [months[k] for k in members], [k[0] for k in members], [k[1] for k in members])

        seasons = {label: period_rows(period_members(label, "season")) for label in SEASONS}
        five_members = [k for label in FIVE_SEASONS for k in period_members(label, "season")]
        five = period_rows(five_members)
        calendar_rows = {y: period_rows(period_members(y, "calendar")) for y in CALENDAR_YEARS}
        water_rows = {y: period_rows(period_members(y, "water")) for y in WATER_YEARS}
        tiles: dict[tuple[int, int], dict] = {}
        for idx in range(n):
            i = int(ci[idx])
            j = int(cj[idx])
            tr, tc, key = climate_tile(i, j)
            tile = tiles.setdefault((tr, tc), {"state": [], "cells": {}})
            tile["state"].append(key)
            if land[idx]:
                tile["cells"][key] = {"i": i, "j": j, "f": five[idx],
                                      "s": [seasons[s][idx] for s in SEASONS],
                                      "c": [calendar_rows[y][idx] for y in CALENDAR_YEARS],
                                      "w": [water_rows[y][idx] for y in WATER_YEARS]}
        for (tr, tc) in sorted(tiles):
            tile = tiles[(tr, tc)]
            tile_state = sorted(set(tile["state"]))
            doc = {"f": FORMAT, "r": tr, "c": tc, "state": tile_state,
                   "cells": {str(k): tile["cells"][k] for k in sorted(tile["cells"])}}
            data = (json.dumps(doc, separators=(",", ":"), sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
            name = hail.tile_name(tr, tc)
            rel = f"hail/c/{name}.json"
            (store / rel).write_bytes(data)
            c_files.append((rel, data))
            total_bytes += len(data)
            records += len(tile["cells"])
        tile_names = [hail.tile_name(tr, tc) for (tr, tc) in sorted(tiles)]
    block = {
        "format": FORMAT,
        "state": state,
        "problem": problem,
        "source": {"name": "NOAA nClimGrid-Daily v1.0.0", "bucket": BUCKET,
                   "files": (f"{BUCKET}/access/grids/2025/ncdd-202506-grd-scaled.nc is the June 2025 scaled file (one "
                             f"scaled file per month); a prelim file, for example {BUCKET}/access/grids/2026/"
                             "ncdd-202610-grd-prelim.nc, is read only where no scaled file exists"),
                   "variables": ["prcp (mm)", "tmax (C)", "tmin (C)"],
                   "licence_attribute": f"license = {LICENSE_ATTRIBUTE}", "attribution": ATTRIBUTION},
        "grid": {"rows": ROWS, "cols": COLS, "per_degree": 24, "lat0": 24.5625, "lon0": -124.6875,
                 "units_per_degree": UNITS_PER_DEG, "lat_centre_units": [LAT_CENTRE0, 2],
                 "lon_centre_units": [LON_CENTRE0, 2], "lat_edge_units": LAT_EDGE, "lon_edge_units": LON_EDGE,
                 "rule": "lat (south edge, north edge], lon [west edge, east edge)"},
        "window": ["2021-07-01", through_date.isoformat() if through_date else None],
        "through": through_date.isoformat() if through_date else None,
        "months_planned": len(plan),
        "months_loaded": len(loaded),
        "months_missing": missing,
        "months_prelim": prelim,
        "months_failed": sorted(ym for ym in failed_months if ym in planned),
        "month_problems": {ym: problems[ym] for ym in sorted(problems)},
        "partial_line": _partial_line(problems) if state == "partial" else None,
        "last_scaled_month": last_scaled,
        "newest_planned_month": planned[-1] if planned else None,
        "mask_cells": n,
        "land_cells": land_count,
        "water_cells": water_count,
        "tiles": len(tile_names),
        "records": records,
        "files": len(c_files),
        "bytes": total_bytes,
        "fields": list(PERIOD_FIELDS),
        "periods": {"seasons": list(SEASONS), "five": list(FIVE_SEASONS), "calendar": list(CALENDAR_YEARS),
                    "water": list(WATER_YEARS)},
        "thresholds": THRESHOLDS,
        "mask_sha256": digest,
        "tile_names": tile_names,
    }
    _update_index_and_manifest(store, block, c_files)
    log(f"wrote {len(c_files)} climate tiles, {records} land records, {total_bytes} bytes; state {state}"
        + (f"; {problem}" if problem else ""))
    return block


def _update_index_and_manifest(store: Path, block: dict, c_files: list) -> None:
    hail_dir = store / "hail"
    index_path = hail_dir / "index.json"
    manifest_path = hail_dir / "manifest.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("format") != hail.FORMAT:
        raise ClimateError("the history index is not in the hail-store-v1 format")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != hail.MANIFEST_FORMAT:
        raise ClimateError("the history manifest is not in the expected format")
    index["climate"] = block
    index_bytes = hail._pretty(index)
    index_path.write_bytes(index_bytes)
    files = {k: v for k, v in manifest.get("files", {}).items()
             if not k.startswith("hail/c/") and k != "hail/index.json"}
    for rel, data in c_files:
        files[rel] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    files["hail/index.json"] = {"bytes": len(index_bytes), "sha256": hashlib.sha256(index_bytes).hexdigest()}
    manifest["files"] = dict(sorted(files.items()))
    manifest_path.write_bytes(hail._pretty(manifest))


# ---------------------------------------------------------------- reading a record

def _tenths_f_text(t: int) -> str:
    sign = "-" if t < 0 else ""
    a = abs(int(t))
    return f"{sign}{a // 10}.{a % 10}"


def _hin_text(h: int) -> str:
    return f"{int(h) // 100}.{int(h) % 100:02d}"


def _date_text(value) -> str | None:
    if value is None:
        return None
    text = str(int(value))
    return hail.fmt_date(date(int(text[:4]), int(text[4:6]), int(text[6:8])))


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _record_row(rec: list) -> dict:
    """The fields of one period record as a plain dict (values, units and the kind word).

    The page counts only the valid days, which are the days minus the missing days (D2). When a period has no valid
    day, its rain total, its counts, its highest and its lowest are None, so no zero stands for a missing day."""
    (days, missing, rain_hin, rmax_hin, rmax_date, tmax_f, tmax_date, tmin_f, tmin_date,
     hot, cold0, frz, below) = rec
    days = int(days)
    missing = int(missing)
    valid = days - missing
    has = valid > 0
    kind = WORDS_CLIMATE["kind"]

    def count(n):
        ok = has and n is not None                  # a count that is null reads as no value, never as None
        return {"value": int(n) if ok else None, "unit": "days", "kind": kind, "number": int(n) if ok else None}

    def temp(f, d):
        ok = has and f is not None
        return {"value": _tenths_f_text(f) if ok else None, "unit": "F", "date": _date_text(d) if ok else None,
                "kind": kind, "number": f if ok else None}

    rain_ok = has and rmax_hin is not None
    total_ok = has and rain_hin is not None
    return {
        "days": days, "missing": missing, "valid": valid,
        "rain": {"value": _hin_text(rain_hin) if total_ok else None, "unit": "in", "kind": kind,
                 "number": rain_hin if total_ok else None},
        "rain_max": {"value": _hin_text(rmax_hin) if rain_ok else None, "unit": "in",
                     "date": _date_text(rmax_date) if rain_ok else None, "kind": kind,
                     "number": rmax_hin if rain_ok else None},
        "tmax": temp(tmax_f, tmax_date),
        "tmin": temp(tmin_f, tmin_date),
        "hot90": count(hot), "cold0": count(cold0), "freeze_thaw": count(frz), "below32": count(below),
    }


WORDS_CLIMATE = {
    "kind": "Grid estimate",
    "title_temperature": "Temperature",
    "title_rain": "Rain",
    "cell_sentence": ("An estimate for a grid cell about 4.6 km north to south and about 3 km east to west, "
                      "not a reading at this address."),
    "temperature_lead": ("Grid estimate: from July 1, 2021 to June 30, 2026, highest {high} F on {high_date}; lowest "
                         "{low} F on {low_date}. An estimate for a grid cell about 4.6 km north to south and about 3 km "
                         "east to west, not a reading at this address."),
    "rain_lead": ("Grid estimate: {total} in of rain from July 1, 2021 to June 30, 2026, with the largest one-day total "
                  "{rain_max} in on {rain_max_date}. An estimate for a grid cell, not a gauge reading at this address."),
    "five_unavailable_temperature": ("Data unavailable for the five seasons: no day from July 1, 2021 to June 30, 2026 "
                                     "has a valid grid value, so no highest or lowest temperature is shown. "
                                     "This is not an all-clear."),
    "five_unavailable_rain": ("Data unavailable for the five seasons: no day from July 1, 2021 to June 30, 2026 has a "
                              "valid grid value, so no rain total is shown. This is not an all-clear."),
    "season_extremes": "Grid estimate: {season} season, highest {high} F on {high_date}; lowest {low} F on {low_date}.",
    "hot_days": "Grid estimate: {n} {days} with a high of 90 F or more in the {season} season.",
    "frost_days": "Grid estimate: {n} {days} with a low below 32 F in the {season} season.",
    "cold_days": "Grid estimate: {n} {days} at or below 0 F in the {season} season.",
    "freeze_thaw": ("Grid estimate: {n} freeze-thaw {days} in the {season} season (a high above 32 F and a low below "
                    "32 F)."),
    "season_rain": ("Grid estimate: {season} season, {total} in of rain; largest one day {rain_max} in on "
                    "{rain_max_date}."),
    "season_unavailable": ("Data unavailable for {label}: no day of this season has a valid grid value. "
                           "This is not an all-clear."),
    "calendar_extremes": ("Grid estimate: calendar {year} ({n_days} days with data): highest {high} F on {high_date}; "
                          "lowest {low} F on {low_date}."),
    "calendar_rain": ("Grid estimate: calendar {year} ({n_days} days with data), {total} in of rain; largest one day "
                      "{rain_max} in on {rain_max_date}."),
    "calendar_unavailable": ("Data unavailable for calendar {year}: no day has a valid grid value, so no highest or "
                             "lowest temperature or rain total is shown. This is not an all-clear."),
    "water_extremes": ("Grid estimate: water year {year} ({n_days} days with data): highest {high} F on {high_date}; "
                       "lowest {low} F on {low_date}."),
    "water_rain": ("Grid estimate: water year {year} ({n_days} days with data), {total} in of rain; largest one day "
                   "{rain_max} in on {rain_max_date}."),
    "water_unavailable": ("Data unavailable for water year {year}: no day has a valid grid value, so no highest or "
                          "lowest temperature or rain total is shown. This is not an all-clear."),
    "days_missing": ("Data unavailable: {n} {days} missing in the {period}; the totals and counts are for the days "
                     "present. This is not an all-clear."),
    # D33 (B5 part B1): the partial season is labelled preliminary in its head, values included; nothing here calls a
    # value a record (D13 holds the 111 F claim back). D41: a partial line ends with the all-clear sentence.
    "partial_season": ("Grid estimate, preliminary: {season} so far, {n_days} days to {through}: highest {high} F on "
                       "{high_date}; lowest {low} F on {low_date}; {hot} {hot_days} at 90 F or more; {frost} "
                       "{frost_days} with a low below 32 F; {total} in of rain, largest one day {rain_max} in on "
                       "{rain_max_date}. The newest days are preliminary and provisional until NOAA publishes the "
                       "scaled month. This is not an all-clear."),
    "partial_none": "No day of the {season} season is in the data yet. This is not an all-clear.",
    "partial_partial": ("Data unavailable for {label}: part of this season has no valid grid value, so its highest, "
                        "lowest and rain totals are not shown. This is not an all-clear."),
    "partial_months": "Data unavailable for some months: {months}. This is not an all-clear.",
    "reason_no_file_one": "no NOAA file was found for it when this update ran",
    "reason_no_file_many": "no NOAA file was found for them when this update ran",
    "reasons": {
        "ReadTimeout": "the request timed out",
        "ConnectTimeout": "the connection timed out",
        "Timeout": "the request timed out",
        "ConnectionError": "the connection failed",
        "ChunkedEncodingError": "the download stopped before the end",
        "SSLError": "the secure connection failed",
        "ShortDownload": "the download was shorter than the listing says",
        "ShortRead": "the source sent fewer bytes than asked",
        "ParseError": "the NOAA file list could not be read",
        "BadListing": "the NOAA file list could not be read",
        "NotAListing": "the NOAA file list could not be read",
        "EmptyListing": "the NOAA file list has no month files",
        "CheckFailed": "the file did not pass its checks",
        "OSError": "the file could not be read or written",
        "KeyError": "the file is missing a variable it needs",
    },
    "stale": "The newest day in this grid is {through}; newer days have not been added yet. This is not an all-clear.",
    "no_land": "No land value for this grid cell, so no grid estimate is shown here. This is not an all-clear.",
    "outside": "Outside Montana. The history covers Montana only.",
    "unavailable": "{part} could not be loaded in this update; that is not the same as no {part_lower}. "
                   "This is not an all-clear.",
    "not_in_store": ("No grid estimate for this spot: the grid cell that holds it is centred outside Montana, "
                     "or this update has no climate figures for the area. This is not an all-clear."),
    "how_made": [
        "Grid estimates come from NOAA nClimGrid-Daily, a daily grid of rain, highest and lowest temperature at about 4.6 km. "
        "Each value is an estimate for the grid cell, not a reading at the address.",
        "A day is a grid day: the 24 hours ending in the early morning of its date.",
        "Rain is rounded to the hundredth of a millimetre a day and summed, then shown in inches.",
        "Temperatures are rounded to the hundredth of a degree C and then to the tenth, which is the unit of the GHCN "
        "station files, and shown in degrees F.",
        "A day with a high of 90 F or more has a high of at least 32.15 C, rounded to the hundredth of a degree (32.15 C "
        "shows as 32.2 C and 90 F; 32.14 C does not count); a freeze-thaw day has a high above 32 F and a low below 32 F.",
        "A day with a low below 32 F has a low below 0 C; a day at or below 0 F has a low of -17.8 C or colder.",
        "A day with a missing value is counted as a missing day and is not counted as zero. Days after the newest grid day are not counted.",
        "Scaled months are the monthly values of the NOAA record; the newest days come from preliminary files, which NOAA says are provisional.",
        ATTRIBUTION,
    ],
}


def _plain_reason(code: str) -> str:
    """The words for a recorded reason: an exception's name, "HTTP nnn" or a fixed code."""
    reasons = WORDS_CLIMATE["reasons"]
    if code in reasons:
        return reasons[code]
    if code.startswith("HTTP "):
        return f"the source returned {code}"
    return "the source did not answer as expected"


def _problems_of(block: dict) -> dict:
    """The month reasons of an index block: the recorded ones, or for an older block the months it lists as missing."""
    if "month_problems" in block:
        return dict(block["month_problems"])
    return {ym: "no_file" for ym in block.get("months_missing") or []}


def _partial_line(problems: dict) -> str | None:
    """The one coverage line for the months that did not load in this update. The months are the same for every
    place, so build_store writes the line once and every place shows it. Months with the same reason are grouped, so
    each reason is said once."""
    if not problems:
        return None
    w = WORDS_CLIMATE
    groups: dict = {}
    for ym in sorted(problems):
        groups.setdefault(problems[ym], []).append(ym)
    pieces = []
    for code, months in groups.items():
        if code == "no_file":
            reason = w["reason_no_file_many" if len(months) > 1 else "reason_no_file_one"]
        else:
            reason = _plain_reason(code)
        pieces.append(f"{', '.join(months)} did not load ({reason})")
    return w["partial_months"].format(months="; ".join(pieces))


def _missing_line(row: dict, period: str) -> str:
    """The coverage line for a period's missing days (D2): the count, the period and the rule for the totals."""
    n = row["missing"]
    return WORDS_CLIMATE["days_missing"].format(n=n, days=_plural(n, "day", "days"), period=period)


def _season_lines(label: str, rec: list) -> dict:
    row = _record_row(rec)
    w = WORDS_CLIMATE
    lines_t = []
    lines_r = []
    if row["valid"] <= 0:
        text = w["season_unavailable"].format(label=label)
        lines_t.append(text)
        lines_r.append(text)
    else:
        lines_t.append(w["season_extremes"].format(season=label, high=row["tmax"]["value"],
                                                  high_date=row["tmax"]["date"], low=row["tmin"]["value"],
                                                  low_date=row["tmin"]["date"]))
        lines_t.append(w["hot_days"].format(n=row["hot90"]["value"], days=_plural(row["hot90"]["value"], "day", "days"),
                                            season=label))
        lines_t.append(w["frost_days"].format(n=row["below32"]["value"],
                                              days=_plural(row["below32"]["value"], "day", "days"), season=label))
        lines_t.append(w["cold_days"].format(n=row["cold0"]["value"], days=_plural(row["cold0"]["value"], "day", "days"),
                                             season=label))
        lines_t.append(w["freeze_thaw"].format(n=row["freeze_thaw"]["value"],
                                               days=_plural(row["freeze_thaw"]["value"], "day", "days"), season=label))
        lines_r.append(w["season_rain"].format(season=label, total=row["rain"]["value"],
                                               rain_max=row["rain_max"]["value"],
                                               rain_max_date=row["rain_max"]["date"]))
    if row["missing"]:
        note = _missing_line(row, label + " season")
        lines_t.append(note)
        lines_r.append(note)
    return {"label": label, "row": row, "temperature": lines_t, "rain": lines_r}


def _year_lines(row: dict, kind: str, year: int) -> tuple:
    """The temperature and rain lines of a calendar year or a water year (kind "calendar" or "water"). A year with no
    day in this build gives no lines. A year whose days all lack a value says so. A year with valid days shows them,
    and its missing days are said in the same words as a season's (D2)."""
    w = WORDS_CLIMATE
    temp: list = []
    rain: list = []
    if not row["days"]:
        return temp, rain
    if row["valid"] <= 0:
        text = w[f"{kind}_unavailable"].format(year=year)
        temp.append(text)
        rain.append(text)
    else:
        temp.append(w[f"{kind}_extremes"].format(year=year, n_days=row["valid"], high=row["tmax"]["value"],
                                                 high_date=row["tmax"]["date"], low=row["tmin"]["value"],
                                                 low_date=row["tmin"]["date"]))
        rain.append(w[f"{kind}_rain"].format(year=year, n_days=row["valid"], total=row["rain"]["value"],
                                             rain_max=row["rain_max"]["value"],
                                             rain_max_date=row["rain_max"]["date"]))
    if row["missing"]:
        note = _missing_line(row, ("calendar " if kind == "calendar" else "water year ") + str(year))
        temp.append(note)
        rain.append(note)
    return temp, rain


def _table_rows(row: dict) -> list:
    """The per-season rows for the five-season table: each with its value, unit, kind word and (where it has one)
    its date. A period with no valid day has no rows (no zero stands for a missing day). A count of missing days is
    not a row: the coverage line says it (D2)."""
    if row["valid"] <= 0:
        return []
    kind = WORDS_CLIMATE["kind"]
    return [
        {"key": "tmax", "label": "Highest temperature", "value": row["tmax"]["value"], "unit": "F",
         "date": row["tmax"]["date"], "kind": kind},
        {"key": "tmin", "label": "Lowest temperature", "value": row["tmin"]["value"], "unit": "F",
         "date": row["tmin"]["date"], "kind": kind},
        {"key": "hot90", "label": "Days with a high of 90 F or more", "value": row["hot90"]["value"],
         "unit": "days", "date": None, "kind": kind},
        {"key": "below32", "label": "Days with a low below 32 F", "value": row["below32"]["value"],
         "unit": "days", "date": None, "kind": kind},
        {"key": "freeze_thaw", "label": "Freeze-thaw days", "value": row["freeze_thaw"]["value"],
         "unit": "days", "date": None, "kind": kind},
        {"key": "rain", "label": "Precipitation", "value": row["rain"]["value"], "unit": "in", "date": None,
         "kind": kind},
        {"key": "rain_max", "label": "Largest one-day precipitation", "value": row["rain_max"]["value"],
         "unit": "in", "date": row["rain_max"]["date"], "kind": kind},
    ]


def _five_from(rec_five: list) -> dict:
    row = _record_row(rec_five)
    return {"label": "Five seasons", "days": row["days"], "missing": row["missing"], "valid": row["valid"],
            "row": row, "table": _table_rows(row)}


def _unavailable(reason: str) -> dict:
    w = WORDS_CLIMATE
    return {"state": "unavailable", "problem": reason, "cell": None,
            "temperature": {"title": w["title_temperature"], "kind": w["kind"],
                            "lead": w["unavailable"].format(part="Temperature", part_lower="temperature"),
                            "lines": []},
            "rain": {"title": w["title_rain"], "kind": w["kind"],
                     "lead": w["unavailable"].format(part="Rain", part_lower="rain"), "lines": []},
            "table": {"seasons": [], "five": None}, "calendar": [], "water": [], "stale": None,
            "how_made": list(w["how_made"])}


def _leads(five_row: dict) -> tuple[str, str]:
    """The temperature and rain leads of the five seasons (F06). A lead is written only from values that exist: a value
    that is None (no valid day carries it) is never printed, and the unavailable sentence says so instead."""
    w = WORDS_CLIMATE
    t_high, t_low = five_row["tmax"], five_row["tmin"]
    r_total, r_max = five_row["rain"], five_row["rain_max"]
    temp_ok = all(part["value"] is not None and part["date"] is not None for part in (t_high, t_low))
    rain_ok = r_total["value"] is not None and r_max["value"] is not None and r_max["date"] is not None
    temp = (w["temperature_lead"].format(high=t_high["value"], high_date=t_high["date"], low=t_low["value"],
                                         low_date=t_low["date"]) if temp_ok else w["five_unavailable_temperature"])
    rain = (w["rain_lead"].format(total=r_total["value"], rain_max=r_max["value"], rain_max_date=r_max["date"])
            if rain_ok else w["five_unavailable_rain"])
    return temp, rain


def _partial_text(row: dict, label: str, through) -> str:
    """The one line below the table for the partial season (D20): "so far, n days to the newest day", with its own
    counts. When the store holds no day of the season, the no-day sentence says so; when no day has a value, the
    unavailable sentence does. Missing days are said in the words a season uses (D2). It is not a season list entry."""
    w = WORDS_CLIMATE
    if row["days"] == 0:
        return w["partial_none"].format(season=label)
    values = (row["tmax"]["value"], row["tmin"]["value"], row["rain"]["value"], row["rain_max"]["value"])
    if row["valid"] <= 0:
        text = w["season_unavailable"].format(label=label)
    elif any(v is None for v in values):
        text = w["partial_partial"].format(label=label)
    else:
        to = hail.fmt_date(date.fromisoformat(through)) if through else "the newest day"
        text = w["partial_season"].format(
            season=label, n_days=row["valid"], through=to,
            high=row["tmax"]["value"], high_date=row["tmax"]["date"], low=row["tmin"]["value"],
            low_date=row["tmin"]["date"], hot=row["hot90"]["value"],
            hot_days=_plural(row["hot90"]["value"], "day", "days"), frost=row["below32"]["value"],
            frost_days=_plural(row["below32"]["value"], "day", "days"), total=row["rain"]["value"],
            rain_max=row["rain_max"]["value"], rain_max_date=row["rain_max"]["date"])
    if row["missing"]:
        text += " " + _missing_line(row, label + " season")
    return text


def describe_climate(index: dict | None, tile_doc: dict | None, row: int, col: int, now) -> dict:
    """The temperature and rain sections for the B1 cell (row, col), from the index and the climate tile that holds
    the grid cell which holds the cell's centre (climate_tile_for_cell). Returns plain dicts and the sentences;
    nothing here is a number a reader must decode: every value carries its unit and kind word."""
    block = (index or {}).get("climate") if isinstance(index, dict) else None
    if not block or block.get("format") != FORMAT:
        return _unavailable("the climate grid is not in this build")
    if block.get("state") == "unavailable":
        return _unavailable(block.get("problem") or "the climate grid could not be read")
    cell = climate_cell_for(*hail.cell_centre(row, col))
    w = WORDS_CLIMATE
    if cell is None:
        return {"state": "outside", "problem": None, "cell": None,
                "temperature": {"title": w["title_temperature"], "kind": w["kind"], "lead": w["outside"], "lines": []},
                "rain": {"title": w["title_rain"], "kind": w["kind"], "lead": w["outside"], "lines": []},
                "table": {"seasons": [], "five": None}, "calendar": [], "water": [], "stale": None,
                "how_made": list(w["how_made"])}
    i, j = cell
    tr, tc, key = climate_tile(i, j)
    if tile_doc is None:
        # No tile for this spot. A tile the store does not list holds a grid cell centred outside Montana (not a
        # failure, and the spot is inside Montana): not in the store. A listed tile that could not be read is a
        # failure, and the page says so.
        if hail.tile_name(tr, tc) in block.get("tile_names", []):
            return _unavailable(block.get("problem") or "the climate tile could not be read")
        return {"state": "outside", "problem": None, "cell": {"i": i, "j": j, "tile": hail.tile_name(tr, tc),
                                                               "key": key},
                "temperature": {"title": w["title_temperature"], "kind": w["kind"], "lead": w["not_in_store"],
                                "lines": []},
                "rain": {"title": w["title_rain"], "kind": w["kind"], "lead": w["not_in_store"], "lines": []},
                "table": {"seasons": [], "five": None}, "calendar": [], "water": [], "stale": None,
                "how_made": list(w["how_made"])}
    if (tile_doc.get("r"), tile_doc.get("c")) != (tr, tc):
        raise ClimateError("the climate tile does not hold the grid cell for this spot")
    lat, lon = climate_centre(i, j)
    cell_info = {"i": i, "j": j, "lat": lat, "lon": lon, "tile": hail.tile_name(tr, tc), "key": key}
    state_keys = tile_doc.get("state", [])
    if key not in state_keys:
        return {"state": "outside", "problem": None, "cell": cell_info,
                "temperature": {"title": w["title_temperature"], "kind": w["kind"], "lead": w["not_in_store"],
                                "lines": []},
                "rain": {"title": w["title_rain"], "kind": w["kind"], "lead": w["not_in_store"], "lines": []},
                "table": {"seasons": [], "five": None}, "calendar": [], "water": [], "stale": None,
                "how_made": list(w["how_made"])}
    rec = tile_doc.get("cells", {}).get(str(key))
    if rec is None:
        return {"state": "no_land", "problem": None, "cell": cell_info,
                "temperature": {"title": w["title_temperature"], "kind": w["kind"], "lead": w["no_land"], "lines": []},
                "rain": {"title": w["title_rain"], "kind": w["kind"], "lead": w["no_land"], "lines": []},
                "table": {"seasons": [], "five": None}, "calendar": [], "water": [], "stale": None,
                "how_made": list(w["how_made"])}
    seasons = [_season_lines(label, rec["s"][k]) for k, label in enumerate(SEASONS)]
    five = _five_from(rec["f"])
    calendar_out = [{"year": y, "row": _record_row(rec["c"][k])} for k, y in enumerate(CALENDAR_YEARS)]
    water_out = [{"year": y, "row": _record_row(rec["w"][k])} for k, y in enumerate(WATER_YEARS)]
    through = block.get("through")
    stale = None
    if through:
        now_date = now.date() if isinstance(now, datetime) else now
        if date.fromisoformat(through) < now_date - timedelta(days=DAYS_STALE):
            stale = w["stale"].format(through=hail.fmt_date(date.fromisoformat(through)))
    state = "loaded" if block.get("state") == "loaded" else "partial"
    partial_line = (block["partial_line"] if "partial_line" in block
                    else _partial_line(_problems_of(block)))
    five_row = five["row"]
    temp_lead, rain_lead = _leads(five_row)
    temp_lines = []
    rain_lines = []
    for s in seasons[:5]:           # D20: the partial season is not in the season lists; its line is below the table
        temp_lines.extend(s["temperature"])
        rain_lines.extend(s["rain"])
    for entry in calendar_out:
        t, r = _year_lines(entry["row"], "calendar", entry["year"])
        temp_lines.extend(t)
        rain_lines.extend(r)
    for entry in water_out:
        t, r = _year_lines(entry["row"], "water", entry["year"])
        temp_lines.extend(t)
        rain_lines.extend(r)
    partial_row = seasons[-1]["row"]
    partial_text = _partial_text(partial_row, SEASONS[-1], through)
    return {
        "state": state,
        "problem": block.get("problem") if state == "partial" else None,
        "cell": cell_info,
        "temperature": {"title": w["title_temperature"], "kind": w["kind"], "lead": temp_lead,
                        "partial": partial_line, "lines": temp_lines},
        "rain": {"title": w["title_rain"], "kind": w["kind"], "lead": rain_lead, "partial": partial_line,
                 "lines": rain_lines},
        "table": {"seasons": [{"label": s["label"], "days": s["row"]["days"], "missing": s["row"]["missing"],
                               "valid": s["row"]["valid"], "rows": _table_rows(s["row"])} for s in seasons[:5]],
                  "five": {"label": "Five seasons", "days": five["days"], "missing": five["missing"],
                           "valid": five["valid"], "rows": five["table"]},
                  "partial": {"label": SEASONS[-1], "days": partial_row["days"], "missing": partial_row["missing"],
                              "valid": partial_row["valid"], "rows": _table_rows(partial_row), "text": partial_text}},
        "calendar": calendar_out,
        "water": water_out,
        "stale": stale,
        "how_made": list(w["how_made"]),
    }


def map_data_climate(index: dict | None) -> dict:
    """The climate block for the page: state, the tile URL pattern, the grid rule, the periods and fields, the
    thresholds (stated once) and the sentences the browser fills. No number here is a secret; the browser does the
    grid arithmetic and the fetch, and every sentence is Python's."""
    block = (index or {}).get("climate") if isinstance(index, dict) else None
    if not block or block.get("format") != FORMAT:
        return {"state": "unavailable", "problem": "the climate grid is not in this build",
                "templates": dict(WORDS_CLIMATE), "tile": "hail/c/{tile}.json"}
    partial_line = (block["partial_line"] if "partial_line" in block
                    else _partial_line(_problems_of(block)))
    return {"state": block.get("state"), "problem": block.get("problem"),
            "through": block.get("through"), "months_missing": block.get("months_missing", []),
            "months_prelim": block.get("months_prelim", []), "months_failed": block.get("months_failed", []),
            "month_problems": _problems_of(block), "partial_line": partial_line,
            "last_scaled_month": block.get("last_scaled_month"),
            "tile": "hail/c/{tile}.json", "tile_names": block.get("tile_names", []),
            "grid": block.get("grid"), "fields": block.get("fields"), "periods": block.get("periods"),
            "thresholds": THRESHOLDS, "templates": dict(WORDS_CLIMATE), "source": block.get("source")}


# ---------------------------------------------------------------- verification

def _read_tile(store: Path, name: str) -> dict:
    path = store / "hail" / "c" / f"{name}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClimateError(f"the climate tile {name} could not be read: {exc}") from None
    return doc


def _walk_numbers(value, where: str, problems: list) -> None:
    if isinstance(value, bool):
        problems.append(f"{where}: a boolean")
    elif isinstance(value, float):
        problems.append(f"{where}: a float {value}")
    elif isinstance(value, list):
        for k, item in enumerate(value):
            _walk_numbers(item, f"{where}[{k}]", problems)
    elif isinstance(value, dict):
        for k, item in value.items():
            _walk_numbers(item, f"{where}.{k}", problems)


def verify_store(store, cache=None, *, independent: bool = False, session=None, log=print,
                 basemap_path=None) -> dict:
    """Check the climate files of a built store: the B1 manifest (hashes, every file listed), each tile's format,
    whole numbers only, state and record keys, the tile of every record, the record counts, the mask count (25,973),
    the land and water counts, and the gate cells (Billings and Benchland). With cache given, the Billings airport's
    GHCN freeze-thaw count for 2025 is set beside the grid's count for the same cell. With independent=True the
    source months needed for the Billings checks are downloaded whole and read again with h5py, separately from the
    build's code path; the checks are zero difference. Raises ClimateError when the store is wrong. An unavailable
    part is checked for what it must hold (no tile files) and nothing else."""
    store = Path(store)
    manifest = hail.check_manifest(store)
    index = hail.load_index(store)
    block = index.get("climate")
    if not block or block.get("format") != FORMAT:
        raise ClimateError("the history index has no climate block")
    listed = {k for k in manifest["files"] if k.startswith("hail/c/")}
    on_disk = {f"hail/c/{p.name}" for p in (store / "hail" / "c").glob("*.json")} if (store / "hail" / "c").exists() else set()
    if listed != on_disk or sorted(block.get("tile_names", [])) != sorted(p.split("/")[-1][:-5] for p in on_disk):
        raise ClimateError("the climate tiles, the manifest and the index do not agree")
    ci, cj = montana_cells(basemap_path)
    mask_set = {(int(a), int(b)) for a, b in zip(ci, cj)}
    if len(mask_set) != block["mask_cells"]:
        raise ClimateError("the mask cell count does not match the index")
    if basemap_path is None and block["mask_cells"] != EXPECTED_MASK_CELLS:
        raise ClimateError("the mask cell count is not the expected Montana count")
    if block.get("state") == "unavailable":
        if listed or block.get("tile_names") or block.get("records"):
            raise ClimateError("an unavailable climate part holds tile files")
        return {"ok": True, "format": FORMAT, "state": "unavailable", "problem": block.get("problem"),
                "mask_cells": block["mask_cells"], "tiles": 0, "records": 0,
                "months_planned": block["months_planned"], "months_loaded": block["months_loaded"],
                "months_missing": block["months_missing"], "months_failed": block.get("months_failed", []),
                "through": block.get("through"), "gates": {}, "airport_comparison_2025": None}
    records = 0
    state_cells = 0
    problems: list = []
    tile_bytes = 0
    seen_cells = set()
    for name in sorted(block["tile_names"]):
        path = store / "hail" / "c" / f"{name}.json"
        raw = path.read_bytes()
        tile_bytes += len(raw)
        doc = json.loads(raw.decode("utf-8"))
        if doc.get("f") != FORMAT or hail.tile_name(doc["r"], doc["c"]) != name:
            raise ClimateError(f"the climate tile {name} is not in the expected format")
        _walk_numbers(doc, name, problems)
        state = doc["state"]
        if state != sorted(set(state)) or not all(type(k) is int and 0 <= k < 100 for k in state):
            raise ClimateError(f"the climate tile {name} has a state list that is not sorted in-tile keys")
        state_cells += len(state)
        for key_text, rec in doc["cells"].items():
            key = int(key_text)
            if key not in state:
                raise ClimateError(f"the climate tile {name} has a record outside its state list")
            i, j = rec["i"], rec["j"]
            if (i, j) not in mask_set:
                raise ClimateError(f"the climate tile {name} holds a grid cell outside the Montana mask")
            tr, tc, k2 = climate_tile(i, j)
            if (tr, tc, k2) != (doc["r"], doc["c"], key):
                raise ClimateError(f"the climate record {i},{j} is in the wrong tile or key")
            seen_cells.add((i, j))
            if len(rec["s"]) != len(SEASONS) or len(rec["c"]) != len(CALENDAR_YEARS) or len(rec["w"]) != len(WATER_YEARS):
                raise ClimateError(f"the climate record {i},{j} has the wrong number of periods")
            for field in [rec["f"]] + rec["s"] + rec["c"] + rec["w"]:
                if len(field) != NF:
                    raise ClimateError(f"the climate record {i},{j} has a period with {len(field)} fields")
                for q, value in enumerate(field):
                    if value is not None and type(value) is not int:
                        raise ClimateError(f"the climate record {i},{j} holds a value that is not a whole number")
                    if value is None and q not in (3, 4, 5, 6, 7, 8):
                        raise ClimateError(f"the climate record {i},{j} has a missing count")
            records += 1
    if problems:
        raise ClimateError("the climate tiles hold a value that is not a whole number: " + problems[0])
    if records != block["records"] or block["land_cells"] != records or state_cells != block["mask_cells"]:
        raise ClimateError("the climate record and state counts do not match the index")
    gates = _gate_cells(store, block, mask_set)
    airport = None
    if cache is not None:
        try:
            dly = fetch_ghcn(Path(cache))
        except SourceError as exc:
            # job-F7: a file that does not come is a comparison that could not be made, recorded with its reason
            airport = {"unavailable": True, "station": GHCN_BILLINGS, "year": 2025, "reason": exc.reason,
                       "sentence": (f"The Billings airport comparison could not be checked in this run: "
                                    f"{_plain_reason(exc.reason)}.")}
        else:
            airport = ghcn_freeze_thaw(dly, 2025)
            tr, tc, key = climate_tile(*climate_cell_for(*stations.GATE_POINTS["billings"]))
            grid_rec = _read_tile(store, hail.tile_name(tr, tc))["cells"].get(str(key))
            airport["grid_billings_calendar_2025_freeze_thaw_days"] = (
                None if grid_rec is None else grid_rec["c"][CALENDAR_YEARS.index(2025)][11])
    report = {
        "ok": True,
        "format": FORMAT,
        "state": block["state"],
        "airport_comparison_2025": airport,
        "mask_cells": block["mask_cells"],
        "land_cells": block["land_cells"],
        "water_cells": block["water_cells"],
        "records": records,
        "state_cells": state_cells,
        "tiles": len(block["tile_names"]),
        "tile_bytes": tile_bytes,
        "months_planned": block["months_planned"],
        "months_loaded": block["months_loaded"],
        "months_missing": block["months_missing"],
        "months_prelim": block["months_prelim"],
        "months_failed": block.get("months_failed", []),
        "through": block["through"],
        "gates": gates,
    }
    if independent:
        try:
            report["independent"] = independent_check(store, cache, session=session, log=log)
        except SourceError as exc:
            # job-F7: the source did not answer, so the independent read was not made; that is said, not raised
            report["independent"] = {"ok": None, "unavailable": True, "reason": exc.reason,
                                     "sentence": f"The independent read was not made in this run: {_plain_reason(exc.reason)}."}
        else:
            if not report["independent"]["ok"]:
                raise ClimateError("the independent read does not match the store (see the report)")
    return report


def _gate_cells(store: Path, block: dict, mask_set) -> dict:
    """The Billings and Benchland cells' records, for the report (no comparison here). The points are the gate points
    of website.stations (GATE_POINTS), the one definition of them."""
    out = {}
    points = {"billings": stations.GATE_POINTS["billings"], "benchland": stations.GATE_POINTS["benchland"]}
    for name, (lat, lon) in points.items():
        cell = climate_cell_for(lat, lon)
        tr, tc, key = climate_tile(*cell)
        tile = hail.tile_name(tr, tc)
        rec = None
        if (store / "hail" / "c" / f"{tile}.json").exists():
            rec = _read_tile(store, tile)["cells"].get(str(key))
        out[name] = {"cell": list(cell), "tile": tile, "key": key,
                     "record": None if rec is None else {"f": rec["f"], "s": rec["s"], "c": rec["c"],
                                                         "w": rec["w"]}}
    return out


GHCN_BILLINGS = "USW00024033"


def ghcn_freeze_thaw(dly_path: Path, year: int) -> dict:
    """Days in a calendar year with TMAX above 0 C and TMIN below 0 C at a GHCN-Daily station, from the .dly file
    (tenths of a degree C; a non-blank quality flag excludes a value; -9999 is missing)."""
    values: dict[str, dict] = {"TMAX": {}, "TMIN": {}}
    with open(dly_path, "rb") as fh:
        for raw in fh:
            line = raw.decode("ascii", "replace").rstrip("\r\n")
            if len(line) < 21:
                continue
            y = int(line[11:15])
            mo = int(line[15:17])
            element = line[17:21]
            if element not in values or y != year:
                continue
            for d in range(1, 32):
                base = 21 + (d - 1) * 8
                v = int(line[base:base + 5])
                flag = line[base + 6]
                if v == -9999 or flag != " ":
                    continue
                try:
                    values[element][date(y, mo, d)] = v
                except ValueError:
                    continue
    days = set(values["TMAX"]) & set(values["TMIN"])
    n = sum(1 for d in days if values["TMAX"][d] > 0 and values["TMIN"][d] < 0)
    return {"station": GHCN_BILLINGS, "year": year, "freeze_thaw_days": n, "days_with_both": len(days),
            "rule": ("a day counts when TMAX is above 0 C and TMIN is below 0 C on the same day, in tenths of a degree C "
                     "from the file; a flagged or missing value is not used")}


def fetch_ghcn(cache: Path) -> Path:
    """The Billings airport's .dly file from NCEI (stations.DLY_URL), kept in the cache. A download that keeps failing
    raises SourceError (after RETRY_ATTEMPTS tries), and a file too short to be a station record is refused."""
    dest = cache / "ghcn" / "dly" / f"{GHCN_BILLINGS}.dly"
    if not dest.exists():
        import requests
        dest.parent.mkdir(parents=True, exist_ok=True)
        what = f"the GHCN file {GHCN_BILLINGS}.dly"
        url = stations.DLY_URL.format(id=GHCN_BILLINGS)
        r = _send_with_retries(what, lambda: requests.get(url, timeout=300, headers={"User-Agent": USER_AGENT}))
        if r.status_code != 200:
            raise SourceError(what, f"HTTP {r.status_code}")
        if len(r.content) < 1000:
            raise SourceError(what, "ShortDownload", f"{len(r.content)} bytes")
        part = dest.with_name(dest.name + ".part")
        try:
            part.write_bytes(r.content)
            os.replace(part, dest)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
    return dest


def independent_check(store, cache, *, session=None, log=print) -> dict:
    """Re-read the Billings grid cell from the source months, separately from the build's code path.

    For each of the 18 months July 2024 to December 2025 the whole file is downloaded once, read with h5py, and
    deleted. The independent path converts each day with pure Python and exact decimal arithmetic. The production
    path (read_box, select_cells, daily_arrays) reads the same file for the mask box. Zero difference is required
    between the two on every day, and between the independent sums and the store's records for calendar 2025 rain
    and the 2024-25 season (freeze-thaw, hot, below 32 F, missing days)."""
    import h5py
    store = Path(store)
    paths = _cache_paths(Path(cache))
    _ensure(paths)
    np = _np()
    ci, cj = montana_cells()
    box = mask_box(ci, cj)
    billings = climate_cell_for(*stations.GATE_POINTS["billings"])
    idx = int(np.flatnonzero((ci == billings[0]) & (cj == billings[1]))[0])
    months = months_between((2024, 7), (2025, 12))
    indep = {}
    raw_days = {}
    mismatches = {"daily_valid": 0, "daily_cmm": 0, "daily_tenths_c": 0}
    bytes_read = 0
    for (y, m) in months:
        ym = f"{y:04d}-{m:02d}"
        entry = _plan_entry(paths, ym)
        dest = paths["months"] / f"{ym}-verify.nc"
        info = fetch_whole(_url(ym, entry["kind"]), dest, entry["size"], session=session)
        bytes_read += info["bytes"]
        try:
            with h5py.File(dest, "r") as f:
                check_file(f, y, m)
                cell_raw = [[float(x) for x in f[v][:, billings[0], billings[1]]] for v in ("prcp", "tmax", "tmin")]
                production_raw = read_box(f, box)
        finally:
            dest.unlink(missing_ok=True)
        cells = select_cells(production_raw, box, ci, cj)
        p_valid, p_cmm, p_tx, p_tn, _fill = daily_arrays(np, cells["prcp"][:, [idx]], cells["tmax"][:, [idx]],
                                                         cells["tmin"][:, [idx]])
        for d in range(days_in(y, m)):
            p, x, n = cell_raw[0][d], cell_raw[1][d], cell_raw[2][d]
            raw_days[date(y, m, d + 1)] = (p, x, n)
            ok = (PRCP_RANGE[0] <= p <= PRCP_RANGE[1] and TEMP_RANGE[0] <= x <= TEMP_RANGE[1]
                  and TEMP_RANGE[0] <= n <= TEMP_RANGE[1])
            cmm = _decimal_centi(p) if ok else 0
            tx = (_decimal_centi(x) + 5) // 10 if ok else 0
            tn = (_decimal_centi(n) + 5) // 10 if ok else 0
            day = date(y, m, d + 1)
            indep[day] = (ok, cmm, tx, tn)
            if bool(p_valid[d, 0]) != ok:
                mismatches["daily_valid"] += 1
            if int(p_cmm[d, 0]) != cmm:
                mismatches["daily_cmm"] += 1
            if int(p_tx[d, 0]) != tx or int(p_tn[d, 0]) != tn:
                mismatches["daily_tenths_c"] += 1
        log(f"  verify {ym}: {info['bytes']} bytes in {info['seconds']} s")
    cal = [(ok, cmm) for day, (ok, cmm, _tx, _tn) in indep.items() if day.year == 2025]
    rain_cmm = sum(cmm for ok, cmm in cal if ok)
    season = [(ok, tx, tn) for day, (ok, _c, tx, tn) in indep.items() if date(2024, 7, 1) <= day <= date(2025, 6, 30)]
    freeze = sum(1 for ok, tx, tn in season if ok and tx > 0 and tn < 0)
    hot = sum(1 for ok, tx, tn in season if ok and tx >= HOT_TENTHS)
    below = sum(1 for ok, tx, tn in season if ok and tn < 0)
    missing = sum(1 for ok, tx, tn in season if not ok)
    jun15 = indep[date(2025, 6, 15)]
    tile_doc = _read_tile(store, climate_tile_name(*billings))
    rec = tile_doc["cells"][str(climate_tile(*billings)[2])]
    store_cal_rain = rec["c"][CALENDAR_YEARS.index(2025)][2]
    s2425 = rec["s"][SEASONS.index("2024-25")]
    checks = {
        "calendar_2025_rain_hin": (store_cal_rain, (10 * rain_cmm + 127) // 254),
        "season_2024_25_freeze_thaw": (s2425[11], freeze),
        "season_2024_25_hot90": (s2425[9], hot),
        "season_2024_25_below32": (s2425[12], below),
        "season_2024_25_missing": (s2425[1], missing),
    }
    diffs = {name: a - b for name, (a, b) in checks.items()}
    result = {
        "cell": list(billings),
        "months_read": [f"{y:04d}-{m:02d}" for (y, m) in months],
        "bytes_read": bytes_read,
        "daily_days_compared": len(indep),
        "mismatches": mismatches,
        "calendar_2025_rain_cmm_independent": rain_cmm,
        "calendar_2025_rain_mm_independent": f"{rain_cmm // 100}.{rain_cmm % 100:02d}",
        "calendar_2025_rain_hin_store_and_independent": [checks["calendar_2025_rain_hin"][0],
                                                         checks["calendar_2025_rain_hin"][1]],
        "season_2024_25_independent": {"freeze_thaw": freeze, "hot90": hot, "below32": below, "missing": missing},
        "season_2024_25_store": {"freeze_thaw": s2425[11], "hot90": s2425[9], "below32": s2425[12],
                                 "missing": s2425[1], "days": s2425[0]},
        "june_15_2025": {"raw_prcp_mm": raw_days[date(2025, 6, 15)][0], "raw_tmax_c": raw_days[date(2025, 6, 15)][1],
                         "raw_tmin_c": raw_days[date(2025, 6, 15)][2], "prcp_hundredths_mm": jun15[1],
                         "tmax_tenths_c": jun15[2], "tmin_tenths_c": jun15[3],
                         "tmax_f_tenths": (18 * jun15[2] + 3205) // 10,
                         "tmin_f_tenths": (18 * jun15[3] + 3205) // 10},
        "differences": diffs,
        "ok": all(v == 0 for v in diffs.values()) and all(v == 0 for v in mismatches.values()),
    }
    return result


def _plan_entry(paths: dict, ym: str) -> dict:
    ledger = _load_ledger(paths)
    for entry in ledger.get("plan", []):
        if entry["month"] == ym and entry["kind"] in ("scaled", "prelim"):
            return entry
    raise ClimateError(f"{ym} is not in the cache plan")


# ---------------------------------------------------------------- the release archive of the aggregates

ARCHIVE_FORMAT = "climate-aggregates-archive-v1"
ARCHIVE_NAME = "climate-aggregates.tar.gz"


def pack_cache(cache, out_path=None) -> dict:
    """Write the cache's aggregates, ledger and listings as one release-asset-shaped archive: aggregates/*.npz,
    ledger.json and manifest.json (the SHA-256 and bytes of every member). The daily job fetches it, unpacks it
    into a cache directory with unpack_cache, and builds the store from it with no network."""
    import tarfile
    cache = Path(cache)
    paths = _cache_paths(cache)
    members = sorted(paths["agg"].glob("*.npz"))
    if not members or not paths["ledger"].exists():
        raise ClimateError("the cache holds no aggregates to pack")
    entries = {}
    for p in members:
        entries[f"aggregates/{p.name}"] = p.read_bytes()
    entries["ledger.json"] = paths["ledger"].read_bytes()
    manifest = {"format": ARCHIVE_FORMAT, "members": {k: {"bytes": len(v), "sha256": hashlib.sha256(v).hexdigest()}
                                                      for k, v in sorted(entries.items())}}
    entries["manifest.json"] = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8")
    out = Path(out_path) if out_path else paths["agg"] / ARCHIVE_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    with tarfile.open(tmp, "w:gz", format=tarfile.PAX_FORMAT) as tar:
        for name in sorted(entries):
            data = entries[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    os.replace(tmp, out)
    return {"path": str(out), "bytes": out.stat().st_size, "members": len(members),
            "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}


def unpack_cache(archive, cache) -> dict:
    """Unpack an archive written by pack_cache into the cache directory. Every member must match the archive's own
    manifest (bytes and SHA-256); a member that does not match is refused and nothing is replaced."""
    import tarfile
    cache = Path(cache)
    paths = _cache_paths(cache)
    _ensure(paths)
    data = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or member.name.startswith("/") or ".." in Path(member.name).parts:
                raise ClimateError("the archive holds a member that is not a plain file in the cache layout")
            if member.name not in ("manifest.json", "ledger.json") and not (
                    member.name.startswith("aggregates/") and member.name.endswith(".npz")):
                raise ClimateError(f"the archive holds an unexpected member: {member.name}")
            data[member.name] = tar.extractfile(member).read()
    if "manifest.json" not in data:
        raise ClimateError("the archive has no manifest")
    manifest = json.loads(data.pop("manifest.json").decode("utf-8"))
    if manifest.get("format") != ARCHIVE_FORMAT:
        raise ClimateError("the archive manifest is not in the expected format")
    if set(manifest["members"]) != set(data):
        raise ClimateError("the archive members do not match its manifest")
    for name, expect in manifest["members"].items():
        if len(data[name]) != expect["bytes"] or hashlib.sha256(data[name]).hexdigest() != expect["sha256"]:
            raise ClimateError(f"the archive member {name} does not match its manifest")
    for name, raw in data.items():
        target = cache / name
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(raw)
        os.replace(tmp, target)
    return {"members": len(data), "cache": str(cache)}


# ---------------------------------------------------------------- command line

def _today(text: str | None) -> date:
    if text:
        return date.fromisoformat(text)
    return datetime.now(timezone.utc).date()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m website.climate", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("backfill", "update"):
        p = sub.add_parser(name)
        p.add_argument("--cache", required=True, help="the cache directory (aggregates, days, ledger)")
        p.add_argument("--today", default=None, help="YYYY-MM-DD (default: today, UTC)")
    p = sub.add_parser("build")
    p.add_argument("--store", required=True, help="the store directory that holds hail/")
    p.add_argument("--cache", required=True)
    p = sub.add_parser("verify")
    p.add_argument("--store", required=True)
    p.add_argument("--cache", required=True)
    p.add_argument("--independent", action="store_true", help="re-read the Billings months from the bucket")
    p = sub.add_parser("pack", help="write the cache's aggregates as the release archive")
    p.add_argument("--cache", required=True)
    p.add_argument("--out", default=None)
    p = sub.add_parser("unpack", help="unpack the release archive into a cache directory")
    p.add_argument("--archive", required=True)
    p.add_argument("--cache", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ("backfill", "update"):
            run = run_update(Path(args.cache), _today(args.today), backfill=args.command == "backfill",
                             log=lambda s: print(s, file=sys.stderr))
            print(json.dumps(run, indent=1, sort_keys=True))
            # A source failure is recorded in the ledger and the run record, not an error of the job: the store
            # builds with that part marked partial or unavailable, and the job goes on (B5 D16).
            recorded = len(run["failures"]["months"]) + (1 if run["failures"]["listing"] else 0)
            if recorded:
                print(f"climate: {recorded} source failure(s) recorded; the store will say so", file=sys.stderr)
        elif args.command == "pack":
            print(json.dumps(pack_cache(Path(args.cache), args.out), indent=1, sort_keys=True))
        elif args.command == "unpack":
            print(json.dumps(unpack_cache(Path(args.archive), Path(args.cache)), indent=1, sort_keys=True))
        elif args.command == "build":
            block = build_store(Path(args.store), Path(args.cache), log=lambda s: print(s, file=sys.stderr))
            print(json.dumps({k: block[k] for k in ("state", "problem", "months_loaded", "months_missing",
                                                    "land_cells", "water_cells", "tiles", "records", "files",
                                                    "bytes")},
                             indent=1, sort_keys=True))
        else:
            report = verify_store(Path(args.store), Path(args.cache), independent=args.independent,
                                  log=lambda s: print(s, file=sys.stderr))
            print(json.dumps(report, indent=1, sort_keys=True))
    except (ClimateError, hail.HailStoreError) as exc:
        print(f"climate: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
