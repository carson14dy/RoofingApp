"""Execute the workflow's planning shell with a fake GitHub CLI, without network."""

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


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
        unit = [line for line in self.text.splitlines() if "python -m unittest" in line]
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
        unit = [line for line in self.text.splitlines() if "python -m unittest" in line]
        self.assertEqual(len(unit), 1)
        self.assertIn("tests.test_satellite", unit[0].split())
        self.assertIn('"tests/test_satellite.py"', self.text)
