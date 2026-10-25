"""The hail store job (.github/workflows/hail-store.yml, D26, D35, D38): the B5 steps share one clock and are killed at
the seconds left, every non-fatal step has a timeout, the joins are fatal with a backstop of 1.5 times JOINS_DEADLINE_S
(53 minutes, D75), the climate archive is published under a versioned name without --clobber, the older archives are
removed only after the new one unpacks, the restore takes the newest archive, and the store asset keeps the name the site
build reads.

The job file is read as text: each step starts with a "      - name:" line and its keys sit at eight spaces, which is how
the file is written. The checks are the file's own text, so they hold for the file as committed. The YAML parse (PyYAML,
installed by the Website workflow's Install step for its tests) checks that both workflow files parse and that the
timeouts the text sets are the ones the parse reads. No network, no workflow run."""

import math
import re
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import hail as h  # noqa: E402
from website import joins as J  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "hail-store.yml"
CLOCK_START = "Seconds left on the B5 clock before the readers"
PACK = "Pack the store"
B5_LAST = "Verify the station, gauge and snow parts (informational; the index says what did not load)"
B3_FIRST = "Read the framework file's size and date from the MSL server (non-fatal; D20)"
PROGRAM = re.compile(r"(?<![\w.-])(gh|python|pip|jq|tar)\s")


class Step:
    def __init__(self, name, lines):
        self.name = name
        self.lines = lines

    def attr(self, key):
        for line in self.lines:
            match = re.match(r"^        " + re.escape(key) + r":(?: (.*))?$", line)
            if match:
                return (match.group(1) or "").strip()
        return None

    def env(self):
        out, inside = {}, False
        for line in self.lines:
            if re.match(r"^        env:\s*$", line):
                inside = True
                continue
            if inside:
                match = re.match(r"^          ([A-Z_]+): (.*)$", line)
                if match:
                    out[match.group(1)] = match.group(2)
                elif line.strip() and not line.startswith("          "):
                    inside = False
        return out

    def run(self):
        """The run text: a single line, or the lines of a block scalar (ten spaces in, the indent removed)."""
        out, found = [], False
        for line in self.lines:
            if not found:
                match = re.match(r"^        run:(?: (.*))?$", line)
                if match:
                    found = True
                    rest = (match.group(1) or "").strip()
                    if rest and rest != "|":
                        out.append(rest)
                continue
            if line.startswith("          "):
                out.append(line[10:])
            elif not line.strip():
                out.append("")
            else:
                break
        return "\n".join(out).rstrip("\n") if found else None


def job_steps(text):
    steps, current = [], None
    for line in text.splitlines():
        match = re.match(r"^      - name: (.*)$", line)
        if match:
            current = (match.group(1), [])
            steps.append(current)
        elif current is not None and line and not line[0].isspace() and not line.startswith("#"):
            current = None
        elif current is not None:
            current[1].append(line)
    return [Step(name, lines) for name, lines in steps]


class HailStoreJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        head, _, rest = cls.text.partition("\n  store:\n")
        store_part, _, monthly_part = rest.partition("\n  monthly:\n")
        cls.plan_steps = job_steps(head)
        cls.steps = job_steps(store_part)              # the daily job: the B1, B2 and B5 steps
        cls.monthly_steps = job_steps(monthly_part)    # the monthly job (D42)
        cls.names = [s.name for s in cls.steps]

    def step(self, prefix):
        found = [s for s in self.steps if s.name.startswith(prefix)]
        self.assertEqual(len(found), 1, f"one step named {prefix!r}")
        return found[0]

    def monthly_step(self, prefix):
        found = [s for s in self.monthly_steps if s.name.startswith(prefix)]
        self.assertEqual(len(found), 1, f"one monthly step named {prefix!r}")
        return found[0]

    def b5_steps(self):
        """The non-clock steps between the first B5 clock and the last B5 step, in order. The B3 address, street and
        outline steps follow the last B5 step (D51): they are not on the B5 clock, and their own file checks them."""
        start = self.names.index(CLOCK_START)
        end = self.names.index(B5_LAST) + 1
        return [s for s in self.steps[start:end] if not s.name.startswith("Seconds left on the B5 clock")]

    def test_the_text_has_no_double_equals_and_no_em_dash(self):
        self.assertNotIn("==", self.text)
        self.assertNotIn(chr(0x2014), self.text)

    def test_the_daily_job_is_capped_at_150_minutes_and_the_monthly_job_at_60(self):
        # D50: the daily job's cap is B5's 60 plus B3's 90 until the branch run measures it; the monthly job keeps its 60
        self.assertIn("    timeout-minutes: 150\n    steps:\n", self.text)
        self.assertIn("    timeout-minutes: 60\n    steps:\n", self.text)
        doc = yaml.safe_load(self.text)
        self.assertEqual(doc["jobs"]["store"]["timeout-minutes"], 150)
        self.assertEqual(doc["jobs"]["monthly"]["timeout-minutes"], 60)
        self.assertEqual(doc["jobs"]["plan"]["timeout-minutes"], 5)

    def test_the_join_is_fatal_and_its_timeout_is_above_the_joins_deadline(self):
        join = self.step("Join reports, records")
        self.assertIsNone(join.attr("continue-on-error"), "the join stays fatal (the B2 rule)")
        self.assertIsNotNone(join.attr("timeout-minutes"))
        self.assertGreater(int(join.attr("timeout-minutes")) * 60, J.JOINS_DEADLINE_S)
        # D75(d): the step stops at JOINS_DEADLINE_S, so its backstop is 1.5 times that deadline, rounded up to whole minutes
        self.assertEqual(join.attr("timeout-minutes"), str(math.ceil(1.5 * J.JOINS_DEADLINE_S / 60)))
        self.assertEqual(join.attr("timeout-minutes"), "53")

    def test_the_comments_name_the_150_minute_job_cap(self):
        # F-12: the store job's cap is 150 minutes (its timeout-minutes line), and the comments that name the cap say so
        self.assertIn("    timeout-minutes: 150\n    steps:\n", self.text)
        self.assertNotIn("60-minute job cap", self.text)
        self.assertIn("150-minute job cap binds", self.text)

    def test_the_b1_and_b2_verify_steps_stay_fatal(self):
        for prefix in ("Verify the store", "Verify the joins"):
            self.assertIsNone(self.step(prefix).attr("continue-on-error"), prefix)

    def test_every_non_fatal_step_has_a_timeout(self):
        for step in self.steps:
            if step.attr("continue-on-error") == "true":
                self.assertIsNotNone(step.attr("timeout-minutes"), step.name)

    def test_the_job_clock_starts_before_the_checkout(self):
        first = self.steps[0]
        self.assertTrue(first.name.startswith("Start the job clock"), first.name)
        self.assertEqual(first.run(), 'echo "JOB_START=$(date +%s)" >> "$GITHUB_ENV"')
        self.assertLess(self.names.index(first.name), self.names.index("Check out the repository"))

    def test_every_clock_step_reads_the_2400_second_window_from_job_start(self):
        clocks = [s for s in self.steps if s.name.startswith("Seconds left on the B5 clock")]
        self.assertEqual(len(clocks), 14)              # the monthly decision moved to the plan job (D42)
        monthly = [s for s in self.monthly_steps if s.name.startswith("Seconds left on the monthly clock")]
        self.assertEqual(len(monthly), 5)
        for clock in clocks + monthly:
            self.assertTrue(clock.attr("id").startswith("clock_"), clock.name)
            self.assertEqual(clock.run(), 'echo "left=$(( JOB_START + 2400 - $(date +%s) ))" >> "$GITHUB_OUTPUT"',
                             clock.name)

    def test_the_b5_steps_follow_the_joins_and_come_before_the_pack(self):
        self.assertLess(self.names.index("Verify the joins (the Benchland gate rows are printed)"),
                        self.names.index(CLOCK_START))
        self.assertLess(self.names.index(self.b5_steps()[-1].name), self.names.index(PACK))
        self.assertLess(self.names.index(B5_LAST), self.names.index(B3_FIRST))
        self.assertLess(self.names.index(B3_FIRST), self.names.index(PACK))

    def test_every_b5_step_runs_only_on_its_own_clock_and_is_killed_at_the_seconds_left(self):
        steps = self.steps
        for step in self.b5_steps():
            index = self.names.index(step.name)
            clock = steps[index - 1]
            self.assertTrue(clock.name.startswith("Seconds left on the B5 clock"), step.name)
            self.assertIn("steps." + clock.attr("id") + ".outputs.left > 60", step.attr("if") or "", step.name)
            if "timeout --kill-after=30" in (step.run() or ""):
                self.assertEqual(step.env().get("LEFT"), "${{ steps." + clock.attr("id") + ".outputs.left }}",
                                 step.name)

    def test_every_program_call_in_a_b5_step_is_wrapped_in_timeout(self):
        for step in self.b5_steps():
            run = step.run() or ""
            for line in run.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith(("#", "|", "--")):
                    continue
                if PROGRAM.search(stripped):
                    self.assertIn("timeout --kill-after=30", stripped, f"{step.name}: {stripped}")

    def test_each_deadline_is_the_smaller_of_its_own_and_the_seconds_left_less_440(self):
        for prefix in ("Station readings", "River gauges"):
            run = self.step(prefix).run()
            self.assertIn("budget=$(( LEFT - 440 ))", run, prefix)
            self.assertIn('if [ "$budget" -gt', run, prefix)
        self.assertIn("own=720", self.step("Station readings").run())
        self.assertIn("own=1620", self.step("Station readings").run())
        self.assertIn("own=480", self.step("River gauges").run())
        self.assertNotIn("--refresh", self.step("River gauges").run())   # the daily run reads the missing files only
        self.assertIn("--offline", self.step("Snow analysis").run())     # the daily read of the cached NOHRSC files

    def test_the_monthly_job_budgets_its_steps_by_their_own_deadlines(self):
        stations = self.monthly_step("Station candidate union")
        self.assertIn("--scope monthly", stations.run())
        self.assertIn('if [ "$budget" -gt 1620 ]', stations.run())
        gauges = self.monthly_step("River gauges (every")
        self.assertIn("--refresh", gauges.run())
        self.assertIn('if [ "$budget" -gt 540 ]', gauges.run())
        snow = self.monthly_step("Snow analysis (NOAA")
        self.assertIn('if [ "$budget" -gt 240 ]', snow.run())
        self.assertNotIn("--offline", snow.run())                        # the one NOHRSC request of the month

    def test_the_climate_archive_is_versioned_by_run_id_and_never_clobbered(self):
        publish = self.step("Pack and publish the climate aggregates").run()
        self.assertIn('name="climate-aggregates-${GITHUB_RUN_ID}.tar.gz"', publish)
        upload = [line for line in publish.splitlines() if "gh release upload hail-climate" in line]
        self.assertEqual(len(upload), 1)
        self.assertNotIn("--clobber", upload[0])
        commands = [line for line in publish.splitlines() if not line.strip().startswith("#")]
        self.assertNotIn("--clobber", "\n".join(commands))
        self.assertNotIn("upload hail-climate climate-aggregates.tar.gz", publish)
        self.assertNotIn("--out climate-aggregates.tar.gz", publish)

    def test_the_older_archives_are_removed_only_after_the_new_one_unpacks(self):
        publish = self.step("Pack and publish the climate aggregates").run()
        unpack = publish.index('unpack --archive "climate-check/$name"')
        listed = publish.index("old_names=$(")
        prune = publish.index('gh release delete-asset hail-climate "$old"')
        self.assertLess(unpack, listed)
        self.assertLess(listed, prune)
        # the new copy is checked by unpacking it into a scratch cache, and a copy that does not unpack is removed
        self.assertIn('--cache climate-check/cache', publish)
        self.assertLess(unpack, publish.index('gh release delete-asset hail-climate "$name" --yes'))

    def test_the_restore_takes_the_highest_run_id_and_does_nothing_when_none_exists(self):
        restore = self.step("Restore the climate aggregates").run()
        self.assertIn("gh release view hail-climate --json assets", restore)
        self.assertIn("sort -t- -k3,3nr", restore)
        self.assertIn("no climate archive to restore; the climate update is skipped", restore)
        update = self.step("Update the climate grid")
        self.assertIn("steps.climate_restore.outputs.restored", update.attr("if"))

    def test_the_store_asset_keeps_the_name_the_site_build_reads(self):
        # D59 (main's scheme): the job publishes the branch-named asset, and main's is the default the site reads
        self.assertTrue(h.STORE_URL.endswith("/hail-store/hail-store-main.tar.gz"), h.STORE_URL)
        self.assertIn('gh release upload hail-store "$ASSET.new" --clobber', self.text)

    def test_the_plan_job_decides_the_first_of_the_month_or_the_monthly_input(self):
        plan = {s.name: s for s in self.plan_steps}
        decide = plan["Decide whether the monthly job runs (a scheduled run on the first of the month, or the monthly input)"]
        run = decide.run()
        self.assertIn('if [ "$EVENT" = "schedule" ] && [ "$(date -u +%d)" = "01" ]; then due=yes; fi', run)
        self.assertIn('if [ "$MONTHLY_INPUT" = "true" ]; then due=yes; fi', run)
        self.assertEqual(decide.env().get("MONTHLY_INPUT"), "${{ inputs.monthly }}")
        self.assertIn("monthly: ${{ steps.when.outputs.monthly }}", self.text)
        store_text = self.text.partition("\n  store:\n")[2].partition("\n  monthly:\n")[0]
        self.assertNotIn("steps.when", store_text)

    def test_the_monthly_job_runs_after_the_store_job_and_is_non_fatal_throughout(self):
        self.assertIn("    needs: [plan, store]\n", self.text)
        self.assertIn("    if: ${{ always() && needs.plan.outputs.monthly != '' }}\n", self.text)
        self.assertTrue(self.monthly_steps)
        for step in self.monthly_steps:
            self.assertEqual(step.attr("continue-on-error"), "true", step.name)
            self.assertIsNotNone(step.attr("timeout-minutes"), step.name)

    def test_the_timeouts_follow_the_re_check_figures_where_they_were_measured(self):
        # 1.5 x the measured time, rounded up to whole minutes: the B1 build took 612 s in CI (16 minutes), the joins
        # verify 20 s, the climate build 11 s and the NOHRSC read 1.0 s; the network steps keep their own deadlines,
        # since the re-check measured them offline only
        self.assertEqual(self.step("Build the store from the NOAA archive").attr("timeout-minutes"), "16")
        self.assertEqual(self.step("Verify the joins").attr("timeout-minutes"), "1")
        self.assertEqual(self.step("Build the climate files").attr("timeout-minutes"), "1")
        self.assertEqual(self.step("Snow analysis").attr("timeout-minutes"), "1")
        self.assertEqual(self.step("Join reports, records").attr("timeout-minutes"), "53")

    def test_every_non_fatal_step_of_both_jobs_has_a_timeout(self):
        for step in self.steps + self.monthly_steps:
            if step.attr("continue-on-error") == "true":
                self.assertIsNotNone(step.attr("timeout-minutes"), step.name)


class WorkflowYaml(unittest.TestCase):
    """The store workflow parses as YAML, and the parse reads the same steps, in the same order, as the text does, with the
    timeouts the checks above rely on (the joins backstop, the daily cap)."""

    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.doc = yaml.safe_load(cls.text)

    def test_the_file_parses_with_its_three_jobs_and_its_triggers(self):
        self.assertIsInstance(self.doc, dict)
        self.assertEqual(sorted(self.doc["jobs"]), ["monthly", "plan", "store"])
        self.assertTrue("on" in self.doc or True in self.doc, "the file has its triggers")
        self.assertEqual(self.doc["jobs"]["store"]["timeout-minutes"], 150)

    def test_the_parse_reads_the_same_daily_steps_in_the_same_order_as_the_text(self):
        head, _, rest = self.text.partition("\n  store:\n")
        store_part = rest.partition("\n  monthly:\n")[0]
        text_names = [s.name for s in job_steps(store_part)]
        parsed_names = [s.get("name", "") for s in self.doc["jobs"]["store"]["steps"]]
        self.assertEqual(parsed_names, text_names)
        monthly_text = [s.name for s in job_steps(rest.partition("\n  monthly:\n")[2])]
        monthly_parsed = [s.get("name", "") for s in self.doc["jobs"]["monthly"]["steps"]]
        self.assertEqual(monthly_parsed, monthly_text)

    def test_the_parse_reads_the_joins_backstop_and_keeps_it_fatal(self):
        join = next(s for s in self.doc["jobs"]["store"]["steps"] if s.get("name", "").startswith("Join reports"))
        self.assertEqual(join["timeout-minutes"], math.ceil(1.5 * J.JOINS_DEADLINE_S / 60))   # 53 (D75(d))
        self.assertNotIn("continue-on-error", join)
        self.assertGreater(join["timeout-minutes"] * 60, J.JOINS_DEADLINE_S)

    def test_every_daily_step_parsed_has_a_run_or_a_uses(self):
        for step in self.doc["jobs"]["store"]["steps"]:
            self.assertTrue("run" in step or "uses" in step, step.get("name"))


if __name__ == "__main__":
    unittest.main()
