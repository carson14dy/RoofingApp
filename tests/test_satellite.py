"""The GOES satellite picture (website/satellite.py) and the satellite's share of website/gridded.py: the
fixed-grid geometry, the file reader, the no-data rules, the listings and the East-then-West fallback,
the freshness words, the picture (size, palette, hatching), the sample picture and describe().

Offline: a fake bucket answers the listings and the files. The geometry reference points were computed
once with pyproj (PROJ geos, the projection the files describe) and are written into this file, so
pyproj is not needed to run it. The file reader is checked on a small NetCDF-4 file built with h5py
(skipped when h5py is not installed); the pipeline tests use a stand-in reader that returns the same
kind of arrays and the grid constants of the two live files, so they run without h5py.
"""

import io
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import gridded as g  # noqa: E402
from website import satellite as s  # noqa: E402

try:
    import h5py
except ImportError:          # the file reader is tested only where h5py is installed
    h5py = None

UTC = timezone.utc
SCAN_END = datetime(2026, 10, 17, 15, 58, 55, 900000, tzinfo=UTC)     # the G19 file of the live check
NOW = datetime(2026, 10, 17, 16, 1, 0, tzinfo=UTC)                     # two minutes after it
SCALE, OFFSET = 0.06145332008600235, 89.62000274658203                 # K = raw * SCALE + OFFSET (both files)
X0 = {"G19": -0.10133200138807297, "G18": -0.06997200101613998}         # x of the first column, rad
DX, DY = 5.6000000768108293e-05, -5.6000000768108293e-05               # x and y steps, rad
Y0 = 0.12821200489997864                                               # y of the first row, rad
LON0 = {"G19": -75.0, "G18": -137.0}
BILLINGS = (45.7833, -108.5007)
CORNERS = {"sw": (43.0, -118.5), "nw": (50.5, -118.5), "ne": (50.5, -101.0), "se": (43.0, -101.0)}
LONG_TIME = re.compile(r"\b\d{1,2}:\d{2} (am|pm) M[DS]T\b")
FORBIDDEN = re.compile(r"\bdry\b|\bno hail\b|(?<!-)\bclear\b|\bmeasured\b", re.IGNORECASE)

# pyproj (PROJ geos: h = 35786023.0 m, sweep x, a = 6378137.0, b = 6356752.31414). The scan angle is the
# projected x or y in metres divided by 35786023.0, in radians, to 12 decimals.
PYPROJ = {
    "G19": {"billings": (-0.063434033519, 0.117752725875), "sw": (-0.082240828768, 0.111144820148),
            "nw": (-0.070687194558, 0.124265177917), "ne": (-0.045871714236, 0.126515981836),
            "se": (-0.053547360326, 0.113496644840)},
    "G18": {"billings": (0.055138754755, 0.118363501313), "sw": (0.039011120339, 0.114186642362),
            "nw": (0.033385889462, 0.127173789657), "ne": (0.060905610020, 0.125340738713),
            "se": (0.070972306070, 0.112266897311)},
}


def geos(platform: str) -> s.Geos:
    return s.Geos(lon0_deg=LON0[platform], height_m=35786023.0, req_m=6378137.0, rpol_m=6356752.31414)


def stamp(t: datetime) -> str:
    """A file-name time, YYYYDDDHHMMSS and then tenths of a second."""
    return f"{t:%Y%j%H%M%S}{t.microsecond // 100000}"


def key_for(platform: str, end: datetime) -> str:
    """A band 13 object key as the bucket names it: the scan starts 2 min 38 s before it ends."""
    start = end - timedelta(seconds=158)
    created = end + timedelta(milliseconds=500)
    return (f"ABI-L2-CMIPC/{end:%Y}/{end:%j}/{end:%H}/OR_ABI-L2-CMIPC-M6C13_{platform}_"
            f"s{stamp(start)}_e{stamp(end)}_c{stamp(created)}.nc")


def listing(keys) -> bytes:
    body = "".join(f"<Contents><Key>{k}</Key><Size>3900000</Size></Contents>" for k in keys)
    return ('<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<Name>noaa-goes19</Name><KeyCount>{len(keys)}</KeyCount><IsTruncated>false</IsTruncated>"
            f"{body}</ListBucketResult>").encode()


def marker(platform: str, end: datetime) -> bytes:
    """Stands in for a downloaded file in the pipeline tests; the stand-in reader reads it back."""
    return f"CMI {platform} {end.isoformat()}".encode()


def _scene_raw(seed: int = 5) -> np.ndarray:
    """A live-like scene on the CONUS grid: a 286 K background falling northward, about 1.5 K of noise and a
    cold top near Billings. Raw int16 values, as the file stores them."""
    rng = np.random.default_rng(seed)
    rows, cols = np.indices(s.GRID)
    kelvin = 286.0 - 0.004 * rows + rng.normal(0.0, 1.5, s.GRID)
    kelvin -= 77.0 * np.exp(-0.5 * (((rows - 187) / 120.0) ** 2 + ((cols - 677) / 120.0) ** 2))
    return np.clip(np.rint((kelvin - OFFSET) / SCALE), 0, 4095).astype(np.int16)


_SCENE = None


def stand_in_cmi(platform: str, end: datetime) -> dict:
    """The dict read_cmip returns, built from the scene and the grid constants of the live files."""
    global _SCENE
    if _SCENE is None:
        _SCENE = _scene_raw()
    return {"raw": _SCENE, "dqf": np.zeros(s.GRID, dtype=np.int8), "scale": SCALE, "offset": OFFSET,
            "fill": -1, "valid_range": (0, 4095), "x0": X0[platform], "dx": DX, "y0": Y0, "dy": DY,
            "nx": s.GRID[1], "ny": s.GRID[0], "Geos": geos(platform), "scan_start": end - timedelta(seconds=158),
            "scan_end": end, "platform": platform}


def stand_in_read(data: bytes, expect_platform: str) -> dict:
    """read_cmip for the pipeline tests: the marker's platform and time, with read_cmip's platform check."""
    text = bytes(data).decode("utf-8", "replace")
    if not text.startswith("CMI "):
        raise ValueError("the download was not a NetCDF-4 satellite file")
    _tag, platform, when = text.split(" ", 2)
    if platform != expect_platform:
        raise ValueError(f"the file is from {s._sat_named(platform)}, not {s._sat_named(expect_platform)}")
    return stand_in_cmi(platform, datetime.fromisoformat(when))


class FakeGoes:
    """Answers like the two GOES buckets: a listing per hour prefix, and each file by its key. scans: a list of
    (platform, scan end, bytes). fail: {part of a URL: error}. lists and reads: the URLs asked for."""

    def __init__(self, scans=(), fail=None):
        self.scans = list(scans)
        self.fail = fail or {}
        self.lists, self.reads = [], []

    def __call__(self, url, headers=None):
        for part, err in self.fail.items():
            if part in url:
                return None, err
        if "list-type=2" in url:
            prefix = parse_qs(urlsplit(url).query)["prefix"][0]
            self.lists.append(url)
            keys = sorted(key_for(p, e) for p, e, _data in self.scans if key_for(p, e).startswith(prefix))
            return listing(keys), None
        for platform, end, data in self.scans:
            if url.endswith(key_for(platform, end)):
                self.reads.append(url)
                return data, None
        return None, "not found"


class SatelliteCase(unittest.TestCase):
    """Pipeline tests: the stand-in reader replaces read_cmip, so h5py is not needed."""

    def setUp(self):
        patcher = mock.patch.object(s, "read_cmip", stand_in_read)
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def build(self, get, now=NOW, sample=False):
        return s.build_satellite(self.out, get, now, sample=sample)

    def east(self, end=SCAN_END, data=None):
        return ("G19", end, marker("G19", end) if data is None else data)

    def west(self, end=SCAN_END, data=None):
        return ("G18", end, marker("G18", end) if data is None else data)


# ---------------------------------------------------------------- geometry

class Geometry(unittest.TestCase):
    def test_scan_angles_match_pyproj_for_billings_and_the_box_corners(self):
        for platform, expected in PYPROJ.items():
            points = {"billings": BILLINGS, **CORNERS}
            for name, (lat, lon) in points.items():
                with self.subTest(satellite=platform, point=name):
                    x, y, visible = s.latlon_to_scan(lat, lon, geos(platform))
                    self.assertTrue(bool(visible))
                    self.assertAlmostEqual(float(x), expected[name][0], delta=1e-6)
                    self.assertAlmostEqual(float(y), expected[name][1], delta=1e-6)

    def test_a_grid_of_points_broadcasts_like_the_picture_grid(self):
        lats, lons = g.pixel_centers(s.WIDTH)
        x, y, visible = s.latlon_to_scan(lats[:, None], lons[None, :], geos("G19"))
        self.assertEqual(x.shape, (lats.size, lons.size))
        self.assertTrue(visible.all())
        x1, y1, _ = s.latlon_to_scan(lats[5], lons[9], geos("G19"))
        self.assertAlmostEqual(float(x[5, 9]), float(x1), places=12)
        self.assertAlmostEqual(float(y[5, 9]), float(y1), places=12)

    def test_billings_maps_to_the_pixels_of_the_live_files(self):
        """The nearest pixel: G19 column 677, row 187; G18 column 2234, row 176 (both from the live files)."""
        for platform, want in (("G19", (677, 187)), ("G18", (2234, 176))):
            with self.subTest(satellite=platform):
                x, y, _ = s.latlon_to_scan(BILLINGS[0], BILLINGS[1], geos(platform))
                col = int(np.rint((float(x) - X0[platform]) / DX))
                row = int(np.rint((float(y) - Y0) / DY))
                self.assertEqual((col, row), want)

    def test_the_box_corner_falls_off_the_goes_west_grid_only(self):
        """GOES-West's CONUS grid stops at column 2499. The box's south-east corner falls at column 2517 (0.2 % of
        the box), so that corner has no GOES-West data; GOES-East's grid covers it."""
        x, _y, _ = s.latlon_to_scan(CORNERS["se"][0], CORNERS["se"][1], geos("G18"))
        self.assertEqual(int(np.rint((float(x) - X0["G18"]) / DX)), 2517)
        x, _y, _ = s.latlon_to_scan(CORNERS["se"][0], CORNERS["se"][1], geos("G19"))
        self.assertLess(int(np.rint((float(x) - X0["G19"]) / DX)), s.GRID[1])

    def test_east_is_tried_first_and_west_is_the_fallback(self):
        self.assertEqual([sat.platform for sat in s.SATELLITES], ["G19", "G18"])
        self.assertEqual([sat.key for sat in s.SATELLITES], ["east", "west"])
        self.assertEqual([sat.parallax for sat in s.SATELLITES], ["north-west", "north-east"])
        self.assertEqual(s.SATELLITES[0].short, "GOES-East")
        self.assertEqual(s.SATELLITES[0].name, "GOES-East (GOES-19)")
        self.assertEqual(s.SATELLITES[1].bucket, "noaa-goes18")


class Names(unittest.TestCase):
    def test_file_name_times_carry_tenths_of_a_second(self):
        self.assertEqual(s._stamp("20262901558559"), datetime(2026, 10, 17, 15, 58, 55, 900000, tzinfo=UTC))
        self.assertEqual(s._stamp("20262901556175"), datetime(2026, 10, 17, 15, 56, 17, 500000, tzinfo=UTC))

    def test_a_file_scan_time_reads_with_one_fraction_digit_none_or_six(self):
        """The files carry one fraction digit (2026-10-17T17:23:55.9Z). datetime.fromisoformat takes only 3 or 6
        digits before Python 3.11, so the reader must not depend on it."""
        self.assertEqual(s._iso_utc("2026-10-17T17:23:55.9Z"), datetime(2026, 10, 17, 17, 23, 55, 900000, tzinfo=UTC))
        self.assertEqual(s._iso_utc("2026-10-17T15:58:55Z"), datetime(2026, 10, 17, 15, 58, 55, tzinfo=UTC))
        self.assertEqual(s._iso_utc("2026-10-17T15:58:55.123456Z"),
                         datetime(2026, 10, 17, 15, 58, 55, 123456, tzinfo=UTC))
        self.assertEqual(s._iso_utc("2026-10-17T15:58:55.5+00:00"),
                         datetime(2026, 10, 17, 15, 58, 55, 500000, tzinfo=UTC))
        with self.assertRaisesRegex(ValueError, "scan times were not readable"):
            s._iso_utc("17 Oct 2026")

    def test_a_listing_gives_each_scan_end_from_its_name(self):
        keys = [key_for("G19", SCAN_END), key_for("G19", SCAN_END - timedelta(minutes=5))]
        found = s.parse_listing(listing(keys), s.SATELLITES[0])
        self.assertEqual(found, [(SCAN_END - timedelta(minutes=5), keys[1]), (SCAN_END, keys[0])])

    def test_a_listing_of_the_other_satellite_is_not_taken(self):
        self.assertEqual(s.parse_listing(listing([key_for("G18", SCAN_END)]), s.SATELLITES[0]), [])

    def test_a_listing_that_is_not_xml_is_a_plain_error(self):
        with self.assertRaisesRegex(ValueError, "the list was not readable"):
            s.parse_listing(b"<html>Gateway timeout</html>", s.SATELLITES[0])


class Listings(SatelliteCase):
    def test_both_hours_are_listed_newest_first_across_the_hour_boundary(self):
        fake = FakeGoes([self.east(datetime(2026, 10, 17, 16, 3, 55, 900000, tzinfo=UTC)), self.east(),
                         self.east(SCAN_END - timedelta(minutes=5)), self.east(SCAN_END - timedelta(minutes=20))])
        scans = s.list_scans(fake, datetime(2026, 10, 17, 16, 12, tzinfo=UTC), s.SATELLITES[0])
        self.assertEqual([end for end, _k in scans],
                         [datetime(2026, 10, 17, 16, 3, 55, 900000, tzinfo=UTC), SCAN_END,
                          SCAN_END - timedelta(minutes=5), SCAN_END - timedelta(minutes=20)])
        self.assertEqual(len(fake.lists), 2)

    def test_the_listing_urls_name_the_hour_and_the_platform(self):
        fake = FakeGoes()
        s.list_scans(fake, datetime(2026, 10, 17, 16, 12, tzinfo=UTC), s.SATELLITES[1])
        self.assertEqual(fake.lists, [
            "https://noaa-goes18.s3.amazonaws.com/?list-type=2"
            "&prefix=ABI-L2-CMIPC/2026/290/16/OR_ABI-L2-CMIPC-M6C13_G18_",
            "https://noaa-goes18.s3.amazonaws.com/?list-type=2"
            "&prefix=ABI-L2-CMIPC/2026/290/15/OR_ABI-L2-CMIPC-M6C13_G18_",
        ])

    def test_a_listing_that_fails_is_named_and_raised(self):
        with self.assertRaisesRegex(ValueError, r"^GOES-East file list didn't load \(HTTP 503\)$"):
            s.list_scans(FakeGoes(fail={"noaa-goes19": "HTTP 503"}), NOW, s.SATELLITES[0])


class Freshness(SatelliteCase):
    def test_a_scan_twenty_five_minutes_old_is_drawn_and_called_stale(self):
        now = SCAN_END + timedelta(seconds=1500)
        layer, status = self.build(FakeGoes([self.east()]), now=now)
        self.assertFalse(status["ok"])
        self.assertEqual(status["detail"], "satellite picture is 25 min old; scan ended 9:58 am (GOES-East)")
        self.assertEqual(len(layer["frames"]), 1)
        self.assertTrue((self.out / layer["frames"][0]["src"]).is_file())

    def test_a_scan_under_twenty_minutes_old_is_ok(self):
        layer, status = self.build(FakeGoes([self.east()]), now=SCAN_END + timedelta(seconds=1199))
        self.assertTrue(status["ok"])
        self.assertEqual(status["detail"], "scan ended 9:58 am (GOES-East)")
        self.assertEqual(len(layer["frames"]), 1)

    def test_no_scan_in_the_last_hour_draws_no_picture(self):
        fake = FakeGoes([self.east()])
        layer, status = self.build(fake, now=SCAN_END + timedelta(seconds=3650))
        self.assertFalse(status["ok"])
        self.assertEqual(status["detail"], "no satellite scan in the last 60 minutes")
        self.assertEqual(layer["frames"], [])
        self.assertEqual(layer["modes"], {"12h": []})
        self.assertEqual(layer["now_index"], {"12h": 0})
        self.assertTrue(any("noaa-goes18" in url for url in fake.lists))      # GOES-West was asked too

    def test_no_file_at_all_is_the_same_plain_words(self):
        layer, status = self.build(FakeGoes([]))
        self.assertEqual(status["detail"], "no satellite scan in the last 60 minutes")
        self.assertEqual(layer["frames"], [])

    def test_an_east_scan_older_than_the_hour_falls_back_to_a_fresh_west_scan(self):
        """GOES-West is tried when GOES-East has no scan in the last hour. The West picture is ok (it is fresh),
        and the status names the East reason."""
        fake = FakeGoes([self.east(), self.west(SCAN_END + timedelta(seconds=3350))])
        layer, status = self.build(fake, now=SCAN_END + timedelta(seconds=3650))
        self.assertTrue(status["ok"])
        self.assertEqual(status["detail"], "scan ended 10:54 am (GOES-West; GOES-East's newest scan ended 9:58 am, "
                                           "more than 60 minutes ago)")
        self.assertEqual(layer["frames"][0]["satellite"], "G18")
        self.assertTrue(any("noaa-goes18" in url for url in fake.lists))

    def test_an_east_listing_with_no_scan_falls_back_to_west(self):
        layer, status = self.build(FakeGoes([self.west()]))
        self.assertTrue(status["ok"])
        self.assertEqual(status["detail"],
                         "scan ended 9:58 am (GOES-West; GOES-East has no scan in the last 60 minutes)")
        self.assertEqual(layer["frames"][0]["satellite"], "G18")
        self.assertTrue((self.out / layer["frames"][0]["src"]).is_file())

    def test_a_west_picture_after_an_east_failure_goes_stale_like_an_east_one(self):
        layer, status = self.build(FakeGoes([self.west()], fail={"noaa-goes19": "HTTP 503"}),
                                   now=SCAN_END + timedelta(seconds=1500))
        self.assertFalse(status["ok"])
        self.assertEqual(status["detail"], "satellite picture is 25 min old; scan ended 9:58 am "
                                           "(GOES-West; GOES-East file list didn't load (HTTP 503))")
        self.assertEqual(len(layer["frames"]), 1)


class Fallback(SatelliteCase):
    def test_east_listing_failing_draws_west_and_says_so(self):
        layer, status = self.build(FakeGoes([self.west()], fail={"noaa-goes19": "HTTP 503"}))
        self.assertTrue(status["ok"])       # fresh, as an East picture is: the status words carry the East failure
        self.assertEqual(status["detail"], "scan ended 9:58 am (GOES-West; GOES-East file list didn't load (HTTP 503))")
        frame = layer["frames"][0]
        self.assertEqual(frame["satellite"], "G18")
        self.assertEqual(frame["source"], "NOAA GOES-West (GOES-18) band 13, observation")
        self.assertEqual(frame["src"], "map/frames/satellite-202610171558-g18.png")
        self.assertTrue(frame["nodata"])            # GOES-West's grid misses the box's south-east corner
        self.assertTrue((self.out / frame["src"]).is_file())

    def test_east_download_failing_draws_west(self):
        fake = FakeGoes([self.east(), self.west()], fail={"M6C13_G19_s": "HTTP 503"})
        layer, status = self.build(fake)
        self.assertEqual(layer["frames"][0]["satellite"], "G18")
        self.assertEqual(status["detail"],
                         "scan ended 9:58 am (GOES-West; GOES-East file for 9:58 am didn't load (HTTP 503))")
        self.assertTrue(status["ok"])

    def test_east_file_that_does_not_decode_draws_west(self):
        layer, status = self.build(FakeGoes([self.east(data=b"not a netcdf file"), self.west()]))
        self.assertEqual(layer["frames"][0]["satellite"], "G18")
        self.assertIn("GOES-East file for 9:58 am couldn't be read (the download was not a NetCDF-4 "
                      "satellite file)", status["detail"])

    def test_east_file_for_another_time_than_its_name_is_refused(self):
        wrong = marker("G19", SCAN_END + timedelta(seconds=5))
        layer, status = self.build(FakeGoes([self.east(data=wrong), self.west()]))
        self.assertIn("the file's own time didn't match its name", status["detail"])
        self.assertEqual(layer["frames"][0]["satellite"], "G18")

    def test_a_picture_with_no_usable_value_is_a_failed_file(self):
        with mock.patch.object(s, "sample_field", return_value=np.full((439, 700), np.nan, np.float32)):
            layer, status = self.build(FakeGoes([self.east()]))
        self.assertEqual(layer["frames"], [])
        self.assertIn("GOES-East file for 9:58 am couldn't be read (the file had no usable values over the map)",
                      status["detail"])

    def test_both_failing_names_both(self):
        layer, status = self.build(FakeGoes(fail={"noaa-goes": "HTTP 503"}))
        self.assertFalse(status["ok"])
        self.assertEqual(status["detail"], "GOES-East file list didn't load (HTTP 503); "
                                           "GOES-West file list didn't load (HTTP 503)")
        self.assertEqual(layer["frames"], [])
        self.assertEqual(layer["title"], "Satellite")

    def test_east_failing_and_no_west_scan_names_both_reasons(self):
        layer, status = self.build(FakeGoes([], fail={"noaa-goes19": "HTTP 503"}))
        self.assertEqual(status["detail"], "GOES-East file list didn't load (HTTP 503); "
                                           "GOES-West has no scan in the last 60 minutes")
        self.assertEqual(layer["frames"], [])

    def test_a_fetcher_that_raises_is_a_status_and_never_a_crash(self):
        def boom(url, headers=None):
            raise RuntimeError("socket on fire")
        layer, status = self.build(boom)
        self.assertFalse(status["ok"])
        self.assertEqual(status["detail"],
                         "GOES-East file list didn't load (unexpected error (RuntimeError)); "
                         "GOES-West file list didn't load (unexpected error (RuntimeError))")
        self.assertEqual(layer["frames"], [])

    def test_a_build_error_is_caught_at_the_top(self):
        with mock.patch.object(s, "_build", side_effect=KeyError("boom")):
            layer, status = self.build(FakeGoes())
        self.assertEqual(status, {"label": s.LABEL, "ok": False,
                                  "detail": "the satellite picture couldn't be drawn (unexpected error (KeyError))"})
        self.assertEqual(layer["frames"], [])

    def test_a_picture_that_cannot_be_saved_is_a_status(self):
        with mock.patch.object(g, "_write", side_effect=OSError("disk full")):
            layer, status = self.build(FakeGoes([self.east()]))
        self.assertEqual(layer["frames"], [])
        self.assertEqual(status["detail"], "the satellite picture couldn't be saved (disk full)")


# ---------------------------------------------------------------- the file reader (needs h5py)

def write_cmip(platform="G19", band=13, units="K", scale=True, lon0=-75.0, shape=s.GRID, valid=True,
               end="2026-10-17T15:58:55.9Z") -> bytes:
    """A NetCDF-4 file with the structure of a band 13 CONUS scan (datasets and attributes as the live files
    carry them), built in memory with h5py. Each option breaks one thing."""
    buf = io.BytesIO()
    with h5py.File(buf, "w") as f:
        f.attrs["platform_ID"] = platform
        f.attrs["scene_id"] = "CONUS"
        f.attrs["time_coverage_start"] = "2026-10-17T15:56:17.5Z"
        f.attrs["time_coverage_end"] = end
        f.create_dataset("band_id", data=np.array([band], dtype=np.int32))
        raw = np.full(shape, 3000, dtype=np.int16)
        if tuple(shape) == s.GRID:
            raw[187, 677] = 3125
        raw[0, 0] = -1                                  # a fill cell, as the off-Earth corners carry
        cmi = f.create_dataset("CMI", data=raw, compression="gzip")
        cmi.attrs["_FillValue"] = np.array([-1], dtype=np.int16)
        if valid:
            cmi.attrs["valid_range"] = np.array([0, 4095], dtype=np.int16)
        if scale:
            cmi.attrs["scale_factor"] = np.array([SCALE])
            cmi.attrs["add_offset"] = np.array([OFFSET])
        cmi.attrs["units"] = units
        cmi.attrs["_Unsigned"] = "true"
        d = f.create_dataset("DQF", data=np.zeros(shape, dtype=np.int8), compression="gzip")
        d.attrs["_FillValue"] = np.array([-1], dtype=np.int8)
        d.attrs["valid_range"] = np.array([0, 4], dtype=np.int8)
        xs = f.create_dataset("x", data=np.arange(shape[1], dtype=np.int16))
        xs.attrs["scale_factor"] = np.array([DX])
        xs.attrs["add_offset"] = np.array([X0["G19"]])
        ys = f.create_dataset("y", data=np.arange(shape[0], dtype=np.int16))
        ys.attrs["scale_factor"] = np.array([DY])
        ys.attrs["add_offset"] = np.array([Y0])
        p = f.create_dataset("goes_imager_projection", data=np.int32(0))
        p.attrs["grid_mapping_name"] = "geostationary"
        p.attrs["perspective_point_height"] = np.array([35786023.0])
        p.attrs["semi_major_axis"] = np.array([6378137.0])
        p.attrs["semi_minor_axis"] = np.array([6356752.31414])
        p.attrs["longitude_of_projection_origin"] = np.array([lon0])
        p.attrs["sweep_angle_axis"] = "x"
    return buf.getvalue()


@unittest.skipUnless(h5py, "h5py is not installed")
class ReadFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.good = write_cmip()

    def test_a_band_13_file_reads_with_its_grid_scale_and_times(self):
        cmi = s.read_cmip(self.good, "G19")
        self.assertEqual(cmi["platform"], "G19")
        self.assertEqual(cmi["raw"].shape, s.GRID)
        self.assertEqual(cmi["dqf"].shape, s.GRID)
        self.assertEqual((cmi["nx"], cmi["ny"]), (2500, 1500))
        self.assertEqual(cmi["fill"], -1)
        self.assertEqual(cmi["valid_range"], (0, 4095))
        self.assertAlmostEqual(cmi["scale"], SCALE, places=12)
        self.assertAlmostEqual(cmi["offset"], OFFSET, places=10)
        self.assertAlmostEqual(cmi["x0"], X0["G19"], places=12)
        self.assertAlmostEqual(cmi["dx"], DX, places=12)
        self.assertAlmostEqual(cmi["y0"], Y0, places=12)
        self.assertAlmostEqual(cmi["dy"], DY, places=12)
        self.assertEqual(cmi["scan_start"], datetime(2026, 10, 17, 15, 56, 17, 500000, tzinfo=UTC))
        self.assertEqual(cmi["scan_end"], SCAN_END)
        self.assertEqual(cmi["Geos"].lon0_deg, -75.0)
        self.assertEqual(cmi["Geos"].sweep, "x")

    def test_a_file_whose_scan_end_has_no_fraction_or_six_digits_is_read(self):
        for end, when in (("2026-10-17T15:58:55Z", datetime(2026, 10, 17, 15, 58, 55, tzinfo=UTC)),
                          ("2026-10-17T15:58:55.123456Z", datetime(2026, 10, 17, 15, 58, 55, 123456, tzinfo=UTC))):
            with self.subTest(end=end):
                self.assertEqual(s.read_cmip(write_cmip(end=end), "G19")["scan_end"], when)

    def test_billings_reads_its_pixel_value_through_sample_field(self):
        cmi = s.read_cmip(self.good, "G19")
        value = s.sample_field(cmi, np.array([BILLINGS[0]]), np.array([BILLINGS[1]]))[0, 0]
        self.assertAlmostEqual(float(value), 3125 * SCALE + OFFSET, places=3)

    def test_a_file_from_the_other_satellite_is_named(self):
        with self.assertRaisesRegex(ValueError, r"^the file is from GOES-West, not GOES-East$"):
            s.read_cmip(write_cmip(platform="G18", lon0=-137.0), "G19")

    def test_a_file_of_another_band_is_named(self):
        with self.assertRaisesRegex(ValueError, r"^the file is band 14, not band 13$"):
            s.read_cmip(write_cmip(band=14), "G19")

    def test_a_missing_scale_is_named(self):
        with self.assertRaisesRegex(ValueError, r"^the file had no scale_factor for its values$"):
            s.read_cmip(write_cmip(scale=False), "G19")

    def test_a_missing_valid_range_is_named(self):
        with self.assertRaisesRegex(ValueError, "the file had no valid_range"):
            s.read_cmip(write_cmip(valid=False), "G19")

    def test_values_not_in_kelvin_are_named(self):
        with self.assertRaisesRegex(ValueError, r"^the file's values are not in kelvin$"):
            s.read_cmip(write_cmip(units="1"), "G19")

    def test_a_file_of_another_grid_is_named(self):
        with self.assertRaisesRegex(ValueError, "the file has an unexpected grid size"):
            s.read_cmip(write_cmip(shape=(100, 200)), "G19")

    def test_a_projection_centred_elsewhere_is_named(self):
        with self.assertRaisesRegex(ValueError, r"centred at -137, not -75"):
            s.read_cmip(write_cmip(lon0=-137.0), "G19")

    def test_bytes_that_are_not_netcdf_are_named(self):
        with self.assertRaisesRegex(ValueError, "not a NetCDF-4 satellite file"):
            s.read_cmip(b"<html>nope</html>", "G19")

    def test_an_end_to_end_build_reads_and_draws_a_file(self):
        def get(url, headers=None):
            if "list-type=2" in url:
                return (listing([key_for("G19", SCAN_END)]) if "/15/" in url else listing([])), None
            return self.good, None
        with tempfile.TemporaryDirectory() as tmp:
            layer, status = s.build_satellite(Path(tmp), get, NOW)
            self.assertTrue(status["ok"], status)
            frame = layer["frames"][0]
            self.assertEqual(frame["satellite"], "G19")
            self.assertTrue((Path(tmp) / frame["src"]).is_file())
            with Image.open(Path(tmp) / frame["src"]) as im:
                self.assertEqual((im.mode, im.size), ("P", (700, 439)))


# ---------------------------------------------------------------- sampling and the no-data rules

class Sampling(unittest.TestCase):
    def cmi(self, raw_value=3000, dqf_value=0):
        return {**stand_in_cmi("G19", SCAN_END), "raw": np.full(s.GRID, raw_value, dtype=np.int16),
                "dqf": np.full(s.GRID, dqf_value, dtype=np.int8)}

    def at(self, cmi, lat, lon):
        return float(s.sample_field(cmi, np.array([lat]), np.array([lon]))[0, 0])

    def test_a_known_raw_value_gives_raw_times_scale_plus_offset(self):
        cmi = self.cmi()
        cmi["raw"][187, 677] = 3125
        self.assertAlmostEqual(self.at(cmi, *BILLINGS), 3125 * SCALE + OFFSET, places=4)

    def test_the_nearest_pixel_is_taken_and_nothing_is_interpolated(self):
        cmi = self.cmi(raw_value=2000)
        cmi["raw"][187, 677] = 3125
        cmi["raw"][187, 676] = 2500
        self.assertAlmostEqual(self.at(cmi, *BILLINGS), 3125 * SCALE + OFFSET, places=4)

    def test_the_fill_value_is_no_data(self):
        cmi = self.cmi()
        cmi["raw"][187, 677] = -1
        self.assertTrue(np.isnan(self.at(cmi, *BILLINGS)))

    def test_raw_values_outside_the_valid_range_are_no_data(self):
        for bad in (4096, -2):
            with self.subTest(raw=bad):
                cmi = self.cmi()
                cmi["raw"][187, 677] = bad
                self.assertTrue(np.isnan(self.at(cmi, *BILLINGS)))

    def test_only_quality_flag_zero_is_drawn(self):
        for flag in (1, 2, 3, 4, -1):
            with self.subTest(dqf=flag):
                cmi = self.cmi()
                cmi["dqf"][187, 677] = flag
                self.assertTrue(np.isnan(self.at(cmi, *BILLINGS)))
        self.assertFalse(np.isnan(self.at(self.cmi(), *BILLINGS)))

    def test_cells_outside_the_satellites_grid_are_no_data(self):
        cmi = {**stand_in_cmi("G18", SCAN_END), "raw": np.full(s.GRID, 3000, dtype=np.int16),
               "dqf": np.zeros(s.GRID, dtype=np.int8)}
        self.assertTrue(np.isnan(self.at(cmi, *CORNERS["se"])))          # column 2517 of 2500
        self.assertFalse(np.isnan(self.at(cmi, *CORNERS["sw"])))

    def test_points_over_the_far_side_of_the_earth_are_no_data(self):
        self.assertTrue(np.isnan(self.at(self.cmi(), 0.0, 105.0)))

    def g18(self):
        """A GOES-West stand-in: raw 3000 everywhere, quality flags 0, GOES-West's grid constants."""
        return {**stand_in_cmi("G18", SCAN_END), "raw": np.full(s.GRID, 3000, dtype=np.int16),
                "dqf": np.zeros(s.GRID, dtype=np.int8)}

    def test_a_point_over_the_horizon_is_no_data_because_of_the_horizon_alone(self):
        """50.0 N 151.5 W is beyond GOES-East's horizon, and its pixel (column 96, row 192) lies inside the grid, so
        the grid rule passes. With the horizon rule switched off, the same point is drawn: the horizon is the only
        reason for the no data."""
        cmi = self.cmi()
        lat, lon = 50.0, -151.5
        x, y, visible = s.latlon_to_scan(lat, lon, cmi["Geos"])
        col = int(np.rint((float(x) - cmi["x0"]) / cmi["dx"]))
        row = int(np.rint((float(y) - cmi["y0"]) / cmi["dy"]))
        self.assertFalse(bool(visible))
        self.assertTrue(0 <= col < s.GRID[1] and 0 <= row < s.GRID[0], (col, row))
        self.assertTrue(np.isnan(self.at(cmi, lat, lon)))
        real = s.latlon_to_scan

        def everything_visible(la, lo, g):
            x1, y1, v1 = real(la, lo, g)
            return x1, y1, np.ones(np.shape(v1), dtype=bool)
        with mock.patch.object(s, "latlon_to_scan", everything_visible):
            self.assertFalse(np.isnan(self.at(cmi, lat, lon)))

    def test_a_point_in_western_idaho_is_visible_from_goes_east_and_is_drawn(self):
        """42.811 N 117.182 W was named as a far-side point, and it is not one: GOES-East sees it (column 369, row 308,
        inside the grid), so it is drawn. Kept as a check, so the far-side claim cannot come back unchecked."""
        cmi = self.cmi()
        x, y, visible = s.latlon_to_scan(42.811, -117.182, cmi["Geos"])
        self.assertTrue(bool(visible))
        self.assertEqual((int(np.rint((float(x) - cmi["x0"]) / cmi["dx"])),
                          int(np.rint((float(y) - cmi["y0"]) / cmi["dy"]))), (369, 308))
        self.assertFalse(np.isnan(self.at(cmi, 42.811, -117.182)))

    def test_goes_west_has_no_data_past_its_last_column(self):
        """GOES-West's grid stops at column 2499. 43.7358 N 101.0125 W falls at column 2500, one past the last, and
        the box's south-east corner, 43.0 N 101.0 W, at column 2517: both are no data. 43.7358 N 101.03 W falls at
        column 2499, inside the grid, and is drawn."""
        cmi = self.g18()
        for lat, lon, column in ((43.7358, -101.0125, 2500), (43.0, -101.0, 2517), (43.7358, -101.03, 2499)):
            x, _y, _visible = s.latlon_to_scan(lat, lon, cmi["Geos"])
            self.assertEqual(int(np.rint((float(x) - cmi["x0"]) / cmi["dx"])), column, (lat, lon))
        self.assertTrue(np.isnan(self.at(cmi, 43.7358, -101.0125)))
        self.assertTrue(np.isnan(self.at(cmi, 43.0, -101.0)))
        self.assertAlmostEqual(self.at(cmi, 43.7358, -101.03), 3000 * SCALE + OFFSET, places=3)

    def test_a_field_is_float32_with_nan_only_where_there_is_no_data(self):
        cmi = self.cmi()
        cmi["raw"][:50, :] = -1
        lats, lons = g.pixel_centers(s.WIDTH)
        field = s.sample_field(cmi, lats, lons)
        self.assertEqual(field.dtype, np.float32)
        self.assertEqual(field.shape, (439, 700))
        self.assertTrue(np.isnan(field).any())
        self.assertFalse(np.isnan(field[100:]).any())


# ---------------------------------------------------------------- the picture (palette PNG)

class Picture(unittest.TestCase):
    def test_the_picture_is_a_palette_png_at_700_pixels_under_150_kb(self):
        lats, lons = g.pixel_centers(s.WIDTH)
        field = s.sample_field(stand_in_cmi("G19", SCAN_END), lats, lons)
        png, nodata = g.render(field, s.LAYER)
        self.assertLess(len(png), 150_000)
        with Image.open(io.BytesIO(png)) as im:
            self.assertEqual((im.mode, im.size), ("P", (700, 439)))
        self.assertFalse(nodata)

    def test_one_kelvin_steps_are_palette_steps_from_195(self):
        idx, nodata = g.to_index(np.array([[180.0, 195.0, 209.0, 209.4, 250.0, 297.0, 300.0]]), "satellite")
        self.assertEqual(idx.tolist(), [[2, 2, 16, 16, 57, 104, 107]])
        self.assertFalse(nodata)

    def test_no_value_is_hatched_or_transparent_and_never_a_colour(self):
        field = np.full((20, 30), 250.0, dtype=np.float32)
        field[5:9, 10:14] = np.nan
        idx, nodata = g.to_index(field, "satellite")
        self.assertTrue(nodata)
        self.assertTrue(set(np.unique(idx[5:9, 10:14]).tolist()) <= {0, 1})
        self.assertTrue((idx[~np.isnan(field)] >= 2).all())

    def test_the_satellite_palette_has_its_levels_and_its_hatch(self):
        rgb, alpha = g.palette("satellite")
        self.assertEqual(len(rgb) // 3, 2 + 106)
        self.assertEqual(len(alpha), 2 + 106)
        self.assertEqual(alpha[0], 0)                        # index 0: no value, transparent
        self.assertEqual(alpha[1], round(g.HATCH[1] * 255))  # index 1: the hatch


class FrameShape(SatelliteCase):
    def test_the_frame_dict_keys_and_formats(self):
        layer, _status = self.build(FakeGoes([self.east()]))
        frame = layer["frames"][0]
        self.assertEqual(set(frame), {"time", "kind", "src", "source", "satellite", "scan_start", "scan_end",
                                      "nodata", "coldest_k", "warmest_k"})
        self.assertEqual(frame["kind"], "satellite")
        self.assertEqual(frame["time"], "2026-10-17T15:58:55Z")
        self.assertEqual(frame["scan_start"], "2026-10-17T15:56:17Z")
        self.assertEqual(frame["scan_end"], "2026-10-17T15:58:55Z")
        self.assertEqual(frame["src"], "map/frames/satellite-202610171558-g19.png")
        self.assertEqual(frame["satellite"], "G19")
        self.assertEqual(frame["source"], "NOAA GOES-East (GOES-19) band 13, observation")
        self.assertFalse(frame["nodata"])
        lats, lons = g.pixel_centers(s.WIDTH)
        field = s.sample_field(stand_in_cmi("G19", SCAN_END), lats, lons)
        self.assertEqual(frame["coldest_k"], int(round(float(np.nanmin(field)))))
        self.assertEqual(frame["warmest_k"], int(round(float(np.nanmax(field)))))
        self.assertNotIn("_png", frame)

    def test_the_layer_has_the_gridded_shape_and_the_satellite_words(self):
        layer, _status = self.build(FakeGoes([self.east()]))
        self.assertTrue({"title", "unit", "legend_note", "legend", "gradient", "frames", "modes", "now_index"}
                        <= set(layer))
        self.assertEqual(layer["title"], "Satellite")
        self.assertEqual(layer["unit"], "K")
        self.assertEqual(layer["legend_note"], "Satellite infrared brightness temperature, K. An observation. "
                                               "Not a height and not a hail signal.")
        self.assertEqual(layer["modes"], {"12h": [0]})
        self.assertEqual(layer["now_index"], {"12h": 0})
        self.assertEqual(layer["legend"][0]["label"], "290 K")
        self.assertEqual(layer["legend"][-1]["label"], "195 K")
        self.assertEqual(layer["legend"][0]["pos"], 1.0)
        self.assertEqual(layer["legend"][-1]["pos"], 0.0)
        self.assertTrue(layer["gradient"].startswith("linear-gradient(to top, rgba("))
        json.dumps(layer)                                 # map.json can carry it as is

    def test_a_layer_with_no_picture_keeps_its_words(self):
        layer, _status = self.build(FakeGoes([]))
        self.assertEqual(layer["title"], "Satellite")
        self.assertEqual(layer["unit"], "K")
        self.assertEqual(len(layer["legend"]), 8)
        self.assertEqual(layer["frames"], [])


class Styles(unittest.TestCase):
    def test_the_satellite_stops_ascend_in_kelvin_with_warm_transparent(self):
        stops, log, levels = g.STYLE["satellite"]
        values = [v for v, _c, _a in stops]
        self.assertEqual(values, sorted(values))
        self.assertEqual((values[0], values[-1]), (195, 300))
        self.assertEqual(stops[-1][2], 0.0)
        self.assertFalse(log)
        self.assertEqual(levels, 106)

    def test_the_satellite_legend_is_in_kelvin(self):
        entries, gradient = g.legend("satellite")
        self.assertEqual([e["label"] for e in entries],
                         ["290 K", "275 K", "255 K", "240 K", "225 K", "215 K", "205 K", "195 K"])
        self.assertEqual(entries[0]["value"], 290)
        self.assertNotIn("limit", entries[0])
        self.assertIn("rgba(", gradient)

    def test_the_other_legends_keep_their_units(self):
        self.assertEqual(g.legend("temp")[0][0]["label"], "105°")
        self.assertEqual(g.legend("wind")[0][0]["label"], "75 mph")

    def test_the_radar_and_model_tables_are_untouched(self):
        self.assertEqual(g.WIDTHS, {"precip": 1400, "temp": 700, "wind": 700})
        self.assertEqual(set(g.LAYER_TEXT), {"precip", "temp", "wind"})
        self.assertEqual(set(g.SAMPLE_NOTES), {"precip", "temp", "wind"})


# ---------------------------------------------------------------- the sample picture (no h5py, no network)

class SampleBuild(unittest.TestCase):
    def test_the_scan_is_the_one_before_the_newest_five_minute_scan(self):
        lats, lons = g.pixel_centers(s.WIDTH)
        _field, scan_end = s.sample_frame(datetime(2026, 10, 17, 9, 6, 34, tzinfo=UTC), lats, lons)
        self.assertEqual(scan_end, datetime(2026, 10, 17, 9, 3, tzinfo=UTC))

    def test_the_sample_has_a_cold_top_a_band_and_a_hatched_corner(self):
        lats, lons = g.pixel_centers(s.WIDTH)
        field, _end = s.sample_frame(NOW, lats, lons)
        finite = field[np.isfinite(field)]
        self.assertAlmostEqual(float(finite.min()), 210.0, delta=3.0)
        self.assertGreater(float(finite.max()), 280.0)
        nodata = ~np.isfinite(field)
        self.assertGreater(nodata.mean(), 0.01)
        self.assertLess(nodata.mean(), 0.05)
        rows, cols = np.nonzero(nodata)
        self.assertTrue((lats[rows] > 49.0).all())
        self.assertTrue((lons[cols] > -104.0).all())

    def test_a_sample_build_is_labelled_and_needs_no_h5py_or_network(self):
        def no_network(url, headers=None):
            raise AssertionError("a sample build must not fetch")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"h5py": None}):
            layer, status = s.build_satellite(Path(tmp), no_network, NOW, sample=True)
            self.assertTrue(status["ok"])
            self.assertTrue(status["detail"].startswith("SAMPLE"))
            self.assertIn("scan ended 9:58 am", status["detail"])
            frame = layer["frames"][0]
            self.assertEqual(frame["satellite"], "SAMPLE")
            self.assertEqual(frame["source"], s.SAMPLE_SOURCE)
            self.assertTrue(frame["source"].startswith("SAMPLE"))
            self.assertEqual(frame["src"], "map/frames/satellite-202610171558-sample.png")
            self.assertTrue((Path(tmp) / frame["src"]).is_file())
            self.assertEqual(layer["legend_note"], "Sample: invented picture, not NOAA GOES.")
            self.assertTrue(frame["nodata"])
            with Image.open(Path(tmp) / frame["src"]) as im:
                self.assertEqual(im.size, g.image_size(s.WIDTH))


# ---------------------------------------------------------------- describe()

class Describe(SatelliteCase):
    def test_a_live_picture_is_described_in_plain_words(self):
        layer, status = self.build(FakeGoes([self.east()]))
        frame = layer["frames"][0]
        text = s.describe(layer, status, NOW)
        self.assertEqual(text, "Satellite picture: NOAA GOES-East (GOES-19) band 13, scan ended 9:58 am MDT, "
                               f"retrieved 10:01 am. Coldest brightness temperature in the picture "
                               f"{frame['coldest_k']} K, warmest {frame['warmest_k']} K. "
                               "An observation of infrared brightness temperature: "
                               "not a height and not a hail signal. A cloud top 2 km up is drawn about 3 to 4 km "
                               "north-west of its true place, and a top 12 to 15 km up about 20 to 33 km (parallax). "
                               "Areas warmer than 300 K are left uncoloured, and missing areas show hatch lines; "
                               "uncoloured is not a statement about the weather.")
        for phrase in ("observation", "not a height", "not a hail signal", "north-west of its true place",
                       "uncoloured is not a statement about the weather"):
            self.assertIn(phrase, text)
        self.assertNotIn("more for higher tops", text)
        self.assertRegex(text, LONG_TIME)
        self.assertFalse(FORBIDDEN.search(text), text)

    def test_the_west_picture_is_drawn_north_east_and_says_why(self):
        layer, status = self.build(FakeGoes([self.west()], fail={"noaa-goes19": "HTTP 503"}))
        text = s.describe(layer, status, NOW)
        self.assertTrue(status["ok"])
        self.assertIn("north-east of its true place", text)
        self.assertIn("NOAA GOES-West (GOES-18) band 13", text)
        self.assertIn("GOES-East file list didn't load (HTTP 503).", text)   # why the paragraph is not GOES-East
        self.assertIn("Hatched areas have no satellite data.", text)
        self.assertFalse(FORBIDDEN.search(text), text)

    def test_a_stale_west_picture_after_an_east_failure_says_both_and_is_not_an_all_clear(self):
        now = SCAN_END + timedelta(seconds=1500)
        layer, status = self.build(FakeGoes([self.west()], fail={"noaa-goes19": "HTTP 503"}), now=now)
        text = s.describe(layer, status, now)
        self.assertIn("Satellite picture is 25 min old; scan ended 9:58 am (GOES-West; GOES-East file list "
                      "didn't load (HTTP 503)). This is not an all-clear.", text)

    def test_a_stale_picture_says_how_old_it_is(self):
        now = SCAN_END + timedelta(seconds=1500)
        layer, status = self.build(FakeGoes([self.east()]), now=now)
        text = s.describe(layer, status, now)
        self.assertIn("Satellite picture is 25 min old; scan ended 9:58 am (GOES-East). "
                      "This is not an all-clear.", text)
        self.assertFalse(FORBIDDEN.search(text), text)

    def test_no_picture_says_it_is_not_an_all_clear(self):
        layer, status = self.build(FakeGoes([]))
        text = s.describe(layer, status, NOW)
        self.assertEqual(text, "Satellite picture: no satellite scan in the last 60 minutes. This is not an all-clear.")
        self.assertFalse(FORBIDDEN.search(text))

    def test_the_sample_is_labelled_in_the_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            layer, status = s.build_satellite(Path(tmp), None, NOW, sample=True)
        text = s.describe(layer, status, NOW)
        self.assertTrue(text.startswith("SAMPLE, invented picture. Satellite picture: invented (not NOAA data), "
                                        "scan ended 9:58 am MDT, retrieved 10:01 am."), text)
        self.assertIn("not a hail signal", text)
        self.assertFalse(FORBIDDEN.search(text), text)

    def test_every_description_avoids_the_forbidden_words(self):
        texts = []
        for get in (FakeGoes([self.east()]), FakeGoes([]),
                    FakeGoes([self.west()], fail={"noaa-goes19": "HTTP 503"})):
            layer, status = self.build(get)
            texts.append(s.describe(layer, status, NOW))
        with tempfile.TemporaryDirectory() as tmp:
            layer, status = s.build_satellite(Path(tmp), None, NOW, sample=True)
            texts.append(s.describe(layer, status, NOW))
        for text in texts:
            self.assertFalse(FORBIDDEN.search(text), text)
            self.assertNotIn("measured", text)


class Constants(unittest.TestCase):
    def test_the_numbers_of_the_design(self):
        self.assertEqual(s.LABEL, "GOES satellite picture")
        self.assertEqual(s.LAYER, "satellite")
        self.assertEqual(s.WIDTH, 700)
        self.assertEqual(s.STALE, timedelta(seconds=1200))
        self.assertEqual(s.UNAVAILABLE, timedelta(seconds=3600))
        self.assertEqual(g.image_size(s.WIDTH), (700, 439))


if __name__ == "__main__":
    unittest.main()
