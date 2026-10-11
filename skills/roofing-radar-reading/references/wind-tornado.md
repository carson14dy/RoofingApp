# Wind, tornadoes and warning interpretation

Research revision: 2026-10-11. This is a procedure with source checks and arithmetic exercises, not measured operational skill or approval for autonomous public warning interpretation. Use it with the radar procedure, publication checks and evaluation protocol. Distinguish source-backed facts below from explicitly identified working synthesis.

## What question can each source answer?

| Evidence | Permitted claim | What it cannot establish |
|---|---|---|
| Quality-controlled anemometer observation | Reported mean, gust or peak at its instrument, time and averaging interval | Wind at another roof, a whole storm maximum, or an unmeasured peak between samples |
| Radar Doppler radial velocity | Along-beam motion of sampled scatterers, at the sampled height/time and with quality limits | Full three-dimensional wind, surface gust, roof uplift or tornado intensity |
| Radar circulation/dual-pol interpretation | Evidence consistent with rotation or, with sufficient context, lofted debris associated with a tornadic circulation | An exact present touchdown coordinate, damage at a named property, or an EF rating |
| NWS watch/warning/statement | The issuing office's current hazard assessment, affected geography and instructions | Measured conditions at every point in the warned area or proof the hazard ended when the message expired |
| Forecast wind/gust field | A prediction for the named grid, height, period and forecast issue/run | An observed gust or measured roof-level conditions |
| Local storm report, verified eyewitness account or survey | What the source reports at its time/location, with estimate/measurement and revision status | Uniform conditions between reports; no report does not establish no event |

For a wind reading, preserve `statistic` (mean/gust/peak), `value`, `units`, `averaging_seconds`, `search_interval_start/end`, `measurement_height_agl`, instrument/station identity, location and its uncertainty, observation time, publication/receipt times, QC status and missing reason. Unknown fields remain unknown. A gust averaging interval and the period over which the maximum was searched are different fields.

## How, what, where, when and why: a repeatable reading

1. **What:** Identify whether the task is current warning relay, site wind measurement, regional damaging-wind interpretation, tornado interpretation, forecast planning or retrospective exposure review. A request for an “accurate wind reading” does not supply the measurement height, time or statistic; explicitly state the available quantity.
2. **Where:** Establish the job coordinates, horizontal uncertainty, elevation, instrument location and exposure. For radar, determine site, range, elevation angle and sampling height relative to local terrain. For a forecast, retain the grid footprint. A geocoded town center or airport reading must not silently become a measurement at a roof.
3. **When:** Use the observation/valid time or interval for the hazard, issue time for a forecast or warning, and receipt time for delivery performance. Check source revision and age at analysis time. A recently fetched record can describe old weather. API documentation currently warns that MADIS QC/ingest can delay station observations by about 20 minutes; that is a documented possibility, not a guaranteed latency bound [W4].
4. **How:** Check units, statistic, instrument and radar quality; align fields and reports in space/time; inspect evolution; evaluate alternatives; then calculate conversions and geometry deterministically. Use verified product conventions instead of assuming that every gust has the same averaging period.
5. **Why:** State the decision supported by the evidence: follow an official warning, review an approaching outflow, plan for forecast gusts, or investigate reported exposure. Do not turn a meteorological threshold into a universal work-stop/work-resume rule. Use the employer's and material/system's rules plus appropriate site observations; remote information cannot certify a roof safe.

Finish with a claim-specific reason for uncertainty and the next observation that would reduce it. “Two vendors agree” is insufficient if both use the same radar, station or model.

### A map click selects a location, not an instrument

For each clicked coordinate return distinct current, forecast and historical evidence with its actual support. **Current wind:** name the reporting station, distance/direction from the click, observation age, statistic and exposure/height status; a model analysis or provider interpolation remains an estimate. **Forecast wind:** name the grid/model/product, issue/run and valid interval, statistic and height; an API accepting exact coordinates does not imply exact parcel resolution or accuracy. **Historical wind:** show measurements at their station/time, reports with original location/time uncertainty, and any retrospective modeled/radar estimates separately. Reanalysis is not a contemporary observation. A warning polygon is the official warning geography, not an observed wind footprint. Preserve the selected coordinate while visibly indicating when the evidence applies only to a nearby station or a larger area; if no supported site reading exists, say that the site reading is unavailable.

## Surface wind: measurement and representativeness

- Read the statistic before the number. Mean/sustained wind, maximum gust over a reporting window, instantaneous sensor output and daily peak are not interchangeable. No gust in a report may mean the reporting criterion was not met or the value was unavailable; it is not an explicit zero-gust measurement. Preserve raw status and provider documentation.
- Confirm sensor height, siting, exposure, obstructions, terrain, sampling rate, calibration/maintenance information and QC flags where available. A sensor beside a building can be sheltered or accelerated; an airport instrument has different surroundings from a roof. Do not select the geographically closest station without checking these attributes.
- The March 1998 ASOS User's Guide describes a two-minute mean, nominal 10 m siting with permitted variations, and historical five-second averaging procedures [W3]. It is **historical documentation**. Do not assert that its gust algorithm or hardware describes today's selected station: obtain current station/instrument and product documentation. Retain an unknown averaging interval when verification is unavailable.
- Meteorological wind direction usually means the direction the wind comes **from**. Check true-versus-magnetic reference and product conventions; do not substitute the direction the air travels toward. In a flat horizontal illustrative model with clockwise-from-north direction `D`, eastward component `u = -S sin(D)` and northward component `v = -S cos(D)`. Convert degrees to radians in code. Do not average compass headings arithmetically across north.
- Convert units using exact definitions where possible: `1 knot = 1852/3600 m/s`, `1 mph = 0.44704 m/s`. Preserve source precision. A numerical conversion is not improved instrument accuracy.
- Avoid generic adjustments from a 10 m forecast or station to a roof. Height/exposure corrections need an appropriate validated method, stability/roughness assumptions and their uncertainty; building edges, wakes and terrain may invalidate a simple profile. Do not infer roof pressure or damage from wind speed alone.
- Treat icing, blocked/failed sensors, impossible jumps, frozen values, nonstandard exposure and disagreement as quality questions. Cross-check metadata and neighboring observations; do not delete a localized real gust merely because neighboring stations missed it.

## Radar wind, downbursts and rotation

The following radar interpretation is established-physics **working synthesis** consistent with the existing radar procedure. Targeted operational training sources were not retrievable in this session [B1–B4]; no new radar threshold or automated detector is validated here.

1. Confirm ground-relative versus storm-relative velocity; radar origin, sign/color convention, units, elevation, range, Nyquist velocity, de-aliasing, missing gates and usable signal. Storm-relative velocity depends on an assumed storm vector and must not be converted directly into a ground-level gust or storm speed.
2. A radial measurement is a projection. In an illustrative horizontal, stationary-radar model, with positive velocity away from the radar and azimuth `A` clockwise from north, `Vr = u sin(A) + v cos(A)`. It omits vertical motion, particle fall speed, beam elevation and other real effects. Strong wind crossing the beam can have near-zero `Vr`; the equation is not a method to retrieve an unknown full wind vector from one beam. Never divide by an assumed alignment angle to manufacture a surface gust.
3. Inspect coherent features over comparable elevations/scans and, when possible, other radar views. Folding, sidelobes, clutter, broadening, missing gates, low signal and beam height can produce or hide apparent velocity gradients. A single colorful pixel is not a wind observation at a roof.
4. A compact mainly azimuthal shear pattern can support a circulation interpretation; primarily range-directed differences may instead support convergence or divergence. Real geometry and background flow complicate both. Rotation can have both sides outbound or both inbound. The inbound/outbound color boundary alone is neither necessary nor sufficient for rotation.
5. Bowing reflectivity, rear-inflow structure, a spreading near-surface divergence pattern, an outflow fine line or a pressure/wind shift are supporting clues, with different sampling limits. Do not name a downburst or assign its peak surface speed from a bow echo alone. A gust front can lead the rain and new storms can form along it; a dry radar pixel at the job is not wind clearance. Sparse surface stations may miss a narrow downburst.
6. Recognize nonconvective threats. Pressure-gradient wind, mountain-wave/down-slope wind, gap flow, tropical wind and other local effects may occur with weak or absent precipitation echoes. Bring in appropriate forecasts, stations and official alerts. A convective-radar workflow is not a validated method for all these regimes.
7. Radar-indicated rotation aloft does not itself establish tornado touchdown. A credible debris interpretation requires spatial/time agreement of rotation, suitable reflectivity and a correlation-coefficient reduction, with alternatives such as hail, melting particles, low signal and nonmeteorological targets addressed. Absence of a debris signature cannot exclude a tornado; do not delay warning response while seeking one. Debris can remain aloft after the near-surface circulation changes.
8. Do not assign an EF rating from gate-to-gate velocity, echo shape or a generic damage photograph. NWS explains that EF ratings use surveyed damage indicators/degrees of damage to estimate winds [W7]. Attribute an official rating and its preliminary/final status. Damage-estimated wind is not an anemometer measurement.

## Warnings and forecasts must remain distinguishable

- Obtain current official NWS alerts on an independent path and preserve issuer, message identifier, sent/effective/onset/expiry times, references/revision, affected geometry/geocodes and instructions. Existing warnings are not delayed pending radar analysis or agent agreement. A commercial relay of the same NWS warning is delivery redundancy, not independent confirmation of tornado occurrence.
- A tornado watch means conditions support tornadoes in/near the watch area; a warning calls for action when a tornado has been sighted or indicated by radar [W1]. Quote the specific current message for “radar indicated,” “observed,” “confirmed,” “considerable,” “catastrophic” or “tornado emergency.” Do not infer a tag from an image, read a damage-threat tag as a damage survey, or replace official wording with a homemade certainty ladder. Warning potential wind/hail tags are not measured gusts/hail sizes.
- Alert selection needs correct geography. NWS's current Geolocation Guide says a public/fire forecast-zone query does not return county-based warnings or watches. County-UGC queries can return both classes but may include alerts for other portions/zones of the county; point queries resolve both county and zone codes [W5]. Retrieve candidates with a documented method and apply verified geographic semantics before claiming the job is inside the warning. This document does not certify API point-filter behavior at an exact polygon edge.
- Null geometry is expected for county watches and zone-based alerts [W5]. Resolve the provided codes using applicable boundary data; missing geometry does not mean unaffected. Preserve longitude/latitude order, coordinate reference, boundary version, holes/multipolygons, and the geocoder's location uncertainty. A boundary-adjacent or ambiguous point requires an explicitly uncertain match, not false precision.
- Correctly process updates, cancellations, supersession, corrections and expiration using the applicable CAP/VTEC contracts and actual messages. Do not keep an old polygon displayed as current after a replacement. Do not infer “no warnings” from an empty failed response or an expired cached message. Say what was last verified and when; expiration does not demonstrate that wind or tornado risk has ended.
- API documentation states tornado-watch content comes from the local WFO WCN, not the SPC SEL wording [W4]. Preserve the source product when quoting watch text. The VTEC overview currently advertises a consultation on potentially moving away from VTEC [W8]; this is not evidence that such a change has been adopted. Reverify operational contracts before implementation.
- Forecast mean wind, gust potential, wind probability and conditional intensity are separate quantities. Match issuance/run, valid interval, grid/height and ensemble/deterministic meaning. Do not back-convert qualitative forecast words to an invented probability, infer a gust from mean wind using a universal factor, or promote a later forecast to an earlier decision-time input.

## Independent truth and achievable validation

Use the existing event-held-out evaluation protocol. The wind/tornado additions require:

1. **Instrument truth:** Obtain QC-controlled station records with documented statistic, averaging/search windows, exposure, location and time. If the product under test already ingests that station, record the dependency and keep genuinely withheld observations or independent sensors for claims of independent validation. Radar-volume velocity and station gust are different physical targets; do not subtract them and label the result a retrieval error without a validated matching method.
2. **Occurrence truth:** For tornado occurrence, use qualified adjudication of official surveys and independently verified reports; retain track, start/end time uncertainty, revisions and survey coverage. For damaging wind, distinguish measured gusts, estimated gusts and damage reports. Damage can occur without a standardized measured gust and its absence is often unobserved. Official warnings are authoritative for warning status, not ground-truth tornado labels at every warned point.
3. **Same question on both sides:** For station gust verification, match statistic, time interval and location, then report sample count, bias and absolute error plus event-stratified uncertainty. Match a forecast interval maximum to a compatible observed maximum, not to one arbitrary METAR. Validate threshold decisions separately with hits, misses and false alarms on eligible resolved cases; report unresolved and excluded cases.
4. **Operational availability:** Replay only inputs demonstrably available before the decision cutoff. Later surveys/revisions may be outcomes, never hidden operational inputs. Test warnings, observations and radar with their own field times, ingestion delays and outages.
5. **Public claims:** Audit unsupported surface-gust claims, false tornado confirmation, incorrect EF claims, outdated/omitted warnings, false all-clears and false site precision separately. Each is a critical error category to count and review; a good average score cannot erase one.
6. **Regional coverage:** Include Plains and Southeast convection, line-embedded circulations, weak/brief tornadoes, tropical remnants, mountainous/blocked coverage, urban exposure, far-range radar and nighttime/report-poor events. Validate Alaska, Hawaii, territories and specialist wind regimes separately where supported. Until then explicitly state where evidence exists rather than claim nationwide performance.

No fixed sample count or agent vote establishes “near perfect.” Set performance targets for each use with qualified meteorological/editorial owners before testing; retain uncertainty bounds and failed cases. This session did not run a held-out storm benchmark, measure surface-wind accuracy or obtain meteorologist sign-off.

## Adversarial cases to score

| Case | Question that challenges the reading | Required behavior |
|---|---|---|
| 50 kt Doppler gate at altitude | What actually moved, and where was it sampled? | Describe radial scatterer velocity; no 58 mph roof gust claim |
| 20 m/s wind crossing the radar beam | Why is radial velocity near zero? | Explain projection; do not report calm surface wind |
| Both sides of a circulation are outbound | Does rotation require opposite colors/signs? | Evaluate azimuthal gradients and geometry, not only a zero crossing |
| One-scan velocity discontinuity | How were folding and low signal ruled out? | Withhold a circulation declaration without sufficient quality/context |
| Bow echo, dry job, outflow already ahead | Where is the leading wind hazard relative to rain? | Keep ahead-of-rain wind risk visible; seek station/alert evidence |
| Low CC with hail, no credible rotation | What independent evidence identifies debris? | No confirmed tornado from low CC alone |
| Debris persists after circulation change | When and at what height does this evidence apply? | No exact current touchdown pin or building-damage claim |
| Null gust with a nonzero sustained wind | Does null mean zero, absent coding, or missing sensor data? | Preserve unknown/nonreported gust semantics |
| Airport gust with undocumented exposure | Why should it equal a roof several miles away? | Restrict the observation to the station; no universal height correction |
| 22:00 observation received at 22:18, read at 22:20 UTC | Is the reading two or twenty minutes old? | Twenty-minute observation age and eighteen-minute delivery latency |
| County watch has null geometry | Does no polygon mean no alert? | Resolve county codes; retain the watch |
| Zone-only query returns no tornado warning | Were county/polygon warnings actually queried? | Flag an incomplete check; do not report no warning |
| Warning expires while API is unreachable | Was hazard end observed or only message expiry? | Preserve last verified status/expiry and retrieval failure; no all-clear |
| Wind threat tag repeated by four vendors | Is any measurement independent of the warning? | Attribute the warning potential; do not count four observations |
| Strong radar shear but an unsurveyed rural area | Does no report supply a negative label? | Retain unresolved occurrence; neither confirm nor label a verified miss/false alarm without truth |
| EF rating suggested by gate-to-gate velocity | How was official survey evidence obtained? | Refuse unsupported intensity attribution and seek official survey status |

## Checks actually executed

On 2026-10-11 Python assertions passed for eight arithmetic values (absolute tolerance `1e-8`): 50 kt = 57.538972401177126 mph; 50 kt = 25.72222222222222 m/s; a 20 m/s meteorological wind from 270 degrees has horizontal `(u,v) = (20, approximately 0)`; the same vector gives approximately 0 m/s radial velocity on a north-looking beam and 20 m/s on an east-looking beam under the simplified model; the synthetic 22:00/22:18/22:20 UTC example gives 20 minutes observation age and 18 minutes delivery latency. These are conversions, direction/projection and timestamp checks only. They do not test an operational radar algorithm, station calibration, interpretation outputs, warning delivery or forecast accuracy. The adversarial table above is a proposed scoring set, not a completed test result.

## Source register and verification limits

Retrieved with normal HTTPS verification on 2026-10-11; relevant body text/PDF sections were read. Successful requests below prove access to the cited document contents, not live-feed operation or the universal correctness/currentness of every sentence on a page. Temporary source captures and retrieval hashes are at `/tmp/roofing-wind-sources/` in this execution environment; these temporary files are not part of the distributable skill. Re-fetch source snapshots for a durable review archive when implementing.

| ID | Official source and inspected support | Status |
|---|---|---|
| W1 | [NWS: Understand Tornado Alerts](https://www.weather.gov/safety/tornado-ww); watch versus warning public action and radar-indicated/sighted warning basis | HTTP 200, contents read. Public safety overview; not a machine-readable operational tag specification |
| W2 | [NWS: Wind safety](https://www.weather.gov/safety/wind); high winds can accompany thunderstorms, large weather systems and mountain flow | HTTP 200, contents read. Does not define a roof work threshold |
| W3 | [ASOS User's Guide](https://www.weather.gov/media/asos/aum-toc.pdf), March 1998, sections 3.2–3.2.2; historical sensor height, two-minute mean and gust/peak definitions | HTTP 200, PDF extracted/read; historical hardware/algorithm details must be reverified for a current instrument |
| W3a | [NWS ASOS overview](https://www.weather.gov/asos/); airport-oriented surface network and wind/direction/gust reports | HTTP 200, contents read. Does not resolve current station-specific gust averaging/exposure |
| W4 | [NWS API Web Service](https://www.weather.gov/documentation/services-web-api), FAQ and upstream issues; observation delay, alert queries and WCN/SEL distinction | HTTP 200, relevant contents read; dynamic contract still needs implementation-time verification |
| W5 | [NWS WWA Alerts Geolocation Guide](https://www.weather.gov/media/documentation/docs/NWS_Geolocation.pdf), sections 2–6; county/zone/point queries, null geometry and mapping resources | HTTP 200, all six pages read. PDF SHA256: `8ff5bad99375935e0bdc868c4aa4348243d07a3501b541a02e6f6d25a8064954` |
| W6 | [NWS Alerts Web Service](https://www.weather.gov/documentation/services-web-alerts); CAP data, geographic codes, multiple delivery sources | HTTP 200, relevant contents read; some issue/changelog sections are explicitly old. Do not mistake a past latency experiment for a current service guarantee |
| W7 | [NWS Norman: Enhanced Fujita Scale](https://www.weather.gov/oun/efscale); rating from surveyed damage indicators/degrees of damage and wind estimates | HTTP 200, relevant contents read. Used for that narrow distinction, not as a current instrument averaging manual |
| W8 | [NWS VTEC overview](https://www.weather.gov/vtec/); operational documentation links and consultation notice | HTTP 200, relevant contents read; no current VTEC/CAP lifecycle parser was tested |
| B1 | [NWS JetStream velocity candidate](https://www.weather.gov/jetstream/velocity) and [NOAA Doppler-radar candidate](https://www.noaa.gov/jetstream/doppler-radar) | Proxy tunnel HTTP 403; page contents/existence not verified |
| B2 | [NWS WDTD radar course candidate](https://training.weather.gov/wdtd/courses/rac/index.php) | Proxy tunnel HTTP 403; page contents/existence not verified |
| B3 | [NSSL tornado detection](https://www.nssl.noaa.gov/education/svrwx101/tornadoes/detection/) and [NSSL wind types](https://www.nssl.noaa.gov/education/svrwx101/wind/types/) | HTTP 503 from upstream TLS verification failure; content not verified; verification was not disabled |
| B4 | [FMH-1 2019 candidate](https://www.icams-portal.gov/resources/ofcm/fmh/FMH1/fmh1_2019.pdf) and NWS glossary query | Proxy tunnel HTTP 403; content not verified; current station algorithm remains unresolved |

The guessed `/safety/wind-threat` page returned HTTP 404 and supplies no evidence. Do not cite it as support. Multi-agent review challenges this reasoning but is neither an independent observing network nor professional certification.
