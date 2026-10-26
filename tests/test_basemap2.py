"""Tests for website/basemap2.py (B6 product P2): the base map vectors, places and peaks.

Offline. The fixtures under tests/fixtures/basemap2/ are real records copied from the sources and cut small (the
seven Montana reservations, three places with their 2020 rows, a few roads, the summit rows of six peaks and the 3DEP
answer at McDonald Peak), plus synthetic service pages with the same keys and layout as the live services (the forest
boxes, the park, water and summit-free queries), so every number the build reads is known. Tests that read a shapefile
or a zip with a shapefile skip when pyshp is absent (the store job installs it).
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from website import basemap2 as b
from website import hail

try:
    import shapefile  # noqa: F401  (pyshp: the reader of the Census and Forest Service shapefiles)
    HAVE_SHAPEFILE = True
except ImportError:
    HAVE_SHAPEFILE = False

FIX = Path(__file__).resolve().parent / "fixtures" / "basemap2"
# the test box: the Missoula valley, one band D shard row of the grid (four tiles touch it)
TEST_BOX = (-114.10, 46.80, -113.90, 47.00)


def _fixture(name: str) -> bytes:
    return (FIX / name).read_bytes()


class RuleTests(unittest.TestCase):
    def test_bands_cover_zoom_5_to_18(self):
        self.assertEqual(b.BAND_ZOOMS, {"A": (5, 7), "B": (8, 10), "C": (11, 12), "D": (13, 18)})
        self.assertEqual(b.band_of(5), "A")
        self.assertEqual(b.band_of(7), "A")
        self.assertEqual(b.band_of(8), "B")
        self.assertEqual(b.band_of(11), "C")
        self.assertEqual(b.band_of(13), "D")
        with self.assertRaises(b.BasemapError):
            b.band_of(4)

    def test_budgets_and_tolerances_are_the_brief_numbers(self):
        self.assertEqual(b.BAND_BUDGET, {"A": 150_000, "B": 100_000, "C": 60_000, "D": 30_000})
        self.assertEqual(b.BAND_TOL_M, {"A": 500.0, "B": 150.0, "C": 50.0, "D": 0.0})

    def test_cell_names_are_south_west_corners(self):
        self.assertEqual(b.cell_name(46, -114), "n46w114")
        self.assertEqual(b.cell_name(44, -118), "n44w118")
        cells = b.cells_for_box(2)
        self.assertEqual(len(cells), 21)
        self.assertIn((46, -114), cells)
        self.assertEqual(len(b.cells_for_box(1)), 78)

    def test_tile_box_matches_the_b1_grid(self):
        self.assertEqual(b.tile_box("r0079_c0199"), (-110.1, 47.0, -110.0, 47.1))
        self.assertEqual(b.tile_of(47.05, -110.05), (79, 199))
        self.assertEqual(hail.tile_name(79, 199), "r0079_c0199")
        with self.assertRaises(b.BasemapError):
            b.tile_box("tile-79")

    def test_lake_and_river_rules(self):
        self.assertEqual([b.lake_zoom(x) for x in (150, 30, 3, 0.5, 0.05, 0.01)], [5, 7, 8, 9, 11, None])
        self.assertEqual([b.river_zoom(x) for x in (20000, 4000, 1500, 500, 150, 99.9, 12, 1)],
                         [5, 6, 7, 8, 9, None, None, None])
        self.assertEqual(b.RIVER_FLOOR_KM2, 100.0)
        self.assertIsNone(b.lake_zoom(None))

    def test_place_rule_boundaries(self):
        self.assertEqual([b.place_zoom(x) for x in (50000, 49999, 10000, 9999, 2000, 1999, 500, 499, None)],
                         [5, 7, 7, 8, 8, 9, 9, 10, 10])

    def test_route_names_from_the_census_road_file(self):
        self.assertEqual(b.route_name("I- 90", "I"), ("interstate", "I-90"))
        self.assertEqual(b.route_name("US Hwy 93", "U"), ("us", "US-93"))
        self.assertEqual(b.route_name("State Hwy 200", "S"), ("state", "MT-200"))
        self.assertIsNone(b.route_name("Main St", "M"))
        self.assertIsNone(b.route_name("US Hwy 93", "S"))

    def test_names_expand_whole_words_only(self):
        self.assertEqual(b.expand_name("Lk Five Riv Crk"), "Lake Five River Creek")
        self.assertEqual(b.expand_name("Lkview Riverside"), "Lkview Riverside")

    def test_seven_forests_and_seven_reservations_are_named(self):
        self.assertEqual(len(b.FOREST_NAMES), 7)
        self.assertEqual(len(b.RESERVATION_NAMES), 7)
        self.assertEqual(b.PARK_RULES["LP"][1], 13)
        self.assertEqual(b.PARK_RULES["SP"][1], 9)
        self.assertEqual(b.PARK_RULES["NP"][1], 5)

    def test_peak_spacing_rule(self):
        peaks = [{"name": "A", "lat": 47.0, "lon": -114.0, "elev_m": 3000.0},
                 {"name": "B", "lat": 47.05, "lon": -114.02, "elev_m": 2900.0},
                 {"name": "C", "lat": 47.5, "lon": -114.0, "elev_m": 2950.0},
                 {"name": "D", "lat": 47.52, "lon": -114.1, "elev_m": 2800.0},
                 {"name": "E", "lat": 47.0, "lon": -114.0 + 0.2, "elev_m": 2700.0}]
        ranked = b.peak_rank(peaks)
        zooms = {p["name"]: p["min_zoom"] for p in ranked}
        self.assertEqual(zooms["A"], 8)
        self.assertEqual(zooms["C"], 8, "C is 55 km from A, past the 25 km spacing")
        self.assertEqual(zooms["B"], 12, "B is 5 km from A, inside the 10 km spacing")
        self.assertEqual(zooms["D"], 12, "D is 2 km from C, inside the 10 km spacing")
        self.assertEqual(zooms["E"], 10, "E is 15 km from A (inside 25 km, past 10 km) and 56 km from C")
        self.assertEqual([p["elev_m"] for p in ranked], sorted([p["elev_m"] for p in ranked], reverse=True))


class GeometryTests(unittest.TestCase):
    def test_douglas_peucker_keeps_corners_and_drops_small_bumps(self):
        ring = [(-114.0, 47.0), (-114.0001, 47.00005), (-113.99, 47.0), (-113.99, 47.01), (-114.0, 47.01), (-114.0, 47.0)]
        self.assertEqual(len(b._dp(ring, 0)), 6)
        self.assertEqual(len(b._dp(ring, 500)), 5)

    def test_pole_of_a_rectangle_is_its_centre(self):
        lon, lat = b.pole([[[-114.0, 47.0], [-113.9, 47.0], [-113.9, 47.1], [-114.0, 47.1]]])
        self.assertAlmostEqual(lon, -113.95, places=3)
        self.assertAlmostEqual(lat, 47.05, places=3)

    def test_pole_avoids_a_hole(self):
        outer = [[-114.0, 47.0], [-113.0, 47.0], [-113.0, 48.0], [-114.0, 48.0]]
        hole = [[-113.6, 47.4], [-113.4, 47.4], [-113.4, 47.6], [-113.6, 47.6]]
        lon, lat = b.pole([outer, hole])
        inside_hole = -113.6 <= lon <= -113.4 and 47.4 <= lat <= 47.6
        self.assertFalse(inside_hole)

    def test_montana_outline_test_separates_montana_from_idaho(self):
        self.assertTrue(b.in_montana(-114.0, 46.87))
        self.assertFalse(b.in_montana(-117.4, 47.66))

    def test_clip_ring_and_line_to_a_box(self):
        clipped = b._clip_ring([(-1.0, -1.0), (2.0, -1.0), (2.0, 2.0), (-1.0, 2.0)], (0.0, 0.0, 1.0, 1.0))
        self.assertEqual(sorted(clipped), [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)])
        pieces = b._clip_path([(-1.0, 0.5), (0.5, 0.5), (2.0, 0.5), (2.0, 0.7), (0.5, 0.7)], (0.0, 0.0, 1.0, 1.0))
        self.assertEqual(pieces, [[(0.0, 0.5), (0.5, 0.5), (1.0, 0.5)], [(1.0, 0.7), (0.5, 0.7)]])

    def test_tidy_drops_repeats_and_degenerate_parts(self):
        ring = [(0.0, 0.0), (0.0, 0.0), (1.0, 0.0), (1.0, 0.0), (0.0, 0.0)]
        self.assertEqual(b._tidy([ring], closed=True), [], "two distinct points are not a ring")
        square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
        self.assertEqual(b._tidy([square], closed=True), [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]])
        self.assertEqual(b._tidy([[(0.0, 0.0)]], closed=False), [])

    def test_area_and_length_are_in_the_right_units(self):
        square = [[(-114.0, 47.0), (-113.0, 47.0), (-113.0, 48.0), (-114.0, 48.0), (-114.0, 47.0)]]
        self.assertGreater(b.area_km2(square), 8000.0)
        self.assertLess(b.area_km2(square), 9000.0)
        self.assertAlmostEqual(b.length_km([[(-114.0, 47.0), (-114.0, 48.0)]]), 110.6, delta=0.5)


class SplitAndFitTests(unittest.TestCase):
    def test_a_feature_crossing_a_cell_edge_keeps_its_label_in_one_piece(self):
        ring = [[-114.2, 46.9], [-113.95, 46.9], [-113.95, 46.92], [-114.2, 46.92]]
        feature = b.finish(b._rec("lake", "Backwater", 13, [ring], closed=True, size=0.2), 0.0)
        pieces = b._split([feature], b._cell_keys(1), lambda key: b.cell_box(key[0], key[1], 1))
        west, east = pieces[(46, -115)][0], pieces[(46, -114)][0]
        self.assertIsNotNone(west["l"], "the label point lies in the west cell, so the west piece holds it")
        self.assertIsNone(east["l"])
        self.assertEqual(west["n"], "Backwater")

    def test_a_line_crossing_a_cell_edge_is_split_at_it(self):
        path = [[-114.5, 46.5], [-113.5, 46.5]]
        feature = b.finish(b._rec("river", "Edge River", 9, [path], closed=False, size=10.0), 0.0)
        pieces = b._split([feature], b._cell_keys(1), lambda key: b.cell_box(key[0], key[1], 1))
        self.assertEqual(len(pieces[(46, -115)]), 1)
        self.assertEqual(len(pieces[(46, -114)]), 1)
        self.assertEqual(set(pieces), {(46, -115), (46, -114)})

    def test_fit_keeps_a_file_whole_when_it_is_within_budget(self):
        feats = [b.finish(b._rec("river", f"R{i}", 9, [[(-114 + i * 0.001, 47.0), (-114 + i * 0.001, 47.01)]], closed=False,
                                 size=1.0), 0.0) for i in range(5)]
        res = b.fit({"f": "x"}, feats, 100_000)
        self.assertEqual((res["dropped"], res["over"], len(res["kept"])), (0, False, 5))

    def test_fit_drops_the_least_visible_first_and_keeps_protected_kinds(self):
        protected = b.finish(b._rec("reservation", "Flathead Reservation", 5, [[(-114.5, 47.0), (-114.0, 47.0),
                                                                             (-114.0, 47.5), (-114.5, 47.5)]],
                                    closed=True, size=900.0), 0.0)
        feats = [protected]
        for i in range(120):
            wiggle = [(-114 + (j * 0.00031 * (i % 7 + 1)), 47.0 + (j * 0.00023 * ((i * 3) % 5 + 1))) for j in range(60)]
            feats.append(b.finish(b._rec("river", f"Stream {i}", 13 if i % 2 else 9, [wiggle], closed=False,
                                         size=float(i)), 0.0))
        res = b.fit({"f": "x", "band": "D"}, feats, 6000)
        kept_names = {f["n"] for f in res["kept"]}
        self.assertIn("Flathead Reservation", kept_names)
        self.assertGreater(res["dropped"], 0)
        self.assertLessEqual(res["gzip"], 6000)
        self.assertFalse(res["over"])
        dropped_zoom = [f["z"] for f in feats if f["n"] not in kept_names and not f["protect"]]
        kept_zoom = [f["z"] for f in res["kept"] if not f["protect"]]
        self.assertLessEqual(max(kept_zoom), min(dropped_zoom), "a feature with a higher minimum zoom goes first")

    def test_fit_marks_over_budget_when_the_protected_kinds_alone_exceed_it(self):
        ring = [[(-114.0 + i * 0.0005, 47.0 + (i % 7) * 0.0003) for i in range(400)]]
        feats = [b.finish(b._rec("forest", "Big Forest", 5, ring, closed=True, size=900.0), 0.0)]
        res = b.fit({"f": "x"}, feats, 10)
        self.assertTrue(res["over"])
        self.assertEqual(len(res["kept"]), 1)


@unittest.skipUnless(HAVE_SHAPEFILE, "pyshp is not installed")
class ReaderTests(unittest.TestCase):
    def test_reservations_are_the_seven_montana_entities(self):
        rows = b.read_reservations(_fixture("tl_2026_us_aiannh_mt.zip"))
        self.assertEqual(sorted(r["name"] for r in rows), sorted(b.RESERVATION_NAMES))
        self.assertTrue(all(r["parts"] for r in rows))

    def test_routes_carry_interstate_us_and_state_shields(self):
        rows = b.read_routes(_fixture("tl_2026_30_prisecroads_sample.zip"))
        refs = {r["ref"] for r in rows}
        self.assertIn("I-90", refs)
        self.assertIn("US-12", refs)
        self.assertIn("MT-200", refs)
        self.assertEqual({r["class"] for r in rows}, {"interstate", "us", "state"})

    def test_places_and_their_2020_population(self):
        places = b.read_places(_fixture("tl_2026_30_place_sample.zip"))
        names = {p["name"] for p in places}
        self.assertTrue({"Lolo", "Frenchtown", "Missoula"} <= names)
        pops = b.read_population(_fixture("mt2020_pl_places_sample.zip"))
        by_name = {p["name"]: pops.get(p["placefp"]) for p in places}
        self.assertEqual(by_name["Lolo"], 4399)
        self.assertEqual(by_name["Frenchtown"], 1958)
        self.assertEqual(by_name["Missoula"], 73489)

    def test_summits_have_names_and_positions_and_no_height(self):
        summits = b.read_summits(_fixture("DomesticNames_MT_sample.zip"))
        names = {s["name"] for s in summits}
        self.assertIn("McDonald Peak", names)
        mc = next(s for s in summits if s["name"] == "McDonald Peak")
        self.assertAlmostEqual(mc["lat"], 47.3825153, places=6)
        self.assertEqual(mc["county"], "Lake")
        self.assertNotIn("elev_m", mc)
        self.assertNotIn("Missoula", names)

    def test_mcdonald_peak_height_is_within_30_m_of_the_published_figure(self):
        answer = json.loads(_fixture("3dep_mcdonald_answer.json"))
        metres = float(answer["samples"][0]["value"])
        self.assertAlmostEqual(b.PEAK_CHECK["metres"], 2993.1, places=1)
        self.assertLessEqual(abs(metres - b.PEAK_CHECK["metres"]), b.PEAK_TOLERANCE_M,
                             f"3DEP {metres:.1f} m against {b.PEAK_CHECK['source']}")


class ParsingTests(unittest.TestCase):
    def test_service_parts_read_rings_and_paths(self):
        self.assertEqual(b.service_parts({"rings": [[[1, 2], [3, 4], [1, 2]]]}), [[(1.0, 2.0), (3.0, 4.0), (1.0, 2.0)]])
        self.assertEqual(b.service_parts({"paths": [[[1, 2], [3, 4]]]}), [[(1.0, 2.0), (3.0, 4.0)]])
        self.assertIsNone(b.service_parts(None))

    def test_service_errors_are_failed_requests(self):
        with self.assertRaises(b.BasemapError):
            b._check_features(b'{"error": {"code": 400}}')
        with self.assertRaises(b.BasemapError):
            b._check_features(b"<html>not json</html>")
        b._check_features(b'{"features": [], "exceededTransferLimit": false}')


@unittest.skipUnless(HAVE_SHAPEFILE, "pyshp is not installed")
class BuildTests(unittest.TestCase):
    """The whole build offline, from the fixtures in a temporary cache and store."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="basemap2-test-"))
        cls.cache = cls.tmp / "cache"
        cls.store = cls.tmp / "store"
        (cls.store / "hail").mkdir(parents=True)
        cls.tiles = sorted({hail.tile_name(*b.tile_of(lat, lon))
                            for lat in (TEST_BOX[1] + 0.01, TEST_BOX[3] - 0.01)
                            for lon in (TEST_BOX[0] + 0.01, TEST_BOX[2] - 0.01)})
        (cls.store / "hail" / "index.json").write_text(json.dumps(
            {"format": "hail-store-v1", "as_of": "2026-10-16", "tiles": cls.tiles}), encoding="utf-8")
        (cls.store / "hail" / "manifest.json").write_text(json.dumps(
            {"format": "hail-manifest-v1", "files": {}, "counts": {}}), encoding="utf-8")
        cls._stage_cache()
        cls.result = b.build(cls.store, cls.cache, offline=True, box=TEST_BOX)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _stage_cache(cls) -> None:
        def put(rel: str, data: bytes) -> None:
            path = cls.cache / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        put("census/tl_2026_us_aiannh.zip", _fixture("tl_2026_us_aiannh_mt.zip"))
        put("census/tl_2026_30_prisecroads.zip", _fixture("tl_2026_30_prisecroads_sample.zip"))
        put("census/tl_2026_30_place.zip", _fixture("tl_2026_30_place_sample.zip"))
        put("census/mt2020.pl.zip", _fixture("mt2020_pl_places_sample.zip"))
        put("gnis/DomesticNames_MT_Text.zip", _fixture("DomesticNames_MT_sample.zip"))
        put(b.page_name("edw", "mt", b.forest_params(), 0), _fixture("edw_forests_page.json"))
        put(b.page_name("padus", "mt", b.padus_params(), 0), _fixture("padus_parks_page.json"))
        put(b.page_name("nhd_small_lines", "mt", b.nhd_params("small_lines", b.MT_BOX), 0),
            _fixture("nhd_small_lines_page.json"))
        put(b.page_name("nhd_small_areas", "mt", b.nhd_params("small_areas", b.MT_BOX), 0),
            _fixture("nhd_small_areas_page.json"))
        key = "box_" + "_".join(f"{v:g}" for v in TEST_BOX)
        put(b.page_name("nhd_large_areas", key, b.nhd_params("large_areas", TEST_BOX), 0),
            _fixture("nhd_large_areas_page.json"))
        put(b.page_name("nhd_large_lines", key, b.nhd_params("large_lines", TEST_BOX), 0),
            _fixture("nhd_large_lines_page.json"))
        summits = b.read_summits(_fixture("DomesticNames_MT_sample.zip"))
        points = [(s["lon"], s["lat"]) for s in summits]
        import hashlib
        digest = hashlib.sha1(json.dumps(points).encode("utf-8")).hexdigest()[:12]
        samples = []
        for i, s in enumerate(summits):
            value = "2969.231689453" if s["name"] == "McDonald Peak" else str(2500.0 + i)
            samples.append({"location": {"x": s["lon"], "y": s["lat"]}, "locationId": i, "value": value, "rasterId": 1})
        put(f"3dep/samples_00000_{digest}.json", json.dumps({"samples": samples}).encode("utf-8"))

    def test_a_test_box_build_is_partial_and_says_so(self):
        self.assertEqual(self.result["state"], "partial", self.result.get("failures"))
        self.assertIn("the box", self.result["problem"])
        self.assertIn("This is not an all-clear.", self.result["problem"])
        self.assertEqual(self.result["requests"], 0, "an offline build makes no request")

    def test_band_a_holds_reservations_forests_rivers_and_interstates(self):
        doc = json.loads((self.store / b.A_FILE).read_text(encoding="utf-8"))
        names = {f["n"] for f in doc["features"]}
        self.assertTrue(set(b.RESERVATION_NAMES) <= names)
        self.assertTrue(set(b.FOREST_NAMES) <= names)
        self.assertIn("Clark Fork", names)
        self.assertIn("Bitterroot River", names)
        self.assertIn("Flathead Lake", names)
        self.assertNotIn("Tiny Creek", names, "a 5 km2 stream is band C, not band A")
        self.assertTrue(all(f["z"] <= 7 for f in doc["features"]))
        self.assertEqual(doc["band"], "A")

    def test_every_band_b_and_c_cell_has_a_file_and_small_lakes_sit_in_band_c(self):
        for lat0, lon0 in b.cells_for_box(2):
            self.assertTrue((self.store / b.B_PREFIX / f"{b.cell_name(lat0, lon0)}.json").is_file())
        for lat0, lon0 in b.cells_for_box(1):
            self.assertTrue((self.store / b.C_PREFIX / f"{b.cell_name(lat0, lon0)}.json").is_file())
        c_names = set()
        for path in (self.store / b.C_PREFIX).glob("*.json"):
            c_names |= {f["n"] for f in json.loads(path.read_text(encoding="utf-8"))["features"]}
        self.assertIn("Mill Pond", c_names)

    def test_band_d_shards_hold_the_named_water_and_parks_of_the_box(self):
        for tile in self.tiles:
            path = self.store / b.W_PREFIX / f"{tile}.json"
            self.assertTrue(path.is_file(), tile)
        names = set()
        for tile in self.tiles:
            doc = json.loads((self.store / b.W_PREFIX / f"{tile}.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["f"], b.FORMAT_TILE)
            names |= {f["n"] for f in doc["features"]}
        self.assertIn("Rattlesnake Lake", names)
        self.assertIn("Sacajawea Park", names)
        self.assertIn("Backwater Slough", names)

    def test_places_and_peaks_are_written_with_their_rules(self):
        places = json.loads((self.store / b.PLACES_FILE).read_text(encoding="utf-8"))["places"]
        by = {p["name"]: p for p in places}
        self.assertEqual(by["Lolo"]["population"], 4399)
        self.assertEqual(by["Lolo"]["min_zoom"], 8)
        self.assertEqual(by["Frenchtown"]["min_zoom"], 9)
        self.assertEqual(by["Missoula"]["min_zoom"], 5, "Missoula keeps the first-paint base map's minimum zoom")
        self.assertEqual(by["Missoula"]["rank"], 1)
        peaks = json.loads((self.store / b.PEAKS_FILE).read_text(encoding="utf-8"))["peaks"]
        mc = next(p for p in peaks if p["name"] == "McDonald Peak")
        self.assertLessEqual(abs(mc["elev_m"] - b.PEAK_CHECK["metres"]), b.PEAK_TOLERANCE_M)
        self.assertLessEqual(abs(mc["elev_ft"] - mc["elev_m"] / 0.3048), 1.0)

    def test_verify_passes_on_the_fixture_build(self):
        result = b.verify(self.store)
        failed = [c for c in result["checks"] if not c["pass"]]
        self.assertTrue(result["ok"], failed)

    def test_the_index_mirrors_into_the_store_index_and_the_manifest(self):
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        mirror = index["base"][b.PRODUCT]
        self.assertEqual(mirror["state"], "partial")
        self.assertEqual(mirror["as_of"], "2026-10-16")
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn(b.A_FILE, manifest["files"])
        self.assertIn(b.INDEX_FILE, manifest["files"])
        self.assertIn("hail/index.json", manifest["files"])

    def test_a_second_build_writes_the_same_bytes(self):
        before = (self.store / b.A_FILE).read_bytes()
        again = b.build(self.store, self.cache, offline=True, box=TEST_BOX)
        self.assertEqual(again["state"], "partial")
        self.assertEqual((self.store / b.A_FILE).read_bytes(), before)

    def test_verify_fails_when_a_file_changes(self):
        target = self.store / b.A_FILE
        original = target.read_bytes()
        try:
            target.write_bytes(original + b" ")
            self.assertFalse(b.verify(self.store)["ok"])
        finally:
            target.write_bytes(original)
        self.assertTrue(b.verify(self.store)["ok"])

    def test_a_missing_forest_source_is_named_and_the_rest_builds(self):
        cache = self.tmp / "cache_no_forests"
        shutil.copytree(self.cache, cache)
        (cache / b.page_name("edw", "mt", b.forest_params(), 0)).unlink()
        store = self.tmp / "store_no_forests"
        shutil.copytree(self.store, store)
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["state"], "partial")
        self.assertIn(b.PART_WORDS["forest"][0].lower(), result["problem"].lower())
        doc = json.loads((store / b.A_FILE).read_text(encoding="utf-8"))
        self.assertNotIn("Flathead National Forest", {f["n"] for f in doc["features"]})
        self.assertIn("Clark Fork", {f["n"] for f in doc["features"]})

    def test_unavailable_marks_the_block_and_keeps_another_products_files(self):
        store = self.tmp / "store_unavailable"
        shutil.copytree(self.store, store)
        other = store / "hail" / "base" / "p" / "other.json"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text("{}", encoding="utf-8")
        block = b.mark_unavailable(store, "the test asked for it")
        self.assertEqual(block["state"], "unavailable")
        self.assertEqual(block["problem"], b.WORDS["unavailable"])
        self.assertFalse((store / b.A_FILE).exists())
        self.assertFalse((store / b.PLACES_FILE).exists())
        self.assertTrue(other.is_file(), "another base product's file is not this product's to remove")
        result = b.verify(store)
        self.assertTrue(result["ok"])
        self.assertEqual(result.get("note"), b.WORDS["unavailable"])

    def test_a_build_with_no_source_at_all_is_unavailable_not_empty(self):
        empty_cache = self.tmp / "cache_empty"
        empty_cache.mkdir()
        store = self.tmp / "store_empty"
        shutil.copytree(self.store, store)
        result = b.build(store, empty_cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["state"], "unavailable")
        self.assertFalse((store / b.A_FILE).exists())

    def test_the_map_block_names_the_unavailable_state(self):
        block = b.map_data_vector(None)
        self.assertEqual(block["state"], "unavailable")
        self.assertEqual(block["problem"], b.WORDS["unavailable"])
        loaded = b.map_data_vector({"state": "loaded", "as_of": "2026-10-16", "budgets": {}})
        self.assertEqual(loaded["tiles"]["a"], b.A_FILE)

    def test_the_command_line_verifies_and_marks_unavailable(self):
        import contextlib
        store = self.tmp / "store_cli"
        shutil.copytree(self.store, store)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(b.main(["verify", "--store", str(store)]), 0)
            self.assertEqual(b.main(["unavailable", "--store", str(store), "--reason", "test"]), 0)
        self.assertEqual(json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))["base"]["vector"]["state"],
                         "unavailable")


class WordsTests(unittest.TestCase):
    def test_words_follow_the_house_rules(self):
        for key, text in b.WORDS.items():
            self.assertNotIn("\u2014", text, key)
            self.assertNotIn("\u2013", text, key)
        self.assertIn("This is not an all-clear.", b.WORDS["unavailable"])
        self.assertIn("that is not the same as no", b.WORDS["unavailable"])
        self.assertTrue(b.WORDS["peak_note"].endswith("shows Data unavailable."))


class CreditTests(unittest.TestCase):
    def test_every_source_has_a_credit_line_and_the_forest_terms_are_open(self):
        self.assertEqual(len(b.CREDIT), 7)
        self.assertTrue(any("U.S. Census Bureau" in c for c in b.CREDIT))
        self.assertTrue(any("3DEP data courtesy of the U.S. Geological Survey" in c for c in b.CREDIT))
        self.assertTrue(any("Forest" in c for c in b.CREDIT))
        self.assertIn("OPEN", b.__doc__)


if __name__ == "__main__":
    unittest.main()
