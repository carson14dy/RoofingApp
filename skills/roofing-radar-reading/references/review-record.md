# Independent agent challenge and disposition

## Version 0.3.0 research and challenge round

Seven separately tasked agents contributed: three hazard researchers, a point-weather researcher, an evaluation/checker author, a science challenger and a public-reporting challenger. The primary agent integrated changes and independently ran the tests.

| Challenge | Correction and verification |
|---|---|
| Exact pin becomes exact property weather | Preserved source footprint, station distance/age/statistic, grid/radar sampling and per-variable gaps. |
| Timestamp assumed to mean instantaneous | Unknown averaging/sampling duration stays unknown; a case was added. |
| Forecast must be wholly future | Preserved forecast class for underway intervals and historical replay. |
| Hail estimate implies actual exposure | Overlap wording now leaves surface occurrence unconfirmed. |
| Numeric boundary inclusion implies certainty | Preserved positional uncertainty spanning the alert boundary. |
| Approximately 20-minute delay sounds like a ceiling | Explicitly documented as a possible delay, not a guaranteed bound. |
| Rain PoP example applied to snow depth | Required appropriate winter liquid-equivalent/product definition. |
| Tropical routing omits jurisdictions | Added Guam/CNMI source/jurisdiction verification. |
| Provider supplies its own permissive rules | Required separately reviewed, versioned policies and explicit fixture trust limits. |
| Checker allows unsupported values/times | Added mandatory value grounding, recent-current semantics, time ordering, lead limits and source/product binding. |

Science and communication reviewers verified their corrections with no outstanding targeted finding. The final checker has 35 passing synthetic tests. Source/empirical gaps remain; review agreement does not quantify weather accuracy. See validation.md for current status.

## Version 0.2.0 history

Reviewed 2026-10-11. Three separately tasked agents read the draft and original project guidance without editing the files. The primary agent integrated findings; all three performed a second pass. This is internal adversarial document review, not independent meteorological certification.

| Reviewer task | Principal findings | Disposition |
|---|---|---|
| radar_science_review | Reflectivity is not received power itself; Doppler samples scatterer motion; same-sign azimuthal shear and along-radial convergence need distinction; debris may persist aloft; MESH overlap is not hail occurrence | Corrected definitions and examples; added field-level timing, beam-volume, KDP and dual-pol caveats. Second pass found all five high-priority findings addressed and no new high-priority regression. Minor observation-time wording was subsequently corrected. |
| evaluation_review | Need decision-time availability, labels for unknowns, frozen matching rules, grouped event splits, metric denominators and abstention coverage; ETA must anchor to observation time | Added evaluation-protocol.md and corrected ETA/swath wording. Second pass confirmed high-priority specification findings addressed without substantive regression. Real-event testing remains outstanding. |
| broadcast_review | Need publication gate, warning lifecycle/outage behavior, tornado attribution, freshness on graphics, no roofing clearance and question-specific evidence authority | Added publication-checks.md and expanded synthetic cases. Second pass confirmed the main communication findings addressed; suggested lifecycle and misleading-graphic cases were added. No actual broadcast workflow was validated. |

## Remaining disagreement and limitations

No unresolved substantive disagreement was reported in the second passes. That is not a probability of correctness. Reviewers may share blind spots and prior knowledge. Their official-source retrieval attempts were independently blocked by proxy 403; multiple blocked requests provide no source verification.

Uncompleted external evidence: current authoritative-document verification; actual access to the four weather plugins; held-out real-radar evaluation; prospective shadow operation; qualified meteorologist/editor approval. This revision may be used as an explicitly unvalidated working procedure and a handoff to Claude, but not advertised as nationwide-news accuracy.
