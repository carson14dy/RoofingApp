# Practice cases and worked interpretations

These are synthetic reasoning exercises, not observed storms or a held-out accuracy benchmark. Each worked answer is a reference interpretation; it does not establish that a model or application passed an automated test.

| Case / supplied evidence | Worked interpretation | Reject |
|---|---|---|
| 1. Screenshot described as reflectivity: prominent core, no legend/time/site | A visually prominent colored feature is present; product, physical magnitude and freshness are unverified. Obtain metadata and a sequence. | Exact hail size, storm speed or current status |
| 2. Fresh retrieval, observation time 45 minutes old | Retrieval succeeded; the observation is 45 minutes old. Apply product-specific freshness policy; current storm state remains unresolved. | “The storm dissipated” or “live” |
| 3. Broad zero radial velocity band; wind crosses the beam | Small along-beam component does not establish calm winds. Check geometry and other evidence. | “No wind hazard” |
| 4. Sharp opposing velocities, unknown Nyquist/de-aliasing status | Rotation is a candidate interpretation; check folding, geometry, adjacent scans/elevations and warnings. | Confirmed tornado or touchdown |
| 5. Low CC in a weak-echo region without credible rotation | Nonmeteorological returns or low signal are alternatives; this is insufficient for a debris signature. | Tornado debris confirmation |
| 6. Hook-like reflectivity with no velocity product | Shape warrants a cross-check; reflectivity shape alone cannot establish rotation/tornado. | Tornado certainty |
| 7. Reflectivity maxima increase after changing from base to composite | The products sample differently; this comparison cannot establish intensification. | Stronger surface hail from unmatched products |
| 8. Distant low-elevation scan with no echo at the job | Check beam height, terrain and other observations; overshoot/coverage limits can leave low-level weather undetected. | Guaranteed dry conditions |
| 9. MESH 1.5 inches; 0.75-inch report 8 km away, 10 minutes later | Preserve the estimate and the report with separate locations/times. Neither measures hail at the job. | Average of 1.125 inches or confirmed roof damage |
| 10. 60-minute maximum hail swath crosses job; latest instantaneous field is weak | The field depicts the maximum radar-estimated hail value at an overlapping grid cell within the product interval. It does not establish hail at the ground, at that roof, or now. | Actual hail occurrence or timing inferred from the historical estimate |
| 11. Active official warning; model and local radar look quiet | Retain official warning and instructions. Investigate coverage/timing; radar cannot cancel it. | All-clear or model-based suppression |
| 12. Terrain-blocked sector represented as blank pixels | Surface conditions are unknown there. Retain the coverage gap and use justified alternatives. | Zero hazard assigned to missing cells |
| 13. Two vendor maps share the same MRMS upstream | They are not independent corroboration. Preserve lineage. | Double-counted confidence |
| 14. Generated radar video from this handoff | Useful only for interface/motion demonstration. All depicted weather is simulated. | Real storm identification or forecast validation |
| 15. Cell moves 24 km east in 12 minutes; job 40 km east and 15 km north of its latest observed center | Under constant motion: 120 km/h, closest approach 20 minutes after that observation, 15 km cross-track distance. No job-hit prediction without a storm footprint. | Distance/speed used as time of impact |
| 16. Same track; job 10 km west of its latest observed center | Closest approach was 5 minutes before that observation under the assumed track. Changes/new development remain possible. | Positive future ETA from unsigned distance |
| 17. Growing line forms new cells ahead of tracked center | Extrapolating one center misses development. Describe conditional timing and seek additional scans/guidance. | Precise guaranteed arrival |
| 18. Warning feed unavailable while radar is readable | Interpret radar with limits and explicitly say official warning status was not verified. | “No warnings” from a failed request |
| 19. Strong azimuthal velocity gradient with both sides outbound | Background flow can keep a candidate circulation on one side of zero; inspect geometry, sampling and sequence. | “No rotation because colors match” or automatic tornado confirmation |
| 20. Opposing velocities primarily along one radial | Consider convergence/divergence and artifacts, not just rotation. | Every inbound/outbound pair called a tornado |
| 21. Debris signature persists aloft after low-level circulation changes | Lofted debris does not locate an exact present touchdown or identify damaged buildings. | Exact current tornado/roof damage claim |
| 22. Latest position at 14:00 UTC gives 20-minute closest approach; retrieval at 14:12 UTC | Conditional closest approach is 14:20 UTC, eight minutes after retrieval, not 14:32. Check freshness/evolution before operational use. | Arrival clock restarted at download time |
| 23. Reflectivity and CC shown at 14:05; velocity sampled at 14:01 in a fast-moving storm | Temporal mismatch weakens apparent co-location; obtain field times and comparable observations. | Debris/rotation confirmed from mismatched panels |
| 24. Overnight date boundary and daylight-saving time transition | Preserve UTC instants and use a timezone-aware conversion with explicit date/offset. | Ambiguous local time used for event matching |
| 25. High reflectivity ring near the melting level in stratiform precipitation | Investigate bright band and thermal/height context; this convective procedure does not establish surface hail. | Hail diagnosis from reflectivity alone |
| 26. Last verified warning expires while the warning feed is unavailable | Give the last verified message and its stated validity; current warning status is unverified. Expiration neither extends the warning nor proves hazards ended. | Indefinite active warning or all-clear |
| 27. New verified warning update removes a town, but an old graphic still covers it | Correct or clearly label the historical graphic and use the latest verified message scope. Retain any unresolved spatial ambiguity. | Stale polygon presented as current |
| 28. Cautious text beside a green “safe to resume” roofing card | Reject the graphic's unsupported clearance claim; radar cannot resolve all site hazards. | Visual certainty contradicted only in fine print |

## Evaluation before claiming improved performance

Use timestamped real radar volumes/loops, full product metadata, warning records and independent observations. Include ordinary rain, hail, non-tornadic rotation, folding/clutter, melting layers, terrain/range gaps, missing feeds and storm evolution. Use event/date-based held-out splits; do not leak later reports or revised records into an earlier decision-time task.

Have qualified reviewers label observations, defensible interpretations, required uncertainty and prohibited claims. Score product/time identification, quality checks, motion/geometry correctness, alternative explanations, source attribution, warning preservation and unsupported claims. Report misses and false alarms as well as correct cases. Evaluate damage claims separately against inspections; an uninspected roof is unknown.

Run both the old and revised procedures on the same held-out cases with the same inputs. Retain raw responses and reviewer disagreements. A worked-answer table, self-review or deterministic arithmetic check is not evidence of improved meteorological accuracy.
