#!/usr/bin/env python3
"""
Rebuild website/static/map/basemap.json, the vector base map under the full-screen map (map.html).

Run by hand when the base map should change. The output is committed; the website build only
serves it and never runs this tool.

    python tools/build_basemap.py                          # download to a temp dir, write the JSON
    python tools/build_basemap.py --src DIR --preview basemap.png   # keep downloads; draw a check image
    python tools/build_basemap.py --src DIR --check        # exit 1 if the committed file is out of date

Sources (both public domain), pinned by hash so a rerun writes the same bytes:
- Natural Earth 10 m GeoJSON, tag v5.1.2 (raw.githubusercontent.com/nvkelso/natural-earth-vector):
  admin-1 states/provinces (used for Canada and for state/province abbreviations), lakes plus the
  North America lakes supplement, rivers and lake centrelines plus the North America rivers
  supplement, roads, populated places.
- us-atlas 3.0.1 (registry.npmjs.org; the tarball `npm pack us-atlas@3.0.1` fetches, checked
  against its npm integrity hash): counties-10m.json, the U.S. Census Bureau cartographic boundary
  files (2017) as TopoJSON. The package itself is ISC-licensed; the data is public domain.

Why US states come from the Census topology and not Natural Earth: county lines must meet the
state lines exactly. In the TopoJSON the state outlines are merged from the same arcs as the
counties, so every Montana county line ends on the Montana outline. (Natural Earth's Montana is
0.7 km off the Census outline on average, up to 3.5 km, and puts the 49th parallel at 48.9925.)

Steps
1. Decode the TopoJSON: each arc is quantized and delta-encoded (x += dx, y += dy, then
   lon = x * scale + translate); a negative index ~i means arc i reversed.
2. Snap the US–Canada border on both sides to exactly 49° so the US and Canadian polygons meet
   without a gap or an overlap (moves points at most 1.3 km; the Census line is within 0.3 km).
3. Split the Canadian polygons into shared arcs (a point is a junction where the neighbouring
   points differ between rings), so a border shared by two provinces is simplified once.
4. Simplify each arc once (Douglas–Peucker), so neighbours keep identical borders; then clip to
   the map image bounds padded by 0.5° and round to 4 decimals (about 11 m).
5. Place labels and give every label and place a min_zoom from a collision check at zooms 5–11
   against the site-town bubbles, so labels never cover each other or a bubble. The map's first view
   shows only a thin strip of Canada on a wide screen, so CANADA, AB, SK and BC each come twice: from
   zoom 6 just north of the border, and at zoom 5 (phones) higher up (see BORDER_STRIP).

Output (one JSON object, one feature per line so diffs stay readable):
  version, bounds (the clip box), image_bounds, sources (attribution),
  land      polygons: name, abbrev, admin, montana (bool)
  borders   lines without the clip-box edges: kind "country" | "state", montana (bool)
  counties  Montana county lines, each shared arc once, interior only: between [county, county]
  lakes     polygons: name, min_zoom          rivers  lines: name, rank 1-3, min_zoom
  roads     lines: ref ("I-90", "US-2"), type ("interstate" | "us"), min_zoom
  labels    {text, lat, lon, kind, min_zoom[, max_zoom]}: the text is centred on lat/lon;
            kinds country, region, region-main, water; max_zoom is a hint (it was checked to
            stay clear up to zoom 11 anyway). CANADA, AB, SK and BC appear twice, one with
            max_zoom 5: hide a label above its max_zoom, or both copies show (still clear of all)
  places    {name, lat, lon, rank 1-4, min_zoom 5-9, state[, site, slug]}: a dot with the name to
            its right; site towns (website/towns.json) are rank 1 with site: true and are drawn
            by the map as bubbles, not by the base map
Stroke land outlines from `borders`, not from the land polygons: the polygons are cut at the clip
box, and their edges there are not borders. Draw lakes above rivers.

Label spacing assumes the sizes in LABEL_METRICS / PLACE_* / TOWN_* below (12 px uppercase region
and country names, 22 px letter-spaced "MONTANA", 11 px italic water names, 12 px place names right
of a 6 px dot, 30 px town bubbles with 13 px bold names on the towns.json side). If map.css draws
labels much larger, change the numbers and rerun; tests/test_basemap.py runs the same layout check.

Needs Python 3.10+ and numpy (label placement); Pillow only for --preview. No shapely: clipping and
simplification are done here in plain Python.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import math
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "website" / "static" / "map" / "basemap.json"
TOWNS = ROOT / "website" / "towns.json"

# The radar/model image grid (map spec; website/gridded.py IMAGE_BOUNDS): ((south, west), (north, east)).
IMAGE_BOUNDS = ((43.0, -118.5), (50.5, -101.0))
PAD = 0.5
BOX = (IMAGE_BOUNDS[0][0] - PAD, IMAGE_BOUNDS[0][1] - PAD, IMAGE_BOUNDS[1][0] + PAD, IMAGE_BOUNDS[1][1] + PAD)
IMG = (IMAGE_BOUNDS[0][0], IMAGE_BOUNDS[0][1], IMAGE_BOUNDS[1][0], IMAGE_BOUNDS[1][1])  # (s, w, n, e)
BUDGET = 450_000  # bytes, uncompressed
DECIMALS = 4

NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/{}.geojson"
NE_SHA256 = {
    "ne_10m_admin_1_states_provinces": "22d0e3ad85eb3e27f17cabf8ba2d50e554fbc27a87796ff891d958185da62fb5",
    "ne_10m_lakes": "2d036f53dedec578001c5c30c2959ee7d4eebc1306900fa4367c49929ec8f2d9",
    "ne_10m_lakes_north_america": "76f49d4b698f3529e690136a989713bcd3c028ade150346f4b358de9815cfc43",
    "ne_10m_rivers_lake_centerlines": "bb854a900ecbd3b408df46d5e16e3e0f974ba55993f9d8b5c26e855273c0905a",
    "ne_10m_rivers_north_america": "dcd2348655a5f3d0ea7be35024073ab24f09115d2e4efb77e7bc0a33567db682",
    "ne_10m_roads": "66a0c7b438e92fd124822cc5921cfa11042f48c294ade5e0f03f2c6640fd0248",
    "ne_10m_populated_places_simple": "fd3fa867a320cbd5c5b6bb5bc550afeec2939fb2cef688e508007282a55ac42f",
}
US_ATLAS_URL = "https://registry.npmjs.org/us-atlas/-/us-atlas-3.0.1.tgz"
US_ATLAS_INTEGRITY = ("sha512-wEIZCq0ImPvGblTd8gZMqNNCPkQshugMUG/8nkSWXb02+XqNFREg9atHOKP9w6prLZTpqcLhSv"
                      "dBW81MkV3/0Q==")
SOURCES = [
    "Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com (public domain; "
    "v5.1.2: provinces, lakes, rivers, roads, places).",
    "U.S. Census Bureau cartographic boundary files, 2017 (public domain): states and counties, "
    "via the us-atlas 3.0.1 TopoJSON (ISC licence).",
]

# Douglas-Peucker tolerances in degrees of latitude (longitude scaled by cos 47°): 0.001 is ~110 m,
# under one screen pixel up to zoom 10 at Montana's latitude.
TOL = {"us": 0.0006, "canada": 0.0012, "lakes": 0.0012, "rivers": 0.0018, "roads": 0.0020}
KX = math.cos(math.radians(47.0))

BORDER_LAT = 49.0
BORDER_SNAP = 0.012              # degrees; the Census line is within 0.003, Natural Earth's within 0.008
BORDER_LON = (-123.32, -95.15)   # where the US–Canada border follows the 49th parallel

ZOOMS = range(5, 12)             # the map's zoom range
PLACE_ZOOMS = range(5, 10)       # a place shows from its min_zoom, at the latest 9
# Label boxes used for spacing, approximating map.css (px): per character width, height.
LABEL_METRICS = {"country": (10.0, 16.0), "region": (9.5, 15.0), "region-main": (21.0, 26.0),
                 "water": (6.3, 14.0)}
PLACE_CHAR, PLACE_H, PLACE_DOT = 6.8, 15.0, 3.0      # 12 px place names, right of a 6 px dot
# Town bubbles and names as map.js drawTowns and map.css .town draw them (tests/test_basemap.py checks
# the CSS still says so): a 30 px bubble on the point; the name 13 px bold with line-height 1, its near
# edge 35 px from the 30 px icon's far edge, i.e. 20 px from the point, on the side towns.json gives.
BUBBLE_R, TOWN_NAME_OFF, TOWN_H = 15.0, 20.0, 13.0
TOWN_LABEL_W = {"Billings": 45.8, "Bozeman": 55.6, "Butte": 32.7, "Glasgow": 51.9, "Glendive": 53.7,
                "Great Falls": 66.5, "Havre": 35.0, "Helena": 42.4, "Kalispell": 53.4,
                "Lewistown": 63.6, "Livingston": 63.2, "Miles City": 61.1, "Missoula": 54.6,
                "West Yellowstone": 106.6}         # .tname widths measured in Chromium; others estimated wide
# At zoom 5 a town name may reach this far (px) into another town's bubble: Missoula's runs 3.5 px into
# Kalispell's, Billings' 1.0 px into Miles City's. No choice of label sides clears zoom 5 (Missoula or
# Billings below their bubble hits Bozeman's or West Yellowstone's name, and the ID label), and the map
# opens there only when it is narrower than about 340 px or very short; from zoom 5.25 all are clear.
TOUCH_Z5 = 4.0
GAP = 3.0                                           # px kept clear between boxes
LABEL_GAP = 28.0                                    # px between two text labels, so "CANADA" and "SK" read apart

# The map opens on Montana, fitted between the legend, the buttons and the timeline (map.js fitView).
# On a wide screen (zoom 6 and up) that first view shows only a thin strip of Canada along the border:
# it reaches just 49.2-49.3° N at 1440x789, 1920x937 and 1920x1080 with no banner (measured in Chromium).
# A phone (zoom 5) shows Canada far to the north, but at 412 px only from 116.45° W to 103.65° W. So each
# Canadian label comes twice: from zoom 6 in BORDER_STRIP, as far south as it fits, and at zoom 5
# (max_zoom 5) anywhere in PHONE_STRIP. At zoom 5 the low strip has no room for all four: Havre's
# bubble reaches the border there. Like every label, both are kept clear of everything up to zoom 11.
BORDER_STRIP = (IMG[0], -116.0, 49.45, -104.1)    # (s, w, n, e)
PHONE_STRIP = (IMG[0], -116.0, IMG[2], -104.1)
CANADA = ("BC", "AB", "SK", "MB")

# Region and country labels: text, kind, the land abbrevs the label must sit inside, min_zoom, max_zoom
# (a hint, see the module docstring), and where: "centre" (near the area's centroid, with room around
# it), "border" (in BORDER_STRIP, as far south as it fits) or "phone" (in PHONE_STRIP, near its
# centroid). A label that does not fit in its strip goes anywhere in its area, with a note. The
# Canadian labels go west to east: at zoom 5 the four only just fit side by side in PHONE_STRIP.
AREA_LABELS = [
    ("MONTANA", "region-main", ("MT",), 5, 7, "centre"),
    ("UNITED STATES", "country", ("ID", "WY"), 5, 6, "centre"),
    ("ID", "region", ("ID",), 5, None, "centre"),
    ("WY", "region", ("WY",), 5, None, "centre"),
    ("ND", "region", ("ND",), 5, None, "centre"),
    ("SD", "region", ("SD",), 5, None, "centre"),
    ("BC", "region", ("BC",), 6, None, "border"),
    ("AB", "region", ("AB",), 6, None, "border"),
    ("CANADA", "country", CANADA, 6, None, "border"),
    ("SK", "region", ("SK",), 6, None, "border"),
    ("BC", "region", ("BC",), 5, 5, "phone"),
    ("AB", "region", ("AB",), 5, 5, "phone"),
    ("CANADA", "country", CANADA, 5, 5, "phone"),
    ("SK", "region", ("SK",), 5, 5, "phone"),
    ("WA", "region", ("WA",), 6, None, "centre"),
    ("OR", "region", ("OR",), 6, None, "centre"),
]
NAME_FIXES = {"Coeur D'Alene Lake": "Coeur d'Alene Lake", "Pend Orielle": "Pend Oreille"}


# ---------------------------------------------------------------- downloads

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sri512(data: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()


def fetch(url: str, dest: Path, check) -> bytes:
    """The file at url, cached at dest; check(data) -> error text or None (a pinned hash)."""
    if dest.exists():
        data = dest.read_bytes()
        if check(data) is None:
            return data
    print(f"  downloading {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "MontanaHailWatch-basemap/1"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    problem = check(data)
    if problem:
        raise SystemExit(f"{url} is not the pinned file ({problem}). Look at the new file, then update "
                         f"the hash in tools/build_basemap.py.")
    dest.write_bytes(data)
    return data


def load_sources(src: Path) -> dict:
    src.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, digest in NE_SHA256.items():
        data = fetch(NE_URL.format(name), src / f"{name}.geojson",
                     lambda d, h=digest: None if _sha256(d) == h else f"sha256 {_sha256(d)}")
        out[name] = json.loads(data)
    tgz = fetch(US_ATLAS_URL, src / "us-atlas-3.0.1.tgz",
                lambda d: None if _sri512(d) == US_ATLAS_INTEGRITY else f"integrity {_sri512(d)}")
    with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as tar:   # read one member; nothing is extracted
        out["counties-10m"] = json.load(tar.extractfile(tar.getmember("package/counties-10m.json")))
    return out


# ---------------------------------------------------------------- geometry

def decode_arcs(topology: dict) -> list[list[tuple[float, float]]]:
    """TopoJSON arcs as lists of (lon, lat): quantized positions, delta-encoded within each arc."""
    tr = topology.get("transform")
    arcs = []
    for arc in topology["arcs"]:
        if tr:
            (sx, sy), (tx, ty) = tr["scale"], tr["translate"]
            x = y = 0
            pts = []
            for pos in arc:
                x += pos[0]
                y += pos[1]
                pts.append((x * sx + tx, y * sy + ty))
        else:
            pts = [(p[0], p[1]) for p in arc]
        arcs.append(pts)
    return arcs


def arc_points(arcs, i: int):
    return arcs[i] if i >= 0 else arcs[~i][::-1]


def stitch(arcs, refs) -> list:
    """One ring (or line) from arc references; the shared end point of consecutive arcs is kept once."""
    pts = []
    for i in refs:
        a = arc_points(arcs, i)
        pts.extend(a if not pts else a[1:])
    return pts


def dedupe(pts) -> list:
    out = []
    for p in pts:
        if not out or out[-1] != p:
            out.append(p)
    return out


def snap49(p):
    x, y = p
    if abs(y - BORDER_LAT) < BORDER_SNAP and BORDER_LON[0] <= x <= BORDER_LON[1]:
        return (x, BORDER_LAT)
    return p


def _seg_d2(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    qx, qy = ax + t * dx, ay + t * dy
    return (px - qx) ** 2 + (py - qy) ** 2


def simplify(points, tol: float) -> list:
    """Douglas-Peucker keeping both ends; works for closed rings too (first == last)."""
    n = len(points)
    if n < 3 or tol <= 0:
        return list(points)
    xs = [p[0] * KX for p in points]
    ys = [p[1] for p in points]
    keep = [False] * n
    keep[0] = keep[-1] = True
    tol2 = tol * tol
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        best, idx = -1.0, -1
        ax, ay, bx, by = xs[a], ys[a], xs[b], ys[b]
        for i in range(a + 1, b):
            d = _seg_d2(xs[i], ys[i], ax, ay, bx, by)
            if d > best:
                best, idx = d, i
        if idx > 0 and best > tol2:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(points, keep) if k]


def _cross(p, q, axis: int, value: float):
    """Where segment p-q crosses x (axis 0) or y (axis 1) = value, computed in one fixed direction so
    two polygons sharing the segment get the same point."""
    if q < p:
        p, q = q, p
    t = (value - p[axis]) / (q[axis] - p[axis])
    if axis == 0:
        return (value, p[1] + t * (q[1] - p[1]))
    return (p[0] + t * (q[0] - p[0]), value)


def clip_ring(ring, box) -> list:
    """Sutherland-Hodgman against an axis-aligned box (s, w, n, e); returns a closed ring or []."""
    s, w, n, e = box
    pts = list(ring[:-1]) if ring and ring[0] == ring[-1] else list(ring)
    for axis, value, keep_ge in ((0, w, True), (0, e, False), (1, s, True), (1, n, False)):
        if not pts:
            break
        inside = (lambda p: p[axis] >= value) if keep_ge else (lambda p: p[axis] <= value)
        out = []
        prev = pts[-1]
        for cur in pts:
            if inside(cur):
                if not inside(prev):
                    out.append(_cross(prev, cur, axis, value))
                out.append(cur)
            elif inside(prev):
                out.append(_cross(prev, cur, axis, value))
            prev = cur
        pts = out
    pts = dedupe(pts)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        return []
    return pts + [pts[0]]


def _clip_segment(a, b, box):
    """Liang-Barsky; returns (p, q) inside the box (the original end points where they are inside) or None."""
    s, w, n, e = box
    x0, y0 = a
    dx, dy = b[0] - x0, b[1] - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - w), (dx, e - x0), (-dy, y0 - s), (dy, n - y0)):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            t0 = max(t0, r)
        else:
            if r < t0:
                return None
            t1 = min(t1, r)
    pa = a if t0 == 0 else (x0 + t0 * dx, y0 + t0 * dy)
    pb = b if t1 == 1 else (x0 + t1 * dx, y0 + t1 * dy)
    return pa, pb


def clip_line(points, box) -> list[list]:
    """The parts of a line inside the box."""
    parts, cur = [], []
    for a, b in zip(points, points[1:]):
        seg = _clip_segment(a, b, box)
        if seg is None:
            if cur:
                parts.append(cur)
                cur = []
            continue
        p, q = seg
        if cur and cur[-1] == p:
            cur.append(q)
        else:
            if cur:
                parts.append(cur)
            cur = [p, q]
        if q != b:
            parts.append(cur)
            cur = []
    if cur:
        parts.append(cur)
    return [d for d in (dedupe(p) for p in parts) if len(d) >= 2]


def rnd(pts) -> list:
    return dedupe([(round(x, DECIMALS), round(y, DECIMALS)) for x, y in pts])


def rnd_ring(ring) -> list:
    r = rnd(ring)
    if len(r) > 1 and r[0] != r[-1]:
        r.append(r[0])
    return r if len(r) >= 4 else []


def bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(ys), min(xs), max(ys), max(xs)          # (s, w, n, e)


def intersects(b, box=BOX) -> bool:
    return not (b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3])


def build_topology(rings):
    """Split closed rings into unique arcs at junctions. Returns (arcs, refs): refs[k] lists
    (arc index, reversed) for ring k. A point is a junction where its neighbours differ between
    rings, i.e. where a shared border starts or ends."""
    neighbours: dict = {}
    for ring in rings:
        pts = ring[:-1]
        n = len(pts)
        for i in range(n):
            neighbours.setdefault(pts[i], set()).add(frozenset((pts[i - 1], pts[(i + 1) % n])))
    arcs, index, refs = [], {}, []

    def add(seq):
        fwd = tuple(seq)
        rev = fwd[::-1]
        key = min(fwd, rev)
        if key not in index:
            index[key] = len(arcs)
            arcs.append(list(key))
        return index[key], key != fwd

    for ring in rings:
        pts = ring[:-1]
        n = len(pts)
        junctions = [i for i in range(n) if len(neighbours[pts[i]]) > 1]
        if not junctions:
            k = min(range(n), key=lambda i: pts[i])
            refs.append([add(pts[k:] + pts[:k] + [pts[k]])])
            continue
        refs.append([add([pts[i % n] for i in range(a, b + 1)])
                     for a, b in zip(junctions, junctions[1:] + [junctions[0] + n])])
    return arcs, refs


def assemble(arcs, ring_refs) -> list:
    pts = []
    for i, rev in ring_refs:
        a = arcs[i][::-1] if rev else arcs[i]
        pts.extend(a if not pts else a[1:])
    return pts


def feature(props: dict, geom_type: str, coords) -> dict:
    if geom_type == "MultiPolygon" and len(coords) == 1:
        geom_type, coords = "Polygon", coords[0]
    if geom_type == "MultiLineString" and len(coords) == 1:
        geom_type, coords = "LineString", coords[0]
    return {"type": "Feature", "properties": props, "geometry": {"type": geom_type, "coordinates": coords}}


def fc(features: list) -> dict:
    return {"type": "FeatureCollection", "features": features}


def clean_name(name):
    if not name:
        return None
    name = " ".join(str(name).split())
    for a, b in (("S. Fk.", "South Fork"), ("N. Fk.", "North Fork"), ("Middle Fk.", "Middle Fork"),
                 ("Fk.", "Fork"), ("Cr.", "Creek")):
        name = name.replace(a, b)
    return NAME_FIXES.get(name, name)


# ---------------------------------------------------------------- layers

def us_layers(topo: dict, postal: dict):
    """US state polygons, Montana county lines and border arcs, all from the one Census topology."""
    arcs = [dedupe([snap49(p) for p in a]) for a in decode_arcs(topo)]
    states = topo["objects"]["states"]["geometries"]
    counties = topo["objects"]["counties"]["geometries"]

    def polys(g):
        return g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]

    users: dict[int, list[str]] = {}            # arc -> states using it (all states, for border kinds)
    for g in states:
        for poly in polys(g):
            for ring in poly:
                for i in ring:
                    users.setdefault(i if i >= 0 else ~i, []).append(g["properties"]["name"])
    chosen = []
    for g in sorted(states, key=lambda g: g["id"]):
        parts = [p for p in polys(g) if intersects(bbox(stitch(arcs, p[0])))]
        if parts:
            chosen.append((g, parts))
    mt_counties = sorted((g for g in counties if str(g["id"]).startswith("30")), key=lambda g: g["id"])
    used = {i if i >= 0 else ~i for _, parts in chosen for poly in parts for ring in poly for i in ring}
    used |= {i if i >= 0 else ~i for g in mt_counties for poly in polys(g) for ring in poly for i in ring}
    sarcs = {i: simplify(arcs[i], TOL["us"]) for i in sorted(used)}
    sarcs_list = [sarcs.get(i, arcs[i]) for i in range(len(arcs))]

    land = []
    for g, parts in chosen:
        name = g["properties"]["name"]
        out = []
        for poly in parts:
            rings = []
            for k, ring in enumerate(poly):
                r = rnd_ring(clip_ring(stitch(sarcs_list, ring), BOX))
                if not r:
                    if k == 0:
                        break
                    continue
                rings.append(r)
            if rings:
                out.append(rings)
        if out:
            land.append(feature({"name": name, "abbrev": postal[("USA", name)],
                                 "admin": "United States of America", "montana": name == "Montana"},
                                "MultiPolygon", out))

    # Montana county lines: arcs used by two Montana counties (the outline is drawn from borders).
    by_arc: dict[int, list[str]] = {}
    for g in mt_counties:
        for poly in polys(g):
            for ring in poly:
                for i in ring:
                    by_arc.setdefault(i if i >= 0 else ~i, []).append(g["properties"]["name"])
    county_lines = []
    for i in sorted(by_arc):
        names = sorted(set(by_arc[i]))
        if len(names) != 2:
            continue
        for part in clip_line(sarcs[i], BOX):
            part = rnd(part)
            if len(part) >= 2:
                county_lines.append(feature({"between": names}, "LineString", part))

    # Border arcs of the chosen states: shared by two states, or the 49th-parallel border.
    border_parts: dict[tuple, list] = {}
    chosen_names = {g["properties"]["name"] for g, _ in chosen}
    for i in sorted(used):
        names = users.get(i, [])
        if not names or not (set(names) & chosen_names):
            continue
        pts = sarcs[i]
        on49 = all(p[1] == BORDER_LAT for p in pts)
        if len(names) == 2:
            kind = "state"
        elif len(names) == 1 and on49:
            kind = "country"
        else:
            continue                            # coastline or a border outside the box
        for part in clip_line(pts, BOX):
            part = rnd(part)
            if len(part) >= 2:
                border_parts.setdefault((kind, "Montana" in names), []).append(part)
    return land, county_lines, border_parts, sorted({g["properties"]["name"] for g in mt_counties})


def canada_layers(admin1: dict):
    feats = sorted((f for f in admin1["features"] if f["properties"]["adm0_a3"] == "CAN"),
                   key=lambda f: f["properties"]["name"])
    rings, owner = [], []          # owner[k] = (feature index, polygon index, ring index)
    meta = []
    for fi, f in enumerate(feats):
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        meta.append(f["properties"])
        for pi, poly in enumerate(polys):
            if not intersects(bbox(poly[0])):
                continue
            for ri, ring in enumerate(poly):
                r = dedupe([snap49((p[0], p[1])) for p in ring])
                if r[0] != r[-1]:
                    r.append(r[0])
                if len(r) >= 4:
                    rings.append(r)
                    owner.append((fi, pi, ri))
    arcs, refs = build_topology(rings)
    sarcs = [simplify(a, TOL["canada"]) for a in arcs]
    polys_out: dict[int, dict[int, list]] = {}
    for (fi, pi, ri), ref in zip(owner, refs):
        r = rnd_ring(clip_ring(assemble(sarcs, ref), BOX))
        if not r:
            continue
        poly = polys_out.setdefault(fi, {}).setdefault(pi, [])
        if ri == 0 or poly:
            poly.append(r)
    land = []
    for fi in sorted(polys_out):
        coords = [rs for _, rs in sorted(polys_out[fi].items()) if rs]
        if coords:
            p = meta[fi]
            land.append(feature({"name": p["name"], "abbrev": p["postal"], "admin": "Canada", "montana": False},
                                "MultiPolygon", coords))
    # province lines: arcs used by two provinces (the 49th parallel is drawn from the US side)
    use_count: dict[int, set] = {}
    for (fi, _, _), ref in zip(owner, refs):
        for i, _ in ref:
            use_count.setdefault(i, set()).add(fi)
    border_parts = {}
    for i in sorted(use_count):
        if len(use_count[i]) != 2:
            continue
        for part in clip_line(sarcs[i], BOX):
            part = rnd(part)
            if len(part) >= 2:
                border_parts.setdefault(("state", False), []).append(part)
    return land, border_parts, len(arcs)


def lakes_layer(base: dict, supplement: dict):
    out = []
    for data in (base, supplement):
        for f in data["features"]:
            g = f["geometry"]
            if not g:
                continue
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            parts, raw = [], []
            for poly in polys:
                if not intersects(bbox(poly[0])):
                    continue
                rings = []
                for k, ring in enumerate(poly):
                    r = rnd_ring(clip_ring(simplify([tuple(p[:2]) for p in ring], TOL["lakes"]), BOX))
                    if not r:
                        if k == 0:
                            break
                        continue
                    rings.append(r)
                if rings:
                    parts.append(rings)
                    raw.append([tuple(p[:2]) for p in poly[0]])
            if not parts:
                continue
            p = f["properties"]
            name = clean_name(p.get("name"))
            mz = p.get("min_zoom") or 6
            props = {"name": name, "min_zoom": max(5, math.ceil(mz))}
            out.append((feature(props, "MultiPolygon", parts), p.get("min_label"), raw))
    out.sort(key=lambda t: (t[0]["properties"]["min_zoom"], t[0]["properties"]["name"] or "~"))
    return out


def point_in_rings(pt, rings) -> bool:
    """Even-odd point-in-polygon (holes are just more rings)."""
    x, y = pt
    inside = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def rivers_layer(base: dict, supplement: dict, lake_features: list):
    """Rivers with a rank: 1 = Natural Earth's main rivers (scale rank up to 7, e.g. Missouri,
    Yellowstone), 2 = the rest of the main file and the supplement's larger rivers, 3 = smaller ones.
    A lake centreline that runs through a lake we draw is left out, so no line crosses the water."""
    lakes = []
    for f in lake_features:
        g = f["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            lakes.append((bbox(poly[0]), poly))

    def in_lake(pt):
        return any(b[0] <= pt[1] <= b[2] and b[1] <= pt[0] <= b[3] and point_in_rings(pt, poly)
                   for b, poly in lakes)

    groups: dict[tuple, list] = {}
    for src, data in (("base", base), ("na", supplement)):
        for f in data["features"]:
            g = f["geometry"]
            if not g:
                continue
            p = f["properties"]
            sr = p.get("scalerank") or 12
            if src == "base":
                rank = 1 if sr <= 7 else 2
            else:
                rank = 2 if sr <= 10 else 3
            name = clean_name(p.get("name"))
            centreline = "Lake Centerline" in (p.get("featurecla") or "")
            lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
            for line in lines:
                line = [tuple(q[:2]) for q in line]
                if len(line) < 2 or not intersects(bbox(line)):
                    continue
                for part in clip_line(simplify(line, TOL["rivers"]), BOX):
                    part = rnd(part)
                    if len(part) < 2:
                        continue
                    if centreline and sum(map(in_lake, part)) * 2 >= len(part):
                        continue
                    groups.setdefault((rank, name or ""), []).append(part)
    feats = []
    for (rank, name), parts in sorted(groups.items()):
        feats.append(feature({"name": name or None, "rank": rank, "min_zoom": {1: 6, 2: 7, 3: 8}[rank]},
                             "MultiLineString", parts))
    return feats


def roads_layer(roads: dict):
    groups: dict[tuple, list] = {}
    for f in roads["features"]:
        p = f["properties"]
        g = f["geometry"]
        if not g or p.get("sov_a3") != "USA" or p.get("level") not in ("Interstate", "Federal"):
            continue
        num = (p.get("name") or "").strip()
        if not num:
            continue
        kind = "interstate" if p["level"] == "Interstate" else "us"
        ref = ("I-" if kind == "interstate" else "US-") + num
        lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        for line in lines:
            line = [tuple(q[:2]) for q in line]
            if len(line) < 2 or not intersects(bbox(line)):
                continue
            for part in clip_line(simplify(line, TOL["roads"]), BOX):
                part = rnd(part)
                if len(part) >= 2:
                    groups.setdefault((kind, ref), []).append(part)

    def order(k):
        kind, ref = k
        digits = "".join(c for c in ref if c.isdigit())
        return (kind != "interstate", int(digits or 0), ref)

    return [feature({"ref": ref, "type": kind, "min_zoom": 7 if kind == "interstate" else 8},
                    "MultiLineString", groups[(kind, ref)]) for kind, ref in sorted(groups, key=order)]


def places_list(pp: dict, towns: list, postal: dict):
    s, w, n, e = IMG
    site = {t["name"].lower(): t for t in towns}
    rows = []
    for f in pp["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        if p.get("adm0_a3") not in ("USA", "CAN") or not (s <= lat <= n and w <= lon <= e):
            continue
        state = postal.get((p["adm0_a3"], p.get("adm1name")))
        name = p["name"]
        if state == "MT" and name.lower() in site:
            continue                                  # the site town stands for it (towns.json position)
        pop = p.get("pop_max") or 0
        sr = p.get("scalerank") or 10
        rank = 2 if (sr <= 4 or pop >= 150_000) else 3 if (sr <= 6 or pop >= 30_000) else 4
        rows.append({"name": name, "lat": round(lat, DECIMALS), "lon": round(lon, DECIMALS), "rank": rank,
                     "state": state, "_pop": pop})
    rows.sort(key=lambda r: (r["rank"], -r["_pop"], r["name"]))
    sites = [{"name": t["name"], "lat": t["lat"], "lon": t["lon"], "rank": 1,
              "min_zoom": 7 if t.get("minor") else 5, "state": "MT", "site": True, "slug": t["slug"]}
             for t in towns]
    return sites, rows


# ---------------------------------------------------------------- labels and places

def px(lat: float, lon: float, z: int):
    size = 256 * 2 ** z
    y = (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * size
    return (lon + 180) / 360 * size, y


def unpx(x: float, y: float, z: int):
    size = 256 * 2 ** z
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / size))))
    return lat, x / size * 360 - 180


def label_size(kind: str, text: str):
    cw, h = LABEL_METRICS[kind]
    return len(text) * cw + 6, h


def town_boxes(t: dict, z: int) -> list:
    """[the bubble's box with its 1.5 px ring, the name's box] in px at zoom z (see BUBBLE_R)."""
    x, y = px(t["lat"], t["lon"], z)
    w = TOWN_LABEL_W.get(t["name"], 8.5 * len(t["name"]))
    r, d, h = BUBBLE_R, TOWN_NAME_OFF, TOWN_H
    side = t.get("label", "right")
    label = {"right": (x + d, y - h / 2, x + d + w, y + h / 2),
             "left": (x - d - w, y - h / 2, x - d, y + h / 2),
             "top": (x - w / 2, y - d - h, x + w / 2, y - d),
             "bottom": (x - w / 2, y + d, x + w / 2, y + d + h)}[side]
    return [(x - r - 1.5, y - r - 1.5, x + r + 1.5, y + r + 1.5), label]


def into_bubble(centre, box) -> float:
    """How far (px) a box reaches into the bubble on `centre` (negative: how far it stays clear)."""
    nx, ny = min(max(centre[0], box[0]), box[2]), min(max(centre[1], box[1]), box[3])
    return BUBBLE_R - math.hypot(nx - centre[0], ny - centre[1])


def town_contacts(towns) -> list:
    """Town against town at zooms 5-11, minor towns from zoom 7: a name over another town's bubble (a
    30 px circle) or name, or two bubbles touching. At zoom 5 a name may reach TOUCH_Z5 px into a bubble."""
    problems = []
    for z in ZOOMS:
        shown = [t for t in towns if z >= 7 or not t.get("minor")]
        for a in shown:
            name, ca = town_boxes(a, z)[1], px(a["lat"], a["lon"], z)
            for b in shown:
                if b is a:
                    continue
                cb = px(b["lat"], b["lon"], z)
                into = into_bubble(cb, name)
                if into > (TOUCH_Z5 if z == ZOOMS[0] else 0):
                    problems.append(f"z{z}: town {a['name']} name / town {b['name']} bubble ({into:.1f} px in)")
                if a["name"] < b["name"]:
                    if overlaps(name, town_boxes(b, z)[1], gap=0):
                        problems.append(f"z{z}: town {a['name']} name / town {b['name']} name")
                    if math.dist(ca, cb) < 2 * BUBBLE_R:
                        problems.append(f"z{z}: town {a['name']} bubble / town {b['name']} bubble")
    return problems


def place_box(p: dict, z: int):
    x, y = px(p["lat"], p["lon"], z)
    w = PLACE_CHAR * len(p["name"]) + 4
    return (x - PLACE_DOT, y - PLACE_H / 2, x + PLACE_DOT + 3 + w, y + PLACE_H / 2)


def text_box(lab: dict, z: int):
    x, y = px(lab["lat"], lab["lon"], z)
    w, h = label_size(lab["kind"], lab["text"])
    return (x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def overlaps(a, b, gap=GAP) -> bool:
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


class Obstacles:
    """Boxes (px) per zoom that a new label or place must stay clear of, each with its own gap."""

    def __init__(self):
        self.by_zoom = {z: [] for z in ZOOMS}

    def add(self, z, box, what, gap=GAP):
        self.by_zoom[z].append((box, what, gap))

    def hits(self, z, box):
        return [what for b, what, gap in self.by_zoom[z] if overlaps(box, b, gap)]


def box_px(z):
    """The clip box (s, w, n, e) in px at zoom z: (x west, y north, x east, y south)."""
    xw, yn = px(BOX[2], BOX[1], z)
    xe, ys = px(BOX[0], BOX[3], z)
    return xw, yn, xe, ys


def within_box(b, z) -> bool:
    xw, yn, xe, ys = box_px(z)
    return b[0] >= xw and b[2] <= xe and b[1] >= yn and b[3] <= ys


def _rings_of(features: list, abbrevs) -> list:
    """Outer and hole rings of the land features with these abbrevs, clipped to the image bounds."""
    out = []
    for f in features:
        if f["properties"]["abbrev"] not in abbrevs:
            continue
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            for ring in poly:
                r = clip_ring([tuple(p) for p in ring], IMG)
                if r:
                    out.append(r)
    return out


def _pip(np, lon, lat, rings):
    """Even-odd point-in-polygon for arrays of points against rings (holes count as rings)."""
    inside = np.zeros(lon.shape, bool)
    for ring in rings:
        r = np.asarray(ring, float)
        x1, y1, x2, y2 = r[:-1, 0], r[:-1, 1], r[1:, 0], r[1:, 1]
        dy = np.where(y2 == y1, 1e-12, y2 - y1)
        for s in range(0, len(lon), 4000):
            px_, py_ = lon[s:s + 4000, None], lat[s:s + 4000, None]
            cond = (y1 > py_) != (y2 > py_)
            xint = x1 + (py_ - y1) * (x2 - x1) / dy
            inside[s:s + 4000] ^= (np.count_nonzero(cond & (px_ < xint), axis=1) % 2) == 1
    return inside


def _boundary_dist(np, X, Y, rings, z):
    """Distance (px at zoom z) from points to the nearest ring edge."""
    best = np.full(X.shape, np.inf)
    for ring in rings:
        pts = np.array([px(lat, lon, z) for lon, lat in ring])
        ax, ay, bx, by = pts[:-1, 0], pts[:-1, 1], pts[1:, 0], pts[1:, 1]
        dx, dy = bx - ax, by - ay
        l2 = np.where(dx * dx + dy * dy == 0, 1e-12, dx * dx + dy * dy)
        for s in range(0, len(X), 2000):
            x, y = X[s:s + 2000, None], Y[s:s + 2000, None]
            t = np.clip(((x - ax) * dx + (y - ay) * dy) / l2, 0, 1)
            d = np.hypot(ax + t * dx - x, ay + t * dy - y).min(axis=1)
            best[s:s + 2000] = np.minimum(best[s:s + 2000], d)
    return best


def _centroid(rings, z):
    a = cx = cy = 0.0
    for ring in rings:
        pts = [px(lat, lon, z) for lon, lat in ring]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            c = x0 * y1 - x1 * y0
            a += c
            cx += (x0 + x1) * c
            cy += (y0 + y1) * c
    if a == 0:
        return None
    return cx / (3 * a), cy / (3 * a)


# Where a label box is tested against an area: its corners and the middles of its sides (fractions of w, h).
BOX_POINTS = ((-.5, -.5), (0, -.5), (.5, -.5), (-.5, 0), (.5, 0), (-.5, .5), (0, .5), (.5, .5))


def place_text(np, text, kind, rings, min_zoom, obstacles, *, inside_box: bool, prefer: str, cap=26.0,
               max_zoom=None, one_ring=False):
    """Best centre for a label inside `rings`, from a grid of candidates: on the base map and clear of
    every obstacle at every zoom from min_zoom to 11 (a max_zoom hint is not relied on), the whole
    box inside the area (when inside_box) at zoom max(min_zoom, 6), or at max_zoom if that is lower;
    then the most room (capped at `cap` px), then nearest the area centroid ("centroid"); or farthest
    from the shore ("pole"); or farthest south, then nearest the centroid's longitude ("south", for a
    label kept next to the border on its north side). With one_ring (and inside_box), a box inside a
    single ring comes first after that row (south) or before the room (centroid): a label over several
    provinces then sits in one of them, with no province line through it."""
    s, w, n, e = bbox([p for r in rings for p in r])
    s, w, n, e = max(s, IMG[0]), max(w, IMG[1]), min(n, IMG[2]), min(e, IMG[3])
    steps = 90
    dlat, dlon = max((n - s) / steps, 0.01), max((e - w) / steps, 0.014)
    lats = np.arange(s + dlat / 2, n, dlat)
    lons = np.arange(w + dlon / 2, e, dlon)
    LON, LAT = np.meshgrid(lons, lats)
    LON, LAT = LON.ravel(), LAT.ravel()
    ok = _pip(np, LON, LAT, rings)
    LON, LAT = LON[ok], LAT[ok]
    if not len(LON):
        return None, "no candidate inside the area"
    lw, lh = label_size(kind, text)
    zc = max(min_zoom, 6) if max_zoom is None else min(max(min_zoom, 6), max_zoom)
    corners = []                                    # the BOX_POINTS of each candidate, as (lons, lats)
    if inside_box:
        good = np.ones(LON.shape, bool)
        XY = [px(la, lo, zc) for la, lo in zip(LAT, LON)]
        for fx, fy in BOX_POINTS:
            pts = [unpx(x + fx * lw, y + fy * lh, zc) for x, y in XY]
            corners.append((np.array([p[1] for p in pts]), np.array([p[0] for p in pts])))
            good &= _pip(np, corners[-1][0], corners[-1][1], rings)
        LON, LAT = LON[good], LAT[good]
        corners = [(clon[good], clat[good]) for clon, clat in corners]
        if not len(LON):
            return None, "the label does not fit inside the area"
    single = np.ones(LON.shape, bool)               # the box lies inside one ring (one_ring only)
    if one_ring and corners:
        single[:] = False
        for ring in rings:
            inside = np.ones(LON.shape, bool)
            for clon, clat in corners:
                inside &= _pip(np, clon, clat, [ring])
            single |= inside
    feasible = np.ones(LON.shape, bool)
    clear = np.full(LON.shape, cap)
    for z in range(min_zoom, ZOOMS[-1] + 1):
        XY = np.array([px(la, lo, z) for la, lo in zip(LAT, LON)])
        x0, y0 = XY[:, 0] - lw / 2, XY[:, 1] - lh / 2
        x1, y1 = XY[:, 0] + lw / 2, XY[:, 1] + lh / 2
        xw, yn, xe, ys = box_px(z)
        feasible &= (x0 >= xw) & (x1 <= xe) & (y0 >= yn) & (y1 <= ys)      # stays on the base map
        for box, _, g in obstacles.by_zoom[z]:
            hit = (x0 < box[2] + g) & (box[0] < x1 + g) & (y0 < box[3] + g) & (box[1] < y1 + g)
            feasible &= ~hit
            if z == zc:
                gx = np.maximum(0, np.maximum(box[0] - x1, x0 - box[2]))
                gy = np.maximum(0, np.maximum(box[1] - y1, y0 - box[3]))
                clear = np.minimum(clear, np.hypot(gx, gy))
    if not feasible.any():
        return None, "every spot covers a town or another label"
    XY = np.array([px(la, lo, zc) for la, lo in zip(LAT, LON)])
    edge = _boundary_dist(np, XY[:, 0], XY[:, 1], rings, zc)
    if inside_box:
        clear = np.minimum(clear, np.maximum(0, edge - lw / 2))
    if prefer == "pole":
        key = np.lexsort((LON, LAT, -edge, ~feasible))
    elif prefer == "south":
        c = _centroid(rings, zc) or (XY[:, 0].mean(), XY[:, 1].mean())
        key = np.lexsort((LON, np.abs(XY[:, 0] - c[0]), ~single, LAT, ~feasible))
    else:
        c = _centroid(rings, zc) or (XY[:, 0].mean(), XY[:, 1].mean())
        dist = np.hypot(XY[:, 0] - c[0], XY[:, 1] - c[1])
        key = np.lexsort((LON, LAT, dist, -np.round(np.minimum(clear, cap)), ~single, ~feasible))
    i = key[0]
    return (round(float(LAT[i]), DECIMALS), round(float(LON[i]), DECIMALS)), None


def _place_area_label(np, text, kind, area, first_zoom, max_zoom, obstacles, prefer, one_ring=False):
    """A region or country label in `area` at the first zoom from first_zoom to 7 (and to max_zoom)
    where it fits: ((lat, lon), zoom, None), or (None, None, why not)."""
    why = "no zoom tried"
    for z in range(first_zoom, min(7, max_zoom or 7) + 1):
        spot, why = place_text(np, text, kind, area, z, obstacles, inside_box=True, prefer=prefer,
                               cap=10.0 if kind == "region-main" else 26.0, max_zoom=max_zoom,
                               one_ring=one_ring)
        if spot:
            return spot, z, None
    return None, None, why


def make_labels_and_places(land, lakes, towns, sites, others, log):
    import numpy as np

    def with_towns():
        obs = Obstacles()
        for t in towns:
            for z in ZOOMS:
                if z >= 7 or not t.get("minor"):
                    for b in town_boxes(t, z):
                        obs.add(z, b, t["name"])
        return obs

    # Labels go first but leave room for the bigger places: rank 2 from zoom 5, rank 3 from zoom 6.
    obstacles = with_towns()
    for p in others:
        if p["rank"] <= 3:
            for z in ZOOMS:
                if z >= {2: 5, 3: 6}[p["rank"]]:
                    obstacles.add(z, place_box(p, z), p["name"])
    labels = []
    place_obstacles = with_towns()      # for the places: towns, labels, and places placed before

    def commit(lab):
        labels.append(lab)
        for z in ZOOMS:
            if z >= lab["min_zoom"]:
                obstacles.add(z, text_box(lab, z), lab["text"], LABEL_GAP)
                place_obstacles.add(z, text_box(lab, z), lab["text"])

    for text, kind, abbrevs, mz, maxz, where in AREA_LABELS:
        rings = _rings_of(land, abbrevs)
        if not rings:
            log.append(f"label {text}: region not in the map")
            continue
        spot = None
        if where in ("border", "phone"):
            box, prefer = (BORDER_STRIP, "south") if where == "border" else (PHONE_STRIP, "centroid")
            strip = [r for r in (clip_ring(ring, box) for ring in rings) if r]
            spot, z, why = (_place_area_label(np, text, kind, strip, mz, maxz, obstacles, prefer, True)
                            if strip else (None, None, "no part of the area is in it"))
            if not spot:
                log.append(f"label {text}: no room in the {where} strip ({why}), placed in the whole area")
        if not spot:
            spot, z, why = _place_area_label(np, text, kind, rings, mz, maxz, obstacles, "centroid")
        if not spot:
            log.append(f"label {text}: not placed ({why})")
            continue
        lab = {"text": text, "lat": spot[0], "lon": spot[1], "kind": kind, "min_zoom": z}
        if maxz is not None:
            lab["max_zoom"] = maxz
        commit(lab)

    for feat, min_label, raw in lakes:
        name = feat["properties"]["name"]
        if not name or min_label is None or min_label > 8:
            continue
        mz = min(9, max(7, math.ceil(min_label) + 1))
        centre = _centroid([[(p[0], p[1]) for p in raw[0]]], 10)
        if centre is None:
            continue
        clat, clon = unpx(centre[0], centre[1], 10)
        if not (IMG[0] <= clat <= IMG[2] and IMG[1] <= clon <= IMG[3]):
            continue                                # mostly off the image: no name at its edge
        g = feat["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        drawn = [[tuple(p) for p in ring] for poly in polys for ring in poly]
        rings = [r for r in (clip_ring(ring, IMG) for ring in drawn) if r]
        if not rings:
            continue
        spot = None
        for z in range(mz, 10):
            spot, why = place_text(np, name, "water", rings, z, obstacles, inside_box=False, prefer="pole")
            if spot:
                mz = z
                break
        if not spot:
            log.append(f"water label {name}: not placed ({why})")
            continue
        commit({"text": name, "lat": spot[0], "lon": spot[1], "kind": "water", "min_zoom": mz})

    # Places, biggest first: the first zoom (5-9) from which the dot and name stay clear of every
    # bubble, label and earlier place at that zoom and all higher ones.
    placed = []
    for p in others:
        start = {2: 5, 3: 6, 4: 7}[p["rank"]]
        for z0 in range(start, PLACE_ZOOMS[-1] + 1):
            if within_box(place_box(p, z0), z0) and not any(
                    place_obstacles.hits(z, place_box(p, z)) for z in range(z0, ZOOMS[-1] + 1)):
                break
        else:
            log.append(f"place {p['name']}: left out, no room up to zoom {PLACE_ZOOMS[-1]}")
            continue
        q = {k: v for k, v in p.items() if not k.startswith("_")}
        q["min_zoom"] = z0
        placed.append(q)
        for z in ZOOMS:
            if z >= z0:
                place_obstacles.add(z, place_box(p, z), p["name"])
    return labels, sites + placed


def check_layout(towns, labels, places):
    """Every pair of label/place/bubble boxes visible at the same zoom, 5-11, that overlap, and every
    town that covers another (town_contacts)."""
    problems = []
    for z in ZOOMS:
        items = []
        for t in towns:
            if z >= 7 or not t.get("minor"):
                items += [(b, f"town {t['name']}") for b in town_boxes(t, z)]
        items += [(text_box(lab, z), f"label {lab['text']}") for lab in labels if z >= lab["min_zoom"]]
        items += [(place_box(p, z), f"place {p['name']}") for p in places
                  if not p.get("site") and z >= p["min_zoom"]]
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if a[1] == b[1] or (a[1].startswith("town") and b[1].startswith("town")):
                    continue                        # a bubble and its own name; town vs town: below
                if overlaps(a[0], b[0], gap=0):
                    problems.append(f"z{z}: {a[1]} / {b[1]}")
    return problems + town_contacts(towns)


# ---------------------------------------------------------------- output

def dump(doc: dict) -> str:
    """Compact JSON with one feature, label or place per line."""
    def j(o):
        return json.dumps(o, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    lines = ["{"]
    keys = list(doc)
    for k_i, k in enumerate(keys):
        v = doc[k]
        comma = "," if k_i < len(keys) - 1 else ""
        if isinstance(v, dict) and v.get("type") == "FeatureCollection":
            lines.append(f'{j(k)}:{{"type":"FeatureCollection","features":[')
            feats = v["features"]
            lines += [j(f) + ("," if i < len(feats) - 1 else "") for i, f in enumerate(feats)]
            lines.append("]}" + comma)
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            lines.append(f"{j(k)}:[")
            lines += [j(x) + ("," if i < len(v) - 1 else "") for i, x in enumerate(v)]
            lines.append("]" + comma)
        else:
            lines.append(f"{j(k)}:{j(v)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def build(src: Path) -> tuple[str, dict, list]:
    data = load_sources(src)
    admin1 = data["ne_10m_admin_1_states_provinces"]
    postal = {(f["properties"]["adm0_a3"], f["properties"]["name"]): f["properties"]["postal"]
              for f in admin1["features"] if f["properties"]["adm0_a3"] in ("USA", "CAN")}
    towns = json.loads(TOWNS.read_text())
    log: list[str] = []

    us_land, county_lines, us_borders, county_names = us_layers(data["counties-10m"], postal)
    ca_land, ca_borders, ca_arcs = canada_layers(admin1)
    land = us_land + ca_land
    borders = []
    for key in sorted(set(us_borders) | set(ca_borders), key=lambda k: (k[0] != "country", not k[1])):
        parts = us_borders.get(key, []) + ca_borders.get(key, [])
        borders.append(feature({"kind": key[0], "montana": key[1]}, "MultiLineString", parts))
    lakes = lakes_layer(data["ne_10m_lakes"], data["ne_10m_lakes_north_america"])
    rivers = rivers_layer(data["ne_10m_rivers_lake_centerlines"], data["ne_10m_rivers_north_america"],
                          [f for f, _, _ in lakes])
    roads = roads_layer(data["ne_10m_roads"])
    sites, others = places_list(data["ne_10m_populated_places_simple"], towns, postal)
    labels, places = make_labels_and_places(land, lakes, towns, sites, others, log)

    doc = {
        "version": 1,
        "bounds": [[BOX[0], BOX[1]], [BOX[2], BOX[3]]],
        "image_bounds": [list(IMAGE_BOUNDS[0]), list(IMAGE_BOUNDS[1])],
        "sources": SOURCES,
        "land": fc(land),
        "borders": fc(borders),
        "counties": fc(county_lines),
        "lakes": fc([f for f, _, _ in lakes]),
        "rivers": fc(rivers),
        "roads": fc(roads),
        "labels": labels,
        "places": places,
    }
    text = dump(doc)
    assert json.loads(text) == json.loads(json.dumps(doc)), "dump changed the data"
    stats = {
        "land": len(land), "borders": len(borders), "counties": len(county_lines),
        "county_names": len({n for f in county_lines for n in f["properties"]["between"]}),
        "county_names_source": len(county_names), "canada_arcs": ca_arcs,
        "lakes": len(lakes), "rivers": len(rivers), "roads": len(roads), "labels": len(labels),
        "places": len(places), "site_places": sum(1 for p in places if p.get("site")),
    }
    log += check_layout(towns, labels, places)
    return text, stats, log


def layer_sizes(text: str) -> dict:
    doc = json.loads(text)
    return {k: len(json.dumps(v, separators=(",", ":"), ensure_ascii=False)) for k, v in doc.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1].strip())
    ap.add_argument("--src", type=Path, help="download/cache folder to keep (default: a temp folder, "
                                             "about 115 MB, deleted when done)")
    ap.add_argument("--out", type=Path, default=OUT, help=f"output file (default: {OUT.relative_to(ROOT)})")
    ap.add_argument("--preview", type=Path, help="also draw a PNG of the result (needs Pillow)")
    ap.add_argument("--check", action="store_true", help="exit 1 if --out differs from a fresh build")
    args = ap.parse_args(argv)

    with contextlib.ExitStack() as stack:          # removes a temp download folder, even after an error
        src = args.src or Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="basemap-src-")))
        print(f"sources in {src}" + ("" if args.src else " (deleted when done; --src DIR keeps them)"))
        text, stats, log = build(src)
    size = len(text.encode())
    print(f"{size:,} bytes (budget {BUDGET:,})")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    for k, v in layer_sizes(text).items():
        print(f"  size {k}: {v:,}")
    for line in log:
        print(f"  note: {line}")
    if size > BUDGET:
        print("over budget: raise the simplification tolerances in TOL", file=sys.stderr)
        return 1
    if args.check:
        same = args.out.exists() and args.out.read_text() == text
        print("committed file is up to date" if same else "committed file differs from a fresh build")
        return 0 if same else 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(f"wrote {args.out}")
    if args.preview:
        print(f"preview {preview(json.loads(text), args.preview)}")
    return 0


# ---------------------------------------------------------------- preview (a check image, not used by the site)

def preview(doc: dict, path: Path, zoom: int = 7, crop=None, contrast=False) -> Path:
    """Draw the base map as the map would at `zoom` (Web Mercator), with labels and places that show
    at that zoom and the site towns as bubbles. crop = (s, w, n, e) to draw part of it."""
    from PIL import Image, ImageDraw, ImageFont

    s, w, n, e = crop or (doc["bounds"][0][0], doc["bounds"][0][1], doc["bounds"][1][0], doc["bounds"][1][1])
    x0, y0 = px(n, w, zoom)
    x1, y1 = px(s, e, zoom)
    W, H = int(round(x1 - x0)), int(round(y1 - y0))
    scale = 2 if W < 1200 else 1
    img = Image.new("RGB", (W * scale, H * scale), "#eef1f4")
    d = ImageDraw.Draw(img)

    def P(lon, lat):
        x, y = px(lat, lon, zoom)
        return ((x - x0) * scale, (y - y0) * scale)

    def font(size, bold=False, italic=False):
        names = []
        if italic:
            names.append("/usr/share/fonts/opentype/inter/Inter-Italic.otf")
        names.append("/usr/share/fonts/opentype/inter/Inter-SemiBold.otf" if bold else
                     "/usr/share/fonts/opentype/inter/Inter-Regular.otf")
        names += ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
        for nm in names:
            try:
                return ImageFont.truetype(nm, int(size * scale))
            except OSError:
                continue
        return ImageFont.load_default()

    def polys(g):
        if g["type"] == "Polygon":
            return [g["coordinates"]]
        if g["type"] == "MultiPolygon":
            return g["coordinates"]
        return []

    def lines(g):
        if g["type"] == "LineString":
            return [g["coordinates"]]
        if g["type"] == "MultiLineString":
            return g["coordinates"]
        return []

    c = {"line": "#7a8794" if contrast else "#c5ccd4", "mt": "#33414f" if contrast else "#9aa5b1",
         "county": "#b9c2cc" if contrast else "#e4e8ec", "lake": "#9cc3ea" if contrast else "#dfeaf5",
         "river": "#5d9be0" if contrast else "#c8dcf0", "road": "#c0832e" if contrast else "#e2e5e9"}
    for f in doc["land"]["features"]:
        fill = "#ffffff" if f["properties"]["montana"] else "#fafafa"
        for poly in polys(f["geometry"]):
            d.polygon([P(*p) for p in poly[0]], fill=fill)
            for hole in poly[1:]:
                d.polygon([P(*p) for p in hole], fill="#eef1f4")
    for f in doc["lakes"]["features"]:
        if f["properties"]["min_zoom"] <= zoom:
            for poly in polys(f["geometry"]):
                d.polygon([P(*p) for p in poly[0]], fill=c["lake"])
    if zoom >= 7:
        for f in doc["rivers"]["features"]:
            if f["properties"]["min_zoom"] <= zoom:
                width = max(1, int((1.6 - 0.3 * f["properties"]["rank"]) * scale))
                for ln in lines(f["geometry"]):
                    d.line([P(*p) for p in ln], fill=c["river"], width=width)
        for f in doc["roads"]["features"]:
            if f["properties"]["min_zoom"] <= zoom:
                width = 2 if f["properties"]["type"] == "interstate" else 1
                for ln in lines(f["geometry"]):
                    d.line([P(*p) for p in ln], fill=c["road"], width=width * scale)
        for f in doc["counties"]["features"]:
            for ln in lines(f["geometry"]):
                d.line([P(*p) for p in ln], fill=c["county"], width=scale)
    for f in doc["borders"]["features"]:
        mt = f["properties"]["montana"]
        country = f["properties"]["kind"] == "country"
        for ln in lines(f["geometry"]):
            d.line([P(*p) for p in ln], fill=c["mt"] if mt else c["line"],
                   width=int((2 if mt or country else 1) * scale))
    # image bounds (the radar frames' extent), dashed
    (is_, iw), (in_, ie) = doc["image_bounds"]
    corners = [P(iw, in_), P(ie, in_), P(ie, is_), P(iw, is_), P(iw, in_)]
    for a, b in zip(corners, corners[1:]):
        steps = int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) // (8 * scale))
        for k in range(0, max(steps, 1), 2):
            t0, t1 = k / max(steps, 1), min(1, (k + 1) / max(steps, 1))
            d.line([(a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                    (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)], fill="#c9a0a0", width=scale)

    def text_centered(xy, text, fnt, fill, spacing=0.0, halo=None):
        widths = [d.textlength(ch, font=fnt) for ch in text]
        total = sum(widths) + spacing * fnt.size * (len(text) - 1)
        x = xy[0] - total / 2
        asc, desc = fnt.getmetrics()
        y = xy[1] - (asc + desc) / 2
        for ch, wd in zip(text, widths):
            if halo:
                d.text((x, y), ch, font=fnt, fill=fill, stroke_width=max(1, scale), stroke_fill=halo)
            else:
                d.text((x, y), ch, font=fnt, fill=fill)
            x += wd + spacing * fnt.size

    styles = {"country": (font(12, True), "#8e959e", 0.25), "region": (font(12, True), "#9aa3ad", 0.08),
              "region-main": (font(22), "#a9b1ba", 0.3), "water": (font(11, italic=True), "#7f9ab5", 0.0)}
    for lab in doc["labels"]:
        if lab["min_zoom"] <= zoom <= lab.get("max_zoom", 99):
            fnt, fill, sp = styles[lab["kind"]]
            text_centered(P(lab["lon"], lab["lat"]), lab["text"], fnt, fill, sp)
    pf = font(12)
    for p in doc["places"]:
        if p.get("site") or p["min_zoom"] > zoom:
            continue
        x, y = P(p["lon"], p["lat"])
        r = 3 * scale
        d.ellipse([x - r, y - r, x + r, y + r], fill="#1c1c1e", outline="#ffffff")
        asc, desc = pf.getmetrics()
        d.text((x + 6 * scale, y - (asc + desc) / 2), p["name"], font=pf, fill="#1c1c1e",
               stroke_width=max(1, scale), stroke_fill="#ffffff")
    tf = font(13, True)
    bf = font(12, True)
    towns = json.loads(TOWNS.read_text())
    for t in towns:
        if zoom < 7 and t.get("minor"):
            continue
        x, y = P(t["lon"], t["lat"])
        r = BUBBLE_R * scale
        d.ellipse([x - r, y - r, x + r, y + r], fill="#4a4a4f")
        text_centered((x, y), "48", bf, "#ffffff")
        side = t.get("label", "right")
        wd = d.textlength(t["name"], font=tf)
        asc, desc = tf.getmetrics()
        hh = asc + desc
        off = TOWN_NAME_OFF * scale
        pos = {"right": (x + off, y - hh / 2), "left": (x - off - wd, y - hh / 2),
               "top": (x - wd / 2, y - off - hh), "bottom": (x - wd / 2, y + off)}[side]
        d.text(pos, t["name"], font=tf, fill="#1c1c1e", stroke_width=max(1, scale), stroke_fill="#ffffff")
    img.save(path)
    return path


if __name__ == "__main__":
    sys.exit(main())
