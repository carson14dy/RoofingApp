export const meta = {
  name: 'globe-sources-b',
  description: 'Live-verify radar tiles and NEXRAD, terrain tiles, base imagery terms and globe libraries, then refute each report',
  phases: [
    { title: 'Verify', detail: 'live request + content check per source' },
    { title: 'Refute', detail: 'independent re-check of each report' },
  ],
}
const WORKER = (typeof args !== 'undefined' && args && args.worker) || undefined  // the worker model alias, passed in args at launch

const SCRATCH = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad'
const EVID = '/home/user/RoofingApp/research/globe/validation-evidence/'

const CTX = `You are one of several agents building the "globe view" research scaffold for RoofingApp (a Montana roofing company's weather desktop app). A supervisor reads your output; it is data, not prose for a person.

Repo: /home/user/RoofingApp. First read /home/user/RoofingApp/research/globe/README.md sections 1-7 (the plan); your workstream is in section 5.

Rules that bind you (from AGENTS.md):
- Rule 7: make the live request AND check the content. Decode the tile or file and report what is inside (pixel stats, decoded elevation, parsed JSON). HTTP 200 proves nothing.
- Rule 9: no "best" claims; comparisons with evidence only.
- Rule 5: observation, satellite estimate, radar estimate and official alert stay separate; never "confirmed damage".

Working rules:
- Today is 2026-10-17 (UTC); day-of-year 290. Outbound HTTPS works through a preconfigured proxy (Python requests and curl honour it). pip install works; you may install packages for research and must list them in your result. Never edit requirements.txt.
- Downloads go into a fresh empty directory ${SCRATCH}/globe-dl/<your-slug>/ . Scripts you write go in ${SCRATCH}/globe-scripts/<your-slug>/ and read downloads by path; run them with "python -I".
- Montana bounding box: lon -116.05 to -104.04, lat 44.36 to 49.00. Billings: 45.7833, -108.5007 (airport elevation about 1,090 m; downtown about 950 m - verify from an authoritative source before using either).
- Write ONLY the files your task names. Your evidence file goes in ${EVID} as JSON of at most 20 KB: no binary captures, no large response bodies.
- Never write model names or AI-vendor identifiers into any file.
- Do not modify payload/, desktop/, tests/, docs/, or research/globe/README.md.
- For documentation and terms pages use WebFetch or WebSearch (load them with ToolSearch "select:WebFetch,WebSearch"). Quote the exact sentence you rely on, with its URL.
- If something cannot be verified, write "unverified" and why. Never guess a number.

Evidence file shape (JSON):
{
  "workstream": "W#", "slug": "...", "checked_at_utc": "...",
  "urls_checked": [{"url": "...", "method": "GET", "status": 200, "bytes": 0, "content_type": "...", "cors_allow_origin": "... or null", "content_check": "what you decoded and what it showed", "verified": true}],
  "facts": [{"claim": "...", "value": "...", "evidence": "url or file", "verified": true}],
  "terms": {"license": "...", "attribution_required": true, "quote": "...", "url": "..."},
  "limits": ["..."], "installed_packages": ["..."], "open_questions": ["..."]
}`

const SRC = {
  type: 'object',
  properties: {
    slug: { type: 'string' },
    evidence_file: { type: 'string' },
    headline_facts: { type: 'array', items: { type: 'string' } },
    blockers: { type: 'array', items: { type: 'string' } },
    installed_packages: { type: 'array', items: { type: 'string' } },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
  },
  required: ['slug', 'evidence_file', 'headline_facts', 'blockers', 'confidence'],
}

const REV = {
  type: 'object',
  properties: {
    slug: { type: 'string' },
    refuted_claims: { type: 'array', items: { type: 'string' } },
    corrections: { type: 'array', items: { type: 'string' } },
    confirmed: { type: 'array', items: { type: 'string' } },
    unverified: { type: 'array', items: { type: 'string' } },
    evidence_file_updated: { type: 'boolean' },
  },
  required: ['slug', 'refuted_claims', 'corrections', 'confirmed', 'unverified', 'evidence_file_updated'],
}

const ITEMS = [
  {
    slug: 'radar-tiles', title: 'W4 NEXRAD Level II on AWS, NWS radar WMS/MapServer, NCEP GeoServer, IEM tile caches',
    task: `1. NEXRAD Level II: bucket noaa-nexrad-level2, list https://noaa-nexrad-level2.s3.amazonaws.com/?list-type=2&prefix=2026/10/17/KBLX/ and the same for KGGW, KTFX, KMSX (the four Montana radars). Latest file name and size per site; cadence from consecutive files (volume scans, expect 4-10 minutes depending on VCP). Also list the real-time chunk bucket unidata-nexrad-level2-chunks for KBLX (prefix KBLX/) and describe its structure. Do NOT install Py-ART; instead record decoding options (Py-ART, MetPy Level2File) and the MetPy wheel size via "pip download --no-deps metpy" into your download directory.
2. NWS radar used by the app today (docs/DECISIONS.md D7): read /home/user/RoofingApp/payload/weather.py (read-only) to see exactly how it requests the radar_base_reflectivity MapServer and the idp_validtime. Reproduce: an export image over the Montana bounding box from https://mapservices.weather.noaa.gov/eventdriven/rest/services/radar/radar_base_reflectivity/MapServer (f=image, layers=show:1, transparent=true, 1024x512). Decode with PIL: percent coloured pixels, distinct colours. Fetch the valid time the same way the app does.
3. NCEP GeoServer: https://opengeo.ncep.noaa.gov/geoserver/conus/conus_bref_qcd/ows?service=WMS&request=GetCapabilities - parse the time dimension (period and latest), then GetMap over Montana (EPSG:3857 or 4326, 1024x512, PNG, transparent) and decode pixel stats. Also list what other conus layers exist (names only, up to 40).
4. IEM: fetch https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/5/6/11.png (and the neighbouring tile) and decode; look for IEM GOES tile layers (start at https://mesonet.agron.iastate.edu/ogc/ and https://mesonet.agron.iastate.edu/GIS/ridge.phtml); quote the IEM disclaimer/terms (https://mesonet.agron.iastate.edu/disclaimer.php) on reliability and attribution.
5. CORS headers for one tile/image from each of the four services (GET with an Origin header).
Write ${EVID}radar-tiles.json.`,
  },
  {
    slug: 'terrain', title: 'W5 Terrain: AWS Terrain Tiles, USGS 3DEP, Cesium World Terrain terms',
    task: `1. AWS Terrain Tiles (registry.opendata.aws/terrain-tiles): fetch https://s3.amazonaws.com/elevation-tiles-prod/terrarium/10/{x}/{y}.png for the tile containing Billings (compute x,y for zoom 10 and show the formula). Decode with PIL: elevation = (R*256 + G + B/256) - 32768 metres; report the decoded elevation at Billings' pixel and the tile's min/max. Also check the "normal" and "geotiff" tile formats exist (HEAD or GET, bytes) and the skadi SRTM HGT layout. Quote the attribution requirement from https://registry.opendata.aws/terrain-tiles/ (it lists several data providers that must be credited).
2. USGS 3DEP: https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/identify?geometry={"x":-108.5007,"y":45.7833,"spatialReference":{"wkid":4326}}&geometryType=esriGeometryPoint&returnGeometry=false&returnCatalogItems=false&f=json - record the elevation value and compare it with the terrarium decode (difference in metres). Quote the USGS terms (public domain) with URL.
3. Cesium terrain options without a Cesium ion account: read the CesiumJS docs for CesiumTerrainProvider (what a layer.json / quantized-mesh or heightmap tileset is), check whether CesiumJS has any built-in provider for terrarium/Terrain-RGB PNG tiles (expect none - quote the provider list from the API docs), and name the open-source converters that produce quantized-mesh from DEMs (e.g. cesium-terrain-builder / ctb-quantized-mesh) with their licences. Read https://cesium.com/pricing/ (or the ion plans page) and quote what the free plan allows for commercial use of Cesium World Terrain; mark unverified if the page cannot be read.
4. three.js / globe.gl / MapLibre: note which can consume terrarium or Terrain-RGB tiles directly (MapLibre raster-dem with encoding terrarium; quote the doc line).
Write ${EVID}terrain.json.`,
  },
  {
    slug: 'base-imagery', title: 'W6 Base imagery: USGS imagery tiles for a globe, GIBS Blue Marble / VIIRS, Esri and Sentinel-2 cloudless terms',
    task: `1. USGS imagery (the app's base map, docs/DECISIONS.md D9): https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer?f=json - record tileInfo (spatial reference, origin, LODs count, max LOD, tile size, format) so a globe library can address it with a Web Mercator {z}/{y}/{x} template. Fetch https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/12/{y}/{x} for Billings (compute y,x) and decode with PIL (size, distinct colours, mean RGB). Fetch a tile over central Europe at zoom 6 to show what happens outside the US (status, decoded content). Quote the USGS terms of use (https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-and-data-national-map).
2. NASA GIBS for the rest of the globe: BlueMarble_ShadedRelief_Bathymetry (static) and VIIRS_SNPP_CorrectedReflectance_TrueColor (daily, time dimension): fetch one tile each over Montana and one over the mid-Pacific at zoom 4 (epsg3857 endpoint https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{Layer}/default/{Time}/GoogleMapsCompatible_Level{N}/{z}/{y}/{x}.jpg - read the TileMatrixSet name and max level from the capabilities, do not guess). Decode each. For VIIRS, record the latest date available versus today (lag in days).
3. Esri World Imagery: read https://www.esri.com/en-us/legal/terms/full-master-agreement and the ArcGIS Location Platform pricing/free-tier page for basemap tiles; quote what commercial use requires (an account? attribution? free tile allowance?). If the pages cannot be fetched, mark unverified and say which URL failed.
4. EOX Sentinel-2 cloudless: read https://s2maps.eu and quote its licence (expected CC-BY-NC-SA 4.0) and what that means for a company product.
5. CORS headers on one USGS tile and one GIBS tile (GET with an Origin header).
Write ${EVID}base-imagery.json.`,
  },
  {
    slug: 'globe-libs', title: 'W7 Globe libraries: CesiumJS, three.js + globe.gl, deck.gl + pydeck, MapLibre GL globe, Google Photorealistic 3D Tiles',
    task: `Produce a comparison table (no "best"): version, licence, download size, needs an account/key?, time-dynamic imagery support, 3D volume/3D-texture support, terrain support without an account, WebGL version required, Python wrapper available.
1. CesiumJS: https://registry.npmjs.org/cesium/latest (version, license, dist.unpackedSize); https://api.cdnjs.com/libraries/cesium?fields=version,filename,assets (is Build/Cesium/Cesium.js plus Workers/ and Assets/ served? HEAD the Cesium.js for content-length). Read the CesiumJS quickstart and the Ion.defaultAccessToken API page: quote whether a token is required when using only your own imagery providers and EllipsoidTerrainProvider, and which Viewer options avoid ion (baseLayer, terrain, geocoder, baseLayerPicker). Check and quote: WebMapTileServiceImageryProvider "times" option for time-dynamic WMTS (GIBS); UrlTemplateImageryProvider; PointPrimitiveCollection and Primitive + BoxGeometry instancing for voxels; VoxelPrimitive status (experimental?) in the latest CHANGES.md; CustomShader scope (3D Tiles only?); createGooglePhotorealistic3DTileset (needs a Google key); minimum WebGL version per CHANGES.md.
2. three.js (registry.npmjs.org/three/latest: version, licence, unpackedSize) and Data3DTexture for volume ray-marching (quote the doc); globe.gl (version, licence, size) and what it wraps (ThreeGlobe).
3. deck.gl: version; the _GlobeView docs (quote the experimental status sentence); pydeck version from PyPI JSON https://pypi.org/pypi/pydeck/json and whether pydeck exposes GlobeView (search its docs; quote or unverified).
4. MapLibre GL JS: version from npm; the globe projection docs (quote that globe is supported in v5), licence BSD-3, custom layers API (WebGL access), raster-dem terrain with terrarium encoding, no native volume rendering (state what you could and could not confirm).
5. Google Photorealistic 3D Tiles: URL of the Map Tiles API docs; the pricing unit (root tile requests) and the current price per 1,000; Maps Platform terms on caching and on displaying Google content outside a Google map (quote the exact sentences). Candidates only, not ranked.
Write ${EVID}globe-libs.json.`,
  },
]

function researchPrompt(it) {
  return CTX + '\n\n# Your workstream: ' + it.title + '\n\n' + it.task +
    '\n\nWhen done, return: slug, evidence_file (absolute path), headline_facts (the 5-10 facts that matter for the plan, each with its number and unit), blockers (anything you could not do, with the exact error), installed_packages, confidence.'
}

function refutePrompt(it, res) {
  return CTX + '\n\n# Your job: REFUTE the report for ' + it.title +
    '\n\nA previous agent wrote ' + EVID + it.slug + '.json and summarised it as:\n' + JSON.stringify(res, null, 2) +
    '\n\nRead the evidence file. Then independently re-check every fact that matters to the plan, using different inputs where possible (a different tile, zoom, file or page than the first agent used), and re-read each quoted terms or documentation page yourself. Default to suspicion: a claim with no decoded content or quoted sentence behind it is unverified; a number from memory is unverified. Check especially: sizes, versions, licence wording, "needs a key" claims, CORS headers, elevation values, and max zoom levels.' +
    '\n\nThen UPDATE the evidence file in place: fix wrong values in "facts" and add "corrected_by_review": true to each one you changed; add a top-level "review" object {"refuted_claims": [...], "corrections": [...], "confirmed": [...], "unverified": [...], "reviewer_checks": [{"url": "...", "content_check": "...", "verified": true}]}. Keep the file at or under 20 KB. Return the same lists plus evidence_file_updated.'
}

log('Wave 1B: verifying radar tiles, terrain, base imagery, globe libraries - each report then refuted')
const results = await pipeline(ITEMS,
  it => agent(researchPrompt(it), { label: 'verify:' + it.slug, phase: 'Verify', model: WORKER, schema: SRC }),
  (res, it) => res ? agent(refutePrompt(it, res), { label: 'refute:' + it.slug, phase: 'Refute', model: WORKER, schema: REV }) : null,
)
return { slugs: ITEMS.map(i => i.slug), reviews: results }
