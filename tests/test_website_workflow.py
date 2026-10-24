"""Execute the workflow's planning shell with a fake GitHub CLI, without network."""

import ast
from datetime import datetime, timezone
import importlib
import inspect
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]


def import_tool(name: str):
    """A module from tools/ (the browser smoke scripts are not a package)."""
    tools = str(ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    return importlib.import_module(name)


class FakeResponse:
    """A browser response as the smoke reads it: its URL, its status and its body."""

    def __init__(self, path: str, body: bytes, status: int = 200):
        self.url, self.status, self._body = "http://127.0.0.1:1/hail/" + path, status, body

    def body(self) -> bytes:
        return self._body


class WebsitePlan(unittest.TestCase):
    def plan(self, response, status=0, ref="refs/heads/main", event="push"):
        workflow = (ROOT / ".github/workflows/website.yml").read_text()
        script = textwrap.dedent(workflow.split("        run: |\n", 1)[1].split("\n      -", 1)[0])
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            gh = tmp / "gh"
            gh.write_text('#!/bin/bash\nprintf "%s\\n" "$FAKE_RESPONSE"\nexit "$FAKE_STATUS"\n')
            gh.chmod(0o755)
            output = tmp / "output"
            env = dict(os.environ, PATH=f"{tmp}:{os.environ['PATH']}",
                       GITHUB_REF=ref, GITHUB_EVENT_NAME=event,
                       GITHUB_REPOSITORY="carson14dy/RoofingApp", GITHUB_OUTPUT=str(output),
                       FAKE_RESPONSE=response, FAKE_STATUS=str(status))
            result = subprocess.run(["bash", "-eo", "pipefail", "-c", script],
                                    env=env, capture_output=True, text=True, check=True)
            return dict(line.split("=", 1) for line in output.read_text().splitlines()), result.stdout

    def test_successful_lookup_publishes(self):
        url = "https://carson14dy.github.io/RoofingApp/"
        output, _ = self.plan(url)
        self.assertEqual(output, {"publish": "true", "run": "true", "pages_url": url})

    def test_failed_lookup_discards_even_url_shaped_output(self):
        for response in ('{"message":"Not Found","status":"404"}',
                         "https://carson14dy.github.io/RoofingApp/"):
            with self.subTest(response=response):
                output, log = self.plan(response, status=1)
                self.assertEqual(output, {"publish": "false", "run": "true", "pages_url": ""})
                self.assertIn("::warning::", log)

    def test_success_status_requires_a_valid_https_url(self):
        for response in ("", "null", "{}", "https://", "https://bad host/", "http://example.org/",
                         "https://example.org/\npublish=true"):
            with self.subTest(response=response):
                output, _ = self.plan(response)
                self.assertEqual(output["publish"], "false")
                self.assertEqual(output["pages_url"], "")

    def test_disabled_pages_skips_scheduled_build(self):
        output, _ = self.plan('{"message":"Not Found"}', status=1, event="schedule")
        self.assertEqual(output, {"publish": "false", "run": "false", "pages_url": ""})

    def test_branch_build_is_preview_only(self):
        output, _ = self.plan("https://example.org/", ref="refs/heads/codex/fix-pages-publication")
        self.assertEqual(output, {"publish": "false", "run": "true", "pages_url": ""})


class StormFlag(unittest.TestCase):
    """--storm-layers (radar echo tops) is passed on branch builds only, and the storm tests run in CI."""

    def setUp(self):
        self.text = (ROOT / ".github/workflows/website.yml").read_text()

    def test_only_the_branch_build_line_passes_the_flag(self):
        build_args = [line for line in self.text.splitlines() if "args+=(" in line and "--storm-layers" in line]
        self.assertEqual(len(build_args), 1)
        self.assertIn('if [ "$GITHUB_REF" != "refs/heads/main" ]', build_args[0])
        self.assertIn("--require-live --storm-layers", build_args[0])
        self.assertFalse(any("website.build" in line and "--storm-layers" in line for line in self.text.splitlines()))

    def test_the_storm_tests_run_in_the_unittest_line_and_the_path_filter(self):
        unit = [line for line in self.text.splitlines() if "python -m unittest tests." in line]   # the offline line (not the parity step's)
        self.assertEqual(len(unit), 1)
        self.assertIn("tests.test_storm", unit[0])
        self.assertIn('"tests/test_storm.py"', self.text)


class SatelliteReader(unittest.TestCase):
    """The GOES reader imports h5py (website/satellite.py read_cmip). The Install step installs it with the
    other packages, and the satellite tests run in the offline unittest line and the path filter."""

    def setUp(self):
        self.text = (ROOT / ".github/workflows/website.yml").read_text()

    def test_the_install_step_installs_h5py_with_the_other_packages(self):
        installs = [line for line in self.text.splitlines() if "python -m pip install" in line and "pygrib" in line]
        self.assertEqual(len(installs), 1)
        self.assertIn("h5py", installs[0].split())

    def test_the_satellite_tests_run_in_the_unittest_line_and_the_path_filter(self):
        unit = [line for line in self.text.splitlines() if "python -m unittest tests." in line]   # the offline line (not the parity step's)
        self.assertEqual(len(unit), 1)
        self.assertIn("tests.test_satellite", unit[0].split())
        self.assertIn('"tests/test_satellite.py"', self.text)


class OfflineWordsRules(unittest.TestCase):
    """D91(f), D92(c): the offline unittest line runs tests.test_words_rules, the tests of the one forbidden list
    (tests/words_rules.py). The module must exist, and the line must name it once, so the words gate runs in CI."""

    def setUp(self):
        self.text = (ROOT / ".github/workflows/website.yml").read_text(encoding="utf-8")

    def test_the_offline_unittest_line_names_the_words_rules_module(self):
        unit = [line for line in self.text.splitlines() if "python -m unittest tests." in line]   # the offline line only
        self.assertEqual(len(unit), 1)
        self.assertEqual(unit[0].split().count("tests.test_words_rules"), 1)
        self.assertTrue((ROOT / "tests" / "test_words_rules.py").is_file())


class SmokeFlags(unittest.TestCase):
    """The Website preview's browser smoke commands, read from the workflow and parsed by the tools' own parsers. The preview
    builds with --hail-history and --hail-addresses, so its smoke runs with --history (a missing five-season summary fails
    there, not with a note) and --addresses. The build line keeps its flags, and CI passes no local store (the build reads
    the release asset and the smoke reads the site's own hail/ folder)."""

    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / ".github/workflows/website.yml").read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def command(self, prefix: str) -> list[str]:
        """The command the workflow runs, from its first word on (a step's run line may start with "run:")."""
        found = []
        for line in self.lines:
            stripped = line.strip()
            if prefix in stripped:
                found.append(stripped[stripped.index(prefix):])
        self.assertEqual(len(found), 1, prefix)
        return shlex.split(found[0])

    def test_the_map_smoke_takes_the_history_and_address_flags_the_preview_passes(self):
        smoke_map = import_tool("smoke_map")
        parsed = smoke_map.build_parser().parse_args(self.command("python tools/smoke_map.py")[2:])
        self.assertEqual(str(parsed.root), "_site")
        self.assertTrue(parsed.addresses)
        self.assertTrue(parsed.history)
        self.assertIsNone(parsed.store)

    def test_the_page_width_check_takes_history(self):
        self.assertEqual(self.command("python tools/smoke_pages.py"), ["python", "tools/smoke_pages.py", "_site", "--history"])
        smoke_pages = import_tool("smoke_pages")
        self.assertTrue(callable(smoke_pages.check))

    def test_the_build_line_keeps_the_history_and_address_flags_and_passes_no_local_store(self):
        build = [line for line in self.lines if "args+=(" in line and "--hail-history" in line]
        self.assertEqual(len(build), 1)
        self.assertIn("--require-live --storm-layers --hail-history --hail-addresses", build[0])
        self.assertNotIn("--hail-store", self.text)

    def test_pyyaml_is_installed_for_the_workflow_file_tests(self):
        installs = [line for line in self.lines if "python -m pip install" in line and "pygrib" in line]
        self.assertEqual(len(installs), 1)
        self.assertIn("pyyaml", installs[0].split())

    def test_the_hail_workflow_tests_run_on_branch_pushes(self):
        self.assertIn('"tests/test_hail_workflow.py"', self.text)
        unit = [line for line in self.lines if "python -m unittest" in line]
        self.assertIn("tests.test_hail_workflow", unit[0].split())

    def test_the_workflow_parses_as_yaml_and_its_smoke_steps_carry_the_flags(self):
        doc = yaml.safe_load(self.text)
        self.assertEqual(sorted(doc["jobs"]), ["build", "deploy"])
        steps = {s.get("name"): s for s in doc["jobs"]["build"]["steps"]}
        self.assertIn("tools/smoke_map.py _site --addresses --history", steps["Map smoke test in a real browser (branch pushes)"]["run"])
        self.assertIn("tools/smoke_pages.py _site --history", steps["Page width check in a real browser (branch pushes)"]["run"])


class SmokeHelpers(unittest.TestCase):
    """The browser smoke's checks that need no browser (tools/smoke_map.py): the sheet's table against summary.describe_summary's
    words for the same cell (exactly), the first screen, the budget map.json carries for a tap's files, the unit and kind words,
    the classes of the phone view's files, and the smoke's own error and store handling. The sheet is a synthetic page built from
    the words the summary gives."""

    @classmethod
    def setUpClass(cls):
        cls.smoke = import_tool("smoke_map")
        cls.sm = cls.smoke.summary_module()

    def want(self):
        """A describe_summary result with three rows and the lines the sheet must show (the shape summary.py gives)."""
        def row(key, label, kind, unit, texts, coverage, five, five_cov=None, five_note=None):
            return {"key": key, "label": label, "kind": kind, "unit": unit, "texts": texts, "coverage": coverage,
                    "five_text": five, "five_coverage": five_cov, "five_note": five_note, "town_only": False}
        rows = [
            row("hail_max", "Largest hail reported within 5 miles", "Report", "in",
                ["No NWS local storm report of hail within 5 miles in 2021-22; reports are not a complete record.",
                 "0.25 in on Jun 5, 2023", "1.00 in on Jun 14, 2025", "0.88 in on Aug 1, 2025", "0.50 in on Jul 1, 2024"],
                ["108 days missing", None, None, None, None], "1.00 in on Jun 14, 2025", "108 days missing"),
            row("hail_n", "Hail reports within 5 miles", "Report", "count",
                ["1 hail report", "2 hail reports", "3 hail reports", "0 hail reports", "5 hail reports"],
                [None] * 5, "11 hail reports"),
            row("tmax", "Highest temperature", "Grid estimate", "F",
                ["94.6 F on Jul 19, 2021", "94.8 F on Jul 18, 2022", "93.4 F on Jul 25, 2023", "96.4 F on Jul 24, 2024",
                 "93.7 F on Aug 20, 2025"], [None] * 5, "96.4 F on Jul 24, 2024", None,
                "An estimate for a grid cell about 4.6 km across, not a reading at this address."),
        ]
        partial = "Preliminary grid estimate: 2026-27 so far, 107 days to Oct 15, 2026. This is not an all-clear."
        held = "Lightning: Data unavailable. The national lightning network is commercial. This is not an all-clear."
        return {"table": {"rows": rows, "partial": {"label": "2026-27", "text": partial}, "held": held},
                "plain": self.sm.WORDS_SUMMARY["plain"], "radar_sentence": self.sm.WORDS_SUMMARY["radar_sentence"]}

    def sheet(self, want, edit=None):
        """What the browser reads from a sheet that shows the words: the table, its rows and the lines around it."""
        table = want["table"]
        body = " ".join([self.sm.WORDS_SUMMARY["table_title"], want["plain"], want["radar_sentence"],
                         table["partial"]["text"], table["held"]] + [r["five_note"] for r in table["rows"] if r["five_note"]])
        box = {"top": 380, "bottom": 420, "left": 0, "right": 390}
        rows = [{"text": "Measure 2021-22 2022-23 2023-24 2024-25 2025-26 Five seasons", "cells": ["Measure"] + list(self.sm.COLUMNS),
                 "rect": box}]
        for r in table["rows"]:
            cells = [f"{r['label']} {r['kind']} {r['unit']}"]
            cells += [t + (f" {c}" if c else "") for t, c in zip(r["texts"], r["coverage"])]
            cells.append(r["five_text"] + (f" {r['five_coverage']}" if r["five_coverage"] else ""))
            rows.append({"text": " ".join(cells), "cells": cells, "rect": box})
        got = {"present": True, "body": body, "rows": rows,
               "viewport": {"w": 390, "h": 844, "scrollW": 390}, "sheet": {"top": 300, "bottom": 844},
               "table": {"top": 340, "bottom": 800, "left": 0, "right": 390}, "above_bottom": 200,
               "first_row": {"top": 380, "bottom": 420}}
        if edit:
            edit(got)
        return got

    def test_a_sheet_that_shows_the_python_words_has_no_problems(self):
        want = self.want()
        self.assertEqual(self.smoke.summary_problems("sheet", want, self.sheet(want)), [])

    def test_a_cell_with_other_words_is_named_with_its_row_and_season(self):
        def edit(got):
            got["rows"][1]["cells"][2] = "0.26 in on Jun 5, 2023"
        problems = self.smoke.summary_problems("sheet", self.want(), self.sheet(self.want(), edit))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("'Largest hail reported within 5 miles'", problems[0])
        self.assertIn("2022-23", problems[0])
        self.assertIn("'0.25 in on Jun 5, 2023'", problems[0])

    def test_a_season_cell_without_its_coverage_line_is_named(self):
        def edit(got):
            got["rows"][1]["cells"][1] = "No NWS local storm report of hail within 5 miles in 2021-22; reports are not a complete record."
        problems = self.smoke.summary_problems("sheet", self.want(), self.sheet(self.want(), edit))
        self.assertTrue(any("2021-22" in p and "108 days missing" in p for p in problems), problems)

    def test_a_row_without_its_kind_word_or_unit_is_named(self):
        def no_kind(got):
            got["rows"][1]["text"] = got["rows"][1]["text"].replace("Report", "")
        problems = self.smoke.summary_problems("sheet", self.want(), self.sheet(self.want(), no_kind))
        self.assertTrue(any("does not show its kind word 'Report'" in p for p in problems), problems)

        def no_unit(got):
            got["rows"][3]["text"] = got["rows"][3]["text"].replace(" F ", " ")
            got["rows"][3]["cells"] = [c.replace(" F", "") for c in got["rows"][3]["cells"]]
        problems = self.smoke.summary_problems("sheet", self.want(), self.sheet(self.want(), no_unit))
        self.assertTrue(any("does not show its unit (degrees Fahrenheit)" in p for p in problems), problems)

    def test_a_missing_row_and_a_missing_table_are_named(self):
        def drop(got):
            del got["rows"][3]
        problems = self.smoke.summary_problems("sheet", self.want(), self.sheet(self.want(), drop))
        self.assertTrue(any("no row labelled 'Highest temperature'" in p for p in problems), problems)
        self.assertEqual(len(self.smoke.summary_problems("sheet", self.want(), {"present": False})), 1)

    def test_a_missing_line_is_named(self):
        def lines(got):
            got["body"] = got["body"].replace("Preliminary grid estimate", "")
        problems = self.smoke.summary_problems("sheet", self.want(), self.sheet(self.want(), lines))
        self.assertTrue(any("partial line" in p for p in problems), problems)

    def test_the_table_must_start_inside_the_first_screen_below_the_address_lines(self):
        want = self.want()
        self.assertEqual(self.smoke.first_screen_problems("sheet", self.sheet(want)), [])

        def low(got):
            got["table"]["top"] = 900
        self.assertTrue(any("outside the first screen" in p
                            for p in self.smoke.first_screen_problems("sheet", self.sheet(want, low))))

        def first(got):
            got["first_row"] = {"top": 830, "bottom": 880}
        self.assertTrue(any("first row is not inside" in p
                            for p in self.smoke.first_screen_problems("sheet", self.sheet(want, first))))

        def above(got):
            got["above_bottom"] = 360
        self.assertTrue(any("address lines and the live line come first" in p
                            for p in self.smoke.first_screen_problems("sheet", self.sheet(want, above))))

        def sideways(got):
            got["viewport"]["scrollW"] = 420
        self.assertTrue(any("runs sideways" in p for p in self.smoke.first_screen_problems("sheet", self.sheet(want, sideways))))

    def test_a_file_a_tap_fetches_is_held_to_the_budget_map_json_carries(self):
        """D66, D75(c): the limit is map.json's hail.budget.tile_events_gzip_bytes (100,000 bytes gzip), never a literal."""
        self.assertEqual(self.smoke.map_budget({"hail": {"budget": {"tile_events_gzip_bytes": 100_000}}}, "tile_events_gzip_bytes"),
                         100_000)
        self.assertIsNone(self.smoke.map_budget({"hail": {}}, "tile_events_gzip_bytes"))
        self.assertIsNone(self.smoke.map_budget({"hail": {"budget": {"tile_events_gzip_bytes": True}}}, "tile_events_gzip_bytes"))
        problems = self.smoke.fetch_problems("tap", {"/hail/c/a.json": 99_999, "/hail/tl/b.json": 100_000}, 100_000)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("/hail/tl/b.json", problems[0])
        self.assertIn("100000-byte limit", problems[0])

    def test_a_tap_is_measured_against_the_limit_the_build_wrote(self):
        body = os.urandom(20_000)
        size = self.smoke.gzip_size(body)
        def real(problems):
            return [p for p in problems if not p.startswith(self.smoke.NOTE)]
        at_limit = self.smoke.tap_problems("tap", [FakeResponse("c/t.json", body)], size)
        self.assertEqual(len(real(at_limit)), 1, at_limit)          # at the limit is over it (the rule is under)
        self.assertIn("/hail/c/t.json", real(at_limit)[0])
        self.assertEqual(real(self.smoke.tap_problems("tap", [FakeResponse("c/t.json", body)], size + 1)), [])
        # without a budget in map.json the sizes are not compared here; check_summary names the missing budget once
        self.assertEqual(real(self.smoke.tap_problems("tap", [FakeResponse("c/t.json", body)], None)), [])
        missing = real(self.smoke.tap_problems("tap", [FakeResponse("c/t.json", b"", 404)], size))
        self.assertEqual(len(missing), 1, missing)
        self.assertIn("c/t.json did not answer 200 OK", missing[0])

    def test_the_unit_and_the_cells_nouns_are_read_from_a_row(self):
        spec = self.sm.UNIT_SPEC
        self.assertTrue(self.smoke.unit_shown("in", "Radar estimate 0.25 in on Jun 5, 2023", spec))
        self.assertTrue(self.smoke.unit_shown("F", "Highest temperature 94.6 F", spec))
        self.assertTrue(self.smoke.unit_shown("count", "Hail reports 3 hail reports", spec))
        self.assertTrue(self.smoke.unit_shown("days", "1 day at Lima", spec))
        self.assertFalse(self.smoke.unit_shown("count", "nothing here", spec))
        self.assertTrue(self.smoke.unit_shown("reason", "Lightning", spec))

    def test_a_cell_is_found_in_order_only_when_it_reads_exactly_its_words_and_line(self):
        """D75(b): the cell's Python words and its coverage line, nothing before or after them; white space is folded."""
        cells = ["Label", "1 day", "1 day 3 days missing", "1 day with more", "0 days", "1 day  3 days  missing"]
        self.assertEqual(self.smoke.find_cell(cells, 1, "1 day", None), 1)
        self.assertIsNone(self.smoke.find_cell(cells, 2, "1 day", None))           # the others carry more words
        self.assertEqual(self.smoke.find_cell(cells, 1, "1 day", "3 days missing"), 2)
        self.assertEqual(self.smoke.find_cell(cells, 3, "1 day", "3 days missing"), 5)
        self.assertIsNone(self.smoke.find_cell(cells, 1, "1 day", "9 days missing"))
        self.assertIsNone(self.smoke.find_cell(cells, 1, "1 day with", None))      # a prefix is not the cell's words

    def test_words_added_to_a_correct_cell_are_named(self):
        """D75(b): a season or five-season cell with the Python words and other words is not the cell."""
        def appended(got):
            got["rows"][1]["cells"][2] = "0.25 in on Jun 5, 2023 and 1.00 in on Jun 14, 2025"
        problems = self.smoke.summary_problems("sheet", self.want(), self.sheet(self.want(), appended))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("2022-23", problems[0])
        self.assertIn("does not show exactly", problems[0])

        def coverage_twice(got):
            got["rows"][1]["cells"][1] = ("No NWS local storm report of hail within 5 miles in 2021-22; reports are not a "
                                          "complete record. 108 days missing 1 day missing")
        problems = self.smoke.summary_problems("sheet", self.want(), self.sheet(self.want(), coverage_twice))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("2021-22", problems[0])

        def five(got):
            got["rows"][1]["cells"][-1] = "1.00 in on Jun 14, 2025 108 days missing and more"
        problems = self.smoke.summary_problems("sheet", self.want(), self.sheet(self.want(), five))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("Five seasons", problems[0])

    def test_the_phone_view_files_are_sorted_into_their_parts(self):
        self.assertEqual(self.smoke.layer_part("http://127.0.0.1:1/map/frames/precip-1.png"), "frames")
        self.assertEqual(self.smoke.layer_part("http://127.0.0.1:1/hail/b/t.json"), "B3 files")
        self.assertEqual(self.smoke.layer_part("http://127.0.0.1:1/hail/live/hail-60.json"), "B4 live files")
        self.assertEqual(self.smoke.layer_part("http://127.0.0.1:1/hail/c/t.json"), "B5 history files")
        self.assertEqual(self.smoke.layer_part("http://127.0.0.1:1/data/map.json"), "shell and data")

    def test_the_three_spots_are_the_billings_cell_and_the_two_named_cells(self):
        hs = self.smoke.hail_store()
        data = {"towns": [{"name": "Billings", "lat": 45.7833, "lon": -108.5007}]}
        spots = dict(self.smoke.summary_spots(data))
        self.assertEqual(spots["Billings"], hs.cell_for(45.7833, -108.5007))
        self.assertEqual(spots["Benchland cell 792,1998"], (792, 1998))
        self.assertEqual(spots["the gate cell 797,1986"], (797, 1986))

    def test_the_build_time_is_read_as_utc(self):
        self.assertEqual(self.smoke.map_now({"now": "2026-10-24T01:36:00Z"}),
                         datetime(2026, 10, 24, 1, 36, tzinfo=timezone.utc))
        self.assertEqual(self.smoke.norm(" a \n  b\tc "), "a b c")

    def test_a_console_error_names_the_file_it_is_about(self):
        """F-14: a 404 in the console is traced to its file by the location Playwright gives."""
        class Message:
            def __init__(self, text, location):
                self.text, self.location = text, location
        message = Message("Failed to load resource: the server responded with a status of 404 (File not found)",
                          {"url": "http://127.0.0.1:1/hail/tl/r0079_c0198.json", "lineNumber": 0, "columnNumber": 0})
        self.assertEqual(self.smoke.console_error(message),
                         "console: Failed to load resource: the server responded with a status of 404 (File not found) "
                         "(http://127.0.0.1:1/hail/tl/r0079_c0198.json)")
        self.assertEqual(self.smoke.console_error(Message("boom", {})), "console: boom")
        self.assertEqual(self.smoke.console_error(Message("boom", None)), "console: boom")

    def test_the_sheet_words_come_from_the_store_given_or_the_site_copy(self):
        self.assertEqual(self.smoke.summary_store(None, Path("_site")), Path("_site"))
        self.assertEqual(self.smoke.summary_store(Path("store"), Path("_site")), Path("store"))

    def test_the_pages_check_usage_line_stands_apart_from_its_prose(self):
        lines = import_tool("smoke_pages").__doc__.splitlines()
        self.assertEqual(lines[lines.index("    python tools/smoke_pages.py _site --history") - 1], "")

    def test_an_error_on_the_first_context_is_reported_once(self):
        """F-15: the first context's errors are reported after that context, and not again after the tapped one."""
        class Page:
            def __init__(self):
                self.handlers = {}

            def on(self, event, handler):
                self.handlers.setdefault(event, []).append(handler)

            def emit(self, event, value):
                for handler in self.handlers.get(event, []):
                    handler(value)

        class Context:
            def __init__(self):
                self.page = Page()

            def new_page(self):
                return self.page

            def close(self):
                pass

        class Browser:
            def new_context(self, **options):
                return Context()

        def fake_b3_open(browser, base, width, height, allow=(), listen=None):
            ctx = Context()
            return ctx, ctx.page

        def first_page_fails(page, base, at=None):          # the ?at= context raises one script error
            page.emit("pageerror", RuntimeError("boom"))

        patches = dict(hail_open=first_page_fails, sheet_settled=lambda page, loading, seconds=15: "the sheet",
                       summary_read=lambda page: {"present": True}, first_screen_problems=lambda label, got: [],
                       sheet_read=lambda page, ids: {"summary": None, "sections": None},
                       snap=lambda page, shots, name: None, b3_open=fake_b3_open,
                       tap_centre=lambda page, lat, lon: None)
        data = {"hail": {"words": {"loading": "Loading the history"}}}
        with mock.patch.multiple(self.smoke, **patches):
            problems = self.smoke.summary_spot(Browser(), "http://127.0.0.1:1/", data, "Billings", (792, 1998), None,
                                               "phone", (390, 844), None, None)
        self.assertEqual([p for p in problems if "boom" in p], ["Billings at phone: script error: boom"], problems)

    def test_an_unreadable_store_is_named_once_and_the_sheet_checks_still_run(self):
        """F-01 and D75: a store that cannot be read is one named failure; each spot is still opened at both sizes, so the
        table's position and the tap's files are checked, with no words to compare."""
        calls = []

        def spot(browser, base, data, label, cell, want, size_name, size, shots, limit, expected=None):
            calls.append((label, size_name, want, limit))
            return []

        data = {"now": "2026-10-24T01:36:00Z", "towns": [{"name": "Billings", "lat": 45.7833, "lon": -108.5007}],
                "hail": {"summary": {"state": "loaded"}, "budget": {"tile_events_gzip_bytes": 100_000}}}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(self.smoke, "summary_spot", spot):
            problems = self.smoke.check_summary(None, "http://127.0.0.1:1/", Path(tmp), data, Path(tmp), None, True)
        self.assertEqual(len(calls), 6, calls)                              # three spots at two sizes
        self.assertTrue(all(want is None and limit == 100_000 for _, _, want, limit in calls), calls)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("cannot be read", problems[0])
        self.assertIn("still checked", problems[0])

    def test_a_build_without_a_tap_budget_is_named_once(self):
        calls = []

        def spot(browser, base, data, label, cell, want, size_name, size, shots, limit, expected=None):
            calls.append(limit)
            return []

        data = {"now": "2026-10-24T01:36:00Z", "towns": [{"name": "Billings", "lat": 45.7833, "lon": -108.5007}],
                "hail": {"summary": {"state": "loaded"}, "budget": {}}}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(self.smoke, "summary_spot", spot):
            problems = self.smoke.check_summary(None, "http://127.0.0.1:1/", Path(tmp), data, Path(tmp), None, True)
        self.assertEqual(calls, [None] * 6)
        self.assertEqual(len([p for p in problems if "tile-file budget" in p]), 1, problems)

    def test_the_phone_view_is_held_to_the_phone_budget_map_json_carries(self):
        """D66, D75: the phone view with every layer on is held to map.json's hail.budget.phone_gzip_bytes."""
        body = os.urandom(20_000)
        size = self.smoke.gzip_size(body)

        class Ctx:
            def close(self):
                pass

        class Page:
            def wait_for_timeout(self, ms):
                pass

        def run(block):
            data = {"layers": {"precip": {"title": "Radar"}}, "hail": {"budget": block}}

            def fake_b3_open(browser, base, width, height, allow=(), listen=None):
                listen(FakeResponse("c/t.json", body))            # a B5 history file: it counts in the phone view's scope
                return Ctx(), Page()

            with mock.patch.multiple(self.smoke, b3_open=fake_b3_open, b3_view=lambda *a, **k: None,
                                     pick_layer=lambda page, title: None):
                return self.smoke.check_every_layer(None, "http://127.0.0.1:1/", data)

        def real(problems):
            return [p for p in problems if not p.startswith(self.smoke.NOTE)]

        over = real(run({"phone_gzip_bytes": 10_000}))
        self.assertEqual(len(over), 1, over)
        self.assertIn("the budget is 10000", over[0])
        self.assertEqual(real(run({"phone_gzip_bytes": size + 1_000})), [])
        missing = real(run({}))
        self.assertEqual(len(missing), 1, missing)
        self.assertIn("no phone-view budget", missing[0])


class SiteCopy(unittest.TestCase):
    """D75(a): with no --store the smoke's summary reads the built site's own hail/ folder, which holds B4's live files under
    hail/live/ that the manifest never lists. The store reader skips those files and no other unlisted file."""

    @classmethod
    def setUpClass(cls):
        cls.hs = import_tool("smoke_map").hail_store()
        cls.fixture = cls.hs.FIXTURE_DIR

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.site = Path(tmp.name) / "site"
        shutil.copytree(self.fixture, self.site)

    def test_a_site_copy_with_live_files_reads_as_the_store(self):
        live = self.site / "hail" / "live" / "1440" / "202610240230" / "r0046_c0201.json"
        live.parent.mkdir(parents=True)
        live.write_text("{}", encoding="utf-8")
        self.assertEqual(self.hs.load_store(self.site), self.site)
        with self.assertRaises(self.hs.HailStoreError):     # the strict check refuses the same folder: only hail/live/ is skipped
            self.hs.check_manifest(self.site)

    def test_any_other_unlisted_file_still_refuses_the_site_copy(self):
        (self.site / "hail" / "stray.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(self.hs.HailStoreError) as caught:
            self.hs.load_store(self.site)
        self.assertIn("hail/stray.json", str(caught.exception))



class SheetReader(unittest.TestCase):
    """The round-2 sheet (B5 part B2; D75, D82, D83): the browser smoke's reader and comparisons, tested on synthetic sheets
    shaped as the page's [data-hail='summary'] and [data-hail='sections'] slots hold them. The browser itself is checked by
    tools/smoke_map.py in Chromium; these tests keep its comparisons honest without one."""

    @classmethod
    def setUpClass(cls):
        cls.smoke = import_tool("smoke_map")
        cls.ids = ["hail", "wind", "storms", "temperature", "rain", "snow", "flooding", "ice", "heat", "roof", "made"]

    def data(self, sample=False, show_first=2, joins_state="loaded"):
        """A map.json block with the eleven section ids, the joins words and the show-first rule the build writes."""
        words = {"show_all": "Show all {n} rows", "sample": "SAMPLE data"}
        return {"hail": {"summary": {"sections": list(self.ids)},
                         "joins": {"state": "sample" if sample else joins_state, "show_first": show_first, "words": words}}}

    @staticmethod
    def hail_row(words, remark=""):
        """A report of hail: its kind label, the time and its words (build.py's _section_of reads them as hail), its remark."""
        return ("Report", f"Jun 14, 2025 11:45 pm MDT: {words}", remark)

    def item(self, sid, rows=(), more=(), notes=(), lead="A lead.", heading=None, groups=(), kinds=True):
        """One section as the reader reads it: its shown rows, its rows behind 'Show all', its notes and its roof groups. The
        sentence of each kind among its rows comes first in its notes (summary.kind_what), as the browser writes them."""
        def row(label, words, note=""):
            return {"label": label, "text": words, "note": note}
        shown = [row(*r) for r in rows]
        behind = [row(*r) for r in more]
        what = self.smoke.summary_module().kind_what(town=False)
        kind_notes = [what[k] for k in dict.fromkeys(r[0] for r in list(rows) + list(more)) if k in what] if kinds else []
        notes = kind_notes + list(notes)
        text_parts = [heading or sid.title(), lead] + [r[1] for r in rows] + [r[1] for r in more] + list(notes)
        return {"id": sid, "heading": heading or sid.title(), "sample": None, "lead": lead, "rows": shown,
                "more": ({"summary": f"Show all {len(shown) + len(behind)} rows", "rows": behind} if behind else None),
                "groups": list(groups), "notes": list(notes), "text": " ".join(text_parts)}

    def sheet(self, items, notices=()):
        text = " ".join([i["text"] for i in items] + list(notices))
        return {"summary": {"notes": []}, "sections": {"hidden": False, "notices": list(notices), "text": text, "items": items}}

    def expected(self, rows):
        """describe_joins' cell: one reports part with these (label, words, remark) rows."""
        return {"sections": [{"id": "reports", "lines": [], "unavailable": None,
                              "rows": [{"text": f"{label}: {words}", "remark": remark} for label, words, remark in rows]}]}

    def test_the_reader_takes_the_round_two_slots_and_every_row_text_not_inner_text(self):
        js = self.smoke.SHEET_READ
        self.assertIn('[data-hail="summary"]', js)
        self.assertIn('[data-hail="sections"]', js)
        self.assertIn("details.hist-more", js)                 # the rows behind 'Show all' are read from the closed details
        self.assertIn("textContent", js)
        self.assertNotIn("innerText", js)                      # D83(a): innerText would leave those rows out

    def test_the_eleven_sections_must_come_in_their_fixed_order(self):
        items = [self.item(sid) for sid in self.ids]
        self.assertEqual(self.smoke.sheet_order_problems("gate", self.sheet(items), self.ids), [])
        swapped = [items[1], items[0]] + items[2:]
        problems = self.smoke.sheet_order_problems("gate", self.sheet(swapped), self.ids)
        self.assertEqual(len(problems), 1)
        self.assertIn("the fixed order is", problems[0])
        hidden = self.smoke.sheet_order_problems("gate", {"sections": {"hidden": True}}, self.ids)
        self.assertTrue(hidden[0].endswith("are hidden"), hidden)

    def test_a_joined_row_behind_show_all_is_compared_as_well(self):
        rows = [self.hail_row("hail, 1.00 in", "Remark: a"), self.hail_row("hail, 1.75 in", "Remark: b")]
        behind = [self.hail_row("hail, 0.75 in", "")]
        expected = self.expected(rows + behind)
        items = [self.item(sid, rows=rows, more=behind) if sid == "hail" else self.item(sid) for sid in self.ids]
        self.assertEqual(self.smoke.joined_problems("gate", self.sheet(items), expected, self.data()), [])
        without = [self.item(sid, rows=rows) if sid == "hail" else self.item(sid) for sid in self.ids]
        problems = self.smoke.joined_problems("gate", self.sheet(without), expected, self.data())
        self.assertTrue(any("joined rows differ at row 3" in p for p in problems), problems)

    def test_show_all_follows_the_rule_and_the_words_map_json_gives(self):
        rows = [self.hail_row("hail, 1.00 in"), self.hail_row("hail, 1.10 in")]
        behind = [self.hail_row("hail, 1.20 in"), self.hail_row("hail, 1.30 in")]
        expected = self.expected(rows + behind)
        items = [self.item(sid, rows=rows, more=behind) if sid == "hail" else self.item(sid) for sid in self.ids]
        self.assertEqual(self.smoke.joined_problems("gate", self.sheet(items), expected, self.data()), [])
        wrong = [dict(i) for i in items]
        wrong[0] = dict(items[0], more=dict(items[0]["more"], summary="Show all 9 rows"))
        self.assertTrue(any("reads 'Show all 9 rows'" in p for p in self.smoke.joined_problems(
            "gate", self.sheet(wrong), expected, self.data())))
        unshown = [self.item(sid, rows=rows + behind) if sid == "hail" else self.item(sid) for sid in self.ids]
        self.assertTrue(any("shows 4 rows before 'Show all', the rule is 2 of 4" in p for p in self.smoke.joined_problems(
            "gate", self.sheet(unshown), expected, self.data())))

    def test_a_line_and_an_unavailable_sentence_of_the_cell_must_be_on_the_sheet(self):
        expected = {"sections": [{"id": "stations", "rows": [], "lines": ["1 reading of 130 kt or more was left out."],
                                  "unavailable": "Station data could not be loaded. This is not an all-clear."}]}
        items = [self.item(sid) for sid in self.ids]
        problems = self.smoke.joined_problems("gate", self.sheet(items), expected, self.data())
        self.assertTrue(any("lacks the line" in p for p in problems), problems)
        self.assertTrue(any("unavailable sentence" in p for p in problems), problems)
        notices = ["Station data could not be loaded. This is not an all-clear."]
        ok = [self.item(sid, notes=["1 reading of 130 kt or more was left out."]) if sid == "wind" else self.item(sid)
              for sid in self.ids]
        self.assertEqual(self.smoke.joined_problems("gate", self.sheet(ok, notices), expected, self.data()), [])

    def test_a_section_shows_the_kind_sentence_of_each_kind_among_its_rows(self):
        what = self.smoke.summary_module().kind_what(town=False)["Report"]
        rows = [self.hail_row("hail, 1.00 in")]
        expected = self.expected(rows)
        bare = [self.item(sid, rows=rows, kinds=False) if sid == "hail" else self.item(sid) for sid in self.ids]
        self.assertTrue(any("lacks the sentence for Report" in p for p in self.smoke.joined_problems(
            "gate", self.sheet(bare), expected, self.data())))
        with_what = [self.item(sid, rows=rows) if sid == "hail" else self.item(sid) for sid in self.ids]
        self.assertIn(what, with_what[0]["notes"])
        self.assertEqual(self.smoke.joined_problems("gate", self.sheet(with_what), expected, self.data()), [])

    def test_the_sections_match_describe_summary_for_the_same_cell(self):
        want = {"sections": [{"id": sid, "heading": sid.title(), "lead": "A lead.", "notes": ["A note."] if sid == "wind" else []}
                             for sid in self.ids],
                "table": {"rows": [{"key": "gust_max", "label": "Strongest gust", "notes": ["A table note."]}]},
                "how_made": ["Source: one.", "Source: two."],
                "roof": {"how_made": ["Roof line note."], "groups": [{
                    "name": "Thresholds", "lines": [{"text": "Days of hail: 3."}],
                    "references": [{"kind": "Reference", "text": "NWS: quote."}], "held": [{"text": "Lightning: Data unavailable."}]}]}}
        roof_item = self.item("roof", notes=["Roof line note."], groups=[{
            "name": "Thresholds", "lines": ["Days of hail: 3."], "refs": ["Reference: NWS: quote."],
            "held": ["Lightning: Data unavailable."]}])
        made = self.item("made", notes=["Source: one.", "Source: two."])
        items = [self.item(sid, notes=["A note.", "A table note."] if sid == "wind" else ()) for sid in self.ids[:9]]
        items += [roof_item, made]
        sheet = self.sheet(items)
        sheet["summary"] = {"notes": ["A table note."]}
        self.assertEqual(self.smoke.sections_problems("gate", want, sheet, self.ids), [])
        self.assertEqual(self.smoke.table_notes_problems("gate", want, sheet["summary"]), [])
        bad_items = [dict(i) for i in items]
        bad_items[1] = dict(items[1], heading="Wind speeds", lead="Another lead.")
        bad_items[9] = dict(roof_item, groups=[dict(roof_item["groups"][0], lines=["Days of hail: 4."])])
        problems = self.smoke.sections_problems("gate", want, self.sheet(bad_items), self.ids)
        self.assertTrue(any("heading on the sheet is 'Wind speeds'" in p for p in problems), problems)
        self.assertTrue(any("lead on the sheet" in p for p in problems), problems)
        self.assertTrue(any("roof group 'Thresholds' shows its lines differently at line 1" in p for p in problems), problems)
        missing_note = self.smoke.table_notes_problems("gate", want, {"notes": []})
        self.assertEqual(missing_note, ["gate: the table's notes lack 'A table note.' (Strongest gust)"])

    def test_the_sample_word_is_on_each_of_the_eleven_sections_of_a_sample_build_only(self):
        sample_data = self.data(sample=True)
        store_data = self.data(sample=False)
        sheet = {"sections": {"items": [{"id": sid, "text": "SAMPLE data " + sid} for sid in self.ids]}}
        self.assertEqual(self.smoke.check_sample_labels(sheet, sample_data, "gate"), [])
        missing = {"sections": {"items": [{"id": sid, "text": "SAMPLE data"} for sid in self.ids[:-1]]}}
        self.assertTrue(any("the made section is missing" in p for p in self.smoke.check_sample_labels(
            missing, sample_data, "gate")))
        unlabelled = {"sections": {"items": [{"id": sid, "text": "" if sid == "heat" else "SAMPLE data"} for sid in self.ids]}}
        self.assertEqual(self.smoke.check_sample_labels(unlabelled, sample_data, "gate"),
                         ["gate: the heat section of a sample build does not say 'SAMPLE data'"])
        says = {"sections": {"items": [{"id": sid, "text": "SAMPLE data" if sid == "rain" else "x"} for sid in self.ids]}}
        self.assertEqual(self.smoke.check_sample_labels(says, store_data, "gate"),
                         ["gate: the rain section of a store build says 'SAMPLE data'"])

    def test_the_history_run_needs_the_address_layer_and_fails_with_one_readable_line(self):
        full = {"hail": {"addresses": {}, "roads": {}, "buildings": {}, "summary": {}}}
        self.assertIsNone(self.smoke.history_problem(full))
        no_addresses = {"hail": {"summary": {}}}
        message = self.smoke.history_problem(no_addresses)
        self.assertIn("the build has no address layer", message)
        self.assertIn("--hail-addresses", message)
        self.assertIn("addresses, roads, buildings", message)
        self.assertEqual(self.smoke.history_problem({"layers": {}}), "the build has no five-season history (no hail data in "
                         "map.json): build with --hail-history")
        import json
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / "data").mkdir()
            (site / "data" / "map.json").write_text(json.dumps(no_addresses), encoding="utf-8")
            self.assertEqual(self.smoke.check(site, history=True), [message])     # one line; no browser is started for it


def reads_parity_store(node) -> bool:
    """Whether a test reads HAIL_PARITY_STORE from the environment (os.environ.get or os.environ[...]), in its body or its
    decorators (ast.walk visits both). A text that only mentions the name, such as a workflow pin, does not count."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "get" \
                and isinstance(sub.func.value, ast.Attribute) and sub.func.value.attr == "environ" and sub.args \
                and isinstance(sub.args[0], ast.Constant) and sub.args[0].value == "HAIL_PARITY_STORE":
            return True
        if isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Attribute) and sub.value.attr == "environ" \
                and isinstance(sub.slice, ast.Constant) and sub.slice.value == "HAIL_PARITY_STORE":
            return True
    return False


def gated_parity_tests() -> set[str]:
    """The dotted names of every test method in tests/test_site.py and tests/test_summary.py that reads HAIL_PARITY_STORE
    (reads_parity_store): the tests the Website workflow's parity step names one by one (D88(a))."""
    found: set[str] = set()
    for module in ("test_site", "test_summary"):
        source = (ROOT / "tests" / f"{module}.py").read_text(encoding="utf-8")
        for node in ast.parse(source).body:
            if not isinstance(node, ast.ClassDef):
                continue
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name.startswith("test_") and reads_parity_store(fn):
                    found.add(f"tests.{module}.{node.name}.{fn.name}")
    return found


class ParityStep(unittest.TestCase):
    """D88(a), F-14: the real-store parity tests run on branch pushes, after the build, against the site's own copy of the store
    (HAIL_PARITY_STORE=_site). The step fails when that copy has no tile lists and when a gated test skips, and it names exactly
    the gated tests of the two modules, so a new or renamed gated test cannot drop out of the step silently."""

    @classmethod
    def setUpClass(cls):
        cls.doc = yaml.safe_load((ROOT / ".github/workflows/website.yml").read_text(encoding="utf-8"))
        cls.steps = cls.doc["jobs"]["build"]["steps"]
        cls.names = [step.get("name") for step in cls.steps]

    def step(self, prefix: str) -> dict:
        found = [step for step in self.steps if (step.get("name") or "").startswith(prefix)]
        self.assertEqual(len(found), 1, prefix)
        return found[0]

    def test_the_step_follows_the_build_and_runs_on_branch_pushes_only(self):
        parity = self.step("Real-store parity tests")
        self.assertEqual(self.names.index(parity["name"]), self.names.index("Build from live data") + 1)
        self.assertLess(self.names.index(parity["name"]), self.names.index("Map smoke test in a real browser (branch pushes)"))
        self.assertEqual(parity["if"], "steps.plan.outputs.run == 'true' && github.ref != 'refs/heads/main'")

    def test_the_step_reads_the_site_copy_and_fails_without_its_tile_lists_or_on_a_skip(self):
        parity = self.step("Real-store parity tests")
        self.assertEqual(parity["env"], {"HAIL_PARITY_STORE": "_site"})
        self.assertIn("if [ ! -d _site/hail/tl ]; then", parity["run"])
        self.assertIn("exit 1", parity["run"])
        self.assertIn("if grep -q '(skipped=' parity.log; then", parity["run"])
        self.assertNotIn("--hail-store", parity["run"])

    def test_the_step_names_exactly_the_gated_tests_of_the_two_modules(self):
        parity = self.step("Real-store parity tests")
        named = set(re.findall(r"tests\.test_(?:site|summary)\.\w+\.test_\w+", parity["run"]))
        self.assertEqual(named, gated_parity_tests())
        self.assertEqual(len(named), 7, named)

    def test_the_offline_step_passes_no_parity_store(self):
        self.assertNotIn("HAIL_PARITY_STORE", str(self.step("Website tests (offline)")))

    def test_the_build_job_timeout_leaves_room_for_the_step(self):
        self.assertGreaterEqual(self.doc["jobs"]["build"]["timeout-minutes"], 25)


class FakeFramePage:
    """The few page calls the swath spot helpers make: the frame picture's box, the free centre the grid finds, the test hook's
    pan, and a zoom that the wheel steps (2.5 levels each, as map.js sets them) move."""

    class Mouse:
        def __init__(self, page):
            self.page = page

        def move(self, x, y):
            pass

        def wheel(self, dx, dy):
            self.page.wheels += 1
            self.page.zoom = min(17.0, self.page.zoom + 2.5)

    class Clock:
        def run_for(self, ms):
            pass

    def __init__(self, smoke, free=None, zoom: float = 0.0):
        self.smoke, self.free, self.zoom, self.wheels, self.pans = smoke, free, zoom, 0, []
        self.mouse, self.clock = self.Mouse(self), self.Clock()

    def locator(self, selector):
        page = self

        class Frame:
            @property
            def first(self):
                return self

            def bounding_box(self):
                return {"x": 0.0, "y": 0.0, "width": 390.0, "height": 844.0}
        return Frame()

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js, arg=None):
        if js == self.smoke.FREE_POINTS_JS:
            return [list(point) for point in self.free]
        if "hailMapTest.pan" in js:
            self.pans.append(list(arg))
            return None
        if "img.leaflet-image-layer.frame" in js:            # map_zoom: the frame picture's width on the screen
            return 256 * 2 ** self.zoom * (-104.0 + 117.0) / 360
        return None


class SmokeRowsAndBudgets(unittest.TestCase):
    """The browser smoke's rules that need no browser (S-1 to S-5, D87(g), D88): the readers take the text a reader sees, every row
    of every section is compared with the one Python source, the eleven section ids come from the summary's constant, the swath
    spot is zoomed to the gate's floor and panned to the visible centre before it is read, and the B3 phone view is held to
    map.json's phone budget."""

    @classmethod
    def setUpClass(cls):
        cls.smoke = import_tool("smoke_map")
        cls.sm = cls.smoke.summary_module()
        cls.ids = list(cls.sm.SECTION_ORDER)

    def test_the_readers_take_the_text_a_reader_sees_and_never_inner_text(self):
        """D83(a), S-2, F-02: the rows behind 'Show all' are in the text the sheet readers take, so none of them uses innerText."""
        smoke = self.smoke
        for js in (smoke.SHEET_BODY_JS, smoke.SUMMARY_READ, smoke.SHEET_READ, smoke.READ_TEXT_JS):
            self.assertNotIn("innerText", js)
        self.assertIn("readText(document.getElementById('sheet-body'", smoke.SHEET_BODY_JS)
        for func in (smoke.sheet_settled, smoke.sheet_text, smoke.check_hail):
            self.assertNotIn("innerText", inspect.getsource(func))
            self.assertNotIn("inner_text(", inspect.getsource(func))

    def test_the_eleven_section_ids_are_the_summary_constant_and_map_json_must_agree(self):
        """S-5, D88(i): the smoke's ids are website.summary.SECTION_ORDER; map.json's section order and sections must equal it."""
        self.assertEqual(self.smoke.section_order(), list(self.sm.SECTION_ORDER))
        self.assertEqual(len(self.smoke.section_order()), 11)
        good = {"hail": {"summary": {"state": "loaded", "section_order": list(self.sm.SECTION_ORDER),
                                     "sections": list(self.sm.SECTION_ORDER)}}}
        self.assertEqual(self.smoke.section_order_problems(good), [])
        short = {"hail": {"summary": {"state": "loaded", "section_order": list(self.sm.SECTION_ORDER)[:10],
                                      "sections": list(self.sm.SECTION_ORDER)}}}
        problems = self.smoke.section_order_problems(short)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("hail.summary.section_order", problems[0])
        self.assertEqual(self.smoke.section_order_problems({"hail": {"summary": {"state": "unavailable"}}}), [])

    def test_the_sheet_words_come_from_describe_sheet_with_its_built_rows(self):
        """D88(p): the smoke's one source is summary.describe_sheet, and its built rows travel with its summary."""
        built = {"rows": {"hail": [{"label": "Radar estimate", "text": "x", "note": ""}]}, "notes": {}}
        fake = {"summary": {"table": {"rows": []}, "sections": []}, "built": built, "section_order": list(self.ids)}
        with mock.patch.object(self.sm, "describe_sheet", lambda store, row, col, now: fake, create=True), \
                mock.patch.object(self.sm, "describe_summary", lambda *a, **k: self.fail("describe_summary was used")):
            words = self.smoke.sheet_words(Path("store"), 797, 1986, None)
        self.assertEqual(self.smoke.python_rows(words, "hail"), [("Radar estimate", "x", "")])
        self.assertIsNone(self.smoke.python_rows(words, "wind"))

    def test_every_row_of_every_section_is_compared_with_the_python_source(self):
        """S-4, D87(g), D88(p): the rows shown and the rows behind 'Show all', of every section, against the one Python source. No
        label list selects them, so a season row and a radar row are compared as a joined row is."""
        season = ("Grid estimate", "highest 94.6 F on Jul 19, 2021; lowest 40.1 F on Jan 3, 2022", "")
        radar = ("Radar estimate", "Jul 4, 2022: 0.34 in (8.7 mm), pea to mothball", "")
        joined = ("Report", "Jun 14, 2025 11:45 pm MDT: hail, 1.00 in", "Remark: a")
        shown, behind = [season, radar, joined], [("Radar estimate", "Jun 14, 2025: 1.20 in (30.5 mm), golf ball", "")]
        items = [self.item_for(sid, shown, behind) for sid in self.ids]
        as_rows = lambda triples: [{"label": label, "text": text, "note": note} for label, text, note in triples]  # noqa: E731
        want = {"rows_by_section": {sid: as_rows(shown + behind) if sid == "hail" else [] for sid in self.ids}}
        self.assertEqual(self.smoke.sheet_rows_problems("gate", want, {"sections": {"items": items}}, self.ids), [])

        changed = [dict(items[0], rows=[dict(items[0]["rows"][0], text="highest 95.0 F on Jul 19, 2021; lowest 40.1 F on Jan 3, 2022")]
                   + items[0]["rows"][1:])] + items[1:]
        problems = self.smoke.sheet_rows_problems("gate", want, {"sections": {"items": changed}}, self.ids)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("the hail section's rows differ at row 1 (4 on the sheet, 4 from the Python source)", problems[0])

        behind_changed = [dict(items[0], more=dict(items[0]["more"], rows=[dict(items[0]["more"]["rows"][0],
                                                                                 text="Jun 14, 2025: 1.30 in (33.0 mm), golf ball")]))] + items[1:]
        problems = self.smoke.sheet_rows_problems("gate", want, {"sections": {"items": behind_changed}}, self.ids)
        self.assertTrue(any("rows differ at row 4" in p for p in problems), problems)

        missing = {"rows_by_section": {sid: rows for sid, rows in want["rows_by_section"].items() if sid != "wind"}}
        problems = self.smoke.sheet_rows_problems("gate", missing, {"sections": {"items": items}}, self.ids)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("gives no rows for the wind section", problems[0])

    def item_for(self, sid, shown, behind):
        """One section as the reader reads it (the same shape SheetReader builds)."""
        def row(triple):
            label, text, note = triple
            return {"label": label, "text": text, "note": note}
        rows = [row(t) for t in shown] if sid == "hail" else []
        more = [row(t) for t in behind] if sid == "hail" and behind else []
        return {"id": sid, "heading": sid.title(), "sample": None, "lead": "A lead.", "rows": rows,
                "more": ({"summary": f"Show all {len(rows) + len(more)} rows", "rows": more} if more else None),
                "groups": [], "notes": [], "text": ""}

    def test_the_swath_spot_is_panned_to_the_visible_centre_before_it_is_read(self):
        """S-3, D88(h): the spot moves to the centre of the part of the map no panel covers. The test hook's pan moves the view the
        other way, so the offset is the spot's place less the centre's."""
        data = {"image_bounds": [[44.0, -117.0], [49.0, -104.0]]}
        # two bands of free points around a card: their centre (198, 387) is on the card, so the free point nearest it is taken
        page = FakeFramePage(self.smoke, free=[(100.0, 300.0), (195.0, 430.0), (300.0, 430.0)], zoom=11.5)
        before = self.smoke.map_pixel(page, data, 45.8, -108.5)
        after = self.smoke.centre_on_spot(page, data, 45.8, -108.5)
        self.assertEqual(page.pans, [[before[0] - 195.0, before[1] - 430.0]])
        self.assertEqual(after, before)                     # this fake frame does not move: the spot reads where it was

    def test_the_swath_zoom_stops_at_the_gate_floor_and_takes_no_step_it_does_not_need(self):
        """S-3, D88(h): the wheel stops at GATE_MIN_ZOOM. A map that is there takes no step; one step from 9 reaches it."""
        data = {"image_bounds": [[44.0, -117.0], [49.0, -104.0]]}
        for start, steps in ((9.0, 1), (10.0, 0), (4.0, 3)):
            page = FakeFramePage(self.smoke, zoom=start)
            self.smoke.zoom_on_spot(page, data, 45.8, -108.5)
            self.assertEqual(page.wheels, steps, start)
            self.assertGreaterEqual(page.zoom, self.smoke.GATE_MIN_ZOOM - 0.05, start)
            self.assertLess(page.zoom, self.smoke.GATE_MIN_ZOOM + 2.5, start)      # at most one step past the floor

    def test_the_b3_phone_view_is_held_to_the_phone_budget_map_json_carries(self):
        """S-1, D82(b), D88(h): the B3 files and the shell of the 390 px view are held to hail.budget.phone_gzip_bytes, the same
        budget the whole phone view is held to; with no budget in map.json the check names it."""
        body = os.urandom(20_000)
        size = self.smoke.gzip_size(body)

        class Ctx:
            def close(self):
                pass

        class Page:
            def wait_for_timeout(self, ms):
                pass

            def evaluate(self, js, arg=None):
                return [] if ("fetches" in js or "draws" in js) else None

        def run(block):
            data = {"hail": {"budget": block}}

            def fake_b3_open(browser, base, width, height, allow=(), listen=None):
                if listen:
                    listen(FakeResponse("b/t.json", body))         # an outline file: a B3 file in the view's scope
                return Ctx(), Page()

            with mock.patch.multiple(self.smoke, b3_open=fake_b3_open, b3_view=lambda *a, **k: None):
                return self.smoke.check_budget_and_pan(None, "http://127.0.0.1:1/", data)

        def real(problems):
            return [p for p in problems if not p.startswith(self.smoke.NOTE)]

        over = real(run({"phone_gzip_bytes": 10_000}))
        self.assertEqual(len(over), 1, over)
        self.assertIn("the budget is 10000", over[0])
        self.assertEqual(real(run({"phone_gzip_bytes": size + 1_000})), [])
        missing = real(run({}))
        self.assertEqual(len(missing), 1, missing)
        self.assertIn("no phone-view budget", missing[0])
