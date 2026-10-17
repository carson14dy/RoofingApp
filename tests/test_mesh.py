"""Hail footprints from synthetic grids (website/mesh.py). Offline: no pygrib, no network.

Most tests use unit cells with the north edge at y=3 and the west edge at x=0, so row r spans
latitude 2-r..3-r and column c spans longitude c..c+1 (outlines are easy to read by eye).
"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import mesh  # noqa: E402

WHEN = datetime(2026, 10, 15, 0, 0, 42, tzinfo=timezone.utc)
UNIT = {"north": 3.0, "west": 0.0, "cell_deg": 1.0}


def fp(grid, sizes=(1.0,), when=WHEN, **kw):
    return mesh.footprint(grid, when, list(sizes), **{**UNIT, **kw})


def ring_area(ring):
    """Absolute planar area of one closed ring of [lon, lat] pairs (degrees squared)."""
    pts = np.asarray(ring, dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    return abs(float(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1])) / 2)


def signed_area(ring):
    pts = np.asarray(ring, dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    return float(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1])) / 2


def shape_area(geometry):
    """Area of a Polygon or MultiPolygon: outer rings minus their holes."""
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    total = 0.0
    for rings in polygons:
        total += ring_area(rings[0]) - sum(ring_area(hole) for hole in rings[1:])
    return total


def polygons_of(feature):
    g = feature["geometry"]
    return [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]


class OneCell(unittest.TestCase):
    def test_one_cell_is_one_square(self):
        out = fp([[30.0]])
        self.assertEqual(out["type"], "FeatureCollection")
        self.assertEqual(len(out["features"]), 1)
        feature = out["features"][0]
        self.assertEqual(feature["geometry"]["type"], "Polygon")
        ring = feature["geometry"]["coordinates"][0]
        self.assertEqual(len(ring), 5)                       # four corners and the closing point
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(sorted({p[0] for p in ring}), [0.0, 1.0])
        self.assertEqual(sorted({p[1] for p in ring}), [2.0, 3.0])
        self.assertAlmostEqual(shape_area(feature["geometry"]), 1.0)

    def test_row_zero_is_the_north_edge(self):
        out = fp([[0.0], [30.0]])                           # the hail is in row 1, the southern row
        ring = out["features"][0]["geometry"]["coordinates"][0]
        self.assertEqual(sorted({p[1] for p in ring}), [1.0, 2.0])

    def test_outer_ring_counter_clockwise(self):
        ring = fp([[30.0]])["features"][0]["geometry"]["coordinates"][0]
        self.assertGreater(signed_area(ring), 0)            # RFC 7946: outer rings are counter-clockwise


class Groups(unittest.TestCase):
    def test_edge_touching_cells_join_into_one_polygon(self):
        out = fp([[30.0, 30.0]])
        self.assertEqual(len(out["features"]), 1)
        feature = out["features"][0]
        self.assertEqual(feature["properties"]["cells"], 2)
        self.assertEqual(len(feature["geometry"]["coordinates"][0]), 5)   # a 2 x 1 rectangle
        self.assertAlmostEqual(shape_area(feature["geometry"]), 2.0)

    def test_corner_touching_cells_stay_apart(self):
        out = fp([[30.0, 0.0], [0.0, 30.0]])
        self.assertEqual(len(out["features"]), 2)
        for feature in out["features"]:
            self.assertEqual(feature["properties"]["cells"], 1)
            self.assertAlmostEqual(shape_area(feature["geometry"]), 1.0)

    def test_separate_groups_get_separate_features(self):
        out = fp([[30.0, 0.0, 30.0]])
        self.assertEqual([f["properties"]["cells"] for f in out["features"]], [1, 1])


class Holes(unittest.TestCase):
    def test_hole_becomes_an_interior_ring(self):
        grid = [[30.0, 30.0, 30.0], [30.0, 0.0, 30.0], [30.0, 30.0, 30.0]]
        out = fp(grid)
        self.assertEqual(len(out["features"]), 1)
        geometry = out["features"][0]["geometry"]
        self.assertEqual(geometry["type"], "Polygon")
        outer, hole = geometry["coordinates"]
        self.assertGreater(signed_area(outer), 0)           # counter-clockwise outer ring
        self.assertLess(signed_area(hole), 0)                # clockwise hole
        self.assertAlmostEqual(shape_area(geometry), 8.0)   # 9 cells less the hole
        self.assertEqual(out["features"][0]["properties"]["cells"], 8)

    def test_nodata_inside_a_ring_is_a_hole_too(self):
        grid = [[30.0, 30.0, 30.0], [30.0, -3.0, 30.0], [30.0, 30.0, 30.0]]
        geometry = fp(grid)["features"][0]["geometry"]
        self.assertEqual(len(geometry["coordinates"]), 2)
        self.assertAlmostEqual(shape_area(geometry), 8.0)

    def test_hole_touching_the_outside_at_a_corner(self):
        # The centre cell is a hole whose corner touches the empty top-left cell. The outline must
        # still be two simple rings with the right area (7 cells), not one tangled ring.
        grid = [[0.0, 30.0, 30.0], [30.0, 0.0, 30.0], [30.0, 30.0, 30.0]]
        out = fp(grid)
        self.assertEqual(len(out["features"]), 1)
        geometry = out["features"][0]["geometry"]
        self.assertEqual(geometry["type"], "Polygon")
        for ring in geometry["coordinates"]:
            self.assertEqual(len({tuple(p) for p in ring[:-1]}), len(ring) - 1)   # no repeated vertex
        self.assertAlmostEqual(shape_area(geometry), 7.0)


class Missing(unittest.TestCase):
    def test_nodata_at_the_grid_edge_is_never_hail(self):
        grid = [[-1.0, 30.0, 30.0], [-3.0, 30.0, 30.0]]
        out = fp(grid)
        self.assertEqual(len(out["features"]), 1)
        geometry = out["features"][0]["geometry"]
        self.assertAlmostEqual(shape_area(geometry), 4.0)
        xs = [p[0] for p in geometry["coordinates"][0]]
        self.assertEqual(min(xs), 1.0)                       # the outline starts at column 1

    def test_missing_values_of_every_kind(self):
        grid = [[None, float("nan"), float("inf"), -1.0, -3.0, -0.5, 30.0]]
        out = fp(grid)
        self.assertEqual([f["properties"]["cells"] for f in out["features"]], [1])
        self.assertEqual(out["features"][0]["geometry"]["coordinates"][0][0][0], 6.0)

    def test_custom_nodata_flag_is_missing(self):
        out = fp([[9999.0, 30.0]], nodata=(9999.0,))
        self.assertEqual([f["properties"]["cells"] for f in out["features"]], [1])
        self.assertEqual(out["features"][0]["geometry"]["coordinates"][0][0][0], 1.0)

    def test_no_nodata_flags_means_only_negative_values_are_missing(self):
        out = fp([[9999.0]], nodata=())
        self.assertEqual(len(out["features"]), 1)            # 9999 mm is a size when nothing flags it


class Thresholds(unittest.TestCase):
    def test_value_exactly_at_the_threshold_counts(self):
        grid = np.array([[25.4, 25.3, 25.39]], dtype=np.float32)   # 1.0 in, float32 rounding included
        out = fp(grid, sizes=[1.0])
        self.assertEqual([f["properties"]["cells"] for f in out["features"]], [1])
        self.assertEqual(out["features"][0]["geometry"]["coordinates"][0][0][0], 0.0)

    def test_exact_threshold_for_a_size_that_is_not_a_clean_float(self):
        size = 88.1 / 25.4                                  # back to 88.1 mm, with float64 round-off
        grid = np.array([[88.1, 88.0]], dtype=np.float32)   # 88.1 is stored as 88.09999847 in float32
        out = fp(grid, sizes=[size])
        self.assertEqual(len(out["features"]), 1)
        self.assertEqual(out["features"][0]["properties"]["cells"], 1)
        self.assertEqual(out["features"][0]["geometry"]["coordinates"][0][0][0], 0.0)

    def test_thresholds_nest(self):
        grid = [[30.0, 60.0]]
        out = fp(grid, sizes=[1.0, 2.0])
        counts = [(f["properties"]["threshold_in"], f["properties"]["cells"]) for f in out["features"]]
        self.assertEqual(counts, [(1.0, 2), (2.0, 1)])      # 60 mm is 2.36 in; 30 mm is 1.18 in

    def test_threshold_properties(self):
        feature = fp([[40.0]], sizes=[1.5], window_minutes=30)["features"][0]   # 40 mm >= 38.1 mm
        self.assertEqual(feature["properties"], {
            "kind": "radar estimate", "threshold_in": 1.5, "threshold_mm": 38.1,
            "valid_time": "2026-10-15T00:00:42Z", "resolution_deg": 1.0, "cells": 1,
            "window_minutes": 30})

    def test_no_window_property_unless_given(self):
        feature = fp([[30.0]])["features"][0]
        self.assertNotIn("window_minutes", feature["properties"])


class Empty(unittest.TestCase):
    def test_all_missing_grid_is_an_empty_collection(self):
        out = fp([[-1.0, -3.0], [-1.0, -3.0]])
        self.assertEqual(out["type"], "FeatureCollection")
        self.assertEqual(out["features"], [])
        self.assertEqual(out["valid_time"], "2026-10-15T00:00:42Z")

    def test_zero_size_grids_are_empty_not_errors(self):
        self.assertEqual(fp([])["features"], [])
        self.assertEqual(fp(np.zeros((0, 0)))["features"], [])
        self.assertEqual(fp([[]])["features"], [])

    def test_no_sizes_is_an_empty_collection(self):
        self.assertEqual(fp([[30.0]], sizes=[])["features"], [])

    def test_no_hail_at_or_above_the_size_is_empty_not_missing(self):
        self.assertEqual(fp([[0.0, 0.8]], sizes=[1.0])["features"], [])


class Inputs(unittest.TestCase):
    def test_numpy_and_list_grids_agree(self):
        grid = [[30.0, -1.0], [60.0, 30.0]]
        self.assertEqual(json.dumps(fp(grid, sizes=[1.0, 2.0])),
                         json.dumps(fp(np.array(grid), sizes=[1.0, 2.0])))

    def test_utc_conversion_of_valid_time(self):
        mountain = timezone(timedelta(hours=-6))
        out = fp([[30.0]], when=datetime(2026, 10, 14, 18, 0, 42, tzinfo=mountain))
        self.assertEqual(out["valid_time"], "2026-10-15T00:00:42Z")

    def test_bad_inputs_raise_value_error(self):
        cases = [
            ("naive time", lambda: mesh.footprint([[30.0]], datetime(2026, 10, 15), [1.0], **UNIT)),
            ("zero size", lambda: fp([[30.0]], sizes=[0])),
            ("negative size", lambda: fp([[30.0]], sizes=[-1.0])),
            ("nan size", lambda: fp([[30.0]], sizes=[float("nan")])),
            ("one size, not a list", lambda: mesh.footprint([[30.0]], WHEN, 1.0, **UNIT)),
            ("ragged rows", lambda: fp([[1.0, 2.0], [3.0]])),
            ("three dimensions", lambda: fp(np.zeros((2, 2, 2)))),
            ("zero window", lambda: fp([[30.0]], window_minutes=0)),
            ("zero cell size", lambda: fp([[30.0]], cell_deg=0.0)),
        ]
        for name, call in cases:
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    call()


class MrmsGrid(unittest.TestCase):
    def test_default_grid_is_the_mrms_conus_grid(self):
        feature = mesh.footprint([[30.0]], WHEN, [1.0])["features"][0]
        ring = feature["geometry"]["coordinates"][0]
        self.assertEqual(min(p[0] for p in ring), -130.0)
        self.assertEqual(max(p[0] for p in ring), -129.99)
        self.assertEqual(min(p[1] for p in ring), 54.99)
        self.assertEqual(max(p[1] for p in ring), 55.0)
        self.assertEqual(feature["properties"]["resolution_deg"], 0.01)


class Random(unittest.TestCase):
    def test_outline_area_equals_cell_count_on_random_grids(self):
        rng = np.random.default_rng(20261016)
        for trial in range(20):
            rows, cols = rng.integers(3, 30, size=2)
            grid = np.where(rng.random((rows, cols)) < 0.55,
                            rng.choice([-1.0, -3.0, 0.8, 12.7, 25.4, 44.5, 60.0], size=(rows, cols)),
                            -1.0).astype(np.float64)
            grid = np.where(grid > 0, np.round(grid * 10) / 10, grid)
            sizes = [0.5, 1.0, 1.75]
            out = mesh.footprint(grid, WHEN, sizes, north=float(rows), west=0.0, cell_deg=1.0)
            for size in sizes:
                want = int(np.count_nonzero(grid >= size * 25.4 - 1e-4))
                got = [f for f in out["features"] if f["properties"]["threshold_in"] == size]
                with self.subTest(trial=trial, size=size):
                    self.assertEqual(sum(f["properties"]["cells"] for f in got), want)
                    self.assertAlmostEqual(sum(shape_area(f["geometry"]) for f in got), want)
                    for f in got:
                        for rings in polygons_of(f):
                            for ring in rings:
                                self.assertEqual(ring[0], ring[-1])
                                self.assertEqual(len({tuple(p) for p in ring[:-1]}), len(ring) - 1)


if __name__ == "__main__":
    unittest.main()
