# Montana and Kansas City live-map pilot

This package contains a working local NWS-backed map prototype and an integration plan for Claude. It extends the [radar and point-weather skill](../../skills/roofing-radar-reading/SKILL.md). It has not been deployed publicly or merged into Claude's application.

The pilot defaults to a statewide **Montana** view with a Billings sample pin at **45.7833, -108.5007** and 13 town presets. Select Kansas City in the territory control or use `?region=kansas-city` to return to **39.0997, -94.5786**. These are public sample coordinates, not particular roofs or instrument sites. The selected pin remains distinct from nearby station locations and forecast grid geometry. See the [Montana implementation and results](MONTANA.md).

## Working now

- Clickable Leaflet map with locally bundled U.S. state outlines, Montana town presets, territory selection and manual latitude/longitude input.
- Real NWS nearby observations, hourly forecasts and independently retrieved official point alerts.
- Source timestamps, station distances, native units, quality flags, stale/missing/error states and disclosed NWS coordinate quantization.
- Exact-point saved query snapshots in a local SQLite archive.
- Browser polling while the page is open: conditions every five minutes, alerts every 60 seconds. There is no unattended collector.

Street tiles are optional and were blocked in this environment. The bundled outline is geographic context, not a rooftop/street basemap. Weather radar, hail estimates, lightning detections, historical backfill and the four commercial providers are not connected. A moving map or a successful request is not proof of meteorological accuracy.

## Run

Requires Python 3.12 or compatible Python 3 standard library. Runtime JS/map assets are bundled with licenses; no pip/npm installation or provider key is required for the NWS baseline.

```sh
# From the repository root:
cd research/live-map/prototype
python3 -B server.py --port 8765
```

The server binds to loopback by default and has no authentication, tenant isolation, deployment service or production request budget. Use the printed address in a normal local browser when running outside the onboarding UI. Do not expose it publicly as a production service. Stop/restart only the process you started; a running process is not retained by an environment snapshot.

The archive defaults to `prototype/.local/state`, which Git ignores. Use `--archive-dir` to select another writable directory.

The default age policies (30-minute observations and 12-hour forecast update age) are explicit **prototype policies**, not validated limits for storm or work decisions. Use the CLI flags to change them only with documented product/decision criteria. The frontend shows numbers for V-coded station quantities only; other QC flags require review, and source-X values are withheld while retained in raw evidence. This conservative policy does not independently verify a sensor or establish roof-level conditions.

## Validate

```sh
# From the repository root:
cd research/live-map/prototype
python3 -B -m unittest discover -s tests -v
```

Optional browser checks require Python Playwright, Chromium and a running prototype with NWS access. The captured Kansas City fixture is bundled in `validation-evidence`; generated results default to the ignored `prototype/.local/browser-checks` directory. From the prototype directory:

```sh
python3 -m pip install playwright
python3 -m playwright install chromium
python3 -B tests/browser_check.py
```

An existing browser can be selected with `--chromium /path/to/chromium` instead of installing Playwright's browser. `--base-url`, `--fixture` and `--output-dir` override the service, fixture and output locations. The tests separate the real integration display from synthetic failure/race scenarios. These are development checks, not a performance benchmark.

The [original Kansas City validation record](VALIDATION.md) documents the initial checks. The [Montana validation](MONTANA.md) records the current 21 backend tests, 10 Montana and seven Kansas City browser checks, plus a 16-point source sweep. History is labeled **Saved query snapshots**: it starts when this prototype queries a location and does not reconstruct earlier weather. The archive currently stores normalized returned evidence, not a complete provider raw-data or warning-revision archive; production collection is specified separately.

## Route to measurable accuracy

1. Preserve this NWS baseline and independent alerts while adding verified source adapters.
2. Obtain actual callable access or documented server APIs for [Tomorrow.io/AccuWeather](tomorrow-accuweather.md) and [WindBorne/ZoomRadar](windborne-zoomradar.md). Confirm products, timestamps, coverage, numerical point access, imagery, history and display/storage rights. Chat-plugin entitlement does not establish app API rights.
3. Preselect Kansas City and Montana test sites and independent instruments/reports, with site location, exposure and averaging periods documented. Collect quiet periods, storms, gaps and failures before choosing a winner.
4. Compare each variable and forecast lead separately against independent observations. Freeze selection/calibration before held-out evaluation; do not blindly average correlated feeds or choose whichever predicts the largest hazard.
5. Add a supported street/radar layer, durable background collection and a verified historical source, then production hosting/authentication and operational monitoring. Expand regions only after appropriate evaluation.

See [service-design.md](service-design.md) for interfaces and [the evaluation protocol](../../skills/roofing-radar-reading/references/evaluation-protocol.md) for proof requirements. Exact query coordinates cannot eliminate station/grid/radar sampling uncertainty.
