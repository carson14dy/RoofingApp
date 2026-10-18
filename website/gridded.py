"""Radar and model pictures for the map page (map.html, data/map.json).

Past hour: NOAA MRMS precipitation rate, a RADAR ESTIMATE, one frame every 10 minutes.
Next 12 hours: the NOAA HRRR model, a MODEL FORECAST: precipitation rate, 2 m temperature, gusts.

Python draws every frame into a small palette PNG on one shared Web-Mercator grid (IMAGE_BOUNDS),
so the browser only places finished pictures with L.imageOverlay and flips between them.

    layers, status = build_gridded(site_dir, get, now)            # live: NOAA buckets on S3
    layers, status = build_gridded(site_dir, get, now, sample=True)  # invented fields, no network

`get(url, headers=None) -> (bytes | None, error | None)` is injected (the build passes its
Fetcher; tests pass fakes). Nothing here raises to the caller, and error texts are plain words
because the map shows them. pygrib is imported only where a GRIB file is decoded, so the tests
and sample builds run without it. Feed details: sources.CONTRACTS "radar" and "forecast_model".
"""
from __future__ import annotations

import gzip
import html
import io
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np

from . import sources as src

UTC = timezone.utc
MT = ZoneInfo("America/Denver")

# ---------------------------------------------------------------- map geometry

IMAGE_BOUNDS = ((43.0, -118.5), (50.5, -101.0))    # ((south, west), (north, east)), every frame
WIDTHS = {"precip": 1400, "temp": 700, "wind": 700}  # px; heights follow from the Mercator aspect
FRAME_DIR = "map/frames"                             # under the site root; frame "src" starts here

# ---------------------------------------------------------------- sources and frame selection

MRMS = "https://noaa-mrms-pds.s3.amazonaws.com/"
MRMS_PREFIX = "CONUS/PrecipRate_00.00/"
MRMS_KEY = re.compile(r"MRMS_PrecipRate_00\.00_(\d{8})-(\d{6})\.grib2\.gz$")
MRMS_PARAM = (209, 6, 1)        # GRIB discipline, category, number of MRMS PrecipRate (mm/h)
HRRR = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/"

RADAR_FRAMES = 7                          # newest file and every 10 minutes back to an hour
RADAR_STEP = timedelta(minutes=10)
RADAR_TOLERANCE = timedelta(minutes=4)    # a target without a file this close is skipped
RADAR_STALE = timedelta(minutes=30)       # newest file older than this: status not ok
LIST_BACK = timedelta(hours=3)            # newest file older than this: no radar frames at all
# The file list reaches back to the oldest frame of a newest file LIST_BACK old, within the tolerance.
LIST_SPAN = LIST_BACK + (RADAR_FRAMES - 1) * RADAR_STEP + RADAR_TOLERANCE
HRRR_RUNS_TRIED = 4                       # newest run hours tried, newest first
FORECAST_HOURS = 12
QUARTER_HOURS = 4

# Layer -> HRRR .idx variable and level, and the GRIB discipline/category/number that the
# downloaded message must carry (a wrong byte range is caught here, not drawn).
HRRR_FIELDS = {"precip": ("PRATE", "surface", (0, 1, 7)),           # kg m-2 s-1
               "temp": ("TMP", "2 m above ground", (0, 0, 0)),      # K
               "wind": ("GUST", "surface", (0, 2, 22))}              # m s-1
CONVERT = {"precip": lambda v: v * 3600.0,                           # -> mm/h
           "temp": lambda v: (v - 273.15) * 1.8 + 32.0,              # -> °F
           "wind": lambda v: v * src.MS_TO_MPH}                      # -> mph

# ---------------------------------------------------------------- colours

# (value, colour, alpha). Precipitation in mm/h on a log scale; the classes are the AMS rainfall
# rates: light < 2.5 mm/h (0.1 in/h), moderate 2.5-7.6, heavy 7.6-50, extreme > 50.
PRECIP_STOPS = ((0.1, "#6fb3ff", 0.45), (1.0, "#3d6ff0", 0.70), (2.5, "#6a4cf2", 0.80),
                (5.0, "#a23ee8", 0.83), (7.6, "#d43fc4", 0.85), (20.0, "#ff4f9a", 0.90),
                (50.0, "#ffd23f", 0.95), (100.0, "#fff6b0", 0.95))
PRECIP_MIN = 0.1                          # mm/h; anything less is drawn transparent
PRECIP_CLASSES = (("Extreme", 50.0), ("Heavy", 7.6), ("Moderate", 2.5), ("Light", 0.1))
MM_PER_INCH = 25.4
TEMP_STOPS = tuple((v, c, 0.55) for v, c in (
    (-20, "#6b3fa0"), (0, "#3b5bdb"), (20, "#4dabf7"), (32, "#66d9e8"), (45, "#69db7c"),
    (60, "#ffe066"), (75, "#ffa94d"), (90, "#ff6b6b"), (105, "#c92a2a")))
WIND_STOPS = ((0, "#d0ebff", 0.0), (10, "#d0ebff", 0.25), (15, "#a5d8ff", 0.40), (20, "#74c0fc", 0.50),
              (25, "#ffd43b", 0.60), (35, "#ff922b", 0.65), (45, "#f03e3e", 0.70), (60, "#ae3ec9", 0.75),
              (75, "#5f3dc4", 0.80))
HATCH = ("#8e8e93", 0.35)                 # stripes over areas without data, transparent between
# Satellite band 13 brightness temperature in K, ascending (the legend needs ascending stops). Cold
# tops are the saturated colours; 300 K and warmer is transparent, so the basemap shows through.
SAT_STOPS = ((195, "#ff6a3d", 0.95), (205, "#c42fa0", 0.90), (215, "#7b3fd6", 0.85),
             (225, "#3b4fc9", 0.80), (240, "#5c6b8a", 0.70), (255, "#8e9299", 0.60), (275, "#c9ccd1", 0.45),
             (290, "#e6e8eb", 0.20), (300, "#e6e8eb", 0.0))

# Layer -> (stops, log scale, colour levels). Palette index 0 is transparent, 1 the hatch, 2.. one
# entry per level. 48 log levels for precipitation (16 % steps; 254 looked the same at half the
# file size on a rainy day), 1 °F steps for temperature (-20..105), 1 mph steps for gusts (0..75),
# 1 K steps for the satellite picture (195..300).
STYLE = {"precip": (PRECIP_STOPS, True, 48), "temp": (TEMP_STOPS, False, 126), "wind": (WIND_STOPS, False, 76),
         "satellite": (SAT_STOPS, False, 106)}
SMOOTH_PX = 1.0                           # Gaussian sigma before colouring: soft edges, smaller files
LAYER_TEXT = {
    "precip": {"title": "Precipitation", "unit": "in/h",
               "legend_note": "Rate as liquid water. Radar estimate up to now, HRRR model forecast after."},
    "temp": {"title": "Temperature", "unit": "°F", "legend_note": "HRRR model."},
    "wind": {"title": "Wind gusts", "unit": "mph",
             "legend_note": f"HRRR model. Roofing limit {src.LIMITS['gust_mph']} mph."},
}
# Sample builds draw invented pictures, so their legend must not name the radar or the model as the source.
SAMPLE_NOTES = {
    "precip": "Rate as liquid water. Sample: invented pictures, not NOAA radar or the HRRR model.",
    "temp": "Sample: invented pictures, not the HRRR model.",
    "wind": f"Sample: invented pictures, not the HRRR model. Roofing limit {src.LIMITS['gust_mph']} mph.",
}
# The satellite picture's width, layer text and sample note live in satellite.py (satellite.WIDTH,
# satellite.LAYER_TEXT, satellite.SAMPLE_NOTE): tests/test_gridded.py pins these three dicts to the
# radar and model layers.
LEGEND_UNIT = {"temp": "°", "wind": " mph", "satellite": " K"}   # the unit after each legend label
RADAR_SOURCE = "NOAA MRMS radar estimate"
MODEL_SOURCE = "NOAA HRRR model"
SAMPLE_RADAR_SOURCE = "SAMPLE — invented radar picture, not NOAA data"
SAMPLE_MODEL_SOURCE = "SAMPLE — invented forecast picture, not the HRRR model"
LABELS = {"radar": "NOAA radar (MRMS)", "forecast": "HRRR forecast"}


# ---------------------------------------------------------------- small helpers

def _hm(dt: datetime) -> str:
    """Montana clock time like the rest of the site: '4:56 pm'."""
    local = dt.astimezone(MT)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'}"


def floor_time(dt: datetime, minutes: int) -> datetime:
    dt = dt.astimezone(UTC).replace(second=0, microsecond=0)
    return dt - timedelta(minutes=(dt.hour * 60 + dt.minute) % minutes)


def frame_src(layer: str, valid: datetime, run: datetime | None = None) -> str:
    """Frame file, relative to the site root: layer and valid time (UTC), and for model frames the
    run hour too ("temp-202610160000-r2026101521.png"). A name must never stand for two different
    pictures: GitHub Pages lets browsers reuse a file for 10 minutes, and each hourly HRRR run
    redraws the same valid times, so without the run a reload could pair cached pictures from the
    old run with the new run's label. A radar frame's MRMS file never changes, so its time is enough."""
    name = f"{layer}-{valid.astimezone(UTC):%Y%m%d%H%M}"
    if run is not None:
        name += f"-r{run.astimezone(UTC):%Y%m%d%H}"
    return f"{FRAME_DIR}/{name}.png"


def _hex(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


# ---------------------------------------------------------------- Web-Mercator image grid

def merc_y(lat):
    """Web-Mercator y (in radians of longitude) of a latitude; numbers or numpy arrays."""
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def image_size(width: int, bounds=IMAGE_BOUNDS) -> tuple[int, int]:
    """(width, height) of a frame: x is linear in longitude, y linear in Mercator y, so
    L.imageOverlay(src, bounds) places every pixel exactly."""
    (s, w), (n, e) = bounds
    return width, int(round(width * float(merc_y(n) - merc_y(s)) / math.radians(e - w)))


def pixel_centers(width: int, bounds=IMAGE_BOUNDS) -> tuple[np.ndarray, np.ndarray]:
    """Latitude of each row centre (row 0 is the NORTH edge) and longitude of each column centre."""
    (s, w), (n, e) = bounds
    wpx, hpx = image_size(width, bounds)
    lons = w + (np.arange(wpx) + 0.5) * (e - w) / wpx
    y = merc_y(n) - (np.arange(hpx) + 0.5) * float(merc_y(n) - merc_y(s)) / hpx
    lats = np.degrees(2 * np.arctan(np.exp(y)) - np.pi / 2)
    return lats, lons


# ---------------------------------------------------------------- MRMS: regular latitude-longitude grid

def mrms_grid(msg) -> dict:
    """The grid as the GRIB message describes it (not trusted constants)."""
    return {"ni": int(msg["Ni"]), "nj": int(msg["Nj"]),
            "lat1": float(msg["latitudeOfFirstGridPointInDegrees"]),
            "lon1": float(msg["longitudeOfFirstGridPointInDegrees"]),
            "di": float(msg["iDirectionIncrementInDegrees"]), "dj": float(msg["jDirectionIncrementInDegrees"]),
            "j_pos": bool(msg["jScansPositively"]), "i_neg": bool(msg["iScansNegatively"])}


def mrms_index(grid: dict, lats, lons):
    """Nearest grid row for each latitude and column for each longitude, plus whether each lies on
    the grid. MRMS scans north to south, so row 0 is its northern edge (54.995 N)."""
    lon1 = (grid["lon1"] + 180.0) % 360.0 - 180.0
    di = -grid["di"] if grid["i_neg"] else grid["di"]
    dj = grid["dj"] if grid["j_pos"] else -grid["dj"]
    dlon = (np.asarray(lons, dtype=float) - lon1 + 180.0) % 360.0 - 180.0
    cols = np.rint(dlon / di).astype(np.int64)
    rows = np.rint((np.asarray(lats, dtype=float) - grid["lat1"]) / dj).astype(np.int64)
    ok_rows = (rows >= 0) & (rows < grid["nj"])
    ok_cols = (cols >= 0) & (cols < grid["ni"])
    return np.clip(rows, 0, grid["nj"] - 1), np.clip(cols, 0, grid["ni"] - 1), ok_rows, ok_cols


def sample_mrms(values: np.ndarray, grid: dict, lats, lons) -> np.ndarray:
    """Nearest-neighbour sample onto the image grid, in mm/h. NaN = no radar coverage: MRMS marks
    it with negative values (-3), and off-grid pixels count the same. Never "dry"."""
    rows, cols, ok_rows, ok_cols = mrms_index(grid, lats, lons)
    out = np.ma.filled(values[rows[:, None], cols[None, :]].astype(np.float32), np.nan)
    out[~(ok_rows[:, None] & ok_cols[None, :])] = np.nan
    out[out < 0] = np.nan
    return out


# ---------------------------------------------------------------- HRRR: Lambert conformal grid

def lcc_grid(msg) -> dict:
    shape = int(msg["shapeOfTheEarth"])
    if shape == 6:
        radius = 6371229.0
    elif shape == 0:
        radius = 6367470.0
    elif shape == 1:
        radius = float(msg["scaledValueOfRadiusOfSphericalEarth"]) / 10 ** int(msg["scaleFactorOfRadiusOfSphericalEarth"])
    else:
        raise ValueError("the model grid uses an earth shape this map doesn't handle")
    return {"nx": int(msg["Nx"]), "ny": int(msg["Ny"]),
            "lat1": float(msg["latitudeOfFirstGridPointInDegrees"]),
            "lon1": float(msg["longitudeOfFirstGridPointInDegrees"]),
            "lov": float(msg["LoVInDegrees"]), "latin1": float(msg["Latin1InDegrees"]),
            "latin2": float(msg["Latin2InDegrees"]), "dx": float(msg["DxInMetres"]),
            "dy": float(msg["DyInMetres"]), "radius": radius,
            "j_pos": bool(msg["jScansPositively"]), "i_neg": bool(msg["iScansNegatively"])}


def lcc_ij(grid: dict, lat, lon) -> tuple[np.ndarray, np.ndarray]:
    """Fractional grid indices (i east, j north for HRRR) of each point: the spherical Lambert
    conformal conic forward projection (Snyder 1987, eq. 15-1 to 15-4), then offsets from the
    grid's first point. No pyproj; checked against pygrib's latlons() in tests/test_gridded.py."""
    p1, p2 = math.radians(grid["latin1"]), math.radians(grid["latin2"])
    if abs(p1 - p2) < 1e-10:
        n = math.sin(p1)
    else:
        n = math.log(math.cos(p1) / math.cos(p2)) / math.log(math.tan(math.pi / 4 + p2 / 2) / math.tan(math.pi / 4 + p1 / 2))
    big_f = math.cos(p1) * math.tan(math.pi / 4 + p1 / 2) ** n / n
    rf = grid["radius"] * big_f

    def xy(la, lo):
        rho = rf / np.tan(np.pi / 4 + np.radians(la) / 2) ** n
        theta = n * np.radians((np.asarray(lo, dtype=float) - grid["lov"] + 180.0) % 360.0 - 180.0)
        return rho * np.sin(theta), -rho * np.cos(theta)    # rho0 cancels against the first point

    x, y = xy(np.asarray(lat, dtype=float), lon)
    x1, y1 = xy(grid["lat1"], grid["lon1"])
    i = (x - x1) / grid["dx"] * (-1 if grid["i_neg"] else 1)
    j = (y - y1) / grid["dy"] * (1 if grid["j_pos"] else -1)
    return i, j


def bilinear(values: np.ndarray, i, j) -> np.ndarray:
    """Bilinear interpolation of values[j, i] in grid-index space; NaN off the grid."""
    ny, nx = values.shape
    i, j = np.asarray(i, dtype=float), np.asarray(j, dtype=float)
    inside = (i >= 0) & (i <= nx - 1) & (j >= 0) & (j <= ny - 1)
    i0 = np.clip(np.floor(np.nan_to_num(i)), 0, nx - 2).astype(np.int64)
    j0 = np.clip(np.floor(np.nan_to_num(j)), 0, ny - 2).astype(np.int64)
    fi = np.clip(i - i0, 0.0, 1.0)
    fj = np.clip(j - j0, 0.0, 1.0)
    out = ((values[j0, i0] * (1 - fi) + values[j0, i0 + 1] * fi) * (1 - fj)
           + (values[j0 + 1, i0] * (1 - fi) + values[j0 + 1, i0 + 1] * fi) * fj).astype(np.float32)
    out[~inside] = np.nan
    return out


def smooth(field: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    """Light Gaussian blur for soft radar edges. No-data pixels (NaN) stay no-data and lend no
    value to their neighbours (normalised convolution)."""
    r = max(1, int(math.ceil(2 * sigma)))
    kernel = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    kernel /= kernel.sum()
    valid = np.isfinite(field)
    if valid.all():                     # the common case: no hatched areas, half the work
        v = np.asarray(field, dtype=np.float32)
        for axis in (0, 1):
            v = _convolve(v, kernel, axis)
        return v
    v = np.where(valid, field, 0.0).astype(np.float32)
    w = valid.astype(np.float32)
    for axis in (0, 1):
        v, w = _convolve(v, kernel, axis), _convolve(w, kernel, axis)
    out = np.where(w > 1e-6, v / np.maximum(w, 1e-6), np.nan).astype(np.float32)
    out[~valid] = np.nan
    return out


def _convolve(a: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    r, n = len(kernel) // 2, a.shape[axis]
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    padded = np.pad(a, pad, mode="edge")
    out = np.zeros_like(a)
    for t, weight in enumerate(kernel):
        window = [slice(None)] * a.ndim
        window[axis] = slice(t, t + n)
        out += weight * padded[tuple(window)]
    return out


# ---------------------------------------------------------------- colours and pictures

def colour_at(value: float, stops, log: bool = False) -> tuple[int, int, int, float]:
    """Colour (0-255 each) and alpha (0-1) at a value, interpolated between stops (in log space
    for precipitation) and held at the end stops."""
    f = math.log if log else float
    xs = [f(s[0]) for s in stops]
    x = min(max(f(value), xs[0]), xs[-1])
    k = max(1, min(len(xs) - 1, next((m for m, xm in enumerate(xs) if xm >= x), len(xs) - 1)))
    t = 0.0 if xs[k] == xs[k - 1] else (x - xs[k - 1]) / (xs[k] - xs[k - 1])
    (r0, g0, b0), (r1, g1, b1) = _hex(stops[k - 1][1]), _hex(stops[k][1])
    a = stops[k - 1][2] + t * (stops[k][2] - stops[k - 1][2])
    return (round(r0 + t * (r1 - r0)), round(g0 + t * (g1 - g0)), round(b0 + t * (b1 - b0)), round(a, 4))


def level_value(layer: str, k: int) -> float:
    """The value (display units) that colour level k stands for."""
    stops, log, n = STYLE[layer]
    lo, hi = stops[0][0], stops[-1][0]
    if log:
        return math.exp(math.log(lo) + (math.log(hi) - math.log(lo)) * k / (n - 1))
    return lo + (hi - lo) * k / (n - 1)


def palette(layer: str) -> tuple[bytes, bytes]:
    """PNG palette (RGB triples) and per-index alpha (the tRNS chunk): transparent, hatch, levels."""
    stops, log, n = STYLE[layer]
    rgb, alpha = [0, 0, 0, *_hex(HATCH[0])], [0, round(HATCH[1] * 255)]
    for k in range(n):
        r, g, b, a = colour_at(level_value(layer, k), stops, log)
        rgb += [r, g, b]
        alpha.append(round(a * 255))
    return bytes(rgb), bytes(alpha)


def hatch_mask(shape: tuple[int, int], width: int) -> np.ndarray:
    """Diagonal stripes; the period scales with the frame width so every layer looks the same on screen."""
    period = max(4, round(8 * width / 1400))
    stripe = max(1, round(2 * width / 1400))
    yy, xx = np.indices(shape)
    return (xx + yy) % period < stripe


def to_index(field: np.ndarray, layer: str) -> tuple[np.ndarray, bool]:
    """Palette indices for a field in display units (mm/h, °F, mph), and whether any pixel has no
    data. No data (NaN, or a negative precipitation rate) is hatched, never drawn as dry or calm."""
    stops, log, n = STYLE[layer]
    field = np.asarray(field, dtype=np.float32)
    nodata = ~np.isfinite(field)
    if layer == "precip":
        nodata |= np.nan_to_num(field, nan=0.0) < 0
    lo, hi = stops[0][0], stops[-1][0]
    safe = np.where(nodata, lo, field)
    with np.errstate(divide="ignore", invalid="ignore"):
        if log:
            t = (np.log(np.maximum(safe, lo)) - math.log(lo)) / (math.log(hi) - math.log(lo))
        else:
            t = (safe - lo) / (hi - lo)
    idx = (2 + np.rint(np.clip(t, 0.0, 1.0) * (n - 1))).astype(np.uint8)
    if layer == "precip":   # the tolerance only absorbs float32 round-off from smoothing
        idx[safe < np.float32(PRECIP_MIN * (1 - 1e-5))] = 0
    idx[nodata] = 0
    has_nodata = bool(nodata.any())
    if has_nodata:
        idx[nodata & hatch_mask(field.shape, field.shape[1])] = 1
    return idx, has_nodata


def png_bytes(index: np.ndarray, layer: str) -> bytes:
    """A palette ("P") PNG with per-index alpha: small files, exact colours."""
    from PIL import Image
    rgb, alpha = palette(layer)
    h, w = index.shape
    img = Image.frombytes("P", (w, h), np.ascontiguousarray(index, dtype=np.uint8).tobytes())
    img.putpalette(rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, transparency=alpha)
    return buf.getvalue()


def render(field: np.ndarray, layer: str) -> tuple[bytes, bool]:
    """Field in display units on the image grid -> (PNG bytes, has no-data areas)."""
    field = np.asarray(field, dtype=np.float32)
    if layer == "precip":   # no coverage must not be blurred into its neighbours as a rate
        field = np.where(field < 0, np.float32(np.nan), field)
    idx, nodata = to_index(smooth(field, SMOOTH_PX), layer)
    return png_bytes(idx, layer), nodata


def precip_class(mm_h: float) -> str | None:
    """AMS rainfall-rate class of a rate; None below the drawing threshold; no data for negatives."""
    if mm_h is None or not math.isfinite(mm_h) or mm_h < 0:
        return "No data"
    if mm_h < PRECIP_MIN:
        return None
    return next(label for label, low in PRECIP_CLASSES if mm_h >= low)


def _sig1(x: float) -> float:
    """One significant figure: 1.97 -> 2.0, 0.299 -> 0.3, 0.0039 -> 0.004."""
    return round(x, -int(math.floor(math.log10(abs(x)))))


def legend(layer: str) -> tuple[list[dict], str]:
    """Legend entries (top of the bar first) and a CSS gradient for the bar, from the same stops
    the pictures use. `pos` is where an entry's colour sits on the bar (0 bottom, 1 top)."""
    stops, log, _n = STYLE[layer]
    if layer == "precip":
        points = [(label, mm, _sig1(mm / MM_PER_INCH)) for label, mm in PRECIP_CLASSES]
    else:
        unit = LEGEND_UNIT[layer]
        points = [(f"{v}{unit}".replace("-", "−"), v, v) for v, _c, a in reversed(stops) if a > 0]
    n = len(points)
    entries = []
    for k, (label, value, shown) in enumerate(points):
        r, g, b, a = colour_at(value, stops, log)
        entry = {"label": label, "value": shown, "color": "#%02x%02x%02x" % (r, g, b), "alpha": a,
                 "pos": round(1 - k / (n - 1), 4)}
        if layer == "wind" and value == src.LIMITS["gust_mph"]:
            entry["limit"] = True
        entries.append(entry)
    # Gradient: every stop inside the legend's range, placed between the entries it falls between.
    f = math.log if log else float
    anchors = [(f(value), 1 - k / (n - 1)) for k, (_l, value, _s) in enumerate(points)][::-1]
    css = []
    for v, _c, _a in stops:
        x = f(v)
        if not anchors[0][0] - 1e-9 <= x <= anchors[-1][0] + 1e-9:
            continue
        m = max(1, next(i for i, (ax, _p) in enumerate(anchors) if ax >= x - 1e-9))
        (x0, p0), (x1, p1) = anchors[m - 1], anchors[m]
        pos = p0 if x1 == x0 else p0 + (x - x0) / (x1 - x0) * (p1 - p0)
        r, g, b, a = colour_at(v, stops, log)
        css.append(f"rgba({r},{g},{b},{a:g}) {pos * 100:.1f}%")
    return entries, "linear-gradient(to top, " + ", ".join(css) + ")"


# ---------------------------------------------------------------- GRIB bytes

def grib_message(data: bytes) -> bytes:
    """The first complete GRIB2 message in data. A download cut short is an error here: eccodes
    would still read the header of a truncated message and only complain on stderr."""
    if not data or data[:4] != b"GRIB" or len(data) < 16:
        raise ValueError("the download was not a GRIB file")
    if data[7] != 2:
        raise ValueError("the download was not a GRIB2 file")
    total = int.from_bytes(data[8:16], "big")
    if total < 16 or len(data) < total or data[total - 4:total] != b"7777":
        raise ValueError("the download was cut short")
    return data[:total]


def _valid_time(msg) -> datetime:
    d, t = int(msg["validityDate"]), int(msg["validityTime"])
    return datetime(d // 10000, d // 100 % 100, d % 100, t // 100, t % 100, tzinfo=UTC)


def decode_mrms(data: bytes, expected: datetime | None = None) -> tuple[np.ndarray, dict]:
    """A gzipped MRMS PrecipRate file -> (values in mm/h as pygrib gives them, grid). Only the
    image window is converted later (sample_mrms): the full grid is 24.5 million points."""
    import pygrib   # only live builds read GRIB files
    raw = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
    msg = pygrib.fromstring(grib_message(raw))
    if (msg["discipline"], msg["parameterCategory"], msg["parameterNumber"]) != MRMS_PARAM:
        raise ValueError("the radar file was not a precipitation-rate grid")
    if msg["gridType"] != "regular_ll":
        raise ValueError("the radar file had an unexpected grid")
    if expected is not None and abs(_valid_time(msg) - expected) > timedelta(minutes=2):
        raise ValueError("the radar file's own time didn't match its name")
    return msg.values, mrms_grid(msg)


def decode_hrrr(data: bytes, layer: str, valid: datetime) -> tuple[np.ndarray, dict]:
    """One HRRR field fetched by byte range -> (values in display units, grid)."""
    import pygrib   # only live builds read GRIB files
    msg = pygrib.fromstring(grib_message(data))
    if (msg["discipline"], msg["parameterCategory"], msg["parameterNumber"]) != HRRR_FIELDS[layer][2]:
        raise ValueError("the model file held a different field than its index listed")
    if msg["gridType"] != "lambert":
        raise ValueError("the model file had an unexpected grid")
    if _valid_time(msg) != valid:
        raise ValueError("the model field was for a different time than its index listed")
    values = np.ma.filled(np.ma.asarray(msg.values, dtype=np.float32), np.nan)
    return CONVERT[layer](values).astype(np.float32), lcc_grid(msg)


# ---------------------------------------------------------------- MRMS file list and frame choice

def mrms_list_urls(now: datetime) -> list[str]:
    """S3 listings covering LIST_SPAN: today's folder, and yesterday's when the span reaches back
    past 00 UTC. One extra minute because start-after skips a file named exactly at the start."""
    start = now.astimezone(UTC) - LIST_SPAN - timedelta(minutes=1)
    urls = []
    for day in sorted({start.date(), now.astimezone(UTC).date()}):
        prefix = f"{MRMS_PREFIX}{day:%Y%m%d}/"
        url = f"{MRMS}?list-type=2&prefix={quote(prefix)}"
        if start.date() == day:
            url += "&start-after=" + quote(f"{prefix}MRMS_PrecipRate_00.00_{start:%Y%m%d-%H%M%S}.grib2.gz")
        urls.append(url)
    return urls


def parse_listing(data) -> tuple[list[tuple[datetime, str]], str | None]:
    """S3 ListObjectsV2 XML -> ([(file time UTC, key)] oldest first, continuation token or None)."""
    text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data or "")
    if "<ListBucketResult" not in text:
        raise ValueError("the radar file list was not readable")
    found = []
    for key in re.findall(r"<Key>([^<]+)</Key>", text):
        key = html.unescape(key)
        m = MRMS_KEY.search(key)
        if m:
            try:
                found.append((datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=UTC), key))
            except ValueError:
                continue
    token = None
    if re.search(r"<IsTruncated>\s*true\s*</IsTruncated>", text):
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
        token = html.unescape(m.group(1)) if m else None
    return sorted(found), token


def list_radar(get, now: datetime) -> list[tuple[datetime, str]]:
    found = set()
    for url in mrms_list_urls(now):
        token = None
        for _page in range(10):
            data, err = get(url + (f"&continuation-token={quote(token, safe='')}" if token else ""))
            if err:
                raise ValueError(f"the radar file list didn't load ({err})")
            items, token = parse_listing(data)
            found.update(items)
            if not token:
                break
    return sorted(found)


def pick_radar(available, count: int = RADAR_FRAMES, step: timedelta = RADAR_STEP,
               tolerance: timedelta = RADAR_TOLERANCE):
    """Targets T0, T0-10 min, ... (T0 = the newest file). Each takes the file at that time, else
    the nearest within the tolerance, else is skipped. -> ([(time, key)] oldest first, skipped targets)."""
    files = sorted(available)
    if not files:
        return [], []
    t0 = files[-1][0]
    picked, skipped = [], []
    for k in range(count):
        target = t0 - k * step
        best = min(files, key=lambda f: (abs(f[0] - target), f[0]))
        if abs(best[0] - target) <= tolerance and best not in picked:
            picked.append(best)
        else:
            skipped.append(target)
    return sorted(picked), sorted(skipped)


# ---------------------------------------------------------------- HRRR runs and .idx byte ranges

def hrrr_url(run: datetime, kind: str, fhour: int) -> str:
    """kind "sfc" (hourly 2-D fields) or "subh" (15-minute steps)."""
    return f"{HRRR}hrrr.{run:%Y%m%d}/conus/hrrr.t{run:%H}z.wrf{kind}f{fhour:02d}.grib2"


def parse_idx(data) -> list[dict]:
    """A wgrib2 .idx inventory -> records with byte offsets, in file order."""
    text = data.decode("utf-8", "replace") if isinstance(data, (bytes, bytearray)) else str(data or "")
    records = []
    for line in text.splitlines():
        parts = line.strip().split(":")
        if len(parts) < 6 or not parts[1].isdigit():
            continue
        records.append({"num": parts[0], "offset": int(parts[1]), "var": parts[3], "level": parts[4],
                        "time": parts[5]})
    if not records:
        raise ValueError("the model file index was empty or unreadable")
    return records


def byte_range(records: list[dict], var: str, level: str, time_label: str) -> tuple[int, int | None]:
    """(start, end) bytes of one field: end = the next record's offset - 1; the last record is
    open-ended (None)."""
    for k, r in enumerate(records):
        if r["var"] == var and r["level"] == level and r["time"] == time_label:
            later = [x["offset"] for x in records[k + 1:] if x["offset"] > r["offset"]]
            return r["offset"], (min(later) - 1 if later else None)
    raise ValueError(f"the model file had no {var} {level} for {time_label}")


def range_header(start: int, end: int | None) -> dict:
    return {"Range": f"bytes={start}-{'' if end is None else end}"}


def lead_label(minutes: int, kind: str) -> str:
    if kind == "subh":
        return f"{minutes} min fcst"
    return "anl" if minutes == 0 else f"{minutes // 60} hour fcst"


def forecast_times(anchor: datetime) -> dict[str, list[datetime]]:
    """Valid times. hourly: the next 12 full hours after the anchor (precipitation "12h");
    quarters: the next four quarter-hours (precipitation "1h"); hours13: the anchor's hour and the
    next 12 (temperature and gusts)."""
    h0, q0 = floor_time(anchor, 60), floor_time(anchor, 15)
    return {"hourly": [h0 + timedelta(hours=k + 1) for k in range(FORECAST_HOURS)],
            "quarters": [q0 + timedelta(minutes=15 * (k + 1)) for k in range(QUARTER_HOURS)],
            "hours13": [h0 + timedelta(hours=k) for k in range(FORECAST_HOURS + 1)]}


def find_run(get, anchor: datetime, tries: int = HRRR_RUNS_TRIED) -> tuple[datetime, dict]:
    """Newest run hour (newest first, `tries` hours) whose file for the longest lead needed has
    its .idx published. -> (run, {idx url: records})."""
    h0 = floor_time(anchor, 60)
    last_valid = h0 + timedelta(hours=FORECAST_HOURS)
    other = None
    for k in range(tries):
        run = h0 - timedelta(hours=k)
        lead = int((last_valid - run) / timedelta(hours=1))
        url = hrrr_url(run, "sfc", lead) + ".idx"
        data, err = get(url)
        if err:
            if not str(err).startswith("not published"):
                other = err
            continue
        try:
            return run, {url: parse_idx(data)}
        except ValueError:
            other = "an index file was unreadable"
    if other:
        raise ValueError(f"the HRRR files didn't load ({other})")
    raise ValueError(f"no complete HRRR run in the last {tries} hours")


# ---------------------------------------------------------------- live layers

class _Grids:
    """Image-grid coordinates per width, and HRRR grid indices per (grid, width), computed once."""

    def __init__(self):
        self.centers, self.ij = {}, {}

    def latlon(self, width):
        if width not in self.centers:
            self.centers[width] = pixel_centers(width)
        return self.centers[width]

    def lcc(self, grid, width):
        key = (tuple(sorted(grid.items())), width)
        if key not in self.ij:
            lats, lons = self.latlon(width)
            self.ij[key] = lcc_ij(grid, lats[:, None], lons[None, :])     # broadcasts to (rows, cols)
        return self.ij[key]


class _Missing(ValueError):
    """A download that failed; its message already says which one."""


def _problem(e: Exception) -> str:
    """Plain words for an error; anything unexpected keeps only its type name."""
    if isinstance(e, ImportError):
        return f"{e.name or 'a needed Python package'} isn't installed on the build machine"
    if isinstance(e, OSError) and e.strerror:
        return e.strerror
    if isinstance(e, (ValueError, OSError)) and str(e):
        return str(e)
    return f"unexpected error ({type(e).__name__})"


def live_radar(get, now: datetime, grids: _Grids) -> tuple[list[dict], dict, datetime | None]:
    """-> (frames with "_png" bytes, status, newest file time). Any failed frame drops them all."""
    label = LABELS["radar"]
    try:
        files = list_radar(get, now)
    except Exception as e:  # noqa: BLE001 - never raise to the build
        return [], {"label": label, "ok": False, "detail": _problem(e)}, None
    if not files or now - files[-1][0] > LIST_BACK:     # older files are listed only for the frames
        return [], {"label": label, "ok": False,
                    "detail": f"no radar files in the last {int(LIST_BACK.total_seconds() // 3600)} hours"}, None
    picked, skipped = pick_radar(files)
    lats, lons = grids.latlon(WIDTHS["precip"])
    frames = []
    for t, key in picked:
        try:
            data, err = get(MRMS + key)
        except Exception as e:  # noqa: BLE001
            data, err = None, _problem(e)
        if err:
            return [], {"label": label, "ok": False, "detail": f"the radar file for {_hm(t)} didn't load ({err})"}, None
        try:
            values, grid = decode_mrms(data, t)
            field = sample_mrms(values, grid, lats, lons)
            del values
            png, nodata = render(field, "precip")
        except Exception as e:  # noqa: BLE001
            return [], {"label": label, "ok": False,
                        "detail": f"the radar file for {_hm(t)} couldn't be read ({_problem(e)})"}, None
        frames.append({"time": src._iso(t), "kind": "radar", "src": frame_src("precip", t),
                       "source": RADAR_SOURCE, "nodata": nodata, "_png": png})
    t0 = picked[-1][0]
    detail = f"{len(frames)} frame{'' if len(frames) == 1 else 's'}, latest {_hm(t0)}"
    if skipped:
        detail += f" (no file near {', '.join(_hm(s) for s in skipped)})"
    age = now - t0
    ok = age <= RADAR_STALE
    if not ok:
        detail = f"radar is {int(age.total_seconds() // 60)} min old; " + detail
    return frames, {"label": label, "ok": ok, "detail": detail}, t0


def live_forecast(get, now: datetime, anchor: datetime, grids: _Grids) -> tuple[dict, dict, datetime | None]:
    """-> ({layer: frames with "_png"}, status, run). A layer keeps its frames only if all loaded."""
    label = LABELS["forecast"]
    try:
        run, idx_cache = find_run(get, anchor)
    except Exception as e:  # noqa: BLE001
        return {}, {"label": label, "ok": False, "detail": _problem(e)}, None
    times = forecast_times(anchor)
    jobs = []   # (kind, fhour, layer, valid, time label)
    for v in times["hourly"]:
        m = int((v - run) / timedelta(minutes=1))
        jobs.append(("sfc", m // 60, "precip", v, lead_label(m, "sfc")))
    for v in times["quarters"]:
        if v.minute == 0:
            continue        # a full hour: the hourly frame is the frame for this time
        m = int((v - run) / timedelta(minutes=1))
        jobs.append(("subh", math.ceil(m / 60), "precip", v, lead_label(m, "subh")))
    for layer in ("temp", "wind"):
        for v in times["hours13"]:
            m = int((v - run) / timedelta(minutes=1))
            jobs.append(("sfc", m // 60, layer, v, lead_label(m, "sfc")))
    frames = {"precip": [], "temp": [], "wind": []}
    errors = {}
    for kind, fhour, layer, valid, tlabel in sorted(jobs, key=lambda j: (j[0], j[1], j[2], j[3])):
        if layer in errors:
            continue
        url = hrrr_url(run, kind, fhour)
        try:
            if url + ".idx" not in idx_cache:
                data, err = get(url + ".idx")
                if err:
                    raise _Missing(f"the model index for {_hm(valid)} didn't load ({err})")
                idx_cache[url + ".idx"] = parse_idx(data)
            var, level, _param = HRRR_FIELDS[layer]
            start, end = byte_range(idx_cache[url + ".idx"], var, level, tlabel)
            data, err = get(url, range_header(start, end))
            if err:
                raise _Missing(f"the model field for {_hm(valid)} didn't load ({err})")
            if end is not None and len(data) != end - start + 1:
                raise _Missing(f"the model field for {_hm(valid)} was cut short")
            values, grid = decode_hrrr(data, layer, valid)
            i, j = grids.lcc(grid, WIDTHS[layer])
            png, nodata = render(bilinear(values, i, j), layer)
        except _Missing as e:
            errors[layer] = str(e)
            continue
        except Exception as e:  # noqa: BLE001
            errors[layer] = f"the model field for {_hm(valid)} couldn't be read ({_problem(e)})"
            continue
        frames[layer].append({"time": src._iso(valid), "kind": "forecast", "src": frame_src(layer, valid, run),
                              "source": MODEL_SOURCE, "run": src._iso(run),
                              "lead_min": int((valid - run) / timedelta(minutes=1)), "nodata": nodata, "_png": png})
    for layer in errors:
        frames[layer] = []
    names = {"precip": "precipitation", "temp": "temperature", "wind": "wind gusts"}
    if not errors:
        detail = f"run {_hm(run)}, {FORECAST_HOURS} hours"
    else:
        detail = "; ".join(f"{names[k]}: {v}" for k, v in errors.items())
        good = [names[k] for k in frames if k not in errors]
        if good:
            detail += f"; {' and '.join(good)} from run {_hm(run)}"
    return frames, {"label": label, "ok": not errors, "detail": detail}, run


# ---------------------------------------------------------------- sample fields (labelled SAMPLE)
# Invented weather for design review and tests, drawn by the same renderers. The shapes follow a
# rough terrain proxy so the pictures read like weather; none of it is a forecast or a radar image.

BILLINGS = (45.7833, -108.5007)
LIVINGSTON, BIG_TIMBER = (45.6624, -110.5605), (45.8339, -109.9554)
# Rough terrain bumps: (lat, lon, height in thousands of feet, spread in lat, spread in lon).
TERRAIN = ((48.4, -114.0, 3.0, 0.8, 0.5), (47.5, -113.7, 2.4, 0.5, 0.3), (46.1, -114.4, 3.0, 0.6, 0.3),
           (45.4, -115.3, 3.4, 0.9, 0.8), (44.2, -114.8, 3.4, 0.6, 0.6), (45.8, -113.1, 2.8, 0.4, 0.35),
           (44.6, -112.6, 2.4, 0.3, 0.6), (45.2, -111.3, 3.2, 0.45, 0.3), (45.1, -110.0, 3.8, 0.3, 0.5),
           (44.5, -110.6, 2.8, 0.45, 0.5), (46.1, -110.3, 2.6, 0.2, 0.15), (46.9, -110.9, 2.2, 0.35, 0.35),
           (47.9, -112.9, 2.8, 0.7, 0.25), (46.9, -109.3, 1.6, 0.12, 0.25), (48.2, -109.6, 1.2, 0.15, 0.2),
           (47.9, -108.6, 0.9, 0.1, 0.12), (44.6, -107.4, 3.5, 0.5, 0.25), (44.3, -109.7, 3.0, 0.5, 0.35),
           (43.2, -109.6, 3.5, 0.5, 0.35), (44.1, -103.7, 1.8, 0.35, 0.25), (50.4, -115.4, 3.5, 0.8, 0.6),
           (49.4, -117.0, 3.0, 0.8, 0.7), (45.7, -118.0, 2.0, 0.4, 0.4), (43.4, -113.0, -1.0, 0.35, 1.2))
# Afternoon showers over the western mountains: (lat, lon, peak mm/h, spread in degrees).
SHOWERS = ((47.9, -114.4, 2.5, 0.10), (47.3, -113.6, 1.8, 0.08), (46.6, -114.2, 3.0, 0.09),
           (46.2, -113.1, 1.5, 0.07), (45.6, -112.8, 2.2, 0.08), (45.3, -111.4, 5.0, 0.07),
           (48.4, -113.4, 1.2, 0.09), (44.9, -112.1, 1.6, 0.07), (46.9, -112.6, 2.0, 0.08),
           (48.8, -114.8, 1.4, 0.10))


def _sample_hours(t: datetime, t0: datetime) -> float:
    return (t - t0).total_seconds() / 3600


def _local_hour(t: datetime) -> float:
    local = t.astimezone(MT)
    return local.hour + local.minute / 60


def _noise(lats, lons, cell: float, seed: int) -> np.ndarray:
    """Smooth, repeatable noise in 0..1 on the grid lats x lons (1-D each): seeded random values on
    a `cell`-degree lattice (40-54 N, 130-95 W), blended with smoothstep weights one axis at a time."""
    lattice = np.random.default_rng(seed).random((int(14 / cell) + 3, int(35 / cell) + 3)).astype(np.float32)

    def axis(v, origin, n):
        x = np.clip((np.asarray(v, dtype=float) - origin) / cell, 0, n - 2.001)
        k = x.astype(np.int64)
        f = x - k
        return k, (f * f * (3 - 2 * f)).astype(np.float32)

    i0, fx = axis(lons, -130.0, lattice.shape[1])
    j0, fy = axis(lats, 40.0, lattice.shape[0])
    rows = lattice[:, i0] * (1 - fx) + lattice[:, i0 + 1] * fx                # lattice rows x columns
    return rows[j0] * (1 - fy)[:, None] + rows[j0 + 1] * fy[:, None]


def _bump(lats, lons, la, lo, s_lat, s_lon) -> np.ndarray:
    """A Gaussian bump on the grid, as an outer product (cheap: the grid is separable)."""
    return np.exp(-0.5 * ((lats - la) / s_lat) ** 2)[:, None] * np.exp(-0.5 * ((lons - lo) / s_lon) ** 2)[None, :]


def sample_elevation(lats, lons) -> np.ndarray:
    """Rough terrain height in thousands of feet: plains rising to the west, plus the main ranges."""
    lats, lons = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
    slope = 1.8 + 2.0 * np.clip((-101.0 - lons) / 11.0, 0, 1) - 1.2 * np.clip((-116.5 - lons) / 2.0, 0, 1)
    elev = np.zeros((lats.size, lons.size)) + slope[None, :]
    for la, lo, height, s_lat, s_lon in TERRAIN:
        elev += height * _bump(lats, lons, la, lo, s_lat, s_lon)
    return elev


def sample_precip(lats, lons, t: datetime, t0: datetime, radar: bool) -> np.ndarray:
    """Invented rain (mm/h) on the grid lats x lons: a band moving west to east across Montana with
    its heavy core over Billings at T0, light rain trailing behind, afternoon showers over the
    western mountains. Radar frames also get an invented edge of radar coverage in the far
    north-west (hatched)."""
    h = _sample_hours(t, t0)
    lats, lons = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
    lat, lon = lats[:, None], lons[None, :]
    axis_lon = BILLINGS[1] - 0.15 + 0.7 * h + (lat - BILLINGS[0]) * 0.47     # SSW-NNE, moving east
    across = (lon - axis_lon) * math.cos(math.radians(46.5))                 # degrees of distance
    along = lat - BILLINGS[0]
    moving = lons - 0.7 * h                                                   # texture moves with the band
    texture = 0.3 + 0.9 * _noise(lats, moving, 0.45, 11) * (0.5 + 0.5 * _noise(lats, moving, 0.12, 12))
    width = 0.17 + 0.1 * _noise(lats, moving, 0.8, 13)
    band = 4.5 * np.exp(-0.5 * (across / width) ** 2) * np.exp(-0.5 * (along / 2.6) ** 2) * texture
    trail = 0.8 * np.exp(-0.5 * ((across + 0.7) / 0.45) ** 2) * np.exp(-0.5 * (along / 2.2) ** 2) * texture
    strength = 55.0 * math.exp(-0.5 * (h / 2.5) ** 2) + 8.0                  # strongest at T0, then weakens
    core = strength * np.exp(-0.5 * (((lon - axis_lon - 0.05) * 0.69) ** 2 + (lat - BILLINGS[0] - 0.05 * h) ** 2)
                             / 0.085 ** 2)
    cell2 = 14.0 * np.exp(-0.5 * (((lon - axis_lon + 0.05) * 0.69) ** 2 + (lat - BILLINGS[0] - 1.4) ** 2) / 0.11 ** 2)
    local = _local_hour(t)
    afternoon = max(0.0, math.sin(math.pi * (local - 11) / 9)) if 11 <= local <= 20 else 0.0
    showers = 0.0
    if afternoon:
        drift = max(0.0, local - 11)
        for la, lo, peak, spread in SHOWERS:
            showers = showers + peak * afternoon * _bump(lats, lons, la + 0.1 * drift, lo + 0.22 * drift,
                                                         spread, spread / 0.69)
        showers = showers * (0.6 + 0.8 * _noise(lats, lons, 0.1, 14))
    rate = (band + trail + core + cell2 + showers).astype(np.float32)
    if radar:   # invented edge of radar coverage, to show the hatching in design review
        edge = 49.75 + 0.25 * np.sin(2.3 * lon)
        rate = np.where((lat > edge) & (lon < -114.8), np.float32(np.nan), rate)
    return rate


def sample_temp(lats, lons, t: datetime, elev: np.ndarray) -> np.ndarray:
    """Invented 2 m temperature (°F): colder with height (the western ranges) and on the Hi-Line
    behind a front, warmest on the south-eastern plains, warming into the afternoon."""
    lat = np.asarray(lats, dtype=float)[:, None]
    diurnal = 12.0 * math.sin(2 * math.pi * (_local_hour(t) - 9) / 24)
    front = 7.0 / (1 + np.exp(-(lat - 48.3) / 0.15))
    wobble = 3.0 * (_noise(lats, lons, 1.2, 31) - 0.5)
    return (60.0 - 3.6 * elev - 1.0 * (lat - 45.0) + diurnal - front + wobble).astype(np.float32)


def sample_wind(lats, lons, t: datetime, t0: datetime, elev: np.ndarray) -> np.ndarray:
    """Invented gusts (mph): the Livingston-Big Timber corridor near 60 mph (the sample High Wind
    Warning), 30-40 along the Rocky Mountain Front, a gusty Hi-Line front, stronger on high ground."""
    h = _sample_hours(t, t0)
    lats, lons = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
    lat, lon = lats[:, None], lons[None, :]
    (la1, lo1), (la2, lo2) = LIVINGSTON, BIG_TIMBER
    ux, uy = lo2 - lo1, la2 - la1
    s = ((lon - lo1) * ux + (lat - la1) * uy) / (ux * ux + uy * uy)          # 0..1 along the corridor
    dist = np.hypot((lon - (lo1 + s * ux)) * 0.69, lat - (la1 + s * uy))
    along = np.exp(-0.5 * (np.clip(np.abs(s - 0.5) - 0.6, 0, None) / 0.4) ** 2)
    warning = 1.0 if h < 10 else max(0.0, 1 - (h - 10) / 3)
    corridor = 44.0 * warning * np.exp(-0.5 * (dist / 0.13) ** 2) * along
    front_range = 20.0 * np.exp(-0.5 * ((lon + 112.45 - 0.25 * (lat - 47.9)) / 0.3) ** 2
                                - 0.5 * ((lat - 47.9) / 0.7) ** 2)
    hiline = 9.0 / (1 + np.exp(-(lat - 48.3) / 0.2))
    ridges = 2.5 * np.clip(elev - 3.0, 0, None)
    base = 7.0 + 7.0 * _noise(lats, lons - 0.3 * h, 0.9, 21)
    daytime = 0.75 + 0.25 * math.sin(2 * math.pi * (_local_hour(t) - 10) / 24)
    return (corridor + (base + ridges + front_range + hiline) * daytime).astype(np.float32)


def _resample(field: np.ndarray, width: int) -> np.ndarray:
    """A field drawn at another width, stretched to `width`: linear along columns, then rows (both
    grids span IMAGE_BOUNDS, linear in longitude and in Mercator y)."""
    h1, w1 = field.shape
    w2, h2 = image_size(width)

    def weights(n_out, n_in):
        x = np.clip((np.arange(n_out) + 0.5) * n_in / n_out - 0.5, 0, n_in - 1)
        k = np.minimum(x.astype(np.int64), n_in - 2)
        return k, (x - k).astype(np.float32)

    i0, fi = weights(w2, w1)
    cols = field[:, i0] * (1 - fi) + field[:, i0 + 1] * fi
    j0, fj = weights(h2, h1)
    return (cols[j0] * (1 - fj)[:, None] + cols[j0 + 1] * fj[:, None]).astype(np.float32)


def sample_layers(now: datetime, grids: _Grids) -> tuple[list[dict], dict, dict, datetime]:
    """Invented frames through the same renderers. -> (radar frames, forecast frames by layer, status, t0).
    The invented rain is computed at half width and stretched: it is smooth, and tests stay fast."""
    t0 = floor_time(now, 2) - timedelta(minutes=4)
    run = floor_time(now, 60) - timedelta(hours=2)
    lats, lons = grids.latlon(WIDTHS["temp"])
    elev = sample_elevation(lats, lons)

    def rain(t, radar):
        field = sample_precip(lats, lons, t, t0, radar)
        return field if field.shape[1] == WIDTHS["precip"] else _resample(field, WIDTHS["precip"])

    radar = []
    for k in reversed(range(RADAR_FRAMES)):
        t = t0 - k * RADAR_STEP
        png, nodata = render(rain(t, True), "precip")
        radar.append({"time": src._iso(t), "kind": "radar", "src": frame_src("precip", t),
                      "source": SAMPLE_RADAR_SOURCE, "nodata": nodata, "_png": png})
    times = forecast_times(t0)
    precip_times = sorted(set(times["hourly"]) | {v for v in times["quarters"] if v.minute})
    forecast = {"precip": [], "temp": [], "wind": []}
    for layer, valid_times in (("precip", precip_times), ("temp", times["hours13"]), ("wind", times["hours13"])):
        for v in valid_times:
            field = (rain(v, False) if layer == "precip" else sample_temp(lats, lons, v, elev)
                     if layer == "temp" else sample_wind(lats, lons, v, t0, elev))
            if field.shape[1] != WIDTHS[layer]:
                field = _resample(field, WIDTHS[layer])
            png, nodata = render(field, layer)
            forecast[layer].append({"time": src._iso(v), "kind": "forecast", "src": frame_src(layer, v, run),
                                    "source": SAMPLE_MODEL_SOURCE, "run": src._iso(run),
                                    "lead_min": int((v - run) / timedelta(minutes=1)), "nodata": nodata,
                                    "_png": png})
    status = {"radar": {"label": LABELS["radar"], "ok": True,
                        "detail": f"SAMPLE — {len(radar)} invented frames, latest {_hm(t0)}"},
              "forecast": {"label": LABELS["forecast"], "ok": True,
                           "detail": f"SAMPLE — invented run {_hm(run)}, {FORECAST_HOURS} hours"}}
    return radar, forecast, status, t0


# ---------------------------------------------------------------- the layers for map.json

def assemble(radar: list[dict], forecast: dict, anchor: datetime | None, sample: bool = False) -> dict:
    """Layer dicts exactly as data/map.json carries them (without the PNG bytes). A sample build's
    legend notes say the pictures are invented (SAMPLE_NOTES)."""
    times = forecast_times(anchor) if anchor else {"hourly": [], "quarters": [], "hours13": []}
    layers = {}
    for layer in ("precip", "temp", "wind"):
        entries, gradient = legend(layer)
        frames = sorted((radar if layer == "precip" else []) + forecast.get(layer, []), key=lambda f: f["time"])
        at = {f["time"]: k for k, f in enumerate(frames)}
        if layer == "precip":
            past = [k for k, f in enumerate(frames) if f["kind"] == "radar"]
            quarters = [at[src._iso(v)] for v in times["quarters"] if src._iso(v) in at]
            hourly = [at[src._iso(v)] for v in times["hourly"] if src._iso(v) in at]
            modes = {"1h": past + quarters, "12h": past + hourly}
            now_index = {m: max(0, len(past) - 1) for m in modes}
        else:
            modes = {"12h": list(range(len(frames)))}
            now_index = {"12h": 0}
        text = {**LAYER_TEXT[layer], "legend_note": SAMPLE_NOTES[layer]} if sample else LAYER_TEXT[layer]
        layers[layer] = {**text, "legend": entries, "gradient": gradient,
                         "frames": [{k: v for k, v in f.items() if k != "_png"} for f in frames],
                         "modes": modes, "now_index": now_index}
    return layers


def _write(out_dir: Path, frames: list[dict]) -> None:
    for f in frames:
        path = Path(out_dir) / f["src"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f["_png"])


def build_gridded(out_dir: Path, get, now: datetime, sample: bool = False) -> tuple[dict, dict]:
    """Draw the map frames into out_dir/map/frames/ (out_dir is the site root) and return
    (layers for data/map.json, status {"radar": ..., "forecast": ...}). Never raises: a source that
    fails leaves its frames out and says why in its status."""
    now = (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(UTC)
    grids = _Grids()
    try:
        if sample:
            radar, forecast, status, anchor = sample_layers(now, grids)
        else:
            radar, radar_status, t0 = live_radar(get, now, grids)
            anchor = t0 if t0 is not None and now - t0 <= RADAR_STALE else floor_time(now, 1)
            forecast, forecast_status, _run = live_forecast(get, now, anchor, grids)
            status = {"radar": radar_status, "forecast": forecast_status}
    except Exception as e:  # noqa: BLE001 - last resort: never raise to the build
        reason = f"the map pictures couldn't be drawn ({_problem(e)})"
        return assemble([], {}, None, sample), {key: {"label": LABELS[key], "ok": False, "detail": reason}
                                                for key in ("radar", "forecast")}
    try:
        _write(out_dir, radar)
    except Exception as e:  # noqa: BLE001
        radar = []
        status["radar"] = {"label": LABELS["radar"], "ok": False,
                           "detail": f"the radar pictures couldn't be saved ({_problem(e)})"}
    for layer in list(forecast):
        try:
            _write(out_dir, forecast[layer])
        except Exception as e:  # noqa: BLE001
            forecast[layer] = []
            status["forecast"] = {"label": LABELS["forecast"], "ok": False,
                                  "detail": f"the forecast pictures couldn't be saved ({_problem(e)})"}
    return assemble(radar, forecast, anchor, sample), status
