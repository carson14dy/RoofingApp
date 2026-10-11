# WindBorne and ZoomRadar: live-map integration research

Prepared 2026-10-11 for Claude's RoofingApp implementation. This document reports a provider-access investigation and a concrete integration contract. It does not claim that either provider's API, plugin, data quality, commercial rights or map embedding has been verified.

## What was actually checked

The user names **Weather by WindBorne** and **Zoom Radar Weather** as installed plugins and explicitly requests using them. The callable tool catalog in this agent's session contains neither provider and no connector-search tool. No tool was used to query either provider, no plugin authorization was tested and no account credentials were inspected. The provider names alone do not identify an API product or grant a RoofingApp distribution license.

Normal HTTPS requests with certificate verification enabled were attempted on 2026-10-11. All six returned `Tunnel connection failed: 403 Forbidden` from the environment's proxy before any provider page was received:

| Candidate public website | Result | Evidence that remains absent |
|---|---|---|
| https://windbornesystems.com/ | Proxy tunnel 403 | Provider identity, current public product documentation and links |
| https://www.windbornesystems.com/ | Proxy tunnel 403 | Same |
| https://windborne.ai/ | Proxy tunnel 403 | Whether this domain belongs to the named plugin/provider or hosts relevant documentation |
| https://www.windborne.ai/ | Proxy tunnel 403 | Same |
| https://zoomradar.com/ | Proxy tunnel 403 | Provider identity, current public product documentation and links |
| https://www.zoomradar.com/ | Proxy tunnel 403 | Same |

These are candidate source locations, **not source-content citations**. Blocked access does not establish that a website is absent, that a subscription is missing or that an API key is required. No alternative domain was used to evade the restriction. Initial request results are retained temporarily at `/tmp/roofing-live-map-sources/retrieval-home.json`; the www attempts were also returned in this task's tool output.

**Verified provider documentation: none. Provider marketing claims examined: none. Provider API endpoints verified: none.** Do not populate missing details from memory or copy credentials/endpoints out of plugin internals. The integration recommendations below are engineering proposals, not vendor promises.

## Provider capability decisions awaiting evidence

Evaluate the two providers separately. Every “unknown” below is a required documentation or response check, not an assertion that the feature is unavailable.

| Capability | Weather by WindBorne | Zoom Radar Weather | Evidence required before implementation |
|---|---|---|---|
| Supported ChatGPT/plugin queries | Unknown; no callable tool | Unknown; no callable tool | Actual callable schema and an authorized successful response |
| Server API usable outside the plugin | Unknown | Unknown | Official developer contract, authentication method and app entitlement |
| Current point weather | Unknown | Unknown | Documented response and sample showing observation/analysis type, time, units, support and QC |
| Point forecast | Unknown | Unknown | Run/issue time, valid interval, grid/height, statistic, probability meaning and horizon |
| Historical point weather | Unknown | Unknown | Archive start/end, revision policy, observation versus reconstruction, source and spatial support |
| Radar tiles or frames | Unknown | Unknown | Official tile/frame contract, observation times, source, product, coverage, quality/missing masks and license |
| Interactive map or iframe embed | Unknown | Unknown | Official supported embed and configuration contract; permitted hosting/branding/click events |
| Quantitative hail/rain/wind data | Unknown | Unknown | Actual documented variables and semantics; imagery alone is insufficient |
| Resolution, refresh and latency | Unknown | Unknown | Per-product sampling/grid resolution and measured delivery behavior, kept separate from pixel size and polling |
| App use, retention and redistribution rights | Unknown | Unknown | Applicable written terms/plan for customers, map display, caching, historical retention, derived summaries and export |

Do not assume the two services are independent. Record upstream radar/model/station lineage. A forecast vendor and radar-display vendor may be complementary; agreement does not automatically validate a surface condition, and repeated NWS/MRMS/ASOS evidence is not multiple independent observations.

## Concrete route for Claude

1. **Obtain the official integration contract through the provider's exposed capability or public documentation.** Once a plugin becomes callable, use it for authorized sample queries and provenance discovery within its documented scope. Do not treat chat-only access as permission to repurpose a hidden endpoint in RoofingApp. If public documentation identifies an external developer API or supported embed, implement that contract and verify app entitlements. A missing plugin does not prevent preparing the app's provider interface.
2. **Choose the integration form from actual capabilities.** A supported iframe/embed can supply a licensed viewing experience but may not expose click-to-query data, playback metadata or app overlays. Confirm those features before selecting it. A documented tile/frame API can be integrated with the app's map if rights and token/CORS rules permit. A point API belongs behind the app's backend with provider credentials protected. If the service supports only chat queries, use those for research and keep production data integration unimplemented until an approved route exists.
3. **Build separate display and quantitative-data adapters.** A map layer returns imagery with frame metadata; a point adapter returns evidence records. Never turn screen colors into an exact hail diameter, rainfall amount or surface wind. Do not assume the visible layer is the source of a neighboring forecast value. Keep the official NWS warning adapter independent of provider forecasts, map availability and AI explanations.
4. **Bind every request/result to the clicked point and requested time mode.** Carry a request ID and the original latitude/longitude. A late result for the previous click must not overwrite the newer selection. Validate longitude/latitude order, bounds, coordinate reference, timezone and any provider-side rounding. Preserve actual source support even when the input permits many decimal places.
5. **Return explicit evidence state.** Use available/current, stale, missing, unsupported, authentication-failed and provider-error states as distinct app states. A successful empty response is not automatically a measured zero. A radar tile with no precipitation is not proof of no wind, lightning or other hazard. Do not silently substitute demo weather when live provider data fail.
6. **Verify useful behavior with authorized samples before choosing either provider.** Compare exactly the same point, product meaning, time interval and decision cutoff. Retain response metadata and permitted snapshots. Measure coverage, timestamp integrity, time to usable data, outage behavior and value semantics before attempting a weather-accuracy benchmark.

### App-internal contract, not a provider endpoint

The following field set is proposed for Claude's own adapter. It makes no assertion that either vendor uses these names or supports every field:

```text
request_id; selected_latitude; selected_longitude
mode: current | forecast | history
requested_time_or_interval_utc
provider; product; product_version; upstream_sources; evidence_id
evidence_type: measured | reported | radar_estimate | model_analysis | forecast
variable; value_or_range; units; statistic; averaging_interval; search_interval
observation_or_valid_interval_utc; issued_utc; fetched_utc; revision
spatial_support: station | report_location | radar_gate | grid_cell | polygon
source_geometry_or_location; horizontal_resolution; location_uncertainty
measurement_height_agl_or_model_level; quality_flags; missing_reason
data_age; documented_freshness_rule; coverage_status
source_attribution; permitted_source_reference
```

Do not fabricate unavailable metadata. A field can be unknown while a narrower claim remains useful. Store point distance from a station and source geometry separately from the selected point. Keep capabilities explicit per provider/product so the UI can show that, for example, historical hail is unsupported even if forecast rain is available.

## Exact map click: what a useful response must show

| User mode | Required output at the selected point | False precision to prevent |
|---|---|---|
| Current | Closest **suitable** station/report or supported analysis with location, distance, actual observation time, age and statistic; sampled radar with its height/quality when relevant; independent current warning status | Relabeling airport wind or a modeled grid value as a measurement at the clicked roof |
| Forecast | Forecast product/run, valid period, spatial footprint, variable/statistic and uncertainty semantics; retain source timezone conversions | Treating accepted coordinate decimals as forecast resolution; converting a model gust into an observed gust |
| History | Evidence available for the requested historical interval with original location/time uncertainty and revision status; distinguish measured reports, radar estimates and later reconstructions | Using a current forecast endpoint for past weather; treating reanalysis as a contemporaneous observation; inventing a precise property footprint from a nearby report |

If WindBorne provides balloon or other upper-air observations in the selected product, retain the measurement level and horizontal position/time; they would not be surface weather at a roof. This is a conditional integration check, not a verified claim that the user's plugin supplies such data.

For any ZoomRadar animation or map product that becomes available, check whether frames are observed radar, a composite, extrapolation/nowcast, forecast precipitation or a mixture. Preserve frame-specific timestamps, legend/product, coverage and quality. Do not assume “live” in branding guarantees a current local tile, fixed cadence or direct quantitative access.

For hail, a provider estimate needs the actual algorithm/product, accumulation window, grid and version. For rain, keep instantaneous rate, interval accumulation and probability separate. For wind, keep mean, gust and peak/search window separate and retain sensor/model height. For other hazards, query a documented appropriate source rather than derive the hazard from unrelated radar colors.

## Licensing and technical questions that determine the route

Resolve these from official terms/entitlements, not from account secrets or a marketing screenshot:

- Does the subscription permit a public or customer-facing commercial RoofingApp, multiple end users and server-to-server calls? Is plugin access separate from an API plan?
- May imagery be embedded, overlaid with jobs and warnings, cached, replayed, exported or included in reports? What attribution and branding are required?
- May quantitative records be stored for historical replay and used in derived exposure summaries? Do permitted retention periods cover the planned history view?
- For map tiles, are browser tokens explicitly intended to be public, domain-restricted and scoped? Keep secret API keys server-side and follow the provider's published mechanism; do not assume an exposed URL authorizes redistribution.
- What are actual request limits, coverage areas, archival availability and product-change notices? Are Alaska, Hawaii and U.S. territories supported for each selected layer and variable?

## Minimum acceptance exercise before live use

This is a proposed test plan; **none of these provider tests has run**.

1. Retrieve one documented sample for each supported current/forecast/history capability at identical coordinates, then repeat in a documented coverage boundary/missing-data location. Retain actual units, evidence type, geometry, timestamps, quality and attribution.
2. Select a different nearby coordinate that maps to the same forecast grid cell and confirm the UI accurately displays identical underlying support. Select a remote station area and verify that current station distance/age remain visible instead of becoming a parcel observation.
3. Play radar frames across a real observation/forecast boundary if the product provides one; require explicit mode/time transitions. Simulate a stale local tile under a current layer header and verify the freshness behavior.
4. Test current/history requests near midnight and daylight-saving changes using absolute UTC intervals and location timezone. A rounded report time or location remains uncertain after conversion.
5. Test key absence, rate limiting, timeout, missing/null values, partial fields, stale data, provider outage and out-of-order click responses. Keep the independent NWS warning display functioning.
6. For accuracy, use the skill's frozen, event-held-out benchmark with independent surface truth and honest unresolved outcomes. Comparing these two vendors against shared upstream data only measures agreement. Weather skill, broadcast readiness and nationwide performance remain unestablished until the relevant tests run.

## Handoff status

Claude can implement the internal evidence/map contracts and failure states now. Connecting either vendor requires a callable authorized capability or verified official developer/embed documentation, applicable app rights and successful response samples. No unverified endpoint, guessed tile URL, fabricated subscription, downloaded provider dataset or production integration is supplied by this research.
