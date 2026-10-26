export const meta = {
  name: 'b6-continue-product',
  description: 'B6 stage 2 part 1 continuation for one product: refute the review findings still pending (two skeptics each), then the fixer on the standing findings, then the checker (the same prompts as the build workflow)',
  phases: [{ title: 'Review', detail: 'the pending refutes, the fixer and the checker' }],
}
const worker = args.worker
const brief = args.brief
const wt = args.wt
const out = args.out
const p = args.product
const rules = 'Rules: never run git write commands (git diff and git status are fine); edit only the files your product owns (listed) and' +
  ' the test module you own; shared files are the integrator\'s (write what they need into integration.md); no AI model, vendor or' +
  ' product names in repository files; no em-dashes; sentence case; plain words; a missing input shows "Data unavailable", never a zero' +
  ' or an all-clear; the adopted store ' + args.store + ' is read only (chattr +i): make a small writable test store under your output folder' +
  ' by copying hail/index.json, hail/manifest.json and only the folders your product reads, and run your build against that copy;' +
  ' downloads go under /home/user/hail-b5/out/b6/cache/<product>/ keyed so a second run reads the cache, under 1 GB per product, scratch' +
  ' deleted; tests offline with small fixtures (under 200 KB) that skip when an optional package is absent; the Python environment is' +
  ' /home/user/hail-b1/venv/bin/python; run python -m py_compile on every file you touch and python -m unittest tests.test_<module>' +
  ' before you finish, and the whole suite once (python -m unittest discover -s tests, about 8 minutes) to confirm nothing else broke.'
const readOnly = rules.replace('edit only the files your product owns (listed) and the test module you own', 'edit nothing')
const REPORT = { type: 'object', properties: { files_written: { type: 'array', items: { type: 'string' } }, tests: { type: 'string' },
  measurements: { type: 'object', additionalProperties: true }, open_points: { type: 'array', items: { type: 'string' } },
  integration_md: { type: 'string' }, report_md: { type: 'string' } }, required: ['files_written', 'tests', 'measurements', 'open_points', 'integration_md', 'report_md'] }
const VERDICT = { type: 'object', properties: { id: { type: 'string' }, refuted: { type: 'boolean' }, reason: { type: 'string' }, evidence: { type: 'string' } }, required: ['id', 'refuted', 'reason', 'evidence'] }
const CHECK = { type: 'object', properties: { tests: { type: 'string' }, suite: { type: 'string' }, verify: { type: 'string' }, measurements: { type: 'object', additionalProperties: true },
  budgets_met: { type: 'boolean' }, problems: { type: 'array', items: { type: 'string' } } }, required: ['tests', 'suite', 'verify', 'measurements', 'budgets_met', 'problems'] }
phase('Review')
const pending = args.pending || []
log(p.key + ': ' + pending.length + ' findings still to refute; ' + (args.standing || []).length + ' already standing')
const items = await parallel(pending.map(f => () => parallel([0, 1].map(k => () => agent(
  'You are skeptic ' + (k + 1) + ' of 2 on a review finding for product ' + p.key + ' in ' + wt + ' (read the brief ' + brief + ' and the' +
  ' code). Finding ' + f.id + ' (' + f.severity + ', ' + f.file + ':' + f.line + '): ' + f.claim + ' Evidence: ' + f.evidence + ' Proposed fix: ' +
  f.fix + '. Check it yourself in the code (run the test or a snippet); refuted=true when the finding is wrong, not required by the brief' +
  ' or the rules, or already handled; refuted=false when it holds. Write nothing in the worktree. ' + readOnly,
  { label: 'refute:' + p.key + ':' + f.id + ':' + (k + 1), phase: 'Review', model: worker, schema: VERDICT }))).then(vs => ({ f: f, stands: vs.filter(Boolean).filter(v => !v.refuted).length >= 1, verdicts: vs }))))
const newly = items.filter(Boolean).filter(i => i.stands).map(i => i.f)
const standing = [...(args.standing || []), ...newly]
log(p.key + ': standing after refutation ' + standing.length + ' (' + newly.length + ' new)')
const fix = standing.length ? await agent('You are the fixer of product ' + p.key + ' in ' + wt + '. Apply these review findings that survived' +
  ' two skeptics, each exactly as its fix says unless the code shows a better minimal fix (say so): ' + JSON.stringify(standing) +
  '. Re-run the product\'s tests and py_compile. Update ' + out + '/' + p.key + '/report.md with what changed. You own: ' + p.files.join(', ') + '. ' + rules,
  { label: 'fix:' + p.key, phase: 'Review', model: worker, schema: REPORT }) : null
const check = await agent('You are the checker of product ' + p.key + ' in ' + wt + '. Run its tests, the whole suite once (python -m unittest' +
  ' discover -s tests), the product\'s verify command against the builder\'s test store under ' + out + '/' + p.key + '/, and re-measure' +
  ' the budgets the brief ' + brief + ' sets; compare with ' + out + '/' + p.key + '/measurements.json; list every problem. Write' +
  ' ' + out + '/' + p.key + '/check.json. Edit nothing in the worktree. ' + readOnly,
  { label: 'check:' + p.key, phase: 'Review', model: worker, schema: CHECK })
return { product: p.key, pending_refuted: items.filter(Boolean).map(i => ({ id: i.f.id, stands: i.stands, verdicts: i.verdicts })), standing: standing, fix: fix, check: check }
