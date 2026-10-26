"""Tests for website/basemap2.py (B6 product P2): the base map vectors, places and peaks.

Offline. The fixtures under tests/fixtures/basemap2/ are real records copied from the sources and cut small (the
seven Montana reservations, three places with their 2020 rows, a few roads, the summit rows of six peaks and the 3DEP
answer at McDonald Peak), plus synthetic service pages with the same keys and layout as the live services (the forest
boxes, the park, water and summit-free queries), so every number the build reads is known. Tests that read a shapefile
or a zip with a shapefile skip when pyshp is absent (the store job installs it).
"""
from __future__ import annotations

import hashlib
import io
import itertools
import json
import math
import shutil
import sys
import tempfile
import time
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

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


def stage_cache(cache: Path) -> None:
    """Copies the fixtures into a cache folder in the layout the build reads (the census and GNIS zips, the EDW, PAD-US and
    NHD pages of the test box, and the 3DEP answer at the summits), so a whole build runs offline."""

    def put(rel: str, data: bytes) -> None:
        path = cache / rel
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
    digest = hashlib.sha1(json.dumps(points).encode("utf-8")).hexdigest()[:12]
    samples = []
    for i, s in enumerate(summits):
        value = "2969.231689453" if s["name"] == "McDonald Peak" else str(2500.0 + i)
        samples.append({"location": {"x": s["lon"], "y": s["lat"]}, "locationId": i, "value": value, "rasterId": 1})
    put(f"3dep/samples_00000_{digest}.json", json.dumps({"samples": samples}).encode("utf-8"))

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

    def test_a_box_that_ends_on_a_tile_edge_does_not_touch_the_tile_beyond(self):
        names = {hail.tile_name(r, c) for r in (79, 80, 81) for c in (159, 160, 161)}
        # 46.9 N to 47.0 N and 114.0 W to 113.9 W: one tile, row 80 column 160 (the edges are its own edges)
        self.assertEqual(b.tiles_for_bbox((-114.0, 46.9, -113.9, 47.0), names), ["r0080_c0160"])

    def test_a_one_degree_cell_holds_exactly_its_hundred_tiles(self):
        names = {hail.tile_name(r, c) for r in range(99, 111) for c in range(159, 171)}
        inside = b.tiles_for_bbox(b.cell_box(44, -114, 1), names)
        self.assertEqual(len(inside), 100)
        self.assertEqual(set(inside), {hail.tile_name(r, c) for r in range(100, 110) for c in range(160, 170)})

    def test_lake_and_river_rules(self):
        self.assertEqual([b.lake_zoom(x) for x in (150, 30, 3, 0.5, 0.05, 0.01)], [5, 7, 8, 9, 11, None])
        self.assertEqual([b.river_zoom(x) for x in (20000, 4000, 1500, 500, 150, 99.9, 12, 1)],
                         [5, 6, 8, 8, 9, None, None, None], "no river starts at zoom 7")
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
        self.assertEqual(b.route_name("US Hwy 93 N", "U"), ("us", "US-93"), "a directional suffix is the same route")
        self.assertEqual(b.route_name("State Hwy 200 E", "S"), ("state", "MT-200"))
        self.assertIsNone(b.route_name("I- 90 Bus", "I"), "a business loop is not drawn as the interstate")
        self.assertIsNone(b.route_name("W US Hwy 12", "U"), "a prefixed variant is not drawn as the route")

    def test_a_route_like_local_name_gives_no_shield(self):
        self.assertIsNone(b.route_name("FAS 533", "S"), "a federal aid secondary road is not a state route shield")
        self.assertIsNone(b.route_name("FAS 533", "M"))
        self.assertIsNone(b.route_name("W US Hwy 12", "U"))
        self.assertEqual({p[0] for p in b.ROUTE_PATTERNS}, {"interstate", "us", "state"})

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


    def test_each_piece_keeps_the_source_id_and_its_own_size(self):
        ring = [[-114.2, 46.9], [-113.95, 46.9], [-113.95, 46.92], [-114.2, 46.92]]
        feature = b.finish(b._rec("lake", "Backwater", 13, [ring], closed=True, size=0.2, oid="77"), 0.0)
        pieces = b._split([feature], b._cell_keys(1), lambda key: b.cell_box(key[0], key[1], 1))
        west, east = pieces[(46, -115)][0], pieces[(46, -114)][0]
        self.assertEqual((west["id"], east["id"]), ("77", "77"), "a feature cut across two cells keeps one id")
        self.assertGreater(west["size"], east["size"], "each piece carries its own area")
        self.assertGreater(east["size"], 0.0)

    def test_a_feature_with_no_size_is_dropped_first_among_its_zoom(self):
        ring = [[-114.0, 47.0], [-113.9, 47.0], [-113.9, 47.1], [-114.0, 47.1]]
        sized = b.finish(b._rec("park", "Sized Park", 9, [ring], closed=True, size=5.0, code="SP", oid="1"), 0.0)
        unsized = b.finish(b._rec("park", "No Acre Park", 9, [ring], closed=True, size=None, code="SP", oid="2"), 0.0)
        self.assertEqual([f["n"] for f in sorted([unsized, sized], key=b._visibility)], ["Sized Park", "No Acre Park"])

    def test_band_features_are_written_with_their_id_and_a_size_or_null(self):
        ring = [[-114.0, 47.0], [-113.9, 47.0], [-113.9, 47.1], [-114.0, 47.1]]
        park = b.finish(b._rec("park", "Quiet Park", 9, [ring], closed=True, size=None, code="SP", oid="42"), 0.0)
        out = b.encode(park)
        self.assertEqual(out["id"], "42")
        self.assertIsNone(out["size"], "no acreage is null, never zero")
        self.assertIn("l", out, "a named area carries its label point")
        lake = b.finish(b._rec("lake", "Quiet Lake", 9, [ring], closed=True, size=2.5, oid="7"), 0.0)
        self.assertEqual((b.encode(lake)["id"], b.encode(lake)["size"]), ("7", 2.5))
        nameless = b.finish(b._rec("park", "", 9, [ring], closed=True, size=1.0, code="SP", oid="8"), 0.0)
        self.assertIsNone(nameless["l"], "a park with no name gets no label point")
        self.assertNotIn("l", b.encode(nameless))
        self.assertEqual(b.encode(nameless)["n"], "")


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
        self.assertAlmostEqual(b.PEAK_CHECK["metres"], 2994.4, places=1)
        self.assertAlmostEqual(b.PEAK_CHECK["feet"] * 0.3048, b.PEAK_CHECK["metres"], delta=0.1)
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

    def test_a_failed_envelope_is_read_as_its_four_quarters(self):
        """The whole envelope has no cached page (offline, so its query fails); the four quarters are cached, so the
        envelope's features are the quarters' features, with no problem left, and a repeat is not counted twice by the
        caller (features are keyed by OBJECTID)."""
        cache = Path(tempfile.mkdtemp(prefix="basemap2-split-"))
        try:
            env = (-114.0, 46.0, -113.0, 47.0)
            key = "46_-114"
            mx, my = -113.5, 46.5
            quarters = [(-114.0, 46.0, mx, my), (mx, 46.0, -113.0, my), (-114.0, my, mx, 47.0), (mx, my, -113.0, 47.0)]
            for i, quarter in enumerate(quarters):
                page = {"features": [{"attributes": {"OBJECTID": i, "gnis_name": f"Quarter {i}"},
                                      "geometry": {"paths": [[[quarter[0] + 0.1, quarter[1] + 0.1],
                                                              [quarter[2] - 0.1, quarter[3] - 0.1]]]}}]}
                path = cache / b.page_name("nhd_large_lines", f"{key}q1{i}", b.nhd_params("large_lines", quarter), 0)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(page), encoding="utf-8")
            ctx = b._Ctx(cache, offline=True, refresh=False, deadline_at=None)
            feats, probs = b.nhd_cell_features(ctx, "large_lines", env, key)
            self.assertEqual(probs, [], "the parts answered, so the envelope is complete")
            self.assertEqual(sorted(f["attributes"]["OBJECTID"] for f in feats), [0, 1, 2, 3])
        finally:
            shutil.rmtree(cache, ignore_errors=True)


    def test_a_failing_envelope_makes_the_design_number_of_requests(self):
        """One request for the envelope and one for each quarter (one try each: the levels above the last), then three
        tries for each sixteenth: 1 + 4 + 16 x 3 = 53 requests. Before the attempts were passed on it made 63."""
        cache = Path(tempfile.mkdtemp(prefix="basemap2-retry-"))
        try:
            answer = types.SimpleNamespace(status_code=504, content=b"")
            with mock.patch("requests.get", return_value=answer) as get, mock.patch("website.basemap2.time.sleep"):
                ctx = b._Ctx(cache, offline=False, refresh=False, deadline_at=None)
                feats, probs = b.nhd_cell_features(ctx, "large_lines", (-114.0, 46.0, -113.0, 47.0), "46_-114")
            self.assertEqual(feats, [])
            self.assertTrue(probs, "the envelope failed, so a problem is named")
            self.assertEqual(get.call_count, 53)
        finally:
            shutil.rmtree(cache, ignore_errors=True)

    def test_an_unreadable_cache_file_is_a_failed_source_not_a_crash(self):
        cache = Path(tempfile.mkdtemp(prefix="basemap2-unreadable-"))
        try:
            name = b.page_name("edw", "mt", b.forest_params(), 0)
            path = cache / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_fixture("edw_forests_page.json"))
            real_read = Path.read_bytes

            def denied(p):
                if p == path:
                    raise PermissionError(13, "Permission denied")
                return real_read(p)

            with mock.patch.object(Path, "read_bytes", denied):
                ctx = b._Ctx(cache, offline=True, refresh=False, deadline_at=None)
                data, state, reason = b.fetch(ctx, "edw", b.EDW_URL, name, b._check_features, params=b.forest_params())
            self.assertIsNone(data)
            self.assertEqual(state, "failed")
            self.assertIn("not usable", reason)
            self.assertEqual(ctx.sources["edw"]["failed"], 1)
        finally:
            shutil.rmtree(cache, ignore_errors=True)

    def test_a_failure_row_that_names_no_kind_names_no_kind(self):
        block = {"state": "partial", "failures": [{"reasons": ["no kind here"]}, {"kind": "place", "reasons": ["x"]}]}
        self.assertEqual(b.map_data_vector(block)["failed_kinds"], ["place"])
        self.assertEqual(b._failed_kinds(block), {"place"})


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
        stage_cache(cls.cache)

    def test_a_test_box_build_is_partial_and_says_so(self):
        self.assertEqual(self.result["state"], "partial", self.result.get("failures"))
        self.assertIn("from 114.1 W to 113.9 W", self.result["problem"])
        self.assertIn("This is not an all-clear.", self.result["problem"])
        self.assertTrue(self.result["problem"].startswith("Data unavailable. Detailed lake, river and park outlines"))
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
        self.assertIn("Data unavailable. " + b.PART_WORDS["forest"][0] + " could not be loaded in this update",
                      result["problem"])
        doc = json.loads((store / b.A_FILE).read_text(encoding="utf-8"))
        self.assertNotIn("Flathead National Forest", {f["n"] for f in doc["features"]})
        self.assertIn("Clark Fork", {f["n"] for f in doc["features"]})
        verdict = b.verify(store)
        self.assertTrue(verdict["ok"], [c for c in verdict["checks"] if not c["pass"]])
        skipped = [c["check"] for c in verdict["checks"] if c.get("skipped")]
        self.assertIn("band A holds the seven national forests", skipped, "a failed source is named, not failed twice")
        self.assertTrue(all(c["pass"] for c in verdict["checks"] if not c["skipped"]), verdict["checks"])

    def test_the_national_park_in_band_a_has_its_unit_name(self):
        doc = json.loads((self.store / b.A_FILE).read_text(encoding="utf-8"))
        parks = {f["n"] for f in doc["features"] if f["k"] == "park"}
        self.assertIn("Glacier National Park", parks)
        self.assertNotIn("GLAC", parks)

    def test_a_box_whose_water_fails_leaves_its_tiles_unbuilt_and_says_so(self):
        cache = self.tmp / "cache_unbuilt"
        shutil.copytree(self.cache, cache)
        key = "box_" + "_".join(f"{v:g}" for v in TEST_BOX)
        (cache / b.page_name("nhd_large_lines", key, b.nhd_params("large_lines", TEST_BOX), 0)).unlink()
        store = self.tmp / "store_unbuilt"
        shutil.copytree(self.store, store)
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["state"], "partial")
        self.assertIn(b.WORDS["band_d_water_partial"].format(failed=1, areas=1), result["problem"])
        self.assertTrue(result["problem"].startswith("Data unavailable. Detailed lake and river outlines"))
        self.assertEqual(list((store / b.W_PREFIX).glob("*.json")), [], "a tile whose water failed has no shard")
        block = json.loads((store / b.INDEX_FILE).read_text(encoding="utf-8"))[b.PRODUCT]
        self.assertEqual(block["coverage"]["tiles_built"], 0)
        self.assertEqual(block["coverage"]["tiles_unbuilt"], len(self.tiles))
        self.assertEqual(block["coverage"]["band_d_failed_cell_count"], 1)
        self.assertEqual(list(block["coverage"]["band_d_cell_reasons"].values()),
                         ["the cache has no copy and this build makes no requests"])
        self.assertTrue(b.verify(store)["ok"])

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


    @staticmethod
    def _band_features(store):
        """Every feature of the vector files of a store (bands A to D)."""
        paths = ([store / b.A_FILE] + sorted((store / b.B_PREFIX).glob("*.json"))
                 + sorted((store / b.C_PREFIX).glob("*.json")) + sorted((store / b.W_PREFIX).glob("*.json")))
        for path in paths:
            for f in json.loads(path.read_text(encoding="utf-8")).get("features", []):
                yield f

    @staticmethod
    def _county_roads_zip() -> bytes:
        """A road file of county roads only: the file gives no interstate, US or state route."""
        import shapefile as pyshp
        tmp = Path(tempfile.mkdtemp(prefix="basemap2-roads-"))
        try:
            writer = pyshp.Writer(str(tmp / "roads"), shapeType=pyshp.POLYLINE)
            for name in ("LINEARID", "FULLNAME", "RTTYP", "MTFCC"):
                writer.field(name, "C", size=40)
            writer.line([[(-114.0, 46.9), (-113.95, 46.92)]])
            writer.record("1103024769294", "County Road 1", "C", "S1400")
            writer.close()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for ext in ("shp", "shx", "dbf"):
                    z.write(tmp / f"roads.{ext}", f"roads.{ext}")
            return buf.getvalue()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _variant(self, label: str):
        """A copy of the staged cache and store, for a test that changes one input or one file."""
        cache = self.tmp / f"cache_{label}"
        store = self.tmp / f"store_{label}"
        shutil.copytree(self.cache, cache)
        shutil.copytree(self.store, store)
        return cache, store

    def test_a_road_file_with_no_route_is_a_named_failure(self):
        cache, store = self._variant("county_roads")
        (cache / "census/tl_2026_30_prisecroads.zip").write_bytes(self._county_roads_zip())
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["state"], "partial")
        self.assertIn(b.PART_WORDS["route"][0].lower(), result["problem"].lower())
        self.assertIn("Data unavailable. " + b.PART_WORDS["route"][0] + " could not be loaded in this update",
                      result["problem"])
        self.assertIn("route", [row["kind"] for row in result["failures"]])
        self.assertTrue(b.verify(store)["ok"], "a named failure is skipped by verify, not failed")

    def test_a_park_query_with_no_known_designation_is_a_named_failure(self):
        cache, store = self._variant("park_codes")
        page = json.loads(_fixture("padus_parks_page.json"))
        for feature in page["features"]:
            feature["attributes"]["Des_Tp"] = "ZZ"
        (cache / b.page_name("padus", "mt", b.padus_params(), 0)).write_text(json.dumps(page), encoding="utf-8")
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["state"], "partial")
        self.assertIn(b.PART_WORDS["park"][0].lower(), result["problem"].lower())
        self.assertIn("park", [row["kind"] for row in result["failures"]])
        self.assertTrue(b.verify(store)["ok"])

    def test_a_forest_query_with_none_of_the_seven_names_is_a_named_failure(self):
        cache, store = self._variant("forest_names")
        page = json.loads(_fixture("edw_forests_page.json"))
        for feature in page["features"]:
            feature["attributes"]["forestname"] = "Nowhere National Forest"
        (cache / b.page_name("edw", "mt", b.forest_params(), 0)).write_text(json.dumps(page), encoding="utf-8")
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["state"], "partial")
        self.assertIn(b.PART_WORDS["forest"][0].lower(), result["problem"].lower())
        self.assertTrue(b.verify(store)["ok"])

    def test_summit_heights_with_no_value_are_named_and_counted(self):
        cache, store = self._variant("no_heights")
        for path in (cache / "3dep").glob("samples_*.json"):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for sample in doc["samples"]:
                sample["value"] = "-9999"
            path.write_text(json.dumps(doc), encoding="utf-8")
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["state"], "partial")
        self.assertIn(b.PART_WORDS["peak"][0].lower(), result["problem"].lower())
        self.assertIn("could not be read in this update", result["problem"])
        self.assertEqual(result["counts"]["peaks"], 0)
        self.assertGreater(result["counts"]["peaks_no_height"], 0)
        self.assertTrue(b.verify(store)["ok"])

    def test_a_missing_population_file_names_the_place_kind_and_the_count(self):
        cache, store = self._variant("no_population")
        (cache / "census/mt2020.pl.zip").unlink()
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["state"], "partial")
        self.assertIn(b.PART_WORDS["place"][0], result["problem"])
        self.assertIn("Data unavailable. The 2020 population of", result["problem"])
        self.assertIn("place", [row["kind"] for row in result["failures"]])
        index = json.loads((store / b.INDEX_FILE).read_text(encoding="utf-8"))[b.PRODUCT]
        self.assertEqual(b.map_data_vector(index)["failed_kinds"], ["place"])
        places = json.loads((store / b.PLACES_FILE).read_text(encoding="utf-8"))["places"]
        self.assertTrue(places)
        self.assertTrue(all(p["population"] is None and p["rank"] is None for p in places))
        self.assertTrue(b.verify(store)["ok"])

    def test_an_unreadable_census_file_is_a_failed_source_and_the_build_finishes(self):
        cache, store = self._variant("unreadable")
        real_read = Path.read_bytes

        def denied(p):
            if p.name == "tl_2026_30_place.zip":
                raise PermissionError(13, "Permission denied")
            return real_read(p)

        with mock.patch.object(Path, "read_bytes", denied):
            result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["state"], "partial")
        self.assertIn(b.PART_WORDS["place"][0], result["problem"])
        self.assertIn("place", [row["kind"] for row in result["failures"]])

    def test_a_store_that_lists_no_tiles_is_unavailable_and_the_command_exits_zero(self):
        import contextlib
        cache, store = self._variant("no_tiles")
        index_path = store / "hail" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["tiles"] = []
        index_path.write_text(json.dumps(index), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            code = b.main(["build", "--store", str(store), "--cache", str(cache), "--offline"])
        self.assertEqual(code, 0)
        block = json.loads((store / b.INDEX_FILE).read_text(encoding="utf-8"))[b.PRODUCT]
        self.assertEqual(block["state"], "unavailable")
        self.assertEqual(block["problem"], b.WORDS["unavailable"])
        self.assertFalse((store / b.A_FILE).exists())
        self.assertEqual(b.verify(store)["note"], b.WORDS["unavailable"])

    def test_the_river_checks_run_when_only_band_d_water_failed(self):
        cache, store = self._variant("band_d_only")
        key = "box_" + "_".join(f"{v:g}" for v in TEST_BOX)
        (cache / b.page_name("nhd_large_lines", key, b.nhd_params("large_lines", TEST_BOX), 0)).unlink()
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["state"], "partial")
        rivers = [c for c in b.verify(store)["checks"] if c["check"].startswith("the river ")]
        self.assertEqual(len(rivers), len(b.RIVER_CHECK))
        self.assertTrue(all(not c["skipped"] and c["pass"] for c in rivers), rivers)

    def test_the_river_checks_are_skipped_when_the_small_scale_water_failed(self):
        cache, store = self._variant("small_water")
        (cache / b.page_name("nhd_small_lines", "mt", b.nhd_params("small_lines", b.MT_BOX), 0)).unlink()
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["state"], "partial")
        verdict = b.verify(store)
        rivers = [c for c in verdict["checks"] if c["check"].startswith("the river ")]
        self.assertTrue(rivers and all(c["skipped"] for c in rivers), rivers)
        self.assertTrue(verdict["ok"], [c for c in verdict["checks"] if not c["pass"]])

    def test_placeholder_park_names_keep_their_outline_and_get_no_label(self):
        cache, store = self._variant("placeholders")
        pages = json.loads(_fixture("padus_parks_page.json"))
        pages["features"] += [
            {"attributes": {"OBJECTID": 901, "Des_Tp": "SP", "Unit_Nm": "Montana Fish, Wildlife and Parks",
                            "Loc_Nm": "", "GIS_Acres": 50},
             "geometry": {"rings": [[[-113.0, 46.5], [-112.98, 46.5], [-112.98, 46.52], [-113.0, 46.52], [-113.0, 46.5]]]}},
            {"attributes": {"OBJECTID": 902, "Des_Tp": "LP", "Unit_Nm": "Unknown Park", "Loc_Nm": "", "GIS_Acres": 10},
             "geometry": {"rings": [[[-113.98, 46.85], [-113.97, 46.85], [-113.97, 46.86], [-113.98, 46.86], [-113.98, 46.85]]]}},
        ]
        (cache / b.page_name("padus", "mt", b.padus_params(), 0)).write_text(json.dumps(pages), encoding="utf-8")
        b.build(store, cache, offline=True, box=TEST_BOX)
        features = list(self._band_features(store))
        unnamed = [f for f in features if f["k"] == "park" and f["n"] == ""]
        self.assertTrue(unnamed, "an unnamed park keeps its outline")
        self.assertTrue(all(f["g"] and "l" not in f for f in unnamed))
        names = {f["n"] for f in features}
        self.assertNotIn("Montana Fish, Wildlife and Parks", names)
        self.assertNotIn("Unknown Park", names)

    def test_a_river_with_no_drainage_area_is_left_out_and_counted_and_a_park_with_no_acreage_has_no_size(self):
        cache, store = self._variant("no_area")
        lines = json.loads(_fixture("nhd_small_lines_page.json"))
        for feature in lines["features"]:
            if feature["attributes"]["GNIS_NAME"] == "Bitterroot River":
                feature["attributes"]["TotDASqKM"] = None
        (cache / b.page_name("nhd_small_lines", "mt", b.nhd_params("small_lines", b.MT_BOX), 0)).write_text(
            json.dumps(lines), encoding="utf-8")
        pages = json.loads(_fixture("padus_parks_page.json"))
        pages["features"].append({"attributes": {"OBJECTID": 905, "Des_Tp": "NP", "Unit_Nm": "Null Acreage National Park",
                                                 "Loc_Nm": "NULLA", "GIS_Acres": None},
                                  "geometry": {"rings": [[[-113.0, 48.2], [-112.8, 48.2], [-112.8, 48.3], [-113.0, 48.3],
                                                          [-113.0, 48.2]]]}})
        (cache / b.page_name("padus", "mt", b.padus_params(), 0)).write_text(json.dumps(pages), encoding="utf-8")
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["unusable"], {"rivers_no_drainage_area": 1, "parks_no_acreage": 1, "collapsed": 0})
        features = list(self._band_features(store))
        self.assertNotIn("Bitterroot River", {f["n"] for f in features})
        park = next(f for f in features if f["n"] == "Null Acreage National Park")
        self.assertIsNone(park["size"], "no acreage is null, never zero")

    def test_every_band_feature_carries_its_source_id_and_a_size(self):
        features = list(self._band_features(self.store))
        self.assertTrue(features)
        for f in features:
            self.assertIsInstance(f["id"], str)
            self.assertNotEqual(f["id"], "", f"{f['k']} {f['n']} has no source id")
            self.assertIn("size", f)
            self.assertTrue(f["size"] is None or f["size"] >= 0)
        mill = {f["id"] for f in features if f["n"] == "Mill Pond"}
        self.assertEqual(mill, {"2", "11"}, "two features with one name keep two source ids")

    def test_verify_names_the_route_park_and_glacier_checks_and_they_pass(self):
        by_name = {c["check"]: c for c in b.verify(self.store)["checks"]}
        for name in ("the files hold route shields for interstates, US routes and state routes",
                     "the files hold park outlines", "band A holds Glacier National Park"):
            self.assertIn(name, by_name)
            self.assertTrue(by_name[name]["pass"] and not by_name[name]["skipped"], by_name[name])


    def test_the_coverage_block_gives_counts_and_no_claim_the_counts_contradict(self):
        cov = json.loads((self.store / b.INDEX_FILE).read_text(encoding="utf-8"))[b.PRODUCT]["coverage"]
        self.assertNotIn("every listed tile", json.dumps(cov))
        self.assertEqual(cov["tiles_built"] + cov["tiles_unbuilt"], cov["tiles_in_coverage"])
        self.assertEqual(cov["tiles_built"], len(self.tiles))
        self.assertEqual(cov["band_d_areas"], 1, "the test box is one envelope")
        self.assertEqual((cov["band_d_failed_cells"], cov["band_d_failed_cell_count"]), ([], 0))
        self.assertEqual(cov["bands_a_to_c"], "every cell touching Montana")

    def test_a_tiny_park_moves_to_band_c_and_the_index_counts_the_move(self):
        cache, store = self._variant("moved")
        pages = json.loads(_fixture("padus_parks_page.json"))
        ring = square(math.sqrt(20_000.0), west=-113.0, south=46.5)
        pages["features"].append({"attributes": {"OBJECTID": 906, "Des_Tp": "SP", "Unit_Nm": "Tiny State Park",
                                                 "Loc_Nm": "Tiny State Park", "GIS_Acres": 4.94},
                                  "geometry": {"rings": [ring]}})
        (cache / b.page_name("padus", "mt", b.padus_params(), 0)).write_text(json.dumps(pages), encoding="utf-8")
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["moved"], {"park": {"B to C": 1}})
        self.assertEqual(result["unusable"]["collapsed"], 0)
        tiny = [(f["k"], f["z"], f["id"]) for f in self._band_features(store) if f["n"] == "Tiny State Park"]
        self.assertEqual(tiny, [("park", 11, "906")])
        block = json.loads((store / b.INDEX_FILE).read_text(encoding="utf-8"))[b.PRODUCT]
        self.assertEqual(block["moved"], {"park": {"B to C": 1}})

    def test_a_test_box_or_an_offline_build_deletes_nothing_from_the_cache(self):
        cache, store = self._variant("keep_cache")
        older = cache / "census" / "tl_2025_30_place.zip"
        older.write_bytes(_fixture("tl_2026_30_place_sample.zip"))
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertTrue(older.is_file())
        self.assertEqual(result["cache"], {"files": 0, "bytes": 0, "skipped": "offline build"})

    def test_a_check_that_did_not_run_is_not_checked_and_outside_the_pass_count(self):
        cache, store = self._variant("not_checked")
        (cache / b.page_name("nhd_small_lines", "mt", b.nhd_params("small_lines", b.MT_BOX), 0)).unlink()
        result = b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertEqual(result["state"], "partial")
        verdict = b.verify(store)
        skipped = [c for c in verdict["checks"] if c["skipped"]]
        ran = [c for c in verdict["checks"] if not c["skipped"]]
        self.assertTrue(skipped)
        self.assertTrue(ran)
        for c in skipped:
            self.assertEqual((c["state"], c["pass"]), ("not checked", None), c["check"])
            self.assertIn("not checked:", c["detail"])
        self.assertEqual(verdict["not_checked"], len(skipped))
        self.assertEqual((verdict["passed"], verdict["failed"]),
                         (sum(1 for c in ran if c["pass"]), sum(1 for c in ran if not c["pass"])))
        self.assertEqual(verdict["ok"], all(c["pass"] for c in ran))
        self.assertTrue(verdict["ok"], [c for c in ran if not c["pass"]])

    def test_a_shared_index_of_another_format_stops_the_build_before_any_change(self):
        cache, store = self._variant("foreign")
        path = store / b.INDEX_FILE
        path.write_text(json.dumps({"f": "hail-base-index-v9", "terrain": {"state": "loaded"}}), encoding="utf-8")

        def snapshot() -> dict:
            return {p.relative_to(store).as_posix(): p.read_bytes() for p in (store / "hail" / "base").rglob("*") if p.is_file()}

        before = snapshot()
        with self.assertRaises(b.BasemapError) as raised:
            b.build(store, cache, offline=True, box=TEST_BOX)
        self.assertIn("'hail-base-index-v9'", str(raised.exception))
        self.assertEqual(snapshot(), before, "no file of the base parts changed")
        verdict = b.verify(store)
        self.assertFalse(verdict["ok"])
        self.assertIn(f"hail/base/index.json is the shared format ({b.FORMAT_INDEX})",
                      [c["check"] for c in verdict["checks"] if not c["pass"]])


class NameAndScopeTests(unittest.TestCase):
    def test_a_national_unit_takes_its_unit_name_not_the_service_code(self):
        self.assertEqual(b.park_name("NP", {"UNIT_NM": "Glacier National Park", "LOC_NM": "GLAC"}),
                         "Glacier National Park")
        self.assertEqual(b.park_name("NRA", {"UNIT_NM": "Bighorn Canyon National Recreation Area", "LOC_NM": "BICA"}),
                         "Bighorn Canyon National Recreation Area")
        self.assertEqual(b.park_name("REC", {"UNIT_NM": "Fort Peck Recreation Area", "LOC_NM": "FORT PECK"}),
                         "Fort Peck Recreation Area")

    def test_other_parks_take_their_location_name_and_a_code_is_the_last_resort(self):
        self.assertEqual(b.park_name("SP", {"UNIT_NM": "Lone Pine", "LOC_NM": "Lone Pine State Park"}),
                         "Lone Pine State Park")
        self.assertEqual(b.park_name("LP", {"UNIT_NM": "Sacajawea", "LOC_NM": "Sacajawea Park"}), "Sacajawea Park")
        self.assertEqual(b.park_name("NP", {"UNIT_NM": "", "LOC_NM": "GLAC"}), "GLAC")

    def test_the_montana_test_agrees_for_many_points_and_for_one(self):
        points = [(-116.0 + i * 0.37, 44.5 + j * 0.27) for i in range(25) for j in range(20)]
        many = b.in_montana_many([p[0] for p in points], [p[1] for p in points])
        one = [b.in_montana(lon, lat) for lon, lat in points]
        self.assertEqual([bool(v) for v in many], one)
        self.assertIn(True, one)
        self.assertIn(False, one)

    def test_water_wholly_in_another_state_is_dropped_and_a_crossing_river_is_kept(self):
        items = [
            {"name": "Montana river", "parts": [[(-114.0, 46.9), (-113.9, 46.95)]]},
            {"name": "Idaho river", "parts": [[(-116.9, 47.0), (-116.8, 47.1)]]},
            {"name": "Crossing river", "parts": [[(-116.5, 47.5), (-114.9, 47.5)]]},
        ]
        self.assertEqual([i["name"] for i in b.keep_in_montana(items)], ["Montana river", "Crossing river"])
        self.assertEqual(b.keep_in_montana([]), [])

    def test_a_blank_or_placeholder_park_name_is_no_name(self):
        self.assertEqual(b.park_name("SP", {"UNIT_NM": "Montana Fish, Wildlife and Parks", "LOC_NM": ""}), "")
        self.assertEqual(b.park_name("LP", {"UNIT_NM": "Unknown Park", "LOC_NM": ""}), "")
        self.assertEqual(b.park_name("LP", {"UNIT_NM": "Unknown Park", "LOC_NM": "Sacajawea Park"}), "Sacajawea Park")
        self.assertEqual(b.park_name("SREC", {"UNIT_NM": "Montana Fish, Wildlife and Parks",
                                              "LOC_NM": "Broadwater Access"}), "Broadwater Access")


class JoinAndPieceTests(unittest.TestCase):
    def test_the_reaches_of_one_river_at_one_zoom_are_one_feature(self):
        def reach(total, path, oid):
            return {"name": "Test River", "total": total, "length": 10.0, "parts": [path], "oid": oid}
        inputs = {"rivers_small": [reach(4000.0, [(-114.0, 47.0), (-113.9, 47.0)], "12"),
                                   reach(3500.0, [(-113.9, 47.0), (-113.8, 47.0)], "7"),
                                   reach(500.0, [(-113.8, 47.0), (-113.7, 47.0)], "9")]}
        feats = b.build_features(inputs)
        band_a = [f for f in feats["A"] if f["n"] == "Test River"]
        self.assertEqual(len(band_a), 1, "two reaches at zoom 6 are one feature with two paths")
        self.assertEqual((band_a[0]["z"], len(band_a[0]["g"])), (6, 2))
        self.assertEqual(band_a[0]["id"], "7", "the joined feature takes the smallest id among its reaches")
        band_b = [f for f in feats["B"] if f["n"] == "Test River"]
        self.assertEqual([(f["z"], len(f["g"]), f["id"]) for f in band_b], [(8, 1, "9")],
                         "the reach at zoom 8 is its own feature")

    def test_areas_are_never_joined(self):
        ring = [(-114.0, 47.0), (-113.99, 47.0), (-113.99, 47.01), (-114.0, 47.01), (-114.0, 47.0)]
        recs = [b._rec("lake", "Twin Lake", 7, [ring], closed=True, size=1.0),
                b._rec("lake", "Twin Lake", 7, [ring], closed=True, size=1.0)]
        self.assertEqual(len(b._merge_lines(recs)), 2)

    def test_each_piece_carries_its_own_length_and_a_part_goes_only_where_it_lies(self):
        path_a = [(-114.5, 46.5), (-113.5, 46.5)]    # crosses the cell edge at 114 W
        path_b = [(-114.8, 46.7), (-114.6, 46.7)]    # lies in the west cell only
        feature = b.finish(b._rec("river", "Two Reaches", 9, [path_a, path_b], closed=False, size=99.0), 0.0)
        pieces = b._split([feature], b._cell_keys(1), lambda key: b.cell_box(key[0], key[1], 1))
        west, east = pieces[(46, -115)][0], pieces[(46, -114)][0]
        self.assertEqual(len(west["g"]), 2, "the west piece holds the west half of path A and path B")
        self.assertEqual(len(east["g"]), 1)
        self.assertAlmostEqual(west["size"], b.length_km(west["g"]), places=6)
        self.assertAlmostEqual(east["size"], b.length_km(east["g"]), places=6)
        self.assertLess(east["size"], 99.0)


class WordsTests(unittest.TestCase):
    def test_words_follow_the_house_rules(self):
        for key, text in b.WORDS.items():
            self.assertNotIn("\u2014", text, key)
            self.assertNotIn("\u2013", text, key)
        self.assertIn("This is not an all-clear.", b.WORDS["unavailable"])
        self.assertIn("that is not the same as no", b.WORDS["unavailable"])
        self.assertTrue(b.WORDS["peak_note"].endswith("is left out of the list, and the number left out is noted."))


class UnavailableWordingTests(unittest.TestCase):
    """B1 (D128(b), D117(b)): every sentence in WORDS that says a part of the map is unavailable or partial begins
    with "Data unavailable.", keeps its D20 wording and ends with "This is not an all-clear.". The notes that
    explain a value or a source (peak_note, place_note, route_note, water_note, park_note) do not say that a part is
    missing, so they keep their wording and do not begin with the words. The water line is the exception to the opening
    (D134(a)): its words sit inside the sentence, so the test checks them there (WORDS_INSIDE)."""

    CLOSING = "This is not an all-clear."
    STATUS = ("unavailable", "part_unavailable", "partial_named", "peaks_unknown", "population_unknown", "coverage_box",
              "band_d_water_partial", "water_line_unavailable")
    NOTES = ("peak_note", "place_note", "route_note", "water_note", "park_note")
    # D134(a): the water line begins "Detailed water and local parks:" and carries "Data unavailable for this area" inside it,
    # so it is the one status sentence exempt from the opening check; the body checks its words where they sit.
    WORDS_INSIDE = ("water_line_unavailable",)

    def test_every_status_sentence_begins_with_the_words_and_ends_with_the_all_clear(self):
        for key in self.STATUS:
            text = b.WORDS[key]
            if key in self.WORDS_INSIDE:
                self.assertIn("Data unavailable for this area", text, key)     # the exemption: the words sit inside the sentence
            else:
                self.assertTrue(text.startswith("Data unavailable. "), key)
            self.assertTrue(text.endswith(" " + self.CLOSING), key)
            self.assertEqual(text.count(self.CLOSING), 1, key)

    def test_every_words_key_is_either_a_status_sentence_or_a_note(self):
        self.assertEqual(sorted(b.WORDS), sorted(self.STATUS + self.NOTES))
        for key in self.NOTES:
            self.assertFalse(b.WORDS[key].startswith("Data unavailable."), key)

    def test_the_status_sentences_keep_their_wording_after_the_words(self):
        forest = b.PART_WORDS["forest"]
        self.assertEqual(b.WORDS["unavailable"],
                         "Data unavailable. Map outlines and names could not be loaded in this update; that is not the "
                         "same as no outline or name. This is not an all-clear.")
        self.assertEqual(b.WORDS["part_unavailable"].format(Part=forest[0], one=forest[1]),
                         "Data unavailable. Forest outlines could not be loaded in this update; that is not the same "
                         "as no forest outline. This is not an all-clear.")
        self.assertEqual(b.WORDS["partial_named"].format(names="forest outlines and park outlines"),
                         "Data unavailable. Some map outlines and names could not be loaded in this update for forest "
                         "outlines and park outlines; that is not the same as none there. This is not an all-clear.")
        self.assertEqual(b.WORDS["peaks_unknown"].format(count=2),
                         "Data unavailable. The height of 2 summits could not be read in this update; they are not "
                         "ranked, which is not the same as no height. This is not an all-clear.")
        self.assertEqual(b.WORDS["population_unknown"].format(count=3),
                         "Data unavailable. The 2020 population of 3 places could not be read in this update; they "
                         "show Data unavailable. This is not an all-clear.")
        self.assertEqual(b.WORDS["coverage_box"].format(area=b._box_words(TEST_BOX)),
                         "Data unavailable. Detailed lake, river and park outlines at zoom 13 and up are built only "
                         "for the tiles in the area from 114.1 W to 113.9 W and from 46.8 N to 47 N. Elsewhere the "
                         "browser keeps drawing band C's lakes and rivers at zoom 13 and up, and the sheet's water "
                         "line reads Data unavailable for that area. This is not an all-clear.")
        self.assertEqual(b.WORDS["band_d_water_partial"].format(failed=1, areas=2),
                         "Data unavailable. Detailed lake and river outlines at zoom 13 and up could not be loaded for "
                         "1 of 2 areas in this update; lakes and rivers at zooms 5 to 12 loaded statewide. This is not "
                         "an all-clear.")
        self.assertEqual(b.WORDS["water_line_unavailable"],
                         "Detailed water and local parks: Data unavailable for this area in this update. This is not "
                         "an all-clear.")


class CreditTests(unittest.TestCase):
    def test_every_source_has_a_credit_line_and_the_forest_terms_are_open(self):
        self.assertEqual(len(b.CREDIT), 7)
        self.assertTrue(any("U.S. Census Bureau" in c for c in b.CREDIT))
        self.assertTrue(any("3DEP data courtesy of the U.S. Geological Survey" in c for c in b.CREDIT))
        self.assertTrue(any("Forest" in c for c in b.CREDIT))
        self.assertIn("OPEN", b.__doc__)

    def test_the_tiger_credit_line_covers_the_place_names_too(self):
        line = "Source: U.S. Census Bureau, TIGER/Line 2026 (reservations, roads and place names)."   # B2 (D130(c))
        self.assertIn(line, b.CREDIT)
        self.assertFalse(any("(reservations and roads)" in c for c in b.CREDIT))
        self.assertIn('Credit: "' + line + '"', " ".join(b.__doc__.split()))   # the module text quotes the same line


class WordingAndCommandTests(unittest.TestCase):
    def test_every_failed_kind_is_named_with_no_count_and_no_cap(self):
        names = b._kinds_text(list(b.ALL_KINDS))
        for kind in b.ALL_KINDS:
            self.assertIn(b.PART_WORDS[kind][0].lower(), names)
        self.assertNotIn("more", names)
        self.assertNotIn("station", names)
        self.assertEqual(b._kinds_text(["forest"]), "forest outlines")
        self.assertEqual(b._kinds_text(["forest", "park"]), "forest outlines and park outlines")

    def test_a_box_is_said_in_words_with_degrees_and_order(self):
        self.assertEqual(b._box_words(TEST_BOX), "from 114.1 W to 113.9 W and from 46.8 N to 47 N")
        self.assertIn("{area}", b.WORDS["coverage_box"])

    def test_the_module_text_states_no_unrecorded_measures(self):
        for figure in ("54,026", "52,291", "121,622", "124 features"):
            self.assertNotIn(figure, b.__doc__)

    def test_the_3dep_statement_is_marked_as_a_secondary_copy(self):
        self.assertIn("secondary copy", b.__doc__)

    def test_the_mcdonald_peak_names_its_reference_and_both_listed_heights(self):
        source = b.PEAK_CHECK["source"]
        self.assertIn("Peakbagger peak 4705", source)
        self.assertIn("9,824 ft", source)
        self.assertIn("9,820 ft", source)
        self.assertNotIn("research record", source)
        self.assertEqual(b.PEAK_CHECK["also_listed_feet"], 9820)

    def test_the_forest_credit_line_is_the_agreed_wording(self):
        self.assertIn("Source: USDA Forest Service, forest boundaries (national forests).", b.CREDIT)

    def test_the_default_cache_is_beside_the_store(self):
        self.assertEqual(b.default_cache("/x/store"), Path("/x/basemap2-cache"))
        self.assertEqual(b.default_cache(Path("store")), Path("basemap2-cache"))

    def test_build_takes_no_cache_argument(self):
        self.assertIsNone(b.build_parser().parse_args(["build", "--store", "s"]).cache)



def box_tiles() -> list[str]:
    """The four B1 tiles that touch the test box (the same as the build tests' store)."""
    return sorted({hail.tile_name(*b.tile_of(lat, lon))
                   for lat in (TEST_BOX[1] + 0.01, TEST_BOX[3] - 0.01)
                   for lon in (TEST_BOX[0] + 0.01, TEST_BOX[2] - 0.01)})


def make_store(store: Path, tiles: list[str]) -> None:
    """A store folder with its store index (the tiles) and an empty manifest: where every build test starts."""
    (store / "hail").mkdir(parents=True, exist_ok=True)
    (store / "hail" / "index.json").write_text(json.dumps(
        {"format": "hail-store-v1", "as_of": "2026-10-16", "tiles": tiles}), encoding="utf-8")
    (store / "hail" / "manifest.json").write_text(json.dumps(
        {"format": "hail-manifest-v1", "files": {}, "counts": {}}), encoding="utf-8")


def square(side_m: float, west: float = -114.0, south: float = 46.9) -> list:
    """A square ring of the given side in metres, in longitude and latitude at the scale the build uses."""
    dlat, dlon = side_m / b._KY, side_m / b._KX
    return [[west, south], [west + dlon, south], [west + dlon, south + dlat], [west, south + dlat], [west, south]]


class CollapseTests(unittest.TestCase):
    """D122(c): a feature whose geometry collapses under its band's tolerance moves to the next finer band, its minimum
    zoom raised to that band's first zoom. One that collapses in band D, the finest band, is dropped and counted."""

    def test_a_tiny_park_collapses_at_band_b_and_is_drawn_in_band_c(self):
        ring = square(math.sqrt(20_000.0))                  # 0.02 km2: a square of about 141 m
        self.assertAlmostEqual(b.area_km2([ring]), 0.02, places=4)
        rec = b._rec("park", "Tiny Park", 9, [ring], closed=True, size=0.02, code="SP", oid="5")
        self.assertIsNone(b.finish(rec, b.BAND_TOL_M["B"]), "at 150 m the square has no shape left")
        self.assertIsNotNone(b.finish(rec, b.BAND_TOL_M["C"]), "at 50 m its corners stay")
        stats: dict = {}
        feats = b.build_features({"parks": [{"code": "SP", "name": "Tiny Park", "parts": [ring], "oid": "5", "size": 0.02}]},
                                 stats)
        self.assertEqual(stats, {"moved": {"park": {"B to C": 1}}, "collapsed": 0})
        self.assertEqual(feats["B"], [])
        self.assertEqual([(f["n"], f["z"], f["id"]) for f in feats["C"]], [("Tiny Park", 11, "5")])

    def test_a_feature_that_collapses_in_band_d_is_dropped_and_counted(self):
        sliver = [[-114.0, 47.0], [-113.99, 47.0], [-113.99, 47.0], [-114.0, 47.0]]     # two distinct points: no ring
        stats: dict = {}
        feats = b.build_features({"parks": [{"code": "LP", "name": "Sliver Park", "parts": [sliver], "oid": "9",
                                             "size": 0.0}]}, stats)
        self.assertEqual(feats["D"], [])
        self.assertEqual(stats, {"moved": {}, "collapsed": 1})

    def test_a_feature_that_keeps_its_shape_is_not_moved(self):
        stats: dict = {}
        feats = b.build_features({"parks": [{"code": "SP", "name": "Big Park", "parts": [square(1000.0)], "oid": "7",
                                             "size": 1.0}]}, stats)
        self.assertEqual([f["n"] for f in feats["B"]], ["Big Park"])
        self.assertEqual(stats, {"moved": {}, "collapsed": 0})


class PlacesTests(unittest.TestCase):
    """D122(f) and D112(h): the first-paint towns keep their names and zooms, and a place with no census count says why."""

    def test_the_twenty_first_paint_towns_keep_their_names_and_zooms(self):
        basemap = {p["name"]: p["min_zoom"] for p in b._basemap_places()}
        self.assertEqual(len(basemap), 20)
        tiger_name = {first: tiger for tiger, first in b.FIRST_PAINT_NAMES}
        rows = [{"name": tiger_name.get(name, name), "lat": 46.0, "lon": -112.0, "placefp": f"{i:05d}", "lsad": "25"}
                for i, name in enumerate(sorted(basemap))]
        by = {p["name"]: p for p in b.build_places(rows, {}, basemap)["places"]}
        self.assertEqual(set(by), set(basemap))
        for name, zoom in basemap.items():
            self.assertEqual((by[name]["min_zoom"], by[name]["zoom_rule"]), (zoom, "basemap"), name)
        self.assertEqual(dict(b.FIRST_PAINT_NAMES), {"Butte-Silver Bow (balance)": "Butte",
                                                     "Anaconda-Deer Lodge County": "Anaconda"})

    def test_a_place_with_no_census_count_says_why(self):
        rows = [{"name": "Sčilíp", "lat": 47.0, "lon": -110.0, "placefp": "66910", "lsad": "43"}]
        block = b.build_places(rows, {}, {})
        row = block["places"][0]
        self.assertIsNone(row["population"])
        self.assertEqual(row["reason"], "no census count under its code")
        self.assertEqual(row["zoom_rule"], "no population")
        self.assertEqual(block["population_unavailable"], 1)
        counted = b.build_places([dict(rows[0], name="Lolo", placefp="07150")], {"07150": 4399}, {})["places"][0]
        self.assertEqual((counted["population"], "reason" in counted), (4399, False))


class ShapefileReaderTests(unittest.TestCase):
    """Without pyshp the three kinds that read shapefiles are named failures with the reason 'the shapefile reader is not
    installed', the build finishes and the state is partial. The module is blocked for the build, so pyshp is not needed."""

    def test_a_missing_shapefile_reader_is_a_named_failure_and_the_build_finishes(self):
        tmp = Path(tempfile.mkdtemp(prefix="basemap2-noshp-"))
        try:
            cache, store = tmp / "cache", tmp / "store"
            stage_cache(cache)
            make_store(store, box_tiles())
            with mock.patch.dict(sys.modules, {"shapefile": None}):
                result = b.build(store, cache, offline=True, box=TEST_BOX)
            self.assertEqual(result["state"], "partial")
            reasons = {row["kind"]: row["reasons"] for row in result["failures"]}
            for kind in ("reservation", "route", "place"):
                self.assertIn(b.REASON_NO_SHAPEFILE, reasons[kind], kind)
            self.assertNotIn("forest", reasons, "the forest layer is read without pyshp and loads")
            self.assertIn("reservation outlines", result["problem"].lower())
            verdict = b.verify(store)
            self.assertTrue(verdict["ok"], [c for c in verdict["checks"] if not c["pass"] and not c["skipped"]])
            self.assertIn("band A holds the seven reservations", {c["check"] for c in verdict["checks"] if c["skipped"]})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SharedIndexTests(unittest.TestCase):
    """P2-R7 (P1-14): hail/base/index.json is one document shared by the three base parts. A new document starts with
    "f": "hail-base-index-v1"; each writer keeps the other blocks; a document of another format is refused and kept."""

    @staticmethod
    def _store() -> Path:
        store = Path(tempfile.mkdtemp(prefix="basemap2-shared-"))
        make_store(store, [])
        return store

    @staticmethod
    def _other_part_writes(store: Path, key: str, block: dict) -> None:
        """What the terrain and landmark parts do to the shared document: read it (a new one starts with the shared format
        key), replace their own key, and write it back. Their own tests cover their writers."""
        path = store / b.INDEX_FILE
        doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"f": b.FORMAT_INDEX}
        doc[key] = block
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding="utf-8")

    def test_a_new_document_starts_with_the_shared_format_key(self):
        store = self._store()
        try:
            b.write_index(store, {"state": "partial", "as_of": "2026-10-16"}, {})
            doc = json.loads((store / b.INDEX_FILE).read_text(encoding="utf-8"))
            self.assertEqual(list(doc)[0], "f")
            self.assertEqual(doc["f"], "hail-base-index-v1")
            self.assertNotIn("format", doc)
        finally:
            shutil.rmtree(store, ignore_errors=True)

    def test_the_three_blocks_survive_in_every_order(self):
        from website import landmarks, terrain
        self.assertEqual(terrain.BASE_INDEX_FORMAT, b.FORMAT_INDEX)
        self.assertEqual(landmarks.BASE_FORMAT, b.FORMAT_INDEX)
        blocks = {"terrain": {"state": "loaded", "as_of": "2026-10-16"},
                  "vector": {"state": "partial", "as_of": "2026-10-16"},
                  "landmarks": {"state": "loaded", "as_of": "2026-10-16"}}
        for order in itertools.permutations(("terrain", "vector", "landmarks")):
            store = self._store()
            try:
                for key in order:
                    if key == "vector":
                        b.write_index(store, blocks["vector"], {})
                    else:
                        self._other_part_writes(store, key, blocks[key])
                doc = json.loads((store / b.INDEX_FILE).read_text(encoding="utf-8"))
                self.assertEqual(doc["f"], b.FORMAT_INDEX, order)
                self.assertEqual({k: doc.get(k) for k in blocks}, blocks, order)
            finally:
                shutil.rmtree(store, ignore_errors=True)

    def test_a_document_of_another_format_is_refused_and_kept(self):
        store = self._store()
        try:
            path = store / b.INDEX_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            for foreign, shown in (({"format": "hail-base-index-v1", "terrain": {"state": "loaded"}}, "no format key"),
                                   ({"f": "hail-base-index-v2", "terrain": {}}, "'hail-base-index-v2'")):
                path.write_text(json.dumps(foreign), encoding="utf-8")
                before = path.read_bytes()
                with self.assertRaises(b.BasemapError) as raised:
                    b.write_index(store, {"state": "partial"}, {})
                self.assertIn(f"is not a hail-base-index-v1 document (its format key: {shown})", str(raised.exception))
                with self.assertRaises(b.BasemapError):
                    b.mark_unavailable(store, "a test reason")
                self.assertEqual(path.read_bytes(), before, "the file is kept, never discarded")
        finally:
            shutil.rmtree(store, ignore_errors=True)

    def test_the_command_line_reports_the_refusal_and_exits_one(self):
        import contextlib
        store = self._store()
        try:
            path = store / b.INDEX_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"format": "hail-base-index-v1"}), encoding="utf-8")
            before = path.read_bytes()
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = b.main(["unavailable", "--store", str(store), "--reason", "a test reason"])
            self.assertEqual(code, 1)
            self.assertIn("not a hail-base-index-v1 document", err.getvalue())
            self.assertEqual(path.read_bytes(), before)
        finally:
            shutil.rmtree(store, ignore_errors=True)


class CachePruneTests(unittest.TestCase):
    """P2-R6 (D112(m)): after a statewide online build with no failed request, the cache keeps the current cycle of each
    source and deletes the older files in the source folders. The plan is tested here; the build's own rule (an offline
    or test box build deletes nothing) is in the build tests."""

    def test_the_plan_keeps_the_current_cycle_and_deletes_the_older_files(self):
        cache = Path(tempfile.mkdtemp(prefix="basemap2-prune-"))
        try:
            env = b.cell_box(46, -114, 1)
            quarter_env, quarter_key = b._envelope_tree(env, "46_-114")[1]
            point = [(-113.9, 46.9)]
            current = {
                b.TIGER_AIANNH, b.TIGER_PRISEC, b.TIGER_PLACE, b.CENSUS_PL, b.GNIS_FILE,
                b.page_name("edw", "mt", b.forest_params(), 0),
                b.page_name("padus", "mt", b.padus_params(), 0),
                b.page_name("nhd_small_lines", "mt", b.nhd_params("small_lines", b.MT_BOX), 0),
                b.page_name("nhd_small_areas", "mt", b.nhd_params("small_areas", b.MT_BOX), 0),
                b.page_name("nhd_large_lines", "46_-114", b.nhd_params("large_lines", env), 1000),   # a later page
                b.page_name("nhd_large_lines", quarter_key, b.nhd_params("large_lines", quarter_env), 0),
                b.page_name("nhd_large_areas", "46_-114", b.nhd_params("large_areas", env), 0),
                b._sample_name(0, point),
            }
            older = {
                "census/tl_2025_30_place.zip",                                   # the 2025 release
                "edw/mt_0123456789_0000000.json",                                # an older query of the forests
                "nhd_large_lines/46_-114_0123456789_0000000.json",               # an older query of the same cell
                "nhd_large_lines/box_-114.1_46.8_-113.9_47_0000000000_0000000.json",   # a test box
                "3dep/samples_00000_0123456789ab.json",                          # an older batch of summits
            }
            for rel in current | older:
                path = cache / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x" * 10)
            (cache / "notes.txt").write_text("outside the source folders", encoding="utf-8")
            exact, prefixes = b.cache_plan([(env, "46_-114")], point)
            removed = b.prune_cache(cache, exact, prefixes)
            kept = {p.relative_to(cache).as_posix() for p in cache.rglob("*") if p.is_file()}
            self.assertEqual(kept, current | {"notes.txt"})
            self.assertEqual(removed, {"files": len(older), "bytes": 10 * len(older)})
        finally:
            shutil.rmtree(cache, ignore_errors=True)

    def test_a_body_that_fails_its_check_is_never_cached(self):
        cache = Path(tempfile.mkdtemp(prefix="basemap2-body-"))
        try:
            name = b.page_name("edw", "mt", b.forest_params(), 0)
            page = types.SimpleNamespace(status_code=200, content=b"<html>an error page</html>")
            with mock.patch("requests.get", return_value=page) as get, mock.patch("website.basemap2.time.sleep"):
                ctx = b._Ctx(cache, offline=False, refresh=False, deadline_at=None)
                data, state, reason = b.fetch(ctx, "edw", b.EDW_URL, name, b._check_features, params=b.forest_params())
            self.assertIsNone(data)
            self.assertEqual(state, "failed")
            self.assertEqual(get.call_count, b.ATTEMPTS)
            self.assertFalse((cache / name).exists(), "a body that fails its check is never written to the cache")
        finally:
            shutil.rmtree(cache, ignore_errors=True)


class DocumentWordingTests(unittest.TestCase):
    """The module text carries the agreed wording: the band D gap said both ways (D122(b)), the figures (D122), the terms and
    their counsel items (D114(b), D122(e)), the full-resolution reservation file (D115(e)), and the deadline and cache rules
    (D114(c), D112(m))."""

    def test_the_band_d_gap_is_said_both_ways(self):
        text = " ".join(b.__doc__.split())
        self.assertIn("not built, the browser draws band C's water there", text)
        self.assertIn("the browser keeps drawing band C's lakes and rivers at zoom 13 and up (they loaded statewide)", text)
        self.assertIn(b.WORDS["water_line_unavailable"], text)
        self.assertEqual(b.WORDS["water_line_unavailable"],
                         "Detailed water and local parks: Data unavailable for this area in this update. This is not "
                         "an all-clear.")

    def test_the_agreed_figures_and_terms_are_in_the_module_text(self):
        text = " ".join(b.__doc__.split())
        self.assertIn("in degrees to five decimals", text)
        self.assertNotIn("whole degrees", text)
        self.assertIn("the 1:500,000 cartographic file is never used", text)
        self.assertIn("17 U.S.C. 105", text)
        self.assertIn("(counsel item 23)", text)
        self.assertIn("(counsel item 24)", text)
        self.assertNotIn("before the layer ships", text)
        self.assertNotIn("held", text)

    def test_reservations_come_from_the_full_resolution_file(self):
        self.assertIn("TIGER2026/AIANNH/tl_2026_us_aiannh.zip", b.AIANNH_URL)
        self.assertNotIn("cb_", b.AIANNH_URL)

    def test_the_credit_lines_are_the_agreed_wording(self):
        for line in ("Source: U.S. Census Bureau, TIGER/Line 2026 (reservations, roads and place names).",
                     "Source: USDA Forest Service, forest boundaries (national forests).",
                     "Source: U.S. Geological Survey, National Hydrography Dataset (lakes and rivers).",
                     "3DEP data courtesy of the U.S. Geological Survey (summit heights)."):
            self.assertIn(line, b.CREDIT)

    def test_the_deadline_and_the_cache_rules_are_in_the_module_text(self):
        text = " ".join(b.__doc__.split())
        self.assertIn('the reason "deadline"', text)
        self.assertIn("The monthly job's step cap is 20 minutes", text)
        self.assertIn("After a statewide online build in which no request failed", text)
        self.assertIn('"f": "hail-base-index-v1"', text)


@unittest.skipUnless(HAVE_SHAPEFILE, "pyshp is not installed")
class ResumeAndDeadlineTests(unittest.TestCase):
    """P2-R1 and P2-R2 (D114): a second run fetches only the cell that failed; a deadline makes no request and lists the cells
    it left as unbuilt with the reason 'deadline', and the cells whose pages are cached are still built."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="basemap2-resume-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _folder(self, name: str) -> tuple[Path, Path]:
        cache, store = self.tmp / f"cache_{name}", self.tmp / f"store_{name}"
        stage_cache(cache)
        make_store(store, box_tiles())
        return cache, store

    def test_a_second_run_fetches_only_the_cell_that_failed(self):
        cache, store = self._folder("resume")
        key = "box_" + "_".join(f"{v:g}" for v in TEST_BOX)
        page = cache / b.page_name("nhd_large_lines", key, b.nhd_params("large_lines", TEST_BOX), 0)
        answered = page.read_bytes()
        page.unlink()                                               # the one failing cell: its page is not in the cache
        down = types.SimpleNamespace(status_code=504, content=b"")
        with mock.patch("requests.get", return_value=down) as first, mock.patch("website.basemap2.time.sleep"):
            before = b.build(store, cache, offline=False, box=TEST_BOX)
        self.assertEqual(before["counts"]["tiles_built"], 0)
        self.assertGreater(first.call_count, 0)
        self.assertTrue(all("/6/query" in c.args[0] for c in first.call_args_list), "only the large-scale lines were asked")
        up = types.SimpleNamespace(status_code=200, content=answered)
        with mock.patch("requests.get", return_value=up) as second, mock.patch("requests.post") as post, \
                mock.patch("website.basemap2.time.sleep"):
            after = b.build(store, cache, offline=False, box=TEST_BOX)
        self.assertEqual(second.call_count, 1, [c.args[0] for c in second.call_args_list])
        self.assertIn("/6/query", second.call_args.args[0])
        self.assertEqual(post.call_count, 0, "the 3DEP batches are in the cache")
        self.assertEqual(after["counts"]["tiles_built"], len(box_tiles()))
        self.assertGreater(after["counts"]["tiles_built"], before["counts"]["tiles_built"])

    def test_a_deadline_makes_no_request_and_lists_the_cells_it_left(self):
        cache, store = self._folder("deadline")
        west = hail.tile_name(*b.tile_of(46.5, -114.5))           # a tile in the cell to the west: no water cached
        index_path = store / "hail" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["tiles"] = sorted(set(index["tiles"]) | {west})
        index_path.write_text(json.dumps(index), encoding="utf-8")
        env = b.cell_box(46, -114, 1)                             # the Missoula cell: its pages are cached under its key
        for source, fixture in (("large_lines", "nhd_large_lines_page.json"), ("large_areas", "nhd_large_areas_page.json")):
            path = cache / b.page_name(f"nhd_{source}", "46_-114", b.nhd_params(source, env), 0)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_fixture(fixture))
        stop = AssertionError("a request was made after the deadline")
        with mock.patch("requests.get", side_effect=stop) as get, mock.patch("requests.post", side_effect=stop), \
                mock.patch("website.basemap2.time.sleep"):
            result = b.build(store, cache, offline=False, deadline_at=time.monotonic() - 1.0)
        self.assertEqual(get.call_count, 0)
        self.assertEqual(result["state"], "partial")
        block = json.loads((store / b.INDEX_FILE).read_text(encoding="utf-8"))[b.PRODUCT]
        self.assertEqual(block["coverage"]["band_d_cell_reasons"], {"46_-115": "deadline"})
        self.assertEqual(block["coverage"]["band_d_areas"], 2)
        # the cached cell builds the tiles it covers; the cell to the west, which the deadline left, holds the rest (the
        # test box straddles the 114 W line, so two of its tiles are in that cell, and the tile added is the third)
        built = sorted(b.tiles_for_bbox(env, set(index["tiles"])))
        self.assertEqual(len(built), 2)
        self.assertEqual(block["coverage"]["tiles_built"], len(built))
        self.assertEqual(block["coverage"]["tiles_unbuilt"], len(index["tiles"]) - len(built))
        self.assertIn(b.WORDS["band_d_water_partial"].format(failed=1, areas=2), result["problem"])
        self.assertEqual(sorted(p.stem for p in (store / b.W_PREFIX).glob("*.json")), built)
        self.assertTrue(b.verify(store)["ok"])


if __name__ == "__main__":
    unittest.main()
