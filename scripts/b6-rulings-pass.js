export const meta = {
  name: 'b6-rulings-pass',
  description: 'B6 stage 2 part 1: apply the supervisor rulings D112 to D115 to each data product (one fixer, one read-only checker per product)',
  phases: [{ title: 'Fix', detail: 'one fixer per product applies the brief items' }, { title: 'Check', detail: 'one read-only checker per product verifies each item' }],
}
const worker = 'haiku'
const BRIEF = '/home/user/wt/wt-session/briefs/map-b6-rulings-pass.md'
const WT = '/home/user/wt/wt-b6'
const PY = '/home/user/hail-b1/venv/bin/python'
const ITEM = { type: 'object', properties: { id: { type: 'string' }, state: { type: 'string', enum: ['applied', 'already so', 'not applied'] },
  evidence: { type: 'string' }, reason: { type: 'string' } }, required: ['id', 'state', 'evidence'] }
const REPORT = { type: 'object', properties: { product: { type: 'string' }, items: { type: 'array', items: ITEM },
  files_changed: { type: 'array', items: { type: 'string' } }, tests: { type: 'string' }, py_compile: { type: 'string' },
  integration_md: { type: 'string' }, open: { type: 'array', items: { type: 'string' } } },
  required: ['product', 'items', 'files_changed', 'tests', 'py_compile', 'integration_md', 'open'] }
const VERDICT = { type: 'object', properties: { id: { type: 'string' }, pass: { type: 'boolean' }, evidence: { type: 'string' } }, required: ['id', 'pass', 'evidence'] }
const CHECK = { type: 'object', properties: { product: { type: 'string' }, verdicts: { type: 'array', items: VERDICT }, tests: { type: 'string' },
  suite: { type: 'string' }, fixtures_private_scan: { type: 'string' }, words_scan: { type: 'string' }, notes: { type: 'string' } },
  required: ['product', 'verdicts', 'tests', 'suite', 'fixtures_private_scan', 'words_scan', 'notes'] }
const PRODUCTS = (args && args.products) || [
  { key: 'P1', module: 'terrain', files: 'website/terrain.py, tests/test_terrain.py, tests/fixtures/terrain/' },
  { key: 'P2', module: 'basemap2', files: 'website/basemap2.py, tests/test_basemap2.py, tests/fixtures/basemap2/' },
  { key: 'P3', module: 'landmarks', files: 'website/landmarks.py, tests/test_landmarks.py, tests/fixtures/landmarks/' },
  { key: 'P4', module: 'history_layers and labels', files: 'website/history_layers.py, website/labels.py, tests/test_history_layers.py, tests/test_labels.py, tests/fixtures/history_layers/, tests/fixtures/labels/' },
]
const common = (p) => ' The worktree is ' + WT + ' (branch claude/map-b6); the Python is ' + PY + '. Read the brief ' + BRIEF + ' first, in full, then the' +
  ' product section for ' + p.key + ' (' + p.module + '). You may edit only these files: ' + p.files + '. Never run a git write command (no add, commit,' +
  ' stash, checkout, reset). The shared files (website/build.py, website/sources.py, the workflows, website/templates/about.html, docs/) are not yours:' +
  ' write what they need into /home/user/hail-b5/out/b6/build/' + p.key + '/integration.md (append a dated section "Rulings pass (D112 to D115)").' +
  ' No AI model, vendor or product names in repository files; no em-dashes (the character U+2014); sentence case; plain words.'
const fixPrompt = (p) => 'You are the fixer for product ' + p.key + ' of the B6 map build.' + common(p) +
  ' Apply every item of your product section exactly as written; where an item is already so, say so with the line; where you judge an item wrong for the code,' +
  ' do not apply it and give the reason (the supervisor rules). Add or update a test for every behaviour change (the tests are offline; fixtures small).' +
  ' Then run ' + PY + ' -m py_compile on every file you touched and ' + PY + ' -m unittest tests.test_<module> -v for each test module of the product' +
  ' (both must pass; fix until they do). Return the report: items with state, evidence (file:line or test name) and reason, files changed, the test output summary,' +
  ' the py_compile result, what you wrote into integration.md, and what is open for the supervisor.'
const checkPrompt = (p, fix) => 'You are the read-only checker for product ' + p.key + ' of the B6 map build.' + common(p) +
  ' You edit nothing in the worktree (you may write scratch under /home/user/hail-b5/out/b6/build/' + p.key + '/rulings-check/ and must delete it at the end).' +
  ' The fixer reported: ' + JSON.stringify(fix) + '. Verify every item of the product section yourself against the code, not the report: read the lines,' +
  ' run ' + PY + ' -m unittest tests.test_<module> -v for each test module of the product, then the whole suite ' + PY + ' -m unittest discover -s tests' +
  ' (report the counts and any failure by name). Scan the product fixtures for private fields: grep -i -E "owner|manager|phone|contact|e-?mail|[0-9]{3}-[0-9]{3}-[0-9]{4}"' +
  ' over text fixtures and the field names of any shapefile or zip fixture. Scan the product files for the em-dash character, for the words "lag" or "read through"' +
  ' in printed words, for vendor or model names, and for a credit line that lacks the "Source:" or "courtesy of" form or implies endorsement.' +
  ' An item passes only when the code shows it; "already so" claims are checked the same way. Return the verdicts with evidence per item, the test and suite results,' +
  ' the two scans and notes.'
phase('Fix')
const results = await pipeline(PRODUCTS,
  p => agent(fixPrompt(p), { label: 'fix:' + p.key, phase: 'Fix', model: worker, schema: REPORT }),
  (fix, p) => agent(checkPrompt(p, fix), { label: 'check:' + p.key, phase: 'Check', model: worker, schema: CHECK }).then(check => ({ product: p.key, fix, check })))
const out = results.filter(Boolean)
const failing = out.flatMap(r => (r.check && r.check.verdicts || []).filter(v => !v.pass).map(v => r.product + ':' + v.id))
log('rulings pass: ' + out.length + ' products; failing items: ' + (failing.length ? failing.join(', ') : 'none'))
return { products: out, failing }
