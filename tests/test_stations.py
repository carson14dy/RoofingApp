"""Stations (B5 Source 3): the fixed-width readers, the quality and trace rules, the D1 thresholds, the no-zero-fill rule,
the station rule (D5) and its words, the periods, and an offline build with a failed file. Synthetic data only; the
real files are checked by `python -m website.stations verify`."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import requests

from website import stations as S

FORBIDDEN = re.compile(r"\b(damag\w*|dry|clear\w*|insurance|eligib\w*|confirm\w*|coverage|risk|probab\w*|claim\w*|"
                       r"loss\w*|all-clear|structure|warrant\w*)\b|\bno hail\b", re.IGNORECASE)
AS_OF = date(2026, 10, 16)


def dly_line(sid: str, year: int, month: int, element: str, days: dict) -> str:
    """One GHCN-Daily month line: days maps day number to (value, mflag, qflag). Missing days are -9999."""
    parts = [f"{sid:<11}", f"{year:04d}", f"{month:02d}", f"{element:<4}"]
    for d in range(1, 32):
        value, mflag, qflag = days.get(d, (-9999, " ", " "))
        parts.append(f"{value:5d}{mflag}{qflag} ")
    return "".join(parts)


def station_line(sid: str, lat: float, lon: float, state: str, name: str) -> str:
    return f"{sid:<11} {lat:8.4f} {lon:9.4f} {1000.0:6.1f} {state:<2} {name:<30}"


def summary(name: str, ok: int, current: bool = True, net: str = "COOP") -> dict:
    return {"name": name, "net": net, "cover": {"SNOW": ok}, "current": current, "periods": {}}


class ReaderTests(unittest.TestCase):
    def test_fixed_width_values_flags_and_missing_days(self):
        text = "\n".join([
            dly_line("USC00000001", 2022, 1, "TMAX", {1: (322, " ", " "), 3: (100, " ", "X")}),
            dly_line("USC00000001", 2022, 1, "SNOW", {4: (0, "T", " ")}),
        ])
        parsed = S.parse_dly(text, "USC00000001")
        self.assertEqual(parsed["malformed"], 0)
        day1 = date(2022, 1, 1).toordinal()
        self.assertEqual(parsed["obs"]["TMAX"], [(day1, 322, True, False),
                                                  (day1 + 2, 100, False, False)])     # day 2 is absent, not zero
        self.assertEqual(parsed["obs"]["SNOW"], [(day1 + 3, 0, True, True)])        # trace: zero and counted

    def test_a_line_of_another_station_is_malformed_not_fatal(self):
        text = dly_line("USC00000002", 2022, 1, "TMAX", {1: (322, " ", " ")})
        parsed = S.parse_dly(text, "USC00000001")
        self.assertEqual(parsed["malformed"], 1)
        self.assertEqual(parsed["obs"]["TMAX"], [])

    def test_days_that_do_not_exist_are_skipped(self):
        text = dly_line("USC00000001", 2021, 2, "PRCP", {30: (5, " ", " ")})   # 30 February 2021 does not exist
        parsed = S.parse_dly(text, "USC00000001")
        self.assertEqual(parsed["obs"]["PRCP"], [])

    def test_station_list_keeps_montana_only(self):
        text = "\n".join([station_line("USC00240802", 45.7717, -108.4811, "MT", "BILLINGS WTP"),
                          station_line("USC00000009", 40.0, -100.0, "NE", "ELSEWHERE")])
        stations = S.parse_station_list(text)
        self.assertEqual(list(stations), ["USC00240802"])
        self.assertEqual(stations["USC00240802"]["name"], "BILLINGS WTP")
        self.assertEqual(stations["USC00240802"]["net"], "COOP")
        self.assertAlmostEqual(stations["USC00240802"]["lon"], -108.4811)

    def test_inventory_reads_core_elements_and_ranges(self):
        text = "\n".join(["USC00240802  45.7717 -108.4811 TMAX 1948 2026",
                          "USC00240802  45.7717 -108.4811 TOBS 1963 1963",
                          "USC00240802  45.7717 -108.4811 SNOW 1948 2026"])
        inv = S.parse_inventory(text, ["USC00240802"])
        self.assertEqual(inv, {"USC00240802": {"TMAX": (1948, 2026), "SNOW": (1948, 2026)}})


class SummaryTests(unittest.TestCase):
    def summarize_month(self, element, days, year=2022, month=1, sid="USC00000001"):
        parsed = S.parse_dly(dly_line(sid, year, month, element, days), sid)
        return S.summarize({"id": sid, "name": "T", "lat": 46.0, "lon": -110.0, "elev": 1000.0, "net": "COOP"},
                           parsed, AS_OF)

    def test_d1_thresholds_at_the_edges(self):
        text = "\n".join([
            dly_line("USC00000001", 2022, 1, "TMAX", {1: (322, " ", " "), 2: (321, " ", " "), 3: (0, " ", " ")}),
            dly_line("USC00000001", 2022, 1, "TMIN", {1: (-1, " ", " "), 2: (0, " ", " "), 3: (-1, " ", " ")}),
            dly_line("USC00000001", 2022, 1, "SNWD", {1: (25, " ", " "), 2: (24, " ", " ")}),
        ])
        sd = S.summarize({"id": "USC00000001", "name": "T", "lat": 46.0, "lon": -110.0, "elev": 1.0, "net": "COOP"},
                         S.parse_dly(text, "USC00000001"), AS_OF)
        season = sd["periods"]["season"]["2021-22"]
        self.assertEqual(season["TMAX"]["ge90"], 1)                   # 322 counts, 321 does not
        self.assertEqual(season["TMIN"]["lt32"], 2)                   # -1 counts, 0 does not
        self.assertEqual(season["SNWD"]["ge1"], 1)                    # 25 mm counts, 24 mm does not
        self.assertEqual(season["FT"], {"ev": 3, "n": 1})             # only day 1 has TMAX above 0 and TMIN below 0
        self.assertEqual(season["TMAX"]["max"], 322)
        self.assertEqual(season["TMAX"]["max_d"], 20220101)

    def test_conversions(self):
        self.assertEqual(S.tenths_c_to_tenths_f(322), 900)            # 32.2 C is 90.0 F
        self.assertEqual(S.tenths_c_to_tenths_f(0), 320)
        self.assertEqual(S.tenths_c_to_tenths_f(-17), 289)
        self.assertEqual(S.mm_to_hundredths_in(25), 98)               # 25 mm is 0.98 in
        self.assertEqual(S.fmt_in(6429), "64.3")

    def test_missing_days_are_not_zero_and_not_in_sums(self):
        sd = self.summarize_month("SNOW", {d: (10, " ", " ") for d in range(1, 11)})
        season = sd["periods"]["season"]["2021-22"]
        self.assertEqual(season["SNOW"]["ok"], 10)
        self.assertEqual(season["SNOW"]["sum"], 100)                  # ten days of 10 mm; the other days add nothing
        self.assertEqual(season["n"], 365)
        self.assertLess(season["SNOW"]["ok"], season["n"])            # the share shows the gap

    def test_flagged_values_are_excluded_and_counted_as_reported(self):
        sd = self.summarize_month("SNOW", {1: (50, " ", "X"), 2: (20, " ", " ")})
        snow = sd["periods"]["season"]["2021-22"]["SNOW"]
        self.assertEqual(snow["rep"], 2)
        self.assertEqual(snow["ok"], 1)
        self.assertEqual(snow["sum"], 20)

    def test_newest_and_current_boundary(self):
        limit = AS_OF.toordinal()
        self.assertTrue(S.newest_current({"TMAX": limit - 30}, AS_OF))
        self.assertFalse(S.newest_current({"TMAX": limit - 31}, AS_OF))
        self.assertFalse(S.newest_current({"TMAX": None}, AS_OF))

    def test_periods_and_labels(self):
        self.assertEqual(S.season_of(date(2022, 6, 30)), "2021-22")
        self.assertEqual(S.season_of(date(2022, 7, 1)), "2022-23")
        self.assertIsNone(S.season_of(date(2020, 8, 1)))
        self.assertEqual(S.water_year_of(date(2021, 10, 1)), 2022)
        self.assertIsNone(S.water_year_of(date(2021, 9, 30)))
        start, end, partial = S.period_bounds("season", "2026-27", AS_OF)
        self.assertEqual((start, end, partial), (date(2026, 7, 1), AS_OF, True))
        self.assertEqual(S.tile_centre(79, 199), (47.05, -110.05))


class RuleTests(unittest.TestCase):
    def test_two_nearest_that_pass_and_the_failure_is_shown(self):
        candidates = [(5.0, "A"), (8.0, "B"), (12.0, "C"), (20.0, "D")]
        summaries = {"A": summary("A", 1500), "B": summary("B", 1900), "C": summary("C", 2000),
                     "D": summary("D", 2100)}
        result = S.choose(candidates, summaries, "SNOW", AS_OF)
        self.assertEqual(result["state"], "two")
        self.assertEqual([c["id"] for c in result["chosen"]], ["B", "C"])
        self.assertEqual([r["id"] for r in result["examined"]], ["A", "B", "C"])     # D is never read
        self.assertFalse(result["examined"][0]["pass"])
        self.assertAlmostEqual(result["examined"][0]["share"], 1500 / 2192, places=4)

    def test_the_eighty_percent_line(self):
        at = S.COVER_DAYS * 0.80
        result = S.choose([(3.0, "A")], {"A": summary("A", int(at) + 1)}, "SNOW", AS_OF)
        self.assertEqual(result["state"], "one")
        result = S.choose([(3.0, "A")], {"A": summary("A", int(at) - 1)}, "SNOW", AS_OF)
        self.assertEqual(result["state"], "none")

    def test_one_and_none_sentences(self):
        one = S.choose([(3.0, "A")], {"A": summary("A", 2000)}, "SNOW", AS_OF)
        self.assertEqual(S.station_words(one, "SNOW"), [
            "Only one station within 40 miles has enough reports for snowfall from 2020 to 2025: A. Stations that did "
            "not pass are not shown."])
        none = S.choose([(3.0, "A")], {"A": summary("A", 100)}, "SNOW", AS_OF)
        self.assertEqual(S.station_words(none, "SNOW"),
                         ["No station within 40 miles has enough reports for snowfall from 2020 to 2025."])

    def test_a_stale_station_does_not_pass(self):
        result = S.choose([(3.0, "A")], {"A": summary("A", 2100, current=False)}, "SNOW", AS_OF)
        self.assertEqual(result["state"], "none")
        self.assertFalse(result["examined"][0]["pass"])

    def test_a_failed_file_is_named_and_skipped(self):
        result = S.choose([(3.0, "A"), (4.0, "B")], {"B": summary("B", 2100)}, "SNOW", AS_OF, frozenset({"A"}))
        self.assertEqual([c["id"] for c in result["chosen"]], ["B"])
        self.assertTrue(result["examined"][0]["unavailable"])

    def test_a_missing_summary_asks_for_that_station(self):
        result = S.choose([(3.0, "A")], {}, "SNOW", AS_OF)
        self.assertEqual(result["state"], "need")
        self.assertEqual(result["need"], "A")

    def test_radius_is_forty_miles(self):
        stations = {"NEAR": {"lat": 46.5, "lon": -110.0}, "FAR": {"lat": 47.2, "lon": -110.0}}
        got = [sid for _m, sid in S.within_radius(stations, 46.0, -110.0)]
        self.assertEqual(got, ["NEAR"])                               # 0.5 degree is about 34.5 miles; 1.2 degrees about 83

    def test_no_forbidden_term_in_any_station_word(self):
        for key, text in S.WORDS.items():
            self.assertIsNone(FORBIDDEN.search(text), f"{key}: {text}")


class OfflineBuildTests(unittest.TestCase):
    """A small store and cache: one station with a full file, one whose file is missing. The build must finish, name
    the failure, and write the same bytes twice (gate B5-13)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        (self.cache / "ghcn" / "dly").mkdir(parents=True)
        self.store = self.root / "store"
        (self.store / "hail").mkdir(parents=True)
        # the synthetic list and inventory are a few lines; their size checks guard the real files only
        self.patches = [mock.patch.object(S, "_check_list", lambda data: None),
                        mock.patch.object(S, "_check_inventory", lambda data: None)]
        for patch in self.patches:
            patch.start()
        (self.store / "hail" / "index.json").write_text(json.dumps({
            "as_of": "2026-10-16", "tiles": ["r0079_c0199"]}), encoding="utf-8")
        (self.store / "hail" / "manifest.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
        (self.cache / "ghcn" / "ghcnd-stations.txt").write_text("\n".join([
            station_line("USC00000001", 47.05, -110.05, "MT", "GOOD"),
            station_line("USC00000002", 47.10, -110.10, "MT", "MISSING")]) + "\n", encoding="utf-8")
        (self.cache / "ghcn" / "ghcnd-inventory.txt").write_text("\n".join([
            "USC00000001  47.0500 -110.0500 SNOW 2000 2026", "USC00000001  47.0500 -110.0500 TMAX 2000 2026",
            "USC00000002  47.1000 -110.1000 SNOW 2000 2026"]) + "\n", encoding="utf-8")
        days = {d: (10, " ", " ") for d in range(1, 29)}
        lines = []
        for year in range(2020, 2027):
            for month in range(1, 13):
                lines.append(dly_line("USC00000001", year, month, "SNOW", days))
                lines.append(dly_line("USC00000001", year, month, "TMAX", {1: (250, " ", " ")}))
        (self.cache / "ghcn" / "dly" / "USC00000001.dly").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def test_build_offline_names_the_failed_file_and_is_deterministic(self):
        first = S.build(self.store, self.cache, offline=True, procs=1)
        self.assertEqual(first["state"], "partial")
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["stations"]
        self.assertTrue(any(f.get("station") == "USC00000002" for f in block["failures"]))
        self.assertTrue((self.store / "hail" / "sd" / "USC00000001.json").is_file())
        self.assertFalse((self.store / "hail" / "sd" / "USC00000002.json").exists())
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("hail/sd/USC00000001.json", manifest["files"])
        first_bytes = (self.store / "hail" / "sd" / "USC00000001.json").read_bytes()
        # a second build into a copy of the store gives the same bytes
        copy = self.root / "store2"
        shutil.copytree(self.store, copy)
        S.build(copy, self.cache, offline=True, procs=1)
        self.assertEqual((copy / "hail" / "sd" / "USC00000001.json").read_bytes(), first_bytes)

    def test_missing_station_list_marks_the_block_unavailable(self):
        (self.cache / "ghcn" / "ghcnd-stations.txt").unlink()
        result = S.build(self.store, self.cache, offline=True, procs=1)
        self.assertEqual(result["state"], "unavailable")
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["stations"]
        self.assertEqual(block["state"], "unavailable")
        self.assertIn("could not be read", block["problem"])


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


META = {"id": "USC00000001", "name": "T", "lat": 46.0, "lon": -110.0, "elev": 1000.0, "net": "COOP"}


class CountKeyTests(unittest.TestCase):
    """The count-key rule: a count key is written wherever the element has an unflagged value in the period (zero when no day
    reached the threshold), and it is absent only when the element has none. Readers get None, never a zero."""

    def summarize_month(self, element, days, year=2022, month=1, sid="USC00000001"):
        parsed = S.parse_dly(dly_line(sid, year, month, element, days), sid)
        return S.summarize(dict(META, id=sid), parsed, AS_OF)

    def test_a_zero_hit_season_has_zero_counts_where_the_element_has_values(self):
        text = "\n".join([
            dly_line("USC00000001", 2022, 1, "TMAX", {d: (250, " ", " ") for d in range(1, 11)}),
            dly_line("USC00000001", 2022, 1, "TMIN", {d: (50, " ", " ") for d in range(1, 11)}),
            dly_line("USC00000001", 2022, 1, "SNWD", {d: (10, " ", " ") for d in range(1, 11)}),
        ])
        season = S.summarize(META, S.parse_dly(text, "USC00000001"), AS_OF)["periods"]["season"]["2021-22"]
        self.assertEqual(season["TMAX"]["ok"], 10)
        self.assertEqual(season["TMAX"]["ge90"], 0)                       # ok above 0: a zero, not an absent key
        self.assertEqual(season["TMIN"]["lt32"], 0)
        self.assertEqual(season["SNWD"]["ge1"], 0)
        self.assertEqual(S.count_of(season, "TMAX", "ge90"), 0)

    def test_trace_is_zero_with_no_trace_days_and_one_with_a_trace_day(self):
        prcp = self.summarize_month("PRCP", {1: (5, " ", " "), 2: (7, " ", " ")})["periods"]["season"]["2021-22"]
        self.assertEqual(prcp["PRCP"]["trace"], 0)
        snow = self.summarize_month("SNOW", {1: (0, "T", " "), 2: (10, " ", " ")})["periods"]["season"]["2021-22"]
        self.assertEqual(snow["SNOW"]["trace"], 1)
        self.assertEqual(snow["SNOW"]["sum"], 10)

    def test_a_season_with_no_record_reads_none_not_zero(self):
        season = self.summarize_month("TMAX", {1: (322, " ", " ")})["periods"]["season"]["2025-26"]
        self.assertNotIn("TMAX", season)
        self.assertIsNone(S.count_of(season, "TMAX", "ge90"))
        self.assertIsNone(S.pair_of(season, "FT"))

    def test_an_all_flagged_season_reads_its_ok_as_zero_and_its_counts_as_none(self):
        season = self.summarize_month("TMAX", {d: (330, " ", "X") for d in range(1, 11)})["periods"]["season"]["2021-22"]
        self.assertEqual(season["TMAX"]["rep"], 10)
        self.assertEqual(season["TMAX"]["ok"], 0)
        self.assertIsNone(S.count_of(season, "TMAX", "ge90"))             # reported but unflagged for none: no count
        self.assertNotIn("max", season["TMAX"])

    def test_the_roof_series_names_a_missing_count_and_never_raises(self):
        # a synthetic zero-hit airport file: highs of 90 F are zero in four seasons and absent in one (no record)
        seasons = {}
        for label in S.ROOF_SEASONS if hasattr(S, "ROOF_SEASONS") else ():
            seasons[label] = {"TMAX": {"rep": 365, "ok": 365, "ge90": 0, "max": 280}}
        del seasons["2024-25"]
        doc = {"periods": {"season": seasons, "calendar": {}}}
        checks = []
        S._verify_roof_series({"USW00024033": doc}, lambda name, passed, detail="": checks.append((name, passed, detail)))
        hot = [c for c in checks if "highs of 90 F" in c[0]]
        self.assertEqual(len(hot), 1)
        self.assertFalse(hot[0][1])
        self.assertEqual(hot[0][2], "no value for this season; not zero")

    def test_the_pair_helper_reads_absent_as_none_and_zero_days_as_zero(self):
        self.assertIsNone(S.pair_of({}, "FT"))
        self.assertIsNone(S.pair_of({"FT": {"ev": 3}}, "FT"))
        self.assertEqual(S.pair_of({"FT": {"ev": 3, "n": 0}}, "FT"), 0)


class RefreshAndFetchTests(unittest.TestCase):
    """The refresh sets, the offline refresh, a corrupt cache, the deadline, the read timeout and the body cap (B5 jobs)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patches = [mock.patch("time.sleep", lambda seconds: None)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    URL = "https://example.invalid/f.dly"

    def test_refresh_settings_are_none_all_or_a_set_of_ids(self):
        self.assertEqual(S.refresh_set("none"), (False, frozenset()))
        self.assertEqual(S.refresh_set(False), (False, frozenset()))
        self.assertEqual(S.refresh_set("all"), (True, frozenset()))
        self.assertEqual(S.refresh_set(True), (True, frozenset()))
        self.assertEqual(S.refresh_set(["USC00000001", " USC00000002 "]),
                         (False, frozenset({"USC00000001", "USC00000002"})))
        with self.assertRaises(S.StationsError):
            S.refresh_set("sometimes")

    def test_offline_refresh_serves_the_cached_copy_and_says_so(self):
        path = self.dir / "f.dly"
        path.write_bytes(b"cached")
        pacer = S._Pacer(0)
        with mock.patch("requests.get", side_effect=AssertionError("no request")):
            data, state, reason = S.fetch(self.URL, path, lambda d: None, offline=True, refresh=True, pacer=pacer)
        self.assertEqual((data, state), (b"cached", "cache"))
        self.assertEqual(reason, "offline: the cached copy was used and was not re-read")
        self.assertEqual(pacer.requests, 0)

    def test_a_corrupt_cached_copy_is_requested_again_and_replaced(self):
        path = self.dir / "f.dly"
        path.write_bytes(b"bad")

        def check(data):
            if data != b"good":
                raise S.StationsError("the file is not a GHCN-Daily file")
        with mock.patch("requests.get", return_value=FakeResponse(200, b"good")) as get:
            data, state, reason = S.fetch(self.URL, path, check, offline=False, refresh=False, pacer=S._Pacer(0))
        self.assertEqual(get.call_count, 1)
        self.assertEqual((data, state), (b"good", "fetched"))
        self.assertEqual(reason, "the cached copy was not usable and was replaced")
        self.assertEqual(path.read_bytes(), b"good")

    def test_a_corrupt_cached_copy_offline_is_a_failed_file_with_its_reason(self):
        path = self.dir / "f.dly"
        path.write_bytes(b"bad")
        data, state, reason = S.fetch(self.URL, path, lambda d: (_ for _ in ()).throw(S.StationsError("no")),
                                      offline=True, refresh=False, pacer=S._Pacer(0))
        self.assertEqual((data, state), (None, "failed"))
        self.assertIn("not usable", reason)

    def test_a_deadline_that_has_passed_makes_no_request(self):
        path = self.dir / "f.dly"
        with mock.patch("requests.get", side_effect=AssertionError("no request")) as get:
            data, state, reason = S.fetch(self.URL, path, lambda d: None, offline=False, refresh=False,
                                          pacer=S._Pacer(0), deadline_at=time.monotonic() - 1)
        self.assertEqual((data, state, reason), (None, "failed", S.REASON_NO_ANSWER))
        self.assertEqual(get.call_count, 0)

    def test_a_read_timeout_on_every_try_is_a_failed_file_not_an_exception(self):
        path = self.dir / "f.dly"
        with mock.patch("requests.get", side_effect=requests.exceptions.ReadTimeout("slow")) as get:
            data, state, reason = S.fetch(self.URL, path, lambda d: None, offline=False, refresh=False,
                                          pacer=S._Pacer(0))
        self.assertEqual((data, state, reason), (None, "failed", "ReadTimeout"))
        self.assertEqual(get.call_count, 3)

    def test_a_body_that_takes_too_long_is_a_failed_request(self):
        path = self.dir / "f.dly"
        with mock.patch.object(S, "BODY_CAP_S", -1.0), \
                mock.patch("requests.get", return_value=FakeResponse(200, b"x" * 100)):
            data, state, reason = S.fetch(self.URL, path, lambda d: None, offline=False, refresh=False,
                                          pacer=S._Pacer(0))
        self.assertEqual((data, state), (None, "failed"))
        self.assertIn("took longer", reason)
        self.assertFalse(path.exists())

    def test_a_failed_refresh_serves_the_cached_copy_with_its_reason(self):
        path = self.dir / "f.dly"
        path.write_bytes(b"cached")
        with mock.patch("requests.get", side_effect=requests.exceptions.ConnectionError("refused")):
            data, state, reason = S.fetch(self.URL, path, lambda d: None, offline=False, refresh=True,
                                          pacer=S._Pacer(0))
        self.assertEqual((data, state), (b"cached", "cache"))
        self.assertIn("served the cached copy after", reason)

    def test_a_file_that_cannot_be_kept_is_a_note_and_the_data_is_still_used(self):
        path = self.dir / "f.dly"
        with mock.patch("requests.get", return_value=FakeResponse(200, b"good")), \
                mock.patch.object(S, "_write_atomic", side_effect=OSError("disk full")):
            data, state, reason = S.fetch(self.URL, path, lambda d: None, offline=False, refresh=False,
                                          pacer=S._Pacer(0))
        self.assertEqual((data, state), (b"good", "fetched"))
        self.assertIn("could not be kept in the cache", reason)

    def test_the_pacer_counts_requests_and_bytes(self):
        pacer = S._Pacer(0)
        pacer.wait()
        pacer.wait()
        pacer.add_bytes(100)
        self.assertEqual((pacer.requests, pacer.downloaded), (2, 100))


class RefreshBuildTests(OfflineBuildTests):
    """The daily and monthly refresh settings in a build: the ids of the rule are recorded, and the list and the
    inventory are refreshed only by the monthly setting."""

    def test_the_rule_ids_are_recorded_and_the_daily_refresh_set_is_the_rule(self):
        S.build(self.store, self.cache, offline=True, procs=1, refresh=frozenset({"USC00000001"}))
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["stations"]
        self.assertEqual(block["refresh"], {"mode": "ids", "ids": 1})
        self.assertIn("USC00000001", block["rule_station_ids"])
        self.assertEqual(S.rule_ids_of(self.store), block["rule_station_ids"])
        self.assertEqual(block["counts"]["requests"], 0)                    # offline: no request was made

    def test_a_monthly_refresh_offline_names_the_cached_list_it_used(self):
        S.build(self.store, self.cache, offline=True, procs=1, refresh="all")
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["stations"]
        self.assertEqual(block["refresh"], {"mode": "all", "ids": 0})
        reasons = [f["reason"] for f in block["failures"] if f.get("source") == "stations"]
        self.assertEqual(reasons, ["offline: the cached copy was used and was not re-read"])

    def test_a_daily_refresh_leaves_the_list_and_the_regression_extras_cached(self):
        calls = []
        with mock.patch("requests.get", side_effect=lambda url, **kw: calls.append(url) or FakeResponse(404)):
            S.build(self.store, self.cache, offline=False, procs=1, refresh=frozenset({"USC00000001"}))
        self.assertTrue(all("ghcnd-stations" not in u and "ghcnd-inventory" not in u for u in calls))
        self.assertIn(S.DLY_URL.format(id="USC00000001"), calls)           # the id in the set is read again
        self.assertEqual(calls.count(S.DLY_URL.format(id="USC00000001")), 1)   # a 404 is not retried

    def test_the_rule_ids_are_an_empty_list_before_any_build(self):
        self.assertEqual(S.rule_ids_of(self.store), [])


class OfflineFailureTests(unittest.TestCase):
    """The job clock (D16): a request the deadline stops is "the source did not answer"; the station side stays partial."""

    def test_a_passed_deadline_stops_every_station_request(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        store = root / "store"
        (store / "hail").mkdir(parents=True)
        (store / "hail" / "index.json").write_text(json.dumps({"as_of": "2026-10-16", "tiles": ["r0079_c0199"]}),
                                                   encoding="utf-8")
        (store / "hail" / "manifest.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
        cache = root / "cache"
        (cache / "ghcn" / "dly").mkdir(parents=True)
        (cache / "ghcn" / "ghcnd-stations.txt").write_text(station_line("USC00000001", 46.0, -110.0, "MT", "A") + "\n",
                                                          encoding="utf-8")
        (cache / "ghcn" / "ghcnd-inventory.txt").write_text("USC00000001  46.0000 -110.0000 SNOW 2000 2026\n",
                                                            encoding="utf-8")
        with mock.patch.object(S, "_check_list", lambda d: None), mock.patch.object(S, "_check_inventory", lambda d: None), \
                mock.patch("requests.get", side_effect=AssertionError("no request")) as get:
            result = S.build(store, cache, offline=False, procs=1, deadline_at=time.monotonic() - 1)
        self.assertEqual(get.call_count, 0)
        self.assertEqual(result["state"], "partial")
        block = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))["stations"]
        self.assertEqual(block["state"], "partial")
        self.assertIn({"source": "daily", "station": "USC00000001", "reason": S.REASON_NO_ANSWER}, block["failures"])


if __name__ == "__main__":
    unittest.main()
