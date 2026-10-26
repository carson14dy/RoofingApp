"""Tests for website/buildings.py (B3 outlines): the words, the geometry-only reader, the WKB parser, the dot rule, the join
(D15, D32), the shards (D26, D28), the restore of the address shards (byte-identical to the addresses module), the wiring,
the source-failure path, the download cache and the command line. Every test works in a folder it made and deletes only
that folder. The tests need no pyogrio except the one that is skipped when it does not import."""
import importlib.util
import json
import re
import shutil
import struct
import sys
import tempfile
import unittest
import zipfile
from collections import namedtuple
from pathlib import Path
from unittest import mock

import numpy as np
import requests

from website import addresses as A
from website import buildings as B
from website import hail as H

try:
    import yaml
except ImportError:                       # the job and the suite have PyYAML; a bare checkout may not
    yaml = None

ROOT = Path(__file__).resolve().parents[1]

# D29 and D34: the words of the building layer. "parcel" is not listed: D32 requires the phrase "at the parcel" for a
# Parcel-placed point, and the words test checks that phrase in its own right.
FORBIDDEN_WORDS = ("home", "homes", "house", "houses", "residence", "residences", "dwelling", "dwellings", "use", "uses",
                   "owner", "owners", "population")
# The FEMA layer's attribute names and the building words the module must never name (decision 6, D12, D14).
FORBIDDEN_NAMES = ("OCC_CLS", "PRIM_OCC", "PROP_ADDR", "PROP_CITY", "PROP_ZIP", "PROP_CNTY", "PROP_ST", "SQFEET",
                   "HEIGHT", "POP_MEDIAN", "B_CODE", "OUTBLDG", "SEC_OCC", "VAL_METHOD", "CENSUSCODE", "UUID",
                   "REMARKS", "FIPS", "GlobalID", "OBJECTID", "Shape_Area", "Shape_Length", "STATE_FIPS")
SCALE = 100000
Row = namedtuple("Row", "lon5 lat5 line city zip number street unit add key cls county")


def rect(x0, y0, w, h):
    """A closed counter-clockwise ring of (lon, lat) for a rectangle."""
    return np.array([[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h], [x0, y0]], dtype=np.float64)


def wkb_polygon(rings, endian="<", code=3, srid=None):
    fmt = endian
    head = (b"\x01" if endian == "<" else b"\x00")
    t = code | (0x20000000 if srid is not None else 0)
    out = head + struct.pack(fmt + "I", t) + (struct.pack(fmt + "I", srid) if srid is not None else b"")
    out += struct.pack(fmt + "I", len(rings))
    for ring in rings:
        out += struct.pack(fmt + "I", len(ring))
        if code >= 1000:                    # a Z type: each point carries a height, which the reader drops
            out += b"".join(struct.pack(fmt + "ddd", float(x), float(y), 10.0) for x, y in ring)
        else:
            out += b"".join(struct.pack(fmt + "dd", float(x), float(y)) for x, y in ring)
    return out


def wkb_multi(polys):
    out = b"\x01" + struct.pack("<I", 6) + struct.pack("<I", len(polys))
    for rings in polys:
        out += wkb_polygon(rings)
    return out


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b""):
        self.status_code = status
        self.headers = headers or {}
        self._body = body

    def iter_content(self, chunk_size=1024):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, head=None, get=None, head_error=None):
        self._head = head
        self._get = get
        self.head_error = head_error
        self.heads = 0
        self.gets = 0

    def head(self, url, **kwargs):
        self.heads += 1
        if self.head_error is not None:
            raise self.head_error
        return self._head

    def get(self, url, **kwargs):
        self.gets += 1
        return self._get


class Scratch(unittest.TestCase):
    """A folder made by the test, removed by the test (never a shared or system folder)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="buildings-test-"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class WordsTest(unittest.TestCase):
    def strings(self):
        out = [v for v in B.WORDS_BUILDINGS.values() if isinstance(v, str)]
        out += list(A.PLACEMENT_HOW.values())
        out += [v for v in B.describe_buildings(None).values() if isinstance(v, str)]
        return out

    def test_no_forbidden_word_and_structure_only_in_the_proper_name(self):
        for text in self.strings():
            for word in FORBIDDEN_WORDS:
                self.assertIsNone(re.search(rf"\b{word}\b", text, re.IGNORECASE), f"{word!r} in {text!r}")
            for match in re.finditer("structure", text, re.IGNORECASE):
                self.assertEqual(text[max(0, match.start() - 4):match.start()], "USA ", text)
            self.assertNotIn("\u2014", text)
            self.assertNotIn("–", text)

    def test_the_sentences_of_decisions_29_and_34(self):
        w = B.WORDS_BUILDINGS
        self.assertEqual(w["legend"], "Each dot is one building outline. Tap a dot for its address, if one is on file, "
                                      "and the weather history for its cell.")
        self.assertEqual(w["no_address"], "No address on file for this building. The weather history below is for this "
                                          "building's cell.")
        self.assertEqual(w["units"], "Units on file: {n}.")
        self.assertEqual(w["placed"], "This address point was placed {how}, not on the building.")
        self.assertEqual(w["count_bubble"], "{n} buildings")
        self.assertEqual(w["about_caveat"], "Outlines come from imagery dated 2008 to 2025 and are not surveys; sheds "
                                            "and barns are outlines too.")
        loaded = {"buildings": {"state": "loaded", "source": {"file_date": "2026-09-13"}}}
        self.assertEqual(B.describe_buildings(loaded)["source"],
                         "Building outlines: USA Structures, Oak Ridge National Laboratory and FEMA (file dated "
                         "2026-09-13).")

    def test_placement_phrases_of_decision_32(self):
        self.assertEqual(dict(A.PLACEMENT_HOW), {"P": "at the property entrance", "G": "along the road by its number",
                                                 "L": "at the parcel", "T": "at the site",
                                                 "U": "by a method the file does not state"})

    def test_map_data_zoom_and_radius_rules(self):
        self.assertEqual(B.map_data_buildings({})["state"], "unavailable")
        block = {"state": "loaded", "reason": None, "source": {"file_date": "2026-09-13"},
                 "counts": {"footprints": 3, "multipart": 0, "with_addresses": 1, "without_address": 2,
                            "matched_rows": 1, "unmatched_rows": 0, "unmatched_by_class": {}},
                 "tiles": ["r0092_c0215"], "split_boxes": {}, "overhang_deg": 0.0, "addresses": "loaded"}
        data = B.map_data_buildings({"buildings": block})
        self.assertEqual(data["zoom"], {"counts": [13, 14], "dots": 15, "fills": 16, "emphasis": 17})
        self.assertEqual(data["tap_radius_px"], 12)
        self.assertEqual(data["shard"], "hail/b/{name}.json")
        self.assertEqual(data["templates"]["count_bubble"], "{n} buildings")
        self.assertEqual(data["dot_radius_px"]["max"], 4.0)
        rule = data["dot_radius_px"]              # the browser's rule (map.js b3Radius): linear, capped at max
        radius = [min(rule["max"], rule["at_zoom"] + rule["per_zoom"] * (z - rule["zoom"])) for z in (13, 14, 15, 16, 17)]
        self.assertEqual(radius, [2.5, 3.0, 3.5, 4.0, 4.0])      # D7: 2.5 px at zoom 13, 4 px from zoom 16


class ForbiddenNamesTest(unittest.TestCase):
    def test_the_module_names_no_building_attribute_and_no_owner_word(self):
        text = Path(B.__file__).read_text(encoding="utf-8")
        for name in FORBIDDEN_NAMES:
            self.assertNotIn(name, text, name)
        for word in ("owner", "parcel", "population", "house", "home", "residence", "dwelling"):
            self.assertIsNone(re.search(rf"\b{word}", text, re.IGNORECASE), word)

    def test_the_reader_asks_for_no_attribute_columns(self):
        calls = {}

        class Raw:
            @staticmethod
            def read(path, **kwargs):
                calls.update(kwargs)
                geoms = np.array([wkb_polygon([rect(-108.5, 45.78, 0.001, 0.001)[:, :]]),
                                  wkb_polygon([rect(-108.4, 45.78, 0.001, 0.001)[:, :]])], dtype=object)
                return ({}, None, geoms, ())

        fake = mock.Mock()
        fake.list_layers.return_value = np.array([["MT_Structures", "MultiPolygon"]], dtype=object)
        fake.read_info.return_value = {"geometry_type": "MultiPolygon", "crs": "EPSG:4326", "features": 2}
        fake.raw = Raw
        with mock.patch.object(B, "_pyogrio", return_value=fake), mock.patch.object(B, "EXPECTED_FEATURES", 2):
            geo = B.read_outlines(Path("/nowhere.gdb"), np)
        self.assertEqual(calls["columns"], [])
        self.assertTrue(calls["read_geometry"])
        self.assertEqual(geo.count, 2)

    def test_the_reader_refuses_a_changed_layer(self):
        def fake_with(info, names=(("MT_Structures", "MultiPolygon"),), fields=()):
            class Raw:
                @staticmethod
                def read(path, **kwargs):
                    geoms = np.array([wkb_polygon([rect(-108.5, 45.78, 0.001, 0.001)]),
                                      wkb_polygon([rect(-108.4, 45.78, 0.001, 0.001)])], dtype=object)
                    return ({}, None, geoms, fields)
            fake = mock.Mock()
            fake.list_layers.return_value = np.array([list(n) for n in names], dtype=object)
            fake.read_info.return_value = info
            fake.raw = Raw
            return fake

        good = {"geometry_type": "MultiPolygon", "crs": "EPSG:4326", "features": 2}
        cases = [
            fake_with({**good, "geometry_type": "Point"}),
            fake_with({**good, "crs": "EPSG:6514"}),
            fake_with({**good, "features": 5}),
            fake_with(good, names=(("MT_Structures", "MultiPolygon"), ("Other", "Point"))),
            fake_with(good, fields=(np.array(["OCC_CLS"]),)),
        ]
        for fake in cases:
            with mock.patch.object(B, "_pyogrio", return_value=fake), mock.patch.object(B, "EXPECTED_FEATURES", 2):
                with self.assertRaises(B.SourceUnavailable):
                    B.read_outlines(Path("/nowhere.gdb"), np)

    def test_the_reader_needs_the_library(self):
        with mock.patch.dict(sys.modules, {"pyogrio": None}):
            with self.assertRaises(B.SourceUnavailable):
                B._pyogrio()


@unittest.skipUnless(importlib.util.find_spec("pyogrio") is not None, "pyogrio is not installed (the job installs it)")
class PyogrioReaderTest(Scratch):
    def test_gdal_reads_the_rings_the_module_decodes(self):
        import pyogrio.raw as raw
        square = [[-108.5, 45.78], [-108.4999, 45.78], [-108.4999, 45.7801], [-108.5, 45.7801], [-108.5, 45.78]]
        geoms = np.array([bytes(wkb_multi([[square]])), bytes(wkb_multi([[square], [square]]))], dtype=object)
        path = self.dir / "test.gpkg"
        raw.write(str(path), geoms, [], [], crs="EPSG:4326", geometry_type="MultiPolygon", layer="MT_Structures",
                  driver="GPKG")
        _m, _f, back, fields = raw.read(str(path), layer="MT_Structures", columns=[], read_geometry=True)
        self.assertEqual(len(fields), 0)
        rings: list = []
        counts = [B.wkb_polygons(bytes(g), np, rings) for g in back]
        self.assertEqual(counts, [1, 2])
        self.assertEqual(len(rings), 3)
        np.testing.assert_allclose(rings[0], np.array(square), atol=1e-9)


class WkbTest(unittest.TestCase):
    def test_polygon_multipolygon_3d_srid_and_big_endian(self):
        ring = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
        out: list = []
        self.assertEqual(B.wkb_polygons(wkb_polygon([ring]), np, out), 1)
        self.assertEqual(B.wkb_polygons(wkb_multi([[ring], [ring]]), np, out), 2)
        self.assertEqual(B.wkb_polygons(wkb_polygon([ring], endian=">"), np, out), 1)
        self.assertEqual(B.wkb_polygons(wkb_polygon([ring], code=1003), np, out), 1)     # PolygonZ: the third value is dropped
        self.assertEqual(B.wkb_polygons(wkb_polygon([ring], srid=4326), np, out), 1)     # EWKB with an SRID
        self.assertEqual(len(out), 6)
        for ring_arr in out:
            self.assertEqual(ring_arr.shape[1], 2)
        with self.assertRaises(B.SourceUnavailable):
            B.wkb_polygons(struct.pack("<BI", 1, 1) + struct.pack("<dd", 0, 0), np, [])   # a point

    def test_a_ring_that_does_not_close_is_closed_and_counted(self):
        open_ring = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)
        geo = B.geo_from_rings([open_ring], [1], [1], np)
        self.assertEqual(geo.stats["rings_not_closed_in_source"], 1)
        self.assertEqual(len(geo.fx), 5)
        self.assertEqual((geo.fx[0], geo.fy[0]), (geo.fx[-1], geo.fy[-1]))


class ExtractAndDownloadTest(Scratch):
    def test_extract_writes_the_folder_and_refuses_a_name_that_climbs_out(self):
        zpath = self.dir / "bad.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("MT_Structures.gdb/a00000009.gdbtable", b"abc")
            zf.writestr("MT_Structures.gdb/../escape.txt", b"x")
        folder = self.dir / "cache"
        with self.assertRaises(B.SourceUnavailable):
            B.extract_gdb(zpath, folder)
        self.assertFalse((self.dir / "escape.txt").exists())
        good = self.dir / "good.zip"
        with zipfile.ZipFile(good, "w") as zf:
            zf.writestr("MT_Structures.gdb/a00000009.gdbtable", b"abc")
            zf.writestr("MT_Structures.gdb/gdb", b"12345678")
        root = B.extract_gdb(good, folder)
        self.assertEqual((root / "a00000009.gdbtable").read_bytes(), b"abc")
        self.assertTrue(str(root).startswith(str(folder)))

    def test_metadata_constraints_are_read_from_the_zip(self):
        zpath = self.dir / "meta.zip"
        xml = ("<metadata><idinfo><accconst>None</accconst><useconst>None</useconst></idinfo>"
               "<pubdate>20260913</pubdate></metadata>")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr(B.META_MEMBER, xml)
        facts = B.metadata_facts(zpath)
        self.assertEqual(facts, {"access_constraints": "None", "use_constraints": "None",
                                 "metadata_pubdate": "20260913"})

    def test_check_zip_refuses_another_size(self):
        path = self.dir / "small.zip"
        path.write_bytes(b"PK")
        with self.assertRaises(B.SourceUnavailable):
            B.check_zip(path)
        with self.assertRaises(B.SourceUnavailable):
            B.check_zip(self.dir / "missing.zip")

    def test_download_cache_hit_makes_no_get(self):
        body = b"PK" + b"x" * 10
        name = "file.zip"
        cache = self.dir / "cache"
        cache.mkdir()
        (cache / name).write_bytes(body)
        (cache / (name + ".meta.json")).write_text(json.dumps(
            {"name": name, "bytes": len(body), "size": len(body), "last_modified": "Tue"}))
        session = FakeSession(head=FakeResponse(200, {"Content-Length": str(len(body)), "Last-Modified": "Tue"}))
        path, info = B.fetch_cached(cache, name, "https://x/file.zip", session=session)
        self.assertEqual(session.gets, 0)
        self.assertFalse(info["fetched"])
        self.assertEqual(path, cache / name)

    def test_download_refetches_when_last_modified_changed_and_checks_the_size(self):
        body = b"PK" + b"y" * 20
        name = "file.zip"
        cache = self.dir / "cache"
        cache.mkdir()
        (cache / name).write_bytes(body)
        (cache / (name + ".meta.json")).write_text(json.dumps(
            {"name": name, "bytes": len(body), "size": len(body), "last_modified": "old"}))
        session = FakeSession(head=FakeResponse(200, {"Content-Length": str(len(body)), "Last-Modified": "new"}),
                              get=FakeResponse(200, {}, body))
        path, info = B.fetch_cached(cache, name, "https://x/file.zip", session=session)
        self.assertEqual(session.gets, 1)
        self.assertTrue(info["fetched"])
        meta = json.loads((cache / (name + ".meta.json")).read_text())
        self.assertEqual(meta["last_modified"], "new")
        short = FakeSession(head=FakeResponse(200, {"Content-Length": "999", "Last-Modified": "new2"}),
                            get=FakeResponse(200, {}, body))
        with self.assertRaises(B.SourceUnavailable):
            B.fetch_cached(cache, name, "https://x/file.zip", session=short)

    def test_download_failures_are_unavailable_with_a_reason(self):
        cache = self.dir / "cache"
        cases = [
            FakeSession(head_error=OSError("refused")),
            FakeSession(head=FakeResponse(503, {})),
            FakeSession(head=FakeResponse(200, {"Content-Length": "5"}), get=FakeResponse(200, {}, b"not a zip")),
        ]
        for session in cases:
            with self.assertRaises(B.SourceUnavailable) as caught:
                B.fetch_cached(cache, "f.zip", "https://x/f.zip", session=session)
            self.assertTrue(str(caught.exception).startswith(B.UNAVAILABLE))


class GeometryTest(unittest.TestCase):
    def derive_of(self, rings, counts, polys=None):
        geo = B.geo_from_rings(rings, counts, polys or [1] * len(counts), np)
        return geo, B.derive(geo, np)

    def inside(self, rings, x, y):
        parity = False
        for ring in rings:
            for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:]):
                if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    parity = not parity
        return parity

    def test_a_square_takes_its_centroid(self):
        geo, der = self.derive_of([rect(-108.5, 45.78, 0.001, 0.0005)], [1])
        self.assertEqual(int(der.how[0]), 0)
        self.assertEqual(int(der.dot_lon5[0]), round((-108.5 + 0.0005) * SCALE))
        self.assertEqual(int(der.dot_lat5[0]), round((45.78 + 0.00025) * SCALE))

    def test_an_l_shape_takes_a_chord_midpoint_inside_it(self):
        L = np.array([[0, 0], [4, 0], [4, 1], [1, 1], [1, 4], [0, 4], [0, 0]], dtype=float)
        geo, der = self.derive_of([L], [1])
        self.assertEqual(int(der.how[0]), 1)
        dot = (der.dot_lon5[0] / SCALE, der.dot_lat5[0] / SCALE)
        self.assertTrue(self.inside([L], *dot))

    def test_orientation_does_not_change_the_centroid_and_a_hole_is_kept(self):
        outer = rect(0, 0, 10, 10)
        cw = outer[::-1].copy()
        _g1, d1 = self.derive_of([outer], [1])
        _g2, d2 = self.derive_of([cw], [1])
        self.assertEqual(int(d1.dot_lon5[0]), int(d2.dot_lon5[0]))
        hole = rect(4, 4, 2, 2)[::-1].copy()          # the hole runs the other way to the outer ring (ESRI)
        geo, der = self.derive_of([outer, hole], [2])
        dot = (der.dot_lon5[0] / SCALE, der.dot_lat5[0] / SCALE)
        self.assertTrue(self.inside([outer, hole], *dot))
        self.assertFalse(self.inside([hole], *dot))
        self.assertEqual(int(der.how[0]), 1)           # the centroid is in the hole: a chord midpoint is the dot

    def test_a_two_part_outline_keeps_its_dot_inside_a_part(self):
        a = rect(0, 0, 1, 1)
        b = rect(2, 2, 1, 1)
        geo, der = self.derive_of([a, b], [1, 1], polys=[2])
        dot = (der.dot_lon5[0] / SCALE, der.dot_lat5[0] / SCALE)
        self.assertTrue(self.inside([a], *dot) or self.inside([b], *dot))


class PointsInOutlineTest(unittest.TestCase):
    def test_even_odd_over_the_rings_of_one_outline(self):
        outer = rect(0, 0, 10, 10)
        hole = rect(4, 4, 2, 2)[::-1].copy()
        geo = B.geo_from_rings([outer, hole], [2], [1], np)
        xs = np.array([1.0, 5.0, 9.5, 11.0])
        ys = np.array([1.0, 5.0, 9.5, 5.0])
        self.assertEqual(B._points_in_outline(0, geo, xs, ys, np).tolist(), [True, False, True, False])


class JoinTest(unittest.TestCase):
    def setUp(self):
        self.x0, self.y0 = -108.5000, 45.7800
        self.s1 = rect(self.x0, self.y0, 0.000167, 0.000129)     # about 10 m by 10 m
        self.geo = B.geo_from_rings([self.s1, rect(-108.45, 45.78, 0.0001, 0.0001)], [1, 1], [1, 1], np)
        self.der = B.derive(self.geo, np)

    def run_join(self, points):
        lon5 = np.array([round(lon * SCALE) for lon, _lat, _cls in points], dtype=np.int64)
        lat5 = np.array([round(lat * SCALE) for _lon, lat, _cls in points], dtype=np.int64)
        cls = np.array([B.CLASS_LETTERS.index(c) for _lon, _lat, c in points], dtype=np.int64)
        return B.join(self.der, lon5, lat5, cls, np, self.geo)

    def test_structure_inside_or_within_fifteen_metres_joins_and_others_do_not(self):
        x0, y0 = self.x0, self.y0
        points = [
            (x0 + 0.00008, y0 + 0.00006, "S"),                 # inside, Structure: joins 0
            (x0 + 0.000167 + 0.00004, y0 + 0.00006, "S"),      # about 4 m east of the outline: joins 0 (near)
            (x0 + 0.00008, y0 + 0.00006 + 0.0004, "S"),        # about 44 m north: unmatched
            (x0 + 0.00008, y0 + 0.00006 - 0.00002, "G"),       # inside, Geocoding: unmatched (D32)
        ]
        match, in_any, near_any = self.run_join(points)
        self.assertEqual(match.tolist(), [0, 0, -1, -1])
        self.assertEqual(int(in_any[3]), 0)                    # it is inside, the count still says so
        self.assertEqual(int(near_any[2]), 2)                  # nothing within 15 m: the count is the outline count

    def test_the_fifteen_metre_edge(self):
        x0 = self.x0
        top = self.y0 + 0.000129
        near, _a, _b = self.run_join([(x0 + 0.00008, top + 0.00013, "S")])     # about 14 m north of the top edge
        far, _c, _d = self.run_join([(x0 + 0.00008, top + 0.00016, "S")])      # about 18 m
        self.assertEqual(int(near[0]), 0)
        self.assertEqual(int(far[0]), -1)

    def test_inside_wins_over_near_and_the_nearest_edge_is_chosen(self):
        # outline b lies about 13 m east of outline a's east edge; a point inside a is within 15 m of b too
        a = rect(-108.5, 45.78, 0.0001, 0.0001)
        b = rect(-108.49975, 45.78, 0.0001, 0.0001)
        geo = B.geo_from_rings([a, b], [1, 1], [1, 1], np)
        der = B.derive(geo, np)
        lat5 = np.array([round(45.78005 * SCALE)], dtype=np.int64)
        inside_a = np.array([round(-108.49992 * SCALE)], dtype=np.int64)
        match, _i, _n = B.join(der, inside_a, lat5, np.array([0]), np, geo)
        self.assertEqual(int(match[0]), 0)
        # between the two, nearer to b's west edge: the nearest outline is b
        nearer_b = np.array([round(-108.49965 * SCALE)], dtype=np.int64)
        match2, _i2, _n2 = B.join(der, nearer_b, lat5, np.array([0]), np, geo)
        self.assertEqual(int(match2[0]), 1)


def tiles_of(rows):
    tr, tc = B._tile_arrays(np.array([r[1] for r in rows], dtype=np.int64),
                            np.array([r[0] for r in rows], dtype=np.int64), np)
    return sorted({H.tile_name(int(a), int(b)) for a, b in zip(tr.tolist(), tc.tolist())})


def sample_store(root: Path, rows):
    """A small store: a B1 index with the tiles of the rows, the address shards and the letter files, the manifest."""
    hail_dir = root / "hail"
    hail_dir.mkdir(parents=True)
    tiles = tiles_of(rows)
    index = {"format": H.FORMAT, "d0": "2020-01-01", "grid": H.GRID, "as_of": "2026-10-15",
             "window": ["2021-10-16", "2026-10-15"], "missing_days": [], "floor_tenths": 64, "tiles": tiles}
    stage = hail_dir / "a"
    stage.mkdir()
    write_addresses_store(stage, rows)
    index["addresses"] = {"format": A.FORMAT, "state": "loaded", "sample": False, "rows": len(rows),
                          "placement": {"classes": {"S": len(rows)}, "by_county": {}}}
    index["addresses"].update(A.disk_figures(root))         # D49: the figures the address build writes, from its files
    (hail_dir / "index.json").write_text(json.dumps(index))
    write_manifest(root)
    return tiles


def write_addresses_store(a_dir: Path, rows):
    objs = []
    for lon5, lat5, line, city, zip_code, cls in sorted(rows):
        parts = line.split(" ", 1)
        number = parts[0]
        street = parts[1] if len(parts) > 1 else ""
        objs.append(Row(lon5, lat5, line, city, zip_code, number, street, "", A.add_value(number),
                        street[:1].upper() or "X", cls, "Yellowstone County"))
    A._write_stage(a_dir, objs)
    return objs


def write_manifest(root: Path):
    files = {}
    for path in sorted((root / "hail").rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            data = path.read_bytes()
            files[path.relative_to(root).as_posix()] = {"bytes": len(data), "sha256": B._sha256(data)}
    index = json.loads((root / "hail" / "index.json").read_text())
    manifest = {"format": H.MANIFEST_FORMAT, "files": files, "counts": {}}
    (root / "hail" / "manifest.json").write_text(json.dumps(manifest))
    return manifest


class ShardTest(Scratch):
    def test_common_pair_and_second_field_and_the_plan(self):
        x0, y0 = -108.5, 45.78
        geo = B.geo_from_rings([rect(x0, y0, 0.0002, 0.0002), rect(x0 + 0.001, y0, 0.0002, 0.0002)], [1, 1], [1, 1], np)
        der = B.derive(geo, np)
        rows = [(round((x0 + 0.00005) * SCALE), round((y0 + 0.00005) * SCALE), "401 North 27th Street", "Billings",
                 "59101", "S"),
                (round((x0 + 0.00005) * SCALE), round((y0 + 0.00015) * SCALE), "403 North 27th Street", "Billings",
                 "59101", "S"),
                (round((x0 + 0.00105) * SCALE), round((y0 + 0.00005) * SCALE), "9 Arm Road", "Roundup", "59072", "S")]
        rows.sort()
        tile = H.tile_name(*[int(v[0]) for v in B._tile_arrays(der.dot_lat5[:1], der.dot_lon5[:1], np)])
        cls = np.array([B.CLASS_LETTERS.index(r[5]) for r in rows], dtype=np.int64)
        lon5 = np.array([r[0] for r in rows], dtype=np.int64)
        lat5 = np.array([r[1] for r in rows], dtype=np.int64)
        match, in_any, near_any = B.join(der, lon5, lat5, cls, np, geo)
        files, stats = B.plan(geo, der, rows, {tile}, np, boxes={})
        docs = {k: json.loads(v) for k, v in files.items() if k.startswith("b/")}
        self.assertEqual(len(docs), 1)
        doc = next(iter(docs.values()))
        self.assertEqual(doc["c"], ["Billings", "59101"])
        self.assertEqual(doc["n"], 2)
        self.assertEqual(doc["m"], 3)
        by_line = {e["p"][0]: e for e in doc["a"]}
        arm = [e for e in doc["a"] if "9 Arm Road" in e["l"]][0]
        self.assertEqual(arm["z"], [["Roundup", "59072"]])
        self.assertNotIn("z", [e for e in doc["a"] if "401 North 27th Street" in e["l"]][0])
        self.assertEqual(len(by_line), 2)
        self.assertEqual(json.loads(files["counts.json"])["total"], 2)
        self.assertEqual(json.loads(files["counts.json"])["tiles"], {tile: 2})
        for entry in doc["a"]:
            for ring in entry["g"]:
                self.assertEqual(ring[0], ring[-1])
                self.assertGreaterEqual(len(ring), 4)
        self.assertNotIn("u", doc)

    def test_a_shard_over_the_limit_splits_by_quadtree_and_keeps_every_outline_once(self):
        x0, y0 = -108.49, 45.71                 # spread over the tile, so the quadrants separate them
        rings = []
        counts = []
        for i in range(30):
            rings.append(rect(x0 + (i % 6) * 0.0145, y0 + (i // 6) * 0.0145, 0.0001, 0.0001))
            counts.append(1)
        geo = B.geo_from_rings(rings, counts, [1] * 30, np)
        der = B.derive(geo, np)
        tiles = {H.tile_name(*v) for v in zip(*[t.tolist() for t in B._tile_arrays(der.dot_lat5, der.dot_lon5, np)])}
        old = B.SHARD_BYTES
        B.SHARD_BYTES = 1200
        try:
            files, stats = B.plan(geo, der, [], tiles, np, boxes={}, addresses_ok=False)
        finally:
            B.SHARD_BYTES = old
        names = sorted(k for k in files if k.startswith("b/"))
        self.assertGreater(len(names), 1)
        seen = []
        for name in names:
            data = files[name]
            leaf = name[2:-5]
            if len(leaf) - len(next(iter(tiles))) < B.DEPTH_CAP:
                self.assertLessEqual(len(data), 1200 if len(json.loads(data)["a"]) > 1 else len(data))
            self.assertTrue(leaf.startswith(next(iter(tiles))))
            seen.extend(e["p"] for e in json.loads(data)["a"])
        self.assertEqual(len(seen), 30)
        self.assertEqual(len({tuple(p) for p in seen}), 30)


class RestoreTest(unittest.TestCase):
    def test_unmatched_only_and_the_full_set_is_the_addresses_module_bytes(self):
        scratch = Path(tempfile.mkdtemp(prefix="buildings-restore-"))
        try:
            lon0, lat0 = -108.5, 45.78
            rows = []
            for i in range(60):
                rows.append((round((lon0 + (i % 10) * 0.00015) * SCALE), round((lat0 + (i // 10) * 0.00015) * SCALE),
                             f"{100 + i} North 27th Street", "Billings", "59101" if i % 3 else "59102",
                             "S" if i % 4 else "G"))
            rows.sort()
            match = np.full(len(rows), -1, dtype=np.int64)
            match[::2] = 7                       # half the rows are matched to outline 7
            full = B._a_files(rows, None, True, np)
            kept = B._a_files(rows, match, False, np)
            stage = scratch / "stage"
            stage.mkdir()
            write_addresses_store(stage, rows)
            for path in stage.glob("*.json"):
                self.assertEqual(full["a/" + path.name], path.read_bytes(), path.name)
            kept_rows = sum(json.loads(v)["n"] for v in kept.values())
            self.assertEqual(kept_rows, int((match < 0).sum()))
            unmatched_lines = set()
            for v in kept.values():
                for row in json.loads(v)["a"]:
                    unmatched_lines.add((row[2], row[3], row[4]))
            self.assertEqual(len(unmatched_lines), kept_rows)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


class StoreTest(Scratch):
    def make_store(self):
        lon0, lat0 = -108.5, 45.78
        rows = [(round((lon0 + 0.00005) * SCALE), round((lat0 + 0.00005) * SCALE), "401 North 27th Street", "Billings",
                 "59101", "S"),
                (round((lon0 + 0.00015) * SCALE), round((lat0 + 0.00005) * SCALE), "403 North 27th Street", "Billings",
                 "59101", "S"),
                (round((lon0 + 0.00120) * SCALE), round((lat0 + 0.00120) * SCALE), "9 Arm Road", "Roundup", "59072",
                 "G")]
        rows.sort()
        root = self.dir / "store"
        tiles = sample_store(root, rows)
        geo = B.geo_from_rings([rect(lon0, lat0, 0.0002, 0.0002), rect(lon0 + 0.0011, lat0 + 0.0011, 0.0002, 0.0002)],
                               [1, 1], [1, 1], np)
        return root, rows, tiles, geo

    def test_build_writes_checks_and_wires_a_store_that_verifies(self):
        root, rows, tiles, geo = self.make_store()
        der = B.derive(geo, np)
        loaded = B.load_rows(root, np, len(rows))
        files, stats = B.plan(geo, der, loaded, set(tiles), np, boxes={})
        B._write_files(root, files)
        block = {"format": B.FORMAT, "state": "loaded", "sample": False, "addresses": "loaded",
                 "source": {"file_date": "2026-09-13"}, "counts": stats["counts"], "boxes": {},
                 "geometry": stats["geometry"], "counties": {"state": "unavailable"},
                 "shards": stats["shards"]["count"], "bytes": stats["shards"]["bytes"],
                 "largest_shard": stats["shards"]["largest"], "depths": stats["shards"]["depths"],
                 "split": stats["split_names"], "split_boxes": stats["split_boxes"], "tiles": stats["tiles"],
                 "outside_grid": stats["counts"]["outside_grid"], "a": stats["a"],
                 "overhang_deg": stats["overhang_deg"], "limits": {}, "rule": "", "seconds": {}}
        B._wire(root, block)
        result = B.verify(root)
        failed = [c for c in result["checks"] if not c["ok"]]
        self.assertTrue(result["ok"], failed)
        index = json.loads((root / "hail" / "index.json").read_text())
        self.assertEqual(index["buildings"]["counts"]["footprints"], 2)
        self.assertEqual(index["buildings"]["counts"]["matched_rows"], 2)
        self.assertEqual(index["buildings"]["counts"]["unmatched_rows"], 1)
        # a changed shard fails the manifest check
        target = next((root / "hail" / "b").glob("*.json"))
        target.write_bytes(target.read_bytes().replace(b'"n":2', b'"n":3', 1))
        self.assertFalse(B.verify(root)["ok"])

    def test_unavailable_removes_the_outlines_and_writes_back_the_full_address_shards(self):
        root, rows, tiles, geo = self.make_store()
        der = B.derive(geo, np)
        loaded = B.load_rows(root, np, len(rows))
        before = {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / "hail" / "a").glob("*.json")}
        files, stats = B.plan(geo, der, loaded, set(tiles), np, boxes={})
        B._write_files(root, files)
        self.assertNotEqual({p.name: p.read_bytes() for p in (root / "hail" / "a").glob("*.json")},
                            {Path(k).name: v for k, v in before.items()})
        result = B.mark_unavailable(root, "the test said so")
        self.assertEqual(result["state"], "unavailable")
        self.assertFalse((root / "hail" / "b").exists())
        self.assertFalse((root / "hail" / "counts.json").exists())
        after = {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / "hail" / "a").glob("*.json")}
        self.assertEqual(after, before)
        index = json.loads((root / "hail" / "index.json").read_text())
        self.assertEqual(index["buildings"]["state"], "unavailable")
        self.assertTrue(index["buildings"]["reason"].startswith(B.UNAVAILABLE))
        self.assertEqual(A.figure_differences(index["addresses"], A.disk_figures(root)), [])     # D49
        self.assertTrue(B.verify(root)["ok"])

    def test_build_from_a_patched_reader_runs_end_to_end_and_a_source_failure_keeps_the_store(self):
        root, rows, tiles, geo = self.make_store()
        zip_path = self.dir / "fake.zip"
        zip_path.write_bytes(b"PK" + b"0" * 16)
        gdb = self.dir / B.GDB_NAME
        gdb.mkdir()
        with mock.patch.object(B, "check_zip", return_value=zip_path), \
                mock.patch.object(B, "metadata_facts", return_value={"access_constraints": "None"}), \
                mock.patch.object(B, "extract_gdb", return_value=gdb), \
                mock.patch.object(B, "read_outlines", return_value=geo):
            block = B.build(str(zip_path), root, cache=self.dir)
        self.assertEqual(block["state"], "loaded")
        self.assertEqual(block["counts"]["footprints"], 2)
        self.assertTrue(B.verify(root)["ok"])
        with mock.patch.object(B, "check_zip", return_value=zip_path), \
                mock.patch.object(B, "metadata_facts", return_value={}), \
                mock.patch.object(B, "extract_gdb", return_value=gdb), \
                mock.patch.object(B, "read_outlines", side_effect=B.SourceUnavailable(B.UNAVAILABLE + ": changed")):
            with self.assertRaises(B.SourceUnavailable):
                B.build(str(zip_path), root, cache=self.dir)
        index = json.loads((root / "hail" / "index.json").read_text())
        self.assertEqual(index["buildings"]["state"], "unavailable")
        self.assertTrue(index["buildings"]["source_unavailable"])
        self.assertTrue(B.verify(root)["ok"])

    def test_verify_recounts_the_dots_and_the_exceptions_from_the_outline_file(self):
        root, rows, tiles, _geo = self.make_store()
        polys = [lattice_ring([(0, 0), (0, 3), (2, 4)]),              # its centroid rounds onto an edge: moved inside
                 lattice_ring([(0, 0), (10, 0), (10, 1), (0, 1)]),    # one unit tall: an exception
                 lattice_ring([(40, 40), (60, 40), (60, 60), (40, 60)])]
        geo = B.geo_from_rings(polys, [1, 1, 1], [1, 1, 1], np)
        der = B.derive(geo, np)
        loaded = B.load_rows(root, np, len(rows))
        files, stats = B.plan(geo, der, loaded, set(tiles), np, boxes={})
        counts = stats["counts"]
        self.assertEqual((counts["dots_outside_outline"], counts["dot_exceptions"], counts["dots_moved"]), (0, 1, 1))
        B._write_files(root, files)
        block = {"format": B.FORMAT, "state": "loaded", "sample": False, "addresses": "loaded",
                 "source": {"file_date": "2026-09-13"}, "counts": counts, "boxes": {},
                 "geometry": stats["geometry"], "counties": {"state": "unavailable"},
                 "shards": stats["shards"]["count"], "bytes": stats["shards"]["bytes"],
                 "largest_shard": stats["shards"]["largest"], "depths": stats["shards"]["depths"],
                 "split": stats["split_names"], "split_boxes": stats["split_boxes"], "tiles": stats["tiles"],
                 "outside_grid": counts["outside_grid"], "a": stats["a"],
                 "overhang_deg": stats["overhang_deg"], "limits": {}, "rule": "", "seconds": {}}
        B._wire(root, block)
        self.assertEqual(exact_recount(root), (0, 1))         # no stored dot that a rule could move is left outside
        zip_path = self.dir / "fake.zip"
        zip_path.write_bytes(b"PK" + b"0" * 16)
        gdb = self.dir / B.GDB_NAME
        gdb.mkdir()
        with mock.patch.object(B, "check_zip", return_value=zip_path), \
                mock.patch.object(B, "metadata_facts", return_value={}), \
                mock.patch.object(B, "extract_gdb", return_value=gdb), \
                mock.patch.object(B, "read_outlines", return_value=geo):
            result = B.verify(root, gdb_zip=str(zip_path))
        failed = [c for c in result["checks"] if not c["ok"]]
        self.assertTrue(result["ok"], failed)
        names = [c["name"] for c in result["checks"]]
        self.assertIn("recomputed dot_exceptions equals the index", names)
        self.assertIn("recomputed dots_outside_outline equals the index", names)

    def test_a_store_whose_index_lacks_a_count_fails_that_check_without_a_key_error(self):     # D48 (R-08)
        root, rows, tiles, _geo = self.make_store()
        polys = [lattice_ring([(0, 0), (0, 3), (2, 4)]),
                 lattice_ring([(0, 0), (10, 0), (10, 1), (0, 1)]),
                 lattice_ring([(40, 40), (60, 40), (60, 60), (40, 60)])]
        geo = B.geo_from_rings(polys, [1, 1, 1], [1, 1, 1], np)
        der = B.derive(geo, np)
        loaded = B.load_rows(root, np, len(rows))
        files, stats = B.plan(geo, der, loaded, set(tiles), np, boxes={})
        counts = {key: value for key, value in stats["counts"].items() if key != "dot_exceptions"}   # an older index
        B._write_files(root, files)
        block = {"format": B.FORMAT, "state": "loaded", "sample": False, "addresses": "loaded",
                 "source": {"file_date": "2026-09-13"}, "counts": counts, "boxes": {},
                 "geometry": stats["geometry"], "counties": {"state": "unavailable"},
                 "shards": stats["shards"]["count"], "bytes": stats["shards"]["bytes"],
                 "largest_shard": stats["shards"]["largest"], "depths": stats["shards"]["depths"],
                 "split": stats["split_names"], "split_boxes": stats["split_boxes"], "tiles": stats["tiles"],
                 "outside_grid": counts["outside_grid"], "a": stats["a"],
                 "overhang_deg": stats["overhang_deg"], "limits": {}, "rule": "", "seconds": {}}
        B._wire(root, block)
        zip_path = self.dir / "fake.zip"
        zip_path.write_bytes(b"PK" + b"0" * 16)
        gdb = self.dir / B.GDB_NAME
        gdb.mkdir()
        with mock.patch.object(B, "check_zip", return_value=zip_path), \
                mock.patch.object(B, "metadata_facts", return_value={}), \
                mock.patch.object(B, "extract_gdb", return_value=gdb), \
                mock.patch.object(B, "read_outlines", return_value=geo):
            result = B.verify(root, gdb_zip=str(zip_path))
        failed = [c for c in result["checks"] if not c["ok"]]
        self.assertEqual([c["name"] for c in failed], ["recomputed dot_exceptions equals the index"])
        self.assertIn("rebuild the store", failed[0]["detail"])
        self.assertFalse(result["ok"])

    def test_the_command_line_marks_unavailable_and_refuses_an_empty_reason(self):
        root, rows, tiles, geo = self.make_store()
        self.assertEqual(B.main(["unavailable", "--store", str(root), "--reason", "test"]), 0)
        index = json.loads((root / "hail" / "index.json").read_text())
        self.assertEqual(index["buildings"]["state"], "unavailable")
        self.assertEqual(B.main(["unavailable", "--store", str(root), "--reason", "   "]), 2)
        parser = B.build_parser()
        args = parser.parse_args(["build", "--store", "s", "--gdb-zip", "z.zip", "--counties-zip", "c.zip"])
        self.assertEqual((args.command, args.store, args.gdb_zip), ("build", "s", "z.zip"))
        self.assertEqual(parser.parse_args(["verify", "s", "--gdb-zip", "z"]).store_dir, "s")

    def test_the_outline_step_rewrites_the_address_figures_from_the_files_on_disk(self):     # D49
        root, rows, tiles, geo = self.make_store()
        index_path = root / "hail" / "index.json"
        before = json.loads(index_path.read_text(encoding="utf-8"))["addresses"]
        zip_path = self.dir / "fake.zip"
        zip_path.write_bytes(b"PK" + b"0" * 16)
        gdb = self.dir / B.GDB_NAME
        gdb.mkdir()
        with mock.patch.object(B, "check_zip", return_value=zip_path), \
                mock.patch.object(B, "metadata_facts", return_value={"access_constraints": "None"}), \
                mock.patch.object(B, "extract_gdb", return_value=gdb), \
                mock.patch.object(B, "read_outlines", return_value=geo):
            block = B.build(str(zip_path), root, cache=self.dir)
        self.assertEqual(block["counts"]["unmatched_rows"], 1)         # only the class G point stays in hail/a
        after = json.loads(index_path.read_text(encoding="utf-8"))["addresses"]
        disk = A.disk_figures(root)
        self.assertEqual({key: after[key] for key in A.FIGURE_KEYS}, disk)
        self.assertEqual(A.figure_differences(after, disk), [])
        self.assertEqual(disk["largest_shard"]["rows"], 1)
        self.assertLess(after["bytes"]["shards"], before["bytes"]["shards"])
        data = index_path.read_bytes()
        manifest = json.loads((root / "hail" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["files"]["hail/index.json"], {"bytes": len(data), "sha256": B._sha256(data)})
        H.check_manifest(root)

    def test_an_address_list_that_is_not_loaded_is_left_without_figures(self):            # D49
        root, rows, tiles, geo = self.make_store()
        index_path = root / "hail" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["addresses"] = {"format": A.FORMAT, "state": "unavailable", "reason": "test", "source_unavailable": True}
        index_path.write_text(json.dumps(index), encoding="utf-8")
        B._wire(root, {"format": B.FORMAT, "state": "unavailable", "reason": "test", "source_unavailable": True})
        after = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(after["addresses"], index["addresses"])
        self.assertEqual(after["buildings"]["state"], "unavailable")

    def test_a_figure_that_cannot_be_read_stops_the_index_write(self):                    # D49
        root, rows, tiles, geo = self.make_store()
        index_path = root / "hail" / "index.json"
        before = index_path.read_bytes()
        (root / "hail" / "a" / "idx" / "cities.json").unlink()
        with self.assertRaises(B.BuildingsError) as caught:
            B._wire(root, {"format": B.FORMAT, "state": "unavailable", "reason": "test", "source_unavailable": False})
        self.assertIn("could not be read back from hail/a", str(caught.exception))
        self.assertEqual(index_path.read_bytes(), before)


class DescribeTest(unittest.TestCase):
    UNDATED = ("Building outlines: USA Structures, Oak Ridge National Laboratory and FEMA (file date not available in "
               "this update).")

    def test_the_index_date_is_quoted_only_when_the_index_read_it(self):
        loaded = {"buildings": {"state": "loaded", "source": {"file_date": "2026-09-13"}}}
        self.assertIn("(file dated 2026-09-13)", B.describe_buildings(loaded)["source"])
        for index in (None, {}, {"buildings": None}, {"buildings": {"state": "unavailable", "reason": "r"}}):
            self.assertEqual(B.describe_buildings(index)["source"], self.UNDATED, index)

    def test_the_outline_caveat_is_said_once_on_the_about_page(self):          # D45 (R-06)
        for index in (None, {"buildings": {"state": "loaded", "source": {"file_date": "2026-09-13"}}}):
            about = B.describe_buildings(index)
            self.assertEqual(sum(str(v).count("not surveys") for v in about.values()), 1, index)
            self.assertIn("not surveys", about["caveat"])
            self.assertNotIn("not surveys", about["source"])

    def test_the_about_text_has_no_county_count_and_no_county_credit(self):
        about = B.describe_buildings(None)
        self.assertNotIn("counties", about)
        self.assertNotIn("county_source", about)
        text = " ".join(str(v) for v in about.values())
        self.assertNotIn("Counts by county", text)
        self.assertNotIn("Counties:", text)
        self.assertNotIn("about_counties", B.WORDS_BUILDINGS)


# ---------------------------------------------------------------- the dot on its own rings (D15): exact and recounted

UNIT = 1e-5                                        # one 5-decimal unit of a degree
OFFS = [(dx, dy) for dx in range(-3, 4) for dy in range(-3, 4)]        # the search square of DOT_SEARCH_UNITS


def lattice_ring(points):
    """A closed ring from points given in 5-decimal units from the Billings origin (-108.5, 45.78)."""
    pts = [(-108.5 + u * UNIT, 45.78 + v * UNIT) for u, v in points]
    return np.array(pts + [pts[0]], dtype=np.float64)


def strict_int(px, py, rings):
    """Whether the integer point is strictly inside the integer rings: on no edge, and an odd number of crossings (the
    even-odd rule). Integer arithmetic only."""
    parity = 0
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:]):
            on = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1) == 0
            if on and min(x1, x2) <= px <= max(x1, x2) and min(y1, y2) <= py <= max(y1, y2):
                return False
            if (y1 > py) != (y2 > py):
                lhs = (px - x1) * (y2 - y1)
                rhs = (py - y1) * (x2 - x1)
                right = (lhs < rhs) if (y2 - y1) > 0 else (lhs > rhs)
                if right:
                    parity ^= 1
    return parity == 1


def exact_recount(root: Path):
    """(stored dots that a rule could have moved but that are not strictly inside, exceptions), recounted from the outline
    shards with integer arithmetic: each stored dot against its own stored rings (D15)."""
    moved_wrong = exceptions = 0
    for path in sorted((root / "hail" / "b").glob("*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8"))["a"]:
            px, py = round(entry["p"][0] * SCALE), round(entry["p"][1] * SCALE)
            rings = [[(round(x * SCALE), round(y * SCALE)) for x, y in ring] for ring in entry["g"]]
            if strict_int(px, py, rings):
                continue
            if any(strict_int(px + dx, py + dy, rings) for dx, dy in OFFS):
                moved_wrong += 1
            else:
                exceptions += 1
    return moved_wrong, exceptions


class ExactDotTest(unittest.TestCase):
    ORIGIN = (round(-108.5 * SCALE), round(45.78 * SCALE))

    def test_a_centroid_that_rounding_puts_on_an_edge_moves_strictly_inside(self):
        # the centroid is (2/3, 7/3) units from the origin: it rounds to (1, 2), on the edge from (0, 0) to (2, 4); the
        # nearest point strictly inside within 3 units is (1, 3), the first candidate in the search that is inside
        geo = B.geo_from_rings([lattice_ring([(0, 0), (0, 3), (2, 4)])], [1], [1], np)
        der = B.derive(geo, np)
        self.assertEqual((int(der.dot_lon5[0]) - self.ORIGIN[0], int(der.dot_lat5[0]) - self.ORIGIN[1]), (1, 3))
        self.assertFalse(bool(der.dot_exception[0]))
        self.assertEqual(der.dots_moved, 1)
        self.assertTrue(bool(B._lattice_strict(der, der.dot_lon5, der.dot_lat5, np)[0]))

    def test_a_footprint_one_unit_tall_is_an_exception_and_keeps_its_rounded_dot(self):
        geo = B.geo_from_rings([lattice_ring([(0, 0), (10, 0), (10, 1), (0, 1)])], [1], [1], np)
        der = B.derive(geo, np)
        self.assertTrue(bool(der.dot_exception[0]))
        self.assertFalse(bool(B._lattice_strict(der, der.dot_lon5, der.dot_lat5, np)[0]))
        self.assertEqual(der.dots_moved, 0)

    def test_a_dot_already_inside_keeps_its_rounded_position(self):
        geo = B.geo_from_rings([lattice_ring([(0, 0), (10, 0), (10, 10), (0, 10)])], [1], [1], np)
        der = B.derive(geo, np)
        self.assertEqual((int(der.dot_lon5[0]) - self.ORIGIN[0], int(der.dot_lat5[0]) - self.ORIGIN[1]), (5, 5))
        self.assertEqual(der.dots_moved, 0)
        self.assertFalse(bool(der.dot_exception[0]))


class BoxFootprintTest(unittest.TestCase):
    """The box figures judge each intersecting outline on every address row, not only the rows inside the box (the
    Billings figures of the box check were 145 and 61 and became 132 and 46)."""

    def test_an_outline_that_reaches_past_the_box_edge_is_judged_on_every_row(self):
        a = rect(0.9, 0.4, 0.2, 0.2)              # 0.9 to 1.1 east: meets the box (0, 0, 1, 1); its one row lies past it
        b = rect(0.1, 0.1, 0.1, 0.1)              # wholly inside the box, with no row
        geo = B.geo_from_rings([a, b], [1, 1], [1, 1], np)
        der = B.derive(geo, np)
        lon5 = np.array([round(1.05 * SCALE)], dtype=np.int64)
        lat5 = np.array([round(0.5 * SCALE)], dtype=np.int64)
        cls = np.array([0], dtype=np.int64)
        match, in_any, near_any = B.join(der, lon5, lat5, cls, np, geo)
        self.assertEqual(match.tolist(), [0])
        stats = B._box_stats((0.0, 0.0, 1.0, 1.0), geo, der, lon5, lat5, cls, in_any, near_any, match, np)
        self.assertEqual(stats["footprints_intersecting"], 2)
        self.assertEqual(stats["footprints_no_point_inside_any"], 1)
        self.assertEqual(stats["footprints_no_structure_match"], 1)

    def test_a_point_on_the_box_edge_is_inside_the_box(self):                    # D46: the box is closed
        a = rect(0.9, 0.4, 0.2, 0.2)              # 0.9 to 1.1 east; the point sits on the box's east edge at 1.0
        geo = B.geo_from_rings([a], [1], [1], np)
        der = B.derive(geo, np)
        lon5 = np.array([round(1.0 * SCALE)], dtype=np.int64)
        lat5 = np.array([round(0.5 * SCALE)], dtype=np.int64)
        cls = np.array([0], dtype=np.int64)
        match, in_any, near_any = B.join(der, lon5, lat5, cls, np, geo)
        stats = B._box_stats((0.0, 0.0, 1.0, 1.0), geo, der, lon5, lat5, cls, in_any, near_any, match, np)
        self.assertEqual((stats["points"], stats["points_inside_any"]), (1, 1))


class BillingsGateTest(unittest.TestCase):
    """D46 and B3-10: the figures of record, their arithmetic and the date rule of the check."""

    BOX = {"points": 864, "points_inside_any": 539, "points_within_15m_any": 305, "points_farther_any": 20}

    def test_the_stated_figures_add_up_and_name_their_box_and_address_date(self):
        self.assertEqual(B.BILLINGS_GATE, {"points": 864, "inside": 539, "within_15m": 305, "farther": 20})
        gate = B.BILLINGS_GATE
        self.assertEqual(gate["inside"] + gate["within_15m"] + gate["farther"], gate["points"])
        self.assertEqual(B.BOXES["billings"], (-108.51, 45.78, -108.50, 45.79))
        self.assertEqual(B.BILLINGS_GATE_ADDRESS_DATE, "2026-09-30")

    def test_the_check_passes_on_the_figures_of_record_and_fails_on_any_other(self):
        gate = B.billings_gate(self.BOX, "2026-09-30")
        self.assertTrue(gate["made"])
        self.assertTrue(gate["ok"])
        self.assertIn("864 points, 539 inside, 305 within 15 m and 20 farther", gate["name"])
        self.assertIn("closed box, merged rows", gate["name"])
        self.assertFalse(B.billings_gate(dict(self.BOX, points_inside_any=535), "2026-09-30")["ok"])

    def test_another_address_list_is_recorded_as_not_made_and_never_failed(self):
        gate = B.billings_gate(self.BOX, "2026-10-31")
        self.assertEqual(gate, {"made": False,
                                "note": "not made: the address list is dated 2026-10-31; the stated figures are for "
                                        "2026-09-30"})
        self.assertFalse(B.billings_gate(self.BOX, None)["made"])


class ZoomAgreementTest(unittest.TestCase):
    def test_the_address_zoom_rules_agree_with_the_outline_zoom_rules(self):      # D27, D47
        self.assertEqual(A.ZOOM["dots"], B.ZOOM["dots"])
        self.assertEqual(A.ZOOM["choose"], B.ZOOM["emphasis"])
        self.assertEqual(B.DOT_RADIUS_PX, A.DOT_RADIUS_PX)


class CountyReaderTest(unittest.TestCase):
    def test_the_county_reader_asks_for_the_code_and_the_name_and_keeps_montana(self):
        calls = {}

        class Raw:
            @staticmethod
            def read(path, **kwargs):
                calls.update(kwargs)
                geoms = np.array([wkb_polygon([rect(-108.5, 45.7, 0.1, 0.1)]),
                                  wkb_polygon([rect(-104.0, 42.0, 0.1, 0.1)]),
                                  wkb_polygon([rect(-112.0, 46.0, 0.1, 0.1)])], dtype=object)
                fields = (np.array(["30111", "56001", "30001"], dtype=object),
                          np.array(["Yellowstone County", "Niobrara County", "Beaverhead County"], dtype=object))
                return ({}, None, geoms, fields)

        fake = mock.Mock()
        fake.read_info.return_value = {"geometry_type": "MultiPolygon", "crs": "EPSG:4326"}
        fake.raw = Raw
        with mock.patch.object(B, "_pyogrio", return_value=fake):
            counties = B.read_counties(Path("/nowhere/cb_2025_us_county_500k.zip"), np)
        self.assertEqual(calls["columns"], ["GEOID", "NAMELSAD"])
        self.assertIs(calls["read_geometry"], True)
        self.assertEqual([(g, n) for g, n, _rings in counties],
                         [("30111", "Yellowstone County"), ("30001", "Beaverhead County")])
        self.assertEqual([len(rings) for _g, _n, rings in counties], [1, 1])


class ScriptedSession:
    """A session whose GETs answer in order: an exception is raised, anything else is returned."""

    def __init__(self, head, gets):
        self._head = head
        self._gets = list(gets)
        self.gets_made = 0

    def head(self, url, **kwargs):
        return self._head

    def get(self, url, **kwargs):
        self.gets_made += 1
        item = self._gets.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RetryTest(Scratch):
    """The outline download is tried up to three times for a dropped connection, a timeout or an HTTP 5xx; any other
    answer fails at once (D20). The sleeps are patched, so the suite stays fast."""

    def fetch(self, session):
        return B.fetch_cached(self.dir / "cache", "f.zip", "https://x/f.zip", session=session)

    def test_a_dropped_connection_is_tried_again_and_then_fetches(self):
        body = b"PK" + b"z" * 30
        head = FakeResponse(200, {"Content-Length": str(len(body)), "Last-Modified": "m"})
        session = ScriptedSession(head, [requests.ConnectionError("dropped"), FakeResponse(200, {}, body)])
        with mock.patch("website.buildings.time.sleep") as sleep:
            path, info = self.fetch(session)
        self.assertEqual(session.gets_made, 2)
        self.assertTrue(info["fetched"])
        self.assertEqual(path.read_bytes(), body)
        sleep.assert_called_once_with(2.0)

    def test_an_http_5xx_is_tried_again(self):
        body = b"PK" + b"y" * 30
        head = FakeResponse(200, {"Content-Length": str(len(body))})
        session = ScriptedSession(head, [FakeResponse(503, {}), FakeResponse(200, {}, body)])
        with mock.patch("website.buildings.time.sleep"):
            _path, info = self.fetch(session)
        self.assertEqual(session.gets_made, 2)
        self.assertTrue(info["fetched"])

    def test_three_failures_give_up_as_unavailable_and_leave_no_part_file(self):
        head = FakeResponse(200, {"Content-Length": "32"})
        session = ScriptedSession(head, [requests.Timeout("slow"), requests.ConnectionError("dropped"),
                                         requests.Timeout("slow again")])
        with mock.patch("website.buildings.time.sleep") as sleep:
            with self.assertRaises(B.SourceUnavailable) as caught:
                self.fetch(session)
        self.assertEqual(session.gets_made, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2.0, 4.0])
        self.assertTrue(str(caught.exception).startswith(B.UNAVAILABLE))
        self.assertFalse((self.dir / "cache" / ".bld-part-f.zip").exists())

    def test_a_not_found_answer_fails_at_once(self):
        head = FakeResponse(200, {"Content-Length": "32"})
        session = ScriptedSession(head, [FakeResponse(404, {}), FakeResponse(200, {}, b"PK" + b"x" * 30)])
        with mock.patch("website.buildings.time.sleep") as sleep:
            with self.assertRaises(B.SourceUnavailable):
                self.fetch(session)
        self.assertEqual(session.gets_made, 1)
        sleep.assert_not_called()


class WorkflowTest(unittest.TestCase):
    """The daily job's outline steps: the non-fatal rules (D20, D36, D39), the branch paths and the cache."""

    def setUp(self):
        self.text = (ROOT / ".github" / "workflows" / "hail-store.yml").read_text(encoding="utf-8")

    @unittest.skipUnless(yaml is not None, "PyYAML is not installed")
    def test_every_step_that_marks_a_source_unavailable_cannot_stop_the_job(self):
        # A mark is a step that writes "unavailable". The manifest check (id manifest) holds the containment commands
        # and is the one fatal step of the daily job (a store that does not check is not published), so it is not a mark.
        doc = yaml.safe_load(self.text)
        marks = {job: [s for s in doc["jobs"][job]["steps"]
                       if " unavailable --store store " in str(s.get("run", "")) and s.get("id") != "manifest"]
                 for job in ("store", "monthly")}
        # daily: the roads, the addresses and the outlines (B3) and the terrain, base map, landmarks, history layers and
        # bubble values (B6); monthly: the landmarks, terrain tiles and base map vectors (B6)
        self.assertEqual([len(marks["store"]), len(marks["monthly"])], [8, 3])
        for job in marks:
            for step in marks[job]:
                self.assertIs(step.get("continue-on-error"), True, step.get("name"))
        check = [s for s in doc["jobs"]["store"]["steps"] if s.get("id") == "manifest"]
        self.assertEqual(len(check), 1)
        self.assertIsNot(check[0].get("continue-on-error"), True, "the daily manifest check must stay fatal")

    def test_a_branch_push_that_changes_a_store_module_runs_the_job(self):
        for path in ("website/streets.py", "website/buildings.py", "website/addresses.py"):
            self.assertIn(f'"{path}"', self.text)

    def test_the_outline_cache_keeps_the_zip_and_not_the_geodatabase(self):
        self.assertIn("path: structures-fema/MT_Structures_20260913.zip*", self.text)

    @unittest.skipUnless(yaml is not None, "PyYAML is not installed")
    def test_the_non_fatal_caps_are_the_measured_ones_and_fit_the_job_timeout(self):
        doc = yaml.safe_load(self.text)
        steps = {s["id"]: s for s in doc["jobs"]["store"]["steps"] if "id" in s}
        caps = [steps[k]["timeout-minutes"] for k in ("roads_build", "roads_verify", "addr_build", "addr_verify",
                                                     "bld_build", "bld_verify")]
        self.assertEqual(caps, [15, 5, 5, 5, 10, 5])          # the cold-cache timings of 2026-10-19, about 2 to 4 times
        for key in ("roads_build", "roads_verify", "addr_build", "addr_verify", "bld_build", "bld_verify"):
            self.assertIs(steps[key].get("continue-on-error"), True, key)
        # the eight non-fatal marks of the daily job in step order: B6's terrain, base map, landmarks and history layers,
        # B3's roads, addresses and outlines, then B6's bubble values; the manifest check is fatal and has its own cap
        unavailable = [s["timeout-minutes"] for s in doc["jobs"]["store"]["steps"]
                       if " unavailable --store store " in str(s.get("run", "")) and s.get("id") != "manifest"]
        self.assertEqual(unavailable, [3, 3, 5, 3, 5, 5, 5, 5])
        manifest = [s["timeout-minutes"] for s in doc["jobs"]["store"]["steps"] if s.get("id") == "manifest"]
        self.assertEqual(manifest, [10])
        self.assertEqual(doc["jobs"]["store"]["timeout-minutes"], 150)   # D50, D51: B5's 60 minutes plus B3's 90
        self.assertLess(sum(caps) + sum(unavailable) + sum(manifest), doc["jobs"]["store"]["timeout-minutes"])


if __name__ == "__main__":
    unittest.main()
