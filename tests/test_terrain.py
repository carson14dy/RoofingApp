"""Terrain shading and land cover tiles (B6 product P1, website/terrain.py): the tile maths, the outline and the tile set
(positive-area overlap, pinned counts), the answer checks and the drawing (the grey JPEG at quality 80 with every grey
value kept, the five-class palette with index 0 transparent, the woody and emergent wetlands in the shrub and grass
class), the tries (a 5xx, 429 or network error is tried three times; a client error is final after one request, and
counts as one request; a body that is not a readable image, truncated ones included, is tried again), the cache (a
cached copy is used before any request, a truncated copy is not used, a refresh that fails serves it with its reason, a
deadline stops requests, the other months are deleted after a build), the land cover description (the layer's month, a
renamed layer), the build (both layers, the index blocks, the manifest entries, a missing tile with its reason, a failed
layer, a failed service description, a truncated answer, the second run from the cache, determinism, one layer at a time,
a land-only build that keeps the shading date during a shading outage, a zoom subset with and without
--keep-other-zooms, the default cache folder, the offline rule (a valid copy is used whatever --refresh says, and a
layer whose cache is not complete is not rebuilt, so no tile file is deleted), the shading copyright line, the
unavailable command), the description refresh (--refresh-descriptions reads both descriptions and no valid tile, a changed
month is requested through its cache key, and --refresh still asks every tile), verify (a wrong image, a stray file, a
manifest mismatch, a seeded re-fetch that matches, one that
does not, a palette match whose bytes differ, and a truncated re-fetch), the sample store's strict manifest check, and
the words (a credit names only a source in use; the layer sentences say Data unavailable beside the D20 wording; the
terms name the NLCD 2021 record and carry no CC0 statement), and the shared base index (SharedBaseIndexTests: a new document
starts with the shared key, the other parts' keys survive a write, a document of another format is refused and kept
byte for byte before any file changes).
Offline: the sources are fakes built from the fixtures in tests/fixtures/terrain (about 100 KB), and the sleep between
tries is a no-op. Tests that need Pillow or numpy skip when the package is absent."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from website import terrain as T
from website import hail

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (words_rules: the sentences a scan allows)
import words_rules as W  # noqa: E402

try:
    import numpy as np
    from PIL import Image
    HAVE_IMAGES = True
except ImportError:                       # the optional packages are absent: the image tests skip
    HAVE_IMAGES = False

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "terrain"
SHADING_PNG = (FIXTURES / "shading_z8_x50_y90.png").read_bytes()    # the 3DEP export of tile 8/50/90 (grey, 256 by 256)
LAND_TIFF = (FIXTURES / "land_cover_z8_x50_y90.tif").read_bytes()   # the NLCD WCS answer of the same tile (palette, 256 px)
LAND_DESCRIBE = (FIXTURES / "land_cover_describe.xml").read_bytes()  # the layer's WCS description (live, 2026-10-26)
META = json.dumps({
    "copyrightText": "USGS National Map 3D Elevation Program (3DEP). October 01, 2026.",
    "description": ("The USGS 3D Elevation Program (3DEP) Bare Earth DEM Dynamic service reflects all 3DEP DEM data "
                    "published as of September 28, 2026."),
}).encode("utf-8")
ZOOM5_KEYS = {"5/5/10", "5/5/11", "5/6/10", "5/6/11"}          # the four tiles of zoom 5 (the outline's overlap rule)
NOOP_SLEEP = lambda seconds: None  # noqa: E731


def key_from_3857(bbox_text: str) -> str:
    """The tile key of a request's bbox in EPSG:3857 (the zoom is the one whose tile width the box has)."""
    x0, y0, x1, y1 = (float(v) for v in bbox_text.split(","))
    zoom = round(math.log2(2 * T.HALF_WORLD_M / (x1 - x0)))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    lon = math.degrees(cx / T.EARTH_RADIUS_M)
    lat = math.degrees(math.atan(math.sinh(cy / T.EARTH_RADIUS_M)))
    x, y = T.tile_index(lon, lat, zoom)
    return T.tile_key(zoom, x, y)


class FakeSource:
    """Answers the three sources from the fixtures. fail maps (layer, key) to an HTTP status, and (layer, "*") to all of
    that layer's tiles; bodies maps (layer, key) to a body that is answered with status 200 (a truncated image, say).
    meta_status and land_meta_status are the statuses of the two service descriptions, and land_describe is the land
    cover description. calls records each request as (kind, key) so a test can count the tries of one tile."""

    def __init__(self, *, fail=None, meta_status=200, shading=SHADING_PNG, land=LAND_TIFF, bodies=None,
                 land_describe=LAND_DESCRIBE, land_meta_status=200, meta=META):
        self.fail = dict(fail or {})
        self.bodies = dict(bodies or {})
        self.meta_status = meta_status
        self.meta = meta                         # the shading description's body (its copyright line is the test's)
        self.land_meta_status = land_meta_status
        self.land_describe = land_describe
        self.shading = shading
        self.land = land
        self.calls: list[tuple[str, str]] = []

    def __call__(self, url, params, timeout=None):
        if url == T.SHADING_META_URL:
            self.calls.append(("meta", ""))
            return self.meta_status, (self.meta if self.meta_status == 200 else b""), ""
        if url == T.LAND_URL and params.get("request") == "DescribeCoverage":
            self.calls.append(("landmeta", ""))
            return self.land_meta_status, (self.land_describe if self.land_meta_status == 200 else b""), ""
        if url == T.SHADING_URL:
            key = key_from_3857(params["bbox"])
            self.calls.append(("h", key))
            status = self.fail.get(("h", key), self.fail.get(("h", "*")))
            return (status, b"", "") if status else (200, self.bodies.get(("h", key), self.shading), "")
        if url == T.LAND_URL:
            key = key_from_3857(params["bbox"])
            self.calls.append(("l", key))
            status = self.fail.get(("l", key), self.fail.get(("l", "*")))
            return (status, b"", "") if status else (200, self.bodies.get(("l", key), self.land), "")
        self.calls.append(("other", url))
        return 404, b"", ""

    def count(self, kind: str, key: str) -> int:
        return sum(1 for call in self.calls if call == (kind, key))


def empty_store(root: Path) -> Path:
    """A store directory with a minimal index and manifest (the build adds its own keys and entries)."""
    (root / "hail").mkdir(parents=True, exist_ok=True)
    (root / "hail" / "index.json").write_text(json.dumps({"format": "hail-store-v1", "as_of": "2026-10-17",
                                                          "gauges": {"state": "loaded"}}), encoding="utf-8")
    (root / "hail" / "manifest.json").write_text(json.dumps({"format": "hail-manifest-v1", "files": {},
                                                             "counts": {}}), encoding="utf-8")
    return root


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- tile maths and the outline

class TileMathTests(unittest.TestCase):
    def test_bbox_matches_the_web_mercator_formula(self):
        # tile 8/50/90, computed on 2026-10-25 with the standard formula (the 3DEP export's own bbox for it)
        x0, y0, x1, y1 = T.tile_bbox_3857(8, 50, 90)
        self.assertAlmostEqual(x0, -12210356.646387195, delta=0.01)
        self.assertAlmostEqual(y0, 5792092.255337516, delta=0.01)
        self.assertAlmostEqual(x1, -12053813.612459155, delta=0.01)
        self.assertAlmostEqual(y1, 5948635.289265556, delta=0.01)

    def test_the_world_tile_is_the_whole_world(self):
        west, south, east, north = T.tile_lonlat(0, 0, 0)
        self.assertAlmostEqual(west, -180.0)
        self.assertAlmostEqual(east, 180.0)
        self.assertAlmostEqual(north, 85.0511, places=3)
        self.assertAlmostEqual(south, -85.0511, places=3)

    def test_a_tile_index_gives_back_its_tile(self):
        for z, x, y in ((5, 6, 11), (8, 50, 90), (10, 182, 354), (10, 216, 370)):
            west, south, east, north = T.tile_lonlat(z, x, y)
            self.assertEqual(T.tile_index((west + east) / 2, (south + north) / 2, z), (x, y))

    def test_missoula_is_in_its_tile_at_zoom_10(self):
        lat, lon = 46.8721, -113.9940
        x, y = T.tile_index(lon, lat, 10)
        west, south, east, north = T.tile_lonlat(10, x, y)
        self.assertTrue(west < lon < east and south < lat < north)

    def test_tile_keys_are_zoom_slash_x_slash_y(self):
        self.assertEqual(T.tile_key(8, 50, 90), "8/50/90")


class OutlineTests(unittest.TestCase):
    def test_the_montana_outline_is_one_ring_of_211_points(self):
        rings = T.montana_rings()
        self.assertEqual(len(rings), 1)
        self.assertEqual(len(rings[0]), 211)                      # the closing point is not repeated

    def test_the_tile_set_is_pinned_to_the_outline(self):
        # 881 tiles in all. The research's 805 came from a sample of 25 points per tile, which misses the slivers
        # (the top row of tiles at zooms 5 and 6 holds a few kilometres of Montana); the exact overlap count is 881.
        counts = {z: len(v) for z, v in T.tile_set(T.montana_rings(), T.ZOOMS).items()}
        self.assertEqual(counts, {5: 4, 6: 9, 7: 22, 8: 56, 9: 178, 10: 612})
        self.assertEqual(sum(counts.values()), 881)

    def test_the_tile_set_is_sorted_and_unique(self):
        for z, tiles in T.tile_set(T.montana_rings(), (6, 8)).items():
            self.assertEqual(tiles, sorted(set(tiles)))
            self.assertTrue(all(0 <= x < 2 ** z and 0 <= y < 2 ** z for x, y in tiles))

    def test_a_rectangle_overlaps_only_with_positive_area(self):
        square = [[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]]
        self.assertTrue(T.rect_overlaps(square, 0.5, 0.5, 1.5, 1.5))     # inside the square
        self.assertTrue(T.rect_overlaps(square, -1.0, -1.0, 3.0, 3.0))   # the square inside the rectangle
        self.assertTrue(T.rect_overlaps(square, 1.0, -1.0, 3.0, 1.0))    # an edge crosses the rectangle
        self.assertTrue(T.rect_overlaps(square, 1.9, 1.9, 2.5, 2.5))     # a sliver of area 0.01
        self.assertFalse(T.rect_overlaps(square, 2.0, 0.0, 3.0, 2.0))    # touches along the right edge
        self.assertFalse(T.rect_overlaps(square, 2.0, 2.0, 3.0, 3.0))    # touches at a corner
        self.assertFalse(T.rect_overlaps(square, 5.0, 5.0, 6.0, 6.0))    # apart
        self.assertFalse(T.rect_overlaps(square, -1.0, 0.5, 0.0, 1.5))   # touches along the left edge
        triangle = [[(0.0, 0.0), (4.0, 0.0), (0.0, 4.0)]]
        self.assertTrue(T.rect_overlaps(triangle, 1.0, 1.0, 2.0, 2.0))
        self.assertFalse(T.rect_overlaps(triangle, 3.0, 3.0, 4.0, 4.0))  # beyond the hypotenuse
        self.assertFalse(T.rect_overlaps(triangle, 2.0, 2.0, 3.0, 3.0))  # the hypotenuse touches its corner only

    def test_an_outline_with_a_hole_or_no_feature_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            holed = Path(tmp) / "holed.json"
            holed.write_text(json.dumps({"land": {"features": [{"properties": {"montana": True}, "geometry": {
                "type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]], [[0.2, 0.2], [0.4, 0.2], [0.2, 0.2]]]}}]}}),
                encoding="utf-8")
            with self.assertRaises(T.TerrainError) as raised:
                T.montana_rings(holed)
            self.assertIn("hole", str(raised.exception))
            absent = Path(tmp) / "absent.json"
            absent.write_text(json.dumps({"land": {"features": []}}), encoding="utf-8")
            with self.assertRaises(T.TerrainError):
                T.montana_rings(absent)


# ---------------------------------------------------------------- the answers and the drawing

@unittest.skipUnless(HAVE_IMAGES, "needs Pillow and numpy")
class ImageTests(unittest.TestCase):
    def test_the_shading_fixture_is_a_256_pixel_grey_png(self):
        T.check_shading_png(SHADING_PNG)
        im = Image.open(io.BytesIO(SHADING_PNG))
        self.assertEqual((im.format, im.mode, im.size), ("PNG", "L", (256, 256)))

    def test_the_shading_check_refuses_a_json_error_a_page_and_another_size(self):
        with self.assertRaises(T.TerrainError):
            T.check_shading_png(b'{"error":{"code":400,"message":"Unable to complete operation."}}')
        with self.assertRaises(T.TerrainError):
            T.check_shading_png(b"<html>Bad gateway</html>")
        buf = io.BytesIO()
        Image.new("L", (16, 16), 128).save(buf, format="PNG")
        with self.assertRaises(T.TerrainError) as raised:
            T.check_shading_png(buf.getvalue())
        self.assertIn("256 pixel", str(raised.exception))

    def test_a_truncated_shading_answer_is_refused(self):
        # the PNG header is whole, so only the decode finds the damage
        with self.assertRaises(T.TerrainError) as raised:
            T.check_shading_png(SHADING_PNG[: len(SHADING_PNG) // 2])
        self.assertIn("not a readable image", str(raised.exception))

    def test_a_truncated_land_cover_answer_is_refused_as_a_terrain_error(self):
        with self.assertRaises(T.TerrainError) as raised:
            T.check_land_tiff(LAND_TIFF[: len(LAND_TIFF) // 2])
        self.assertIn("not a readable image", str(raised.exception))

    def test_the_land_cover_fixture_holds_only_legend_codes(self):
        T.check_land_tiff(LAND_TIFF)
        codes = np.unique(np.asarray(Image.open(io.BytesIO(LAND_TIFF))))
        self.assertTrue(set(int(c) for c in codes) <= set(T.LEGEND_CODES))

    def test_the_fill_outside_the_coverage_is_accepted_and_drawn_transparent(self):
        codes = np.full((256, 256), 255, np.uint8)            # the fill the answer gives outside the coverage
        codes[:, :128] = 41
        palette = Image.fromarray(codes, mode="P")
        palette.putpalette([0, 0, 0] * 256)
        buf = io.BytesIO()
        palette.save(buf, format="TIFF")
        T.check_land_tiff(buf.getvalue())
        out = np.asarray(Image.open(io.BytesIO(T.tint_png(buf.getvalue()))))
        self.assertEqual(out[0, 0], 1)                         # forest
        self.assertEqual(out[0, 255], 0)                       # the fill is transparent

    def test_the_land_cover_check_refuses_a_code_outside_the_legend(self):
        palette = Image.new("P", (256, 256), 200)
        palette.putpalette([0, 0, 0] * 256)
        buf = io.BytesIO()
        palette.save(buf, format="TIFF")
        with self.assertRaises(T.TerrainError) as raised:
            T.check_land_tiff(buf.getvalue())
        self.assertIn("legend", str(raised.exception))

    def test_the_shading_jpeg_is_grey_at_quality_80_and_repeats_exactly(self):
        first = T.shading_jpeg(SHADING_PNG)
        self.assertEqual(first, T.shading_jpeg(SHADING_PNG))
        im = Image.open(io.BytesIO(first))
        self.assertEqual((im.format, im.mode, im.size), ("JPEG", "L", (256, 256)))
        # the IJG luminance table scaled to quality 80: the first (DC) entry is 6 (16 * 40 / 100, rounded)
        self.assertEqual(im.quantization[0][0], 6)

    def test_the_transparency_grey_is_kept_as_the_service_sends_it(self):
        grid = np.full((256, 256), 100, np.uint8)
        grid[:64, :] = 253                                    # a grey value the service marks as transparent
        buf = io.BytesIO()
        im = Image.fromarray(grid, mode="L")
        im.save(buf, format="PNG", transparency=253)
        out = np.asarray(Image.open(io.BytesIO(T.shading_jpeg(buf.getvalue()))).convert("L"))
        self.assertLess(abs(float(out[8:56, :].mean()) - 253.0), 1.5)     # kept, not written as white (255)
        self.assertLess(abs(float(out[100:, :].mean()) - 100.0), 3.0)

    def test_the_tint_maps_each_code_to_its_class_and_index_0_is_transparent(self):
        row = [11, 41, 52, 71, 21, 82, 90, 0]                 # water, forest, shrub, grass, developed, crop, woody wetland, none
        codes = np.tile(np.array(row, np.uint8), (256, 32))
        palette = Image.fromarray(codes, mode="P")
        palette.putpalette([0, 0, 0] * 256)
        buf = io.BytesIO()
        palette.save(buf, format="TIFF")
        out = Image.open(io.BytesIO(T.tint_png(buf.getvalue())))
        self.assertEqual((out.format, out.mode, out.size), ("PNG", "P", (256, 256)))
        self.assertEqual(out.info.get("transparency"), 0)
        indices = np.asarray(out)[0, :8].tolist()
        self.assertEqual(indices, [5, 1, 2, 2, 3, 4, 2, 0])      # the woody wetland 90 takes the shrub and grass class

    def test_the_tint_palette_holds_the_five_proof_colours(self):
        flat = T._palette_flat()
        colours = ["#%02x%02x%02x" % tuple(flat[i * 3:i * 3 + 3]) for i in range(1, 6)]
        self.assertEqual(colours, ["#cde2c3", "#e6ecd6", "#f1ead6", "#f2efd0", "#b9d9f2"])
        self.assertEqual([name for _i, name, _c, _codes in T.TINT],
                         ["forest", "shrub and grass", "developed", "crop", "water"])

    def test_the_land_cover_tile_uses_only_the_five_indices(self):
        out = np.asarray(Image.open(io.BytesIO(T.tint_png(LAND_TIFF))))
        values = set(np.unique(out).tolist())
        self.assertTrue(values <= {0, 1, 2, 3, 4, 5})
        self.assertIn(0, values)                              # the fixture has a transparent code (31, bare ground)
        self.assertEqual(T.tint_png(LAND_TIFF), T.tint_png(LAND_TIFF))

    def test_the_wetland_codes_take_the_shrub_and_grass_class_and_barren_stays_transparent(self):
        lut = T._lut()
        self.assertEqual([int(lut[c]) for c in (90, 95)], [2, 2])                       # woody and emergent wetlands
        self.assertEqual([int(lut[c]) for c in (52, 71)], [2, 2])                       # shrub and grass, as before
        self.assertEqual([int(lut[c]) for c in (31, 32)], [0, 0])                       # barren stays transparent
        self.assertEqual([int(lut[c]) for c in (0, 12, 51, 72, 73, 74, 255)], [0] * 7)  # the other codes stay transparent
        self.assertEqual([int(lut[c]) for c in (21, 22, 23, 24)], [3, 3, 3, 3])         # the four developed codes, one shade
        self.assertEqual([int(lut[c]) for c in (81, 82)], [4, 4])                       # pasture and hay with crop
        self.assertEqual(int(lut[11]), 5)                                               # water
        self.assertEqual([name for _i, name, _c, codes in T.TINT if 95 in codes], ["shrub and grass"])
        self.assertIn("90 and 95", T.__doc__)                                           # the docstring's class list says so

    def test_the_shading_fixture_round_trips_through_the_drawing(self):
        self.assertEqual(T.shading_jpeg(SHADING_PNG), T.shading_jpeg(SHADING_PNG))
        out = Image.open(io.BytesIO(T.shading_jpeg(SHADING_PNG)))
        self.assertEqual(out.size, (256, 256))


# ---------------------------------------------------------------- tries and the cache

@unittest.skipUnless(HAVE_IMAGES, "needs Pillow and numpy")
class TriesTests(unittest.TestCase):
    def test_a_server_error_is_tried_again_and_the_answer_is_kept(self):
        answers = [(503, b"", ""), (200, SHADING_PNG, "")]
        sleeps: list[float] = []
        body, tries = T.fetch_checked("u", {}, T.check_shading_png, get=lambda url, p: answers.pop(0),
                                      sleep=sleeps.append)
        self.assertEqual((body, tries), (SHADING_PNG, 2))
        self.assertEqual(sleeps, [T.WAIT_S])

    def test_three_failed_tries_give_the_last_reason(self):
        calls = []
        sleeps: list[float] = []

        def get(url, params):
            calls.append(url)
            return 500, b"", ""
        with self.assertRaises(T.TerrainError) as raised:
            T.fetch_checked("u", {}, T.check_shading_png, get=get, sleep=sleeps.append)
        self.assertEqual(str(raised.exception), "HTTP 500")
        self.assertEqual(raised.exception.tries, T.TRIES)
        self.assertEqual(len(calls), T.TRIES)
        self.assertEqual(sleeps, [T.WAIT_S, 2 * T.WAIT_S])

    def test_a_client_error_is_final(self):
        calls = []
        with self.assertRaises(T.TerrainError) as raised:
            T.fetch_checked("u", {}, T.check_shading_png,
                            get=lambda url, p: (calls.append(url), (404, b"", ""))[1], sleep=NOOP_SLEEP)
        self.assertEqual(str(raised.exception), "HTTP 404")
        self.assertEqual(len(calls), 1)
        self.assertEqual(raised.exception.tries, 1)              # the one request it took, counted as one (not zero)

    def test_a_body_that_is_not_the_image_is_tried_again(self):
        calls = []
        with self.assertRaises(T.TerrainError) as raised:
            T.fetch_checked("u", {}, T.check_shading_png,
                            get=lambda url, p: (calls.append(url), (200, b"<html>", ""))[1], sleep=NOOP_SLEEP)
        self.assertEqual(len(calls), T.TRIES)
        self.assertIn("not a PNG", str(raised.exception))

    def test_the_timeout_is_passed_to_each_request(self):
        with mock.patch.object(T, "_http_get", return_value=(200, SHADING_PNG, "")) as get:
            T.fetch_checked("u", {"a": 1}, T.check_shading_png, sleep=NOOP_SLEEP, timeout=45)
        self.assertEqual(get.call_args.kwargs.get("timeout"), 45)
        with mock.patch.object(T, "_http_get", return_value=(200, SHADING_PNG, "")) as get:
            T.fetch_checked("u", {}, T.check_shading_png, sleep=NOOP_SLEEP)
        self.assertEqual(get.call_args.kwargs.get("timeout"), T.TIMEOUT_S)

    def test_a_timeout_outside_five_to_120_seconds_is_refused(self):
        import contextlib
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(T.main(["build", "--store", "unused", "--cache", "unused", "--timeout", "1"]), 2)

    def test_a_truncated_land_cover_answer_with_status_200_is_tried_three_times(self):
        calls = []
        truncated = LAND_TIFF[: len(LAND_TIFF) // 2]
        with self.assertRaises(T.TerrainError) as raised:
            T.fetch_checked(T.LAND_URL, {}, T.check_land_tiff,
                            get=lambda url, p: (calls.append(url), (200, truncated, ""))[1], sleep=NOOP_SLEEP)
        self.assertEqual(len(calls), T.TRIES)
        self.assertEqual(raised.exception.tries, T.TRIES)
        self.assertIn("not a readable image", str(raised.exception))

    def test_a_network_error_and_a_429_are_tried_again(self):
        answers = [(None, b"", "the request failed (ConnectionError)"), (429, b"", ""), (200, SHADING_PNG, "")]
        body, tries = T.fetch_checked("u", {}, T.check_shading_png, get=lambda url, p: answers.pop(0), sleep=NOOP_SLEEP)
        self.assertEqual(tries, 3)
        self.assertEqual(body, SHADING_PNG)


@unittest.skipUnless(HAVE_IMAGES, "needs Pillow and numpy")
class CacheTests(unittest.TestCase):
    def test_a_cached_copy_is_used_without_a_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "8" / "50" / "90.png"
            path.parent.mkdir(parents=True)
            path.write_bytes(SHADING_PNG)

            def never(url, params):
                raise AssertionError("a cached copy must not be requested")
            body, origin, tries, note = T.source_bytes("u", {}, T.check_shading_png, path, offline=False, refresh=False,
                                                       deadline_at=None, get=never, sleep=NOOP_SLEEP)
            self.assertEqual((origin, tries, note), ("cache", 0, None))
            self.assertEqual(body, SHADING_PNG)

    def test_offline_without_a_copy_makes_no_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            def never(url, params):
                raise AssertionError("offline must not request")
            with self.assertRaises(T.TerrainError) as raised:
                T.source_bytes("u", {}, T.check_shading_png, Path(tmp) / "none.png", offline=True, refresh=False,
                               deadline_at=None, get=never, sleep=NOOP_SLEEP)
            self.assertIn("no copy", str(raised.exception))

    def test_a_refresh_that_fails_serves_the_cached_copy_with_its_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keep.png"
            path.write_bytes(SHADING_PNG)
            body, origin, tries, note = T.source_bytes("u", {}, T.check_shading_png, path, offline=False, refresh=True,
                                                       deadline_at=None, get=lambda url, p: (503, b"", ""),
                                                       sleep=NOOP_SLEEP)
            self.assertEqual((origin, tries, body), ("cache", T.TRIES, SHADING_PNG))
            self.assertIn("served the cached copy after: HTTP 503", note)

    def test_a_corrupt_cached_copy_is_replaced_by_a_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.png"
            path.write_bytes(b"not an image")
            body, origin, tries, note = T.source_bytes("u", {}, T.check_shading_png, path, offline=False, refresh=False,
                                                       deadline_at=None, get=lambda url, p: (200, SHADING_PNG, ""),
                                                       sleep=NOOP_SLEEP)
            self.assertEqual((origin, tries), ("fetched", 1))
            self.assertIn("the cached copy was not usable", note)
            self.assertEqual(path.read_bytes(), SHADING_PNG)

    def test_a_truncated_cached_shading_copy_is_requested_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "truncated.png"
            path.write_bytes(SHADING_PNG[: len(SHADING_PNG) // 2])
            body, origin, tries, note = T.source_bytes("u", {}, T.check_shading_png, path, offline=False, refresh=False,
                                                       deadline_at=None, get=lambda url, p: (200, SHADING_PNG, ""),
                                                       sleep=NOOP_SLEEP)
            self.assertEqual((origin, tries), ("fetched", 1))
            self.assertIn("the cached copy was not usable", note)
            self.assertEqual(body, SHADING_PNG)
            self.assertEqual(path.read_bytes(), SHADING_PNG)

    def test_a_truncated_cached_land_cover_copy_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "truncated.tif"
            path.write_bytes(LAND_TIFF[: len(LAND_TIFF) // 2])
            _body, origin, _tries, note = T.source_bytes("u", {}, T.check_land_tiff, path, offline=False, refresh=False,
                                                         deadline_at=None, get=lambda url, p: (200, LAND_TIFF, ""),
                                                         sleep=NOOP_SLEEP)
            self.assertEqual(origin, "fetched")
            self.assertIn("not a readable image", note)

    def test_an_offline_build_uses_a_valid_copy_whatever_refresh_says(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "8" / "50" / "90.png"
            path.parent.mkdir(parents=True)
            path.write_bytes(SHADING_PNG)

            def never(url, params):
                raise AssertionError("an offline build must not request")
            body, origin, tries, note = T.source_bytes("u", {}, T.check_shading_png, path, offline=True, refresh=True,
                                                       deadline_at=None, get=never, sleep=NOOP_SLEEP)
            self.assertEqual((origin, tries, note), ("cache", 0, None))
            self.assertEqual(body, SHADING_PNG)

    def test_a_refresh_refused_with_a_client_error_is_one_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keep.png"
            path.write_bytes(SHADING_PNG)
            body, origin, tries, note = T.source_bytes("u", {}, T.check_shading_png, path, offline=False, refresh=True,
                                                       deadline_at=None, get=lambda url, p: (404, b"", ""),
                                                       sleep=NOOP_SLEEP)
            self.assertEqual((origin, tries, body), ("cache", 1, SHADING_PNG))
            self.assertIn("served the cached copy after: HTTP 404", note)

    def test_a_deadline_stops_the_request_with_its_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            def never(url, params):
                raise AssertionError("past the deadline no request is made")
            with self.assertRaises(T.TerrainError) as raised:
                T.source_bytes("u", {}, T.check_shading_png, Path(tmp) / "x.png", offline=False, refresh=False,
                               deadline_at=time.monotonic() - 1.0, get=never, sleep=NOOP_SLEEP)
            self.assertEqual(str(raised.exception), T.REASON_DEADLINE)


# ---------------------------------------------------------------- the build

@unittest.skipUnless(HAVE_IMAGES, "needs Pillow and numpy")
class BuildTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = empty_store(self.root / "store")
        self.cache = self.root / "cache"

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, source, *, zooms=(5,), only=T.LAYERS, cache=None):
        return T.build(self.store, cache or self.cache, zooms=zooms, only=only, get=source, sleep=NOOP_SLEEP, procs=2)

    def index_block(self) -> dict:
        return json.loads((self.store / "hail" / "base" / "index.json").read_text(encoding="utf-8"))["terrain"]

    def tile_hashes(self) -> dict:
        """The hash of every tile file (the base index is left out: it carries the build's time)."""
        base = self.store / "hail" / "base"
        return {p.relative_to(base).as_posix(): sha(p) for p in base.rglob("*") if p.is_file() and p.name != "index.json"}

    def test_both_layers_are_written_with_their_index_blocks_and_manifest_entries(self):
        source = FakeSource()
        result = self.build(source)
        self.assertEqual(result["state"], "loaded")
        self.assertEqual(result["files"], 8)
        for key in ZOOM5_KEYS:
            z, x, y = key.split("/")
            self.assertTrue((self.store / "hail" / "base" / "h" / z / x / f"{y}.jpg").is_file())
            self.assertTrue((self.store / "hail" / "base" / "l" / z / x / f"{y}.png").is_file())
        block = self.index_block()
        self.assertEqual((block["format"], block["state"], block["zooms"]), (T.FORMAT, "loaded", [5]))
        self.assertEqual(block["as_of"]["shading_date"], "2026-09-28")
        self.assertEqual(block["as_of"]["land_cover"], "2023-06")
        self.assertEqual(block["counts"]["tiles_by_zoom"], {"5": 4})
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        mirror = index["base"]["terrain"]
        self.assertEqual((mirror["state"], mirror["bytes"]), ("loaded", block["bytes"]))
        self.assertEqual(index["gauges"], {"state": "loaded"})            # another part's key is kept
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))["files"]
        for rel in ("hail/base/index.json", "hail/index.json"):
            self.assertIn(rel, manifest)
        base_files = [k for k in manifest if k.startswith(("hail/base/h/", "hail/base/l/"))]
        self.assertEqual(len(base_files), 8)
        for rel in base_files:
            data = (self.root / "store" / rel).read_bytes()
            self.assertEqual(manifest[rel], {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_a_tile_that_fails_three_tries_is_missing_and_the_build_goes_on(self):
        failing = sorted(ZOOM5_KEYS)[0]
        source = FakeSource(fail={("h", failing): 503})
        result = self.build(source)
        self.assertEqual(result["state"], "partial")
        self.assertEqual(source.count("h", failing), T.TRIES)
        block = self.index_block()
        self.assertEqual(block["layers"]["h"]["missing"], [failing])
        self.assertEqual(block["layers"]["h"]["state"], "partial")
        self.assertEqual(block["layers"]["l"]["state"], "loaded")
        self.assertEqual(block["problem"], "Data unavailable. Terrain shading could not be loaded in this update for 1 of 4 "
                                           "tiles; that is not the same as no terrain shading. This is not an all-clear.")
        z, x, y = failing.split("/")
        self.assertFalse((self.store / "hail" / "base" / "h" / z / x / f"{y}.jpg").exists())
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_a_layer_that_fails_everywhere_is_unavailable_and_its_files_are_gone(self):
        source = FakeSource(fail={("l", "*"): 500})
        result = self.build(source)
        self.assertEqual(result["state"], "partial")
        self.assertFalse((self.store / "hail" / "base" / "l").exists())
        block = self.index_block()
        self.assertEqual(block["layers"]["l"]["state"], "unavailable")
        self.assertEqual(block["problem"], "Data unavailable. The land cover tint could not be loaded in this update; that is "
                                           "not the same as no land cover tint. This is not an all-clear.")
        self.assertIn("Data unavailable", block["layers"]["l"]["problem"])
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))["files"]
        self.assertFalse([k for k in manifest if k.startswith("hail/base/l/")])
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_a_failed_service_description_makes_the_shading_unavailable_without_shading_requests(self):
        source = FakeSource(meta_status=500)
        result = self.build(source)
        self.assertEqual(result["state"], "partial")
        self.assertEqual([c for c in source.calls if c[0] == "h"], [])
        block = self.index_block()
        self.assertEqual(block["layers"]["h"]["state"], "unavailable")
        self.assertIn("HTTP 500", block["detail"])
        self.assertEqual(block["layers"]["l"]["state"], "loaded")
        self.assertFalse((self.store / "hail" / "base" / "h").exists())
        credits = T.map_data(json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8")))["credits"]
        self.assertEqual(credits["shading"], "Terrain shading: Data unavailable in this update.")
        self.assertIn("National Land Cover Database", credits["land_cover"])

    def test_a_refused_tile_is_one_request_in_the_counts(self):
        key = sorted(ZOOM5_KEYS)[1]
        source = FakeSource(fail={("l", key): 404})
        self.build(source)
        block = self.index_block()
        self.assertEqual(block["layers"]["l"]["missing_reasons"][key], {"reason": "HTTP 404", "tries": 1})
        self.assertEqual(source.count("l", key), 1)
        self.assertEqual(block["counts"]["requests"], 8)              # four shading and four land cover answers, one each
        self.assertEqual(block["counts"]["retries"], 0)

    def test_an_offline_build_with_a_refresh_uses_the_cache_and_writes_the_same_files(self):
        self.build(FakeSource())
        first = self.tile_hashes()

        def never(url, params):
            raise AssertionError("an offline build must not request")
        result = T.build(self.store, self.cache, zooms=(5,), get=never, sleep=NOOP_SLEEP, procs=2, offline=True,
                         refresh=True)
        self.assertEqual(result["state"], "loaded")
        self.assertEqual(result["not_rebuilt"], {})
        self.assertEqual(result["requests"], 0)
        self.assertEqual(self.tile_hashes(), first)
        self.assertEqual(self.index_block()["counts"]["cache_hits"], 8)
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_an_offline_build_with_a_tile_missing_from_the_cache_deletes_no_tile_file(self):
        self.build(FakeSource())
        before = self.tile_hashes()
        z, x, y = sorted(ZOOM5_KEYS)[0].split("/")
        (self.cache / "shading" / "2026-09" / z / x / f"{y}.png").unlink()

        def never(url, params):
            raise AssertionError("an offline build must not request")
        result = T.build(self.store, self.cache, zooms=(5,), get=never, sleep=NOOP_SLEEP, procs=2, offline=True)
        self.assertEqual(self.tile_hashes(), before)                  # nothing deleted and nothing rewritten
        self.assertIn("1 of 4 tiles have no valid cached copy", result["not_rebuilt"]["h"])
        self.assertNotIn("l", result["not_rebuilt"])                  # the land cover is complete, so it is rebuilt
        block = self.index_block()
        self.assertEqual((block["state"], block["layers"]["h"]["state"], block["layers"]["h"]["files"]),
                         ("loaded", "loaded", 4))
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_an_offline_build_without_the_shading_description_keeps_the_shading_its_date_and_files(self):
        self.build(FakeSource())
        before_tiles = self.tile_hashes()
        before_block = self.index_block()
        (self.cache / "meta" / "3dep-service.json").unlink()

        def never(url, params):
            raise AssertionError("an offline build must not request")
        result = T.build(self.store, self.cache, zooms=(5,), get=never, sleep=NOOP_SLEEP, procs=2, offline=True)
        self.assertIn("the cache has no copy", result["not_rebuilt"]["h"])
        self.assertEqual(self.tile_hashes(), before_tiles)
        block = self.index_block()
        self.assertEqual(block["layers"]["h"], before_block["layers"]["h"])
        self.assertEqual((block["as_of"]["shading_date"], block["as_of"]["shading_month"]), ("2026-09-28", "2026-09"))
        self.assertEqual(block["state"], "loaded")
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_a_land_only_build_during_a_shading_outage_keeps_the_shading_date_month_and_files(self):
        self.build(FakeSource())
        before_block = self.index_block()
        before_h = {k: v for k, v in self.tile_hashes().items() if k.startswith("h/")}
        source = FakeSource(meta_status=500)
        result = self.build(source, only=("l",))
        self.assertEqual(source.count("meta", ""), 0)     # the shading description is not read for a land-only build
        self.assertEqual(result["state"], "loaded")
        block = self.index_block()
        self.assertEqual((block["as_of"]["shading_date"], block["as_of"]["shading_month"]), ("2026-09-28", "2026-09"))
        self.assertEqual(block["layers"]["h"], before_block["layers"]["h"])
        self.assertEqual({k: v for k, v in self.tile_hashes().items() if k.startswith("h/")}, before_h)
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        self.assertIn("data as of 2026-09-28", T.map_data(index)["credits"]["shading"])
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_the_shading_copyright_line_is_read_from_the_description_and_falls_back_to_the_constant(self):
        description = json.loads(META)["description"]
        self.build(FakeSource())
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        copyright_text = json.loads(META)["copyrightText"]
        self.assertEqual(self.index_block()["sources"]["shading"]["copyright"], copyright_text)
        self.assertEqual(index["base"]["terrain"]["sources"]["shading"]["copyright"], copyright_text)
        newer = json.dumps({"copyrightText": "USGS National Map 3D Elevation Program (3DEP). November 02, 2026.",
                            "description": description}).encode("utf-8")
        T.build(self.store, self.cache, zooms=(5,), get=FakeSource(meta=newer), sleep=NOOP_SLEEP, procs=2, refresh=True)
        self.assertEqual(self.index_block()["sources"]["shading"]["copyright"],
                         "USGS National Map 3D Elevation Program (3DEP). November 02, 2026.")
        bare = json.dumps({"description": description}).encode("utf-8")       # a description with no copyrightText
        T.build(self.store, self.cache, zooms=(5,), get=FakeSource(meta=bare), sleep=NOOP_SLEEP, procs=2, refresh=True)
        self.assertEqual(self.index_block()["sources"]["shading"]["copyright"], T.SOURCES["shading"]["copyright_fallback"])

    def test_an_offline_first_build_with_no_cache_builds_nothing_and_says_why(self):
        def never(url, params):
            raise AssertionError("an offline build must not request")
        result = T.build(self.store, self.cache, zooms=(5,), get=never, sleep=NOOP_SLEEP, procs=2, offline=True)
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(sorted(result["not_rebuilt"]), ["h", "l"])
        self.assertIn("terrain shading not rebuilt offline (shading service: the cache has no copy", result["detail"])
        self.assertIn("land cover tint not rebuilt offline (land cover service: the cache has no copy", result["detail"])
        self.assertEqual(result["detail"].count("shading service"), 1)            # each reason is given once
        self.assertFalse((self.store / "hail" / "base" / "h").exists())
        self.assertFalse((self.store / "hail" / "base" / "l").exists())
        self.assertEqual(self.index_block()["state"], "unavailable")
        self.assertEqual(self.index_block()["detail"], result["detail"])
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_the_second_run_reads_the_cache_and_writes_the_same_bytes(self):
        self.build(FakeSource())
        first = self.tile_hashes()
        second_source = FakeSource()
        self.build(second_source)
        self.assertEqual([c for c in second_source.calls if c[0] in ("h", "l", "meta", "landmeta")], [])
        self.assertEqual(first, self.tile_hashes())
        self.assertEqual(self.index_block()["counts"]["cache_hits"], 8)

    def test_two_builds_with_separate_caches_write_identical_files(self):
        other_store = empty_store(self.root / "other")
        self.build(FakeSource())
        T.build(other_store, self.root / "other-cache", zooms=(5,), get=FakeSource(), sleep=NOOP_SLEEP, procs=2)
        mine = {p.relative_to(self.store / "hail" / "base").as_posix(): sha(p)
                for p in (self.store / "hail" / "base").rglob("*") if p.is_file() and p.name != "index.json"}
        theirs = {p.relative_to(other_store / "hail" / "base").as_posix(): sha(p)
                  for p in (other_store / "hail" / "base").rglob("*") if p.is_file() and p.name != "index.json"}
        self.assertEqual(mine, theirs)

    def test_one_layer_rebuilt_keeps_the_other_layer_and_its_manifest_entries(self):
        self.build(FakeSource())
        result = self.build(FakeSource(fail={("h", "*"): 500}), only=("h",), cache=self.root / "fresh-cache")
        self.assertEqual(result["layers"]["h"]["state"], "unavailable")
        self.assertFalse((self.store / "hail" / "base" / "h").exists())
        self.assertTrue(any((self.store / "hail" / "base" / "l").rglob("*.png")))
        block = self.index_block()
        self.assertEqual(block["layers"]["l"]["state"], "loaded")
        self.assertEqual(block["state"], "partial")
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))["files"]
        self.assertEqual(len([k for k in manifest if k.startswith("hail/base/l/")]), 4)

    def test_the_unavailable_command_removes_the_files_and_keeps_other_parts_keys(self):
        self.build(FakeSource())
        base_path = self.store / "hail" / "base" / "index.json"
        base = json.loads(base_path.read_text(encoding="utf-8"))
        base["areas"] = {"state": "loaded"}
        base_path.write_text(json.dumps(base), encoding="utf-8")
        result = T.mark_unavailable(self.store, "the job's download failed")
        self.assertEqual(result["state"], "unavailable")
        self.assertFalse((self.store / "hail" / "base" / "h").exists())
        self.assertFalse((self.store / "hail" / "base" / "l").exists())
        kept = json.loads(base_path.read_text(encoding="utf-8"))
        self.assertEqual(kept["areas"], {"state": "loaded"})
        self.assertEqual(kept["terrain"]["state"], "unavailable")
        self.assertEqual(kept["terrain"]["problem"], T.WORDS["unavailable"])
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["base"]["terrain"]["state"], "unavailable")
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_the_command_line_refuses_a_zoom_subset_without_keep_other_zooms(self):
        self.build(FakeSource(), zooms=(5, 6))
        before = self.tile_hashes()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = T.main(["build", "--store", str(self.store), "--cache", str(self.cache), "--zooms", "5"])
        self.assertEqual(code, 2)
        self.assertIn("--keep-other-zooms", err.getvalue())
        self.assertEqual(self.tile_hashes(), before)

    def test_the_command_line_builds_and_marks_unavailable(self):
        self.build(FakeSource(), zooms=(5,))
        with mock.patch.object(T, "_http_get", FakeSource()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(T.main(["build", "--store", str(self.store), "--cache", str(self.cache), "--zooms", "5",
                                     "--keep-other-zooms", "--procs", "2"]), 0)
        self.assertEqual(self.index_block()["state"], "loaded")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(T.main(["unavailable", "--store", str(self.store), "--reason", "the job stopped"]), 0)
        self.assertEqual(self.index_block()["state"], "unavailable")

    def test_the_default_cache_sits_beside_the_store(self):
        self.assertEqual(T.default_cache_dir(self.root / "store"), (self.root / "terrain-cache").resolve())
        self.build(FakeSource(), zooms=(5,))
        with mock.patch.object(T, "_http_get", FakeSource()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(T.main(["build", "--store", str(self.store), "--zooms", "5", "--keep-other-zooms",
                                     "--procs", "2"]), 0)
        self.assertTrue((self.root / "terrain-cache" / "shading" / "2026-09").is_dir())

    def test_a_zoom_subset_with_keep_other_zooms_rebuilds_its_zoom_and_keeps_the_rest(self):
        self.build(FakeSource(), zooms=(5, 6))
        before = self.tile_hashes()
        source = FakeSource()
        result = T.build(self.store, self.cache, zooms=(6,), get=source, sleep=NOOP_SLEEP, procs=2, refresh=True,
                         keep_other_zooms=True)
        self.assertEqual(result["state"], "loaded")
        requested = {key for kind, key in source.calls if kind in ("h", "l")}
        self.assertTrue(requested)
        self.assertTrue(all(key.startswith("6/") for key in requested))
        after = self.tile_hashes()
        zoom5 = [rel for rel in before if rel.split("/")[1] == "5"]
        self.assertEqual(len(zoom5), 8)
        self.assertEqual({rel: after[rel] for rel in zoom5}, {rel: before[rel] for rel in zoom5})
        block = self.index_block()
        self.assertEqual(block["zooms"], [5, 6])
        self.assertEqual(block["counts"]["tiles_by_zoom"], {"5": 4, "6": 9})
        self.assertEqual(block["counts"]["requests"], 18)      # the kept tiles made no request in this run
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_a_subset_build_needs_an_earlier_build_that_covers_its_zooms(self):
        with self.assertRaises(T.TerrainError) as raised:
            T.build(self.store, self.cache, zooms=(5,), get=FakeSource(), sleep=NOOP_SLEEP, procs=2,
                    keep_other_zooms=True)
        self.assertIn("no earlier build", str(raised.exception))
        self.build(FakeSource(), zooms=(5,))
        with self.assertRaises(T.TerrainError) as raised:
            T.build(self.store, self.cache, zooms=(6,), get=FakeSource(), sleep=NOOP_SLEEP, procs=2,
                    keep_other_zooms=True)
        self.assertIn("not all in the earlier build", str(raised.exception))
        self.assertEqual(self.index_block()["zooms"], [5])      # the refused request changed nothing

    def test_a_truncated_land_cover_answer_leaves_its_tile_missing_and_the_build_goes_on(self):
        key = sorted(ZOOM5_KEYS)[0]
        source = FakeSource(bodies={("l", key): LAND_TIFF[: len(LAND_TIFF) // 2]})
        result = self.build(source)
        self.assertEqual(result["state"], "partial")
        self.assertEqual(source.count("l", key), T.TRIES)
        block = self.index_block()
        self.assertEqual(block["layers"]["l"]["missing"], [key])
        self.assertEqual(block["layers"]["h"]["state"], "loaded")
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_a_truncated_shading_answer_is_not_kept_and_the_next_run_requests_it_again(self):
        key = sorted(ZOOM5_KEYS)[0]
        first = FakeSource(bodies={("h", key): SHADING_PNG[: len(SHADING_PNG) // 2]})
        self.build(first)
        self.assertEqual(first.count("h", key), T.TRIES)
        self.assertEqual(self.index_block()["layers"]["h"]["missing"], [key])
        second = FakeSource()
        result = self.build(second)
        self.assertEqual(second.count("h", key), 1)
        self.assertEqual(result["state"], "loaded")

    def test_the_detail_gives_each_missing_tile_its_own_reason(self):
        shading_key, land_key = sorted(ZOOM5_KEYS)[0], sorted(ZOOM5_KEYS)[1]
        self.build(FakeSource(fail={("h", shading_key): 503, ("l", land_key): 404}))
        block = self.index_block()
        self.assertEqual(block["layers"]["h"]["missing_reasons"][shading_key], {"reason": "HTTP 503", "tries": T.TRIES})
        self.assertIn(f"h {shading_key}: did not load after {T.TRIES} tries: HTTP 503", block["detail"])
        self.assertIn(f"l {land_key}: did not load: HTTP 404", block["detail"])
        self.assertNotIn(f"l {land_key}: did not load after", block["detail"])

    def test_a_layer_whose_description_names_another_layer_fails_loudly(self):
        renamed = LAND_DESCRIBE.replace(b"NLCD_2021_Land_Cover_L48", b"NLCD_2031_Land_Cover_L48")
        source = FakeSource(land_describe=renamed)
        result = self.build(source)
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["layers"]["l"]["state"], "unavailable")
        self.assertEqual([c for c in source.calls if c[0] == "l"], [])      # no land cover tile is requested
        block = self.index_block()
        self.assertIn("land cover service: the land cover layer mrlc_display:NLCD_2021_Land_Cover_L48 is not in the service",
                      block["detail"])
        self.assertFalse((self.store / "hail" / "base" / "l").exists())
        self.assertEqual(block["layers"]["h"]["state"], "loaded")
        self.assertIsNone(block["as_of"]["land_cover"])
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_the_land_cover_month_is_read_from_the_service_description(self):
        self.build(FakeSource(land_describe=LAND_DESCRIBE.replace(b"20230630", b"20240515")))
        self.assertEqual(self.index_block()["as_of"]["land_cover"], "2024-05")
        self.assertTrue((self.cache / "land_cover" / "2024-05").is_dir())
        self.assertTrue((self.cache / "meta" / "nlcd-coverage.xml").is_file())

    def test_a_refresh_reads_both_descriptions_again(self):
        self.build(FakeSource())
        source = FakeSource()
        T.build(self.store, self.cache, zooms=(5,), get=source, sleep=NOOP_SLEEP, procs=2, refresh=True)
        self.assertEqual(source.count("meta", ""), 1)
        self.assertEqual(source.count("landmeta", ""), 1)

    def test_a_refresh_descriptions_reads_both_descriptions_and_requests_no_valid_tile(self):
        # D128(f): the descriptions are read again, and every cached tile is used whatever its age (the copies are years old)
        self.build(FakeSource())
        first = self.tile_hashes()
        old = time.time() - 4 * 365 * 86400
        for path in self.cache.rglob("*"):
            if path.is_file():
                os.utime(path, (old, old))
        source = FakeSource()
        result = T.build(self.store, self.cache, zooms=(5,), get=source, sleep=NOOP_SLEEP, procs=2, refresh_descriptions=True)
        self.assertEqual(result["state"], "loaded")
        self.assertEqual(source.count("meta", ""), 1)
        self.assertEqual(source.count("landmeta", ""), 1)
        self.assertEqual([c for c in source.calls if c[0] in ("h", "l")], [])
        self.assertEqual(result["requests"], 0)
        self.assertEqual(self.index_block()["counts"]["cache_hits"], 8)
        self.assertEqual(self.tile_hashes(), first)
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_a_changed_month_under_refresh_descriptions_requests_its_tiles_through_the_new_cache_key(self):
        # D128(f): the shading month changed, so its four tiles are requested under the new month; the land cover month did not
        self.build(FakeSource())
        description = json.loads(META)
        newer = json.dumps({"copyrightText": description["copyrightText"],
                            "description": description["description"].replace("September 28, 2026", "November 02, 2026")})
        source = FakeSource(meta=newer.encode("utf-8"))
        T.build(self.store, self.cache, zooms=(5,), get=source, sleep=NOOP_SLEEP, procs=2, refresh_descriptions=True)
        self.assertEqual(self.index_block()["as_of"]["shading_month"], "2026-11")
        self.assertEqual(len([c for c in source.calls if c[0] == "h"]), 4)
        self.assertEqual([c for c in source.calls if c[0] == "l"], [])
        self.assertTrue((self.cache / "shading" / "2026-11").is_dir())
        self.assertFalse((self.cache / "shading" / "2026-09").exists())
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_a_refresh_still_requests_every_tile_and_reads_both_descriptions(self):
        # --refresh keeps its meaning: every tile is asked again, though each one is cached, and both descriptions are read
        self.build(FakeSource())
        source = FakeSource()
        result = T.build(self.store, self.cache, zooms=(5,), get=source, sleep=NOOP_SLEEP, procs=2, refresh=True)
        self.assertEqual(source.count("meta", ""), 1)
        self.assertEqual(source.count("landmeta", ""), 1)
        self.assertEqual(len([c for c in source.calls if c[0] in ("h", "l")]), 8)
        self.assertEqual(result["requests"], 8)
        self.assertEqual(self.index_block()["counts"]["cache_hits"], 0)

    def test_an_offline_build_with_refresh_descriptions_makes_no_request(self):
        self.build(FakeSource())

        def never(url, params):
            raise AssertionError("an offline build must not request")
        result = T.build(self.store, self.cache, zooms=(5,), get=never, sleep=NOOP_SLEEP, procs=2, offline=True,
                         refresh_descriptions=True)
        self.assertEqual(result["state"], "loaded")
        self.assertEqual(result["not_rebuilt"], {})
        self.assertEqual(result["requests"], 0)

    def test_the_command_line_refresh_descriptions_asks_both_descriptions_and_no_tile(self):
        self.build(FakeSource(), zooms=(5,))
        source = FakeSource()
        with mock.patch.object(T, "_http_get", source), contextlib.redirect_stdout(io.StringIO()):
            code = T.main(["build", "--store", str(self.store), "--cache", str(self.cache), "--zooms", "5",
                           "--keep-other-zooms", "--procs", "2", "--refresh-descriptions"])
        self.assertEqual(code, 0)
        self.assertEqual(source.count("meta", ""), 1)
        self.assertEqual(source.count("landmeta", ""), 1)
        self.assertEqual([c for c in source.calls if c[0] in ("h", "l")], [])

    def test_after_a_build_only_the_current_months_stay_in_the_cache(self):
        old_shading = self.cache / "shading" / "2026-08" / "8" / "50" / "90.png"
        old_shading.parent.mkdir(parents=True)
        old_shading.write_bytes(SHADING_PNG)
        old_land = self.cache / "land_cover" / "2022-01" / "5" / "5" / "10.tif"
        old_land.parent.mkdir(parents=True)
        old_land.write_bytes(LAND_TIFF)
        self.build(FakeSource())
        self.assertFalse((self.cache / "shading" / "2026-08").exists())
        self.assertFalse((self.cache / "land_cover" / "2022-01").exists())
        self.assertTrue((self.cache / "shading" / "2026-09").is_dir())
        self.assertTrue((self.cache / "land_cover" / "2023-06").is_dir())

    def test_a_build_that_writes_no_blocks_keeps_the_other_months(self):
        old_shading = self.cache / "shading" / "2026-08" / "8" / "50" / "90.png"
        old_shading.parent.mkdir(parents=True)
        old_shading.write_bytes(SHADING_PNG)
        result = self.build(FakeSource(meta_status=500, land_meta_status=500))
        self.assertEqual(result["state"], "unavailable")
        self.assertTrue(old_shading.is_file())

    def test_zoom_text_is_a_range_or_a_list_and_bad_zooms_are_refused(self):
        self.assertEqual(T._parse_zooms("5-10"), (5, 6, 7, 8, 9, 10))
        self.assertEqual(T._parse_zooms("8"), (8,))
        self.assertEqual(T._parse_zooms("5,7"), (5, 7))
        with self.assertRaises(T.TerrainError):
            T._parse_zooms("15")

    def test_a_deadline_already_past_marks_every_tile_missing_with_its_reason(self):
        source = FakeSource()
        result = T.build(self.store, self.cache, zooms=(5,), get=source, sleep=NOOP_SLEEP, procs=2,
                         deadline_at=time.monotonic() - 1.0)
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual([c for c in source.calls if c[0] in ("h", "l")], [])
        self.assertIn("deadline", self.index_block()["detail"])

    def test_the_site_reads_the_map_block_from_the_store_index_alone(self):
        self.build(FakeSource())
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        data = T.map_data(index)
        self.assertEqual(data["state"], "loaded")
        self.assertEqual(data["zooms"], [5])
        self.assertEqual(data["layers"]["h"]["template"], "hail/base/h/{z}/{x}/{y}.jpg")
        self.assertEqual(data["layers"]["l"]["missing"], [])
        self.assertIn("Relief: 3DEP data courtesy of the U.S. Geological Survey", T.describe(index)["shading_source"])

    def test_the_sample_store_passes_the_strict_manifest_check_after_a_build(self):
        sample = Path(self.root / "sample")
        sample.mkdir()
        hail.fixture_store(sample)
        T.build(sample, self.cache, zooms=(5,), get=FakeSource(), sleep=NOOP_SLEEP, procs=2)
        manifest = hail.check_manifest(sample)
        self.assertTrue(any(k.startswith("hail/base/h/5/") for k in manifest["files"]))
        self.assertTrue(T.verify(sample, offline=True)["ok"])


@unittest.skipUnless(HAVE_IMAGES, "needs Pillow and numpy")
class SharedBaseIndexTests(unittest.TestCase):
    """B6 P1-F1 (P3-R8 applied to the terrain reader): hail/base/index.json is one document that the B6 parts
    share. A new document starts with the shared format key, and a write keeps every key it does not own. A document
    with no format key, another format key, or no JSON is refused with a TerrainError that names the file and the
    format found. A refused write changes nothing: the document is kept byte for byte, no request is made, and no file
    of the store changes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = empty_store(self.root / "store")
        self.cache = self.root / "cache"
        self.base = self.store / "hail" / "base" / "index.json"

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, source=None):
        return T.build(self.store, self.cache, zooms=(5,), only=T.LAYERS, get=source or FakeSource(), sleep=NOOP_SLEEP,
                       procs=2)

    def read(self) -> dict:
        return json.loads(self.base.read_text(encoding="utf-8"))

    def write_base(self, text: bytes) -> None:
        self.base.parent.mkdir(parents=True, exist_ok=True)
        self.base.write_bytes(text)

    def snapshot(self) -> dict:
        """Every file of the store with its hash: a refused write must leave this unchanged."""
        return {p.relative_to(self.store).as_posix(): sha(p) for p in self.store.rglob("*") if p.is_file()}

    def other_parts_document(self) -> dict:
        """The document as the other parts write it: the shared format key, their own keys and their block."""
        return {"f": T.BASE_INDEX_FORMAT,
                "landmarks": {"state": "loaded", "counts": {"points": 3}},
                "vector": {"state": "loaded", "as_of": "2026-10-25", "problem": None}}

    def test_a_new_document_starts_with_the_shared_format_key(self):
        self.assertFalse(self.base.exists())
        self.assertEqual(T._read_base_index(self.store), {"f": "hail-base-index-v1"})
        self.assertEqual(T.BASE_INDEX_FORMAT, "hail-base-index-v1")
        self.build()
        doc = self.read()
        self.assertEqual(doc["f"], "hail-base-index-v1")
        self.assertEqual(sorted(doc), ["f", "terrain"])

    def test_a_readable_document_with_the_shared_key_is_used_and_the_other_parts_keys_survive_a_write(self):
        document = self.other_parts_document()
        self.write_base(json.dumps(document, indent=1).encode("utf-8"))
        self.assertEqual(T._read_base_index(self.store), document)
        hail_index = self.store / "hail" / "index.json"
        index = json.loads(hail_index.read_text(encoding="utf-8"))
        index["base"] = {"format": "hail-base-v1", "vector": {"state": "loaded"}}
        hail_index.write_text(json.dumps(index), encoding="utf-8")
        self.build()
        doc = self.read()
        self.assertEqual((doc["landmarks"], doc["vector"]), (document["landmarks"], document["vector"]))
        self.assertEqual(doc["terrain"]["state"], "loaded")
        mirror = json.loads(hail_index.read_text(encoding="utf-8"))["base"]
        self.assertEqual(mirror["vector"], {"state": "loaded"})          # the other parts' mirror blocks are kept too
        self.assertEqual(mirror["terrain"]["state"], "loaded")
        self.assertTrue(T.verify(self.store, offline=True)["ok"])

    def test_the_other_parts_blocks_survive_the_unavailable_write_too(self):
        document = self.other_parts_document()
        self.write_base(json.dumps(document, indent=1).encode("utf-8"))
        T.mark_unavailable(self.store, "the job's download failed")
        doc = self.read()
        self.assertEqual((doc["landmarks"], doc["vector"]), (document["landmarks"], document["vector"]))
        self.assertEqual(doc["terrain"]["state"], "unavailable")

    def test_a_document_of_another_format_is_refused_and_kept_byte_for_byte(self):
        cases = (
            ('{"f": "some-other-format", "landmarks": {"state": "loaded"}}', "its format key: 'some-other-format'"),
            ('{"format": "hail-base-index-v1", "vector": {"state": "loaded"}}', "its format key: no format key"),
            ('{"landmarks": {"state": "loaded"}}', "its format key: no format key"),
            ("not json at all {", "is not JSON"),
            ('["a", "list"]', "is not a JSON object"),
        )
        for text, found in cases:
            with self.subTest(text=text):
                raw = text.encode("utf-8")
                self.write_base(raw)
                before = self.snapshot()
                source = FakeSource()
                with self.assertRaises(T.TerrainError) as ctx:
                    self.build(source)
                message = str(ctx.exception)
                self.assertIn("hail/base/index.json", message)
                self.assertIn(found, message)
                self.assertEqual(source.calls, [])                       # no request is made
                self.assertEqual(self.base.read_bytes(), raw)            # the document is kept byte for byte
                self.assertEqual(self.snapshot(), before)                # no file of the store changes

    def test_a_refused_document_stops_the_unavailable_write_before_any_file_is_removed(self):
        self.build()
        self.assertTrue((self.store / "hail" / "base" / "h").is_dir())
        self.write_base(b'{"f": "some-other-format"}')
        before = self.snapshot()
        with self.assertRaises(T.TerrainError) as ctx:
            T.mark_unavailable(self.store, "the job's download failed")
        self.assertIn("'some-other-format'", str(ctx.exception))
        self.assertEqual(self.snapshot(), before)
        self.assertTrue((self.store / "hail" / "base" / "h").is_dir())
        self.assertTrue((self.store / "hail" / "base" / "l").is_dir())

    def test_a_base_index_that_cannot_be_read_is_refused_and_nothing_is_written(self):
        self.base.mkdir(parents=True)                                    # a folder where the document should be
        source = FakeSource()
        before = self.snapshot()
        with self.assertRaises(T.TerrainError) as ctx:
            self.build(source)
        self.assertIn("hail/base/index.json cannot be read", str(ctx.exception))
        self.assertEqual(source.calls, [])
        self.assertEqual(self.snapshot(), before)

    def test_the_command_line_stops_with_the_reason_and_changes_nothing(self):
        self.write_base(b'{"f": "some-other-format"}')
        before = self.snapshot()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = T.main(["build", "--store", str(self.store), "--cache", str(self.cache), "--offline"])
        self.assertEqual(code, 2)
        self.assertIn("error: hail/base/index.json is not a hail-base-index-v1 document", err.getvalue())
        self.assertIn("'some-other-format'", err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = T.main(["unavailable", "--store", str(self.store), "--reason", "the test failed"])
        self.assertEqual(code, 2)
        self.assertIn("error: hail/base/index.json", err.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_verify_reports_a_refused_document_as_a_failed_check_and_exits_1(self):
        self.build()
        self.write_base(b'{"f": "some-other-format"}')
        result = T.verify(self.store, offline=True)
        self.assertFalse(result["ok"])
        failed = [c for c in result["checks"] if not c["pass"]]
        self.assertEqual([c["check"] for c in failed],
                         ["hail/base/index.json is the shared format (hail-base-index-v1)"])
        self.assertIn("'some-other-format'", failed[0]["detail"])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = T.main(["verify", "--store", str(self.store), "--offline"])
        self.assertEqual(code, 1)
        self.assertIn("is the shared format", out.getvalue())


@unittest.skipUnless(HAVE_IMAGES, "needs Pillow and numpy")
class VerifyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = empty_store(self.root / "store")
        self.cache = self.root / "cache"
        T.build(self.store, self.cache, zooms=(5,), get=FakeSource(), sleep=NOOP_SLEEP, procs=2)

    def tearDown(self):
        self._tmp.cleanup()

    def failed(self, result) -> list[str]:
        return [c["check"] for c in result["checks"] if not c["pass"]]

    def test_a_clean_build_verifies_offline_and_on_a_re_fetch(self):
        self.assertTrue(T.verify(self.store, offline=True)["ok"])
        result = T.verify(self.store, get=FakeSource(), sleep=NOOP_SLEEP, sample=4)
        self.assertTrue(result["ok"], self.failed(result))
        self.assertEqual(result["refetch"]["match"], 4)

    def test_a_tile_with_the_wrong_image_fails(self):
        target = self.store / "hail" / "base" / "h" / "5" / "5" / "10.jpg"
        buf = io.BytesIO()
        Image.new("RGB", (256, 256), (10, 20, 30)).save(buf, format="PNG")
        target.write_bytes(buf.getvalue())
        result = T.verify(self.store, offline=True)
        self.assertFalse(result["ok"])
        self.assertIn("h: every file has the pixels and the mode of its layer", self.failed(result))

    def test_a_stray_file_in_the_layer_fails(self):
        stray = self.store / "hail" / "base" / "l" / "5" / "0" / "0.png"
        stray.parent.mkdir(parents=True)
        stray.write_bytes(T.tint_png(LAND_TIFF))
        result = T.verify(self.store, offline=True)
        self.assertFalse(result["ok"])
        self.assertIn("l: files and missing tiles together are the whole set", self.failed(result))

    def test_a_manifest_entry_that_does_not_match_fails(self):
        path = self.store / "hail" / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        victim = sorted(k for k in manifest["files"] if k.startswith("hail/base/h/"))[0]
        manifest["files"][victim]["sha256"] = "0" * 64
        path.write_text(json.dumps(manifest), encoding="utf-8")
        result = T.verify(self.store, offline=True)
        self.assertIn("manifest lists each base file with its bytes and SHA-256", self.failed(result))

    def test_a_re_fetch_that_differs_is_reported(self):
        inverted = np.asarray(Image.open(io.BytesIO(SHADING_PNG)))
        buf = io.BytesIO()
        Image.fromarray(255 - inverted, mode="L").save(buf, format="PNG")
        result = T.verify(self.store, get=FakeSource(shading=buf.getvalue()), sleep=NOOP_SLEEP, sample=8)
        self.assertGreaterEqual(result["refetch"]["mismatch"], 1)
        self.assertIn("a seeded sample of tiles re-fetched matches the stored files", self.failed(result))

    def test_a_re_fetch_of_a_truncated_answer_is_a_failed_re_fetch_and_verify_does_not_raise(self):
        truncated = LAND_TIFF[: len(LAND_TIFF) // 2]
        result = T.verify(self.store, get=FakeSource(bodies={("l", "5/5/10"): truncated}), sleep=NOOP_SLEEP, sample=8)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["refetch"]["failed"]), 1)
        self.assertIn("not a readable image", result["refetch"]["failed"][0]["reason"])
        self.assertIn("a seeded sample of tiles re-fetched matches the stored files", self.failed(result))

    def test_a_land_cover_palette_match_with_other_bytes_is_reported_and_counted_as_a_failed_match(self):
        rel = "hail/base/l/5/5/10.png"
        target = self.store / rel
        with Image.open(target) as im:
            im.load()
            pixels = np.asarray(im).copy()
            palette = im.getpalette()
        image = Image.fromarray(pixels, mode="P")
        image.putpalette(palette)
        buf = io.BytesIO()
        image.save(buf, format="PNG", transparency=0, compress_level=0)     # the same pixels and palette, other bytes
        different = buf.getvalue()
        self.assertNotEqual(different, target.read_bytes())
        target.write_bytes(different)
        manifest_path = self.store / "hail" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][rel] = {"bytes": len(different), "sha256": hashlib.sha256(different).hexdigest()}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")   # only the re-fetch check should fail
        result = T.verify(self.store, get=FakeSource(), sleep=NOOP_SLEEP, sample=8)
        self.assertEqual(result["refetch"]["palette_match_bytes_differ"], 1)
        self.assertEqual((result["refetch"]["match"], result["refetch"]["mismatch"]), (7, 0))
        check = [c for c in result["checks"] if c["check"] == "a seeded sample of tiles re-fetched matches the stored files"]
        self.assertEqual(len(check), 1)
        self.assertFalse(check[0]["pass"])
        self.assertIn("1 palette match, bytes differ", check[0]["detail"])
        self.assertIn("7 byte for byte", check[0]["detail"])

    def test_the_budget_line_holds_for_a_small_build(self):
        result = T.verify(self.store, offline=True)
        budget = [c for c in result["checks"] if c["check"].startswith("zooms 5 to 10")]
        self.assertEqual(len(budget), 1)
        self.assertTrue(budget[0]["pass"])


# ---------------------------------------------------------------- the words and the copy

class WordTests(unittest.TestCase):
    SAMPLE = {"Part": "Terrain shading", "part": "terrain shading", "count": 3, "total": 881, "date": "2026-09-28"}

    def test_every_sentence_passes_the_site_word_scan(self):
        for name, template in T.WORDS.items():
            text = template.format(**self.SAMPLE) if "{" in template else template
            for pattern in W.EXEMPT:
                text = pattern.sub("", text)
            self.assertIsNone(W.FORBIDDEN.search(text), f"{name}: {text!r}")
            self.assertIsNone(W.NO_HAIL.search(text), name)

    def test_the_layer_sentences_name_their_layer(self):
        for layer, words in T.LAYER_WORDS.items():
            sentence = T.WORDS["part_partial"].format(count=2, total=881, **words)
            self.assertIn(words["part"], sentence)
            self.assertTrue(sentence.endswith("This is not an all-clear."))

    def test_the_credit_lines_carry_the_sources_credit_and_terms(self):
        self.assertEqual(T.SOURCES["shading"]["credit"], "Relief: 3DEP data courtesy of the U.S. Geological Survey")
        self.assertEqual(T.SOURCES["land_cover"]["credit"],
                         "Land cover: National Land Cover Database 2021, U.S. Geological Survey and the "
                         "Multi-Resolution Land Characteristics Consortium (public domain)")
        terms = T.SOURCES["land_cover"]["terms"]
        self.assertIn("10.5066/P9JZ7AO3", terms)                             # the NLCD 2021 Products record's DOI
        self.assertIn("use constraints None", terms)                         # the record's use constraints
        self.assertNotIn("CC0", terms)                                       # the CC0 statement is on another product
        note = " ".join(T.__doc__.split())                                   # the terms note, whitespace folded
        self.assertIn('"complete, current, and consistent public domain information"', note)
        self.assertIn("10.5066/P9JZ7AO3", note)
        self.assertIn("record (doi 10.5066/P94UXNTS), a different product", note)
        self.assertIn("so it is not claimed for NLCD 2021", note)
        self.assertIn(T.SOURCES["land_cover"]["credit"], T.WORDS["land_source"])
        shading = T.WORDS["shading_source"].format(date="2026-09-28")
        self.assertIn("Relief: 3DEP data courtesy of the U.S. Geological Survey", shading)
        self.assertIn("data as of 2026-09-28", shading)
        self.assertIn("copyright_fallback", T.SOURCES["shading"])

    def test_the_layer_sentences_carry_data_unavailable_beside_the_d20_wording(self):
        words = T.LAYER_WORDS["l"]
        for name in ("part_unavailable", "part_partial", "unavailable"):
            template = T.WORDS[name]
            text = template.format(count=2, total=881, **words) if "{" in template else template
            self.assertTrue(text.startswith("Data unavailable. "), name)
            self.assertIn("could not be loaded in this update", text, name)
            self.assertIn("that is not the same as no", text, name)
            self.assertTrue(text.endswith("This is not an all-clear."), name)

    def test_no_em_dash_and_no_product_or_vendor_names_in_the_module_or_its_tests(self):
        names = "|".join(["Cla" + "ude", "Anthro" + "pic", "Open" + "AI", "Chat" + "GPT", "Hai" + "ku", "Ap" + "ple",
                          "Zil" + "low", "Es" + "ri"])
        dash = "\u2014"
        for path in (Path(T.__file__), Path(__file__)):
            self.assertNotIn(dash, path.read_text(encoding="utf-8"), path.name)
        module_text = Path(T.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\b(?:" + names + r")\b", module_text))

    def test_a_source_that_is_not_in_use_is_not_credited(self):
        index = {"base": {"format": "hail-base-v1", "terrain": {
            "state": "partial", "as_of": {"shading_date": None, "land_cover": "2023-06"}, "zooms": [5],
            "layers": {"h": {"state": "unavailable", "path": "hail/base/h/{z}/{x}/{y}.jpg", "missing": [], "files": 0},
                       "l": {"state": "loaded", "path": "hail/base/l/{z}/{x}/{y}.png", "missing": [], "files": 4}}}}}
        data = T.map_data(index)
        self.assertEqual(data["credits"]["shading"], "Terrain shading: Data unavailable in this update.")
        self.assertEqual(data["credits"]["land_cover"], T.WORDS["land_source"])
        self.assertEqual(T.describe(index)["shading_source"], "Terrain shading: Data unavailable in this update.")
        self.assertNotIn("unknown", json.dumps(data))
        landless = {"base": {"format": "hail-base-v1", "terrain": {
            "state": "partial", "as_of": {"shading_date": "2026-09-28", "land_cover": "2023-06"}, "zooms": [5],
            "layers": {"h": {"state": "loaded", "path": "hail/base/h/{z}/{x}/{y}.jpg", "missing": [], "files": 4},
                       "l": {"state": "unavailable", "path": "hail/base/l/{z}/{x}/{y}.png", "missing": [], "files": 0}}}}}
        landless_data = T.map_data(landless)
        self.assertEqual(landless_data["credits"]["land_cover"], "Land cover tint: Data unavailable in this update.")
        self.assertIn("data as of 2026-09-28", landless_data["credits"]["shading"])

    def test_map_data_and_describe_read_the_block(self):
        unavailable = {"base": {"format": "hail-base-v1", "terrain": {"state": "unavailable",
                                                                    "problem": T.WORDS["unavailable"]}}}
        self.assertEqual(T.map_data(unavailable)["state"], "unavailable")
        self.assertTrue(T.describe(unavailable)["unavailable"])
        loaded = {"base": {"format": "hail-base-v1", "terrain": {
            "state": "loaded", "zooms": [5], "as_of": {"shading_date": "2026-09-28", "land_cover": "2023-06"},
            "layers": {"h": {"state": "loaded", "path": "hail/base/h/{z}/{x}/{y}.jpg", "missing": [], "files": 4},
                       "l": {"state": "loaded", "path": "hail/base/l/{z}/{x}/{y}.png", "missing": ["5/5/11"], "files": 3}},
        }}}
        data = T.map_data(loaded)
        self.assertEqual(data["zooms"], [5])
        self.assertEqual(data["layers"]["l"]["missing"], ["5/5/11"])
        self.assertEqual(data["layers"]["h"]["template"], "hail/base/h/{z}/{x}/{y}.jpg")
        self.assertIn("data as of 2026-09-28", data["credits"]["shading"])
        about = T.describe(loaded)
        self.assertFalse(about["unavailable"])
        self.assertIn("Relief: 3DEP data courtesy of the U.S. Geological Survey", about["shading_source"])


class LandDescriptionTests(unittest.TestCase):
    """The land cover layer's month comes from its WCS description (a live answer, kept in the fixtures)."""

    def test_the_layer_month_comes_from_its_date_keyword(self):
        self.assertEqual(T._land_as_of(LAND_DESCRIBE), "2023-06")

    def test_a_renamed_layer_is_refused_by_name(self):
        renamed = LAND_DESCRIBE.replace(b"NLCD_2021_Land_Cover_L48", b"NLCD_2031_Land_Cover_L48")
        with self.assertRaises(T.TerrainError) as raised:
            T._land_as_of(renamed)
        self.assertIn("is not in the service", str(raised.exception))
        self.assertIn("name may have changed", str(raised.exception))

    def test_a_service_exception_names_no_layer_and_is_refused(self):
        answer = (b'<?xml version="1.0" encoding="UTF-8"?><ServiceExceptionReport version="1.2.0"><ServiceException '
                  b'code="InvalidParameterValue" locator="coverage">Could not find coverage '
                  b"'mrlc_display:NLCD_2099_Nope'</ServiceException></ServiceExceptionReport>")
        with self.assertRaises(T.TerrainError) as raised:
            T._land_as_of(answer)
        self.assertIn("is not in the service", str(raised.exception))

    def test_a_layer_without_a_date_keyword_and_a_page_that_is_not_xml_are_refused(self):
        undated = LAND_DESCRIBE.replace(b"_20230630_3857", b"_3857")
        with self.assertRaises(T.TerrainError) as raised:
            T._land_as_of(undated)
        self.assertIn("no date keyword", str(raised.exception))
        with self.assertRaises(T.TerrainError) as raised:
            T._land_as_of(b"<html>Bad gateway")
        self.assertIn("not XML", str(raised.exception))


# ---------------------------------------------------------------- the monthly flags (no images needed)

class MonthlyFlagTests(unittest.TestCase):
    # The monthly job's flags: --refresh-descriptions is its own flag, apart from --refresh (D128(f)), and the module docstring
    # names the flags and the figures the monthly steps use (D128(f), D132(e)). The workflow's own pins are in
    # tests/test_hail_workflow.py.

    def test_the_command_line_keeps_refresh_descriptions_apart_from_refresh(self):
        only_descriptions = T.build_parser().parse_args(["build", "--store", "s", "--refresh-descriptions"])
        self.assertTrue(only_descriptions.refresh_descriptions)
        self.assertFalse(only_descriptions.refresh)
        everything = T.build_parser().parse_args(["build", "--store", "s", "--refresh"])
        self.assertTrue(everything.refresh)
        self.assertFalse(everything.refresh_descriptions)

    def test_the_module_docstring_names_the_monthly_flags_and_their_figures(self):
        for text in ("--refresh-descriptions", "--timeout 60", "25-minute cap", "1500 seconds", "120 seconds", "900 seconds",
                     "16 minutes"):
            with self.subTest(text=text):
                self.assertIn(text, T.__doc__)


if __name__ == "__main__":
    unittest.main()
