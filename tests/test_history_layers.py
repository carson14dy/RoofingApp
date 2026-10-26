"""Five-year pictures, zone counts, recent radar cells and zone outlines (B6 product P4, website/history_layers.py).

Offline, on a small fixture store (tests/fixtures/history_layers: one radar shard, one climate tile, five zone product files,
the polygon rows and one tile's join file, all cut from the adopted store) and on a synthetic zone file of the 83 current
zones. A build runs in a temporary copy, so the fixtures never change. The tests need numpy (the pictures and the arrays) and
Pillow (the PNG files); without either, the test that needs it is skipped. Checked here: the class words and the bands; the
picture cells and climate pixels (every pixel against its own cell, and the climate column alignment); the PNG palette and
transparency; the radar window (1 inch days, the largest estimate, the recent 30 days); the zone counts (the window, the
switch to the removed zones, the cover bits, the missing files and the unloaded parts); the outline simplification (150 m,
closed rings, five decimals) and the 83-zone check; a build (its manifest with hail.check_manifest, its determinism, the
stale sentence, a missing radar shard, the unavailable command and verify); and the words against the forbidden list.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from website import hail
from website import history_layers as H

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures" / "history_layers"
TILE = "r0081_c0160"

sys.path.insert(0, str(ROOT))
import words_rules as W  # noqa: E402  (the one forbidden list; tests/ is on sys.path under discover)

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:                       # pragma: no cover - the job installs numpy
    np = None
    HAVE_NUMPY = False
try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:                       # pragma: no cover
    HAVE_PIL = False

needs_numpy = unittest.skipUnless(HAVE_NUMPY, "numpy is not installed")
needs_pil = unittest.skipUnless(HAVE_NUMPY and HAVE_PIL, "numpy or Pillow is not installed")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture_index() -> dict:
    return json.loads((FIXTURE / "hail" / "index.json").read_text(encoding="utf-8"))


def make_store(tmp: Path) -> Path:
    """A copy of the fixture store with the zone files every public zone needs, and a manifest that lists every file."""
    store = tmp / "store"
    shutil.copytree(FIXTURE, store)
    index = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))
    names = dict(index["joins"]["zone_names"])
    for code in sorted(set(index["joins"]["zone_list"]) | set(index["joins"]["zone_list_before"])):
        path = store / "hail" / "z" / f"{code}.json"
        if not path.exists():
            path.write_text(json.dumps({"f": "hail-zone-v1", "zone": code, "name": names.get(code, code),
                                        "events": [], "records": []}), encoding="utf-8")
    write_manifest(store)
    return store


def write_manifest(store: Path) -> None:
    files = {}
    for path in sorted((store / "hail").rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            data = path.read_bytes()
            files[path.relative_to(store).as_posix()] = {"bytes": len(data), "sha256": _sha(data)}
    (store / "hail" / "manifest.json").write_text(
        json.dumps({"format": "hail-manifest-v1", "as_of": "2026-10-16", "counts": {}, "files": files}), encoding="utf-8")


def ugcs_geojson(path: Path, codes: list[str], extra_ring: bool = False) -> Path:
    """An IEM-style zone file: one small square per zone (and, when asked, one circle of 400 points to test the
    simplification), with a county feature that must be ignored."""
    feats = []
    for n, code in enumerate(codes):
        lon0 = -116.0 + (n % 10) * 0.2
        lat0 = 45.0 + (n // 10) * 0.2
        ring = [[lon0, lat0], [lon0 + 0.1, lat0], [lon0 + 0.1, lat0 + 0.1], [lon0, lat0 + 0.1], [lon0, lat0]]
        feats.append({"type": "Feature", "properties": {"ugc": code, "name": f"Zone {code}", "state": "MT", "wfo": "TFX"},
                      "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]}})
    if extra_ring:
        cx, cy, r = -110.0, 47.0, 0.2
        circle = [[cx + r * math.cos(2 * math.pi * k / 400), cy + r * math.sin(2 * math.pi * k / 400)] for k in range(400)]
        circle.append(circle[0])
        feats[0]["geometry"] = {"type": "Polygon", "coordinates": [circle]}
    feats.append({"type": "Feature", "properties": {"ugc": "MTC001", "name": "Beaverhead", "state": "MT", "wfo": "TFX"},
                  "geometry": {"type": "Polygon", "coordinates": [[[-113.0, 45.0], [-112.9, 45.0], [-112.9, 45.1],
                                                                     [-113.0, 45.0]]]}})
    doc = {"type": "FeatureCollection", "name": "test", "features": feats}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def fixture_zone_file(tmp: Path, extra_ring: bool = False) -> Path:
    codes = fixture_index()["joins"]["zone_list"]
    return ugcs_geojson(tmp / "ugcs.geojson", codes, extra_ring=extra_ring)


class ClassWords(unittest.TestCase):
    """The class tables: four hail classes, six heat bands of 25 days, and the words that name them."""

    def test_hail_classes_name_days(self):
        words = [c["word"] for c in H.HAIL_CLASSES]
        self.assertEqual(words, ["1 day", "2 days", "3 to 5 days", "6 days or more"])
        self.assertEqual([(c["min"], c["max"]) for c in H.HAIL_CLASSES], [(1, 1), (2, 2), (3, 5), (6, None)])

    def test_heat_bands_are_25_days_wide(self):
        self.assertEqual([(c["min"], c["max"]) for c in H.HEAT_CLASSES],
                         [(0, 24), (25, 49), (50, 74), (75, 99), (100, 124), (125, None)])

    def test_one_inch_is_the_store_figure(self):
        self.assertEqual(H.HAIL_ONE_INCH, 254)
        self.assertEqual(H.HAIL_ONE_INCH, hail.TENTHS_PER_INCH)


@needs_numpy
class Pictures(unittest.TestCase):
    """The picture arrays: every pixel takes the class of the cell that holds its centre, and the climate pixels line up with
    the climate columns."""

    def test_every_hail_pixel_takes_its_cells_class(self):
        from website import gridded
        rng = np.random.default_rng(3)
        ge1 = np.zeros((hail.ROWS, hail.COLS), dtype=np.int16)
        rows = rng.integers(450, 1200, 4000)
        cols = rng.integers(1150, 2900, 4000)
        ge1[rows, cols] = rng.choice([1, 2, 3, 5, 6, 30], 4000)
        idx, h = H.hail_indices(ge1, H.HAIL_WIDTH)
        lats, lons = gridded.pixel_centers(H.HAIL_WIDTH)
        self.assertEqual(idx.shape, (h, H.HAIL_WIDTH))
        r = np.floor(5500.0 - 100.0 * lats).astype(np.int64)
        c = np.floor(100.0 * lons + 13000.0).astype(np.int64)
        values = ge1[np.ix_(r, c)]
        expect = np.zeros_like(idx)
        expect[values == 1] = 1
        expect[values == 2] = 2
        expect[(values >= 3) & (values <= 5)] = 3
        expect[values >= 6] = 4
        self.assertTrue(np.array_equal(idx, expect))

    def test_hail_picture_is_one_pixel_per_hundredth_of_a_degree(self):
        from website import gridded
        _h, _lats, lons = H._geometry(H.HAIL_WIDTH)
        steps = np.diff(lons)
        self.assertTrue(np.allclose(steps, 0.01, atol=1e-9))
        centres = 100.0 * lons + 13000.0 - 0.5     # a centre sits half a cell inside each cell, so this is whole
        self.assertTrue(np.allclose(centres, np.round(centres), atol=1e-6))
        self.assertEqual(gridded.image_size(H.HAIL_WIDTH)[0], H.HAIL_WIDTH)

    def test_climate_pixel_columns_are_climate_columns(self):
        _h, _lats, lons = H._geometry(H.HEAT_WIDTH)
        j = (lons - H.CLIMATE_LON0) * H.CLIMATE_STEP
        self.assertTrue(np.allclose(j, np.round(j), atol=1e-6))

    def test_a_climate_cell_colours_its_pixels(self):
        val = np.full((H.CLIMATE_ROWS, H.CLIMATE_COLS), -1, dtype=np.int16)
        val[536, 258] = 73
        idx, h = H.heat_indices(val, H.HEAT_WIDTH)
        _h, lats, lons = H._geometry(H.HEAT_WIDTH)
        ii = np.rint((lats - H.CLIMATE_LAT0) * H.CLIMATE_STEP).astype(int)
        jj = np.rint((lons - H.CLIMATE_LON0) * H.CLIMATE_STEP).astype(int)
        hit = np.argwhere((ii[:, None] == 536) & (jj[None, :] == 258))
        self.assertGreaterEqual(len(hit), 1)
        for y, x in hit:
            self.assertEqual(idx[y, x], 3)          # 73 days: the band 50 to 74 is index 3 (band 2 plus one)
        self.assertEqual(int(np.count_nonzero(idx)), int(np.count_nonzero((ii[:, None] == 536) & (jj[None, :] == 258))))

    def test_a_missing_value_is_transparent_not_zero_coloured(self):
        val = np.full((H.CLIMATE_ROWS, H.CLIMATE_COLS), -1, dtype=np.int16)
        val[536, 258] = 0                            # a stored zero is a count: it takes the lowest band
        idx, _h = H.heat_indices(val, H.HEAT_WIDTH)
        self.assertEqual(int(idx.max()), 1)
        self.assertGreater(int(np.count_nonzero(idx == 1)), 0)
        self.assertEqual(int(np.count_nonzero(idx == 0)), idx.size - int(np.count_nonzero(idx == 1)))


@needs_pil
class Png(unittest.TestCase):
    def test_palette_png_with_transparent_index_zero(self):
        from PIL import Image
        idx = np.zeros((5, 7), dtype=np.uint8)
        idx[1, 2] = 2
        idx[3, 4] = 4
        data = H.encode_png(idx, H.HAIL_CLASSES, H.HAIL_ALPHA, 7)
        img = Image.open(__import__("io").BytesIO(data))
        self.assertEqual(img.mode, "P")
        self.assertEqual(img.size, (7, 5))
        palette = img.getpalette()
        self.assertEqual(tuple(palette[3 * 2:3 * 2 + 3]), tuple(int(H.HAIL_CLASSES[1]["colour"][i:i + 2], 16) for i in (1, 3, 5)))
        alpha = img.info["transparency"]
        self.assertEqual(alpha[0], 0)
        self.assertEqual(alpha[2], H.HAIL_ALPHA)
        back = np.array(img)
        self.assertTrue(np.array_equal(back, idx))


@needs_numpy
class Radar(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = make_store(self.tmp)
        self.index = H._read_index(self.store)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_window_days_at_one_inch_per_cell(self):
        scan = H.scan_radar(self.store, self.index)
        self.assertEqual(int(scan.ge1[810, 1606]), 2)     # 2023-06-15 (260) and 2026-10-02 (300); 2020 and 130 excluded
        self.assertEqual(int(scan.ge1[811, 1607]), 5)     # five days at 254 or more inside the window
        self.assertEqual(int(scan.ge1[815, 1609]), 6)     # six days, including 254 exactly
        self.assertEqual(int(scan.ge1[818, 1608]), 1)     # the newest day, 2026-10-16, counts
        self.assertEqual(int(scan.ge1[812, 1603]), 0)     # 200 and 100 only: no day at one inch
        self.assertEqual(int(scan.ge1[814, 1601]), 0)     # its only day is before the window

    def test_largest_estimate_over_the_window(self):
        scan = H.scan_radar(self.store, self.index)
        self.assertEqual(int(scan.top[810, 1606]), 300)   # the 400 of 2020 is before the window
        self.assertEqual(int(scan.top[811, 1607]), 390)
        self.assertEqual(int(scan.top[814, 1601]), 0)     # nothing in the window: no value

    def test_recent_cells_are_the_last_thirty_days(self):
        scan = H.scan_radar(self.store, self.index, recent_first=date(2026, 9, 17), recent_last=date(2026, 10, 16))
        self.assertEqual(sorted(scan.recent), [(810, 1606), (811, 1607), (818, 1608)])
        self.assertEqual(scan.recent[(811, 1607)], [[hail.day_index(date(2026, 9, 30)), 260]])

    def test_a_missing_listed_shard_is_named(self):
        (self.store / "hail" / "t" / f"{TILE}.json").unlink()
        scan = H.scan_radar(self.store, self.index)
        self.assertEqual(scan.missing, [TILE])
        self.assertEqual(scan.tiles, 0)


class ZoneCounts(unittest.TestCase):
    """The six zone measures, from the zone products (hail/z) and the polygon rows (hail/j), over the window."""

    EXPECT = {
        "MTZ001": {"high_wind_warnings": 1, "high_wind_watches": 1, "wind_advisories": 1,
                   "flood_watches": 2, "flood_warnings": 3, "flood_advisories": 1},
        "MTZ002": {"high_wind_warnings": 1, "high_wind_watches": 0, "wind_advisories": 0,
                   "flood_watches": 0, "flood_warnings": 0, "flood_advisories": 1},
        "MTZ047": {"high_wind_warnings": 1, "high_wind_watches": 1, "wind_advisories": 0,
                   "flood_watches": 0, "flood_warnings": 1, "flood_advisories": 0},
        "MTZ060": {"high_wind_warnings": 0, "high_wind_watches": 0, "wind_advisories": 1,
                   "flood_watches": 0, "flood_warnings": 0, "flood_advisories": 1},
        "MTZ301": {"high_wind_warnings": 0, "high_wind_watches": 1, "wind_advisories": 0,
                   "flood_watches": 0, "flood_warnings": 0, "flood_advisories": 0},
    }

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = make_store(self.tmp)
        self.index = H._read_index(self.store)
        self.codes = H._zone_public_codes(self.index)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def counts(self):
        return H.count_zones(self.store, self.index, self.codes)

    def test_the_fixture_counts_match_the_hand_count(self):
        out = self.counts()
        for code, expect in self.EXPECT.items():
            for key, value in expect.items():
                self.assertEqual(out["zones"][code][key], value, f"{code} {key}")

    def test_every_public_zone_has_a_row_and_fire_zones_have_none(self):
        out = self.counts()
        self.assertEqual(len(out["zones"]), 103)
        fire = [code for code in out["zones"] if "MTZ104" <= code <= "MTZ137"]   # the fire weather zones (not public)
        self.assertEqual(fire, [])

    def test_the_switch_uses_the_removed_zone_only_before_it(self):
        out = self.counts()
        self.assertEqual(out["zones"]["MTZ047"]["flood_warnings"], 1)     # the 2022 warning (before the switch) touches its cells
        self.assertEqual(out["zones"]["MTZ060"]["flood_advisories"], 1)   # the 2025 advisory (after the switch) touches MTZ060

    def test_rows_outside_the_window_do_not_count(self):
        out = self.counts()
        self.assertEqual(out["zones"]["MTZ001"]["high_wind_warnings"], 1)  # the 2020 warning is outside the window

    def test_a_missing_zone_file_is_null_for_that_zone_only(self):
        (self.store / "hail" / "z" / "MTZ002.json").unlink()
        out = H.count_zones(self.store, self.index, self.codes)
        self.assertEqual(out["missing_zone_files"], ["MTZ002"])
        self.assertIsNone(out["zones"]["MTZ002"]["high_wind_warnings"])
        self.assertEqual(out["zones"]["MTZ001"]["high_wind_warnings"], 1)

    def test_an_unloaded_joins_part_is_null_for_its_measures(self):
        index = dict(self.index)
        index["joins"] = dict(self.index["joins"], parts=dict(self.index["joins"]["parts"], warnings="unavailable"),
                              reasons={"warnings": "the warnings did not load"})
        out = H.count_zones(self.store, index, self.codes)
        self.assertIsNone(out["zones"]["MTZ001"]["flood_warnings"])
        self.assertEqual(out["zones"]["MTZ001"]["high_wind_warnings"], 1)
        self.assertEqual(out["unavailable"]["flood_warnings"], "the warnings did not load")
        self.assertNotIn("high_wind_warnings", out["unavailable"])

    def test_a_non_flood_polygon_is_not_a_zone_measure(self):
        keys = {m["key"] for m in H.MEASURES}
        self.assertEqual(keys, {"high_wind_warnings", "high_wind_watches", "wind_advisories", "flood_watches",
                                "flood_warnings", "flood_advisories"})


def _dist_to_segment(px, py, ax, ay, bx, by):
    """The distance from a point to a segment, in the projected metres the simplification uses (the test's own)."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class Outlines(unittest.TestCase):
    def test_simplification_keeps_the_ring_closed_and_within_tolerance(self):
        ring = [[-110.0 + 0.2 * math.cos(2 * math.pi * k / 400), 47.0 + 0.2 * math.sin(2 * math.pi * k / 400)]
                for k in range(400)]
        ring.append(list(ring[0]))
        out = H.simplify_ring(ring, 150.0)
        self.assertEqual(out[0], out[-1])
        self.assertLess(len(out), len(ring))
        self.assertGreaterEqual(len(out), 4)
        kept = [H._project(lon, lat) for lon, lat in out[:-1]]
        for lon, lat in ring[:-1]:
            x, y = H._project(lon, lat)
            best = min(_dist_to_segment(x, y, kept[i][0], kept[i][1], kept[(i + 1) % len(kept)][0],
                                          kept[(i + 1) % len(kept)][1]) for i in range(len(kept)))
            self.assertLessEqual(best, 150.0 + 1e-6)

    def test_coordinates_have_five_decimals(self):
        ring = [[-110.123456789, 47.1], [-110.2, 47.1], [-110.2, 47.2], [-110.123456789, 47.1]]
        out = H.simplify_ring(ring)
        for lon, lat in out:
            self.assertEqual(lon, round(lon, 5))
            self.assertEqual(lat, round(lat, 5))

    def test_a_short_ring_is_kept(self):
        ring = [[-110.0, 47.0], [-110.1, 47.0], [-110.1, 47.1], [-110.0, 47.0]]
        out = H.simplify_ring(ring)
        self.assertEqual(len(out), 4)

    def test_the_zone_file_must_hold_the_current_83_zones(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            codes = fixture_index()["joins"]["zone_list"]
            good = ugcs_geojson(tmp / "good.json", codes)
            self.assertEqual(len(H.read_zone_outlines(good)), 83)
            bad = ugcs_geojson(tmp / "bad.json", codes[:82])
            with self.assertRaises(H.HistoryError):
                H.read_zone_outlines(bad)
            not_fc = tmp / "not.json"
            not_fc.write_text(json.dumps({"type": "Feature"}), encoding="utf-8")
            with self.assertRaises(H.HistoryError):
                H.read_zone_outlines(not_fc)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_county_features_are_ignored(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            codes = fixture_index()["joins"]["zone_list"]
            zones = H.read_zone_outlines(ugcs_geojson(tmp / "z.json", codes))
            self.assertTrue(all(z["zone"].startswith("MTZ") for z in zones))
            self.assertEqual([z["zone"] for z in zones], sorted(codes))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Build(unittest.TestCase):
    NOW = "2026-10-17T12:00:00Z"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = make_store(self.tmp)
        self.zones = fixture_zone_file(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @needs_pil
    def test_a_build_writes_every_part_and_the_manifest_holds(self):
        result = H.build(self.store, zones_file=self.zones, now=self.NOW)
        self.assertEqual(result["state"], "loaded", result)
        for rel in (H.HAIL1_PATH, H.HEAT_PATH, H.SIDECAR_PATH, H.ZONES_PATH, H.RECENT_PATH, H.OUTLINE_PATH):
            self.assertTrue((self.store / rel).is_file(), rel)
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index[H.INDEX_KEY]["state"], "loaded")
        self.assertEqual(index[H.RECENT_KEY]["state"], "loaded")
        hail.check_manifest(self.store)                 # every file listed, with its bytes and hash

    @needs_pil
    def test_the_build_is_deterministic(self):
        H.build(self.store, zones_file=self.zones, now=self.NOW)
        first = {p.relative_to(self.store).as_posix(): p.read_bytes()
                 for p in (self.store / "hail").rglob("*") if p.is_file() and p.name not in ("manifest.json", "index.json")}
        other = Path(tempfile.mkdtemp())
        try:
            store2 = make_store(other)
            H.build(store2, zones_file=self.zones, now=self.NOW)
            second = {p.relative_to(store2).as_posix(): p.read_bytes()
                      for p in (store2 / "hail").rglob("*") if p.is_file() and p.name not in ("manifest.json", "index.json")}
            self.assertEqual(sorted(first), sorted(second))
            for name in first:
                self.assertEqual(first[name], second[name], name)
        finally:
            shutil.rmtree(other, ignore_errors=True)

    @needs_pil
    def test_the_stale_sentence_appears_only_when_the_store_is_old(self):
        H.build(self.store, zones_file=self.zones, now="2026-10-17T12:00:00Z")
        recent = json.loads((self.store / H.RECENT_PATH).read_text(encoding="utf-8"))
        self.assertIsNone(recent["stale"])
        H.build(self.store, zones_file=self.zones, now="2026-10-25T12:00:00Z")
        recent = json.loads((self.store / H.RECENT_PATH).read_text(encoding="utf-8"))
        self.assertIn("newest day in this history is 2026-10-16", recent["stale"])

    @needs_pil
    def test_a_missing_radar_shard_leaves_the_pictures_unavailable_and_the_zones_built(self):
        (self.store / "hail" / "t" / f"{TILE}.json").unlink()
        write_manifest(self.store)
        result = H.build(self.store, zones_file=self.zones, now=self.NOW)
        self.assertEqual(result["pictures"]["hail1"], "unavailable")
        self.assertEqual(result["recent"], "unavailable")
        self.assertEqual(result["zones"], "loaded")
        self.assertEqual(result["outlines"], "loaded")
        self.assertFalse((self.store / H.HAIL1_PATH).exists())
        reason = result["failures"][0]["reason"]
        self.assertIn(TILE, reason)
        self.assertEqual(result["state"], "partial")

    @needs_pil
    def test_the_unavailable_command_removes_the_files_and_verify_accepts_it(self):
        H.build(self.store, zones_file=self.zones, now=self.NOW)
        H.unavailable(self.store, "the radar files were not in this update")
        self.assertFalse((self.store / H.HAIL1_PATH).exists())
        self.assertFalse((self.store / H.OUTLINE_PATH).exists())
        result = H.verify(self.store)
        self.assertTrue(result["ok"], result)
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index[H.INDEX_KEY]["state"], "unavailable")
        self.assertIn("not in this update", index[H.INDEX_KEY]["problem"])

    @needs_pil
    def test_verify_passes_after_a_build_and_names_a_changed_file(self):
        H.build(self.store, zones_file=self.zones, now=self.NOW)
        self.assertTrue(H.verify(self.store)["ok"])
        path = self.store / H.ZONES_PATH
        path.write_bytes(path.read_bytes() + b" ")
        result = H.verify(self.store)
        self.assertFalse(result["ok"])
        failed = [c["check"] for c in result["checks"] if not c["pass"]]
        self.assertTrue(any(H.ZONES_PATH in name for name in failed), failed)

    @needs_pil
    def test_the_outline_file_carries_the_zone_source(self):
        H.build(self.store, zones_file=self.zones, now=self.NOW)
        doc = json.loads((self.store / H.OUTLINE_PATH).read_text(encoding="utf-8"))
        self.assertEqual(doc["f"], H.FORMAT_OUTLINES)
        self.assertEqual(len(doc["zones"]), 83)
        self.assertEqual(doc["source"]["sha256"], _sha(self.zones.read_bytes()))
        self.assertEqual(doc["simplify_m"], 150.0)

    @needs_pil
    def test_an_offline_build_without_the_zone_file_keeps_the_rest(self):
        result = H.build(self.store, offline=True, now=self.NOW)
        self.assertEqual(result["outlines"], "unavailable")
        self.assertFalse((self.store / H.OUTLINE_PATH).exists())

    def test_the_cli_verify_and_unavailable(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(H.main(["unavailable", "--store", str(self.store), "--reason", "a test"]), 0)
            self.assertEqual(H.main(["verify", "--store", str(self.store)]), 0)


class Words(unittest.TestCase):
    """Every sentence the browser shows is written here: none may hold a forbidden word, and the module keeps to plain
    punctuation (no dash characters, no names of AI models or vendors)."""

    def test_the_templates_pass_the_forbidden_list(self):
        for key, text in H.WORDS.items():
            if isinstance(text, str):
                W.assert_clean(self, text, f"history_layers.WORDS[{key}]")
        for m in H.MEASURES:
            W.assert_clean(self, m["label"], m["key"])
            W.assert_clean(self, m["kind"], m["key"])

    def test_the_module_text_has_no_dash_characters(self):
        text = Path(H.__file__).read_text(encoding="utf-8")
        self.assertNotIn("\u2014", text)
        self.assertNotIn("\u2013", text)


if __name__ == "__main__":
    unittest.main()
