"""Offline unit tests for mrms_volume.py (synthetic data only; no network).

Run from research/globe/prototype:
    python -m unittest discover -s tests -v

The decode test writes one small GRIB2 file with eccodes into a temporary directory, and skips
when eccodes is not importable. Nothing here downloads from the bucket.
"""

import contextlib
import datetime as dt
import gzip
import io
import json
import math
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mrms_volume as mv  # noqa: E402

UTC = dt.timezone.utc
G = mv.MRMS_GRID


def at(hour, minute, second, day=(2026, 10, 17)):
    return dt.datetime(day[0], day[1], day[2], hour, minute, second, tzinfo=UTC)


def obj(km, when, size=1000):
    return mv.Obj(km=km, key=mv.object_key(km, when), size=size, time=when, last_modified="")


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def try_eccodes():
    try:
        import eccodes  # noqa: F401
        return True
    except Exception:
        return False


HAVE_ECCODES = try_eccodes()


class GridFacts(unittest.TestCase):
    """Grid constants against validation-evidence/mrms.json (eccodes header decode)."""

    def test_grid_matches_recorded_facts(self):
        self.assertEqual((G.ni, G.nj), (7000, 3500))
        self.assertAlmostEqual(G.lat0, 54.995)
        self.assertAlmostEqual(G.lon0, -129.995)     # 230.005 E in the GRIB2 header
        self.assertAlmostEqual(G.dx, 0.01)
        self.assertAlmostEqual(G.dy, 0.01)

    def test_last_point_matches_recorded_facts(self):
        self.assertAlmostEqual(G.lat_of_row(G.nj - 1), 20.005)
        self.assertAlmostEqual(G.lon_of_col(G.ni - 1), -60.005)   # 299.995 E

    def test_billings_index_matches_recorded_facts(self):
        # mrms.json: Billings nearest point is row 921, column 2149, flat index 6,449,149.
        row = round((G.lat0 - 45.7833) / G.dy)
        col = round((-108.5007 - G.lon0) / G.dx)
        self.assertEqual((row, col), (921, 2149))
        self.assertEqual(G.flat_index(row, col), 6449149)

    def test_billings_distance_matches_recorded_value(self):
        # mrms.json: 0.383 km from Billings to that point.
        d = haversine_km(45.7833, -108.5007, G.lat_of_row(921), G.lon_of_col(2149))
        self.assertAlmostEqual(d, 0.383, delta=0.01)


class CropIndices(unittest.TestCase):
    def test_default_montana_border_crop(self):
        c = mv.crop_for_bbox(mv.DEFAULT_BBOX)
        self.assertEqual((c.i0, c.i1, c.j0, c.j1), (1320, 2669, 525, 1139))
        self.assertEqual((c.nx, c.ny), (1350, 615))
        self.assertFalse(c.clipped)

    def test_first_and_last_cells_are_inside_and_neighbours_outside(self):
        lon_min, lat_min, lon_max, lat_max = mv.DEFAULT_BBOX
        c = mv.crop_for_bbox(mv.DEFAULT_BBOX)
        self.assertGreaterEqual(G.lon_of_col(c.i0), lon_min)
        self.assertLessEqual(G.lon_of_col(c.i1), lon_max)
        self.assertLessEqual(G.lat_of_row(c.j0), lat_max)
        self.assertGreaterEqual(G.lat_of_row(c.j1), lat_min)
        self.assertLess(G.lon_of_col(c.i0 - 1), lon_min)
        self.assertGreater(G.lon_of_col(c.i1 + 1), lon_max)
        self.assertGreater(G.lat_of_row(c.j0 - 1), lat_max)
        self.assertLess(G.lat_of_row(c.j1 + 1), lat_min)

    def test_crop_is_index_arithmetic_on_a_small_grid(self):
        small = mv.GridSpec(ni=60, nj=50, lat0=46.0, lon0=-112.0, dx=0.05, dy=0.05)
        full = np.arange(small.ni * small.nj, dtype=np.float64).reshape(small.nj, small.ni)
        bbox = (-111.0, 44.5, -109.5, 45.8)
        c = mv.crop_for_bbox(bbox, small)
        # Both box edges sit exactly on cell centres, so both edge cells are included.
        self.assertEqual((c.i0, c.i1, c.j0, c.j1), (20, 50, 4, 30))
        sub = full[c.j0:c.j1 + 1, c.i0:c.i1 + 1]
        self.assertEqual(sub.shape, (c.ny, c.nx))
        self.assertEqual(sub[0, 0], small.flat_index(c.j0, c.i0))
        self.assertEqual(sub[-1, -1], small.flat_index(c.j1, c.i1))
        self.assertAlmostEqual(small.lon_of_col(c.i0), -111.0)
        self.assertAlmostEqual(small.lat_of_row(c.j1), 44.5)

    def test_partly_outside_box_is_clipped_and_flagged(self):
        c = mv.crop_for_bbox((-130.0, 30.0, -125.0, 40.0))
        self.assertEqual(c.i0, 0)
        self.assertTrue(c.clipped)

    def test_box_outside_the_grid_is_refused(self):
        with self.assertRaises(ValueError):
            mv.crop_for_bbox((-100.0, 10.0, -99.0, 11.0))

    def test_inverted_box_is_refused(self):
        with self.assertRaises(ValueError):
            mv.crop_for_bbox((-103.3, 43.6, -116.8, 49.75))


class Arguments(unittest.TestCase):
    def test_default_levels_are_the_eleven_requested(self):
        self.assertEqual(mv.parse_levels(mv.DEFAULT_LEVELS_TEXT),
                         (0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0))

    def test_all_is_thirty_three_levels_with_bucket_tags(self):
        levels = mv.parse_levels("all")
        self.assertEqual(len(levels), 33)
        self.assertEqual(mv.level_tag(0.5), "00.50")
        self.assertEqual(mv.level_tag(0.75), "00.75")
        self.assertEqual(mv.level_tag(10.0), "10.00")
        self.assertEqual(mv.level_tag(19.0), "19.00")
        self.assertEqual(sum(1 for v in levels if v <= 3.0), 11)     # 0.25 km steps to 3 km
        self.assertEqual(sum(1 for v in levels if 3.0 < v <= 9.0), 12)  # 0.5 km steps to 9 km
        self.assertEqual(sum(1 for v in levels if v > 9.0), 10)      # 1 km steps to 19 km

    def test_unknown_level_is_refused(self):
        with self.assertRaises(ValueError):
            mv.parse_levels("0.6")

    def test_time_argument(self):
        self.assertIsNone(mv.parse_time("latest"))
        self.assertEqual(mv.parse_time("20250615-231241"), dt.datetime(2025, 6, 15, 23, 12, 41, tzinfo=UTC))
        with self.assertRaises(ValueError):
            mv.parse_time("2025-06-15 23:12")

    def test_threshold_must_sit_above_the_sentinels(self):
        self.assertEqual(mv.validate_threshold(20), 20.0)
        for bad in (-90.0, -99.0, -999.0, float("nan"), float("inf")):
            with self.subTest(threshold=bad), self.assertRaises(ValueError):
                mv.validate_threshold(bad)

    def test_default_bbox_parses(self):
        self.assertEqual(mv.parse_bbox("-116.8,43.6,-103.3,49.75"), mv.DEFAULT_BBOX)
        with self.assertRaises(ValueError):
            mv.parse_bbox("-116.8,43.6,-103.3")


class ObjectNames(unittest.TestCase):
    def test_parse_object_name(self):
        key = ("CONUS/MergedReflectivityQC_00.50/20261017/"
               "MRMS_MergedReflectivityQC_00.50_20261017-020439.grib2.gz")
        self.assertEqual(mv.parse_object_key(key), (0.5, at(2, 4, 39)))

    def test_object_key_matches_the_bucket_name(self):
        self.assertEqual(mv.object_key(3.0, dt.datetime(2025, 6, 15, 23, 12, 41, tzinfo=UTC)),
                         "CONUS/MergedReflectivityQC_03.00/20250615/"
                         "MRMS_MergedReflectivityQC_03.00_20250615-231241.grib2.gz")

    def test_other_products_are_refused(self):
        with self.assertRaises(ValueError):
            mv.parse_object_key("CONUS/MESH_00.50/20261017/MRMS_MESH_00.50_20261017-020439.grib2.gz")

    def test_hour_prefix(self):
        self.assertEqual(mv.hour_prefix(3.0, dt.datetime(2025, 6, 15, 23, 12, 41, tzinfo=UTC)),
                         "CONUS/MergedReflectivityQC_03.00/20250615/MRMS_MergedReflectivityQC_03.00_20250615-23")


class NearestJoin(unittest.TestCase):
    def test_jitter_picks_the_file_within_sixty_seconds(self):
        # mrms.json: on one step 00.50 is stamped 00:18:38 and the other levels 00:18:40.
        target = at(0, 18, 40)
        self.assertEqual(mv.nearest_within([obj(0.5, at(0, 18, 38)), obj(0.5, at(0, 20, 38))], target).time,
                         at(0, 18, 38))
        self.assertEqual(mv.nearest_within([obj(3.0, at(0, 18, 40))], target).time, target)
        # A file two minutes earlier is another step, so it is not joined.
        self.assertIsNone(mv.nearest_within([obj(6.0, at(0, 16, 40))], target))

    def test_exactly_sixty_seconds_joins_and_ties_go_to_the_earlier_file(self):
        target = at(0, 20, 40)
        found = mv.nearest_within([obj(3.0, at(0, 19, 40)), obj(3.0, at(0, 21, 40))], target)
        self.assertEqual(found.time, at(0, 19, 40))
        self.assertIsNone(mv.nearest_within([obj(3.0, at(0, 19, 39))], target))

    def test_latest_skips_a_level_that_is_not_yet_published(self):
        per_level = {
            0.5: [obj(0.5, at(2, 26, 41)), obj(0.5, at(2, 28, 41))],
            3.0: [obj(3.0, at(2, 26, 40)), obj(3.0, at(2, 28, 40))],
            19.0: [obj(19.0, at(2, 26, 39))],       # 02:28:41 is not published yet on 19 km
        }
        when, picks = mv.latest_common_step(per_level, [0.5, 3.0, 19.0])
        self.assertEqual(when, at(2, 26, 41))
        self.assertEqual(picks[19.0].time, at(2, 26, 39))

    def test_latest_takes_the_newest_common_step(self):
        per_level = {0.5: [obj(0.5, at(2, 26, 41)), obj(0.5, at(2, 28, 41))],
                     3.0: [obj(3.0, at(2, 28, 40))]}
        when, _ = mv.latest_common_step(per_level, [0.5, 3.0])
        self.assertEqual(when, at(2, 28, 41))

    def test_latest_is_none_when_no_step_is_common(self):
        per_level = {0.5: [obj(0.5, at(2, 28, 41))], 3.0: []}
        self.assertEqual(mv.latest_common_step(per_level, [0.5, 3.0]), (None, {}))


class CodesAndVoxels(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(20261017)
        arr = rng.uniform(-15.0, 70.0, size=(60, 90))
        m999 = rng.random(arr.shape) < 0.2
        m99 = (rng.random(arr.shape) < 0.1) & ~m999
        arr[m999] = -999.0
        arr[m99] = -99.0
        arr[0, :5] = np.nan
        self.arr = arr

    def test_threshold_count_parity_with_numpy(self):
        # Predeclared metric threshold_count_parity: inclusive >= counts, zero difference required.
        for thr in (20.0, 35.0, 50.0):
            with self.subTest(threshold=thr):
                voxels = mv.level_voxels(self.arr, 0, thr)
                self.assertEqual(len(voxels), int(np.count_nonzero(self.arr >= thr)))

    def test_voxels_point_at_their_source_cells_with_declared_rounding(self):
        for i, j, k, v in mv.level_voxels(self.arr, 2, 35.0):
            self.assertEqual(k, 2)
            self.assertGreaterEqual(self.arr[j, i], 35.0)
            self.assertEqual(v, mv.round_half_step(self.arr[j, i]))

    def test_sentinels_never_become_voxels_or_zero(self):
        # Threshold -80 is the lowest allowed: sentinels at -99 and -999 are still excluded.
        voxels = mv.level_voxels(self.arr, 0, -80.0)
        sentinel_cells = set(zip(*(idx.tolist() for idx in np.nonzero(self.arr < -90))))
        for i, j, _, v in voxels:
            self.assertNotIn((j, i), sentinel_cells)
            self.assertNotEqual(self.arr[j, i], -999.0)
            self.assertNotEqual(self.arr[j, i], -99.0)
        self.assertEqual(len(voxels), int(np.count_nonzero(np.isfinite(self.arr) & (self.arr >= -80.0)
                                                             & (self.arr > -90.0))))

    def test_all_sentinel_level_gives_no_voxels_and_no_valid_cells(self):
        arr = np.full((5, 5), -999.0)
        arr[1, 1] = -99.0
        self.assertEqual(mv.level_voxels(arr, 0, 20.0), [])
        codes = mv.level_codes(arr)
        self.assertEqual((codes["-999"], codes["-99"], codes["valid"]), (24, 1, 0))
        self.assertIsNone(codes["min_valid"])

    def test_codes_count_sentinels_and_valid_cells(self):
        arr = np.array([[-999.0, -99.0, 0.0], [25.0, -999.0, -99.0]])
        codes = mv.level_codes(arr)
        self.assertEqual(codes, {"-999": 2, "-99": 2, "valid": 2, "min_valid": 0.0, "max_valid": 25.0})
        voxels = mv.level_voxels(arr, 0, 0.0)
        self.assertEqual(sorted((i, j) for i, j, _, _ in voxels), [(0, 1), (2, 0)])

    def test_non_finite_cells_stop_the_level_instead_of_being_counted(self):
        arr = np.array([[1.0, np.nan]])
        with self.assertRaises(mv.MrmsError):
            mv.level_codes(arr)
        # the voxel path still never selects a NaN cell
        self.assertEqual([(i, j) for i, j, _, _ in mv.level_voxels(arr, 0, -80.0)], [(0, 0)])

    def test_threshold_guard_blocks_sentinels_even_if_called_directly(self):
        with self.assertRaises(ValueError):
            mv.level_voxels(np.full((2, 2), -999.0), 0, -999.0)

    def test_dbz_rounding_to_the_nearest_half_with_ties_up(self):
        cases = {19.74: 19.5, 19.75: 20.0, 19.76: 20.0, 34.9: 35.0, 35.0: 35.0,
                 20.25: 20.5, -15.7: -15.5, 0.24: 0.0, 0.25: 0.5}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(mv.round_half_step(raw), expected)

    def test_selection_uses_the_raw_value_not_the_rounded_one(self):
        arr = np.array([[34.9, 35.0, 35.2]])
        voxels = mv.level_voxels(arr, 0, 35.0)
        self.assertEqual([(i, j) for i, j, _, _ in voxels], [(1, 0), (2, 0)])
        self.assertEqual([v for _, _, _, v in voxels], [35, 35])

    def test_whole_numbers_are_written_without_a_decimal_point(self):
        self.assertEqual(mv._json_number(35.0), 35)
        self.assertIsInstance(mv._json_number(35.0), int)
        self.assertEqual(mv._json_number(35.5), 35.5)


class SyntheticAndOutput(unittest.TestCase):
    BOX = (-110.6, 46.3, -109.4, 47.5)
    REQUIRED_TOP = ("product", "source", "join_time_utc", "valid_time_utc", "retrieved_time_utc",
                    "complete", "missing_levels_km", "grid", "threshold_dbz", "codes", "voxel_format",
                    "voxels", "bytes_downloaded", "timing_s", "provenance", "notes")
    REQUIRED_GRID = ("origin", "dx", "dy", "nx", "ny", "levels_km", "bbox_requested",
                     "full_grid_index", "clipped_to_grid", "level_reference")

    def test_synthetic_field_has_sentinels_and_a_storm_core(self):
        crop = mv.crop_for_bbox(self.BOX)
        arr = mv.synthetic_level(3.0, crop)
        self.assertEqual(arr.shape, (crop.ny, crop.nx))
        self.assertGreater(np.count_nonzero(arr == -999.0), 0)
        self.assertGreater(np.count_nonzero(arr == -99.0), 0)
        self.assertGreater(arr[arr > -90].max(), 35.0)

    def test_synthetic_run_has_the_schema_and_the_label(self):
        crop = mv.crop_for_bbox(self.BOX)
        out = mv.run_synthetic(levels=(0.5, 3.0, 6.0), bbox=self.BOX, crop=crop, threshold=35.0,
                               target=None, retrieved=at(3, 0, 0))
        for key in self.REQUIRED_TOP:
            self.assertIn(key, out)
        for key in self.REQUIRED_GRID:
            self.assertIn(key, out["grid"])
        self.assertEqual(out["label"], "synthetic: not weather")
        self.assertEqual(out["source"], "synthetic")
        self.assertTrue(out["notes"].startswith("synthetic: not weather"))
        self.assertEqual(out["bytes_downloaded"], 0)
        self.assertEqual(json.loads(json.dumps(out, separators=(",", ":"))), out)

    def test_real_notes_text_is_the_declared_text(self):
        self.assertEqual(mv.NOTES, "radar estimate; -99 and -999 are no radar data (meanings unverified); "
                                   "no echo is not clear")

    def test_voxel_indices_stay_inside_the_crop(self):
        crop = mv.crop_for_bbox(self.BOX)
        levels = (0.5, 3.0, 6.0)
        out = mv.run_synthetic(levels=levels, bbox=self.BOX, crop=crop, threshold=20.0,
                               target=None, retrieved=at(3, 0, 0))
        self.assertGreater(len(out["voxels"]), 0)
        for i, j, k, v in out["voxels"]:
            self.assertTrue(0 <= i < crop.nx and 0 <= j < crop.ny)
            self.assertTrue(0 <= k < len(levels))
            self.assertGreaterEqual(v, 20.0)
            self.assertEqual(v * 2, math.floor(v * 2))           # on the 0.5 grid

    def test_synthetic_run_needs_no_network(self):
        crop = mv.crop_for_bbox(self.BOX)
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
            out = mv.run_synthetic(levels=(0.5,), bbox=self.BOX, crop=crop, threshold=35.0,
                                   target=None, retrieved=at(3, 0, 0))
        self.assertTrue(out["complete"])

    def test_missing_level_is_flagged_not_rendered_as_zero(self):
        levels = (0.5, 3.0)
        crop = mv.crop_for_bbox(self.BOX)
        arr = mv.synthetic_level(0.5, crop)
        out = mv.build_output(
            levels=levels, bbox=self.BOX, crop=crop, grid=G, threshold=20.0,
            valid_times={0.5: at(2, 28, 41), 3.0: None}, join_time=at(2, 28, 41), join_spread_s=0,
            retrieved=at(2, 30, 0), decoded={0.5: mv.level_codes(arr)},
            voxels=mv.level_voxels(arr, 0, 20.0),
            bytes_downloaded=0, timing={}, provenance={}, synthetic=False)
        self.assertFalse(out["complete"])
        self.assertEqual(out["missing_levels_km"], [3.0])
        self.assertEqual(sorted(out["codes"].keys()), ["0.5"])
        self.assertIsNone(out["valid_time_utc"]["3"])
        self.assertTrue(all(k == 0 for _, _, k, _ in out["voxels"]))

    def test_provenance_and_grid_describe_the_crop(self):
        crop = mv.crop_for_bbox(mv.DEFAULT_BBOX)
        block = mv.grid_block(G, crop, (0.5, 1.0), mv.DEFAULT_BBOX)
        self.assertEqual(block["origin"], {"lat": 49.745, "lon": -116.795})
        self.assertEqual(block["full_grid_index"], {"i0": 1320, "i1": 2669, "j0": 525, "j1": 1139,
                                                    "ni": 7000, "nj": 3500})
        self.assertEqual(block["bbox_requested"]["lon_min"], -116.8)
        self.assertEqual(block["nx"], 1350)
        self.assertEqual(block["ny"], 615)


class DownloadsAndListings(unittest.TestCase):
    """Listing, cache and gzip checks with the network replaced by fixtures."""

    LIST_XML = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        "<IsTruncated>{truncated}</IsTruncated>{token}"
        "<Contents><Key>CONUS/MergedReflectivityQC_00.50/20261017/"
        "MRMS_MergedReflectivityQC_00.50_20261017-020439.grib2.gz</Key>"
        "<LastModified>2026-10-17T02:05:16.000Z</LastModified><Size>306943</Size></Contents>"
        "<Contents><Key>CONUS/MergedReflectivityQC_00.50/20261017/"
        "MRMS_MergedReflectivityQC_00.50_20261017-020241.grib2.gz.part</Key>"
        "<LastModified>2026-10-17T02:03:16.000Z</LastModified><Size>5</Size></Contents>"
        "</ListBucketResult>"
    )

    def test_listing_rows_are_parsed_and_stray_keys_skipped_later(self):
        body = self.LIST_XML.format(truncated="false", token="").encode()
        with mock.patch.object(mv, "_http_bytes", return_value=body):
            rows, listed = mv.list_objects("CONUS/MergedReflectivityQC_00.50/20261017/", 5)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1], 306943)
        self.assertEqual(listed, len(body))
        with mock.patch.object(mv, "list_objects", return_value=(rows, listed)):
            found, _ = mv.objects_for_hours(0.5, [at(2, 0, 0)], 5)
        self.assertEqual([o.time for o in found], [at(2, 4, 39)])

    def test_listing_follows_continuation_tokens(self):
        first = self.LIST_XML.format(truncated="true", token="<NextContinuationToken>abc</NextContinuationToken>")
        second = self.LIST_XML.format(truncated="false", token="")
        with mock.patch.object(mv, "_http_bytes", side_effect=[first.encode(), second.encode()]) as http:
            rows, _ = mv.list_objects("CONUS/MergedReflectivityQC_00.50/20261017/", 5)
        self.assertEqual(len(rows), 4)
        self.assertIn("continuation-token=abc", http.call_args_list[1].args[0])

    def test_unexpected_listing_root_is_refused_not_read_as_empty(self):
        with mock.patch.object(mv, "_http_bytes", return_value=b"<html>proxy page</html>"):
            with self.assertRaises(mv.MrmsError):
                mv.list_objects("CONUS/MergedReflectivityQC_00.50/", 5)

    def test_http_404_stops_without_retrying(self):
        err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        with mock.patch.object(mv, "_open", side_effect=err) as opener, mock.patch("time.sleep"):
            with self.assertRaises(mv.MrmsError):
                mv._http_bytes("https://example.invalid/", 5)
        self.assertEqual(opener.call_count, 1)

    def test_cached_file_with_matching_size_is_used_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = gzip.compress(b"GRIB-placeholder")
            path = os.path.join(tmp, os.path.basename(obj(0.5, at(2, 4, 39)).key))
            with open(path, "wb") as fh:
                fh.write(payload)
            o = obj(0.5, at(2, 4, 39), size=len(payload))
            with mock.patch.object(mv, "_download_to", side_effect=AssertionError("network used")):
                got_path, got_bytes, cached = mv.fetch_level(o, tmp, 5)
        self.assertEqual((got_bytes, cached), (0, True))
        self.assertEqual(got_path, path)

    def test_download_size_must_match_the_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            o = obj(0.5, at(2, 4, 39), size=100)
            payload = gzip.compress(b"x" * 10)

            def fake_download(url, dest, timeout, attempts=3):
                with open(dest, "wb") as fh:
                    fh.write(payload)
                return len(payload)

            with mock.patch.object(mv, "_download_to", side_effect=fake_download):
                with self.assertRaises(mv.MrmsError):
                    mv.fetch_level(o, tmp, 5)
            self.assertFalse(os.path.exists(os.path.join(tmp, os.path.basename(o.key))))

    def test_non_gzip_download_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            o = obj(0.5, at(2, 4, 39), size=12)

            def fake_download(url, dest, timeout, attempts=3):
                with open(dest, "wb") as fh:
                    fh.write(b"<html>nope!")
                return 11

            with mock.patch.object(mv, "_download_to", side_effect=fake_download):
                with self.assertRaises(mv.MrmsError):
                    mv.fetch_level(o, tmp, 5)

    def test_truncated_gzip_is_refused_at_gunzip(self):
        with tempfile.TemporaryDirectory() as tmp:
            full = gzip.compress(b"0123456789" * 1000)
            path = os.path.join(tmp, "MRMS_MergedReflectivityQC_00.50_20261017-020439.grib2.gz")
            with open(path, "wb") as fh:
                fh.write(full[: len(full) // 2])
            with self.assertRaises(mv.MrmsError):
                mv.gunzip(path)


class DecodeRoundTrip(unittest.TestCase):
    """Writes a small GRIB2 with eccodes and reads it back through decode_message."""

    NI, NJ = 30, 20
    GRID = mv.GridSpec(ni=30, nj=20, lat0=46.0, lon0=-112.0, dx=0.05, dy=0.05)

    def _field(self):
        vals = np.full((self.NJ, self.NI), -10.0)
        vals[5:8, 10:14] = 41.5
        vals[0, :] = -999.0        # top row: no coverage
        vals[19, 0] = -99.0        # bottom-left cell: no radar data
        vals[9, 9] = 12.3
        return vals

    def _write(self, path, level_m=3000, data_date=20250615, data_hhmm=2312):
        import eccodes
        vals = self._field().reshape(-1)
        handle = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
        try:
            eccodes.codes_set(handle, "Ni", self.NI)
            eccodes.codes_set(handle, "Nj", self.NJ)
            eccodes.codes_set(handle, "latitudeOfFirstGridPointInDegrees", self.GRID.lat0)
            eccodes.codes_set(handle, "longitudeOfFirstGridPointInDegrees", self.GRID.lon0 % 360)
            eccodes.codes_set(handle, "latitudeOfLastGridPointInDegrees",
                              self.GRID.lat0 - (self.NJ - 1) * self.GRID.dy)
            eccodes.codes_set(handle, "longitudeOfLastGridPointInDegrees",
                              (self.GRID.lon0 + (self.NI - 1) * self.GRID.dx) % 360)
            eccodes.codes_set(handle, "iDirectionIncrementInDegrees", self.GRID.dx)
            eccodes.codes_set(handle, "jDirectionIncrementInDegrees", self.GRID.dy)
            eccodes.codes_set(handle, "jScansPositively", 0)
            eccodes.codes_set(handle, "iScansNegatively", 0)
            eccodes.codes_set(handle, "typeOfLevel", "heightAboveSea")
            eccodes.codes_set(handle, "level", level_m)
            eccodes.codes_set(handle, "dataDate", data_date)
            eccodes.codes_set(handle, "dataTime", data_hhmm)
            eccodes.codes_set(handle, "packingType", "grid_simple")
            eccodes.codes_set(handle, "bitsPerValue", 16)
            eccodes.codes_set(handle, "decimalScaleFactor", 1)
            eccodes.codes_set_values(handle, vals)
            with open(path, "wb") as fh:
                eccodes.codes_write(handle, fh)
        finally:
            eccodes.codes_release(handle)

    @unittest.skipUnless(HAVE_ECCODES, "eccodes is not importable")
    def test_decode_crops_and_keeps_sentinels_out_of_the_values(self):
        import eccodes  # noqa: F401  (import check above)
        when = dt.datetime(2025, 6, 15, 23, 12, 41, tzinfo=UTC)
        o = mv.Obj(km=3.0, key=mv.object_key(3.0, when), size=0, time=when, last_modified="")
        crop = mv.Crop(i0=0, i1=self.NI - 1, j0=0, j1=self.NJ - 1, clipped=False)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "field.grib2")
            try:
                self._write(path)
            except Exception as exc:  # sample templates differ between eccodes builds
                self.skipTest(f"could not write a sample GRIB2 with this eccodes build: {exc}")
            with open(path, "rb") as fh:
                arr, meta = mv.decode_message(fh, o, self.GRID, crop)
        self.assertEqual(meta["grib_level_m"], 3000)
        np.testing.assert_allclose(arr, self._field(), atol=0.06)
        codes = mv.level_codes(arr)
        self.assertEqual(codes["-999"], self.NI)
        self.assertEqual(codes["-99"], 1)
        voxels = mv.level_voxels(arr, 0, 35.0)
        self.assertEqual(len(voxels), int(np.count_nonzero(arr >= 35.0)))
        self.assertEqual(len(voxels), 12)

    @unittest.skipUnless(HAVE_ECCODES, "eccodes is not importable")
    def test_header_that_disagrees_with_the_object_is_refused(self):
        when = dt.datetime(2025, 6, 15, 23, 12, 41, tzinfo=UTC)
        o = mv.Obj(km=3.0, key=mv.object_key(3.0, when), size=0, time=when, last_modified="")
        crop = mv.Crop(i0=0, i1=self.NI - 1, j0=0, j1=self.NJ - 1, clipped=False)
        with tempfile.TemporaryDirectory() as tmp:
            for kwargs, label in ((dict(level_m=6000), "level"), (dict(data_hhmm=2313), "time")):
                path = os.path.join(tmp, f"{label}.grib2")
                try:
                    self._write(path, **kwargs)
                except Exception as exc:
                    self.skipTest(f"could not write a sample GRIB2 with this eccodes build: {exc}")
                with self.subTest(check=label), open(path, "rb") as fh:
                    with self.assertRaises(mv.MrmsError):
                        mv.decode_message(fh, o, self.GRID, crop)


class CommandLine(unittest.TestCase):
    def test_bbox_with_leading_minus_needs_the_equals_form(self):
        args = mv.build_parser().parse_args(["--bbox=-116.8,43.6,-103.3,49.75", "--levels", "all"])
        self.assertEqual(mv.parse_bbox(args.bbox), mv.DEFAULT_BBOX)
        self.assertEqual(len(mv.parse_levels(args.levels)), 33)

    def test_bad_arguments_exit_with_usage_code_before_any_network(self):
        quiet = io.StringIO()
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")), \
                contextlib.redirect_stderr(quiet), contextlib.redirect_stdout(quiet):
            self.assertEqual(mv.main(["--levels", "0.6"]), mv.EXIT_USAGE)
            self.assertEqual(mv.main(["--threshold", "-99"]), mv.EXIT_USAGE)
            self.assertEqual(mv.main(["--time", "yesterday"]), mv.EXIT_USAGE)

    def test_synthetic_command_writes_a_labelled_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "fixture.json")
            quiet = io.StringIO()
            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network used")), \
                    contextlib.redirect_stdout(quiet):
                code = mv.main(["--synthetic", "--bbox=-110.6,46.3,-109.4,47.5", "--levels", "0.5,3",
                                "--threshold", "35", "--out", out])
            self.assertEqual(code, mv.EXIT_OK)
            with open(out, "r", encoding="ascii") as fh:
                data = json.load(fh)
        self.assertEqual(data["label"], "synthetic: not weather")
        self.assertTrue(data["complete"])


if __name__ == "__main__":
    unittest.main()
