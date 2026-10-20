"""Hail history store (website/hail.py, B1): the grid round trips, shard and cell keys, day indexes, inches,
the size classes and their boundaries, the words (forbidden terms and placeholders), describe() for the
Benchland and Billings SAMPLE cells, map_data(), the readers and manifest checks, the size and hashes of the
committed SAMPLE fixture (website/data/hail-fixture), and the command line. The store builder (the copy rule,
the pack rule, the mask, the fetch and load of a release archive, the build, verify and compare) is tested
offline with a fake HTTP client and a fake GRIB reader. No network, no pygrib."""

import contextlib
import copy
import functools
import gzip
import hashlib
import io
import inspect
import json
import math
import os
import random
import re
import shutil
import string
import subprocess
import sys
import tarfile
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import hail as h  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)          # the day after the fixture's as_of
BENCHLAND = (47.08, -110.02)
FIXTURE = h.FIXTURE_DIR
FORBIDDEN = re.compile(r"\b(damag\w*|dry|clear|insurance|eligib\w*|confirm\w*)\b", re.IGNORECASE)
NEGATION = re.compile(r"\bnot\b")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
ALLOWED_FIELDS = {"n", "start", "end", "largest_in", "largest_mm", "largest_date", "missing", "date", "in",
                  "mm", "class", "list", "problem", "as_of", "days", "word"}
NO_HAIL_KEYS = {"lead_none", "lead_none_one", "lead_none_plain", "unavailable", "what_this_is"}  # negation sentences
REQUIRED_WORDS = {"title", "lead_many", "lead_one", "lead_none", "lead_none_one", "lead_none_plain", "row",
                  "severe_tag", "large_note", "class_counts_title", "class_count_one", "class_count_many",
                  "what_this_is", "missing", "outside", "unavailable", "source", "sample", "stale", "loading"}


def strings_in(obj):
    """Every string inside a nested dict or list, for checks on rendered output."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from strings_in(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from strings_in(value)


def assert_clean_words(test, text):
    """No forbidden term, and "no hail" only inside a sentence that says it is not the conclusion."""
    test.assertIsNone(FORBIDDEN.search(text), f"forbidden term in: {text!r}")
    for sentence in SENTENCE_END.split(text):
        if re.search(r"no hail", sentence, re.IGNORECASE):
            test.assertIsNotNone(NEGATION.search(sentence), f"'no hail' without a negation: {sentence!r}")


def sample_index():
    return h.load_index(FIXTURE)


@functools.lru_cache(maxsize=1)
def scenario_mesh():
    """The Montana cells of the box rows 790 to 921 and columns 1985 to 2149, which holds every cell the build and
    compare tests use (Benchland, the check cell and Billings). Its cells are the full mask's cells in that box, so their
    indexes and their rows and columns are the real ones; the builds write about a twentieth of the full store's shards."""
    full = h.montana_mesh()
    row0, col0, nrow, ncol = 790, 1985, 132, 165
    inside = (full.rows >= row0) & (full.rows < row0 + nrow) & (full.cols >= col0) & (full.cols < col0 + ncol)
    mask = np.zeros((nrow, ncol), dtype=bool)
    mask[full.rows[inside] - row0, full.cols[inside] - col0] = True
    return h.Mesh(row0, col0, mask)


class GridTests(unittest.TestCase):
    def test_row_zero_and_last_centres(self):
        self.assertEqual(h.cell_centre(0, 0), (54.995, -129.995))
        lat, lon = h.cell_centre(3499, 6999)
        self.assertAlmostEqual(lat, 20.005, places=9)
        self.assertAlmostEqual(lon, -60.005, places=9)

    def test_benchland_point_is_row_792_column_1998(self):
        self.assertEqual(h.cell_for(*BENCHLAND), (792, 1998))
        self.assertEqual(h.cell_centre(792, 1998), (47.075, -110.015))

    def test_edge_points_go_south_and_east(self):
        self.assertEqual(h.cell_for(47.09, -110.0), (791, 2000))      # on the edge: the cell to the south
        self.assertEqual(h.cell_for(47.0901, -110.0), (790, 2000))    # just north of the edge
        self.assertEqual(h.cell_for(47.0899, -110.0), (791, 2000))
        self.assertEqual(h.cell_for(54.995, -129.99), (0, 1))         # on the east edge of column 0

    def test_montana_corners_round_trip(self):
        corners = [(49.0, -116.05), (49.0, -104.04), (44.36, -116.05), (44.36, -104.04)]
        for lat, lon in corners:
            cell = h.cell_for(lat, lon)
            self.assertTrue(h.in_grid(*cell))
            centre = h.cell_centre(*cell)
            self.assertEqual(h.cell_for(*centre), cell)
            self.assertLessEqual(abs(lat - centre[0]), 0.005 + 1e-9)
            self.assertLessEqual(abs(lon - centre[1]), 0.005 + 1e-9)

    def test_tile_edge_cells_round_trip(self):
        rows = (0, 9, 10, 19, 790, 791, 799, 800, 3490, 3499)
        cols = (0, 9, 10, 19, 1989, 1990, 1998, 1999, 2000, 6990, 6999)
        for r in rows:
            for c in cols:
                centre = h.cell_centre(r, c)
                self.assertEqual(h.cell_for(*centre), (r, c), (r, c))

    def test_random_cells_round_trip(self):
        rng = random.Random(20261018)
        for _ in range(3000):
            r, c = rng.randrange(h.ROWS), rng.randrange(h.COLS)
            self.assertEqual(h.cell_for(*h.cell_centre(r, c)), (r, c))

    def test_points_inside_a_cell_stay_in_it(self):
        rng = random.Random(7)
        for _ in range(500):
            r, c = rng.randrange(1, h.ROWS - 1), rng.randrange(1, h.COLS - 1)
            lat, lon = h.cell_centre(r, c)
            self.assertEqual(h.cell_for(lat + 0.0049, lon - 0.0049), (r, c))
            self.assertEqual(h.cell_for(lat + 0.0051, lon), (r - 1, c))      # north neighbour
            self.assertEqual(h.cell_for(lat - 0.0051, lon), (r + 1, c))      # south neighbour
            self.assertEqual(h.cell_for(lat, lon + 0.0051), (r, c + 1))      # east neighbour
            self.assertEqual(h.cell_for(lat, lon - 0.0051), (r, c - 1))      # west neighbour

    def test_outside_grid_and_bad_input(self):
        self.assertFalse(h.in_grid(*h.cell_for(60.0, -130.0)))
        self.assertTrue(h.in_grid(*h.cell_for(40.0, -100.0)))
        with self.assertRaises(ValueError):
            h.cell_for(float("nan"), -110.0)
        with self.assertRaises(ValueError):
            h.cell_for(47.0, math.inf)


class ShardAndKeyTests(unittest.TestCase):
    def test_shard_path_examples(self):
        self.assertEqual(h.shard_path(792, 1998), "hail/t/r0079_c0199.json")
        self.assertEqual(h.shard_path(0, 0), "hail/t/r0000_c0000.json")
        self.assertEqual(h.shard_path(3499, 6999), "hail/t/r0349_c0699.json")
        self.assertEqual(h.shard_path(921, 2149), "hail/t/r0092_c0214.json")
        self.assertEqual(h.shard_path(799, 1999), "hail/t/r0079_c0199.json")
        self.assertEqual(h.shard_path(800, 2000), "hail/t/r0080_c0200.json")

    def test_cell_key_examples(self):
        self.assertEqual(h.cell_key(792, 1998), 28)
        self.assertEqual(h.cell_key(921, 2149), 19)
        self.assertEqual(h.cell_key(0, 0), 0)
        self.assertEqual(h.cell_key(3499, 6999), 99)

    def test_keys_are_unique_within_a_tile(self):
        self.assertEqual({h.cell_key(r, c) for r in range(10, 20) for c in range(1990, 2000)}, set(range(100)))

    def test_shard_is_the_tile_of_the_cell(self):
        rng = random.Random(3)
        for _ in range(500):
            r, c = rng.randrange(h.ROWS), rng.randrange(h.COLS)
            self.assertEqual(h.shard_path(r, c), f"hail/t/r{r // 10:04d}_c{c // 10:04d}.json")

    def test_tile_names(self):
        self.assertEqual(h.tile_name(79, 199), "r0079_c0199")
        self.assertEqual(h.tile_name(0, 0), "r0000_c0000")
        self.assertEqual(h.shard_path(792, 1998), f"hail/t/{h.tile_name(79, 199)}.json")


class DayTests(unittest.TestCase):
    def test_day_index_for_2025_06_15(self):
        self.assertEqual((date(2025, 6, 15) - date(2020, 1, 1)).days, 1992)
        self.assertEqual(h.day_index(date(2025, 6, 15)), 1992)
        self.assertEqual(h.day_of_index(1992), date(2025, 6, 15))

    def test_origin(self):
        self.assertEqual(h.day_index(date(2020, 1, 1)), 0)
        self.assertEqual(h.day_of_index(0), date(2020, 1, 1))

    def test_round_trip_over_the_window(self):
        start, end = h.window_for(date(2026, 10, 17))
        d = start
        while d <= end:
            self.assertEqual(h.day_of_index(h.day_index(d)), d)
            d += timedelta(days=1)

    def test_window_is_1826_days_ending_on_as_of(self):
        start, end = h.window_for(date(2026, 10, 17))
        self.assertEqual((start, end), (date(2021, 10, 18), date(2026, 10, 17)))
        self.assertEqual((end - start).days + 1, 1826)

    def test_stamp_rule(self):
        self.assertEqual(h.stamp_for_day(date(2025, 6, 15)), date(2025, 6, 16))
        self.assertEqual(h.day_for_stamp(date(2025, 6, 16)), date(2025, 6, 15))


class InchTests(unittest.TestCase):
    def test_inches_round_down_to_the_hundredth(self):
        cases = {513: "2.01", 254: "1.00", 64: "0.25", 190: "0.74", 191: "0.75", 1016: "4.00", 1041: "4.09",
                 762: "3.00", 330: "1.29", 89: "0.35", 178: "0.70", 216: "0.85", 124: "0.48", 127: "0.50",
                 185: "0.72", 0: "0.00", 253: "0.99", 1015: "3.99", 1003: "3.94"}
        for tenths, text in cases.items():
            self.assertEqual(h.inches(tenths), text, tenths)

    def test_the_brief_examples_hold(self):
        self.assertEqual(h.inches(513), "2.01")       # 51.3 mm is 2.0197 in: rounded down
        self.assertEqual(h.inches(185), "0.72")       # 18.5 mm is 0.7283 in
        self.assertEqual(h.inches(253), "0.99")       # 25.3 mm is 0.9961 in
        self.assertEqual(h.inches(190), "0.74")       # 19.0 mm is 0.7480 in
        self.assertEqual(h.inches(1015), "3.99")      # 101.5 mm is 3.9961 in
        self.assertEqual(h.inches(254), "1.00")
        self.assertEqual(h.inches(64), "0.25")

    def test_band_edges_show_inside_their_class(self):
        cases = {241: "0.94", 242: "0.95", 253: "0.99", 254: "1.00", 368: "1.44", 369: "1.45", 380: "1.49",
                 381: "1.50", 495: "1.94", 496: "1.95", 507: "1.99", 508: "2.00", 698: "2.74", 699: "2.75",
                 1003: "3.94", 1004: "3.95", 1015: "3.99", 1016: "4.00"}
        for tenths, text in cases.items():
            self.assertEqual(h.inches(tenths), text, tenths)

    def test_class_edges_show_their_own_inch_cuts(self):
        for cls in h.CLASSES:
            self.assertEqual(float(h.inches(cls["min_tenths"])), cls["min_in"], cls["word"])
            if cls["max_tenths"] is not None:
                self.assertEqual(float(h.inches(cls["max_tenths"])), cls["max_in"], cls["word"])

    def test_a_shown_size_is_the_exact_size_rounded_down_inside_its_class(self):
        previous = -1
        for tenths in range(h.FLOOR_TENTHS, 10001):
            cls = h.class_for(tenths)
            shown = round(float(h.inches(tenths)) * 100)
            self.assertEqual(shown, (100 * tenths) // 254, tenths)
            self.assertGreaterEqual(shown, round(cls["min_in"] * 100), tenths)
            if cls["max_in"] is not None:
                self.assertLessEqual(shown, round(cls["max_in"] * 100), tenths)
            self.assertEqual(shown >= 100, cls["severe"], tenths)
            self.assertEqual(shown >= 400, cls["note"] is not None, tenths)
            self.assertGreaterEqual(shown, previous, tenths)
            previous = shown

    def test_there_is_one_display_rule_and_no_caps_table(self):
        for name in ("DISPLAY_CAPS", "NOTE_HUNDREDTHS", "display_hundredths"):
            self.assertFalse(hasattr(h, name), name)
        block = h.map_data(sample_index())
        self.assertNotIn("display_caps", block)
        self.assertEqual(block["tenths_per_inch"], 254)

    def test_inches_stay_within_a_hundredth_below_the_exact_value(self):
        for tenths in range(64, 1100):
            shown = round(float(h.inches(tenths)) * 100)
            self.assertLessEqual(254 * shown, 100 * tenths, tenths)
            self.assertLess(100 * tenths - 254 * shown, 254, tenths)

    def test_zero_shows_as_zero_point_zero_zero(self):
        self.assertEqual(h.inches(0), "0.00")

    def test_millimetres_text(self):
        self.assertEqual(h.mm_text(513), "51.3")
        self.assertEqual(h.mm_text(64), "6.4")
        self.assertEqual(h.mm_text(1016), "101.6")

    def test_negative_sizes_are_refused(self):
        with self.assertRaises(ValueError):
            h.inches(-1)
        with self.assertRaises(ValueError):
            h.mm_text(-1)

    def test_dates_read_like_the_sheet(self):
        self.assertEqual(h.fmt_date(date(2025, 6, 15)), "Jun 15, 2025")
        self.assertEqual(h.fmt_date(date(2026, 6, 5)), "Jun 5, 2026")


class ClassTests(unittest.TestCase):
    def test_class_boundaries(self):
        cases = [(64, "pea to mothball", False), (190, "pea to mothball", False),
                 (191, "penny to nickel", False), (253, "penny to nickel", False),
                 (254, "quarter to half dollar", True), (380, "quarter to half dollar", True),
                 (381, "ping-pong ball to golf ball", True), (507, "ping-pong ball to golf ball", True),
                 (508, "hen egg to tennis ball", True), (698, "hen egg to tennis ball", True),
                 (699, "baseball or larger", True), (1015, "baseball or larger", True)]
        for tenths, word, severe in cases:
            cls = h.class_for(tenths)
            self.assertEqual((cls["word"], cls["severe"]), (word, severe), tenths)
            self.assertIsNone(cls["note"], tenths)

    def test_note_from_four_inches(self):
        self.assertEqual(h.class_for(1016)["note"], h.WORDS["large_note"])
        self.assertEqual(h.class_for(1016)["word"], "baseball or larger")
        self.assertEqual(h.NOTE_TENTHS, 1016)

    def test_below_the_floor_is_refused(self):
        with self.assertRaises(ValueError):
            h.class_for(63)

    def test_class_for_returns_a_copy(self):
        cls = h.class_for(300)
        cls["word"] = "changed"
        self.assertEqual(h.CLASSES[2]["word"], "quarter to half dollar")

    def test_class_table_is_contiguous_and_matches_the_inch_cuts(self):
        for i, cls in enumerate(h.CLASSES):
            self.assertEqual(cls["min_tenths"], math.ceil(Decimal(str(cls["min_in"])) * 254), cls["word"])
            self.assertEqual(cls["severe"], cls["min_in"] >= 1.0, cls["word"])
            if i + 1 < len(h.CLASSES):
                self.assertEqual(cls["max_tenths"], h.CLASSES[i + 1]["min_tenths"] - 1, cls["word"])
            else:
                self.assertIsNone(cls["max_tenths"])
                self.assertIsNone(cls["max_in"])
        self.assertEqual(h.FLOOR_TENTHS, h.CLASSES[0]["min_tenths"])

    def test_words_are_the_nws_size_words(self):
        self.assertEqual([c["word"] for c in h.CLASSES],
                         ["pea to mothball", "penny to nickel", "quarter to half dollar",
                          "ping-pong ball to golf ball", "hen egg to tennis ball", "baseball or larger"])


class WordTests(unittest.TestCase):
    def test_no_forbidden_term_in_any_word(self):
        for key, template in h.WORDS.items():
            assert_clean_words(self, template)
        for cls in h.CLASSES:
            assert_clean_words(self, cls["word"])

    def test_no_hail_only_in_the_negation_sentences(self):
        found = {key for key, template in h.WORDS.items() if re.search(r"no hail", template, re.IGNORECASE)}
        self.assertEqual(found, NO_HAIL_KEYS)
        for key in found:
            for sentence in SENTENCE_END.split(h.WORDS[key]):
                if re.search(r"no hail", sentence, re.IGNORECASE):
                    self.assertIsNotNone(NEGATION.search(sentence), key)

    def test_placeholders_are_known_and_templates_fill(self):
        fill = {name: "x" for name in ALLOWED_FIELDS}
        for key, template in h.WORDS.items():
            fields = {field for _lit, field, _spec, _conv in string.Formatter().parse(template) if field}
            self.assertTrue(fields <= ALLOWED_FIELDS, (key, fields))
            template.format_map(fill)                  # raises KeyError on a missing field
        self.assertEqual(h.WORDS["row"].format_map({"date": "Jun 15, 2025", "in": "2.01", "mm": "51.3",
                                                    "class": "hen egg to tennis ball"}),
                         "Jun 15, 2025: 2.01 in (51.3 mm), hen egg to tennis ball")

    def test_required_words_exist(self):
        self.assertTrue(REQUIRED_WORDS <= set(h.WORDS))

    def test_source_line_names_the_source(self):
        self.assertIn(h.SOURCE_NAME, h.WORDS["source"])

    def test_what_this_is_gives_the_day_in_both_times(self):
        text = h.WORDS["what_this_is"]
        self.assertIn("A day runs from 12:00 UTC to 12:00 UTC the next day: 6 am to 6 am Mountain daylight time, "
                      "5 am to 5 am in winter (the SPC reporting day).", text)
        self.assertIn("the largest hail over this cell, about 0.7 miles north to south and 0.5 miles east to west, "
                      "during the day", text)
        self.assertIn("Sizes are shown to the hundredth of an inch, rounded down, with the millimetre value exact.",
                      text)
        self.assertIn("Days not listed have no radar estimate of 0.25 in or more; that is not the same as no hail.",
                      text)
        self.assertNotIn("11:59", text)
        self.assertNotIn("about 6 am to 6 am", text)

    def test_source_gives_the_next_day_sentence(self):
        self.assertIn("The newest day is added by a job that starts at 12:43 UTC and shows here on the next rebuild, "
                      "usually within the hour.", h.WORDS["source"])

    def test_no_em_dash_in_the_module_or_the_words(self):
        dash = "\u2014"
        self.assertNotIn(dash, (ROOT / "website" / "hail.py").read_text(encoding="utf-8"))
        for template in h.WORDS.values():
            self.assertNotIn(dash, template)


class DescribeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = sample_index()
        cls.benchland = h.cell_events(FIXTURE, *BENCHLAND)

    def test_benchland_lead_and_rows(self):
        out = h.describe(self.index, self.benchland, NOW, sample=True)
        self.assertEqual(out["state"], "loaded")
        self.assertEqual(out["lead"], "10 days with a radar-estimated hail size of 0.25 in or more between "
                                      "Oct 16, 2021 and Oct 15, 2026. Largest: 1.72 in (43.9 mm) on Sep 6, 2026.")
        self.assertEqual(out["rows"][0]["text"], "Sep 6, 2026: 1.72 in (43.9 mm), ping-pong ball to golf ball, "
                                                 "severe size")
        self.assertEqual(out["rows"][5]["text"], "Jun 15, 2025: 0.72 in (18.5 mm), pea to mothball")
        self.assertEqual([r["iso"] for r in out["rows"]][:3], ["2026-09-06", "2026-05-29", "2026-05-13"])   # newest first
        self.assertEqual(out["rows"][-1]["iso"], "2022-07-06")
        self.assertEqual(out["sample"], "SAMPLE data")
        self.assertIn("1.72 in", out["lead"])
        self.assertIn("43.9 mm", out["rows"][0]["text"])
        self.assertIn("severe size", out["rows"][0]["text"])

    def test_benchland_class_lines_and_missing_line(self):
        out = h.describe(self.index, self.benchland, NOW)
        self.assertIsNone(out["sample"])
        self.assertEqual(out["class_title"], "Days by size class")
        self.assertEqual(out["class_lines"], ["8 days: pea to mothball", "1 day: penny to nickel",
                                              "1 day: ping-pong ball to golf ball"])
        self.assertEqual(out["missing"], "Days with no data, not counted: Jun 8, 2022.")
        self.assertIsNone(out["stale"])

    def test_source_and_what_this_is(self):
        out = h.describe(self.index, self.benchland, NOW)
        self.assertEqual(out["source"], "Source: NOAA MRMS MESH 24-hour maximum, 12:00 UTC files, NOAA Open Data on "
                                        "AWS. History as of Oct 15, 2026. The newest day is added by a job that starts "
                                        "at 12:43 UTC and shows here on the next rebuild, usually within the hour.")
        self.assertIn("not a measurement at the ground and not an inspection", out["what_this_is"])
        self.assertIn("about 0.7 miles north to south and 0.5 miles east to west", out["what_this_is"])
        self.assertIn("6 am to 6 am Mountain daylight time", out["what_this_is"])
        self.assertIn("5 am to 5 am in winter", out["what_this_is"])

    def test_single_day_uses_the_singular(self):
        out = h.describe(self.index, [(date(2025, 6, 15), 513)], NOW)
        self.assertTrue(out["lead"].startswith("1 day with a radar-estimated hail size"), out["lead"])
        self.assertIn("Largest: 2.01 in (51.3 mm) on Jun 15, 2025.", out["lead"])

    def test_billings_four_days_from_the_town_coordinates(self):
        towns = json.loads((ROOT / "website" / "towns.json").read_text(encoding="utf-8"))
        billings = next(t for t in towns if t["slug"] == "billings")
        events = h.cell_events(FIXTURE, billings["lat"], billings["lon"])
        self.assertEqual(len(events), 4)
        out = h.describe(self.index, events, NOW)
        self.assertTrue(out["lead"].startswith("4 days with"), out["lead"])
        self.assertEqual(out["rows"][0]["iso"], "2025-07-28")
        self.assertEqual(out["rows"][0]["text"], "Jul 28, 2025: 0.32 in (8.3 mm), pea to mothball")
        self.assertIn("Largest: 0.62 in (16.0 mm) on Jul 24, 2022.", out["lead"])

    def test_empty_cell_says_not_the_same_as_no_hail(self):
        events = h.cell_events(FIXTURE, 45.755, -108.575)      # a Billings cell in the state with no events
        self.assertEqual(events, [])
        out = h.describe(self.index, events, NOW)
        self.assertEqual(out["lead"], "No day between Oct 16, 2021 and Oct 15, 2026 has a radar-estimated hail "
                                      "size of 0.25 in or more at this spot. That is not the same as no hail: "
                                      "radar estimates miss some hail, and 1 day has no data.")
        self.assertEqual(out["rows"], [])
        self.assertIsNone(out["class_title"])

    def test_empty_cell_plural_and_plain_leads(self):
        plural = copy.deepcopy(self.index)
        plural["missing_days"] = ["2022-06-09", "2022-06-10"]
        self.assertIn("and 2 days have no data.", h.describe(plural, [], NOW)["lead"])
        plain = copy.deepcopy(self.index)
        plain["missing_days"] = []
        out = h.describe(plain, [], NOW)
        self.assertNotIn("has no data", out["lead"])
        self.assertTrue(out["lead"].endswith("radar estimates miss some hail."), out["lead"])
        self.assertIsNone(out["missing"])

    def test_large_value_carries_the_note(self):
        out = h.describe(self.index, [(date(2024, 6, 5), 1041)], NOW)
        row = out["rows"][0]
        self.assertEqual(row["in"], "4.09")
        self.assertEqual(row["text"], "Jun 5, 2024: 4.09 in (104.1 mm), baseball or larger, severe size, "
                                      "unusually large for a radar estimate; treat with care")

    def test_the_four_inch_note_starts_at_1016_tenths(self):
        for tenths, noted in ((1015, False), (1016, True)):
            row = h.describe(self.index, [(date(2024, 6, 5), tenths)], NOW)["rows"][0]
            self.assertEqual(row["note"] is not None, noted, tenths)
            self.assertEqual("treat with care" in row["text"], noted, tenths)
        self.assertEqual(h.describe(self.index, [(date(2024, 6, 5), 1015)], NOW)["rows"][0]["in"], "3.99")

    def test_outside_montana(self):
        out = h.describe(self.index, None, NOW)
        self.assertEqual(out["state"], "outside")
        self.assertEqual(out["outside"], "Outside Montana. The history covers Montana only.")
        self.assertIsNone(out["lead"])
        self.assertEqual(out["rows"], [])

    def test_a_sample_build_does_not_call_a_spot_it_does_not_hold_outside_montana(self):
        out = h.describe(self.index, None, NOW, sample=True)
        self.assertEqual(out["state"], "outside")
        self.assertEqual(out["outside"], h.WORDS["sample_outside"])
        self.assertNotIn("Outside Montana", out["outside"])
        self.assertTrue(out["outside"].startswith("Not in the SAMPLE data"), out["outside"])
        assert_clean_words(self, out["outside"])

    def test_stale_line_after_three_days(self):
        old = copy.deepcopy(self.index)
        old["as_of"] = "2026-10-13"
        self.assertIsNotNone(h.describe(old, self.benchland, NOW)["stale"])
        self.assertIn("The newest day in this history is Oct 13, 2026; newer days have not been added yet.",
                      h.describe(old, self.benchland, NOW)["stale"])
        self.assertIsNone(h.describe(self.index, self.benchland, datetime(2026, 10, 18, tzinfo=UTC))["stale"])
        self.assertIsNotNone(h.describe(self.index, self.benchland, datetime(2026, 10, 19, tzinfo=UTC))["stale"])

    def test_unavailable_words(self):
        out = h.describe_unavailable("the history index file is missing")
        self.assertEqual(out["state"], "unavailable")
        self.assertEqual(out["unavailable"], "Hail history is unavailable: the history index file is missing. "
                                             "This is not the same as no hail.")

    def test_no_forbidden_term_in_any_rendered_text(self):
        texts = []
        for lat, lon in [BENCHLAND, (45.7833, -108.5007), (47.085, -110.045), (46.8721, -113.994),
                         h.cell_centre(796, 1993), h.cell_centre(793, 1997)]:
            texts.extend(strings_in(h.describe(self.index, h.cell_events(FIXTURE, lat, lon), NOW, sample=True)))
        texts.extend(strings_in(h.describe(self.index, None, NOW)))
        texts.extend(strings_in(h.describe_unavailable("the history index file is missing")))
        for text in texts:
            assert_clean_words(self, text)


class MapDataTests(unittest.TestCase):
    def test_keys_and_values(self):
        index = sample_index()
        block = h.map_data(index, sample=True)
        self.assertEqual(set(block), {"state", "as_of", "window", "d0", "missing_days", "grid", "shard", "tiles",
                                      "floor_tenths", "floor_in", "tenths_per_inch", "large_note_tenths",
                                      "classes", "words", "source", "problem"})
        self.assertEqual(block["state"], "sample")
        self.assertEqual(block["as_of"], "2026-10-15")
        self.assertEqual(block["window"], ["2021-10-16", "2026-10-15"])
        self.assertEqual(block["d0"], "2020-01-01")
        self.assertEqual(block["missing_days"], ["2022-06-08"])
        self.assertEqual(block["grid"], h.GRID)
        self.assertEqual(block["shard"], "hail/t/r{r}_c{c}.json")
        self.assertEqual(block["tiles"], ["r0079_c0198", "r0079_c0199", "r0092_c0214"])
        self.assertEqual(block["tenths_per_inch"], 254)
        self.assertEqual(block["floor_tenths"], 64)
        self.assertEqual(block["floor_in"], 0.25)
        self.assertEqual(block["large_note_tenths"], 1016)
        self.assertEqual(block["words"], h.WORDS)
        self.assertIsNone(block["problem"])
        self.assertEqual(len(block["classes"]), 6)
        self.assertEqual(block["classes"][2], {"min_tenths": 254, "max_tenths": 380, "min_in": 1.0,
                                               "max_in": 1.49, "word": "quarter to half dollar", "severe": True})
        json.dumps(block)                                 # plain JSON for map.json

    def test_loaded_state_is_not_the_sample_state(self):
        self.assertEqual(h.map_data(sample_index())["state"], "loaded")

    def test_unavailable_block(self):
        block = h.map_data_unavailable("the history index file is missing")
        self.assertEqual(block["state"], "unavailable")
        self.assertEqual(block["problem"], "the history index file is missing")
        self.assertIsNone(block["as_of"])
        self.assertEqual(block["tiles"], [])
        self.assertEqual(block["words"], h.WORDS)
        self.assertEqual(len(block["classes"]), 6)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hail-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def copy_fixture(self):
        dest = self.tmp / "store"
        shutil.copytree(FIXTURE, dest)
        return dest

    def test_load_index_reads_the_fixture(self):
        index = sample_index()
        self.assertEqual(index["format"], "hail-store-v1")
        self.assertIs(index["sample"], True)
        self.assertEqual(index["grid"], h.GRID)

    def test_missing_store_is_a_plain_problem(self):
        with self.assertRaises(h.HailStoreError) as ctx:
            h.load_index(self.tmp)
        self.assertEqual(str(ctx.exception), "the history index file is missing")

    def test_wrong_format_and_grid_are_refused(self):
        dest = self.copy_fixture()
        index_path = dest / "hail" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["format"] = "hail-store-v0"
        index_path.write_text(json.dumps(index), encoding="utf-8")
        with self.assertRaises(h.HailStoreError):
            h.load_index(dest)
        index["format"] = "hail-store-v1"
        index["grid"]["rows"] = 3000
        index_path.write_text(json.dumps(index), encoding="utf-8")
        with self.assertRaises(h.HailStoreError) as ctx:
            h.load_index(dest)
        self.assertIn("grid", str(ctx.exception))

    def test_cell_events_are_typed_and_sorted(self):
        events = h.cell_events(FIXTURE, *BENCHLAND)
        self.assertEqual([d for d, _t in events], sorted(d for d, _t in events))
        self.assertTrue(all(isinstance(d, date) and isinstance(t, int) for d, t in events))
        self.assertEqual(events[-1], (date(2026, 9, 6), 439))
        self.assertIn((date(2025, 6, 15), 185), events)

    def test_a_tile_the_store_does_not_list_reads_as_outside(self):
        self.assertIsNone(h.cell_events(FIXTURE, 46.8721, -113.994))     # Missoula: its tile is not in the sample
        self.assertIsNone(h.cell_events(FIXTURE, 80.0, 0.0))             # outside the grid
        self.assertEqual(h.cell_events(FIXTURE, 45.755, -108.575), [])   # in the state, no events: no estimate

    def test_a_shard_with_the_wrong_header_is_refused(self):
        dest = self.copy_fixture()
        shard = dest / h.shard_path(*h.cell_for(*BENCHLAND))
        doc = json.loads(shard.read_text(encoding="utf-8"))
        doc["r"] = 80
        shard.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(h.HailStoreError):
            h.cell_events(dest, *BENCHLAND)

    def test_manifest_passes_on_the_fixture(self):
        # the B2 layout: B1's shards and index, and the joins' j/, s/ and z/ files (the fire zone files of the sample's
        # tiles included). A manifest does not list itself, so hail/manifest.json is not in this list.
        manifest = h.check_manifest(FIXTURE)
        self.assertEqual(sorted(manifest["files"]), [
            "hail/index.json", "hail/j/e/r0079_c0198.json", "hail/j/e/r0079_c0199.json", "hail/j/e/r0092_c0214.json",
            "hail/j/events.json", "hail/j/r0079_c0198.json", "hail/j/r0079_c0199.json",
            "hail/j/r0092_c0214.json", "hail/j/towns.json", "hail/k/MTC045.json", "hail/k/MTC111.json", "hail/s/1LM.json",
            "hail/s/6S8.json",
            "hail/s/BIL.json", "hail/s/LWT.json", "hail/t/r0079_c0198.json", "hail/t/r0079_c0199.json",
            "hail/t/r0092_c0214.json", "hail/z/MTZ235.json", "hail/z/MTZ313.json", "hail/z/fire-MTZ117.json",
            "hail/z/fire-MTZ128.json"])

    def test_manifest_catches_a_changed_shard(self):
        dest = self.copy_fixture()
        shard = dest / "hail" / "t" / "r0079_c0199.json"
        shard.write_text(shard.read_text(encoding="utf-8").replace(",185]", ",186]"), encoding="utf-8")
        with self.assertRaises(h.HailStoreError) as ctx:
            h.check_manifest(dest)
        self.assertIn("does not match the manifest", str(ctx.exception))

    def test_manifest_catches_an_unlisted_file(self):
        dest = self.copy_fixture()
        (dest / "hail" / "t" / "r0001_c0001.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(h.HailStoreError) as ctx:
            h.check_manifest(dest)
        self.assertIn("does not list", str(ctx.exception))

    def test_manifest_catches_a_non_json_file(self):
        dest = self.copy_fixture()
        (dest / "hail" / "t" / "evil.sh").write_text("echo hi\n", encoding="utf-8")
        with self.assertRaises(h.HailStoreError) as ctx:
            h.check_manifest(dest)
        self.assertIn("does not list", str(ctx.exception))

    def test_manifest_catches_stray_text_and_compressed_files(self):
        for name in ("stray.txt", "stray.json.gz"):
            dest = self.tmp / f"copy-{name}"
            shutil.copytree(FIXTURE, dest)
            (dest / "hail" / "t" / name).write_bytes(b"x")
            with self.assertRaises(h.HailStoreError) as ctx:
                h.check_manifest(dest)
            self.assertIn("does not list", str(ctx.exception), name)

    def test_manifest_catches_an_unlisted_html_file(self):
        dest = self.copy_fixture()
        (dest / "hail" / "evil.html").write_text("<script>alert(1)</script>", encoding="utf-8")
        with self.assertRaises(h.HailStoreError) as ctx:
            h.check_manifest(dest)
        self.assertIn("does not list", str(ctx.exception))

    def test_manifest_catches_a_linked_directory(self):
        dest = self.copy_fixture()
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "notes.html").write_text("<p>x</p>", encoding="utf-8")
        os.symlink(outside, dest / "hail" / "linked", target_is_directory=True)
        with self.assertRaises(h.HailStoreError) as ctx:
            h.check_manifest(dest)
        self.assertIn("link, which is not allowed", str(ctx.exception))

    def test_manifest_catches_a_dangling_link_named_like_a_shard(self):
        dest = self.copy_fixture()
        os.symlink(self.tmp / "missing.json", dest / "hail" / "t" / "r0001_c0001.json")
        with self.assertRaises(h.HailStoreError) as ctx:
            h.check_manifest(dest)
        self.assertIn("link, which is not allowed", str(ctx.exception))

    def test_a_hail_folder_that_is_a_file_is_a_plain_problem(self):
        dest = self.tmp / "bad"
        dest.mkdir()
        (dest / "hail").write_text("not a folder", encoding="utf-8")
        with self.assertRaises(h.HailStoreError) as ctx:
            h.check_manifest(dest)
        self.assertEqual(str(ctx.exception), "the history file manifest.json could not be read")

    def test_a_shard_value_that_is_not_a_whole_number_is_refused(self):
        dest = self.copy_fixture()
        shard = dest / "hail" / "t" / "r0079_c0199.json"
        doc = json.loads(shard.read_text(encoding="utf-8"))
        day_1992 = h.day_index(date(2025, 6, 15))
        for row in doc["cells"][str(h.cell_key(792, 1998))]:
            if row[0] == day_1992:
                row[1] = 185.7
        data = h._compact(doc)
        shard.write_bytes(data)
        manifest_path = dest / "hail" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["hail/t/r0079_c0199.json"] = {"bytes": len(data),
                                                        "sha256": hashlib.sha256(data).hexdigest()}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(h.HailStoreError) as ctx:
            h.verify(dest)
        self.assertIn("not a whole number", str(ctx.exception))

    def test_a_manifest_in_the_wrong_format_is_refused(self):
        store = self.copy_fixture()
        path = store / "hail" / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["format"] = "hail-manifest-v0"
        path.write_bytes(h._pretty(manifest))
        with self.assertRaises(h.HailStoreError) as ctx:
            h.check_manifest(store)
        self.assertEqual(str(ctx.exception), "the history manifest is not in the expected format")

    def test_a_listed_file_that_is_missing_is_refused(self):
        store = self.copy_fixture()
        (store / "hail" / "t" / "r0092_c0214.json").unlink()          # a copy this test made
        with self.assertRaises(h.HailStoreError) as ctx:
            h.check_manifest(store)
        self.assertEqual(str(ctx.exception), "the history file hail/t/r0092_c0214.json is missing")

    def test_manifest_catches_a_count_mismatch(self):
        dest = self.copy_fixture()
        manifest_path = dest / "hail" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["counts"]["events"] = manifest["counts"]["events"] + 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(h.HailStoreError):
            h.check_manifest(dest)

    def test_load_index_refuses_an_index_without_tiles(self):
        dest = self.copy_fixture()
        index_path = dest / "hail" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        del index["tiles"]
        index_path.write_text(json.dumps(index), encoding="utf-8")
        with self.assertRaises(h.HailStoreError) as ctx:
            h.load_index(dest)
        self.assertEqual(str(ctx.exception), "the history index has no tiles")


class FixtureTests(unittest.TestCase):
    def test_fixture_is_under_50_kb_and_holds_only_the_store_and_joins_files(self):
        files = sorted(p.relative_to(FIXTURE).as_posix() for p in FIXTURE.rglob("*") if p.is_file())
        self.assertEqual(files, [
            "hail/index.json", "hail/j/e/r0079_c0198.json", "hail/j/e/r0079_c0199.json", "hail/j/e/r0092_c0214.json",
            "hail/j/events.json", "hail/j/r0079_c0198.json", "hail/j/r0079_c0199.json",
            "hail/j/r0092_c0214.json", "hail/j/towns.json", "hail/k/MTC045.json", "hail/k/MTC111.json",
            "hail/manifest.json",
            "hail/s/1LM.json", "hail/s/6S8.json", "hail/s/BIL.json", "hail/s/LWT.json", "hail/t/r0079_c0198.json",
            "hail/t/r0079_c0199.json", "hail/t/r0092_c0214.json", "hail/z/MTZ235.json", "hail/z/MTZ313.json",
            "hail/z/fire-MTZ117.json", "hail/z/fire-MTZ128.json"])
        total = sum(p.stat().st_size for p in FIXTURE.rglob("*") if p.is_file())
        self.assertLess(total, 50_000)

    def test_fixture_is_the_current_output_of_fixture_store(self):
        # The joins layer and its manifest come from the joins build (tests/test_joins.py checks them), so this compares
        # the B1 part: the shards byte for byte, and the index and manifest without the joins block. It writes into a
        # folder this test made, never into the committed fixture.
        tmp = Path(tempfile.mkdtemp(prefix="hail-fixture-"))
        try:
            h.fixture_store(tmp)
            for path in (tmp / "hail" / "t").rglob("*.json"):
                rel = path.relative_to(tmp)
                self.assertEqual(path.read_bytes(), (FIXTURE / rel).read_bytes(), str(rel))
            generated = json.loads((tmp / "hail" / "index.json").read_text(encoding="utf-8"))
            committed = json.loads((FIXTURE / "hail" / "index.json").read_text(encoding="utf-8"))
            committed.pop("joins")
            self.assertEqual(committed, generated)
            generated = json.loads((tmp / "hail" / "manifest.json").read_text(encoding="utf-8"))
            committed = json.loads((FIXTURE / "hail" / "manifest.json").read_text(encoding="utf-8"))
            committed.pop("joins")
            for doc in (generated, committed):      # the index's own entry hashes the index with its joins block
                doc["files"] = {k: v for k, v in doc["files"].items() if k.startswith("hail/t/")}
            self.assertEqual(committed, generated)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fixture_counts_and_labels(self):
        index = sample_index()
        self.assertEqual(index["events"], 1575)
        self.assertEqual(index["shards"], 3)
        self.assertEqual(index["days_expected"], 1826)
        self.assertEqual(index["days_present"], 1825)
        self.assertEqual(index["window"], ["2021-10-16", "2026-10-15"])
        self.assertEqual(index["as_of"], "2026-10-15")
        self.assertEqual(index["tiles"], ["r0079_c0198", "r0079_c0199", "r0092_c0214"])
        self.assertEqual(index["bytes"], sum((FIXTURE / "hail" / "t" / f"{name}.json").stat().st_size
                                             for name in index["tiles"]))
        self.assertIs(h.check_manifest(FIXTURE)["sample"], True)
        self.assertEqual(index["floor_tenths"], h.FLOOR_TENTHS)

    def test_fixture_shard_contents(self):
        start, end = h.window_for(date(2026, 10, 15))
        seen_events = 0
        for path in sorted((FIXTURE / "hail" / "t").glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((doc["f"], doc["d0"], doc["u"]), ("hail-cells-v1", "2020-01-01", "tenths of a mm"))
            self.assertEqual(path.name, f"r{doc['r']:04d}_c{doc['c']:04d}.json")
            self.assertEqual(list(doc), ["f", "r", "c", "d0", "u", "state", "cells"])
            self.assertEqual(doc["state"], list(range(100)))          # the three tiles lie inside Montana
            for key, rows in doc["cells"].items():
                self.assertIn(int(key), doc["state"])
                days = [d for d, _t in rows]
                self.assertEqual(days, sorted(days))
                for day, tenths in rows:
                    seen_events += 1
                    self.assertIsInstance(tenths, int)
                    self.assertGreaterEqual(tenths, h.FLOOR_TENTHS)
                    self.assertTrue(start <= h.day_of_index(day) <= end)
        self.assertEqual(seen_events, 1575)

    def test_fixture_benchland_day_is_2025_06_15_at_185(self):
        self.assertIn((date(2025, 6, 15), 185), h.cell_events(FIXTURE, *BENCHLAND))

    def test_fixture_holds_the_check_value_at_the_check_cell(self):
        self.assertIn((date(2025, 6, 15), 513), h.cell_events(FIXTURE, *h.GATE_POINT))

    def test_fixture_has_no_em_dash(self):
        for path in FIXTURE.rglob("*.json"):
            self.assertNotIn("\u2014", path.read_text(encoding="utf-8"))

    def test_the_sample_events_module_holds_data_only(self):
        from website import hail_fixture_data as data
        names = sorted(name for name in vars(data) if not name.startswith("__"))
        self.assertEqual(names, ["SAMPLE_EVENTS"])          # no functions or classes: data only
        self.assertIsInstance(data.SAMPLE_EVENTS, tuple)
        for row, col, days in data.SAMPLE_EVENTS:
            self.assertEqual((type(row), type(col)), (int, int))
            self.assertTrue(days)
            for iso, tenths in days:
                self.assertEqual((type(iso), type(tenths)), (str, int))
                self.assertGreaterEqual(tenths, h.FLOOR_TENTHS)

    def test_a_normal_import_never_loads_the_sample_events(self):
        code = "import sys, website.hail, website.build; print('website.hail_fixture_data' in sys.modules)"
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(done.stdout.strip(), "False")


class ApiTests(unittest.TestCase):
    def test_constants_and_names(self):
        self.assertEqual(h.FLOOR_TENTHS, 64)
        self.assertEqual(h.D0, date(2020, 1, 1))
        self.assertEqual(h.TILE, 10)
        self.assertTrue(h.STORE_URL.endswith("/releases/download/hail-store/hail-store.tar.gz"))
        self.assertTrue(issubclass(h.HailStoreError, Exception))
        for name in ("cell_for", "cell_centre", "shard_path", "tile_name", "cell_key", "day_index", "day_of_index",
                     "inches", "class_for", "fetch_store", "load_index", "cell_events", "describe", "map_data",
                     "fixture_store", "build", "verify", "compare", "load_store"):
            self.assertTrue(callable(getattr(h, name)), name)

    def test_signatures(self):
        params = {name: list(inspect.signature(getattr(h, name)).parameters)
                  for name in ("cell_for", "cell_centre", "shard_path", "cell_key", "day_index", "inches",
                               "class_for", "fetch_store", "load_index", "cell_events", "describe",
                               "map_data", "fixture_store", "load_store")}
        self.assertEqual(params["cell_for"], ["lat", "lon"])
        self.assertEqual(params["cell_centre"], ["row", "col"])
        self.assertEqual(params["shard_path"], ["row", "col"])
        self.assertEqual(params["cell_key"], ["row", "col"])
        self.assertEqual(params["fetch_store"], ["get", "dest_dir", "url"])
        self.assertEqual(params["load_index"], ["store_dir"])
        self.assertEqual(params["cell_events"], ["store_dir", "lat", "lon", "index"])
        self.assertEqual(params["describe"], ["index", "events", "now", "sample"])
        self.assertEqual(params["map_data"], ["index", "sample"])
        self.assertEqual(params["fixture_store"], ["dest_dir"])
        self.assertEqual(params["load_store"], ["path", "dest_dir"])
        self.assertEqual(inspect.signature(h.describe).parameters["sample"].default, False)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = h.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_fixture_command_writes_the_store(self):
        tmp = Path(tempfile.mkdtemp(prefix="hail-cli-"))
        try:
            code, out, _err = self.run_cli(["fixture", "--out", str(tmp)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["events"], 1575)
            self.assertTrue((tmp / "hail" / "index.json").is_file())
            self.assertTrue((tmp / "hail" / "manifest.json").is_file())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_bad_date_is_an_argument_error(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                h.main(["build", "--start", "2025-13-01"])


# ---------------------------------------------------------------- the store builder (offline)

def has_pyarrow() -> bool:
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        return False
    return True


def grib_bytes(values, pad: int = 0) -> bytes:
    """A fake GRIB2 file: values maps mesh cell index to tenths of a mm (or a code such as -3), in a gzip."""
    body = json.dumps({"v": {str(k): v for k, v in values.items()}, "pad": "x" * pad}, sort_keys=True)
    return gzip.compress(b"GRIB" + body.encode("ascii") + b"7777", mtime=0)


def fake_decode(path, mesh):
    """Stands in for the GRIB reader: the mesh's values in mask order, as mm, with -1 everywhere else."""
    doc = json.loads(gzip.decompress(Path(path).read_bytes())[4:-4].decode("ascii"))
    out = np.full(mesh.n, -1.0)
    for key, value in doc["v"].items():
        out[int(key)] = float(value) / 10.0 if value >= 0 else float(value)
    return out


class FakeHttp:
    """Stands in for the builder's HTTP. copies maps a full URL to the bytes it serves (absent means 404).
    heads_fail lists URLs whose HEAD fails with a network error."""

    def __init__(self, copies, heads_fail=()):
        self.copies = dict(copies)
        self.heads_fail = set(heads_fail)
        self.downloads = 0

    def head(self, url):
        if url in self.heads_fail:
            return {"status": None, "bytes": None, "etag": None, "last_modified": None, "error": "ConnectionError"}
        data = self.copies.get(url)
        if data is None:
            return {"status": 404, "bytes": None, "etag": None, "last_modified": None, "error": None}
        return {"status": 200, "bytes": len(data), "etag": '"fake"', "last_modified": "Sat, 17 Oct 2026 12:08:17 GMT",
                "error": None}

    def download(self, url, dest, expect_bytes=None):
        data = self.copies.get(url)
        if data is None:
            return {"status": 404, "bytes": None, "sha256": None, "etag": None, "last_modified": None, "error": None}
        if expect_bytes is not None and len(data) != expect_bytes:
            return {"status": None, "bytes": None, "sha256": None, "etag": None, "last_modified": None,
                    "error": "size changed"}
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(data)
        self.downloads += 1
        return {"status": 200, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "etag": '"fake"',
                "last_modified": "Sat, 17 Oct 2026 12:08:17 GMT", "error": None}

    def list_keys(self, prefix):
        keys = []
        for url in self.copies:
            if url.startswith(h.BUCKET + "/") and url[len(h.BUCKET) + 1:].startswith(prefix):
                keys.append(url[len(h.BUCKET) + 1:])
        return sorted(keys)


def scenario_copies(a: int, b: int, c: int) -> dict:
    """Eight SPC days, 2021-10-17 to 2021-10-24, that cover every copy decision (see BuildTests)."""
    copies = {}

    def bucket(day, values, pad=0):
        copies[h.bucket_url(day + timedelta(days=1))] = grib_bytes(values, pad)

    def iem(day, values, pad=0):
        copies[h.iem_url(day + timedelta(days=1))] = grib_bytes(values, pad)

    bucket(date(2021, 10, 17), {a: 185, b: -3})                       # skipped: IEM has no copy (HTTP 404)
    bucket(date(2021, 10, 19), {a: 300})                              # same: both copies, same bytes
    iem(date(2021, 10, 19), {a: 300})
    bucket(date(2021, 10, 20), {a: 999})                              # rederive: the copies differ in size
    iem(date(2021, 10, 20), {a: 300}, pad=100)
    iem(date(2021, 10, 21), {c: 120})                                 # iem: the bucket has no file
    bucket(date(2021, 10, 22), {a: 64})                               # same, exactly at the 0.25 in floor
    iem(date(2021, 10, 22), {a: 64})
    bucket(date(2021, 10, 23), {a: 63, b: 30})                        # skipped, both below the floor
    frames = [("20211020", "130037", {a: 250}), ("20211020", "140037", {a: 310}),
              ("20211021", "000040", {b: 100}), ("20211021", "120000", {c: 999})]   # the last is outside the day
    for folder, clock, values in frames:
        copies[f"{h.BUCKET}/CONUS/MESH_00.50/{folder}/MRMS_MESH_00.50_{folder}-{clock}.grib2.gz"] = grib_bytes(values)
    return copies


class CopyRuleTests(unittest.TestCase):
    def test_every_decision(self):
        self.assertEqual(h.copy_decision(100, 100), "same")
        self.assertEqual(h.copy_decision(100, 101), "rederive")
        self.assertEqual(h.copy_decision(100, None), "skipped")
        self.assertEqual(h.copy_decision(None, 100), "iem")
        self.assertEqual(h.copy_decision(None, None), "missing")

    def test_sizes_are_compared_as_numbers_of_bytes(self):
        self.assertEqual(h.copy_decision(1637004, 1580844), "rederive")     # 2025-06-26's two copies
        self.assertEqual(h.copy_decision(1404818, 1404818), "same")
        self.assertEqual(h.copy_decision(10, 9), "rederive")

    def test_the_skipped_sentence_names_what_iem_said(self):
        self.assertIsNone(h._skipped_words({}, []))
        one = {date(2021, 10, 17): {"iem_status": 404}}
        self.assertEqual(h._skipped_words(one, [date(2021, 10, 17)]),
                         "IEM has no copy of 1 day (HTTP 404), on 2021-10-17; that day uses the bucket copy")
        mixed = {date(2021, 10, 17): {"iem_status": None}, date(2021, 10, 18): {"iem_status": 404}}
        self.assertEqual(h._skipped_words(mixed, [date(2021, 10, 17), date(2021, 10, 18)]),
                         "IEM has no copy or did not answer for 2 days, from 2021-10-17 to 2021-10-18; "
                         "those days use the bucket copy")


class FileNameTests(unittest.TestCase):
    def test_bucket_and_iem_names(self):
        stamp = date(2025, 6, 16)
        self.assertEqual(h.bucket_name(stamp), "MRMS_MESH_Max_1440min_00.50_20250616-120000.grib2.gz")
        self.assertEqual(h.bucket_url(stamp), "https://noaa-mrms-pds.s3.amazonaws.com/CONUS/MESH_Max_1440min_00.50/"
                                              "20250616/MRMS_MESH_Max_1440min_00.50_20250616-120000.grib2.gz")
        self.assertEqual(h.iem_url(stamp), "https://mtarchive.geol.iastate.edu/2025/06/16/mrms/ncep/"
                                           "MESH_Max_1440min/MESH_Max_1440min_00.50_20250616-120000.grib2.gz")

    def test_frame_and_stamp_name_patterns(self):
        self.assertIsNotNone(h.FRAME_NAME.fullmatch("MRMS_MESH_00.50_20250625-120037.grib2.gz"))
        self.assertIsNone(h.FRAME_NAME.fullmatch("MRMS_MESH_Max_1440min_00.50_20250625-120000.grib2.gz"))
        found = h.STAMP_NAME.fullmatch("MRMS_MESH_Max_1440min_00.50_20250616-120000.grib2.gz")
        self.assertEqual(found.group(1), "20250616")
        self.assertIsNone(h.STAMP_NAME.fullmatch("MRMS_MESH_Max_1440min_00.50_20250616-000000.grib2.gz"))


class PackTests(unittest.TestCase):
    """The prototype's cases (test_mesh_history.py) and the rounding rule, on numpy arrays."""

    def test_codes_and_nan_are_no_data(self):
        raw = np.array([-1.0, -3.0, -999.0, np.nan, 0.0, 0.1, 35.7, 98.7])
        tenths, st = h.pack_tenths(raw)
        self.assertEqual(tenths.tolist(), [0, 0, 0, 0, 0, 1, 357, 987])
        self.assertEqual((st["n_minus1"], st["n_minus3"], st["n_other_neg"], st["n_nan"], st["n_zero"], st["n_pos"]),
                         (1, 1, 1, 1, 1, 3))
        self.assertEqual(st["max_mm"], 98.7)
        self.assertEqual(st["n_ge_floor"], 2)

    def test_negative_codes_never_become_values(self):
        tenths, _ = h.pack_tenths(np.array([-1.0] * 5 + [-3.0] * 5))
        self.assertFalse(tenths.any())

    def test_values_above_uint16_raise_and_are_not_clamped(self):
        with self.assertRaises(ValueError):
            h.pack_tenths(np.array([6600.0]))
        tenths, _ = h.pack_tenths(np.array([6553.5]))
        self.assertEqual(int(tenths[0]), 65535)

    def test_positive_values_off_the_tenth_grid_are_counted(self):
        tenths, st = h.pack_tenths(np.array([0.04, 5.0]))
        self.assertEqual(st["n_pos_lost"], 1)
        self.assertEqual(tenths.tolist(), [0, 50])

    def test_six_point_three_five_mm_is_at_the_floor(self):
        tenths, st = h.pack_tenths(np.array([6.35, 6.34, 6.36]))
        self.assertEqual(tenths.tolist(), [64, 63, 64])          # 6.35 mm is 63.5 tenths; the half goes to 64
        self.assertEqual(st["n_ge_floor"], 2)
        self.assertEqual(h.FLOOR_TENTHS, 64)

    def test_rounding_is_to_the_nearest_tenth_and_halves_go_to_the_even_tenth(self):
        tenths, _ = h.pack_tenths(np.array([35.74, 35.76, 2.25, 2.75, 1.25]))
        self.assertEqual(tenths.tolist(), [357, 358, 22, 28, 12])


class MeshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mesh = h.montana_mesh()

    def test_state_cell_count_and_frame_box(self):
        self.assertEqual(self.mesh.n, h.CELLS_IN_STATE)
        self.assertEqual(self.mesh.n, 450765)
        self.assertEqual(h._frame_box(), (450, 750, 1150, 1750))
        self.assertEqual(self.mesh.mask.shape, (750, 1750))

    def test_cells_are_in_row_major_order(self):
        key = self.mesh.rows * h.COLS + self.mesh.cols
        self.assertTrue(np.all(np.diff(key) > 0))

    def test_mesh_cells_match_the_grid_helpers_and_lie_in_montana(self):
        rng = random.Random(11)
        picks = [0, 1, 500, 12345, self.mesh.n - 1] + [rng.randrange(self.mesh.n) for _ in range(200)]
        for i in picks:
            r, c = int(self.mesh.rows[i]), int(self.mesh.cols[i])
            self.assertEqual(h.cell_for(*h.cell_centre(r, c)), (r, c))
            lat, lon = h.cell_centre(r, c)
            self.assertTrue(44.0 < lat < 49.5 and -117.0 < lon < -103.5, (lat, lon))

    def test_benchland_cell_is_one_mesh_cell(self):
        row, col = h.cell_for(*BENCHLAND)
        self.assertEqual(int(np.count_nonzero((self.mesh.rows == row) & (self.mesh.cols == col))), 1)

    def test_montana_outline_is_the_prototype_outline(self):
        # The mask comes from the Montana ring in basemap.json, not from the whole file: the base map is rebuilt
        # when towns or labels change (D31), and the store must not change with it. The ring is the prototype's
        # (212 vertices; its hash is the same in the base map before and after the towns rebuild).
        ring = h._montana_ring(h.BASEMAP)
        self.assertEqual(len(ring), 212)
        self.assertEqual(hashlib.sha256(json.dumps(ring).encode()).hexdigest(), "2211a6037c1fc52eb973249070a9d48191d6d9a5e76a850253468a66ff7d83f4")


class GribCheckTests(unittest.TestCase):
    def test_accepts_one_message_and_rejects_the_rest(self):
        tmp = Path(tempfile.mkdtemp(prefix="hail-grib-"))
        try:
            good = tmp / "good.grib2.gz"
            good.write_bytes(gzip.compress(b"GRIB" + b"x" * 100 + b"7777"))
            self.assertTrue(h._gz_is_grib(good)[0])
            plain = tmp / "plain.gz"
            plain.write_bytes(b"not gzip at all")
            self.assertEqual(h._gz_is_grib(plain), (False, "no gzip magic"))
            wrong = tmp / "wrong.gz"
            wrong.write_bytes(gzip.compress(b"HTML" + b"x" * 10))
            self.assertFalse(h._gz_is_grib(wrong)[0])
            data = gzip.compress(b"GRIB" + b"y" * 5000 + b"7777")
            cut = tmp / "cut.gz"
            cut.write_bytes(data[: len(data) // 2])
            self.assertFalse(h._gz_is_grib(cut)[0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ListingTests(unittest.TestCase):
    """The daily listing and the frame window, with a fake HTTP client (no network)."""

    def test_newest_stamp_is_the_newest_listed_12z_file(self):
        copies = {h.bucket_url(date(2026, 10, 16)): b"x", h.bucket_url(date(2026, 10, 17)): b"y"}
        self.assertEqual(h.newest_stamp(FakeHttp(copies), date(2026, 10, 18)), date(2026, 10, 17))
        self.assertEqual(h.newest_stamp(FakeHttp(copies), date(2026, 10, 17)), date(2026, 10, 17))

    def test_newest_stamp_refuses_an_empty_listing(self):
        with self.assertRaises(h.HailStoreError) as ctx:
            h.newest_stamp(FakeHttp({}), date(2026, 10, 18))
        self.assertIn("lists no 12:00 UTC file", str(ctx.exception))

    def test_frames_are_the_12z_to_12z_window_sorted_by_time(self):
        copies = {}
        for folder, clock in [("20211020", "115800"), ("20211020", "120037"), ("20211020", "235843"),
                              ("20211021", "000040"), ("20211021", "115843"), ("20211021", "120000")]:
            copies[f"{h.BUCKET}/CONUS/MESH_00.50/{folder}/MRMS_MESH_00.50_{folder}-{clock}.grib2.gz"] = b"x"
        found = h._frames_for_day(FakeHttp(copies), date(2021, 10, 20))
        self.assertEqual([when.strftime("%Y%m%d-%H%M%S") for when, _key in found],
                         ["20211020-120037", "20211020-235843", "20211021-000040", "20211021-115843"])


class BuildTests(unittest.TestCase):
    """The store builder end to end on eight fake days (no network, no GRIB reader): every copy decision, the
    missing days, the shards, the index, the manifest, the ledger, the cache and byte-identical reruns."""

    @classmethod
    def setUpClass(cls):
        cls.mesh = scenario_mesh()
        cls.a = cls.index_of(792, 1998)     # Benchland
        cls.b = cls.index_of(796, 1993)
        cls.c = cls.index_of(921, 2149)     # Billings

    @classmethod
    def index_of(cls, row, col):
        hits = np.flatnonzero((cls.mesh.rows == row) & (cls.mesh.cols == col))
        assert hits.size == 1, (row, col)
        return int(hits[0])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hail-build-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_build(self, out, cache, copies, max_missing=5, heads_fail=()):
        http = FakeHttp(copies, heads_fail=heads_fail)
        with mock.patch.object(h, "MIN_FRAMES", 3):
            index = h._run_build(out, date(2021, 10, 17), date(2021, 10, 24), http, cache, 0, self.mesh,
                                 decode=fake_decode, max_missing=max_missing)
        return index, http

    def test_index_for_the_eight_day_scenario(self):
        index, _http = self.run_build(self.tmp / "store", self.tmp / "cache", scenario_copies(self.a, self.b, self.c))
        montana_tiles = [h.tile_name(r, c) for r, c, _keys in h._tile_states(self.mesh)]
        self.assertEqual(index["format"], "hail-store-v1")
        self.assertEqual(index["window"], ["2021-10-17", "2021-10-24"])
        self.assertEqual(index["as_of"], "2021-10-24")
        self.assertEqual(index["missing_days"], ["2021-10-18", "2021-10-24"])
        self.assertEqual((index["days_expected"], index["days_present"]), (8, 6))
        self.assertEqual(index["events"], 6)
        self.assertEqual(index["shards"], len(montana_tiles))       # a shard for every tile with a Montana cell
        self.assertEqual(index["tiles"], montana_tiles)
        self.assertIn("r0079_c0199", index["tiles"])
        self.assertEqual(index["cells_in_state"], self.mesh.n)
        self.assertLess(self.mesh.n, h.CELLS_IN_STATE)              # the scenario box, not the whole state
        self.assertEqual(index["grid"], h.GRID)
        self.assertNotIn("sample", index)
        cc = index["copy_check"]
        self.assertEqual(cc["days_checked"], 3)
        self.assertEqual(cc["days_differed"], ["2021-10-20"])
        self.assertEqual(cc["rederived"], ["2021-10-20"])
        self.assertEqual(cc["frames"], {"2021-10-20": 3})
        self.assertEqual(cc["coverage"], {"2021-10-20": {"listed": 3, "near_duplicate_pairs": 0, "distinct_slots": 3,
                                                         "largest_gap_s": 36003}})
        self.assertEqual(cc["partial"], [{"day": "2021-10-20", "frames": 3, "expected": 720}])
        self.assertEqual(cc["skipped"], "IEM has no copy of 2 days (HTTP 404), from 2021-10-17 to 2021-10-23; "
                                        "those days use the bucket copy")

    def test_a_failed_iem_request_is_not_reported_as_a_404(self):
        heads_fail = {h.iem_url(date(2021, 10, 18))}          # the IEM request for 2021-10-17 fails on the network
        index, _http = self.run_build(self.tmp / "store", self.tmp / "cache", scenario_copies(self.a, self.b, self.c),
                                      heads_fail=heads_fail)
        self.assertEqual(index["copy_check"]["skipped"],
                         "IEM has no copy or did not answer for 2 days, from 2021-10-17 to 2021-10-23; "
                         "those days use the bucket copy")

    def test_shards_hold_the_events_sorted_by_day(self):
        self.run_build(self.tmp / "store", self.tmp / "cache", scenario_copies(self.a, self.b, self.c))
        t = self.tmp / "store" / "hail" / "t"
        states = {(r, c): keys for r, c, keys in h._tile_states(self.mesh)}
        self.assertEqual(len(list(t.iterdir())), len(states))
        doc = json.loads((t / "r0079_c0199.json").read_text(encoding="utf-8"))
        self.assertEqual((doc["f"], doc["r"], doc["c"], doc["d0"], doc["u"]),
                         ("hail-cells-v1", 79, 199, "2020-01-01", "tenths of a mm"))
        self.assertEqual(list(doc), ["f", "r", "c", "d0", "u", "state", "cells"])          # the field order of D34
        self.assertEqual(doc["state"], states[(79, 199)])
        d = date.fromisoformat
        self.assertEqual(doc["cells"][str(h.cell_key(792, 1998))],
                         [[h.day_index(d("2021-10-17")), 185], [h.day_index(d("2021-10-19")), 300],
                          [h.day_index(d("2021-10-20")), 310], [h.day_index(d("2021-10-22")), 64]])
        self.assertEqual(doc["cells"][str(h.cell_key(796, 1993))], [[h.day_index(d("2021-10-20")), 100]])
        billings = json.loads((t / "r0092_c0214.json").read_text(encoding="utf-8"))
        self.assertEqual(billings["cells"][str(h.cell_key(921, 2149))], [[h.day_index(d("2021-10-21")), 120]])

    def test_a_tile_without_events_still_has_a_shard_with_its_state(self):
        self.run_build(self.tmp / "store", self.tmp / "cache", scenario_copies(self.a, self.b, self.c))
        with_events = {(79, 199), (92, 214)}                  # the tiles of Benchland and Billings
        r, c, keys = next(tile for tile in h._tile_states(self.mesh) if (tile[0], tile[1]) not in with_events)
        doc = json.loads((self.tmp / "store" / h.shard_path(r * h.TILE, c * h.TILE)).read_text(encoding="utf-8"))
        self.assertEqual(doc["cells"], {})
        self.assertEqual(doc["state"], keys)

    def test_manifest_hashes_and_counts_verify(self):
        out = self.tmp / "store"
        index, _http = self.run_build(out, self.tmp / "cache", scenario_copies(self.a, self.b, self.c))
        manifest = h.check_manifest(out)
        tiles = [h.tile_name(r, c) for r, c, _keys in h._tile_states(self.mesh)]
        self.assertEqual(sorted(manifest["files"]),
                         sorted(["hail/index.json"] + [f"hail/t/{name}.json" for name in tiles]))
        self.assertEqual(manifest["counts"]["events"], index["events"])
        report = h.verify(out)
        self.assertTrue(report["ok"])
        self.assertEqual(report["events"], 6)
        self.assertEqual(report["shards"], len(tiles))
        self.assertEqual(report["tiles"], len(tiles))
        self.assertEqual(report["state_cells"], self.mesh.n)
        self.assertIsNone(report["benchland"]["tenths"])          # no 2025 day in this window

    def test_a_changed_shard_fails_verification(self):
        out = self.tmp / "store"
        self.run_build(out, self.tmp / "cache", scenario_copies(self.a, self.b, self.c))
        shard = out / "hail" / "t" / "r0079_c0199.json"
        shard.write_text(shard.read_text(encoding="utf-8").replace("310", "311"), encoding="utf-8")
        with self.assertRaises(h.HailStoreError) as ctx:
            h.verify(out)
        self.assertIn("does not match the manifest", str(ctx.exception))

    def test_missing_days_write_no_values(self):
        out = self.tmp / "store"
        self.run_build(out, self.tmp / "cache", scenario_copies(self.a, self.b, self.c))
        for doc_path in (out / "hail" / "t").glob("*.json"):
            doc = json.loads(doc_path.read_text(encoding="utf-8"))
            for rows in doc["cells"].values():
                days = [h.day_of_index(d) for d, _t in rows]
                self.assertNotIn(date(2021, 10, 18), days)
                self.assertNotIn(date(2021, 10, 24), days)

    def test_too_many_missing_days_stops_the_build(self):
        out = self.tmp / "store"
        with self.assertRaises(h.HailStoreError) as ctx:
            self.run_build(out, self.tmp / "cache", scenario_copies(self.a, self.b, self.c), max_missing=1)
        self.assertIn("2 days have no file", str(ctx.exception))
        self.assertFalse((out / "hail").exists())

    def test_ledger_and_run_record_are_written_outside_hail(self):
        out = self.tmp / "store"
        self.run_build(out, self.tmp / "cache", scenario_copies(self.a, self.b, self.c))
        lines = (out / "ledger" / "fetch.jsonl").read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines]
        self.assertEqual([r["spc_day"] for r in records], [d.isoformat() for d in
                                                           h._day_range(date(2021, 10, 17), date(2021, 10, 24))])
        by_day = {r["spc_day"]: r for r in records}
        self.assertEqual(by_day["2021-10-17"]["decision"], "skipped")
        self.assertEqual(by_day["2021-10-18"]["source"], "missing")
        self.assertEqual(by_day["2021-10-20"]["source"], "frames")
        self.assertEqual(by_day["2021-10-20"]["frames"], {"listed": 3, "decoded": 3})
        self.assertEqual(by_day["2021-10-19"]["bucket"]["bytes"], by_day["2021-10-19"]["iem"]["bytes"])
        run = json.loads((out / "ledger" / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["events"], 6)
        self.assertEqual(run["requested_end"], "2021-10-24")
        self.assertNotIn("ledger", [p.name for p in (out / "hail").iterdir()])
        with np.load(out / "ledger" / "rederived" / "2021-10-20.npz") as record:      # the builder's frame maxima
            self.assertEqual(sorted(record["tenths"].tolist()), [100, 310])
            self.assertEqual(int(record["frames"]), 3)

    def test_rerun_from_a_warm_cache_gives_identical_shards(self):
        cache = self.tmp / "cache"
        first, http1 = self.run_build(self.tmp / "one", cache, scenario_copies(self.a, self.b, self.c))
        second, http2 = self.run_build(self.tmp / "two", cache, scenario_copies(self.a, self.b, self.c))
        self.assertEqual(http1.downloads, 8)          # 5 files and 3 frames
        self.assertEqual(http2.downloads, 0)          # every file, and the derived day, come from the cache
        for path in sorted((self.tmp / "one" / "hail" / "t").glob("*.json")):
            other = self.tmp / "two" / "hail" / "t" / path.name
            self.assertEqual(path.read_bytes(), other.read_bytes(), path.name)
        first.pop("built_at")
        second.pop("built_at")
        self.assertEqual(first, second)

    def test_a_cold_cache_gives_identical_shards(self):
        self.run_build(self.tmp / "one", self.tmp / "cache-a", scenario_copies(self.a, self.b, self.c))
        self.run_build(self.tmp / "two", self.tmp / "cache-b", scenario_copies(self.a, self.b, self.c))
        self.assertEqual(sorted(p.name for p in (self.tmp / "one" / "hail" / "t").iterdir()),
                         sorted(p.name for p in (self.tmp / "two" / "hail" / "t").iterdir()))
        for path in (self.tmp / "one" / "hail" / "t").iterdir():
            self.assertEqual(path.read_bytes(), (self.tmp / "two" / "hail" / "t" / path.name).read_bytes())

    def test_too_few_frames_refuse_the_day(self):
        copies = scenario_copies(self.a, self.b, self.c)
        for key in [k for k in copies if k.startswith(f"{h.BUCKET}/CONUS/MESH_00.50/")]:
            del copies[key]
        with self.assertRaises(h.HailStoreError) as ctx:
            with mock.patch.object(h, "MIN_FRAMES", 3):
                h._run_build(self.tmp / "store", date(2021, 10, 17), date(2021, 10, 24), FakeHttp(copies),
                             self.tmp / "cache", 0, self.mesh, decode=fake_decode, max_missing=5)
        self.assertIn("only 0 two-minute frames are listed for 2021-10-20", str(ctx.exception))

    def test_a_bad_copy_stops_the_build(self):
        copies = scenario_copies(self.a, self.b, self.c)
        url = h.bucket_url(date(2021, 10, 19) + timedelta(days=1))
        http = FakeHttp(copies, heads_fail={url})
        with self.assertRaises(h.HailStoreError) as ctx:
            h._run_build(self.tmp / "store", date(2021, 10, 17), date(2021, 10, 24), http, self.tmp / "cache", 0,
                         self.mesh, decode=fake_decode)
        self.assertIn("did not answer for the 12:00 UTC file stamped 2021-10-20", str(ctx.exception))
        self.assertFalse((self.tmp / "store" / "hail").exists())


class StateListTests(unittest.TestCase):
    """The state lists decide what is outside Montana: a Montana cell with no value reads as no estimate, a key that is
    not in the state reads as outside, and a listed tile has its shard. A small mask keeps the build quick."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hail-state-"))
        mask = np.zeros((10, 10), dtype=bool)
        mask[0, 0] = True                                  # cell (790, 1990), key 0
        mask[5, 5] = True                                  # cell (795, 1995), key 55
        self.day = date(2021, 10, 20)
        self.store = self.tmp / "store"
        copies = {h.bucket_url(self.day + timedelta(days=1)): grib_bytes({0: 300})}
        h._run_build(self.store, self.day, self.day, FakeHttp(copies), self.tmp / "cache", 0,
                     h.Mesh(790, 1990, mask), decode=fake_decode, max_missing=5)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_key_outside_the_state_is_outside_and_an_empty_key_is_no_estimate(self):
        self.assertEqual(h.cell_events(self.store, 47.095, -110.095), [(self.day, 300)])   # cell (790, 1990)
        self.assertEqual(h.cell_events(self.store, 47.045, -110.045), [])                   # cell (795, 1995)
        self.assertIsNone(h.cell_events(self.store, 47.085, -110.095))                      # cell (791, 1990)

    def test_the_shard_lists_its_state_and_only_its_events(self):
        self.assertEqual(h.load_index(self.store)["tiles"], ["r0079_c0199"])
        doc = json.loads((self.store / "hail" / "t" / "r0079_c0199.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["state"], [0, 55])
        self.assertEqual(doc["cells"], {"0": [[h.day_index(self.day), 300]]})
        self.assertEqual(h.verify(self.store)["state_cells"], 2)

    def test_a_listed_tile_whose_shard_is_missing_is_refused(self):
        (self.store / "hail" / "t" / "r0079_c0199.json").unlink()
        with self.assertRaises(h.HailStoreError) as ctx:
            h.cell_events(self.store, 47.095, -110.095)
        self.assertIn("is missing", str(ctx.exception))


@unittest.skipUnless(has_pyarrow(), "pyarrow is needed to write and read the prototype's events.parquet")
class CompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hail-compare-"))
        BuildTests.setUpClass()
        self.mesh = BuildTests.mesh

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_prototype(self, store, tenths_override=None):
        """A prototype folder built from the store's own events: its crop, mask and events.parquet."""
        import pyarrow as pa
        import pyarrow.parquet as pq
        mesh = h.montana_mesh()
        proto = self.tmp / "proto"
        proto.mkdir()
        days, rows, cols, vals = h._store_events(store)
        key_mesh = mesh.rows * h.COLS + mesh.cols
        cell_index = np.searchsorted(key_mesh, rows * h.COLS + cols).astype(np.int32)
        if tenths_override is not None:
            vals = vals.copy()
            vals[tenths_override[0]] = tenths_override[1]
        dates = np.array([h.day_of_index(int(d)).isoformat() for d in days], dtype="datetime64[D]")
        table = pa.table({"cell_index": pa.array(cell_index, type=pa.int32()),
                          "day": pa.array(dates, type=pa.date32()),
                          "mm": pa.array(vals / 10.0, type=pa.float64())})
        pq.write_table(table, proto / "events.parquet")
        index = h.load_index(store)
        start, end = h._window_dates(index)
        missing = set(index["missing_days"])
        present = [d.isoformat() for d in h._day_range(start, end) if d.isoformat() not in missing]
        (proto / "grid.json").write_text(json.dumps({
            "crop": {"row0": mesh.row0, "col0": mesh.col0, "nrow": mesh.nrow, "ncol": mesh.ncol},
            "days": present, "n_cells": mesh.n,
            "basemap_sha256": hashlib.sha256(h.BASEMAP.read_bytes()).hexdigest()}), encoding="utf-8")
        (proto / "mask.bin").write_bytes(np.packbits(mesh.mask.ravel()).tobytes())
        return proto

    def build_store(self):
        out = self.tmp / "store"
        BuildTests.run_build(self, out, self.tmp / "cache", scenario_copies(BuildTests.index_of(792, 1998),
                                                                            BuildTests.index_of(796, 1993),
                                                                            BuildTests.index_of(921, 2149)))
        return out

    def test_a_store_equals_its_own_prototype(self):
        out = self.build_store()
        report = h.compare(out, self.make_prototype(out))
        self.assertEqual((report["matched"], report["mismatches"]), (6, 0))
        self.assertTrue(report["mask_equal"])
        self.assertEqual(report["overlap_days"], 6)
        self.assertEqual(report["rederived_record_missing"], [])
        self.assertEqual(report["rederived_record_mismatches"], 0)
        # the scenario's re-derived day has 3 frames: it is listed as partial and does not fail the gate
        self.assertEqual(report["partial_days"], [{"day": "2021-10-20", "frames": 3, "expected": 720}])
        self.assertTrue(report["passed"])

    def test_a_missing_frame_maximum_record_keeps_the_gate_closed(self):
        out = self.build_store()
        (out / "ledger" / "rederived" / "2021-10-20.npz").unlink()
        report = h.compare(out, self.make_prototype(out))
        self.assertEqual(report["rederived_record_missing"], ["2021-10-20"])
        self.assertFalse(report["passed"])

    def test_a_frame_maximum_record_that_differs_from_the_store_keeps_the_gate_closed(self):
        out = self.build_store()
        path = out / "ledger" / "rederived" / "2021-10-20.npz"
        with np.load(path) as record:
            data = {name: record[name] for name in record.files}
        data["tenths"] = data["tenths"] + 1
        np.savez_compressed(path, **data)
        report = h.compare(out, self.make_prototype(out))
        self.assertEqual(report["rederived_record_mismatches"], 2)
        self.assertFalse(report["passed"])

    def test_a_value_on_an_ordinary_day_is_a_mismatch(self):
        out = self.build_store()
        _days, _rows, _cols, vals = h._store_events(out)
        position = int(np.flatnonzero(vals == 300)[0])          # 2021-10-19, not a re-derived day
        report = h.compare(out, self.make_prototype(out, tenths_override=(position, 301)))
        self.assertFalse(report["passed"])
        self.assertEqual(report["value_differs"], 1)
        self.assertEqual(report["mismatches_on_other_days"], 1)
        self.assertEqual(report["mismatches_on_rederived_days"], 0)
        self.assertEqual(report["days_with_mismatches"], {"2021-10-19": 1})


def mesh_cell_index(row: int, col: int) -> int:
    """The index of grid cell (row, col) among the scenario mesh's cells (the order the decoded values come in)."""
    mesh = scenario_mesh()
    hits = np.flatnonzero((mesh.rows == row) & (mesh.cols == col))
    assert hits.size == 1, (row, col)
    return int(hits[0])


def frame_copies(day: date, slots, near=()) -> dict:
    """The two-minute frames of one SPC day (12:00 UTC on day to 12:00 UTC the next day). slots are the slot numbers
    (0 to 719) that have a frame; near lists slots that also get a near-identical copy 3 seconds later. Every frame
    reads the Benchland cell, a tenth of a mm higher than the frame before, so the day's maximum is the last."""
    cell = mesh_cell_index(792, 1998)
    start = datetime(day.year, day.month, day.day, 12, 0)
    times = [start + timedelta(minutes=2 * k) for k in slots]
    times += [start + timedelta(minutes=2 * k, seconds=3) for k in near]
    copies = {}
    for n, when in enumerate(sorted(times)):
        name = f"MRMS_MESH_00.50_{when:%Y%m%d-%H%M%S}.grib2.gz"
        copies[f"{h.BUCKET}/CONUS/MESH_00.50/{when:%Y%m%d}/{name}"] = grib_bytes({cell: 100 + n})
    return copies


def derived_day_copies(day: date, slots, near=()) -> dict:
    """The copies of one SPC day that must be re-derived: its frames, and a bucket and an IEM 12:00 file of different
    sizes (the copy rule sees the difference; the 12:00 values are not used for the day)."""
    copies = frame_copies(day, slots, near)
    copies[h.bucket_url(day + timedelta(days=1))] = grib_bytes({mesh_cell_index(792, 1998): 999})
    copies[h.iem_url(day + timedelta(days=1))] = grib_bytes({mesh_cell_index(792, 1998): 300}, pad=100)
    return copies


def build_one_day(out, cache, day: date, copies: dict):
    """Build a store for one SPC day from fake copies. Returns the index and the fake HTTP client."""
    http = FakeHttp(copies)
    index = h._run_build(out, day, day, http, cache, 0, scenario_mesh(), decode=fake_decode, max_missing=5)
    return index, http


class RederivedDayTests(unittest.TestCase):
    """A re-derived day's coverage: distinct two-minute slots, near-identical copies, and the longest gap."""
    DAY = date(2021, 10, 20)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hail-derive-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_missing_slot_and_a_near_copy_make_a_partial_day(self):
        slots = [k for k in range(h.SLOTS_PER_DAY) if k != 5]           # slot 5 has no frame: a 240-second gap
        index, _http = build_one_day(self.tmp / "store", self.tmp / "cache", self.DAY,
                                     derived_day_copies(self.DAY, slots, near=(10,)))
        cc = index["copy_check"]
        self.assertEqual(cc["rederived"], ["2021-10-20"])
        self.assertEqual(cc["coverage"], {"2021-10-20": {"listed": 720, "near_duplicate_pairs": 1,
                                                         "distinct_slots": 719, "largest_gap_s": 240}})
        self.assertEqual(cc["partial"], [{"day": "2021-10-20", "frames": 719, "expected": h.SLOTS_PER_DAY}])
        self.assertEqual(cc["frames"], {"2021-10-20": 720})
        report = h.verify(self.tmp / "store")                           # a partial day does not fail verify
        self.assertEqual(report["partial_days"], cc["partial"])

    def test_a_full_day_with_a_near_copy_is_not_partial(self):
        index, _http = build_one_day(self.tmp / "store", self.tmp / "cache", self.DAY,
                                     derived_day_copies(self.DAY, range(h.SLOTS_PER_DAY), near=(10,)))
        cc = index["copy_check"]
        self.assertEqual(cc["coverage"]["2021-10-20"], {"listed": 721, "near_duplicate_pairs": 1,
                                                        "distinct_slots": 720, "largest_gap_s": 120})
        self.assertEqual(cc["partial"], [])

    def test_a_cache_entry_with_its_coverage_is_reused(self):
        cache = self.tmp / "cache"
        first, _first_http = build_one_day(self.tmp / "one", cache, self.DAY,
                                           derived_day_copies(self.DAY, range(h.SLOTS_PER_DAY)))
        second, second_http = build_one_day(self.tmp / "two", cache, self.DAY,
                                            derived_day_copies(self.DAY, range(h.SLOTS_PER_DAY)))
        self.assertEqual(second_http.downloads, 0)
        self.assertEqual(first["copy_check"]["coverage"], second["copy_check"]["coverage"])

    def test_a_cache_entry_without_its_coverage_is_a_miss(self):
        cache = self.tmp / "cache"
        build_one_day(self.tmp / "one", cache, self.DAY, derived_day_copies(self.DAY, range(h.SLOTS_PER_DAY)))
        meta = cache / "derived" / "2021-10-20.json"
        doc = json.loads(meta.read_text(encoding="utf-8"))
        del doc["coverage"]
        meta.write_text(json.dumps(doc), encoding="utf-8")
        _second, second_http = build_one_day(self.tmp / "two", cache, self.DAY,
                                             derived_day_copies(self.DAY, range(h.SLOTS_PER_DAY)))
        self.assertGreater(second_http.downloads, 0)                  # the frames are read again
        self.assertIn("coverage", json.loads(meta.read_text(encoding="utf-8")))


# The five cells of the Montana mask that hold 513 tenths on SPC day 2025-06-15 in the full store. They come from a
# decode of the 12:00 UTC file stamped 2025-06-16 over the mask; the sample holds only the cell at (797, 1986).
HAIL_513_CELLS_2025_06_15 = [(737, 1910), (742, 1918), (797, 1986), (822, 2351), (936, 2464)]


def haversine_km(lat1, lon1, lat2, lon2):
    """The great-circle distance in kilometres on a sphere of mean radius 6371 km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


class CheckCellTests(unittest.TestCase):
    """verify() runs the check cell on a built store whose window holds its day (2025-06-15)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hail-check-cell-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build_store(self, value):
        gate = mesh_cell_index(*h.cell_for(*h.GATE_POINT))
        copies = {}
        for day, values in ((date(2025, 6, 14), {}), (h.GATE_DAY, {gate: value}), (date(2025, 6, 16), {})):
            copies[h.bucket_url(day + timedelta(days=1))] = grib_bytes(values)
        out = self.tmp / "store"
        h._run_build(out, date(2025, 6, 14), date(2025, 6, 16), FakeHttp(copies), self.tmp / "cache", 0,
                     scenario_mesh(), decode=fake_decode, max_missing=5)
        return out

    def test_a_store_holding_the_check_value_verifies_and_says_so(self):
        check = h.verify(self.build_store(h.GATE_TENTHS))["benchland"]
        self.assertEqual((check["cell"], check["tenths"], check["mm"]), ([797, 1986], 513, "51.3"))
        self.assertTrue(check["checked"])
        self.assertTrue(check["matches_gate_expectation"])

    def test_a_store_without_the_check_value_is_refused(self):
        with self.assertRaises(h.HailStoreError) as ctx:
            h.verify(self.build_store(185))
        self.assertEqual(str(ctx.exception), "the history does not hold 2.01 in on Jun 15, 2025 at the check cell")

    def test_the_check_cell_is_the_nearest_513_to_benchland(self):
        self.assertEqual(h.cell_for(*h.GATE_POINT), (797, 1986))
        self.assertEqual(h.cell_centre(797, 1986), h.GATE_POINT)
        self.assertEqual(h.cell_for(*h.BENCHLAND), (792, 1998))
        self.assertEqual(h.GATE_TENTHS, 513)
        nearest = min(HAIL_513_CELLS_2025_06_15, key=lambda rc: haversine_km(*BENCHLAND, *h.cell_centre(*rc)))
        self.assertEqual(h.cell_for(*h.GATE_POINT), nearest)


class CompareGateTests(unittest.TestCase):
    """compare() with the prototype's events given directly (no pyarrow). A re-derived day that differs from the
    prototype passes the gate when it has SLOTS_PER_DAY distinct frames, and keeps the gate open when it does not."""
    DAY = date(2021, 10, 20)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hail-compare-gate-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def compare_with_prototype(self, store, override=None, proto_days=None):
        """Compare the store with a prototype whose events are the store's, except one value (override = (position,
        tenths), or None). proto_days lists the prototype's days (by default, the days of the store's
        window). The prototype folder has the whole Montana crop, so the masks are equal."""
        mesh = h.montana_mesh()
        proto = self.tmp / "proto"
        proto.mkdir(exist_ok=True)
        index = h.load_index(store)
        start, end = h._window_dates(index)
        missing = set(index["missing_days"])
        present = [d.isoformat() for d in h._day_range(start, end) if d.isoformat() not in missing]
        (proto / "grid.json").write_text(json.dumps({
            "crop": {"row0": mesh.row0, "col0": mesh.col0, "nrow": mesh.nrow, "ncol": mesh.ncol},
            "days": present if proto_days is None else proto_days, "n_cells": mesh.n,
            "basemap_sha256": hashlib.sha256(h.BASEMAP.read_bytes()).hexdigest()}), encoding="utf-8")
        (proto / "mask.bin").write_bytes(np.packbits(mesh.mask.ravel()).tobytes())
        days, rows, cols, vals = h._store_events(store)
        key_mesh = mesh.rows * h.COLS + mesh.cols
        arrays = {"cell_index": np.searchsorted(key_mesh, rows * h.COLS + cols).astype(np.int64),
                  "day": days + (h.D0 - h.EPOCH).days,
                  "mm": vals.astype(np.float64) / 10.0}
        if override is not None:
            position, tenths = override
            arrays["mm"][position] = tenths / 10.0
        with mock.patch.object(h, "_prototype_events", return_value=arrays):
            return h.compare(store, proto)

    def test_a_full_day_that_differs_from_the_prototype_passes_the_gate(self):
        out = self.tmp / "store"
        build_one_day(out, self.tmp / "cache", self.DAY, derived_day_copies(self.DAY, range(h.SLOTS_PER_DAY)))
        report = self.compare_with_prototype(out, override=(0, 820))
        self.assertEqual((report["mismatches_on_rederived_days"], report["mismatches_on_other_days"]), (1, 0))
        self.assertEqual(report["partial_days"], [])
        self.assertTrue(report["passed"], report)

    def test_a_partial_day_that_differs_from_the_prototype_is_listed_and_passes(self):
        out = self.tmp / "store"
        slots = [k for k in range(h.SLOTS_PER_DAY) if k != 5]
        build_one_day(out, self.tmp / "cache", self.DAY, derived_day_copies(self.DAY, slots))
        report = self.compare_with_prototype(out, override=(0, 820))
        self.assertEqual(report["partial_days"], [{"day": "2021-10-20", "frames": 719, "expected": h.SLOTS_PER_DAY}])
        self.assertEqual((report["mismatches_on_rederived_days"], report["mismatches_on_other_days"]), (1, 0))
        self.assertTrue(report["passed"])

    def test_a_mismatch_on_an_ordinary_day_keeps_the_gate_closed(self):
        out = self.tmp / "store"
        copies = {h.bucket_url(self.DAY + timedelta(days=1)): grib_bytes({mesh_cell_index(792, 1998): 300})}
        build_one_day(out, self.tmp / "cache", self.DAY, copies)           # bucket copy only: not re-derived
        report = self.compare_with_prototype(out, override=(0, 301))
        self.assertEqual(report["rederived_days"], [])
        self.assertEqual((report["mismatches_on_other_days"], report["mismatches_on_rederived_days"]), (1, 0))
        self.assertFalse(report["passed"])

    def test_a_store_with_no_day_in_the_prototype_keeps_the_gate_closed(self):
        out = self.tmp / "store"
        copies = {h.bucket_url(self.DAY + timedelta(days=1)): grib_bytes({mesh_cell_index(792, 1998): 300})}
        build_one_day(out, self.tmp / "cache", self.DAY, copies)
        report = self.compare_with_prototype(out, override=None, proto_days=["2030-01-01"])
        self.assertEqual(report["overlap_days"], 0)
        self.assertFalse(report["passed"])


class WorkflowTests(unittest.TestCase):
    def test_the_daily_job_installs_unpinned_like_the_site_build(self):
        # the B2 brief's job section and D12: the job also installs pyshp (the zone shapefiles, joins.py only)
        text = (ROOT / ".github" / "workflows" / "hail-store.yml").read_text(encoding="utf-8")
        self.assertIn("run: pip install numpy pygrib requests pyshp\n", text)
        self.assertNotIn("==", text)
        self.assertIn('python-version: "3.12"', text)
        self.assertIn("python -m website.hail verify store", text)


class FetchAndLoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hail-fetch-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def make_tar(members, links=()):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as archive:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
            for name, target in links:
                info = tarfile.TarInfo(name)
                info.type = tarfile.SYMTYPE
                info.linkname = target
                archive.addfile(info)
        return buf.getvalue()

    @staticmethod
    def fixture_members():
        members = {}
        for path in sorted((FIXTURE / "hail").rglob("*")):
            if path.is_file():
                members[path.relative_to(FIXTURE).as_posix()] = path.read_bytes()
        return members

    @staticmethod
    def getter(data, error=None):
        def get(url, headers=None):
            return data, error
        return get

    def test_fetch_store_unpacks_the_fixture_tar(self):
        dest = self.tmp / "store"
        index = h.fetch_store(self.getter(self.make_tar(self.fixture_members())), dest)
        self.assertEqual(index["as_of"], "2026-10-15")
        self.assertEqual(sorted(p.name for p in dest.iterdir()), ["hail"])
        for rel, data in self.fixture_members().items():
            self.assertEqual((dest / rel).read_bytes(), data, rel)

    def test_a_bad_hash_is_refused(self):
        members = self.fixture_members()
        members["hail/t/r0079_c0199.json"] = members["hail/t/r0079_c0199.json"].replace(b",185]", b",186]")
        with self.assertRaises(h.HailStoreError) as ctx:
            h.fetch_store(self.getter(self.make_tar(members)), self.tmp / "store")
        self.assertIn("does not match the manifest", str(ctx.exception))
        self.assertFalse((self.tmp / "store" / "hail").exists())

    def test_a_non_tar_body_is_refused(self):
        with self.assertRaises(h.HailStoreError) as ctx:
            h.fetch_store(self.getter(gzip.compress(b"plain text, not a tar")), self.tmp / "a")
        self.assertEqual(str(ctx.exception), "the history download is not a tar.gz archive")
        with self.assertRaises(h.HailStoreError) as ctx:
            h.fetch_store(self.getter(b"<html>an error page</html>"), self.tmp / "b")
        self.assertEqual(str(ctx.exception), "the history download is not a gzip file")

    def test_a_failed_get_says_why(self):
        with self.assertRaises(h.HailStoreError) as ctx:
            h.fetch_store(self.getter(None, "not published (HTTP 404)"), self.tmp / "c")
        self.assertEqual(str(ctx.exception), "the history download failed: not published (HTTP 404)")

    def test_names_that_climb_out_and_links_are_refused(self):
        with self.assertRaises(h.HailStoreError) as ctx:
            h.fetch_store(self.getter(self.make_tar({"hail/../evil.json": b"{}"})), self.tmp / "d")
        self.assertIn("not allowed", str(ctx.exception))
        with self.assertRaises(h.HailStoreError) as ctx:
            h.fetch_store(self.getter(self.make_tar({}, links=[("hail/t/link.json", "../index.json")])),
                          self.tmp / "e")
        self.assertIn("link or special file", str(ctx.exception))

    def test_other_members_are_skipped_and_an_empty_archive_is_refused(self):
        members = self.fixture_members()
        members["other/readme.txt"] = b"not part of the store"
        dest = self.tmp / "f"
        h.fetch_store(self.getter(self.make_tar(members)), dest)
        self.assertFalse((dest / "other").exists())
        with self.assertRaises(h.HailStoreError) as ctx:
            h.fetch_store(self.getter(self.make_tar({"readme": b"x"})), self.tmp / "g")
        self.assertEqual(str(ctx.exception), "the history archive has no store files")

    def test_a_manifest_that_lists_a_file_outside_hail_is_refused(self):
        members = self.fixture_members()
        manifest = json.loads(members["hail/manifest.json"].decode("utf-8"))
        manifest["files"]["../outside.json"] = {"bytes": 2, "sha256": hashlib.sha256(b"{}").hexdigest()}
        members["hail/manifest.json"] = h._pretty(manifest)
        dest = self.tmp / "store"
        with self.assertRaises(h.HailStoreError) as ctx:
            h.fetch_store(self.getter(self.make_tar(members)), dest)
        self.assertEqual(str(ctx.exception), "the history manifest lists a file outside hail/: ../outside.json")
        self.assertFalse((dest / "hail").exists())

    def test_load_store_takes_a_directory_or_a_tar(self):
        self.assertEqual(h.load_store(FIXTURE), FIXTURE)
        tar_path = self.tmp / "hail-store.tar.gz"
        tar_path.write_bytes(self.make_tar(self.fixture_members()))
        dest = self.tmp / "unpacked"
        found = h.load_store(tar_path, dest)
        self.assertEqual(found, dest)
        self.assertEqual(h.load_index(found)["as_of"], "2026-10-15")
        self.assertEqual(h.cell_events(found, *BENCHLAND)[-1], (date(2026, 9, 6), 439))

    def test_load_store_refuses_a_missing_path(self):
        with self.assertRaises(h.HailStoreError) as ctx:
            h.load_store(self.tmp / "absent.tar.gz")
        self.assertIn("is not at", str(ctx.exception))


@contextlib.contextmanager
def own_folder(prefix: str):
    """A folder that this test makes; it is the only thing removed afterwards."""
    folder = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@contextlib.contextmanager
def fixture_copy():
    """A copy of the SAMPLE store, in a folder this test makes, for one change and one verify."""
    with own_folder("hail-verify-") as tmp:
        store = tmp / "store"
        shutil.copytree(FIXTURE, store)
        yield store


def refresh_manifest(root: Path) -> None:
    """Make a copied store's index and manifest agree with its files, so the only thing verify can refuse is the
    change a test made: the index's byte count is the sum of the shard sizes, every listed file has its current
    size and SHA-256, and the manifest's counts are the index's counts."""
    hail = root / "hail"
    index_path = hail / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["bytes"] = sum(path.stat().st_size for path in (hail / "t").glob("*.json"))
    index_path.write_bytes(h._pretty(index))
    files = {}
    for path in sorted(hail.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            data = path.read_bytes()
            files[path.relative_to(root).as_posix()] = {"bytes": len(data),
                                                        "sha256": hashlib.sha256(data).hexdigest()}
    manifest_path = hail / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = files
    manifest["counts"] = {key: index[key] for key in ("days_expected", "days_present", "events", "shards", "bytes")}
    manifest_path.write_bytes(h._pretty(manifest))


def read_doc(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class VerifyAndCommandTests(unittest.TestCase):
    def test_the_fixture_verifies(self):
        report = h.verify(FIXTURE)
        self.assertTrue(report["ok"])
        self.assertEqual((report["events"], report["shards"], report["tiles"]), (1575, 3, 3))
        self.assertFalse(report["benchland"]["checked"])            # a sample store is not checked
        self.assertEqual(report["benchland"]["tenths"], 513)        # the sample holds the check value, read from the store
        self.assertTrue(report["benchland"]["matches_gate_expectation"])

    def test_verify_command_prints_the_report(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = h.main(["verify", str(FIXTURE)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertTrue(json.loads(out.getvalue())["ok"])

    def test_compare_without_a_prototype_says_what_is_missing(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = h.main(["compare", "--store", str(FIXTURE), "--prototype", str(FIXTURE / "absent")])
        self.assertEqual(code, 1)
        self.assertIn("grid.json cannot be read", err.getvalue())

    def expect_refused(self, store: Path, message: str) -> None:
        """Refresh the copied store's index and manifest, then check that verify refuses it with this message."""
        refresh_manifest(store)
        with self.assertRaises(h.HailStoreError) as ctx:
            h.verify(store)
        self.assertEqual(str(ctx.exception), message)

    def test_a_copy_of_the_fixture_verifies_once_its_manifest_is_refreshed(self):
        with fixture_copy() as store:
            refresh_manifest(store)
            self.assertTrue(h.verify(store)["ok"])

    def test_the_as_of_date_must_be_the_last_day_of_the_window(self):
        with fixture_copy() as store:
            path = store / "hail" / "index.json"
            index = read_doc(path)
            index["as_of"] = "2026-10-14"
            path.write_bytes(h._pretty(index))
            self.expect_refused(store, "the history as-of date is not the last day of its window")

    def test_the_day_counts_must_match_the_window_and_the_missing_days(self):
        with fixture_copy() as store:
            path = store / "hail" / "index.json"
            index = read_doc(path)
            index["days_present"] = 1824
            path.write_bytes(h._pretty(index))
            self.expect_refused(store, "the history day counts do not match its window and its missing days")

    def test_a_missing_day_must_lie_inside_the_window(self):
        with fixture_copy() as store:
            path = store / "hail" / "index.json"
            index = read_doc(path)
            index["missing_days"] = ["2019-01-01"]
            path.write_bytes(h._pretty(index))
            self.expect_refused(store, "a missing day lies outside the window")

    def test_the_tiles_list_must_be_sorted_and_unique(self):
        with fixture_copy() as store:
            path = store / "hail" / "index.json"
            index = read_doc(path)
            index["tiles"] = sorted(index["tiles"], reverse=True)
            path.write_bytes(h._pretty(index))
            self.expect_refused(store, "the history tiles list is not sorted, or it names a tile twice")

    def test_the_tiles_list_must_name_each_shard_file(self):
        with fixture_copy() as store:
            path = store / "hail" / "index.json"
            index = read_doc(path)
            index["tiles"] = index["tiles"][:-1]
            path.write_bytes(h._pretty(index))
            self.expect_refused(store, "the history tiles list does not match the shard files")

    def test_a_state_list_must_be_sorted_cell_keys(self):
        with fixture_copy() as store:
            path = store / "hail" / "t" / "r0079_c0198.json"
            doc = read_doc(path)
            doc["state"] = list(reversed(doc["state"]))
            path.write_bytes(h._compact(doc))
            self.expect_refused(store, "the history shard r0079_c0198.json has a state list that is not sorted "
                                       "cell keys")

    def test_cells_must_be_keys_in_the_state_list(self):
        with fixture_copy() as store:
            path = store / "hail" / "t" / "r0079_c0198.json"
            doc = read_doc(path)
            key = h.cell_key(797, 1986)                      # the check cell, which holds 513 on 2025-06-15
            self.assertIn(str(key), doc["cells"])
            doc["state"] = [k for k in doc["state"] if k != key]
            path.write_bytes(h._compact(doc))
            self.expect_refused(store, "the history shard r0079_c0198.json holds cells outside its state list")

    def test_no_value_may_fall_after_as_of(self):
        with fixture_copy() as store:
            path = store / "hail" / "t" / "r0079_c0199.json"
            doc = read_doc(path)
            doc["cells"]["18"].append([h.day_index(date(2026, 10, 16)), 100])
            path.write_bytes(h._compact(doc))
            self.expect_refused(store, "the history shard r0079_c0199.json holds a day outside the window "
                                       "or a day with no data")

    def test_no_value_may_fall_on_a_missing_day(self):
        with fixture_copy() as store:
            path = store / "hail" / "t" / "r0079_c0199.json"
            doc = read_doc(path)
            doc["cells"]["18"].append([h.day_index(date(2022, 6, 8)), 100])     # 2022-06-08 is a missing day
            path.write_bytes(h._compact(doc))
            self.expect_refused(store, "the history shard r0079_c0199.json holds a day outside the window "
                                       "or a day with no data")

    def test_a_value_must_be_at_or_above_the_floor(self):
        with fixture_copy() as store:
            path = store / "hail" / "t" / "r0079_c0199.json"
            doc = read_doc(path)
            doc["cells"]["18"][0][1] = 63
            path.write_bytes(h._compact(doc))
            self.expect_refused(store, "the history shard r0079_c0199.json holds a value below the floor "
                                       "or out of day order")

    def test_days_must_be_in_order(self):
        with fixture_copy() as store:
            path = store / "hail" / "t" / "r0079_c0199.json"
            doc = read_doc(path)
            rows = doc["cells"]["18"]
            self.assertGreaterEqual(len(rows), 2)
            rows[0], rows[1] = rows[1], rows[0]
            path.write_bytes(h._compact(doc))
            self.expect_refused(store, "the history shard r0079_c0199.json holds a value below the floor "
                                       "or out of day order")

    def test_the_index_events_must_equal_the_shard_events(self):
        with fixture_copy() as store:
            path = store / "hail" / "index.json"
            index = read_doc(path)
            index["events"] += 1
            path.write_bytes(h._pretty(index))
            self.expect_refused(store, "the history counts do not match its shards")

    def test_the_state_lists_must_hold_the_montana_cells(self):
        with fixture_copy() as store:
            path = store / "hail" / "index.json"
            index = read_doc(path)
            del index["sample"]                              # a built store: cells_in_state is the state's count
            path.write_bytes(h._pretty(index))
            self.expect_refused(store, "the history state lists do not hold the Montana cells")

    def test_the_state_lists_must_match_the_montana_mask(self):
        # The same small store as StateListTests (two Montana cells); the Montana constants are patched to it.
        mask = np.zeros((10, 10), dtype=bool)
        mask[0, 0] = True                                    # cell (790, 1990), key 0
        mask[5, 5] = True                                    # cell (795, 1995), key 55
        mesh = h.Mesh(790, 1990, mask)
        day = date(2021, 10, 20)
        with own_folder("hail-mask-") as tmp:
            store = tmp / "store"
            copies = {h.bucket_url(day + timedelta(days=1)): grib_bytes({0: 300})}
            h._run_build(store, day, day, FakeHttp(copies), tmp / "cache", 0, mesh, decode=fake_decode,
                         max_missing=5)
            with mock.patch.object(h, "montana_mesh", return_value=mesh):
                with mock.patch.object(h, "CELLS_IN_STATE", mesh.n):
                    self.assertEqual(h.verify(store)["state_cells"], 2)          # the store as built passes
                    path = store / "hail" / "t" / "r0079_c0199.json"
                    doc = read_doc(path)
                    self.assertEqual(doc["state"], [0, 55])
                    doc["state"] = [0, 54]                   # as many keys, but not the Montana ones
                    path.write_bytes(h._compact(doc))
                    refresh_manifest(store)
                    with self.assertRaises(h.HailStoreError) as ctx:
                        h.verify(store)
        self.assertEqual(str(ctx.exception), "the history tiles and state lists do not match the Montana mask")

    def test_a_cell_with_an_empty_list_is_refused(self):
        with fixture_copy() as store:
            path = store / "hail" / "t" / "r0092_c0214.json"
            doc = read_doc(path)
            empty = next(k for k in doc["state"] if str(k) not in doc["cells"])   # a Montana cell with no events
            self.assertIn(empty, doc["state"])
            self.assertNotIn(str(empty), doc["cells"])
            doc["cells"][str(empty)] = []
            path.write_bytes(h._compact(doc))
            self.expect_refused(store, "the history shard r0092_c0214.json lists a cell with no events")

    def test_a_shard_that_is_not_valid_json_is_refused(self):
        with fixture_copy() as store:
            (store / "hail" / "t" / "r0079_c0199.json").write_bytes(b"{not json")
            self.expect_refused(store, "the history shard r0079_c0199.json is not valid JSON")

    def test_a_shard_in_the_wrong_format_is_refused(self):
        with fixture_copy() as store:
            path = store / "hail" / "t" / "r0079_c0199.json"
            doc = read_doc(path)
            doc["f"] = "hail-cells-v0"
            path.write_bytes(h._compact(doc))
            self.expect_refused(store, "the history shard r0079_c0199.json is not in the expected format")

    def test_a_cell_that_is_not_a_list_of_days_is_refused(self):
        with fixture_copy() as store:
            path = store / "hail" / "t" / "r0079_c0199.json"
            doc = read_doc(path)
            doc["cells"]["28"] = "x"
            path.write_bytes(h._compact(doc))
            self.expect_refused(store, "the history shard r0079_c0199.json holds a cell that is not a list of days")

    def test_a_day_and_value_that_are_not_a_pair_are_refused(self):
        with fixture_copy() as store:
            path = store / "hail" / "t" / "r0079_c0199.json"
            doc = read_doc(path)
            doc["cells"]["28"][0] = [1]
            path.write_bytes(h._compact(doc))
            self.expect_refused(store, "the history shard r0079_c0199.json holds a day and value that are not a pair")

    def test_build_has_the_documented_defaults(self):
        self.assertTrue(callable(h.build))
        self.assertEqual(inspect.signature(h.build).parameters["procs"].default, 4)


if __name__ == "__main__":
    unittest.main()
