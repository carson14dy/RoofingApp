export const meta = {
  name: 'b6-integrator',
  description: 'B6 stage 2 phase B: integrate the four data products into the shared files (build.py, sources.py, the jobs, About, docs, tests), then a local build and smoke, then review, refute, fix and check',
  phases: [{ title: 'Integrate', detail: 'four integrators over the shared files, then the build and smoke' }, { title: 'Review', detail: 'two reviewers, two skeptics per finding, a fixer and a checker' }],
}
const worker = 'haiku'
const BRIEF = '/home/user/wt/wt-session/briefs/map-b6-integrator-brief.md'
const RULINGS = '/home/user/wt/wt-session/briefs/hail-b5-brief.md'
const RULINGS_PASS = '/home/user/wt/wt-session/briefs/map-b6-rulings-pass.md'
// D116 to D125 are in the brief file after D115; the integrator brief carries the additions.
const WT = '/home/user/wt/wt-b6'
const PY = '/home/user/hail-b1/venv/bin/python'
const OUT = '/home/user/hail-b5/out/b6/build/integrator'
const REPORT = { type: 'object', properties: { task: { type: 'string' }, files_changed: { type: 'array', items: { type: 'string' } },
  done: { type: 'array', items: { type: 'string' } }, tests: { type: 'string' }, open: { type: 'array', items: { type: 'string' } },
  for_next: { type: 'string' } }, required: ['task', 'files_changed', 'done', 'tests', 'open', 'for_next'] }
const FINDINGS = { type: 'object', properties: { findings: { type: 'array', items: { type: 'object', properties: {
  id: { type: 'string' }, severity: { type: 'string', enum: ['high', 'medium', 'low'] }, file: { type: 'string' }, line: { type: 'integer' },
  claim: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' } }, required: ['id', 'severity', 'file', 'line', 'claim', 'evidence', 'fix'] } } },
  required: ['findings'] }
const VERDICT = { type: 'object', properties: { id: { type: 'string' }, refuted: { type: 'boolean' }, reason: { type: 'string' } }, required: ['id', 'refuted', 'reason'] }
const CHECK = { type: 'object', properties: { suite: { type: 'string' }, selftest: { type: 'string' }, build: { type: 'string' }, manifest: { type: 'string' },
  smoke: { type: 'string' }, words: { type: 'string' }, verdicts: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, fixed: { type: 'boolean' },
  evidence: { type: 'string' } }, required: ['id', 'fixed', 'evidence'] } }, open: { type: 'array', items: { type: 'string' } } },
  required: ['suite', 'selftest', 'build', 'manifest', 'smoke', 'words', 'verdicts', 'open'] }
const common = ' The worktree is ' + WT + ' (branch claude/map-b6); the Python is ' + PY + '. Read first: ' + BRIEF + ' (the integrator brief, in full), the' +
  ' supervisor rulings in ' + RULINGS + ' from the heading "B6: the owner\'s map reference" to the end (D106 to D126) and ' + RULINGS_PASS + ', and the four' +
  ' products\' integration.md and report.md under /home/user/hail-b5/out/b6/build/P1..P4/. Never run a git write command (no add, commit, stash, checkout, reset).' +
  ' Keep every product module (website/terrain.py, basemap2.py, landmarks.py, history_layers.py, labels.py and their tests) as it is: the shared files are yours.' +
  ' No AI model, vendor or product names in repository files; no em-dashes (U+2014); sentence case; plain words; every credit line reads "Source: ..." or' +
  ' "... data courtesy of ..." and never implies endorsement (D113(a)); a missing input shows "Data unavailable", never a zero or an all-clear (rule 5);' +
  ' every string the browser prints comes from map.json or from the data file map.json names (data/base.json), both built by Python (D29, D41, D125(d));' +
  ' held kinds and sources show "held" with the reason and no number derived from them appears anywhere (D118(b)); the About sentences are in the "Source: ..." form' +
  ' built from the modules\' labelled credit lines (D121(a)); an unbuilt band D tile is said both ways (D122(b)). Run ' + PY + ' -m py_compile on every Python file you touch and the tests named for your task.' +
  ' Write your notes for the next integrator into ' + OUT + '/<task>.md.'
const TASKS = {
  I1: 'Task 1 of the brief as amended by D125(d) (website/build.py: HAIL_FOLDERS_B6, _copy_hail, a small first-paint pointer block "base" in map.json (the tile URL templates,' +
    ' zooms, state, the as_of and the name of the second file) and a second Python-built data file data/base.json that carries the blocks "base" (bands, cells, the landmark' +
    ' shard pattern, peaks and places files, credit lines, held kinds and sources with reasons, the words the browser prints, the legend lines), "history_layers", "recent"' +
    ' and the label flags\' words and budgets; map.json stays under its 163,840-byte raw gate; the identity rule for a build without the new parts covers both files) and the' +
    ' test pins for it in tests/test_site.py (the copy list, the keys of both files, the identity of the sample build, the raw size gate). The words come from the product' +
    ' modules\' WORDS, CREDIT and SOURCES constants where they exist (import them; do not retype), so the browser prints the modules\' words. Run ' + PY + ' -m unittest tests.test_site -v and fix until green.',
  I2: 'Task 2 and task 5 of the brief (website/sources.py: one CONTRACTS row per source from the integration notes with the words corrected by D112(c), D113(b), D113(c),' +
    ' D113(d); website/templates/about.html: one sentence per source with its credit line under the hail history headings, the landmark kinds with the held kinds and' +
    ' sources and their reasons, the five-year pictures, the zone counts with the newest-warning date words, the recent radar hail switch) and their pins in' +
    ' tests/test_site.py (the rows exist; the About words). The previous integrator\'s notes are in ' + OUT + '/I1.md: tests/test_site.py already carries its pins, so' +
    ' extend, never rewrite. Run ' + PY + ' -m unittest tests.test_site tests.test_sources -v (whichever exist) and fix until green.',
  I3: 'Task 3 and task 4 of the brief (.github/workflows/hail-store.yml: the monthly job runs P1 (terrain build --refresh --timeout 60 under a 20-minute step cap, non-fatal, the' +
    ' cache restored and saved, verify --timeout 60) and P2 (bands A to C each run, band D continued under the step\'s deadline with --deadline-at; the step reads vector.state from' +
    ' hail/base/index.json because build exits 0 for an unavailable store), each with its verify and its unavailable mark; the store writers run one after another; the daily' +
    ' job runs P3 (landmarks), P4 history_layers and recent after the joins, and the labels pass after the outlines step, all non-fatal on the B5 clock with the clock' +
    ' checks the other B5 steps use; pyshp installed for the parks source; the pack and the manifest check cover the new folders; hail.check_manifest after the last' +
    ' part; the buildings verify stays before the labels pass. .github/workflows/website.yml: on.push.paths and the offline unittest line list the five new test modules; the parity step unchanged;' +
    ' .gitignore gains terrain-cache/, b6-cache/ and !tests/fixtures/**/*.zip; AGENTS.md\'s website install line gains pyshp) and the pins in' +
    ' tests/test_website_workflow.py (PushPathsCoverTheTests must pass). Run ' + PY + ' -m unittest tests.test_website_workflow -v and fix until green.',
  I4: 'Task 6 of the brief (docs): docs/DECISIONS.md gains D107 to D126 as the D38 round\'s next bullets in the style of D101 to D105 (copy the rulings\' substance,' +
    ' not the brief\'s headings; keep every figure with its unit); docs/DESIGN.md gains section 13 "The map\'s own cartography, the options sheet and the value bubbles' +
    ' (B6)" with the store layout, the bands, the budgets, the picture palettes (from the products\' integration notes, as named constants with hex values), the sheet' +
    ' spec from /home/user/hail-b5/out/b6/design/sheet/spec.md with D110 applied, the bubble rule (A clusters by default, B per building as the owner\'s alternative)' +
    ' and the D115 amendments to section 8 (land cover tint and relief at zooms 5 to 10 fading through 12, paper white from 13; hidden in dark mode); docs/ROADMAP.md' +
    ' gains the B6 row and the owner items (bubble rule A or B and the below-side option, the sheet, the terrain tint veto, the kv wording, the landmark display names, the cold-run' +
    ' figure, issued-only zone counts, the split threshold and flag bytes, the NLCD CC0 question) and the counsel items (21 to 24, the TIGER area landmark use constraints, the' +
    ' PAD-US and FEMA terms, the Forest Service hazard DUA); README.md\'s layout and commands lines name' +
    ' the new modules. Run ' + PY + ' -m unittest tests.test_docs -v if it exists.',
  I5: 'Tasks 7 and 8 of the brief: run the whole suite ' + PY + ' -m unittest discover -s tests (must pass; fix only shared files and their pins if not, and say what) and' +
    ' ' + PY + ' desktop/launcher.py --selftest payload; make one writable copy of the adopted store\'s index, manifest and the folders the site build reads' +
    ' (/home/user/hail-b5/out/combined/store is read only) under /home/user/hail-b5/out/b6/store-copy, then build the new parts in place, one writer after another, from the product' +
    ' caches (P1 terrain build --offline from /home/user/hail-b5/out/b6/cache/P1; P2 basemap2 build --offline from cache/P2; P3 landmarks build --offline from cache/P3; P4 history_layers' +
    ' build and the labels pass for the Missoula and Billings tiles only; each writer carries the shared base index key f hail-base-index-v1; no base index with the old format key may' +
    ' exist first), check map.json stays under 163,840 bytes raw, run' +
    ' ' + PY + ' -m website.build --out /home/user/hail-b5/out/b6/site --hail-history --hail-addresses --hail-store /home/user/hail-b5/out/b6/store-copy --now' +
    ' 2026-10-17T12:00:00Z, run hail.check_manifest on the copy, run the Chromium smoke tools/smoke_map.py with --addresses --history against the built site and' +
    ' record the phone view bytes, and write ' + OUT + '/report.md with every figure (bytes, counts, seconds), the suite result, the selftest result and what is open.' +
    ' Delete the store copy\'s large folders you added when done if disk is under 3 GB free (df -h /home/user).',
}
const integrate = (key, prev) => agent('You are integrator ' + key + ' of the B6 map build.' + common + ' Your task: ' + TASKS[key] +
  (prev ? ' The previous integrators reported: ' + JSON.stringify(prev) : '') + ' Return: the task, the files changed, what was done, the test output summary, what is open, and notes for the next integrator.',
  { label: 'integrate:' + key, phase: 'Integrate', model: worker, schema: REPORT })
phase('Integrate')
const [i12, i3, i4] = await parallel([
  () => integrate('I1').then(r1 => integrate('I2', [r1]).then(r2 => [r1, r2])),
  () => integrate('I3'),
  () => integrate('I4'),
])
const first = [...(i12 || []), i3, i4].filter(Boolean)
const i5 = await integrate('I5', first)
const reports = [...first, i5].filter(Boolean)
log('integration: ' + reports.length + ' of 5 reports')
phase('Review')
const LENSES = [
  { key: 'rules', prompt: 'the rules: rule 5 (missing never zero, "Data unavailable", not an all-clear), D29/D41 (every printed word from map.json), D113(a) credits, the identity rule for builds without the new parts, no vendor or model names, no em-dashes, sentence case, the workflow pins' },
  { key: 'correctness', prompt: 'correctness: every key of map.json and data/base.json the integration notes name exists with the right shape and words, map.json stays under its 163,840-byte raw gate, the copy list copies the new folders and states absences, the CONTRACTS rows match the modules, the jobs\' steps call the modules with the options they accept (read the argparse of each module), the store writers run in sequence with the shared base index key, the test pins test the behaviour, the docs figures match the reports' },
]
const reviews = await parallel(LENSES.map(l => () => agent('You are a read-only reviewer of the B6 integration on the shared files.' + common +
  ' Review the uncommitted changes to the shared files (git diff and git status are read-only and allowed) through ' + l.prompt + '. The integrators reported: ' +
  JSON.stringify(reports) + '. Return findings with file and line and the fix; severity high for a wrong number, a missed failure path or a rule breach, medium for a' +
  ' wrong word or a missing pin, low for style. No finding for matters of taste. Delete any scratch you make.',
  { label: 'review:' + l.key, phase: 'Review', model: worker, schema: FINDINGS })))
const findings = reviews.filter(Boolean).flatMap((r, i) => (r.findings || []).map(f => ({ ...f, id: LENSES[i].key + '-' + f.id })))
log('review: ' + findings.length + ' findings')
const refuted = await pipeline(findings, f => parallel([1, 2].map(n => () => agent('You are skeptic ' + n + ' of 2. Try to refute this review finding on the B6' +
  ' integration (read-only; git diff is allowed; delete any scratch).' + common + ' Finding ' + f.id + ' (' + f.severity + ', ' + f.file + ':' + f.line + '): ' + f.claim +
  ' Evidence: ' + f.evidence + ' Proposed fix: ' + f.fix + '. Check it yourself in the code (run the test or a snippet); refuted=true when the finding is wrong, not' +
  ' required by the brief or the rulings, or already so; refuted=false only when the code shows the defect.',
  { label: 'refute:' + f.id + ':' + n, phase: 'Review', model: worker, schema: VERDICT }))).then(vs => ({ f, standing: vs.filter(Boolean).filter(v => !v.refuted).length >= 1 })))
const standing = refuted.filter(Boolean).filter(r => r.standing).map(r => r.f)
log('standing after refutation: ' + standing.length + ' of ' + findings.length)
const fix = standing.length ? await agent('You are the fixer of the B6 integration.' + common + ' Apply these standing findings, each exactly as its fix says unless the' +
  ' code shows a better minimal fix (say so): ' + JSON.stringify(standing) + '. Edit shared files and their pins only. Run the tests of every file you touch and then' +
  ' the whole suite ' + PY + ' -m unittest discover -s tests; fix until green. Return the report.', { label: 'fix:integration', phase: 'Review', model: worker, schema: REPORT }) : null
const check = await agent('You are the final read-only checker of the B6 integration.' + common + ' The fixer reported: ' + JSON.stringify(fix) + ' for the standing findings ' +
  JSON.stringify(standing) + '. Run the whole suite ' + PY + ' -m unittest discover -s tests, ' + PY + ' desktop/launcher.py --selftest payload, the build command of task 8' +
  ' against /home/user/hail-b5/out/b6/store-copy if it exists (else say so), hail.check_manifest on that copy, and the smoke tools/smoke_map.py --addresses --history;' +
  ' scan the shared files for em-dashes, vendor or model names, "lag" and "read through" in printed words, and credit lines without the "Source:" or "courtesy of" form;' +
  ' confirm each standing finding is fixed with evidence. Return the results and what is open. Delete scratch you make.',
  { label: 'check:integration', phase: 'Review', model: worker, schema: CHECK })
return { reports, findings, standing, fix, check }
