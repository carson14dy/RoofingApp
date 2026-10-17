"""
Map frame checks (website/gridded.py): radar file choice, HRRR byte ranges and run choice, the
Lambert projection, the image grid, colours and legends, the sample build and failure handling.

Offline: no network and no pygrib. The projection is checked against reference points captured
from a real HRRR grid with pygrib's latlons() (run 2026-10-15 21z); where a test needs downloaded
fields, GRIB decoding is swapped for fakes that return small grids. The decoders themselves run
against a stand-in pygrib that hands back the keys of real MRMS and HRRR messages.
"""

import gzip
import io
import json
import math
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import gridded as g  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)          # 9:00 am MDT
SMALL = {"precip": 140, "temp": 70, "wind": 70}           # fast frames for pipeline tests

# The HRRR grid as its GRIB message describes it, and points captured from pygrib latlons():
# (i, j, lat, lon). Corners, the grid centre and points around Montana.
HRRR_GRID = {"nx": 1799, "ny": 1059, "lat1": 21.138123, "lon1": 237.280472, "lov": 262.5, "latin1": 38.5,
             "latin2": 38.5, "dx": 3000.0, "dy": 3000.0, "radius": 6371229.0, "j_pos": True, "i_neg": False}
HRRR_REF = [(0, 0, 21.138123, -122.719528), (1798, 0, 21.140547, -72.289718), (0, 1058, 47.838623, -134.09548),
            (1798, 1058, 47.842195, -60.917193), (899, 529, 38.497247, -97.505977),
            (600, 950, 49.254414, -109.671996), (450, 980, 49.381661, -115.882239),
            (800, 700, 43.052654, -101.150664), (700, 1040, 51.905332, -105.966845)]
# The MRMS grid from a real PrecipRate message, and (row, col, lat, lon) from its latlons().
MRMS_GRID = {"ni": 7000, "nj": 3500, "lat1": 54.995, "lon1": 230.005, "di": 0.01, "dj": 0.01,
             "j_pos": False, "i_neg": False}
MRMS_REF = [(0, 0, 54.995, -129.995), (3499, 6999, 20.005, -60.005), (600, 1500, 48.995, -114.995),
            (1000, 2600, 44.995, -103.995)]
# The keys gridded.py reads, as real messages carry them: an MRMS PrecipRate file for 2026-10-15
# 22:56 UTC and HRRR PRATE from run 21z valid 22z (pygrib gives the scan flags as 0/1 and
# validityTime as HHMM).
MRMS_KEYS = {"discipline": 209, "parameterCategory": 6, "parameterNumber": 1, "gridType": "regular_ll",
             "validityDate": 20261015, "validityTime": 2256, "Ni": 7000, "Nj": 3500,
             "latitudeOfFirstGridPointInDegrees": 54.995, "longitudeOfFirstGridPointInDegrees": 230.005,
             "iDirectionIncrementInDegrees": 0.01, "jDirectionIncrementInDegrees": 0.01,
             "jScansPositively": 0, "iScansNegatively": 0}
HRRR_KEYS = {"discipline": 0, "parameterCategory": 1, "parameterNumber": 7, "gridType": "lambert",
             "validityDate": 20261015, "validityTime": 2200, "shapeOfTheEarth": 6, "Nx": 1799, "Ny": 1059,
             "latitudeOfFirstGridPointInDegrees": 21.138123, "longitudeOfFirstGridPointInDegrees": 237.280472,
             "LoVInDegrees": 262.5, "Latin1InDegrees": 38.5, "Latin2InDegrees": 38.5, "DxInMetres": 3000.0,
             "DyInMetres": 3000.0, "jScansPositively": 1, "iScansNegatively": 0}

# Lines from a real wrfsfcf14 .idx (run 2026-10-15 21z), including its last record.
IDX = """1:0:d=2026101521:REFC:entire atmosphere:14 hour fcst:
8:4223500:d=2026101521:REFD:263 K level:14 hour fcst:
9:4472136:d=2026101521:GUST:surface:14 hour fcst:
10:5829984:d=2026101521:UGRD:250 mb:14 hour fcst:
70:47037744:d=2026101521:SNOD:surface:14 hour fcst:
71:47077814:d=2026101521:TMP:2 m above ground:14 hour fcst:
72:48289538:d=2026101521:POT:2 m above ground:14 hour fcst:
82:63556767:d=2026101521:CPOFP:surface:14 hour fcst:
83:63794441:d=2026101521:PRATE:surface:14 hour fcst:
84:63923105:d=2026101521:APCP:surface:0-14 hour acc fcst:
171:147503115:d=2026101521:SBT124:top of atmosphere:14 hour fcst:
172:149915013:d=2026101521:SBT113:top of atmosphere:14 hour fcst:
173:151406504:d=2026101521:SBT114:top of atmosphere:14 hour fcst:
"""
SUBH_IDX = """24:25366165:d=2026101521:CPOFP:surface:135 min fcst:
25:25472395:d=2026101521:PRATE:surface:135 min fcst:
26:25544554:d=2026101521:APCP:surface:120-135 min acc fcst:
"""


def mrms_key(t: datetime) -> str:
    return f"CONUS/PrecipRate_00.00/{t:%Y%m%d}/MRMS_PrecipRate_00.00_{t:%Y%m%d-%H%M%S}.grib2.gz"


def listing(keys, truncated=False, token=None) -> bytes:
    body = "".join(f"<Contents><Key>{k}</Key><Size>900000</Size></Contents>" for k in keys)
    more = f"<NextContinuationToken>{token}</NextContinuationToken>" if token else ""
    return ('<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<Name>noaa-mrms-pds</Name><KeyCount>{len(keys)}</KeyCount>"
            f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>{body}{more}</ListBucketResult>").encode()


def every_2_min(first: datetime, last: datetime, skip=()):
    out, t = [], first
    while t <= last:
        if t not in skip:
            out.append((t, mrms_key(t)))
        t += timedelta(minutes=2)
    return out


def grib_blob(body: bytes = b"\x00" * 20) -> bytes:
    """A minimal well-formed GRIB2 message: 'GRIB', edition 2, total length, body, '7777'."""
    return b"GRIB\x00\x00\x00\x02" + (16 + len(body) + 4).to_bytes(8, "big") + body + b"7777"


class FakeMsg:
    """Just enough of a pygrib message: keys by name, and .values."""

    def __init__(self, keys, values=None):
        self.keys, self.values = dict(keys), values

    def __getitem__(self, key):
        return self.keys[key]


def png_arrays(data: bytes):
    """(palette indices, RGBA) of a PNG."""
    with Image.open(io.BytesIO(data)) as im:
        return np.array(im), np.array(im.convert("RGBA"))


def nearest_legend_label(rgb, layer="precip") -> str:
    rgb = [int(v) for v in rgb]          # numpy uint8 would wrap around below zero
    entries, _ = g.legend(layer)
    return min(entries, key=lambda e: sum((c - x) ** 2 for c, x in zip(g._hex(e["color"]), rgb)))["label"]


# ---------------------------------------------------------------- radar file list and frame choice

class RadarFiles(unittest.TestCase):
    def test_listing_keeps_only_precip_rate_files_in_time_order(self):
        t1, t2 = datetime(2026, 10, 14, 14, 56, tzinfo=UTC), datetime(2026, 10, 14, 14, 54, tzinfo=UTC)
        doc = listing([mrms_key(t1), "CONUS/PrecipRate_00.00/20261014/README.txt", mrms_key(t2),
                       "CONUS/PrecipRate_00.00/20261014/MRMS_PrecipRate_00.00_20261014-1x5600.grib2.gz"])
        files, token = g.parse_listing(doc)
        self.assertEqual(files, [(t2, mrms_key(t2)), (t1, mrms_key(t1))])
        self.assertIsNone(token)

    def test_unreadable_list_is_an_error_not_an_empty_list(self):
        for bad in (b"", b"<html>Service Unavailable</html>", None):
            with self.assertRaises(ValueError):
                g.parse_listing(bad)
        self.assertEqual(g.parse_listing(listing([])), ([], None))

    def test_truncated_list_is_followed_to_the_end(self):
        a = every_2_min(NOW - timedelta(minutes=20), NOW - timedelta(minutes=12))
        b = every_2_min(NOW - timedelta(minutes=10), NOW - timedelta(minutes=4))
        seen = []

        def get(url, headers=None):
            seen.append(url)
            if "continuation-token" in url:
                return listing([k for _t, k in b]), None
            return listing([k for _t, k in a], truncated=True, token="1x/Y+z"), None

        self.assertEqual(g.list_radar(get, NOW), a + b)
        self.assertIn("continuation-token=1x%2FY%2Bz", seen[1])

    def test_list_requests_reach_the_frames_of_a_three_hour_old_file(self):
        # The newest file may be 3 hours old and its oldest frame is an hour before that, give or
        # take 4 minutes: 4 h 04 min, and a minute more because start-after skips the file it names.
        (url,) = g.mrms_list_urls(NOW)
        q = parse_qs(urlsplit(url).query)
        self.assertTrue(url.startswith(g.MRMS + "?list-type=2"))
        self.assertEqual(q["prefix"], ["CONUS/PrecipRate_00.00/20261014/"])
        self.assertEqual(q["start-after"], [mrms_key(datetime(2026, 10, 14, 10, 55, tzinfo=UTC))])

    def test_near_midnight_yesterday_is_listed_too(self):
        urls = g.mrms_list_urls(datetime(2026, 10, 15, 0, 30, tzinfo=UTC))
        self.assertEqual(len(urls), 2)
        first, second = (parse_qs(urlsplit(u).query) for u in urls)
        self.assertEqual(first["prefix"], ["CONUS/PrecipRate_00.00/20261014/"])
        self.assertEqual(first["start-after"], [mrms_key(datetime(2026, 10, 14, 20, 25, tzinfo=UTC))])
        self.assertEqual(second["prefix"], ["CONUS/PrecipRate_00.00/20261015/"])
        self.assertNotIn("start-after", second)        # would skip the 00:00:00 file
        self.assertEqual(len(g.mrms_list_urls(datetime(2026, 10, 15, 4, 4, tzinfo=UTC))), 2)
        self.assertEqual(len(g.mrms_list_urls(datetime(2026, 10, 15, 4, 5, tzinfo=UTC))), 1)

    def test_seven_frames_ten_minutes_apart_ending_at_the_newest_file(self):
        t0 = datetime(2026, 10, 14, 14, 56, tzinfo=UTC)
        picked, skipped = g.pick_radar(every_2_min(t0 - timedelta(hours=2), t0))
        self.assertEqual([t for t, _k in picked], [t0 - timedelta(minutes=10 * k) for k in range(6, -1, -1)])
        self.assertEqual(skipped, [])

    def test_missing_file_takes_the_nearest_within_four_minutes_else_is_skipped(self):
        t0 = datetime(2026, 10, 14, 14, 56, tzinfo=UTC)
        m = lambda n: t0 - timedelta(minutes=n)  # noqa: E731
        gone = {m(10), m(20), m(18), m(22), m(30), m(28), m(32), m(26), m(34)}
        picked, skipped = g.pick_radar(every_2_min(m(120), t0, skip=gone))
        times = [t for t, _k in picked]
        # 10 min: files 2 min either side, the earlier wins the tie; 20 min: 4 min away still counts;
        # 30 min: nothing within 4 minutes, so that frame is left out (and said so in the status).
        self.assertEqual(times, [m(60), m(50), m(40), m(24), m(12), t0])
        self.assertEqual(skipped, [m(30)])

    def test_no_files_no_frames(self):
        self.assertEqual(g.pick_radar([]), ([], []))


# ---------------------------------------------------------------- HRRR inventories, byte ranges, runs

class ModelFiles(unittest.TestCase):
    def test_idx_records(self):
        recs = g.parse_idx(IDX.encode())
        self.assertEqual(len(recs), 13)
        self.assertEqual(recs[5], {"num": "71", "offset": 47077814, "var": "TMP", "level": "2 m above ground",
                                   "time": "14 hour fcst"})

    def test_a_field_ends_one_byte_before_the_next_record(self):
        recs = g.parse_idx(IDX)
        self.assertEqual(g.byte_range(recs, "TMP", "2 m above ground", "14 hour fcst"), (47077814, 48289537))
        self.assertEqual(g.byte_range(recs, "GUST", "surface", "14 hour fcst"), (4472136, 5829983))
        self.assertEqual(g.byte_range(recs, "PRATE", "surface", "14 hour fcst"), (63794441, 63923104))
        self.assertEqual(g.range_header(4472136, 5829983), {"Range": "bytes=4472136-5829983"})

    def test_the_last_record_is_open_ended(self):
        recs = g.parse_idx(IDX)
        self.assertEqual(g.byte_range(recs, "SBT114", "top of atmosphere", "14 hour fcst"), (151406504, None))
        self.assertEqual(g.range_header(151406504, None), {"Range": "bytes=151406504-"})

    def test_subhourly_fields_are_found_by_minutes(self):
        recs = g.parse_idx(SUBH_IDX)
        self.assertEqual(g.byte_range(recs, "PRATE", "surface", g.lead_label(135, "subh")), (25472395, 25544553))

    def test_records_sharing_an_offset_end_at_the_next_new_offset(self):
        recs = g.parse_idx("5.1:100:d=2026101521:UGRD:10 m above ground:1 hour fcst:\n"
                           "5.2:100:d=2026101521:VGRD:10 m above ground:1 hour fcst:\n"
                           "6:300:d=2026101521:GUST:surface:1 hour fcst:\n")
        self.assertEqual(g.byte_range(recs, "UGRD", "10 m above ground", "1 hour fcst"), (100, 299))

    def test_missing_field_or_empty_index_is_an_error(self):
        with self.assertRaises(ValueError):
            g.byte_range(g.parse_idx(IDX), "PRATE", "surface", "13 hour fcst")
        for bad in (b"", b"<Error><Code>NoSuchKey</Code></Error>"):
            with self.assertRaises(ValueError):
                g.parse_idx(bad)

    def test_lead_labels_match_the_idx_wording(self):
        self.assertEqual(g.lead_label(0, "sfc"), "anl")
        self.assertEqual(g.lead_label(14 * 60, "sfc"), "14 hour fcst")
        self.assertEqual(g.lead_label(135, "subh"), "135 min fcst")

    def test_file_names(self):
        run = datetime(2026, 10, 15, 21, tzinfo=UTC)
        self.assertEqual(g.hrrr_url(run, "sfc", 3),
                         "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.20261015/conus/hrrr.t21z.wrfsfcf03.grib2")
        self.assertEqual(g.hrrr_url(run, "subh", 12),
                         "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.20261015/conus/hrrr.t21z.wrfsubhf12.grib2")

    def test_newest_run_whose_longest_lead_is_published(self):
        tried = []

        def get(url, headers=None):
            tried.append(url.rsplit("/", 1)[1])
            if "t21z.wrfsfcf14" in url:
                return IDX.encode(), None
            return None, "not published (HTTP 404)"

        run, cache = g.find_run(get, datetime(2026, 10, 15, 23, 6, tzinfo=UTC))
        self.assertEqual(run, datetime(2026, 10, 15, 21, tzinfo=UTC))
        self.assertEqual(tried, ["hrrr.t23z.wrfsfcf12.grib2.idx", "hrrr.t22z.wrfsfcf13.grib2.idx",
                                 "hrrr.t21z.wrfsfcf14.grib2.idx"])
        self.assertEqual(len(next(iter(cache.values()))), 13)      # the index is kept for its frame

    def test_no_run_in_four_hours_or_a_network_failure_is_said_in_words(self):
        with self.assertRaisesRegex(ValueError, "no complete HRRR run in the last 4 hours"):
            g.find_run(lambda url, headers=None: (None, "not published (HTTP 404)"), NOW)
        with self.assertRaisesRegex(ValueError, r"didn't load \(ConnectionError\)"):
            g.find_run(lambda url, headers=None: (None, "ConnectionError"), NOW)

    def test_forecast_valid_times(self):
        times = g.forecast_times(datetime(2026, 10, 15, 23, 6, tzinfo=UTC))
        h = lambda d, hh, mm=0: datetime(2026, 10, d, hh, mm, tzinfo=UTC)  # noqa: E731
        self.assertEqual(times["hourly"], [h(16, k) for k in range(12)])
        self.assertEqual(times["quarters"], [h(15, 23, 15), h(15, 23, 30), h(15, 23, 45), h(16, 0)])
        self.assertEqual(times["hours13"], [h(15, 23)] + [h(16, k) for k in range(12)])
        on_the_hour = g.forecast_times(datetime(2026, 10, 15, 23, 0, tzinfo=UTC))
        self.assertEqual(on_the_hour["hourly"][0], h(16, 0))       # "after" the anchor, not at it
        self.assertEqual(on_the_hour["quarters"][0], h(15, 23, 15))

    def test_unit_conversions(self):
        self.assertAlmostEqual(float(g.CONVERT["precip"](np.float32(1 / 3600))), 1.0, places=5)
        self.assertAlmostEqual(float(g.CONVERT["temp"](np.float32(273.15))), 32.0, places=3)
        self.assertAlmostEqual(float(g.CONVERT["wind"](np.float32(10.0))), 22.37, places=2)

    def test_cut_short_or_foreign_downloads_are_refused_before_decoding(self):
        msg = grib_blob()
        self.assertEqual(g.grib_message(msg + b"GRIB-next"), msg)
        with self.assertRaisesRegex(ValueError, "cut short"):
            g.grib_message(msg[:-10])
        with self.assertRaisesRegex(ValueError, "not a GRIB"):
            g.grib_message(b"<Error>AccessDenied</Error>")
        with self.assertRaisesRegex(ValueError, "GRIB2"):
            g.grib_message(b"GRIB\x00\x00\x00\x01" + msg[8:])


# ---------------------------------------------------------------- GRIB decoding, with a stand-in pygrib

class GribDecoding(unittest.TestCase):
    """decode_mrms and decode_hrrr with pygrib swapped for a stand-in that returns one FakeMsg, so the
    field, grid and time checks, the masked-to-NaN fill and the unit conversions run offline."""

    def setUp(self):
        self.got, self.msg = [], None            # bytes handed to fromstring(); the message it returns

        def fromstring(data):
            self.got.append(bytes(data))
            return self.msg

        p = mock.patch.dict(sys.modules, {"pygrib": SimpleNamespace(fromstring=fromstring)})
        p.start()
        self.addCleanup(p.stop)

    def message(self, keys, values=None, **changes):
        self.msg = FakeMsg({**keys, **changes}, np.zeros((2, 3)) if values is None else values)

    def test_hrrr_fields_are_converted_and_masked_cells_are_missing(self):
        valid = datetime(2026, 10, 15, 22, tzinfo=UTC)
        cases = {"precip": ((0, 1, 7), 1 / 3600, 1.0),      # kg m-2 s-1 -> mm/h
                 "temp": ((0, 0, 0), 273.15, 32.0),         # K -> °F
                 "wind": ((0, 2, 22), 10.0, 22.369)}        # m/s -> mph
        for layer, ((d, c, n), raw, shown) in cases.items():
            values = np.ma.masked_array(np.full((2, 3), raw), mask=[[False, False, True], [False] * 3])
            self.message(HRRR_KEYS, values, discipline=d, parameterCategory=c, parameterNumber=n)
            out, grid = g.decode_hrrr(grib_blob() + b"GRIB the next message", layer, valid)
            self.assertEqual(out.dtype, np.float32)
            self.assertTrue(np.isnan(out[0, 2]), layer)                    # masked: missing, never 0
            np.testing.assert_allclose(out[np.isfinite(out)], shown, rtol=1e-4, err_msg=layer)
            self.assertEqual(int(np.isfinite(out).sum()), 5)
            self.assertEqual(grid, HRRR_GRID)                              # read from the message
        self.assertEqual(self.got, [grib_blob()] * 3)                      # only the one message

    def test_hrrr_wrong_field_grid_or_time_is_refused(self):
        valid = datetime(2026, 10, 15, 22, tzinfo=UTC)
        self.message(HRRR_KEYS, parameterCategory=0, parameterNumber=0)    # temperature, not rain rate
        with self.assertRaisesRegex(ValueError, "different field than its index listed"):
            g.decode_hrrr(grib_blob(), "precip", valid)
        self.message(HRRR_KEYS, gridType="regular_ll")
        with self.assertRaisesRegex(ValueError, "unexpected grid"):
            g.decode_hrrr(grib_blob(), "precip", valid)
        self.message(HRRR_KEYS)
        with self.assertRaisesRegex(ValueError, "different time than its index listed"):
            g.decode_hrrr(grib_blob(), "precip", valid + timedelta(hours=1))

    def test_validity_time_is_hours_and_minutes(self):
        # A 15-minute field valid at 00:15 UTC carries validityDate 20261016 and validityTime 15.
        self.message(HRRR_KEYS, validityDate=20261016, validityTime=15)
        out, _grid = g.decode_hrrr(grib_blob(), "precip", datetime(2026, 10, 16, 0, 15, tzinfo=UTC))
        self.assertEqual(out.shape, (2, 3))
        with self.assertRaisesRegex(ValueError, "different time"):
            g.decode_hrrr(grib_blob(), "precip", datetime(2026, 10, 16, 0, 30, tzinfo=UTC))
        self.assertEqual(g._valid_time(FakeMsg({"validityDate": 20261015, "validityTime": 2315})),
                         datetime(2026, 10, 15, 23, 15, tzinfo=UTC))

    def test_mrms_file_is_unzipped_checked_and_its_grid_read(self):
        t = datetime(2026, 10, 15, 22, 56, tzinfo=UTC)
        values = np.array([[0.0, 2.5, -3.0]])
        self.message(MRMS_KEYS, values)
        for data in (gzip.compress(grib_blob() + b"\x00" * 7), grib_blob()):    # as published, and plain
            out, grid = g.decode_mrms(data, t)
            self.assertIs(out, values)          # passed on as is: sample_mrms reads only the map window
            self.assertEqual(grid, MRMS_GRID)
        self.assertEqual(self.got, [grib_blob()] * 2)
        g.decode_mrms(grib_blob(), t + timedelta(minutes=2))                     # within 2 minutes
        with self.assertRaisesRegex(ValueError, "own time didn't match its name"):
            g.decode_mrms(grib_blob(), t + timedelta(minutes=3))
        with self.assertRaisesRegex(ValueError, "own time didn't match its name"):
            g.decode_mrms(grib_blob(), t - timedelta(minutes=3))

    def test_mrms_wrong_product_grid_or_a_cut_short_file_is_refused(self):
        self.message(MRMS_KEYS, discipline=0, parameterCategory=1, parameterNumber=7)
        with self.assertRaisesRegex(ValueError, "not a precipitation-rate grid"):
            g.decode_mrms(grib_blob())
        self.message(MRMS_KEYS, gridType="lambert")
        with self.assertRaisesRegex(ValueError, "unexpected grid"):
            g.decode_mrms(grib_blob())
        self.got.clear()
        with self.assertRaisesRegex(ValueError, "cut short"):
            g.decode_mrms(gzip.compress(grib_blob()[:-10]))
        self.assertEqual(self.got, [])                                           # never decoded

    def test_masked_radar_cells_are_no_coverage(self):
        grid = {"ni": 3, "nj": 1, "lat1": 47.0, "lon1": 250.0, "di": 1.0, "dj": 1.0, "j_pos": False,
                "i_neg": False}
        values = np.ma.masked_array([[1.0, 2.0, 3.0]], mask=[[False, True, False]])
        out = g.sample_mrms(values, grid, np.array([47.0]), np.array([-110.0, -109.0, -108.0]))
        self.assertEqual((out[0, 0], out[0, 2]), (1.0, 3.0))
        self.assertTrue(np.isnan(out[0, 1]))

    def test_earth_shapes(self):
        def radius(**changes):
            return g.lcc_grid(FakeMsg({**HRRR_KEYS, **changes}))["radius"]

        self.assertEqual(radius(), 6371229.0)                                    # HRRR: shape 6
        self.assertEqual(radius(shapeOfTheEarth=0), 6367470.0)
        self.assertEqual(radius(shapeOfTheEarth=1, scaledValueOfRadiusOfSphericalEarth=63712290,
                                scaleFactorOfRadiusOfSphericalEarth=1), 6371229.0)
        with self.assertRaisesRegex(ValueError, "earth shape"):
            radius(shapeOfTheEarth=5)                                            # an ellipsoid


# ---------------------------------------------------------------- projections and the image grid

class Projection(unittest.TestCase):
    def test_lambert_matches_pygrib_latlons(self):
        for i, j, lat, lon in HRRR_REF:
            fi, fj = g.lcc_ij(HRRR_GRID, lat, lon)
            # 0.001 grid cells is 3 m; the reference coordinates are rounded to 1e-6 degrees
            self.assertAlmostEqual(float(fi), i, delta=1e-3, msg=(lat, lon))
            self.assertAlmostEqual(float(fj), j, delta=1e-3, msg=(lat, lon))

    def test_the_whole_image_lies_inside_the_hrrr_grid(self):
        (s, w), (n, e) = g.IMAGE_BOUNDS
        for lat, lon in ((s, w), (s, e), (n, w), (n, e), ((s + n) / 2, w), (n, (w + e) / 2)):
            fi, fj = g.lcc_ij(HRRR_GRID, lat, lon)
            self.assertTrue(0 <= fi <= HRRR_GRID["nx"] - 1 and 0 <= fj <= HRRR_GRID["ny"] - 1, (lat, lon))

    def test_secant_cone_formula_agrees_with_the_tangent_one(self):
        secant = dict(HRRR_GRID, latin2=38.5 + 1e-7)
        for _i, _j, lat, lon in HRRR_REF[4:]:
            a, b = g.lcc_ij(HRRR_GRID, lat, lon), g.lcc_ij(secant, lat, lon)
            self.assertAlmostEqual(float(a[0]), float(b[0]), delta=1e-3)
            self.assertAlmostEqual(float(a[1]), float(b[1]), delta=1e-3)

    def test_bilinear_is_exact_on_a_plane_and_empty_off_the_grid(self):
        jj, ii = np.indices((5, 7)).astype(np.float32)
        values = 2 * ii + 10 * jj
        out = g.bilinear(values, np.array([0.0, 2.5, 6.0, 6.5, -0.1]), np.array([0.0, 1.25, 4.0, 1.0, 1.0]))
        np.testing.assert_allclose(out[:3], [0.0, 17.5, 52.0], rtol=1e-6)
        self.assertTrue(np.isnan(out[3]) and np.isnan(out[4]))

    def test_mrms_index_from_the_message_grid(self):
        for row, col, lat, lon in MRMS_REF:
            r, c, ok_r, ok_c = g.mrms_index(MRMS_GRID, np.array([lat, lat + 0.004]), np.array([lon, lon - 0.004]))
            self.assertEqual((list(r), list(c)), ([row, row], [col, col]))
            self.assertTrue(ok_r.all() and ok_c.all())
        _r, _c, ok_r, ok_c = g.mrms_index(MRMS_GRID, np.array([55.1, 19.9]), np.array([-130.1, -59.9]))
        self.assertFalse(ok_r.any() or ok_c.any())

    def test_mrms_negative_values_are_no_coverage_never_dry(self):
        grid = {"ni": 4, "nj": 3, "lat1": 47.0, "lon1": -110.0 + 360, "di": 1.0, "dj": 1.0, "j_pos": False,
                "i_neg": False}
        values = np.array([[0.0, 2.0, -3.0, 0.5], [1.0, -3.0, 0.0, 0.0], [0.0, 0.0, 0.0, 9.0]])
        out = g.sample_mrms(values, grid, np.array([47.0, 46.0, 30.0]), np.array([-110.0, -109.0, -108.0]))
        self.assertEqual(out[0, 0], 0.0)
        self.assertEqual(out[0, 1], 2.0)
        self.assertTrue(np.isnan(out[0, 2]))        # -3: outside radar coverage
        self.assertTrue(np.isnan(out[1, 1]))
        self.assertTrue(np.isnan(out[2]).all())     # off the grid counts as no coverage too

    def test_frame_sizes(self):
        self.assertEqual(g.image_size(1400), (1400, 878))      # 877.7 and 438.9 rounded
        self.assertEqual(g.image_size(700), (700, 439))
        self.assertEqual({k: g.image_size(w) for k, w in g.WIDTHS.items()},
                         {"precip": (1400, 878), "temp": (700, 439), "wind": (700, 439)})

    def test_columns_linear_in_longitude_rows_linear_in_mercator_north_first(self):
        (s, w), (n, e) = g.IMAGE_BOUNDS
        lats, lons = g.pixel_centers(1400)
        self.assertEqual((len(lats), len(lons)), (878, 1400))
        dx = (e - w) / 1400
        self.assertAlmostEqual(lons[0], w + dx / 2)
        np.testing.assert_allclose(np.diff(lons), dx, rtol=1e-9)
        y = g.merc_y(lats)
        dy = (g.merc_y(n) - g.merc_y(s)) / 878
        np.testing.assert_allclose(np.diff(y), -dy, rtol=1e-6)
        self.assertAlmostEqual(float(g.merc_y(n) - y[0]), float(dy / 2), places=9)   # row 0 is the north edge
        self.assertAlmostEqual(float(y[-1] - g.merc_y(s)), float(dy / 2), places=9)

    def test_aspect_matches_leaflet_image_overlay(self):
        (s, w), (n, e) = g.IMAGE_BOUNDS
        for width in (1400, 700):
            wpx, hpx = g.image_size(width)
            self.assertLessEqual(abs(hpx / wpx - float(g.merc_y(n) - g.merc_y(s)) / math.radians(e - w)), 0.5 / wpx)


# ---------------------------------------------------------------- colours, legends, pictures

class Colours(unittest.TestCase):
    def test_precipitation_thresholds(self):
        values = [0.09, 0.1, 3.0, 8.0, 60.0, -3.0]
        field = np.repeat(np.repeat(np.array([values], dtype=np.float32), 40, axis=0), 40, axis=1)
        png, nodata = g.render(field, "precip")
        self.assertTrue(nodata)
        idx, rgba = png_arrays(png)
        centre = lambda k: (20, 40 * k + 20)  # noqa: E731
        self.assertEqual(rgba[centre(0)][3], 0)                                   # 0.09: transparent
        self.assertEqual(tuple(rgba[centre(1)]), (0x6f, 0xb3, 0xff, round(0.45 * 255)))   # 0.1: light
        for k, label in ((1, "Light"), (2, "Moderate"), (3, "Heavy"), (4, "Extreme")):
            shown = g.level_value("precip", int(idx[centre(k)]) - 2)
            self.assertEqual(g.precip_class(shown), label, values[k])
            self.assertEqual(nearest_legend_label(rgba[centre(k)][:3]), label, values[k])
        block = (slice(4, 36), slice(204, 236))                                    # -3: hatched
        stripes = g.hatch_mask(field.shape, field.shape[1])[block]
        self.assertTrue((idx[block][stripes] == 1).all())
        self.assertTrue((rgba[block][stripes] == (0x8e, 0x8e, 0x93, round(0.35 * 255))).all())
        self.assertTrue((rgba[block][~stripes][:, 3] == 0).all())
        self.assertTrue(stripes.any() and (~stripes).any())

    def test_exact_threshold_without_smoothing(self):
        row = np.array([[0.0999, 0.1, 2.5, 100.0, np.nan, 500.0]], dtype=np.float32)
        self.assertEqual(g.hatch_mask(row.shape, row.shape[1])[0].tolist(), [True, False, False, False, True, False])
        idx, nodata = g.to_index(row, "precip")
        # 0.0999 transparent; 0.1 the first level; 2.5 level 22 (2.54 mm/h); 100 and above the top
        # level; the NaN sits on a stripe, so it is hatched (index 1), not transparent like dry.
        self.assertEqual(idx[0].tolist(), [0, 2, 24, 49, 1, 49])
        self.assertTrue(nodata)
        self.assertEqual([g.precip_class(g.level_value("precip", int(k) - 2)) for k in idx[0, 1:4]],
                         ["Light", "Moderate", "Extreme"])

    def test_precip_classes(self):
        cases = {0.09: None, 0.1: "Light", 2.49: "Light", 2.5: "Moderate", 7.59: "Moderate", 7.6: "Heavy",
                 49.9: "Heavy", 50.0: "Extreme", 60.0: "Extreme", -3.0: "No data"}
        for value, label in cases.items():
            self.assertEqual(g.precip_class(value), label, value)

    def test_precip_legend_matches_the_picture_colours(self):
        entries, gradient = g.legend("precip")
        self.assertEqual([e["label"] for e in entries], ["Extreme", "Heavy", "Moderate", "Light"])
        self.assertEqual([e["value"] for e in entries], [2.0, 0.3, 0.1, 0.004])        # in/h
        self.assertEqual([e["color"] for e in entries], ["#ffd23f", "#d43fc4", "#6a4cf2", "#6fb3ff"])
        for e in entries:
            mm = e["value"] * g.MM_PER_INCH
            self.assertEqual(g.precip_class(mm), e["label"])
            r, gg, b, a = g.colour_at(mm, g.PRECIP_STOPS, log=True)
            self.assertLessEqual(max(abs(x - y) for x, y in zip((r, gg, b), g._hex(e["color"]))), 12)
            self.assertIn(f"rgba({','.join(str(c) for c in g._hex(e['color']))},", gradient)
        self.assertTrue(gradient.startswith("linear-gradient(to top, rgba(111,179,255,0.45) 0.0%"))
        self.assertTrue(gradient.endswith("rgba(255,210,63,0.95) 100.0%)"))
        self.assertEqual([e["pos"] for e in entries], [1.0, 0.6667, 0.3333, 0.0])

    def test_temperature_and_gust_legends_are_the_stops(self):
        temp, _ = g.legend("temp")
        self.assertEqual([e["value"] for e in temp], [s[0] for s in reversed(g.TEMP_STOPS)])
        self.assertEqual([e["color"] for e in temp], [s[1] for s in reversed(g.TEMP_STOPS)])
        self.assertEqual(temp[-1]["label"], "−20°")
        wind, gradient = g.legend("wind")
        self.assertEqual([e["value"] for e in wind], [75, 60, 45, 35, 25, 20, 15, 10])     # 0 is transparent
        self.assertEqual([e["value"] for e in wind if e.get("limit")], [25])
        self.assertTrue(all(e["alpha"] > 0 for e in wind))
        self.assertIn("rgba(255,212,59,0.6)", gradient)

    def test_levels_are_whole_degrees_and_whole_mph(self):
        self.assertEqual([g.level_value("temp", k) for k in (0, 52, 125)], [-20, 32, 105])
        self.assertEqual([g.level_value("wind", k) for k in (0, 25, 75)], [0, 25, 75])
        self.assertAlmostEqual(g.level_value("precip", 0), 0.1)
        self.assertAlmostEqual(g.level_value("precip", 47), 100.0)

    def test_palette_alpha(self):
        rgb, alpha = g.palette("temp")
        self.assertEqual(len(rgb), 3 * len(alpha))
        self.assertEqual((alpha[0], alpha[1]), (0, round(0.35 * 255)))
        self.assertEqual(set(alpha[2:]), {round(0.55 * 255)})
        _rgb, alpha = g.palette("wind")
        self.assertEqual(alpha[2], 0)                      # 0 mph: transparent, not hatched
        self.assertEqual(alpha[2 + 25], round(0.6 * 255))

    def test_missing_temperature_is_hatched_but_below_zero_is_a_temperature(self):
        field = np.full((40, 80), -10.0, dtype=np.float32)
        field[:, 40:] = np.nan
        png, nodata = g.render(field, "temp")
        self.assertTrue(nodata)
        idx, rgba = png_arrays(png)
        self.assertEqual(g.level_value("temp", int(idx[20, 10]) - 2), -10)
        self.assertEqual(rgba[20, 10][3], round(0.55 * 255))
        stripes = g.hatch_mask(field.shape, 80)
        self.assertTrue((idx[:, 44:][stripes[:, 44:]] == 1).all())

    def test_frames_are_palette_pngs_with_transparency(self):
        png, _ = g.render(np.full((10, 20), 30.0, dtype=np.float32), "wind")
        with Image.open(io.BytesIO(png)) as im:
            self.assertEqual((im.mode, im.size), ("P", (20, 10)))
            self.assertIn("transparency", im.info)

    def test_montana_times(self):
        self.assertEqual(g._hm(datetime(2026, 10, 15, 22, 56, tzinfo=UTC)), "4:56 pm")
        self.assertEqual(g._hm(datetime(2026, 10, 16, 6, 5, tzinfo=UTC)), "12:05 am")
        self.assertEqual(g._hm(datetime(2026, 12, 15, 19, 0, tzinfo=UTC)), "12:00 pm")    # MST in winter
        valid, run = datetime(2026, 10, 15, 23, 0, tzinfo=UTC), datetime(2026, 10, 15, 21, 0, tzinfo=UTC)
        self.assertEqual(g.frame_src("precip", valid), "map/frames/precip-202610152300.png")       # radar
        self.assertEqual(g.frame_src("temp", valid, run), "map/frames/temp-202610152300-r2026101521.png")


# ---------------------------------------------------------------- the sample build

class SampleBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.out = Path(tmp.name)
        # Half-size frames: the same code paths (the rain is still drawn at half the precipitation
        # width and stretched) in about a quarter of the 5 s a full-size sample build takes. The
        # patch stays on for the whole class so the size checks below compare like with like.
        widths = mock.patch.dict(g.WIDTHS, {"precip": 700, "temp": 350, "wind": 350})
        widths.start()
        cls.addClassCleanup(widths.stop)

        def no_network(url, headers=None):
            raise AssertionError("a sample build must not fetch anything")

        with mock.patch.dict(sys.modules, {"pygrib": None}):     # and must not need pygrib
            cls.layers, cls.status = g.build_gridded(cls.out, no_network, NOW, sample=True)

    def pixel(self, layer, frame, lat, lon):
        """The value a frame's pixel stands for at a place."""
        (s, w), (n, e) = g.IMAGE_BOUNDS
        with Image.open(self.out / frame["src"]) as im:
            idx = np.array(im)
        h, wd = idx.shape
        x = int((lon - w) / (e - w) * wd)
        y = int(float(g.merc_y(n) - g.merc_y(lat)) / float(g.merc_y(n) - g.merc_y(s)) * h)
        k = int(idx[y, x])
        return None if k < 2 else g.level_value(layer, k - 2)

    def test_status_and_sources_say_sample(self):
        self.assertEqual(set(self.status), {"radar", "forecast"})
        for st in self.status.values():
            self.assertTrue(st["ok"])
            self.assertTrue(st["detail"].startswith("SAMPLE —"), st["detail"])
        self.assertEqual(self.status["radar"]["label"], "NOAA radar (MRMS)")
        for layer in self.layers.values():
            for f in layer["frames"]:
                self.assertTrue(f["source"].startswith("SAMPLE —"), f["source"])

    def test_layer_contract(self):
        self.assertEqual(list(self.layers), ["precip", "temp", "wind"])
        self.assertEqual({k: v["title"] for k, v in self.layers.items()},
                         {"precip": "Precipitation", "temp": "Temperature", "wind": "Wind gusts"})
        self.assertEqual({k: v["unit"] for k, v in self.layers.items()}, {"precip": "in/h", "temp": "°F", "wind": "mph"})
        self.assertIn("Roofing limit 25 mph", self.layers["wind"]["legend_note"])
        for layer in self.layers.values():
            self.assertTrue({"title", "unit", "legend", "legend_note", "frames", "modes", "now_index"} <= set(layer))
        json.dumps(self.layers)                                    # map.json can carry it as is

    def test_legend_notes_say_the_pictures_are_invented(self):
        """The legend sits beside the pictures: in a sample build it must not name the radar or the
        HRRR model as their source (the live notes do, tested in LivePath)."""
        notes = {k: v["legend_note"] for k, v in self.layers.items()}
        self.assertEqual(notes, g.SAMPLE_NOTES)
        for key, note in notes.items():
            self.assertTrue(note.startswith("Rate as liquid water. Sample:" if key == "precip" else "Sample:"), note)
            self.assertNotEqual(note, g.LAYER_TEXT[key]["legend_note"])
            self.assertNotRegex(note, r"(^|\. )HRRR model")         # the live notes start a sentence with it
            self.assertNotIn("Radar estimate", note)
        self.assertIn("not NOAA radar or the HRRR model", notes["precip"])
        self.assertIn("not the HRRR model", notes["temp"])
        self.assertTrue(notes["wind"].endswith("Roofing limit 25 mph."))

    def test_frames_are_chronological_and_their_files_exist(self):
        for name, layer in self.layers.items():
            times = [f["time"] for f in layer["frames"]]
            self.assertEqual(times, sorted(times))
            self.assertEqual(len(set(times)), len(times))
            for f in layer["frames"]:
                self.assertTrue(f["time"].endswith("Z"))
                valid = datetime.fromisoformat(f["time"].replace("Z", "+00:00"))
                with Image.open(self.out / f["src"]) as im:
                    self.assertEqual((im.mode, im.size), ("P", g.image_size(g.WIDTHS[name])))
                if f["kind"] == "forecast":
                    run = datetime.fromisoformat(f["run"].replace("Z", "+00:00"))
                    self.assertEqual(f["lead_min"], (valid - run) / timedelta(minutes=1))
                    self.assertEqual(f["src"], g.frame_src(name, valid, run))     # the run is in the name
                else:
                    self.assertEqual(f["src"], g.frame_src(name, valid))

    def test_modes_and_now(self):
        precip = self.layers["precip"]
        frames = precip["frames"]
        self.assertEqual([f["kind"] for f in frames[:7]], ["radar"] * 7)
        self.assertEqual(len(frames), 7 + 3 + 12)          # the full-hour quarter reuses the hourly frame
        self.assertEqual(len(precip["modes"]["1h"]), 7 + 4)
        self.assertEqual(len(precip["modes"]["12h"]), 7 + 12)
        for mode, indices in precip["modes"].items():
            self.assertEqual(indices, sorted(set(indices)))
            now = frames[indices[precip["now_index"][mode]]]
            self.assertEqual(now["kind"], "radar")
            self.assertEqual(now["time"], frames[6]["time"])
            self.assertEqual([frames[k]["kind"] for k in indices[precip["now_index"][mode] + 1:]],
                             ["forecast"] * (len(indices) - 7))
        quarter_times = [frames[k]["time"][11:16] for k in precip["modes"]["1h"][7:]]
        self.assertEqual(quarter_times, ["15:00", "15:15", "15:30", "15:45"])
        for name in ("temp", "wind"):
            layer = self.layers[name]
            self.assertEqual(list(layer["modes"]), ["12h"])
            self.assertEqual(layer["modes"]["12h"], list(range(13)))
            self.assertEqual(layer["now_index"], {"12h": 0})
            self.assertEqual(layer["frames"][0]["time"], "2026-10-14T14:00:00Z")    # the hour of "now"

    def test_invented_weather_has_the_promised_shape(self):
        frames = self.layers["precip"]["frames"]
        self.assertTrue(frames[0]["nodata"])                       # invented radar coverage edge
        self.assertFalse(any(f["nodata"] for f in frames[7:]))
        core = self.pixel("precip", frames[6], 45.7833, -108.5007)  # Billings at "now"
        self.assertIn(g.precip_class(core), ("Heavy", "Extreme"))
        self.assertIsNone(self.pixel("precip", frames[6], 46.87, -113.99))   # Missoula dry in the morning
        wind = self.layers["wind"]["frames"][0]
        self.assertGreaterEqual(self.pixel("wind", wind, 45.75, -110.25), 40)   # Livingston-Big Timber
        self.assertLess(self.pixel("wind", wind, 48.197, -106.6367), 25)        # Glasgow
        temps = self.layers["temp"]["frames"]
        self.assertLess(self.pixel("temp", temps[0], 44.66, -111.10), self.pixel("temp", temps[0], 46.41, -105.84))
        self.assertGreater(self.pixel("temp", temps[7], 46.41, -105.84),       # 3 pm warmer than 8 am
                           self.pixel("temp", temps[0], 46.41, -105.84))


# ---------------------------------------------------------------- the live path, with fake NOAA buckets

COARSE_LCC = dict(HRRR_GRID, nx=181, ny=107, dx=30000.0, dy=30000.0)      # covers the same area
COARSE_MRMS = {"ni": 700, "nj": 350, "lat1": 54.95, "lon1": 230.05, "di": 0.1, "dj": 0.1, "j_pos": False,
               "i_neg": False}
FIELD = {"precip": 2.0, "temp": 50.0, "wind": 30.0}


class FakeNoaa:
    """Answers like the MRMS and HRRR buckets: listings, files, .idx inventories and byte ranges."""

    def __init__(self, newest, ready=(), fail=None, short=None, empty=False, keep=None):
        self.newest, self.ready, self.fail, self.short, self.empty = newest, set(ready), fail or {}, short, empty
        self.keep = keep or (lambda t: True)       # which radar file times exist (every 2 min by default)
        self.calls = []

    def __call__(self, url, headers=None):
        rng = (headers or {}).get("Range")
        self.calls.append((url, rng))
        for part, err in self.fail.items():
            if part in url:
                return None, err
        if url.startswith(g.MRMS + "?"):
            q = parse_qs(urlsplit(url).query)
            prefix = q["prefix"][0]
            day = datetime.strptime(prefix.split("/")[-2], "%Y%m%d").replace(tzinfo=UTC)
            after = q.get("start-after", [""])[0]
            keys = [] if self.empty else [k for t, k in every_2_min(day, self.newest)
                                          if k.startswith(prefix) and k > after and self.keep(t)]
            return listing(keys), None
        if url.startswith(g.MRMS):
            return b"\x1f\x8b fake radar file", None
        name = url.rsplit("/", 1)[1]
        run = datetime.strptime(url.split("hrrr.")[1][:8] + name[6:8], "%Y%m%d%H").replace(tzinfo=UTC)
        kind = "subh" if ".wrfsubhf" in name else "sfc"
        fh = int(name.split("f")[-1].split(".")[0])
        if run not in self.ready:
            return None, "not published (HTTP 404)"
        if name.endswith(".idx"):
            return self.idx(run, kind, fh), None
        start, _, end = rng.split("=")[1].partition("-")
        size = 64 if not end else int(end) - int(start) + 1
        return b"x" * (size - 1 if self.short and self.short in url else size), None

    @staticmethod
    def idx(run, kind, fh):
        rows = []
        if kind == "sfc":
            label = "anl" if fh == 0 else f"{fh} hour fcst"
            rows = [(0, "REFC", "entire atmosphere", label), (100, "GUST", "surface", label),
                    (250, "TMP", "2 m above ground", label), (400, "PRATE", "surface", label),
                    (550, "APCP", "surface", f"0-{fh} hour acc fcst")]
        else:
            for q in range(1, 5):
                minutes = 60 * (fh - 1) + 15 * q
                rows += [(1000 * q, "GUST", "surface", f"{minutes} min fcst"),
                         (1000 * q + 300, "PRATE", "surface", f"{minutes} min fcst")]
        return "".join(f"{n + 1}:{o}:d={run:%Y%m%d%H}:{v}:{lev}:{lab}:\n"
                       for n, (o, v, lev, lab) in enumerate(rows)).encode()


class LivePath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.decoded = []
        patches = [mock.patch.dict(g.WIDTHS, SMALL),
                   mock.patch.object(g, "decode_mrms", self.fake_mrms),
                   mock.patch.object(g, "decode_hrrr", self.fake_hrrr)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        self.fail_layer = None
        self.radar_expected = []        # the file time each radar decode was asked to check

    def fake_mrms(self, data, expected=None):
        self.radar_expected.append(expected)
        return np.full((350, 700), 1.0, dtype=np.float32), COARSE_MRMS

    def fake_hrrr(self, data, layer, valid):
        if layer == self.fail_layer:
            raise ValueError("the model file held a different field than its index listed")
        self.decoded.append((layer, valid))
        return np.full((107, 181), FIELD[layer], dtype=np.float32), COARSE_LCC

    def build(self, noaa, now=NOW):
        return g.build_gridded(self.out, noaa, now)

    def test_a_full_build(self):
        noaa = FakeNoaa(newest=NOW - timedelta(minutes=4), ready={NOW - timedelta(hours=2), NOW - timedelta(hours=3)})
        layers, status = self.build(noaa)
        self.assertEqual(status["radar"], {"label": "NOAA radar (MRMS)", "ok": True, "detail": "7 frames, latest 8:56 am"})
        self.assertEqual(status["forecast"], {"label": "HRRR forecast", "ok": True, "detail": "run 7:00 am, 12 hours"})
        precip = layers["precip"]
        self.assertEqual(len(precip["frames"]), 22)
        self.assertEqual(precip["modes"]["1h"], list(range(11)))
        self.assertEqual(precip["modes"]["12h"], list(range(8)) + list(range(11, 22)))
        self.assertEqual(precip["now_index"], {"1h": 6, "12h": 6})
        self.assertEqual(precip["frames"][6]["time"], "2026-10-14T14:56:00Z")
        self.assertEqual(precip["frames"][6]["source"], "NOAA MRMS radar estimate")
        self.assertEqual({k: v["legend_note"] for k, v in layers.items()},
                         {k: v["legend_note"] for k, v in g.LAYER_TEXT.items()})     # real data: names its sources
        self.assertEqual([t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in self.radar_expected],
                         [f["time"] for f in precip["frames"][:7]])     # each file checked against its name
        self.assertEqual(precip["frames"][6]["src"], "map/frames/precip-202610141456.png")
        self.assertEqual(precip["frames"][7]["src"], "map/frames/precip-202610141500-r2026101413.png")
        first_forecast = precip["frames"][7]
        self.assertEqual((first_forecast["time"], first_forecast["run"], first_forecast["lead_min"], first_forecast["source"]),
                         ("2026-10-14T15:00:00Z", "2026-10-14T13:00:00Z", 120, "NOAA HRRR model"))
        for name in ("temp", "wind"):
            self.assertEqual(len(layers[name]["frames"]), 13)
            self.assertEqual(layers[name]["frames"][0]["lead_min"], 60)
        for layer in layers.values():
            for f in layer["frames"]:
                self.assertTrue((self.out / f["src"]).is_file(), f["src"])
        # The right fields at the right times, each fetched by its own byte range.
        hrrr = [(u.rsplit("/", 1)[1], r) for u, r in noaa.calls if u.startswith(g.HRRR) and r]
        self.assertIn(("hrrr.t13z.wrfsfcf02.grib2", "bytes=400-549"), hrrr)        # PRATE 15:00
        self.assertIn(("hrrr.t13z.wrfsfcf01.grib2", "bytes=250-399"), hrrr)        # TMP 14:00
        self.assertIn(("hrrr.t13z.wrfsfcf13.grib2", "bytes=100-249"), hrrr)        # GUST 02:00
        self.assertIn(("hrrr.t13z.wrfsubhf03.grib2", "bytes=1300-1999"), hrrr)     # PRATE 15:15 (135 min)
        self.assertEqual(len(hrrr), 12 + 3 + 13 + 13)
        idx_requests = [u for u, _r in noaa.calls if u.endswith(".idx")]
        self.assertEqual(len(idx_requests), len(set(idx_requests)))                 # each index fetched once
        self.assertEqual(sorted(v for layer, v in self.decoded if layer == "temp"),
                         [datetime(2026, 10, 14, 14, tzinfo=UTC) + timedelta(hours=k) for k in range(13)])

    def test_radar_list_failure_keeps_the_forecast(self):
        noaa = FakeNoaa(newest=NOW - timedelta(minutes=4), ready={NOW - timedelta(hours=2)},
                        fail={g.MRMS + "?": "server error (HTTP 503)"})
        layers, status = self.build(noaa)
        self.assertFalse(status["radar"]["ok"])
        self.assertEqual(status["radar"]["detail"], "the radar file list didn't load (server error (HTTP 503))")
        self.assertTrue(status["forecast"]["ok"])
        precip = layers["precip"]
        self.assertFalse([f for f in precip["frames"] if f["kind"] == "radar"])
        self.assertEqual(precip["now_index"], {"1h": 0, "12h": 0})
        self.assertEqual(precip["frames"][0]["time"], "2026-10-14T15:15:00Z")      # after the build time

    def test_no_radar_files(self):
        _layers, status = self.build(FakeNoaa(newest=NOW, ready=(), empty=True))
        self.assertEqual(status["radar"]["detail"], "no radar files in the last 3 hours")

    def test_one_radar_file_failing_drops_the_radar_frames_and_says_which(self):
        noaa = FakeNoaa(newest=NOW - timedelta(minutes=4), ready={NOW - timedelta(hours=2)},
                        fail={"20261014-143600": "not published (HTTP 404)"})
        layers, status = self.build(noaa)
        self.assertFalse(status["radar"]["ok"])
        self.assertEqual(status["radar"]["detail"], "the radar file for 8:36 am didn't load (not published (HTTP 404))")
        self.assertFalse([f for f in layers["precip"]["frames"] if f["kind"] == "radar"])
        self.assertEqual(len(layers["temp"]["frames"]), 13)

    def test_stale_radar_is_shown_but_not_ok(self):
        noaa = FakeNoaa(newest=NOW - timedelta(minutes=46), ready={NOW - timedelta(hours=2)})
        layers, status = self.build(noaa)
        self.assertFalse(status["radar"]["ok"])
        self.assertEqual(status["radar"]["detail"], "radar is 46 min old; 7 frames, latest 8:14 am")
        radar = [f for f in layers["precip"]["frames"] if f["kind"] == "radar"]
        self.assertEqual(len(radar), 7)
        forecast = [f for f in layers["precip"]["frames"] if f["kind"] == "forecast"]
        self.assertEqual(forecast[0]["time"], "2026-10-14T15:15:00Z")               # from the build time

    def test_a_long_radar_outage_still_finds_every_frame(self):
        # Newest file 170 min old: its frames reach back 230 min, past the 3 hours the newest file
        # must lie in. They are all in the bucket, so none may be reported missing.
        noaa = FakeNoaa(newest=NOW - timedelta(minutes=170), ready={NOW - timedelta(hours=2)})
        layers, status = self.build(noaa)
        self.assertEqual(status["radar"], {"label": "NOAA radar (MRMS)", "ok": False,
                                           "detail": "radar is 170 min old; 7 frames, latest 6:10 am"})
        self.assertEqual(len([f for f in layers["precip"]["frames"] if f["kind"] == "radar"]), 7)

    def test_radar_older_than_three_hours_is_left_out(self):
        noaa = FakeNoaa(newest=NOW - timedelta(minutes=190), ready={NOW - timedelta(hours=2)})
        layers, status = self.build(noaa)
        self.assertEqual(status["radar"], {"label": "NOAA radar (MRMS)", "ok": False,
                                           "detail": "no radar files in the last 3 hours"})
        self.assertEqual({f["kind"] for f in layers["precip"]["frames"]}, {"forecast"})
        self.assertEqual(layers["precip"]["frames"][0]["time"], "2026-10-14T15:15:00Z")  # from the build time

    def test_one_radar_frame_is_one_frame(self):
        newest = NOW - timedelta(minutes=4)
        noaa = FakeNoaa(newest=newest, ready={NOW - timedelta(hours=2)}, keep=lambda t: t == newest)
        layers, status = self.build(noaa)
        self.assertEqual(status["radar"], {"label": "NOAA radar (MRMS)", "ok": True, "detail":
                                           "1 frame, latest 8:56 am (no file near 7:56 am, 8:06 am, 8:16 am, "
                                           "8:26 am, 8:36 am, 8:46 am)"})
        self.assertEqual(layers["precip"]["now_index"], {"1h": 0, "12h": 0})

    def test_radar_frames_across_midnight_utc_come_from_both_folders(self):
        now = datetime(2026, 10, 15, 0, 30, tzinfo=UTC)                           # 6:30 pm MDT
        noaa = FakeNoaa(newest=now - timedelta(minutes=4), ready={datetime(2026, 10, 14, 22, tzinfo=UTC)})
        layers, status = self.build(noaa, now)
        self.assertEqual(status["radar"]["detail"], "7 frames, latest 6:26 pm")
        self.assertEqual(status["forecast"]["detail"], "run 4:00 pm, 12 hours")    # 22z, yesterday's folder
        radar = [f["time"] for f in layers["precip"]["frames"] if f["kind"] == "radar"]
        self.assertEqual((radar[0], radar[-1]), ("2026-10-14T23:26:00Z", "2026-10-15T00:26:00Z"))

    def test_a_new_model_run_gets_new_frame_names(self):
        # Browsers may reuse a file for 10 minutes, so a name must never stand for two pictures: the
        # next run redraws the same valid times under new names; radar frames keep theirs.
        names = []
        for run in (NOW - timedelta(hours=2), NOW - timedelta(hours=1)):
            layers, _status = self.build(FakeNoaa(newest=NOW - timedelta(minutes=4), ready={run}))
            names.append({(name, f["kind"], f["time"]): f["src"] for name, layer in layers.items()
                          for f in layer["frames"]})
        old, new = names
        self.assertEqual(old.keys(), new.keys())
        for key in old:
            (self.assertEqual if key[1] == "radar" else self.assertNotEqual)(old[key], new[key], key)
        self.assertEqual(old[("temp", "forecast", "2026-10-14T16:00:00Z")],
                         "map/frames/temp-202610141600-r2026101413.png")
        self.assertEqual(new[("temp", "forecast", "2026-10-14T16:00:00Z")],
                         "map/frames/temp-202610141600-r2026101414.png")

    def test_no_model_run(self):
        layers, status = self.build(FakeNoaa(newest=NOW - timedelta(minutes=4), ready=()))
        self.assertTrue(status["radar"]["ok"])
        self.assertEqual(status["forecast"], {"label": "HRRR forecast", "ok": False,
                                              "detail": "no complete HRRR run in the last 4 hours"})
        self.assertEqual((layers["temp"]["frames"], layers["wind"]["frames"]), ([], []))
        self.assertEqual(layers["temp"]["modes"], {"12h": []})
        self.assertEqual(len(layers["precip"]["frames"]), 7)
        self.assertEqual(layers["precip"]["modes"]["12h"], list(range(7)))

    def test_one_layer_failing_leaves_the_others(self):
        self.fail_layer = "wind"
        layers, status = self.build(FakeNoaa(newest=NOW - timedelta(minutes=4), ready={NOW - timedelta(hours=2)}))
        self.assertFalse(status["forecast"]["ok"])
        self.assertEqual(status["forecast"]["detail"],
                         "wind gusts: the model field for 8:00 am couldn't be read (the model file held a different "
                         "field than its index listed); precipitation and temperature from run 7:00 am")
        self.assertEqual(layers["wind"]["frames"], [])
        self.assertEqual(len(layers["temp"]["frames"]), 13)
        self.assertEqual(len(layers["precip"]["frames"]), 22)

    def test_a_cut_short_field_is_not_drawn(self):
        noaa = FakeNoaa(newest=NOW - timedelta(minutes=4), ready={NOW - timedelta(hours=2)}, short="wrfsubhf03")
        layers, status = self.build(noaa)
        self.assertFalse(status["forecast"]["ok"])
        self.assertIn("precipitation: the model field for 9:15 am was cut short", status["forecast"]["detail"])
        self.assertEqual([f["kind"] for f in layers["precip"]["frames"]], ["radar"] * 7)

    def test_a_downloader_that_raises_never_breaks_the_build(self):
        def broken(url, headers=None):
            raise RuntimeError("boom")

        layers, status = self.build(broken)
        self.assertFalse(status["radar"]["ok"] or status["forecast"]["ok"])
        self.assertEqual(status["radar"]["detail"], "unexpected error (RuntimeError)")
        self.assertTrue(all(layer["frames"] == [] for layer in layers.values()))

    def test_unwritable_output_is_reported(self):
        blocker = self.out / "file"
        blocker.write_text("not a folder")
        noaa = FakeNoaa(newest=NOW - timedelta(minutes=4), ready={NOW - timedelta(hours=2)})
        layers, status = g.build_gridded(blocker, noaa, NOW)
        self.assertFalse(status["radar"]["ok"] or status["forecast"]["ok"])
        self.assertIn("couldn't be saved", status["radar"]["detail"])
        self.assertTrue(all(layer["frames"] == [] for layer in layers.values()))


class WithoutPygrib(unittest.TestCase):
    def test_missing_pygrib_is_reported_not_raised(self):
        noaa = FakeNoaa(newest=NOW - timedelta(minutes=4), ready={NOW - timedelta(hours=2)})
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(g.WIDTHS, SMALL), \
                mock.patch.dict(sys.modules, {"pygrib": None}):
            layers, status = g.build_gridded(Path(tmp), noaa, NOW)
        self.assertFalse(status["radar"]["ok"] or status["forecast"]["ok"])
        self.assertEqual(status["radar"]["detail"],
                         "the radar file for 7:56 am couldn't be read (pygrib isn't installed on the build machine)")
        self.assertIn("pygrib isn't installed", status["forecast"]["detail"])
        self.assertTrue(all(layer["frames"] == [] for layer in layers.values()))


if __name__ == "__main__":
    unittest.main()
