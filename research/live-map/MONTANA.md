# Montana weather-map pilot

Implemented October 11, 2026, on top of the Kansas City pilot. This is a shared local service and Claude integration handoff, not a deployed statewide monitoring network.

## What works

The default map fits and highlights Montana, with **13 public town sample pins**: Billings, Missoula, Kalispell, Great Falls, Helena, Bozeman, Butte, Havre, Lewistown, Glasgow, Miles City, Glendive and West Yellowstone. Choose a town, click the map or enter precise coordinates. The **View territory** button returns to the statewide view without changing the selected coordinate. Kansas City remains available through the territory selector or `?region=kansas-city`.

Current evidence, hourly forecasts, independent official alerts and saved query history use the selected coordinate. The statewide view is navigation: it does not display every active Montana warning or establish statewide weather coverage. The town pins are illustrative navigation samples, not surveyed roofs or instruments.

Station elevation and forecast-grid elevation are displayed separately. Site/roof elevation, terrain exposure and station representativeness remain unknown. No elevation, rooftop wind or terrain correction is applied. Precipitation probability wording includes liquid-equivalent frozen precipitation. NWS point metadata supplies the timezone; known sample locations have a regional fallback, while unknown custom-location timezones fall back to UTC. Official alert times remain explicitly UTC.

## Actual source checks

A sweep on October 11 at **2:32 p.m. CDT / 1:32 p.m. MDT** queried 16 sample coordinates: the 13 town presets and three additional divide-area, rural and northern-border points. All 16 returned point metadata, three station records, 156 hourly forecast periods and successful independent official-alert requests. All 16 saved snapshots were retrieved for their exact original coordinates. Source metadata returned America/Denver and the office assignments below; no office boundary was guessed from the map.

These are dated integration results, not continuing weather statements. **35 of 48 station records exceeded the illustrative 30-minute observation age limit**; four sample queries had no station record within that limit. Some records are repeated stations across queries, not 48 independent instruments. Missing gust/precipitation values remain missing, and non-V station quantities remain withheld from normal numeric display under the existing prototype policy. Successful retrieval does not imply fresh, representative or complete observations.

| Sample coordinate | Returned office | Nearest returned station (km) | Stations within the prototype age limit |
|---|---|---:|---:|
| Billings (45.7833, -108.5007) | BYZ | 2.934 | 1/3 |
| Missoula (46.8721, -113.994) | MSO | 8.430 | 1/3 |
| Kalispell (48.19199, -114.31681) | MSO | 12.726 | 2/3 |
| Great Falls (47.5053, -111.3008) | TFX | 5.912 | 1/3 |
| Helena (46.5891, -112.0391) | TFX | 3.224 | 1/3 |
| Bozeman (45.677, -111.0429) | TFX | 14.152 | 1/3 |
| Butte (46.0038, -112.5348) | MSO | 6.559 | 1/3 |
| Havre (48.55, -109.6841) | TFX | 6.323 | 1/3 |
| Lewistown (47.0625, -109.4282) | TFX | 12.886 | 0/3 |
| Glasgow (48.19696, -106.6367) | GGW | 2.845 | 0/3 |
| Miles City (46.4083, -105.8406) | BYZ | 3.302 | 1/3 |
| Glendive (47.1053, -104.7125) | GGW | 7.168 | 1/3 |
| West Yellowstone (44.6621, -111.1041) | TFX | 30.171 | 0/3 |
| Divide-area sample (46.58, -112.3) | TFX | 23.032 | 1/3 |
| Rural eastern sample (47.25, -106.5) | GGW | 33.629 | 0/3 |
| Northern border sample (48.99, -111.96) | TFX | 3.641 | 1/3 |

The nearest returned station for West Yellowstone was 30.171 km away; for the rural eastern sample, 33.629 km. Nearest means nearest among the NWS-returned station list, not a validated site-representativeness ranking. Alert collections at some samples contained messages; see the captured timestamps and evidence rather than treating these results as a current warning inventory.

The [live sweep](validation-evidence/montana/live-sweep.json) retains query/source times, URLs, grids, station locations/elevations/distances, quality-related field availability and archive results. The [Billings capture](validation-evidence/montana/billings-point.json) preserves one full response. Other full sample responses remain local development evidence. The screenshot records one later Billings browser query; it is not a map of actual weather across the state.

## Executed checks and independent review

- **21 backend tests passed**, including zero-distance/elevation uncertainty, source-provided Montana office/timezone metadata, and separate alert/history queries for very close pins sharing one rounded NWS point lookup.
- **35 synthetic weather-evidence contract tests passed**; these test metadata rules, not meteorological prediction.
- **10 Montana browser checks passed**: real Billings display/statewide extent, evidence scope/elevations, real Missoula selection/Mountain Time, mobile layout, stale/missing values, delayed cross-region warning handling, independent warnings during weather-source failure, custom-coordinate precision/UTC fallback, territory-view pin preservation and actual map-click selection.
- **Seven Kansas City browser regression checks passed**. Both browser runs recorded zero JavaScript errors. Failure/race cases use explicitly synthetic responses; synthetic clocks are tied to fixture dates.

Separate agents researched Montana official sources, implemented the frontend, extended backend evidence/tests and independently challenged claims and region-switch behavior. The reviewer checked source caveats against captured official text, including a fire-data outage message and an older wind-PDF issuance. Their agreement is not independent weather measurement or meteorologist certification.

## Run and repeat

Follow the shared [setup instructions](README.md). Starting the service opens Montana by default; the Kansas City route remains supported. No additional runtime packages or commercial keys are needed beyond the NWS baseline.

From `research/live-map/prototype`, with a running service:

```sh
python3 -B -m unittest discover -s tests -v
python3 -B tests/check_points.py --points ../validation-evidence/montana/sample-points.json --output-dir .local/montana-sweep
python3 -B tests/browser_montana.py
python3 -B tests/browser_check.py
```

The browser checks require Playwright and Chromium as described in the shared README. `--chromium`, `--base-url` and `--output-dir` allow local overrides. The point sweep uses two concurrent sample queries, does not retry failed captures, preserves per-source failures, and requires a new output directory for each run to avoid replacing evidence. Exit zero means captures/checks completed, not that every source was available or weather was accurate.

## Limits and next accuracy work

The [Montana research](montana-research.md) and [Montana reading procedure](../../skills/roofing-radar-reading/references/montana.md) cover radar beam/terrain limits, hail/rain, gap winds, snow/ice, fire/smoke, flooding and incomplete history. Current official sources were read; no radar interpretation or full terrain-coverage model was executed.

The four commercial weather plugins remain unavailable as callable tools. Live radar/hail/lightning/smoke layers, verified street/parcel basemaps, earlier historical weather, a continuous collector and production hosting are not connected. Saved history begins when this prototype queries each exact location; extending the map does not backfill Montana storm history.

Before making accuracy claims, instrument independent urban/valley/pass/plains/rural sites, verify siting/exposure and product definitions, collect quiet/storm/outage cases through seasonal changes, and score each variable and forecast lead on held-out events/sites. A successful 16-point sweep does not establish exact roof weather or statewide/nationwide broadcast readiness.
