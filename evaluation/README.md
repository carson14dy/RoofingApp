# Evaluation harness

The rules are in [PREREGISTRATION.md](PREREGISTRATION.md). That file is **PROPOSED** and needs Carson's
sign-off before any real decision record is scored. No decision records exist yet, so the harness has
only been run on the synthetic fixtures in `tests/fixtures/evaluation/`.

## Run it

```bash
python3 evaluation/harness.py <decisions.jsonl> <outcomes.csv>
python3 evaluation/harness.py decisions.jsonl outcomes.csv --split season --min-days 30
python3 -m unittest tests.test_evaluation -v        # offline, a fraction of a second
```

Standard library only. The optional check against `website/sources.py` runs only when `requests` is
installed. The output is a markdown table with one row per arm:

- miss rate, false-alarm ratio and median lead time, each with a 95% bootstrap interval;
- the counts behind them (event and quiet days, town-days, outcomes, misses, late hits);
- the number of outcome town-days the arm has no record for, which are not scored.

Arms are never pooled. A metric prints `insufficient data` when the arm has fewer than the minimum
number of held-out event or quiet days, or when its denominator is zero. Zero outcomes is never shown
as zero misses.

Options: `--split event|season|none` (default `event`), `--fraction` (0.5), `--seed` (20261016),
`--min-days` (30), `--resamples` (2000), `--towns` (default `website/towns.json`). The header of the
output repeats the values used.

## Decision records (`decisions.jsonl`)

One JSON object per line:

```json
{"as_of": "2026-06-10T14:00:00Z", "decision_time": "2026-06-10T14:00:00Z", "arm": "B", "town": "billings", "reporting_day": "2026-06-10", "decision": {"warned": true}}
```

- `as_of`: when the record was written (UTC, ISO 8601 with a zone).
- `decision_time`: when the arm's decision applies. `as_of` must not be later than it. It may not fall
  after the record's reporting day has ended (12:00 UTC the next day).
- `arm`: `A`, `B` or `C`.
- `town`: a slug from `website/towns.json`.
- `reporting_day`: the SPC reporting day, `YYYY-MM-DD`.
- `decision.warned`: `true` if the decision shows an official alert or a rule-triggered flag for the
  town that day, `false` otherwise. Other keys in `decision` are kept by the writer and ignored here.

A malformed line, or one that breaks these rules, stops the run with the line number and a non-zero
exit. A record is never dropped silently.

## Outcomes (`outcomes.csv`)

SPC filtered storm reports, with two extra leading columns, `day` (`YYYY-MM-DD`) and `kind` (`hail` or
`wind`). The rest are SPC's own columns:

```
day,kind,Time,Size,Speed,Location,County,State,Lat,Lon,Comments
2026-06-10,hail,2115,125,,3 N Billings,Yellowstone,MT,45.7833,-108.5007,SYNTHETIC
2026-06-12,wind,1900,,61,Great Falls area,Cascade,MT,47.5051,-111.3008,SYNTHETIC
```

For a day, paste each SPC `YYMMDD_rpts_filtered_hail.csv` and `_wind.csv` under the same header, adding
`day` and `kind`. A qualifying outcome is hail of 1.00 in or more, or wind of 58 mph or more, within
25 miles of a town, on its reporting day. Reports outside Montana and duplicates are dropped the way
`website/sources.py` drops them. A row with a blank time or position is skipped and counted in the output.

SPC reports are preliminary and incomplete. They are a proxy, not ground truth, and "no report" is not
"no hail".

## Files

| File | Purpose |
|---|---|
| `harness.py` | The scorer (under 400 lines, standard library only) |
| `PREREGISTRATION.md` | The predeclared arms, outcomes, metrics, splits and thresholds (PROPOSED) |
| `tests/test_evaluation.py` | Split rules, rejected records, outcome rules, exact hand-checked metrics, insufficient-data output, arms never pooled, seeded intervals |
| `tests/fixtures/evaluation/` | Synthetic towns, decisions (38 rows) and outcomes (10 rows) |

## What the harness does not score

Review time, interruptions, rescheduling reasons, findings per crew-hour, language quality, reliability
and latency, and cost. Those need other inputs and are recorded by hand (see PREREGISTRATION section 10).

## Not yet in place

- `website/build.py` writes `data/state.json` with alerts, status, points, stations and readings, but
  not the forecast values or flags each town card showed. Decision records need that block before a real
  run can score anything.
- Nothing writes decision records or commits them to a `data` branch yet (PREREGISTRATION section 4).
