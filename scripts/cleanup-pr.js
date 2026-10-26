export const meta = {
  name: 'cleanup-pr',
  description: 'Remove the parked desktop app and the globe research: the docs and rules edits, two skeptics, a fixer and a verifier (D143(b))',
  phases: [{ title: 'Build' }, { title: 'Refute' }, { title: 'Fix' }, { title: 'Verify' }],
}
const BRIEF = '/home/user/wt/wt-session/briefs/cleanup-brief.md'
const WT = '/home/user/wt/wt-clean'
const REPORT = { type: 'object', properties: {
  files: { type: 'array', items: { type: 'string' } },
  checks: { type: 'array', items: { type: 'object', properties: { what: { type: 'string' }, how: { type: 'string' }, result: { type: 'string' }, evidence: { type: 'string' } }, required: ['what', 'how', 'result'] } },
  open: { type: 'array', items: { type: 'string' } },
  summary: { type: 'string' } }, required: ['files', 'checks', 'open', 'summary'] }
const FINDINGS = { type: 'object', properties: {
  findings: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, severity: { type: 'string', enum: ['blocker', 'major', 'minor'] }, file: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' } }, required: ['title', 'severity', 'evidence', 'fix'] } },
  verified_ok: { type: 'array', items: { type: 'string' } },
  summary: { type: 'string' } }, required: ['findings', 'verified_ok', 'summary'] }
const GATES = { type: 'object', properties: {
  gates: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, result: { type: 'string', enum: ['pass', 'fail'] }, output: { type: 'string' } }, required: ['name', 'result', 'output'] } },
  summary: { type: 'string' } }, required: ['gates', 'summary'] }
const common = `Read ${BRIEF} first, whole, and follow it exactly; it names the worktree (${WT}), the Python to use, the inventory file and the rulings. Work only in ${WT}. Never run a git command that writes. Every claim in your report carries the command you ran and its output.`

phase('Build')
const build = await agent(`${common}
You are the builder of the cleanup. The supervisor already removed the app, the globe research and the app icons with git rm (staged). Your job is every edit the brief's rulings 1 to 12 name: requirements.txt, the workflow rename to tests.yml, AGENTS.md, CLAUDE.md, README.md, docs/DECISIONS.md (the D143 entry and the Gotchas), docs/ROADMAP.md, docs/DESIGN.md, the research/globe citations in tests/test_storm.py, website/satellite.py and website/storm.py, and every other remaining reference ruling 11 names. Read each file's current lines before editing (the inventory's line numbers are a guide, not a fact). Write the D143 entry in the file's own voice: read D142 and the entries before it for the style (a bold label, the decision, what it replaces, what was measured). Then run the checks the brief lists and return the report.`, { label: 'cleanup:build', phase: 'Build', model: 'haiku', schema: REPORT })

phase('Refute')
const lenses = [
  { key: 'refs', prompt: `You are skeptic A: references and the suite. Independently grep the whole worktree (not .git) for every name ruling 11 lists and judge each remaining mention: fixed, history, or stale (a stale one is a finding with the file and line). Run the whole suite, the yml check and the sample build the brief lists, and read git status --short against the brief's list of deletions and edits: anything else changed or deleted is a finding. Try to refute the builder's report: a check it claims passed, re-run it.` },
  { key: 'docs', prompt: `You are skeptic B: the documents. Check the D143 entry against git facts (git log for the shas, the dates, the PR numbers in the brief), its placement and style against the entries before it, that it names what it replaces, and the one honest line about PR 12's merge message. Check AGENTS.md (rules 2 and 3 retired on one line; rules 4 to 9 keep their numbers; the layout, commands and tests entries), CLAUDE.md, README.md (the app section gone, the intro line, the contents), ROADMAP.md (the globe lines closed; the Live hail swaths row untouched), DESIGN.md (the three edits; the "## 11. " heading intact), requirements.txt against website.yml's pip line, tests.yml's content. Wording: sentence case, no em-dash (grep for the character), no AI vendor, model or product name, plain words. Each finding carries the file, the line and the words.` },
]
const refutes = await parallel(lenses.map(l => () => agent(`${common}
${l.prompt}
The builder's report: ${JSON.stringify(build)}`, { label: `cleanup:skeptic:${l.key}`, phase: 'Refute', model: 'haiku', schema: FINDINGS })))
const findings = refutes.filter(Boolean).flatMap(r => r.findings)
log(`cleanup: ${findings.length} findings from ${refutes.filter(Boolean).length} skeptics`)

phase('Fix')
let fix = null
if (findings.length) {
  fix = await agent(`${common}
You are the fixer. Verify each finding below against the files before acting (a finding you cannot reproduce is reported as "not reproduced", not fixed). Apply the ones that hold, within the brief's rulings, then re-run the whole suite and git status --short, and return the report with one line per finding: fixed, not reproduced, or declined and why.
Findings: ${JSON.stringify(findings)}`, { label: 'cleanup:fix', phase: 'Fix', model: 'haiku', schema: REPORT })
}

phase('Verify')
const verify = await agent(`${common}
You are the verifier. Run each gate and return pass or fail with the output: (1) the whole suite with the test count; (2) the yml check; (3) the sample build (remove its folder after); (4) grep for every name in ruling 11 with the judgement per remaining mention; (5) git status --short equals the brief's deletions, the rename and the edited files, nothing else; (6) no em-dash and no vendor name in the changed files; (7) the D143 entry exists once, before the Gotchas heading, and names 33cda31, ec7bfbb, 687a609 and aaf4455.`, { label: 'cleanup:verify', phase: 'Verify', model: 'haiku', schema: GATES })
return { build, refutes, fix, verify }