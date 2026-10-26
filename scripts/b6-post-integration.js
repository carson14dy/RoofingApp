export const meta = {
  name: 'b6-post-integration',
  description: 'B6 stage 2: the post-integration fix round on the product files and the monthly terrain step (D128), one fixer per product in parallel, then one read-only checker over all of them',
  phases: [{ title: 'Fix', detail: 'four fixers, one per product' }, { title: 'Check', detail: 'one read-only checker' }],
}
const worker = 'haiku'
const WT = '/home/user/wt/wt-b6'
const PY = '/home/user/hail-b1/venv/bin/python'
const ITEM = { type: 'object', properties: { id: { type: 'string' }, state: { type: 'string', enum: ['applied', 'already so', 'not applied'] }, evidence: { type: 'string' }, reason: { type: 'string' } }, required: ['id', 'state', 'evidence'] }
const REPORT = { type: 'object', properties: { product: { type: 'string' }, items: { type: 'array', items: ITEM }, files_changed: { type: 'array', items: { type: 'string' } }, tests: { type: 'string' }, open: { type: 'array', items: { type: 'string' } } }, required: ['product', 'items', 'files_changed', 'tests', 'open'] }
const CHECK = { type: 'object', properties: { verdicts: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, pass: { type: 'boolean' }, evidence: { type: 'string' } }, required: ['id', 'pass', 'evidence'] } }, suite: { type: 'string' }, notes: { type: 'string' } }, required: ['verdicts', 'suite', 'notes'] }
const common = (files) => ' The worktree is ' + WT + ' (branch claude/map-b6); the Python is ' + PY + '. You may edit only these files: ' + files + '. Never run a git write command (no add, commit, stash, checkout, reset). Make no network request.' +
  ' No AI model, vendor or product names in repository files; no em-dashes (U+2014); sentence case; plain words; a missing input shows "Data unavailable", never a zero or an all-clear (rule 5).' +
  ' The integrator has finished: website/build.py reads the modules\' WORDS, CREDIT and SOURCES constants into data/base.json and map.json, and tests/test_site.py pins them, so after your change run ' + PY + ' -m unittest tests.test_site -v as well as your module\'s tests, and fix your module (never build.py or test_site.py) until both pass; if a pin in test_site.py must change because of your item, say so in open and stop there.'
const JOBS = [
  { key: 'P1', files: 'website/terrain.py, tests/test_terrain.py, .github/workflows/hail-store.yml, tests/test_hail_workflow.py', module: 'terrain', items:
    'A1 (D128(f)): add a --refresh-descriptions option to the terrain build: it re-reads the two service descriptions (the 3DEP description with its data date and the NLCD coverage description with its date keyword) and otherwise uses a valid cached tile whatever its age, so a data month that has not changed costs no tile request and a changed month re-fetches through the cache key as today; --refresh keeps its meaning (every tile again); a test for each. ' +
    'A2 (D128(f)): in .github/workflows/hail-store.yml the monthly terrain step runs with --refresh-descriptions (not --refresh) and --timeout 60 under a 25-minute cap (CAP 1500 s, the deadline 120 s earlier), and the docstring of terrain.py and its integration note say so; the pins in tests/test_hail_workflow.py follow (the cap, the flag); run ' + PY + ' -m unittest tests.test_hail_workflow -v.' },
  { key: 'P2', files: 'website/basemap2.py, tests/test_basemap2.py', module: 'basemap2', items:
    'B1 (D128(b), D117(b)): every unavailable or partial sentence in WORDS (unavailable, part_unavailable, partial_named, peaks_unknown, band_d_water_partial and any other sentence that describes a missing or partial input) begins with the words "Data unavailable." and keeps its D20 wording and its closing "This is not an all-clear."; a test asserts the words on each such sentence.' },
  { key: 'P3', files: 'website/landmarks.py, tests/test_landmarks.py', module: 'landmarks', items:
    'C1 (D128(e)): landmarks.py writes its block into the hail/index.json "base" mirror as terrain.py and basemap2.py do (read their _mirror or equivalent and follow the same shape: state, as_of, counts, sources, bytes, the held block with null counts), keeping the other parts\' mirror blocks and writing only its own key; the unavailable command mirrors its unavailable block; a test shows the mirror after a build and after unavailable, with the other two blocks surviving.' },
  { key: 'P4', files: 'website/history_layers.py, website/labels.py, tests/test_history_layers.py, tests/test_labels.py', module: 'history_layers and labels', items:
    'D1 (D128(a)): one bubble legend: the printed legend is the D110(c) sentence that website/build.py puts in labels.words.legend (read build.py\'s BUBBLE_LEGEND or the words it uses); the module\'s own label_legend text in history_layers.WORDS is replaced by that exact sentence (so there is one text) or removed if nothing reads it; the test follows. ' +
    'D2 (D128(b), D117(b)): every unavailable or partial sentence in history_layers.WORDS and labels words (unavailable, outline_unavailable and any sentence that describes a missing or partial input) begins with "Data unavailable." and keeps its wording and its closing "This is not an all-clear."; a test asserts the words.' },
]
phase('Fix')
const fixes = await parallel(JOBS.map(j => () => agent('You are the post-integration fixer for product ' + j.key + ' of the B6 map build.' + common(j.files) + ' Items: ' + j.items +
  ' Apply each item exactly as written (already so with the line where it is); add or update tests; run ' + PY + ' -m py_compile on every Python file you touch and ' + PY + ' -m unittest tests.test_' + j.module.split(' ')[0] + ' -v' + (j.key === 'P4' ? ' and tests.test_labels -v' : '') + ' (must pass), then tests.test_site -v. Return the items with state and evidence, the files changed, the test summary and what is open.',
  { label: 'fix:' + j.key, phase: 'Fix', model: worker, schema: REPORT })))
phase('Check')
const check = await agent('You are the read-only checker of the post-integration round of the B6 map build.' + common('nothing (you edit nothing; scratch under /home/user/hail-b5/out/b6/build/post-check/ only, deleted at the end)') +
  ' The fixers reported: ' + JSON.stringify(fixes.filter(Boolean)) + '. Verify every item against the code (read the lines, run each product\'s tests, run ' + PY + ' -m unittest tests.test_site tests.test_hail_workflow tests.test_website_workflow -v), then the whole suite ' + PY + ' -m unittest discover -s tests (report counts and every failure by name), and scan the changed files for em-dashes and vendor or model names. Return verdicts with evidence, the suite result and notes.',
  { label: 'check:post', phase: 'Check', model: worker, schema: CHECK })
return { fixes: fixes.filter(Boolean), check, failing: (check && check.verdicts || []).filter(v => !v.pass).map(v => v.id) }
