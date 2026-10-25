export const meta = {
  name: 'b6-landmark-sources',
  description: 'Fill the gaps the vector worker found: public-domain sources for schools, hospitals, places of worship, airports and parks (NCES EDGE, HIFLD, FAA, PAD-US by another route), summit elevations from 3DEP, and the NHD small-scale rivers for the low zooms; verified live with Montana counts; two skeptics per claim',
  phases: [{ title: 'Verify', detail: 'two source workers' }, { title: 'Refute', detail: 'two skeptics per claim' }],
}
const worker = args.worker
const out = args.out
const rules = 'Rules: never run git write commands; do not edit files under /home/user/wt; write only under ' + out + '/<your-label>/; disk is limited' +
  ' (about 5 GB free): never download more than 600 MB in total, each download in its own new empty directory, delete big files after' +
  ' measuring, prefer a service query for a county or a box over a national file; read downloaded JSON with python -I; verify content, not' +
  ' just HTTP 200 (open the file, count features, read names); every claim needs a source URL, the licence or terms words quoted, the bytes' +
  ' for Montana, the update cadence and how you checked; plain words, sentence case, no em-dashes, no AI model or vendor names in files.' +
  ' The Python environment is /home/user/hail-b1/venv/bin/python (requests, numpy, pillow, pyproj, pyogrio, pyarrow); pip install into your' +
  ' own venv under your directory if you need more. Earlier findings to build on: TIGER 2026 point landmarks hold only 52 school points,' +
  ' 37 hospital points and 6 places of worship for all of Montana, so they are not enough; PAD-US 4.1 Montana (109,752,792 bytes) could not' +
  ' be read from ScienceBase (a web page or 403 came back); GNIS Montana (28,354 features, 3,181 summits) has no elevation column; the' +
  ' USGS NHD map service has large-scale and small-scale flowline layers; www.usgs.gov pages return 403 to this session (use the services' +
  ' and the metadata files instead).'
const CLAIMS = { type: 'object', properties: {
  claims: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, layer: { type: 'string' }, claim: { type: 'string' },
    evidence: { type: 'string' }, source_url: { type: 'string' }, licence: { type: 'string' }, size_for_montana: { type: 'string' },
    cadence: { type: 'string' }, checked_how: { type: 'string' }, confidence: { type: 'string', enum: ['verified', 'partly verified', 'not verified'] } },
    required: ['id', 'layer', 'claim', 'evidence', 'source_url', 'licence', 'size_for_montana', 'cadence', 'checked_how', 'confidence'] } },
  summary: { type: 'string' }, blockers: { type: 'array', items: { type: 'string' } }, files: { type: 'array', items: { type: 'string' } } },
  required: ['claims', 'summary', 'blockers', 'files'] }
const landmarksPrompt = 'You verify public-domain landmark sources for the Montana Hail Watch map (schools, hospitals, places of worship,' +
  ' airports, parks), each with a Montana count and a check that these exist with a name near Missoula: Loyola Sacred Heart High School,' +
  ' Hellgate High School, Sacajawea Park, Rose Park, McCormick Park, St. Paul Lutheran church, Missoula Montana Airport, Community Medical' +
  ' Center or St. Patrick Hospital. Sources to check: (1) NCES EDGE geocodes for public schools (the Common Core of Data) and private schools' +
  ' (the Private School Survey), the EDGE open data site or its ArcGIS services (query Montana by state code 30, count, read names, note the' +
  ' licence words on the site); (2) HIFLD open data (the Homeland Infrastructure Foundation-Level Data ArcGIS Hub): Hospitals, Places of' +
  ' Worship, Fire Stations, Public and Private Schools, Aircraft Landing Facilities: for each, query Montana, count, read a few names, quote' +
  ' the licence and the source each layer credits (some are compiled from non-federal sources: say which and whether the terms allow reuse);' +
  ' (3) FAA airports (the Airport Data and Information Portal or the FAA ADIP download, or the National Transportation Atlas Database' +
  ' from the Bureau of Transportation Statistics): Montana count, names, licence; (4) PAD-US 4.1 by another route: the USGS National Map' +
  ' staged products bucket (https://prd-tnm.s3.amazonaws.com/ under StagedProducts, look for PADUS) or the PAD-US ArcGIS feature service' +
  ' (the PAD-US 4.1 "Fee" or "Combined" layers): query the Missoula box, count park polygons by designation, read names, quote the rights' +
  ' words; (5) city parks as a fallback: the TIGER area landmarks (already counted: K2180 104, K2184 101, K2188 22 statewide) and the' +
  ' Missoula County area landmark names. Write ' + out + '/landmarks/notes.md with the commands, counts and quotes. ' + rules
const terrainPrompt = 'You verify two things for the Montana Hail Watch map. (A) Summit elevations: GNIS Montana summits have no elevation' +
  ' column, so sample the USGS 3DEP elevation service at the summit point (the 3DEPElevation ImageServer identify or getSamples endpoint,' +
  ' https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer) for these peaks and compare with a published figure' +
  ' you can cite: McDonald Peak (47.38252 N, 113.91900 W), Mount Sentinel (near 46.8469 N, 113.9733 W), Granite Peak (the state high point,' +
  ' 45.1633 N, 109.8075 W), Lolo Peak, Mount Jumbo; report the sampled metres and feet and the differences; then measure how long 200' +
  ' samples take and what the service limits are (the getSamples maximum per request), so a build could tag the 3,181 summits. Also find' +
  ' the GNIS file (the Montana domestic names text file at the USGS GNIS download page or its services) and confirm whether any field' +
  ' gives elevation in the current format, and whether the older format or a service does. (B) Rivers for the low zooms: the USGS NHD map' +
  ' service (https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer): list its layers, find the small-scale flowline and' +
  ' waterbody layers, query Montana (the outline or the box -116.1,44.3,-104.1,49.1) for named features (gnis_name not null): count them,' +
  ' list the 30 longest named rivers by total length, measure the bytes of the Montana result as GeoJSON with 5-decimal coordinates and' +
  ' after a Douglas-Peucker simplification at 100 m and 500 m (pyproj and a simple simplifier, or shapely if you install it), so the' +
  ' statewide rivers for zooms 5 to 12 have a size; do the same for the large-scale named lakes over 1 km2. Quote the service copyright' +
  ' text and the USGS public-domain wording from the NHD metadata. Write ' + out + '/terrain-rivers/notes.md. ' + rules
phase('Verify')
const [landmarks, terrain] = await parallel([
  () => agent(landmarksPrompt, { label: 'verify:landmarks', phase: 'Verify', model: worker, schema: CLAIMS }),
  () => agent(terrainPrompt, { label: 'verify:peaks-rivers', phase: 'Verify', model: worker, schema: CLAIMS }),
])
const VERDICT = { type: 'object', properties: { id: { type: 'string' }, refuted: { type: 'boolean' }, reason: { type: 'string' }, evidence: { type: 'string' } },
  required: ['id', 'refuted', 'reason', 'evidence'] }
phase('Refute')
const items = []
if (landmarks) (landmarks.claims || []).forEach(c => items.push({ part: 'landmarks', c: c }))
if (terrain) (terrain.claims || []).forEach(c => items.push({ part: 'peaks-rivers', c: c }))
const verdicts = await pipeline(items, it => parallel([0, 1].map(k => () => agent(
  'You are skeptic ' + (k + 1) + ' of 2. Try to refute this claim about a public-domain data source for the Montana Hail Watch map (' +
  it.part + '). Claim ' + it.c.id + ' (' + it.c.layer + '): ' + it.c.claim + ' Evidence: ' + it.c.evidence + ' Source: ' + it.c.source_url +
  ' Licence as stated: ' + it.c.licence + ' Size as stated: ' + it.c.size_for_montana + ' Checked how: ' + it.c.checked_how + '. Make your' +
  ' own independent check (fetch the URL or a better one, re-run a count on a small sample). Judge substance: refuted=true only when the' +
  ' fact is wrong, the licence is misread, a count or size is off by more than a factor of two, or the source is unreachable for you too' +
  ' after two tries; wording quibbles are not refutations, write "stands with a note" in the reason instead. Quote what you read. ' +
  rules.replace('<your-label>', 'refute'), { label: 'refute:' + it.c.id + ':' + (k + 1), phase: 'Refute', model: worker, schema: VERDICT })))
  .then(vs => ({ part: it.part, id: it.c.id, layer: it.c.layer, claim: it.c.claim, verdicts: vs.filter(Boolean), stands: vs.filter(Boolean).filter(v => !v.refuted).length === 2 })))
log('claims: ' + items.length + '; standing: ' + verdicts.filter(Boolean).filter(v => v.stands).length)
return { landmarks, terrain, verdicts }