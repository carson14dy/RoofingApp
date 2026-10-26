"""Terrain shading and land cover tint tiles for the Map page (B6 product P1; docs/DESIGN.md section 13).

What it is: two picture layers under the map, on one tile set for zooms 5 to 10. The terrain shading ("h") is the
grey relief of the ground, lit from the north-west at 45 degrees. The land cover tint ("l") is five colours for the
cover of the ground: forest, shrub and grass, developed land, crop land and water. The browser draws the tint under
the shading at low opacity and turns either layer off on its own, so the two stay apart on disk. Neither layer is a
measurement at an address, and a tile that is not in the store is shown as paper, never as a zero or an all-clear.

Sources (requests checked live on 2026-10-25 by the content of each answer, not only by its status):
  Shading      https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage with
               bboxSR and imageSR 3857, size 256,256, format png, renderingRule {"rasterFunction":"Hillshade Gray"}
               (solar azimuth 315 degrees, altitude 45 degrees, from the rule's help text). One request per tile; the
               service has no tile cache, so tiles come from exports. The data date is read from the service
               description ("as of September 28, 2026") at each build; it keys the cache.
  Land cover   https://www.mrlc.gov/geoserver/mrlc_display/wcs, WCS 1.0.0 GetCoverage for
               mrlc_display:NLCD_2021_Land_Cover_L48 with crs EPSG:3857, the tile's bbox, width and height 256 and
               interpolation "nearest neighbor" (the default too: the two answers are byte-identical). The answer is a
               palette GeoTIFF whose palette index is the NLCD class code. The layer's date stamp is 20230630 (its
               keyword), so the cache is keyed 2023-06.
  Outline      website/static/map/basemap.json, the Montana land polygon (one ring, no holes). A tile is in the set when
               its open square overlaps the outline with positive area (see tile_set). The research count of 805 came
               from a sample of 25 points per tile, which misses tiles that hold only a sliver of Montana (the top row
               of tiles at zooms 5 and 6, whose south edge lies just below the 49th parallel); the exact count is 881.

Terms: 3DEP is public domain: "3DEP data courtesy of the U.S. Geological Survey" is the suggested credit (quoted in a
secondary copy of the USGS terms; the USGS pages were blocked to the check on 2026-10-25), and the service copyright line
is "USGS National Map 3D Elevation Program (3DEP). October 01, 2026." NLCD: the MRLC About page says "public domain
information", and the WMS capabilities give Fees NONE and AccessConstraints NONE. The NLCD 2021 credit text is the
owner's to confirm; the citation the MRLC FAQ gives is for the Annual NLCD product, not this layer.

Outputs (written under the store's hail/base/, one file per tile, the same tile set for both layers):
  h/<z>/<x>/<y>.jpg   grey JPEG, 256 by 256, quality 80 (optimized Huffman tables, which do not change a pixel). The
                      PNG the service returns is decoded and encoded once, so the JPEG is the same bytes every run. The service's no-data grey value (its PNG transparency
                      value) becomes 255, which the browser's multiply leaves unchanged.
  l/<z>/<x>/<y>.png   palette PNG, 256 by 256, 8-bit indices with index 0 transparent. Index 1 to 5 are the tint classes
                      in TINT, with the colours of the B6 stage 1 proof picture (its LAND table):
                      forest 41, 42, 43 (#cde2c3); shrub and grass 52, 71 (#e6ecd6); developed 21, 22, 23, 24
                      (#f1ead6, one shade for the four developed codes); crop 81 pasture and hay, 82 cultivated crops
                      (#f2efd0); water 11 (#b9d9f2). Every other code (0 no data, 12, 31, 32, 51, 72 to 74, 90, 95) is
                      transparent. Nothing is averaged: the colour of a pixel is the class of one sampled cell.
  hail/base/index.json   this module's own index: {"f": "hail-base-index-v1", "terrain": block} (the other B6 products
                      add their own keys; a write keeps the keys it does not own).
  hail/index.json        gains "base": {"format": "hail-base-v1", "terrain": block}, where the block is the mirror: the
                      state, problem, as_of, zooms, counts, bytes, budget, sources, and the layers (state, path, missing,
                      files), which is what the site build reads for the map.
  hail/manifest.json     lists every h and l file with its bytes and SHA-256, and the base index file.

The index block (hail/base/index.json "terrain"; format "hail-terrain-v1"): state ("loaded", "partial" or
"unavailable"), problem and detail (the D20 sentence and the technical reason), built_at, as_of (the data dates),
zooms, tile_px, rule, layers ({"h": ..., "l": ...}: state, problem, path, format, tiles, files, missing (keys
"z/x/y" of the tiles that failed after three tries), bytes, bytes_by_zoom), counts (tiles by zoom, files, missing,
requests, retries, cache hits, downloaded bytes), bytes, bytes_by_zoom, budget (zooms 5 to 10 under 20,000,000 bytes),
sources (the credit lines and the request forms), palette, failures (the first 50) and seconds.

Units: shading values are 8-bit grey (0 to 255, larger is brighter); land cover values are NLCD class codes (the 2021
legend: 0 no data, 11 open water, 12 ice and snow, 21 to 24 developed, 31 barren, 32 unconsolidated shore, 41 to 43
forest, 51 dwarf scrub, 52 shrub and scrub, 71 grassland and herbaceous, 72 to 74 sedge, lichens and moss, 81 pasture
and hay, 82 cultivated crops, 90 woody wetlands, 95 emergent herbaceous wetlands; 255 is the fill the answer gives
outside the coverage, which the tint draws as transparent like 0). Sizes are bytes; the budget is
20,000,000 bytes (20 MB, decimal) for zooms 5 to 10 together.

Missing rules: a tile that fails three tries (a timeout each: 20 seconds, or the --timeout the job names; a 5xx, 429,
timeout or a body that is not the expected image is retried, other client errors are not) is listed in the layer's
"missing" and has no file. The browser shows the paper colour there. A later build requests a missing tile again,
because only a checked answer is kept in the cache. Zoom 5 land cover answers take 15 to 30 seconds on the service, so
the job passes --timeout 60; the default stays at the brief's 20 seconds. A tile whose request is stopped by the job's deadline is missing with that
reason. A cached copy that passes its check is used before any request; a refresh that fails serves the cached copy
with its reason. Land cover codes outside the NLCD legend fail the tile (never drawn as a class); the fill 255 that the
answer gives outside the coverage is accepted and drawn as transparent.

Failures (D16): one tile's failure is that tile's only. The other tiles of the layer, the other layer and the rest of
the store go on, and the build exits 0. A layer whose service description cannot be read (with no cached copy), or
whose every tile fails, is unavailable (D20): its files are removed, its block carries the reason, and its sentence
says the layer could not be loaded and is not an all-clear. The job's failure branch runs the unavailable command, so a
crashed build also leaves an unavailable block, never a missing one.

Command line (run from the repository root):
    python -m website.terrain build --store DIR [--cache DIR] [--zooms 5-10] [--only h|l] [--procs 4] [--offline]
                                    [--refresh] [--deadline-at EPOCH] [--timeout SECONDS]
    python -m website.terrain verify --store DIR [--cache DIR] [--sample 10] [--offline] [--timeout SECONDS]
    python -m website.terrain unavailable --store DIR --reason TEXT

The verify command re-reads the outline and recomputes the tile set; it checks every file's image (256 pixels, the mode
and the palette), the counts and bytes against the index, the manifest entries of every base file, that no file under
hail/base/h or hail/base/l is unlisted, the budget, and a seeded sample of tiles (10 by default, seed 20261025) re-fetched
from the sources and re-encoded: the shading must match byte for byte (or, if the encoder changes, within one grey
level), and the land cover tile must match byte for byte. --offline skips the re-fetch; --timeout sets the seconds each
re-fetch request may take (20 by default). Pillow and numpy are imported
only when a tile is read or drawn, and requests only when a source is read, so the site build can import this module.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import random
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

FORMAT = "hail-terrain-v1"               # the block in hail/base/index.json
BASE_INDEX_FORMAT = "hail-base-index-v1"  # hail/base/index.json
BASE_FORMAT = "hail-base-v1"             # the mirror block at hail/index.json "base"
INDEX_KEY = "base"                       # the key in hail/index.json
BASE_DIR = "hail/base"
LAYERS = ("h", "l")                      # h: shading (jpg); l: land cover tint (png)
LAYER_NAMES = {"h": "terrain shading", "l": "land cover tint"}
ZOOMS = (5, 6, 7, 8, 9, 10)
TILE_PX = 256
BUDGET_BYTES = 20_000_000                # zooms 5 to 10 together (decimal megabytes, the brief's budget)
JPEG_QUALITY = 80
TIMEOUT_S = 20                           # each request's timeout, in seconds
TRIES = 3                                # a tile fails after this many tries
WAIT_S = 2.0                             # the wait before try n + 1 is WAIT_S times n
PROCS = 4                                # at most this many requests at a time
VERIFY_SAMPLE = 10
VERIFY_SEED = 20261025
REASON_DEADLINE = "the job's deadline stopped the request"
SHADING_URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
SHADING_META_URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer?f=pjson"
RENDER_RULE = "Hillshade Gray"
LAND_URL = "https://www.mrlc.gov/geoserver/mrlc_display/wcs"
LAND_COVERAGE = "mrlc_display:NLCD_2021_Land_Cover_L48"
LAND_AS_OF = "2023-06"                   # the layer's date stamp (20230630 in its keyword), the cache key for land cover
USER_AGENT = "montana-hail-watch-terrain/1 (+https://github.com/carson14dy/RoofingApp)"
BASEMAP = Path(__file__).resolve().parent / "static" / "map" / "basemap.json"
EARTH_RADIUS_M = 6378137.0
HALF_WORLD_M = math.pi * EARTH_RADIUS_M  # the Web Mercator world is 2 x this across

# The five tint classes: palette index, name, colour (the proof's), and the NLCD codes they take.
TINT = (
    (1, "forest", "#cde2c3", (41, 42, 43)),
    (2, "shrub and grass", "#e6ecd6", (52, 71)),
    (3, "developed", "#f1ead6", (21, 22, 23, 24)),
    (4, "crop", "#f2efd0", (81, 82)),
    (5, "water", "#b9d9f2", (11,)),
)
# Every code of the NLCD 2021 legend (the WMS legend and the Missoula file): 0 is no data inside the coverage.
LEGEND_CODES = (0, 11, 12, 21, 22, 23, 24, 31, 32, 41, 42, 43, 51, 52, 71, 72, 73, 74, 81, 82, 90, 95)
# The fill the answer gives outside the coverage (the Missoula file's nodata value, 255): no data, drawn as transparent.
NODATA_CODES = (255,)

SOURCES = {
    "shading": {
        "name": "USGS 3D Elevation Program (3DEP), hillshade",
        "url": SHADING_URL,
        "rule": RENDER_RULE,
        "credit": "3DEP data courtesy of the U.S. Geological Survey.",
        "copyright_example": "USGS National Map 3D Elevation Program (3DEP). October 01, 2026.",
        "terms": "Public domain (USGS 3DEP); the credit is requested.",
    },
    "land_cover": {
        "name": "National Land Cover Database (NLCD) 2021, land cover",
        "url": LAND_URL,
        "coverage": LAND_COVERAGE,
        "credit": "National Land Cover Database (NLCD) 2021, U.S. Geological Survey and MRLC. Public domain information; no fee.",
        "terms": "Public domain information (MRLC About page); Fees NONE, AccessConstraints NONE (WMS capabilities).",
    },
}

# The layer names the sentences use: "{Part} could not be loaded ...; that is not the same as no {part}."
LAYER_WORDS = {"h": {"Part": "Terrain shading", "part": "terrain shading"},
               "l": {"Part": "The land cover tint", "part": "land cover tint"}}

WORDS = {
    # D20: a layer that did not load (the reason is kept in the block); both layers in one sentence
    "unavailable": ("Terrain shading and the land cover tint could not be loaded in this update; that is not the same as "
                    "no terrain shading or land cover tint. This is not an all-clear."),
    # D20 for one layer, and D16 for a layer with some tiles missing (the count is of the tiles in the set)
    "part_unavailable": "{Part} could not be loaded in this update; that is not the same as no {part}. This is not an all-clear.",
    "part_partial": ("{Part} could not be loaded in this update for {count} of {total} tiles; that is not the same as no "
                     "{part}. This is not an all-clear."),
    # a tile in the set that has no file: the browser shows the paper colour and this line where the tile is named
    "tile_missing": "Data unavailable: this tile did not load in this update, so it is drawn as paper.",
    "what": ("Terrain shading shows the shape of the ground, lit from the north-west at 45 degrees above the horizon. The land "
             "cover tint shows what covers the ground: forest, shrub and grass, developed land, crop land and water. "
             "Neither layer is a measurement at this address."),
    "shading_source": ("Terrain shading: USGS 3D Elevation Program (3DEP) hillshade, data as of {date}. 3DEP data courtesy "
                       "of the U.S. Geological Survey."),
    "land_source": ("Land cover tint: National Land Cover Database (NLCD) 2021, U.S. Geological Survey and MRLC. Public "
                    "domain information; no fee."),
}


class TerrainError(Exception):
    """A file, answer or figure that cannot be used. The message is plain words, lower case, with no full stop; it is a
    failed request (retried, then the cache is used) or a failed tile, never a crash of the whole build. tries is the
    number of requests the failure followed (0 when none was made)."""

    def __init__(self, message: str, tries: int = 0):
        super().__init__(message)
        self.tries = tries


# ---------------------------------------------------------------- Web Mercator tiles

def tile_lonlat(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """(west, south, east, north) in degrees of a Web Mercator tile. A tile is a rectangle in longitude and latitude."""
    n = 2.0 ** z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 1) / n))))
    return west, south, east, north


def tile_bbox_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) in metres of a Web Mercator (EPSG:3857) tile: x grows east, y grows north."""
    size = 2.0 * HALF_WORLD_M / (2 ** z)
    x0 = -HALF_WORLD_M + x * size
    y1 = HALF_WORLD_M - y * size
    return x0, y1 - size, x0 + size, y1


def tile_index(lon: float, lat: float, z: int) -> tuple[int, int]:
    """The tile (x, y) that holds a point, clamped to the world."""
    n = 2 ** z
    x = int(math.floor((lon + 180.0) / 360.0 * n))
    y = int(math.floor((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n))
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tile_key(z: int, x: int, y: int) -> str:
    return f"{int(z)}/{int(x)}/{int(y)}"


# ---------------------------------------------------------------- the outline and the tile set

def montana_rings(path: Path = BASEMAP) -> list[list[tuple[float, float]]]:
    """The exterior ring of each polygon of the Montana land feature (the outline the tiles are chosen against). Raises
    TerrainError when the feature is missing or has a hole, which this module does not handle."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        feats = doc["land"]["features"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise TerrainError("the Montana outline could not be read") from exc
    found = [f for f in feats if isinstance(f, dict) and (f.get("properties") or {}).get("montana") is True]
    if len(found) != 1:
        raise TerrainError("the Montana outline is not a single feature")
    geom = found[0].get("geometry") or {}
    if geom.get("type") == "Polygon":
        polygons = [geom.get("coordinates") or []]
    elif geom.get("type") == "MultiPolygon":
        polygons = geom.get("coordinates") or []
    else:
        raise TerrainError("the Montana outline is not a polygon")
    rings = []
    for rings_of in polygons:
        if not rings_of or len(rings_of) != 1:
            raise TerrainError("the Montana outline has a hole, which the tile rule does not handle")
        ring = [(float(p[0]), float(p[1])) for p in rings_of[0]]
        if len(ring) > 1 and ring[0] == ring[-1]:
            ring = ring[:-1]
        if len(ring) < 3:
            raise TerrainError("the Montana outline has a ring with fewer than three points")
        rings.append(ring)
    return rings


def _on_segment(px, py, ax, ay, bx, by) -> bool:
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if abs(cross) > 1e-12:
        return False
    return min(ax, bx) - 1e-12 <= px <= max(ax, bx) + 1e-12 and min(ay, by) - 1e-12 <= py <= max(ay, by) + 1e-12


def _strictly_inside(px: float, py: float, ring) -> bool:
    """True when the point is inside the ring and not on its edge (even-odd rule)."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if _on_segment(px, py, x1, y1, x2, y2):
            return False
        if (y1 > py) != (y2 > py) and x1 + (py - y1) * (x2 - x1) / (y2 - y1) > px:
            inside = not inside
    return inside


def _edge_enters(p, q, west: float, south: float, east: float, north: float) -> bool:
    """True when the segment p to q passes through the open rectangle (a positive-length piece inside it). The piece is
    clipped against the closed rectangle (Liang-Barsky); its midpoint then has to lie strictly inside, so an edge that
    runs along a side of the rectangle does not count."""
    x0, y0 = p
    x1, y1 = q
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, x0 - west), (dx, east - x0), (-dy, y0 - south), (dy, north - y0)):
        if pp == 0:
            if qq < 0:
                return False
            continue
        r = qq / pp
        if pp < 0:
            if r > t1:
                return False
            t0 = max(t0, r)
        else:
            if r < t0:
                return False
            t1 = min(t1, r)
    if t1 - t0 <= 1e-15:
        return False
    tm = (t0 + t1) / 2.0
    mx, my = x0 + dx * tm, y0 + dy * tm
    return west < mx < east and south < my < north


def overlaps_outline(z: int, x: int, y: int, rings) -> bool:
    """True when the open square of tile (z, x, y) and a polygon of the outline share positive area. A tile that only
    touches the outline along a line or at a point is not in the set."""
    return rect_overlaps(rings, *tile_lonlat(z, x, y))


def rect_overlaps(rings, west: float, south: float, east: float, north: float) -> bool:
    """True when the open rectangle (west, south, east, north), in degrees, and a polygon of the outline share positive
    area. A rectangle that only touches the outline along a line or at a point does not overlap it."""
    for ring in rings:
        if any(west < px < east and south < py < north for px, py in ring):
            return True
        if any(_strictly_inside(cx, cy, ring) for cx, cy in ((west, south), (east, south), (east, north), (west, north))):
            return True
        for i in range(len(ring)):
            if _edge_enters(ring[i], ring[(i + 1) % len(ring)], west, south, east, north):
                return True
    return False


def tile_set(rings, zooms=ZOOMS) -> dict[int, list[tuple[int, int]]]:
    """The tiles of each zoom whose open square overlaps the outline (positive area), sorted by x then y."""
    lons = [p[0] for ring in rings for p in ring]
    lats = [p[1] for ring in rings for p in ring]
    out: dict[int, list[tuple[int, int]]] = {}
    for z in zooms:
        n = 2 ** z
        west, north_row = tile_index(min(lons), max(lats), z)
        east, south_row = tile_index(max(lons), min(lats), z)
        found = []
        for x in range(max(0, west - 1), min(n - 1, east + 1) + 1):
            for y in range(max(0, north_row - 1), min(n - 1, south_row + 1) + 1):
                if overlaps_outline(z, x, y, rings):
                    found.append((x, y))
        out[z] = sorted(found)
    return out


# ---------------------------------------------------------------- requests and checks

def shading_request(z: int, x: int, y: int) -> dict:
    """The exportImage parameters of one shading tile (a lossless PNG; the JPEG is made here)."""
    bbox = tile_bbox_3857(z, x, y)
    return {"bbox": ",".join(f"{v:.6f}" for v in bbox), "bboxSR": 3857, "imageSR": 3857, "size": f"{TILE_PX},{TILE_PX}",
            "format": "png", "renderingRule": json.dumps({"rasterFunction": RENDER_RULE}), "f": "image"}


def land_request(z: int, x: int, y: int) -> dict:
    """The WCS 1.0.0 GetCoverage parameters of one land cover tile: its bbox in EPSG:3857 at 256 by 256, nearest."""
    bbox = tile_bbox_3857(z, x, y)
    return {"service": "WCS", "version": "1.0.0", "request": "GetCoverage", "coverage": LAND_COVERAGE, "crs": "EPSG:3857",
            "bbox": ",".join(f"{v:.6f}" for v in bbox), "width": TILE_PX, "height": TILE_PX, "format": "GeoTIFF",
            "response_crs": "EPSG:3857", "interpolation": "nearest neighbor"}


def _pil():
    try:
        from PIL import Image
    except ImportError as exc:                   # the tiles cannot be read or drawn without it
        raise TerrainError("the image library is not installed") from exc
    return Image


def _np():
    try:
        import numpy
    except ImportError as exc:
        raise TerrainError("the array library is not installed") from exc
    return numpy


def _open(data: bytes):
    try:
        return _pil().open(io.BytesIO(data))
    except TerrainError:
        raise
    except Exception as exc:                     # any bad image is a failed answer, whatever the library's class
        raise TerrainError("the answer is not a readable image") from exc


def check_shading_png(data: bytes) -> None:
    """The answer must be a 256 pixel, 8-bit grey PNG (a JSON error or an HTML page is a failed answer)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise TerrainError("the shading answer is not a PNG image")
    im = _open(data)
    if im.format != "PNG" or im.mode != "L" or im.size != (TILE_PX, TILE_PX):
        raise TerrainError("the shading tile is not a 256 pixel grey image")


def check_land_tiff(data: bytes) -> None:
    """The answer must be a 256 pixel palette TIFF whose indices are NLCD legend codes."""
    if data[:4] not in (b"II*\x00", b"MM\x00*"):
        raise TerrainError("the land cover answer is not a TIFF image")
    im = _open(data)
    if im.mode != "P" or im.size != (TILE_PX, TILE_PX):
        raise TerrainError("the land cover tile is not a 256 pixel palette image")
    np = _np()
    codes = np.unique(np.asarray(im))
    accepted = np.array(LEGEND_CODES + NODATA_CODES)
    if np.any(~np.isin(codes, accepted)):
        raise TerrainError("the land cover tile holds codes that are not in the NLCD legend")


def _lut():
    np = _np()
    table = np.zeros(256, dtype=np.uint8)
    for index, _name, _colour, codes in TINT:
        for code in codes:
            table[code] = index
    return table


def _palette_flat() -> list[int]:
    flat = [0] * 768
    for index, _name, colour, _codes in TINT:
        r, g, b = int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)
        flat[index * 3:index * 3 + 3] = [r, g, b]
    return flat


def shading_jpeg(png: bytes) -> bytes:
    """The grey JPEG (quality 80) of a shading PNG. The PNG's transparency grey (its no-data value) is written as 255."""
    np = _np()
    im = _open(png)
    arr = np.array(im.convert("L"), dtype=np.uint8)
    nodata = im.info.get("transparency")
    if isinstance(nodata, int):
        arr[arr == nodata] = 255
    buf = io.BytesIO()
    _pil().fromarray(arr, mode="L").save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def tint_png(tiff: bytes) -> bytes:
    """The palette PNG (indices 1 to 5, index 0 transparent) of a land cover TIFF whose palette indices are NLCD codes."""
    np = _np()
    im = _open(tiff)
    codes = np.array(im, dtype=np.uint8)
    indices = _lut()[codes]
    out = _pil().fromarray(indices, mode="P")
    out.putpalette(_palette_flat())
    buf = io.BytesIO()
    out.save(buf, format="PNG", transparency=0, optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------- fetching with tries and the cache

def _http_get(url: str, params: dict, timeout: float = TIMEOUT_S) -> tuple[int | None, bytes, str]:
    """One GET: (status or None, body, reason). A network error is a reason, never an exception."""
    try:
        import requests
        resp = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
        return resp.status_code, resp.content, ""
    except Exception as exc:                      # requests and socket errors alike: the try fails, with the class name
        return None, b"", f"the request failed ({type(exc).__name__})"


def fetch_checked(url: str, params: dict, check, *, get=None, sleep=time.sleep, timeout: float = TIMEOUT_S):
    """(body, tries). Up to TRIES tries: a 5xx, a 429, a network error or a body that fails check is tried again after a
    wait; any other status is final. Raises TerrainError with the last reason when every try fails. timeout is the
    seconds each request may take (TIMEOUT_S, 20, unless the job names a longer one for zoom 5)."""
    getter = get or (lambda u, p: _http_get(u, p, timeout=timeout))
    last = "the source did not answer"
    for attempt in range(1, TRIES + 1):
        status, body, reason = getter(url, params)
        if status is None:
            last = reason or "the source did not answer"
        elif status == 200:
            try:
                check(body)
            except TerrainError as exc:
                last = str(exc)
            else:
                return body, attempt
        elif status == 429 or status >= 500:
            last = f"HTTP {status}"
        else:
            raise TerrainError(f"HTTP {status}")
        if attempt < TRIES:
            sleep(WAIT_S * attempt)
    raise TerrainError(last, tries=TRIES)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".terrain-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def source_bytes(url: str, params: dict, check, path: Path, *, offline: bool, refresh: bool, deadline_at, get, sleep,
                 timeout: float = TIMEOUT_S):
    """(body, origin, tries, note): a cached copy that passes check is used first; otherwise the source is requested
    (unless offline or past the deadline) and the body is kept in the cache. A refresh that fails serves the cached copy
    with its reason. Raises TerrainError when there is no usable body."""
    cached_note = None
    if path.is_file():
        data = path.read_bytes()
        try:
            check(data)
        except TerrainError as exc:
            cached_note = f"the cached copy was not usable ({exc})"
        else:
            if not refresh:
                return data, "cache", 0, None
    if offline:
        if cached_note:
            raise TerrainError(f"{cached_note}, and this build makes no requests")
        raise TerrainError("the cache has no copy and this build makes no requests")
    if deadline_at is not None and time.monotonic() >= deadline_at:
        raise TerrainError(REASON_DEADLINE)
    try:
        data, tries = fetch_checked(url, params, check, get=get, sleep=sleep, timeout=timeout)
    except TerrainError as exc:
        if path.is_file():
            kept = path.read_bytes()
            try:
                check(kept)
            except TerrainError:
                raise exc
            return kept, "cache", TRIES, f"served the cached copy after: {exc}"
        raise
    _write_atomic(path, data)
    return data, "fetched", tries, cached_note


# ---------------------------------------------------------------- the build

def _shading_meta(cache: Path, *, offline: bool, refresh: bool, deadline_at, get, sleep,
                  timeout: float = TIMEOUT_S) -> dict:
    """The data date of the shading service, from its description ("as of September 28, 2026")."""
    import re
    path = cache / "meta" / "3dep-service.json"

    def check(data: bytes) -> None:
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise TerrainError("the service description is not JSON") from exc
        if not isinstance(doc, dict) or not isinstance(doc.get("description"), str):
            raise TerrainError("the service description has no description text")

    body, origin, _tries, note = source_bytes(SHADING_META_URL, {}, check, path, offline=offline, refresh=refresh,
                                              deadline_at=deadline_at, get=get, sleep=sleep, timeout=timeout)
    doc = json.loads(body.decode("utf-8"))
    found = re.search(r"as of ([A-Za-z]+ \d{1,2}, \d{4})", doc["description"])
    if not found:
        raise TerrainError("the service description has no data date")
    try:
        stamp = datetime.strptime(found.group(1), "%B %d, %Y").date()
    except ValueError as exc:
        raise TerrainError("the service data date is not a date") from exc
    return {"as_of": stamp.isoformat(), "as_of_month": stamp.strftime("%Y-%m"), "origin": origin, "note": note,
            "copyright": doc.get("copyrightText")}


def _tile_job(layer: str, z: int, x: int, y: int, ctx: dict) -> dict:
    key = tile_key(z, x, y)
    if layer == "h":
        url, params = SHADING_URL, shading_request(z, x, y)
        check = check_shading_png
        path = ctx["cache"] / "shading" / ctx["as_of_month"] / str(z) / str(x) / f"{y}.png"
        rel = f"{BASE_DIR}/h/{z}/{x}/{y}.jpg"
        draw = shading_jpeg
    else:
        url, params = LAND_URL, land_request(z, x, y)
        check = check_land_tiff
        path = ctx["cache"] / "land_cover" / LAND_AS_OF / str(z) / str(x) / f"{y}.tif"
        rel = f"{BASE_DIR}/l/{z}/{x}/{y}.png"
        draw = tint_png
    try:
        body, origin, tries, note = source_bytes(url, params, check, path, offline=ctx["offline"], refresh=ctx["refresh"],
                                                 deadline_at=ctx["deadline_at"], get=ctx["get"], sleep=ctx["sleep"],
                                                 timeout=ctx["timeout"])
    except TerrainError as exc:
        return {"key": key, "zoom": z, "missing": str(exc), "tries": exc.tries}
    try:
        out = draw(body)
    except Exception as exc:                     # one tile's failure is that tile's only (D16)
        return {"key": key, "zoom": z, "missing": f"the tile could not be drawn ({type(exc).__name__})", "tries": tries}
    try:
        _write_atomic(ctx["store"] / rel, out)
    except OSError as exc:
        return {"key": key, "zoom": z, "missing": f"the file could not be written ({type(exc).__name__})", "tries": tries}
    return {"key": key, "zoom": z, "rel": rel, "bytes": len(out), "sha256": hashlib.sha256(out).hexdigest(),
            "origin": origin, "tries": tries, "downloaded": len(body) if origin == "fetched" else 0, "note": note}


def _parse_zooms(text: str) -> tuple[int, ...]:
    text = str(text).strip()
    if "-" in text:
        first, last = text.split("-", 1)
        zooms = tuple(range(int(first), int(last) + 1))
    else:
        zooms = tuple(int(part) for part in text.split(",") if part.strip())
    if not zooms or any(z < 0 or z > 14 for z in zooms):
        raise TerrainError("the zooms must be between 0 and 14")
    return zooms


def _layer_block(layer: str, zooms, tiles, results: list[dict], built: bool) -> dict:
    files = [r for r in results if "rel" in r]
    missing = sorted((r["key"] for r in results if "missing" in r), key=_key_order)
    by_zoom = {str(z): 0 for z in zooms}
    for r in files:
        by_zoom[str(r["zoom"])] += r["bytes"]
    total_set = sum(len(tiles[z]) for z in zooms)
    words = LAYER_WORDS[layer]
    if not built or not files:
        state = "unavailable"
        problem = WORDS["part_unavailable"].format(**words)
    elif missing:
        state = "partial"
        problem = WORDS["part_partial"].format(count=len(missing), total=total_set, **words)
    else:
        state = "loaded"
        problem = None
    return {
        "state": state,
        "problem": problem,
        "path": f"{BASE_DIR}/{layer}/{{z}}/{{x}}/{{y}}.{'jpg' if layer == 'h' else 'png'}",
        "format": ("image/jpeg, 8-bit grey, 256 by 256, quality 80" if layer == "h"
                   else "image/png, palette of 6 entries with index 0 transparent, 256 by 256"),
        "tiles": total_set,
        "files": len(files),
        "missing": missing,
        "bytes": sum(r["bytes"] for r in files),
        "bytes_by_zoom": by_zoom,
        "requests": sum(r.get("tries", 0) for r in results),
        "cache_hits": sum(1 for r in files if r.get("origin") == "cache"),
        "downloaded_bytes": sum(r.get("downloaded", 0) for r in results),
        "retries": sum(max(0, r.get("tries", 0) - 1) for r in results),
        "notes": sorted({r["note"] for r in files if r.get("note")})[:20],
    }


def _key_order(key: str):
    return tuple(int(part) for part in key.split("/"))


def _sources_block(as_of: dict) -> dict:
    return {
        "shading": dict(SOURCES["shading"], as_of=as_of.get("shading_date")),
        "land_cover": dict(SOURCES["land_cover"], as_of=as_of.get("land_cover")),
    }


def _failure_list(results_by_layer: dict) -> list[dict]:
    out = []
    for layer, results in results_by_layer.items():
        for r in results:
            if "missing" in r:
                out.append({"layer": layer, "tile": r["key"], "reason": r["missing"]})
    return out[:50]


def _terrain_state(layers: dict) -> str:
    states = [layers[name]["state"] for name in LAYERS if name in layers]
    if not states or all(s == "unavailable" for s in states):
        return "unavailable"
    if all(s == "loaded" for s in states):
        return "loaded"
    return "partial"


def _terrain_problem(layers: dict, state: str) -> str | None:
    """The sentence of the whole block: the D20 sentence when nothing loaded, else each layer's sentence in layer order."""
    if state == "loaded":
        return None
    if state == "unavailable":
        return WORDS["unavailable"]
    sentences = [layers[name]["problem"] for name in LAYERS if name in layers and layers[name].get("problem")]
    return " ".join(sentences)


def build(store, cache, *, zooms=ZOOMS, only=LAYERS, offline: bool = False, refresh: bool = False,
          procs: int = PROCS, deadline_at: float | None = None, get=None, sleep=time.sleep,
          timeout: float = TIMEOUT_S) -> dict:
    """Write the tiles of the chosen layers into store/hail/base, then the index blocks and the manifest entries. Returns
    the summary. A layer whose tiles all fail is unavailable (its files removed, its block says why); the store's other
    files are kept. The outline must read, or the whole part is unavailable."""
    t0 = time.monotonic()
    store, cache = Path(store), Path(cache)
    only = tuple(name for name in LAYERS if name in only)
    try:
        rings = montana_rings()
        tiles = tile_set(rings, tuple(zooms))
    except TerrainError as exc:
        return mark_unavailable(store, f"the outline for the tile set could not be read ({exc})")
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    try:
        meta = _shading_meta(cache, offline=offline, refresh=refresh, deadline_at=deadline_at, get=get, sleep=sleep,
                             timeout=timeout)
        meta_error = None
    except TerrainError as exc:
        meta, meta_error = None, str(exc)
    as_of = {"shading_date": meta["as_of"] if meta else None,
             "shading_month": meta["as_of_month"] if meta else None, "land_cover": LAND_AS_OF}
    results_by_layer: dict[str, list[dict]] = {}
    layer_blocks: dict[str, dict] = {}
    store_base = store / BASE_DIR
    for layer in only:
        target = store_base / ("h" if layer == "h" else "l")
        if target.is_dir():
            shutil.rmtree(target)
        if layer == "h" and meta is None:
            layer_blocks[layer] = _layer_block(layer, zooms, tiles, [], built=False)
            layer_blocks[layer]["detail"] = meta_error
            results_by_layer[layer] = []
            continue
        ctx = {"store": store, "cache": cache, "as_of_month": meta["as_of_month"] if meta else "unknown",
               "offline": offline, "refresh": refresh, "deadline_at": deadline_at, "get": get, "sleep": sleep,
               "timeout": timeout}
        jobs = [(z, x, y) for z in zooms for (x, y) in tiles[z]]
        with ThreadPoolExecutor(max_workers=max(1, procs)) as pool:
            results = list(pool.map(lambda job: _tile_job(layer, job[0], job[1], job[2], ctx), jobs))
        results_by_layer[layer] = results
        layer_blocks[layer] = _layer_block(layer, zooms, tiles, results, built=True)
        if layer_blocks[layer]["state"] == "unavailable" and target.is_dir():
            shutil.rmtree(target)
    # the other layer, when only one was built, keeps the block the index already holds
    old_terrain = ((_read_base_index(store).get("terrain") or {}).get("layers") or {})
    for layer in LAYERS:
        if layer not in layer_blocks and layer in old_terrain:
            layer_blocks[layer] = old_terrain[layer]
    layers_ordered = {name: layer_blocks[name] for name in LAYERS if name in layer_blocks}
    state = _terrain_state(layers_ordered)
    problem = _terrain_problem(layers_ordered, state)
    total_bytes = sum(b["bytes"] for b in layers_ordered.values())
    by_zoom = {str(z): sum(b["bytes_by_zoom"].get(str(z), 0) for b in layers_ordered.values()) for z in zooms}
    counts = {"tiles_by_zoom": {str(z): len(tiles[z]) for z in zooms}, "tiles": sum(len(tiles[z]) for z in zooms),
              "files": sum(b["files"] for b in layers_ordered.values()),
              "missing": sum(len(b["missing"]) for b in layers_ordered.values()),
              "requests": sum(b["requests"] for b in layers_ordered.values()),
              "retries": sum(b["retries"] for b in layers_ordered.values()),
              "cache_hits": sum(b["cache_hits"] for b in layers_ordered.values()),
              "downloaded_bytes": sum(b["downloaded_bytes"] for b in layers_ordered.values())}
    block = {
        "format": FORMAT,
        "state": state,
        "problem": problem,
        "detail": None if state == "loaded" else _detail(layers_ordered, meta_error),
        "built_at": now,
        "as_of": as_of,
        "zooms": list(zooms),
        "tile_px": TILE_PX,
        "rule": ("tiles whose open square overlaps the Montana outline (basemap land polygon, positive area); one 256 "
                 "pixel request per tile and layer; nearest sampling for land cover; each layer's files are rebuilt whole"),
        "layers": layers_ordered,
        "counts": counts,
        "bytes": total_bytes,
        "bytes_by_zoom": by_zoom,
        "budget": {"zooms": "5 to 10", "bytes_limit": BUDGET_BYTES, "bytes": total_bytes,
                   "under_budget": total_bytes < BUDGET_BYTES},
        "sources": _sources_block(as_of),
        "palette": [{"index": i, "class": name, "hex": colour, "nlcd": list(codes)} for i, name, colour, codes in TINT],
        "failures": _failure_list(results_by_layer),
        "seconds": round(time.monotonic() - t0, 1),
    }
    _store_block(store, block, rebuilt=only)
    return {"state": state, "seconds": block["seconds"], "tiles": counts["tiles"], "files": counts["files"],
            "missing": counts["missing"], "bytes": total_bytes, "bytes_by_zoom": by_zoom,
            "requests": counts["requests"], "cache_hits": counts["cache_hits"], "budget_ok": total_bytes < BUDGET_BYTES,
            "layers": {name: {"state": b["state"], "files": b["files"], "missing": len(b["missing"]),
                              "bytes": b["bytes"]} for name, b in layers_ordered.items()}}


def _detail(layers: dict, meta_error: str | None) -> str:
    reasons = []
    if meta_error:
        reasons.append(f"shading service: {meta_error}")
    for name in LAYERS:
        block = layers.get(name)
        if not block:
            continue
        if block["state"] == "unavailable" and block.get("problem"):
            reasons.append(f"{LAYER_NAMES[name]}: no tile loaded")
        for key in block["missing"][:10]:
            reasons.append(f"{name} {key}: did not load after {TRIES} tries")
    return "; ".join(reasons[:50])


def _read_index(store: Path) -> dict:
    return json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))


def _read_base_index(store: Path) -> dict:
    path = store / BASE_DIR / "index.json"
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, ValueError):
            doc = None
        if isinstance(doc, dict) and doc.get("f") == BASE_INDEX_FORMAT:
            return doc
    return {"f": BASE_INDEX_FORMAT}


def _mirror(block: dict) -> dict:
    """The block as the store index carries it (hail/index.json "base"): the state, the dates, the counts, the sources and
    the bytes, and the layer lists the site's map needs (the missing tiles, the tile templates), so the site build reads
    the store index alone."""
    return {"state": block["state"], "problem": block.get("problem"), "as_of": block["as_of"],
            "zooms": block.get("zooms", []), "counts": block["counts"], "bytes": block["bytes"],
            "budget": block.get("budget"),
            "sources": {k: {"name": v["name"], "url": v["url"], "credit": v.get("credit")}
                        for k, v in block["sources"].items()},
            "layers": {name: {"state": info["state"], "path": info["path"], "missing": info["missing"],
                              "files": info["files"], "problem": info.get("problem")}
                       for name, info in block.get("layers", {}).items()}}


def _store_block(store: Path, block: dict | None, *, rebuilt: tuple) -> None:
    """Writes the block into the base index and the store index, then refreshes the manifest entries of the base files."""
    base = _read_base_index(store)
    if block is None:
        base.pop("terrain", None)
    else:
        base["terrain"] = block
    raw = (json.dumps(base, indent=1, ensure_ascii=True) + "\n").encode("utf-8")
    _write_atomic(store / BASE_DIR / "index.json", raw)
    index = _read_index(store)
    mirror_block = _mirror(block) if block is not None else {"state": "unavailable",
                                                            "as_of": {}, "counts": {}, "sources": {}, "bytes": 0}
    existing = index.get(INDEX_KEY) if isinstance(index.get(INDEX_KEY), dict) else {}
    existing["format"] = BASE_FORMAT
    existing["terrain"] = mirror_block
    index[INDEX_KEY] = existing
    _write_atomic(store / "hail" / "index.json", (json.dumps(index, indent=1, ensure_ascii=True) + "\n").encode("utf-8"))
    files, prefixes = _manifest_files(store, rebuilt)
    _merge_manifest(store, files, prefixes)


def _manifest_files(store: Path, rebuilt: tuple) -> tuple[dict, tuple]:
    """The manifest entries of the base files: every h and l file under the rebuilt layers, and the base index file."""
    prefixes = tuple(f"{BASE_DIR}/{'h' if name == 'h' else 'l'}/" for name in rebuilt) + (f"{BASE_DIR}/index.json",)
    files = {}
    for name in rebuilt:
        folder = store / BASE_DIR / ("h" if name == "h" else "l")
        if folder.is_dir():
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    data = path.read_bytes()
                    files[path.relative_to(store).as_posix()] = {"bytes": len(data),
                                                                 "sha256": hashlib.sha256(data).hexdigest()}
    base_path = store / BASE_DIR / "index.json"
    if base_path.is_file():
        data = base_path.read_bytes()
        files[f"{BASE_DIR}/index.json"] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return files, prefixes


def _merge_manifest(store: Path, new_files: dict, prefixes: tuple) -> None:
    """Replaces the manifest entries under prefixes with new_files and refreshes hail/index.json's own entry."""
    path = store / "hail" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    kept = {k: v for k, v in manifest.get("files", {}).items() if not k.startswith(prefixes)}
    kept.update(new_files)
    index_bytes = (store / "hail" / "index.json").read_bytes()
    kept["hail/index.json"] = {"bytes": len(index_bytes), "sha256": hashlib.sha256(index_bytes).hexdigest()}
    manifest["files"] = {k: kept[k] for k in sorted(kept)}
    _write_atomic(path, (json.dumps(manifest, indent=1, ensure_ascii=True) + "\n").encode("utf-8"))


def mark_unavailable(store, reason: str) -> dict:
    """The terrain layers are unavailable with the plain reason (D20). Their files are removed; the block says why; the
    rest of the store is kept (the other B6 products' keys are not touched)."""
    store = Path(store)
    text = " ".join(str(reason).split()) or "no reason was given"
    for name in LAYERS:
        folder = store / BASE_DIR / ("h" if name == "h" else "l")
        if folder.is_dir():
            shutil.rmtree(folder)
    block = {"format": FORMAT, "state": "unavailable", "problem": WORDS["unavailable"], "detail": text,
             "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
             "as_of": {}, "zooms": list(ZOOMS), "tile_px": TILE_PX, "rule": None, "layers": {}, "counts": {},
             "bytes": 0, "bytes_by_zoom": {}, "budget": {"zooms": "5 to 10", "bytes_limit": BUDGET_BYTES, "bytes": 0,
                                                       "under_budget": True}, "sources": _sources_block({}),
             "palette": [{"index": i, "class": name, "hex": colour, "nlcd": list(codes)} for i, name, colour, codes in TINT],
             "failures": [], "seconds": 0.0}
    _store_block(store, block, rebuilt=LAYERS)
    return {"state": "unavailable", "reason": text}


# ---------------------------------------------------------------- verify

def verify(store, cache=None, *, sample: int = VERIFY_SAMPLE, seed: int = VERIFY_SEED, offline: bool = False,
           get=None, sleep=time.sleep, timeout: float = TIMEOUT_S) -> dict:
    """Checks the terrain block, the tile files, the manifest entries and the budget, then re-fetches a seeded sample of
    tiles (unless offline) and compares the re-encoded bytes with the stored files. Returns {"ok", "checks", ...}."""
    store = Path(store)
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "pass": bool(passed), "detail": detail})

    index = _read_index(store)
    block = (_read_base_index(store).get("terrain"))
    check("base index block present", isinstance(block, dict))
    if not isinstance(block, dict):
        return {"ok": False, "checks": checks}
    check("terrain state is loaded, partial or unavailable", block.get("state") in ("loaded", "partial", "unavailable"),
          str(block.get("state")))
    mirror = (index.get(INDEX_KEY) or {}).get("terrain")
    check("hail/index.json base mirror matches the block",
          isinstance(mirror, dict) and mirror.get("state") == block.get("state")
          and mirror.get("bytes") == block.get("bytes") and mirror.get("counts") == block.get("counts"))
    if block.get("state") == "unavailable":
        present = [p for p in (store / BASE_DIR / "h", store / BASE_DIR / "l") if p.exists()]
        check("unavailable layers have no files", not present, ", ".join(str(p) for p in present))
        return {"ok": all(c["pass"] for c in checks), "checks": checks, "note": block.get("detail")}
    zooms = tuple(block["zooms"])
    try:
        rings = montana_rings()
        recomputed = tile_set(rings, zooms)
    except TerrainError as exc:
        check("the outline can be read for the tile set", False, str(exc))
        return {"ok": False, "checks": checks}
    expected_counts = {str(z): len(recomputed[z]) for z in zooms}
    check("tile count per zoom matches the current outline", block["counts"].get("tiles_by_zoom") == expected_counts,
          json.dumps(expected_counts, sort_keys=True))
    manifest = json.loads((store / "hail" / "manifest.json").read_text(encoding="utf-8"))
    listed = manifest.get("files", {})
    stored_files: dict[str, dict] = {}
    for name in LAYERS:
        expect_block = block["layers"].get(name)
        folder = store / BASE_DIR / ("h" if name == "h" else "l")
        if not expect_block:
            continue
        if expect_block["state"] == "unavailable":
            check(f"{name}: unavailable layer has no files", not folder.exists(), str(folder))
            continue
        expected_keys = {tile_key(z, x, y) for z in zooms for (x, y) in recomputed[z]}
        missing = set(expect_block["missing"])
        check(f"{name}: missing tiles are tiles of the set", missing <= expected_keys,
              f"{len(missing - expected_keys)} outside the set")
        found = set()
        bytes_total = 0
        by_zoom = {str(z): 0 for z in zooms}
        bad_image = []
        for path in sorted(folder.rglob("*")) if folder.is_dir() else []:
            if not path.is_file():
                continue
            rel = path.relative_to(store).as_posix()
            data = path.read_bytes()
            stored_files[rel] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            parts = path.relative_to(folder).with_suffix("").parts
            if len(parts) != 3 or not all(part.isdigit() for part in parts):
                bad_image.append(rel)
                continue
            key = "/".join(parts)
            found.add(key)
            bytes_total += len(data)
            by_zoom[parts[0]] = by_zoom.get(parts[0], 0) + len(data)
            problem = _image_problem(name, data)
            if problem:
                bad_image.append(f"{rel}: {problem}")
        check(f"{name}: every file has the pixels and the mode of its layer", not bad_image,
              f"{len(bad_image)} problems" + (f": {bad_image[0]}" if bad_image else ""))
        check(f"{name}: files and missing tiles together are the whole set", found | missing == expected_keys,
              f"{len(found)} files, {len(missing)} missing, {len(expected_keys)} in the set")
        check(f"{name}: file count matches the index", len(found) == expect_block["files"],
              f"{len(found)} files, index says {expect_block['files']}")
        check(f"{name}: bytes match the index", bytes_total == expect_block["bytes"],
              f"{bytes_total} bytes, index says {expect_block['bytes']}")
        check(f"{name}: bytes by zoom match the index", by_zoom == {k: v for k, v in expect_block["bytes_by_zoom"].items()},
              "")
    mismatched = [rel for rel, entry in stored_files.items() if listed.get(rel) != entry]
    check("manifest lists each base file with its bytes and SHA-256", not mismatched,
          f"{len(mismatched)} mismatches" + (f": {mismatched[0]}" if mismatched else ""))
    unlisted = [rel for rel in stored_files if rel not in listed]
    check("no base file is missing from the manifest", not unlisted, f"{len(unlisted)} unlisted")
    stale = sorted(k for k in listed if k.startswith((f"{BASE_DIR}/h/", f"{BASE_DIR}/l/")) and k not in stored_files)
    check("the manifest lists no tile file that is not on disk", not stale, f"{len(stale)} stale entries")
    total = block["bytes"]
    check("zooms 5 to 10 together are under the 20 MB budget", total < BUDGET_BYTES, f"{total} bytes")
    refetch = {"checked": 0, "match": 0, "within_tolerance": 0, "mismatch": 0, "failed": []}
    if not offline and sample > 0:
        candidates = sorted(stored_files)
        rng = random.Random(seed)
        picks = rng.sample(candidates, min(sample, len(candidates)))
        for rel in picks:
            outcome = _refetch_compare(store, rel, block, get=get, sleep=sleep, timeout=timeout)
            refetch["checked"] += 1
            if outcome.get("error"):
                refetch["failed"].append({"file": rel, "reason": outcome["error"]})
                continue
            refetch[outcome["result"]] += 1
        check("a seeded sample of tiles re-fetched matches the stored files",
              refetch["mismatch"] == 0 and not refetch["failed"],
              f"{refetch['match']} byte for byte, {refetch['within_tolerance']} within tolerance, "
              f"{refetch['mismatch']} mismatched, {len(refetch['failed'])} could not be re-fetched")
    ok = all(c["pass"] for c in checks)
    return {"ok": ok, "checks": checks, "counts": block["counts"], "bytes": total, "bytes_by_zoom": block["bytes_by_zoom"],
            "refetch": refetch}


def _image_problem(layer: str, data: bytes) -> str | None:
    try:
        im = _pil().open(io.BytesIO(data))
        im.load()
    except Exception:
        return "not a readable image"
    if im.size != (TILE_PX, TILE_PX):
        return f"{im.size[0]} by {im.size[1]} pixels"
    if layer == "h":
        if im.format != "JPEG" or im.mode != "L":
            return f"{im.format} {im.mode}, not a grey JPEG"
    else:
        if im.format != "PNG" or im.mode != "P" or im.info.get("transparency") != 0:
            return f"{im.format} {im.mode}, not a palette PNG with index 0 transparent"
        np = _np()
        values = np.unique(np.asarray(im))
        if np.any(values > len(TINT)):
            return "an index above the five tint classes"
    return None


def _refetch_compare(store: Path, rel: str, block: dict, *, get, sleep, timeout: float = TIMEOUT_S) -> dict:
    parts = Path(rel).parts                      # hail, base, h|l, z, x, y.ext
    layer = parts[2]
    z, x = int(parts[3]), int(parts[4])
    y = int(Path(parts[5]).stem)
    stored = (store / rel).read_bytes()
    try:
        if layer == "h":
            body, _tries = fetch_checked(SHADING_URL, shading_request(z, x, y), check_shading_png, get=get, sleep=sleep,
                                         timeout=timeout)
            draw = shading_jpeg(body)
            if draw == stored:
                return {"result": "match"}
            np = _np()
            a = np.asarray(_pil().open(io.BytesIO(draw)).convert("L"), dtype=np.int16)
            b = np.asarray(_pil().open(io.BytesIO(stored)).convert("L"), dtype=np.int16)
            if int(np.abs(a - b).max()) <= 1:
                return {"result": "within_tolerance"}
            return {"result": "mismatch"}
        body, _tries = fetch_checked(LAND_URL, land_request(z, x, y), check_land_tiff, get=get, sleep=sleep,
                                     timeout=timeout)
        draw = tint_png(body)
        if draw == stored:
            return {"result": "match"}
        np = _np()
        a = np.asarray(_pil().open(io.BytesIO(draw)))
        b = np.asarray(_pil().open(io.BytesIO(stored)))
        return {"result": "match" if np.array_equal(a, b) else "mismatch"}
    except TerrainError as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------- words for the site (the integrator's build reads them)

def describe(index: dict | None = None) -> dict:
    """The About text of the terrain layers: the two credit lines, the plain description, or the unavailable sentence."""
    block = _block_from(index)
    if block is None or block.get("state") == "unavailable":
        return {"title": "Terrain shading and land cover", "unavailable": True,
                "problem": WORDS["unavailable"], "what": WORDS["what"]}
    date_text = (block.get("as_of") or {}).get("shading_date") or "unknown"
    return {"title": "Terrain shading and land cover", "unavailable": False, "what": WORDS["what"],
            "shading_source": WORDS["shading_source"].format(date=date_text),
            "land_source": WORDS["land_source"]}


def map_data(index: dict | None = None) -> dict:
    """The map.json "base" block for the terrain layers: the tile templates, the zooms, the missing tiles of each layer,
    the palette and the words. Nothing here reads a file; the browser requests one tile at a time."""
    block = _block_from(index)
    words = {"tile_missing": WORDS["tile_missing"], "unavailable": WORDS["unavailable"],
             "part_unavailable": WORDS["part_unavailable"], "part_partial": WORDS["part_partial"], "what": WORDS["what"]}
    if block is None or block.get("state") == "unavailable":
        problem = (block or {}).get("problem") or WORDS["unavailable"]
        return {"state": "unavailable", "problem": problem, "words": words}
    layers = {}
    for name in LAYERS:
        info = (block.get("layers") or {}).get(name)
        if not info:
            continue
        layers[name] = {"state": info["state"], "template": info["path"], "missing": list(info["missing"]),
                        "files": info["files"], "problem": info.get("problem")}
    date_text = (block.get("as_of") or {}).get("shading_date") or "unknown"
    return {"state": block["state"], "problem": block.get("problem"), "zooms": list(block["zooms"]),
            "tile_px": TILE_PX, "layers": layers,
            "palette": [{"index": i, "class": name, "hex": colour} for i, name, colour, _codes in TINT],
            "as_of": block.get("as_of", {}), "words": words,
            "credits": {"shading": WORDS["shading_source"].format(date=date_text), "land_cover": WORDS["land_source"]}}


def _block_from(index: dict | None):
    if isinstance(index, dict) and isinstance(index.get(INDEX_KEY), dict):
        terrain = index[INDEX_KEY].get("terrain")
        if isinstance(terrain, dict):
            return terrain
    return None


# ---------------------------------------------------------------- command line

def _epoch_to_monotonic(epoch: float | None) -> float | None:
    if epoch is None:
        return None
    return time.monotonic() + (epoch - time.time())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.terrain",
                                     description="Terrain shading and land cover tint tiles (B6 product P1).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="fetch and draw the tiles, then write the index blocks and the manifest entries")
    b.add_argument("--store", required=True, help="the store directory that holds hail/")
    b.add_argument("--cache", default="terrain-cache", help="the download cache (raw source answers, keyed by as-of)")
    b.add_argument("--zooms", default="5-10", help="the zooms, such as 5-10 or 8 (the default is the whole set)")
    b.add_argument("--only", default="h,l", help="the layers to build: h (shading), l (land cover), or both")
    b.add_argument("--procs", type=int, default=PROCS, help="requests at a time (at most 4)")
    b.add_argument("--offline", action="store_true", help="make no requests; use the cache only")
    b.add_argument("--refresh", action="store_true", help="request every tile again (the monthly job)")
    b.add_argument("--deadline-at", type=float, default=None, help="epoch seconds: no request starts after this time")
    b.add_argument("--timeout", type=float, default=TIMEOUT_S,
                   help="seconds each request may take (default 20; 60 for zoom 5, whose land cover answers take 15 to 30 s)")
    v = sub.add_parser("verify", help="check the tiles, the index and the manifest; re-fetch a sample (exit 1 on a failure)")
    v.add_argument("--store", required=True)
    v.add_argument("--cache", default=None, help="accepted for symmetry with build; the re-fetch does not use the cache")
    v.add_argument("--sample", type=int, default=VERIFY_SAMPLE, help="tiles to re-fetch (default 10)")
    v.add_argument("--offline", action="store_true", help="make no requests (skips the re-fetch)")
    v.add_argument("--timeout", type=float, default=TIMEOUT_S, help="seconds each re-fetch request may take (default 20)")
    u = sub.add_parser("unavailable", help="mark the terrain layers unavailable with a reason and remove their files")
    u.add_argument("--store", required=True)
    u.add_argument("--reason", required=True, help="the plain reason the terrain layers are unavailable")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "build":
        only = tuple(part.strip() for part in args.only.split(",") if part.strip())
        if not only or any(part not in LAYERS for part in only):
            print("error: --only takes h, l or h,l", file=sys.stderr)
            return 2
        if not 5 <= args.timeout <= 120:
            print("error: --timeout takes seconds from 5 to 120", file=sys.stderr)
            return 2
        result = build(args.store, args.cache, zooms=_parse_zooms(args.zooms), only=only, offline=args.offline,
                       refresh=args.refresh, procs=min(max(1, args.procs), PROCS),
                       deadline_at=_epoch_to_monotonic(args.deadline_at), timeout=args.timeout)
        print(json.dumps(result, indent=1, sort_keys=True, default=str))
        return 0
    if args.cmd == "verify":
        result = verify(args.store, args.cache, sample=args.sample, offline=args.offline, timeout=args.timeout)
        print(json.dumps(result, indent=1, sort_keys=True, default=str))
        return 0 if result["ok"] else 1
    result = mark_unavailable(args.store, args.reason)
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
