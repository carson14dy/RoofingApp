# Hail-data vendors: what each candidate publicly documents

Checked 2026-10-16 for the Roadmap P1 "broader vendor comparison" and Next 11 (commercial trial). Under D21 the candidates are not integrated and not ranked. This page records what public pages say. It contains no ranking, no "best" claim, and no recommendation beyond the procurement questions in section 6.

## How to read this page

- Each row gives what the page states, then its URL and the check date, 2026-10-16. "Not stated" means the page read that day did not say it. It does not mean the vendor lacks the feature.
- Quoted text is as the fetch tool returned it. The tool summarises pages, so check each quote against the live page before relying on it.
- Statements by a vendor about accuracy, customers or coverage are marked **claim**. None was tested here, and none is a finding (AGENTS.md rule 5).
- "No public price found" means no price on the pages read. It does not mean free.
- Nothing was bought. No account was made, no quote was requested, and no vendor was contacted. Login pages and pages blocked by robots rules were not worked around.
- Montana is inside the continental U.S. None of the pages read names Montana.

## At a glance

Facts from the pages read. Rows follow the order of sections 1 to 5.

| Source | Public price on pages read | History start stated | Use or redistribution terms stated | Accuracy evidence on pages read |
|---|---|---|---|---|
| NOAA: NWS, SPC, MRMS | None found for these products | NWS alerts: past 7 days. SPC and MRMS: not stated. NCEI: not read | NWS disclaimer (public domain, with notice rules). MRMS: software licence only | None. MESH page: no verification statistics, one 2014 example |
| Xweather | Pay-as-you-go $0.0006 per access; hail products 12x | US from 2024-01-01 (other regions conflict, section 2.7) | Not stated on the pricing pages; terms pages not read | Vendor study of 170 solar-site events; no method given |
| The Weather Company HailZone | No public price found | Not stated | Not stated | None on the page read; page carries a Beta label |
| Verisk Benchmark | Hurricane wind $35 per report; hail, wind, lightning not published | Sample report: 2009 to present. Vendor: "the most extensive history" (no span) | Sample disclaimers: named customer, one address, no third-party sharing without written consent | Calibration against claims data, stated by the vendor (claim) |
| Cotality Weather Verify | No public price found | Not stated | Not stated | Vendor statements only; "over 99% accuracy" for lightning, no method |

## 1. NOAA baseline: NWS, SPC, MRMS and NCEI

Review's role for this row: "Baseline official guidance, reports and estimated hail." Review's key unresolved question: "Cost and expertise of processing/operating the selected data pipeline."

### 1.1 NWS API

| Item | What the page states | Source, checked 2026-10-16 |
|---|---|---|
| Documented capability | Forecasts: "12-hour and hourly forecast periods over the next seven days, plus raw grid data." Observations: station data that "may be delayed up to 20 minutes from the upstream MADIS source due to quality control." Alerts: filterable, e.g. all active alerts for a state. Radar: "status data only"; no display imagery. | https://www.weather.gov/documentation/services-web-API |
| Coverage and history | Forecasts on each Weather Forecast Office's grid. Alerts: "issued over the past seven days"; for an official archive the page points to NCEI. Coverage beyond NWS offices: not stated. | https://www.weather.gov/documentation/services-web-API |
| Resolution and units | Forecast grid "about 2.5km x 2.5km". Units for observations and grids: not stated. | https://www.weather.gov/documentation/services-web-API |
| Output type | Point lookup (/points returns office and grid), gridded forecast, station observation, alert records. | https://www.weather.gov/documentation/services-web-API |
| Alert geometry | A zone-code query "does not return county-based alerts." "API queries for zone-based alerts do not contain spatial polygon geometry." County watches "do not contain spatial polygon geometry." The guide shows no date. | https://www.weather.gov/media/documentation/docs/NWS_Geolocation.pdf |
| Update cadence and latency | Cadence not stated. Observations up to 20 minutes behind QC. Caching: "cache-friendly, with content expiring based on its information life cycle." | https://www.weather.gov/documentation/services-web-API |
| Access method | Web API. A User-Agent header is required. The docs say "an API key will replace this requirement in the future." | https://www.weather.gov/documentation/services-web-API |
| Documented limits | "The rate limit is not public information." Over-limit requests return an error; the docs suggest retrying "typically within 5 seconds." Recheck /points periodically; a grid lookup may be cached. | https://www.weather.gov/documentation/services-web-API |
| Redistribution, display, storage, export | Disclaimer: NWS web page information "are in the public domain, unless specifically noted otherwise" and "may be used without charge for any lawful purpose" unless you present it as your own, imply NOAA or NWS endorsement, or alter it and present it as official. Third parties whose works consist mostly of NWS material must give notice that the material "is not subject to copyright protection." The NWS name and logo are trademarks. The disclaimer is written for web page information; the pages read do not say whether it covers API responses. | https://www.weather.gov/disclaimer |
| Public price | None found. The "without charge" wording is in the disclaimer for web page information. | https://www.weather.gov/disclaimer |
| Disclaimers | Timely delivery "not guaranteed"; data provided "as is"; "special attention should be given to the date and time of the data." | https://www.weather.gov/disclaimer |

Conflict to check: D23 cites /points at four decimals with "≤ 7 m quantization." The NWS geolocation guide read gives four decimals in its example request and gives no precision requirement or quantization distance. Source: https://www.weather.gov/media/documentation/docs/NWS_Geolocation.pdf (checked 2026-10-16).

### 1.2 MRMS (NSSL), including MESH and hail swaths

| Item | What the pages state | Source, checked 2026-10-16 |
|---|---|---|
| Documented capability | Over 100 products. Hail-related: SHI ("Severe Hail Index", unit "index"); POSH ("Prob of Severe Hail", %); MESH (mm); MESH swaths for 30 and 60 minutes (2-minute updates) and for 120, 240, 360 and 1440 minutes (30-minute updates); PrecipFlag (surface precipitation type including hail; flag). | https://www.nssl.noaa.gov/projects/mrms/operational/tables.php ; https://www.nssl.noaa.gov/projects/mrms/ |
| Coverage and history | "The primary coverage is the CONUS." Initial 3D mosaics for Hawaii and Alaska; initial connections to Mexican and Caribbean radars. History depth: not stated. The table page gives no coverage limit for the hail rows and does not say whether coverage is limited. | https://www.nssl.noaa.gov/projects/mrms/ ; https://www.nssl.noaa.gov/projects/mrms/operational/tables.php |
| Resolution and units | Overview lists "Resolution of 1-km x 2-min update cycle" under "Current work", and "Operational .5 km CONUS 4D reflectivity mosaics and products" separately. MESH page: 0.01 degrees latitude and longitude, 2-minute time step. MESH: "MESH base units (used in calculations): mm"; "Display units ... AWIPS: Inches." SHI: index. POSH: %. Missing "-1"; no coverage "-3"; range folding "n/a". | https://www.nssl.noaa.gov/projects/mrms/ ; https://vlab.noaa.gov/web/wdtd/-/maximum-estimated-size-of-hail-mes-2 ; https://www.nssl.noaa.gov/projects/mrms/operational/tables.php |
| Output type | Gridded. The table page says GRIB2 filenames get an "MRMS_" prefix, so MESH is MRMS_MESH. Swaths are maxima over an interval; the review notes a swath maximum "belongs to an interval, not necessarily the latest timestamp." | https://www.nssl.noaa.gov/projects/mrms/operational/tables.php |
| What MESH is | "Estimate of the maximum hail size that can be expected." Derived "from the 3D Reflectivity Cube"; the listed input is SHI; temperature comes from "mesoscale model analysis data." The size equation is an image the text read did not show. Reference: Witt et al. (1998). | https://vlab.noaa.gov/web/wdtd/-/maximum-estimated-size-of-hail-mes-2 |
| Update cadence and latency | 2 minutes for MESH and the 30- and 60-minute swaths; 30 minutes for the 120 to 1440-minute swaths. Latency: not stated. | https://www.nssl.noaa.gov/projects/mrms/operational/tables.php ; https://www.nssl.noaa.gov/projects/mrms/ |
| Access method | Products go to NCEP service centers, WFOs and RFCs; "the full suite is publicly available" (overview). File access routes: not read. The UCAR README for MRMS MESH could not be read (section 7). | https://www.nssl.noaa.gov/projects/mrms/ |
| Redistribution, display, storage, export | "The University of Oklahoma retains the right to commercially license the software. Government use is free." This concerns the software. Data redistribution terms: not stated on the pages read. | https://www.nssl.noaa.gov/projects/mrms/ |
| Public price | None found. | https://www.nssl.noaa.gov/projects/mrms/ |
| Documented limits | Overview: no accuracy guarantee stated; automated QC still in work for TDWR, Canadian and commercial radars; several items described as "initial, prototype, or in development." MESH page: MESH "has a tendency to underestimate hail size in" highly tilted storms in strong deep-layer shear, left-moving supercells, supercells with a large bounded weak echo region, and storms with low-density, dry hailstones. The page is "Subject to the biases and deficiencies of the mesoscale model"; "bright band contamination remains." Overestimation is not mentioned. NSSL hail page: on Doppler radar hail "looks like extremely heavy rainfall"; dual-pol helps separate hail from ice pellets and rain. | https://www.nssl.noaa.gov/projects/mrms/ ; https://vlab.noaa.gov/web/wdtd/-/maximum-estimated-size-of-hail-mes-2 ; https://www.nssl.noaa.gov/education/svrwx101/hail/detection/ |
| Verification on the MESH page | "The page contains no verification statistics." One comparison, a figure caption: MESH "approximately 2 inches, near a SPC storm report of 1.75 inch hail" (one storm, 21 July 2014, North Dakota). The page cites no evaluation study. | https://vlab.noaa.gov/web/wdtd/-/maximum-estimated-size-of-hail-mes-2 |

Conflicts to check on the MRMS pages:
- Resolution: "1-km x 2-min" is listed under "Current work"; ".5 km" is listed as operational; the MESH page gives 0.01 degrees. Confirm the operational grid of each hail file.
- Units: MESH is calculated in mm and displayed in inches (AWIPS). Confirm which units the delivered file carries.

### 1.3 SPC preliminary storm reports

| Item | What the page states | Source, checked 2026-10-16 |
|---|---|---|
| Documented capability | Point reports for tornado, hail and wind. CSV and raw CSV downloads, and KML that is "time-enabled" for the Google Earth Time Slider. | https://origin-west-www-spc.woc.noaa.gov/climo/reports/today.html |
| Coverage and history | The page read is one day's report page; its example is the 20150430 page. Coverage area and history depth: not stated. | https://origin-west-www-spc.woc.noaa.gov/climo/reports/today.html |
| Units | Hail: "Hail Sizes in 1/100 of an Inch (175 = 1.75 inches)". Wind: "Wind Gusts in MPH". "Fields marked UNK are unknown"; how UNK is handled downstream: not stated. | https://origin-west-www-spc.woc.noaa.gov/climo/reports/today.html |
| Reporting day | "reports received from 1200 UTC to 1159 UTC the next day." | https://origin-west-www-spc.woc.noaa.gov/climo/reports/today.html |
| Output type | Point reports, not swaths. Files are CSV and KML; the page gives link labels only, not file URLs. | https://origin-west-www-spc.woc.noaa.gov/climo/reports/today.html |
| Update cadence | Not stated. "Page last modified: March 05, 2026." | https://origin-west-www-spc.woc.noaa.gov/climo/reports/today.html |
| Preliminary status | "All Reports Are Considered Preliminary." The page does not say "subject to revision" and does not describe how reports are revised. | https://origin-west-www-spc.woc.noaa.gov/climo/reports/today.html |
| Access, terms, price | File downloads from the report pages. No API described. Terms and price: not stated. | https://origin-west-www-spc.woc.noaa.gov/climo/reports/today.html |

### 1.4 NCEI Storm Events Database

| Item | What the pages state | Source, checked 2026-10-16 |
|---|---|---|
| Documented capability | Historical event records (handoff source table). | https://www.ncei.noaa.gov/access/storm-events-database/ |
| Read status | Not read. The access page returned a server error on fetch, and a repeat was refused for the same error. The products page returned a client error. | https://www.ncei.noaa.gov/access/storm-events-database/ ; https://www.ncei.noaa.gov/products/storm-events-database |

Not verified for NCEI: coverage years, whether hail events are included, publication lag, file formats, terms and price. The handoff says to "check current archive coverage and publication status before promising a history period."

## 2. Xweather (Vaisala)

Review's role for this row: "Live weather, hail nowcasts, recent hail archive, lightning, integration convenience." Review's key unresolved question: "Exact product coverage, latency, archive method, commercial rights and billable usage."

Shared facts from the docs read on 2026-10-16: the docs version is Weather API v1.44.0 (landing page and endpoints index). Every request names one action in the path and carries client_id and client_secret. An active subscription and a registered application are required. Some endpoints are "only available as part of add-ons." Sources: https://www.xweather.com/docs/weather-api and https://www.xweather.com/docs/weather-api/endpoints

### 2.1 Hail threats (/hail/threats)

| Item | What the page states | Source, checked 2026-10-16 |
|---|---|---|
| Documented capability | Hail threats as a nowcast, reported "in ten-minute intervals over the next 60 minutes." Polygon per period with a centroid point and optional forecast path. Fields: probSevere, severe flag, threat speed and direction. | https://www.xweather.com/docs/weather-api/endpoints/hail-threats |
| Coverage and history | "US, Europe, Canada, Japan, Australia." No historical range or archive start on this page. | https://www.xweather.com/docs/weather-api/endpoints/hail-threats |
| Horizon and time step | "Now to +60 minutes" in 10-minute periods. The sample has seven periods. | https://www.xweather.com/docs/weather-api/endpoints/hail-threats |
| Resolution and units | Spatial resolution: not stated. Size: maxSizeMM and maxSizeIN. probSevere: "Probability this threat will produce severe hail (severe is 1 inch / 2.54 cm or greater)." Its unit is not stated; the sample value 10 suggests 0 to 100, but the page does not say so. severe: boolean. Speeds in KTS, KPH, MPH and MPS; direction in degrees. | https://www.xweather.com/docs/weather-api/endpoints/hail-threats |
| Output type | GeoJSON polygons and centroid points per period, coordinates longitude first. forecastPath is a LineString, "Null if not available." Responses use a JSON envelope (success, error, response). | https://www.xweather.com/docs/weather-api/endpoints/hail-threats |
| Update cadence and latency | "Real-time." No refresh period stated. | https://www.xweather.com/docs/weather-api/endpoints/hail-threats |
| Access method | GET /hail/threats/{action} with client_id and client_secret. Actions named include :id, closest, route and contains. The page lists "contains" without explaining how it applies to hail. | https://www.xweather.com/docs/weather-api/endpoints/hail-threats |
| Redistribution, display, storage, export | Not stated on this page. | https://www.xweather.com/docs/weather-api/endpoints/hail-threats |
| Public price | No hail-threat price beyond the pay-as-you-go hail multiplier of 12x (section 2.5). | https://www.xweather.com/pricing/weather-api-pay-as-you-go |
| Documented limits | No entitlement statement on the page. "Rate Limiting" and "Cost Headers" are linked and were not read. | https://www.xweather.com/docs/weather-api/endpoints/hail-threats |

### 2.2 Storm cells (/stormcells)

| Item | What the page states | Source, checked 2026-10-16 |
|---|---|---|
| Documented capability | Storm-cell detection and tracking, described as a product that "attempts to identify and track storm cell movement." Per cell: hail object, traits (general, hail, rotating, tornado), mesocyclone value, tornado vortex signature, reflectivity, VIL, heights. Forecast positions every 15 minutes for up to one hour, with error values and cones. Source described as the US NEXRAD radar network. | https://www.xweather.com/docs/weather-api/endpoints/stormcells ; https://www.xweather.com/docs/weather-api/endpoints |
| Coverage and history | "United States, Puerto Rico, and Guam." Time range "Latest." No historical depth stated. | https://www.xweather.com/docs/weather-api/endpoints/stormcells |
| Resolution and units | Not stated for the detection grid. Distance from radar in nautical miles. Units of ob.dbzm and ob.vil: not given. Heights in feet and metres. | https://www.xweather.com/docs/weather-api/endpoints/stormcells |
| Hail fields | ob.hail is null "if hail information unavailable for the storm cell." ob.hail.prob: "Probability that the storm contains hail of any size." ob.hail.probSevere: severe means "1.00 inch or larger." maxSize: "Maximum diameter of hail stones in hundredths of an inch," listed beside maxSizeIN and maxSizeCM. traits.hail: "1 = at least a 70% probability of hail, 0 = no significant hail threat." | https://www.xweather.com/docs/weather-api/endpoints/stormcells |
| Output type | Cell records. Output formats beyond the listed fields: not stated. | https://www.xweather.com/docs/weather-api/endpoints/stormcells |
| Update cadence and latency | "every 2-3 minutes." End-to-end latency: not stated. | https://www.xweather.com/docs/weather-api/endpoints/stormcells |
| Access method | GET /stormcells/{action}; actions :id, closest, within, search, affects. Summary at /stormcells/summary. | https://www.xweather.com/docs/weather-api/endpoints/stormcells ; https://www.xweather.com/docs/weather-api/endpoints |
| Documented limits and price | No rate limit, quota or entitlement tier on the page. Authentication and rate-limit pages not read. The pricing page lists no storm-cell multiplier; the endpoints index shows multipliers of 5x, 10x, 12x and 25x that the page does not define. | https://www.xweather.com/docs/weather-api/endpoints/stormcells ; https://www.xweather.com/pricing/weather-api-pay-as-you-go |
| Redistribution, display, storage, export | Not stated. | https://www.xweather.com/docs/weather-api/endpoints/stormcells |

Conflict to check: maxSize is documented in hundredths of an inch, and maxSizeIN is documented in inches. Confirm both units against a live response before any use.

### 2.3 Hail archive (/hail/archive)

| Item | What the page states | Source, checked 2026-10-16 |
|---|---|---|
| Documented capability | "Historical hail occurrence and severity" (endpoints index). Hourly periods with maxSizeIN, maxSizeMM, probSevere, timestamp and dateTimeISO; profile time zone and elevation. | https://www.xweather.com/docs/weather-api/endpoints/hail-archive ; https://www.xweather.com/docs/weather-api/endpoints |
| Coverage and start dates | US data begins 2024-01-01; Europe 2024-03-08; "other regions" 2025-02-01. The endpoint page names the regions as "US, Canada, Japan, Europe, Australia." See section 2.7 for a conflict. | https://www.xweather.com/docs/weather-api/endpoints/hail-archive |
| Update cadence | "Data refreshes hourly." | https://www.xweather.com/docs/weather-api/endpoints/hail-archive |
| Query increment | 24 hours: data "retrieved in 24 hour increments"; "Additional data will require additional queries." | https://www.xweather.com/docs/weather-api/endpoints/hail-archive ; https://www.xweather.com/docs/weather-api/endpoints |
| Multiplier | 12x. The endpoint page does not say what the multiplier applies to; the pricing page lists hail/archive as an example of 12x. | https://www.xweather.com/docs/weather-api/endpoints/hail-archive ; https://www.xweather.com/pricing/weather-api-pay-as-you-go |
| Resolution | Not stated. The hail-data page says hail is "localized within a few kilometers" and gives no grid size. | https://xweather.com/weather-api/hail-data |
| Probability field | probSevere: "Probability of severity for this hail event." No scale or unit given. | https://www.xweather.com/docs/weather-api/endpoints/hail-archive |
| Output type | periods[] array of hourly records; loc.lat. The page's description of loc.long ("The place or nearest place to the record") does not match a numeric field, probably a documentation error. | https://www.xweather.com/docs/weather-api/endpoints/hail-archive |
| Access method | GET /hail/archive/{action}. Only :id is documented; it accepts a city name, lat/long, or US and Canadian postal codes. Filters, queries and sorting sections are headed but empty. | https://www.xweather.com/docs/weather-api/endpoints/hail-archive |
| As-of access and revisions | Not stated. Whether a period's values change after first publication: not stated. | https://www.xweather.com/docs/weather-api/endpoints/hail-archive |
| Documented limits | The only stated limit is the 24-hour increment. No rate limit, result cap or maximum date range on the page. | https://www.xweather.com/docs/weather-api/endpoints/hail-archive |

### 2.4 MCP server and Phrases API

| Item | What the page states | Source, checked 2026-10-16 |
|---|---|---|
| MCP: capability | Tool categories: "General, Forecast, Air Quality, Lightning, Tropical, Maps, and Roadweather." Hail is not mentioned on the page. | https://www.xweather.com/docs/mcp-server |
| MCP: coverage and history | The page refers to "looking back at past weather" but names no datasets or endpoints. | https://www.xweather.com/docs/mcp-server |
| MCP: access, price, terms | Requires an Xweather API key; whether it goes in a header or a query parameter is on a linked page not read. Subscription, usage limits, free tier and data-use terms: not stated. Terms of Service and Privacy Policy are linked and were not read. | https://www.xweather.com/docs/mcp-server |
| Phrases: capability | An "AI-driven weather API" that synthesizes Xweather data into "simple, comprehensive, and actionable text based summaries tailored to your location." Hail: not mentioned on the page read. | https://www.xweather.com/docs/phrases-api |
| Phrases: inputs and coverage | "combines all of the most important, high-quality datasets from the Xweather Data API." Datasets and geographic coverage: not stated. | https://www.xweather.com/docs/phrases-api |
| Phrases: access | Registration with the Phrases API gives an access ID and secret key. An active Xweather account is required; available data depends on the subscription. Changelog version shown: 1.0.0. | https://www.xweather.com/docs/phrases-api |
| Phrases: languages, price, terms | "Supported Languages" is linked and was not read. No Phrases-specific pricing. Terms & Conditions and the Attribution Guide are linked and were not read. | https://www.xweather.com/docs/phrases-api |

Note on Phrases: the vendor describes this output as AI-driven. AGENTS.md rule 6 says "No AI-generated text anywhere in the alert path," so under that rule its text could not enter the alert path.

### 2.5 Pricing and terms, all Xweather products

Sources for every row: https://www.xweather.com/pricing/weather-api-pay-as-you-go and https://xweather.com/pricing/weather-api-subscription, both checked 2026-10-16.

| Item | What the pages state |
|---|---|
| Pay-as-you-go base rate | "$0.0006 per access" in each calculator row. The pages use "$" and name no currency code. Pay-as-you-go is "available in the US and Canada only." |
| Free allowance | "The first 15,000 accesses each month are free across all services." The allowance is shared across services. |
| Billing start | "Costs start only after your combined usage (including any multipliers) exceeds the free tier." Accesses past the free tier use the base rate; no separate overage schedule is shown. |
| Multipliers | Standard endpoints 1x (forecasts, conditions, alerts). Lightning 10x. Hail 12x ("Example endpoints include hail/threats, hail/archive"). Air quality 5x. Raster maps 1x. MapsGL 150x ("1 MapsGL 5-minute unlimited use session uses 150 accesses"). /roadweather 1x; other road weather multipliers not stated. |
| Derived hail rate (our arithmetic) | 0.0006 x 12 = $0.0072 per access. Arithmetic from the published values, not a published rate. |
| Definition of an access | Not defined on the pages read. The estimator is "for planning purposes and does not represent an invoice." |
| Minimums and caps | None stated for pay-as-you-go. "No spending caps — you control your usage." A payment method is needed once free usage runs out; signup needs no credit card. |
| Add-ons | "Additional endpoints might require an add-on." No add-on prices are given. |
| Annual and enterprise | Annual plan "extra savings", no figure. Enterprise volume bands "from 5M to 1B+" with a sales contact; no enterprise prices. Enterprise plans offer "custom SLA arrangements and 99.99% uptime" (vendor statement). |
| Commercial use, display, storage, redistribution | Not stated on the pricing pages. The landing page says the Attribution Guide and Terms & Conditions are hosted by Vaisala; they were not read. |
| Effective date | None stated. Footer: "© 2026 Vaisala." |
| Review's illustration (not a quote) | The review's arithmetic: 1,000 properties polled once a minute for 30 days is 43.2 million requests; at 12x that is 518.4 million accesses; after the 15,000 free accesses, at $0.0006, $311,031. The arithmetic checks against the published values. The review says it "is not a forecast of this app's costs." |

### 2.6 Vendor claims on the hail-data page (not tested)

Source for this subsection: https://xweather.com/weather-api/hail-data, checked 2026-10-16.

- **claim**: a validation study of "170 independently confirmed severe hail events at commercial solar facilities." Stated results: "Xweather Protect correctly forecast severe hail for all 170 events with zero misses"; "at least 20 minutes lead time for 95% of the events"; "37-minutes average lead time." The page gives no methodology, comparator or sample definition. "Read the study" links to a blog post, which was not followed.
- **claim**: a "$58 million" average solar hail claim attributed to AXIS Capital (2024). The page says to check the original; not checked.
- **claim**: stow protocols "have been shown to materially reduce damage exposure," attributed to AXIS Capital; the underlying study is not described.
- Unqualified superlatives appear on the page, for example "The weather industry's only hail forecast API." They are not used here.
- Products named on the page: hail threats; the historical hail archive, described as "validated past hail records"; MapsGL with "Eight dedicated hail map layers," "updated every 2 minutes"; Xweather Protect alerts "within a 3 km radius of your assets." Alert add-on price: not stated.
- Intended users named: "solar and energy, and insurance and risk," and "Any organization with outdoor infrastructure." Roofers and contractors are not named.

### 2.7 Conflicts on the Xweather pages

- Hail archive start dates. The endpoint page and endpoints index give US from 2024-01-01, Europe from 2024-03-08 and "other regions" from 2025-02-01. The hail-data page says "January 2024 (US) and February 2024 (Canada, Japan, Europe, Australia)." Ask which is current.
- Hail archive "validated past hail records" (hail-data page) against an endpoint page that describes no validation.
- Severe hail definition: "1 inch / 2.54 cm or greater" on the endpoint pages; "diameter greater than 2.54 cm" on the hail-data page.
- Hail threats sample: the same storm ID, 20250527151500-0, shows 37.1 mm, probSevere 10 and severe true in the JSON sample, and 14.4 mm, probSevere 0 and severe false in the GeoJSON sample. The page calls the samples illustrative.
- Storm-cell hail size units (section 2.2) and the undefined probSevere unit (sections 2.1 and 2.3).
- Archive loc.long description (section 2.3).

## 3. The Weather Company HailZone

Review's role for this row: "HailZone short-range hail guidance and map delivery." Review's key unresolved question: "Independent incremental value, upstream overlap, access terms and production quote."

Source for this section, unless a row says otherwise: https://developer.weather.com/docs/openapi/hailzone-30-minute-2-0, checked 2026-10-16.

| Item | What the page states |
|---|---|
| Documented capability | A MESH-based hail forecast: "forecasts hail size in the 30-minute window following data process time." Variable ID MESHTrack030min; MESH in mm. "Recommended hail detection threshold: 3mm." |
| Products | 326: US CONUS. 410: Canada. australianHailMesh: Australia, using "the Bureau of Meteorology radar network." |
| Coverage and history | CONUS (326); "Southern Canadian areas within radar coverage" (410); Australia. History depth: none stated. Alaska and Hawaii are not listed. |
| Resolution and units | "1-km resolution," listed as a key feature. Forecast time step: not stated. Units: mm (MESH). |
| Output type | Tiler: 256 x 256-pixel binary raster tiles. Featurizer tile: "GeoJSON polygon or line" in Web Mercator. Featurizer feature: GeoJSON vector data at native 1-km resolution. |
| Endpoints | GET /v2/tiler/info returns rt (model run time) and t (valid time); "Call this first." GET /v2/tiler/data returns a raster tile and needs rt, t, level of detail and tile coordinates. GET /v2/featurizer/tile returns vector data where MESH crosses a threshold (rt, t). GET /v2/featurizer/feature returns threshold vectors at native resolution (rt, t). The full parameter schema is not on the page. |
| Update cadence | "Every 5 minutes" for product 326 and australianHailMesh; "Every 2 minutes" for product 410. Latency from radar to product: not stated. |
| Access method | HTTP API. "Standard HTTP caching headers (Cache-Control, Expires) are used." Authentication: not described in the read. |
| Redistribution, display, storage, export | Not stated. |
| Public price | No public price found. A WebSearch for HailZone pricing on 2026-10-16 returned no HailZone price page; its results were other vendors' pages. |
| Documented limits | Rate limits: "Not stated." Terms and licensing: "Not stated." Page title includes "Weather Data API Hub Beta." Changelog: "No updates recorded yet for this API." |
| Conflicts | None found on the page read. Refresh differs by product (5 or 2 minutes). |

## 4. Verisk Benchmark

Review's role for this row: "Property weather history." Review's key unresolved question: "Current schemas, archive depth, correction history, bulk cost and SaaS/export rights."

Pages read on 2026-10-16:

| Document | Date shown on the page | URL |
|---|---|---|
| Press release announcing the API | Dateline 9 August 2021 | https://www.verisk.com/company/newsroom/insurers-can-integrate-detailed-weather-analytics-into-their-systems-with-verisks-new-api/ |
| API brochure (the handoff's source) | "© 2022"; no publication date | https://www.verisk.com/siteassets/media/downloads/property-estimating/benchmark-api-brochure-2022.pdf |
| Hail, wind and lightning brochure | "© 2022"; no publication date | https://www.verisk.com/495e81/siteassets/media/downloads/property-estimating/benchmark-for-hail-wind-and-lightning.pdf |
| Product page, Canada locale | Metadata 15 February 2024; footer "© 2008, 2026" | https://www.verisk.com/en-CA/products/benchmark |
| Product page, Xactware | No date | https://www.xactware.com/products/benchmark.html |
| Sample hail history report | Sample report dated 14 August 2026 | https://www.verisk.com/4a4a83/siteassets/media/downloads/property-estimating/benchmark-hail-history-report-sample.pdf |
| Storefront | Not read: robots rules block it | https://bmstore.veriskweather.com |

| Item | What the pages state | Source, checked 2026-10-16 |
|---|---|---|
| Documented capability | Hail (size, "probability of severe hail", 1- and 5-mile context); straight-line wind (gust speed and duration); lightning (strikes within 5 miles over three days); hurricane wind. The 2022 API brochure: "property-specific weather peril analysis for hail, straight-line wind, lightning, and hurricane wind." The Canada product page names only hail and lightning. | Brochure 2022; en-CA page; Xactware page (URLs in table above) |
| Related product | The hail, wind and lightning brochure says Respond uses "dual-polarization radar" and "severe weather shape files," and is "pitched to users setting reserves." Respond was not evaluated. | Hail, wind and lightning brochure (URL in table above) |
| Coverage | "continental U.S. or Canada" (Xactware page). "in the United States and Canada" (hail, wind and lightning brochure). The 2022 API brochure states no coverage. | Xactware page; hail, wind and lightning brochure |
| History depth | Xactware page: "History on demand"; "damage that predates policy inception." No start year. Sample report: period "01 Jan 2009 to present," but its table begins with a 2 June 2020 event and notes earlier and later events exist. Brochure: "the most extensive history of weather-related events" with no span. | Xactware page; sample report; 2022 API brochure |
| Resolution and units | "address-specific" (brochure); "property-specific" (Canada page and sample). No grid or cell size given; maps described as "granular." Sample units: hail in inches (diameter); probability in percent; wind in mph, defined as the "estimated maximum 3-second peak gust at 10 meters above ground from straight-line, non-tornadic winds, excluding tropical cyclones." A significant event is hail of 0.75 inch or greater (sample). | Sample report; hail, wind and lightning brochure |
| Output type | Property-specific reports. The sample is a PDF with an event table of 18 rows and three locations: the property, the daily maximum within 1 mile, and the daily maximum within 5 miles. Reports arrive in Xactimate, XactAnalysis, ClaimSearch Research Hub, Guidewire, the online store and the API; they can be ordered automatically "based on peril type, intensity, and location." | Xactware page; sample report |
| Update cadence and latency | "Delivered in seconds" (Xactware page); "available in near-real-time" (brochure). No refresh cadence stated. Latency distribution: not stated. | Xactware page; hail, wind and lightning brochure |
| Access method | Benchmark API: "integrate location-specific weather data directly into your existing applications." The 2022 brochure says data is "streamed into their desired platform." Also the storefront (not read) and platform integrations. | Canada page; 2022 API brochure |
| Data sources (sample) | "Benchmark natural hazard history database"; "WSR-88D network data, including polarimetric variables"; numerical weather models; lightning networks; datasets "calibrated against industry claims data and other ground-truth sources" (**claim**, not checked). "Storm reports are not mentioned." | Sample report |
| Redistribution, display, storage, export | Sample disclaimers, which are not the contract: the report is "wholly advisory in nature and are provided as is." It "may be used for the specific address of interest and may not be used for any other address or location." It is for the named customer only, may not be shared with third parties without written consent, and may not be altered or misrepresented. Verisk may terminate access. Storage, retention, AI use, multi-company display and export: not stated on the pages read. The brochure has no redistribution or data-use terms. | Sample report; 2022 API brochure |
| Public price | Hurricane wind reports: $35 per report, "subject to change." No published price for hail, wind or lightning reports. "Pricing is per report, with no subscription required" (Xactware page). "Enterprise volume and API access are 'quoted by sales.'" No free trial or demo mentioned; sales hours Monday to Friday, 8 a.m. to 4 p.m. Eastern (Canada page). | Xactware page; Canada page |
| Documented limits | The sample says the report is "wholly advisory." The sample's claim fields are blank, and the report does not reference a claim-specific inspection. The sample's probability key labels 70% as "very high certainty," 50% as "high," 30% as "possible" and 10% as "low"; the event the probability refers to is not defined on the page read. Under AGENTS.md rule 5 it cannot be shown as a damage probability. | Sample report |
| Intended users | "Property and casualty insurers and their service provider partners" (brochure); "insurers and adjusters" (Xactware page); "Insurance claims and underwriting teams" (2021 press release). Roofers and contractors are not named on any page read. | 2022 API brochure; Xactware page; 2021 press release |
| Current technical documentation | None found. No endpoint, schema, authentication or version page appeared in search or in the pages read. The 2022 brochure is a "marketing overview, not technical documentation" (fetch summary). | 2022 API brochure; Canada page; Xactware page |
| Vendor claims (not tested) | "The most extensive history of weather-related events for each property location in the United States and Canada" (brochure). "Minimize guesswork" (brochure). "40% of hail-related claims carry an inconsistent date of loss," citing an undated XactAnalysis statistic (Xactware page). Datasets "calibrated against industry claims data" (sample). | Brochure; Xactware page; sample report |

Sample report notes (checked 2026-10-16): the requester fields are placeholders (a placeholder address and the phone number 000-000-0000). The disclaimer names "ISO," not Verisk; the page does not explain the relationship. The sample is a sample; it shows the layout, not a verified report.

Conflicts to check:
- Perils: the 2022 API brochure and the Xactware page list four perils; the Canada page lists two; the hail, wind and lightning brochure lists three.
- Coverage: stated on the Xactware page and the hail, wind and lightning brochure, but not on the 2022 API brochure or the Canada page.

## 5. Cotality Weather Verify

Review's role for this row: "Historical hail verification." Review's key unresolved question: "Structured API access, event finalization, accuracy evidence and commercial rights."

Pages read on 2026-10-16:
- Product documentation, the main source: https://content.cotality.com/product-docs/claims-weather-hail-verify/
- Marketing page: https://content.cotality.com/cotality-weather-verifytm/
- Product page with FAQ: https://www.cotality.com/platforms/weather-verify
- Product page (publisher footer "©2026 CoreLogic, Inc."): https://cotality.com/products/weather-verify

| Item | What the pages state | Source, checked 2026-10-16 |
|---|---|---|
| Documented capability | Hail Verification Report, which "confirm[s] hail date, size, and location" (vendor wording); Hail Size Maps; Wind Verification Report and Wind Speed Maps; STRIKEnet Lightning Verification Report ("Pinpoint strike dates, times, & locations"). Hail reports check the loss location and points within 1, 3 and 5 miles. | Product docs; platform page; marketing page |
| Hail threshold | Hail of "0.75 inches or larger" at the loss location and within 1, 3 and 5 miles "on the date of loss." | Product docs |
| Coverage | "continental U.S." (product docs). The region switcher shows "United States." No other coverage detail. | Product docs; products page |
| History depth | A "historical database" is mentioned; no span is stated. | Product docs; products page |
| Resolution and units | "highly granular data for hail size, wind speed, and lightning strikes," with no number. Hail sizes described as "approximate." Hail thresholds in inches. | Products page; product docs |
| Output type | Address- or parcel-level verification reports and hail size maps (product docs); "high-resolution maps" (FAQ). File formats (PDF, CSV, GIS): not stated. | Product docs; platform page |
| Update cadence and latency | "real-time mapping solutions" (products page). Data available "at the first notice of loss (FNOL)" (FAQ, **claim**). Event finalization: not addressed on any page read. Revisions: not stated. | Products page; platform page; product docs |
| Access method | "API integration" is "one way to obtain reports, alongside online purchase and license agreement" (product docs). "API connectivity, the Guidewire Marketplace, or Claims Workspace" (FAQ). No API endpoints, formats or authentication on any page read. | Product docs; platform page |
| Redistribution, display, storage, export | No terms of service or licence text on the pages read. The header "Sign In" links to cotality.com/customer-sign-in, which was not read. The hero "Login" link points to "#". | Products page; platform page |
| Public price | No public price found. "Volume discounts available" (product docs). Calls to action are "Request a demo" and "Schedule a demo." The region switcher refers to "pricing specific to your location." | Product docs; platform page; marketing page |
| Documented limits | Hail sizes are "approximate." No accuracy figure for hail or wind on the pages read. | Products page |
| Intended users | Adjusters and insurers ("adjusters can connect" via the FAQ); "Used by most major insurance carriers" (**claim**, no carriers named). Roofers and contractors are not named. | Platform page; product docs |

Vendor claims (not tested). Each is a **claim** from the pages named; none cites a study or method unless stated:
- "We set the industry standard for hail reporting backed by forensic and Level 2 Radar data." (product docs)
- "Used by most major insurance carriers." (product docs)
- Cotality says its algorithms use the actual storm path rather than a predicted one. No benchmark is cited. (product docs)
- The platform "allows insurers to identify fraudulent claims without question." No evidence is given. (product docs)
- "forensic-grade verification reports that far exceed the limitations of free public data." (platform FAQ)
- "This high level of accuracy protects operational integrity and reduces guesswork." No metrics are given. (platform FAQ)
- "over 99% accuracy" for STRIKEnet, in confirming lightning "at or near the insured address." No method is cited. (marketing page)
- Wind report: "Verify if damaging winds caused the loss." FAQ: the product helps with "distinguishing new damage from pre-existing conditions." These are damage and cause statements. Under AGENTS.md rule 5 this app does not repeat them, and it does not adopt the vendor's "confirm" wording as an evidence label.

Gaps in the pages read: no API documentation, no event finalization or revision policy, no accuracy method, no history span, no terms, no price.

## 6. Procurement questions

The review's procurement questions, one row per question, one column per provider. Answers are left blank: nothing was answered from the pages read. Fill each cell from the vendor's written answer, with its date. Review wording: "For each product request documented region/period coverage, native resolution, upstream sources, probability/size meaning, validation methods, latency distribution, revisions and as-of archive access. Confirm multi-company display, homeowner exports, storage/retention, AI use, contract-end access, per-unit charges and trial datasets."

| # | Question | NOAA | Xweather | HailZone | Verisk | Cotality |
|---|---|---|---|---|---|---|
| 1 | Region and period coverage documented for the product requested | ________ | ________ | ________ | ________ | ________ |
| 2 | Native resolution, spatial and temporal | ________ | ________ | ________ | ________ | ________ |
| 3 | Upstream sources | ________ | ________ | ________ | ________ | ________ |
| 4 | What the probability or size value means (event, window, distance) | ________ | ________ | ________ | ________ | ________ |
| 5 | Validation methods, and who ran them | ________ | ________ | ________ | ________ | ________ |
| 6 | Latency distribution, event to delivery (p50 and p95) | ________ | ________ | ________ | ________ | ________ |
| 7 | Revisions: preliminary or final; how and when values change | ________ | ________ | ________ | ________ | ________ |
| 8 | As-of archive access: the value delivered at an earlier time | ________ | ________ | ________ | ________ | ________ |
| 9 | Multi-company display | ________ | ________ | ________ | ________ | ________ |
| 10 | Homeowner exports | ________ | ________ | ________ | ________ | ________ |
| 11 | Storage and retention | ________ | ________ | ________ | ________ | ________ |
| 12 | AI use of the data | ________ | ________ | ________ | ________ | ________ |
| 13 | Contract-end access | ________ | ________ | ________ | ________ | ________ |
| 14 | Per-unit charges, each billable unit and multiplier | ________ | ________ | ________ | ________ | ________ |
| 15 | Trial datasets | ________ | ________ | ________ | ________ | ________ |

Review's key unresolved question for each provider is in its section above (sections 1 to 5). For NOAA, the NWS disclaimer says web page information "may be used without charge"; no charge for the API, MRMS or SPC products is stated on the pages read, so confirm the answer in writing.

## 7. Not verified

### Pages not read, or read only in part

- NCEI Storm Events Database: both attempts failed on 2026-10-16. Coverage years, hail records, publication lag, file formats, terms and price are unknown.
- MRMS file access routes and latency. The UCAR README for MRMS MESH is a JavaScript-only page; no text was read.
- The MESH size equation: the VLab page shows it as an image that the text read did not include.
- NSSL hail detection page: used only for detection context; it has no MESH definition.
- Xweather pages linked but not read: Authentication, Rate Limiting, Cost Headers, Terms & Conditions, Attribution Guide, Data Sources, Supported Languages, Changelog, Xweather Protect, and the subscription pages outside the US and Canada.
- Xweather's 170-event validation study (the "Read the study" link was not followed) and the AXIS Capital figures (not checked).
- HailZone: authentication, rate limits, terms, upstream sources for product 326, forecast validation, and any change to the Beta status.
- Verisk: the storefront (robots rules block it), Verisk's terms, the Respond product, and any current API documentation (none found in search or the pages read).
- Cotality: the sign-in and Claims Workspace pages, any login-gated documentation, terms of service, and the FAQ beyond the summary read.
- D23's NWS facts: the 30-second alert polling limit is not verified. The 7-day alert history and the 20-minute observation lag are verified on the NWS API page. The 7-metre /points quantization is not in the NWS geolocation guide read.

### Not established by any page read

- Accuracy, skill or validation for any product. Every accuracy statement here is a vendor claim.
- Latency distributions for any product.
- Revision and correction history for any product.
- Redistribution, display, storage, export and AI-use rights for a roofing company's use. Only the NWS disclaimer, the MRMS software licence and the Verisk sample disclaimers state any such terms, and none of them is a contract.
- Prices: none found for HailZone; none published for Verisk hail, wind or lightning reports or for Cotality; none published for Xweather enterprise plans or add-ons. Whether Xweather hail products count toward the free allowance is not stated.
- Whether any product covers Montana specifically. The pages state continental U.S., CONUS or U.S. coverage.
- Whether any candidate serves roofing contractors. The Verisk and Cotality pages name insurers; Xweather names insurance and risk, and solar.
- Whether the Verisk sample reflects a real report.
- Whether any candidate performs better than the NOAA baseline on any task. The review's evaluation (Next 4) has not been run, and this page makes no comparison.
