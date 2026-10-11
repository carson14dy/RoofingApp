# Roofing Weather Intelligence — Independent Challenge Review
October 11, 2026

## Verdict
The existing research is a credible starting architecture, but it does not establish the best-performing weather system for roofing companies. Four independent AI reviewers examined meteorology, data vendors, engineering reliability and roofing workflows. The lead reviewer checked the major findings against primary sources and challenged an incomplete vendor conclusion.

The result is a stronger research and implementation plan. This was a documentation review, not a meteorologist certification, live API trial, accuracy benchmark or deployed-system test. Reviewer agreement is not independent scientific validation.

Reviewed: Roofing_Weather_Claude_Handoff.md and Roofing_Weather_Engine_Blueprint.md. This review supplements those documents and supersedes their incomplete provider shortlist and general advanced-source/refresh guidance. Existing code and production behavior were not inspected.

## What survives the challenge
Keep official NWS forecasts/alerts as the baseline; source-linked evidence; separate estimates, reports, forecasts and inspections; deterministic calculations; explicit freshness and coverage states; independent official-alert delivery; and a product-specific national coverage matrix.

Keep the ability to teach versioned procedures. A skill is a reasoning/workflow resource; continuous collection requires a running service, and adding documents does not retrain a foundation model.

## Priority findings and decisions

| Priority | Finding | Decision for Claude |
|---|---|---|
| P0 | Alert location matching can silently omit applicable warnings. | Add explicit point/county/zone/polygon and null-geometry tests before launch. |
| P0 | “Continuously updates” lacks recovery and lifecycle acceptance gates. | Test revisions, out-of-order events, duplicates, outages and evidence replay. |
| P0 | No comparison demonstrates better forecasting or decisions. | Establish a baseline and predeclare evaluation metrics before selecting advanced feeds. |
| P1 | Roofing context is underspecified. | Add material/system, work phase, duration, dry-in time and site verification fields. |
| P1 | Advanced severe-weather source research is incomplete. | Trial current SPC intensity guidance and operational ProbSevere v3; investigate lightning observations and forecasts separately. |
| P1 | Commercial hail shortlist is too narrow. | Compare Xweather, The Weather Company, Verisk and Cotality against NOAA/MRMS for their respective tasks. |
| P1 | Generic source cadence is insufficient. | Pin each chosen product's version, units, accumulation window, cadence and missing-value semantics. |
| P2 | Raw national model ingestion may be premature. | Add products only when held-out evaluation shows useful incremental value. |

P0 means before a production claim; P1 means part of the next implementation/research pass; P2 is a later candidate. These priorities are review judgments.

## Verified corrections

### Alert matching
NWS says queries using a public forecast zone can omit county-based watches and warnings. Point queries resolve both county and zone; county results may include zones elsewhere in that county. Some valid alerts have null geometry. County and public-zone boundaries are not one-to-one, and zones change. [1]

Use an explicit alert applicability rule: source polygon when present, otherwise appropriate source county/zone coverage. Preserve the scope in the UI. Do not interpret null geometry as no alert. Refresh boundary/mapping data and test sites near boundaries.

### More useful advance guidance
SPC documentation now includes Conditional Intensity Groups alongside probabilities. Preserve event likelihood separately from intensity conditional on occurrence; regional probabilities describe events within 25 miles of a point, not a roof-hit probability. [2]

CIMSS states ProbSevere v3 became operational at NOAA in August 2025 for CONUS. Make it a concrete trial candidate. [3] Its next-hour storm probabilities depend on identified storm objects; shallow/low-lightning storms and squall-line tracking are documented limitations. Never let a low score suppress an official warning. [4]

LightningCast predicts lightning using a GLM-based target. It is not a ground-strike observation feed; documented seasonal/cloud limitations require evaluation. Its retrieved guide is dated January 2024, so confirm current deployment/version separately. [5] Research observed lightning and predictive guidance as distinct inputs.

### Product-specific timing
MRMS lists MESH and 30/60-minute MESH swaths at two-minute update frequency, while 120/240/360/1440-minute swaths are listed at 30-minute frequency. [6] A swath maximum belongs to an interval, not necessarily the latest timestamp. Validate the exact delivered version against its specification; show source age independently from successful retrieval.

### Corrected Xweather conclusion
Our follow-up challenge found a separate documented `/hail/archive` endpoint. It lists U.S. history beginning January 1, 2024, hourly updates, 24-hour query increments and a 12x multiplier. [7] Therefore Xweather belongs in the recent-history comparison as well as the live-weather comparison. The existence of that archive does not prove its forensic accuracy, completeness or equivalence to a competitor.

## Conditional provider comparison
This table is a trial shortlist, not a quality ranking.

| Candidate | Appropriate comparison | Key unresolved question |
|---|---|---|
| NOAA/NWS/SPC/MRMS | Baseline official guidance, reports and estimated hail | Cost and expertise of processing/operating the selected data pipeline |
| Xweather | Live weather, hail nowcasts, recent hail archive, lightning, integration convenience | Exact product coverage, latency, archive method, commercial rights and billable usage |
| The Weather Company | HailZone short-range hail guidance and map delivery | Independent incremental value, upstream overlap, access terms and production quote |
| Verisk Benchmark | Property weather history | Current schemas, archive depth, correction history, bulk cost and SaaS/export rights |
| Cotality Weather Verify | Historical hail verification | Structured API access, event finalization, accuracy evidence and commercial rights |

The Weather Company's HailZone documentation describes a CONUS 30-minute forecast with 1-km data and five-minute refresh. [8] Verisk's official API brochure supports business integration of weather history, but is dated 2022 and is not a current contract. [9] Cotality documents continental-U.S. hail reporting and API integration. Treat its accuracy/claims marketing as claims to test, not independent proof. [10]

Xweather also documents an MCP service and a Phrases API. Evaluate these as ways to reduce integration work and as a baseline for readable summaries. They do not replace the app's job rules, evidence checks or continuous runtime. [11–12]

### Cost correction
Xweather publishes a $0.0006 base access rate, 15,000 shared free monthly accesses, and premium multipliers including 12x hail. [13] The earlier statement that no pricing was confirmed was incomplete.

Illustrative arithmetic, not a quote: 1,000 properties polled once per minute for 30 days produces 43.2 million requests. At 12x that is 518.4 million accesses; applying the published base rate after 15,000 free accesses yields $311,031. This deliberately inefficient design illustrates why territory sharing, caching, event-driven updates and negotiated volume terms matter. It is not a forecast of this app's costs.

Model realistic scenarios for active territories, jobs, map sessions, archives, AI summaries and notifications. Apply budget limits. Do not assume a webhook eliminates underlying data charges.

## Roofing-specific changes
Represent each job with its roof system and exact product, planned phase, required uninterrupted duration, expected time to make an open roof weather-tight, company criteria and required site checks. Distinguish inspection, tear-off, installation, adhesion/coating and staging.

Manufacturer guidance supports this distinction: GAF directs product-specific shingle procedures, while Carlisle discusses material temperature and condensation during adhesive flash-off. [14–15] These are reasons to capture site/material conditions; a forecast does not establish a dry deck or ready adhesive. Do not transfer thresholds between products.

Add relevant heat information. NWS distinguishes WBGT, which accounts for more environmental factors, from shade-based heat index. [16] Preserve whether a value is forecast or measured and use company procedures; do not generate individualized work/rest rules from a regional forecast.

Suggested home-screen order: active warnings; today's jobs needing review; tomorrow's scheduling conflicts; inspection candidates. Each card should say what changed, which job, when, why and what to review. Put technical layers behind details. Avoid an unexplained universal 0–100 roofing score.

## Revised build sequence
1. Keep nationwide data interfaces and a product-by-region coverage matrix.
2. Validate a complete daily job-planning workflow in one service territory and one roof-system family.
3. Deliver official alerts independently of AI; collect job context and show evidence freshness.
4. Add reports and one estimated hail source to an inspection queue.
5. Run commercial comparisons and advanced-source trials in shadow mode.
6. Expand across regions and seasons after demonstrated reliability and usefulness.

A narrow pilot accelerates testing; it does not redefine the nationwide goal or establish national accuracy.

## Evaluation that can support a “better” claim
Compare:
A. Existing company practice plus official NWS guidance.
B. Same sources with deterministic job-specific rules.
C. Additional weather feeds and AI explanations.

This separates the value of job context from the value of extra data or prose.

Use event/date-based held-out splits, not random neighboring pixels. Preserve what was available at decision time; do not leak revised history into the earlier forecast. Include quiet days, missed storms, different seasons/terrain, radar gaps and relevant regions. Validate against independent observations where possible; MESH agreement alone is not ground-truth hail verification.

| Evaluation area | Measures |
|---|---|
| Weather | Misses, false alarms, useful lead time, magnitude/timing errors; probability calibration and Brier score where appropriate |
| Operations | Review time, unexpected interruptions per 100 job-days, rescheduling reasons and completed phases |
| Inspection targeting | Findings per crew-hour plus sampled comparison properties and evidence quality |
| Language | Correct understanding of job, time, uncertainty and next action; unsupported claims |
| Reliability | Alert matching/revisions, stale detection, processing and delivery latency, recovery |
| Economics | Provider, compute, AI, map and notification cost per active company/job |

Probability verification should assess calibration and discrimination, not just attractive maps or confident wording. [17] Uninspected properties are unknown, not negative damage examples. A short pilot is not proof of nationwide performance.

### Proposed release gates
These are initial engineering targets for the team to refine, not vendor guarantees or completed test results:
- At least 100 curated alert lifecycle/geography scenarios: no missed applicable severe/tornado alert within that suite and no duplicated user notifications.
- Every injected feed outage displays appropriate stale/unavailable status; no missing-data all-clear.
- At least 500 adversarial summaries: no invented numerical facts, alert changes or unsupported work-clearance statements.
- Trace every displayed number/time/location to evidence.
- Initial p95 target under 60 seconds from successful alert retrieval to notification-provider acceptance; report upstream and device-delivery delays separately.
- Replay a peak regional day at three times its input rate and recover from a 30-minute ingestion interruption without lost normalized records.
- Report confidence intervals and geographic/seasonal limitations for comparative results; predeclare what constitutes meaningful improvement.

## Procurement questions
For each product request documented region/period coverage, native resolution, upstream sources, probability/size meaning, validation methods, latency distribution, revisions and as-of archive access. Confirm multi-company display, homeowner exports, storage/retention, AI use, contract-end access, per-unit charges and trial datasets. No accounts, purchases or vendor outreach were performed during this review.

## Claude handoff
Continue the existing implementation, but apply this review before expanding data sources. First build correct alert geography/lifecycle handling, versioned evidence and job context. Pin each feed contract and keep warnings independent of generated prose. Implement a baseline and replay harness. Add advanced guidance and vendor adapters as evaluated candidates. Report measured results and unresolved rights/coverage/cost questions. Do not describe any provider or model as best until the predefined comparison supports the specific claim.

## Sources checked
1. NWS geolocation: https://www.weather.gov/media/documentation/docs/NWS_Geolocation.pdf
2. SPC current outlooks: https://origin-west-www-spc.woc.noaa.gov/about/outlooks/
3. ProbSevere status: https://cimss.ssec.wisc.edu/probsevere/ps/
4. ProbSevere guide: https://cimss.ssec.wisc.edu/probsevere/wp-content/uploads/sites/29/2025/11/ProbSevere_QuickGuide.pdf
5. LightningCast guide: https://cimss.ssec.wisc.edu/probsevere/wp-content/uploads/sites/29/2025/11/LightningCast_QuickGuide.pdf
6. MRMS product table: https://www.nssl.noaa.gov/projects/mrms/operational/tables.php
7. Xweather archive: https://www.xweather.com/docs/weather-api/endpoints/hail-archive
8. HailZone: https://developer.weather.com/docs/openapi/hailzone-30-minute-2-0
9. Verisk API brochure: https://www.verisk.com/siteassets/media/downloads/property-estimating/benchmark-api-brochure-2022.pdf
10. Cotality Verify: https://content.cotality.com/product-docs/claims-weather-hail-verify/
11. Xweather MCP: https://www.xweather.com/docs/mcp-server
12. Xweather Phrases: https://www.xweather.com/docs/phrases-api
13. Xweather pricing: https://www.xweather.com/pricing/weather-api-pay-as-you-go
14. GAF bulletin: https://www.gaf.com/en-us/document-library/documents/technical-bulletins-%26-notes/r-114-hand-sealing-shingles.pdf
15. Carlisle guidance: https://www.carlislesyntec.com/en/Resources/Media/Blog-Landing-Page/TecTopics/2020/11/17/Cold-Weather-Installation-Tips-for-CAV-GRIP-III-and-CAV-GRIP-PVC
16. NWS heat measures: https://www.weather.gov/ict/WBGT
17. NWS probability verification: https://www.weather.gov/media/owp/oh/hrl/docs/OHD_ProbVerifIntro.pdf

