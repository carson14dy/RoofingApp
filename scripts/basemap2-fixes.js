export const meta = {
  name: 'basemap2-fixes',
  description: 'Fix the base map vectors that never load on main: the verify path crash and the water fetch deadline, with live measurements, two skeptics, a fixer and a verifier',
  phases: [{ title: 'Investigate and fix' }, { title: 'Refute' }, { title: 'Fix' }, { title: 'Verify' }],
}
const BRIEF = '/home/user/wt/wt-session/briefs/basemap2-fixes-brief.md'
const WT = '/home/user/wt/wt-bm2'
const REPORT = { type: 'object', properties: {
  files: { type: 'array', items: { type: 'string' } },
  measurements: { type: 'array', items: { type: 'object', properties: { what: { type: 'string' }, url_or_params: { type: 'string' }, status: { type: 'string' }, seconds: { type: 'number' }, features: { type: 'number' } }, required: ['what', 'status', 'seconds'] } },
  changes: { type: 'array', items: { type: 'string' } },
  tests: { type: 'object', properties: { added: { type: 'array', items: { type: 'string' } }, updated: { type: 'array', items: { type: 'string' } }, command: { type: 'string' }, result: { type: 'string' } } },
  checks: { type: 'array', items: { type: 'object', properties: { what: { type: 'string' }, how: { type: 'string' }, result: { type: 'string' }, evidence: { type: 'string' } }, required: ['what', 'how', 'result'] } },
  open: { type: 'array', items: { type: 'string' } },
  summary: { type: 'string' } }, required: ['files', 'changes', 'checks', 'open', 'summary'] }
const FINDINGS = { type: 'object', properties: {
  findings: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, severity: { type: 'string', enum: ['blocker', 'major', 'minor'] }, file: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' } }, required: ['title', 'severity', 'evidence', 'fix'] } },
  verified_ok: { type: 'array', items: { type: 'string' } },
  summary: { type: 'string' } }, required: ['findings', 'verified_ok', 'summary'] }
const GATES = { type: 'object', properties: {
  gates: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, result: { type: 'string', enum: ['pass', 'fail'] }, output: { type: 'string' } }, required: ['name', 'result', 'output'] } },
  summary: { type: 'string' } }, required: ['gates', 'summary'] }
const common = `Read ${BRIEF} first, whole, and follow it exactly: it names the worktree (${WT}), the Python, the runner logs, the three facts and the tasks A to D. Work only in ${WT}. Never run a git command that writes. Never read a large file whole: grep -n and sed -n ranges. Every claim in your report carries the command you ran and its output. Scratch files go under /tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/bm2/<your label>/ and are removed when you finish.`

phase('Investigate and fix')
const build = await agent(`${common}
You are the investigator and builder. Do tasks A, B, C and D of the brief in that order: the verify path fix with its regression test (fail before, pass after), the live measurements of the water queries (three timed requests each, one at a time, with the module's own request builders), the reading of the deadline and retry rules, the smallest change that makes the water load inside the monthly budget on a slow service, the local cold-cache measurement with --deadline-at now plus 1,020 s, and the checks. Label: builder.`, { label: 'bm2:build', phase: 'Investigate and fix', model: 'haiku', schema: REPORT })

phase('Refute')
const lenses = [
  { key: 'rootcause', prompt: `You are skeptic A: the root cause and the verify fix. Reproduce the runner's crash on the unfixed code (git stash is a write: instead, read the diff with git diff and reason, or copy the original function from git show HEAD:website/basemap2.py into a scratch file to run it against a tiny store) and confirm the new test fails without the fix and passes with it; search the module for any other place where a path under the store or the cache is joined to the store or cache again (grep for "store /" and "cache /" near glob or rglob); run PY -m unittest tests.test_basemap2 and quote its tail; check that nothing outside the brief's files changed (git status --short, git diff --stat).` },
  { key: 'water', prompt: `You are skeptic B: the water change. Re-measure the water queries live yourself (one at a time, the module's pacing) and compare with the builder's figures; read the change and try to refute that it keeps the module's contract (the CONTRACTS rows in website/sources.py, the formats, the band budgets, the pacing and one request at a time per host, the credit lines), that a partial build still reads partial and never loaded, that the deadline is still honoured (no request starts in the last 120 seconds), and that the docstring states every new rule and a test pins it. Run the builder's local cold-cache build command again if its scratch cache is gone, or read its figures from its report and the state file it names; quote the state, water_bands_failed, seconds and requests.` },
]
const refutes = await parallel(lenses.map(l => () => agent(`${common}
${l.prompt} Each finding carries its evidence (a command and its output) and the fix you propose; a finding without evidence is not a finding.
The builder's report: ${JSON.stringify(build)}`, { label: `bm2:skeptic:${l.key}`, phase: 'Refute', model: 'haiku', schema: FINDINGS })))
const findings = refutes.filter(Boolean).flatMap(r => r.findings)
log(`bm2: ${findings.length} findings from ${refutes.filter(Boolean).length} skeptics`)

phase('Fix')
let fix = null
if (findings.length) {
  fix = await agent(`${common}
You are the fixer. Verify each finding below against the files before acting (a finding you cannot reproduce is reported as "not reproduced", not fixed). Apply the ones that hold within the brief's tasks, re-run PY -m unittest tests.test_basemap2, and return the report with one line per finding: fixed, not reproduced, or declined and why.
Findings: ${JSON.stringify(findings)}`, { label: 'bm2:fix', phase: 'Fix', model: 'haiku', schema: REPORT })
}

phase('Verify')
const verify = await agent(`${common}
You are the verifier. Run each gate and return pass or fail with the output: (1) PY -m unittest tests.test_basemap2; (2) the whole suite PY -m unittest discover -s tests with its count; (3) from a scratch working directory where the store is the relative path "store", the job's commands as .github/workflows/hail-store.yml writes them for the monthly base map step and its verify (build with --deadline-at now plus 300 s into a cold scratch cache, then verify --store store --cache <cache>): the verify exits 0 and the index state is partial or loaded, never unavailable, and the "store/store" path never appears; (4) git status --short lists only website/basemap2.py, tests/test_basemap2.py and, if the brief allowed it, website/sources.py, docs or the workflow with tests/test_hail_workflow.py; (5) no em-dash and no vendor name in the changed lines (git diff -U0 | grep '^+'); (6) the docstring names each new rule the diff adds. Remove your scratch store and cache after.`, { label: 'bm2:verify', phase: 'Verify', model: 'haiku', schema: GATES })
return { build, refutes, fix, verify }