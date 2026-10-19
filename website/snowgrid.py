"""Snow analysis (B5 Source 2): the NOHRSC season-total snowfall grid, the D7 unit check, and hail/n/.

What it is: NOAA's National Snow Analysis (NOHRSC) gives one season-total snowfall GeoTIFF per water year (October 1 to
September 30). The file for 2025-26 is the water year 2026. An analysis, not a measurement at an address: a grid cell is
about 3 to 4 km across, and the words say so on every row (AGENTS.md rule 5).

Source (the research record snow-alternatives.json and its refuter; the terms were read live on 2026-10-19):
  URL       https://www.nohrsc.noaa.gov/snowfall/data/<YYYYMM>/sfav2_CONUS_<Y>093012_to_<Y+1>093012.tif, where <YYYYMM>
            is the year and month the file ends (202609 for 2025093012_to_2026093012). The block records the concrete
            URL of each water year (block "urls"), never the template.
  Files     five water years, 2022 to 2026: 2021-22 (water year 2022) to 2025-26 (water year 2026); 11,562,084 bytes in
            all. The 2020-21 file (water year 2021) is missing upstream: HTTP 404 on the live request of 2026-10-19. The
            window is fixed at these five years (gate 4); a rolling window is a separate decision. The 2026-27 season
            file (to date) is not fetched: no consumer names it, and the daily job has no NOHRSC step.
  Dates     each file read records its Last-Modified header, bytes and SHA-256 (block "water_year_files"). The 2025-26
            file (water year 2026) gets one HEAD request per run and is requested again when its Last-Modified changes.
            The other files are not checked for revisions after their fetch, and the block says so (block "revisions").
            Live on 2026-10-19: 2025-26 Mon, 05 Oct 2026 14:33:16 GMT, 2,354,154 bytes, SHA-256 8549604727ea...fae99ff.
  Grid      1500 by 850 float32, PixelIsArea, WGS 84, 0.04 degree (GeoTIFF tag 33550: 0.04, 0.04); the upper-left corner
            is -126.0 E, 55.0 N (tag 33922); LZW. Pillow reads it in mode F.
  No data   values below -9000 (the file uses -99999; about 60 percent of the cells are no data, most of them outside
            the state). The 71 water cells of the nClimGrid grid are a different product and not read here.
  Units     the file, the NOHRSC page and the product description print no units. D7 decides them: a regression of
            station season totals in inches (from the GHCN files; water years with at least 95 percent of days) on the
            grid values at the station points. A slope from 0.85 to 1.15 means inches and the product is shown; anything
            else and it stays out of the sheet, with the words saying why. Inches are the only unit ever shown.
  Terms     TERMS_NOTE holds the NWS public-domain paragraph and the 17 U.S.C. 403 sentence as the live page
            https://www.weather.gov/disclaimer reads them (2026-10-19), inside quotation marks. The page also says the NWS
            name and visual identifier are trademark protected, and that a site may not present its own information as
            official government information.

The cell rule (D4): cell_for() is the snow grid's own lookup, with the hail grid's half-open rule. A point on the north
edge of a cell or on its west edge goes to that cell (a point on an edge goes to the cell to the south or the east), in
exact decimal arithmetic in thousandths of a degree. Benchland's point (47.08 N, 110.02 W) is row 198, column 399, and
Billings (45.7836 N, 108.5047 W) is row 230, column 437. Every hail cell's lookup goes through website.hail.cell_for.
The tile that holds a snow cell is the hail tile of the snow cell's centre, through website.hail.cell_for.

Montana box: the cells whose centres lie within 44.36 to 49.00 N and 116.08 to 104.04 W are rows 150 to 265 and
columns 248 to 548: 34,916 cells (a half-open slice [150:266, 248:549]).

Store (format hail-snow-v1), see docs/DECISIONS.md D34 and the B5 brief:
  hail/n/<tile>.json  one per B1 tile that holds a box cell centre: {"f", "tile", "wy": [2022..2026], "u": "hundredths
                      of an inch", "cells": {"<row>:<col>": [five integers or null]}}. Written only when the D7 unit check
                      passes. Rounding is half up: floor(value x 100 + 0.5), so 68.625 inches is 6863. A missing value is
                      null, never zero. A finite negative value is null as well (a snowfall is not below zero), and the
                      block counts those cells per water year (block "negative_cells").
  hail/index.json     gains "snow": the state, the D7 check (slope, intercept, stations, correlation, residuals), the
                      pairs at the Billings and Benchland samples, the grid facts, the urls, the terms, the file records
                      of each water year, the counts and the problem sentence.
  hail/manifest.json  lists every hail/n/ file with its bytes and SHA-256.

Failures (D16, and the job clock): a download that is refused, stalls, or answers with something
that is not a grid leaves its water year out, which is then named in missing_water_years, and the rest of the block
builds. A cached file that cannot be read is removed and requested once more (online; offline it is reported). A request
that the job's deadline stops is "the source did not answer". The block's problem is the B2 D20 sentence for a part that
did not load ("Snow analysis for water year 2025 could not be loaded in this update; that is not the same as no snow
analysis for water year 2025."), and the D7 sentence when the units are not shown.

Command line (run from the repository root):
    python -m website.snowgrid build --store DIR --cache DIR [--offline] [--deadline-at EPOCH]
    python -m website.snowgrid verify --store DIR --cache DIR     check the grid, the check and the samples (exit 1 on a failure)
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
import time
from decimal import Decimal
from pathlib import Path

import numpy as np

from . import hail
from . import stations as S

FORMAT = "hail-snow-v1"
INDEX_KEY = "snow"
N_PREFIX = "hail/n/"
WATER_YEARS = S.WATER_YEARS                              # 2022 .. 2026
REVISION_YEAR = 2026                                     # the water year whose file gets one HEAD request per run
NODATA_BELOW = -9000.0
ROWS, COLS = 850, 1500
ORIGIN_LAT, ORIGIN_LON = Decimal("55.0"), Decimal("-126.0")
CELL = Decimal("0.04")
BOX_LAT = (Decimal("44.36"), Decimal("49.00"))
BOX_LON = (Decimal("-116.08"), Decimal("-104.04"))
BOX_ROWS = (150, 266)                                    # half-open
BOX_COLS = (248, 549)
SLOPE_MIN, SLOPE_MAX = 0.85, 1.15                        # D7
URL = "https://www.nohrsc.noaa.gov/snowfall/data/{yyyymm}/sfav2_CONUS_{start}093012_to_{end}093012.tif"
USER_AGENT = "montana-hail-watch-snowgrid/1 (+https://github.com/carson14dy/RoofingApp)"
ATTEMPTS = 3                                             # tries per water-year download (network errors, 429, 5xx)
PACE_S = 0.2                                             # at least this long between two NOHRSC requests
# the research's values, for the verify gate (raw grid values, two decimals)
RESEARCH_VALUES = {
    "billings": {"cell": (230, 437), "wy": {2025: 50.29, 2026: 33.85}},
    "benchland": {"cell": (198, 399), "wy": {2025: 87.17, 2026: 94.05}},
}
SAMPLE_POINTS = {"billings": (45.7836, -108.5047), "benchland": (47.08, -110.02)}
# The NWS disclaimer, verbatim from https://www.weather.gov/disclaimer (read live 2026-10-19). Quoted, so the words
# scan (tests/words_rules.py) and the snow word test read it as the source's own wording, not as a site's words.
PUBLIC_DOMAIN_TEXT = ("The information on National Weather Service (NWS) Web pages are in the public domain, unless "
                      "specifically noted otherwise, and may be used without charge for any lawful purpose so long as "
                      "you do not: 1) claim it is your own (e.g., by claiming copyright for NWS information -- see "
                      "below), 2) use it in a manner that implies an endorsement or affiliation with NOAA/NWS, or 3) "
                      "modify its content and then present it as official government material.")
SECTION_403_TEXT = ("As required by 17 U.S.C. § 403, third parties producing copyrighted works consisting predominantly "
                    "of the material appearing in NWS Web pages must provide notice with such work(s) identifying the "
                    "NWS material incorporated and stating that such material is not subject to copyright protection.")
TERMS_NOTE = ("NWS terms, quoted as the live page reads (https://www.weather.gov/disclaimer, 2026-10-19): "
              f"\"{PUBLIC_DOMAIN_TEXT}\" \"{SECTION_403_TEXT}\"")
REVISIONS_NOTE = ("The 2025-26 file (water year 2026) is checked with one HEAD request per run, and it is requested again "
                  "when its Last-Modified changes. The other water-year files are not checked for revisions after "
                  "their fetch.")
NOT_IN_STORE = ("the 2020-21 season (water year 2021) is missing upstream: its NOHRSC file returns HTTP 404 "
                "(checked live on 2026-10-19), so it is not in the five water years")


class SnowError(Exception):
    """A file or figure that cannot be used. The message is plain words, lower case, with no full stop."""


WORDS = {
    "analysis": ("Analysis: {inches} in of snow in the {water_year} water year, from the analysis cell about {miles} "
                 "miles away. An analysis, not a measurement at this address."),
    "no_value": ("Analysis: no value for the {water_year} water year at this cell. That is not the same as no snow."),
    "unit_failed": ("Analysis: not shown. Its figures did not agree with station snowfall closely enough to show that "
                    "they are in inches. Station readings are shown instead."),
    "unit_unchecked": ("Analysis: not shown. Its units could not be checked against station snowfall, so it is not "
                       "shown. Station readings are shown instead."),
    "unavailable": "{Part} could not be loaded in this update; that is not the same as no {one}.",
    "what": ("The National Snow Analysis is NOAA's gridded estimate of season snowfall, one cell about 3 to 4 km across, "
             "built from station observations and other inputs. An analysis, not a measurement at this address."),
    "water_year_label": "{yy} (October {y0} to September {y1})",
}


# ---------------------------------------------------------------- cells and the Montana box

def _d(value) -> Decimal:
    return Decimal(repr(float(value)))


def cell_for(lat: float, lon: float) -> tuple[int, int]:
    """(row, col) of the snow grid cell that holds (lat, lon): row = floor((55.0 - lat) / 0.04) and
    col = floor((lon + 126.0) / 0.04), in exact decimal arithmetic in thousandths of a degree (a point on an edge
    goes to the cell to the south or east). The result can lie outside the grid; use in_grid()."""
    lat_e3 = _d(lat) * 1000
    lon_e3 = _d(lon) * 1000
    row = math.floor((Decimal(55000) - lat_e3) / 40)
    col = math.floor((lon_e3 + Decimal(126000)) / 40)
    return int(row), int(col)


def cell_centre(row: int, col: int) -> tuple[float, float]:
    """The centre of snow cell (row, col): lat = 55.0 - 0.04 (row + 0.5), lon = -126.0 + 0.04 (col + 0.5), in thousandths."""
    return (55000 - 40 * int(row) - 20) / 1000, (-126000 + 40 * int(col) + 20) / 1000


def in_grid(row: int, col: int) -> bool:
    return 0 <= int(row) < ROWS and 0 <= int(col) < COLS


def in_box(row: int, col: int) -> bool:
    return BOX_ROWS[0] <= int(row) < BOX_ROWS[1] and BOX_COLS[0] <= int(col) < BOX_COLS[1]


def box_cells() -> list[tuple[int, int]]:
    """The Montana box: every snow cell whose centre lies in BOX_LAT by BOX_LON, row by row. The grid is regular, so
    a row's centre latitude is the same for every column (and a column's longitude for every row): the rows and the
    columns are found from one column and one row, and no centre lies on a box edge (checked in the tests)."""
    rows = [r for r in range(ROWS) if float(BOX_LAT[0]) <= cell_centre(r, 0)[0] <= float(BOX_LAT[1])]
    cols = [c for c in range(COLS) if float(BOX_LON[0]) <= cell_centre(0, c)[1] <= float(BOX_LON[1])]
    return [(r, c) for r in rows for c in cols]


def snow_tile(row: int, col: int) -> tuple[int, int]:
    """The B1 tile that holds this snow cell: the hail tile of the snow cell's centre (website.hail.cell_for)."""
    lat, lon = cell_centre(row, col)
    hrow, hcol = hail.cell_for(lat, lon)
    return hrow // hail.TILE, hcol // hail.TILE


def tile_name_for(row: int, col: int) -> str:
    tr, tc = snow_tile(row, col)
    return hail.tile_name(tr, tc)


def cell_key(row: int, col: int) -> str:
    return f"{int(row)}:{int(col)}"


# ---------------------------------------------------------------- reading the GeoTIFF

def read_grid(source, name: str | None = None) -> np.ndarray:
    """The 850 by 1500 float32 grid (no data as NaN), read with Pillow from a path or from downloaded bytes. Refuses a
    file whose mode, size, scale or corner differs from the NOHRSC grid the research read, and any file that cannot be
    decoded: every such file raises SnowError (plain words), never another exception."""
    from PIL import Image
    if isinstance(source, (bytes, bytearray)):
        label = name or "the download"
        handle = io.BytesIO(bytes(source))
    else:
        label = name or Path(source).name
        handle = Path(source)
    try:
        image = Image.open(handle)
    except Exception as exc:                  # any decoder error means the file cannot be read
        raise SnowError(f"the snow file {label} cannot be read ({type(exc).__name__})") from exc
    with image:
        if image.mode != "F" or image.size != (COLS, ROWS):
            raise SnowError(f"the snow file {label} is not the expected grid ({image.mode} {image.size})")
        try:
            scale = image.tag_v2.get(33550)
            tie = image.tag_v2.get(33922)
            scale_ok = bool(scale) and abs(float(scale[0]) - 0.04) <= 1e-9 and abs(float(scale[1]) - 0.04) <= 1e-9
            tie_ok = bool(tie) and abs(float(tie[3]) + 126.0) <= 1e-9 and abs(float(tie[4]) - 55.0) <= 1e-9
        except (IndexError, TypeError, ValueError) as exc:
            raise SnowError(f"the snow file {label} has unreadable georeferencing") from exc
        if not scale_ok:
            raise SnowError(f"the snow file {label} does not have a 0.04 degree cell")
        if not tie_ok:
            raise SnowError(f"the snow file {label} does not start at 126.0 W and 55.0 N")
        try:
            values = np.asarray(image, dtype=np.float32).astype(np.float64)
        except Exception as exc:              # a truncated or damaged body
            raise SnowError(f"the snow file {label} cannot be decoded ({type(exc).__name__})") from exc
    values[values < NODATA_BELOW] = np.nan
    return values


def water_year_file(year: int) -> str:
    """The NOHRSC file name of a water year: water year 2026 is 2025093012_to_2026093012."""
    return f"sfav2_CONUS_{year - 1}093012_to_{year}093012.tif"


def water_year_url(year: int) -> str:
    return URL.format(yyyymm=f"{year}09", start=year - 1, end=year)


def _years_phrase(years) -> str:
    names = [str(y) for y in years]
    if len(names) == 1:
        return f"water year {names[0]}"
    return f"water years {', '.join(names[:-1])} and {names[-1]}"


def _unavailable_years(years) -> str:
    phrase = "snow analysis for " + _years_phrase(years)
    return WORDS["unavailable"].format(Part=phrase[0].upper() + phrase[1:], one=phrase)


def _unavailable_all() -> str:
    return WORDS["unavailable"].format(Part="Snow analysis", one="snow analysis")


# ---------------------------------------------------------------- the cache and the downloads

def _meta_path(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def _read_meta(path: Path) -> dict | None:
    meta = _meta_path(path)
    try:
        doc = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _write_meta(path: Path, meta: dict) -> None:
    S._write_atomic(_meta_path(path), (json.dumps(meta, sort_keys=True, indent=1) + "\n").encode("utf-8"))


def _remove(path: Path) -> None:
    for part in (path, _meta_path(path)):
        if part.is_file():
            part.unlink()


def _header(headers: dict, name: str) -> str | None:
    wanted = name.lower()
    for key, value in (headers or {}).items():
        if str(key).lower() == wanted:
            return str(value)
    return None


def _read_cached(path: Path) -> tuple[np.ndarray | None, str | None]:
    try:
        return read_grid(path), None
    except SnowError as exc:
        return None, str(exc)


def _head_last_modified(url: str, *, deadline_at: float | None, pacer: S._Pacer) -> tuple[str | None, str]:
    """One HEAD request: (Last-Modified or None, status words)."""
    import requests
    if deadline_at is not None and time.monotonic() >= deadline_at:
        return None, S.REASON_NO_ANSWER
    pacer.wait()
    try:
        resp = requests.head(url, timeout=S.READ_TIMEOUT, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
    except requests.RequestException as exc:
        return None, type(exc).__name__
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"
    value = _header(dict(resp.headers or {}), "Last-Modified")
    return (value, "checked") if value else (None, "no Last-Modified header")


def _download(path: Path, year: int, *, deadline_at: float | None, pacer: S._Pacer) -> tuple[np.ndarray | None, dict]:
    """One water-year file with up to ATTEMPTS tries. The file and its record are kept only when the grid reads. Returns
    (grid or None, {"last_modified": ...} or {"reason": ...})."""
    import requests
    url = water_year_url(year)
    last = S.REASON_NO_ANSWER
    for attempt in range(1, ATTEMPTS + 1):
        if deadline_at is not None and time.monotonic() >= deadline_at:
            return None, {"reason": S.REASON_NO_ANSWER}
        pacer.wait()
        try:
            status, data, headers = S._get(url, {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
        except requests.RequestException as exc:
            last = type(exc).__name__
        except S.StationsError as exc:
            last = str(exc)
        else:
            if status == 200:
                try:
                    grid = read_grid(data, name=path.name)
                except SnowError as exc:
                    last = str(exc)                 # a 200 answer that is not a grid is refused, not kept
                else:
                    pacer.add_bytes(len(data))
                    last_modified = _header(headers, "Last-Modified")
                    S._write_atomic(path, data)
                    _write_meta(path, {"url": url, "last_modified": last_modified, "bytes": len(data),
                                       "sha256": hashlib.sha256(data).hexdigest()})
                    return grid, {"last_modified": last_modified}
            else:
                last = f"HTTP {status}"
                if status != 429 and status < 500:
                    break
        if attempt < ATTEMPTS:
            time.sleep(1.5 * attempt)
    return None, {"reason": last}


def load_years(cache: Path, *, offline: bool, deadline_at: float | None = None,
               pacer: S._Pacer | None = None) -> tuple[dict[int, np.ndarray], dict[str, dict]]:
    """The five water-year grids that could be read, keyed by water year, and one record per water year: the file, its
    URL, its bytes and SHA-256, the Last-Modified header it was fetched with, and where it came from (cache or fetched),
    or the plain reason it is missing. A cached file that cannot be read is removed and requested once more (online);
    offline it is reported and left as it is. The 2025-26 file gets one HEAD request per run and is requested again when
    its Last-Modified changes; a failed request then keeps the cached copy."""
    pacer = pacer or S._Pacer(PACE_S)
    folder = Path(cache) / "nohrsc"
    folder.mkdir(parents=True, exist_ok=True)
    grids: dict[int, np.ndarray] = {}
    records: dict[str, dict] = {}
    for year in WATER_YEARS:
        path = folder / water_year_file(year)
        rec: dict = {"file": path.name, "url": water_year_url(year)}
        grid = None
        if path.is_file():
            cached_meta = _read_meta(path) or {}
            grid, problem = _read_cached(path)
            if grid is not None:
                rec["source"] = "cache"
                rec["last_modified"] = cached_meta.get("last_modified")
            else:
                rec["cache_problem"] = problem
                if not offline:
                    _remove(path)                   # the unreadable copy goes; it is requested once below
        fallback = grid
        if grid is not None and not offline and (year == REVISION_YEAR or rec.get("last_modified") is None):
            now, status = _head_last_modified(water_year_url(year), deadline_at=deadline_at, pacer=pacer)
            if year == REVISION_YEAR:
                rec["revision_check"] = {"status": status, "last_modified_now": now,
                                         "last_modified_cached": rec.get("last_modified")}
                if now and now != rec.get("last_modified"):
                    rec["revision_check"]["status"] = "changed: requested again"
                    grid = None
            elif now:                               # a file cached before dates were kept: its date is recorded, not re-read
                rec["last_modified"] = now
                rec["last_modified_note"] = "read by one HEAD request on this run; the file was cached before dates were kept"
                _write_meta(path, dict(cached_meta, url=water_year_url(year), last_modified=now))
        if grid is None and not offline:
            got, info = _download(path, year, deadline_at=deadline_at, pacer=pacer)
            if got is not None:
                grid = got
                rec["source"] = "fetched"
                rec["last_modified"] = info.get("last_modified")
            else:
                rec["reason"] = info["reason"]
                if fallback is not None:            # the cached copy is still good: it is used, and that is said
                    grid = fallback
                    rec["source"] = "cache"
                    rec["reason"] = f"served the cached copy after: {info['reason']}"
        if grid is None:
            if offline:
                why = ("the cached copy is not usable, and this build makes no requests" if "cache_problem" in rec
                       else "the file is not in the cache and this build makes no requests")
            else:
                why = "the file could not be read"
            rec.setdefault("reason", why)
            records[str(year)] = rec
            continue
        grids[year] = grid
        data = path.read_bytes()
        rec["bytes"] = len(data)
        rec["sha256"] = hashlib.sha256(data).hexdigest()
        rec.setdefault("last_modified", None)       # null: not recorded (a file cached before this record was kept)
        records[str(year)] = rec
    return grids, records


# ---------------------------------------------------------------- the D7 check

def regress(pairs: list[tuple[float, float]]) -> dict:
    """Ordinary least squares of y (station inches) on x (grid value): slope, intercept, n, residuals (in the order
    given), and the residual root mean square and largest absolute residual. Refuses fewer than three pairs, or no
    spread in x."""
    n = len(pairs)
    if n < 3:
        raise SnowError("fewer than three station seasons, so the snow check cannot run")
    xs = [float(x) for x, _ in pairs]
    ys = [float(y) for _, y in pairs]
    xbar = math.fsum(xs) / n
    ybar = math.fsum(ys) / n
    sxx = math.fsum((x - xbar) ** 2 for x in xs)
    if sxx <= 0:
        raise SnowError("the grid values at the stations do not vary, so the snow check cannot run")
    sxy = math.fsum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = ybar - slope * xbar
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    rms = math.sqrt(math.fsum(r * r for r in residuals) / n)
    syy = math.fsum((y - ybar) ** 2 for y in ys)
    corr = sxy / math.sqrt(sxx * syy) if syy > 0 else float("nan")
    return {"slope": slope, "intercept": intercept, "n": n, "rms": rms, "r": corr,
            "max_abs": max(abs(r) for r in residuals), "residuals": residuals}


def unit_check(slope: float) -> dict:
    """D7: inches when the slope is from 0.85 to 1.15; otherwise the product stays out."""
    passed = SLOPE_MIN <= slope <= SLOPE_MAX
    return {"rule": "slope from 0.85 to 1.15 means inches (D7)", "unit": "inches" if passed else None, "pass": passed}


def station_pairs(sd_docs: dict, grids: dict[int, np.ndarray]) -> tuple[list[dict], dict]:
    """Every (station, water year) with a complete season (at least 95 percent of days with an unflagged SNOW value) and
    a valid grid value at the station point. Returns the pair rows and the counts of what was left out, and why. A
    season with no SNOW value, or a negative grid value, is left out (no value is never a zero)."""
    rows = []
    left = {"incomplete": 0, "no_grid_value": 0, "no_grid": 0}
    for sid in sorted(sd_docs):
        doc = sd_docs[sid]
        water = doc.get("periods", {}).get("water", {})
        for year in WATER_YEARS:
            rec = water.get(str(year))
            ok = S.count_of(rec, "SNOW", "ok")
            if ok is None:
                continue                            # no SNOW record in this season: nothing to pair
            if ok < S.SEASON_MIN * rec["n"]:       # includes a season whose every value is flagged (ok 0)
                left["incomplete"] += 1
                continue
            total = S.count_of(rec, "SNOW", "sum")
            if total is None:
                continue
            if year not in grids:
                left["no_grid"] += 1
                continue
            row, col = cell_for(doc["lat"], doc["lon"])
            value = grids[year][row, col] if in_grid(row, col) else np.nan
            if not np.isfinite(value) or value < 0:
                left["no_grid_value"] += 1
                continue
            rows.append({"id": sid, "wy": year, "x": float(value), "y": total / 25.4, "row": row, "col": col,
                         "n": rec["n"], "ok": ok})
    return rows, left


def sample_values(grids: dict[int, np.ndarray]) -> dict:
    out = {}
    for name, info in RESEARCH_VALUES.items():
        row, col = info["cell"]
        lat, lon = cell_centre(row, col)
        out[name] = {"row": row, "col": col, "centre": [lat, lon],
                     "wy": {str(y): (None if y not in grids or not np.isfinite(grids[y][row, col])
                                     else round(float(grids[y][row, col]), 2)) for y in WATER_YEARS}}
    return out


# ---------------------------------------------------------------- the build

def hundredths_half_up(value) -> int:
    """A non-negative value in inches to whole hundredths, rounded half up (the B5 rule): floor(value x 100 + 0.5).
    Python's round() rounds halves to even (68.625 would give 6862), so it is not used here."""
    return math.floor(float(value) * 100 + 0.5)


def build(store: Path, cache: Path, *, offline: bool = False, deadline_at: float | None = None) -> dict:
    store = Path(store)
    index_path = store / "hail" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    t0 = time.monotonic()
    pacer = S._Pacer(PACE_S)
    grids, records = load_years(Path(cache), offline=offline, deadline_at=deadline_at, pacer=pacer)
    missing = [y for y in WATER_YEARS if y not in grids]
    sd_dir = store / "hail" / "sd"
    sd_docs = {}
    if sd_dir.is_dir():
        for path in sorted(sd_dir.glob("*.json")):
            sd_docs[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    base = {"f": FORMAT, "source": "NOHRSC National Snow Analysis, season-total snowfall (water years)",
            "urls": {str(y): water_year_url(y) for y in WATER_YEARS}, "water_years": list(WATER_YEARS),
            "missing_water_years": missing, "water_year_files": records, "revisions": REVISIONS_NOTE,
            "not_in_store": NOT_IN_STORE,
            "grid": {"cell_deg": 0.04, "rows": ROWS, "cols": COLS, "origin_lat": 55.0, "origin_lon": -126.0,
                     "box_rows": list(BOX_ROWS), "box_cols": list(BOX_COLS), "box_cells": 34916,
                     "nodata_below": NODATA_BELOW},
            "terms": TERMS_NOTE, "words": WORDS}
    counts = {"requests": pacer.requests, "downloaded_bytes": pacer.downloaded}
    if missing and not grids:
        block = dict(base, state="unavailable", problem=_unavailable_all(), shown=False, **counts)
        _merge_index(store, block)
        _merge_manifest(store, {}, prefixes=(N_PREFIX,))
        return {"state": "unavailable", "missing": missing}
    if not sd_docs:
        block = dict(base, state="unavailable", problem=_unavailable_all(), shown=False,
                     detail="the station files are not in the store, so the unit check cannot run", **counts)
        _merge_index(store, block)
        _merge_manifest(store, {}, prefixes=(N_PREFIX,))
        return {"state": "unavailable", "problem": "no station files"}
    rows, left = station_pairs(sd_docs, grids)
    try:
        fit = regress([(r["x"], r["y"]) for r in rows])
    except SnowError as exc:
        block = dict(base, state="unavailable", problem=WORDS["unit_unchecked"], detail=str(exc), shown=False,
                     pairs=len(rows), left_out=left, **counts)
        _merge_index(store, block)
        _merge_manifest(store, {}, prefixes=(N_PREFIX,))
        return {"state": "unavailable", "problem": str(exc)}
    check = unit_check(fit["slope"])
    samples = sample_values(grids)
    billings_pairs = [{"station": r["id"], "wy": r["wy"], "grid_in": round(r["x"], 2), "station_in": round(r["y"], 2)}
                      for r in rows if r["id"] in ("USW00024033", "USC00240802") and r["wy"] >= 2025]
    summary = {"slope": round(fit["slope"], 6), "intercept": round(fit["intercept"], 6), "stations": fit["n"],
               "correlation": round(fit["r"], 6), "rms_residual_in": round(fit["rms"], 4),
               "max_abs_residual_in": round(fit["max_abs"], 4), "pass": check["pass"], "unit": check["unit"],
               "rule": check["rule"], "fit": "ordinary least squares of station inches on the grid value"}
    files: dict[str, dict] = {}
    n_bytes = 0
    cells_written = 0
    negatives = None
    if check["pass"]:
        cells_written, files, n_bytes, negatives = _write_n(store, grids, index)
    n_files = len(files)
    if not check["pass"]:
        state, problem = "unavailable", WORDS["unit_failed"]
    elif missing:
        state, problem = "partial", _unavailable_years(missing)
    else:
        state, problem = "loaded", None
    block = dict(base, state=state, shown=check["pass"], check=summary, pairs=len(rows), left_out=left,
                 pairs_billings=billings_pairs, samples=samples, files=n_files, bytes=n_bytes, cells=cells_written,
                 negative_cells=negatives, problem=problem, **counts)
    _merge_index(store, block)
    _merge_manifest(store, files, prefixes=(N_PREFIX,))
    return {"state": state, "seconds": round(time.monotonic() - t0, 1), "shown": check["pass"],
            "slope": round(fit["slope"], 4), "intercept": round(fit["intercept"], 4), "stations": fit["n"],
            "files": n_files, "bytes": n_bytes, "missing_water_years": missing, "requests": pacer.requests,
            "downloaded_bytes": pacer.downloaded}


def _write_n(store: Path, grids: dict[int, np.ndarray],
             index: dict) -> tuple[int, dict, int, dict]:
    """Writes hail/n/<tile>.json for every tile that holds a box cell centre. Values are hundredths of an inch, rounded
    half up. Returns (cells, files, bytes, negatives): negatives counts the finite negative values per water year, which
    are written as null (a missing value is null, never zero)."""
    by_tile: dict[str, dict] = {}
    negatives = {str(y): 0 for y in WATER_YEARS}
    for row, col in box_cells():
        name = tile_name_for(row, col)
        vals = []
        for year in WATER_YEARS:
            grid = grids.get(year)
            v = grid[row, col] if grid is not None else np.nan
            if not np.isfinite(v):
                vals.append(None)
            elif v < 0:
                negatives[str(year)] += 1
                vals.append(None)
            else:
                vals.append(hundredths_half_up(v))
        by_tile.setdefault(name, {})[cell_key(row, col)] = vals
    files = {}
    total = 0
    cells = 0
    for name in sorted(by_tile):
        doc = {"f": FORMAT, "tile": name, "wy": list(WATER_YEARS), "u": "hundredths of an inch",
               "cells": {k: by_tile[name][k] for k in sorted(by_tile[name], key=_key_order)}}
        data = (json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
        rel = f"{N_PREFIX}{name}.json"
        S._write_atomic(store / rel, data)
        files[rel] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        total += len(data)
        cells += len(doc["cells"])
    return cells, files, total, negatives


def _key_order(key: str) -> tuple[int, int]:
    row, col = key.split(":")
    return int(row), int(col)


def _merge_index(store: Path, block: dict) -> None:
    path = store / "hail" / "index.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    index[INDEX_KEY] = block
    S._write_atomic(path, (json.dumps(index, indent=1, ensure_ascii=True) + "\n").encode("utf-8"))


def _merge_manifest(store: Path, new_files: dict, prefixes: tuple) -> None:
    S._merge_manifest(store, new_files, prefixes)


# ---------------------------------------------------------------- verify

def verify(store: Path, cache: Path | None = None) -> dict:
    store = Path(store)
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "pass": bool(passed), "detail": detail})

    index = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))
    block = index.get(INDEX_KEY)
    check("snow block present", isinstance(block, dict))
    if not isinstance(block, dict):
        return {"ok": False, "checks": checks}
    check("cell_for: Benchland point is row 198, column 399", cell_for(47.08, -110.02) == (198, 399))
    check("cell_for: Billings point is row 230, column 437", cell_for(45.7836, -108.5047) == (230, 437))
    check("cell_for: the north edge of row 198 is row 198 and the east edge of column 399 is column 400",
          cell_for(47.08, -110.0) == (198, 400) and cell_for(47.08, -110.04) == (198, 399))
    boxes = box_cells()
    check("Montana box has 34,916 cells in rows 150 to 265 and columns 248 to 548",
          len(boxes) == 34916 and min(r for r, _ in boxes) == 150 and max(r for r, _ in boxes) == 265
          and min(c for _, c in boxes) == 248 and max(c for _, c in boxes) == 548, f"{len(boxes)} cells")
    check("snow block state is loaded or unavailable with words", block.get("state") in ("loaded", "partial",
                                                                                          "unavailable"))
    check("missing water years are named", isinstance(block.get("missing_water_years"), list),
          str(block.get("missing_water_years")))
    urls = block.get("urls") or {}
    check("one concrete URL per water year, with no template marks",
          sorted(urls) == sorted(str(y) for y in WATER_YEARS)
          and all(urls[str(y)] == water_year_url(y) and "{" not in urls[str(y)] and "<" not in urls[str(y)]
                  for y in WATER_YEARS))
    check("unit check recorded", isinstance(block.get("check"), dict) or block.get("state") == "unavailable")
    shown = bool(block.get("shown"))
    chk = block.get("check") or {}
    if chk:
        expect_pass = SLOPE_MIN <= chk.get("slope", float("nan")) <= SLOPE_MAX
        check("display decision follows the D7 check", bool(chk.get("pass")) == expect_pass == shown,
              f"slope {chk.get('slope')}")
        check("check slope and intercept are finite numbers", math.isfinite(chk["slope"]) and
              math.isfinite(chk["intercept"]))
    grids: dict[int, np.ndarray] = {}
    if cache is not None and (Path(cache) / "nohrsc").is_dir():
        grids, _records = load_years(Path(cache), offline=True)
        for name, info in RESEARCH_VALUES.items():
            row, col = info["cell"]
            for year, want in info["wy"].items():
                if year not in grids:
                    check(f"research value {name} {year}", False, "file missing")
                    continue
                got = float(grids[year][row, col])
                check(f"research value {name} water year {year}", abs(got - want) <= 0.005,
                      f"{got:.4f} against {want}")
    if shown:
        files = sorted((store / "hail" / "n").glob("*.json"))
        seen = 0
        bad = 0
        manifest = json.loads((store / "hail" / "manifest.json").read_text(encoding="utf-8"))
        for path in files:
            data = path.read_bytes()
            entry = manifest["files"].get(path.relative_to(store).as_posix())
            if entry is None or entry["bytes"] != len(data) or entry["sha256"] != hashlib.sha256(data).hexdigest():
                bad += 1
            doc = json.loads(data)
            for key, vals in doc["cells"].items():
                seen += 1
                if len(vals) != 5 or any(v is not None and (not isinstance(v, int) or v < 0) for v in vals):
                    bad += 1
        check("n files: five integers or null per cell, manifest hashes match", bad == 0, f"{bad} problems")
        check("n files hold every box cell once", seen == 34916, f"{seen} cells")
        for name, info in RESEARCH_VALUES.items():
            row, col = info["cell"]
            tile = tile_name_for(row, col)
            path = store / "hail" / "n" / f"{tile}.json"
            doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"cells": {}}
            vals = doc["cells"].get(cell_key(row, col), [])
            for year, want in info["wy"].items():
                idx = WATER_YEARS.index(year)
                got = vals[idx] if len(vals) == 5 else None
                check(f"stored {name} water year {year} equals {want} in hundredths",
                      got == round(want * 100), f"stored {got}")
    ok = all(c["pass"] for c in checks)
    return {"ok": ok, "checks": checks, "state": block.get("state"), "shown": shown,
            "check": block.get("check"), "pairs_billings": block.get("pairs_billings")}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.snowgrid", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="read the five water years, run the unit check, write hail/n/")
    b.add_argument("--store", required=True)
    b.add_argument("--cache", required=True)
    b.add_argument("--offline", action="store_true")
    b.add_argument("--deadline-at", type=float, default=None,
                   help="epoch seconds: no request starts after this time (the job's clock)")
    v = sub.add_parser("verify", help="check the snow block, the n files and the research values")
    v.add_argument("--store", required=True)
    v.add_argument("--cache", default=None)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "build":
        deadline_at = None
        if args.deadline_at is not None:
            deadline_at = time.monotonic() + (args.deadline_at - time.time())
        print(json.dumps(build(Path(args.store), Path(args.cache), offline=args.offline, deadline_at=deadline_at),
                         indent=1, sort_keys=True))
        return 0
    result = verify(Path(args.store), Path(args.cache) if args.cache else None)
    print(json.dumps(result, indent=1, sort_keys=True, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
