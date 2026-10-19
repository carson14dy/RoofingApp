"""River gauges (B5 Source 7): the pool and its exclusions, the NWPS detail reader and its shape guards, the USGS peak reader
(the parameter, the duplicate water years and their qualifiers, the hundredths, a row that is not feet), the nearest rule
at ten miles (a listed gauge whose detail failed is a candidate), the scope of the store, the words, the
failures of one gauge or one series (an HTML answer, an unusable list, a discharge row, a null feature, a
cached copy that is not usable), and an offline build with a missing list. Synthetic responses only, routed through a
fake requests.get, with time.sleep patched; the cached real responses are checked by `python -m website.gauges verify`."""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from website import gauges as Gs
from website import stations as S

FORBIDDEN = re.compile(r"\b(damag\w*|dry|clear\w*|insurance|eligib\w*|confirm\w*|coverage|risk|probab\w*|claim\w*|"
                       r"loss\w*|all-clear|structure|warrant\w*)\b|\bno hail\b", re.IGNORECASE)


def detail(lid, name, lat, lon, state="MT", usgs="06214500", minor=13.5, action=12.5, moderate=14.5, major=15.0):
    def cat(stage):
        return {"stage": stage, "flow": -9999}
    cats = {"action": cat(action), "minor": cat(minor), "moderate": cat(moderate), "major": cat(major)}
    return {"lid": lid, "name": name, "usgsId": usgs, "state": {"abbreviation": state, "name": state},
            "latitude": lat, "longitude": lon, "wfo": {"abbreviation": "BYZ"}, "flood": {"categories": cats}}


def peaks_doc(usgs, rows):
    feats = []
    for wy, day, value, quals in rows:
        feats.append({"type": "Feature", "properties": {
            "monitoring_location_id": f"USGS-{usgs}", "parameter_code": "00065", "unit_of_measure": "ft",
            "value": value, "time": day, "water_year": wy, "qualifier": quals}})
    return {"type": "FeatureCollection", "features": feats}


class FakeResponse:
    def __init__(self, status=200, body=b""):
        self.status_code = status
        self._body = body
        self.headers = {}

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        pass


class PoolTests(unittest.TestCase):
    def test_exclusions_and_the_pool(self):
        pool_gauge = Gs.parse_detail(detail("BILM8", "Yellowstone River at Billings", 45.8, -108.47))
        self.assertEqual(Gs.pool_status(pool_gauge), "pool")
        self.assertEqual(pool_gauge["usgs"], "06214500")
        no_flood = Gs.parse_detail(detail("RESM8", "Reservoir", 45.0, -108.0, minor=None, action=12.0))
        self.assertEqual(Gs.pool_status(no_flood), "no_flood_stage")
        elevation = Gs.parse_detail(detail("HOPI1", "Lake Pend Oreille at Hope", 48.3, -116.3, state="ID",
                                           minor=2063.5, action=2060.0, moderate=2064.0, major=2065.0))
        self.assertEqual(Gs.pool_status(elevation), "elevation")

    def test_missing_stage_is_not_defined_not_zero(self):
        gauge = Gs.parse_detail(detail("X", "X", 45.0, -108.0, minor=-9999.0))
        self.assertIsNone(gauge["stages"]["minor"])
        self.assertEqual(Gs.pool_status(gauge), "no_flood_stage")

    def test_nearest_within_ten_miles(self):
        near = {"lid": "NEAR", "usgs": "1", "name": "Near", "state": "MT", "lat": 45.0, "lon": -108.0,
                "stages": {"minor": 13.5}}
        far = {"lid": "FAR", "usgs": "2", "name": "Far", "state": "MT", "lat": 45.0, "lon": -107.7,
               "stages": {"minor": 13.5}}
        self.assertEqual(Gs.nearest([far, near], 45.0, -108.0)["lid"], "NEAR")
        self.assertIsNone(Gs.nearest([far], 45.0, -108.0))                       # 0.3 degree is about 14 miles
        self.assertEqual(Gs.RADIUS_MILES, 10.0)

    def test_nearest_tie_goes_to_the_lid(self):
        # two gauges at the same position are an exact tie in distance, so the LID decides
        a = {"lid": "AAA", "usgs": "1", "name": "A", "state": "MT", "lat": 45.1, "lon": -108.0, "stages": {"minor": 1}}
        b = {"lid": "BBB", "usgs": "2", "name": "B", "state": "MT", "lat": 45.1, "lon": -108.0, "stages": {"minor": 1}}
        self.assertEqual(Gs.nearest([b, a], 45.0, -108.0)["lid"], "AAA")

    def test_the_detail_reader_reads_a_wrong_shape_as_absent_not_as_an_error(self):
        # a flood section or a category that is not an object reads as absent; no exception
        odd = detail("ODDM8", "Odd", 45.0, -108.0)
        odd["flood"] = ["not", "an", "object"]
        gauge = Gs.parse_detail(odd)
        self.assertIsNotNone(gauge)
        self.assertEqual(gauge["stages"], {"action": None, "minor": None, "moderate": None, "major": None})
        self.assertIsNone(Gs.parse_detail(["not", "a", "gauge"]))
        self.assertIsNone(Gs.parse_detail({"lid": "NOPOS", "latitude": "north"}))

    def test_a_listed_gauge_whose_detail_failed_is_a_candidate_by_its_position(self):
        # the nearest rule knows the failed gauge from the list; it is not silently skipped
        failed = [{"lid": "BILM8", "name": "Yellowstone River at Billings", "lat": 45.8001, "lon": -108.468,
                   "state": "MT"}]
        line = Gs.nearest_listed([], failed, 45.7836, -108.5007)
        self.assertTrue(line["unavailable"])
        self.assertEqual(line["lid"], "BILM8")
        self.assertEqual(line["name"], "Yellowstone River at Billings")
        self.assertLess(line["miles"], 10.0)
        self.assertIn("could not be loaded in this update", line["sentence"])
        self.assertNotIn("No gauge", line["sentence"])

    def test_a_failed_gauge_nearer_than_the_pool_gauge_wins_and_a_farther_one_does_not(self):
        pool = [{"lid": "FAR", "usgs": "2", "name": "Far", "state": "MT", "lat": 45.0, "lon": -107.9,
                 "stages": {"minor": 13.5}}]
        near_failed = [{"lid": "NEAR", "name": "Near", "lat": 45.0, "lon": -108.0, "state": "MT"}]
        self.assertTrue(Gs.nearest_listed(pool, near_failed, 45.0, -108.0)["unavailable"])
        far_failed = [{"lid": "ZZZ", "name": "Zed", "lat": 46.0, "lon": -108.0, "state": "MT"}]
        self.assertEqual(Gs.nearest_listed(pool, far_failed, 45.0, -108.0)["lid"], "FAR")
        self.assertIsNone(Gs.nearest_listed([], [], 45.0, -108.0))


class PeakTests(unittest.TestCase):
    def test_billings_peak_in_hundredths_with_its_date(self):
        doc = peaks_doc("06214500", [(2022, "2022-06-15", "16.37", None), (2011, "2011-07-02", "14.37", None)])
        rows = Gs.parse_peaks(doc, "06214500")
        self.assertEqual(rows, [[2011, "2011-07-02", 1437, []], [2022, "2022-06-15", 1637, []]])

    def test_duplicate_water_years_keep_both_rows_with_qualifiers(self):
        doc = peaks_doc("06185110", [(1987, "1986-11-14", "10.28", ["BACKWATER", "GHNOTASSCPKQ"]),
                                     (1987, "1987-05-28", "7.01", ["NOTMAXGH"])])
        rows = Gs.parse_peaks(doc, "06185110")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][3], ["BACKWATER", "GHNOTASSCPKQ"])
        self.assertEqual(rows[1][3], ["NOTMAXGH"])

    def test_a_discharge_row_is_refused(self):
        doc = peaks_doc("06214500", [(2022, "2022-06-15", "83600", None)])
        doc["features"][0]["properties"]["parameter_code"] = "00060"
        doc["features"][0]["properties"]["unit_of_measure"] = "ft3/s"
        with self.assertRaises(Gs.GaugeError):
            Gs.parse_peaks(doc, "06214500")

    def test_a_null_or_bare_feature_is_refused_as_a_gauge_error_not_an_attribute_error(self):
        for feature in (None, "row", ["row"]):
            doc = {"features": [feature]}
            with self.assertRaises(Gs.GaugeError):
                Gs.parse_peaks(doc, "06214500")

    def test_stage_values_in_hundredths(self):
        gauge = Gs.parse_detail(detail("BILM8", "Yellowstone River at Billings", 45.8, -108.47))
        doc = Gs.gauge_doc("06214500", ["BILM8"], gauge, [[2022, "2022-06-15", 1637, []]])
        self.assertEqual(doc["stages"], {"action": 1250, "minor": 1350, "moderate": 1450, "major": 1500})
        self.assertEqual(doc["water_years"], [2022, 2022])
        self.assertEqual(doc["unit"], "hundredths of a foot")

    def test_words_are_plain_and_forbidden_free(self):
        for key, text in Gs.WORDS.items():
            self.assertIsNone(FORBIDDEN.search(text), f"{key}: {text}")
        self.assertEqual(Gs.WORDS["lead"].format(name="Yellowstone River at Billings", miles="2.0"),
                         "River flood record at the Yellowstone River at Billings gauge, 2.0 miles away; it does not "
                         "say water reached this address.")

    def test_the_gauge_error_is_a_stations_error_so_a_bad_download_is_a_failed_request(self):
        self.assertTrue(issubclass(Gs.GaugeError, S.StationsError))
        check = Gs._check_json("list")
        with self.assertRaises(S.StationsError):
            check(b"<html>an error page</html>")
        with self.assertRaises(S.StationsError):
            check(b"[1, 2, 3]")                                  # a JSON array is not the list object (the shape guard)
        Gs._check_json("detail")(b'{"lid": "X"}')                # an object passes


class ScopeTests(unittest.TestCase):
    """The scope rule: the store holds every Montana pool gauge and the nearest pool gauge in any state to each town, gate point
    and tile centre within 10 miles. An out-of-state gauge that is not the nearest to any of those points is not kept."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "store"
        (self.store / "hail").mkdir(parents=True)
        self.pool = [
            {"lid": "MTONE", "usgs": "1", "name": "Montana gauge", "state": "MT", "lat": 45.0, "lon": -108.0,
             "stages": {"minor": 13.5}},
            {"lid": "WYONE", "usgs": "2", "name": "Wyoming gauge", "state": "WY", "lat": 44.95, "lon": -107.9,
             "stages": {"minor": 9.0}},
        ]
        self.town = mock.patch.object(Gs, "_towns", lambda: [{"slug": "t", "lat": 45.0, "lon": -108.0}])
        self.town.start()

    def tearDown(self):
        self.town.stop()
        self.tmp.cleanup()

    def write_index(self, tiles):
        (self.store / "hail" / "index.json").write_text(json.dumps({"as_of": "2026-10-16", "tiles": tiles}),
                                                        encoding="utf-8")

    def test_an_out_of_state_gauge_is_not_kept_where_a_montana_gauge_is_nearer(self):
        self.write_index([])
        kept = [g["lid"] for g in Gs._scope(self.pool, self.store)]
        self.assertEqual(kept, ["MTONE"])                       # the Wyoming gauge is about 5 miles from the town,
        #                                                         the Montana gauge is at the town: the one kept is MT

    def test_an_out_of_state_gauge_that_is_the_nearest_to_a_tile_centre_is_kept(self):
        # tile r0100_c0220 has its centre at (44.95, -107.95): the Wyoming gauge is nearer to it than the Montana one
        self.write_index(["r0100_c0220"])
        kept = sorted(g["lid"] for g in Gs._scope(self.pool, self.store))
        self.assertEqual(kept, ["MTONE", "WYONE"])

    def test_the_scope_rule_is_stated_in_the_block_rule(self):
        self.assertIn("nearest pool gauge in any state", Gs._rule()["scope"])


class OfflineBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        self.store = self.root / "store"
        (self.store / "hail").mkdir(parents=True)
        (self.store / "hail" / "index.json").write_text(json.dumps({"as_of": "2026-10-16", "tiles": []}),
                                                        encoding="utf-8")
        (self.store / "hail" / "manifest.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
        (self.cache / "nwps" / "detail").mkdir(parents=True)
        (self.cache / "usgs" / "peaks").mkdir(parents=True)
        listing = {"gauges": [{"lid": "BILM8"}, {"lid": "RESM8"}, {"lid": "HOPI1"}]}
        (self.cache / "nwps" / "gauges_list_wide.json").write_text(json.dumps(listing), encoding="utf-8")
        details = {"BILM8": detail("BILM8", "Yellowstone River at Billings", 45.8001, -108.4680),
                   "RESM8": detail("RESM8", "Reservoir", 45.0, -108.0, minor=None, action=12.0),
                   "HOPI1": detail("HOPI1", "Lake Pend Oreille at Hope", 48.3, -116.3, state="ID",
                                   minor=2063.5, action=2060.0, moderate=2064.0, major=2065.0)}
        for lid, doc in details.items():
            (self.cache / "nwps" / "detail" / f"{lid}.json").write_text(json.dumps(doc), encoding="utf-8")
        (self.cache / "usgs" / "peaks" / "06214500.json").write_text(json.dumps(peaks_doc(
            "06214500", [(2022, "2022-06-15", "16.37", None)])), encoding="utf-8")
        self.patch = mock.patch("time.sleep", lambda seconds: None)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_build_offline_writes_the_pool_and_the_g_file(self):
        result = Gs.build(self.store, self.cache, offline=True, procs=1)
        self.assertEqual(result["pool"], 1)
        self.assertEqual(result["g_files"], 1)
        g = json.loads((self.store / "hail" / "g" / "06214500.json").read_text(encoding="utf-8"))
        self.assertEqual(g["peaks"], [[2022, "2022-06-15", 1637, []]])
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["gauges"]
        self.assertEqual(block["counts"]["elevation_excluded"], 1)
        self.assertEqual(block["counts"]["no_flood_stage"], 1)
        self.assertEqual(block["gates"]["billings_nearest"]["lid"], "BILM8")
        self.assertEqual(block["gates"]["billings_nearest"]["peaks"], "available")
        self.assertEqual(block["pool"][0]["peaks"], "available")
        self.assertIn("hail/g/06214500.json", json.loads((self.store / "hail" / "manifest.json").read_text(
            encoding="utf-8"))["files"])

    def test_the_index_sources_hold_examples_and_no_template_or_store_word(self):
        Gs.build(self.store, self.cache, offline=True, procs=1)
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["gauges"]
        sources = block["sources"]
        for key, text in sources.items():
            self.assertNotIn("{", text, key)
            self.assertNotIn("<", text, key)
        self.assertEqual(sources["detail_example"], "https://api.water.noaa.gov/nwps/v1/gauges/BILM8")
        self.assertEqual(sources["peaks_example"], Gs.PEAKS_URL.format(usgs="06214500"))
        words = re.findall(r"[a-z-]+", sources["terms"].lower())
        self.assertEqual([w for w in words if w.startswith(("claim", "damag", "risk", "insurance", "eligib"))], [])

    def test_a_missing_list_marks_the_block_unavailable(self):
        (self.cache / "nwps" / "gauges_list_wide.json").unlink()
        result = Gs.build(self.store, self.cache, offline=True, procs=1)
        self.assertEqual(result["state"], "unavailable")
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["gauges"]
        self.assertEqual(block["state"], "unavailable")
        self.assertIn("could not be read", block["problem"])

    def test_a_json_array_in_place_of_the_list_is_unavailable_not_an_exception(self):
        # the cached list is an array: the whole gauge section is unavailable, and nothing raises
        (self.cache / "nwps" / "gauges_list_wide.json").write_text("[1, 2, 3]", encoding="utf-8")
        result = Gs.build(self.store, self.cache, offline=True, procs=1)
        self.assertEqual(result["state"], "unavailable")
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["gauges"]
        self.assertEqual(block["state"], "unavailable")

    def test_a_cached_html_peaks_file_offline_is_a_failed_series(self):
        (self.cache / "usgs" / "peaks" / "06214500.json").write_text("<html>an error page</html>", encoding="utf-8")
        result = Gs.build(self.store, self.cache, offline=True, procs=1)
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["peaks_failed"], 1)
        self.assertFalse((self.store / "hail" / "g" / "06214500.json").exists())
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["gauges"]
        self.assertEqual(block["towns"]["billings"]["peaks"], "unavailable")
        self.assertEqual(block["gates"]["billings_peak"], {"found": False, "peaks": "unavailable"})

    def test_a_good_cached_copy_is_used_when_offline_refresh_is_asked_for(self):
        # --refresh with a good cached copy: no exception; the cached copy is used, and the reason says so
        result = Gs.build(self.store, self.cache, offline=True, procs=1, refresh="all")
        self.assertEqual(result["g_files"], 1)
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["gauges"]
        reasons = [f["reason"] for f in block["failures"]]
        self.assertIn("offline: the cached copy was used and was not re-read", reasons)

    def test_verify_names_an_unreadable_cached_peaks_copy_as_a_failed_check(self):
        Gs.build(self.store, self.cache, offline=True, procs=1)
        (self.cache / "usgs" / "peaks" / "06214500.json").write_text("<html>not json</html>", encoding="utf-8")
        result = Gs.verify(self.store, self.cache)
        check = [c for c in result["checks"] if c["check"] == "cached Billings peaks parse to the same record"]
        self.assertEqual(len(check), 1)
        self.assertFalse(check[0]["pass"])
        self.assertIn("could not be read", check[0]["detail"])


class RoutedBuildTests(unittest.TestCase):
    """Online builds with a routed fake requests.get: every URL that is not routed is an unexpected request."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        self.store = self.root / "store"
        (self.store / "hail").mkdir(parents=True)
        (self.store / "hail" / "index.json").write_text(json.dumps({"as_of": "2026-10-16", "tiles": []}),
                                                        encoding="utf-8")
        (self.store / "hail" / "manifest.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
        (self.cache / "nwps" / "detail").mkdir(parents=True)
        (self.cache / "usgs" / "peaks").mkdir(parents=True)
        self.routes: dict[str, object] = {}
        self.calls: list[str] = []
        self.patches = [mock.patch("time.sleep", lambda seconds: None),
                        mock.patch("requests.get", side_effect=self.route)]
        for patch in self.patches:
            patch.start()
        # two Montana gauges: BILM8 (Billings, usgs 06214500) and PLOM8 (far away, usgs 06214600)
        self.list_doc = {"gauges": [
            {"lid": "BILM8", "name": "Yellowstone River at Billings", "state": {"abbreviation": "MT"},
             "latitude": 45.8001, "longitude": -108.468},
            {"lid": "PLOM8", "name": "Plombs River", "state": {"abbreviation": "MT"},
             "latitude": 46.5, "longitude": -105.0},
        ]}
        self.details = {"BILM8": detail("BILM8", "Yellowstone River at Billings", 45.8001, -108.4680),
                        "PLOM8": detail("PLOM8", "Plombs River", 46.5, -105.0, usgs="06214600")}
        self.plom_peaks = peaks_doc("06214600", [(2021, "2021-05-30", "9.12", None)])
        self.bil_peaks = peaks_doc("06214500", [(2022, "2022-06-15", "16.37", None)])
        self.list_url = Gs.LIST_URL
        self.routes[self.list_url] = FakeResponse(200, json.dumps(self.list_doc).encode("utf-8"))

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def route(self, url, **kwargs):
        self.calls.append(url)
        if url not in self.routes:
            raise AssertionError(f"unexpected request to {url}")
        value = self.routes[url]
        if isinstance(value, Exception):
            raise value
        return value

    def cache_detail(self, lid, doc=None):
        (self.cache / "nwps" / "detail" / f"{lid}.json").write_text(json.dumps(doc or self.details[lid]),
                                                                    encoding="utf-8")

    def cache_list(self, text=None):
        (self.cache / "nwps" / "gauges_list_wide.json").write_text(
            text if text is not None else json.dumps(self.list_doc), encoding="utf-8")

    def cache_peaks(self, usgs, doc_or_text):
        text = doc_or_text if isinstance(doc_or_text, str) else json.dumps(doc_or_text)
        (self.cache / "usgs" / "peaks" / f"{usgs}.json").write_text(text, encoding="utf-8")

    def block(self):
        return json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["gauges"]

    def manifest_matches_disk(self):
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))["files"]
        on_disk = sorted(p.relative_to(self.store).as_posix() for p in (self.store / "hail" / "g").glob("*.json"))
        return sorted(k for k in manifest if k.startswith("hail/g/")) == on_disk

    def test_an_html_detail_is_one_failed_gauge_and_the_others_are_written(self):
        # the bad LID is requested three times, its town gets an unavailable line (never none), the other
        # gauge's series is written, and the failure says that the bad gauge's peak series was not requested
        self.cache_list()
        self.cache_detail("PLOM8")
        self.cache_peaks("06214600", self.plom_peaks)
        url = Gs.DETAIL_URL.format(lid="BILM8")
        self.routes[url] = FakeResponse(200, b"<html>a page, not JSON</html>")
        result = Gs.build(self.store, self.cache, offline=False, procs=1)
        self.assertEqual(result["state"], "partial")
        self.assertEqual(self.calls.count(url), 3)
        self.assertTrue((self.store / "hail" / "g" / "06214600.json").is_file())
        self.assertFalse((self.store / "hail" / "g" / "06214500.json").exists())
        block = self.block()
        self.assertIn({"source": "nwps detail", "lid": "BILM8", "reason": "the detail is not JSON"}, block["failures"])
        self.assertTrue(any(f.get("lid") == "BILM8" and "not requested" in f["reason"] for f in block["failures"]))
        billings = block["towns"]["billings"]
        self.assertTrue(billings["unavailable"])
        self.assertEqual(billings["lid"], "BILM8")
        self.assertNotEqual(billings, {"none": True})
        self.assertTrue(self.manifest_matches_disk())

    def test_an_html_peaks_answer_is_partial_not_an_exception(self):
        self.cache_list()
        self.cache_detail("BILM8")
        self.cache_detail("PLOM8")
        self.cache_peaks("06214600", self.plom_peaks)
        url = Gs.PEAKS_URL.format(usgs="06214500")
        self.routes[url] = FakeResponse(200, b"<html>gateway page</html>")
        result = Gs.build(self.store, self.cache, offline=False, procs=1)
        self.assertEqual(result["state"], "partial")
        self.assertEqual(self.calls.count(url), 3)
        block = self.block()
        self.assertEqual(block["towns"]["billings"]["peaks"], "unavailable")
        self.assertEqual(block["towns"]["billings"]["lid"], "BILM8")
        self.assertEqual(block["towns"]["billings"]["peaks_sentence"],
                         "The annual peaks at this gauge could not be loaded in this update; that is not the same as no "
                         "annual peak.")
        self.assertEqual(block["gates"]["billings_peak"], {"found": False, "peaks": "unavailable"})
        self.assertFalse((self.store / "hail" / "g" / "06214500.json").exists())
        self.assertTrue((self.store / "hail" / "g" / "06214600.json").is_file())
        self.assertTrue(self.manifest_matches_disk())

    def test_a_discharge_row_refuses_only_its_series_and_the_build_exits_normally(self):
        # one row that is not gage height in feet fails its series; the good series is written; no exception
        self.cache_list()
        self.cache_detail("BILM8")
        self.cache_detail("PLOM8")
        self.cache_peaks("06214600", self.plom_peaks)
        discharge = peaks_doc("06214500", [(2022, "2022-06-15", "83600", None)])
        discharge["features"][0]["properties"]["parameter_code"] = "00060"
        discharge["features"][0]["properties"]["unit_of_measure"] = "ft3/s"
        self.cache_peaks("06214500", discharge)
        result = Gs.build(self.store, self.cache, offline=True, procs=1)
        self.assertEqual(result["state"], "partial")
        self.assertIn({"source": "usgs peaks", "usgs": "06214500", "reason": "the USGS peaks could not be read"},
                      self.block()["failures"])
        self.assertTrue((self.store / "hail" / "g" / "06214600.json").is_file())
        self.assertFalse((self.store / "hail" / "g" / "06214500.json").exists())
        self.assertTrue(self.manifest_matches_disk())

    def test_a_null_peaks_feature_fails_its_series_and_not_the_build(self):
        self.cache_list()
        self.cache_detail("BILM8")
        self.cache_detail("PLOM8")
        self.cache_peaks("06214600", self.plom_peaks)
        self.cache_peaks("06214500", {"type": "FeatureCollection", "features": [None]})
        result = Gs.build(self.store, self.cache, offline=True, procs=1)
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["peaks_failed"], 1)
        self.assertTrue((self.store / "hail" / "g" / "06214600.json").is_file())

    def test_a_list_that_is_an_html_page_online_is_unavailable_not_an_exception(self):
        self.routes[self.list_url] = FakeResponse(200, b"<html>maintenance</html>")
        result = Gs.build(self.store, self.cache, offline=False, procs=1)
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(self.calls.count(self.list_url), 3)
        self.assertEqual(self.block()["state"], "unavailable")

    def test_a_failed_listed_gauge_leaves_its_town_unavailable_and_its_pool_entry_absent(self):
        # the detail is not reachable at all (a connection error on each try): the town says so, never "none"
        self.cache_list()
        self.cache_detail("PLOM8")
        self.cache_peaks("06214600", self.plom_peaks)
        self.routes[Gs.DETAIL_URL.format(lid="BILM8")] = requests.exceptions.ConnectionError("refused")
        result = Gs.build(self.store, self.cache, offline=False, procs=1)
        self.assertEqual(result["state"], "partial")
        block = self.block()
        billings = block["towns"]["billings"]
        self.assertTrue(billings["unavailable"])
        self.assertEqual(billings["lid"], "BILM8")
        self.assertIn("The Yellowstone River at Billings gauge", billings["sentence"])
        self.assertIn("could not be loaded in this update; that is not the same as no river flood record",
                      billings["sentence"])
        self.assertNotIn("No gauge", billings["sentence"])
        self.assertIsNone(FORBIDDEN.search(billings["sentence"]))
        self.assertNotIn("BILM8", [p["lid"] for p in block["pool"]])


if __name__ == "__main__":
    unittest.main()
