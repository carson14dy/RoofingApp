export const meta = {
  name: 'b6-browser-s2',
  description: 'B6 browser stage S2: the base map drawn (terrain tiles, vector bands, places, summits, credits), refuted by three skeptics, fixed and verified',
  phases: [{ title: 'Build' }, { title: 'Refute' }, { title: 'Fix' }, { title: 'Verify' }],
}
const BRIEF = '/home/user/wt/wt-session/briefs/b6-browser-brief.md'
const S2 = '/home/user/wt/wt-session/briefs/b6-s2-brief.md'
const WT = '/home/user/wt/wt-b6b'
const SITE = '/home/user/hail-b5/out/b6b/site'
const REPORT = { type: 'object', properties: {
  files: { type: 'array', items: { type: 'string' } },
  words_added: { type: 'object', additionalProperties: { type: 'string' } },
  tests: { type: 'object', properties: { added: { type: 'array', items: { type: 'string' } }, updated: { type: 'array', items: { type: 'string' } }, command: { type: 'string' }, result: { type: 'string' } } },
  checks: { type: 'array', items: { type: 'object', properties: { what: { type: 'string' }, how: { type: 'string' }, result: { type: 'string' }, evidence: { type: 'string' } }, required: ['what', 'how', 'result'] } },
  figures: { type: 'object' },
  shots: { type: 'array', items: { type: 'string' } },
  open: { type: 'array', items: { type: 'string' } },
  summary: { type: 'string' } }, required: ['files', 'checks', 'open', 'summary'] }
const FINDINGS = { type: 'object', properties: {
  findings: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, severity: { type: 'string', enum: ['blocker', 'major', 'minor'] }, file: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' } }, required: ['title', 'severity', 'evidence', 'fix'] } },
  verified_ok: { type: 'array', items: { type: 'string' } },
  summary: { type: 'string' } }, required: ['findings', 'verified_ok', 'summary'] }
const GATES = { type: 'object', properties: {
  gates: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, result: { type: 'string', enum: ['pass', 'fail'] }, output: { type: 'string' } }, required: ['name', 'result', 'output'] } },
  figures: { type: 'object' },
  summary: { type: 'string' } }, required: ['gates', 'summary'] }
const common = `Read ${BRIEF} first, whole (the programme, the rules, the commands, the rulings after S1), then ${S2}, whole (the S2 rulings, what S2 draws, its checks). Work only in ${WT}; the one site directory is ${SITE}. Never run a git command that writes. Never read map.js, smoke_map.py, test_site.py or basemap2.py whole: grep -n for names and sed -n ranges. Read the format docstrings in website/basemap2.py and website/terrain.py before drawing. Every claim in your report carries the command you ran and its output, or a screenshot path.`

phase('Build')
const build = await agent(`${common}
You are the builder of stage S2. Steps, in order: (1) study the S1 code you build on: in map.js the boot, start, createMap, pane, drawBasemap, tidyLabels, placeCrowded, the options hooks (toggleOptions, renderOptions, setBase) and how data/base.json is fetched and kept; in map.html the script tags and the sheet's base map line (#mo-base-line); in map.css the token blocks; in build.py the map page context (SHEET_WORDS, the base pointer). (2) Read the data: the built site's data/map.json base block and data/base.json base block (tiles, zooms, vector tiles and zooms, credit, problem sentences), a band A file, a band B cell, a band C cell, a band D shard, places.json and peaks.json under ${SITE}/hail/base/, and the terrain tiles' folder shape. (3) Write website/static/map/layers.js per the S2 brief (the header, the interface with map.js, the terrain layers, the band fetcher and cache, the canvas drawing, the places and summit labels, the credits, the base map line), the roles in map.css, the script tag and the interface in map.js and map.html, and the tests. (4) Build the site in full, serve on port 8601, and run the Chromium checks of the S2 brief at the four zooms, light and dark, with screenshots; measure the figures of ruling (b). (5) Add check_base_map to tools/smoke_map.py and run the whole smoke. Return the report with the figures.`, { label: 's2:build', phase: 'Build', model: 'haiku', schema: REPORT })

phase('Refute')
const lenses = [
  { key: 'words', port: 8611, prompt: `You are skeptic A: words and rules. Try to refute: rule 1 (grep layers.js and the changed lines of map.js for any literal sentence, label, unit or credit; every word must come from data/base.json or map.json), ruling (c) (no hex in a drawing call; every role present in both token blocks; dark values readable), ruling (d) (a part with state unavailable draws nothing; test it by editing a copy of base.json in a scratch folder is not possible on the served site, so read the code paths and the tests instead), rule 10 (nothing outside the stage's files: git status --short, git diff --stat), the tests (run PY -m unittest tests.test_site and quote the tail).` },
  { key: 'draw', port: 8612, prompt: `You are skeptic B: the drawing. Serve the built site and in Chromium at 390 by 844 and 1280 by 800, light and dark, at zooms 6, 9, 12 and 15 over Billings and at zoom 7 over the whole state: check that the right band files and tiles are requested and nothing else, that the canvas draws (pixel samples) and that the drawn kinds match the data (count a few features in the fetched band file against what you see), that each feature appears only from its minimum zoom, that the terrain fades through zooms 11 and 12 and is hidden in dark mode, that the labels do not overlap town labels and are 13 px or more, that the credit lines are in the attribution exactly as the data gives them, that the sheet's base map line shows the right sentence for a band D tile not built (find one from base.json's coverage), redraw times under 50 ms, no console error. Save screenshots.` },
  { key: 'budget', port: 8613, prompt: `You are skeptic C: budgets and requests. Measure yourself: layers.js gzip bytes; in Chromium at 390 by 844, every response fetched for the zoom 15 Billings view and for a zoom 8 statewide view, grouped into B3 files, the B3 shell, and the B6 files (layers.js, data/base.json, hail/base/*), with gzip bytes and the page total; compare with the builder's figures. Check that the band cache evicts under its cap when you pan across the state at zoom 9 (count requests and cached bytes through the interface the builder exposed or the network), that no request leaves the site, that a pan at zoom 15 makes fewer requests than the smoke's PAN_FETCH_LIMIT, and run the smoke's check_base_map and check_budget_and_pan (the whole smoke if time allows) and quote their notes.` },
]
const refutes = await parallel(lenses.map(l => () => agent(`${common}
${l.prompt} Your server port is ${l.port}; start your own server and kill its pid when done. Each finding carries its evidence (a command and its output, or a screenshot path) and the fix you propose; a finding without evidence is not a finding.
The builder's report: ${JSON.stringify(build)}`, { label: `s2:skeptic:${l.key}`, phase: 'Refute', model: 'haiku', schema: FINDINGS })))
const findings = refutes.filter(Boolean).flatMap(r => r.findings)
log(`s2: ${findings.length} findings from ${refutes.filter(Boolean).length} skeptics`)

phase('Fix')
let fix = null
if (findings.length) {
  fix = await agent(`${common}
You are the fixer of stage S2. Verify each finding below against the files and the page before acting (a finding you cannot reproduce is reported as "not reproduced", not fixed). Apply the ones that hold within the rules (Python words first), re-run PY -m unittest tests.test_site, rebuild or copy the static files into the site as the brief says, re-check in Chromium at 390 and 1280 px at zooms 9 and 15, and return the report with one line per finding: fixed, not reproduced, or declined and why. Your server port is 8602.
Findings: ${JSON.stringify(findings)}`, { label: 's2:fix', phase: 'Fix', model: 'haiku', schema: REPORT })
}

phase('Verify')
const verify = await agent(`${common}
You are the verifier of stage S2. Rebuild the site in full, then run each gate and return pass or fail with the output and the figures: (1) PY -m unittest tests.test_site; (2) the whole smoke with its summary and every failure quoted, and the budget note's B3, shell, B6 and page total figures; (3) a Chromium pass at 390 by 844 and 1280 by 800, light and dark, at zooms 6, 9, 12 and 15 over Billings: the canvas draws, the expected files only, no off-site request, no console error, terrain hidden in dark mode, credits present, redraw under 50 ms; (4) grep layers.js and the changed map.js lines for literal sentences (none); (5) layers.js gzip bytes and the B6 files' gzip bytes at zoom 15 and zoom 8; (6) git status --short lists only website/static/map/layers.js, website/static/map/map.js, website/static/map/map.css, website/templates/map.html, website/build.py (if a word was added), tests/test_site.py and tools/smoke_map.py. Your server port is 8603.`, { label: 's2:verify', phase: 'Verify', model: 'haiku', schema: GATES })
return { build, refutes, fix, verify }