# A live weather map Claude can implement

Implementation proposal — 2026-10-11. No Claude application source was supplied in this checkout. This document defines a small deployable service; it does not claim that it is already running. Continue Claude's existing stack when its source arrives. If a new service is needed, the default below supplies a concrete starting point.

## First working slice

Build a map with a movable pin and **Current**, **Forecast**, and **History** panels. The first configured source is NWS: official alerts, grid forecasts and nearby station observations. It can support a useful live point map once its endpoints are reachable. It does not supply exact roof measurements, radar imagery through its radar-status endpoints, reliable observed hail size at every point, or a complete historical archive.

Use a separate adapter for radar tiles/frames and a separate adapter for historical data. Start recording permitted evidence immediately when collection actually begins; publish the collection start and gaps. Past periods outside collected coverage need an authorized archive. Keep those gaps visible while connecting commercial sources.

The four requested candidates are AccuWeather, Weather by WindBorne, Zoom Radar Weather and Tomorrow.io Weather. Their chat plugins can help retrieve/check information when exposed in a chat session. A production app needs licensed server APIs or SDKs, account entitlements, server credential bindings and permitted storage/display/export. Installing a chat plugin does not grant an application continuous API access, bulk queries, historical retention or redistribution rights. Do not copy chat-session tokens into the app. Verify the exact provider/product behind each plugin name before integrating it.

## Small deployable architecture

Default if Claude has no existing stack: TypeScript, a Next.js/React UI, MapLibre GL JS, one Node.js API/worker codebase, and PostgreSQL with PostGIS. Use a durable database job table and transactional outbox first; add a separate broker/cache only when measured load requires it. A licensed basemap tile/style service is another dependency; MapLibre itself does not supply hosted map data. Pin supported dependency versions and commit the application lockfile when implementation is authorized.

```text
NWS alerts -> independent alert worker -> versioned alerts -> alert API/SSE -> map
NWS/vendor point feeds -> workers/adapters -> evidence store -> point API -> panels
Radar provider -> frame manifest/tile adapter ---------------------------> map
Archive provider + collected evidence -> historical query -------------> history
                                           |
                                  optional grounded summary
```

Run the worker as a supervised process separate from request lifetimes. A browser session, scheduled chat or background promise inside a short-lived request is not continuous collection. The API and worker may share a deployment initially but need independent health, bounded resource use, retry policies and restart recovery. Official alerts must remain accessible when the language model, radar vendor or summary service fails.

Core dependencies are HTTPS access to approved provider hosts, a descriptive NWS `User-Agent`, a reachable database, a reliable clock, timezone data, maintained official boundary geometry, a map tile/style service, and credentials/rights only for products that require them. Keep credentials server-side; use short-lived or domain-scoped public map tokens only where the tile provider explicitly supports that design. Avoid exposing saved customer job locations to unnecessary providers or logs.

## Baseline NWS adapter

Use these **documented NWS routes/links**, not invented vendor equivalents:

1. `/points/{latitude},{longitude}` resolves the current forecast office/grid and returns forecast, hourly/grid-data, station and zone links. Follow returned links. Refresh the mapping periodically and after relevant failures/change notices; NWS says office/grid assignments can change.
2. Fetch the returned hourly forecast and/or raw grid data according to the requested variable and valid interval. Record issue/run time, valid period, source cell and its approximate 2.5 km native grid support. Coastal marine grid forecasts have different availability; the documentation points to `forecastGridData` there. An unavailable land forecast link does not mean clear weather offshore.
3. Discover candidate observation stations from returned station links, retrieve their observations using the currently verified API schema, and retain station location, distance, elevation/height metadata when available, observation time and QC. Do not promote the nearest station to an onsite measurement. A source may provide wind and temperature while precipitation remains null.
4. Query official alerts by point and/or ingest sufficiently broad areas and apply verified local spatial matching. `/alerts/active?point={latitude},{longitude}` and county-aware queries avoid the public-forecast-zone-only omission of county watches/polygon warnings. Null geometry requires county/zone resolution. Use official polygons when supplied; county-query results can extend beyond the selected point.
5. Preserve update/cancel/expiry lifecycles and independent last-successful retrieval state. NWS recommends alert requests no more frequently than every 30 seconds; centralize and share requests. Do not create one upstream polling loop per pin, tenant or open tab. Respect cache headers, rate limits, backoff and source-specific policies.

NWS observations may be delayed by upstream QC/ingest; an HTTP response arriving now is not an observation made now. Its `/alerts` history is approximately seven days, and its current forecast routes are not archived past forecasts. Its `/radar` API routes describe radar status and do not return display imagery. Use an independently verified NWS OGC/radar data service or licensed commercial imagery adapter for radar, with actual product/frame metadata and attribution.

## App API contracts

The paths below are **proposed routes for our own service**, not claims about external providers. Match existing Claude routes if available.

| Route | Minimum contract |
| --- | --- |
| `GET /v1/capabilities?lat=…&lon=…` | Per-product/variable geographic coverage, current/forecast/history availability, earliest/latest history, forecast horizon, configured state and licensing-enabled operations. Does not claim accuracy. |
| `POST /v1/point/query` | Validated coordinate and `request_id`; mode; UTC interval; optional historical decision cutoff; variables and units. Returns exact request context, snapshot ID, independently labeled evidence by variable, partial/gap states and provenance. |
| `GET /v1/alerts?lat=…&lon=…` | Independent official-alert snapshot, matched official geometry/area, lifecycle times, retrieval status and unresolved applicability. AI is never a dependency. |
| `GET /v1/map/layers` | Licensed layers available in this environment, source/evidence kind, legend/units, coverage and attribution. Unsupported/disabled layers remain identifiable. |
| `GET /v1/map/layers/{layerId}/frames` | Available real frame IDs, observation/valid intervals, local coverage/quality metadata where provided, expiry and authorized tile URL template or proxy reference. No synthetic current timestamp. |
| `GET /v1/updates` | SSE snapshot/lifecycle updates with reconnect cursor; clients refetch the relevant snapshot after gaps. No guarantee of device delivery or acknowledgement. |
| `GET /health/live`, `GET /health/ready` | Process health versus dependencies needed to serve requests. Include separately authorized operator details; do not expose credentials. Weather-source freshness is a separate field. |

Example request shape:

```json
{
  "request_id": "client-generated-id",
  "point": {"latitude_deg": 39.7456, "longitude_deg": -97.0892, "crs": "EPSG:4326"},
  "mode": "current",
  "variables": ["air_temperature", "wind_gust", "precipitation", "hail"],
  "units": "us_customary"
}
```

This is a request example, not a live weather result. History adds an explicit start/end and `retrospective` or `as_of` semantics; `as_of` requires the decision cutoff. Forecast requests preserve actual provider valid intervals. Invalid coordinates/intervals return a client error. Valid queries with partial or absent source evidence return explicit variable/source states; failed upstream calls must not become numeric zero or “no weather.” The API must distinguish a successful empty alert result from failed alert retrieval.

Use the full [point-weather contract](../../skills/roofing-radar-reading/references/point-weather.md) and [reading contract](../../skills/roofing-radar-reading/references/reading-contract.md) for normalization. Minimum display metadata is value/unit, evidence kind, actual source location/footprint, observation or valid time, provider/product, quality/freshness, and source link. Unknown metadata stays unknown. For a derived value retain its input evidence IDs and deterministic calculation version.

## Spatial and temporal rules that affect implementation

- Preserve the clicked WGS 84 point. Use named latitude/longitude fields internally; GeoJSON is longitude-first while NWS point URLs are latitude-first. Reverse geocoding labels a point and must not move it to a town centroid.
- Query native data cells in the source CRS. A raster color under the cursor is not an authoritative numeric observation. Numeric point readings need provider point/grid data or a verified numeric raster with the actual legend, scale, missing mask, projection and value support. Never decode a screenshot to manufacture exact hail size or wind.
- Show a station observation as nearby with its distance and timestamp, a grid estimate as an area value, and a forecast as a forecast. A source cell spanning many roofs may correctly return the same value at each roof. Do not interpolate categorical hazards or invent subgrid certainty.
- Radar animation uses actual observation frame times and preserves gaps. A forecast animation is labeled forecast with run and valid times. Do not slide an older radar frame to the current clock. Do not merge forecast and observed frames into an unlabeled loop.
- Store UTC instants and display the selected point's IANA timezone. DST days are not always 24 hours. Historical accumulation logic accounts for overlap, missing intervals and actual local-day bounds. “What was knowable then” uses publication/receipt evidence and a cutoff, not merely an older valid time.
- Cache raw payloads by source/product/version, cell/station/frame, run/revision and interval. Cache query-derived results additionally by exact point, requested mode/interval/cutoff, methods and alert snapshot. A shared forecast cell never licenses reuse of a different pin's alert inclusion or station distance. Revalidation does not reset observation age.
- Tie every reply to the requested pin and request ID. If request A completes after a later click B, A cannot populate B's panel. Maintain separate states for individual fields; fresh temperature cannot make stale wind or missing hail appear current.

## Persistence and worker jobs

Use a small durable schema:

- `source_products`: reviewed product version, fields, units, coverage, cadence, freshness policy, upstream lineage and enabled rights.
- `source_records`: immutable source identity/revision, valid/issue/publication/receipt times, raw reference/hash and source/QC metadata. Store payloads or archive objects only as permitted; keep revisions and a first-received ledger.
- `normalized_evidence`: typed values, source support geometry, time intervals, method version and links to source records. PostGIS supports spatial queries; retain original source geometries/CRS references too.
- `official_alert_versions`: source ID/references, lifecycle, geometry/geocodes, official text and boundary version. Do not overwrite history in place.
- `query_snapshots`: reproducible evidence IDs, request context, availability/gap states and optional grounded summary version. Apply customer-data retention policy.
- `jobs`, `outbox`, `collection_status`: durable scheduled work, idempotency/retry state, delivered update cursors and coverage/retrieval checkpoints. Store errors without credential-bearing URLs.

Workers resolve mappings, collect active alerts, refresh active cells/stations, fetch frame manifests, archive permitted records, reconcile revisions and produce outbox updates. Configure polling from selected product contracts and active territory demand; separate alerts from slower archive/backfill work. Use bounded concurrency, timeout/backoff with jitter, circuit breaking, deduplicated retries and request budgets. Recover by replaying durable jobs/checkpoints after restart; log gaps that cannot be recovered. A new collector cannot backfill data it never received unless an archive supplies it.

Persist raw observations and forecasts distinctly. Reanalysis belongs to its own evidence type. Retrospective corrected records can update a modern history panel while a stored earlier decision snapshot stays reproducible. Do not silently rewrite historical alert applicability using today's changed zone boundaries.

## Four-provider integration and selection

Give each adapter the same operations: capability registration, point/current retrieval, forecast retrieval, historical retrieval, frame discovery and normalized provenance. Operations can be unsupported; do not force one vendor to supply everything. Preserve native probability definitions, horizons and variable meanings before comparing results. An adapter cannot define its own permissive freshness policy from untrusted payload data.

Before writing a provider-specific request, verify the official API/SDK schema, auth method, actual subscribed product, geographic coverage, variable definitions, native resolution, issue/valid times, history start and revisions, rate limits, costs, attribution and display/storage/export rights. Request sample responses and a representative trial period through available authorized access. If credentials are absent, record required binding names after confirming the vendor's documented auth method; never invent a key or ask for its value in chat.

Choose providers by a predeclared comparison against NWS plus suitable independent observations. Compare ordinary and severe days across regions, seasons, terrain and forecast lead times; use independent storms/sites for holdout. Score rain amount/timing and probability calibration, wind mean/gust error, hail detection/false alarms and location/time tolerance separately. Report missingness, latency and historical coverage as well as error. Vendor feeds sharing the same upstream radar/model are not independent corroboration. Choose sources or a calibrated combination by variable, lead time, region and weather regime; freeze selection and calibration on development data before held-out evaluation. Blind averaging may degrade skill, especially with shared upstream inputs. Select separate providers for imagery, point forecasts and archives if the evidence/rights/cost support that choice; no winner is established yet.

## Definition of live and release checks

“Live” describes a specific configured layer/field whose real source timestamps, local coverage and freshness policy have passed, while its collector is operating. A reachable app, green process probe, successful fetch, moving demo image or valid API key does not prove live weather. An app may have live warnings, a current nearby observation, a stale radar frame and unsupported hail history at the same time. Show these states separately. Demo fixtures use a separate explicit mode and can never silently fill a live outage.

Implement the following before promoting the first service territory; expand geographic claims only after equivalent checks:

1. A real endpoint smoke test resolves a chosen pin, retrieves official alerts and at least one forecast/observation response, and verifies metadata and source age. Preserve the actual result/coverage; this proves integration, not forecast accuracy.
2. Geometry/lifecycle tests include county and zone mismatches, null geometry, points at polygon edges/holes, overlapping and cancelled warnings, old boundary versions and geometry-service outage. No outage may become an all-clear.
3. Point tests include adjacent roofs sharing a grid, changed NWS mapping, unsupported coast/territory, a station across terrain, lon/lat ordering and reverse-order click replies.
4. Time/value tests include a fresh download of stale local radar, forecast labeled as observation, unit conversion, null versus zero, overlapping rain totals, DST boundaries, later corrected reports and unavailable historical receipt times.
5. Worker tests interrupt collection, restart it, replay duplicates/revisions/out-of-order records and exhaust a provider rate limit. Confirm alert updates remain independent of failed vendor/AI calls and that unrecoverable history gaps remain visible.
6. Radar tests verify actual frame order/times, tile no-data areas, gaps, attribution and point-reading independence from rendered colors. Tiles outside a product's supported domain must not show a false zero.
7. Security/cost checks cover server-only secrets, tenant isolation, coordinate-log handling, request budgets and provider retention/display rules. These are concrete integration checks, not a meteorological certification.

Do not use synthetic contract tests as an accuracy result. Run the separate [evaluation protocol](../../skills/roofing-radar-reading/references/evaluation-protocol.md) against real held-out events and independent observations before claims of improved hail/rain/wind performance. Qualified meteorological/editorial review remains necessary for the intended public-reporting workflow.

## Current evidence and remaining prerequisites

As of this design pass, available tool discovery did not establish callable tools for the four weather plugins. A names/status-only environment scan found no matching weather/API-key-like variables and no repository `.env` files; this does not establish whether the user has active plugin accounts or external API entitlements. No secret values were read or copied. The lead agent's new checks successfully retrieved HTTP 200 from `api.weather.gov/points/39.7456,-97.0892` and `/alerts/active?point=39.7456,-97.0892`, replacing the earlier blocked-access finding for those tested routes. Responses are retained in `/workspace/live-map-evidence/nws_point.response` and `nws_alerts.response`. Other routes, source age, supported fields and sustained worker operation still require their own checks.

The following official documentation was retrieved and read during the preceding point-weather pass: [NWS API](https://www.weather.gov/documentation/services-web-api), [NWS alert geolocation guide](https://www.weather.gov/media/documentation/docs/NWS_Geolocation.pdf), [NWS alerts](https://www.weather.gov/documentation/services-web-alerts), and [NWS PoP definition](https://www.weather.gov/ffc/pop). Those sources support the baseline contracts above. They do not demonstrate current endpoint connectivity, subscribed commercial features, live radar access or past-period completeness. Reverify the current schema and selected products when implementing.

Immediate build order: integrate the NWS point/alert slice and durable collector; connect one verified imagery adapter; connect a documented archive; trial the four commercial candidates in shadow mode; expand geography and hazard claims only with source coverage and measured results. Ship honest partial capabilities as each source becomes operational rather than labeling the entire map uniformly live or exact.

## Implemented Kansas City proof and remaining gap

The user selected Kansas City. The first prototype query uses downtown sample coordinates 39.0997, -94.5786, not a property or known sensor site. The earlier 39.7456, -97.0892 request was a Kansas API-route smoke test, not Kansas City validation.

The standalone prototype now serves an interactive map, NWS nearby observations, hourly forecasts, independent point alerts and exact-point saved query snapshots. Real Kansas City source responses succeeded; read VALIDATION.md for results. This is an on-demand service, with browser polling while its page is open. It has no unattended background collector, live radar, historical backfill, licensed vendor adapters or empirical accuracy certification. Saved query snapshots do not establish historical weather coverage.

For the field pilot, preselect Kansas City urban/suburban/rural sites and observation schedules before storms occur. Record independent sensor location, height, exposure and calibration; separate wind mean/gust, rainfall rate/amount and hail-report truth. Retain quiet periods, outages and no-observation labels. Evaluate forecasts against held-out events/sites, grouped by storm, and archive predictions before outcomes. Report errors and missingness by variable/lead/terrain. Expand territory only after measured results; one successful city does not validate nationwide roof conditions.
