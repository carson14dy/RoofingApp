"""Radar echo tops for the 14 towns: the text first (P1 of the storm layers; research/globe §6).

NOAA MRMS MergedReflectivityQC is a radar estimate of reflectivity (dBZ) at 11 heights above mean
sea level, 0.5 to 15 km. Each height is one GRIB2 file every 2 minutes on the public bucket. For
each town this module takes the newest time at which all 11 heights have a file within 10 seconds,
reads the town's cell from each file, and works out:

- the echo top: the highest height above ground at which dBZ is 35 or more, among the heights that had
  radar data (metres above sea level). If heights above it had no radar value, the top is a lower bound
  and the text says "at least";
- the counts behind it: heights with a dBZ value, heights with no radar value (-99 or -999), and
  heights below the town's ground height, which are counted and not used.

-99 and -999 mean "no radar value". Their meaning is not verified (research/globe/validation-evidence/
mrms.json; p0-gates.json says "not settled"), so they are never a value and never 0. Other negative
values are weak echoes: values.

This is a radar estimate. No echo is not an all-clear, and no text here says dry, clear or no hail.

    results, status = collect(get, now, towns)                # live: the NOAA bucket
    results, status = collect(get, now, towns, sample=True)   # labelled SAMPLE values, no network

`towns` is a list of {"slug", "name", "lat", "lon", "ground_m"}; ground_m is None when the NWS grid
height didn't load. `get(url, headers=None) -> (bytes | None, error | None)` is the build's fetcher.
Nothing here raises to the caller: a failure becomes a status and plain words. pygrib is imported
only where a GRIB file is decoded, so the tests run without it. Feed details: sources.CONTRACTS
"storm_levels".
"""
from __future__ import annotations

import gzip
import html
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np

from . import gridded
from . import sources as src

UTC = timezone.utc
MT = ZoneInfo("America/Denver")

LABEL = "MRMS reflectivity levels"
SOURCE = "NOAA MRMS MergedReflectivityQC, radar estimate"
SAMPLE_SOURCE = "SAMPLE: invented values, not NOAA MRMS"

LEVELS_KM = (0.50, 1.00, 2.00, 3.00, 4.00, 5.00, 6.00, 8.00, 10.00, 12.00, 15.00)
LEVEL_NAMES = tuple(f"{k:05.2f}" for k in LEVELS_KM)        # file names: "00.50" ... "15.00"
HEIGHTS_M = tuple(round(k * 1000) for k in LEVELS_KM)        # metres above mean sea level
PRODUCT = "CONUS/MergedReflectivityQC_"
KEY = re.compile(r"MRMS_MergedReflectivityQC_(\d\d\.\d\d)_(\d{8})-(\d{6})\.grib2\.gz$")
REFLECTIVITY = (209, 9, 0)      # discipline, category, number: checked on the 11 live files, 2026-10-17
GRID_SHAPE = (7000, 3500)       # Ni, Nj of the regular latitude-longitude grid (0.01 degree)
ECHO_DBZ = 35.0
ECHO_EPS = 1e-4                 # float rounding allowance on the 35 dBZ test
NO_DATA = (-99.0, -999.0)       # "no radar value"; meaning unverified; never a value, never 0
JOIN = timedelta(seconds=10)    # the 11 heights of one time may differ by up to 10 s
WINDOW = timedelta(minutes=60)  # how far back the file lists look for a common time
STALE = gridded.RADAR_STALE     # 30 minutes, as the radar frames
STALE_MIN = int(STALE.total_seconds() // 60)


# ---------------------------------------------------------------- time helpers

def _km(level: str) -> str:
    """A height's file-name level in plain words: '04.00' -> '4 km'."""
    return f"{float(level):g} km"


def _clock(dt: datetime) -> str:
    """Montana clock time with its zone, as the site writes times: '2:40 pm MDT'."""
    local = dt.astimezone(MT)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'} {local.tzname()}"


# ---------------------------------------------------------------- finding a common time

def list_urls(level: str, now: datetime) -> list[str]:
    """S3 listings of one height for the last WINDOW: today's folder, and yesterday's when the window
    starts there. One extra minute, because start-after skips a file named exactly at the start."""
    start = now.astimezone(UTC) - WINDOW - timedelta(minutes=1)
    urls = []
    for day in sorted({start.date(), now.astimezone(UTC).date()}):
        prefix = f"{PRODUCT}{level}/{day:%Y%m%d}/"
        url = f"{gridded.MRMS}?list-type=2&prefix={quote(prefix)}"
        if start.date() == day:
            url += "&start-after=" + quote(f"{prefix}MRMS_MergedReflectivityQC_{level}_{start:%Y%m%d-%H%M%S}.grib2.gz")
        urls.append(url)
    return urls


def parse_keys(data, level: str) -> tuple[list[tuple[datetime, str]], str | None]:
    """S3 ListObjectsV2 XML -> ([(file time UTC, key)] for one height, continuation token or None)."""
    text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data or "")
    if "<ListBucketResult" not in text:
        raise ValueError(f"the radar file list for {_km(level)} was not readable")
    found = []
    for key in re.findall(r"<Key>([^<]+)</Key>", text):
        key = html.unescape(key)
        m = KEY.search(key)
        if m and m.group(1) == level:
            try:
                found.append((datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M%S").replace(tzinfo=UTC), key))
            except ValueError:
                continue
    token = None
    if re.search(r"<IsTruncated>\s*true\s*</IsTruncated>", text):
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        token = html.unescape(m.group(1)) if m else None
    return sorted(found), token


def list_levels(get, now: datetime) -> tuple[dict[str, list[tuple[datetime, str]]], int]:
    """-> ({height name: [(file time UTC, key)] oldest first}, bytes of listings read). Raises
    ValueError (plain words) when a listing doesn't load."""
    files, listed = {}, 0
    oldest = now.astimezone(UTC) - WINDOW - timedelta(minutes=1)
    for level in LEVEL_NAMES:
        found = set()
        for url in list_urls(level, now):
            token = None
            for _page in range(10):
                data, err = get(url + (f"&continuation-token={quote(token, safe='')}" if token else ""))
                if err:
                    raise ValueError(f"the radar file list for {_km(level)} didn't load: {err}")
                listed += len(data or b"")
                items, token = parse_keys(data, level)
                found.update(item for item in items if item[0] >= oldest)
                if not token:
                    break
        files[level] = sorted(found)
    return files, listed


def common_step(files: dict, tolerance: timedelta = JOIN):
    """The newest time at which every height has a file within `tolerance`, as (time, {height name:
    (file time, key)}), or None. Candidates are the file times, newest first; each height takes its
    nearest file to the candidate (a tie takes the earlier file)."""
    if any(not files.get(level) for level in LEVEL_NAMES):
        return None
    candidates = sorted({t for level in LEVEL_NAMES for t, _key in files[level]}, reverse=True)
    for when in candidates:
        picks = {}
        for level in LEVEL_NAMES:
            best = min(files[level], key=lambda f: (abs(f[0] - when), f[0]))
            if abs(best[0] - when) > tolerance:
                break
            picks[level] = best
        else:
            return when, picks
    return None


# ---------------------------------------------------------------- decoding one height

def _no_data_to_nan(values) -> np.ndarray:
    """dBZ as float64, with -99, -999 and anything not finite as NaN. NaN is never a value or 0."""
    a = np.asarray(values, dtype=np.float64)
    bad = ~np.isfinite(a)
    for code in NO_DATA:
        bad |= np.abs(a - code) < 1e-6
    return np.where(bad, np.nan, a)


def decode_level(data: bytes, level: str, when: datetime, lats, lons) -> np.ndarray:
    """One height's gzipped GRIB2 file -> dBZ at each town's cell (NaN = no radar value). Checks that the
    file is a reflectivity grid at this height, on the expected grid, at its own time."""
    import pygrib   # only live builds read GRIB files
    raw = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
    msg = pygrib.fromstring(gridded.grib_message(raw))
    if (msg["discipline"], msg["parameterCategory"], msg["parameterNumber"]) != REFLECTIVITY:
        raise ValueError("the radar file was not a reflectivity grid")
    if msg["gridType"] != "regular_ll":
        raise ValueError("the radar file had an unexpected grid")
    if msg["typeOfLevel"] != "heightAboveSea" or int(msg["level"]) != round(float(level) * 1000):
        raise ValueError(f"the radar file was not the {_km(level)} height")
    grid = gridded.mrms_grid(msg)
    if (grid["ni"], grid["nj"]) != GRID_SHAPE:
        raise ValueError("the radar file had an unexpected grid size")
    if abs(gridded._valid_time(msg) - when) > timedelta(minutes=2):
        raise ValueError("the radar file's own time didn't match its name")
    rows, cols, ok_rows, ok_cols = gridded.mrms_index(grid, lats, lons)
    if not bool(np.all(ok_rows & ok_cols)):
        raise ValueError("a town lies outside the radar grid")
    values = msg.values                       # the whole grid; only the town cells are kept
    # A masked cell (pygrib's mask) is no radar value, whatever number lies under the mask.
    picked = np.ma.filled(np.ma.asarray(values[rows, cols], dtype=np.float64), np.nan)
    del values
    return _no_data_to_nan(picked)


# ---------------------------------------------------------------- one town's column

def column(dbz: dict, ground_m: float | None) -> dict:
    """The numbers behind one town's text. dbz: {height_m: dBZ, NaN = no radar value}. Heights below ground_m
    are counted and not used; with no ground height the echo fields stay None. top_nodata lists the heights
    above the echo top that had no radar value: while it is not empty, the top is a lower bound."""
    have = {h: bool(np.isfinite(dbz[h])) for h in HEIGHTS_M}
    out = {"valid": sum(have.values()), "nodata_all": len(HEIGHTS_M) - sum(have.values()),
           "below": None, "above": None, "data": None, "nodata": None, "hits": None,
           "top": None, "top_nodata": None, "peak_dbz": None, "peak_m": None}
    if ground_m is None:
        return out
    above = [h for h in HEIGHTS_M if h >= ground_m]
    data = [h for h in above if have[h]]
    hits = [h for h in data if dbz[h] >= ECHO_DBZ - ECHO_EPS]
    top = max(hits) if hits else None
    out.update(below=len(HEIGHTS_M) - len(above), above=len(above), data=len(data),
               nodata=len(above) - len(data), hits=len(hits), top=top,
               top_nodata=None if top is None else [h for h in above if h > top and not have[h]])
    if data:
        peak = max(data, key=lambda h: (dbz[h], h))
        out.update(peak_dbz=round(float(dbz[peak]), 1), peak_m=peak)
    return out


def _plural(n: int, one: str, many: str) -> str:
    """The count with its noun: '1 height', '8 heights'."""
    return f"{n} {one if n == 1 else many}"


def _notes(col: dict, nodata: bool = True) -> str:
    """The brackets after a town's words: heights with no radar value (if nodata), then heights below ground."""
    parts = []
    if nodata and col["nodata"]:
        parts.append(f"{_plural(col['nodata'], 'height', 'heights')} with no radar value")
    if col["below"]:
        parts.append(f"{_plural(col['below'], 'height', 'heights')} below ground, not used")
    return f" ({'; '.join(parts)})" if parts else ""


def _describe(col: dict, when: datetime, age_min: int, stale: bool, sample: bool) -> str:
    """The words for a town with a radar time: the echo top, or the named reason there is none."""
    clock = _clock(when)
    if col["above"] == 0:
        body = (f"All {len(HEIGHTS_M)} sampled heights are below ground here, so no echo top is stated "
                f"(radar estimate, valid {clock}).")
    elif col["data"] == 0:
        body = (f"No radar value (radar estimate; codes -99 or -999, meaning not verified) at any of the "
                f"{_plural(col['above'], 'height', 'heights')} above ground, valid {clock}"
                f"{_notes(col, nodata=False)}.")
    elif col["hits"] == 0:
        if col["nodata"] == 0:
            head = f"All {_plural(col['above'], 'height', 'heights')} above ground had radar data"
        else:
            head = f"Only {col['data']} of the {col['above']} heights above ground had radar data"
        body = (f"No echo at or above {ECHO_DBZ:g} dBZ (radar estimate), valid {clock}. {head}, and none "
                f"reached {ECHO_DBZ:g} dBZ{_notes(col)}.")
    else:
        lower = bool(col["top_nodata"])
        head = (f"Echo top (radar estimate): {'at least ' if lower else ''}{col['top']:,} m above sea level, "
                f"valid {clock}.")
        if lower:
            head += (f" The top may be higher: {_plural(len(col['top_nodata']), 'height', 'heights')} above it "
                     f"had no radar value.")
        body = (f"{head} dBZ {ECHO_DBZ:g} or more at {col['hits']} of the {col['data']} "
                f"{'height' if col['data'] == 1 else 'heights'} above ground with radar data{_notes(col)}.")
    if stale:
        body += f" The radar is {age_min} min old, past the {STALE_MIN}-minute limit."
    body += " This is not an all-clear."
    return ("SAMPLE, invented values. " if sample else "") + body


def _storm(town: dict, now: datetime, status: str, text: str, sample: bool, **fields) -> dict:
    """One town's storm record, in the shape data/map.json carries (the same keys every time)."""
    base = {"status": status, "text": text, "reason": None, "echo_top_m": None, "echo_top_at_least": None,
            "max_dbz": None,
            "max_dbz_m": None, "valid_time_utc": None, "retrieved_utc": src._iso(now),
            "valid_levels": None, "no_data_levels": None, "below_ground_levels": None,
            "ground_m": None if town.get("ground_m") is None else round(float(town["ground_m"]), 1),
            "levels": None, "source": SAMPLE_SOURCE if sample else SOURCE}
    base.update(fields)
    return base


GROUND_MISSING = ("this town's ground height didn't load in this update, so levels below ground "
                  "can't be left out")


def _problem(town: dict, now: datetime, reason: str, sample: bool, **fields) -> dict:
    """A town whose echo top can't be stated: the feed failed, or its ground height is missing."""
    return _storm(town, now, "problem",
                  f"Echo top not available: {reason}. This is not an all-clear.", sample, reason=reason, **fields)


def _levels(dbz: dict, ground_m: float | None) -> list[dict]:
    """Each height's dBZ (None = no radar value) and whether it is below the town's ground height."""
    return [{"height_m": h, "dbz": None if np.isnan(dbz[h]) else round(dbz[h], 1),
             "below_ground": None if ground_m is None else h < ground_m} for h in HEIGHTS_M]


def _results(now: datetime, towns: list[dict], when: datetime, values: dict, sample: bool) -> tuple[dict, dict]:
    """Every town's record from the 11 heights' dBZ (values[slug]: one NaN-or-dBZ per height, in order)."""
    age = now.astimezone(UTC) - when
    stale = age > STALE
    age_min = int(age.total_seconds() // 60)
    out, hit_towns, nodata_towns = {}, 0, 0
    for t in towns:
        dbz = dict(zip(HEIGHTS_M, (float(v) for v in values[t["slug"]])))
        ground = None if t.get("ground_m") is None else float(t["ground_m"])
        col = column(dbz, ground)
        if ground is None:              # the values are known; the echo top needs the ground height
            out[t["slug"]] = _problem(t, now, GROUND_MISSING, sample, valid_time_utc=src._iso(when),
                                      valid_levels=col["valid"], no_data_levels=col["nodata_all"],
                                      levels=_levels(dbz, None))
            continue
        if col["top"] is not None:
            hit_towns += 1
        if col["above"] and col["data"] == 0:
            nodata_towns += 1
        out[t["slug"]] = _storm(
            t, now, "stale" if stale else "loaded", _describe(col, when, age_min, stale, sample), sample,
            echo_top_m=col["top"], echo_top_at_least=None if col["top"] is None else bool(col["top_nodata"]),
            max_dbz=col["peak_dbz"], max_dbz_m=col["peak_m"],
            valid_time_utc=src._iso(when), valid_levels=col["valid"], no_data_levels=col["nodata_all"],
            below_ground_levels=col["below"], levels=_levels(dbz, ground))
    n = len(towns)
    no_ground = sum(1 for t in towns if t.get("ground_m") is None)
    detail = (f"{'SAMPLE, invented values; ' if sample else ''}11 heights, valid {_clock(when)}; "
              f"echo top at {hit_towns} of {n} towns, no radar value above ground at {nodata_towns} of {n} towns")
    if no_ground:
        detail += f"; ground height missing at {no_ground} of {n} towns"
    if stale:
        detail = f"radar is {age_min} min old; " + detail
    return out, {"ok": not stale, "detail": detail}


# ---------------------------------------------------------------- live and sample inputs

def live(get, now: datetime, towns: list[dict]) -> tuple[datetime, dict, int, float]:
    """-> (valid time, {slug: 11 dBZ values}, bytes downloaded, decode seconds). Raises ValueError with
    plain words; any failed height drops the whole set (the same rule as the radar frames)."""
    files, listed = list_levels(get, now)
    found = common_step(files)
    if found is None:
        raise ValueError(f"no time in the last {int(WINDOW.total_seconds() // 60)} minutes had all "
                         f"{len(LEVEL_NAMES)} heights")
    when, picks = found
    lats = np.array([t["lat"] for t in towns], dtype=float)
    lons = np.array([t["lon"] for t in towns], dtype=float)
    columns, downloaded, decode_s = {}, listed, 0.0
    for level in LEVEL_NAMES:
        t_file, key = picks[level]
        try:
            data, err = get(gridded.MRMS + key)
        except Exception as e:  # noqa: BLE001 - never raise to the build
            data, err = None, gridded._problem(e)
        if err:
            raise ValueError(f"the radar file for {_km(level)} at {_clock(t_file)} didn't load: {err}")
        downloaded += len(data or b"")
        started = time.perf_counter()
        try:
            columns[level] = decode_level(data, level, t_file, lats, lons)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"the radar file for {_km(level)} at {_clock(t_file)} couldn't be read: "
                             f"{gridded._problem(e)}") from None
        decode_s += time.perf_counter() - started
    values = {t["slug"]: [columns[level][i] for level in LEVEL_NAMES] for i, t in enumerate(towns)}
    return when, values, downloaded, decode_s


def collect(get, now: datetime, towns: list[dict], sample: bool = False) -> tuple[dict, dict]:
    """-> ({slug: the town's storm record}, status {"ok": bool, "detail": str}). Never raises."""
    now = (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(UTC)
    try:
        if sample:
            from .sample import storm_levels
            when, values = storm_levels(now, towns)
        else:
            when, values, _downloaded, _seconds = live(get, now, towns)
    except Exception as e:  # noqa: BLE001 - a failed feed is a status, never a crash
        reason = gridded._problem(e)
        results = {t["slug"]: _problem(t, now, reason, sample) for t in towns}
        return results, {"ok": False, "detail": reason}
    return _results(now, towns, when, values, sample)
