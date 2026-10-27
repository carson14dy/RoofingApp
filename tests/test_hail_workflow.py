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

try:
    import yaml
except ImportError:   # a machine without pyyaml skips these; the Tests and Website workflows install it
    yaml = None
# every class below reads the workflow files through yaml, so each one skips when pyyaml is absent
needs_yaml = unittest.skipUnless(yaml is not None, "pyyaml is not installed (the Website workflow installs it)")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import hail as h  # noqa: E402
from website import joins as J  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "hail-store.yml"
MONTHLY_CLOCK = 4800     # the monthly builds wait for this clock: JOB_START + 4800 (80 minutes)
MONTHLY_END = 6300       # the checks, marks and tail wait for this one: JOB_START + 6300 (105 minutes)
JOB_CAP = 6600           # the monthly job's cap: 110 minutes
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


@needs_yaml
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

    def test_the_daily_job_is_capped_at_150_minutes_and_the_monthly_job_at_110(self):
        # D50: the daily job's cap is B5's 60 plus B3's 90 until the branch run measures it. The monthly job's cap is 110
        # minutes: the B6 monthly steps (the terrain build at 25 minutes, the base map build at 20, the landmark refresh) need
        # more than the 60 it had. Its builds start only before its clock (JOB_START + 4800); the checks, the marks and the
        # tail wait for the monthly end (JOB_START + 6300), so the last of them ends inside the cap (the pins in B6Parts).
        self.assertIn("    timeout-minutes: 150\n    steps:\n", self.text)
        self.assertIn("    timeout-minutes: 110\n    steps:\n", self.text)
        self.assertNotIn("    timeout-minutes: 60\n    steps:\n", self.text)
        doc = yaml.safe_load(self.text)
        self.assertEqual(doc["jobs"]["store"]["timeout-minutes"], 150)
        self.assertEqual(doc["jobs"]["monthly"]["timeout-minutes"], 110)
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

    def test_every_clock_step_reads_its_jobs_window_from_job_start(self):
        # The daily B5 steps share 2,400 seconds from JOB_START (the B5 clock, D26); the daily B6 steps share 3,600 seconds
        # (the 60-minute daily budget, D105(a)); the monthly steps share 4,800 seconds (the 80-minute monthly clock).
        daily = [s for s in self.steps if s.name.startswith("Seconds left on the")]
        monthly = [s for s in self.monthly_steps if s.name.startswith("Seconds left on the")]
        windows = (("Seconds left on the B5 clock", 14, 2400), ("Seconds left on the B6 clock", 5, 3600),
                   ("Seconds left on the monthly clock", 8, 4800))
        self.assertEqual(len(daily) + len(monthly), sum(count for _, count, _ in windows))   # the monthly decision: D42
        for prefix, count, seconds in windows:
            found = [s for s in daily + monthly if s.name.startswith(prefix)]
            self.assertEqual(len(found), count, prefix)
            for clock in found:
                self.assertTrue(clock.attr("id").startswith("clock_"), clock.name)
                self.assertEqual(clock.run(), f'echo "left=$(( JOB_START + {seconds} - $(date +%s) ))" >> "$GITHUB_OUTPUT"',
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


@needs_yaml
class B6Parts(unittest.TestCase):
    """The B6 steps of the store job (DECISIONS D107 to D127). The daily store is built fresh, so the terrain tiles and the base
    map vectors are rebuilt each day from the caches that the monthly job refreshes (no request). Each part is non-fatal and is
    marked unavailable when it is not built and checked in its run (rule 5). The bubble values wait for the outlines and their
    check. The manifest check is the last part before the pack: fatal in the daily job, and in the monthly job it gates the
    publish. The monthly terrain step is capped at 25 minutes and the base map step at 20; both keep their caches under
    b6-cache/, and the checks, the marks and the tail wait for the monthly end (105 minutes after JOB_START)."""

    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.doc = yaml.safe_load(cls.text)
        _, _, rest = cls.text.partition("\n  store:\n")
        store_part, _, monthly_part = rest.partition("\n  monthly:\n")
        cls.steps = job_steps(store_part)
        cls.monthly_steps = job_steps(monthly_part)
        cls.names = [s.name for s in cls.steps]

    def step(self, prefix):
        found = [s for s in self.steps if s.name.startswith(prefix)]
        self.assertEqual(len(found), 1, f"one daily step named {prefix!r}")
        return found[0]

    def monthly(self, prefix):
        found = [s for s in self.monthly_steps if s.name.startswith(prefix)]
        self.assertEqual(len(found), 1, f"one monthly step named {prefix!r}")
        return found[0]

    def test_the_b6_parts_run_after_the_b5_section_and_before_the_b3_steps(self):
        after_b5, before_b3 = self.names.index(B5_LAST), self.names.index(B3_FIRST)
        for prefix in ("Seconds left on the B6 clock before the terrain tiles", "Terrain tiles from the cache",
                       "Base map vectors from the cache", "Landmark points (", "Build the five-year pictures"):
            with self.subTest(step=prefix):
                self.assertTrue(after_b5 < self.names.index(self.step(prefix).name) < before_b3)

    def test_the_bubble_labels_follow_the_buildings_verify_and_come_before_the_manifest_check_and_the_pack(self):
        labels = self.names.index(self.step("Label the building outlines").name)
        self.assertLess(self.names.index(self.step("Verify the outlines").name), labels)        # D112, D125: the verify first
        self.assertLess(self.names.index(self.step("Mark the outlines unavailable").name), labels)
        manifest = self.names.index(self.step("Check the store manifest after the last store part").name)
        self.assertLess(labels, manifest)
        self.assertLess(manifest, self.names.index(PACK))

    def test_the_bubble_values_wait_for_the_b6_clock_and_are_removed_when_the_pass_does_not_run(self):
        self.assertIn("steps.clock_labels.outputs.left > 60", self.step("Label the building outlines").attr("if") or "")
        remove = self.step("Remove the bubble values").attr("if") or ""
        self.assertIn("steps.lab_build.outputs.built != 'yes'", remove)
        self.assertIn("steps.lab_verify.outputs.verified != 'yes'", remove)

    def test_the_daily_manifest_check_is_fatal_and_names_the_b6_parts_it_contains_before_it_checks_again(self):
        check = self.step("Check the store manifest after the last store part")
        self.assertIsNone(check.attr("continue-on-error"), "fatal: a store that does not check is not published")
        run = check.run()
        self.assertIn('h.check_manifest("store")', run)
        for module in ("labels", "history_layers", "landmarks", "basemap2", "terrain"):
            self.assertIn(f"python -m website.{module} unavailable --store store", run, module)
        self.assertIn("exit 1", run)

    def test_the_monthly_manifest_check_gates_the_publish_and_contains_the_monthly_base_map_parts(self):
        check = self.monthly("Check the store manifest after the monthly parts")
        self.assertEqual(check.attr("continue-on-error"), "true")
        run = check.run()
        self.assertIn('h.check_manifest("store")', run)
        for module in ("landmarks", "basemap2", "terrain"):
            self.assertIn(f"python -m website.{module} unavailable --store store", run, module)
        publish = self.monthly("Publish the monthly store").attr("if") or ""
        self.assertIn("contains(steps.manifest.outcome, 'success')", publish)
        self.assertIn("contains(steps.pack.outcome, 'success')", publish)

    def test_the_daily_base_parts_are_rebuilt_offline_from_the_caches_the_monthly_job_saves(self):
        for prefix in ("Terrain tiles from the cache", "Base map vectors from the cache", "Check the terrain tiles from the cache"):
            with self.subTest(step=prefix):
                run = self.step(prefix).run()
                self.assertIn("--offline", run)
                self.assertNotIn("--refresh", run)
        for prefix in ("Restore the terrain cache", "Restore the base map cache"):
            with self.subTest(step=prefix):
                self.assertEqual(self.step(prefix).attr("uses"), "actions/cache/restore@v4")       # read only: no save each day
                self.assertEqual(self.monthly(prefix).attr("uses"), "actions/cache@v4")            # the monthly job saves it

    def test_the_monthly_terrain_build_is_capped_at_twenty_five_minutes_and_reads_the_descriptions_again(self):
        # D128(f): the monthly job reads the two service descriptions again and uses each cached tile whatever its age, so a
        # data month that has not changed costs no tile request, and a changed month is requested through its cache key. The
        # bare --refresh (every tile again) is not passed. The cap is 1500 seconds; the deadline is 120 seconds before it.
        build = self.monthly("Terrain tiles, descriptions asked again")
        self.assertEqual(build.attr("timeout-minutes"), "25")
        run = build.run()
        for flag in ("--zooms 5-10", "--cache b6-cache/terrain", "--timeout 60", "--refresh-descriptions", "--deadline-at",
                     "CAP=$(( LEFT < 1500 ? LEFT : 1500 ))", "DEADLINE=$(( $(date +%s) + CAP - 120 ))"):
            with self.subTest(flag=flag):
                self.assertIn(flag, run)
        self.assertIsNone(re.search(r"--refresh(?![\w-])", run), "the bare --refresh is not passed")
        self.assertIn("--timeout 60", self.monthly("Check the terrain tiles after the monthly build").run())
        self.assertNotIn("--keep-other-zooms", self.text)     # the job never passes it: the build refuses a zoom subset without it

    def test_the_monthly_terrain_check_allows_900_seconds_in_a_sixteen_minute_step(self):
        # D132(e): the sample of ten re-fetches runs one after another at the 60-second timeout, so the check allows 900 seconds
        # (less when the monthly end leaves less time), and its step is capped at 16 minutes, above that allowance.
        check = self.monthly("Check the terrain tiles after the monthly build")
        self.assertEqual(check.attr("timeout-minutes"), "16")
        run = check.run()
        self.assertIn("CAP=$(( LEFT < 900 ? LEFT : 900 ))", run)
        self.assertIn('timeout --kill-after=30 "$CAP" python -m website.terrain verify --store store --cache b6-cache/terrain '
                      "--timeout 60", run)
        self.assertGreater(int(check.attr("timeout-minutes")) * 60, 900 + 30)

    def test_the_monthly_end_clock_reads_105_minutes_and_keeps_five_minutes_under_the_cap(self):
        # The checks, the marks and the tail wait for the monthly end (JOB_START + 6300), so the last of them ends inside the
        # 110-minute cap; the five minutes left are for the cache saves that follow the last step and the job's teardown.
        ends = [s for s in self.monthly_steps if s.name.startswith("Seconds left to the monthly end")]
        self.assertEqual(len(ends), 9)
        for clock in ends:
            with self.subTest(step=clock.name):
                self.assertEqual(clock.run(), f'echo "left=$(( JOB_START + {MONTHLY_END} - $(date +%s) ))" >> "$GITHUB_OUTPUT"')
                self.assertTrue(clock.attr("id").startswith("clock_end_"), clock.attr("id"))
                self.assertEqual(clock.attr("continue-on-error"), "true")
                self.assertEqual(clock.attr("timeout-minutes"), "1")
        self.assertEqual(JOB_CAP - MONTHLY_END, 300)

    def test_the_manifest_check_the_pack_and_the_publish_start_only_when_their_whole_cap_fits_before_the_monthly_end(self):
        for prefix, minutes in (("Check the store manifest after the monthly parts", 10),
                                ("Pack the store (whatever the monthly steps left in it)", 5),
                                ("Publish the monthly store", 10)):
            with self.subTest(step=prefix):
                step = self.monthly(prefix)
                self.assertEqual(step.attr("timeout-minutes"), str(minutes))
                guard = re.search(r"steps\.clock_end_\w+\.outputs\.left > (\d+)", step.attr("if") or "")
                self.assertIsNotNone(guard, "the step waits for the monthly end")
                self.assertGreaterEqual(int(guard.group(1)), minutes * 60)

    def test_the_checks_and_marks_after_the_monthly_clock_run_for_the_time_left_and_within_their_caps(self):
        chain = (("Landmark check after the monthly build", 180),
                 ("Mark the landmarks unavailable when the monthly build", 300),
                 ("Check the terrain tiles after the monthly build", 900),
                 ("Mark the terrain tiles unavailable when the monthly build", 300),
                 ("Check the base map vectors after the monthly build", 300),
                 ("Mark the base map vectors unavailable when the monthly build", 300))
        for prefix, seconds in chain:
            with self.subTest(step=prefix):
                step = self.monthly(prefix)
                run = step.run()
                self.assertIn(f"CAP=$(( LEFT < {seconds} ? LEFT : {seconds} ))", run)
                self.assertIn('timeout --kill-after=30 "$CAP"', run)
                self.assertTrue((step.env().get("LEFT") or "").startswith("${{ steps.clock_end_"), prefix)
                self.assertIn("outputs.left > 60", step.attr("if") or "")
                self.assertGreaterEqual(int(step.attr("timeout-minutes")) * 60, seconds)

    def test_every_step_after_the_monthly_clock_names_the_clock_it_waits_for(self):
        # The builds wait for the 80-minute clock (JOB_START + 4800); the checks, the marks, the manifest check, the pack and the
        # publish wait for the monthly end (JOB_START + 6300). Each such step names a clock of one of those two windows.
        clocks = {s.attr("id"): s for s in self.monthly_steps if (s.attr("id") or "").startswith("clock_")}
        names = [s.name for s in self.monthly_steps]
        first = names.index(self.monthly("Seconds left on the monthly clock before the terrain tiles").name)
        for step in self.monthly_steps[first + 1:]:
            if step.name.startswith(("Seconds left on the monthly clock", "Seconds left to the monthly end")):
                continue
            with self.subTest(step=step.name):
                refs = re.findall(r"steps\.(clock_\w+)\.outputs\.left", step.attr("if") or "")
                self.assertTrue(refs, "a step after the monthly clock waits for a clock")
                for ref in refs:
                    window = int(re.search(r"JOB_START \+ (\d+)", clocks[ref].run()).group(1))
                    self.assertIn(window, (MONTHLY_CLOCK, MONTHLY_END))

    def test_the_monthly_base_map_is_capped_at_twenty_minutes_and_reads_its_state_from_the_index(self):
        build = self.monthly("Base map vectors (bands A to C each month")
        self.assertEqual(build.attr("timeout-minutes"), "20")
        run = build.run()
        self.assertIn("['vector']['state']", run)            # the build exits 0 for an unavailable store (D122(j))
        self.assertIn("CAP=$(( LEFT < 1140 ? LEFT : 1140 ))", run)
        self.assertIn("--deadline-at", run)
        self.assertNotIn("--refresh", run)                    # the cached pages are read; band D continues over the runs

    def test_the_monthly_landmarks_ask_every_list_again_and_the_daily_landmarks_read_the_cache(self):
        monthly = self.monthly("Landmark points, every list asked again").run()
        self.assertIn("--refresh", monthly)
        self.assertIn('if [ "$budget" -gt 540 ]; then budget=540; fi', monthly)
        daily = self.step("Landmark points (").run()
        self.assertNotIn("--refresh", daily)
        self.assertIn("--cache b6-cache/landmarks", daily)

    def test_pyshp_numpy_and_pillow_are_installed_for_the_b6_steps_in_both_jobs(self):
        grib = self.step("Install the GRIB reader").run().split()
        self.assertTrue({"numpy", "pyshp", "requests"} <= set(grib), grib)
        pillow = self.step("Install Pillow")
        self.assertEqual(pillow.attr("continue-on-error"), "true")
        self.assertIn("Pillow", pillow.run().split())
        self.assertLess(self.names.index(pillow.name), self.names.index(self.step("Seconds left on the B6 clock before the terrain tiles").name))
        monthly = self.monthly("Install the monthly readers").run().split()
        self.assertTrue({"numpy", "pyshp", "Pillow"} <= set(monthly), monthly)

    def test_the_store_job_runs_on_the_pushes_that_change_the_b6_modules(self):
        triggers = self.doc.get("on", self.doc.get(True))
        paths = triggers["push"]["paths"]
        for module in ("terrain", "basemap2", "landmarks", "history_layers", "labels"):
            self.assertIn(f"website/{module}.py", paths)

    def test_the_b6_cache_folders_sit_under_b6_cache(self):
        paths = set()
        for step in self.steps + self.monthly_steps:
            for line in step.lines:
                match = re.match(r"^          path: (\S+)$", line)
                if match:
                    paths.add(match.group(1))
        self.assertTrue({"b6-cache/terrain", "b6-cache/basemap2", "b6-cache/landmarks", "b6-cache/zone-outlines"} <= paths,
                        sorted(paths))
        self.assertEqual([p for p in paths if "b6" in p and not p.startswith("b6-cache/")], [])


@needs_yaml
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
