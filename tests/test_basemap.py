"""
Base map checks (website/static/map/basemap.json, built by tools/build_basemap.py).

Everything runs offline against the committed file: size budget, bounds, the Montana outline
(closed, the right area, straight 49th parallel, the Yellowstone notch, every site town inside it),
all 56 Montana counties in the county lines, the site towns marked in places, coordinates inside the
padded bounds, valid labels with no NaN, labels that stay clear of the town bubbles, and Canadian
labels inside what the map's first view shows. The coarse context layer outside the padded bounds
(state and province lines, a few state and city names from zoom 5) stays out of the box, meets its
lines at the edge and has no loose ends. A few tests also run the tool's geometry helpers (TopoJSON
decoding, clipping, simplifying) on tiny inputs, and its handling of the download folder.

If towns.json changes (a town added, moved or given another label side), these tests fail until
the base map is rebuilt: python tools/build_basemap.py
"""

import ast
import collections
import contextlib
import importlib.util
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BASEMAP = ROOT / "website" / "static" / "map" / "basemap.json"
TOWNS = json.loads((ROOT / "website" / "towns.json").read_text())

IMAGE_BOUNDS = [[43.0, -118.5], [50.5, -101.0]]     # the radar/model frames' grid (map spec)
PAD = 0.5
BOUNDS = [[42.5, -119.0], [51.0, -100.5]]
CONTEXT_BOUNDS = [[37.5, -122.0], [60.5, -95.2]]    # the context layer, east of the Pacific coast
BUDGET = 450_000
MONTANA_KM2 = 380_831                               # total area, U.S. Census Bureau
LABEL_KINDS = {"country", "region", "region-main", "water"}
# The context layer's names (outside the image bounds), with roughly each state's or province's box
# (s, w, n, e) or the city's state.
CONTEXT_REGIONS = {"NV": (35.0, -120.01, 42.0, -114.03), "UT": (37.0, -114.06, 42.0, -109.04),
                   "CO": (37.0, -109.06, 41.0, -102.04), "NE": (40.0, -104.06, 43.0, -95.3),
                   "KS": (37.0, -102.06, 40.0, -94.58), "MN": (43.49, -97.24, 49.39, -89.48),
                   "MB": (49.0, -102.04, 60.0, -88.9)}
CONTEXT_PLACES = {"Calgary": "AB", "Edmonton": "AB", "Saskatoon": "SK", "Winnipeg": "MB",
                  "Salt Lake City": "UT", "Casper": "WY", "Cheyenne": "WY", "Denver": "CO",
                  "Bismarck": "ND", "Pierre": "SD"}


def load_tool():
    spec = importlib.util.spec_from_file_location("build_basemap", ROOT / "tools" / "build_basemap.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def reject_constant(name):
    raise ValueError(f"{name} in basemap.json")


def load_doc():
    return json.loads(BASEMAP.read_text(), parse_constant=reject_constant)


def polygons(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    raise AssertionError(f"not a polygon: {geom['type']}")


def lines(geom):
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return geom["coordinates"]
    raise AssertionError(f"not a line: {geom['type']}")


def point_in(pt, rings):
    x, y = pt
    inside = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def area_km2(ring):
    """Ring area on an equal-area (Lambert cylindrical) projection."""
    r = 6371.0088
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        total += (math.radians(x1) * r * math.sin(math.radians(y2)) * r
                  - math.radians(x2) * r * math.sin(math.radians(y1)) * r)
    return abs(total) / 2


def project(lat, lon, zoom):
    size = 256 * 2 ** zoom
    y = (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2 * size
    return (lon + 180) / 360 * size, y


def shown(labels, text, zoom):
    """The labels with this text that a map honouring min_zoom and max_zoom shows at this zoom."""
    return [lab for lab in labels if lab["text"] == text and lab["min_zoom"] <= zoom <= lab.get("max_zoom", 11)]


def inside(lat, lon, bounds):
    (s, w), (n, e) = bounds
    return s <= lat <= n and w <= lon <= e


def km(a, b):
    """Distance in km between two (lon, lat) points (flat-earth, fine over a few km)."""
    kx = 111.32 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * 110.57)


def km_to_lines(pt, parts):
    """Distance in km from a (lon, lat) point to the nearest of these lines."""
    kx = 111.32 * math.cos(math.radians(pt[1]))
    best = float("inf")
    for part in parts:
        for (x1, y1), (x2, y2) in zip(part, part[1:]):
            ax, ay = (x1 - pt[0]) * kx, (y1 - pt[1]) * 110.57
            bx, by = (x2 - pt[0]) * kx, (y2 - pt[1]) * 110.57
            dx, dy = bx - ax, by - ay
            u = max(0.0, min(1.0, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) or 1e-12)))
            best = min(best, math.hypot(ax + u * dx, ay + u * dy))
    return best


class File(unittest.TestCase):
    def test_under_budget(self):
        self.assertLessEqual(BASEMAP.stat().st_size, BUDGET)

    def test_no_nan_or_infinity(self):
        doc = load_doc()                    # parse_constant rejects NaN / Infinity
        stack = [doc]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, float):
                self.assertTrue(math.isfinite(item))

    def test_structure_and_bounds(self):
        doc = load_doc()
        self.assertEqual(doc["version"], 1)
        self.assertEqual(doc["bounds"], BOUNDS)
        self.assertEqual(doc["context_bounds"], CONTEXT_BOUNDS)
        self.assertEqual(doc["image_bounds"], IMAGE_BOUNDS)
        self.assertTrue(doc["sources"] and all(isinstance(s, str) and s for s in doc["sources"]))
        self.assertTrue(any("Natural Earth" in s for s in doc["sources"]))
        self.assertTrue(any("Census" in s for s in doc["sources"]))
        for key in ("land", "borders", "counties", "lakes", "rivers", "roads"):
            self.assertEqual(doc[key]["type"], "FeatureCollection", key)
            self.assertTrue(doc[key]["features"], key)
        self.assertIsInstance(doc["labels"], list)
        self.assertIsInstance(doc["places"], list)

    def test_image_bounds_match_the_frames(self):
        """Read IMAGE_BOUNDS from website/gridded.py without importing it."""
        path = ROOT / "website" / "gridded.py"
        if not path.exists():
            self.skipTest("website/gridded.py not there yet")
        for node in ast.walk(ast.parse(path.read_text())):
            targets = [getattr(t, "id", None) for t in getattr(node, "targets", [])]
            if isinstance(node, ast.Assign) and "IMAGE_BOUNDS" in targets:
                value = ast.literal_eval(node.value)
                self.assertEqual([list(value[0]), list(value[1])], IMAGE_BOUNDS)
                return
        self.skipTest("no literal IMAGE_BOUNDS in website/gridded.py")

    def test_every_coordinate_inside_the_padded_bounds_with_4_decimals(self):
        """The context layer (its lines, the 49th parallel running on through it, its names) inside
        context_bounds; everything else inside the padded bounds."""
        doc = load_doc()

        def check(lon, lat, where, bounds=BOUNDS):
            self.assertTrue(inside(lat, lon, bounds), f"{where}: {lat}, {lon} outside the bounds")
            self.assertEqual(round(lon, 4), lon, where)
            self.assertEqual(round(lat, 4), lat, where)

        for key in ("land", "borders", "counties", "lakes", "rivers", "roads"):
            for f in doc[key]["features"]:
                g = f["geometry"]
                outer = f["properties"].get("kind") in ("context", "country")
                parts = (lines(g) if "Line" in g["type"] else [r for poly in polygons(g) for r in poly])
                for part in parts:
                    self.assertGreaterEqual(len(part), 2, key)
                    for lon, lat in part:
                        check(lon, lat, key, CONTEXT_BOUNDS if outer else BOUNDS)
        for item in doc["labels"] + doc["places"]:
            check(item["lon"], item["lat"], item.get("text") or item.get("name"), CONTEXT_BOUNDS)


class Land(unittest.TestCase):
    def setUp(self):
        self.doc = load_doc()
        self.land = {f["properties"]["abbrev"]: f for f in self.doc["land"]["features"]}

    def montana(self):
        mt = [f for f in self.doc["land"]["features"] if f["properties"]["montana"]]
        self.assertEqual(len(mt), 1)
        return mt[0]

    def test_rings_closed(self):
        for f in self.doc["land"]["features"] + self.doc["lakes"]["features"]:
            for poly in polygons(f["geometry"]):
                for ring in poly:
                    self.assertGreaterEqual(len(ring), 4, f["properties"])
                    self.assertEqual(ring[0], ring[-1], f["properties"])

    def test_montana_polygon(self):
        mt = self.montana()
        self.assertEqual(mt["properties"]["name"], "Montana")
        self.assertEqual(mt["properties"]["abbrev"], "MT")
        self.assertEqual(mt["properties"]["admin"], "United States of America")
        polys = polygons(mt["geometry"])
        self.assertEqual(len(polys), 1, "Montana is one piece")
        ring = polys[0][0]
        self.assertGreater(len(ring), 100)
        self.assertAlmostEqual(area_km2(ring) / MONTANA_KM2, 1.0, delta=0.015)
        lats, lons = [p[1] for p in ring], [p[0] for p in ring]
        self.assertEqual(max(lats), 49.0)
        self.assertAlmostEqual(min(lats), 44.358, delta=0.02)
        self.assertAlmostEqual(min(lons), -116.05, delta=0.02)
        self.assertAlmostEqual(max(lons), -104.04, delta=0.02)

    def test_montana_shape(self):
        ring = polygons(self.montana()["geometry"])[0][0]
        north = [p for p in ring if p[1] > 48.95]
        self.assertTrue(north and all(p[1] == 49.0 for p in north), "northern border straight on 49°")
        # The southern border is the 45th parallel east of Yellowstone; only west of the Wyoming line
        # (111.05° W) does Montana reach south of it (the notch down to 44.36° near West Yellowstone).
        self.assertTrue(all(p[0] < -111.0 for p in ring if p[1] < 44.99))
        south45 = [p for p in ring if -111.0 < p[0] < -104.1 and p[1] < 45.5]
        self.assertTrue(south45 and all(abs(p[1] - 45.0) < 0.02 for p in south45))
        self.assertTrue(any(abs(p[1] - 45.0) < 0.02 and abs(p[0] + 111.05) < 0.02 for p in ring),
                        "the corner where the 45th parallel meets the Wyoming line")
        # the Idaho border is the long wiggly side: many vertices west of 112.5° W below 47.9° N
        self.assertGreater(len([p for p in ring if p[0] < -112.5 and 44.4 < p[1] < 47.9]), 40)

    def test_every_site_town_inside_montana(self):
        rings = polygons(self.montana()["geometry"])[0]
        for t in TOWNS:
            self.assertTrue(point_in((t["lon"], t["lat"]), rings), t["name"])

    def test_neighbours(self):
        for abbrev, admin in (("ID", "United States of America"), ("WY", "United States of America"),
                              ("ND", "United States of America"), ("SD", "United States of America"),
                              ("BC", "Canada"), ("AB", "Canada"), ("SK", "Canada")):
            self.assertIn(abbrev, self.land)
            self.assertEqual(self.land[abbrev]["properties"]["admin"], admin)
            self.assertFalse(self.land[abbrev]["properties"]["montana"])

    def test_us_canada_seam_on_49(self):
        """The two countries' polygons meet on exactly 49° (no gap, no overlap)."""
        for abbrev in ("BC", "AB", "SK"):
            pts = [p for poly in polygons(self.land[abbrev]["geometry"]) for r in poly for p in r]
            self.assertEqual(min(p[1] for p in pts), 49.0, abbrev)
        for abbrev in ("ID", "MT", "ND"):
            pts = [p for poly in polygons(self.land[abbrev]["geometry"]) for r in poly for p in r]
            self.assertEqual(max(p[1] for p in pts), 49.0, abbrev)

    def test_borders(self):
        kinds = {(f["properties"]["kind"], f["properties"]["montana"]) for f in self.doc["borders"]["features"]}
        self.assertEqual(kinds, {("country", True), ("country", False), ("state", True), ("state", False),
                                 ("context", False)})
        for f in self.doc["borders"]["features"]:
            if f["properties"]["kind"] == "country":
                self.assertTrue(all(p[1] == 49.0 for part in lines(f["geometry"]) for p in part))


class Counties(unittest.TestCase):
    def test_all_56_counties_once_each_line(self):
        doc = load_doc()
        names, seen = set(), set()
        for f in doc["counties"]["features"]:
            between = f["properties"]["between"]
            self.assertEqual(len(between), 2)
            self.assertNotEqual(between[0], between[1])
            names.update(between)
            coords = tuple(map(tuple, f["geometry"]["coordinates"]))
            self.assertEqual(f["geometry"]["type"], "LineString")
            key = min(coords, coords[::-1])
            self.assertNotIn(key, seen, "a county line is drawn twice")
            seen.add(key)
        self.assertEqual(len(names), 56, sorted(names))
        for name in ("Yellowstone", "Gallatin", "Lewis and Clark", "Silver Bow", "Wibaux", "Petroleum"):
            self.assertIn(name, names)

    def test_county_lines_are_inside_montana(self):
        doc = load_doc()
        mt = [f for f in doc["land"]["features"] if f["properties"]["montana"]][0]
        rings = polygons(mt["geometry"])[0]
        for f in doc["counties"]["features"]:
            c = f["geometry"]["coordinates"]
            k = len(c) // 2
            mid = ((c[k - 1][0] + c[k][0]) / 2, (c[k - 1][1] + c[k][1]) / 2) if len(c) % 2 == 0 else tuple(c[k])
            self.assertTrue(point_in(mid, rings), f["properties"])


class Water(unittest.TestCase):
    def test_lakes_rivers_roads(self):
        doc = load_doc()
        lakes = {f["properties"]["name"] for f in doc["lakes"]["features"]}
        for name in ("Flathead Lake", "Fort Peck Lake", "Canyon Ferry Lake", "Yellowstone Lake"):
            self.assertIn(name, lakes)
        rivers = {f["properties"]["name"]: f["properties"] for f in doc["rivers"]["features"]}
        for name in ("Missouri", "Yellowstone"):
            self.assertEqual(rivers[name]["rank"], 1, name)
        self.assertTrue(all(f["properties"]["rank"] in (1, 2, 3) for f in doc["rivers"]["features"]))
        refs = {f["properties"]["ref"]: f["properties"] for f in doc["roads"]["features"]}
        for ref in ("I-90", "I-94", "I-15"):
            self.assertEqual(refs[ref]["type"], "interstate", ref)
        for ref in ("US-2", "US-87", "US-93", "US-191", "US-212"):
            self.assertEqual(refs[ref]["type"], "us", ref)
        self.assertTrue(all(f["properties"]["type"] in ("interstate", "us") for f in doc["roads"]["features"]))
        for key in ("lakes", "rivers", "roads"):
            for f in doc[key]["features"]:
                self.assertIn(f["properties"]["min_zoom"], range(5, 12), (key, f["properties"]))

    def test_interstates_reach_their_montana_towns(self):
        """I-90 passes Missoula, Butte, Bozeman, Billings; I-94 Miles City and Glendive; I-15 Helena
        and Great Falls: each within 8 km of the road line."""
        doc = load_doc()
        roads = {f["properties"]["ref"]: lines(f["geometry"]) for f in doc["roads"]["features"]}
        towns = {t["name"]: t for t in TOWNS}
        for ref, names in (("I-90", ["Missoula", "Butte", "Bozeman", "Livingston", "Billings"]),
                           ("I-94", ["Miles City", "Glendive"]), ("I-15", ["Butte", "Helena", "Great Falls"])):
            for name in names:
                t = towns[name]
                self.assertLess(km_to_lines((t["lon"], t["lat"]), roads[ref]), 8, f"{ref} near {name}")


class Places(unittest.TestCase):
    def setUp(self):
        self.doc = load_doc()

    def test_every_site_town_marked_not_dropped(self):
        sites = [p for p in self.doc["places"] if p.get("site")]
        self.assertEqual(len(sites), len(TOWNS))
        by_slug = {p["slug"]: p for p in sites}
        for t in TOWNS:
            p = by_slug[t["slug"]]
            self.assertEqual((p["name"], p["lat"], p["lon"]), (t["name"], t["lat"], t["lon"]))
            self.assertEqual(p["rank"], 1)
            self.assertIs(p["site"], True)
            self.assertEqual(p["state"], "MT")
            self.assertEqual(p["min_zoom"], 7 if t.get("minor") else 5)
        others = {p["name"] for p in self.doc["places"] if not p.get("site")}
        self.assertFalse(others & {t["name"] for t in TOWNS}, "a site town is also a plain place")

    def test_place_fields(self):
        for p in self.doc["places"]:
            self.assertTrue(p["name"])
            self.assertIn(p["rank"], (1, 2, 3, 4), p)
            self.assertIn(p["min_zoom"], range(5, 10), p)
            self.assertRegex(p["state"], r"^[A-Z]{2}$")
            self.assertEqual(inside(p["lat"], p["lon"], IMAGE_BOUNDS), p["name"] not in CONTEXT_PLACES, p["name"])
            if not p.get("site"):
                self.assertGreaterEqual(p["rank"], 2, p)
        names = {p["name"] for p in self.doc["places"]}
        for city in ("Spokane", "Lethbridge", "Medicine Hat", "Williston", "Cody", "Idaho Falls"):
            self.assertIn(city, names)

    def test_only_big_places_at_state_zoom(self):
        early = [p for p in self.doc["places"] if not p.get("site") and p["min_zoom"] <= 6]
        self.assertTrue(early)
        self.assertTrue(all(p["rank"] <= 3 for p in early), early)
        in_box = [p for p in early if inside(p["lat"], p["lon"], IMAGE_BOUNDS)]   # context cities: test_names
        self.assertLessEqual(len([p for p in in_box if p["min_zoom"] == 5]), 6)


class Labels(unittest.TestCase):
    def setUp(self):
        self.doc = load_doc()
        self.labels = self.doc["labels"]
        self.land = {f["properties"]["abbrev"]: f for f in self.doc["land"]["features"]}

    def test_fields_and_kinds(self):
        for lab in self.labels:
            self.assertIn(lab["kind"], LABEL_KINDS, lab)
            self.assertTrue(lab["text"].strip(), lab)
            self.assertIn(lab["min_zoom"], range(5, 12), lab)
            if "max_zoom" in lab:
                self.assertGreaterEqual(lab["max_zoom"], lab["min_zoom"], lab)
        for text, kind in (("CANADA", "country"), ("UNITED STATES", "country"), ("MONTANA", "region-main"),
                           ("Flathead Lake", "water"), ("Fort Peck Lake", "water")):
            labs = [lab for lab in self.labels if lab["text"] == text]
            self.assertTrue(labs, text)
            self.assertTrue(all(lab["kind"] == kind for lab in labs), text)
        self.assertTrue(shown(self.labels, "MONTANA", 6))
        for z in range(5, 12):
            self.assertTrue(shown(self.labels, "CANADA", z), f"no CANADA at zoom {z}")

    def test_each_label_shows_once_at_a_time(self):
        """A text may come twice (each Canadian label has one copy for zoom 5 and one from zoom 6), but
        a map that hides labels above their max_zoom never shows it twice at once."""
        for text in {lab["text"] for lab in self.labels}:
            for z in range(5, 12):
                self.assertLessEqual(len(shown(self.labels, text, z)), 1, f"{text} twice at zoom {z}")

    def test_canadian_labels_in_the_first_view(self):
        """The map opens on Montana fitted between its controls (map.js fitView). On a wide screen (zoom
        6 and up) that shows only a thin strip of Canada: with no banner the top edge is at 49.25° N at
        1440x789 and 49.27° N at 1920x1080 (measured in Chromium), so a 12 px label must sit by about
        49.2° N. A phone (zoom 5) shows far into Canada, but a 412 px one only from 116.45° W to
        103.65° W. So at every zoom CANADA, AB, SK and BC sit in that view, between 116.0° W and 104.1° W."""
        for text in ("CANADA", "AB", "SK", "BC"):
            for z in range(5, 12):
                labs = shown(self.labels, text, z)
                self.assertEqual(len(labs), 1, f"{text} at zoom {z}")
                lat, lon = labs[0]["lat"], labs[0]["lon"]
                self.assertTrue(-116.0 <= lon <= -104.1, f"{text} at zoom {z}: {lon} is off a phone's first view")
                self.assertGreater(lat, 49.0, text)
                if z >= 6:
                    self.assertLessEqual(lat, 49.2, f"{text} at zoom {z}: {lat} is off a wide screen's first view")

    def test_region_labels_inside_their_region(self):
        (s, w), (n, e) = IMAGE_BOUNDS
        canada = [r for a in ("BC", "AB", "SK") for poly in polygons(self.land[a]["geometry"]) for r in poly]
        for abbrev in ("ID", "WY", "ND", "SD", "BC", "AB", "SK", "MT", "CANADA"):
            text = {"MT": "MONTANA"}.get(abbrev, abbrev)
            rings = canada if abbrev == "CANADA" else [r for poly in polygons(self.land[abbrev]["geometry"])
                                                       for r in poly]
            labs = [lab for lab in self.labels if lab["text"] == text]
            self.assertTrue(labs, text)
            for lab in labs:
                self.assertTrue(point_in((lab["lon"], lab["lat"]), rings), text)
                self.assertTrue(s <= lab["lat"] <= n and w <= lab["lon"] <= e, text)

    def test_water_labels_near_their_lake(self):
        lakes = {}
        for f in self.doc["lakes"]["features"]:
            rings = [r for poly in polygons(f["geometry"]) for r in poly]
            lakes.setdefault(f["properties"]["name"], []).extend(rings)
        for lab in self.labels:
            if lab["kind"] == "water":
                self.assertIn(lab["text"], lakes)
                self.assertTrue(point_in((lab["lon"], lab["lat"]), lakes[lab["text"]]), lab["text"])

    def test_montana_label_clear_of_site_towns(self):
        lab = [x for x in self.labels if x["kind"] == "region-main"][0]
        for z in range(lab["min_zoom"], lab.get("max_zoom", 11) + 1):
            lx, ly = project(lab["lat"], lab["lon"], z)
            for t in TOWNS:
                if z < 7 and t.get("minor"):
                    continue
                tx, ty = project(t["lat"], t["lon"], z)
                self.assertGreater(math.hypot(lx - tx, ly - ty), 30, f"zoom {z}: MONTANA on {t['name']}")

    def test_labels_and_places_never_cover_a_bubble_or_each_other(self):
        """The tool's own layout check (label sizes as map.css draws them), zooms 5-11: labels, places,
        bubbles and town names, town against town too (one 4 px allowance at zoom 5, TOUCH_Z5).
        This is the label test AGENTS.md means: it must pass when a town is added or moved."""
        tool = load_tool()
        self.assertEqual(tool.check_layout(TOWNS, self.labels, self.doc["places"]), [])

    def test_a_town_over_another_town_fails_the_check(self):
        tool = load_tool()
        near = {"name": "Testville", "slug": "testville", "lat": 45.9, "lon": -108.9, "label": "right"}
        problems = tool.check_layout(TOWNS + [near], self.labels, self.doc["places"])
        self.assertIn("z5: town Testville name / town Billings bubble", " | ".join(problems))
        self.assertIn("z5: town Billings bubble / town Testville bubble", " | ".join(problems))
        # the allowance is for zoom 5 only, and only as deep as TOUCH_Z5
        towns = [dict(t, label="top") if t["name"] == "Billings" else t for t in TOWNS]
        self.assertTrue(any(p.startswith("z5: town Billings name") for p in tool.town_contacts(towns)))
        with mock.patch.object(tool, "TOUCH_Z5", 0.0):
            self.assertEqual(len(tool.town_contacts(TOWNS)), 2)            # Missoula/Kalispell, Billings/Miles City
        self.assertEqual([p for p in tool.town_contacts(TOWNS)], [])

    def test_town_geometry_is_what_the_map_draws(self):
        """town_boxes models map.js drawTowns and map.css .town: change them together."""
        tool = load_tool()
        css = (ROOT / "website" / "static" / "map" / "map.css").read_text()
        js = (ROOT / "website" / "static" / "map" / "map.js").read_text()
        self.assertIn("iconSize: [30, 30], iconAnchor: [15, 15]", js)
        for side, edge in (("right", "left"), ("left", "right"), ("top", "bottom"), ("bottom", "top")):
            self.assertRegex(css, rf"\.town\.side-{side} \.tname \{{ {edge}: 35px;")
        self.assertRegex(css, r"\.town \.tname \{[^}]*font-size: 13px;[^}]*line-height: 1;")
        self.assertEqual((tool.BUBBLE_R, tool.TOWN_NAME_OFF, tool.TOWN_H), (15.0, 35 - 30 / 2, 13.0))
        self.assertEqual(set(tool.TOWN_LABEL_W), {t["name"] for t in TOWNS})


class Context(unittest.TestCase):
    """The coarse layer outside the padded bounds: a phone's first view reaches far past them (about
    39-59.7° N at 390x844), and the reference runs a map edge to edge."""

    def setUp(self):
        self.doc = load_doc()
        self.outer, self.inner = [], []         # context lines (with the 49th parallel's), the box's lines
        for f in self.doc["borders"]["features"]:
            for part in lines(f["geometry"]):
                boxed = f["properties"]["kind"] != "context" and all(inside(y, x, BOUNDS) for x, y in part)
                (self.inner if boxed else self.outer).append([tuple(p) for p in part])

    @staticmethod
    def on_edge(p, bounds=BOUNDS):
        (s, w), (n, e) = bounds
        return inside(p[1], p[0], bounds) and (p[0] in (w, e) or p[1] in (s, n))

    def test_lines_stay_out_of_the_box(self):
        """No context line inside the padded bounds, where the box's own lines are drawn: no double lines."""
        (s, w), (n, e) = BOUNDS
        self.assertGreater(len(self.outer), 20)
        for part in self.outer:
            for (x1, y1), (x2, y2) in zip(part, part[1:]):
                for x, y in ((x1, y1), ((x1 + x2) / 2, (y1 + y2) / 2)):
                    self.assertFalse(s < y < n and w < x < e, f"a context line inside the box at {y}, {x}")

    def test_lines_meet_the_box_lines(self):
        """Every border leaving the box goes on in the context layer, and every context line reaching
        the box goes on inside it, within 1.5 km (Natural Earth outside, the Census lines inside)."""
        inner = [p for part in self.inner for p in (part[0], part[-1]) if self.on_edge(p)]
        outer = [p for part in self.outer for p in (part[0], part[-1]) if self.on_edge(p)]
        self.assertGreaterEqual(len(inner), 11)
        for a, b, what in ((inner, outer, "box line"), (outer, inner, "context line")):
            for p in a:
                self.assertLess(min(km(p, q) for q in b), 1.5, f"the {what} ending at {p} goes on nowhere")

    def test_no_loose_ends(self):
        """A context line ends on the layer's edge, on the box's edge or where other lines end: so no
        coastline (the layer stops east of the Pacific) and no gap."""
        ends = [p for part in self.outer for p in (part[0], part[-1])]
        meets = collections.Counter(ends)
        for p in ends:
            self.assertTrue(self.on_edge(p, CONTEXT_BOUNDS) or self.on_edge(p) or meets[p] > 1,
                            f"a context line ends at {p}")

    def test_known_borders_drawn(self):
        for name, pt in (("AB-SK", (-110.0, 55.0)), ("BC-AB", (-120.0, 57.0)), ("SK-MB", (-102.0, 58.0)),
                         ("60th parallel", (-105.0, 60.0)), ("WY-CO", (-106.0, 41.0)), ("UT-NV", (-114.04, 39.5)),
                         ("CA-NV", (-120.0, 40.5)), ("ND-SD", (-98.0, 45.94)), ("NE-KS", (-99.0, 40.0)),
                         ("ID-UT", (-112.5, 42.0)), ("49th parallel, west", (-121.0, 49.0)),
                         ("49th parallel, east", (-96.0, 49.0))):
            self.assertLess(km_to_lines(pt, self.outer), 2.0, name)

    def test_country_border_runs_on_along_49(self):
        country = [p for f in self.doc["borders"]["features"] if f["properties"]["kind"] == "country"
                   for p in lines(f["geometry"])]
        lons = sorted(x for part in country for x, _ in part)
        self.assertEqual((lons[0], lons[-1]), (-122.0, -95.2))
        covered = sorted((min(x for x, _ in part), max(x for x, _ in part)) for part in country)
        reach = covered[0][1]
        for lo, hi in covered[1:]:
            self.assertLessEqual(lo, reach, f"a gap in the 49th parallel at {reach}")
            reach = max(reach, hi)

    def test_names(self):
        """The context's state abbreviations and cities: inside their state or province, none twice,
        and on a phone's first view (zoom 5.25-5.5): the state and province names from zoom 5, the
        cities by zoom 6 (Winnipeg's name would run past the layer's edge at 5). map.js hides any name
        that a panel or the note's line would cut."""
        labels = [lab for lab in self.doc["labels"] if not inside(lab["lat"], lab["lon"], IMAGE_BOUNDS)]
        self.assertEqual(sorted(lab["text"] for lab in labels), sorted(CONTEXT_REGIONS))
        for lab in labels:
            s, w, n, e = CONTEXT_REGIONS[lab["text"]]
            self.assertTrue(s <= lab["lat"] <= n and w <= lab["lon"] <= e, lab)
            self.assertEqual(lab["kind"], "region", lab)
            self.assertEqual(lab["min_zoom"], 5, lab)
            self.assertNotIn("max_zoom", lab)
        places = [p for p in self.doc["places"] if not inside(p["lat"], p["lon"], IMAGE_BOUNDS)]
        self.assertEqual({p["name"]: p["state"] for p in places}, CONTEXT_PLACES)
        for p in places:
            self.assertLessEqual(p["min_zoom"], 6, p)
            self.assertLessEqual(p["rank"], 3, p)
        names = [p["name"] for p in self.doc["places"]]
        self.assertEqual(len(names), len(set(names)), "a place comes twice")


class Tool(unittest.TestCase):
    """The generator's geometry helpers on tiny inputs (no network, no numpy)."""

    @classmethod
    def setUpClass(cls):
        cls.t = load_tool()

    def test_decode_topojson_arcs(self):
        topo = {"transform": {"scale": [0.5, 0.25], "translate": [-110.0, 45.0]},
                "arcs": [[[0, 0], [2, 0], [0, 4]], [[2, 4], [-2, 0]]]}
        arcs = self.t.decode_arcs(topo)
        self.assertEqual(arcs[0], [(-110.0, 45.0), (-109.0, 45.0), (-109.0, 46.0)])
        self.assertEqual(arcs[1], [(-109.0, 46.0), (-110.0, 46.0)])
        # ~1 is arc 1 reversed; the shared point is kept once
        ring = self.t.stitch(arcs, [0, 1])
        self.assertEqual(ring, [(-110.0, 45.0), (-109.0, 45.0), (-109.0, 46.0), (-110.0, 46.0)])
        self.assertEqual(self.t.stitch(arcs, [~1]), [(-110.0, 46.0), (-109.0, 46.0)])

    def test_clip_ring_to_box(self):
        square = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)]
        clipped = self.t.clip_ring(square, (1.0, 1.0, 2.0, 3.0))       # (s, w, n, e)
        self.assertEqual(clipped[0], clipped[-1])
        self.assertEqual(sorted(set(clipped)), [(1.0, 1.0), (1.0, 2.0), (3.0, 1.0), (3.0, 2.0)])
        self.assertEqual(self.t.clip_ring(square, (10.0, 10.0, 11.0, 11.0)), [])

    def test_clip_line_splits_where_it_leaves(self):
        line = [(0.0, 0.5), (2.0, 0.5), (2.0, 3.0), (0.5, 3.0), (0.5, 0.8)]
        parts = self.t.clip_line(line, (0.0, 0.0, 1.0, 1.0))
        self.assertEqual(parts, [[(0.0, 0.5), (1.0, 0.5)], [(0.5, 1.0), (0.5, 0.8)]])
        # clip_line_outside keeps the rest (the context layer: everything outside the box)
        self.assertEqual(self.t.clip_line_outside(line, (0.0, 0.0, 1.0, 1.0)),
                         [[(1.0, 0.5), (2.0, 0.5), (2.0, 3.0), (0.5, 3.0), (0.5, 1.0)]])
        self.assertEqual(self.t.clip_line_outside([(-1.0, 0.5), (2.0, 0.5)], (0.0, 0.0, 1.0, 1.0)),
                         [[(-1.0, 0.5), (0.0, 0.5)], [(1.0, 0.5), (2.0, 0.5)]])
        self.assertEqual(self.t.clip_line_outside([(0.2, 0.2), (0.8, 0.8)], (0.0, 0.0, 1.0, 1.0)), [])

    def test_simplify_keeps_ends_and_corners(self):
        line = [(0.0, 0.0), (1.0, 0.00001), (2.0, 0.0), (2.0, 1.0)]
        self.assertEqual(self.t.simplify(line, 0.001), [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0)])

    def test_shared_border_becomes_one_arc(self):
        a = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
        b = [(1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
        arcs, refs = self.t.build_topology([a, b])
        self.assertEqual(len(arcs), 3)
        shared = set(i for i, _ in refs[0]) & set(i for i, _ in refs[1])
        self.assertEqual(len(shared), 1)
        self.assertEqual(sorted(arcs[shared.pop()]), [(1.0, 0.0), (1.0, 1.0)])
        for ring, ref in zip((a, b), refs):
            out = self.t.assemble(arcs, ref)
            self.assertEqual(out[0], out[-1])
            self.assertEqual(set(out), set(ring))

    def test_border_snap(self):
        self.assertEqual(self.t.snap49((-110.0, 48.9925)), (-110.0, 49.0))
        self.assertEqual(self.t.snap49((-110.0, 48.95)), (-110.0, 48.95))
        self.assertEqual(self.t.snap49((-90.0, 48.995)), (-90.0, 48.995))     # east of the 49th-parallel border

    def test_default_download_folder_is_deleted(self):
        """Without --src the downloads (about 115 MB) go to a temp folder that is deleted afterwards,
        also when the build fails; a folder given with --src is kept as a cache."""
        seen = []

        def fake_build(src):
            seen.append(src)
            self.assertTrue(src.is_dir())
            return '{"version":1}\n', {}, []

        def failing_build(src):
            seen.append(src)
            raise SystemExit("not the pinned file")

        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            out = Path(tmp) / "basemap.json"
            with mock.patch.object(self.t, "build", fake_build):
                self.assertEqual(self.t.main(["--out", str(out)]), 0)
                self.assertFalse(seen[-1].exists(), "the temp download folder was left behind")
                keep = Path(tmp) / "cache"
                keep.mkdir()
                self.assertEqual(self.t.main(["--src", str(keep), "--out", str(out)]), 0)
                self.assertEqual(seen[-1], keep)
                self.assertTrue(keep.is_dir())
            with mock.patch.object(self.t, "build", failing_build), self.assertRaises(SystemExit):
                self.t.main(["--out", str(out)])
            self.assertFalse(seen[-1].exists(), "the temp download folder was left behind after a failure")


if __name__ == "__main__":
    unittest.main()
