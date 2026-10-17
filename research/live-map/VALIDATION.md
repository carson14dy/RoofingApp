# Validation record — October 11, 2026

## Executed successfully

Real NWS requests for downtown Kansas City (39.0997, -94.5786) returned point metadata, hourly forecasts, station observations and official point alerts. The final recorded query at **12:06 p.m. CDT** returned 156 hourly periods and three stations:

| Station | Distance from sample pin | Observation time in that response |
|---|---:|---|
| KMKC, Kansas City Downtown Airport | 2.916 km | 11:45 a.m. CDT |
| KLXT, Lee's Summit Regional Airport | 24.532 km | 11:45 a.m. CDT |
| KMCI, Kansas City International Airport | 27.358 km | 11:45 a.m. CDT |

The hourly forecast's source update time was 6:01 a.m. CDT, distinct from response generation/retrieval. The alert request returned an empty active-alert collection for that coordinate at its fetch time. These are dated integration observations, not today's continuing weather statement or an accuracy score. Missing wind, gust or precipitation fields remained missing.

The earlier 39.7456, -97.0892 sample was a generic Kansas route test, not Kansas City validation.

- **18 backend tests passed** against synthetic controlled responses, including exact-point history isolation, source outages, independent alert behavior, timestamp/quality errors, native units/missing values, URL restrictions and static-file confinement.
- **Seven Chromium checks passed**, with zero JavaScript errors: real Kansas City map/observation/forecast display; mobile layout; station-QC gating without blocking quantitative forecasts; browser outage with last-known warning retention; no cross-point warning carryover; reverse-order click responses; correct point-specific archive start.
- Source timestamps, history persistence and the final 30-minute prototype observation age policy were checked through the running service.

The browser failure/race/QC cases use explicitly synthetic payloads. None is a real severe-weather event test. State outlines, source markers and forecast panel were viewed in the captured screenshot. Optional street tiles were not validated; their server-side access check returned CONNECT 403.

## Independent review findings resolved

The reviewer identified missing map-asset routing, hidden refresh failures, lost last-known warnings, ignored QC flags, global-versus-point history timestamps, a stuck forecast loading state, stale timezone use, inappropriate station-QC gating of forecasts and browser-level alert retention. These were corrected; targeted browser tests cover the highest-impact display/failure cases. The code preserves raw source values where a prototype QC rule withholds them from normal display.

## Remaining blockers and limitations

All four named commercial plugins remain absent from the callable tool catalog. Candidate provider-document requests returned CONNECT 403; no provider API response, subscription, accuracy ranking or commercial display/storage right was verified. Secure app API credentials were not present under the inspected relevant names; this does not determine the user's plugin account status.

No live radar/hail/lightning layer, earlier historical weather archive, unattended collector, full warning-geometry engine, rooftop sensor network or production deployment exists. The local archive preserves queried snapshots only. This prototype is single-user development software with no public-service authentication or production capacity guarantee.

No independent meteorological benchmark has run. A 2.916 km-away station and a forecast grid do not measure exact conditions at a roof. The next accuracy phase is a preregistered Kansas City field comparison using independent observations and held-out events, separate scoring by variable/lead/terrain, and explicit missingness, false alarms and uncertainty.

## Configuration and evidence

Before publishing the GitHub branch, the 18 backend tests and 35 skill-contract tests passed again. After replacing workspace-specific defaults, all seven browser checks passed against a newly started service on port 8766, using the bundled fixture, a configurable Chromium path and ignored local output. The archive's default is now `prototype/.local/state`; `--archive-dir` preserves support for the original cloud setup's explicit path. No weather algorithms changed during packaging.

Real response captures, screenshot and browser results are retained in `/workspace/live-map-evidence`; the shareable handoff includes selected dated evidence and hashes. Records contain public sample coordinates, not customer addresses. The local SQLite history is in `/workspace/live-map-state` and is not bundled as a historical-weather product.

The environment draft preserves existing settings and adds provider-document, basemap-policy/tile and MADIS-document domains. Saving that draft is not proof they were applied. Review/save in environment settings, then publish, to activate the prepared configuration/snapshot. Provider tools still need to be exposed to this session or documented app API access supplied securely before those integrations can be tested.
