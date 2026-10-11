# Tomorrow.io and AccuWeather: live-map integration research

Research date: 2026-10-11. Requested decision: support a user-selected map coordinate in current, forecast and historical modes, while preserving accurate meanings for rain, hail, wind and other hazards.

## What was established in this session

The callable tool catalogue contains no Tomorrow.io or AccuWeather connector tools and no connector-search tool. The user's explicit plugin links identify intended services, but a link does not make an API/tool callable in this session. No plugin weather query was executed.

All attempted official Tomorrow.io and AccuWeather documentation/site requests failed while creating the HTTPS CONNECT tunnel with `403 Forbidden`. That is an access-path failure before the origin page could be read. It does **not** establish that the vendor API is down, that an account lacks an entitlement, that an API key is invalid or that the requested page currently exists. No provider documentation content or API payload was retrieved here. Current capability, plan, coverage, price, licence and accuracy claims therefore remain unverified.

The integration routes below are concrete candidates and contract checks, not statements that these subscriptions currently expose the required endpoints. No credentials were printed, requested in chat or placed in files. No API request, live map, live feed or service deployment was performed as part of this research.

## Feasible routes once actual access is verified

1. **Use a callable chat connector for research, if it becomes available.** Inspect its real schema, supported parameters and response metadata. Exercise one current/forecast/history question at the same public coordinate and retain returned provenance. A connector can support an analyst workflow, but its presence does not establish an application API, an unattended polling service, map-layer rights, full-resolution radar fields or historical archives.
2. **Use the vendor's application API through a backend adapter.** Confirm the exact account/product, authenticated endpoint, location semantics, fields and licence. Normalize each response into the common evidence contract below. Keep credentials in the server's secret mechanism; any browser credential must be explicitly documented as a restricted public token. Do not reuse connector authentication as an assumed application credential.
3. **Acquire a map layer separately when needed.** Point current conditions or point forecasts do not themselves provide a radar basemap, animation tiles, raw radar fields, hail swaths or click-to-value data. Confirm a licensed tile/image/vector/grid interface and its query semantics. Otherwise combine licensed point data with a separately verified radar source, showing both provenances.
4. **Keep official NWS warnings on the independent path required by AGENTS.md.** A vendor point summary must not replace, delay or suppress that path. A provider outage should yield an explicit unavailable/stale layer while preserving other functioning evidence.

Do not choose an accuracy winner from vendor marketing, number of plugins or visual sharpness. Compare matched quantities and decision-time inputs against independent observations using the skill's evaluation protocol.

## Capability questions to resolve by vendor

| Need | Tomorrow.io: documentation/contract to verify | AccuWeather: documentation/contract to verify | Acceptance evidence |
|---|---|---|---|
| Current point conditions | Candidate realtime-weather documentation; verify coordinate syntax, returned location, whether fields represent analyses/estimates/observations, timestamps, quality and update behavior. | Candidate locations and current-conditions documentation; determine whether a coordinate resolves to a location key, named place or observation site and what area/source the conditions represent. Do not assume the returned location equals the clicked point. | An actual authorized payload with location, source/product, observation or valid time, units, quality and fetch time; independently check a representative observation. |
| Forecast point series | Candidate weather-forecast documentation; verify timesteps, lead horizon, issue/run time, field definitions, ensemble/probability semantics, location and plan entitlement. | Resolve the actual hourly/daily/minute forecast products supplied to this account, location/key semantics, lead horizons, interval aggregation and issue times. These endpoint details were not read here. | Authorized sample covering the required intervals; distinguish instantaneous, interval maximum/minimum/mean, amount and probability. |
| Historical point weather | Candidate historical-weather documentation; verify archive reach, allowed dates, cadence, whether data are observations, analysis/reanalysis, reconstructions or forecasts, revisions and query limits. | Identify the actual licensed historical product rather than assuming a recent-conditions lookback is a multi-year archive. Confirm whether it archives observations, estimated conditions, forecasts-as-issued or another dataset. | A past-event payload with coverage, valid interval, revision and provenance; documented availability at the original decision cutoff if used for operational replay. |
| Rain at a point | Verify separate precipitation intensity, accumulation, probability and type fields with their units/intervals; determine whether any estimate incorporates gauges/models/radar. | Verify the corresponding quantities and supporting location/interval definitions in the selected products. | Same quantity/interval compared with QC'd independent gauges; disclose gauge-versus-grid differences. |
| Hail exposure/size | Do not infer an observed hail-size layer from a weather code or precipitation-type enum. Verify a dedicated product, field/algorithm, units, footprint, window and surface-validation evidence if offered. | Same requirement. A mention of hail in narrative conditions or warnings is not a measured hail diameter or a forensic hail footprint. | Product specification and authorized examples, then independent time/location-matched hail evidence; no damage claim from a weather estimate. |
| Wind/gust at a point | Verify sustained-versus-gust semantics, height/exposure, averaging interval, modeled/estimated/measured status and valid time. | Verify the same in the selected location/product; a current-conditions value can have a different support from an hourly forecast gust. | Time-aligned independent observations with their own height/exposure; do not call a grid or nearby station value a rooftop measurement. |
| Radar display and animation | Verify whether the account provides observed radar, forecast precipitation maps or other weather fields; tile protocol/projection, frame time, legend, coverage, retention, animation and attribution rights. | Verify the actual radar/map product and licence separately from point-weather APIs. | Real frames with source/valid/receipt time, legend and missing-coverage behavior; documented license to display/cache them. |
| Numerical values on map click | Verify a raw grid or supported point-query interface for the displayed layer. The point endpoint must match that layer's quantity/time/version to be labeled its clicked value. | Same requirement. A location-based conditions query may be useful beside a layer while measuring something different. | A reproducible map-coordinate-to-source-sample trace, containing cell/footprint or station coordinates and query method. Never estimate an exact number from rendered colors. |
| Nationwide scope | Confirm each product's supported U.S. states, territories, offshore regions and local coverage masks independently. | Same requirement; a global location search does not prove nationwide hail/radar/history availability. | Contract coverage and representative live/test queries in each intended region; missing coverage remains unavailable. |

No row above is marked verified because the necessary docs and authorized responses were unavailable in this session. This is deliberately different from asserting that a vendor cannot supply a feature.

## One map click, three different time modes

The requested latitude/longitude and timezone should remain visible. Preserve the vendor-returned location and spatial support alongside it; never overwrite the latter with the user's pin.

- **Current:** Use evidence with actual observation/analysis/valid time and a product-specific freshness rule. Retain age and quality. "Fetched now" is not "observed now." Distinguish an observation from an analyzed current estimate.
- **Forecast:** Require issue/run time, the requested valid interval, lead time, supported horizon and the exact statistic/quantity. Intervals may already be underway, and archived forecasts retain their forecast class; historical replay must preserve availability at the chosen cutoff. A forecast radar-style image must be labeled forecast. Do not describe it as an observed echo.
- **Past:** Show archived observation/estimate intervals and revisions. Distinguish weather reconstructed later from what a forecaster/provider actually knew at the time. A historical forecast requires its original issue time and availability evidence.

A precise coordinate or a high zoom level does not create parcel-scale accuracy. The panel should say, for example, "estimated for this grid cell," "reported at this nearby station" or "forecast for this location" when that is what the verified metadata establishes. Do not invent resolution or interpolation details if the provider does not expose them.

If a map layer and a point response differ in quantity, interval, version or spatial support, show them as separate evidence. Do not average them into a fictitious single exact reading. For rain, distinguish rate, amount, probability and roof wetness. For hail, distinguish radar estimate, surface report and inspection. For wind, distinguish grid forecast, station measurement, gust statistic and radar radial velocity.

## Common evidence contract for the application

Require these fields where relevant and explicitly mark unknown metadata rather than filling it with guesses:

- Request: requested coordinate, mode, requested valid time/interval, requested quantity and units.
- Provider: vendor, endpoint/tool identifier, product/version, licence reference and upstream lineage when disclosed.
- Spatial support: returned coordinate/location key, station/grid/area type, footprint or resolution, interpolation method and distance from the requested point where applicable.
- Timing: observation time, issue/model run, valid start/end, fetch time, revision, expiry/freshness rule and original availability evidence for historical replay.
- Value: quantity definition, statistic, units, measured/reported/estimated/forecast classification, source quality, missing flags and uncertainty when supplied with a documented meaning.
- Display: layer/frame identifier, legend, observed/forecast/history label, attribution, missing-coverage state and permitted evidence links.

The adapter must preserve raw provenance or a permitted audit representation. Units, location/time matching, interval arithmetic, filtering and freshness should be deterministic code. Generated prose should cite those structured records and abstain from claims they cannot support.

## Credentials, account and rights checks

Before asking the user for any secret, inspect the available configuration and only the names/presence of injected variables. If a callable connector appears, test its supplied authentication first. An API credential and plan may be required for a backend route, but the exact authentication method and account entitlements must come from the current vendor contract; they were not verified here.

Confirm supported queries, quotas/rate limits, concurrency, intended update/polling behavior and handling of throttling before sizing the service. Do not quote prices, quotas or retained-history durations from memory. Confirm terms for commercial display, caching, archiving, derived summaries, exports, redistribution, screenshots and attribution. Possession of a plugin subscription is not proof that all these rights extend to the roofing application's users.

Treat a failed request by layer: connector availability, network path, authentication, account entitlement, malformed request, rate limit, origin failure or unsupported coverage. The failures in this session were network CONNECT failures. They do not justify requesting a new API key or purchasing an upgraded plan.

## Actual source-attempt register

All attempts used HTTPS with normal TLS verification on 2026-10-11. Every entry below produced `Tunnel connection failed: 403 Forbidden`; **zero page contents were read**. The listed paths are candidate documentation/discovery references, not freshly verified citations for feature claims. No API endpoints were exercised.

| Candidate URL requested | Intended evidence | Actual result |
|---|---|---|
| https://docs.tomorrow.io/reference/welcome | Developer entry point | CONNECT 403; unread |
| https://docs.tomorrow.io/reference/realtime-weather | Realtime point product definition | CONNECT 403; unread |
| https://docs.tomorrow.io/reference/weather-forecast | Forecast product definition | CONNECT 403; unread |
| https://docs.tomorrow.io/reference/historical-weather | Historical product definition | CONNECT 403; unread |
| https://www.tomorrow.io/weather-api/ | Official API overview | CONNECT 403; unread |
| https://www.tomorrow.io/weather-api/weather-maps/ | Candidate map-product discovery route | CONNECT 403; unread; path existence unverified |
| https://www.tomorrow.io/legal/terms-of-service/ | Candidate service terms | CONNECT 403; unread; no rights determination |
| https://developer.accuweather.com/ | Developer entry point | CONNECT 403; unread |
| https://developer.accuweather.com/apis | Candidate endpoint catalogue | CONNECT 403; unread |
| https://developer.accuweather.com/accuweather-current-conditions-api/apis | Candidate current-conditions catalogue | CONNECT 403; unread |
| https://developer.accuweather.com/accuweather-locations-api/apis | Candidate location-query catalogue | CONNECT 403; unread |
| https://www.accuweather.com/en/enterprise-solutions | Candidate official enterprise overview | CONNECT 403; unread |
| https://corporate.accuweather.com/for-business/ | Candidate official commercial overview | CONNECT 403; unread |

Needed research access: `docs.tomorrow.io` and `developer.accuweather.com`; additional official terms/product domains as linked from verified documentation. Do not replace an unknown network allowlist wholesale. Actual API hosts and any CDN/map-tile hosts should be taken from verified documentation before adding them. Restored documentation access would still not establish account entitlement, live-data quality or application redistribution rights.

## Minimum evidence before calling a map live and accurate

Run authenticated representative queries for each enabled mode/product, validate field meanings and source clocks, and render at least one real timestamped frame if radar is offered. Check blank/stale/missing layers, unsupported regions, units, day/timezone boundaries, overlapping accumulation intervals, revisions, throttling and recovery. Compare real rain/wind/hail cases with independent measurements at matching times/scales and report per-hazard errors, misses, false alarms and coverage. Retain an unavailable state when the evidence is absent. A visually working map or successful HTTP request is functionality evidence, not a claim of meteorological accuracy or news-readiness.
