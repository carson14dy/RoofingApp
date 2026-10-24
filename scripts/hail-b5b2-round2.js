export const meta = {
  name: 'hail-b5b2-round2',
  description: 'B5 part B2, round 2: per owner named in args.items (browser, site, products, smoke), a builder with the round-2 items, a read-only reviewer, two skeptics per finding, a fixer and a final check; owners flow independently',
  phases: [{ title: 'Build' }, { title: 'Review' }, { title: 'Skeptics' }, { title: 'Fix' }, { title: 'Check' }],
}
const WT = (args && args.wt) || '/home/user/wt/wt-b5'
const BRIEF = '/home/user/wt/briefs/hail-b5-brief.md'
const VENV = '/home/user/hail-b1/venv/bin/python'
const STORE = (args && args.store) || '/home/user/hail-b5/out/combined/store'
const OUT = (args && args.out) || '/home/user/hail-b5/out/b2r2'
const WORKER = (args && args.worker) || 'worker'
const ITEMS = (args && args.items) || {}
const FILES = {
  browser: { n: 1, files: 'website/static/map/map.js, website/static/map/map.css and website/templates/map.html (a hook only)' },
  site: { n: 2, files: 'website/build.py, website/summary.py, tests/test_site.py and tests/test_summary.py' },
  products: { n: 3, files: 'website/joins.py, website/stations.py, website/sources.py, tests/test_joins.py, tests/test_stations.py and tests/test_snowgrid.py, and website/data/hail-fixture only through the fixture command (swapped in by one rename) with the fixture tests of tests/test_hail.py' },
  smoke: { n: 4, files: 'tools/smoke_map.py, tools/smoke_pages.py, .github/workflows/website.yml, .github/workflows/hail-store.yml, tests/test_website_workflow.py and tests/test_hail_workflow.py' },
  docs: { n: 5, files: 'docs/DECISIONS.md, docs/DESIGN.md, docs/ROADMAP.md, README.md, AGENTS.md, website/templates/about.html, website/addresses.py (its About words only) and research/hail-history/validation-evidence/b5-verification.json' },
}
const COMMON = (o) => 'You work in the git worktree ' + WT + ' (branch claude/hail-b5), on the merged tree (B3 streets, outlines, dots and search; B4 live swath layers; B5 history) after the first part B2 round. Read ' + BRIEF + ' first: the Product section and the "Product north star", the rulings D1 to D71 (D59 to D71 rule on part B2 and are your instructions), and the section "Part B2 build list (steps 3 to 5)" whose owner ' + o.n + ' you are; the first round\'s check files under /home/user/hail-b5/out/b2/<owner>/check.json and /home/user/hail-b5/out/b2/products-fix/check.json say what was done and what was left. Other owners edit other files in this worktree now: edit only ' + o.files + '; never run a git write command (add, commit, checkout, restore, reset, stash, merge, push); scratch and builds only under ' + OUT + '/' + o.key + '/ which you create (one site build at a time, deleted when checked; store copies are full copies, one at a time, because the store\'s files are immutable and refuse hard links); the combined store ' + STORE + ' is read-only. Python is ' + VENV + ' (Chromium at /opt/pw-browsers/chromium for Playwright). Rules (AGENTS.md is in your context): Python first; hand-written JavaScript only for browser-only needs, documented inline; the browser carries no literal sentence, unit, threshold, constant or colour (D29, D41: every word comes from map.json); evidence honesty (kinds apart, never damage, insurance or an all-clear; missing is never zero; a failed part never reads as an absence; every unavailable, partial and held line ends "This is not an all-clear."); plain words in sentence case; no em-dashes; no model, AI-vendor or AI-product names in repository files; tests with every behaviour change; decision 6 and D12 (no owner, parcel, place-type or building-use field read, stored or shown). Return a plain report: what you built (file and line), the commands you ran with their tails, what you measured, and two lists: "needed from the <other> owner" (exact keys, texts or checks) and "not done" with reasons.'
const build = (o) => agent(COMMON(o) + '\n\nYou are the builder for owner ' + o.n + ' (' + o.key + ') in round 2. Your items: ' + o.extra + ' Run the tests of your files and ' + VENV + ' -m unittest discover -s tests at the end (tail; name every failure and whose it is).', { label: 'build:' + o.key, phase: 'Build', model: WORKER })
const FINDINGS = { type: 'object', properties: { findings: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, file: { type: 'string' }, line: { type: 'integer' }, claim: { type: 'string' }, evidence: { type: 'string' }, severity: { type: 'string', enum: ['blocking', 'should', 'nit'] }, owner: { type: 'string' } }, required: ['id', 'file', 'claim', 'evidence', 'severity', 'owner'] } }, measurements: { type: 'object' }, tests_tail: { type: 'string' } }, required: ['findings', 'tests_tail'] }
const review = (o, built) => agent(COMMON(o) + '\n\nYou are the read-only reviewer for owner ' + o.n + ' (' + o.key + '): never edit a repository file. The builder reported:\n' + built + '\n\nRead every change of the owner\'s files (git diff HEAD -- <files>) against the owner\'s round-2 items (' + o.extra + '), the Product section and the rulings; run the owner\'s tests and the build or smoke the items name; measure what the gates ask (sizes, counts, texts). Report each defect as a finding with the file and line, the claim, the evidence (a command tail, a measured value, a quoted text) and the owner it belongs to (this owner or another), severity blocking (a gate or rule fails), should (a brief item not met) or nit. No finding without evidence you produced.', { label: 'review:' + o.key, phase: 'Review', model: WORKER, schema: FINDINGS })
const VERDICT = { type: 'object', properties: { id: { type: 'string' }, defect_real: { type: 'boolean' }, refuted: { type: 'boolean' }, reason: { type: 'string' } }, required: ['id', 'defect_real', 'refuted', 'reason'] }
const skeptic = (o, f, k) => agent(COMMON(o) + '\n\nYou are skeptic ' + k + ' (read-only; never edit a repository file). Try to refute this review finding by reproducing its evidence yourself: ' + JSON.stringify(f) + '. refuted=true when the evidence does not reproduce, the claim misreads the brief or the rulings, or the behaviour is what the brief asks; defect_real=true only when you reproduced the defect. Give the command or text that decides it.', { label: 'skeptic:' + o.key + ':' + f.id + ':' + k, phase: 'Skeptics', model: WORKER, schema: VERDICT })
const fix = (o, confirmed) => agent(COMMON(o) + '\n\nYou are the fixer for owner ' + o.n + ' (' + o.key + '). Fix each of these confirmed findings in your files (findings that belong to another owner are listed back under "needed from the <other> owner", untouched): ' + JSON.stringify(confirmed) + '. Keep the rulings; add or update tests; run the owner\'s tests and the full suite (tail).', { label: 'fix:' + o.key, phase: 'Fix', model: WORKER })
const check = (o) => agent(COMMON(o) + '\n\nYou are the final checker for owner ' + o.n + ' (' + o.key + '), read-only. Re-run the owner\'s tests and the gates of the build list that this owner\'s files decide; write ' + OUT + '/' + o.key + '/check.json with {items: [{item, status: done|partial|not done, evidence}], gates: [{gate, status, evidence}], needed_from_others: [...], tests_tail} and return it as text.', { label: 'check:' + o.key, phase: 'Check', model: WORKER })
const owners = Object.keys(ITEMS).filter((k) => FILES[k]).map((k) => Object.assign({ key: k, extra: ITEMS[k] }, FILES[k]))
if (!owners.length) { log('no owners named in args.items'); return { owners: [] } }
const results = await pipeline(
  owners,
  (o) => build(o).then((r) => ({ o, built: (r || '').slice(0, 12000) })),
  async (s) => { const r = await review(s.o, s.built); return Object.assign(s, { review: r }) },
  async (s) => {
    const fs = (s.review && s.review.findings) || []
    const judged = await parallel(fs.map((f) => () => parallel([1, 2].map((k) => () => skeptic(s.o, f, k))).then((vs) => ({ f, vs: vs.filter(Boolean) }))))
    const ok = judged.filter(Boolean)
    const confirmed = ok.filter((j) => j.vs.length && j.vs.every((v) => v.defect_real && !v.refuted)).map((j) => j.f)
    log(s.o.key + ': ' + fs.length + ' findings, ' + confirmed.length + ' confirmed')
    return Object.assign(s, { confirmed, judged: ok.map((j) => ({ id: j.f.id, verdicts: j.vs })) })
  },
  async (s) => { const mine = s.confirmed.filter((f) => new RegExp(s.o.key + '|owner ' + s.o.n, 'i').test(f.owner || '') || !Object.keys(FILES).some((k) => new RegExp(k, 'i').test(f.owner || ''))); const r = mine.length ? await fix(s.o, mine) : 'no confirmed findings of this owner'; return Object.assign(s, { fixed: (r || '').slice(0, 8000), cross: s.confirmed.filter((f) => !mine.includes(f)) }) },
  async (s) => { const r = await check(s.o); return { owner: s.o.key, built: s.built, review: s.review, judged: s.judged, confirmed: s.confirmed, fixed: s.fixed, cross: s.cross, check: (r || '').slice(0, 12000) } },
)
return results.filter(Boolean)
