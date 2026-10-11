# Roofing app: weather research and Claude build handoff

Prepared October 11, 2026. Scope: U.S. roofing companies; storm inspection targeting and crew weather planning. Company name, launch market, stack, provider budget, and current Claude implementation are not yet supplied. Recommendations below are a starting design, not a live integration or vendor purchase.

## Recommended direction

Build three connected views: Live Storms, Storm History, and Crew Outlook. Use NWS forecasts and alerts as the baseline, SPC reports as supporting observations, and MRMS MESH or a licensed commercial hail product for estimated hail footprints. Keep estimated, reported, forecast, and inspection-confirmed information separate.

A street-address lookup is useful, but address precision is not weather precision. The app can identify properties inside an estimated exposure area; it cannot establish that a specific roof was damaged. Label these properties “Inspection candidates.”

## Verified source shortlist

| Source | What it contributes | Limits and implementation choice |
|---|---|---|
| NWS API [1] | Free forecasts, observations, and official alerts. Coordinate lookup returns hourly and raw grid forecast URLs. | Identifying User-Agent required; honor caching and rate limits. Forecast grids are roughly 2.5 km. It does not provide radar display imagery. Use it as the first forecast and warning adapter. |
| NOAA/NSSL MRMS [2–4] | Radar-based estimated hail size (MESH), reflectivity and precipitation products; system describes 1 km grids and a 2-minute update cycle. | Product-specific units, timing, missing values and coverage must be checked. MESH is an estimate, not a roof inspection. Ingestion, gridded processing and map tiles require backend work. |
| SPC preliminary reports [5] | Hail and thunderstorm wind point reports; CSV downloads. | Preliminary, subject to revision. Points are observations near reported locations, not continuous swaths. Reports without numeric wind speed stay unknown. Useful corroborating layer. |
| NOAA NCEI Storm Events [6] | Historical event records. | Use for retrospective context, not the live warning engine. Check current archive coverage and publication status before promising a history period. |
| Xweather [7–9] | Documented hail nowcasts, storm-cell tracking and lightning-related products. Hail threats cover now to +60 minutes in 10-minute intervals. | Subscription and product entitlements apply. Hail threats are forecasts, not historical hail verification. Evaluate as a faster commercial integration path; do not assume all products share coverage or pricing. |
| Verisk [10–11] | Publicly documents API delivery of hail, wind and lightning analytics; Benchmark sample demonstrates estimated weather history at and near an address. | Candidate for licensed property weather history. Confirm present availability for roofing businesses, endpoint documentation, retention and redistribution rights, coverage and quote before selecting. |

Recommendation: start with the free forecast/report layers and one hail-footprint path. For a quick production launch, trial a commercial hail provider against MRMS on known events. Free source data still has processing, storage, map and maintenance costs. No commercial pricing or SLA has been confirmed.

## Product specification

### 1. Live Storms

- Search by city, ZIP, address or saved service territory. Save branch territories and job locations independently.
- Toggle radar reflectivity, estimated hail, reported hail, official warnings and job markers. Each layer has its own legend and time.
- Play recent radar frames. Show frame time, source time and feed age. Never animate old frames as if they are current.
- Show official warning headline, affected area, issue/expiry time and source link. Preserve updates and cancellations.
- Offer territory/job alerts with configurable hail thresholds. Notification copy says “Estimated hail exposure” or “Reported hail nearby,” according to evidence type.
- Optional storm-cell movement and short-term nowcast layer only when supplied by a documented provider. Never derive ground wind speed from a storm’s travel speed.

### 2. Storm History and inspection targeting

- Pick a date range, event and hail-size filter. Compare the event footprint with saved properties and territories.
- On a property card show estimated hail at the available grid/geometry, nearby report size and distance, event time, data source, and resolution. Keep point reports separate from estimates.
- Distinguish forecast gusts, station-measured gusts, reported estimates and modeled event winds. Radar colors do not measure wind at a roof.
- Convert selected properties into inspection candidates; assign a rep; track not contacted, scheduled, inspected and completed. Inspection results remain separate from weather evidence.
- Count intersecting saved properties. Do not call that count “damaged roofs,” “customers” or confirmed leads. Broad neighborhood counts need licensed property/building data.
- Export a weather exposure summary with a timestamped map, legend, sources, observations, estimate labels and inspection notes. Do not describe an internally generated export as certified weather evidence.
- An absence of reports is not evidence that no hail occurred. A circular buffer around a report may be a search area, but cannot be portrayed as a measured hail footprint.

### 3. Crew Outlook

- Per-job hourly rain chance, rain amount when available, sustained wind, gusts, temperature and relevant official alerts, plus a 7-day planning view.
- Display daylight and humidity where supported; add lightning proximity/nowcast only with an appropriate data source. General hourly forecasts are not lightning detectors.
- Suggest weather review windows using company-configured work rules and material requirements. Explain which conditions triggered the suggestion.
- Status language: “Weather review needed,” “Forecast meets configured conditions,” and “Data unavailable.” A green forecast badge must not promise that roof work is safe.
- Include a supervisor review action and crew acknowledgement. Outages or missing critical inputs must not become an all-clear status.

## Data and engineering requirements

Use provider adapters so vendors can change without rewriting the UI. Proposed normalized records:

```typescript
type EvidenceKind = 'forecast' | 'radar_estimate' | 'point_report'
  | 'station_observation' | 'official_alert' | 'inspection';

interface WeatherEvidence {
  id: string;
  provider: string;
  sourceRecordId: string;
  kind: EvidenceKind;
  hazard: 'hail' | 'wind' | 'rain' | 'lightning' | 'tornado' | 'other';
  issuedAt: string | null;       // ISO 8601 UTC
  validFrom: string;
  validTo: string | null;
  receivedAt: string;
  geometry: GeoJSON.Geometry | null;
  spatialResolutionMeters: number | null;
  magnitude: number | null;
  unit: string | null;
  providerProbability: number | null;
  probabilityMeaning: string | null;
  sourceUrl: string | null;
  status: 'preliminary' | 'active' | 'updated' | 'expired' | 'cancelled' | 'archived';
}
```

These are proposed internal fields, not a representation of a provider’s actual response schema. Store original units and raw provenance alongside normalized values. Keep the provider’s probability definition; do not turn it into a roof-damage probability.

- Store UTC; display the timezone at the job/property. Do not use the phone’s timezone to assign storm dates.
- SPC reporting days span 12:00 UTC to 11:59 UTC the next day. Hail CSV size is hundredths of an inch; 175 means 1.75 inches. Preserve unknown gusts as null. [5]
- Discover NWS URLs through `/points/{latitude},{longitude}`; follow returned forecast URLs. Use documented alert filters. Radar must come through a separate display/data source. [1]
- Spatial joins should record the cell or footprint used, event interval and resolution. Show “Estimated exposure” when a point intersects an estimated swath.
- Process MRMS grids server-side into bounded event footprints and map tiles. Check product metadata and nodata sentinels against current tables. Record missing frames and partial coverage; avoid smoothing boundaries into false street-level precision.
- Cache shared requests by weather grid/territory. Honor provider caching, use backoff, cap retries and monitor latency, missing frames and ingestion failures.
- Configure feed-specific freshness thresholds; display explicit stale/partial/unavailable status. Retain an official warning until its status and validity are reconciled rather than clearing it after a failed request.
- Handle provider revisions idempotently. Deduplicate notifications by event revision, territory/job, hazard and user rule. Persist delivery failures for retry without repeated user alerts.
- Keep keys server-side. Configure attribution, retention, commercial display and export rights per provider. Do not assume a consumer weather subscription permits embedding its maps in this app.

## Inspection priority: start explainable

Use configurable priority tiers, with a visible reason such as “Inside estimated 1.5-inch hail area; nearby report; not yet inspected.” The sample threshold is a company targeting choice, not a universal damage threshold. Do not invent an accuracy percentage or damage probability.

Later, evaluate targeting against documented inspection outcomes across roof materials, ages and markets. Any predictive damage model needs independent validation and calibration before displaying probabilities.

## Build sequence and acceptance checks

1. Implement source-labelled NWS forecasts/alerts, job locations and stale-feed states.
2. Add preliminary storm reports and event history browsing.
3. Add one validated estimated hail-footprint source and property intersections.
4. Add assignments, saved territories, notifications and weather exposure exports.
5. Add licensed lightning/nowcast data, advanced history and measured targeting analytics if budget supports them.

Required checks: 175 converts to 1.75 inches; unknown wind stays unknown; UTC/local midnight and daylight-saving cases retain correct dates; warning updates/cancellations reconcile; feed failures display unavailable/stale; estimates and reports stay distinct; no report is not an all-clear; repeated ingestion does not create duplicate candidates or notifications; a map intersection never creates “confirmed damage”; exports retain source/legend/timestamps; demo metrics never appear as live data.

## Image direction and asset boundaries

Two original visuals accompany this handoff: a weather dashboard concept and a decorative post-storm neighborhood hero photograph. The dashboard is a design reference with fictional sample metrics, not usable weather data or a production map. The hero is synthetic decorative imagery and must never be used as inspection or storm evidence.

Suggested UI: off-white cards, navy navigation, teal actions, amber/purple estimated hail bands, labelled report markers and a clear evidence legend. Make legends accessible with text and shape as well as color. Keep the map large, the layer count manageable, the property action near its evidence, and job weather readable on mobile.

Build actual charts, map overlays, weather symbols and interactive UI in code using real data and provider-approved assets. Do not crop the mockup into the app as functional controls. Keep synthetic images out of inspection records, customer evidence and historical weather reports.

Image-generation prompts:

Both visuals were generated with the built-in image tool. Any company name or logo in the mockup is an illustrative placeholder; use the actual company's existing branding. The property-level wording and map boundaries in the mockup are conceptual: production must show the source's spatial resolution and avoid implying parcel-scale weather measurement.

- Dashboard: clearly labelled demo roofing Storm Intelligence interface; desktop map with distinct estimated-hail swath and reported-hail points; Live/History/Crew tabs; property exposure card; schedule-inspection action; hourly crew outlook; mobile companion; navy/off-white/teal styling; fictional metrics; visible inspection-needed wording.
- Hero: photorealistic elevated view of ordinary suburban asphalt-shingle roofs after a storm; wet surfaces, receding clouds and daylight; quiet space for text; no logos, labels, maps, people on roofs or invented damage.

## Copy-and-paste instruction for Claude

> Continue building the roofing app using this handoff as the weather module specification. First inspect the existing app and adapt to its stack, navigation and design system. Implement Live Storms, Storm History and Crew Outlook with provider adapters, source-labelled evidence, honest spatial precision and feed freshness. Start with documented free forecast/alert/report data and keep the hail-footprint adapter configurable. Treat the attached dashboard image as visual inspiration and the hero as decorative only. Use clearly flagged demo fixtures until each live integration is connected; never silently substitute demo weather for failed live feeds. Preserve estimates, forecasts, reports and inspections as different evidence kinds. Do not create confirmed roof damage, insurance eligibility or a probability of damage from weather exposure alone. Complete the acceptance checks above and report which feeds are live, which are demos, and which require subscriptions. Integrate this module into the existing project rather than replacing unrelated app work.

## Sources

Provider facts checked October 11, 2026. Public documentation supports capabilities; commercial entitlements and quotes require confirmation.

1. NWS API documentation: https://www.weather.gov/documentation/services-web-API
2. NOAA NSSL MRMS overview: https://www.nssl.noaa.gov/projects/mrms/
3. MRMS operational product tables: https://www.nssl.noaa.gov/projects/mrms/operational/tables.php
4. NOAA NSSL hail detection: https://www.nssl.noaa.gov/education/svrwx101/hail/detection/
5. SPC preliminary report format and reporting-day notes: https://origin-west-www-spc.woc.noaa.gov/climo/reports/today.html
6. NOAA NCEI Storm Events: https://www.ncei.noaa.gov/access/storm-events-database/
7. Xweather hail threats: https://www.xweather.com/docs/weather-api/endpoints/hail-threats
8. Xweather storm cells: https://www.xweather.com/docs/weather-api/endpoints/stormcells
9. Xweather endpoint/product entitlements: https://www.xweather.com/docs/weather-api/endpoints
10. Verisk weather analytics API announcement: https://www.verisk.com/company/newsroom/insurers-can-integrate-detailed-weather-analytics-into-their-systems-with-verisks-new-api/
11. Verisk Benchmark sample: https://www.verisk.com/4a4a83/siteassets/media/downloads/property-estimating/benchmark-hail-history-report-sample.pdf

## Exact generation prompts

### Dashboard

Use case: ui-mockup. Asset type: visual design reference for a U.S. roofing company's weather module, desktop dashboard plus a small mobile companion screen. Create a polished realistic SaaS interface concept, wide landscape composition. Calm off-white cards, dark navy sidebar, teal action buttons, amber and purple hail overlay accents, readable modern type, generous spacing. Main desktop title 'Storm Intelligence'; persistent visible banner 'DEMO DATA • DESIGN CONCEPT'. Sidebar Weather, Properties, Inspections, Crews. Main map is a fictional suburban neighborhood street grid, no real location, with a translucent amber and purple radar-estimated hail swath and separate point markers for reported hail. Map legend 'Estimated hail' and 'Reported hail'. Small tabs 'Live', 'History', 'Crew outlook'. Cards: 'Estimated hail: 1.5 in', 'Nearby report: 1.25 in', 'Inspection candidates: 84'. These are fictional examples. A right-side selected property card 'Weather exposure', 'Radar estimate', 'Inspection needed', teal 'Schedule inspection' button. Bottom hourly crew weather strip with rain and gust icons, timestamps, restrained typography. Small mobile companion shows crew outlook and amber 'Weather review needed' card. Add a short visible note 'Weather exposure does not confirm roof damage'. No fabricated damage percentages, no insurance claims or approval language. No actual weather data, no real street addresses, no vendor logos. Treat all maps and metrics as clearly labelled demo design only. Flat front-facing product presentation without a photograph background or heavy perspective. Prioritize coherent practical interface and large readable text over dense tiny copy.

### Hero

Use case: photorealistic-natural. Asset type: wide landscape hero/background photograph for a professional roofing weather app. Primary request: an original editorial-style aerial view of an ordinary U.S. suburban neighborhood immediately after a storm has passed. Show authentic asphalt-shingle roof textures, modest houses, trees and streets, wet roof surfaces with subtle reflections, dark receding storm clouds toward the far horizon and warm clear daylight breaking through. View from a moderate elevated drone angle; roofing surfaces are the main subject. Composition has quieter darker sky and soft distant neighborhood detail across the left third for future text overlay, sharper roof detail in lower right. Calm, credible, practical mood. No text, no brand logos, no map pins, no radar overlays, no fake weather metrics, no people on roofs, no spectacular tornado, no invented roof damage or giant hailstones. This is decorative synthetic imagery, not a photograph of an actual storm or inspection. Natural photographic proportions and physically plausible roofs. Wide 16:9 style composition.

