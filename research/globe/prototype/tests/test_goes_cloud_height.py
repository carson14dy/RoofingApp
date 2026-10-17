"""Checks for goes_cloud_height.py.

Offline by default (synthetic data and a fake bucket listing). Run from the prototype folder:

    python -m unittest discover -s tests -v

Live checks (real NOAA bucket, real download, about 0.3 MB) run only when GOES_LIVE=1 is set and
skip cleanly when the network is not reachable:

    GOES_LIVE=1 python -m unittest discover -s tests -v

Reference pairs in this file come from PROJ 9 through pyproj 3.8.0, with
+proj=geos +sweep=x +h=35786023 +a=6378137 +b=6356752.31414. PROJ's projected coordinate equals
perspective height times the scan angle (checked to 1e-12 rad while writing this file). The
GOES-East origin is -75.0, the value in the file's goes_imager_projection (the nominal platform
subpoint in the same files is -75.2; it is not the grid origin). GOES-West is -137.0.
"""

import datetime as dt
import json
import math
import os
import shutil
import sys
import tempfile
import unittest
import urllib.parse
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.dirname(HERE)
if PROTO not in sys.path:
    sys.path.insert(0, PROTO)

import numpy as np  # noqa: E402

import goes_cloud_height as gch  # noqa: E402

H_M = 35786023.0
A_M = 6378137.0
B_M = 6356752.31414
EAST = gch.Geos(lon0_deg=-75.0, height_m=H_M, req_m=A_M, rpol_m=B_M, sweep="x")
WEST = gch.Geos(lon0_deg=-137.0, height_m=H_M, req_m=A_M, rpol_m=B_M, sweep="x")

# (lat, lon, x_rad, y_rad). Montana sites from the PROJ forward transform divided by h, then three
# PROJ inverse points on scan angles.
PROJ_REFS_EAST = [
    (46.8721, -113.994, -0.07027887995941583, 0.11891392052523928),   # Missoula
    (45.7833, -108.5007, -0.06343403351893216, 0.11775272587533613),  # Billings
    (48.197, -106.635, -0.057476134390468475, 0.12216474215125575),   # Glasgow
    (46.4083, -105.8406, -0.058359948139321716, 0.11919443987773419), # Miles City
    (47.5053, -111.3008, -0.06548483741758951, 0.12038799622902392),  # Great Falls
    (3.24276110917967, -68.53633820628545, 0.02, 0.01),
    (9.857264875354357, -91.73487905722706, -0.05, 0.03),
    (-13.124567939626141, -75.0, 0.0, -0.04),
]
PROJ_REFS_WEST = [
    (46.8721, -113.994, 0.044400746978903886, 0.12084589121828875),   # Missoula
    (45.7833, -108.5007, 0.05513875475461718, 0.11836350131323366),   # Billings
    (48.197, -106.635, 0.05546730489098915, 0.12231754533618067),     # Glasgow
    (46.4083, -105.8406, 0.058882590299279725, 0.1191556152778814),   # Miles City
    (47.5053, -111.3008, 0.048504949487306936, 0.12166735728387944),  # Great Falls
    (3.24276110917967, -130.53633820628545, 0.02, 0.01),
    (9.857264875354357, -153.73487905722703, -0.05, 0.03),
    (-13.124567939626141, -137.0, 0.0, -0.04),
]


def _achac_grid(bbox=gch.DEFAULT_BBOX, nx=500, ny=300, step=0.00028, g=EAST):
    """Regular scan-angle grid centred on the bbox, like the real ACHAC grid (north row first)."""
    lat_c = 0.5 * (bbox[1] + bbox[3])
    lon_c = 0.5 * (bbox[0] + bbox[2])
    xc, yc, _ = gch.latlon_to_scan(lat_c, lon_c, g)
    x = float(xc) + (np.arange(nx) - (nx - 1) / 2.0) * step
    y = float(yc) - (np.arange(ny) - (ny - 1) / 2.0) * step
    return x, y


def _listing_xml(entries, truncated=False, token=None):
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">',
             "<Name>noaa-goes19</Name>", f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>"]
    if token:
        parts.append(f"<NextContinuationToken>{token}</NextContinuationToken>")
    for key, lm, size in entries:
        parts.append(f"<Contents><Key>{key}</Key><LastModified>{lm}</LastModified>"
                     f"<ETag>&quot;x&quot;</ETag><Size>{size}</Size><StorageClass>STANDARD</StorageClass>"
                     "</Contents>")
    parts.append("</ListBucketResult>")
    return "".join(parts).encode("utf-8")


def _fake_fetch(listings: dict, log: list):
    def fetch(url):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        prefix = q["prefix"][0]
        log.append((prefix, q.get("continuation-token", [None])[0]))
        return listings.get(prefix, _listing_xml([]))
    return fetch


ACHAC_KEY_G19 = ("ABI-L2-ACHAC/2026/290/03/OR_ABI-L2-ACHAC-M6_G19_s20262900316174_e20262900318547_"
                 "c20262900320430.nc")
CMIP_KEY_C13 = ("ABI-L2-CMIPC/2026/290/03/OR_ABI-L2-CMIPC-M6C13_G19_s20262900316174_e20262900318559_"
                "c20262900319040.nc")
CMIP_KEY_C16 = CMIP_KEY_C13.replace("M6C13", "M6C16")


class FixedGridTests(unittest.TestCase):
    def test_sub_satellite_point_maps_to_origin_and_longitude(self):
        for g in (EAST, WEST):
            lat, lon = gch.scan_to_latlon(0.0, 0.0, g)
            self.assertAlmostEqual(float(lat), 0.0, places=12)
            self.assertAlmostEqual(float(lon), g.lon0_deg, places=12)
            x, y, vis = gch.latlon_to_scan(0.0, g.lon0_deg, g)
            self.assertTrue(bool(vis))
            self.assertAlmostEqual(float(x), 0.0, places=12)
            self.assertAlmostEqual(float(y), 0.0, places=12)

    def test_matches_proj_reference_pairs(self):
        for g, refs in ((EAST, PROJ_REFS_EAST), (WEST, PROJ_REFS_WEST)):
            for lat, lon, x, y in refs:
                la, lo = gch.scan_to_latlon(x, y, g)
                self.assertAlmostEqual(float(la), lat, delta=1e-8, msg=f"lat for scan {x},{y}")
                self.assertAlmostEqual(float(lo), lon, delta=1e-8, msg=f"lon for scan {x},{y}")
                xi, yi, vis = gch.latlon_to_scan(lat, lon, g)
                self.assertTrue(bool(vis))
                self.assertAlmostEqual(float(xi), x, delta=1e-10, msg=f"x for {lat},{lon}")
                self.assertAlmostEqual(float(yi), y, delta=1e-10, msg=f"y for {lat},{lon}")

    def test_east_scan_angle_increases_eastward(self):
        _, lon = gch.scan_to_latlon(0.02, 0.0, EAST)
        self.assertGreater(float(lon), EAST.lon0_deg)
        x, _, _ = gch.latlon_to_scan(0.0, EAST.lon0_deg + 5.0, EAST)
        self.assertGreater(float(x), 0.0)

    def test_round_trip_over_the_bbox(self):
        rng = np.random.default_rng(11)
        lon_min, lat_min, lon_max, lat_max = gch.DEFAULT_BBOX
        lat = rng.uniform(lat_min, lat_max, 2000)
        lon = rng.uniform(lon_min, lon_max, 2000)
        for g in (EAST, WEST):
            x, y, vis = gch.latlon_to_scan(lat, lon, g)
            self.assertTrue(np.all(vis))
            la, lo = gch.scan_to_latlon(x, y, g)
            self.assertLess(float(np.max(np.abs(la - lat))), 1e-9)
            dlon = ((lo - lon + 180.0) % 360.0) - 180.0
            self.assertLess(float(np.max(np.abs(dlon))), 1e-9)

    def test_horizon_is_arccos_a_over_h_on_the_equator(self):
        horizon = math.degrees(math.acos(A_M / (H_M + A_M)))
        self.assertAlmostEqual(horizon, 81.30, delta=0.02)
        _, _, inside = gch.latlon_to_scan(0.0, EAST.lon0_deg + horizon - 0.05, EAST)
        _, _, outside = gch.latlon_to_scan(0.0, EAST.lon0_deg + horizon + 0.05, EAST)
        self.assertTrue(bool(inside))
        self.assertFalse(bool(outside))

    def test_ray_that_misses_the_earth_is_nan(self):
        lat, lon = gch.scan_to_latlon(0.16, 0.0, EAST)
        self.assertTrue(math.isnan(float(lat)))
        self.assertTrue(math.isnan(float(lon)))

    def test_longitudes_are_wrapped_to_180(self):
        x = np.linspace(-0.14, 0.14, 201)
        y = np.linspace(-0.08, 0.08, 121)
        XX, YY = np.meshgrid(x, y)
        for g in (EAST, WEST):
            _, lon = gch.scan_to_latlon(XX, YY, g)
            finite = lon[np.isfinite(lon)]
            self.assertTrue(np.all(finite >= -180.0) and np.all(finite < 180.0))

    def test_only_x_sweep_is_implemented(self):
        g = gch.Geos(lon0_deg=-75.0, height_m=H_M, req_m=A_M, rpol_m=B_M, sweep="y")
        with self.assertRaises(NotImplementedError):
            gch.scan_to_latlon(0.0, 0.0, g)


class GridAndFootprintTests(unittest.TestCase):
    def test_nadir_pixel_sizes_match_abi_definition(self):
        achac = gch.native_spacing_km(EAST, 0.00028, -0.00028)
        self.assertAlmostEqual(achac["nadir_dx_km"], 10.02, delta=0.01)
        band13 = gch.native_spacing_km(EAST, 0.000056, -0.000056)
        self.assertAlmostEqual(band13["nadir_dx_km"], 2.004, delta=0.001)

    def test_default_target_grid_shape_and_centres(self):
        lon, lat = gch.target_axes(gch.DEFAULT_BBOX)
        self.assertEqual(lon.size, 675)
        self.assertEqual(lat.size, 308)
        self.assertAlmostEqual(lon[0], -116.79, places=9)
        self.assertAlmostEqual(lon[-1], -103.31, places=9)
        self.assertAlmostEqual(lat[0], 49.74, places=9)
        self.assertAlmostEqual(lat[-1], 43.60, places=9)
        self.assertAlmostEqual(float(np.diff(lon)[0]), 0.02, places=9)
        self.assertAlmostEqual(float(-np.diff(lat)[0]), 0.02, places=9)

    def test_window_contains_every_native_pixel_centre_in_the_bbox(self):
        x, y = _achac_grid()
        i0, i1, j0, j1 = gch.window_indices(gch.DEFAULT_BBOX, x, y, EAST, pad=10)
        XX, YY = np.meshgrid(x, y)
        la, lo = gch.scan_to_latlon(XX, YY, EAST)
        lon_min, lat_min, lon_max, lat_max = gch.DEFAULT_BBOX
        inside = (la >= lat_min) & (la <= lat_max) & (lo >= lon_min) & (lo <= lon_max)
        jj, ii = np.nonzero(inside)
        self.assertTrue(np.all((ii >= i0) & (ii < i1) & (jj >= j0) & (jj < j1)))
        self.assertGreater(int(inside.sum()), 1000)

    def test_footprint_is_longer_along_the_tilt_over_montana(self):
        x, y = _achac_grid()
        i, j = 250, 150
        foot = gch.footprint_km(EAST, x, y, i, j)
        self.assertGreater(foot["pixel_long_km"], 18.0)
        self.assertLess(foot["pixel_long_km"], 28.0)
        self.assertLess(foot["pixel_short_km"], 12.0)
        ratio = foot["pixel_long_km"] / foot["pixel_short_km"]
        self.assertGreater(ratio, 1.8)
        self.assertLess(ratio, 3.0)


class ResamplingTests(unittest.TestCase):
    def test_nearest_pixel_is_within_half_a_step_in_scan_space(self):
        x, y = _achac_grid()
        rng = np.random.default_rng(5)
        lat = rng.uniform(44.0, 49.0, 3000)
        lon = rng.uniform(-115.0, -105.0, 3000)
        ii, jj, inside = gch.resample_nearest(lat, lon, EAST, x, y)
        self.assertTrue(np.all(inside))
        xs, ys, _ = gch.latlon_to_scan(lat, lon, EAST)
        self.assertLessEqual(float(np.max(np.abs(xs - x[ii]))), 0.00028 / 2 + 1e-12)
        self.assertLessEqual(float(np.max(np.abs(ys - y[jj]))), 0.00028 / 2 + 1e-12)

    def test_points_outside_the_native_grid_are_not_assigned(self):
        x, y = _achac_grid()
        ii, jj, inside = gch.resample_nearest(np.array([0.0, 47.0]), np.array([-75.0, -105.0]), EAST, x, y)
        self.assertFalse(bool(inside[0]))
        self.assertTrue(bool(inside[1]))

    def test_resampling_keeps_counts(self):
        data = gch.synthetic_dataset("ACHAC", "east")
        png, res = gch.process_dataset(data, gch.DEFAULT_BBOX, product_key="ACHAC", include_flagged=True)
        tcode = res["_target_codes"]
        ii, jj, inside = res["_target_native_index"]
        cells = tcode.size
        self.assertEqual(int(np.count_nonzero(inside)) + int(np.count_nonzero(tcode == 0)), cells)
        # Every inside target cell gets exactly one native pixel: the counts per native pixel add up.
        flat = (jj * data["raw"].shape[1] + ii)[inside]
        per_pixel = np.bincount(flat, minlength=data["raw"].size)
        self.assertEqual(int(per_pixel.sum()), int(np.count_nonzero(inside)))
        # Target counts per class equal the class-weighted sum over native pixels.
        code = gch.classify(data["raw"], data["fill"], data["valid_range"][0], data["valid_range"][1],
                            data["dqf"], data["dqf_fill"], *data["dqf_valid_range"])
        for k in range(1, 6):
            from_target = int(np.count_nonzero(tcode == k))
            from_native = int(per_pixel[(code.ravel() == k)].sum())
            self.assertEqual(from_target, from_native, msg=f"class {k}")

    def test_most_inside_native_pixels_receive_a_target_cell(self):
        data = gch.synthetic_dataset("ACHAC", "east")
        _, res = gch.process_dataset(data, gch.DEFAULT_BBOX, product_key="ACHAC")
        ii, jj, inside = res["_target_native_index"]
        hit = np.zeros(data["raw"].shape, dtype=bool)
        hit[jj[inside], ii[inside]] = True
        lon_min, lat_min, lon_max, lat_max = gch.DEFAULT_BBOX
        XX, YY = np.meshgrid(data["x"], data["y"])
        la, lo = gch.scan_to_latlon(XX, YY, data["proj"])
        native_in = (la >= lat_min) & (la <= lat_max) & (lo >= lon_min) & (lo <= lon_max)
        self.assertGreater(float(hit[native_in].mean()), 0.99)


class ValidityTests(unittest.TestCase):
    def test_fill_is_no_retrieval_not_a_height(self):
        raw = np.array([[65535, 0, 1000, 65531]], dtype=np.uint16)
        code = gch.classify(raw, 65535, 0, 65530, None, 255, 0, 3)
        self.assertEqual(code.tolist(), [[gch.CODE_NO_RETRIEVAL, gch.CODE_GOOD, gch.CODE_GOOD,
                                          gch.CODE_OUT_OF_RANGE]])

    def test_zero_metres_is_one_metre_so_zero_stays_no_data(self):
        out = gch.encode_png_values(np.array([0.0, 0.2, 1500.4, 19999.6]), "m")
        self.assertEqual(out.tolist(), [1, 1, 1500, 20000])
        self.assertEqual(out.dtype, np.uint16)

    def test_brightness_temperature_is_stored_in_tenths_of_a_kelvin(self):
        out = gch.encode_png_values(np.array([275.6, 89.62, 341.27]), "K")
        self.assertEqual(out.tolist(), [2756, 896, 3413])

    def test_dqf_invalid_value_is_not_good(self):
        raw = np.array([[1000, 1000, 1000]], dtype=np.uint16)
        dqf = np.array([[0, 1, 255]], dtype=np.uint8)
        code = gch.classify(raw, 65535, 0, 65530, dqf, 255, 0, 3)
        self.assertEqual(code.tolist(), [[gch.CODE_GOOD, gch.CODE_FLAGGED, gch.CODE_DQF_INVALID]])

    def test_flagged_values_are_reported_and_only_drawn_when_asked(self):
        data = gch.synthetic_dataset("ACHAC", "east")
        png_default, res_default = gch.process_dataset(data, gch.DEFAULT_BBOX, product_key="ACHAC")
        tcode = res_default["_target_codes"]
        self.assertGreater(int(np.count_nonzero(tcode == gch.CODE_FLAGGED)), 0)
        self.assertTrue(np.all(png_default[tcode == gch.CODE_FLAGGED] == 0))
        self.assertTrue(np.all(png_default[tcode == gch.CODE_NO_RETRIEVAL] == 0))
        self.assertTrue(np.all(png_default[tcode == gch.CODE_GOOD] > 0))
        self.assertEqual(res_default["stats"]["flagged_with_value"]["n"],
                         res_default["native_pixels_in_bbox"]["flagged_with_value"])
        self.assertEqual(res_default["stats"]["good"]["n"], res_default["native_pixels_in_bbox"]["good"])
        png_all, res_all = gch.process_dataset(data, gch.DEFAULT_BBOX, product_key="ACHAC",
                                               include_flagged=True)
        self.assertTrue(np.all(png_all[res_all["_target_codes"] == gch.CODE_FLAGGED] > 0))
        self.assertEqual(int(np.count_nonzero(png_all)), int(np.count_nonzero(png_default)) +
                         int(np.count_nonzero(res_default["_target_codes"] == gch.CODE_FLAGGED)))

    def test_png_zero_means_no_data_everywhere_else(self):
        data = gch.synthetic_dataset("ACHAC", "east")
        png, res = gch.process_dataset(data, gch.DEFAULT_BBOX, product_key="ACHAC")
        self.assertEqual(int(np.count_nonzero(png)), res["target_grid_counts"]["good"])

    def test_percentages_are_in_range(self):
        data = gch.synthetic_dataset("ACHAC", "east")
        _, res = gch.process_dataset(data, gch.DEFAULT_BBOX, product_key="ACHAC")
        for block in (res["percent_native_bbox"], res["percent_target_grid"]):
            for v in block.values():
                self.assertTrue(v is None or 0.0 <= v <= 100.0)


class PngTests(unittest.TestCase):
    def _round_trip(self, arr):
        data = gch.encode_png16(arr)
        back = gch.decode_png16(data)
        np.testing.assert_array_equal(back, arr)

    def test_round_trip_random_with_no_data_zeros(self):
        rng = np.random.default_rng(2)
        arr = rng.integers(0, 65535, size=(17, 23), dtype=np.uint16)
        arr[rng.random(arr.shape) < 0.4] = 0
        self._round_trip(arr)

    def test_round_trip_exercises_each_filter(self):
        rows = []
        rows.append(np.full(40, 4321, dtype=np.uint16))                       # constant: none wins
        rows.append(np.arange(40, dtype=np.uint16) * 300)                    # gradient: sub wins
        rows.append(np.tile(np.array([7, 9000], dtype=np.uint16), 20))       # alternating
        rows.append(np.arange(40, dtype=np.uint16) * 300 + 17)
        rng = np.random.default_rng(9)
        rows.append(rng.integers(0, 65535, 40, dtype=np.uint16))
        arr = np.vstack(rows)
        arr = np.vstack([arr, arr + 1, arr[::-1]])
        self._round_trip(arr)

    def test_header_is_16_bit_grayscale(self):
        data = gch.encode_png16(np.zeros((3, 5), dtype=np.uint16))
        self.assertEqual(data[:8], gch.PNG_SIGNATURE)
        width, height, depth, ctype, comp, filt, interlace = gch.struct.unpack(">IIBBBBB", data[16:29])
        self.assertEqual((width, height, depth, ctype, comp, filt, interlace), (5, 3, 16, 0, 0, 0, 0))

    def test_pillow_reads_the_file_when_available(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        arr = np.array([[0, 1, 896], [2756, 65535, 3413]], dtype=np.uint16)
        tmp = tempfile.mkdtemp(prefix="gch-png-")
        try:
            path = os.path.join(tmp, "t.png")
            with open(path, "wb") as fh:
                fh.write(gch.encode_png16(arr))
            with Image.open(path) as im:
                back = np.array(im).astype(np.int64)
            np.testing.assert_array_equal(back, arr.astype(np.int64))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ListingAndTimeTests(unittest.TestCase):
    def test_scan_stamp_parses_tenths(self):
        t = gch.parse_scan_stamp("20262900141174")
        self.assertEqual(t, dt.datetime(2026, 10, 17, 1, 41, 17, 400000, tzinfo=dt.timezone.utc))

    def test_hour_prefix_uses_day_of_year(self):
        cfg = gch.PRODUCTS["ACHAC"]
        when = dt.datetime(2026, 10, 17, 3, tzinfo=dt.timezone.utc)
        self.assertEqual(gch.hour_prefix(cfg, when), "ABI-L2-ACHAC/2026/290/03/")

    def test_newest_band13_only_for_cmipc13(self):
        entries = [gch.Entry(CMIP_KEY_C16, dt.datetime(2026, 10, 17, 3, 30, tzinfo=dt.timezone.utc), 1),
                   gch.Entry(CMIP_KEY_C13, dt.datetime(2026, 10, 17, 3, 20, tzinfo=dt.timezone.utc), 2),
                   gch.Entry(CMIP_KEY_C13.replace("s20262900316174", "s20262900311174"),
                             dt.datetime(2026, 10, 17, 3, 40, tzinfo=dt.timezone.utc), 3)]
        pick = gch.newest_pick(entries, gch.PRODUCTS["CMIPC13"])
        self.assertEqual(pick.band, "C13")
        self.assertEqual(pick.key, CMIP_KEY_C13)
        self.assertEqual(pick.platform, "G19")
        self.assertEqual(gch.newest_pick([entries[0]], gch.PRODUCTS["CMIPC13"]), None)

    def test_achac_ignores_band_files(self):
        entries = [gch.Entry(CMIP_KEY_C13, dt.datetime(2026, 10, 17, 3, 20, tzinfo=dt.timezone.utc), 2),
                   gch.Entry(ACHAC_KEY_G19, dt.datetime(2026, 10, 17, 3, 21, tzinfo=dt.timezone.utc), 9)]
        pick = gch.newest_pick(entries, gch.PRODUCTS["ACHAC"])
        self.assertEqual(pick.key, ACHAC_KEY_G19)
        self.assertIsNone(pick.band)

    def test_newest_is_by_scan_start_not_upload(self):
        older_key = ACHAC_KEY_G19
        newer_key = ACHAC_KEY_G19.replace("s20262900316174", "s20262900321174")
        entries = [gch.Entry(newer_key, dt.datetime(2026, 10, 17, 3, 22, tzinfo=dt.timezone.utc), 1),
                   gch.Entry(older_key, dt.datetime(2026, 10, 17, 3, 40, tzinfo=dt.timezone.utc), 1)]
        self.assertEqual(gch.newest_pick(entries, gch.PRODUCTS["ACHAC"]).key, newer_key)

    def test_parse_listing_handles_namespace_and_truncation(self):
        body = _listing_xml([(ACHAC_KEY_G19, "2026-10-17T03:20:50.000Z", "318477")], truncated=True,
                            token="tok-1")
        entries, truncated, token = gch.parse_listing(body)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].size, 318477)
        self.assertEqual(entries[0].last_modified, dt.datetime(2026, 10, 17, 3, 20, 50, tzinfo=dt.timezone.utc))
        self.assertTrue(truncated)
        self.assertEqual(token, "tok-1")

    def test_list_prefix_follows_the_continuation_token(self):
        prefix = "ABI-L2-ACHAC/2026/290/03/"
        pages = {
            prefix: _listing_xml([(ACHAC_KEY_G19, "2026-10-17T03:20:50.000Z", "1")], truncated=True,
                                 token="next"),
        }
        log = []
        calls = {"n": 0}

        def fetch(url):
            calls["n"] += 1
            if calls["n"] == 1:
                return pages[prefix]
            log.append(url)
            return _listing_xml([(ACHAC_KEY_G19.replace("s20262900316174", "s20262900321174"),
                                  "2026-10-17T03:25:50.000Z", "2")])

        entries, nbytes = gch.list_prefix("noaa-goes19", prefix, fetch)
        self.assertEqual(len(entries), 2)
        self.assertIn("continuation-token=next", log[0])
        self.assertGreater(nbytes, 0)

    def test_find_latest_walks_back_one_hour(self):
        now = dt.datetime(2026, 10, 17, 3, 27, 14, tzinfo=dt.timezone.utc)
        prev_prefix = "ABI-L2-ACHAC/2026/290/02/"
        listings = {prev_prefix: _listing_xml([(ACHAC_KEY_G19.replace("/03/", "/02/"),
                                                "2026-10-17T02:55:00.000Z", "318000")])}
        log = []
        pick, list_bytes, checked = gch.find_latest("noaa-goes19", gch.PRODUCTS["ACHAC"], now,
                                                    _fake_fetch(listings, log))
        self.assertEqual(checked, ["ABI-L2-ACHAC/2026/290/03/", prev_prefix])
        self.assertTrue(pick.key.startswith(prev_prefix))
        self.assertEqual(pick.size, 318000)
        self.assertGreater(list_bytes, 0)

    def test_find_hour_raises_when_nothing_is_listed(self):
        with self.assertRaises(RuntimeError):
            gch.find_hour("noaa-goes19", gch.PRODUCTS["ACHAC"], 2026, 290, 5, _fake_fetch({}, []))

    def test_time_argument_parsing(self):
        self.assertIsNone(gch.parse_time_arg("latest"))
        self.assertEqual(gch.parse_time_arg("2026-290-01"), (2026, 290, 1))
        self.assertEqual(gch.parse_time_arg("2024-366-23"), (2024, 366, 23))
        for bad in ("2026-367-01", "2025-366-00", "2026-290-24", "2026-290", "yesterday"):
            with self.assertRaises(ValueError, msg=bad):
                gch.parse_time_arg(bad)

    def test_bbox_parsing(self):
        self.assertEqual(gch.parse_bbox("-116.8,43.6,-103.3,49.75"), gch.DEFAULT_BBOX)
        with self.assertRaises(ValueError):
            gch.parse_bbox("-103.3,43.6,-116.8,49.75")
        with self.assertRaises(ValueError):
            gch.parse_bbox("1,2,3")


def _args(**kw):
    base = dict(satellite="east", product="ACHAC", time="latest", key=None,
                bbox=",".join(str(v) for v in gch.DEFAULT_BBOX), out="height.png", download_dir=None,
                keep_download=False, include_flagged=False, synthetic=False)
    base.update(kw)
    return SimpleNamespace(**base)


REQUIRED = gch.REQUIRED_JSON_KEYS


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gch-run-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_synthetic_run_writes_png_and_strict_json(self):
        out_png = os.path.join(self.tmp, "synth.png")
        out = gch.run(_args(synthetic=True, out=out_png), bbox=gch.DEFAULT_BBOX, time_req=None)
        self.assertTrue(os.path.exists(out_png))
        with open(os.path.splitext(out_png)[0] + ".json", "r", encoding="utf-8") as fh:
            text = fh.read()
        doc = json.loads(text, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
        for key in REQUIRED:
            self.assertIn(key, doc, msg=f"missing {key}")
        self.assertTrue(doc["synthetic"])
        self.assertIsNone(doc["latency_s"])
        self.assertEqual(doc["bytes_downloaded"]["total"], 0)
        self.assertEqual(doc["note"], gch.NOTE_ACHA)
        with open(out_png, "rb") as fh:
            png = gch.decode_png16(fh.read())
        self.assertEqual(png.shape, (308, 675))
        self.assertEqual(int(np.count_nonzero(png)), doc["output"]["png_cells_with_value"])
        self.assertIn("percent_native_bbox", out)

    def test_fake_bucket_run_end_to_end(self):
        now = dt.datetime(2026, 10, 17, 3, 27, 14, tzinfo=dt.timezone.utc)
        size = 318477
        listings = {"ABI-L2-ACHAC/2026/290/03/": _listing_xml(
            [(ACHAC_KEY_G19, "2026-10-17T03:20:50.000Z", str(size))])}
        log = []
        dataset = gch.synthetic_dataset("ACHAC", "east")
        dataset["global_attrs"] = {"time_coverage_start": "2026-10-17T03:16:17.4Z",
                                   "time_coverage_end": "2026-10-17T03:18:54.7Z",
                                   "platform_ID": "G19", "orbital_slot": "GOES-East",
                                   "license": "Unclassified data.  Access is restricted to approved users only."}
        downloads = []

        def fake_download(url, dest, expected):
            downloads.append((url, dest, expected))
            with open(dest, "wb") as fh:
                fh.write(b"\0" * expected)
            return expected

        out_png = os.path.join(self.tmp, "live-like.png")
        with mock.patch.object(gch, "download", side_effect=fake_download), \
                mock.patch.object(gch, "read_netcdf", return_value=dataset):
            out = gch.run(_args(out=out_png, download_dir=self.tmp), bbox=gch.DEFAULT_BBOX, time_req=None,
                          fetch=_fake_fetch(listings, log), now=now)
        self.assertEqual(out["object_key"], ACHAC_KEY_G19)
        self.assertEqual(downloads[0][0], "https://noaa-goes19.s3.amazonaws.com/" + ACHAC_KEY_G19)
        self.assertEqual(out["bytes_downloaded"]["object"], size)
        self.assertEqual(out["bytes_downloaded"]["total"], out["bytes_downloaded"]["listing"] + size)
        self.assertAlmostEqual(out["latency_s"]["age_at_check_s"], 499.3, places=1)
        self.assertAlmostEqual(out["latency_s"]["upload_minus_scan_end_s"], 115.3, places=1)
        self.assertEqual(out["time_request"], "latest")
        self.assertFalse(out["synthetic"])
        for key in REQUIRED:
            self.assertIn(key, out, msg=f"missing {key}")
        self.assertFalse(os.path.exists(downloads[0][1]))  # removed unless --keep-download
        with open(os.path.splitext(out_png)[0] + ".json", "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["object_key"], ACHAC_KEY_G19)

    def test_platform_mismatch_is_refused(self):
        listings = {"ABI-L2-ACHAC/2026/290/03/": _listing_xml(
            [(ACHAC_KEY_G19.replace("G19", "G18"), "2026-10-17T03:20:50.000Z", "10")])}
        with mock.patch.object(gch, "download", side_effect=AssertionError("must not download")):
            with self.assertRaises(RuntimeError):
                gch.run(_args(out=os.path.join(self.tmp, "x.png"), download_dir=self.tmp, time="2026-290-03"),
                        bbox=gch.DEFAULT_BBOX, time_req=(2026, 290, 3), fetch=_fake_fetch(listings, []),
                        now=dt.datetime(2026, 10, 17, 3, 30, tzinfo=dt.timezone.utc))

    def test_all_zero_valid_pixels_is_reported_as_none_not_zero(self):
        data = gch.synthetic_dataset("ACHAC", "east")
        data["raw"] = np.full(data["raw"].shape, data["fill"], dtype=data["raw"].dtype)
        png, res = gch.process_dataset(data, gch.DEFAULT_BBOX, product_key="ACHAC")
        self.assertEqual(int(np.count_nonzero(png)), 0)
        self.assertIsNone(res["stats"]["good"]["p50"])
        self.assertEqual(res["stats"]["good"]["n"], 0)


class CmipTests(unittest.TestCase):
    def test_band13_synthetic_pipeline_uses_kelvin_and_no_height_reference(self):
        data = gch.synthetic_dataset("CMIPC13", "west", nx=1200, ny=700)
        png, res = gch.process_dataset(data, gch.DEFAULT_BBOX, product_key="CMIPC13")
        drawn = png[png > 0]
        self.assertGreater(drawn.size, 100000)
        self.assertTrue(np.all((drawn >= 896) & (drawn <= 3413)))
        self.assertEqual(res["stats"]["unit"], "K")
        self.assertIn("note", res["stats"])


class LiveTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get("GOES_LIVE") != "1":
            self.skipTest("set GOES_LIVE=1 for the live bucket check")

    def test_latest_achac_east_listing_and_centre_match_the_file(self):
        try:
            import netCDF4  # noqa: F401
        except ImportError:
            self.skipTest("netCDF4 not installed (needed to open the downloaded file)")
        tmp = tempfile.mkdtemp(prefix="gch-live-")
        try:
            try:
                pick, _bytes, _checked = gch.find_latest("noaa-goes19", gch.PRODUCTS["ACHAC"],
                                                         gch.utcnow(), gch.http_get)
            except (RuntimeError, OSError) as exc:
                self.skipTest(f"no network or bucket unreachable: {exc}")
            self.assertEqual(pick.platform, "G19")
            self.assertTrue(pick.key.startswith("ABI-L2-ACHAC/"))
            dest = os.path.join(tmp, os.path.basename(pick.key))
            try:
                gch.download("https://noaa-goes19.s3.amazonaws.com/" + pick.key, dest, pick.size)
            except (RuntimeError, OSError) as exc:
                self.skipTest(f"download failed: {exc}")
            data = gch.read_netcdf(dest, "ACHAC")
            gl = data["geo_ref"]["geospatial_lat_lon_extent"]
            xm = 0.5 * (data["x"][0] + data["x"][-1])
            ym = 0.5 * (data["y"][0] + data["y"][-1])
            la, lo = gch.scan_to_latlon(xm, ym, data["proj"])
            self.assertAlmostEqual(float(la), float(gl["geospatial_lat_center"]), delta=1e-3)
            self.assertAlmostEqual(float(lo), float(gl["geospatial_lon_center"]), delta=1e-3)
            self.assertEqual(data["proj"].sweep, "x")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
