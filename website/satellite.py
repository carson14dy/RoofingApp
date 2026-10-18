"""The GOES satellite picture for the map page (P2 of the storm layers; research/globe README §3, §6).

NOAA's GOES-East (GOES-19) and GOES-West (GOES-18) imagers scan the CONUS every 5 minutes in band 13
(10.3 µm, the "clean" infrared). Each file holds the brightness temperature in kelvin on a 2 km grid.
This module takes the newest scan and draws it as one palette PNG on the map's image box
(gridded.IMAGE_BOUNDS), so the browser places it like the radar and model pictures.

An OBSERVATION of infrared brightness temperature. It is not a cloud height and not a hail signal, and
it is never blended with the radar estimate or the model forecast. An uncorrected cloud top is drawn
away from the satellite (north-west for GOES-East, north-east for GOES-West). Pixels with no good value
are hatched as "no satellite data", never drawn as clear sky.

    layer, status = build_satellite(site_dir, get, now)              # live: NOAA buckets on S3
    layer, status = build_satellite(site_dir, get, now, sample=True)  # invented field, no network

`get(url, headers=None) -> (bytes | None, error | None)` is injected (the build's Fetcher; tests pass
fakes). GOES-East is tried first. GOES-West is tried when East's listing, download or decode fails, or
when East has no scan in the last hour. Nothing here raises to the caller, and error texts are plain
words because the map shows them.
h5py is imported only where a NetCDF file is read, so the tests and sample builds run without it.
Feed details: sources.CONTRACTS "satellite".
"""
from __future__ import annotations

import html
import io
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

import numpy as np

from . import gridded
from . import sources as src

UTC = timezone.utc
MT = gridded.MT

LABEL = "GOES satellite picture"          # the build's status label
LAYER = "satellite"                       # the layer key in data/map.json
WIDTH = 700                               # px across the picture (gridded.WIDTHS holds the radar and model only)
STALE = timedelta(seconds=1200)           # older than this: the picture is drawn, and the status says so
UNAVAILABLE = timedelta(seconds=3600)     # older than this (or no file): no picture
LAYER_TEXT = {"title": "Satellite", "unit": "K",
              "legend_note": "Satellite infrared brightness temperature, K. An observation. "
                             "Not a height and not a hail signal."}
SAMPLE_NOTE = "Sample: invented picture, not NOAA GOES."   # a sample build's legend note
NO_SCAN = "no satellite scan in the last 60 minutes"
LIVE_SOURCE = "NOAA {name} band 13, observation"
SAMPLE_SOURCE = "SAMPLE — invented satellite picture, not NOAA data"
SAMPLE_STATUS = "SAMPLE — invented picture, scan ended {when}"

PREFIX = "ABI-L2-CMIPC"                   # CONUS band 13 products, one file per 5-minute scan
GRID = (1500, 2500)                       # (rows, columns) of the CONUS grid
LON_TOLERANCE = 0.5                       # degrees; the projection origin as the file carries it
SCAN_KEY = re.compile(r"OR_ABI-L2-CMIPC-M6C13_(G1[89])_s(\d{14})_e(\d{14})_c(\d{14})\.nc$")
ISO_UTC = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(?:Z|\+00:00)$")   # the files' scan times


class Sat(NamedTuple):
    key: str          # "east" or "west"
    bucket: str       # the public S3 bucket
    platform: str     # the platform id in the file name and in the file's platform_ID
    name: str         # the name in words
    parallax: str     # the direction an uncorrected cloud top is drawn from its true place

    @property
    def short(self) -> str:
        return self.name.split(" (")[0]   # "GOES-East"


SATELLITES = (     # in try order: GOES-East first, GOES-West when East fails or has no scan in the last hour
    Sat("east", "noaa-goes19", "G19", "GOES-East (GOES-19)", "north-west"),
    Sat("west", "noaa-goes18", "G18", "GOES-West (GOES-18)", "north-east"),
)
ORIGIN_LON = {"G19": -75.0, "G18": -137.0}   # longitude_of_projection_origin, as the files carry it

# Invented sample field (K): a warm background cooled by terrain, one cold top, one mid-cloud band,
# and a corner with no data so the hatching is shown.
SAMPLE_BACKGROUND_K = 286.0
SAMPLE_LAPSE_K_PER_KM = 6.0
SAMPLE_TOP = (45.7, -110.6, 210.0, 50.0)     # lat, lon, core K, spread in km (about 120 km across)
SAMPLE_BAND = (49.0, 250.0)                  # latitude of the band, K
SAMPLE_NODATA_FROM = (49.2, -103.8)          # north-east corner: from this latitude and longitude on


# ---------------------------------------------------------------- geometry (GOES fixed grid)
# Copied from research/globe/prototype/goes_cloud_height.py (Geos and latlon_to_scan), which agrees with
# PROJ's geos projection to 1e-9 degrees. tests/test_satellite.py checks it against reference points.

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


def latlon_to_scan(lat, lon, g: Geos):
    """Geodetic latitude and longitude (degrees) to fixed-grid scan angles (radians).

    Returns (x, y, visible). visible is False where the point is over the horizon of the satellite.
    lat and lon broadcast, so a column of latitudes and a row of longitudes give a grid.
    """
    if g.sweep != "x":
        raise ValueError("the file's projection sweep isn't x")
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


# ---------------------------------------------------------------- times and words

def _stamp(text: str) -> datetime:
    """A file-name time, YYYYDDDHHMMSSt (day of year, then tenths of a second): 20262901556175 is
    15:56:17.5 UTC on 2026-10-17."""
    return datetime.strptime(text[:13], "%Y%j%H%M%S").replace(tzinfo=UTC) + timedelta(milliseconds=100 * int(text[13]))


def _iso_utc(text: str) -> datetime:
    """A file's scan time, ISO UTC with any number of fraction digits or none: 2026-10-17T15:58:55.9Z. Read by
    hand because datetime.fromisoformat takes only 3 or 6 fraction digits before Python 3.11, and the README
    asks for Python 3.10."""
    m = ISO_UTC.match(str(text).strip())
    if not m:
        raise ValueError("the file's scan times were not readable")
    whole = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    return whole + timedelta(microseconds=int(((m.group(2) or "") + "000000")[:6]))


def _iso_seconds(dt: datetime) -> str:
    """ISO UTC to the second, as the frame and the contract carry times: 2026-10-17T15:58:55Z."""
    return src._iso(dt.replace(microsecond=0))


def _clock(dt: datetime) -> str:
    """Montana clock time with its zone, as the scan end is written: '9:58 am MDT'."""
    return f"{gridded._hm(dt)} {dt.astimezone(MT).tzname()}"


def _sat_named(platform: str | None) -> str:
    """A platform id in words: 'GOES-West' for G18; the id itself when it is not one of ours."""
    return next((s.short for s in SATELLITES if s.platform == platform), platform or "an unknown satellite")


def _first_up(text: str) -> str:
    return text[:1].upper() + text[1:]


# ---------------------------------------------------------------- finding the newest scan

def parse_listing(data, sat: Sat) -> list[tuple[datetime, str]]:
    """S3 ListObjectsV2 XML -> [(scan end UTC, key)] of one satellite's band 13 files, oldest first. The
    scan end is read from the file name (the "_e" time)."""
    text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data or "")
    if "<ListBucketResult" not in text:
        raise ValueError("the list was not readable")
    found = []
    for key in re.findall(r"<Key>([^<]+)</Key>", text):
        key = html.unescape(key)
        m = SCAN_KEY.search(key)
        if m and m.group(1) == sat.platform:
            found.append((_stamp(m.group(3)), key))
    return sorted(found)


def list_scans(get, now: datetime, sat: Sat) -> list[tuple[datetime, str]]:
    """The band 13 scans of one satellite in the current and the previous UTC hour, as [(scan end UTC,
    key)] newest first. The two hours cover a scan that starts a new hour. Raises ValueError (plain
    words) when a listing doesn't load or can't be read."""
    now = now.astimezone(UTC)
    found = {}
    for hour in (now, now - timedelta(hours=1)):
        prefix = f"{PREFIX}/{hour:%Y}/{hour:%j}/{hour:%H}/OR_ABI-L2-CMIPC-M6C13_{sat.platform}_"
        url = f"https://{sat.bucket}.s3.amazonaws.com/?list-type=2&prefix={quote(prefix)}"
        try:
            data, err = get(url)
        except Exception as e:  # noqa: BLE001 - a failed request is a reason, not a crash
            data, err = None, gridded._problem(e)
        if err:
            raise ValueError(f"{sat.short} file list didn't load ({err})")
        try:
            items = parse_listing(data, sat)
        except ValueError as e:
            raise ValueError(f"{sat.short} file list didn't load ({e})") from None
        for end, key in items:
            found[key] = end
    return sorted(((end, key) for key, end in found.items()), reverse=True)


# ---------------------------------------------------------------- reading a file

def _plain(value):
    """An HDF5 attribute as a Python value: bytes decoded, a one-element array a scalar."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    arr = np.asarray(value)
    if arr.dtype.kind in "SO":
        return _plain(arr.reshape(-1)[0]) if arr.size else None
    return arr.reshape(-1)[0].item() if arr.size == 1 else arr.tolist()


def _number(obj, name: str) -> float:
    """A numeric attribute, or a plain-words error: a file with no scale is never drawn."""
    if name not in obj.attrs:
        raise ValueError(f"the file had no {name} for its values")
    value = _plain(obj.attrs[name])
    if not isinstance(value, (int, float)):
        raise ValueError(f"the file's {name} was not a number")
    return float(value)


def read_cmip(data: bytes, expect_platform: str) -> dict:
    """One band 13 CONUS NetCDF file -> the arrays and the geometry that sample_field needs. Raises
    ValueError with plain words when the file is not the band 13 file of expect_platform, so a wrong
    file is named, never drawn.

    Values are read as stored (int16). The files carry _Unsigned = "true": read as unsigned, a negative
    stored value is a large number far outside valid_range; read as signed, it is below valid_range. Either
    way it is no data, and the fill value (-1) is one of them.
    """
    import h5py   # only the live build reads NetCDF files
    try:
        f = h5py.File(io.BytesIO(data), "r")
    except Exception:  # noqa: BLE001 - whatever the reader says, the download is not a NetCDF-4 file
        raise ValueError("the download was not a NetCDF-4 satellite file") from None
    with f:
        return _read_open(f, expect_platform)


def _read_open(f, expect: str) -> dict:
    platform = _plain(f.attrs["platform_ID"]) if "platform_ID" in f.attrs else None
    if platform != expect:
        raise ValueError(f"the file is from {_sat_named(platform)}, not {_sat_named(expect)}")
    if "band_id" not in f:
        raise ValueError("the file has no band number")
    band = int(np.asarray(f["band_id"][...]).reshape(-1)[0])
    if band != 13:
        raise ValueError(f"the file is band {band}, not band 13")
    for name in ("CMI", "DQF", "x", "y", "goes_imager_projection"):
        if name not in f:
            raise ValueError(f"the file has no {name}")
    cmi = f["CMI"]
    if tuple(cmi.shape) != GRID:
        raise ValueError("the file has an unexpected grid size")
    units = _plain(cmi.attrs["units"]) if "units" in cmi.attrs else None
    if units != "K":
        raise ValueError("the file's values are not in kelvin")
    scale, offset = _number(cmi, "scale_factor"), _number(cmi, "add_offset")
    fill = int(_number(cmi, "_FillValue"))
    if "valid_range" not in cmi.attrs:
        raise ValueError("the file had no valid_range for its values")
    vr = np.asarray(cmi.attrs["valid_range"]).reshape(-1)
    if vr.size != 2:
        raise ValueError("the file's valid_range was not a pair of values")
    if tuple(f["DQF"].shape) != GRID:
        raise ValueError("the file's quality flags have an unexpected grid size")
    xv, yv = f["x"], f["y"]
    if tuple(xv.shape) != (GRID[1],) or tuple(yv.shape) != (GRID[0],):
        raise ValueError("the file's grid coordinates have an unexpected size")
    xr, yr = np.asarray(xv[...]).astype(np.int64), np.asarray(yv[...]).astype(np.int64)
    if not (np.all(np.diff(xr) == 1) and np.all(np.diff(yr) == 1)):
        raise ValueError("the file's grid coordinates are not evenly spaced")
    xs, xo = _number(xv, "scale_factor"), _number(xv, "add_offset")
    ys, yo = _number(yv, "scale_factor"), _number(yv, "add_offset")
    p = f["goes_imager_projection"].attrs
    needed = ("perspective_point_height", "semi_major_axis", "semi_minor_axis", "longitude_of_projection_origin")
    if any(k not in p for k in needed) or "sweep_angle_axis" not in p:
        raise ValueError("the file had no projection details")
    geos = Geos(lon0_deg=float(_plain(p["longitude_of_projection_origin"])),
                height_m=float(_plain(p["perspective_point_height"])),
                req_m=float(_plain(p["semi_major_axis"])), rpol_m=float(_plain(p["semi_minor_axis"])),
                sweep=str(_plain(p["sweep_angle_axis"])).strip().lower())
    if geos.sweep != "x":
        raise ValueError("the file's projection sweep isn't x")
    if abs(geos.lon0_deg - ORIGIN_LON[platform]) > LON_TOLERANCE:
        raise ValueError(f"the file's projection is centred at {geos.lon0_deg:g}, not {ORIGIN_LON[platform]:g}")
    times = []
    for name in ("time_coverage_start", "time_coverage_end"):
        text = _plain(f.attrs[name]) if name in f.attrs else None
        if not text:
            raise ValueError("the file had no scan times")
        times.append(_iso_utc(text))
    return {
        "raw": np.asarray(cmi[...]), "dqf": np.asarray(f["DQF"][...]),
        "scale": scale, "offset": offset, "fill": fill, "valid_range": (int(vr[0]), int(vr[1])),
        "x0": float(xr[0]) * xs + xo, "dx": xs, "y0": float(yr[0]) * ys + yo, "dy": ys,
        "nx": GRID[1], "ny": GRID[0], "Geos": geos,
        "scan_start": times[0], "scan_end": times[1], "platform": platform,
    }


# ---------------------------------------------------------------- the picture grid

def sample_field(cmi: dict, lats, lons) -> np.ndarray:
    """Band 13 kelvin at each latitude (rows) and longitude (columns): the nearest native pixel, no
    interpolation. NaN where the point is over the satellite's horizon or outside its grid, where the
    pixel holds fill or a raw value outside the file's valid range, and where its quality flag is not 0.
    Only DQF 0 is drawn."""
    la = np.asarray(lats, dtype=float)[:, None]
    lo = np.asarray(lons, dtype=float)[None, :]
    x, y, visible = latlon_to_scan(la, lo, cmi["Geos"])
    col = np.rint((x - cmi["x0"]) / cmi["dx"])
    row = np.rint((y - cmi["y0"]) / cmi["dy"])
    finite = np.isfinite(col) & np.isfinite(row)
    col = np.where(finite, col, -1.0)
    row = np.where(finite, row, -1.0)
    inside = visible & finite & (col >= 0) & (col < cmi["nx"]) & (row >= 0) & (row < cmi["ny"])
    r = np.clip(row, 0, cmi["ny"] - 1).astype(np.intp)
    c = np.clip(col, 0, cmi["nx"] - 1).astype(np.intp)
    raw = np.asarray(cmi["raw"])[r, c].astype(np.int64)
    dqf = np.asarray(cmi["dqf"])[r, c]
    lo_v, hi_v = cmi["valid_range"]
    good = inside & (raw != cmi["fill"]) & (raw >= lo_v) & (raw <= hi_v) & (dqf == 0)
    kelvin = raw * cmi["scale"] + cmi["offset"]
    return np.where(good, kelvin, np.nan).astype(np.float32)


def sample_frame(now: datetime, lats, lons) -> tuple[np.ndarray, datetime]:
    """Invented band 13 kelvin on the picture grid (lats: rows, lons: columns) and the scan end the sample
    pretends to show: the scan before the newest one at `now`. No h5py, no network."""
    scan_end = gridded.floor_time(now, 5) - timedelta(minutes=2)
    la1, lo1 = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
    la, lo = la1[:, None], lo1[None, :]
    # sample_elevation is in thousands of feet; x 0.3048 gives kilometres for the lapse rate
    base = SAMPLE_BACKGROUND_K - SAMPLE_LAPSE_K_PER_KM * gridded.sample_elevation(la1, lo1) * 0.3048
    top_lat, top_lon, top_k, spread_km = SAMPLE_TOP
    dy_km = (la - top_lat) * 111.0
    dx_km = (lo - top_lon) * 111.0 * math.cos(math.radians(top_lat))
    top = np.exp(-0.5 * (dx_km ** 2 + dy_km ** 2) / spread_km ** 2)
    field = base + (top_k - base) * top
    band = np.exp(-0.5 * ((la - SAMPLE_BAND[0]) / 0.25) ** 2)
    field = field + (SAMPLE_BAND[1] - field) * 0.7 * band
    field = field + 2.0 * (gridded._noise(la1, lo1, 0.5, 41) - 0.5)
    notch = (la >= SAMPLE_NODATA_FROM[0]) & (lo >= SAMPLE_NODATA_FROM[1])
    return np.where(notch, np.nan, field).astype(np.float32), scan_end


# ---------------------------------------------------------------- frames, layer and status

def _frame(png: bytes, nodata: bool, field: np.ndarray, *, satellite: str, tag: str, source: str,
           scan_start: datetime, scan_end: datetime) -> dict:
    """One picture in the shape data/map.json carries (plus _png, which is written and then dropped)."""
    finite = field[np.isfinite(field)]
    return {"time": _iso_seconds(scan_end), "kind": "satellite",
            "src": f"{gridded.FRAME_DIR}/satellite-{scan_end:%Y%m%d%H%M}-{tag}.png",
            "source": source, "satellite": satellite,
            "scan_start": _iso_seconds(scan_start), "scan_end": _iso_seconds(scan_end),
            "nodata": nodata, "coldest_k": int(round(float(finite.min()))),
            "warmest_k": int(round(float(finite.max()))), "_png": png}


def _layer(frames: list[dict], sample: bool) -> dict:
    """The layer dict as gridded.assemble makes one (without the PNG bytes)."""
    entries, gradient = gridded.legend(LAYER)
    text = {**LAYER_TEXT, "legend_note": SAMPLE_NOTE} if sample else LAYER_TEXT
    return {**text, "legend": entries, "gradient": gradient,
            "frames": [{k: v for k, v in f.items() if k != "_png"} for f in frames],
            "modes": {"12h": list(range(len(frames)))}, "now_index": {"12h": 0}}


class _NoScan(ValueError):
    """One satellite has no scan in the last hour: none is listed, or the newest is older than UNAVAILABLE. The
    message is the reason in plain words, and it names the satellite."""


def _newest(get, now: datetime, sat: Sat, lats, lons) -> tuple[dict, timedelta]:
    """The newest scan of one satellite, drawn -> (frame, age of the scan). Raises _NoScan when no scan is
    within the last hour, and ValueError with plain words when the listing, the download or the decode fails."""
    scans = list_scans(get, now, sat)
    if not scans:
        raise _NoScan(f"{sat.short} has no scan in the last 60 minutes")
    listed_end, key = scans[0]
    if now - listed_end > UNAVAILABLE:
        raise _NoScan(f"{sat.short}'s newest scan ended {gridded._hm(listed_end)}, more than 60 minutes ago")
    try:
        data, err = get(f"https://{sat.bucket}.s3.amazonaws.com/{key}")
    except Exception as e:  # noqa: BLE001
        data, err = None, gridded._problem(e)
    if err:
        raise ValueError(f"{sat.short} file for {gridded._hm(listed_end)} didn't load ({err})")
    try:
        cmi = read_cmip(data, sat.platform)
        if abs(cmi["scan_end"] - listed_end) > timedelta(seconds=1):
            raise ValueError("the file's own time didn't match its name")
        field = sample_field(cmi, lats, lons)
        if not np.isfinite(field).any():
            raise ValueError("the file had no usable values over the map")
        png, nodata = gridded.render(field, LAYER)
    except Exception as e:  # noqa: BLE001 - a file that doesn't decode is named, never drawn
        raise ValueError(f"{sat.short} file for {gridded._hm(listed_end)} couldn't be read "
                         f"({gridded._problem(e)})") from None
    frame = _frame(png, nodata, field, satellite=sat.platform, tag=sat.platform.lower(),
                   source=LIVE_SOURCE.format(name=sat.name), scan_start=cmi["scan_start"],
                   scan_end=cmi["scan_end"])
    return frame, now - cmi["scan_end"]


def _live(get, now: datetime, lats, lons) -> tuple[list[dict], dict]:
    """GOES-East first. GOES-West is tried when East's listing, download or decode fails, or when East has no
    scan in the last hour. A picture from GOES-West after an East failure is ok by freshness alone, as East's
    is, and its status names the East reason: 'scan ended 9:58 am (GOES-West; GOES-East file list didn't load
    (HTTP 503))'. With no picture, the status names each satellite's reason, or says that no satellite has a
    scan in the last 60 minutes."""
    reasons, no_scan = [], []
    for sat in SATELLITES:
        try:
            frame, age = _newest(get, now, sat, lats, lons)
        except _NoScan as e:
            reasons.append(str(e))
            no_scan.append(True)
            continue
        except Exception as e:  # noqa: BLE001 - the reason is kept, and the next satellite is tried
            reasons.append(gridded._problem(e))
            no_scan.append(False)
            continue
        stale = age > STALE
        picture = f"scan ended {gridded._hm(_frame_end(frame))} ({sat.short}" + "".join(f"; {r}" for r in reasons) + ")"
        if stale:
            picture = f"satellite picture is {int(age.total_seconds() // 60)} min old; {picture}"
        return [frame], {"label": LABEL, "ok": not stale, "detail": picture}
    detail = NO_SCAN if all(no_scan) else "; ".join(reasons)
    return [], {"label": LABEL, "ok": False, "detail": detail}


def _frame_end(frame: dict) -> datetime:
    """A frame's scan end as a datetime (the frame carries it to the second)."""
    return datetime.fromisoformat(frame["scan_end"].replace("Z", "+00:00"))


def _build(out_dir: Path, get, now: datetime, sample: bool) -> tuple[dict, dict]:
    lats, lons = gridded.pixel_centers(WIDTH)
    if sample:
        field, scan_end = sample_frame(now, lats, lons)
        png, nodata = gridded.render(field, LAYER)
        frames = [_frame(png, nodata, field, satellite="SAMPLE", tag="sample", source=SAMPLE_SOURCE,
                         scan_start=scan_end - timedelta(seconds=158), scan_end=scan_end)]
        status = {"label": LABEL, "ok": True, "detail": SAMPLE_STATUS.format(when=gridded._hm(scan_end))}
    else:
        frames, status = _live(get, now, lats, lons)
    try:
        gridded._write(out_dir, frames)
    except Exception as e:  # noqa: BLE001
        frames = []
        status = {"label": LABEL, "ok": False,
                  "detail": f"the satellite picture couldn't be saved ({gridded._problem(e)})"}
    return _layer(frames, sample), status


def build_satellite(out_dir: Path, get, now: datetime, sample: bool = False) -> tuple[dict, dict]:
    """Draw the newest satellite picture into out_dir/map/frames/ (out_dir is the site root) and return
    (layer for data/map.json, status {"label", "ok", "detail"}). With no picture the layer has frames []
    and the status says why. Never raises."""
    now = (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(UTC)
    try:
        return _build(Path(out_dir), get, now, sample)
    except Exception as e:  # noqa: BLE001 - last resort: never raise to the build
        return _layer([], sample), {"label": LABEL, "ok": False,
                                    "detail": f"the satellite picture couldn't be drawn ({gridded._problem(e)})"}


def describe(layer: dict, status: dict, now: datetime) -> str:
    """One plain-words paragraph about the picture, for the noscript panel, the List sheet and the build log."""
    detail = status.get("detail", "")
    sample = detail.startswith("SAMPLE")
    prefix = "SAMPLE, invented picture. " if sample else ""
    frames = layer.get("frames") or []
    if not frames:
        return f"{prefix}Satellite picture: {detail}. This is not an all-clear."
    f = frames[0]
    scan_end = datetime.fromisoformat(f["scan_end"].replace("Z", "+00:00"))
    sat = next((s for s in SATELLITES if s.platform == f.get("satellite")), None)
    if sample:
        origin, direction = "invented (not NOAA data)", SATELLITES[0].parallax
    else:
        origin = f"NOAA {sat.name} band 13" if sat else "NOAA satellite band 13"
        direction = sat.parallax if sat else SATELLITES[0].parallax
    text = (f"{prefix}Satellite picture: {origin}, scan ended {_clock(scan_end)}, retrieved {gridded._hm(now)}. "
            f"Coldest brightness temperature in the picture {f.get('coldest_k')} K, warmest {f.get('warmest_k')} K. "
            "An observation of infrared brightness temperature: not a height and not a hail signal. "
            f"A cloud top 2 km up is drawn about 3 to 4 km {direction} of its true place, and a top 12 to 15 km up "
            "about 20 to 33 km (parallax). "
            "Areas warmer than 300 K are left uncoloured, and missing areas show hatch lines; "
            "uncoloured is not a statement about the weather.")
    if f.get("nodata"):
        text += " Hatched areas have no satellite data."
    if not status.get("ok", False):
        text += f" {_first_up(detail)}. This is not an all-clear."
    else:
        note = _after_failure(detail, sat) if sat else None
        if note:                                  # a GOES-West picture after a GOES-East failure says why
            text += f" {_first_up(note)}."
    return text


def _after_failure(detail: str, sat: Sat) -> str | None:
    """The reason the other satellite was passed over, from a status like 'scan ended 9:58 am (GOES-West;
    GOES-East file list didn't load (HTTP 503))'; None when nothing was passed over."""
    m = re.search(rf"\({re.escape(sat.short)}; (.+)\)$", detail)
    return m.group(1) if m else None
