export const meta = {
  name: 'hail-b2-round2',
  description: 'B2 round two: apply the re-check findings F-01 to F-14 under decisions D15 to D24, re-review (browser parity, data), verify, fix, re-check',
  phases: [
    { title: 'Fix2', detail: 'three fixers by ownership' },
    { title: 'Review2', detail: 'browser parity and smoke; zone editions, spans and counts' },
    { title: 'Verify2', detail: 'one skeptic per finding' },
    { title: 'Fix3', detail: 'fixers by ownership' },
    { title: 'Recheck2', detail: 'tests, builds, smoke, record' },
  ],
}

const WT = '/home/user/wt/wt-b2'
const BRIEF = '/home/user/wt/briefs/hail-b2-brief.md'
const OUT = '/home/user/hail-b2/out2'
const STORE_DIR = '/home/user/hail-b1/out2/store/store'
const JOINS_STORE = '/home/user/hail-b2/out/joins/store'
const JOINS_CACHE = '/home/user/hail-b2/out/joins/cache'
const RECHECK = '/home/user/wt/b2-recheck-full.txt'
const VENV = '/home/user/hail-b1/venv/bin/python'

const COMMON = `You work in the git worktree ${WT} (branch claude/hail-b2; B2 is built, reviewed once and fixed once; the working tree and local WIP commits hold it). Read ${BRIEF} in full first, including the two decision sections at its end (D1 to D14 and D15 to D24): they are the contract and they override older text. Then read the re-check report ${RECHECK} (its JSON lists findings F-01 to F-14 with file, line, evidence and fix). Repository rules (AGENTS.md is in your context): Python first (every word the viewer reads is written in Python; the browser fetches, filters, fills templates and lists), evidence honesty, feed contracts, real-browser checks, plain wording in sentence case, no em-dashes, no model, AI-vendor or AI-product names in repository files (branch names excepted), tests with every behaviour change, no new pip package for the site build. Edit only the files you own; other fixers edit other files in the same worktree now; never run git checkout, stash, reset, add, commit or push; never delete anything outside a folder you created under ${OUT}/<your-name>/; tests delete only folders they created. The B1 store is ${STORE_DIR}; the round-1 joins store is ${JOINS_STORE} with its cache at ${JOINS_CACHE}; a python with pyarrow is ${VENV} (pyshp is in the joins venv the builder made, see the reports under ${JOINS_STORE}/../ or install pyshp in your own venv under your scratch folder). Network is available. Return a plain report: what you changed per finding and decision, the commands you ran with results and numbers, and anything not done.`

const FIX_JOINS = `${COMMON}

You are the joins fixer. You own website/joins.py, tests/test_joins.py, tests/test_hail.py, website/hail.py (minimal changes only), .github/workflows/hail-store.yml and website/data/hail-fixture/. Apply, in this order: F-03 and F-04 and F-05 per D16 (begin from the earliest NEW or CON issue, else "start not recorded"; end from the earliest cancellation row's expire time, else the latest non-cancellation expiry, else "end not recorded"; fetch every public zone edition the NWS page links (z_18mr25.zip and z_16ap26.zip) and give each event the zone code of the edition in force at its issue time, with the cut-over at the newer edition's effective date from its file name; remove the April 2026 claim and the ZONE_CODE_CHANGES guesswork; verify the Montana zone geometry of the two editions is identical as F-05 found, and record it in the index); F-10 per D11 as corrected (per-zone counts of unplaced and earlier products, or the sentence says "in Montana"); F-07 per D20 (the exact unavailable sentence per part); F-12 and D19 (type words only for codes without a unit; export the unit code set in map_data_joins as unit_codes); D17 (two zone leads: public zone products and red flag warnings for the fire zone, each with its own count; the lead never mixes them); D18 (s/ files carry integer mph and kt; the station row prints "{kt} kt ({mph} mph)" with integers); D15 (re-pull windows beat the cache, with the January rule; the cached copy only on a failed fresh request, recorded as served from cache since a date); D21 (malformed rows skipped and counted); D22 (drop the "older years have fewer tags" sentence); D23 (JOINS_DEADLINE_S stays 35 minutes); the reports_what sentence "A report is not an inspection and not a finding about a roof." (round-1 rules-8). Keep every public name. Update tests for each change (spans, editions, unit codes, integer station values, the unavailable sentence, the per-zone counts, the malformed-row skip) and make tests.test_joins and tests.test_hail pass. Regenerate the fixture (j/, z/, s/, index, manifest) from the rebuilt store so it stays under 50 KB and byte-identical to the fixture command's output. Then rebuild the joins: copy ${STORE_DIR} to ${OUT}/joins/store, run python -m website.joins build --store ${OUT}/joins/store --cache ${JOINS_CACHE} --procs 4 (the cache has the files; the prior zone edition will be fetched), verify, compare, measure (wall time, bytes of j/, z/, s/, the largest file, the number of zone events with ends now recorded, the MTZ060 placements), rebuild once more from the same cache and diff -r for determinism, and tar ${OUT}/joins/hail-store.tar.gz. Report the Benchland gate rows per D1 again.`

const FIX_SITE = `${COMMON}

You are the site fixer. You own website/build.py, website/sources.py, website/templates/ (map.html, town.html, about.html), website/static/map/map.js, website/static/map/map.css, tools/smoke_map.py, tests/test_site.py and .github/workflows/website.yml. The joins fixer is changing website/joins.py now (read it as it appears; never edit it): it exports unit_codes in map_data_joins, two zone leads (D17), integer station values (D18), the exact unavailable sentences (D20), typed rows (D19), per-zone counts (F-10) and spans with ends (D16). Apply: F-01 (fetch hail/z/fire-<zone>.json for the cell's fire zone and render the red flag rows with the fire words; the two zone leads per D17); F-02 and D19 (typed template for codes not in J.unit_codes; never a bare number or "no size given"); F-06 per D18 (integers; drop toFixed(1)); F-07 per D20 (the browser's unavailable sentences come from the templates, identical to Python's); F-08 (the smoke's cross-day check returns a note when the tile file is absent in a sample build); F-13 and F-14 (sources.py wording); the records_row keys, the zones_end_unset, zones_cancelled, zones_heading_no_zone, zones_changed, zones_unplaced and fire_product lines, the records_changed and records_unplaced lines, the partial sentences for detections and records, records_lead_one, warnings_lead_unknown and no-outline lines, the lag words (the round-1 joins fixer's list of browser gaps); the About paragraph's two zone systems. Then build.py: JOIN_SITE_WORDS cleanup (remove zone_unknown_* and not_known; the zones heading uses zones_heading_no_zone; town-table labels per D3). Update tests/test_site.py (the browser-versus-module parity test renders describe_joins and the browser for the gate cell, Benchland's cell and a no-join cell from the same store and compares section texts; the sample and real smoke pass). Builds: --sample --hail-history --now 2026-10-18T12:00:00Z into ${OUT}/site/sample; when ${OUT}/joins/hail-store.tar.gz exists (poll every 2 minutes up to 60 minutes; the joins fixer writes it), --sample --hail-history --hail-store that tar into ${OUT}/site/real; PW_CHROMIUM=/opt/pw-browsers/chromium python tools/smoke_map.py on both (--shots on the real one) and quote the results; the smoke must pass on both. Report what you changed and measured.`

const FIX_DOCS = `${COMMON}

You are the docs fixer. You own docs/DECISIONS.md, docs/DESIGN.md, docs/ROADMAP.md, README.md, AGENTS.md and research/hail-history/validation-evidence/b2-verification.json. Apply D24 and F-11: D35 documents the fire weather zones (D7), the two zone leads (D17), the zone editions and span rules (D16), the labels on every row template (D3), the exact unavailable sentences (D20), the integer station values (D18), the typed rows (D19), the per-zone counts (D11 as corrected), the cache rule (D15), JOINS_DEADLINE_S (D23, in D35 not D34), and the "a report is not an inspection" sentence; the sizes in D35 and DESIGN section 9 become "measured in the re-check" placeholders that the re-check fills (do not quote the 15:20 UTC build); DESIGN section 9 row templates carry the labels, the warning template its "issuance polygon in effect" words, and the states include partial and unavailable with D20's sentences; DECISIONS 783 items (5) and (6) corrected; the record's gate B2-1 text is D1's two-cell wording and its open items drop the ones the decisions settle. Em-dashes 0 in your lines; no model, AI-vendor or AI-product names; no invented measurements. Report the diff stat of your files.`

const FINDINGS = {
  type: 'object',
  properties: {
    findings: { type: 'array', items: { type: 'object', properties: {
      id: { type: 'string' }, file: { type: 'string' }, line: { type: 'integer' }, claim: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' },
      severity: { type: 'string', enum: ['blocking', 'should', 'minor'] }, confidence: { type: 'number' } },
      required: ['id', 'file', 'line', 'claim', 'evidence', 'fix', 'severity', 'confidence'] } },
    measurements: { type: 'object', additionalProperties: true },
    gates: { type: 'array', items: { type: 'object', properties: { gate: { type: 'string' }, status: { type: 'string', enum: ['pass', 'fail', 'not_checked'] }, evidence: { type: 'string' } }, required: ['gate', 'status', 'evidence'] } },
    summary: { type: 'string' },
  },
  required: ['findings', 'measurements', 'gates', 'summary'],
}
const VERDICT = { type: 'object', properties: { id: { type: 'string' }, refuted: { type: 'boolean' }, reason: { type: 'string' }, fix_ok: { type: 'boolean' }, adjusted_fix: { type: 'string' } }, required: ['id', 'refuted', 'reason', 'fix_ok', 'adjusted_fix'] }

const REVIEW_COMMON = `Read-only reviewer in ${WT} (branch claude/hail-b2). Read ${BRIEF} in full first (the contract, gates B2-1 to B2-9, decisions D1 to D24) and ${RECHECK} (the previous re-check). Never edit, stage, commit or push; scratch only under ${OUT}/<your-name>/ which you create; never delete anything outside it. Report concrete defects only, each with file, line, evidence and an exact minimal fix; rank blocking first; fill the gates you checked; put every measured number in measurements.`

const REVIEWERS = [
  { key: 'browser', prompt: `${REVIEW_COMMON} Lens: browser parity and the smoke (gates B2-3, B2-4, B2-5, B2-6, B2-7, B2-9). Build from a copy of the worktree (cp -r without .git into ${OUT}/browser/src): flag-off --sample --now 2026-10-18T12:00:00Z into ${OUT}/browser/off, --hail-history --sample into ${OUT}/browser/sample, --hail-history --sample --hail-store ${OUT}/joins/hail-store.tar.gz into ${OUT}/browser/real, and base 7aec754 (git archive) flag-off into ${OUT}/browser/base-off; diff -rq base-off vs off (only map.js, map.css and ?v= lines may differ). Run tools/smoke_map.py (PW_CHROMIUM=/opt/pw-browsers/chromium) on sample and real and quote the results; then your own parity probes: for the gate cell (797,1986), Benchland's cell (792,1998), a no-join cell and a cell in a tile with red flag warnings, render describe_joins in Python and read the browser sheet, and compare every section's lead, rows and sentences text for text (list each difference); the unavailable state (a store copy with one part marked unavailable in index.json) shows D20's sentence in both; typed rows show the type word only; station rows integers; zone rows show begin and end with cancellations; red flag rows present with the fire zone lead; cross-day warnings show both dates; every request on-site; screenshots at 390 and 1280 px, light and dark, described.` },
  { key: 'data', prompt: `${REVIEW_COMMON} Lens: zone editions, spans and counts (gates B2-1, B2-2, B2-6, B2-8). On ${OUT}/joins/store (rebuilt this round): (1) the two public zone editions were fetched (ledger) and the Montana geometry compared; the MTZ060 products (19 HW, 4 WS, 1 BZ issued 2025-03-20 to 2026-04-07) are now placed on a zone and listed; (2) spans: sample 40 cancelled zone events and recompute begin and end from the cached zone CSV rows per D16 (earliest NEW or CON issue; earliest CAN expire); count events with "end not recorded" and "start not recorded" and check each has no better source; no zero-length span; (3) per-zone unplaced and earlier counts (F-10) are per zone or say "in Montana"; (4) station files hold integers; (5) unit_codes in the index or map data lists exactly the LSR codes with a unit (H, G, N, A, S, R and any other with a unit); (6) D15: inspect the cache code path and the ledger for the re-pull windows (fresh fetches recorded for the last two months of LSR and SWDI); (7) determinism: two builds from the same cache identical; verify and compare pass; the research counts still match; (8) the fixture is regenerated, under 50 KB, byte-identical to the fixture command, and every file it lists exists (F-09).` },
]

const OWNERSHIP = {
  joins: ['website/joins.py', 'tests/test_joins.py', 'tests/test_hail.py', 'website/hail.py', '.github/workflows/hail-store.yml', 'website/data/hail-fixture/'],
  site: ['website/build.py', 'website/sources.py', 'website/templates/', 'website/static/map/map.js', 'website/static/map/map.css', 'tools/smoke_map.py', 'tests/test_site.py', '.github/workflows/website.yml'],
  docs: ['docs/', 'README.md', 'AGENTS.md', 'research/hail-history/validation-evidence/b2-verification.json'],
}
function ownerOf(file) {
  for (const [k, prefixes] of Object.entries(OWNERSHIP)) if (prefixes.some((p) => file.startsWith(p) || file.includes(p))) return k
  return 'site'
}

phase('Fix2')
const fixes = await parallel([
  () => agent(FIX_JOINS, { label: 'fix2:joins', phase: 'Fix2', model: 'haiku' }),
  () => agent(FIX_SITE, { label: 'fix2:site', phase: 'Fix2', model: 'haiku' }),
  () => agent(FIX_DOCS, { label: 'fix2:docs', phase: 'Fix2', model: 'haiku' }),
])
const [joinsR, siteR, docsR] = fixes
log(`fix2 done: joins ${joinsR ? 'ok' : 'null'}, site ${siteR ? 'ok' : 'null'}, docs ${docsR ? 'ok' : 'null'}`)

phase('Review2')
const reviews = await pipeline(
  REVIEWERS,
  (r) => agent(`${r.prompt}\n\nFixer reports for context (claims to check, not facts):\nJOINS: ${(joinsR || 'none').slice(0, 7000)}\nSITE: ${(siteR || 'none').slice(0, 6000)}\nDOCS: ${(docsR || 'none').slice(0, 2500)}`, { label: `review2:${r.key}`, phase: 'Review2', schema: FINDINGS, model: 'haiku' }),
  async (result, r) => {
    if (!result) return { key: r.key, findings: [], measurements: {}, gates: [], summary: 'reviewer returned nothing' }
    const fs = result.findings.map((f, i) => ({ ...f, id: `${r.key}-${i + 1}` }))
    log(`${r.key}: ${fs.length} findings`)
    const verdicts = await parallel(fs.map((f) => () =>
      agent(`You are a skeptic checking one review finding in ${WT} (read-only; never edit, stage, commit or push; scratch only under ${OUT}/skeptic-${f.id}/ which you create; never delete anything outside it). The finding:\n${JSON.stringify(f, null, 1)}\n\nOpen the file at the line, reproduce the observation yourself, and read ${BRIEF} (contract and decisions D1 to D24). The finding stands only if the defect is real, matters to the gates or the repository rules (AGENTS.md), and the proposed fix is correct and minimal and introduces nothing unsupported (no new number, no em-dash, no model or AI-product name, no new pip package for the site build, no scope widening, no contradiction of a decision). If the defect is real but the fix is wrong or too broad, set fix_ok false and give an adjusted_fix. Default to refuted=true when uncertain.`,
        { label: `verify2:${f.id}`, phase: 'Verify2', schema: VERDICT, model: 'haiku' })
        .then((v) => (v ? { ...f, verdict: v } : null))))
    return { key: r.key, findings: verdicts.filter(Boolean), measurements: result.measurements, gates: result.gates, summary: result.summary }
  },
)

const all = reviews.flatMap((r) => r.findings)
const confirmed = all.filter((f) => !f.verdict.refuted).map((f) => ({ id: f.id, file: f.file, line: f.line, claim: f.claim, evidence: f.evidence, severity: f.severity, fix: f.verdict.fix_ok ? f.fix : f.verdict.adjusted_fix, owner: ownerOf(f.file) })).filter((f) => f.fix && f.fix.length > 0)
const refuted = all.filter((f) => f.verdict.refuted).map((f) => ({ id: f.id, file: f.file, claim: f.claim, reason: f.verdict.reason }))
log(`confirmed ${confirmed.length} (blocking ${confirmed.filter((f) => f.severity === 'blocking').length}), refuted ${refuted.length}`)

phase('Fix3')
const groups = ['joins', 'site', 'docs'].map((k) => ({ k, items: confirmed.filter((f) => f.owner === k) })).filter((g) => g.items.length)
const fix3 = await parallel(groups.map((g) => () =>
  agent(`${COMMON}\n\nYou are the round-3 fixer for the ${g.k} files; you own exactly: ${OWNERSHIP[g.k].join(', ')}. Apply these confirmed findings with exact, minimal edits that keep every public name and the decisions. Skip and report any finding naming a file you do not own. After editing run python -m unittest tests.test_joins tests.test_site tests.test_hail (and the full suite if you changed joins.py or build.py); if a fix changes the j/, z/ or s/ format or a join, rebuild ${OUT}/joins/store from ${STORE_DIR} with the cache at ${JOINS_CACHE} and re-tar ${OUT}/joins/hail-store.tar.gz, and say so. Report applied ids, skipped ids with reasons, and the test tail.\n\nFINDINGS:\n${JSON.stringify(g.items, null, 1)}`,
    { label: `fix3:${g.k}`, phase: 'Fix3', model: 'haiku' })))

phase('Recheck2')
const recheck = await agent(`${REVIEW_COMMON} You are the final checker. Run and quote: ${VENV} -m unittest discover -s tests (tail); python desktop/launcher.py --selftest payload; builds from a copy of the worktree (cp -r without .git into ${OUT}/recheck/src): --sample --now 2026-10-18T12:00:00Z into ${OUT}/recheck/off, --hail-history --sample into ${OUT}/recheck/sample, --hail-history --sample --hail-store ${OUT}/joins/hail-store.tar.gz into ${OUT}/recheck/real; PW_CHROMIUM=/opt/pw-browsers/chromium python tools/smoke_map.py on each (--shots on the real one) and tools/smoke_pages.py on the real one; du -sb of hail/j, hail/z, hail/s and hail/ in the real build and of each _site; the largest j/ file; python -m website.joins verify and compare on ${OUT}/joins/store; the parity probe (describe_joins vs the browser) on the gate cell, Benchland's cell and a no-join cell; git -C ${WT} status --short and diff --stat 7aec754; em-dash and banned-name counts over added lines; a grep of the built real pages for an unfilled brace inside hail sections; the decision 7 audit. Then update research/hail-history/validation-evidence/b2-verification.json in ${WT} (the one file you may edit): each gate's status and evidence from what you measured (B2-1 per D1), measurements (and fill the sizes the docs fixer left as "measured in the re-check" by listing them in the record; do not edit the docs), and the findings applied and refuted under notes. Return the gate table and measurements as JSON text.`,
  { label: 'recheck2', phase: 'Recheck2', model: 'haiku' })

return { joinsR: (joinsR || '').slice(0, 7000), siteR: (siteR || '').slice(0, 6000), docsR: (docsR || '').slice(0, 2500), reviews: reviews.map((r) => ({ key: r.key, summary: r.summary, gates: r.gates, measurements: r.measurements })), confirmed, refuted, fix3, recheck }