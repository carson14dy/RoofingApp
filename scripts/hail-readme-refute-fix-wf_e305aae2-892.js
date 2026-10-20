export const meta = {
  name: 'hail-readme-refute-fix',
  description: 'Three-lens adversarial check of the hail research README edits, verify each finding, apply confirmed fixes, mechanical checks',
  phases: [
    { title: 'Refute', detail: 'three lenses over the new README text' },
    { title: 'Verify', detail: 'one skeptic per finding' },
    { title: 'Fix', detail: 'apply confirmed findings and the supervisor edits' },
    { title: 'Check', detail: 'links, dashes, names, numbers' },
  ],
}
const WORKER = (typeof args !== 'undefined' && args && args.worker) || undefined  // the worker model alias, passed in args at launch

const WT = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/wt-hail'
const README = `${WT}/research/hail-history/README.md`
const EV = `${WT}/research/hail-history/validation-evidence`
const OWNER = `The owner (Carson) wrote on 2026-10-18, verbatim: "Decisions that are mine. 1. Trailing 5 years to today. 2. A public lookup by typed address or clicked location. Each address in montana should have a dot to click on the map with a popup on each history of weather. 3. Pages only for now. 4. Make the weather updates consistent and recent as possible 5. Try to find and read hail units and codes then process it and make the user understand it easier. Where they can find the exact date that the hail happened at that location. 6. Don't include owners names. But I do want all addresses included and all types of weather at that address for the past 5 years in a popup after you click the house on the map. 7. Follow the laws"`

const RULES = `Rules of this repository that apply: every number, quote or claim in the README must come from an evidence file under ${EV} (cited as a relative link) or from the owner's text; where the evidence says unverified or refuted, the README must say so; never a hail or damage finding; no "best" claims; no model, AI-vendor or AI-product names (a branch name on line 3 is the one allowed exception); plain wording, sentence case, no em-dashes or en-dashes. You are read-only: do not edit, stage, commit or push anything.`

const FINDINGS = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          line: { type: 'integer' },
          quote: { type: 'string', description: 'exact text from the README, copied verbatim, 20 to 300 characters, occurring once' },
          problem: { type: 'string' },
          evidence: { type: 'string', description: 'the file and fact, or the owner sentence, that shows the problem' },
          fix: { type: 'string', description: 'the exact replacement text for the quote (or empty to delete it)' },
          severity: { type: 'string', enum: ['blocking', 'minor'] },
          confidence: { type: 'number' },
        },
        required: ['id', 'line', 'quote', 'problem', 'evidence', 'fix', 'severity', 'confidence'],
      },
    },
    checked: { type: 'string', description: 'what you read and compared, in two sentences' },
  },
  required: ['findings', 'checked'],
}

const VERDICT = {
  type: 'object',
  properties: {
    id: { type: 'string' },
    refuted: { type: 'boolean' },
    reason: { type: 'string' },
    fix_ok: { type: 'boolean', description: 'true when the proposed fix is itself correct and cites or states nothing unsupported' },
    adjusted_fix: { type: 'string', description: 'a corrected replacement text when fix_ok is false and a correct one exists; else empty' },
  },
  required: ['id', 'refuted', 'reason', 'fix_ok', 'adjusted_fix'],
}

const LENSES = [
  {
    key: 'owner',
    prompt: `Lens: fidelity to the owner's answers. ${OWNER}\n\nRead ${README} in full (it is about 690 lines), especially section 1 item 6, section 8.3, the section 9 intro, the 9.1 decisions table (which has a column "Owner's answer (2026-10-18)") and the sentence after it, and section 9.2's B1 to B4 rows. Check: (1) every quoted owner sentence is verbatim (character for character, including "montana" lower case and the missing full stop after answer 4); (2) each answer sits on the row it belongs to (1 window; 2 and 6 per-address publication and address source; 3 hosting; 4 update job; 5 units and codes; 7 counsel); (3) a recommendation that differs from the answer is marked superseded and its text kept; (4) nothing attributes to the owner an intent he did not state (for example a radius, a threshold, a vendor, a go-live date); (5) the B3 row's "his answer 6" and "his answer 7" claims match what he wrote; (6) the README nowhere says anything per-address is published or approved. Report every concrete problem with the exact quote and a replacement. ${RULES}`,
  },
  {
    key: 'units',
    prompt: `Lens: the units and codes gate. Read ${EV}/mrms-grib2-tables/mrms-grib2-tables.json in full and the MESH, MESHMax1440min and MergedReflectivityQC rows of the three CSVs beside it. Then read ${README} in full and find every sentence about MESH units, the codes -1 and -3, the reflectivity codes -99 and -999, the plausibility cap, or inches. Check: (1) each such sentence agrees with the table (mm; -1 Missing; -3 No Coverage; dBZ -99 and -999) and keeps the caveat that the archive files do not state their MRMS version while the three table versions agree; (2) no sentence still presents the units or codes as unverified, assumed or unknown as a current fact (a superseded recommendation kept behind a "Superseded" marker is allowed; recorded history of what wave 1 found is allowed when it is dated); (3) the cap of 4.00 in and the 10 cells above 127 mm stay a review rule and the README never calls a 1,437.4 mm value plausible; (4) section 4.8 says its templates come from ${EV}/evaluation-and-wording.json; open that file and compare the radar_no_value and codes wording: where the README's templates now differ from the file, the README must say the wording was updated after the gate closed and cite mrms-grib2-tables.json, rather than claim the templates are copied; (5) section 10's index and the method's file counts include the new folder correctly; (6) every number in the new units sentences (parameter numbers 28 to 34, the discipline and category 209 and 3, the dates) matches the JSON. Report concrete problems only. ${RULES}`,
  },
  {
    key: 'plan',
    prompt: `Lens: the plan, status and mechanics. Read ${README} in full. Check: (1) the status line (line 3 or so) and section 9.2's dated paragraph and B1 to B4 rows: no invented measurement (every number in those rows must be in an evidence file under ${EV}; open the cited file and find it), the flag name is written as --hail-history consistently, the rows' done-when, stop and tests are coherent with the H rows above them, and the sentence about B1's branch does not claim a branch exists or has started when the repository refs (run: git -C ${WT} branch -a) show none named for B1; the correct statement is that B1 is the next pull request on its own branch, claude/hail-b1, which is created when the build starts; (2) section 4.1's new qualifier about the 496 to 3,623 s figure and the 644 late bucket files: open the cited evidence (h1-mesh-store.json fetch.last_modified and h1-mesh-store-review.json copy_coverage and C3) and confirm 644 and the sample basis; (3) section 10's sentence about the sections/ drafts; (4) run these mechanical checks yourself with shell commands and report counts: em-dashes and en-dashes in the README (must be 0), the words Claude, Anthropic, Codex, ChatGPT, OpenAI, Copilot, Gemini, the worker model, the larger model, the mid model case-insensitive (only the branch name on line 3 may match), and every relative markdown link target resolving to a file under ${WT}/research/hail-history (list unresolved ones); (5) pick 15 numbers from the lines changed in the last edit (git -C ${WT} diff -U0 -- research/hail-history/README.md shows them) and trace each to its evidence file or the owner's text; report any you cannot trace. ${RULES}`,
  },
]

phase('Refute')
const perLens = await pipeline(
  LENSES,
  (lens) => agent(lens.prompt, { label: `refute:${lens.key}`, phase: 'Refute', schema: FINDINGS, model: WORKER }),
  async (result, lens) => {
    if (!result) return []
    const fs = result.findings.map((f, i) => ({ ...f, id: `${lens.key}-${i + 1}` }))
    log(`${lens.key}: ${fs.length} findings`)
    const verdicts = await parallel(fs.map((f) => () =>
      agent(`You are a skeptic. Another reviewer claims this problem in ${README}:\n${JSON.stringify(f, null, 1)}\n\nTry to REFUTE it: open the README at that line (grep for the quote), open the evidence it names under ${EV} (and, when the owner's words matter, use this verbatim text: ${OWNER}). The finding stands only if the quote exists once in the README as written, the problem is real against the evidence or the owner's text, and the proposed fix is correct and introduces nothing unsupported (no new number, no new claim, no em-dash, no model or AI-product name). If the problem is real but the fix is wrong, say fix_ok false and give an adjusted_fix that is correct, or leave it empty when none is possible. Default to refuted=true when uncertain. Read-only: edit nothing. ${RULES}`,
        { label: `verify:${f.id}`, phase: 'Verify', schema: VERDICT, model: WORKER })
        .then((v) => (v ? { ...f, verdict: v } : null))))
    return verdicts.filter(Boolean)
  },
)

const all = perLens.flat().filter(Boolean)
const confirmed = all.filter((f) => !f.verdict.refuted).map((f) => ({
  id: f.id, line: f.line, quote: f.quote, problem: f.problem, evidence: f.evidence, severity: f.severity,
  fix: f.verdict.fix_ok ? f.fix : f.verdict.adjusted_fix,
})).filter((f) => f.fix !== undefined && f.fix !== null && (f.fix.length > 0 || true))
const refuted = all.filter((f) => f.verdict.refuted).map((f) => ({ id: f.id, quote: f.quote, reason: f.verdict.reason }))
log(`confirmed ${confirmed.length}, refuted ${refuted.length}`)

phase('Fix')
const SUPERVISOR_EDITS = `Supervisor edits (apply these as well, exact-match replacements, in the README only):
(a) In section 9.2's dated paragraph, replace the sentence about B1's branch (it says B1 has started on a separate branch that is not yet in the refs) with: "B1 is the next pull request, on its own branch, claude/hail-b1, created when the build starts." Keep the rest of the paragraph.
(b) In section 4.8, where the README says the templates are copied from evaluation-and-wording.json, make it say they were taken from that file and that the codes wording was updated on 2026-10-18 after the units gate closed ([mrms-grib2-tables.json](validation-evidence/mrms-grib2-tables/mrms-grib2-tables.json)), so the two now differ on the codes sentence. Do this only if a confirmed finding has not already fixed it.
(c) Nowhere else change meaning.`
const fixReport = await agent(
  `Apply these confirmed review findings to ${README} with exact-match replacements (each "quote" occurs once; replace it with "fix"; an empty fix deletes the quote). Do not apply anything else from the list of refuted findings. After the findings, apply the supervisor edits. Then re-run: em-dash and en-dash count (must be 0), the banned-name grep (only the branch name on line 3 may match), and the relative-link check (0 unresolved). Do not touch any other file; do not stage, commit or push. Return JSON with applied (ids), skipped (id and why, for any quote that does not occur exactly once or any fix that would add an unsupported claim), and the three check results.\n\nCONFIRMED FINDINGS:\n${JSON.stringify(confirmed, null, 1)}\n\n${SUPERVISOR_EDITS}\n\nNo model, AI-vendor or AI-product names; no em-dashes; plain wording.`,
  { label: 'fix', phase: 'Fix', model: WORKER, schema: {
    type: 'object',
    properties: {
      applied: { type: 'array', items: { type: 'string' } },
      skipped: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, why: { type: 'string' } }, required: ['id', 'why'] } },
      emdashes: { type: 'integer' }, banned_hits: { type: 'integer' }, unresolved_links: { type: 'integer' }, lines: { type: 'integer' },
    },
    required: ['applied', 'skipped', 'emdashes', 'banned_hits', 'unresolved_links', 'lines'],
  } },
)

phase('Check')
const check = await agent(
  `Final read-only check of ${README} after edits. Run with shell commands and report: (1) em-dash and en-dash count; (2) case-insensitive hits of Claude, Anthropic, Codex, ChatGPT, OpenAI, Copilot, Gemini, the worker model, the larger model, the mid model with line numbers (the branch name on line 3 is allowed); (3) relative markdown links whose target does not exist under ${WT}/research/hail-history; (4) grep for "has started" and "not yet in this repository" (both must be absent); (5) grep for "mm assumed" and "units are unverified" and "codes are unverified" and list the lines with the 8 words around each so the supervisor can see whether each is a dated record or a superseded recommendation (allowed) or a current claim (not allowed); (6) the line count. Edit nothing.`,
  { label: 'check', phase: 'Check', model: WORKER, schema: {
    type: 'object',
    properties: {
      emdashes: { type: 'integer' }, banned: { type: 'array', items: { type: 'string' } }, unresolved_links: { type: 'array', items: { type: 'string' } },
      started_phrases: { type: 'array', items: { type: 'string' } }, unverified_lines: { type: 'array', items: { type: 'string' } }, lines: { type: 'integer' },
    },
    required: ['emdashes', 'banned', 'unresolved_links', 'started_phrases', 'unverified_lines', 'lines'],
  } },
)

return { confirmed, refuted, fixReport, check }