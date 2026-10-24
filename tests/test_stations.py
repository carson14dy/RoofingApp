"""Stations (B5 Source 3): the fixed-width readers, the quality and trace rules, the D1 thresholds, the no-zero-fill rule,
the station rule (D5) and its words, the periods, and an offline build with a failed file. Synthetic data only; the
real files are checked by `python -m website.stations verify`."""
from __future__ import annotations

import json
import math
import random
import re
import shutil
import sys
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import requests

from website import stations as S

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tests/ (words_rules: the sentences a scan allows)
import words_rules as W  # noqa: E402

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


def unread_entry(name: str, reason: str = "the source did not answer") -> dict:
    """A stations block entry for a candidate whose file did not load (B5 job-1 and job-3): null counts, unread true."""
    return {"name": name, "lat": 47.0, "lon": -110.0, "elev": 1000.0, "net": "COOP", "unread": True, "reason": reason,
            "cover": {"SNOW": None}}


def summary(name: str, ok: int, current=True, net: str = "COOP") -> dict:
    """A station summary for the rule. current is one flag for every element, or a dict of flags per element (D18)."""
    flags = {e: current for e in S.CORE} if isinstance(current, bool) else dict(current)
    return {"name": name, "net": net, "cover": {"SNOW": ok}, "current": flags, "periods": {}}


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

    def test_station_list_keeps_stations_by_position_not_by_state(self):
        # D62: the pool is the box, whatever the state; the state is kept (the snow regression reads Montana only)
        text = "\n".join([station_line("USC00240802", 45.7717, -108.4811, "MT", "BILLINGS WTP"),
                          station_line("USS0014C05S", 46.0, -114.0, "ID", "LOLO PASS"),
                          station_line("USC00000009", 40.0, -100.0, "NE", "ELSEWHERE"), "",
                          station_line("CAN03031402", 49.1, -111.5, "AB", "CARWAY")])
        stations = S.parse_station_list(text, (44.0, 49.6, -117.0, -103.0))
        self.assertEqual(sorted(stations), ["CAN03031402", "USC00240802", "USS0014C05S"])
        self.assertEqual(stations["USC00240802"]["name"], "BILLINGS WTP")
        self.assertEqual(stations["USC00240802"]["net"], "COOP")
        self.assertEqual((stations["USC00240802"]["state"], stations["USS0014C05S"]["state"]), ("MT", "ID"))
        self.assertAlmostEqual(stations["USC00240802"]["lon"], -108.4811)

    def test_a_station_line_without_a_position_is_a_stations_error_not_a_silent_skip(self):
        with self.assertRaises(S.StationsError):
            S.parse_station_list("USC00000007 xx.xxxx  -110.0000 MT", (40.0, 50.0, -120.0, -100.0))

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
        self.assertIsNone(result["examined"][0]["pass"])        # never read: neither a pass nor a non-pass (B5 job-3)
        self.assertEqual([u["id"] for u in result["unread"]], ["A"])
        self.assertTrue(result["incomplete"])                    # the nearer file might pass: the two nearest are not known
        self.assertEqual(result["state"], "one")
        words = S.station_words(result, "SNOW")
        self.assertEqual(len(words), 1)
        self.assertTrue(words[0].startswith("Data unavailable for some stations: A did not load, so the two nearest"))
        self.assertTrue(words[0].endswith("the two nearest stations that pass are not known for snowfall. "
                                          "This is not an all-clear."))
        self.assertIsNone(FORBIDDEN.search(W.residue(words[0])))

    def test_candidates_that_all_failed_are_unavailable_not_none(self):
        # B5 job-1: a location whose candidates all failed reads unavailable, and no station is said to have too few reports
        light = {"A": unread_entry("Alpha"), "B": unread_entry("Bravo")}
        result = S.choose([(3.0, "A"), (4.0, "B")], light, "SNOW", AS_OF)
        self.assertEqual((result["state"], result["chosen"]), ("unavailable", []))
        self.assertEqual([u["name"] for u in result["unread"]], ["Alpha", "Bravo"])
        words = S.station_words(result, "SNOW")
        self.assertEqual(words, ["Data unavailable for snowfall: Alpha and Bravo did not load (the source did not answer), "
                                 "so it is not known whether a station within 40 miles has enough reports. This is not an "
                                 "all-clear."])
        self.assertNotIn("No station", " ".join(words))
        self.assertIsNone(FORBIDDEN.search(W.residue(words[0])))

    def test_the_unread_names_are_capped_at_three_and_the_rest_are_counted(self):
        # a sentence a roofer can read: the three nearest by name, then the count (nearest first, as the walk meets them)
        ids = ["A", "B", "C", "D", "E"]
        light = {sid: unread_entry(f"Station {sid}") for sid in ids}
        result = S.choose([(float(i + 1), sid) for i, sid in enumerate(ids)], light, "SNOW", AS_OF)
        self.assertEqual(S.station_words(result, "SNOW"), [
            "Data unavailable for snowfall: Station A, Station B, Station C and 2 more stations did not load (the source "
            "did not answer), so it is not known whether a station within 40 miles has enough reports. This is not an "
            "all-clear."])

    def test_one_passing_and_one_unread_keeps_one_and_does_not_claim_only_one(self):
        # B5 job-1 (kept as "one"): the passing station stays; the words say the other file did not load, not "only one"
        light = {"A": unread_entry("Alpha"), "B": summary("Bravo", 2100)}
        result = S.choose([(3.0, "A"), (4.0, "B")], light, "SNOW", AS_OF)
        self.assertEqual((result["state"], [c["name"] for c in result["chosen"]]), ("one", ["Bravo"]))
        words = S.station_words(result, "SNOW")
        self.assertEqual(words, ["Data unavailable for some stations: Alpha did not load (the source did not answer), so the "
                                 "two nearest stations that pass are not known for snowfall. This is not an all-clear."])
        self.assertNotIn("Only one station", " ".join(words))

    def test_a_failed_nearest_station_is_named_and_the_farther_passes_are_partial(self):
        # B5 job-3: the two farther stations pass; they are shown under the partial words, never as the two nearest
        light = {"A": unread_entry("Alpha"), "B": summary("Bravo", 2100), "C": summary("Charlie", 2000)}
        result = S.choose([(3.0, "A"), (5.0, "B"), (8.0, "C"), (12.0, "D")], light, "SNOW", AS_OF)
        self.assertEqual([c["id"] for c in result["chosen"]], ["B", "C"])
        self.assertEqual([r["id"] for r in result["examined"]], ["A", "B", "C"])     # D is never read
        self.assertEqual((result["state"], result["incomplete"]), ("two", True))
        words = S.station_words(result, "SNOW")
        self.assertEqual(len(words), 1)
        self.assertTrue(words[0].startswith("Data unavailable for some stations: Alpha did not load"))
        self.assertIn("are not known for snowfall", words[0])
        self.assertNotIn("Bravo did not load", words[0])
        self.assertIsNone(FORBIDDEN.search(W.residue(words[0])))

    def test_a_failed_file_after_the_second_pass_changes_nothing(self):
        light = {"A": summary("Alpha", 2100), "B": summary("Bravo", 2100), "C": unread_entry("Charlie")}
        result = S.choose([(3.0, "A"), (4.0, "B"), (9.0, "C")], light, "SNOW", AS_OF)
        self.assertEqual((result["state"], result["incomplete"], result["unread"]), ("two", False, []))
        self.assertEqual(S.station_words(result, "SNOW"), [])

    def test_a_failed_file_may_be_named_by_a_mapping_of_reasons(self):
        result = S.choose([(3.0, "A"), (4.0, "B")], {"B": summary("Bravo", 2100)}, "SNOW", AS_OF,
                          {"A": "the file was in an unexpected format"})
        self.assertEqual(result["unread"][0]["reason"], "the file was in an unexpected format")
        self.assertIn("A did not load (the file was in an unexpected format), so the two nearest",
                      S.station_words(result, "SNOW")[0])

    def test_a_missing_summary_asks_for_that_station(self):
        result = S.choose([(3.0, "A")], {}, "SNOW", AS_OF)
        self.assertEqual(result["state"], "need")
        self.assertEqual(result["need"], "A")

    def test_radius_is_forty_miles(self):
        stations = {"NEAR": {"lat": 46.5, "lon": -110.0}, "FAR": {"lat": 47.2, "lon": -110.0}}
        got = [sid for _m, sid in S.within_radius(stations, 46.0, -110.0)]
        self.assertEqual(got, ["NEAR"])                               # 0.5 degree is about 34.5 miles; 1.2 degrees about 83

    def test_no_forbidden_term_in_any_station_word(self):
        # the required sentence of an unavailable line is allowed (tests/words_rules.py); nothing else is removed
        for key, text in S.WORDS.items():
            self.assertIsNone(FORBIDDEN.search(W.residue(text)), f"{key}: {text}")

    def test_the_unavailable_lines_end_with_the_negation(self):
        # every unavailable or unread line ends with the required sentence (D13, D20); data_unavailable is the season
        # line that the supervisor decides (rules-13 item 5b), so it is not in this list
        checked = sorted(k for k in S.WORDS if ("unavailable" in k or k.startswith("unread")) and k != "data_unavailable")
        self.assertEqual(checked, ["unavailable", "unread_block", "unread_element", "unread_named", "unread_partial"])
        for key in checked:
            self.assertTrue(S.WORDS[key].endswith("This is not an all-clear."), key)


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
        # D28: the D20 sentence is the block's problem; the technical reason sits beside it as the detail
        self.assertEqual(block["problem"], "Station readings could not be loaded in this update; that is not the same "
                                           "as no station reading. This is not an all-clear.")
        self.assertIn("could not be read", block["detail"])

    def test_the_failed_station_reaches_the_block_and_the_rule_at_a_town_and_a_tile_centre(self):
        # B5 job-1 and job-3: the failed file is listed block-wide, is an unread entry with null counts, has no sd file,
        # and the rule at a town and at a tile centre (not stored in the block) sees it as unread, not as a non-pass
        S.build(self.store, self.cache, offline=True, procs=1)
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["stations"]
        self.assertEqual(block["failed_station_ids"], ["USC00000002"])
        entry = block["stations"]["USC00000002"]
        self.assertTrue(entry["unread"])
        self.assertEqual(entry["cover"], {"SNOW": None})
        self.assertFalse((self.store / "hail" / "sd" / "USC00000002.json").exists())
        # D28: the partial sentence is the problem, and the technical reason sits beside it as the detail
        # D32: the problem line names the candidate whose file failed, with its id (the D20 sentence)
        self.assertEqual(block["problem"], "Station readings could not be loaded in this update for MISSING (USC00000002); "
                                           "that is not the same as no station reading. This is not an all-clear.")
        self.assertIn("USC00000002", block["detail"])
        # the town row: Lewistown's nearest-first walk meets the failed file, so the row is incomplete and names it
        towns = [slug for slug, per in block["towns"].items() if "USC00000002" in [r["id"] for r in per["SNOW"]["examined"]]]
        self.assertEqual(towns, ["lewistown"])
        row = block["towns"]["lewistown"]["SNOW"]
        self.assertEqual((row["state"], row["incomplete"], row["unread"]), ("one", True, ["USC00000002"]))
        self.assertEqual(row["chosen"], ["USC00000001"])
        failed = [r for r in row["examined"] if r["id"] == "USC00000002"][0]
        self.assertEqual((failed["unavailable"], failed["pass"]), (True, None))
        # a tile centre (47.05 N, 109.95 W) is not stored; point_rule reads the block and gives the build's answer
        here = S.point_rule(block["stations"], 47.05, -109.95, "SNOW", date(2026, 10, 16))
        self.assertEqual((here["state"], [c["id"] for c in here["chosen"]], [u["id"] for u in here["unread"]]),
                         ("one", ["USC00000001"], ["USC00000002"]))
        # the failed file lists SNOW only, so no other element reads it
        self.assertEqual(S.point_rule(block["stations"], 47.05, -109.95, "TMAX", date(2026, 10, 16))["unread"], [])
        # verify: the loaded files match the loaded entries, and the failed file is listed with no sd file
        checks = {c["check"]: c["pass"] for c in S.verify(self.store)["checks"]}
        self.assertTrue(checks["sd files match the stations block"])
        self.assertTrue(checks["failed or not-read candidates are listed, and none has an sd file"])


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
        self.assertEqual(block["refresh"], {"mode": "ids", "ids": 1, "unchanged": 0})
        self.assertIn("USC00000001", block["rule_station_ids"])
        self.assertEqual(S.rule_ids_of(self.store), block["rule_station_ids"])
        self.assertEqual(block["counts"]["requests"], 0)                    # offline: no request was made

    def test_a_monthly_refresh_offline_names_the_cached_list_it_used(self):
        S.build(self.store, self.cache, offline=True, procs=1, refresh="all")
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["stations"]
        self.assertEqual(block["refresh"], {"mode": "all", "ids": 0, "unchanged": 0})
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


class PerElementCurrencyTests(unittest.TestCase):
    """D18: a station is current for an element when that element has a report in the 30 days before as_of. The rule
    runs per element, so a station current for one element is not thereby current for another."""

    def test_summarize_flags_currency_per_element(self):
        parsed = {"obs": {"TMAX": [(date(2026, 10, 10).toordinal(), 250, True, False)],
                          "SNOW": [(date(2026, 5, 18).toordinal(), 0, True, False)]}, "malformed": 0}
        sd = S.summarize(dict(META), parsed, AS_OF)
        self.assertEqual(sd["current"], {"PRCP": False, "SNOW": False, "SNWD": False, "TMAX": True, "TMIN": False})

    def test_choose_passes_a_station_only_for_the_element_it_is_current_for(self):
        station = {"name": "A", "net": "COOP", "cover": {"TMAX": 2000, "SNOW": 2000}, "periods": {},
                   "current": {"TMAX": True, "SNOW": False}}
        candidates = [(3.0, "A")]
        self.assertEqual(S.choose(candidates, {"A": station}, "TMAX", AS_OF)["state"], "one")
        snow = S.choose(candidates, {"A": station}, "SNOW", AS_OF)
        self.assertEqual(snow["state"], "none")
        self.assertIs(snow["examined"][0]["current"], False)

    def test_the_replaced_benchland_snow_pick_is_checked_against_its_recorded_reason(self):
        gates = {"benchland": {"SNOW": {"chosen": ["US1MTFG0003", "USC00243947"], "examined": [
            {"id": "USC00244978", "current": False, "pass": False}]}}}
        checks = []
        S._verify_gates({"gates": gates}, {}, lambda name, passed, detail="": checks.append((name, passed)))
        self.assertEqual([p for n, p in checks if "replaced by" in n], [True])
        gates["benchland"]["SNOW"]["examined"][0]["current"] = True
        checks.clear()
        S._verify_gates({"gates": gates}, {}, lambda name, passed, detail="": checks.append((name, passed)))
        self.assertEqual([p for n, p in checks if "replaced by" in n], [False])


class ScopeTests(unittest.TestCase):
    """D26: the job scopes, and the earlier refresh meanings when no scope is given."""

    def test_daily_refreshes_the_chosen_stations_and_the_list_with_the_last_modified_skip(self):
        index = {"stations": {"chosen_station_ids": ["USC00000002", "USC00000001"]}}
        self.assertEqual(S.scope_settings("daily", index),
                         (False, frozenset({"USC00000001", "USC00000002"}), True, True))

    def test_monthly_refreshes_every_file_with_no_skip(self):
        self.assertEqual(S.scope_settings("monthly", {}), (True, frozenset(), False, True))

    def test_no_scope_keeps_the_earlier_refresh_meanings(self):
        self.assertEqual(S.scope_settings(None, {}, "none"), (False, frozenset(), False, False))
        self.assertEqual(S.scope_settings(None, {}, "all"), (True, frozenset(), False, True))
        self.assertEqual(S.scope_settings(None, {}, ["USC00000001"]), (False, frozenset({"USC00000001"}), False, False))
        with self.assertRaises(S.StationsError):
            S.scope_settings("weekly", {})

    def test_the_command_line_refuses_a_scope_with_an_earlier_refresh_flag(self):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            S.main(["build", "--store", "unused", "--cache", "unused", "--scope", "daily", "--refresh", "all"])


class LastModifiedTests(unittest.TestCase):
    """D26: a cached file whose kept Last-Modified equals the one header of a HEAD request is not fetched; any other
    answer (a changed date, no kept date, a failed or non-200 HEAD) fetches the file as the earlier rule did."""

    URL = "https://example.invalid/USC00000001.dly"
    LM = "Mon, 05 Oct 2026 14:33:16 GMT"
    LM_NEW = "Tue, 06 Oct 2026 14:33:16 GMT"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "USC00000001.dly"
        self.body = dly_line("USC00000001", 2022, 1, "TMAX", {1: (322, " ", " ")}).encode("ascii")
        self.path.write_bytes(self.body)
        self.check = S._check_dly("USC00000001")
        self.patches = [mock.patch("time.sleep", lambda seconds: None)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    @staticmethod
    def head(value=None, status=200):
        resp = FakeResponse(status)
        resp.headers = {"Last-Modified": value} if value else {}
        return resp

    def fetch(self, *, skip=True):
        return S.fetch(self.URL, self.path, self.check, offline=False, refresh=True, pacer=S._Pacer(0),
                       skip_unchanged=skip)

    def test_an_unchanged_last_modified_is_not_fetched(self):
        S._write_lastmod(self.path, self.LM)
        with mock.patch("requests.head", return_value=self.head(self.LM)) as head, \
                mock.patch("requests.get") as get:
            data, state, reason = self.fetch()
        self.assertEqual((state, reason, data), ("unchanged", None, self.body))
        self.assertEqual(head.call_count, 1)
        get.assert_not_called()

    def test_a_changed_last_modified_is_fetched_and_the_new_date_is_kept(self):
        S._write_lastmod(self.path, self.LM)
        answer = FakeResponse(200, self.body)
        answer.headers = {"Last-Modified": self.LM_NEW}
        with mock.patch("requests.head", return_value=self.head(self.LM_NEW)), \
                mock.patch("requests.get", return_value=answer) as get:
            data, state, _reason = self.fetch()
        self.assertEqual(state, "fetched")
        get.assert_called_once()
        self.assertEqual(S._read_lastmod(self.path), self.LM_NEW)

    def test_a_file_with_no_kept_date_is_fetched_without_a_head_request(self):
        answer = FakeResponse(200, self.body)
        answer.headers = {"Last-Modified": self.LM}
        with mock.patch("requests.head") as head, mock.patch("requests.get", return_value=answer):
            _data, state, _reason = self.fetch()
        head.assert_not_called()
        self.assertEqual((state, S._read_lastmod(self.path)), ("fetched", self.LM))

    def test_a_failed_or_empty_head_request_fetches_the_file(self):
        S._write_lastmod(self.path, self.LM)
        for head_answer in ({"side_effect": requests.ConnectionError("no answer")},
                            {"return_value": self.head(status=404)},
                            {"return_value": self.head(None)}):
            answer = FakeResponse(200, self.body)
            answer.headers = {"Last-Modified": self.LM}
            with mock.patch("requests.head", **head_answer), mock.patch("requests.get", return_value=answer) as get:
                _data, state, _reason = self.fetch()
            self.assertEqual(state, "fetched")
            get.assert_called_once()

    def test_a_refresh_without_the_skip_setting_makes_no_head_request(self):
        S._write_lastmod(self.path, self.LM)
        answer = FakeResponse(200, self.body)
        answer.headers = {"Last-Modified": self.LM}
        with mock.patch("requests.head") as head, mock.patch("requests.get", return_value=answer):
            _data, state, _reason = self.fetch(skip=False)
        head.assert_not_called()
        self.assertEqual(state, "fetched")

    def test_a_kept_date_that_cannot_be_written_is_a_note_and_the_file_still_loads(self):
        S._write_lastmod(self.path, self.LM)
        answer = FakeResponse(200, self.body)
        answer.headers = {"Last-Modified": self.LM_NEW}
        with mock.patch("requests.head", return_value=self.head(self.LM_NEW)), \
                mock.patch("requests.get", return_value=answer), \
                mock.patch.object(S, "_write_atomic", side_effect=OSError("disk full")):
            data, state, reason = self.fetch()
        self.assertEqual((data, state), (self.body, "fetched"))
        self.assertIn("could not be kept", reason)


class DailyScopeBuildTests(OfflineBuildTests):
    """A daily build reads the chosen stations' files and the list and the inventory; a file whose kept Last-Modified
    is unchanged is not fetched, and the block counts it."""

    def test_a_daily_build_requests_the_list_and_the_chosen_file_and_skips_an_unchanged_one(self):
        S.build(self.store, self.cache, offline=True, procs=1)
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["stations"]["chosen_station_ids"], ["USC00000001"])
        dly = self.cache / "ghcn" / "dly" / "USC00000001.dly"
        S._write_lastmod(dly, "Mon, 05 Oct 2026 14:33:16 GMT")
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            return FakeResponse(404)

        head = FakeResponse(200)
        head.headers = {"Last-Modified": "Mon, 05 Oct 2026 14:33:16 GMT"}
        with mock.patch("requests.get", side_effect=fake_get), mock.patch("requests.head", return_value=head):
            S.build(self.store, self.cache, offline=False, procs=1, scope="daily")
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["stations"]
        self.assertEqual(block["refresh"], {"mode": "daily", "ids": 1, "unchanged": 1})
        self.assertEqual(block["unchanged_station_ids"], ["USC00000001"])
        self.assertIn(S.STATIONS_URL, calls)
        self.assertIn(S.INVENTORY_URL, calls)
        self.assertNotIn(S.DLY_URL.format(id="USC00000001"), calls)


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


def passing_positions(store: Path, tile: str, element: str) -> list:
    """The (lat, lon) of each passing station of a tile list of a test store, in the list's own order (nearest first)."""
    doc = json.loads((store / "hail" / "tl" / f"{tile}.json").read_text(encoding="utf-8"))
    return [(p["lat"], p["lon"]) for p in doc["elements"][element]["passing"]]


class TileListTests(unittest.TestCase):
    """D36 and D32: the tile list of r0079_c0199 (centre 47.05 N, 110.05 W) holds up to six passing stations per element,
    nearest first, with positions and shares; a candidate whose file did not load is named in it and in the problem line.
    Eight stations carry a full SNOW record; the nearest of them and one more are walked past or cut at the cap."""

    TILE = "r0079_c0199"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        (self.cache / "ghcn" / "dly").mkdir(parents=True)
        self.store = self.root / "store"
        (self.store / "hail").mkdir(parents=True)
        self.patches = [mock.patch.object(S, "_check_list", lambda data: None),
                        mock.patch.object(S, "_check_inventory", lambda data: None)]
        for patch in self.patches:
            patch.start()
        (self.store / "hail" / "index.json").write_text(json.dumps({
            "as_of": "2026-10-16", "tiles": [self.TILE]}), encoding="utf-8")
        (self.store / "hail" / "manifest.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
        ids = [f"USC0000{n:04d}" for n in range(101, 109)]              # eight stations, moving away from the centre
        stations = [station_line(sid, 47.05 + 0.02 * k, -110.05 + 0.03 * k, "MT", f"STATION {k}")
                    for k, sid in enumerate(ids)]
        stations.append(station_line("USC00000150", 47.06, -110.04, "MT", "BROKEN"))   # nearest; its file is missing
        inventory = [f"{sid:<11} {47.05 + 0.02 * k:8.4f} {-110.05 + 0.03 * k:9.4f} SNOW 2000 2026"
                     for k, sid in enumerate(ids)]
        inventory.append("USC00000150  47.0600 -110.0400 SNOW 2000 2026")
        (self.cache / "ghcn" / "ghcnd-stations.txt").write_text("\n".join(stations) + "\n", encoding="utf-8")
        (self.cache / "ghcn" / "ghcnd-inventory.txt").write_text("\n".join(inventory) + "\n", encoding="utf-8")
        days = {d: (10, " ", " ") for d in range(1, 29)}
        for sid in ids:
            lines = [dly_line(sid, year, month, "SNOW", days) for year in range(2020, 2027) for month in range(1, 13)]
            (self.cache / "ghcn" / "dly" / f"{sid}.dly").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def test_a_tile_list_holds_every_passing_station_with_no_cap_and_names_the_failed_candidate(self):
        result = S.build(self.store, self.cache, offline=True, procs=1)
        self.assertEqual(result["state"], "partial")
        doc = json.loads((self.store / "hail" / "tl" / f"{self.TILE}.json").read_text(encoding="utf-8"))
        self.assertEqual((doc["f"], doc["tile"], doc["miles"]), ("hail-stn-tiles-v1", self.TILE, 40.0))
        self.assertNotIn("cap", doc)                                       # D61: the cap is gone
        self.assertEqual(doc["margin_miles"], S.tile_margin_miles(79, 199))
        self.assertEqual(doc["centre"], [47.05, -110.05])
        snow = doc["elements"]["SNOW"]
        self.assertEqual([p["id"] for p in snow["passing"]], [f"USC0000{n:04d}" for n in range(101, 109)])   # all eight
        self.assertFalse(snow["capped"])
        self.assertEqual([u["id"] for u in snow["unread"]], ["USC00000150"])
        self.assertEqual(snow["unread"][0]["name"], "BROKEN")
        self.assertIsNotNone(snow["unread"][0]["lat"])
        miles = [p["miles"] for p in snow["passing"]]
        self.assertEqual(miles, sorted(miles))
        for p in snow["passing"]:
            self.assertEqual(p["of"], 2192)
            self.assertGreaterEqual(p["share"], 0.8)
            self.assertEqual(set(p), {"id", "name", "lat", "lon", "miles", "ok", "of", "share"})
        self.assertEqual(doc["elements"]["TMAX"], {"centre": [47.05, -110.05], "margin_miles": S.tile_margin_miles(79, 199),
                                                   "passing": [], "rejected": [], "unread": [], "capped": False})   # no TMAX candidate
        self.assertEqual(snow["rejected"], [])                                  # all eight pass: nothing is rejected (D69)
        self.assertEqual((snow["centre"], snow["margin_miles"]), ([47.05, -110.05], S.tile_margin_miles(79, 199)))
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["stations"]
        self.assertEqual((block["tile_lists"]["capped"], block["tile_lists"]["unread"]), (0, 1))
        self.assertEqual(block["tile_lists"]["margin_miles_max"], S.tile_margin_miles(79, 199))
        self.assertEqual(block["tile_lists"]["format"], "hail-stn-tiles-v1")
        # D32: the problem line names the failed candidate, with its name and id, and no absence claim
        self.assertEqual(block["problem"], "Station readings could not be loaded in this update for BROKEN (USC00000150); "
                                           "that is not the same as no station reading. This is not an all-clear.")
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))
        data = (self.store / "hail" / "tl" / f"{self.TILE}.json").read_bytes()
        self.assertEqual(manifest["files"][f"hail/tl/{self.TILE}.json"]["sha256"], __import__("hashlib").sha256(data).hexdigest())

    def test_the_tile_list_is_the_same_bytes_on_a_second_build(self):
        S.build(self.store, self.cache, offline=True, procs=1)
        first = (self.store / "hail" / "tl" / f"{self.TILE}.json").read_bytes()
        S.build(self.store, self.cache, offline=True, procs=1)
        self.assertEqual((self.store / "hail" / "tl" / f"{self.TILE}.json").read_bytes(), first)

    def test_verify_records_the_two_picks_at_the_benchland_point_from_this_tile(self):
        S.build(self.store, self.cache, offline=True, procs=1)
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        block = index["stations"]
        manifest = json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8"))
        # the manifest of this synthetic store lists the tile lists and the station files it wrote
        checks = []
        picks, parity = S._verify_tile_lists(self.store, index, block, manifest,
                                             lambda name, passed, detail="": checks.append((name, passed, detail)))
        self.assertEqual(sorted(picks), ["benchland", "billings"])
        self.assertEqual(parity["differences"], 0)
        self.assertEqual(parity["points"], 9 * len(S.CORE))                 # the centre, four cell corners, four routed corners
        self.assertEqual((parity["tile_files"]["files"], parity["tile_files"]["longest_list"]), (1, 8))   # D61: recorded
        self.assertGreater(parity["tile_files"]["largest_gzip"], 0)
        snow = picks["benchland"]["SNOW"]
        self.assertEqual(len(snow["picks"]), 2)
        self.assertTrue(set(snow["picks"]) <= {f"USC0000{n:04d}" for n in range(101, 107)})
        # the failed candidate is nearer to the Benchland point than the second pick, so the picks are not known
        broken = S.haversine_miles(47.08, -110.02, 47.06, -110.04)
        second = passing_positions(self.store, self.TILE, "SNOW")[1]
        cut = S.haversine_miles(47.08, -110.02, *second)
        self.assertEqual(snow["failed_nearer"], ["USC00000150"] if broken < cut else [])
        self.assertEqual(picks["benchland"]["TMAX"], {"picks": [], "miles": [], "failed_nearer": [], "rejected_nearer": [],
                                                      "rejected_more": 0})
        # the listed checks: one file per index tile, the manifest entry, and the list's own rules
        names = {name: passed for name, passed, _detail in checks}
        self.assertTrue(names["tile lists: one file per index tile"])
        self.assertTrue(names["manifest lists each tile list with its bytes and SHA-256"])
        self.assertTrue(names["tile lists: format, margin, uncapped, nearest first, passing entries current at 80 percent "
                               "and within the radius, unread entries are candidates not read, rejected entries are read "
                               "candidates that fail the rule"])
        self.assertTrue(names["tile lists agree with the point rule at each tile's centre, cell corners and routed corners, "
                               "every element (D61, D63, D69, D72)"])
        self.assertTrue(names["the daily set holds every passing station of every tile list (D73)"])

    def test_the_passing_walk_keeps_every_passing_station_and_asks_for_a_missing_summary(self):
        cands = [(1.0, "A"), (2.0, "B"), (3.0, "C"), (4.0, "D")]
        def summary(sid, share_ok=2000):
            return {"name": sid, "lat": 47.0, "lon": -110.0, "cover": {"SNOW": share_ok}, "current": {"SNOW": True},
                    "newest": {"SNOW": 20261001}}
        summaries = {"A": summary("A"), "B": summary("B"), "C": summary("C"), "D": summary("D")}
        walked = S._passing_list(cands, summaries, "SNOW", date(2026, 10, 16))
        self.assertEqual([p["id"] for p in walked["passing"]], ["A", "B", "C", "D"])   # D61: no cap
        self.assertFalse(walked["capped"])
        self.assertIsNone(walked["need"])
        short = S._passing_list(cands, {"A": summary("A")}, "SNOW", date(2026, 10, 16))
        self.assertEqual((short["passing"][0]["id"], short["need"]), ("A", "B"))   # the walk pulls B, then walks again
        failing = S._passing_list(cands, {"A": summary("A", 100), "B": summary("B")}, "SNOW", date(2026, 10, 16))
        self.assertEqual([p["id"] for p in failing["passing"]], ["B"])               # A is under 80 percent

    def test_the_partial_problem_names_each_failed_candidate_and_counts_the_other_files(self):
        named = S._partial_problem([{"id": "USC00000002", "name": "Buffalo 1.7 E"}], [])
        self.assertEqual(named, "Station readings could not be loaded in this update for Buffalo 1.7 E (USC00000002); that is "
                                "not the same as no station reading. This is not an all-clear.")
        many = S._partial_problem([{"id": f"U{n}", "name": f"S{n}"} for n in range(5)], [])
        self.assertIn("S0 (U0), S1 (U1), S2 (U2) and 2 more stations", many)
        counted = S._partial_problem([], [{"source": "stations", "reason": "x"}, {"source": "daily", "station": "Z"}])
        self.assertEqual(counted, "Some station files could not be loaded in this update (2 files); that is not the same as "
                                  "no station reading. This is not an all-clear.")


class PointPicksTests(unittest.TestCase):
    """D36, the shared rule for the picks at a point (stations.tile_list_picks; the browser is to run the same rule): the two
    nearest passing stations of one element's tile list to the point, the unread candidates nearer than the second pick
    named (D32), and a capped list that cannot answer. The Billings case is the gate's: from the Billings gate point the
    SNOW list of the Billings tile names WTP (1.4 miles) and the airport (2.6 miles); the positions are the store's own."""

    GATE = (45.7836, -108.5047)                  # the Billings gate point (stations.GATE_POINTS["billings"])
    FRAME = {"centre": [47.0, -110.0], "margin_miles": 4.3}     # the test points are this centre (D72: a list carries both)

    def gate_frame(self) -> dict:
        """The centre and margin of the tile that holds the Billings gate point."""
        from website import hail
        row, col = hail.cell_for(*self.GATE)
        return {"centre": list(S.tile_centre(row // hail.TILE, col // hail.TILE)),
                "margin_miles": S.tile_margin_miles(row // hail.TILE, col // hail.TILE)}
    MILE_DEG = 1.0 / 69.09                       # one mile of latitude, near these latitudes (the rule is haversine)

    @staticmethod
    def entry(sid, name, lat, lon):
        return {"id": sid, "name": name, "lat": lat, "lon": lon, "miles": 0.0, "ok": 2000, "of": 2192, "share": 0.91}

    def north(self, miles, lon=-110.0):
        return (47.0 + miles * self.MILE_DEG, lon)

    def test_the_billings_gate_names_the_cooperative_site_and_the_airport(self):
        block = {**self.gate_frame(), "capped": True, "unread": [], "passing": [
            self.entry("USC00240801", "BILLINGS WFO", 45.7503, -108.5697),
            self.entry("USC00240802", "BILLINGS WTP", 45.7717, -108.4811),
            self.entry("USW00024033", "BILLINGS INTL AP", 45.8072, -108.5461),
            self.entry("US1MTYS0014", "BILLINGS 4.5 NE", 45.8323, -108.444)]}
        got = S.tile_list_picks(block, *self.GATE, light={"USC00240802": {"net": "COOP"}, "USW00024033": {"net": "WBAN"}})
        self.assertEqual(got["state"], "two")
        self.assertEqual([(p["id"], p["name"], p["net"], p["miles"]) for p in got["picks"]],
                         [("USC00240802", "BILLINGS WTP", "COOP", 1.4), ("USW00024033", "BILLINGS INTL AP", "WBAN", 2.6)])
        self.assertEqual(got["unread"], [])
        self.assertFalse(got["incomplete"])

    def test_the_two_nearest_passing_stations_come_first_and_ties_go_by_id(self):
        block = {**self.FRAME, "capped": False, "unread": [], "passing": [
            self.entry("USC00000003", "FAR", *self.north(9.0)),
            self.entry("USC00000002", "TIE B", *self.north(3.0)),
            self.entry("USC00000001", "TIE A", *self.north(3.0)),
            self.entry("USC00000004", "NEAR", *self.north(1.0))]}
        got = S.tile_list_picks(block, 47.0, -110.0)
        self.assertEqual([p["id"] for p in got["picks"]], ["USC00000004", "USC00000001"])   # nearest, then the tie by id
        self.assertEqual(got["state"], "two")
        self.assertEqual(got["candidates"], 4)

    def test_a_passing_station_beyond_the_radius_is_not_a_pick(self):
        block = {**self.FRAME, "capped": False, "unread": [], "passing": [self.entry("USC00000005", "FAR", *self.north(45.0))]}
        got = S.tile_list_picks(block, 47.0, -110.0)
        self.assertEqual(got["picks"], [])
        self.assertEqual(got["state"], "none")                  # no passing station within 40 miles, nothing unread
        self.assertEqual(got["candidates"], 0)

    def test_one_pick_is_state_one_and_the_radius_bounds_the_pick_list(self):
        block = {**self.FRAME, "capped": False, "unread": [], "passing": [self.entry("USC00000006", "ONLY", *self.north(12.0)),
                                                            self.entry("USC00000007", "OUT", *self.north(41.0))]}
        got = S.tile_list_picks(block, 47.0, -110.0)
        self.assertEqual(got["state"], "one")
        self.assertEqual([p["id"] for p in got["picks"]], ["USC00000006"])

    def test_an_unread_candidate_nearer_than_the_second_pick_is_named_and_a_farther_one_is_not(self):
        block = {**self.FRAME, "capped": False, "passing": [self.entry("USC00000010", "P1", *self.north(1.0)),
                                              self.entry("USC00000011", "P2", *self.north(5.0))],
                 "unread": [{"id": "USC00000012", "name": "NEAR UNREAD", "lat": 47.0 + 2.0 * self.MILE_DEG,
                             "lon": -110.0, "reason": "its file did not load"},
                            {"id": "USC00000013", "name": "FAR UNREAD", "lat": 47.0 + 30.0 * self.MILE_DEG,
                             "lon": -110.0, "reason": "its file did not load"}]}
        got = S.tile_list_picks(block, 47.0, -110.0)
        self.assertEqual([p["id"] for p in got["picks"]], ["USC00000010", "USC00000011"])
        self.assertEqual([u["name"] for u in got["unread"]], ["NEAR UNREAD"])        # named (D32), never skipped
        self.assertEqual(got["unread"][0]["reason"], "its file did not load")
        self.assertTrue(got["incomplete"])
        self.assertEqual(got["state"], "two")

    def test_an_unread_candidate_without_a_position_is_always_named(self):
        block = {**self.FRAME, "capped": False, "passing": [], "unread": [{"id": "USC00000020", "name": "NO POSITION", "lat": None,
                                                             "lon": None, "reason": "the file did not load"}]}
        got = S.tile_list_picks(block, 47.0, -110.0)
        self.assertEqual(got["state"], "unavailable")          # no pick and an unread candidate: never "none"
        self.assertEqual([(u["name"], u["miles"]) for u in got["unread"]], [("NO POSITION", None)])

    def test_a_capped_list_with_fewer_than_two_stations_in_the_radius_cannot_answer(self):
        block = {**self.FRAME, "capped": True, "unread": [], "passing": [self.entry("USC00000030", "IN", *self.north(4.0)),
                                                           self.entry("USC00000031", "OUT", *self.north(50.0))]}
        self.assertIsNone(S.tile_list_picks(block, 47.0, -110.0))   # a station the list does not hold might be nearer

    def test_a_capped_list_with_two_stations_in_the_radius_answers(self):
        block = {**self.FRAME, "capped": True, "unread": [], "passing": [self.entry("USC00000040", "A", *self.north(4.0)),
                                                           self.entry("USC00000041", "B", *self.north(8.0)),
                                                           self.entry("USC00000042", "C", *self.north(50.0))]}
        got = S.tile_list_picks(block, 47.0, -110.0)
        self.assertEqual([p["id"] for p in got["picks"]], ["USC00000040", "USC00000041"])

    def test_no_block_cannot_answer_and_an_empty_block_says_none(self):
        self.assertIsNone(S.tile_list_picks(None, 47.0, -110.0))            # the file or the element is not in the store
        self.assertIsNone(S.tile_list_picks({}, 47.0, -110.0))
        empty = S.tile_list_picks({**self.FRAME, "capped": False, "passing": [], "unread": []}, 47.0, -110.0)
        self.assertEqual((empty["state"], empty["picks"]), ("none", []))


class RejectedAndMarginTests(unittest.TestCase):
    """D68, D69, D72 and D74: a point beyond the margin is refused and a block without its centre and margin cannot answer; the
    rejected candidates nearer than the second pick are named and the rest counted; rejected_rule and tile_list_picks name the
    same candidates; the margin covers every routed corner. Synthetic stations; the real tile lists are checked by verify."""

    CENTRE = (47.05, -110.05)

    def north(self, miles: float) -> tuple[float, float]:
        return (self.CENTRE[0] + miles / 69.09, self.CENTRE[1])

    def row(self, sid: str, name: str, miles: float, *, ok: int = 2000, current: bool = True, newest: int = 20260901) -> dict:
        lat, lon = self.north(miles)
        return {"id": sid, "name": name, "lat": lat, "lon": lon, "miles": miles, "ok": ok, "of": 2192,
                "share": round(ok / 2192, 4), "current": current, "newest": newest}

    def frame(self, passing=(), unread=(), rejected=(), capped: bool = False, margin: float = 4.2) -> dict:
        return {"centre": list(self.CENTRE), "margin_miles": margin, "capped": capped, "passing": list(passing),
                "unread": list(unread), "rejected": list(rejected)}

    def test_the_margin_covers_every_routed_corner_and_a_point_beyond_it_is_refused(self):
        self.assertTrue(all(abs(lat - self.CENTRE[0]) <= 0.05 and abs(lon - self.CENTRE[1]) <= 0.05
                            for lat, lon in S.routed_corners(79, 199)))
        block = self.frame(passing=[self.row("USC00000001", "A", 0.1)])
        self.assertEqual(S.tile_list_picks(block, *self.CENTRE)["state"], "one")
        self.assertIsNone(S.tile_list_picks(block, self.CENTRE[0] + 0.1, self.CENTRE[1]))   # 6.9 miles north: beyond 4.2

    def test_a_block_without_its_centre_or_margin_cannot_answer(self):
        block = self.frame(passing=[self.row("USC00000002", "B", 0.5)])
        self.assertIsNone(S.tile_list_picks({k: v for k, v in block.items() if k != "margin_miles"}, *self.CENTRE))   # D68
        self.assertIsNone(S.tile_list_picks({k: v for k, v in block.items() if k != "centre"}, *self.CENTRE))
        self.assertEqual(S.tile_list_picks(block, *self.CENTRE)["picks"][0]["id"], "USC00000002")

    def test_the_rejected_candidates_nearer_than_the_second_pick_are_named_and_the_others_counted(self):
        block = self.frame(passing=[self.row("USC00000010", "P1", 1.0), self.row("USC00000011", "P2", 5.0)],
                           rejected=[self.row("USC00000012", "R NEAR", 2.0, ok=300),
                                     self.row("USC00000013", "R FAR", 6.0, ok=300, current=False, newest=20250601),
                                     self.row("USC00000014", "R TINY", 0.5, ok=100),
                                     self.row("USC00000015", "R OUTSIDE", 44.0, ok=100)])
        got = S.tile_list_picks(block, *self.CENTRE)
        self.assertEqual([p["id"] for p in got["picks"]], ["USC00000010", "USC00000011"])
        self.assertEqual([r["name"] for r in got["rejected"]], ["R TINY", "R NEAR"])     # nearer than P2, nearest first
        self.assertEqual(got["rejected_more"], 1)                                       # R FAR is beyond P2: counted
        self.assertEqual(set(got["rejected"][0]), {"id", "name", "miles", "ok", "of", "share", "current", "newest"})
        self.assertEqual((got["rejected"][1]["miles"], got["rejected"][1]["share"]), (2.0, round(300 / 2192, 4)))
        self.assertEqual(got["state"], "two")                                           # a rejected station is not unread

    def test_with_one_pick_every_rejected_candidate_within_the_radius_is_named(self):
        block = self.frame(passing=[self.row("USC00000020", "P1", 1.0)],
                           rejected=[self.row("USC00000021", "R A", 2.0, ok=100), self.row("USC00000022", "R B", 30.0, ok=100),
                                     self.row("USC00000023", "R C", 50.0, ok=100)])
        got = S.tile_list_picks(block, *self.CENTRE)
        self.assertEqual(got["state"], "one")
        self.assertEqual([r["name"] for r in got["rejected"]], ["R A", "R B"])          # R C is beyond the radius
        self.assertEqual(got["rejected_more"], 0)

    def test_the_routed_corners_are_inside_their_tile_and_inside_the_margin(self):
        from website import hail
        for tr, tc in ((79, 199), (60, 140), (106, 171)):
            centre = S.tile_centre(tr, tc)
            for lat, lon in S.routed_corners(tr, tc):
                self.assertEqual(hail.tile_name(*(v // hail.TILE for v in hail.cell_for(lat, lon))), hail.tile_name(tr, tc))
                self.assertLessEqual(S.haversine_miles(centre[0], centre[1], lat, lon), S.tile_margin_miles(tr, tc))

    def test_rejected_rule_and_the_tile_list_name_the_same_candidates_and_counts_at_each_point(self):
        light = {}
        for sid, name, miles, ok, current in [("USC00000030", "A", 1.0, 2000, True), ("USC00000031", "B", 3.0, 300, True),
                                              ("USC00000032", "C", 4.0, 2000, True), ("USC00000033", "D", 2.0, 2000, False),
                                              ("USC00000034", "E", 9.0, 2000, True), ("USC00000035", "F", 30.0, 300, True)]:
            lat, lon = self.north(miles)
            light[sid] = {"name": name, "lat": lat, "lon": lon, "elev": 0.0, "net": "COOP", "current": {"SNOW": current},
                          "newest": {"SNOW": 20260901 if current else 20250601}, "cover": {"SNOW": ok}}
        cands = S.ordered_candidates(S.within_radius(light, *self.CENTRE), {s: r["cover"] for s, r in light.items()}, "SNOW")
        block = S._passing_list(cands, light, "SNOW", date(2026, 10, 16))
        block.update(centre=list(self.CENTRE), margin_miles=4.2)
        block["rejected"] = S.rejected_of_tile(S.within_radius(light, *self.CENTRE), light, "SNOW")
        self.assertEqual([r["name"] for r in S.rejected_rule(light, *self.CENTRE, "SNOW")["rejected"]], ["D", "B"])
        for point in (self.CENTRE, self.north(3.5), self.north(-4.0), self.north(1.2)):
            want = S.rejected_rule(light, *point, "SNOW")
            got = S.tile_list_picks(block, *point, light=light)
            self.assertEqual(got["rejected"], want["rejected"])
            self.assertEqual(got["rejected_more"], want["rejected_more"])
            self.assertEqual(got["picks"] and [p["id"] for p in got["picks"]],
                             [c["id"] for c in S.point_rule(light, *point, "SNOW", date(2026, 10, 16))["chosen"]])


class RejectedBuildTests(unittest.TestCase):
    """D69, D73 and D74 on a built store: an unread candidate that cannot report the element into the current window is not
    named for it (D74); the daily set holds every loaded station in reach with 80 percent coverage for some element, current
    or not (D73); the rejected part of the tile list names the candidates that fail the rule (D69)."""

    TILE = "r0079_c0199"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        (self.cache / "ghcn" / "dly").mkdir(parents=True)
        self.store = self.root / "store"
        (self.store / "hail").mkdir(parents=True)
        self.patches = [mock.patch.object(S, "_check_list", lambda data: None),
                        mock.patch.object(S, "_check_inventory", lambda data: None)]
        for patch in self.patches:
            patch.start()
        (self.store / "hail" / "index.json").write_text(json.dumps({"as_of": "2026-10-16", "tiles": [self.TILE]}),
                                                        encoding="utf-8")
        (self.store / "hail" / "manifest.json").write_text(json.dumps({"files": {}}), encoding="utf-8")

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def write_store(self, rows: list[tuple]) -> None:
        """rows: (id, lat, lon, name, {element: (first_year, last_year)}, {element: [(year, months)]} or None). None means the
        station file is missing from the cache, so the station failed."""
        days = {d: (10, " ", " ") for d in range(1, 29)}
        stn, inv = [], []
        for sid, lat, lon, name, spans, records in rows:
            stn.append(station_line(sid, lat, lon, "MT", name))
            for element, (first, last) in spans.items():
                inv.append(f"{sid:<11} {lat:8.4f} {lon:9.4f} {element} {first} {last}")
            if records is not None:
                lines = [dly_line(sid, year, month, element, days)
                         for element, periods in records.items() for year, months in periods for month in months]
                (self.cache / "ghcn" / "dly" / f"{sid}.dly").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (self.cache / "ghcn" / "ghcnd-stations.txt").write_text("\n".join(stn) + "\n", encoding="utf-8")
        (self.cache / "ghcn" / "ghcnd-inventory.txt").write_text("\n".join(inv) + "\n", encoding="utf-8")

    def test_an_unread_candidate_that_cannot_report_the_element_now_is_not_named_for_it(self):
        self.write_store([
            ("USC00000201", 47.06, -110.04, "GOOD", {"SNOW": (2000, 2026)}, {"SNOW": [(y, range(1, 13)) for y in range(2020, 2027)]}),
            ("USC00000202", 47.07, -110.03, "OLD SNOW", {"TMAX": (2000, 2026), "SNOW": (2000, 2019)}, None),
            ("USC00000203", 47.08, -110.02, "NEW SNOW", {"SNOW": (2000, 2026)}, None)])
        S.build(self.store, self.cache, offline=True, procs=1)
        doc = json.loads((self.store / "hail" / "tl" / f"{self.TILE}.json").read_text(encoding="utf-8"))
        self.assertEqual([u["name"] for u in doc["elements"]["SNOW"]["unread"]], ["NEW SNOW"])     # OLD SNOW ended in 2019
        self.assertEqual([u["name"] for u in doc["elements"]["TMAX"]["unread"]], ["OLD SNOW"])     # but it reports TMAX
        block = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))["stations"]["stations"]
        self.assertEqual(block["USC00000202"]["cover"], {"TMAX": None})                             # D74: the walk's elements
        self.assertEqual(block["USC00000203"]["cover"], {"SNOW": None})

    def test_the_daily_set_holds_the_loaded_stations_in_reach_with_80_percent_coverage_current_or_not(self):
        full = {"SNOW": [(y, range(1, 13)) for y in range(2020, 2027)]}
        self.write_store([
            ("USC00000211", 47.06, -110.04, "CURRENT", {"SNOW": (2000, 2026)}, full),
            ("USC00000212", 47.09, -110.00, "NOT CURRENT",
             {"SNOW": (2000, 2026)}, {"SNOW": [(y, range(1, 13)) for y in range(2020, 2026)] + [(2026, range(1, 8))]}),
            ("USC00000213", 47.10, -110.00, "LOW COVERAGE", {"SNOW": (2000, 2026)},
             {"SNOW": [(y, range(1, 13)) for y in range(2024, 2027)]}),
            ("USC00000214", 49.20, -107.00, "FAR", {"SNOW": (2000, 2026)}, full)])
        S.build(self.store, self.cache, offline=True, procs=1)
        index = json.loads((self.store / "hail" / "index.json").read_text(encoding="utf-8"))
        daily = set(index["stations"]["chosen_station_ids"])
        self.assertIn("USC00000211", daily)                       # a pick
        self.assertIn("USC00000212", daily)                       # D73: in reach, 92 percent coverage, not current
        self.assertNotIn("USC00000213", daily)                    # under 80 percent for every element
        self.assertTrue((self.store / "hail" / "sd" / "USC00000214.json").is_file())   # loaded: the regression set reads it
        self.assertNotIn("USC00000214", daily)                    # loaded and complete, but in reach of no location
        self.assertEqual(index["stations"]["counts"]["pick_files"], 1)
        self.assertEqual(index["stations"]["counts"]["daily_reach_files"], len(daily) - 1)
        doc = json.loads((self.store / "hail" / "tl" / f"{self.TILE}.json").read_text(encoding="utf-8"))
        snow = doc["elements"]["SNOW"]
        self.assertEqual([p["name"] for p in snow["passing"]], ["CURRENT"])
        rejected = {r["name"]: r for r in snow["rejected"]}                  # D69: the candidates that fail the rule
        self.assertEqual(sorted(rejected), ["LOW COVERAGE", "NOT CURRENT"])
        self.assertFalse(rejected["NOT CURRENT"]["current"])
        self.assertEqual(rejected["NOT CURRENT"]["newest"], 20260728)
        self.assertEqual(rejected["LOW COVERAGE"]["share"], round(672 / 2192, 4))
        self.assertEqual(index["stations"]["tile_lists"]["rejected"], 2)
        checks = []
        S._verify_tile_lists(self.store, index, index["stations"],
                             json.loads((self.store / "hail" / "manifest.json").read_text(encoding="utf-8")),
                             lambda name, passed, detail="": checks.append((name, passed)))
        self.assertIn(("the daily set holds every passing station of every tile list (D73)", True), checks)


def destination(lat: float, lon: float, bearing_deg: float, miles: float) -> tuple[float, float]:
    """The point miles away from (lat, lon) along the initial bearing (spherical; the module's own earth radius)."""
    d = miles / (S.EARTH_KM / S.MILE_KM)
    th, p1, l1 = math.radians(bearing_deg), math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(th))
    l2 = l1 + math.atan2(math.sin(th) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def bearing_to(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y))


class PoolFixture:
    """A cache and an empty store for the given tiles. Each station is (id, lat, lon, state, name, elements): it reports
    each element unflagged on 28 days of every month from 2020 to 2026 (the records of TileListTests), and its inventory
    lists the element to 2026. The list and inventory checks of the build are the synthetic-size ones."""

    def __init__(self, root: Path, tiles: list[str], stations: list[tuple]):
        self.root = root
        self.cache = root / "cache"
        (self.cache / "ghcn" / "dly").mkdir(parents=True)
        self.store = root / "store"
        (self.store / "hail").mkdir(parents=True)
        (self.store / "hail" / "index.json").write_text(json.dumps({"as_of": "2026-10-16", "tiles": tiles}), encoding="utf-8")
        (self.store / "hail" / "manifest.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
        stn, inv, lines = [], [], {}
        days = {d: (10, " ", " ") for d in range(1, 29)}
        for sid, lat, lon, state, name, elements in stations:
            stn.append(station_line(sid, lat, lon, state, name))
            for element in elements:
                inv.append(f"{sid:<11} {lat:8.4f} {lon:9.4f} {element} 2000 2026")
                lines.setdefault(sid, []).extend(dly_line(sid, y, m, element, days)
                                                 for y in range(2020, 2027) for m in range(1, 13))
        (self.cache / "ghcn" / "ghcnd-stations.txt").write_text("\n".join(stn) + "\n", encoding="utf-8")
        (self.cache / "ghcn" / "ghcnd-inventory.txt").write_text("\n".join(inv) + "\n", encoding="utf-8")
        for sid, rows in lines.items():
            if sid.startswith("CA"):             # a Canadian station's file is never in the cache (D62)
                continue
            (self.cache / "ghcn" / "dly" / f"{sid}.dly").write_text("\n".join(rows) + "\n", encoding="utf-8")


class PoolTests(unittest.TestCase):
    """D61 and D62: the tile's margin, the uncapped list, the Canadian candidates that are not read, the pool by position,
    the regression set, and the words. Synthetic stations only; the real files are checked by verify."""

    TILE = "r0079_c0199"                                  # centre 47.05 N, 110.05 W; margin 4.181 miles
    CENTRE = (47.05, -110.05)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [mock.patch.object(S, "_check_list", lambda data: None),
                        mock.patch.object(S, "_check_inventory", lambda data: None)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def build(self, fixture: PoolFixture, *, record_calls: list | None = None) -> dict:
        real = S.fetch

        def recording(url, *args, **kwargs):
            if record_calls is not None:
                record_calls.append(url)
            return real(url, *args, **kwargs)

        with mock.patch.object(S, "fetch", side_effect=recording):
            S.build(fixture.store, fixture.cache, offline=True, procs=1)
        return json.loads((fixture.store / "hail" / "index.json").read_text(encoding="utf-8"))["stations"]["stations"]

    def test_a_tile_margin_is_the_distance_to_its_farthest_corner_and_covers_every_routed_corner(self):
        centre = S.tile_centre(79, 199)
        far = max(S.haversine_miles(centre[0], centre[1], lat, lon)
                  for lat in (centre[0] - 0.05, centre[0] + 0.05) for lon in (centre[1] - 0.05, centre[1] + 0.05))
        self.assertEqual(S.tile_margin_miles(79, 199), math.ceil(far * 1000) / 1000)   # D72: the corner, rounded up
        self.assertTrue(4.1 < S.tile_margin_miles(79, 199) < 4.3)                       # 4.181 miles for this tile
        for lat, lon in S.routed_corners(79, 199):
            self.assertLessEqual(S.haversine_miles(centre[0], centre[1], lat, lon), S.tile_margin_miles(79, 199))

    def test_a_station_forty_two_miles_from_the_centre_is_listed_for_a_cell_about_four_miles_off_it(self):
        # the north-east corner cell of the tile is about 3.8 miles from the centre; a station 42 miles from the centre on
        # the same bearing is 38 miles from that cell: inside the rule's 40 miles for the cell, outside 40 for the centre
        from website import hail
        cell = hail.cell_centre(790, 1999)
        self.assertLess(S.haversine_miles(*self.CENTRE, *cell), 4.0)
        far = destination(*self.CENTRE, bearing_to(*self.CENTRE, *cell), 42.0)
        fixture = PoolFixture(self.root, [self.TILE], [("USC00000201", far[0], far[1], "MT", "FAR NE", ["SNOW"]),
                                                       ("USC00000202", 47.10, -110.10, "MT", "NEAR", ["SNOW"])])
        light = self.build(fixture)
        self.assertAlmostEqual(S.haversine_miles(*self.CENTRE, *far), 42.0, places=3)
        self.assertLess(S.haversine_miles(*cell, *far), S.RADIUS_MILES)
        doc = json.loads((fixture.store / "hail" / "tl" / f"{self.TILE}.json").read_text(encoding="utf-8"))
        listed = {p["id"]: p["miles"] for p in doc["elements"]["SNOW"]["passing"]}
        self.assertIn("USC00000201", listed)                                  # the margin admits it to the list
        self.assertAlmostEqual(listed["USC00000201"], 42.0, places=1)
        cell_pick = S.tile_list_picks(doc["elements"]["SNOW"], *cell, light=light)
        self.assertIn("USC00000201", [p["id"] for p in cell_pick["picks"]])
        self.assertEqual(S.point_rule(light, *cell, "SNOW", AS_OF)["chosen"][1]["id"], "USC00000201")   # the same rule
        centre_pick = S.tile_list_picks(doc["elements"]["SNOW"], *self.CENTRE, light=light)
        self.assertNotIn("USC00000201", [p["id"] for p in centre_pick["picks"]])   # 42 miles: outside 40 for the centre

    def test_a_canadian_station_is_a_candidate_not_read_named_only_when_it_is_nearer_than_a_pick(self):
        near = destination(*self.CENTRE, 180.0, 3.0)
        far = destination(*self.CENTRE, 270.0, 30.0)
        fixture = PoolFixture(self.root, [self.TILE], [
            ("USC00000301", *destination(*self.CENTRE, 0.0, 5.0), "MT", "FIVE N", ["SNOW"]),
            ("USC00000302", *destination(*self.CENTRE, 90.0, 10.0), "MT", "TEN E", ["SNOW"]),
            ("CAN00000001", *near, "AB", "CARWAY NEAR", ["SNOW"]),
            ("CAN00000002", *far, "AB", "CARWAY FAR", ["SNOW"])])
        calls: list[str] = []
        light = self.build(fixture, record_calls=calls)
        self.assertFalse(any("/CAN" in url for url in calls))                 # never requested (D62)
        self.assertFalse((fixture.cache / "ghcn" / "dly" / "CAN00000001.dly").exists())
        self.assertFalse((fixture.store / "hail" / "sd" / "CAN00000001.json").exists())
        self.assertTrue(light["CAN00000001"]["unread"])
        self.assertEqual(light["CAN00000001"]["reason"], S.CANADA_REASON)
        self.assertEqual(light["CAN00000001"]["cover"], {"SNOW": None})
        self.assertEqual(light["CAN00000001"]["net"], "other")
        self.assertEqual(sorted(light["CAN00000001"]["cover"]), ["SNOW"])
        self.assertEqual(sorted(light["CAN00000002"]["cover"]), ["SNOW"])
        index = json.loads((fixture.store / "hail" / "index.json").read_text(encoding="utf-8"))["stations"]
        self.assertEqual(index["not_read_station_ids"], ["CAN00000001", "CAN00000002"])
        self.assertEqual(index["failed_station_ids"], [])
        self.assertEqual(index["state"], "loaded")                            # a candidate not read is not a failed file
        doc = json.loads((fixture.store / "hail" / "tl" / f"{self.TILE}.json").read_text(encoding="utf-8"))
        snow = doc["elements"]["SNOW"]
        self.assertEqual({u["id"]: u["reason"] for u in snow["unread"]},
                         {"CAN00000001": S.CANADA_REASON, "CAN00000002": S.CANADA_REASON})
        self.assertNotIn("CAN00000001", [p["id"] for p in snow["passing"]])   # never counted as passing
        centre = S.tile_list_picks(snow, *self.CENTRE, light=light)
        self.assertEqual([p["id"] for p in centre["picks"]], ["USC00000301", "USC00000302"])
        self.assertEqual([u["id"] for u in centre["unread"]], ["CAN00000001"])   # 3 miles: before the second pick (10)
        self.assertTrue(centre["incomplete"])
        self.assertEqual(centre["state"], "two")
        rule = S.point_rule(light, *self.CENTRE, "SNOW", AS_OF)
        self.assertEqual([u["id"] for u in rule["unread"]], ["CAN00000001"])     # the one rule agrees (D63)
        words = " ".join(S.station_words(rule, "SNOW"))
        self.assertIn("CARWAY NEAR is not read (in Canada; the terms for its data are under review)", words)
        self.assertIn("so the two nearest stations that pass are not known for snowfall", words)
        self.assertTrue(words.endswith("This is not an all-clear."))
        self.assertNotIn("did not load", words)

    def test_the_words_say_not_read_for_a_canadian_station_and_did_not_load_for_a_failed_file(self):
        def result(*rows, state="unavailable"):
            return {"state": state, "chosen": [], "unread": list(rows)}
        canada = {"id": "CAN00000001", "name": "CARWAY", "miles": 3.0, "reason": S.CANADA_REASON}
        failed = {"id": "USC00000009", "name": "BROKEN", "miles": 2.0, "reason": "HTTP 503"}
        self.assertIn("CARWAY is not read (in Canada; the terms for its data are under review)",
                      S.station_words(result(canada), "SNOW")[0])
        self.assertIn("BROKEN did not load (HTTP 503)", S.station_words(result(failed), "SNOW")[0])
        mixed = S.station_words(result(canada, failed), "SNOW")[0]
        self.assertIn("could not be read", mixed)
        self.assertIn("CARWAY", mixed)
        self.assertIn("BROKEN", mixed)
        for line in (S.station_words(result(canada), "SNOW")[0], S.station_words(result(failed), "SNOW")[0], mixed):
            self.assertTrue(line.endswith("This is not an all-clear."))
            self.assertIsNone(FORBIDDEN.search(line.replace("This is not an all-clear.", "")))

    def test_the_pool_box_holds_every_station_within_the_radius_of_any_point_it_is_drawn_for(self):
        points = [(47.05, -110.05), (45.0, -104.0), (48.9, -116.0), (44.4, -115.0)]
        radius = S.RADIUS_MILES + 4.0
        box = S.pool_box(points, radius)
        for lat, lon in points:
            for bearing in range(0, 360, 15):
                for miles in (S.RADIUS_MILES, radius):
                    plat, plon = destination(lat, lon, bearing, miles)
                    self.assertTrue(box[0] <= plat <= box[1] and box[2] <= plon <= box[3],
                                    f"{plat:.4f},{plon:.4f} at {miles} miles from {lat},{lon} is outside the box")

    def test_within_radius_skips_by_latitude_and_gives_the_same_answer_as_the_distance_alone(self):
        rng = random.Random(7)
        stations = {f"S{i:04d}": {"lat": 44.0 + 6.0 * rng.random(), "lon": -117.0 + 14.0 * rng.random()} for i in range(400)}
        for radius in (40.0, 44.0):
            for lat, lon in [(47.05, -110.05), (49.0, -104.0), (44.5, -116.5)]:
                brute = sorted((S.haversine_miles(lat, lon, m["lat"], m["lon"]), sid) for sid, m in stations.items()
                               if S.haversine_miles(lat, lon, m["lat"], m["lon"]) <= radius)
                self.assertEqual(S.within_radius(stations, lat, lon, radius), brute)

    def test_a_neighbouring_state_station_is_a_candidate_and_the_snow_regression_reads_montana_only(self):
        fixture = PoolFixture(self.root, [self.TILE], [
            ("USS0014C05S", *destination(*self.CENTRE, 45.0, 20.0), "ID", "IDAHO SITE", ["SNOW"]),
            ("USC00000401", *destination(*self.CENTRE, 225.0, 20.0), "WY", "WYOMING SITE", ["SNOW"]),
            ("USC00000402", *destination(*self.CENTRE, 135.0, 20.0), "MT", "MONTANA SITE", ["SNOW"])])
        light = self.build(fixture)
        self.assertEqual(light["USS0014C05S"]["net"], "SNOTEL")
        self.assertTrue((fixture.store / "hail" / "sd" / "USS0014C05S.json").exists())    # read like any station
        self.assertTrue((fixture.store / "hail" / "sd" / "USC00000401.json").exists())
        got = S.collect(json.loads((fixture.store / "hail" / "index.json").read_text(encoding="utf-8")), fixture.cache,
                        offline=True, procs=1)
        self.assertEqual(got["regression"], ["USC00000402"])                              # Montana only (D7)
        self.assertEqual(sorted(got["not_read"]), [])
