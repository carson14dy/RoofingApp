# Montana point-weather procedure

Version 0.4.0 — October 11, 2026. Apply the general point-weather contract and independent official warnings. The [Montana research and source record](../../../research/live-map/montana-research.md) supplies freshly reviewed NWS references; the [pilot results](../../../research/live-map/MONTANA.md) distinguish executed integration checks from proposed accuracy evaluation.

## Before interpreting a Montana pin

1. Preserve exact requested coordinates. Resolve NWS office, grid and timezone from the returned point metadata, rather than a city label or nearest radar. Town presets are navigation samples, not a geocoded property or sensor. The statewide outline supplies context; the alert query covers the selected point.
2. Identify the evidence footprint. Retain station coordinates, distance, elevation, observation time, field quality and units. Station elevation, forecast-grid elevation and selected-site elevation are different quantities. Without a site survey or verified elevation source, site elevation and terrain/exposure comparisons remain unknown. Even a zero-distance station is not proof of roof conditions.
3. Compare valleys, ridges, passes, basins and plains where that information is established. Do not infer terrain representativeness from shortest distance. Do not apply an unvalidated lapse-rate, wind-height, rain/snow or roof-load correction. A fresh temperature does not make missing wind, gust or precipitation measurements available.
4. For radar interpretation, check the selected product's beam height, range, terrain blockage, overshoot, source age and coverage. Radar links on four office pages do not establish complete Montana coverage. No radar layer or terrain-aware radar calculation is connected in this pilot.
5. Preserve forecast interval and phase. Probability of precipitation includes measurable liquid equivalent; it is not specifically rain probability, expected duration, snowfall depth or hail probability. Snow depth, liquid precipitation, ice accretion, surface frost and structural snow load need distinct evidence.
6. Interpret wind with siting and averaging definitions. Gap-wind guidance, radial velocity, airport gusts and roof exposure are distinct. Fire-weather warnings do not identify ignition or evacuation zones. Experimental surface/column smoke forecasts do not establish measured AQI.
7. Inspect source issue time and availability within the response. A successfully downloaded old wind chart or a fire page reporting a provider outage supplies no verified current conditions. Keep official warning retrieval independent of these failures.
8. For history, state the exact-point collection start and gaps. Locally saved queries, selected NWS event summaries and station climate statistics do not reconstruct all earlier weather at a roof. Absence of a rural hail report is unknown ground truth, not a no-hail observation.

## Accuracy evaluation still required

Stratify independent reference sites across western valleys, the divide and high valleys, central communities, northern/eastern plains, rural areas and boundaries. Include quiet periods, severe storms, snow/ice transitions, smoke and outages over multiple seasons. Document actual instrument location, height, elevation, exposure, calibration and observation statistic before calling it a reference.

Score each weather variable and forecast lead separately, with site/event holdouts and explicit missingness. Evaluate warning applicability separately from forecast error. Avoid treating several vendors sharing an upstream model as independent confirmation. Town-query success demonstrates a working integration at those samples; it cannot establish statewide coverage, exact roof weather or readiness for public broadcast.
