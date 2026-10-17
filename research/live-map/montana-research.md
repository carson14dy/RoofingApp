# Montana companion research

Prepared October 11, 2026. Scope: extend the pilot's selectable geography across Montana while preserving source limitations. Statewide map selection does not demonstrate statewide observation coverage, radar coverage or forecast accuracy. No commercial connector is callable in this session. This research did not query point weather; the separate live point sweep must supply those results.

## What, where, when, how and why

**What:** Current mode can present available nearby station observations; forecast mode can present the returned NWS grid forecast and independent official point alerts. Past mode remains **saved query snapshots**, beginning when that exact location is queried. It is not historical backfill, a continuous archive or proof that a location had no earlier storm. Selected official event summaries and station climate records can guide later historical research, with their own scope and gaps.

**Where:** Discover office/grid/station links through NWS `/points` for each selected coordinate. Do not assign jurisdiction by nearest city, radar or a hand-drawn office boundary. The four retrieved Montana office homepages identify Missoula, Great Falls, Billings and Glasgow resources; they do not verify which office serves each pin. Preserve source grid geometry, station distance/elevation and missingness. A nearby airport in a valley may poorly represent a pass, ridge or neighboring basin.

**When:** Retain source observation/forecast-update time, valid interval, retrieval time and revisions separately; use the timezone returned for the location. Recheck severe hazards when new evidence arrives, rather than treating successful retrieval as fresh data. The linked Billings wind PDF fetched on October 11 carries an October 9 issuance: its successful HTTP response does not establish current wind conditions.

**How:** Keep official alerts independent of station/forecast failures. Apply deterministic coordinate, unit, time and quality checks. Present source values with their evidence type; do not interpolate station conditions into invented roof measurements. The prototype's nearest-three-stations and age policies are implementation choices needing Montana validation, not scientific guarantees.

**Why:** Terrain, elevation, sampling distance, differing forecast quantities and missing observations can dominate location-level error. A larger map requires a broader validation sample, not a stronger accuracy label.

## Montana interpretation checks

- **Radar, hail and rain:** Retrieved office pages link KMSX, KTFX, KBLX and KGGW radar resources. These links are not a low-level coverage assessment. Before interpreting a pin, evaluate beam height/range, terrain blockage, overshoot, radar status and neighboring sources using the radar skill. No terrain/beam-coverage calculation was completed here. NWS radar documentation distinguishes base reflectivity, maximum-in-volume composite reflectivity, radial velocity and algorithmic hydrometeor classes. None directly measures hail diameter or rain at a roof. Treat MESH as an estimate, align rain accumulation intervals and preserve missing coverage. Rural absence of hail reports is not a valid negative observation.
- **Wind:** Compare exposure, station height, averaging period, gust definition, elevation and terrain setting. Livingston/Big Timber/Harlowton gap-wind products warrant targeted validation; no current gust or universal roofing-work limit is inferred from them. Radar radial velocity is not rooftop wind. A road crosswind product does not certify roof-work conditions.
- **Snow and ice:** Separate snowfall depth, liquid equivalent, blowing snow, ice accretion and substrate frost. A valley temperature or precipitation icon cannot establish pass conditions or roof icing. Use current winter warnings, forecast uncertainty and onsite observations; do not turn a rain/snow forecast into structural roof-load or safe-travel advice. The Great Falls winter page was discoverable, but its dynamic forecast values were not validated here.
- **Fire and smoke:** Fire-weather conditions/Red Flag Warnings are distinct from ignition, active perimeter and evacuation instructions. The regional fire page returned HTTP 200 while reporting a data-provider technical problem. The Missoula-linked Boise smoke page explicitly calls its forecast experimental, potentially unavailable and not an official air-quality forecast. Total-column smoke and surface smoke are different quantities; neither is automatically measured surface PM2.5 or AQI. Montana DEQ/AirNow observations and official advisories need separate verified access; DEQ retrieval failed here.
- **Flooding and roof conditions:** Upstream precipitation, snowmelt, ice jams, drainage and antecedent conditions matter. A dry job-point radar view does not establish absence of downstream flooding. Snow/rain ending does not establish a dry or ice-free roof. Apply material/system requirements and onsite checks.

These are interpretation requirements, not newly validated Montana hazard algorithms.

## Representative validation matrix

Public localities below are proposed test strata, not confirmed station/grid assignments. Verify actual coordinates, jurisdiction, elevation and source availability during the point sweep.

| Stratum / examples | How and why to challenge the reading |
|---|---|
| Urban valleys: Missoula, Kalispell | Compare urban pin and available stations; test valley/ridge mismatch, inversion/smoke limitations, gaps and frozen precipitation. |
| Central communities: Great Falls, Helena, Bozeman | Test forecast-grid/elevation changes, strong wind, temperature and precipitation phase across nearby terrain. |
| South-central: Billings, Livingston, Big Timber | Compare ordinary wind with gap-wind situations; retain distinct station, grid and specialized probability products. |
| Northern/eastern plains: Glasgow, Havre, Glendive, Miles City | Test longer station distances, sparse reports, wind/hail/rain variability, winter outages and missing quantitative fields. |
| Rural basins/front: Libby, Seeley Lake, Browning | Challenge nearest-station representativeness and radar assumptions; preserve unavailable status rather than importing distant conditions. |
| Mountain and edge cases: Rogers Pass, Lookout Pass, Beartooth Pass; state-border points | Verify the exact side/elevation and `/points` result, missing/stale observations, snow/ice differences and correct state/office boundary behavior. Do not equate the pass name with one precise sampling point. |

For each case retain station distances/elevations, forecast grid, source times, quality, missing fields, point-alert result and archive behavior. Include quiet weather, actual storms, freezing transitions, outages and changing locations. Later compare forecasts by hazard/lead and terrain against independent QC'd observations, accounting for spatial mismatch; report misses, false alarms, bias/error and unobserved cases separately.

## Source retrieval and review record

Normal HTTPS/TLS was used. Times below are UTC on **2026-10-11**; entries indicate request start, not observation time. Relevant page text/links were read; dynamic map data were not verified.

| Official source | Time; result; what was established |
|---|---|
| [Missoula](https://www.weather.gov/mso/), [Great Falls](https://www.weather.gov/tfx/), [Billings](https://www.weather.gov/byz/), [Glasgow](https://www.weather.gov/ggw/) | 19:29:18; all HTTP 200. Office identities and linked radar/winter/fire/climate resources. No jurisdiction or live-hazard conclusion. |
| [NWS radar FAQ](https://www.weather.gov/radarfaq) | 19:29:52; HTTP 200. Product definitions and radar-status/display discussion reviewed; not Montana beam-coverage certification. |
| [Great Falls winter](https://www.weather.gov/tfx/winter) | 19:29:52; HTTP 200. Winter-resource page and links read; dynamic forecast values not established. |
| [Billings crosswinds](https://www.weather.gov/byz/highway_crosswinds) and [linked wind PDF](https://www.weather.gov/media/byz/DSSBuilder/GapWindProbabilities.pdf) | 19:29:52 and 19:30:38; HTTP 200. PDF fully retrieved, text extraction succeeded; charts carry October 9 issuance. No current-wind conclusion adopted. |
| [Regional fire page, Missoula selection](https://www.weather.gov/wrh/fire?wfo=mso) | 19:29:52; HTTP 200 with a visible data-provider technical-issue message. Read point/zone instructions, not functioning live fire data. |
| [Missoula-linked Boise smoke page](https://www.weather.gov/boi/smoke) | 19:29:52; HTTP 200. Experimental/non-official-AQI limitations and surface/total smoke distinction read. No Montana smoke observation retrieved. |
| [Billings event summaries](https://www.weather.gov/byz/eventsummaries), [Missoula climate](https://www.weather.gov/mso/climate) | 19:29:52; HTTP 200. Selected-event scope and location-based climate access reviewed. Climate page includes older normals; neither page supplies complete parcel history. |
| [JetStream radar FAQ](https://www.weather.gov/jetstream/radarfaq), [Montana DEQ smoke](https://deq.mt.gov/air/Programs/smokeforecast) | 19:29:18 and 19:30:38; CONNECT 403. No content read. |

Unsuccessful discovery paths: `https://www.weather.gov/mso/radar` and `https://www.weather.gov/tfx/mountains` returned HTTP 404 at 19:29:18; `https://www.weather.gov/safety/winter-science` and `https://www.weather.gov/safety/fire` returned HTTP 404 at 19:30:38. No claims derive from these failures. Temporary captures and request records are in `/tmp/roofing-montana-sources`; they are not a persistent weather archive.

## Staged follow-up

1. Complete representative real point queries and interface/history-isolation checks; publish dated availability results without extrapolating to every Montana pin.
2. Test outages, freshness, nearest-station limitations, boundary/elevation cases and warning preservation. Preserve explicit unavailable states for radar, hail, smoke and historical backfill until connected.
3. Obtain verified source contracts and appropriate archive rights; add independent observation/forecast evaluation across the strata and seasons above.
4. Run prospective shadow evaluation and qualified meteorological review before offering accuracy claims or public-reporting assurances.
