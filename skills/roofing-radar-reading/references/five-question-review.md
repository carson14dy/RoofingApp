# Five-question challenge for every weather reading

This is a claim-by-claim review, not a confidence vote. A second reviewer must try to produce an alternative explanation or a counterexample. Record disagreements and revise the claim to the scope the evidence supports.

| Question | Researcher must establish | Challenger must ask |
|---|---|---|
| What? | Variable, units, statistic, evidence kind and exact claim | Is this actually a measurement, estimate, report, warning, forecast or damage observation? Did a proxy become a fact? |
| Where? | Query latitude/longitude, source geometry, elevation, coverage and spatial relation | Does this source cover the pin, or only a nearby station/grid area? Could a boundary, height, terrain or land/water mismatch change the answer? |
| When? | Observation/issue/valid/receipt times, analysis cutoff, interval and timezone | Was the input available then? Is a current-looking display old? Did an hourly amount become an instantaneous rate, or a forecast become history? |
| How? | Source/product version, measurement/algorithm, quality flags and reproducible transformations | Which calculation produced the number? Are the units, geometry and uncertainty justified? Is provider agreement the same upstream data repeated? |
| Why? | Physical/empirical reason the evidence supports this specific inference | What competing explanation fits? What observation would falsify the claim? Why does it matter to this job without inventing damage or a safety clearance? |

For each numerical result preserve the raw value/unit, normalized value/unit, method/version and source. Do not add decimal places beyond justified precision. A precise map pin improves query identity; it does not improve the physical resolution of the source.

## Disposition

- **Supported as described:** evidence can support the qualified statement at its actual location/time/scale, subject to required human review.
- **Needs review:** an unresolved conflict, quality issue or spatial/temporal ambiguity prevents a stronger statement.
- **Withhold the claim:** required evidence is missing, incompatible, stale for the decision or outside coverage. Explain the gap; do not supply zero or a plausible replacement.

These are evidence dispositions, not probabilities of truth. An eligible synthetic record does not certify a provider, algorithm, forecast, or weather interpretation.

## Counterexample prompts

1. Could this hail return be a sampling/particle-mixture issue rather than hail at the roof?
2. Would a different accumulation interval reverse the rain statement?
3. Could the measured wind be elevated/exposed differently from the property?
4. Could an old forecast or later-revised historical report leak into the chosen time?
5. Could the weather change across this grid cell or a terrain/coast boundary?
6. Does “no data/no reports/no warnings” incorrectly become “nothing happened”?
7. Do the headline, map colors and numbers imply more certainty than the evidence panel?
8. What independent observation would test this interpretation, and is it actually available?
