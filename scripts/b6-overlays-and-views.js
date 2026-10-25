export const meta = {
  name: 'b6-overlays-and-views',
  description: 'Side-by-side views of our map against the owner\'s reference screenshots, the per-house bubble measurements, and the live-verified sources for the risk layers (fire, air, heat, flood, wind, hail); then skeptics',
  phases: [{ title: 'Measure', detail: 'views and bubbles; risk sources' }, { title: 'Refute', detail: 'two skeptics per source claim; one critic for the views' }],
}
const worker = args.worker
const out = args.out
const site = args.site
const uploads = args.uploads
const rules = 'Rules: never run git write commands; do not edit files under /home/user/wt; write only under ' + out + '/<your-label>/; disk is limited' +
  ' (about 5 GB free), download little and delete after measuring; read downloaded JSON with python -I; verify content, not just HTTP 200;' +
  ' every claim needs a source URL and how you checked it; plain words, sentence case, no em-dashes, no AI model or vendor names in files.'
const VIEWS = { type: 'object', properties: {
  views: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, reference: { type: 'string' }, ours_png: { type: 'string' },
    composite_png: { type: 'string' }, zoom: { type: 'number' }, center: { type: 'string' }, missing_in_ours: { type: 'array', items: { type: 'string' } },
    present_in_ours: { type: 'array', items: { type: 'string' } } }, required: ['name', 'reference', 'ours_png', 'composite_png', 'zoom', 'center', 'missing_in_ours', 'present_in_ours'] } },
  bubbles: { type: 'object', properties: { dots_in_block_view: { type: 'number' }, buildings_in_block_view: { type: 'number' }, zoom_of_block_view: { type: 'number' },
    value_available_per_house: { type: 'string' }, same_value_shared_by_neighbours: { type: 'string' }, label_fit_estimate: { type: 'string' }, budget_note: { type: 'string' } },
    required: ['dots_in_block_view', 'buildings_in_block_view', 'zoom_of_block_view', 'value_available_per_house', 'same_value_shared_by_neighbours', 'label_fit_estimate', 'budget_note'] },
  summary: { type: 'string' }, problems: { type: 'array', items: { type: 'string' } } }, required: ['views', 'bubbles', 'summary', 'problems'] }
const CLAIMS = { type: 'object', properties: {
  claims: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, layer: { type: 'string' }, claim: { type: 'string' }, evidence: { type: 'string' },
    source_url: { type: 'string' }, licence: { type: 'string' }, size_or_cadence: { type: 'string' }, checked_how: { type: 'string' },
    confidence: { type: 'string', enum: ['verified', 'partly verified', 'not verified'] } },
    required: ['id', 'layer', 'claim', 'evidence', 'source_url', 'licence', 'size_or_cadence', 'checked_how', 'confidence'] } },
  summary: { type: 'string' }, blockers: { type: 'array', items: { type: 'string' } } }, required: ['claims', 'summary', 'blockers'] }
const viewsPrompt = 'You are a measurement worker for the Montana Hail Watch website (repo /home/user/wt/wt-b5). The owner sent ten reference' +
  ' screenshots of Apple Maps inside the Zillow app and wants our Map page to look and work like them. A local build of our site with every' +
  ' layer on (the history, the address dots, the storm layers) is being written to ' + site + '; wait until the file ' + site + '/../build.done' +
  ' exists (poll every 20 s, up to 25 minutes; the log is ' + site + '/../build.log). Then serve it (python -m http.server from the site folder on a' +
  ' free port) and drive it in Chromium with Playwright from /home/user/hail-b1/venv/bin/python (tools/smoke_map.py in the repo shows how the' +
  ' map page is opened and the address search used; if the bundled browser is not found, launch with executable_path=/opt/pw-browsers/chromium).' +
  ' Use a 390 by 844 viewport, device scale factor 2. The reference files, in order: ' + uploads.join(', ') + '. The first is the Map options sheet;' +
  ' the second is the block view with a price bubble on every house around Brooks St, Blaine St and E Florence St in Missoula (the slant streets);' +
  ' the third the neighbourhood around Loyola Sacred Heart High School and Rockin Rudy\'s; the fourth the city (Missoula label, McCormick Park, the' +
  ' University of Montana); the fifth the wider city (I-90, MT 200, Fort Missoula Park, Mount Sentinel); the sixth the metro (the airport, Orchard' +
  ' Homes, US 93, 12, 200); the seventh the region (Frenchtown, Lolo, Florence); the eighth the wider region (the Flathead Indian Reservation,' +
  ' Seeley Lake, Hamilton, Philipsburg, the Bitterroot National Forest); the ninth eastern Montana (Fort Peck, Fort Belknap and Crow reservations,' +
  ' Billings); the tenth the state (Great Falls, Helena, Butte, Bozeman, the Blackfeet reservation). For each of the eight map views (2 to 10,' +
  ' skipping 9 if our map cannot reach it): find the matching centre on our map (use the site\'s own address search for Blaine St or E Florence St' +
  ' in Missoula for the close views; the town list for the others), pick the zoom that shows the same extent, screenshot our map (the map only,' +
  ' with the dots and outlines visible at the close zooms), and compose a side-by-side PNG (reference left, ours right, same height, a one-line' +
  ' caption with the zoom) with Pillow into ' + out + '/views/. List for each view what the reference shows that ours lacks (points of interest' +
  ' with icons, hillshade, reservations, national forests, parks, route shields, river names, place labels, the price bubbles) and what ours has' +
  ' that the reference lacks. Then measure the bubble question on the block view: how many dots and building outlines are in the 390 px view at' +
  ' the dots\' top zoom (count from the tile files the page fetched, hail/b/ or hail/a/, or from the page\'s own counters), which per-house value' +
  ' our store could print in a bubble (read website/summary.py and hail/t/<tile>.json for the radar cell\'s largest hail in five years or its' +
  ' count of 1 inch days; note that the radar value is per 1 km cell, so neighbouring houses share one value, and say how many distinct cells' +
  ' the block view spans), whether a 5 to 7 character label fits over each dot without overlap at that zoom (estimate from the dot spacing in' +
  ' pixels), and what the labels would add to the per-tile file sizes. Also screenshot our current layer menu and the hail sheet for a house' +
  ' tap at the block view, into ' + out + '/views/. ' + rules
const sourcesPrompt = 'You are a sources worker for the Montana Hail Watch website (repo /home/user/wt/wt-b5; read AGENTS.md rule 5 on evidence' +
  ' honesty and rule 7 on feeds). The owner wants risk-layer chips on the map like Zillow\'s Flood, Fire, Wind, Air and Heat, plus our Hail. Each' +
  ' chip would colour the map by a public-domain or permissive dataset, labelled by its kind. For each layer, verify live and record: the' +
  ' candidate dataset(s), the exact download or tile URL, the licence or terms (quote), the format, the size for Montana, the update cadence,' +
  ' and what the layer can honestly say (never "no risk"). Layers: HAIL: our own store (hail/t/ tile files hold the radar MESH days per cell for' +
  ' five years; website/hail.py describes them; the climate grid under hail/c/ and the zone products under hail/z/ exist too): state what a' +
  ' per-cell choropleth (days with hail of 1 inch or more in five years, or the largest size) needs from the store and whether it can be a' +
  ' pre-rendered PNG per zoom like the radar frames website/gridded.py draws. HEAT: the nClimGrid-daily grid already in hail/c/ (count of days' +
  ' at or over 90 F per cell) and, as an alternative, NOAA\'s climate normals; WIND: the NWS high wind zone products already in hail/z/ (count' +
  ' per forecast zone) and the station gust records; FLOOD: the NWS flood warnings and watches already in the store per zone and county, the' +
  ' FEMA National Flood Hazard Layer (NFHL) as a map service (quote its terms; the project record says FEMA flood zones were left out with' +
  ' reasons in docs/DECISIONS.md D38, find and quote the reason), and the USGS or NWS flood inundation maps; FIRE: NIFC fire perimeters' +
  ' (current and historic, the NIFC Open Data ArcGIS services), MTBS burn severity, and the USFS Wildfire Risk to Communities (wildfirerisk.org,' +
  ' the "wildfire hazard potential" raster, public domain); AIR: EPA AirNow (API key, free; the data terms), the NOAA HMS smoke polygons' +
  ' (public domain), and PurpleAir (terms, not public domain). For each dataset fetch a real sample (a small bounding box or one file) and' +
  ' confirm the content, not just the status. Also note for every layer the words the chip could use and the sentence the legend must carry' +
  ' (what the data is, from whom, how old). Write ' + out + '/risk-sources/notes.md with the commands, the quotes and the sizes. ' + rules
phase('Measure')
const [views, sources] = await parallel([
  () => agent(viewsPrompt, { label: 'measure:views', phase: 'Measure', model: worker, schema: VIEWS }),
  () => agent(sourcesPrompt, { label: 'measure:risk-sources', phase: 'Measure', model: worker, schema: CLAIMS }),
])
const VERDICT = { type: 'object', properties: { id: { type: 'string' }, refuted: { type: 'boolean' }, reason: { type: 'string' }, evidence: { type: 'string' } },
  required: ['id', 'refuted', 'reason', 'evidence'] }
phase('Refute')
const claims = (sources && sources.claims) || []
const verdicts = await pipeline(claims, c => parallel([0, 1].map(k => () => agent(
  'You are skeptic ' + (k + 1) + ' of 2. Try to refute this claim about a risk-layer data source for the Montana Hail Watch map. Claim ' + c.id +
  ' (' + c.layer + '): ' + c.claim + ' Evidence: ' + c.evidence + ' Source: ' + c.source_url + ' Licence as stated: ' + c.licence +
  ' Size or cadence as stated: ' + c.size_or_cadence + ' Checked how: ' + c.checked_how + '. Make your own independent check (fetch the URL or' +
  ' a better one, re-run a measurement); refuted=true when the claim is wrong, overstated, out of date, legally misread, or when you cannot' +
  ' verify it yourself; refuted=false only when your own check confirms it. Quote what you read. ' + rules.replace('<your-label>', 'refute'),
  { label: 'refute:' + c.id + ':' + (k + 1), phase: 'Refute', model: worker, schema: VERDICT })))
  .then(vs => ({ id: c.id, layer: c.layer, claim: c.claim, verdicts: vs.filter(Boolean), stands: vs.filter(Boolean).filter(v => !v.refuted).length === 2 })))
const CRITIC = { type: 'object', properties: { ok: { type: 'boolean' }, problems: { type: 'array', items: { type: 'string' } }, checked: { type: 'array', items: { type: 'string' } } }, required: ['ok', 'problems', 'checked'] }
const critic = views ? await agent('You are a critic. The views worker reported: ' + JSON.stringify(views).slice(0, 6000) + '. Open every composite PNG it' +
  ' names (Read the image files), check that each really shows the reference on the left and our map on the right at a comparable extent, that' +
  ' the close views show our dots and outlines, that the missing-and-present lists match what the pictures show, and that the bubble figures' +
  ' are backed by files it names (re-count one). Report problems precisely. ' + rules.replace('<your-label>', 'critic'),
  { label: 'critic:views', phase: 'Refute', model: worker, schema: CRITIC }) : null
log('source claims: ' + claims.length + '; standing: ' + verdicts.filter(Boolean).filter(v => v.stands).length + '; views ok: ' + (critic && critic.ok))
return { views, sources, verdicts, critic }