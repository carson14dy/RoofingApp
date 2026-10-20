export const meta = {
  name: 'hail-history-synthesis',
  description: 'Write the hail history research README from the refuted evidence: ten section writers, an assembler, a critic',
  phases: [
    { title: 'Write sections', detail: 'ten writers, one section each, from the evidence files', model: WORKER },
    { title: 'Assemble', detail: 'join the sections, fix links', model: WORKER },
    { title: 'Critique', detail: 'trace every number to the evidence; fix what is plainly right', model: WORKER },
  ],
}
const WORKER = (typeof args !== 'undefined' && args && args.worker) || undefined  // the worker model alias, passed in args at launch

const BRIEF = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/hail-synthesis-brief.md'
const WT = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/wt-hail'
const SECTIONS = ['01-bottom-line', '02-sources', '03-every-house', '04-what-a-record-says', '05-sizes-and-architecture',
  '06-live-tracking', '07-programs', '08-evaluation-and-honesty', '09-decisions-and-plan', '10-open-questions-and-index']

const SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    lines: { type: 'integer' },
    citations: { type: 'integer' },
    unverified_items_marked: { type: 'array', items: { type: 'string' } },
    problems: { type: 'array', items: { type: 'string' } },
  },
  required: ['file', 'lines', 'citations', 'unverified_items_marked', 'problems'],
}

const COMMON = `Read the brief ${BRIEF} in full, then the wave-1 brief it names, then the evidence files under ${WT}/research/hail-history/validation-evidence/ that your section needs (read the whole file, not a summary; the "review" object holds the refuter's corrections and the facts carry "verified" flags and "corrected_from" values; a fact with "verified": false is refuted and must not be restated as true). Work only in the worktree ${WT} (branch claude/hail-history). Never commit or push. No model, AI-vendor or AI-product names in any file; commercial weather vendors may be named. No em-dashes. Plain wording, sentence case.`

phase('Write sections')
log('Synthesis: ten section writers')
const written = await parallel(SECTIONS.map(s => () => agent(`${COMMON}

ROLE: WRITER of section ${s}. Write ${WT}/research/hail-history/sections/${s}.md exactly as the brief specifies for that section (its heading, its content, its line cap). Every number and quote cites its evidence file and fact. Where the evidence is refuted, unverified or missing, say so in the text rather than filling the gap. Return the structured summary.`, { label: `write:${s}`, phase: 'Write sections', model: WORKER, schema: SCHEMA })))
log('Sections written: ' + written.filter(Boolean).length + ' of ' + SECTIONS.length)

phase('Assemble')
const assembled = await agent(`${COMMON}

ROLE: ASSEMBLER. The writers' reports: ${JSON.stringify(written)}. Join the ten section files into ${WT}/research/hail-history/README.md as the brief's assembler step says (title "Hail tracking and a five-year hail and wind history for Montana addresses: research"; status line with the branch, the date 2026-10-17 and "research; nothing ships"; a table of contents; the sections in order with consistent heading levels; cross-references fixed; every relative link checked to resolve against the worktree; 0 em-dashes; 0 banned names). Keep the sections folder. Return the structured summary (lines of the README, citations counted, problems).`, { label: 'assemble', phase: 'Assemble', model: WORKER, schema: SCHEMA })

phase('Critique')
const critic = await agent(`${COMMON}

ROLE: CRITIC. Assembler's report: ${JSON.stringify(assembled)}. Read ${WT}/research/hail-history/README.md end to end against the ten evidence files, as the brief's critic step says: every number traced to a fact (spot-check at least 60 numbers across all sections, and every number in sections 01, 05 and 09); refuted facts not restated; unverified items marked; no damage, hail-finding or "best" claims; owner decisions complete and honest; the plan's first step buildable with what the evidence verified. Write ${WT}/research/hail-history/validation-evidence/critic-report.json (findings: section, claim, evidence, severity, fix, applied true|false) and apply the fixes that are plainly right in the README (wrong numbers, missing "unverified", a claim stronger than its evidence); leave judgment calls in the report. Return the structured summary with the count of findings and of fixes applied in problems.`, { label: 'critic', phase: 'Critique', model: WORKER, schema: SCHEMA })

return { written, assembled, critic }