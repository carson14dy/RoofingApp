#!/usr/bin/env python3
"""Proof of look for the Montana Hail Watch base map, drawn by Python from public-domain inputs.

This is a proof, not product code. It draws two pictures in the site's palette and font:

  region.png  a 390 x 844 CSS px phone frame at scale 2 (780 x 1688 px), Leaflet zoom 8.5,
              centred on the middle of the box -115.0,46.3,-113.2,47.4
  city.png    the Missoula box -114.15,46.78,-113.90,46.95 at zoom 12, scale 2

Steps (run each, or "all"):
  fetch      download every input into its own new folder; a file that exists is skipped
  render     draw region.png and city.png
  composite  owner reference on the left, proof on the right, one caption line each
  measure    sample tiles at zooms 5 to 12: bytes per layer, Montana tile counts, statewide estimate

Run with the hail-b1 environment, from any folder:
  /home/user/hail-b1/venv/bin/python -I /home/user/hail-b5/out/b6/cartography/render/proof_render.py all

Reads the site's basemap.json, towns.json and fonts from the website repo copy (read only).
Writes only under /home/user/hail-b5/out/b6/cartography/proof/.
Packages: numpy, Pillow, pyproj, pyogrio, requests (the hail-b1 environment); shapely and
fontTools with brotli (pip install --target <proof>/work/pylib shapely fonttools brotli).
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import os
import re
import sys
import time

LABEL = "/home/user/hail-b5/out/b6/cartography/proof"
REPO = "/home/user/wt/wt-b6"  # read only
BASEMAP = os.path.join(REPO, "website/static/map/basemap.json")
TOWNS = os.path.join(REPO, "website/towns.json")
FONT_SRC = os.path.join(REPO, "website/static/fonts")
FONT_DIR = os.path.join(LABEL, "work/fonts")
REFS = {  # the owner's two reference views, copied into the label folder (see reference/)
    "region": os.path.join(LABEL, "reference", "region-reference.jpg"),
    "city": os.path.join(LABEL, "reference", "city-reference.jpg"),
}
sys.path.append(os.path.join(LABEL, "work/pylib"))  # appended: the environment's numpy and Pillow come first

import numpy as np  # noqa: E402
import pyogrio  # noqa: E402
import requests  # noqa: E402
import shapely  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from pyproj import Transformer  # noqa: E402
from shapely.affinity import affine_transform  # noqa: E402
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box, shape  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

CIRC = 40075016.68557849  # metres around the equator in EPSG:3857
SS = 2  # vectors and text are drawn at 2x and reduced with LANCZOS
DPR = 2  # device pixels per CSS pixel (phone scale 2)
RESAMPLE = Image.Resampling
TO3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
TO4326 = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

# ---- the site's palette (website/static/style.css tokens) and the new soft colours ----
PAPER, WHITE, INK, INK600, INK300 = "#f7f6f2", "#ffffff", "#111c28", "#4d5d6e", "#c6ced7"
SKY700, VIOLET, GREEN_EDGE = "#1a5a9c", "#6b3fa0", "#4f7d3f"
WATER, RIVER, COUNTY = "#b9d9f2", "#8fc0f5", "#d3dae3"
CASING_I, CASING_US, CASING_MT = "#7f93ab", "#b9c3cf", "#c3ccd7"
CASING_LOCAL = "#d5dbe3"
LAND = {  # NLCD 2021 class code -> colour (soft green forest, cream developed land, blue water)
    0: PAPER, 11: WATER, 12: "#eef6fc", 21: "#f5f1e6", 22: "#f1ead6", 23: "#ece2c8", 24: "#e5d6b5",
    31: "#e9e3d4", 41: "#cde2c3", 42: "#cde2c3", 43: "#cde2c3", 52: "#e6ecd6", 71: "#eaf0dc",
    81: "#f0efd9", 82: "#f2efd0", 90: "#c5dfd2", 95: "#cfe6d6",
}
HILLSHADE_AMOUNT = 0.28  # the grey hillshade is multiplied in at this strength (low opacity)

REGION_CENTRE = (-114.10, 46.85)  # middle of -115.0,46.3,-113.2,47.4
REGION_ZOOM = 8.5
REGION_CSS = (390, 844)
CITY_BOX = (-114.15, 46.78, -113.90, 46.95)
CITY_ZOOM = 12
BOX_SPEC = (-115.0, 46.3, -113.2, 47.4)  # the owner's box, fetched at 1600 px wide as asked
NLCD_COVERAGE = "mrlc_display:NLCD_2021_Land_Cover_L48"
DEM_URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
NLCD_URL = "https://www.mrlc.gov/geoserver/mrlc_display/wcs"
AIANNH_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_aiannh_500k.zip"
PLACES_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_30_place_500k.zip"
TIGER_CO_ROADS_URL = "https://www2.census.gov/geo/tiger/TIGER2026/ROADS/tl_2026_30063_roads.zip"
PRISEC_URL = "https://www2.census.gov/geo/tiger/TIGER2026/PRISECROADS/tl_2026_30_prisecroads.zip"
FOREST_URL = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_ForestSystemBoundaries_01/MapServer/0/query"

_TRANSFORM_CACHE: dict = {}


def dl(folder: str, name: str = "") -> str:
    return os.path.join(LABEL, "dl", folder, name) if name else os.path.join(LABEL, "dl", folder)


def device_metres(zoom: float) -> float:
    """Metres per device pixel at a Leaflet zoom for 256 px tiles and the phone scale."""
    return CIRC / (256 * 2 ** zoom) / DPR


class Frame:
    """A picture's pixel grid in EPSG:3857, one final (1x) pixel per cell."""

    def __init__(self, name, bbox, W, H):
        self.name, self.bbox, self.W, self.H = name, bbox, W, H
        self.x0, self.y0, self.x1, self.y1 = bbox
        self.m = (self.x1 - self.x0) / W

    def ll_bounds(self):
        lon, lat = TO4326.transform([self.x0, self.x1, self.x0, self.x1], [self.y0, self.y0, self.y1, self.y1])
        return min(lon), min(lat), max(lon), max(lat)

    def to_px(self, g, lonlat=True):
        if lonlat:
            g = shapely.transform(g, _ll_to_3857)
        return affine_transform(g, [1 / self.m, 0, 0, -1 / self.m, -self.x0 / self.m, self.y1 / self.m])

    def point_px(self, lon, lat):
        x, y = TO3857.transform(lon, lat)
        return (x - self.x0) / self.m, (self.y1 - y) / self.m

    def clip_box(self, margin=0.0):
        return box(-margin, -margin, self.W + margin, self.H + margin)


def _ll_to_3857(c):
    x, y = TO3857.transform(c[:, 0], c[:, 1])
    return np.column_stack([x, y])


def frame_region() -> Frame:
    x, y = TO3857.transform(*REGION_CENTRE)
    m = device_metres(REGION_ZOOM)
    W, H = REGION_CSS[0] * DPR, REGION_CSS[1] * DPR
    return Frame("region", (x - W * m / 2, y - H * m / 2, x + W * m / 2, y + H * m / 2), W, H)


def frame_city() -> Frame:
    x0, y0 = TO3857.transform(CITY_BOX[0], CITY_BOX[1])
    x1, y1 = TO3857.transform(CITY_BOX[2], CITY_BOX[3])
    m = device_metres(CITY_ZOOM)
    W, H = round((x1 - x0) / m), round((y1 - y0) / m)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return Frame("city", (cx - W * m / 2, cy - H * m / 2, cx + W * m / 2, cy + H * m / 2), W, H)


# ------------------------------------------------------------------ fetch

def _check_magic(body: bytes, magic):
    if magic is None:
        return True
    return any(body.startswith(m) for m in magic)


def fetch_file(folder, name, url, params, note, magic):
    """Download once into the folder (created only when absent). Writes <name>.meta.json beside it."""
    d = dl(folder)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name)
    if os.path.exists(path):
        return path, "exists"
    t0 = time.time()
    last = None
    for attempt in range(6):  # the services answer HTTP 502 for a while under load; wait and retry
        try:
            r = requests.get(url, params=params, timeout=600)
            last = r
            if r.status_code == 200 and r.content and _check_magic(r.content, magic):
                break
        except requests.RequestException as exc:  # retry a dropped connection
            last = exc
        time.sleep(min(60, 5 * (attempt + 1)))
    if not (isinstance(last, requests.Response) and last.status_code == 200 and _check_magic(last.content, magic)):
        raise RuntimeError(f"download failed for {name}: {last if not isinstance(last, requests.Response) else last.status_code}")
    body = last.content
    with open(path, "wb") as fh:
        fh.write(body)
    meta = {"url": last.url, "http_status": last.status_code, "content_type": last.headers.get("content-type"),
            "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "seconds": round(time.time() - t0, 2),
            "fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "note": note}
    with open(path + ".meta.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    return path, "downloaded"


def bbox_str(b):
    return ",".join(f"{v:.6f}" for v in b)


def dem_params(frame: Frame):
    return {"bbox": bbox_str(frame.bbox), "bboxSR": 3857, "imageSR": 3857, "size": f"{frame.W},{frame.H}",
            "format": "png", "renderingRule": json.dumps({"rasterFunction": "Hillshade Gray"}), "f": "image"}


def nlcd_params(bbox, w, h):
    return {"service": "WCS", "version": "1.0.0", "request": "GetCoverage", "coverage": NLCD_COVERAGE,
            "crs": "EPSG:3857", "bbox": bbox_str(bbox), "width": w, "height": h, "format": "GeoTIFF",
            "response_crs": "EPSG:3857"}


def fetch_all():
    fr, fc = frame_region(), frame_city()
    done = {}
    done["box_1600"] = fetch_file(
        "3dep-box-1600", "box-1600.png", DEM_URL,
        {"bbox": ",".join(map(str, BOX_SPEC)), "bboxSR": 4326, "imageSR": 4326, "size": "1600,978", "format": "png",
         "renderingRule": json.dumps({"rasterFunction": "Hillshade Gray"}), "f": "image"},
        "owner box at 1600 px wide, 3DEP Hillshade Gray (checked: 1600 x 978, grey 0 to 255)", [b"\x89PNG"])
    done["dem_region"] = fetch_file("3dep-region-frame", "hillshade-region-780x1688.png", DEM_URL, dem_params(fr),
                                    "region frame at 1x", [b"\x89PNG"])
    done["dem_city"] = fetch_file("3dep-city", "hillshade-city-1456x1448.png", DEM_URL, dem_params(fc),
                                  "city box at 1x", [b"\x89PNG"])
    done["nlcd_region"] = fetch_file(
        "nlcd-region-frame", "nlcd-region-3x.tif", NLCD_URL, nlcd_params(fr.bbox, fr.W * 3, fr.H * 3),
        "region frame at 3x (mode taken down to 1x)", [b"II*\x00", b"MM\x00*"])
    done["nlcd_city"] = fetch_file(
        "nlcd-city", "nlcd-city-native.tif", NLCD_URL, nlcd_params(fc.bbox, 927, 922),
        "city box at about native 30 m cells", [b"II*\x00", b"MM\x00*"])
    done["aiannh"] = fetch_file("aiannh-national", "cb_2024_us_aiannh_500k.zip", AIANNH_URL, None,
                                "Census reservation outlines, national 1:500,000", [b"PK"])
    fq = {"where": "1=1", "geometry": bbox_str(fr.bbox), "geometryType": "esriGeometryEnvelope", "inSR": 3857,
          "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "outSR": 3857, "maxAllowableOffset": 60, "f": "json"}
    done["forest"] = fetch_file("forest-frame-json", "fs-forest-frame.json", FOREST_URL, fq,
                                "Forest Service administrative forests, region frame", [b"{"])
    done["places"] = fetch_file("census-places-mt", "cb_2024_30_place_500k.zip", PLACES_URL, None,
                                "Census places, Montana, 1:500,000", [b"PK"])
    done["roads_county"] = fetch_file("tiger-roads-missoula", "tl_2026_30063_roads.zip", TIGER_CO_ROADS_URL, None,
                                      "Census TIGER/Line roads, Missoula County", [b"PK"])
    done["roads_state"] = fetch_file("tiger-prisecroads-mt", "tl_2026_30_prisecroads.zip", PRISEC_URL, None,
                                     "Census primary and secondary roads, Montana", [b"PK"])
    for k, (p, status) in done.items():
        print(f"{k:14s} {status:10s} {os.path.getsize(p):>10d} bytes  {os.path.relpath(p, LABEL)}")


# ------------------------------------------------------------------ fonts

def ensure_fonts():
    os.makedirs(FONT_DIR, exist_ok=True)
    sys.path.append(os.path.join(LABEL, "work/pylib"))
    from fontTools.ttLib import TTFont  # noqa: E402  (fontTools with brotli reads the WOFF2 files)
    for w in (400, 600, 700):
        out = os.path.join(FONT_DIR, f"AtkinsonHyperlegibleNext-{w}.ttf")
        if not os.path.exists(out):
            f = TTFont(os.path.join(FONT_SRC, f"atkinson-hyperlegible-next-latin-{w}-normal.woff2"))
            f.flavor = None
            f.save(out)


_FONTS: dict = {}


def font(weight: int, px: float) -> ImageFont.FreeTypeFont:
    key = (weight, round(px * SS))
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype(os.path.join(FONT_DIR, f"AtkinsonHyperlegibleNext-{weight}.ttf"),
                                         int(round(px * SS)))
    return _FONTS[key]


# ------------------------------------------------------------------ loaders

def read_classes(path):
    return np.asarray(Image.open(path))  # palette index = NLCD class code (checked in the downloads)


def read_grey(path):
    return np.asarray(Image.open(path).convert("L"))


def read_zip_layer(zip_path, columns, bbox=None):
    src = "/vsizip/" + zip_path
    if bbox is None:
        _, tbl = pyogrio.read_arrow(src, columns=columns)
    else:
        _, tbl = pyogrio.read_arrow(src, columns=columns, bbox=bbox)
    d = tbl.to_pydict()
    geoms = [shapely.from_wkb(b) for b in d.pop("wkb_geometry")]
    return d, geoms


def load_basemap():
    with open(BASEMAP, encoding="utf-8") as fh:
        return json.load(fh)


def load_towns():
    with open(TOWNS, encoding="utf-8") as fh:
        return json.load(fh)


def load_census_places():
    d, geoms = read_zip_layer(dl("census-places-mt", "cb_2024_30_place_500k.zip"), ["NAME", "LSAD", "ALAND"])
    out = []
    for name, lsad, aland, g in zip(d["NAME"], d["LSAD"], d["ALAND"], geoms):
        p = g.representative_point()
        out.append({"name": name, "lsad": lsad, "aland": float(aland), "lon": p.x, "lat": p.y})
    return out


def load_forest(frame: Frame):
    with open(dl("forest-frame-json", "fs-forest-frame.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    out = []
    for ft in doc["features"]:
        g = None
        for ring in ft["geometry"]["rings"]:  # even-odd fill: holes and islands come out right
            p = Polygon(ring).buffer(0)
            g = p if g is None else g.symmetric_difference(p)
        out.append((ft["attributes"]["forestname"], frame.to_px(g, lonlat=False)))
    return out


def route_from_name(name):
    """Route keys from the Census road names: 'I- 90', 'US Hwy 93', 'State Hwy 200'."""
    if not name:
        return None
    n = name.strip()
    m = re.match(r"^I-\s*(\d+)$", n)
    if m:
        return ("I", m.group(1))
    m = re.match(r"^US Hwy (\d+)(?: [NSEW])?$", n)
    if m:
        return ("US", m.group(1))
    m = re.match(r"^State Hwy (\d+)(?: [NSEW])?$", n)
    if m:
        return ("MT", m.group(1))
    return None


def route_from_ref(ref):
    m = re.match(r"^(I|US)-(\d+)$", ref or "")
    return (m.group(1), m.group(2)) if m else None


def lines_of(g):
    if g.is_empty:
        return []
    if g.geom_type == "LineString":
        return [g]
    if g.geom_type in ("MultiLineString", "GeometryCollection"):
        out = []
        for part in g.geoms:
            out.extend(lines_of(part))
        return out
    return []


# ------------------------------------------------------------------ raster

def class_field(arr, W, H):
    """Class per final pixel: box average of one-hot classes when shrinking (the mode), bilinear when growing."""
    codes = [int(c) for c in np.unique(arr)]
    method = RESAMPLE.BOX if arr.shape[1] >= W else RESAMPLE.BILINEAR
    stack = np.zeros((len(codes), H, W), np.float32)
    for k, c in enumerate(codes):
        im = Image.fromarray(np.where(arr == c, 255, 0).astype(np.uint8))
        stack[k] = np.asarray(im.resize((W, H), method), np.float32) / 255.0
    return np.asarray(codes, np.int32)[stack.argmax(axis=0)]


def hex_rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def base_raster(cls, shade):
    lut = np.zeros((256, 3), np.float32)
    lut[:] = hex_rgb(PAPER)
    for code, colour in LAND.items():
        lut[code] = hex_rgb(colour)
    rgb = lut[cls]
    grey = shade.astype(np.float32) / 255.0
    factor = (1 - HILLSHADE_AMOUNT) + HILLSHADE_AMOUNT * (grey / grey.mean())
    factor = np.clip(factor, 0.7, 1.25)[..., None]
    return np.clip(rgb * factor, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------ drawing helpers

class Placer:
    """Keeps label and shield boxes (canvas pixels) apart."""

    def __init__(self, W, H):
        self.W, self.H = W * SS, H * SS
        self.boxes: list = []

    def free(self, b, pad=2.0):
        x0, y0, x1, y1 = b
        if x0 < 0 or y0 < 0 or x1 > self.W or y1 > self.H:
            return False
        p = pad * SS
        for bx0, by0, bx1, by1 in self.boxes:
            if x0 < bx1 + p and x1 > bx0 - p and y0 < by1 + p and y1 > by0 - p:
                return False
        return True

    def add(self, b):
        self.boxes.append(b)


def text_width(f, text, spacing=0.0):
    return f.getlength(text) + spacing * SS * max(len(text) - 1, 0)


def text_box(x, y, f, text, spacing=0.0, pad=1.0):
    asc, desc = f.getmetrics()
    w = text_width(f, text, spacing)
    return (x - pad * SS, y - asc - pad * SS, x + w + pad * SS, y + desc + pad * SS)


def draw_text(d, x, y, f, text, fill, halo=None, halo_w=0.0, spacing=0.0):
    """x, y: left baseline in canvas pixels. Letter spacing in final pixels."""
    sw = int(round(halo_w * SS)) if halo else 0
    if spacing == 0:
        d.text((x, y), text, font=f, fill=fill, anchor="ls", stroke_width=sw, stroke_fill=halo)
        return
    cx = x
    for ch in text:
        d.text((cx, y), ch, font=f, fill=fill, anchor="ls", stroke_width=sw, stroke_fill=halo)
        cx += f.getlength(ch) + spacing * SS


def draw_lines(d, geoms, colour, width):
    w = max(1, int(round(width * SS)))
    for g in geoms:
        for ln in lines_of(g):
            pts = [(x * SS, y * SS) for x, y in ln.coords]
            if len(pts) >= 2:
                d.line(pts, fill=colour, width=w, joint="curve")


def draw_dashed(d, geoms, colour, width, dash=12.0, gap=8.0):
    w = max(1, int(round(width * SS)))
    for g in geoms:
        for ln in lines_of(g):
            pts = [(x * SS, y * SS) for x, y in ln.coords]
            state_on, remain = True, dash * SS
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                seg = math.hypot(x1 - x0, y1 - y0)
                t = 0.0
                while seg - t > 1e-6:
                    step = min(remain, seg - t)
                    a = (x0 + (x1 - x0) * t / seg, y0 + (y1 - y0) * t / seg)
                    b = (x0 + (x1 - x0) * (t + step) / seg, y0 + (y1 - y0) * (t + step) / seg)
                    if state_on:
                        d.line([a, b], fill=colour, width=w)
                    t += step
                    remain -= step
                    if remain <= 1e-6:
                        state_on = not state_on
                        remain = (dash if state_on else gap) * SS


def pole_point(g, frame, step=10.0, tries=400):
    """Candidate anchor points inside a visible polygon, best (furthest from the edge) first."""
    vis = g.intersection(frame.clip_box(0))
    if vis.is_empty or vis.geom_type not in ("Polygon", "MultiPolygon"):
        return []
    bnd = vis.boundary
    minx, miny, maxx, maxy = vis.bounds
    scored = []
    for x in np.arange(minx, maxx, step):
        for y in np.arange(miny, maxy, step):
            p = Point(x, y)
            if vis.contains(p):
                scored.append((bnd.distance(p), (float(x), float(y))))
    scored.sort(key=lambda s: -s[0])
    return [s[1] for s in scored[:tries]]


def place_area_label(d, placer, anchors, lines, weight, px, fill, halo, spacing):
    f = font(weight, px)
    asc, desc = f.getmetrics()
    line_h = px * 1.25 * SS
    widths = [text_width(f, t, spacing) for t in lines]
    total_h = line_h * (len(lines) - 1) + asc + desc
    for ax, ay in anchors:
        cx, cy = ax * SS, ay * SS
        top = cy - total_h / 2
        boxes = []
        for i, t in enumerate(lines):
            base = top + asc + i * line_h
            boxes.append(text_box(cx - widths[i] / 2, base, f, t, spacing, pad=1))
        union = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        if placer.free(union, pad=3):
            placer.add(union)
            for i, t in enumerate(lines):
                draw_text(d, cx - widths[i] / 2, top + asc + i * line_h, f, t, fill, halo, 3.0, spacing)
            return True
    return False


def rotated_label(canvas, placer, cx, cy, text, weight, px, fill, halo, spacing, angle):
    """Text along a line: drawn on its own layer, rotated, pasted with its alpha."""
    f = font(weight, px)
    asc, desc = f.getmetrics()
    w = int(text_width(f, text, spacing)) + 12 * SS
    h = asc + desc + 12 * SS
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw_text(ImageDraw.Draw(layer), 6 * SS, 6 * SS + asc, f, text, fill, halo, 3.0, spacing)
    rot = layer.rotate(angle, resample=RESAMPLE.BICUBIC, expand=True)
    rw, rh = rot.size
    x0, y0 = int(round(cx * SS - rw / 2)), int(round(cy * SS - rh / 2))
    b = (x0, y0, x0 + rw, y0 + rh)
    if not placer.free(b, pad=1):
        return False
    canvas.paste(rot, (x0, y0), rot)
    placer.add(b)
    return True


def line_angle(ln, at):
    """Text angle (counter-clockwise, degrees, readable) along a line at a distance."""
    a = ln.interpolate(max(at - 8, 0))
    b = ln.interpolate(min(at + 8, ln.length))
    ang = math.degrees(math.atan2(-(b.y - a.y), b.x - a.x))
    if ang > 90:
        ang -= 180
    if ang <= -90:
        ang += 180
    return ang


def draw_shield(d, cx, cy, kind, num):
    """Shield centred on canvas pixels (cx, cy). I: blue. US and MT: white with an outline."""
    w, h = (44 * SS, 40 * SS) if kind != "MT" else (48 * SS, 36 * SS)
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    nf = font(700, 19 if len(num) <= 2 else 16)
    if kind == "I":
        poly = [(x0, y0), (x1, y0), (x1, y0 + 0.62 * h), (cx, y1), (x0, y0 + 0.62 * h)]
        d.polygon(poly, fill=SKY700, outline=WHITE, width=2 * SS)
        draw_text(d, cx - nf.getlength(num) / 2, cy + 6 * SS, nf, num, WHITE)
        return
    if kind == "US":
        poly = [(x0, y0), (x1, y0), (x1, y0 + 0.62 * h), (cx, y1), (x0, y0 + 0.62 * h)]
        d.polygon(poly, fill=WHITE, outline=INK, width=2 * SS)
    else:
        d.rounded_rectangle((x0, y0, x1, y1), radius=7 * SS, fill=WHITE, outline=INK600, width=2 * SS)
    top = "US" if kind == "US" else "MT"
    tf = font(400, 10)
    draw_text(d, cx - tf.getlength(top) / 2, y0 + 12 * SS, tf, top, INK)
    draw_text(d, cx - nf.getlength(num) / 2, y0 + 30 * SS, nf, num, INK)


def place_shields(d, placer, routes, W, H, per_route, spacing):
    """routes: {(kind, number): [LineString in final pixels]}. One or more shields per route."""
    placed = []
    centre = (W / 2, H / 2)
    for key, lines in sorted(routes.items()):
        cand = []
        for ln in lines:
            if ln.length < 60:
                continue
            for dist in np.arange(24, ln.length - 24, 5.0):
                p = ln.interpolate(dist)
                if 60 <= p.x <= W - 60 and 90 <= p.y <= H - 110:
                    cand.append((math.hypot(p.x - centre[0], p.y - centre[1]), p.x, p.y, ln, dist))
        cand.sort(key=lambda c: c[0])
        chosen = []
        for _, x, y, ln, dist in cand:
            if any(math.hypot(x - cx, y - cy) < spacing for cx, cy in chosen):
                continue
            b = (x * SS - 22 * SS, y * SS - 18 * SS, x * SS + 22 * SS, y * SS + 18 * SS)
            if not placer.free(b, pad=3):
                continue
            placer.add(b)
            chosen.append((x, y))
            placed.append((key, x, y))
            if len(chosen) >= per_route:
                break
    for (kind, num), x, y in placed:
        draw_shield(d, x * SS, y * SS, kind, num)
    return len(placed)


def credit_band(d, W, H, text):
    band = 30
    d.rectangle((0, (H - band) * SS, W * SS, H * SS), fill=PAPER)
    d.line([(0, (H - band) * SS), (W * SS, (H - band) * SS)], fill=INK300, width=2 * SS)
    f = font(400, 14)
    draw_text(d, 10 * SS, (H - 10) * SS, f, text, INK600)
    return (0, (H - band) * SS, W * SS, H * SS)


# ------------------------------------------------------------------ the two pictures

def draw_towns(d, placer, frame, towns, census, zoom):
    w, s, e, n = frame.ll_bounds()
    pad = 0.01
    rows = []
    site_names = set()
    for t in towns:
        site_names.add(t["name"])
        rows.append({"name": t["name"], "lon": t["lon"], "lat": t["lat"], "kind": "site", "aland": 1e12})
    for p in census:
        if p["name"] in site_names:
            continue
        kind = "incorporated" if p["lsad"] in ("25", "43", "47") else "cdp"
        rows.append({"name": p["name"], "lon": p["lon"], "lat": p["lat"], "kind": kind, "aland": p["aland"]})
    rows = [r for r in rows if w - pad <= r["lon"] <= e + pad and s - pad <= r["lat"] <= n + pad]
    order = {"site": 0, "incorporated": 1, "cdp": 2}
    rows.sort(key=lambda r: (order[r["kind"]], -r["aland"]))
    style = {"site": (700, 26, INK, 0), "incorporated": (600, 22, INK, 0), "cdp": (400, 19, INK600, 0)}
    shown = []
    for r in rows:
        px, py = frame.point_px(r["lon"], r["lat"])
        if not (4 <= px <= frame.W - 4 and 4 <= py <= frame.H - 4):
            continue
        weight, size, colour, _ = style[r["kind"]]
        f = font(weight, size)
        asc, desc = f.getmetrics()
        sx, sy = px * SS, py * SS
        tw = f.getlength(r["name"])
        base_y = sy + 0.35 * size * SS
        options = [
            (sx + 9 * SS, base_y),
            (sx - 9 * SS - tw, base_y),
            (sx - tw / 2, sy - 10 * SS),
            (sx - tw / 2, sy + 10 * SS + asc),
        ]
        for bx, by in options:
            b = (bx - 3 * SS, by - asc - 2 * SS, bx + tw + 3 * SS, by + desc + 2 * SS)
            if placer.free(b, pad=3):
                placer.add(b)
                r_dot = 6 if r["kind"] == "site" else 4.5
                d.ellipse((sx - (r_dot + 2) * SS, sy - (r_dot + 2) * SS, sx + (r_dot + 2) * SS, sy + (r_dot + 2) * SS), fill=WHITE)
                d.ellipse((sx - r_dot * SS, sy - r_dot * SS, sx + r_dot * SS, sy + r_dot * SS), fill=INK)
                draw_text(d, bx, by, f, r["name"], colour, WHITE, 3.0)
                shown.append(r["name"])
                break
    return shown


def draw_water_names(canvas, d, placer, frame, rivers, lakes, lonlat_zoom):
    names = []
    for geom, name, rank in rivers:
        if not name:
            continue
        best = None  # the longest visible piece of the river, labelled at its middle
        for ln in lines_of(geom):
            if ln.length >= 30 and (best is None or ln.length > best.length):
                best = ln
        if best is None:
            continue
        ln = best
        mid = ln.interpolate(ln.length / 2)
        angle = line_angle(ln, ln.length / 2) if frame.name == "city" else 0.0
        if frame.name == "city":
            if rotated_label(canvas, placer, mid.x, mid.y, name, 400, 17, SKY700, WHITE, 0.4, angle):
                names.append(name)
        else:
            tw = font(400, 19).getlength(name)
            bx, by = mid.x * SS - tw / 2, mid.y * SS
            fb = text_box(bx, by, font(400, 19), name, pad=2)
            if placer.free(fb, pad=3):
                placer.add(fb)
                draw_text(d, bx, by, font(400, 19), name, SKY700, WHITE, 3.0)
                names.append(name)
    for geom, name in lakes:
        if not name:
            continue
        anchors = pole_point(geom, frame)
        for ax, ay in anchors[:50]:
            f = font(400, 19)
            tw = f.getlength(name)
            bx, by = ax * SS - tw / 2, ay * SS
            fb = text_box(bx, by, f, name, pad=2)
            if placer.free(fb, pad=3):
                placer.add(fb)
                draw_text(d, bx, by, f, name, SKY700, WHITE, 3.0)
                names.append(name)
                break
    return names


def water_and_lines(d, frame, bm, zoom):
    counties = [frame.to_px(shape(ft["geometry"])) for ft in bm["counties"]["features"]]
    draw_lines(d, [c.intersection(frame.clip_box(2)) for c in counties], COUNTY, 1.2)
    lakes, rivers = [], []
    for ft in bm["lakes"]["features"]:
        if ft["properties"].get("min_zoom", 0) <= zoom:
            g = frame.to_px(shape(ft["geometry"])).intersection(frame.clip_box(2))
            if not g.is_empty:
                for poly in ([g] if g.geom_type == "Polygon" else list(getattr(g, "geoms", []))):
                    if poly.geom_type == "Polygon":
                        d.polygon([(x * SS, y * SS) for x, y in poly.exterior.coords], fill=WATER)
                lakes.append((g, ft["properties"].get("name")))
    for ft in bm["rivers"]["features"]:
        p = ft["properties"]
        if p.get("min_zoom", 0) <= zoom:
            g = frame.to_px(shape(ft["geometry"])).intersection(frame.clip_box(2))
            if not g.is_empty:
                rivers.append((g, p.get("name"), p.get("rank", 3)))
    widths = {1: 4.6, 2: 3.2, 3: 2.2}
    for rank in (3, 2, 1):
        draw_lines(d, [g for g, _, r in rivers if r == rank], RIVER, widths[rank])
    return rivers, lakes


def render_region(out_path):
    fr = frame_region()
    bm = load_basemap()
    cls = class_field(read_classes(dl("nlcd-region-frame", "nlcd-region-3x.tif")), fr.W, fr.H)
    shade = read_grey(dl("3dep-region-frame", "hillshade-region-780x1688.png"))
    base = base_raster(cls, shade)
    canvas = Image.fromarray(base).resize((fr.W * SS, fr.H * SS), RESAMPLE.BILINEAR)
    d = ImageDraw.Draw(canvas)
    placer = Placer(fr.W, fr.H)
    rivers, lakes = water_and_lines(d, fr, bm, REGION_ZOOM)
    # state routes, US and interstates from the Census primary and secondary roads (public domain)
    d_rows, rgeoms = read_zip_layer(dl("tiger-prisecroads-mt", "tl_2026_30_prisecroads.zip"),
                                    ["FULLNAME", "RTTYP", "MTFCC"], bbox=_bbox_ll(fr))
    roads = []
    for name, rtt, mtfcc, g in zip(d_rows["FULLNAME"], d_rows["RTTYP"], d_rows["MTFCC"], rgeoms):
        if rtt not in ("I", "U", "S") or mtfcc not in ("S1100", "S1200"):
            continue
        g2 = fr.to_px(g).intersection(fr.clip_box(2))
        if not g2.is_empty:
            roads.append((rtt, name, g2))
    for cls_, colour, width in (("S", CASING_MT, 5.6), ("U", CASING_US, 6.6), ("I", CASING_I, 7.8)):
        draw_lines(d, [g for c, _, g in roads if c == cls_], colour, width)
    for cls_, colour, width in (("S", WHITE, 3.4), ("U", WHITE, 4.4), ("I", WHITE, 5.0)):
        draw_lines(d, [g for c, _, g in roads if c == cls_], colour, width)
    # forests and reservations: dashed outlines, names in small capitals
    forests = load_forest(fr)
    draw_dashed(d, [g.boundary for _, g in forests], GREEN_EDGE, 2.2)
    aiannh_d, aiannh_g = read_zip_layer(dl("aiannh-national", "cb_2024_us_aiannh_500k.zip"), ["NAMELSAD", "GEOID"],
                                        bbox=_bbox_ll(fr))
    reserv = []
    for nm, g in zip(aiannh_d["NAMELSAD"], aiannh_g):
        g2 = fr.to_px(g).intersection(fr.clip_box(2))
        if not g2.is_empty:
            reserv.append((nm, g2))
    draw_dashed(d, [g.boundary for _, g in reserv], VIOLET, 2.6, dash=14, gap=7)
    shown_area = []
    for nm, g in reserv:
        anchors = pole_point(g, fr)
        if place_area_label(d, placer, anchors, [nm.upper()], 600, 19, INK600, PAPER, 2.2):
            shown_area.append(nm)
    for name, g in forests:
        pretty = name.replace(" National Forest", "").upper()
        lines = [pretty, "NATIONAL FOREST"]
        anchors = pole_point(g, fr)
        if place_area_label(d, placer, anchors, lines, 600, 19, INK600, PAPER, 2.2):
            shown_area.append(name)
    water_names = draw_water_names(canvas, d, placer, fr, rivers, lakes, REGION_ZOOM)
    towns = load_towns()
    census = load_census_places()
    shown_towns = draw_towns(d, placer, fr, towns, census, REGION_ZOOM)
    routes = {}
    for rtt, name, g in roads:
        key = route_from_name(name)
        if key:
            routes.setdefault(key, []).extend(lines_of(g))
    n_shields = place_shields(d, placer, routes, fr.W, fr.H, per_route=2, spacing=260)
    credit_band(d, fr.W, fr.H, "Relief USGS 3DEP. Land cover MRLC NLCD 2021. Roads Census TIGER 2026. Places Census.")
    img = canvas.resize((fr.W, fr.H), RESAMPLE.LANCZOS)
    img.save(out_path, optimize=True)
    return {"file": out_path, "size": [fr.W, fr.H], "areas": shown_area, "towns": shown_towns,
            "water_names": water_names, "shields": n_shields, "roads": len(roads), "forests": len(forests),
            "reservations": len(reserv)}


def _bbox_ll(fr: Frame):
    w, s, e, n = fr.ll_bounds()
    return (w, s, e, n)


def render_city(out_path):
    fc = frame_city()
    bm = load_basemap()
    cls = class_field(read_classes(dl("nlcd-city", "nlcd-city-native.tif")), fc.W, fc.H)
    shade = read_grey(dl("3dep-city", "hillshade-city-1456x1448.png"))
    base = base_raster(cls, shade)
    canvas = Image.fromarray(base).resize((fc.W * SS, fc.H * SS), RESAMPLE.BILINEAR)
    d = ImageDraw.Draw(canvas)
    placer = Placer(fc.W, fc.H)
    rivers, lakes = water_and_lines(d, fc, bm, CITY_ZOOM)
    d_rows, geoms = read_zip_layer(dl("tiger-roads-missoula", "tl_2026_30063_roads.zip"),
                                   ["FULLNAME", "MTFCC"], bbox=_bbox_ll(fc))
    roads = []
    for name, mtfcc, g in zip(d_rows["FULLNAME"], d_rows["MTFCC"], geoms):
        if mtfcc not in ("S1100", "S1200", "S1400", "S1630"):
            continue
        g2 = fc.to_px(g).intersection(fc.clip_box(2))
        if not g2.is_empty:
            roads.append((mtfcc, name, g2))
    order = [("S1400", CASING_LOCAL, 3.6, WHITE, 2.0), ("S1630", CASING_LOCAL, 3.6, WHITE, 2.0),
             ("S1200", CASING_US, 5.2, WHITE, 3.4), ("S1100", CASING_I, 7.2, WHITE, 4.6)]
    for mt, casing, cw, _, _ in order:
        draw_lines(d, [g for m, _, g in roads if m == mt], casing, cw)
    for mt, _, _, fill, fw in order:
        draw_lines(d, [g for m, _, g in roads if m == mt], fill, fw)
    # street names along the longest named streets (not the route shields)
    named = {}
    for mt, name, g in roads:
        if name and mt in ("S1200", "S1100", "S1400") and not re.search(r"Hwy|State|Bus|Co Rd|^I-", name):
            named.setdefault(name, []).extend(lines_of(g))
    street_names = []
    for name, lines in sorted(named.items(), key=lambda kv: -sum(l.length for l in kv[1]))[:18]:
        best = max(lines, key=lambda l: l.length)
        if best.length < 120 * 1.0:
            continue
        at = best.length / 2
        p = best.interpolate(at)
        if not (80 <= p.x <= fc.W - 80 and 80 <= p.y <= fc.H - 80):
            continue
        ang = line_angle(best, at)
        if abs(ang) > 40:
            continue
        if rotated_label(canvas, placer, p.x, p.y, name.upper(), 600, 14, INK600, WHITE, 1.3, ang):
            street_names.append(name)
    water_names = draw_water_names(canvas, d, placer, fc, rivers, lakes, CITY_ZOOM)
    towns = load_towns()
    census = load_census_places()
    shown_towns = draw_towns(d, placer, fc, towns, census, CITY_ZOOM)
    routes = {}
    for mt, name, g in roads:
        key = route_from_name(name)
        if key:
            routes.setdefault(key, []).extend(lines_of(g))
    n_shields = place_shields(d, placer, routes, fc.W, fc.H, per_route=1, spacing=200)
    credit_band(d, fc.W, fc.H, "Roads Census TIGER 2026. Rivers Natural Earth. Relief USGS 3DEP. Land cover MRLC NLCD 2021.")
    img = canvas.resize((fc.W, fc.H), RESAMPLE.LANCZOS)
    img.save(out_path, optimize=True)
    return {"file": out_path, "size": [fc.W, fc.H], "towns": shown_towns, "water_names": water_names,
            "street_names": street_names, "shields": n_shields, "roads": len(roads)}


def render_all():
    ensure_fonts()
    info = {}
    info["region"] = render_region(os.path.join(LABEL, "region.png"))
    info["city"] = render_city(os.path.join(LABEL, "city.png"))
    print(json.dumps(info, indent=1, ensure_ascii=False))
    return info


# ------------------------------------------------------------------ composite

def composite_all():
    ensure_fonts()
    specs = [
        ("region", REFS["region"], os.path.join(LABEL, "region.png"), os.path.join(LABEL, "composite-region.png"),
         "Left: owner reference (region). Right: proof at zoom 8.5, phone frame 390 by 844 at scale 2."),
        ("city", REFS["city"], os.path.join(LABEL, "city.png"), os.path.join(LABEL, "composite-city.png"),
         "Left: owner reference (wider city). Right: proof of Missoula at zoom 12, scale 2."),
    ]
    out = {}
    for key, ref_path, ours_path, out_path, caption in specs:
        ref = Image.open(ref_path).convert("RGB")
        ours = Image.open(ours_path).convert("RGB")
        H = 1200
        a = ref.resize((round(ref.width * H / ref.height), H), RESAMPLE.LANCZOS)
        b = ours.resize((round(ours.width * H / ours.height), H), RESAMPLE.LANCZOS)
        margin, gap, cap_h = 24, 24, 70
        W = margin * 2 + a.width + gap + b.width
        canvas = Image.new("RGB", (W, cap_h + H + margin), PAPER)
        d = ImageDraw.Draw(canvas)
        d.text((margin, 22), caption, font=ImageFont.truetype(os.path.join(FONT_DIR, "AtkinsonHyperlegibleNext-600.ttf"), 26), fill=INK, anchor="la")
        canvas.paste(a, (margin, cap_h))
        canvas.paste(b, (margin + a.width + gap, cap_h))
        canvas.save(out_path, optimize=True)
        out[key] = {"file": out_path, "size": [W, cap_h + H + margin], "caption": caption}
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return out


# ------------------------------------------------------------------ measure

SAMPLE_PER_ZOOM = 6  # stratified sample of Montana tiles per zoom; every tile when there are fewer
MEASURE_ZOOMS = list(range(5, 13))
LAYERS_STATEWIDE = ["tint_png", "shade_png", "base_png", "base_webp", "vector_json", "vector_gzip"]


def tile_index(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lr = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lr) + 1.0 / math.cos(lr)) / math.pi) / 2.0 * n)
    return x, y


def tile_box3857(x, y, z):
    size = CIRC / 2 ** z
    x0 = -CIRC / 2 + x * size
    y1 = CIRC / 2 - y * size
    return (x0, y1 - size, x0 + size, y1)


def tile_box_ll(x, y, z):
    x0, y0, x1, y1 = tile_box3857(x, y, z)
    lon, lat = TO4326.transform([x0, x1, x0, x1], [y0, y0, y1, y1])
    return min(lon), min(lat), max(lon), max(lat)


def mt_polygon_3857():
    bm = load_basemap()
    geoms = [shape(ft["geometry"]) for ft in bm["land"]["features"] if ft["properties"].get("montana")]
    return shapely.transform(unary_union(geoms), _ll_to_3857)


def touching_tiles(poly, z):
    """(bounding-box tile count, [(x, y) of every tile that touches the Montana outline])."""
    minx, miny, maxx, maxy = poly.bounds
    size = CIRC / 2 ** z
    x0 = int(math.floor((minx + CIRC / 2) / size))
    x1 = int(math.floor((maxx + CIRC / 2) / size))
    y0 = int(math.floor((CIRC / 2 - maxy) / size))
    y1 = int(math.floor((CIRC / 2 - miny) / size))
    shapely.prepare(poly)
    out = []
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if poly.intersects(box(*tile_box3857(x, y, z))):
                out.append((x, y))
    return (x1 - x0 + 1) * (y1 - y0 + 1), out


def stratified(tiles, k, seed=7):
    """One random tile from each cell of a 2 x 3 grid over the state (all tiles when there are at most k)."""
    if len(tiles) <= k:
        return sorted(tiles)
    xs = [t[0] for t in tiles]
    ys = [t[1] for t in tiles]
    x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
    rng = np.random.default_rng(seed)
    chosen = []
    for r in range(3):
        for c in range(2):
            cell = [t for t in tiles
                    if int((t[0] - x0) * 2 / (x1 - x0)) == c and int((t[1] - y0) * 3 / (y1 - y0)) == r]
            if cell:
                chosen.append(cell[int(rng.integers(len(cell)))])
    return chosen


def keep_lines_polygons(g):
    """One family of parts (lines or polygons) from a clipped geometry; points and empty parts are dropped."""
    lines_k = ("LineString", "MultiLineString")
    polys_k = ("Polygon", "MultiPolygon")
    if g.geom_type in lines_k + polys_k:
        return None if g.is_empty else g
    if g.geom_type == "GeometryCollection":
        parts = [p for p in g.geoms if not p.is_empty]
        lines = [p for p in parts if p.geom_type in lines_k]
        polys = [p for p in parts if p.geom_type in polys_k]
        family = lines if lines else polys
        return unary_union(family) if family else None
    return None


def round_coords(g):
    gj = shapely.geometry.mapping(g)

    def rr(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], 4), round(c[1], 4)]
        return [rr(x) for x in c]
    return {"type": gj["type"], "coordinates": rr(gj["coordinates"])}


_BM = {}


def vector_tile_bytes(z, ll_box):
    if "bm" not in _BM:
        _BM["bm"] = load_basemap()
    bm = _BM["bm"]
    clip = box(*ll_box)
    feats = []
    for layer in ("rivers", "lakes", "counties", "roads", "borders"):
        for ft in bm[layer]["features"]:
            mz = ft["properties"].get("min_zoom")
            if layer == "counties":
                mz = 7  # the base map draws county lines from zoom 7
            if mz is not None and mz > z:
                continue
            g = shape(ft["geometry"])
            if not g.intersects(clip):
                continue
            g = keep_lines_polygons(g.intersection(clip))
            if g is None or g.is_empty:
                continue
            feats.append({"layer": layer, "props": ft["properties"], "geom": round_coords(g)})
    raw = json.dumps(feats, separators=(",", ":")).encode("utf-8")
    return len(raw), len(gzip.compress(raw, 9)), len(feats)


def png_bytes(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def webp_size(arr):
    buf = io.BytesIO()
    try:
        Image.fromarray(arr).save(buf, format="WEBP", quality=80, method=4)
    except Exception:  # WebP not built into this Pillow
        return None
    return len(buf.getvalue())


def tint_only(cls):
    lut = np.zeros((256, 3), np.uint8)
    lut[:] = hex_rgb(PAPER)
    for code, colour in LAND.items():
        lut[code] = hex_rgb(colour)
    return lut[cls]


def fetch_samples(z, tiles):
    """Download the NLCD and 3DEP 256 px tiles for one zoom, six at a time, into one new folder per zoom."""
    folder = f"sample-z{z:02d}"

    def job(item):
        i, (x, y) = item
        bb = tile_box3857(x, y, z)
        fr = Frame(f"s{z}-{i}", bb, 256, 256)
        n, _ = fetch_file(folder, f"nlcd-{i}.tif", NLCD_URL, nlcd_params(bb, 256, 256),
                          f"sample tile z{z} tile {x},{y}: WCS nearest sampling of the NLCD grid",
                          [b"II*\x00", b"MM\x00*"])
        d, _ = fetch_file(folder, f"dem-{i}.png", DEM_URL, dem_params(fr),
                          f"sample tile z{z} tile {x},{y}: 3DEP Hillshade Gray", [b"\x89PNG"])
        return n, d

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as ex:
        return list(ex.map(job, list(enumerate(tiles))))


def measure_tile(z, xy, nlcd_p, dem_p):
    x, y = xy
    cls = read_classes(nlcd_p)
    shade = read_grey(dem_p)
    base = base_raster(cls, shade)
    vb, vz, nf = vector_tile_bytes(z, tile_box_ll(x, y, z))
    return {
        "tile": [z, x, y],
        "nlcd_tif_bytes": os.path.getsize(nlcd_p),
        "dem_png_bytes_from_service": os.path.getsize(dem_p),
        "tint_png": len(png_bytes(tint_only(cls))),
        "shade_png": len(png_bytes(shade)),
        "base_png": len(png_bytes(base)),
        "base_webp": webp_size(base),
        "vector_json": vb,
        "vector_gzip": vz,
        "vector_features": nf,
    }


def measure_all():
    ensure_fonts()
    poly = mt_polygon_3857()
    stat, samples, counts = {}, {}, {}
    for z in MEASURE_ZOOMS:
        n_bbox, tiles = touching_tiles(poly, z)
        counts[z] = {"bbox_tiles": n_bbox, "tiles_touching_montana": len(tiles)}
        chosen = stratified(tiles, SAMPLE_PER_ZOOM)
        files = fetch_samples(z, chosen)
        rows = [measure_tile(z, xy, n, d) for xy, (n, d) in zip(chosen, files)]
        samples[z] = rows
        n_touch = len(tiles)
        mean, low, high = {}, {}, {}
        for layer in LAYERS_STATEWIDE:
            vals = [r[layer] for r in rows if r[layer] is not None]
            mean[layer] = sum(vals) / len(vals)
            low[layer] = min(vals)
            high[layer] = max(vals)
        stat[z] = {"tiles_touching_montana": n_touch, "sample_tiles": len(rows),
                   "mean_bytes_per_tile": mean, "min_sample_bytes": low, "max_sample_bytes": high,
                   "statewide_bytes_from_mean": {k: round(v * n_touch) for k, v in mean.items()},
                   "statewide_bytes_range": {k: [round(low[k] * n_touch), round(high[k] * n_touch)]
                                             for k in LAYERS_STATEWIDE}}
        print("z", z, counts[z], "sample", len(rows), {k: round(mean[k]) for k in LAYERS_STATEWIDE}, flush=True)
    totals = {layer: sum(stat[z]["statewide_bytes_from_mean"][layer] for z in MEASURE_ZOOMS)
              for layer in LAYERS_STATEWIDE}
    tiles_total = sum(stat[z]["tiles_touching_montana"] for z in MEASURE_ZOOMS)
    frames = {}
    for key, fr, cls_path, shade_path, out_png in (
            ("region", frame_region(), dl("nlcd-region-frame", "nlcd-region-3x.tif"),
             dl("3dep-region-frame", "hillshade-region-780x1688.png"), os.path.join(LABEL, "region.png")),
            ("city", frame_city(), dl("nlcd-city", "nlcd-city-native.tif"),
             dl("3dep-city", "hillshade-city-1456x1448.png"), os.path.join(LABEL, "city.png"))):
        cls = class_field(read_classes(cls_path), fr.W, fr.H)
        shade = read_grey(shade_path)
        base = base_raster(cls, shade)
        frames[key] = {"size": [fr.W, fr.H], "tint_png": len(png_bytes(tint_only(cls))),
                       "shade_png": len(png_bytes(shade)), "base_png": len(png_bytes(base)),
                       "base_webp": webp_size(base), "final_picture_png": os.path.getsize(out_png)}
    downloads = []
    for root, _, files in os.walk(dl(".")):
        for f in files:
            if f.endswith(".meta.json") or f == "headers.txt":
                continue
            p = os.path.join(root, f)
            downloads.append({"path": os.path.relpath(p, LABEL), "bytes": os.path.getsize(p)})
    downloads.sort(key=lambda r: r["path"])
    result = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "sampling": f"stratified: up to {SAMPLE_PER_ZOOM} tiles per zoom, one random tile in each cell of a 2 x 3 grid over the tiles touching Montana; all tiles at zoom 5",
              "counts": {str(z): counts[z] for z in MEASURE_ZOOMS},
              "statewide": {str(z): stat[z] for z in MEASURE_ZOOMS},
              "statewide_totals_from_mean": totals, "tiles_z5_to_z12": tiles_total,
              "samples": {str(z): samples[z] for z in MEASURE_ZOOMS},
              "frames": frames, "downloads": downloads}
    out = os.path.join(LABEL, "measurements.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    print("wrote", out)
    print(json.dumps({"tiles_z5_to_z12": tiles_total, "statewide_totals_from_mean": totals}, indent=1))
    return result


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description="Proof of look for the Montana Hail Watch base map.")
    ap.add_argument("step", choices=["fetch", "render", "composite", "measure", "all"])
    args = ap.parse_args(argv)
    if args.step in ("fetch", "all"):
        fetch_all()
    if args.step in ("render", "all"):
        render_all()
    if args.step in ("composite", "all"):
        composite_all()
    if args.step in ("measure", "all"):
        measure_all()


if __name__ == "__main__":
    main()
