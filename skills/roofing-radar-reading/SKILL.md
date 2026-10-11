---
name: roofing-radar-reading
description: Interpret U.S. radar and point-weather evidence for roofing decisions across hail, rain, wind and other hazards. Resolve precise map queries for current, forecast and historical conditions while preserving source location, resolution, time, uncertainty and independent warnings. Use alongside roofing-weather-intelligence.
---

# Roofing radar and point-weather reading

Version 0.3.0 — 2026-10-11. Local companion to the installed roofing-weather-intelligence skill. This file improves the interpretation procedure; it does not retrain a model, install a weather feed, or establish forecast skill. The original handoff remains unchanged. Scope now includes methods for several weather hazards and exact-coordinate queries; nationwide meteorological accuracy remains unvalidated. Point precision does not imply weather precision.

Read [the radar procedure](references/radar-procedure.md) before analysis and [practice cases](references/practice-cases.md) when evaluating changes. Source-verification and evaluation status are recorded in [validation](references/validation.md).

For public reporting, also apply [publication checks](references/publication-checks.md). This version is a reviewed draft, not approved for autonomous broadcast. A concise answer must still preserve evidence type, source time, uncertainty and official-warning status.

Use the [evaluation protocol](references/evaluation-protocol.md) before claiming improved accuracy and the [provider verification procedure](references/provider-verification.md) when comparing the user's weather services. See the [independent agent review record](references/review-record.md) for changes and unresolved evidence gaps.

## Choose the evidence procedure

| Request | Required procedure |
|---|---|
| Any map click, current/forecast/history | [Point-weather contract](references/point-weather.md), plus [reading contract](references/reading-contract.md) |
| Hail, rain intensity/amount, rain probability, flood relevance | [Hail and rain](references/hail-rain.md), with the radar procedure when radar is involved |
| Wind, outflow, downburst, rotation, tornado | [Wind and tornado](references/wind-tornado.md), plus independent official warnings |
| Lightning, snow/ice, heat/cold, fog or other weather | [Other hazards](references/other-hazards.md); use the relevant non-radar observations and product limits |
| Research or a contested inference | [How/what/where/when/why review](references/five-question-review.md) and the evaluation protocol |

Retrieve only the relevant evidence; more feeds do not automatically improve a reading. If the product or geography is unsupported, report unavailable/unknown rather than inventing a point value. For an unspecified location, improve the method or ask for the location before claiming actual local conditions.

For a map click preserve the requested latitude/longitude and answer in separate **Current**, **Forecast**, and **History** modes. Every displayed value needs its source, evidence kind, location/footprint relationship, observation or valid time, and quality/freshness state. Show measured-at-site, nearby observation, grid estimate, forecast and historical report distinctly. A pin inside a grid cell does not imply that the value was measured at that pin. Current readings describe the latest usable evidence and its age, not an invented measurement at the present second.

## Workflow

1. Establish the decision, location, local timezone and event time. For a supplied image, read the image before interpreting it. Identify unknown metadata instead of filling gaps with assumptions.
2. Identify radar site/mosaic, product, units/legend, elevation, scan time, valid interval and display time. Determine whether imagery is observed, forecast, archived or simulated. A generated concept is not weather evidence.
3. Retrieve current official warning information independently for a current-weather task. Preserve warning instructions, validity and geometry. Radar interpretation never cancels a warning or proves an all-clear.
4. Check beam height/range, terrain blockage, clutter, anomalous propagation, melting-layer effects, attenuation, missing gates, velocity folding and processing artifacts as relevant. Mark uncertain coverage before discussing hazards.
5. Describe observations first, then candidate interpretations. Use a time sequence and consistent products for motion or trends; seek at least three comparable scans as a working practice, not a universal detection requirement. State what a single image cannot establish.
6. Cross-check reflectivity with velocity, dual-polarization products, neighboring radars, environmental context and time-matched surface reports when available. Distinguish agreement from independent evidence: several products may derive from the same radar.
7. Calculate timing, geometry and units with code. Separate cell motion from radial wind. An extrapolated arrival is conditional on persistence and track; do not attach an invented confidence interval.
8. Translate evidence into roofing relevance: active warning response, approaching precipitation, possible hail exposure, scheduling uncertainty or inspection follow-up. Apply company/material criteria when provided. Do not invent roof-level measurements or damage conclusions.
9. Audit every claim against the input. Report missing/stale evidence and the next useful observation. Never claim unattended monitoring is running without verifying it.

## Response format

- **Read:** Product, location, observation time/timezone, source and age.
- **Observed:** What the imagery/data actually shows, with evidence references.
- **Interpretation:** Supported explanation and credible alternatives.
- **Roofing relevance:** Decision implications tied to warnings and supplied work rules.
- **Limits / next check:** Coverage, conflicting evidence, conditional timing and review trigger.

Use plain language first; put technical metrics after the decision explanation. Confidence should describe the evidence for a particular claim, not a single score for the entire storm. Do not give numerical confidence without a validated method.

## Hard boundaries

Do not infer exact hail size from reflectivity, a surface gust from radial velocity, a tornado from a color couplet alone, roof damage from MESH, or an all-clear from a blank/stale radar display. Do not turn a report buffer into an observed footprint. Do not apply universal dual-pol cutoffs across products, heights and environments. Missing observations remain unknown.
