# User-added weather services

The user identified AccuWeather, Weather by WindBorne, Zoom Radar Weather and Tomorrow.io as available plugins. The callable tool catalog was rechecked for version 0.3.0 and contains none of these services and no connector-search tool. They have not been queried, tested or compared. Do not infer their exact products, subscriptions, geography, radar capabilities or independent data ownership from their names.

When tools become available, inspect each tool schema and provider documentation before use. For the same location and analysis time record:

| Check | Required evidence |
|---|---|
| Capability | Actual callable product/endpoint and requested decision |
| Provenance | Original observing system/model and provider transformations |
| Time | Observation, issue/run, valid interval, receipt, revisions and delay |
| Geography | Coverage, grid/object geometry, resolution and missing masks |
| Meaning | Units, thresholds, estimated/observed/forecast status, probability definitions |
| Quality | Known artifacts, uncertainty, stale/missing behavior, flags |
| Access/rights | Actual returned access/entitlements plus attribution/display/export terms |
| Comparison | Time/space-aligned evidence with conflicts retained and upstream duplicates identified |

Official NWS warnings remain independently checked and attributed. A commercial provider's warning copy is not automatically a second source. Forecast agreement does not validate observed radar, and product agreement cannot establish damage. Never declare one provider most accurate from a single scene or marketing descriptions. Compare retrospective and prospective performance using the evaluation protocol.

Tool access enables retrieval; it does not make a provider an independent reviewer or certify this procedure. Do not install unrelated plugins or ask for secret values in chat to compensate for missing tool exposure.

For point queries, compare the same coordinate, elevation context, quantity, statistic, valid interval and as-of cutoff. If one provider returns a nearby station, another a grid estimate and another a forecast, retain those labels rather than averaging the values. Preserve vendor-supplied location and footprint instead of replacing them with the user's pin. Query success does not establish parcel-scale accuracy. Historical evaluation must separate data available at the time from later corrections and reanalysis.
