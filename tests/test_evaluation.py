"""Predeclared evaluation harness (evaluation/): split rules, decision-time rejection, outcome rules,
bootstrap determinism, insufficient-data output and the rule that arms are never pooled.

Everything runs offline on the synthetic fixtures in tests/fixtures/evaluation/ (under 50 rows each).
The website's SPC parser is compared with the harness's copy when `requests` is installed.
"""

import contextlib
import csv
import io
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation import harness as h  # noqa: E402

try:  # the website's parser needs requests; the harness itself does not
    from website import sources as src  # noqa: E402
except ImportError:
    src = None

FIX = ROOT / "tests" / "fixtures" / "evaluation"
UTC = timezone.utc
TOWNS = h.load_towns(FIX / "towns.json")
RECORDS = h.load_records(FIX / "decisions.jsonl", TOWNS)
REPORTS, SKIPPED = h.load_outcomes(FIX / "outcomes.csv")
DAYS = sorted({r["day"] for r in RECORDS})
EVENT_DAYS = {date(2026, 6, 10), date(2026, 6, 12)}


def scored(records=RECORDS, reports=REPORTS, **kw):
    kw.setdefault("split", "none")
    kw.setdefault("min_days", 2)
    kw.setdefault("resamples", 50)
    return h.evaluate(records, reports, TOWNS, **kw)


def row(text: str, arm: str) -> list[str]:
    for line in text.splitlines():
        if line.startswith(f"| {arm} |"):
            return [c.strip() for c in line.split("|")]
    raise AssertionError(f"no row for arm {arm}")


class Split(unittest.TestCase):
    def test_an_event_day_is_never_on_both_sides(self):
        for seed in range(1, 6):
            held = h.held_out_days(DAYS, "event", 0.5, seed)
            self.assertEqual(held | (set(DAYS) - held), set(DAYS))
            for day in EVENT_DAYS:
                sides = {r["day"] in held for r in RECORDS if r["day"] == day}
                self.assertEqual(len(sides), 1, f"{day} split across the held-out line (seed {seed})")

    def test_a_season_stays_on_one_side(self):
        days = [date(2026, 1, 5), date(2026, 2, 1), date(2026, 6, 10), date(2026, 6, 11), date(2026, 10, 3),
                date(2026, 11, 20), date(2026, 5, 2)]
        for seed in range(1, 6):
            held = h.held_out_days(days, "season", 0.5, seed)
            for season in ("winter", "spring", "summer", "fall"):
                sides = {d in held for d in days if h.SEASON[d.month] == season}
                self.assertEqual(len(sides), 1, f"{season} split across the held-out line (seed {seed})")

    def test_the_same_seed_gives_the_same_split(self):
        self.assertEqual(h.held_out_days(DAYS, "event", 0.5, 7), h.held_out_days(DAYS, "event", 0.5, 7))
        self.assertEqual(h.held_out_days(DAYS, "none"), set(DAYS))


class DecisionRecords(unittest.TestCase):
    def record(self, **over):
        rec = {"as_of": "2026-06-10T14:00:00Z", "decision_time": "2026-06-10T14:00:00Z", "arm": "A",
               "town": "billings", "reporting_day": "2026-06-10", "decision": {"warned": False}}
        rec.update(over)
        return rec

    def test_a_record_written_after_its_decision_is_rejected(self):
        late = self.record(as_of="2026-06-10T15:00:00Z", decision_time="2026-06-10T14:00:00Z")
        with self.assertRaisesRegex(ValueError, "rejected.*later than decision_time"):
            h.check_record(late, TOWNS, "decisions line 1")

    def test_a_decision_dated_after_its_reporting_day_ended_is_rejected(self):
        # Reporting day 2026-06-10 ends at 12:00 UTC on 2026-06-11.
        after = self.record(as_of="2026-06-11T12:00:00Z", decision_time="2026-06-11T12:00:00Z")
        with self.assertRaisesRegex(ValueError, "after reporting day 2026-06-10 ended"):
            h.check_record(after, TOWNS, "decisions line 1")
        ok = self.record(as_of="2026-06-11T11:59:00Z", decision_time="2026-06-11T11:59:00Z")
        self.assertTrue(h.check_record(ok, TOWNS, "decisions line 1")["decision_time"].hour == 11)

    def test_unknown_arm_town_or_missing_warned_is_rejected(self):
        for bad in (self.record(arm="D"), self.record(town="helena"), self.record(decision={}),
                    self.record(decision={"warned": "yes"})):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                h.check_record(bad, TOWNS, "decisions line 1")

    def test_a_bad_line_stops_the_run_and_the_command_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decisions.jsonl"
            path.write_text(
                '{"as_of": "2026-06-10T14:00:00Z", "decision_time": "2026-06-10T14:00:00Z", "arm": "A", '
                '"town": "billings", "reporting_day": "2026-06-10", "decision": {"warned": true}}\n'
                '{"as_of": "2026-06-10T15:00:00Z", "decision_time": "2026-06-10T14:00:00Z", "arm": "A", '
                '"town": "billings", "reporting_day": "2026-06-10", "decision": {"warned": true}}\n')
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = h.main([str(path), str(FIX / "outcomes.csv"), "--towns", str(FIX / "towns.json")])
        self.assertEqual(code, 1)
        self.assertIn("decisions line 2", err.getvalue())

    def test_fixture_records_load_and_stay_small(self):
        self.assertEqual(len(RECORDS), 38)
        for path in (FIX / "decisions.jsonl", FIX / "outcomes.csv"):
            with self.subTest(path=path.name):
                self.assertLess(len(path.read_text().splitlines()), 50)


class Outcomes(unittest.TestCase):
    def test_thresholds_duplicates_blank_times_and_area(self):
        # 7 reports survive: 3 qualify (hail 1.25 in, hail 1.00 in 40 miles north, wind 61 mph).
        self.assertEqual(len(REPORTS), 7)
        self.assertEqual(sum(r["qualifies"] for r in REPORTS), 3)
        self.assertEqual(SKIPPED, 1)     # the blank-time row is counted, not scored as midnight
        self.assertFalse(any(r["lat"] < 40 for r in REPORTS), "the Texas row must be outside Montana")
        big = [r for r in REPORTS if r["kind"] == "hail" and r["size_in"] == 1.25]
        self.assertEqual(len(big), 1, "the duplicate row must be dropped")
        self.assertEqual(big[0]["time"], datetime(2026, 6, 10, 21, 15, tzinfo=UTC))

    def test_unknown_wind_and_sub_threshold_wind_do_not_qualify(self):
        wind = {r["mph"]: r["qualifies"] for r in REPORTS if r["kind"] == "wind"}
        self.assertEqual(wind, {61: True, None: False, 52: False})

    @unittest.skipUnless(src is not None, "website.sources needs requests, which is not installed")
    def test_parser_matches_the_website_parser_on_the_same_rows(self):
        with (FIX / "outcomes.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        for day, kind, field in (("2026-06-10", "hail", "Size"), ("2026-06-12", "wind", "Speed")):
            keep = [r for r in rows if r["day"] == day and r["kind"] == kind and r["Time"].strip()]
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=["Time", field, "Location", "County", "State", "Lat", "Lon",
                                                     "Comments"])
            writer.writeheader()
            for r in keep:
                writer.writerow({k: r[k] for k in writer.fieldnames})
            theirs = src.parse_spc(buf.getvalue(), date.fromisoformat(day), kind)
            mine = [r for r in REPORTS if r["day"] == date.fromisoformat(day) and r["kind"] == kind]
            self.assertEqual(
                [(r["time"], r["lat"], r["lon"], r["size_in"], r["mph"]) for r in mine],
                [(src.parse_iso(r["time"]), r["lat"], r["lon"], r["size_in"], r["mph"]) for r in theirs])


class Metrics(unittest.TestCase):
    def test_fixture_metrics_match_the_hand_counts(self):
        arms = scored()["arms"]
        a, b, c = arms["A"]["metrics"], arms["B"]["metrics"], arms["C"]["metrics"]
        self.assertAlmostEqual(a["miss_rate"][0], 0.5)           # A misses the Billings hail
        self.assertAlmostEqual(a["fa_ratio"][0], 2 / 3)          # two false alarms, one hit
        self.assertAlmostEqual(a["lead_h"][0], 9.0)
        self.assertAlmostEqual(b["miss_rate"][0], 0.0)
        self.assertAlmostEqual(b["fa_ratio"][0], 0.5)
        self.assertAlmostEqual(b["lead_h"][0], (7.25 + -1.0) / 2)  # median of two hits, one of them late
        self.assertEqual(arms["B"]["late"], 1)
        self.assertAlmostEqual(c["fa_ratio"][0], 0.5)
        self.assertAlmostEqual(c["lead_h"][0], (5.25 + 9.0) / 2)  # the earliest warned record counts

    def test_zero_outcomes_is_insufficient_data_not_zero_misses(self):
        glasgow_only = [r for r in RECORDS if r["town"] == "glasgow"]
        result = scored(records=glasgow_only)
        self.assertEqual(result["arms"]["A"]["outcomes"], 0)
        self.assertIsNone(result["arms"]["A"]["metrics"]["miss_rate"])
        cells = row(h.render(result), "A")
        self.assertEqual(cells[6], h.INSUFFICIENT)   # misses
        self.assertEqual(cells[7], h.INSUFFICIENT)   # miss rate
        self.assertNotIn("0.00 [", h.render(result))

    def test_below_the_minimum_sample_every_metric_is_insufficient(self):
        result = scored(min_days=30)
        text = h.render(result)
        for arm in h.ARMS:
            self.assertEqual(result["arms"][arm]["status"], h.INSUFFICIENT)
            self.assertIsNone(result["arms"][arm]["metrics"])
            cells = row(text, arm)
            self.assertEqual(cells[7:10], [h.INSUFFICIENT] * 3, f"arm {arm}: miss rate, false alarms, lead")

    def test_arms_are_never_pooled(self):
        everything = scored()
        only_a = scored(records=[r for r in RECORDS if r["arm"] == "A"])
        self.assertEqual(everything["arms"]["A"], only_a["arms"]["A"])
        changed = [dict(r) for r in RECORDS]
        for r in changed:
            if r["arm"] == "B" and r["town"] == "billings" and r["day"] == date(2026, 6, 10):
                r["warned"] = False
        after = scored(records=changed)
        self.assertEqual(after["arms"]["A"], everything["arms"]["A"])
        self.assertEqual(after["arms"]["B"]["misses"], 1)
        self.assertEqual(everything["arms"]["B"]["misses"], 0)

    def test_the_same_seed_gives_the_same_intervals(self):
        first = scored(seed=7, resamples=200)
        again = scored(seed=7, resamples=200)
        self.assertEqual(first, again)
        self.assertEqual(h.render(first), h.render(again))
        other = scored(seed=8, resamples=200)
        for arm in h.ARMS:   # the point estimates do not depend on the seed
            self.assertEqual(other["arms"][arm]["metrics"]["miss_rate"][0], first["arms"][arm]["metrics"]["miss_rate"][0])

    def test_a_missing_record_is_counted_not_scored_as_a_miss(self):
        no_c_at_billings = [r for r in RECORDS if not (r["arm"] == "C" and r["town"] == "billings"
                                                      and r["day"] == date(2026, 6, 10))]
        result = scored(records=no_c_at_billings)
        self.assertEqual(result["arms"]["C"]["no_record"], 1)
        self.assertEqual(result["arms"]["C"]["misses"], 0)


class Command(unittest.TestCase):
    def run_cli(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = h.main([str(FIX / "decisions.jsonl"), str(FIX / "outcomes.csv"),
                           "--towns", str(FIX / "towns.json"), *extra])
        return code, out.getvalue()

    def test_prints_one_row_per_arm_and_says_proxy(self):
        code, text = self.run_cli("--min-days", "2", "--resamples", "50", "--split", "none")
        self.assertEqual(code, 0)
        for arm in h.ARMS:
            self.assertTrue(row(text, arm))
        self.assertIn("proxy outcomes, not ground truth", text)
        self.assertNotIn("best", text.lower())

    def test_default_minimum_sample_prints_insufficient_for_the_fixture(self):
        code, text = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Minimum sample per arm: 30 event and 30 quiet days", text)
        for arm in h.ARMS:
            self.assertEqual(row(text, arm)[7], h.INSUFFICIENT)


if __name__ == "__main__":
    unittest.main()
