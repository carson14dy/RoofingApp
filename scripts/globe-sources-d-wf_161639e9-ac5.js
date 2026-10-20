export const meta = {
  name: 'globe-sources-d',
  description: 'Design references from the owner screenshots, high-res Montana imagery/buildings/boundaries, and labels over imagery on a globe, then refute',
  phases: [
    { title: 'Verify', detail: 'analyse screenshots; live request + content check per source' },
    { title: 'Refute', detail: 'independent re-check of each report' },
  ],
}
const WORKER = (typeof args !== 'undefined' && args && args.worker) || undefined  // the worker model alias, passed in args at launch

const SCRATCH = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad'
const EVID = '/home/user/RoofingApp/research/globe/validation-evidence/'
const UPLOADS = '/root/.claude/uploads/7638440a-a008-5ef8-a289-86be0a23e7a7/'
const SHOTS = ['4d997b22-image.png', '2aa7f2a6-image.png', '94b162dc-image.png', '5c373874-image.png', '110dd852-image.png', 'bd481183-image.png']

const CTX = `You are one of several agents building the "globe view" research scaffold for RoofingApp (a Montana roofing company's weather desktop app). A supervisor reads your output; it is data, not prose for a person.

Repo: /home/user/RoofingApp. First read /home/user/RoofingApp/research/globe/README.md sections 1-7 (the plan).

Rules that bind you (from AGENTS.md):
- Rule 7: make the live request AND check the content. Decode the tile or file and report what is inside (pixel stats, parsed JSON, feature counts). HTTP 200 proves nothing.
- Rule 9: no "best" claims; comparisons with evidence only.
- Rule 5: observation, satellite estimate, radar estimate and official alert stay separate; never "confirmed damage".

Working rules:
- Today is 2026-10-17 (UTC). Outbound HTTPS works through a preconfigured proxy (Python requests and curl honour it). pip install works; list anything you install. Never edit requirements.txt.
- Downloads go into a fresh empty directory ${SCRATCH}/globe-dl/<your-slug>/ . Scripts you write go in ${SCRATCH}/globe-scripts/<your-slug>/ and read downloads by path; run them with "python -I".
- Missoula downtown: lon -113.994, lat 46.872. Billings: 45.7833, -108.5007. Montana bounding box: lon -116.05 to -104.04, lat 44.36 to 49.00.
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
  "terms": [{"source": "...", "license": "...", "attribution_required": true, "quote": "...", "url": "..."}],
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
    slug: 'design-references', title: 'W18 Design references: the owner\'s six Apple Maps screenshots (his OSM Boundary Extractor iOS app) as a zoom-level brief',
    task: `The owner sent six iPhone screenshots of his own iOS app "OSM Boundary Extractor" ("Tap map to add 5 points (Apple Maps / MapKit)") showing Missoula, Montana at different zooms, and said: "I added those to assist in designing a map." The files, in the order he sent them, are:
${SHOTS.map((s, i) => (i + 1) + '. ' + UPLOADS + s).join('\n')}
1. View each image with the Read tool. For each, record: approximate map scale (street / neighbourhood / city / valley / region) and an estimated Web Mercator zoom level with your reasoning (e.g. block lengths, labelled streets, state labels), the visible cartographic elements (3D extruded buildings, POI pins with categories, district shading such as "Heart of Missoula", road hierarchy, rivers, parks, hillshade/terrain tint, state/province boundaries and labels, highway shields, the Apple Maps attribution), the colour palette (light base, which accent colours), what the user is doing in the app (the subtitle says tap to add 5 points).
2. Make small design-reference copies for the repo: pip-free, with PIL: resize each to 480 px wide, save as JPEG quality 72 into /home/user/RoofingApp/research/globe/design-references/ named 01-street-3d-buildings.jpg, 02-street-detail.jpg, 03-downtown-blocks.jpg, 04-city.jpg, 05-valley-terrain.jpg, 06-region-states.jpg (match names to what each image actually shows; if the order differs, name by content and say so). Each must be at most 80 KB; report final sizes and the total. Do not copy the originals into the repo.
3. Write the design brief as data: for each zoom band, which of the plan's free sources (section 3 of the README) would draw it on the globe, what is missing (e.g. 3D buildings, POIs, district shading have no source yet), and what the roofing use needs at that zoom (a storm over a territory at city zoom; a specific roof at street zoom; the whole state at region zoom). Note where the app's dark "storm" look (docs/DECISIONS.md D19, templates/base.html tokens) meets the light Apple cartography: a recommendation with reasons, not a "best".
4. Relevance of the owner's extractor app: it taps points and extracts an OpenStreetMap boundary; list how a territory or neighbourhood polygon from it could enter the app (GeoJSON import into territories) and the open questions (export format, which OSM boundary it picks, licence of OSM boundaries = ODbL).
Write ${EVID}design-references.json with keys: images (one object each: file, repo_copy, kb, scale_band, zoom_estimate, elements, palette), zoom_bands (one object per band: band, zoom_range, sources_available, sources_missing, roofing_need), style_recommendation, extractor_integration, open_questions.`,
  },
  {
    slug: 'montana-imagery-buildings', title: 'W16 High-resolution Montana orthoimagery, building footprints and boundaries (street-zoom sources)',
    task: `The owner wants a Google Earth-like street zoom (see the plan). Find and verify free sources for Montana:
1. Montana State Library (MSL) imagery services: search for the MSL ArcGIS REST catalogue (likely under https://gisservicemt.gov/arcgis/rest/services/ - list the folders and any ImageServer or MapServer with "Imagery", "NAIP", "Ortho" in the name; record each service's ?f=json pixel size (resolution in metres), extent, and whether it exports or serves tiles). Export a 512x512 image over downtown Missoula (bbox about 500 m wide) from the highest-resolution service you find, decode with PIL (distinct colours, mean RGB, is it a real aerial photo?). Quote the MSL / Montana data terms (public?) with URL.
2. Missoula County or City of Missoula GIS: search for their ArcGIS REST or Open Data imagery (e.g. 6-inch orthoimagery). If found: service URL, resolution, an export decoded as above, terms quoted. If not found in 20 minutes, say so.
3. USDA NAIP: what resolution the current Montana NAIP is (60 cm or 30 cm; quote the USDA/USGS page), and that the USGS imagery tile service the app already uses (docs/DECISIONS.md D9) is where NAIP reaches a globe for free; note the NAIP on AWS buckets (naip-visualization, requester-pays) as an alternative with a one-line cost note.
4. Building footprints: (a) OpenStreetMap via the public Overpass API - run one query for ways tagged building inside a 1 km box around downtown Missoula; report the count and how many carry height or building:levels tags; quote the Overpass public-instance usage policy; (b) Microsoft Global ML Building Footprints (GitHub README: licence ODbL, how the US/Montana files are laid out, approximate size); (c) Overture Maps buildings (latest release page: licence statement, how to fetch one bbox, file sizes); (d) Cesium OSM Buildings - quote that it is a Cesium ion asset (needs a token). State the ODbL share-alike condition in one plain sentence for the app's own territory database.
5. Boundaries: (a) Census TIGERweb REST - fetch the Missoula city place polygon and Missoula County polygon as JSON (query endpoint; report vertex counts; terms public domain, quote); (b) Nominatim lookup for "Missoula, Montana" with polygon_geojson=1 (report what boundary type comes back, vertex count, the usage policy quote: 1 request/s, identifying User-Agent); (c) whether "Heart of Missoula" exists in OSM as a neighbourhood/place node or area (Nominatim or Overpass; report what you find). Record CORS headers on one request from each service.
Write ${EVID}montana-imagery-buildings.json.`,
  },
  {
    slug: 'labels-on-globe', title: 'W17 Names, roads and boundaries over imagery on a globe: label sources, their terms, and how a globe library draws them',
    task: `A storm globe on raw imagery is unreadable without place names, roads and boundaries. Verify free options:
1. USGS: https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryTopo/MapServer and .../USGSTopo/MapServer - record ?f=json tileInfo (LODs, max LOD) and fetch tiles over Missoula at zoom 12 and zoom 15 (compute y,x; URL .../tile/{z}/{y}/{x}); decode with PIL (size, distinct colours, mean RGB) and state whether the Imagery Topo tile visibly combines imagery with labels/roads (compare its colour statistics against the plain USGSImageryOnly tile for the same z/y/x). Keep any crops in your download directory, never in the repo. Quote the USGS terms (public domain) with URL.
2. NASA GIBS reference layers: find Reference_Labels_15m, Reference_Features_15m, Coastlines_15m (or current names) in https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml ; fetch one tile each over Montana at zoom 5 and decode; state what they show (country/state names? cities?) and their max zoom.
3. OpenStreetMap raster tiles: quote the OSMF tile usage policy (https://operations.osmfoundation.org/policies/tiles/) sentences on bulk/heavy use and apps; CARTO basemaps: confirm the current status (D9 says they now require an API key) by fetching one tile from https://basemaps.cartocdn.com/light_only_labels/5/6/11.png and recording status and body; OpenFreeMap (https://openfreemap.org) and Protomaps (https://protomaps.com) - quote their terms and note they are vector tiles (MapLibre-style), not raster, and what that means for a Cesium globe.
4. Apple MapKit JS as a candidate for the flat map only: https://developer.apple.com/maps/web/ - quote the daily free allowance and the Apple Developer Program requirement; check the MapKit JS docs for 3D or globe support (expect none; quote or unverified); quote any restriction on use inside non-browser containers if stated. Candidate only, not ranked.
5. CesiumJS: how it draws labels (LabelCollection / entity labels) and whether a raster label tile layer can sit over imagery with alpha (ImageryLayer alpha option) - quote the API doc lines with URLs. Also whether Cesium can render vector tiles natively (expect: not without a plugin; quote or unverified).
Record CORS headers on one tile from each raster service. Write ${EVID}labels-on-globe.json.`,
  },
]

function researchPrompt(it) {
  return CTX + '\n\n# Your workstream: ' + it.title + '\n\n' + it.task +
    '\n\nWhen done, return: slug, evidence_file (absolute path), headline_facts (the 5-10 facts that matter for the plan, each with its number and unit), blockers (anything you could not do, with the exact error), installed_packages, confidence.'
}

function refutePrompt(it, res) {
  return CTX + '\n\n# Your job: REFUTE the report for ' + it.title +
    '\n\nA previous agent wrote ' + EVID + it.slug + '.json and summarised it as:\n' + JSON.stringify(res, null, 2) +
    '\n\nRead the evidence file. Then independently re-check every fact that matters to the plan, using different inputs where possible (a different tile, zoom, bbox, page or image than the first agent used), and re-read each quoted terms page yourself. For the design-references report, view the six screenshots yourself (' + UPLOADS + SHOTS.join(', ' + UPLOADS) + ') and check the repo copies exist, are at most 80 KB each, and are named by what they show. Default to suspicion: a claim with no decoded content or quoted sentence behind it is unverified.' +
    '\n\nThen UPDATE the evidence file in place: fix wrong values and add "corrected_by_review": true to each you changed; add a top-level "review" object {"refuted_claims": [...], "corrections": [...], "confirmed": [...], "unverified": [...], "reviewer_checks": [{"what": "...", "result": "...", "verified": true}]}. Keep the file at or under 20 KB. Return the same lists plus evidence_file_updated.'
}

log('Wave 1D: design references, Montana street-zoom sources, labels over imagery - each report then refuted')
const results = await pipeline(ITEMS,
  it => agent(researchPrompt(it), { label: 'verify:' + it.slug, phase: 'Verify', model: WORKER, schema: SRC }),
  (res, it) => res ? agent(refutePrompt(it, res), { label: 'refute:' + it.slug, phase: 'Refute', model: WORKER, schema: REV }) : null,
)
return { slugs: ITEMS.map(i => i.slug), reviews: results }
