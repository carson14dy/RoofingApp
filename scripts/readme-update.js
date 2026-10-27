export const meta = {
  name: 'readme-update',
  description: 'README.md tells the truth about main today: a builder, two skeptics, a fixer and a verifier (Carson, 2026-10-27)',
  phases: [{ title: 'Write' }, { title: 'Refute' }, { title: 'Fix' }, { title: 'Verify' }],
}
const BRIEF = '/home/user/wt/wt-session/briefs/readme-update-brief.md'
const WT = '/home/user/wt/wt-readme'
const REPORT = { type: 'object', properties: {
  files: { type: 'array', items: { type: 'string' } },
  changes: { type: 'array', items: { type: 'string' } },
  checks: { type: 'array', items: { type: 'object', properties: { what: { type: 'string' }, how: { type: 'string' }, result: { type: 'string' }, evidence: { type: 'string' } }, required: ['what', 'how', 'result'] } },
  open: { type: 'array', items: { type: 'string' } },
  summary: { type: 'string' } }, required: ['files', 'changes', 'checks', 'open', 'summary'] }
const FINDINGS = { type: 'object', properties: {
  findings: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, severity: { type: 'string', enum: ['blocker', 'major', 'minor'] }, line: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' } }, required: ['title', 'severity', 'evidence', 'fix'] } },
  verified_ok: { type: 'array', items: { type: 'string' } },
  summary: { type: 'string' } }, required: ['findings', 'verified_ok', 'summary'] }
const GATES = { type: 'object', properties: {
  gates: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, result: { type: 'string', enum: ['pass', 'fail'] }, output: { type: 'string' } }, required: ['name', 'result', 'output'] } },
  summary: { type: 'string' } }, required: ['gates', 'summary'] }
const common = `Read ${BRIEF} first, whole, and follow it exactly: it names the worktree (${WT}), the Python, the readers, what main has that the README may lack, and the rules. Work only in ${WT} and edit only README.md. Never run a git command that writes. Never read a large file whole: grep -n and sed -n ranges. Every claim in your report carries the command you ran and its output.`

phase('Write')
const build = await agent(`${common}
You are the builder. First inventory: read README.md whole (187 lines), then for each of its sentences about what the site shows, how it updates, how it is built and where the files are, find the fact in the tree or on the live site and mark it right, stale or missing; read the brief's list of what main has today. Then edit README.md: change what is stale, add what is missing (one short paragraph or row each, in the file's voice), keep right sentences, and add the dated status paragraph about the public site from the live data files. Run every command you cite (or its --help), check every path and link, run the test modules the brief names, and return the report with a line per change.`, { label: 'readme:build', phase: 'Write', model: 'haiku', schema: REPORT })

phase('Refute')
const lenses = [
  { key: 'facts', prompt: `You are skeptic A: the facts. Take every statement in the new README.md that names a page, a feature, a flag, a job, a schedule, a count, a file, a command or a link, and check it against the tree (grep the code, the workflows, the docs) or the live site; run every command (or --help) and the link check yourself; run the test modules the brief names. A statement you cannot confirm is a finding with the line and the evidence.` },
  { key: 'reader', prompt: `You are skeptic B: the readers. Read the new README.md as Carson (does it say what the site is and what is on main today, including what is not yet drawn and what reads Data unavailable, without overclaiming?), as a crew lead on a phone (can they find what the Map and the sheet show and what an estimate is?), and as a contributor (can they build, test and check it from the commands alone?). Check the words rules (sentence case, no em-dash, no vendor name beyond the agents line, plain words, evidence honesty) line by line, the Contents list against the headings, the length, and that nothing describes the options sheet or the new layers as live. Each finding names the line and the words.` },
]
const refutes = await parallel(lenses.map(l => () => agent(`${common}
${l.prompt}
The builder's report: ${JSON.stringify(build)}`, { label: `readme:skeptic:${l.key}`, phase: 'Refute', model: 'haiku', schema: FINDINGS })))
const findings = refutes.filter(Boolean).flatMap(r => r.findings)
log(`readme: ${findings.length} findings from ${refutes.filter(Boolean).length} skeptics`)

phase('Fix')
let fix = null
if (findings.length) {
  fix = await agent(`${common}
You are the fixer. Verify each finding below against the file, the tree or the live site before acting (a finding you cannot reproduce is reported as "not reproduced", not fixed). Apply the ones that hold, re-run the test modules the brief names and the link check, and return the report with one line per finding: fixed, not reproduced, or declined and why.
Findings: ${JSON.stringify(findings)}`, { label: 'readme:fix', phase: 'Fix', model: 'haiku', schema: REPORT })
}

phase('Verify')
const verify = await agent(`${common}
You are the verifier. Run each gate and return pass or fail with the output: (1) PY -m unittest tests.test_addresses tests.test_gridded tests.test_storm tests.test_streets tests.test_site; (2) every relative link and anchor in README.md resolves (a script); (3) every command line in README.md that starts with python runs with --help, exit 0 (list them); (4) git status --short shows only README.md; (5) no em-dash (grep for the character) and no AI vendor, model or product name in the added lines (git diff -U0 README.md | grep '^+'); (6) the Contents list matches the headings; (7) the file is under 240 lines.`, { label: 'readme:verify', phase: 'Verify', model: 'haiku', schema: GATES })
return { build, refutes, fix, verify }