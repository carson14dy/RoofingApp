export const meta = {
  name: 'globe-prototype',
  description: 'Build the globe prototype: Cesium page with GIBS/USGS/alerts, MRMS 3D volume script, GOES cloud-top script, 3D storms layer, real-browser checks',
  phases: [
    { title: 'Build', detail: 'globe page, MRMS volume, GOES cloud height (parallel)' },
    { title: 'Volume layer', detail: '3D storms on the globe page + browser pixel check' },
    { title: 'Integrate', detail: 'run every test, size and hygiene checks' },
  ],
}

const REPO = '/home/user/RoofingApp'
const PROTO = REPO + '/research/globe/prototype'
const EVID = REPO + '/research/globe/validation-evidence/'
const SCRATCH = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad'

const CTX = `You are one of several agents building the "globe view" research prototype for RoofingApp, a Montana roofing company's weather desktop app. A supervisor reads your output; it is data, not prose for a person.

Repo: ${REPO}. Read first: ${REPO}/research/globe/README.md sections 1-7 (the plan; the prototype is Phase 0, outside the app), and the evidence files named in your task under ${EVID} (facts verified live by earlier agents; a "review" key, where present, holds the refuter's corrections and wins over "facts").

Rules that bind you (from AGENTS.md):
- Rule 5 (evidence honesty): satellite imagery is an observation; cloud-top height is a satellite estimate; reflectivity and MESH are radar estimates. Never "hail" on a reflectivity legend (dBZ = radar echo strength), never "confirmed damage", never an all-clear from missing data. No echo is not clear; MRMS codes -99 and -999 are both "no radar data" until their meanings are verified (they are not yet).
- Rule 7: before building on a request, make it live and check the content; record what you checked.
- Rule 8: UI is verified in a real browser with pixel checks, not string checks on HTML.
- Rule 9: no "best" claims.
- Python first: all data fetching, time logic, geometry, cropping, thresholds and freshness states live in Python and are served as JSON; the browser JavaScript only draws what it is given and handles browser-only events. Document every JavaScript section with a comment saying what it does and why it must run in the browser.

Working rules:
- Today is 2026-10-17 (UTC). Outbound HTTPS works through a preconfigured proxy (Python requests/urllib and curl honour it). pip install works; eccodes 2.50 is already installed in the system Python; check netCDF4 before installing. Playwright: a scratch venv and the working launch recipe (executable_path to the pre-installed Chromium, headless, no extra flags) are described in ${EVID}webgl-runtime.json under "recipe"; reuse that venv if it still exists, else create your own venv under ${SCRATCH}/venv-pw with "pip install playwright pillow" and never run "playwright install". Never add anything to requirements.txt.
- Downloads go to a fresh directory under ${SCRATCH}/globe-dl/<your-slug>/ and are never committed. Run scripts that read downloaded files with "python -I".
- Write ONLY under ${PROTO}/ (your named files) and the one evidence file your task names under ${EVID} (JSON, at most 25 KB) plus, for browser tasks, one screenshot PNG under ${EVID} downscaled to at most 300 KB. Fixtures committed under ${PROTO}/fixtures/ are at most 60 KB each and carry provenance (source URL, valid time, how they were cut). Do not touch ${PROTO}/parallax.py or ${PROTO}/tests/test_parallax.py except to import them. Do not modify payload/, desktop/, tests/, docs/ or the README.
- Never write model names or AI-vendor identifiers into any file.
- Montana + border bounding box for crops: lon -116.8 to -103.3, lat 43.6 to 49.75. Places fixture: Billings 45.7833,-108.5007; Great Falls 47.5053,-111.3008; Missoula 46.8721,-113.9940; Glasgow 48.1970,-106.6350; Miles City 46.4083,-105.8406.
- Tests are unittest, offline (synthetic data), discoverable with: cd ${PROTO} && python -m unittest discover -s tests. Network-using checks are separate scripts or tests that skip cleanly when the network or browser is unavailable.
- Your final output is data for the supervisor: files written, what works, what failed (with the exact error), test commands and their results, measurements with units.`

const PROTO_SCHEMA = {
  type: 'object',
  properties: {
    slug: { type: 'string' },
    files_written: { type: 'array', items: { type: 'string' } },
    what_works: { type: 'array', items: { type: 'string' } },
    what_failed: { type: 'array', items: { type: 'string' } },
    tests: { type: 'array', items: { type: 'object', properties: { command: { type: 'string' }, result: { type: 'string' } }, required: ['command', 'result'] } },
    measurements: { type: 'array', items: { type: 'string' } },
    evidence_file: { type: 'string' },
    notes_for_supervisor: { type: 'array', items: { type: 'string' } },
  },
  required: ['slug', 'files_written', 'what_works', 'what_failed', 'tests', 'measurements', 'evidence_file'],
}

const P1 = `# Task P1 — the globe page (slug: globe-page)
Read ${EVID}gibs.json (tile template, layer names, time format, 10-min period, ~40-min latency, 404 on missing times, CORS *), ${EVID}webgl-runtime.json (browser recipe), ${EVID}radar-tiles.json (how the app's NWS radar MapServer export and valid time work), ${EVID}parallax.json (the "wording" for the uncorrected-cloud legend), ${EVID}app-integration.json (the flat map's layer/freshness pattern to mirror), and ${REPO}/payload/templates/base.html (:root colour tokens for the dark "storm" look — reuse the token names and values).

Build, under ${PROTO}/:
1. serve.py — standard library only (http.server + urllib). Serves the static page and these JSON endpoints, all computed in Python:
   - /api/layers.json: the layer list. For each layer: id, name, kind (base map | observation | satellite estimate | radar estimate | official alert | places), source name and URL, valid_time_utc, retrieved_time_utc, state (live | stale | unavailable | off) with the limit used (propose: GOES 15 min, radar 15 min, alerts 10 min, imagery daily; say these are proposals, not D12), legend text, and the provider tile template the browser should use. The GOES layer's valid time comes from Python probing GIBS for the newest available 10-minute frame (walk back from now in 10-min steps until a tile at zoom 3 over Montana returns 200; cap at 12 steps; record the frame time and the latency).
   - /api/alerts.json: NWS active alerts for area=MT fetched server-side with a User-Agent header (NWS requires one; use "RoofingApp-globe-prototype (research)"), as GeoJSON features with properties event, headline, severity, onset, ends, sent, and a flag geometry_source = "polygon" | "zone" | "none". For alerts with null geometry, resolve their UGC zone/county codes to outlines through https://api.weather.gov/zones/{type}/{id} (cap 20 fetches per request, cache in memory, mark geometry_source "zone"); when no outline is available, emit a point feature at the zone's centroid if known else no geometry, with geometry_source "none" and text "zone match, outline not loaded" — never drop the alert.
   - /api/places.json: the places fixture above.
   - /api/radar.json: the NWS radar MapServer export URL for the Montana box plus its valid time, fetched the way the app does (see radar-tiles.json / payload/weather.py; read-only).
   - Use --offline to serve with no network: every live layer then reports state "off" with the text "Live feeds are off" (mirroring the app's self-test state), and the page must still render the base layers it can and the layer panel.
   - Port from --port (default 0 = pick free) printed on stdout as "PORT=<n>".
2. index.html + globe.js + globe.css — CesiumJS from cdnjs: fetch https://api.cdnjs.com/libraries/cesium?fields=version to pin the current version, load Build/Cesium/Cesium.js and Widgets/widgets.css with that exact version, set window.CESIUM_BASE_URL accordingly, and include an integrity attribute computed from the fetched file (sha384, base64) with crossorigin="anonymous". No Cesium ion token: Viewer with baseLayerPicker:false, geocoder:false, animation:false, timeline:false, terrain = EllipsoidTerrainProvider (document that terrain is a later phase), baseLayer = USGS imagery (https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}, Web Mercator, note CONUS-only) with NASA GIBS BlueMarble_ShadedRelief_Bathymetry underneath for low zoom. Layers from /api/layers.json: GOES-East GeoColor and Band 13 (GIBS WMTS, time from the API), NWS radar export image as a SingleTileImageryProvider over the Montana box, alerts as outlined polygons (no fill by severity, no extrusion) plus zone-match markers, places as labelled points (hover names). A layer panel (always visible, dark tokens) lists every layer with source, valid, retrieved and state; the GOES legend includes the uncorrected-parallax wording from parallax.json verbatim; a "3D view could not load" message appears when Cesium fails to load (test by blocking the CDN) and is separate from the layers' data states. The camera opens on the Montana box. Keep globe.js small and sectioned with comments: config from the API, imagery providers, alerts drawing, panel rendering, failure handling.
3. tests/test_globe_browser.py — unittest; skips (not fails) if Playwright or the Chromium binary is missing. It: starts serve.py on a free port; opens the page with the recipe; waits until Cesium reports globe.tilesLoaded or 45 s; takes a screenshot; downsizes a copy to at most 300 KB at ${EVID}globe-prototype.png; computes with PIL the fraction of non-black canvas pixels (assert > 0.2); toggles the GOES layer off through the panel and asserts the canvas pixels change; asserts the legend and parallax text are in the DOM; then reloads with the cdnjs route aborted and asserts the "3D view could not load" text appears while the layer panel still renders. Also tests/test_serve.py — offline unit tests for the layer-state logic (fresh/stale/unavailable/off from times) and the alerts geometry_source classification on fixture JSON (polygon, zone, none).
4. Run everything, fix until the browser test passes (or document exactly what fails). Write ${EVID}prototype-globe.json: files, Cesium version and integrity hash, which layers drew, GOES frame time and latency measured, alerts count by geometry_source at run time, canvas pixel stats, timings, test results, limits.`

const P2 = `# Task P2 — MRMS 3D volume script (slug: mrms-volume)
Read ${EVID}mrms.json fully (33 levels, file naming, 2-min cadence, 20-22 MB gz per step for all levels, grid 7000x3500 at 0.01 deg with first point 54.995 N / -129.995 E, the timestamp jitter across levels, the -99/-999 counts, the archived 2025-06-15 event scan with its peak step, and the eccodes keys used). eccodes 2.50 is installed in the system Python.

Build ${PROTO}/mrms_volume.py (numpy + eccodes + standard library; requests only if already importable) with a CLI:
  --time latest | YYYYMMDD-HHMMSS   (nearest-time join across levels, per the jitter fact)
  --levels all | a comma list of heights in km (default: 0.5,1,2,3,4,5,6,8,10,12,15)
  --bbox lon_min,lat_min,lon_max,lat_max (default the Montana + border box)
  --threshold 20 (dBZ)  --out volume.json  --synthetic (no network: a built-in storm-shaped test grid)
Behaviour: list the bucket for the chosen step (S3 REST list-type=2 on noaa-mrms-pds), download each level's grib2.gz into the download directory, gunzip, decode with eccodes, crop with index arithmetic from the grid facts (no full-grid lat/lon arrays), and write a compact JSON: {"product": "MergedReflectivityQC", "source": "noaa-mrms-pds", "valid_time_utc" per level and the join time, "retrieved_time_utc", "grid": {origin, dx, dy, nx, ny in the crop, "levels_km": [...]}, "threshold_dbz", "codes": {"-999": count, "-99": count, "valid": count} per level, "voxels": a flat list of [i, j, k, dbz_rounded_to_0.5] for cells >= threshold, "bytes_downloaded", "runtime_s", "notes": "radar estimate; -99 and -999 are no radar data (meanings unverified); no echo is not clear"}. Never emit a voxel for a sentinel cell. Print a summary line with counts, bytes downloaded, output bytes and runtime.
Tests ${PROTO}/tests/test_mrms_volume.py (offline, synthetic): crop indices correct against the grid formula (Billings index check from mrms.json), threshold count parity against numpy on the same array (the predeclared metric threshold_count_parity), sentinels never become voxels or 0 dBZ (no_data_rendered_as_echo_or_clear), nearest-time join picks the right files from a list of names with jitter, dBZ rounding, and the JSON schema keys exist.
Then run it for real: (a) --time latest for the Montana box at the default levels; (b) the archived day 2025-06-15 at the peak step mrms.json reports (or scan the hour around it at 6-step stride to find the step with the most >=35 dBZ cells) for the default levels and also for all 33 levels. Measure for each run: bytes downloaded, decode time, output JSON bytes at thresholds 20 and 35, voxel counts. Cut a committed sample ${PROTO}/fixtures/volume-2025-06-15-sample.json (at most 60 KB: the default levels, threshold 35, cropped to a 1.5 x 1.5 degree box around the strongest cell; provenance fields inside) and a synthetic fixture ${PROTO}/fixtures/volume-synthetic.json labelled "synthetic: not weather" (at most 20 KB) for browser tests. Write ${EVID}prototype-mrms.json with all measurements (units!), the step chosen, the peak counts, runtime, and the Montana -999/-99 shares per level at both steps.`

const P3 = `# Task P3 — GOES cloud-top-height crop script (slug: goes-cloud-height)
Read ${EVID}goes-aws.json fully, especially its "review" key (the refuter made nine corrections; trust the review over the facts) and ${EVID}parallax.json (the satellite longitudes were ASSUMED as -75.2 and -137.0; your script must read the real ones from the file attributes and your evidence file must report them).

Build ${PROTO}/goes_cloud_height.py (numpy + netCDF4 — pip install netCDF4 if "import netCDF4" fails — + standard library) with a CLI: --satellite east|west (noaa-goes19 | noaa-goes18), --product ACHAC (default) | CMIPC13, --time latest | YYYY-DDD-HH (day-of-year hour), --bbox (default the Montana + border box), --out height.png + height.json, --synthetic. Behaviour: list the bucket prefix ABI-L2-{product}/{year}/{doy}/{hour}/ via S3 REST, pick the newest file, download it, open with netCDF4, read the data variable (HT for ACHA; CMI for CMIP) with its scale/offset/fill/valid range and DQF, read goes_imager_projection attributes (longitude_of_projection_origin, perspective_point_height, semi_major_axis, semi_minor_axis, sweep_angle_axis) and the x/y scan angles, compute lat/lon of each pixel with the GOES fixed-grid equations (vectorised numpy; state the source equation in a docstring), resample nearest-neighbour onto a regular 0.02-degree lat/lon grid over the bbox (document that this is for a globe drape and that the pixel is 4-5 km across along the view tilt here), and write: a 16-bit PNG (height in metres, 0 = no data; or brightness temperature in 0.1 K for CMIP) and a JSON sidecar {source, bucket, object key, satellite longitude, perspective_point_height, units, scale/offset, fill, valid range, DQF shares (good vs flagged), time_coverage_start/end, bbox, grid dx/dy, height reference as stated in the file metadata or "unverified", percent valid in bbox, p10/p50/p90 heights, bytes downloaded, runtime_s, note "satellite estimate (retrieval), cloud top only, not cloud base"}. Never mix DQF-flagged pixels into the valid stats silently: report both.
Tests ${PROTO}/tests/test_goes_cloud_height.py (offline, synthetic): the fixed-grid lat/lon transform against a known pair (e.g. the sub-satellite point maps to (0, satellite longitude); a documented test pair from the GOES-R PUG if you can cite one), fill handling (fill never becomes 0 m), resampling keeps counts, PNG round-trips the heights, JSON keys present.
Run it for real for ACHAC east and west (latest) and CMIPC13 east (latest). Measure bytes downloaded, runtime, percent valid over the box, DQF shares, and the latency (now minus time_coverage_end). Commit no real outputs except a synthetic fixture ${PROTO}/fixtures/cloud-height-synthetic.png + .json (at most 30 KB, labelled synthetic). Write ${EVID}prototype-goes.json with the measurements, the real satellite longitudes and heights read from the files (and whether they match the parallax assumptions), the ACHA height units and reference as the file states them, and anything in goes-aws.json you found wrong.`

const P4 = (p1, p2) => `# Task P4 — the 3D storms layer on the globe page (slug: volume-layer)
Earlier agents built the globe page and the MRMS volume script; their summaries:
P1: ${JSON.stringify(p1)}
P2: ${JSON.stringify(p2)}
Read ${PROTO}/serve.py, ${PROTO}/globe.js, ${PROTO}/index.html, ${PROTO}/mrms_volume.py, the fixtures under ${PROTO}/fixtures/, and ${EVID}prototype-mrms.json.

Add, keeping every earlier test passing:
1. serve.py: /api/volume.json serving a volume file chosen by --volume <path> (default fixtures/volume-synthetic.json; the 2025-06-15 sample via --volume), with its provenance; the layer list gains "3D storms (MRMS reflectivity)", kind radar estimate, legend "Radar echo strength (dBZ). Not hail size. -99/-999 cells are no radar data; no echo is not clear.", plus the "synthetic: not weather" or archived-event label from the file, and its valid time.
2. globe.js: draw voxels from /api/volume.json as a Cesium PointPrimitiveCollection (one point per voxel, pixel size scaled by camera distance, colour by dBZ using the standard NWS reflectivity colour steps — list them in a comment with their dBZ ranges) positioned at the cell centre lon/lat and the level height in metres above the ellipsoid; a labelled vertical-exaggeration control (1x default, 3x, 5x; the label shows the factor on screen); a toggle in the panel; a legend with text and colour swatches per dBZ step. Document why this must run in the browser. Do not draw anything on the places layer from the volume.
3. tests/test_globe_browser.py: add a case that loads with the synthetic volume, asserts the volume layer's legend text is in the DOM, toggles the layer and asserts the canvas pixels change; and a case with --volume fixtures/volume-2025-06-15-sample.json that asserts the voxel count shown in the panel equals the fixture's count. Save the screenshot of the sample run downscaled to ${EVID}globe-volume.png (at most 300 KB).
4. Run the whole prototype test suite and the browser tests; fix until green or document the exact failure. Update ${EVID}prototype-globe.json with the volume results (draw time, voxel count, pixel diff) under a "volume" key.`

const P5 = (all) => `# Task P5 — integration and hygiene (slug: integrate)
Earlier builders reported: ${JSON.stringify(all)}
Do, from ${REPO}:
1. Run: cd ${PROTO} && python -m unittest discover -s tests -v ; then the browser tests the way their file documents; then the repo's own checks: cd ${REPO} && python -m unittest discover -s tests && python desktop/launcher.py --selftest payload. Record every command and result verbatim (pass counts, failures).
2. Hygiene: list every file under ${PROTO} and ${EVID} with its byte size; flag any file over its limit (fixtures 60 KB, evidence JSON 25 KB, screenshots 300 KB, any other file over 200 KB) and any downloaded data accidentally placed in the repo; grep the whole of research/globe for model names or AI-vendor identifiers and for absolute scratchpad paths that should not be in committed code; check that every script has a module docstring saying how to run it and that --synthetic/--offline modes exist where the task asked; check git status for files outside research/globe (report them, do not touch them).
3. Fix only small things yourself (a missing docstring, an oversized screenshot you can re-downscale, a stray path). For anything larger, report it with the exact file and line.
4. Write ${EVID}prototype-integration.json with the test results, the size table, and the hygiene findings. Return the structured summary.`

log('Wave 2a: building the globe prototype (P1 page, P2 MRMS volume, P3 GOES cloud height in parallel)')
const built = await parallel([
  () => agent(CTX + '\n\n' + P1, { label: 'build:globe-page', phase: 'Build', model: 'haiku', schema: PROTO_SCHEMA }),
  () => agent(CTX + '\n\n' + P2, { label: 'build:mrms-volume', phase: 'Build', model: 'haiku', schema: PROTO_SCHEMA }),
  () => agent(CTX + '\n\n' + P3, { label: 'build:goes-cloud-height', phase: 'Build', model: 'haiku', schema: PROTO_SCHEMA }),
])
const [p1, p2, p3] = built
if (!p1 || !p2) {
  log('P1 or P2 did not return; skipping the volume layer stage')
}
let p4 = null
if (p1 && p2) {
  log('Wave 2a: adding the 3D storms layer to the globe page')
  p4 = await agent(CTX + '\n\n' + P4(p1, p2), { label: 'build:volume-layer', phase: 'Volume layer', model: 'haiku', schema: PROTO_SCHEMA })
}
log('Wave 2a: integration run (all tests, sizes, hygiene)')
const p5 = await agent(CTX + '\n\n' + P5({ p1, p2, p3, p4 }), { label: 'integrate', phase: 'Integrate', model: 'haiku', schema: PROTO_SCHEMA })
return { p1, p2, p3, p4, p5 }
