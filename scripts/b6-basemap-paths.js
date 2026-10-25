export const meta = {
  name: 'b6-basemap-paths',
  description: 'Verify live the two base-map paths for the Apple-style map (Apple MapKit JS; self-hosted MapLibre with OpenStreetMap, USGS imagery and terrain): facts, licences, sizes, limits; then two skeptics per claim',
  phases: [{ title: 'Verify', detail: 'one agent per path, live checks' }, { title: 'Refute', detail: 'two skeptics per claim' }],
}
const worker = args.worker
const out = args.out
const common = [
  'You are a research worker for the Montana Hail Watch website (a static site built by Python, published by GitHub Pages at',
  'https://carson14dy.github.io/RoofingApp/, repo at /home/user/wt/wt-b5, branch claude/hail-b5). The owner wants the Map page to look and',
  'work like Apple Maps as seen inside the Zillow app: Apple-style cartography at every zoom (points of interest with icons, terrain tint and',
  'hillshade, reservations with their names, national forests, parks, rivers, route shields), a Map options sheet with Default / Satellite /',
  '3D View, risk-layer chips, amenity chips (Banks, Bars and clubs, Coffee shops), a Points of interest toggle, and a value bubble on every',
  'house at the closest zoom. The site today draws its own white vector base map (website/static/map/basemap.json: land, borders, counties,',
  'lakes, rivers, roads, labels, places from Natural Earth and Census) with Leaflet served by the site, plus an opt-in USGS imagery base map.',
  'Rules you must respect: never run git write commands; do not edit files under /home/user/wt; write everything under ' + out + '/<your-label>/;',
  'disk is limited (about 5 GB free): never download more than 1.5 GB in total, delete big downloads after measuring, and put each download',
  'in its own new empty directory; read downloaded JSON with python -I; verify content, not just HTTP 200 (quote the sentence or the field you',
  'read); every claim needs a source URL and how you checked it; say "not verified" when you could not. Plain words, sentence case, no',
  'em-dashes, no AI model or vendor names in any file you write. Use WebFetch or curl through the configured proxy for web pages.',
].join(' ')
const CLAIMS = { type: 'object', properties: {
  claims: { type: 'array', items: { type: 'object', properties: {
    id: { type: 'string' }, claim: { type: 'string' }, evidence: { type: 'string' }, source_url: { type: 'string' },
    checked_how: { type: 'string' }, confidence: { type: 'string', enum: ['verified', 'partly verified', 'not verified'] } },
    required: ['id', 'claim', 'evidence', 'source_url', 'checked_how', 'confidence'] } },
  summary: { type: 'string' }, blockers: { type: 'array', items: { type: 'string' } }, files: { type: 'array', items: { type: 'string' } } },
  required: ['claims', 'summary', 'blockers', 'files'] }
const paths = [
  { key: 'apple', prompt: common + ' YOUR PATH: Apple MapKit JS (Apple\'s web maps). Verify from developer.apple.com (MapKit JS documentation,' +
    ' "Creating and using tokens with MapKit JS", the mapkit.Map, mapkit.PointOfInterestFilter and mapkit.PointOfInterestCategory pages, the' +
    ' overlays and annotations pages, TileOverlay, the Apple Developer Program pages and the MapKit JS terms or the Apple Developer Program' +
    ' License Agreement where readable) and from Apple\'s "Maps Server API / MapKit JS" usage pages. Claims to establish, each with a quoted' +
    ' sentence: A1 what the free usage allowance is (map initializations per day, service calls per day) and what a developer account costs per' +
    ' year; A2 how a token works for a static site with no server (origin restriction, expiry, whether a long-lived token is allowed, and whether' +
    ' a token could be minted at each build by a GitHub Actions job from a stored key with Python); A3 which map types exist (standard, satellite,' +
    ' hybrid, muted standard) and whether MapKit JS on the web offers a 3D view at all; A4 the point-of-interest filter: which categories exist' +
    ' (list them; note Bank, Cafe, Nightlife, Restaurant, School, Park and the like) and whether a page can show only chosen categories and hide' +
    ' the rest, which is what the amenity chips and the Points of interest toggle need; A5 overlays: can the page draw its own raster tiles' +
    ' (TileOverlay) and polygons, circles and image annotations with custom HTML (our radar frames, hail cells, house dots and value bubbles);' +
    ' A6 the attribution and legal requirements (the Apple logo and legal link MapKit renders; whether they may be hidden; whether the script' +
    ' must load from Apple\'s CDN, which it must by the terms if so); A7 whether a site on a github.io origin or a custom domain is allowed as' +
    ' the token origin; A8 whether the map data may be cached or stored by the page (expect no) and what that means for an offline or sample' +
    ' build; A9 rate of change: when the MapKit JS version last changed and whether the 5.x API is current. Also write ' + out +
    '/apple/notes.md with every quoted sentence and URL, and the list of what the owner would have to do (account, Maps ID, key) step by step.',
  },
  { key: 'open', prompt: common + ' YOUR PATH: a self-hosted stack: MapLibre GL JS (served by the site), OpenStreetMap-derived vector tiles' +
    ' from Protomaps basemap builds as one PMTiles file for Montana, USGS imagery tiles for the satellite view, and public-domain terrain for' +
    ' hillshade and 3D. Claims to establish live: O1 Protomaps: the daily planet basemap build URL (https://maps.protomaps.com/builds/ or' +
    ' build.protomaps.com), its licence words, and the size of a Montana extract: download the pmtiles command-line tool (a Go binary from' +
    ' github.com/protomaps/go-pmtiles releases, into its own directory, check its sha or at least its size), run an extract for the Montana' +
    ' bounding box -116.1,44.3,-104.0,49.1 at maxzoom 10 first and measure the file; then extract a small Missoula box (-114.08,46.80,-113.93,46.92)' +
    ' at the build\'s full zoom and measure it; estimate the full-Montana full-zoom size from the two (state your method); keep the Missoula extract' +
    ' (it is small) and delete the rest. O2 Points of interest in OpenStreetMap for Missoula: decode tiles of the Missoula extract (pip install' +
    ' mapbox-vector-tile into a venv under your directory, or use the Overpass API at https://overpass-api.de/api/interpreter) and report whether' +
    ' these exist with a name and a category: Big Dipper Ice Cream, Clyde Coffee, Rockin Rudy\'s, Florabella, Tagliare Delicatessen, Loyola' +
    ' Sacred Heart High School, Hellgate High School, Sacajawea Park, Rose Park, St. Paul Lutheran; and count the pois layer features by kind in' +
    ' the Missoula box (banks, cafes, bars or nightlife, restaurants, schools, parks). O3 Licences: OpenStreetMap ODbL 1.0 (quote the' +
    ' attribution requirement and the Produced Work versus Derivative Database distinction from osmfoundation.org or opendatacommons.org;' +
    ' state in one paragraph, with "counsel to confirm", whether a site that shows OSM tiles and, as separate layers, its own hail cells and the' +
    ' State Library address points is a Produced Work with a Collective Database, so no share-alike obligation attaches to the hail or address' +
    ' data); the Protomaps basemap tiles licence; MapLibre GL JS licence (BSD-3-Clause) and its minified size and gzip size for the current' +
    ' release (download from npm or unpkg into your directory and measure). O4 Terrain: the AWS Open Data terrain tiles (Terrarium PNG at' +
    ' https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png, registry.opendata.aws/terrain-tiles): fetch one tile over Missoula' +
    ' at zoom 10 and one at zoom 12, confirm it decodes as a PNG with plausible elevations (decode a few pixels: height = R*256 + G + B/256 - 32768,' +
    ' Missoula is about 980 m), quote the attribution and licence words; also note USGS 3DEP as the public-domain source behind it. O5 Satellite:' +
    ' the USGS ImageryOnly tile service already used by the site (find the URL in /home/user/wt/wt-b5/website/build.py or static/map/map.js),' +
    ' fetch one tile over Missoula and confirm it is a JPEG or PNG image. O6 Hosting: GitHub Pages serves byte ranges? Send a GET with' +
    ' Range: bytes=0-1023 to a large file on the live site (for example https://carson14dy.github.io/RoofingApp/hail/j/events.json or any file' +
    ' over 1 MB you find from https://carson14dy.github.io/RoofingApp/data/map.json) and report the status (206 expected), Accept-Ranges,' +
    ' Content-Range and whether a second request with a different range returns different bytes; also report GitHub Pages size limits (the' +
    ' published site at most 1 GB; the docs page docs.github.com "GitHub Pages limits") and the size of the current hail store (552,012,463' +
    ' bytes) so the headroom for a tiles file is stated. O7 3D: MapLibre terrain (raster-dem source with the Terrarium encoding) and' +
    ' fill-extrusion of OSM building footprints: how many buildings in the Missoula extract carry a height or levels tag (count from the tiles' +
    ' or Overpass) so the 3D view\'s honesty is known (buildings without a height get a default height, say so). O8 Fonts and glyphs: MapLibre' +
    ' needs PBF glyph ranges for labels; state how to build them from the site\'s own fonts (website/static/fonts) with a tool such as' +
    ' font-maker or node-fontnik, and their size, so no font is served from a CDN. Write ' + out + '/open/notes.md with the measurements,' +
    ' the commands you ran and every quoted sentence and URL.',
  },
]
phase('Verify')
const results = await parallel(paths.map(p => () => agent(p.prompt, { label: 'verify:' + p.key, phase: 'Verify', model: worker, schema: CLAIMS })))
const VERDICT = { type: 'object', properties: { id: { type: 'string' }, refuted: { type: 'boolean' }, reason: { type: 'string' }, evidence: { type: 'string' } },
  required: ['id', 'refuted', 'reason', 'evidence'] }
function refutePrompt(item, k) {
  return 'You are skeptic ' + (k + 1) + ' of 2. Try to refute this claim about the ' + item.path + ' base-map path for the Montana Hail Watch map. ' +
    'Claim ' + item.claim.id + ': ' + item.claim.claim + ' Evidence given: ' + item.claim.evidence + ' Source: ' + item.claim.source_url +
    ' Checked how: ' + item.claim.checked_how + '. Make your own independent check (fetch the source URL or a better one through the configured proxy,' +
    ' re-run a measurement if it is a size or a count, read the notes under ' + out + ' only as a lead, never as proof). refuted=true when the' +
    ' claim is wrong, overstated, out of date, or when you cannot verify it yourself; refuted=false only when your own check confirms it.' +
    ' Quote what you read. Never run git write commands; write nothing outside ' + out + '/refute/. No AI model or vendor names in files.'
}
phase('Refute')
const items = []
results.forEach((r, i) => { ((r && r.claims) || []).forEach(c => items.push({ path: paths[i].key, claim: c })) })
const verdicts = await pipeline(items, item => parallel([0, 1].map(k => () =>
  agent(refutePrompt(item, k), { label: 'refute:' + item.path + ':' + item.claim.id + ':' + (k + 1), phase: 'Refute', model: worker, schema: VERDICT })))
  .then(vs => ({ path: item.path, id: item.claim.id, claim: item.claim.claim, confidence: item.claim.confidence,
    verdicts: vs.filter(Boolean), stands: vs.filter(Boolean).filter(v => !v.refuted).length === 2 })))
log('claims: ' + items.length + '; standing: ' + verdicts.filter(Boolean).filter(v => v.stands).length)
return { results, verdicts }