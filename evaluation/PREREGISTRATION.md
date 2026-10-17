# Predeclared evaluation: Montana Hail Watch

Status: **PROPOSED, not signed off.** Every number, threshold and rule marked PROPOSED needs Carson's
sign-off before any decision record is scored. This file was written before any analysis; no decision
records exist yet and none have been scored.

Sources: `docs/handoff/Roofing_Weather_Independent_Review.md` ("Evaluation that can support a 'better'
claim" and "Proposed release gates"), `docs/DECISIONS.md` D21 (no "best" claims) and D28/D29 (the
website and station readings), `website/build.py` (what each build writes), `website/sources.py`
(the SPC parser and `CONTRACTS`).

## 1. Purpose

Answer one question with predeclared measures: does a change to what a town or job is told improve
the decision it supports, compared with the company's current practice? Until these metrics have been
run on held-out data, no output may be called "better", "best" or "more accurate" (AGENTS.md rule 9,
D21).

## 2. Arms

The three arms are the review's, unchanged:

- **A.** Existing company practice plus official NWS guidance (the NWS forecast, alerts, and the
  station readings shown on the site).
- **B.** A, plus deterministic job-specific rules (company limits per roof system, phase and duration;
  rules are code with tests, never generated prose).
- **C.** B, plus additional weather feeds (for example SPC CIG, ProbSevere v3, LightningCast, a
  commercial hail source) and AI explanations.

B tests the value of job context. C tests the value of extra data or prose on top of B. Arms are
**never pooled**: every metric is reported per arm, and no metric combines arms.

## 3. What one decision record contains

One record per town (or job) per build (about every 10 minutes), appended to a durable store. Each
record is one JSON object with these fields:

| Field | Meaning |
|---|---|
| `as_of` | UTC time the record was written (the build time). Must not be later than `decision_time`. |
| `decision_time` | UTC time the arm's decision applies to. A decision may not be dated after its reporting day has ended (12:00 UTC the next day). |
| `arm` | `A`, `B` or `C`. |
| `town` | Town slug, as in `website/towns.json`. Later: a job id. |
| `reporting_day` | SPC reporting day the record is about (`YYYY-MM-DD`; 12:00 to 11:59 UTC). |
| `decision` | What the arm told the user for that town or job: the alert ids shown, the flags shown with their values and times, the NWS forecast values shown, and the next action shown. `decision.warned` is the scored bit: true when the decision shows an official alert or a rule-triggered flag for the town on that reporting day, else false. |
| `sources` | Per source: its status (ok or not), its issue or fetch time, and its version or contract name. |

**Gap in the current build (for the coordinator, not changed here).** `website/build.py` writes
`data/state.json` with `built`, `sample`, `status`, `alerts`, `points`, `stations` and `readings`
(the raw station values with their MADIS flags). It does **not** write the hourly values, flags or
issue times each town card showed; those exist only in `data/map.json` and the rendered HTML, and
`map.json` is overwritten each build. A decision record therefore cannot be scored from `state.json`
alone until the build also writes a per-town `decision` block. Proposed contract change, a few lines
in `build.py`, to be reviewed separately.

Records are written at each build, so a record's `as_of` is always the build time, and the record is
the only thing a later score may read for that decision.

## 4. Durable storage (recommendation, not implemented)

- Keep one JSON Lines file per arm per UTC day, and commit it to a `data` branch, as the roadmap
  already proposes (Next 4). Commit hourly rather than every 10 minutes to keep history small;
  each hourly commit holds the six records of the hour's builds.
- Never rewrite or delete a committed line. A correction is a new line with a later `as_of` and a
  `corrects` field naming the earlier record.
- Keep the `data/state.json` copy the build already publishes, but treat it as a convenience, not
  the record.
- The workflow is not changed by this document. Carson's sign-off is needed for the branch and for
  the hourly commit.

## 5. Evaluation unit

One **town (or job) on one SPC reporting day**. A decision is scored against what happened on that
reporting day and at that town's location, using only records whose `as_of` is earlier than the
decision time the record supports.

Decision time, PROPOSED: a unit's decision time is the earliest `decision_time` among its records
with `warned` true. Lead time is measured from that to the first qualifying report. A warning first
given after the first qualifying report is a late hit: it counts as a hit, its lead is negative, and
the harness reports late hits in their own column.

## 6. Outcomes (a proxy, not ground truth)

An outcome is **SPC storm reports** at or above a size, within a radius of the town, on that
reporting day.

- Size, PROPOSED: hail 1.00 in (100 hundredths of an inch) or larger; wind 58 mph or higher.
- Radius, PROPOSED: 25 miles of the town point, which matches SPC's own regional convention
  (review; SPC probabilities describe events within 25 miles of a point).
- Time window: the reporting day, 12:00 to 11:59 UTC, as `website/sources.py` `spc_day_for` defines it.
- Distance: great-circle miles to the town point in `website/towns.json`.
- Event day (the same for every arm): a reporting day with at least one qualifying report within
  25 miles of any town in the list. Every other reporting day is a quiet day.
- Parsing: SPC rows are read with the rules of `website/sources.py` `parse_spc` (Montana box plus
  0.75 degrees, duplicates dropped, hail in hundredths of an inch, `UNK` wind unknown). A row with a
  blank or unreadable time or position is skipped and counted in the report; a blank time is never
  read as midnight.

**Labelled a proxy.** SPC reports are preliminary, incomplete and depend on who reports. They are
not ground truth for hail, wind or damage. A report at the town is not confirmation of a roof
impact; no report is not "no hail" (AGENTS.md rule 5). MESH agreement is not ground truth either
(review). The site already reads SPC files with `parse_spc`, which keeps only reports within the
Montana box plus 0.75 degrees; a 25-mile radius around any Montana town sits inside that box.

## 7. Metrics

All metrics are reported per arm, with 95% bootstrap intervals (section 9).

**Weather (per town-day):**
- **Misses:** qualifying outcome, arm told nothing applicable (no alert shown, no flag shown). Rate =
  misses / outcome town-days.
- **False alarms:** arm told an alert or flag, no qualifying outcome. Rate = false alarms /
  alert-or-flag town-days (the false-alarm ratio).
- **Lead time:** hours from the decision time to the first qualifying report, median and interquartile
  range, over hits only.
- **Magnitude and timing error:** for the forecast values shown, absolute error against the observed
  station value at the matching hour (deferred until station values are scored; not automatic).
- **Probability calibration and Brier score:** only where an arm states a probability. Neither the
  current site nor arm A states one, so these are reported as "not applicable" for A and B unless an
  arm adds a probability (arm C).

**Operations:**
- **Review time** per 100 job-days (minutes, from the crew's log).
- **Unexpected interruptions** per 100 job-days, with reschedule reasons.
- **Completed phases** per job.

**Inspection targeting (later):**
- **Findings per crew-hour**, plus sampled comparison properties. Uninspected properties are unknown,
  not negatives (review).

**Language (human-scored, see section 11):**
- Correct reading of job, time, uncertainty and next action; unsupported claims count.

**Reliability:**
- Alert matching and revisions, stale detection (readings older than 75 minutes must show as stale),
  processing and delivery latency, and recovery from outage with no lost records.

**Economics:**
- Provider, compute, AI, map and notification cost per active company and per job, reported as
  reported, not as a ranking.

## 8. Held-out splits

- Split by **event day** (section 6) or by **season** (the meteorological seasons, by month), never by
  random hour, random pixel or random town-hour.
- PROPOSED: the held-out side is a seeded draw of whole groups, fraction 0.5, seed 20261016. Metrics
  are reported on the held-out side only. A chronological split is the alternative; Carson picks
  one before any run.
- A split never puts one event day on both sides. The harness enforces this.
- Include quiet days (no reports, no alerts), missed storms, different seasons and terrain, radar gaps,
  and relevant regions. Stratify the report by season and by eastern and western Montana.
- **Decision-time rule:** a score may use a record only if its `as_of` is at or before its
  `decision_time`, and only the record's own `decision` block. No revised history, no later forecast,
  no later report may enter the record. The harness rejects any record whose `as_of` is later than its
  `decision_time`, and any record whose `decision_time` falls after its reporting day has ended, and it
  stops the run on a malformed line rather than dropping it.

## 9. Sample size and "meaningful improvement" (PROPOSED)

- **Minimum sample:** at least 30 held-out event days and at least 30 held-out quiet days on which the
  arm has records, before any metric for that arm is reported. Below that the harness prints
  "insufficient data" for the arm. Zero outcomes is never reported as zero misses.
- **Meaningful improvement (PROPOSED):** an arm beats the comparator only if, on held-out days:
  - the 95% interval of the difference in misses excludes zero and the arm misses fewer storms; and
  - the difference in false-alarm ratio does not widen by more than 5 percentage points; and
  - the difference in median lead time is at least 30 minutes, or lead time is unchanged.
- **Bootstrap:** resample reporting days (event and quiet, with each day's towns and builds moving
  together) with replacement, 2000 resamples, seed fixed at 20261016 so the same data always gives the
  same intervals. Reported as percentile 95% intervals. Each arm uses its own generator from the same
  seed, so arms are never pooled.
- No comparison is reported as "better" unless all three conditions hold. A result that is
  "not shown to be better" is the default.

## 10. What is not scored automatically

- Language, including whether a line says what the user should do, is human-scored with a written
  rubric by two people who did not write it.
- Whether a warning was applicable to a job's roof system (judgement; recorded, not computed).
- Any claim that a product or model is "best" (D21). The harness never writes that word.
- Inspection findings (needs a crew and a site check).
- Damage, insurance eligibility and damage probability: out of scope and never stated (AGENTS.md rule 5).

## 11. Known limits (stated in every report)

- SPC reports are preliminary and incomplete; report counts depend on population and reporting.
- MESH agreement is not ground-truth hail verification.
- SPC proxies are county- or point-based and within a radius; they do not measure hail on a roof.
- A short pilot is not proof of nationwide performance (review).
- Montana only until the contiguous US is added (D24); results do not transfer by region or season
  without new held-out data.
- Radar is a 2-minute estimate that is 10-minute stale in the site's snapshots; model values are
  model values, not NWS forecasts.

## 12. Changes to this document

Changes after sign-off are dated and listed here. The metrics, outcome definition and minimum sample
may not change after a comparison has been run on a split without a new predeclaration and a new
held-out split.

Changelog:
- 2026-10-16: first draft, PROPOSED, written before any analysis.
- 2026-10-16: the harness (`evaluation/harness.py`) was written against this draft. `decision_time`,
  `decision.warned`, the arm-independent event-day rule, the held-out draw and the reporting-day
  bootstrap were made explicit to match it. No thresholds or sample sizes changed. Still PROPOSED.
