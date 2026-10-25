export const meta = {
  name: 'b6-own-cartography',
  description: 'Public-domain sources for our own map cartography (terrain shading and land cover tint, water with names, reservations, national forests, parks, landmarks, peaks, places, route numbers), verified live with Montana sizes, plus one proof picture rendered by Python in the site palette; two skeptics per claim and a critic on the picture',
  phases: [{ title: 'Verify', detail: 'two source workers and one renderer' }, { title: 'Refute', detail: 'two skeptics per claim; a critic on the picture' }],
}
const worker = args.worker
const out = args.out
const rules = 'Rules: never run git write commands; do not edit files under /home/user/wt; write only under ' + out + '/<your-label>/; disk is limited' +
  ' (about 5 GB free): never download more than 1 GB in total, put each download in its own new empty directory, delete big files after' +
  ' measuring, prefer a service export of a small region over a statewide download and estimate statewide volume from it; read downloaded' +
  ' JSON with python -I; verify content, not just HTTP 200 (open the file, count features, read a value); every claim needs a source URL' +
  ' and how you checked it; quote the licence or terms words; plain words, sentence case, no em-dashes, no AI model or vendor names in files.' +
  ' The Python environment is /home/user/hail-b1/venv/bin/python (requests, numpy, pillow, pyproj, pyogrio, pyarrow available; pip install' +
  ' into your own venv under your directory if you need more).'
const context = 'Context: the Montana Hail Watch website (repo /home/user/wt/wt-b6, read docs/DESIGN.md sections 1 and 8 for the look, the tokens' +
  ' in website/static/style.css, and tools/build_basemap.py for how the base map is built from Natural Earth and Census files into' +
  ' website/static/map/basemap.json, drawn by Leaflet on a canvas). The owner wants the map to work like a modern phone map at every zoom' +
  ' (terrain tint and shading at the region and state zooms, rivers and lakes with names, reservations and national forests with names,' +
  ' parks, landmarks such as schools, hospitals, airports and churches with icons, peaks, more town names, highway shields) in the site\'s' +
  ' own design, from public-domain data only (no OpenStreetMap, no commercial data), built by Python into site files, with no request to' +
  ' another site while the map is used (the opt-in USGS imagery is the one exception today). The streets and building outlines at zoom' +
  ' 13 and up already come from the Montana State Library and the FEMA and ORNL USA Structures file (website/streets.py,' +
  ' website/buildings.py).'
const CLAIMS = { type: 'object', properties: {
  claims: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, layer: { type: 'string' }, claim: { type: 'string' },
    evidence: { type: 'string' }, source_url: { type: 'string' }, licence: { type: 'string' }, size_for_montana: { type: 'string' },
    cadence: { type: 'string' }, checked_how: { type: 'string' }, confidence: { type: 'string', enum: ['verified', 'partly verified', 'not verified'] } },
    required: ['id', 'layer', 'claim', 'evidence', 'source_url', 'licence', 'size_for_montana', 'cadence', 'checked_how', 'confidence'] } },
  summary: { type: 'string' }, blockers: { type: 'array', items: { type: 'string' } }, files: { type: 'array', items: { type: 'string' } } },
  required: ['claims', 'summary', 'blockers', 'files'] }
const RENDER = { type: 'object', properties: { pictures: { type: 'array', items: { type: 'object', properties: { path: { type: 'string' }, view: { type: 'string' },
  zoom: { type: 'number' }, layers: { type: 'array', items: { type: 'string' } }, bytes: { type: 'number' } }, required: ['path', 'view', 'zoom', 'layers', 'bytes'] } },
  method: { type: 'string' }, statewide_estimate: { type: 'string' }, problems: { type: 'array', items: { type: 'string' } }, files: { type: 'array', items: { type: 'string' } } },
  required: ['pictures', 'method', 'statewide_estimate', 'problems', 'files'] }
const terrainPrompt = context + ' YOUR JOB: the raster layers. (1) Terrain shading: USGS 3DEP. Check the 3DEPElevation image service' +
  ' (https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer): its exportImage with a rendering rule such as' +
  ' "Hillshade Gray" or "Hillshade Elevation Tinted" for a box over Missoula (about -114.6,46.5,-113.4,47.2) at 1024 px, PNG; confirm' +
  ' the image has real shading (pixel statistics, not a blank), its size, the service\'s copyright text and the USGS data policy words' +
  ' (public domain, credit requested); also check whether the service can be read as 256 px tiles (the tile endpoint, if any) and the' +
  ' request limits in its JSON (maxImageHeight, maxImageWidth). Estimate the number and bytes of 256 px hillshade tiles for the Montana' +
  ' box at zooms 5 to 10 and 5 to 12 from a measured sample (export a few tiles at zoom 10 and 12 and weigh them). (2) Land cover tint:' +
  ' the NLCD land cover (MRLC): find a public service or download (the MRLC web map service or the NLCD 2021 or Annual NLCD product on' +
  ' the USGS or MRLC site), export the same Missoula box, confirm the classes present (forest, shrub, grass, developed, water, crop) and' +
  ' the licence words; estimate the statewide volume at 30 m and at a 240 m generalisation. (3) Alternative tint without NLCD: the' +
  ' USGS Shaded Relief or the National Map "USGS Shaded Relief" and "USGS Hydro Cached" services as tiles (check a tile over Missoula,' +
  ' the service terms). (4) Write ' + out + '/raster/notes.md with every command, size and quoted sentence. ' + rules
const vectorPrompt = context + ' YOUR JOB: the vector layers, each verified live with a Montana sample and a statewide size estimate.' +
  ' (1) Water: the USGS National Hydrography Dataset (NHD) or the Census TIGER/Line 2026 area water and linear water county files' +
  ' (download one county, Missoula County FIPS 30063, count features, read names such as Clark Fork, Bitterroot River, Rattlesnake' +
  ' Creek; note which rivers carry a GNIS name) and the state-level option. (2) Reservations: Census TIGER/Line American Indian Areas' +
  ' (AIANNH) national file: count the Montana reservations, read the names (Flathead, Blackfeet, Crow, Fort Peck, Fort Belknap,' +
  ' Northern Cheyenne, Rocky Boy\'s), and the Salish name question (TIGER has English names only; say so). (3) National forests: the' +
  ' Forest Service administrative forest boundaries (the FSGeodata clearinghouse or the EDW map service), count the Montana forests and' +
  ' read names (Bitterroot, Lolo, Flathead, Beaverhead-Deerlodge, Custer Gallatin, Helena-Lewis and Clark, Kootenai). (4) Parks: PAD-US' +
  ' (USGS) for state and national parks and the Census TIGER area landmark file for Missoula County (MTFCC codes for parks K2180 to' +
  ' K2190, schools K2543, hospitals K1231, airports K2451 to K2460, places of worship K3544, cemeteries): count by code, read names' +
  ' (Rose Park, McCormick Park, Sacajawea Park, Loyola Sacred Heart High School, Hellgate High School), note that TIGER point landmarks' +
  ' are a separate file. (5) Peaks and places: USGS GNIS (the domestic names file for Montana): count summits with elevation (McDonald' +
  ' Peak, Mount Sentinel) and populated places; and the Census places (incorporated and CDP, 2026) with population from the ACS or' +
  ' the decennial API for a min-zoom-by-population rule (Lolo, Frenchtown, Florence, Stevensville, Hamilton, Seeley Lake, Darby). (6)' +
  ' Route numbers: our basemap.json already carries refs such as I-90 and US-12 on the Natural Earth roads; check the Montana State' +
  ' Library transportation framework or TIGER primary roads for state routes (MT 200, MT 83) and Interstate business loops, and say' +
  ' which file gives route numbers per road segment. For every source: the URL, the licence or terms words quoted, the bytes for' +
  ' Montana, the update cadence, and what an honest attribution line reads. Write ' + out + '/vector/notes.md with commands, counts and' +
  ' quotes. ' + rules
const renderPrompt = context + ' YOUR JOB: a proof picture, rendered by Python, of what our own map could look like at the region zoom and' +
  ' at the city zoom, in the site\'s palette (read website/static/style.css tokens: paper, ink, sky, mist; use a soft green for forest' +
  ' from the land cover and a cream for developed land, blue for water, a light hillshade at low opacity; labels in the site\'s font' +
  ' Atkinson Hyperlegible Next from website/static/fonts, converted if needed). Inputs you fetch yourself, small: a USGS 3DEP hillshade' +
  ' export (the 3DEPElevation image service exportImage, rendering rule Hillshade Gray) for the box -115.0,46.3,-113.2,47.4 at 1600 px' +
  ' wide; a land cover export for the same box (MRLC NLCD service, or if it is unreachable the USGS shaded relief or hydro cached tiles' +
  ' as a stand-in and say so); the existing website/static/map/basemap.json for roads, rivers, lakes and places; the reservation and' +
  ' forest outlines if you can fetch them in under 50 MB (Census AIANNH, Forest Service boundaries), else leave them out and say so.' +
  ' Produce: (a) region.png, the box at about zoom 8.5 as a 780 by 1688 px picture (a 390 by 844 phone at scale 2) with terrain tint and' +
  ' shading, water, major roads with route numbers in small shields, town names, reservation and forest names in the small capitals the' +
  ' reference uses for areas; (b) city.png, Missoula at about zoom 12 (the box -114.15,46.78,-113.90,46.95) with the same layers plus' +
  ' the local roads from basemap.json if present; (c) a composite beside the owner\'s reference views /root/.claude/uploads/' +
  '7638440a-a008-5ef8-a289-86be0a23e7a7/eca9a283-image.jpg (the region) and /root/.claude/uploads/7638440a-a008-5ef8-a289-86be0a23e7a7/' +
  '6a526b96-image.jpg (the wider city) using Pillow: reference left, ours right, one caption line. Measure the bytes of each layer and' +
  ' estimate the statewide volume for tiles at zooms 5 to 12 (number of 256 px tiles and bytes from your sample). This is a proof of' +
  ' look, not product code: write it as a standalone script under ' + out + '/render/ and say what the product build would do' +
  ' differently. ' + rules
phase('Verify')
const [raster, vector, render] = await parallel([
  () => agent(terrainPrompt, { label: 'verify:raster', phase: 'Verify', model: worker, schema: CLAIMS }),
  () => agent(vectorPrompt, { label: 'verify:vector', phase: 'Verify', model: worker, schema: CLAIMS }),
  () => agent(renderPrompt, { label: 'render:proof', phase: 'Verify', model: worker, schema: RENDER }),
])
const VERDICT = { type: 'object', properties: { id: { type: 'string' }, refuted: { type: 'boolean' }, reason: { type: 'string' }, evidence: { type: 'string' } },
  required: ['id', 'refuted', 'reason', 'evidence'] }
phase('Refute')
const items = []
if (raster) (raster.claims || []).forEach(c => items.push({ part: 'raster', c: c }))
if (vector) (vector.claims || []).forEach(c => items.push({ part: 'vector', c: c }))
const verdicts = await pipeline(items, it => parallel([0, 1].map(k => () => agent(
  'You are skeptic ' + (k + 1) + ' of 2. Try to refute this claim about a public-domain map data source for the Montana Hail Watch map' +
  ' (' + it.part + ' layers). Claim ' + it.c.id + ' (' + it.c.layer + '): ' + it.c.claim + ' Evidence: ' + it.c.evidence + ' Source: ' +
  it.c.source_url + ' Licence as stated: ' + it.c.licence + ' Size as stated: ' + it.c.size_for_montana + ' Checked how: ' + it.c.checked_how +
  '. Make your own independent check (fetch the URL or a better one, re-run a count or a measurement on a small sample). Judge substance:' +
  ' refuted=true only when the fact is wrong, the licence is misread, the size is off by more than a factor of two, or the source is' +
  ' unreachable for you too after two tries; wording quibbles are not refutations, say "stands with a note" in the reason instead.' +
  ' Quote what you read. ' + rules.replace('<your-label>', 'refute'),
  { label: 'refute:' + it.c.id + ':' + (k + 1), phase: 'Refute', model: worker, schema: VERDICT })))
  .then(vs => ({ part: it.part, id: it.c.id, layer: it.c.layer, claim: it.c.claim, verdicts: vs.filter(Boolean), stands: vs.filter(Boolean).filter(v => !v.refuted).length === 2 })))
const CRITIC = { type: 'object', properties: { ok: { type: 'boolean' }, problems: { type: 'array', items: { type: 'string' } }, strengths: { type: 'array', items: { type: 'string' } }, checked: { type: 'array', items: { type: 'string' } } }, required: ['ok', 'problems', 'strengths', 'checked'] }
const critic = render ? await agent('You are a design critic for the Montana Hail Watch map (read docs/DESIGN.md sections 1 and 8 in' +
  ' /home/user/wt/wt-b6 for the field-sheet look and its rules: tokens only, every hazard colour carries its word, sentence case, nothing' +
  ' to decode). The renderer reported: ' + JSON.stringify(render).slice(0, 5000) + '. Open every picture it names (Read the image files)' +
  ' and the composites; judge whether the picture reads as the same kind of map as the owner\'s reference at that zoom (terrain, water,' +
  ' forests and reservations named, towns, shields) while staying in the site\'s palette, whether labels are legible at phone size, and' +
  ' whether anything is dishonest (a layer that is a stand-in must be labelled as such in the report). List concrete problems and' +
  ' strengths. ' + rules.replace('<your-label>', 'critic'), { label: 'critic:render', phase: 'Refute', model: worker, schema: CRITIC }) : null
log('claims: ' + items.length + '; standing: ' + verdicts.filter(Boolean).filter(v => v.stands).length + '; render ok: ' + (critic && critic.ok))
return { raster, vector, render, verdicts, critic }