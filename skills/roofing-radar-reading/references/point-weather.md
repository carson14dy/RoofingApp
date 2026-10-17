# Weather at a selected map point

Design contract, version 0.3.0, 2026-10-11. This specifies what Claude's future implementation must return and test. No live point service or property-level accuracy benchmark was implemented by writing this document.

## The promise and its limits

Every click identifies a specific coordinate and requests available current evidence, forecasts, and requested historical evidence for that coordinate. Show the coordinate and let the user correct the pin. The selected coordinate can be precise even when the weather source represents a larger area, a nearby instrument, an observation aloft, or an uncertain event location. Preserve those differences throughout the query, display, history and export.

Do not label an interpolated value, a neighboring station report, an image pixel, or a forecast grid cell as an exact measurement at a roof. A finer map zoom or additional decimal places does not improve the weather source's spatial accuracy. Many different roof locations legitimately share the same source grid cell. A point query returning a number for every location is a coverage property, not proof of accuracy.

The useful target is: **correct coordinate, correct source footprint, correct time, correct evidence label, measured error where independent observations exist, and an explicit gap where they do not.**

## Questions every point result must answer

| Question | Required answer | Challenge before display |
| --- | --- | --- |
| What? | Variable, units, evidence type, statistic/threshold, source and product version. | Is this measured rain, radar-estimated rain, modeled rain, or a forecast probability? |
| Where? | Selected coordinate; actual sample geometry, elevation/height when relevant, effective resolution and distance to nearby observations. | Does the source support a point statement, an area statement, or only nearby context? |
| When? | Observation/valid interval, issue time, receipt time, revision and age; selected location's timezone for display. | Was it available at the requested decision time, and is it fresh at this specific point? |
| How? | Lookup, spatial match, resampling/interpolation, unit conversion and quality handling. | Did the method create unsupported detail, mix grids, or turn missing into zero? |
| Why? | Connection between source evidence and the stated conclusion, including competing evidence. | Why does a radar signature support possible hail rather than proof that hail struck this roof? |

## Coordinate and location contract

1. Store named `latitude_deg` and `longitude_deg` fields in WGS 84 geographic coordinates. Require finite numbers with latitude in [-90, 90] and longitude in [-180, 180]. Preserve the submitted coordinate and any normalized coordinate. Reject latitude/longitude swaps that can be detected; do not silently repair an ambiguous pair. A service accepting both swapped numbers does not prove the order was correct.
2. For GeoJSON, serialize coordinates as `[longitude, latitude]`. NWS URL examples use `/points/{latitude},{longitude}` and `?point=latitude,longitude`; use named adapter arguments to prevent order confusion. Project Web Mercator screen/map coordinates to geographic coordinates before querying. Never pass map pixel coordinates or projected meters as latitude/longitude.
3. Retain enough decimal precision to locate the clicked pin consistently; do not equate decimal precision with geolocation accuracy. Record GPS accuracy radius when supplied, and distinguish a manual click from a measured position. If an adapter quantizes coordinates, preserve the original point, submitted point and distance between them. Quantization must not silently change hazard inclusion or assign a neighboring forecast cell.
4. Keep clicked coordinates authoritative over reverse-geocoded names, postal codes or addresses. Show a nearest place name as a label; do not move the query to that place's centroid. An address may resolve to a street/parcel centroid, not the user's roof or GPS position.
5. Keep ground/site elevation, source terrain elevation and measurement height separate, with units and vertical datum when available. Do not silently apply a lapse-rate correction, convert 10 m model wind into roof wind, or infer rooftop gusts from an airport observation. Those would require separately validated methods and site inputs.
6. Maintain a versioned geographic coverage catalog per source, product and variable. Test Alaska, Hawaii, Puerto Rico, other claimed territories, coastal water and border areas explicitly. A source described as U.S. or CONUS cannot automatically support the entire claimed map. Other countries and unsupported ocean points must receive an honest availability result.
7. Use geodesic distance or an appropriate documented projection for distances and buffers. Handle longitude wrap and antimeridian-crossing geometries. A plain longitude bounding box can incorrectly cover almost the whole globe. Test polar/high-latitude behavior and the map projection's latitude limits.

## Three views from one point query

### Current

Return the latest available evidence relevant to the selected coordinate and requested current time. Distinguish:

- **Observed at site:** an instrument or verified report tied to this site, retaining its siting/time/quality limits.
- **Observed nearby:** a named station or report with actual coordinates, distance, elevation difference when known, timestamp and representativeness caveat. Choose by a documented quality/representativeness policy; the nearest station alone is not always suitable. No universal distance threshold makes a station representative of every hazard.
- **Estimated over this area:** radar, satellite or analysis grid covering the point, with the cell/footprint and method retained.
- **Forecast/nowcast valid now:** a forecast whose valid interval contains the requested time. Keep it visibly labeled as forecast, including when it fills an observation gap.

Do not construct a single unlabeled “current conditions” tuple from measurements and forecasts with different timestamps. If a summary combines them, each variable retains its own label, age and evidence link. “Fetched just now” must never replace “observed 25 minutes ago.” A latest record may already be stale. NWS describes observation QC/ingest delays of approximately 20 minutes [S1]; actual delay can vary, and this is not a guaranteed bound or a suitable freshness threshold for every use.

### Future

Return forecasts by their actual valid intervals and lead times. Preserve model/provider, issue/run time, grid footprint, terrain height where available, forecast horizon and ensemble/quantile/probability definitions. Display forecast intervals without presenting them as continuously measured conditions. Do not manufacture minute-level changes by resampling an hourly source.

Precipitation probability must identify the precipitation threshold and valid period. The cited NWS example describes PoP as the probability that the forecast grid/point receives at least 0.01 inch of rain [S3]. For snow or mixed precipitation, verify the selected product’s measurable-precipitation/liquid-equivalent definition; this is not 0.01 inch of snow depth. It is not the fraction of that period that will be rainy, nor a parcel hail probability. Precipitation amount, intensity, type, probability and accumulation interval are separate fields.

An ensemble spread is not automatically a calibrated confidence interval. Quantile bands require their stated variable/period and documented interpretation. Deterministic forecasts and hazard outlooks must not acquire invented point probabilities. SPC neighborhood/outlook probabilities retain their defined area and period even when queried at a pin.

### Past

Offer two explicitly different historical modes:

- **Best available retrospective evidence:** current version of archived observations, radar estimates, reports and any separately labeled reanalysis, including late reports and corrections. Record revision and retrieval date. “Historical” does not mean every field is measured or final.
- **What was knowable then:** inputs issued/published/received by a specified decision cutoff, including the forecasts and warnings available then. A valid time earlier than the cutoff does not establish that the data was available then. If availability cannot be reconstructed, this mode is unsupported for that source and period.

Store valid time and knowledge/availability time separately. Preserve report revisions and deduplicate event updates without discarding their change history. A corrected hail report can change the best retrospective summary without rewriting what users saw earlier. Never turn a modern reanalysis or corrected archive into a past real-time observation.

Specify history coverage separately for each product and variable: earliest available date, gaps, retention, licensing and revision policy. NWS `/alerts` provides approximately seven days of alert history; longer warning history needs an archive [S1, S2]. Its forecast endpoints are not a historical forecast archive. A commercial provider's history endpoint must be checked for whether it serves observations, model estimates, reanalysis or archived forecasts.

Historical rain totals require matching accumulation windows, timezone/date boundaries and sufficient coverage. Do not sum overlapping running accumulations; do not combine a rolling 60-minute accumulation with adjacent hourly totals without interval accounting. Missing intervals stay missing or explicitly partial. Do not sum hail swath maxima or treat every repeated report as another event.

## Evidence and response fields

This is a proposed adapter-neutral schema, not an implemented API. A response must retain the request rather than silently replacing it with source coordinates.

```text
request:
  request_id, latitude_deg, longitude_deg, crs, location_origin
  location_accuracy_radius_m?                         # only if known
  view: current | forecast | historical
  requested_interval_utc, decision_cutoff_utc?        # required for knowable-then
  historical_mode?, hazards_requested[], units_requested
  requested_at_utc

response:
  request_id, selected_point, submitted_point_by_adapter[]
  location_timezone_iana, timezone_database_version
  response_generated_at_utc, snapshot_id, partial, missing_sources[]
  evidence[], official_alerts[], limitations[]

evidence:
  evidence_id, provider, upstream_lineage[], product, product_version
  source_record_id, revision, source_url, rights_and_attribution
  variable, evidence_kind, value?, unit, statistic, threshold?
  value_status: available | missing | not_applicable
  source_state: available | unavailable | not_configured | unsupported
  coverage_state: covered | partial | outside_coverage | unknown
  freshness_state: fresh | stale | unknown | not_applicable
  quality_flags[], exclusion_reason?, conflict_evidence_ids[]
  observed_interval_utc?, valid_interval_utc, issued_at_utc?
  source_published_at_utc?, first_received_at_utc?, fetched_at_utc
  available_by_cutoff: yes | no | unknown | not_applicable
  expires_at_utc?, freshness_policy_id
  support_geometry, support_crs, source_cell_or_station_id?
  sample_latitude_deg?, sample_longitude_deg?, distance_to_point_m?
  grid_spacing_m?, effective_resolution_description?, location_uncertainty?
  terrain_elevation_m?, measurement_height_m?, vertical_datum?
  radar_site?, beam_height_m?, height_reference?, elevation_angle_deg?
  spatial_method, temporal_method, transformations[], interpolation_policy_id?
  applicability: at_site | area_covering_point | nearby_context | unresolved
  uncertainty_description, validated_error_reference?
```

Use nullable values and explicit enums; zero remains a valid physical value only when supported by the source. A request can have fresh rain evidence, stale wind evidence and unsupported hail evidence simultaneously. Never compress those states into one green status. Unknown confidence must not be converted to 0% probability. Store raw source fields or permitted references so transformations can be audited.

For a retrospective historical value, `freshness_state` is generally `not_applicable`; assess event-time coverage, QC and archive revision instead. Keep archive service health separate. For historical forecasts, preserve lead time relative to original issuance, not retrieval date. When averaging, sampling or accumulation duration is undocumented, retain an unknown interval; a timestamp does not prove an instantaneous measurement. Do not use it as an interval maximum or total.

## Deterministic resolution route

1. Validate the coordinate and UTC request interval. Resolve location timezone and geographic coverage. Begin the official-alert path independently of radar, commercial providers and AI.
2. Discover source support for each requested variable, geography and time. A missing provider credential or unlicensed archive is a configuration gap, not no weather. Return gaps per source/variable while processing supported sources.
3. For NWS forecasts, request `/points/{latitude},{longitude}` and use its returned forecast links, office, grid identifiers, station links and zone information. Recheck this mapping periodically and on relevant failures or change notices; NWS says office/grid mappings can change. Its gridded forecasts are approximately 2.5 km by 2.5 km [S1], not measurements at the click. Follow the API links rather than constructing enduring assumptions from a previous office/grid mapping. Coastal marine forecasts are documented as available through `forecastGridData`; do not assume the land text/hourly paths work offshore [S1].
4. Resolve source cells using the source CRS, grid origin, cell bounds, pixel orientation and documented value support. Distinguish cell mean, cell maximum, grid-node value and nearest sample. Preserve no-data masks. Default to the source-native representation; interpolation requires a variable-specific supported method, flags and tests. Never bilinearly interpolate warning categories, categorical weather type, event occurrence, or hail maxima into fictitious values.
5. For radar, retain local sample time, quality/coverage, source radar/mosaic lineage, gate/cell footprint, range and sample height if available. A mosaic's newest timestamp cannot make every component or pixel fresh. Radar gates widen with range; displayed pixel size is not the effective physical resolution. If beam height cannot be derived from reliable scan/site metadata, mark it unknown. Radar evidence often samples weather aloft and cannot establish exact surface hail size or wind at the selected roof.
6. Retrieve station/report context with a documented spatial/time search policy and quality filters. Keep original report uncertainty; never snap a town-level storm report to a parcel. Surface observations can differ legitimately across a sea breeze, outflow boundary, elevation change or storm track. Preserve disagreement and explain its possible causes rather than automatically averaging it away.
7. Align variable-specific valid intervals and verify units, availability cutoff, quality and source version. A forecast interval overlapping the request does not establish an observation during that interval. Handle partial interval coverage explicitly; do not assume precipitation uniform within an interval to invent subperiod totals.
8. Generate a bounded summary from structured evidence. The AI may explain differences; deterministic code selects sources, computes spatial matches, converts units and enforces temporal support. Every number and location statement must trace to evidence. If summaries fail grounding checks, display a deterministic evidence summary.

## Official alerts at a point

Use NWS point queries and/or appropriately broad ingestion followed by verified local matching; do not rely solely on the forecast zone returned from a forecast lookup. NWS's Geolocation Guide confirms that point queries resolve county and zone codes, county queries also return intersecting zone alerts, and public-zone-only queries omit county-based watches and polygon warnings [S2]. A county response therefore may be broader than the actual location.

Retain official polygons, county/zone identifiers, geometry version, status, issue/effective/onset/expiry/end fields and update/cancel relationships. Preserve multiple overlapping alerts. For polygon products use the official polygon for point applicability while retaining county context separately. For null geometry, resolve the appropriate county/public/fire/marine zone geometry from maintained official boundaries. Null geometry is not an empty affected area. If geometry cannot be resolved, show “location applicability unresolved” with the official area text; do not claim “no alerts.”

Specify and test polygon boundary semantics, multipolygons and holes. Use a boundary-inclusive point match for the application's official outer boundary policy; test the geometry library's handling of hole boundaries and numerical precision. Record that this is deterministic location matching, not a claim about a sharp physical edge to the hazard. If known GPS/geocoding uncertainty spans an alert boundary, mark actual-location applicability uncertain even when the nominal coordinate has a deterministic match. Keep nearby alerts visibly distinct from alerts covering the point. A configured nearby buffer must not expand an official polygon or become an observed footprint.

Track official alert lifecycle independently of cached graphics and AI summaries. On a retrieval outage, distinguish “last known warning; current status unavailable” from “fresh query returned no active alerts.” Do not represent an expired last-known warning as confirmed currently active, or its expiration as proof of safety. Poll according to source guidance and rate limits; NWS recommends alert requests no more often than every 30 seconds [S4]. Product issuance cadence, our polling interval and end-to-end latency remain separate measures.

## Hazard-specific claims and gaps

| Hazard/variable | What a point query may support | What still requires separate evidence |
| --- | --- | --- |
| Rain | Gauge accumulation at a site; area radar/gauge/model precipitation estimate; forecast amount/rate/probability for its period. | Exact roof wetness, drainage/ponding, uniform intensity inside an accumulation interval. |
| Hail | Nearby observed hail report with location/time uncertainty; radar-derived estimated hail in an area; official warning; correctly defined outlook/nowcast probability. | Exact stone size at a roof, precise fall swath edge, impact count or damage without suitable surface evidence. |
| Wind | Site/nearby wind measurement with height, averaging period and gust definition; forecast grid wind/gust; radar radial velocity aloft. | A roof-level gust or full surface wind vector inferred from a radial velocity pixel. |
| Tornado | Official warning status and source-grounded radar interpretation; verified reports with time/location uncertainty. | Exact tornado position/path width from a couplet alone, absence from a blank radar view, damage at an uninspected building. |
| Lightning | Licensed or official detection/forecast evidence with network coverage, time and uncertainty. | A radar-only strike location or guaranteed lightning-free site. |
| Snow, sleet, freezing rain, ice | Supported observations, precipitation-type estimates and forecasts, with temperature-profile/terrain limits. | Roof ice load, substrate temperature or exact accumulation without appropriate measurements. |
| Flooding and coastal hazards | Official alerts; supported gauges/models and mapped forecast scenarios. | Parcel inundation, roof/access safety, or flood depth from a rain pixel or county alert alone. |
| Heat/cold/humidity | Measurement or model estimate with site/height/period; derived index only within its documented validity. | Roof/substrate temperature, worker physiological response or a guaranteed safe work interval. |
| Fog, visibility, smoke/dust, air quality | Dedicated station/satellite/model/alert products with variable-specific support. | Visibility or pollutant concentration at the roof from reflectivity alone. |
| Tropical, fire-weather and other hazards | Hazard-specific official products and supported evidence while preserving forecast-cone, wind-probability, warning and outlook semantics. | “All weather covered” based on a radar provider's presence. |

Each row is a routing requirement, not a claim that all feeds are connected. Unsupported hazards receive `unsupported` or `not_configured` for the relevant source with a useful explanation. Roof condition and job suitability require their own site observations and material/work rules.

## Time, boundaries, caching and display

- Store all event/valid/issue/receipt/cutoff times as unambiguous UTC instants. Display in the selected point's IANA timezone, which may differ from the user's device timezone. A Chicago user clicking Arizona or Alaska should see the point's local time and UTC on detailed evidence.
- A date-only historical request needs a location timezone and a documented local-day interpretation. Convert local midnight bounds to UTC using the timezone database; daylight-saving transitions produce 23- or 25-hour local days. Require offset/fold disambiguation for repeated wall-clock times. Never invent nonexistent spring-forward times. Use consistent half-open accumulation/query intervals where appropriate, preserving official product time semantics.
- Source data caches may be shared by actual source cell/station/product/run/revision. Point applicability must still be calculated for the actual requested coordinate. Do not reuse a previous point's warning results, station distances or map label merely because both points share a weather grid cell.
- Include provider/product/version, source cell or station, model/run/revision, requested interval, field/statistic, unit conversion, sampling method, coordinate normalization and historical availability mode/cutoff in the appropriate cache keys. A returned point summary additionally needs the exact submitted request context and alert snapshot. Keep raw and derived caches separate so changing units or interpolation cannot reuse the wrong answer.
- Honor HTTP cache headers, conditional requests, rate limits and source TTLs. Revalidation/HTTP 304 updates transport knowledge; it does not reset observation age. Invalidate/recompute affected derived results when mappings, boundaries, source revisions, methods or official-alert lifecycle change. Stale fallback values remain labeled stale.
- Associate each client result with `request_id` and coordinate. If clicks A then B return in reverse order, A must not overwrite B. Late provider replies may update only their matching snapshot/point. A tile still loading must not show the previous tile's values as the new point's weather.
- Show per-variable evidence labels in the point panel: e.g., “Radar estimate over this area, scan valid 14:06 CDT,” “Station observation 8 km away, observed 13:55 CDT,” and “Grid forecast 15:00–16:00 CDT.” These strings are format examples with fictional times/distances, not current observations. Offer evidence details including footprint, source time, quality and source link.

## Required adversarial cases before a point-weather accuracy claim

These are specified tests, not passed results. Combine deterministic contract tests with independently adjudicated meteorological validation. Use event-separated cases and held-out sites; do not use the same upstream data as prediction and supposed ground truth.

| Case | Required behavior |
| --- | --- |
| Two neighboring roofs share one forecast cell. | Preserve each pin and identical source cell; do not invent different roof forecasts. |
| Lon/lat accidentally swapped, or Web Mercator meters supplied. | Validate formats/CRS and fail clearly; include a swap where both values are numerically legal to test adapter ordering. |
| Point on grid/forecast-office boundary; mapping changes tomorrow. | Deterministic source selection with provenance; re-resolve mappings and invalidate derived caches. |
| Point near a tornado polygon edge; county overlaps but point is outside. | Preserve official geometry; separate nearby/county context from point warning inclusion. Test exact outer boundary, holes and multipolygons. |
| County-based watch has null geometry; public-zone-only query has no alerts. | Resolve county evidence; never conclude no alert from the incomplete zone response. |
| Null geometry and boundary service outage. | Return unresolved point applicability with last-known/source area information; no false all-clear. |
| Current composite tile contains a stale local radar contribution. | Point age/coverage reveals the stale contribution; newest mosaic timestamp cannot override it. |
| Nearest airport is across a mountain/coastline/outflow boundary. | Preserve station location/height/age and representativeness limits; do not substitute it as a site measurement. |
| Hail swath overlaps a roof and a report is 5 km away. | Distinguish area estimate from nearby observation; no exact size, roof impact or damage conclusion. |
| Small reported hail corrects to large hail after decision cutoff. | Retrospective result includes correction; knowable-then result includes only information available then. |
| NWS API observation is 20 minutes old; latest forecast is valid now. | Show separate observation and forecast labels; retrieval time cannot make either a fresh measurement at the site. |
| Overnight rain straddles DST and overlaps running totals. | Correct local-day UTC bounds and non-overlapping interval accounting; partial coverage is explicit. |
| Forecast arrives after its issue time; archive lacks availability logs. | Historical decision replay marks availability unknown; does not claim operational verification. |
| Alaska, Hawaii, Puerto Rico, coast/ocean, U.S. border and antimeridian. | Product-specific coverage, correct geometry and timezone; unsupported products remain explicit gaps. |
| Click A, then click B; A completes last. | B remains selected, with no values or warnings from A attributed to B. |
| API outages, revoked access, rate limiting, empty payload and null field. | Distinct source/value/coverage states; never zero rainfall, zero hail probability or no warnings by default. |
| Provider resamples the same upstream model to a finer grid. | Record common lineage; do not claim independent agreement or improved actual resolution without validation. |
| Timestamped station wind has undocumented averaging period. | Preserve unknown duration; do not treat it as instantaneous, a gust, or an interval maximum without supporting metadata. |
| Exact site sensor disagrees with radar/forecast. | Evaluate QC and times; preserve difference and score against eligible independent evidence instead of automatically selecting agreement. |

Score point-location correctness, source-support matching, warning inclusion, temporal eligibility and honest missing/stale handling separately from meteorological error. For each variable, predeclare the reference instrument/report quality, spatial/temporal tolerance, accumulation/averaging period, units and scoring method. Report site/event counts, geography/season/terrain strata, unresolved observations and uncertainty. A perfect coordinate test does not measure hail skill; strong rain estimates do not validate severe gust forecasts.

## Source verification for this contract

Authoritative source contents were retrieved and read on 2026-10-11. Website documentation verifies the stated contracts; it does not establish endpoint runtime availability, current commercial access or benchmark accuracy.

- **[S1] NWS API documentation:** https://www.weather.gov/documentation/services-web-api — HTTP 200. Checked approximately 2.5 km forecast grids; `/points` mapping changes; linked forecast/station/zone information; coastal marine `forecastGridData`; seven-day alerts history; radar endpoints supply status, not radar display imagery; upstream observation delays. The precipitation-rounding entry is in the **Resolutions** section and is not cited as an ongoing defect. `api.weather.gov` runtime requests are blocked by this environment's CONNECT 403 according to the shared research checks; documentation access does not resolve that limitation.
- **[S2] NWS WWA Alerts Geolocation Guide:** https://www.weather.gov/media/documentation/docs/NWS_Geolocation.pdf — HTTP 200; PDF text extracted and read. Checked point/county/zone query behavior; null geometry watches and zone alerts; GeoJSON longitude-first coordinate example; changing official boundaries and update notices. Historical boundary versions still need to be obtained for historical spatial verification.
- **[S3] NWS Peachtree City PoP explanation:** https://www.weather.gov/ffc/pop — HTTP 200. Checked probability of at least 0.01 inch at a forecast point/grid. Apply each selected product's actual threshold and period; do not generalize this to hail or non-NWS products.
- **[S4] NWS alerts documentation:** https://www.weather.gov/documentation/services-web-alerts — HTTP 200. Checked point-query example and recommendation to request alerts no more frequently than every 30 seconds. Some issue/change sections carry older dates; geographic/provider behavior still requires release-specific runtime checks.
- **Not verified in this pass:** RFC 7946 at `rfc-editor.org` and NCEI Storm Events landing page were blocked by CONNECT 403; one NSSL MRMS page returned HTTP 503. They are not treated as newly read evidence. Source CRS/GeoJSON compliance, historical archive contracts and MRMS product-specific geometry require authoritative source/adapter verification before implementation approval.

Coordinate handling, cache design, display labels and the tests above are engineering recommendations derived from the evidence and known query risks. They are not undocumented guarantees from any provider. AccuWeather, WindBorne, Zoom Radar and Tomorrow.io must each satisfy this contract with verified product metadata, live sample responses and license/coverage checks before their point values can be compared or used in production.
