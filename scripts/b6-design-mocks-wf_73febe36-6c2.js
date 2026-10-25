export const meta = {
  name: 'b6-design-mocks',
  description: 'Design mocks in the site\'s own design for the Map options sheet, the value bubbles per house and the risk legends, rendered in Chromium at phone size, with a Python label-placement measurement; then a critic against DESIGN.md and the owner\'s reference behaviours',
  phases: [{ title: 'Design', detail: 'sheet mock; bubbles and placement' }, { title: 'Critique', detail: 'one critic per mock' }],
}
const worker = args.worker
const out = args.out
const site = args.site
const rules = 'Rules: never run git write commands; do not edit files under /home/user/wt; write only under ' + out + '/<your-label>/; plain words,' +
  ' sentence case, no em-dashes, no AI model or vendor names in files; colours only from the tokens in website/static/style.css (never a' +
  ' new hex value); the site\'s fonts from website/static/fonts; every hazard colour carries its word; an unavailable value reads' +
  ' "Data unavailable" or "--", never 0; nothing implies "no hail" or "no risk". The Python environment is /home/user/hail-b1/venv/bin/python' +
  ' with Playwright (if the bundled browser is missing, launch Chromium with executable_path=/opt/pw-browsers/chromium).'
const context = 'Context: the Montana Hail Watch website, repo /home/user/wt/wt-b6 (read docs/DESIGN.md sections 1, 8, 9 and 10 and' +
  ' website/static/map/map.css for the current layer menu and sheet styles). The owner sent screenshots of a phone map app and wants our' +
  ' Map page to work like it, in our own design: a "Map options" sheet with base map choices (Map, Satellite; no 3D), chips for the live' +
  ' layers (Precipitation, Temperature, Wind gusts, Hail last hour, Hail last 24 hours), chips for five-year risk layers (Hail, Heat, Wind,' +
  ' Flood, later Fire and Smoke), chips for landmarks (Schools, Parks, Hospitals, Airports, Churches; businesses are not available from' +
  ' public-domain data), a "Points of interest" switch, a "Highlight recent hail" switch (buildings in cells with a radar estimate of 1 inch' +
  ' or more in the last 30 days), the existing Warnings and Storm reports switches, and a Reset button; and at the closest zooms a value' +
  ' bubble on every house (the 1 km radar cell\'s largest five-year estimate such as "0.39 in", or "--" when nothing of 0.25 in or more' +
  ' was stored; every house in a cell shares its value and the sheet says so). The reference sheet is /root/.claude/uploads/' +
  '7638440a-a008-5ef8-a289-86be0a23e7a7/16cd4c34-image.jpg and the reference block view /root/.claude/uploads/' +
  '7638440a-a008-5ef8-a289-86be0a23e7a7/7f2067ec-image.jpg (for behaviour and structure only, never for colours or type). A local build' +
  ' of our site with every layer on is at ' + site + ' (serve it with python -m http.server from that folder); our block-view capture is' +
  ' /home/user/hail-b5/out/ref/views/ours-v02-block-z17.00.png and the layer menu capture /home/user/hail-b5/out/ref/views/layers-menu-ours-390x844.png.'
const MOCK = { type: 'object', properties: { pictures: { type: 'array', items: { type: 'object', properties: { path: { type: 'string' }, what: { type: 'string' },
  width: { type: 'number' }, height: { type: 'number' }, theme: { type: 'string' } }, required: ['path', 'what', 'width', 'height', 'theme'] } },
  spec: { type: 'string' }, measurements: { type: 'object', additionalProperties: true }, problems: { type: 'array', items: { type: 'string' } },
  files: { type: 'array', items: { type: 'string' } } }, required: ['pictures', 'spec', 'measurements', 'problems', 'files'] }
const sheetPrompt = context + ' YOUR JOB: the Map options sheet mock. Write a standalone HTML page under ' + out + '/sheet/ that uses' +
  ' website/static/style.css and map.css (copy them beside the page, unchanged) and shows, over our block-view capture as the background,' +
  ' the Map options sheet in the site\'s design: a header with a layers icon and the title, a close button, a row of base map pictograms' +
  ' (Map selected, Satellite; no 3D), the chip groups with headings in this order: Live weather; Five-year risks (Hail, Heat, Wind, Flood;' +
  ' Fire and Smoke greyed with "coming" in plain words); Landmarks (Schools, Parks, Hospitals, Airports, Churches); then the switches' +
  ' Points of interest, Highlight recent hail, Warnings, Storm reports, each with its one-line description in the muted text (the words' +
  ' the current layer menu uses for Warnings and Storm reports, read them in the site\'s map.html or map.js words); a Reset button; every' +
  ' control reachable at 44 px minimum; the sheet scrolls inside itself when taller than the screen. Render it in Chromium at 390 by' +
  ' 844 (scale 2) and at 1280 by 800, light and dark (prefers-color-scheme), screenshot each, and compose a side-by-side with the' +
  ' reference sheet (reference left, ours right). Write a short spec (the states of a chip: off, on, unavailable with reason; the' +
  ' legend line a chip opens; what Reset restores; how the sheet replaces the current layer menu in map.js, naming the functions and' +
  ' the data-* hooks the Python template would write) as spec.md. ' + rules
const bubblePrompt = context + ' YOUR JOB: the value bubbles and their placement. (1) From the local site, read the building shards and' +
  ' the radar cell values for the block view (centre 46.86016, -113.99992): the page fetched hail/b/ shards for the dots at zoom 17 (see' +
  ' website/buildings.py for the shard format and the dot positions) and hail/t/ shards for the cell values (website/hail.py, the largest' +
  ' value per cell over the five seasons: use website/summary.py or the index as the rule for "largest radar hail estimate"). (2) Write' +
  ' a Python label placement: for zoom 17 and zoom 18 compute each dot\'s pixel position, make a bubble label of the cell\'s value text' +
  ' ("0.39 in" or "--") in the site\'s bold 13 px type (measure the text width with Pillow and the site font), place bubbles greedily in' +
  ' a deterministic order (by value descending then by position), skipping any that would overlap an already placed bubble by more than' +
  ' 2 px, and report how many of the dots get a bubble at each zoom and in each of the four cells; also compute the variant where every' +
  ' house in a cell shows the value once per cell cluster (one bubble per visible cluster of houses) and say which reads better. (3)' +
  ' Draw the result over our block capture with Pillow in the site\'s design (a dark ink bubble with white text and a small pointer, the' +
  ' tokens from style.css: ink-950 on white, sky-700 for a selected house), at zoom 17 (use the capture) and describe zoom 18. (4) Write' +
  ' the data format proposal: per-building label flags per zoom written by Python into the building shards (bytes added, measured on' +
  ' the four shards of this view) versus the browser thinning at draw time (what JavaScript it needs), and recommend one with the' +
  ' reason, under the rule that Python does the work where it can. Save pictures and a bubbles.md under ' + out + '/bubbles/. ' + rules
phase('Design')
const [sheet, bubbles] = await parallel([
  () => agent(sheetPrompt, { label: 'design:sheet', phase: 'Design', model: worker, schema: MOCK }),
  () => agent(bubblePrompt, { label: 'design:bubbles', phase: 'Design', model: worker, schema: MOCK }),
])
const CRITIC = { type: 'object', properties: { ok: { type: 'boolean' }, problems: { type: 'array', items: { type: 'string' } }, strengths: { type: 'array', items: { type: 'string' } }, checked: { type: 'array', items: { type: 'string' } } }, required: ['ok', 'problems', 'strengths', 'checked'] }
phase('Critique')
const critics = await parallel([
  () => sheet ? agent('You are a design critic. Read docs/DESIGN.md sections 1 and 8 in /home/user/wt/wt-b6 (the field-sheet look, tokens' +
    ' only, sentence case, 44 px targets, nothing to decode, every hazard colour carries its word) and the owner\'s reference sheet' +
    ' /root/.claude/uploads/7638440a-a008-5ef8-a289-86be0a23e7a7/16cd4c34-image.jpg (behaviour and structure only). The sheet designer' +
    ' reported: ' + JSON.stringify(sheet).slice(0, 5000) + '. Open every picture (Read the image files) and the HTML; check the tokens' +
    ' (grep the page and its CSS for hex values that are not in style.css), the contrast in dark mode, the tap targets, the words, that no' +
    ' chip implies an all-clear, that unavailable chips say why, and that the sheet matches the reference\'s structure without copying its' +
    ' look. List concrete problems and strengths. ' + rules.replace('<your-label>', 'critic-sheet'),
    { label: 'critic:sheet', phase: 'Critique', model: worker, schema: CRITIC }) : null,
  () => bubbles ? agent('You are a critic for evidence honesty and placement. Read AGENTS.md rule 5 and docs/DESIGN.md section 9 in' +
    ' /home/user/wt/wt-b6. The bubbles worker reported: ' + JSON.stringify(bubbles).slice(0, 5000) + '. Open its pictures and re-run its' +
    ' placement script once (it must be deterministic: the same counts twice); check that a cell with no stored value reads "--" and never' +
    ' 0, that the counts per cell are backed by the shards it names, that the recommended data format follows the Python-first rule, and' +
    ' that the bubble text has its unit. List concrete problems and strengths. ' + rules.replace('<your-label>', 'critic-bubbles'),
    { label: 'critic:bubbles', phase: 'Critique', model: worker, schema: CRITIC }) : null,
])
log('sheet ok: ' + (critics[0] && critics[0].ok) + '; bubbles ok: ' + (critics[1] && critics[1].ok))
return { sheet, bubbles, critics }