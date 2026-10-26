"""Offline tests for mesh_history.py (H1 prototype).

Run from the prototype folder with the interpreter that has numpy and pyarrow:
    python3 -I -m unittest discover -s tests -v
No network and no pygrib are needed. The fixture is a saved 8 x 10 crop of one real
12:00 UTC MESH file (see README.md). The Montana mask tests read the website's
basemap.json from this repository.
"""
import gzip
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import mesh_history as m  # noqa: E402

try:
    import pyarrow  # noqa: F401

    HAVE_PYARROW = True
except ImportError:  # the store tests need pyarrow; they are reported as skipped
    HAVE_PYARROW = False

FIXTURE = HERE / "fixtures" / "mesh1440_20250616_benchland_8x10.json"
BASEMAP = m.default_basemap()


def load_fixture():
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    values = np.array(doc["values"], dtype=np.float64)
    return doc, values


class UnitsAndThresholds(unittest.TestCase):
    def test_inch_thresholds_in_tenths(self):
        # 0.25 in = 6.35 mm -> first stored tenth at or above is 64 (6.4 mm)
        self.assertEqual(m.inch_threshold_tenths(0.25), 64)
        self.assertEqual(m.inch_threshold_tenths(0.75), 191)   # 19.05 mm -> 190.5 tenths -> 191
        self.assertEqual(m.inch_threshold_tenths(1.00), 254)   # 25.4 mm exactly
        self.assertEqual(m.inch_threshold_tenths(1.50), 381)   # 38.1 mm exactly
        self.assertEqual(m.inch_threshold_tenths(2.00), 508)   # 50.8 mm exactly
        self.assertEqual(m.THRESH, {"0.25": 64, "0.75": 191, "1.00": 254, "1.50": 381, "2.00": 508})
        self.assertEqual(m.EVENT_MIN_TENTHS, 64)

    def test_one_inch_is_25_4_mm(self):
        self.assertEqual(m.mm_to_inch(25.4), 1.0)
        self.assertAlmostEqual(m.mm_to_inch(35.7), 1.405512, places=6)

    def test_boundaries_follow_the_inch_cut(self):
        t = np.array([0, 1, 63, 64, 253, 254], dtype=np.uint16)     # 0, 0.1, 6.3, 6.4, 25.3, 25.4 mm
        _tenths, st = m.pack_tenths(t.astype(np.float64) / 10.0)
        self.assertEqual(st["n_ge_0.25"], 3)    # 6.4, 25.3, 25.4 are at or above 6.35 mm
        self.assertEqual(st["n_ge_1.00"], 1)    # only 25.4 mm reaches 1.00 in


class NoDataRule(unittest.TestCase):
    def test_codes_and_nan_are_no_data(self):
        raw = np.array([-1.0, -3.0, -999.0, np.nan, 0.0, 0.1, 35.7, 98.7])
        tenths, st = m.pack_tenths(raw)
        self.assertEqual(tenths.tolist(), [0, 0, 0, 0, 0, 1, 357, 987])
        self.assertEqual(st["n_minus1"], 1)
        self.assertEqual(st["n_minus3"], 1)
        self.assertEqual(st["n_other_neg"], 1)
        self.assertEqual(st["n_nan"], 1)
        self.assertEqual(st["n_zero"], 1)
        self.assertEqual(st["n_pos"], 3)
        self.assertEqual(st["max_mm"], 98.7)
        self.assertEqual(st["n_ge_0.25"], 2)

    def test_negative_codes_never_become_values(self):
        tenths, _ = m.pack_tenths(np.array([-1.0] * 5 + [-3.0] * 5))
        self.assertFalse(tenths.any())

    def test_values_above_uint16_raise_and_are_not_clamped(self):
        with self.assertRaises(ValueError):
            m.pack_tenths(np.array([6600.0]))                      # 6600 mm -> 66000 tenths
        tenths, _ = m.pack_tenths(np.array([6553.5]))             # the largest storable value
        self.assertEqual(int(tenths[0]), 65535)

    def test_positive_values_off_the_tenth_grid_are_counted(self):
        tenths, st = m.pack_tenths(np.array([0.04, 5.0]))
        self.assertEqual(st["n_pos_lost"], 1)                      # 0.04 mm rounds to zero tenths
        self.assertEqual(tenths.tolist(), [0, 50])


class Encoding(unittest.TestCase):
    def test_round_trip_dense_sparse_and_empty(self):
        rng = np.random.default_rng(3)
        n = 5000
        dense = rng.integers(1, 400, size=n).astype(np.uint16)
        sparse = np.zeros(n, dtype=np.uint16)
        pick = rng.choice(n, size=40, replace=False)
        sparse[pick] = rng.integers(1, 400, size=40)
        empty = np.zeros(n, dtype=np.uint16)
        for arr in (dense, sparse, empty):
            blob = m.encode_tenths(arr)
            self.assertTrue(np.array_equal(m.decode_tenths(blob, n), arr))

    def test_smaller_encoding_is_chosen(self):
        # full grid length: a few hundred bytes sparse against about a kilobyte of zlib'd zeros
        rng = np.random.default_rng(4)
        n = 450765
        dense = rng.integers(1, 400, size=n).astype(np.uint16)
        sparse = np.zeros(n, dtype=np.uint16)
        sparse[rng.choice(n, size=50, replace=False)] = 123
        self.assertEqual(m.encode_tenths(dense)[0], 0)
        blob = m.encode_tenths(sparse)
        self.assertEqual(blob[0], 1)
        self.assertLess(len(blob), 400)

    def test_wrong_cell_count_is_an_error(self):
        blob = m.encode_tenths(np.zeros(10, dtype=np.uint16))
        with self.assertRaises(ValueError):
            m.decode_tenths(blob, 11)


@unittest.skipUnless(BASEMAP.exists(), "website basemap.json not present")
class MontanaMask(unittest.TestCase):
    def test_full_state_count_matches_the_evidence(self):
        g = m.montana_grid(BASEMAP)
        self.assertEqual(g.n, 450765)                              # strict rule (boundary cells out)
        gi = m.montana_grid(BASEMAP, inclusive=True)
        self.assertEqual(gi.n, 450981)                             # boundary cells in
        self.assertEqual(gi.n - g.n, 216)                          # all on the east edge at lon -104.045

    def test_frame_box(self):
        self.assertEqual(m.frame_box(), (450, 750, 1150, 1750))

    def test_tie_block_on_the_east_edge(self):
        ring = m.load_state_ring(BASEMAP)
        strict, incl = m.polygon_masks(ring, 800, 4, 2592, 6)
        self.assertEqual(int(strict.sum()), 12)                    # columns 2592 to 2594 inside
        self.assertEqual(int(incl.sum()), 16)                      # column 2595 (lon -104.045) is the tie
        self.assertFalse(strict[:, 3].any())
        self.assertTrue(incl[:, 3].all())

    def test_fixture_block_is_inside_montana(self):
        doc, _values = load_fixture()
        ring = m.load_state_ring(BASEMAP)
        strict, _incl = m.polygon_masks(ring, doc["row0"], doc["nrow"], doc["col0"], doc["ncol"])
        self.assertEqual(int(strict.sum()), doc["nrow"] * doc["ncol"])

    def test_grid_index_round_trip(self):
        g = m.montana_grid(BASEMAP)
        k = np.arange(0, g.n, 9973)
        for i in k:
            self.assertEqual(g.index_of(int(g.rows[i]), int(g.cols[i])), int(i))
        self.assertEqual(g.index_of(0, 0), -1)


class Shards(unittest.TestCase):
    def test_shard_names(self):
        self.assertEqual(m.shard_name(450, 1150), "r0045_c0115.json.gz")
        self.assertEqual(m.shard_name(599, 1159), "r0059_c0115.json.gz")
        self.assertEqual(m.shard_name(600, 1160), "r0060_c0116.json.gz")
        self.assertEqual(m.shard_name(791, 1995), "r0079_c0199.json.gz")

    def test_shard_contains_its_cells(self):
        rng = np.random.default_rng(5)
        for _ in range(200):
            row, col = int(rng.integers(450, 1200)), int(rng.integers(1150, 2900))
            name = m.shard_name(row, col)
            self.assertRegex(name, r"^r\d{4}_c\d{4}\.json\.gz$")
            tr, tc = int(name[1:5]), int(name[7:11])
            self.assertTrue(tr * 10 <= row < tr * 10 + 10)     # the tile's rows
            self.assertTrue(tc * 10 <= col < tc * 10 + 10)     # the tile's columns


class DatesAndNames(unittest.TestCase):
    def test_stamp_and_spc_day(self):
        import datetime as dt

        self.assertEqual(m.stamp_of_day(dt.date(2025, 6, 15)), dt.date(2025, 6, 16))
        self.assertEqual(m.day_of_stamp(dt.date(2025, 6, 16)), dt.date(2025, 6, 15))
        self.assertEqual(m.five_year_spc_days(), ("2021-10-16", "2026-10-15"))
        self.assertTrue(m.in_five_years("2021-10-16"))
        self.assertFalse(m.in_five_years("2021-10-15"))
        self.assertTrue(m.in_five_years("2026-10-15"))
        self.assertFalse(m.in_five_years("2026-10-16"))

    def test_bucket_and_iem_names(self):
        import datetime as dt

        s = dt.date(2025, 6, 16)
        self.assertEqual(m.bucket_name(s), "MRMS_MESH_Max_1440min_00.50_20250616-120000.grib2.gz")
        self.assertEqual(m.bucket_url(s),
                         "https://noaa-mrms-pds.s3.amazonaws.com/CONUS/MESH_Max_1440min_00.50/20250616/"
                         "MRMS_MESH_Max_1440min_00.50_20250616-120000.grib2.gz")
        self.assertEqual(m.iem_url(s),
                         "https://mtarchive.geol.iastate.edu/2025/06/16/mrms/ncep/MESH_Max_1440min/"
                         "MESH_Max_1440min_00.50_20250616-120000.grib2.gz")

    def test_iem_copy_uses_the_folder_name_iem_publishes(self):
        # IEM names the folder without the "_00.50" suffix; a 404 from the wrong folder
        # was once recorded as "missing at IEM". This URL returned 200 for 2025-06-26.
        import datetime as dt

        self.assertEqual(m.iem_url(dt.date(2025, 6, 26)),
                         "https://mtarchive.geol.iastate.edu/2025/06/26/mrms/ncep/MESH_Max_1440min/"
                         "MESH_Max_1440min_00.50_20250626-120000.grib2.gz")

    def test_haversine_one_degree_of_latitude(self):
        self.assertAlmostEqual(float(m.haversine_km(47.0, -110.0, 48.0, -110.0)), 111.2, delta=0.2)


class GribFileCheck(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _write_gz(self, name, payload):
        p = self.dir / name
        p.write_bytes(gzip.compress(payload))
        return p

    def test_accepts_a_single_message_shape(self):
        p = self._write_gz("ok.grib2.gz", b"GRIB" + b"\x00" * 100 + b"7777")
        ok, detail = m.gz_is_grib(p)
        self.assertTrue(ok, detail)

    def test_rejects_plain_bytes_truncated_and_untrailed(self):
        plain = self.dir / "plain.gz"
        plain.write_bytes(b"not gzip at all")
        self.assertFalse(m.gz_is_grib(plain)[0])
        no_trailer = self._write_gz("notrail.gz", b"GRIB" + b"\x00" * 50)
        self.assertFalse(m.gz_is_grib(no_trailer)[0])
        full = gzip.compress(b"GRIB" + b"\x01" * 5000 + b"7777")
        cut = self.dir / "cut.gz"
        cut.write_bytes(full[: len(full) // 2])
        self.assertFalse(m.gz_is_grib(cut)[0])


class FixtureArrayPath(unittest.TestCase):
    """Array path end to end on the saved fixture: crop, pack, build, lookup, no-data cells."""

    @classmethod
    def setUpClass(cls):
        cls.doc, cls.values = load_fixture()
        cls.r0, cls.c0 = cls.doc["row0"], cls.doc["col0"]
        cls.nrow, cls.ncol = cls.doc["nrow"], cls.doc["ncol"]
        cls.grid = m.Grid(cls.r0, cls.c0, np.ones((cls.nrow, cls.ncol), dtype=bool))
        cls.raw = m.crop_values(cls.values, cls.grid, origin_row=cls.r0, origin_col=cls.c0)
        cls.tenths, cls.stats = m.pack_tenths(cls.raw)
        peak_r, peak_c = 791, 1995
        cls.peak_idx = cls.grid.index_of(peak_r, peak_c)
        cls.peak_latlon = (float(cls.grid.lat[cls.peak_idx]), float(cls.grid.lon[cls.peak_idx]))

    def test_fixture_reads_as_expected(self):
        self.assertEqual(self.raw.size, 80)
        self.assertEqual(self.stats["n_minus1"], 5)
        self.assertEqual(self.stats["n_pos"], 75)
        self.assertEqual(int(self.tenths[self.peak_idx]), 357)
        self.assertAlmostEqual(self.peak_latlon[0], 47.085, places=3)
        self.assertAlmostEqual(self.peak_latlon[1], -110.045, places=3)

    def test_crop_rejects_a_short_array(self):
        with self.assertRaises(ValueError):
            m.crop_values(self.values[:4], self.grid, origin_row=self.r0, origin_col=self.c0)

    def test_disk_max_within_half_a_kilometre_is_the_peak(self):
        d = m.disk_max(self.grid, self.tenths, self.peak_latlon[0], self.peak_latlon[1], 0.5)
        self.assertEqual(d["cells_in_disk"], 1)
        self.assertEqual(d["max_mm"], 35.7)

    @unittest.skipUnless(HAVE_PYARROW, "pyarrow not installed (store tests)")
    def test_build_then_lookup(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            store = tmp / "store"
            raw_list = self.raw.tolist()
            rows = [
                {"day": "2025-06-15", "stamp": "2025-06-16", "job": ("raw", raw_list),
                 "source": "bucket", "bytes": 1, "sha256": "x", "last_modified": "t"},
                {"day": "2025-06-14", "stamp": "2025-06-15", "job": None, "source": "missing",
                 "bytes": None, "sha256": None, "last_modified": None},
                {"day": "2025-06-16", "stamp": "2025-06-17", "job": ("raw", [-1.0] * self.raw.size),
                 "source": "bucket", "bytes": 1, "sha256": "y", "last_modified": "t"},
            ]
            summary = m.build_store(self.grid, rows, store, procs=0, extra={"test": True}, log=lambda s: None)
            self.assertEqual(summary["stored_days"], 2)
            # events are the fixture cells at or above 6.35 mm (the all-no-data day adds none)
            self.assertEqual(summary["events"], int(np.count_nonzero(self.tenths >= 64)))

            st = m.Store(store)
            res = m.lookup_point(st, self.peak_latlon[0], self.peak_latlon[1])
            self.assertEqual(res["top_five_year"][0]["mm"], 35.7)
            self.assertEqual(res["top_five_year"][0]["day"], "2025-06-15")
            self.assertEqual(res["top_five_year"][0]["file_stamp"], "2025-06-16")
            self.assertEqual(res["top_five_year"][0]["in"], 1.41)
            self.assertEqual(res["day_counts_five_year"]["positive_any"], 1)
            self.assertEqual(res["day_counts_five_year"]["at_or_above_1.00_in"], 1)
            self.assertIn("Radar estimate", res["wording"][0])
            self.assertIn("not the same as no hail", " ".join(res["wording"]).lower())

            # the day array round-trips, and the all-day scan finds only the peak day
            self.assertTrue(np.array_equal(st.day_tenths("2025-06-15"), self.tenths))
            self.assertEqual(st.cell_all_days(self.peak_idx), [("2025-06-15", 357)])

            # a day of no data is stored as zeros, not as an estimate
            self.assertFalse(st.day_tenths("2025-06-16").any())

            # the missing day has no array and is recorded as missing
            daily = {r["day"]: r for r in json.loads((store / "daily_stats.json").read_text())}
            self.assertFalse(daily["2025-06-14"]["present"])
            self.assertEqual(daily["2025-06-16"]["n_minus1"], self.raw.size)
            self.assertEqual(daily["2025-06-16"]["n_pos"], 0)
            self.assertTrue(daily["2025-06-15"]["five_year"])

            # the store lists only the stored days; the missing day is recorded in its own list
            meta = json.loads((store / "grid.json").read_text())
            self.assertEqual(meta["days"], ["2025-06-15", "2025-06-16"])
            self.assertEqual(meta["missing_or_unfetched_days"], ["2025-06-14"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(HAVE_PYARROW, "pyarrow not installed (store tests)")
    def test_no_data_cell_has_no_estimate(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            store = tmp / "store"
            rows = [{"day": "2025-06-15", "stamp": "2025-06-16", "job": ("raw", self.raw.tolist()),
                     "source": "bucket", "bytes": 1, "sha256": "x", "last_modified": "t"}]
            m.build_store(self.grid, rows, store, procs=0, extra={}, log=lambda s: None)
            st = m.Store(store)
            minus1 = int(np.flatnonzero(self.raw == -1.0)[0])
            lat, lon = float(self.grid.lat[minus1]), float(self.grid.lon[minus1])
            res = m.lookup_point(st, lat, lon)
            self.assertEqual(res["events_five_year"], [])
            self.assertIn("No stored estimate at or above 0.25 in", res["wording"][1])
            self.assertIn("not the same as no hail", " ".join(res["wording"]).lower())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(HAVE_PYARROW, "pyarrow not installed (store tests)")
    def test_point_outside_the_store_grid(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            store = tmp / "store"
            rows = [{"day": "2025-06-15", "stamp": "2025-06-16", "job": ("raw", self.raw.tolist()),
                     "source": "bucket", "bytes": 1, "sha256": "x", "last_modified": "t"}]
            m.build_store(self.grid, rows, store, procs=0, extra={}, log=lambda s: None)
            res = m.lookup_point(m.Store(store), 40.0, -110.0)
            self.assertIsNone(res["cell"])
            self.assertIn("not the same as no hail", res["wording"][0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_nearest_cell_prefers_the_closest_centre(self):
        lat, lon = self.peak_latlon[0] + 0.004, self.peak_latlon[1] - 0.004
        idx, dist = m.nearest_cell(self.grid, lat, lon)
        self.assertEqual(idx, self.peak_idx)
        self.assertLess(dist, 1.0)


if __name__ == "__main__":
    unittest.main()
