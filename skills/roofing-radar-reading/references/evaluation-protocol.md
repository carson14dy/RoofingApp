# Evaluation protocol before accuracy claims

Status: specification, not an executed real-storm benchmark. Freeze the task, cases, procedure version, scoring and acceptable performance criteria before reviewing test results. Meteorological/editorial owners must set criteria for the intended use; do not invent a universal “news-ready” score.

## Case records and leakage controls

Each case needs: case/event IDs; geography/timezone; hazard/question; decision cutoff UTC; input evidence IDs; provider/upstream/product/version; observation interval; issuance/publication and receipt times; revision; historical availability evidence; quality/coverage; reviewer labels and their provenance. Preserve source snapshots or permitted references.

An input must have been available at the decision cutoff, not merely valid before it. Corrected archives, reanalysis, later reports and later warnings can be explicitly labeled outcome evidence; they cannot quietly become earlier inputs. If availability cannot be reconstructed, call the task retrospective interpretation, not operational forecast verification.

Group an evolving storm across radar domains, vendors and midnight boundaries. Split by independent events into development, validation and untouched test sets. Freeze the procedure before opening test outputs. Disclose famous-event familiarity. Reviewers evaluating outputs should be blinded to procedure version where practical; reviewers shown answer keys are not blind independent evaluators.

## Reference outcomes

Distinguish observed event, valid negative observation, unresolved and unobserved. No report is not a verified negative; an uninspected roof is not undamaged. Warning coverage is not proof the hazard occurred everywhere in it. An MRMS-derived vendor product cannot independently verify surface hail against MRMS. Preserve uncertainty in time/location, observer exposure and reporting bias.

Predeclare hazard definitions, event/object/site unit, lead-time interval, geographic tolerance, accumulation alignment and duplicates. Test justified tolerance sensitivity without selecting the best radius after outcomes are known. Rounded report times and town-level locations cannot supply exact parcel labels.

## Metrics

Report counts and denominators, not a blended “accuracy” number. For eligible resolved binary cases define hits H, misses M, false alarms F and correct negatives C:

- Probability of detection: H/(H+M).
- False-alarm ratio: F/(H+F).
- False-positive rate: F/(F+C).

An empty denominator is undefined, not zero. Report unresolved/excluded cases separately. Measure unsupported claims, warning preservation, product/time identification, stale/coverage handling, traceability and timing errors separately. If abstention is allowed, report answer coverage, error among answered cases and missed actionable hazards; saying “unknown” everywhere is not useful performance.

Compare old and revised procedures on identical decision-time inputs. Report paired outcomes and uncertainty clustered by independent event, plus region/season/range/terrain/product strata and representative quiet-day weighting. Proper probability scores require defined probabilities and independent outcomes; do not assign a percentage to qualitative words afterward.

## Staged gates

1. Execute deterministic unit/time/geometry checks and separately evaluate claim grounding. Retain actual outputs; arithmetic alone does not test interpretation.
2. Verify authoritative source contents, applicable versions, geographic limits and contracts.
3. Run a preregistered real-event benchmark with independent qualified adjudication, paired comparison and documented failures.
4. Shadow-test prospective operation for latency, outages, revisions, abstentions and recovery, with operational review and rollback.
5. Obtain qualified meteorological and editorial review for the specific public-reporting workflow.

Multi-agent agreement is internal review, not independent weather observation or professional certification. Passing synthetic exercises or a small flawless sample cannot establish near-perfect performance.

## Additional adversarial evaluation requirements

Include past-due ETAs from stale scans; ambiguous/zero speed; out-of-plane/terrain sampling; same storm split across midnight; reports published after cutoff; corrected hail sizes; unobserved quiet areas versus true negatives; warning expiration during outage; stale polygon graphics; current mosaic with stale local tile; old social clips; rounded/object-based hail sizes; onsite thunder despite no echo; misleading green clearance cards; and all-abstaining outputs. Exercise all supported geographies and do not imply nationwide validation from one region.
