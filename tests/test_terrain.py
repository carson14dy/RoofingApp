"""Terrain shading and land cover tiles (B6 product P1, website/terrain.py): the tile maths, the outline and the tile set
(positive-area overlap, pinned counts), the answer checks and the drawing (the grey JPEG at quality 80, the five-class
palette with index 0 transparent, the no-data value written as white), the tries (a 5xx, 429 or network error is tried
three times; a client error is final; a body that is not the image is tried again), the cache (a cached copy is used
before any request; a refresh that fails serves it with its reason; a deadline stops requests), the build (both layers,
the index blocks, the manifest entries, a missing tile, a failed layer, a failed service description, the second run
from the cache, determinism, one layer at a time, the unavailable command), verify (a wrong image, a stray file, a
manifest mismatch, a seeded re-fetch that matches and one that does not), the sample store's strict manifest check, and
the words. Offline: the sources are fakes built from two small fixtures (tests/fixtures/terrain, about 100 KB), and the
sleep between tries is a no-op. Tests that need Pillow or numpy skip when the package is absent."""
from __future__ import annotations

import hashlib
import io
import json
import math
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
    that layer's tiles; meta_status is the status of the service description. calls records each request as
    (kind, key) so a test can count the tries of one tile."""

    def __init__(self, *, fail=None, meta_status=200, shading=SHADING_PNG, land=LAND_TIFF):
        self.fail = dict(fail or {})
        self.meta_status = meta_status
        self.shading = shading
        self.land = land
        self.calls: list[tuple[str, str]] = []

    def __call__(self, url, params, timeout=None):
        if url == T.SHADING_META_URL:
            self.calls.append(("meta", ""))
            return self.meta_status, META if self.meta_status == 200 else b"", ""
        if url == T.SHADING_URL:
            key = key_from_3857(params["bbox"])
            self.calls.append(("h", key))
            status = self.fail.get(("h", key), self.fail.get(("h", "*")))
            return (status, b"", "") if status else (200, self.shading, "")
        if url == T.LAND_URL:
            key = key_from_3857(params["bbox"])
            self.calls.append(("l", key))
            status = self.fail.get(("l", key), self.fail.get(("l", "*")))
            return (status, b"", "") if status else (200, self.land, "")
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

    def test_the_no_data_grey_value_is_written_as_white(self):
        grid = np.full((256, 256), 100, np.uint8)
        grid[:64, :] = 253                                    # the service's no-data grey value (its transparency)
        buf = io.BytesIO()
        im = Image.fromarray(grid, mode="L")
        im.save(buf, format="PNG", transparency=253)
        out = np.asarray(Image.open(io.BytesIO(T.shading_jpeg(buf.getvalue()))).convert("L"))
        self.assertGreaterEqual(float(out[:60, :].mean()), 250.0)
        self.assertLess(abs(float(out[100:, :].mean()) - 100.0), 3.0)

    def test_the_tint_maps_each_code_to_its_class_and_index_0_is_transparent(self):
        row = [11, 41, 52, 71, 21, 82, 90, 0]                 # water, forest, shrub, grass, developed, crop, wetland, none
        codes = np.tile(np.array(row, np.uint8), (256, 32))
        palette = Image.fromarray(codes, mode="P")
        palette.putpalette([0, 0, 0] * 256)
        buf = io.BytesIO()
        palette.save(buf, format="TIFF")
        out = Image.open(io.BytesIO(T.tint_png(buf.getvalue())))
        self.assertEqual((out.format, out.mode, out.size), ("PNG", "P", (256, 256)))
        self.assertEqual(out.info.get("transparency"), 0)
        indices = np.asarray(out)[0, :8].tolist()
        self.assertEqual(indices, [5, 1, 2, 2, 3, 4, 0, 0])

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
        self.assertIn(0, values)                              # the fixture has transparent codes (wetland, bare)
        self.assertEqual(T.tint_png(LAND_TIFF), T.tint_png(LAND_TIFF))

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
        self.assertEqual(raised.exception.tries, 0)

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
        self.assertEqual(block["as_of"]["land_cover"], T.LAND_AS_OF)
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
        self.assertEqual(block["problem"], "Terrain shading could not be loaded in this update for 1 of 4 tiles; "
                                           "that is not the same as no terrain shading. This is not an all-clear.")
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
        self.assertEqual(block["problem"], "The land cover tint could not be loaded in this update; that is not the same "
                                           "as no land cover tint. This is not an all-clear.")
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

    def test_the_second_run_reads_the_cache_and_writes_the_same_bytes(self):
        self.build(FakeSource())
        first = self.tile_hashes()
        second_source = FakeSource()
        self.build(second_source)
        self.assertEqual([c for c in second_source.calls if c[0] in ("h", "l", "meta")], [])
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

    def test_the_command_line_builds_and_marks_unavailable(self):
        import contextlib
        with mock.patch.object(T, "_http_get", FakeSource()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(T.main(["build", "--store", str(self.store), "--cache", str(self.cache),
                                     "--zooms", "5", "--procs", "2"]), 0)
        self.assertEqual(self.index_block()["state"], "loaded")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(T.main(["unavailable", "--store", str(self.store), "--reason", "the job stopped"]), 0)
        self.assertEqual(self.index_block()["state"], "unavailable")

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
        self.assertIn("3DEP data courtesy of the U.S. Geological Survey.", T.describe(index)["shading_source"])

    def test_the_sample_store_passes_the_strict_manifest_check_after_a_build(self):
        sample = Path(self.root / "sample")
        sample.mkdir()
        hail.fixture_store(sample)
        T.build(sample, self.cache, zooms=(5,), get=FakeSource(), sleep=NOOP_SLEEP, procs=2)
        manifest = hail.check_manifest(sample)
        self.assertTrue(any(k.startswith("hail/base/h/5/") for k in manifest["files"]))
        self.assertTrue(T.verify(sample, offline=True)["ok"])


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
        self.assertEqual(T.SOURCES["shading"]["credit"], "3DEP data courtesy of the U.S. Geological Survey.")
        self.assertIn("Public domain information", T.WORDS["land_source"])
        self.assertIn("data as of 2026-09-28", T.WORDS["shading_source"].format(date="2026-09-28"))

    def test_no_em_dash_and_no_product_or_vendor_names_in_the_module_or_its_tests(self):
        names = "|".join(["Cla" + "ude", "Anthro" + "pic", "Open" + "AI", "Chat" + "GPT", "Hai" + "ku", "Ap" + "ple",
                          "Zil" + "low", "Es" + "ri"])
        dash = "\u2014"
        for path in (Path(T.__file__), Path(__file__)):
            self.assertNotIn(dash, path.read_text(encoding="utf-8"), path.name)
        module_text = Path(T.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\b(?:" + names + r")\b", module_text))

    def test_map_data_and_describe_read_the_block(self):
        unavailable = {"base": {"format": "hail-base-v1", "terrain": {"state": "unavailable",
                                                                    "problem": T.WORDS["unavailable"]}}}
        self.assertEqual(T.map_data(unavailable)["state"], "unavailable")
        self.assertTrue(T.describe(unavailable)["unavailable"])
        loaded = {"base": {"format": "hail-base-v1", "terrain": {
            "state": "loaded", "zooms": [5], "as_of": {"shading_date": "2026-09-28", "land_cover": T.LAND_AS_OF},
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
        self.assertIn("3DEP data courtesy of the U.S. Geological Survey.", about["shading_source"])


if __name__ == "__main__":
    unittest.main()
