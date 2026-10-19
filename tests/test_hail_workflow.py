"""The hail store job (.github/workflows/hail-store.yml, D26, D35, D38): the B5 steps share one clock and are killed at
the seconds left, every non-fatal step has a timeout, the joins are fatal with a timeout above JOINS_DEADLINE_S, the
climate archive is published under a versioned name without --clobber, the older archives are removed only after the
new one unpacks, the restore takes the newest archive, and the store asset keeps the name the site build reads.

The job file is read as text (no YAML package is needed): each step starts with a "      - name:" line and its keys sit
at eight spaces, which is how the file is written. The checks are the file's own text, so they hold for the file as
committed. No network, no workflow run."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from website import hail as h  # noqa: E402
from website import joins as J  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "hail-store.yml"
CLOCK_START = "Seconds left on the B5 clock before the readers"
PACK = "Pack the store"
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
        cls.steps = job_steps(cls.text)
        cls.names = [s.name for s in cls.steps]

    def step(self, prefix):
        found = [s for s in self.steps if s.name.startswith(prefix)]
        self.assertEqual(len(found), 1, f"one step named {prefix!r}")
        return found[0]

    def b5_steps(self):
        """The non-clock steps between the first B5 clock and the pack, in order."""
        start = self.names.index(CLOCK_START)
        end = self.names.index(PACK)
        return [s for s in self.steps[start:end] if not s.name.startswith("Seconds left on the B5 clock")]

    def test_the_text_has_no_double_equals_and_no_em_dash(self):
        self.assertNotIn("==", self.text)
        self.assertNotIn(chr(0x2014), self.text)

    def test_the_job_keeps_its_sixty_minute_cap(self):
        self.assertIn("    timeout-minutes: 60\n    steps:\n", self.text)

    def test_the_join_is_fatal_and_its_timeout_is_above_the_joins_deadline(self):
        join = self.step("Join reports, records")
        self.assertIsNone(join.attr("continue-on-error"), "the join stays fatal (the B2 rule)")
        self.assertIsNotNone(join.attr("timeout-minutes"))
        self.assertGreater(int(join.attr("timeout-minutes")) * 60, J.JOINS_DEADLINE_S)
        self.assertEqual(join.attr("timeout-minutes"), "50")

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
        self.assertGreaterEqual(len(clocks), 15)
        for clock in clocks:
            self.assertTrue(clock.attr("id").startswith("clock_"), clock.name)
            self.assertEqual(clock.run(), 'echo "left=$(( JOB_START + 2400 - $(date +%s) ))" >> "$GITHUB_OUTPUT"',
                             clock.name)

    def test_the_b5_steps_follow_the_joins_and_come_before_the_pack(self):
        self.assertLess(self.names.index("Verify the joins (the Benchland gate rows are printed)"),
                        self.names.index(CLOCK_START))
        self.assertLess(self.names.index(self.b5_steps()[-1].name), self.names.index(PACK))

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
        for prefix in ("Station readings", "River gauges", "Snow analysis"):
            run = self.step(prefix).run()
            self.assertIn("budget=$(( LEFT - 440 ))", run, prefix)
            self.assertIn('if [ "$budget" -gt', run, prefix)
        self.assertIn("own=720", self.step("Station readings").run())
        self.assertIn("own=1620", self.step("Station readings").run())
        self.assertIn("own=540", self.step("River gauges").run())
        self.assertIn("own=480", self.step("River gauges").run())
        self.assertIn('if [ "$budget" -gt 240 ]', self.step("Snow analysis").run())

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
        self.assertTrue(h.STORE_URL.endswith("/hail-store/hail-store.tar.gz"), h.STORE_URL)
        self.assertIn("gh release upload hail-store hail-store.tar.gz --clobber", self.text)


if __name__ == "__main__":
    unittest.main()
