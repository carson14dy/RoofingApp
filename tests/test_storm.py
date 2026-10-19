"""Radar echo tops (website/storm.py): the echo top, the no-data codes, heights below ground, the common
time, the named reasons, stale and failed feeds, the words, and the checks on each GRIB file.

Offline: a fake bucket answers the listings and the files, and pygrib is a stand-in that reads a small
JSON body inside each fake GRIB message (the same approach as tests/test_gridded.py). The sample build's
storm values are checked in tests/test_site.py.
"""

import gzip
import json
import random
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import gridded as g  # noqa: E402
from website import sources as src  # noqa: E402
from website import storm as st  # noqa: E402

UTC = timezone.utc
STEP = datetime(2026, 10, 17, 9, 6, 34, tzinfo=UTC)     # 3:06 am MDT: the newest common time in most tests
NOW = STEP + timedelta(minutes=4)
TOWNS = [
    {"slug": "billings", "name": "Billings", "lat": 45.7833, "lon": -108.5007, "ground_m": 975.1},
    {"slug": "bozeman", "name": "Bozeman", "lat": 45.677, "lon": -111.0429, "ground_m": 1455.1},
    {"slug": "west-yellowstone", "name": "West Yellowstone", "lat": 44.6621, "lon": -111.1041, "ground_m": 2100.0},
]
LEVEL_NAMES = st.LEVEL_NAMES
HEIGHTS = st.HEIGHTS_M
FORBIDDEN = re.compile(r"\bdry\b|\bno hail\b|(?<!-)\bclear\b|no radar coverage", re.IGNORECASE)
VALID_TIME = re.compile(r"valid \d{1,2}:\d{2} (am|pm) M[DS]T")


def grib_blob(body: bytes) -> bytes:
    """A minimal well-formed GRIB2 message: 'GRIB', edition 2, total length, body, '7777'."""
    return b"GRIB\x00\x00\x00\x02" + (16 + len(body) + 4).to_bytes(8, "big") + body + b"7777"


def key_for(level: str, t: datetime) -> str:
    return (f"CONUS/MergedReflectivityQC_{level}/{t:%Y%m%d}/"
            f"MRMS_MergedReflectivityQC_{level}_{t:%Y%m%d-%H%M%S}.grib2.gz")


def listing(keys) -> bytes:
    body = "".join(f"<Contents><Key>{k}</Key><Size>900000</Size></Contents>" for k in keys)
    return ('<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<Name>noaa-mrms-pds</Name><KeyCount>{len(keys)}</KeyCount><IsTruncated>false</IsTruncated>"
            f"{body}</ListBucketResult>").encode()


def core(height_m, lat, lon):
    """Billings: 42 dBZ at every height up to 8 km (500 m is below ground there). Bozeman: a weak echo,
    -5 dBZ, a value. Elsewhere in Montana: no radar value (-99). Outside the box: -999."""
    if lat > 49.5 or lat < 40.0:
        return -999.0
    if abs(lat - 45.78) < 0.1 and abs(lon + 108.5) < 0.1:
        return 42.0 if height_m <= 8000 else 18.0
    if abs(lat - 45.68) < 0.1 and abs(lon + 111.04) < 0.1:
        return -5.0
    return -99.0


class FieldValues:
    """One height's grid values, computed from latitude and longitude. Indexing takes the (rows, cols)
    arrays that gridded.mrms_index returns, so no full 7000 x 3500 grid is built."""

    def __init__(self, fn, grid):
        self.fn, self.grid = fn, grid

    def __getitem__(self, index):
        rows, cols = index
        lat = self.grid["lat1"] - np.asarray(rows, dtype=float) * self.grid["dj"]
        lon = ((self.grid["lon1"] + np.asarray(cols, dtype=float) * self.grid["di"] + 180.0) % 360.0) - 180.0
        return np.array([self.fn(float(a), float(b)) for a, b in zip(lat, lon)])


def stand_in_message(data: bytes, field):
    """What pygrib.fromstring gives for a fake message: keys by name, and .values."""
    body = json.loads(data[16:-4].decode())
    t = body["time"]
    keys = {"discipline": body["param"][0], "parameterCategory": body["param"][1],
            "parameterNumber": body["param"][2], "gridType": body["grid"], "typeOfLevel": "heightAboveSea",
            "level": body["level_m"], "Ni": body["Ni"], "Nj": body["Nj"],
            "validityDate": int(t[:8]), "validityTime": int(t[8:12]),
            "latitudeOfFirstGridPointInDegrees": 54.995, "longitudeOfFirstGridPointInDegrees": 230.005,
            "iDirectionIncrementInDegrees": 0.01, "jDirectionIncrementInDegrees": 0.01,
            "jScansPositively": 0, "iScansNegatively": 0, **body.get("override", {})}
    grid = {"ni": keys["Ni"], "nj": keys["Nj"], "lat1": 54.995, "lon1": 230.005, "di": 0.01, "dj": 0.01,
            "j_pos": False, "i_neg": False}
    return FakeMessage(keys, FieldValues(field(body["level_m"]), grid))


class MaskedValues:
    """What pygrib gives for a grid with missing cells: a masked array with its mask set, the number kept under it."""

    def __init__(self, inner):
        self.inner = inner

    def __getitem__(self, index):
        values = self.inner[index]
        return np.ma.masked_array(values, mask=np.ones(values.shape, dtype=bool))


class FakeMessage:
    """A pygrib message: keys by name, and .values."""

    def __init__(self, keys, values):
        self.keys, self.values = keys, values

    def __getitem__(self, name):
        return self.keys[name]


class FakeBucket:
    """Answers like the MRMS bucket for the 11 heights: listings with start-after, and each file as gzipped
    GRIB. times: {height name: [file times]}. fail: {part of a URL: error}. override: {height name: {message
    key: value}}, to make one file wrong on purpose. reads: the file URLs fetched."""

    def __init__(self, times, fail=None, override=None):
        self.times, self.fail, self.override = times, fail or {}, override or {}
        self.reads = []

    def __call__(self, url, headers=None):
        for part, err in self.fail.items():
            if part in url:
                return None, err
        if url.startswith(g.MRMS + "?"):
            q = parse_qs(urlsplit(url).query)
            prefix = q["prefix"][0]
            level = prefix.split("/")[1].split("_")[1]
            day = prefix.split("/")[2]
            after = q.get("start-after", [""])[0]
            keys = sorted(key_for(level, t) for t in self.times.get(level, [])
                          if f"{t:%Y%m%d}" == day and key_for(level, t) > after)
            return listing(keys), None
        name = url.rsplit("/", 1)[1]                     # MRMS_MergedReflectivityQC_00.50_20261017-090634.grib2.gz
        level = name.split("_")[2]
        t = datetime.strptime(name.split("_")[3][:15], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
        self.reads.append(url)
        body = {"level_m": round(float(level) * 1000), "time": f"{t:%Y%m%d%H%M%S}", "param": [209, 9, 0],
                "grid": "regular_ll", "Ni": 7000, "Nj": 3500, "override": self.override.get(level, {})}
        return gzip.compress(grib_blob(json.dumps(body).encode())), None


def every_height(at=STEP, extra=None):
    """Every height has a file at `at`; extra: {height name: [times]} adds more files to a height."""
    files = {level: [at] for level in LEVEL_NAMES}
    for level, more in (extra or {}).items():
        files[level] = sorted(set(files[level]) | set(more))
    return files


class StormCase(unittest.TestCase):
    def setUp(self):
        self.field = core
        p = mock.patch.dict(sys.modules, {"pygrib": SimpleNamespace(fromstring=self.fromstring)})
        p.start()
        self.addCleanup(p.stop)

    def fromstring(self, data):
        return stand_in_message(data, lambda level_m: lambda lat, lon: self.field(level_m, lat, lon))

    def run_storm(self, bucket, towns=TOWNS, now=NOW):
        return st.collect(bucket, now, towns)

    def assert_words(self, text):
        self.assertFalse(FORBIDDEN.search(text), text)
        self.assertIn("This is not an all-clear.", text)


class EchoTop(StormCase):
    def test_the_echo_top_is_the_highest_height_at_35_dbz_above_ground(self):
        results, status = self.run_storm(FakeBucket(every_height()))
        b = results["billings"]
        self.assertEqual((b["status"], b["echo_top_m"]), ("loaded", 8000))
        self.assertEqual((b["max_dbz"], b["max_dbz_m"]), (42.0, 8000))
        self.assertEqual((b["valid_levels"], b["no_data_levels"], b["below_ground_levels"]), (11, 0, 1))
        self.assertEqual(b["valid_time_utc"], "2026-10-17T09:06:34Z")
        self.assertEqual(b["text"],
                         "Echo top (radar estimate): 8,000 m above sea level, valid 3:06 am MDT. dBZ 35 or more at "
                         "7 of the 10 heights above ground with radar data (1 height below ground, not used). "
                         "This is not an all-clear.")
        self.assertFalse(b["echo_top_at_least"])
        self.assertTrue(status["ok"])
        self.assertIn("echo top at 1 of 3 towns", status["detail"])

    def test_35_dbz_is_an_echo_and_34_9_is_not(self):
        for value, is_echo in ((34.99, False), (34.9, False), (35.0, True), (39.9, True)):
            with self.subTest(dbz=value):
                self.field = lambda h, lat, lon, v=value: v if h == 3000 else -99.0
                results, _ = self.run_storm(FakeBucket(every_height()), towns=[TOWNS[0]])
                b = results["billings"]
                if is_echo:
                    self.assertEqual(b["echo_top_m"], 3000)
                else:
                    self.assertIsNone(b["echo_top_m"])
                    self.assertIn("No echo at or above 35 dBZ", b["text"])

    def test_the_eleven_heights_are_the_mrms_levels(self):
        self.assertEqual(LEVEL_NAMES, ("00.50", "01.00", "02.00", "03.00", "04.00", "05.00", "06.00", "08.00",
                                       "10.00", "12.00", "15.00"))
        self.assertEqual(HEIGHTS, (500, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000, 12000, 15000))

    def test_a_negative_dbz_is_a_weak_echo_value_not_a_gap(self):
        results, _ = self.run_storm(FakeBucket(every_height()))
        bozeman = results["bozeman"]
        self.assertEqual(bozeman["valid_levels"], 11)
        self.assertEqual(bozeman["levels"][0]["dbz"], -5.0)
        self.assertIsNone(bozeman["echo_top_m"])


class Sentinels(StormCase):
    def test_no_data_codes_are_never_a_value_or_zero(self):
        out = st._no_data_to_nan([-99.0, -999.0, 0.0, -5.0, 12.5, np.nan, np.inf, -98.9])
        self.assertTrue(np.isnan(out[0]) and np.isnan(out[1]) and np.isnan(out[5]) and np.isnan(out[6]))
        self.assertEqual(list(out[2:5]), [0.0, -5.0, 12.5])      # a real 0 dBZ stays a value
        self.assertEqual(out[7], -98.9)                           # close to -99 is not -99

    def test_a_town_with_only_no_data_has_zero_values_and_a_named_reason(self):
        results, _ = self.run_storm(FakeBucket(every_height()))
        wy = results["west-yellowstone"]
        self.assertEqual((wy["valid_levels"], wy["no_data_levels"]), (0, 11))
        self.assertIsNone(wy["echo_top_m"])
        self.assertIsNone(wy["max_dbz"])
        self.assertTrue(all(level["dbz"] is None for level in wy["levels"]))
        self.assertEqual(wy["text"], "No radar value (radar estimate; code -99 means missing, code -999 means no "
                                     "coverage) at any of the 8 heights above ground, valid 3:06 am MDT (3 heights "
                                     "below ground, not used). This is not an all-clear.")
        self.assert_words(wy["text"])

    def test_valid_and_no_data_levels_always_add_up_to_eleven(self):
        rng = random.Random(7)
        for _ in range(300):
            dbz = {h: (float("nan") if rng.random() < 0.4 else rng.uniform(-30, 60)) for h in HEIGHTS}
            ground = rng.choice([None, 500.0, 1200.0, 2100.0, 9000.0])
            col = st.column(dbz, ground)
            self.assertEqual(col["valid"] + col["nodata_all"], 11)
            if ground is not None:
                self.assertEqual(col["above"] + col["below"], 11)
                self.assertEqual(col["data"] + col["nodata"], col["above"])


class BelowGround(StormCase):
    def test_heights_below_ground_are_counted_and_not_used(self):
        self.field = lambda h, lat, lon: 40.0 if h <= 2000 else (12.0 if lat > 40 else -99.0)
        results, _ = self.run_storm(FakeBucket(every_height()))
        wy = results["west-yellowstone"]
        self.assertEqual(wy["below_ground_levels"], 3)            # 0.5, 1 and 2 km under 2,100 m
        self.assertIsNone(wy["echo_top_m"])                       # the 40 dBZ below ground is not an echo top
        self.assertEqual((wy["max_dbz"], wy["max_dbz_m"]), (12.0, 15000))   # the peak is taken above ground only
        self.assertIn("All 8 heights above ground had radar data, and none reached 35 dBZ (3 heights below ground, "
                      "not used)", wy["text"])
        self.assert_words(wy["text"])

    def test_a_level_at_exactly_the_ground_height_is_above_ground(self):
        self.field = lambda h, lat, lon: 40.0 if h == 2000 else -99.0
        results, _ = self.run_storm(FakeBucket(every_height()), towns=[dict(TOWNS[0], ground_m=2000.0)])
        b = results["billings"]
        self.assertEqual(b["below_ground_levels"], 2)            # 0.5 and 1 km only
        self.assertEqual(b["echo_top_m"], 2000)                  # the 2 km level counts: it is at ground

    def test_a_town_needs_its_ground_height_for_an_echo_top(self):
        results, status = self.run_storm(FakeBucket(every_height()), towns=[dict(TOWNS[0], ground_m=None)])
        b = results["billings"]
        self.assertEqual(b["status"], "problem")
        self.assertIsNone(b["echo_top_m"])
        self.assertIsNone(b["below_ground_levels"])
        self.assertEqual((b["valid_levels"], b["no_data_levels"]), (11, 0))     # the values are still counted
        self.assertEqual(len(b["levels"]), 11)
        self.assertIsNone(b["levels"][0]["below_ground"])
        self.assertIn("ground height didn't load", b["text"])
        self.assertTrue(status["ok"])                             # the radar files themselves were fine
        self.assertIn("ground height missing at 1 of 1 towns", status["detail"])


class CommonTime(StormCase):
    def test_the_newest_time_with_every_height_within_ten_seconds_is_joined(self):
        t0 = STEP - timedelta(minutes=2)
        files = {level: [t0 - timedelta(seconds=2), t0, STEP] for level in LEVEL_NAMES}
        files["06.00"] = [t0 - timedelta(seconds=2), t0 + timedelta(seconds=12)]   # nothing within 10 s of STEP
        files["15.00"] = [t0 - timedelta(seconds=2), t0, STEP + timedelta(seconds=2)]
        found = st.common_step({k: [(t, key_for(k, t)) for t in v] for k, v in files.items()})
        self.assertIsNotNone(found)
        when, picks = found
        self.assertEqual(when, t0)
        self.assertEqual(picks["06.00"][0], t0 - timedelta(seconds=2))
        self.assertEqual(picks["15.00"][0], t0)

    def test_each_height_takes_its_nearest_file_to_the_join(self):
        times = [STEP - timedelta(seconds=7), STEP + timedelta(seconds=3)]
        files = {level: [(t, key_for(level, t)) for t in times] for level in LEVEL_NAMES}
        when, picks = st.common_step(files)
        self.assertEqual(when, STEP + timedelta(seconds=3))       # the newest candidate with every height
        self.assertTrue(all(picks[level][0] == when for level in LEVEL_NAMES))

    def test_heights_that_never_share_a_time_give_no_join(self):
        files = every_height()
        files["15.00"] = [STEP + timedelta(seconds=15)]           # 15 s from the others: not within 10 s
        self.assertIsNone(st.common_step({k: [(t, key_for(k, t)) for t in v] for k, v in files.items()}))

    def test_a_height_with_no_file_gives_no_join(self):
        files = every_height()
        files["03.00"] = []
        self.assertIsNone(st.common_step({k: [(t, key_for(k, t)) for t in v] for k, v in files.items()}))

    def test_the_record_carries_the_join_time_not_a_later_single_height(self):
        extra = {"15.00": [STEP + timedelta(seconds=15)]}          # a newer 15 km file, not joined
        results, _ = self.run_storm(FakeBucket(every_height(extra=extra)))
        self.assertEqual(results["billings"]["valid_time_utc"], "2026-10-17T09:06:34Z")

    def test_no_file_in_the_last_hour_is_a_named_problem(self):
        results, status = self.run_storm(FakeBucket({level: [STEP - timedelta(hours=2)] for level in LEVEL_NAMES}))
        self.assertFalse(status["ok"])
        self.assertIn("no time in the last 60 minutes had all 11 heights", status["detail"])
        for t in TOWNS:
            self.assertEqual(results[t["slug"]]["status"], "problem")
            self.assertTrue(results[t["slug"]]["text"].startswith("Echo top not available:"))
            self.assert_words(results[t["slug"]]["text"])


class Freshness(StormCase):
    def test_older_than_thirty_minutes_is_stale_and_says_how_old(self):
        results, status = self.run_storm(FakeBucket(every_height()), now=STEP + timedelta(minutes=45))
        b = results["billings"]
        self.assertEqual(b["status"], "stale")
        self.assertFalse(status["ok"])
        self.assertTrue(status["detail"].startswith("radar is 45 min old; "))
        self.assertIn("The radar is 45 min old, past the 30-minute limit.", b["text"])
        self.assert_words(b["text"])

    def test_thirty_minutes_old_is_still_loaded(self):
        results, status = self.run_storm(FakeBucket(every_height()), now=STEP + timedelta(minutes=30))
        self.assertEqual(results["billings"]["status"], "loaded")
        self.assertTrue(status["ok"])


class FailedFeeds(StormCase):
    def test_a_height_that_does_not_load_drops_the_whole_set_with_its_reason(self):
        bucket = FakeBucket(every_height(), fail={"MRMS_MergedReflectivityQC_15.00_20261017-090634": "HTTP 503"})
        results, status = self.run_storm(bucket)
        self.assertFalse(status["ok"])
        self.assertIn("the radar file for 15 km at 3:06 am MDT didn't load: HTTP 503", status["detail"])
        for t in TOWNS:
            self.assertEqual(results[t["slug"]]["status"], "problem")
            self.assertIsNone(results[t["slug"]]["echo_top_m"])
            self.assertIn("HTTP 503", results[t["slug"]]["text"])
            self.assert_words(results[t["slug"]]["text"])

    def test_a_listing_that_does_not_load_is_a_problem(self):
        bucket = FakeBucket(every_height(), fail={"prefix=CONUS/MergedReflectivityQC_06.00": "server error (HTTP 503)"})
        results, status = self.run_storm(bucket)
        self.assertFalse(status["ok"])
        self.assertIn("the radar file list for 6 km didn't load: server error (HTTP 503)", status["detail"])

    def test_an_exception_in_the_fetcher_is_a_status_not_a_crash(self):
        def boom(url, headers=None):
            raise RuntimeError("socket on fire")
        results, status = st.collect(boom, NOW, TOWNS)
        self.assertFalse(status["ok"])
        self.assertEqual(status["detail"], "unexpected error (RuntimeError)")
        self.assertEqual(results["billings"]["status"], "problem")

    def test_missing_pygrib_is_named_not_raised(self):
        with mock.patch.dict(sys.modules, {"pygrib": None}):
            _, status = self.run_storm(FakeBucket(every_height()))
        self.assertFalse(status["ok"])
        self.assertIn("pygrib isn't installed on the build machine", status["detail"])


class FileChecks(StormCase):
    def test_a_file_for_another_height_is_refused(self):
        _, status = self.run_storm(FakeBucket(every_height(), override={"04.00": {"level": 3000}}))
        self.assertFalse(status["ok"])
        self.assertIn("the radar file for 4 km at 3:06 am MDT couldn't be read: the radar file was not the 4 km height",
                      status["detail"])

    def test_a_file_that_is_not_reflectivity_is_refused(self):
        _, status = self.run_storm(FakeBucket(every_height(), override={"01.00": {"parameterCategory": 6,
                                                                                  "parameterNumber": 1}}))
        self.assertIn("was not a reflectivity grid", status["detail"])

    def test_a_grid_of_another_size_is_refused(self):
        _, status = self.run_storm(FakeBucket(every_height(), override={"02.00": {"Ni": 7001}}))
        self.assertIn("the radar file had an unexpected grid size", status["detail"])

    def test_a_file_at_another_time_is_refused(self):
        _, status = self.run_storm(FakeBucket(every_height(), override={"03.00": {"validityTime": 900}}))
        self.assertIn("the radar file's own time didn't match its name", status["detail"])

    def test_only_the_towns_cells_are_read_from_each_file(self):
        results, _ = self.run_storm(FakeBucket(every_height()))
        self.assertEqual(results["billings"]["echo_top_m"], 8000)
        self.assertIsNone(results["bozeman"]["echo_top_m"])
        self.assertEqual(results["bozeman"]["levels"][1]["dbz"], -5.0)

    def test_a_town_outside_the_grid_is_refused(self):
        _, status = self.run_storm(FakeBucket(every_height()), towns=[dict(TOWNS[0], lat=10.0)])
        self.assertFalse(status["ok"])
        self.assertIn("a town lies outside the radar grid", status["detail"])

    def test_one_file_per_height_is_read(self):
        bucket = FakeBucket(every_height())
        when, values, downloaded, decode_s = st.live(bucket, NOW, TOWNS)
        self.assertEqual(when, STEP)
        self.assertEqual(len(bucket.reads), 11)
        self.assertEqual(len(values["billings"]), 11)
        self.assertGreater(downloaded, 0)
        self.assertGreaterEqual(decode_s, 0.0)


class Requests(unittest.TestCase):
    def test_listings_use_start_after_and_yesterday_only_past_midnight(self):
        urls = st.list_urls("00.50", datetime(2026, 10, 17, 9, 10, tzinfo=UTC))
        self.assertEqual(len(urls), 1)
        self.assertIn("start-after=CONUS/MergedReflectivityQC_00.50/20261017/MRMS_MergedReflectivityQC_00.50_"
                      "20261017-080900.grib2.gz", urls[0])
        urls = st.list_urls("00.50", datetime(2026, 10, 17, 0, 20, tzinfo=UTC))
        self.assertEqual(len(urls), 2)
        self.assertIn("20261016", urls[0])
        self.assertIn("start-after", urls[0])
        self.assertNotIn("start-after", urls[1])

    def test_the_grid_and_the_reflectivity_code_are_the_checked_ones(self):
        self.assertEqual(st.REFLECTIVITY, (209, 9, 0))
        self.assertEqual(st.GRID_SHAPE, (7000, 3500))
        self.assertEqual(st.STALE.total_seconds(), 30 * 60)
        self.assertEqual(st.STALE, g.RADAR_STALE)


class Words(StormCase):
    def test_every_kind_of_text_avoids_dry_clear_and_no_hail(self):
        results = [
            st.collect(FakeBucket(every_height()), NOW, TOWNS)[0],
            st.collect(FakeBucket(every_height()), STEP + timedelta(minutes=45), TOWNS)[0],
            st.collect(FakeBucket(every_height(), fail={"MRMS_MergedReflectivityQC_01.00_20261017-090634": "HTTP 500"}), NOW, TOWNS)[0],
            st.collect(FakeBucket(every_height()), NOW, [dict(TOWNS[0], ground_m=None)])[0],
            st.collect(FakeBucket({}), NOW, TOWNS, sample=True)[0],
        ]
        texts = [t["text"] for result in results for t in result.values()]
        self.assertEqual(len(texts), 13)            # 3 + 3 + 3 + 1 + 3 towns
        for text in texts:
            self.assert_words(text)

    def test_loaded_values_carry_radar_estimate_and_a_valid_time(self):
        results, _ = self.run_storm(FakeBucket(every_height()))
        for slug in ("billings", "bozeman", "west-yellowstone"):
            self.assertIn("radar estimate", results[slug]["text"])
            self.assertRegex(results[slug]["text"], VALID_TIME)
        self.assertIn("8,000 m above sea level", results["billings"]["text"])

    def test_sample_text_says_it_is_invented(self):
        results, status = st.collect(FakeBucket({}), NOW, TOWNS, sample=True)
        self.assertTrue(status["ok"])
        self.assertTrue(status["detail"].startswith("SAMPLE, invented values; "))
        for t in TOWNS:
            self.assertTrue(results[t["slug"]]["text"].startswith("SAMPLE, invented values."))
            self.assertIn("SAMPLE", results[t["slug"]]["source"])

    def test_every_record_has_the_same_keys(self):
        live_one = st.collect(FakeBucket(every_height()), NOW, TOWNS)[0]["billings"]
        problem = st.collect(FakeBucket({}), NOW, TOWNS)[0]["billings"]
        self.assertEqual(set(live_one), set(problem))
        self.assertTrue({"status", "text", "reason", "echo_top_m", "echo_top_at_least", "valid_time_utc",
                         "retrieved_utc",
                         "valid_levels", "no_data_levels", "below_ground_levels", "levels", "source"} <= set(live_one))


class Qualifiers(StormCase):
    def test_an_echo_top_with_no_radar_value_above_it_is_a_lower_bound(self):
        self.field = lambda h, lat, lon: 40.0 if h <= 3000 else -99.0
        results, _ = self.run_storm(FakeBucket(every_height()), towns=[TOWNS[0]])
        b = results["billings"]
        self.assertEqual((b["echo_top_m"], b["echo_top_at_least"]), (3000, True))
        self.assertEqual(b["text"], "Echo top (radar estimate): at least 3,000 m above sea level, valid 3:06 am MDT. "
                                    "The top may be higher: 7 heights above it had no radar value. dBZ 35 or more at "
                                    "3 of the 3 heights above ground with radar data (7 heights with no radar value; "
                                    "1 height below ground, not used). This is not an all-clear.")
        self.assertNotIn("Echo top (radar estimate): 3,000 m", b["text"])     # the bare value is never stated
        self.assert_words(b["text"])

    def test_a_sparse_column_with_no_echo_says_how_many_heights_had_data(self):
        self.field = lambda h, lat, lon: 20.0 if h == 1000 else -99.0
        results, _ = self.run_storm(FakeBucket(every_height()), towns=[TOWNS[0]])
        b = results["billings"]
        self.assertIsNone(b["echo_top_m"])
        self.assertEqual(b["text"], "No echo at or above 35 dBZ (radar estimate), valid 3:06 am MDT. Only 1 of the 10 "
                                    "heights above ground had radar data, and none reached 35 dBZ (9 heights with no "
                                    "radar value; 1 height below ground, not used). This is not an all-clear.")
        self.assert_words(b["text"])

    def test_a_top_with_radar_data_at_every_height_above_it_has_no_qualifier(self):
        results, _ = self.run_storm(FakeBucket(every_height()), towns=[TOWNS[0]])
        b = results["billings"]
        self.assertFalse(b["echo_top_at_least"])
        self.assertNotIn("at least", b["text"])
        self.assertNotIn("may be higher", b["text"])


class MaskedCells(StormCase):
    def test_a_masked_cell_is_no_radar_value_even_when_a_number_lies_under_the_mask(self):
        self.field = lambda h, lat, lon: 40.0
        data, _err = FakeBucket(every_height())(g.MRMS + key_for("03.00", STEP))
        lats, lons = np.array([TOWNS[0]["lat"]]), np.array([TOWNS[0]["lon"]])
        self.assertEqual(float(st.decode_level(data, "03.00", STEP, lats, lons)[0]), 40.0)     # nothing masked

        def masked(blob):
            msg = self.fromstring(blob)
            msg.values = MaskedValues(msg.values)
            return msg
        with mock.patch.dict(sys.modules, {"pygrib": SimpleNamespace(fromstring=masked)}):
            self.assertTrue(np.isnan(st.decode_level(data, "03.00", STEP, lats, lons)[0]))


class SampleValues(unittest.TestCase):
    def test_the_sample_weak_echo_is_12_dbz_and_never_zero(self):
        from website import sample
        towns = [{"slug": s, "name": s, "lat": 45.0, "lon": -110.0, "ground_m": 1000.0}
                 for s in ("billings", "glasgow", "west-yellowstone", "havre")]
        _when, values = sample.storm_levels(NOW, towns)
        flat = [v for row in values.values() for v in row if not np.isnan(v)]
        self.assertIn(12.0, flat)                 # the weak echo is invented, labelled SAMPLE on the page
        self.assertNotIn(0.0, flat)               # never 0 dBZ, which would read as a measured value
        self.assertTrue(set(flat) <= {12.0, 18.0, 30.0, 42.0})


class BrowserScript(unittest.TestCase):
    """website/static/map/storm.js places the words into the Map's sheets; it is browser-only (AGENTS.md rule 4).
    The cap is a proposal until research/globe/README.md section 9b lists the duty and its limits."""

    MAX_LINES, MAX_BYTES = 40, 2000   # the cap proposed in research/globe/README.md section 9b (row S1)

    def setUp(self):
        self.text = (ROOT / "website" / "static" / "map" / "storm.js").read_text(encoding="utf-8")

    def test_the_script_stays_under_its_caps(self):
        self.assertLessEqual(len(self.text.splitlines()), self.MAX_LINES)
        self.assertLessEqual(len(self.text.encode("utf-8")), self.MAX_BYTES)

    def test_the_script_holds_no_radar_numbers_or_units(self):
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", self.text, flags=re.S)     # the header comment may say what it is
        self.assertIsNone(re.search(r"dbz|\b35\b|3\.28|feet|stale", code, re.IGNORECASE), code)

    def test_the_script_does_not_add_a_second_copy_to_a_sheet(self):
        self.assertIn('body.querySelector("[data-storm]")', self.text)


class SourceText(unittest.TestCase):
    def test_the_contract_names_the_rules(self):
        c = src.CONTRACTS["storm_levels"]
        self.assertEqual(set(c), {"name", "request", "units", "timing", "missing"})
        self.assertTrue(all(isinstance(v, str) and v.strip() for v in c.values()))
        self.assertIn("dBZ", c["units"])
        self.assertIn("mean sea level", c["units"])
        self.assertIn("2 minutes", c["timing"])
        self.assertIn("30 minutes", c["timing"])
        self.assertIn("-99 and -999 mean no radar value: -99 is missing and -999 is no coverage", c["missing"])
        self.assertNotIn("not verified", c["missing"])
        self.assertIn("never a value", c["missing"])
        self.assertIn("Echo top not available", c["missing"])
        self.assertIn("not a surveyed terrain height", c["units"])
        self.assertIn("35 dBZ", c["units"])
        self.assertIn("A radar estimate, not observed hail or damage.", c["missing"])


if __name__ == "__main__":
    unittest.main()
