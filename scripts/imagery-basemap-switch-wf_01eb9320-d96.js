export const meta = {
  name: 'imagery-basemap-switch',
  description: 'Build, verify, review and fix the opt-in USGS imagery base map switch on the Map page',
  phases: [
    { title: 'Build', detail: 'two builders: integration, and checks', model: 'haiku' },
    { title: 'Integrate', detail: 'tests, sample builds, browser checks with and without internet, evidence', model: 'haiku' },
    { title: 'Review', detail: 'rules and privacy lens; technical refuter', model: 'haiku' },
    { title: 'Fix', detail: 'apply blocking and major findings, re-verify', model: 'haiku' },
  ],
}

const BRIEF = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/imagery-brief.md'
const WT = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/wt-imagery'
const SCRATCH = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/imagery-work'

const COMMON = `You are a worker on the Montana Hail Watch website. WORKTREE: ${WT} on branch claude/imagery-basemap (based on branch claude/storm-layers-p2, which adds the satellite layer; main is behind it). Every command runs there; use absolute paths under ${WT}; never touch /home/user/RoofingApp. Read the brief ${BRIEF} in full first, then the files it names (map.js, map.html, build.py, sources.py, about.html, tests/test_site.py, tools/smoke_map.py, docs/DECISIONS.md, docs/DESIGN.md, AGENTS.md rule 4). Never commit, never push, never change git state (git diff/status/log are fine). Never write a model, AI-vendor or AI-product name into any repo file. Plain wording, sentence case, no em-dashes in new prose. Scratch outputs go under ${SCRATCH}/. The decision numbers: the towns branch uses D31 and this change is D32 in docs/DECISIONS.md. Playwright: PW_CHROMIUM=/opt/pw-browsers/chromium. The USGS tile host is reachable from this machine (checked today), so the browser check can load real tiles.`

const SCHEMA = {
  type: 'object',
  properties: {
    files_changed: { type: 'array', items: { type: 'string' } },
    tests: { type: 'string' },
    failures: { type: 'array', items: { type: 'string' } },
    open_issues: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['files_changed', 'tests', 'failures', 'open_issues', 'notes'],
}
const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    findings: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string', enum: ['blocking', 'major', 'minor'] }, file: { type: 'string' }, line: { type: 'integer' },
      claim: { type: 'string' }, evidence: { type: 'string' }, fix: { type: 'string' } },
      required: ['severity', 'file', 'claim', 'evidence', 'fix'] } },
    verified_ok: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
  },
  required: ['findings', 'verified_ok', 'summary'],
}

phase('Build')
const built = await parallel([
  () => agent(`${COMMON}

STAGE A1, integration. You own: website/build.py, website/sources.py, website/templates/map.html, website/templates/about.html, website/static/map/map.js, website/static/map/map.css, AGENTS.md (rule 4 wording and the site-files sentence only), docs/DECISIONS.md (D32), docs/DESIGN.md, docs/ROADMAP.md. Implement brief sections "Design" items 1 to 5 exactly: the Base map radios in the Layers popover with the privacy line under Imagery; Python passes the imagery source (url template, max_zoom 16, credit, host) in a data-imagery attribute on #app and under "imagery" in data/map.json; CONTRACTS "imagery" entry with the brief's wording; map.js: the tile layer created only on switch, the is-imagery class hiding the vector base map's land fill, lakes, rivers, roads, county lines, place dots and labels (keep the Montana outline and the country and state borders), max zoom 16 in imagery mode and back to 11 with a clamp, the credit as a legend key row, base=imagery in the page address, the card never using imagery; the About page paragraph; the decision D32; DESIGN and ROADMAP notes; map.js line 9's sentence and AGENTS.md rule 4 updated to name the one exception. Each map.js change commented in the file's own style; keep the diff small. Run python -m unittest discover -s tests and the sample builds (brief section 5 of the P2 brief style: --sample and --sample --storm-layers into ${SCRATCH}/a1-off and a1-on) before you finish.`, { label: 'build:integration', phase: 'Build', model: 'haiku', schema: SCHEMA }),
  () => agent(`${COMMON}

STAGE A2, checks. You own: tools/smoke_map.py and tests/test_site.py (add tests; do not rewrite existing ones), tests/test_website_workflow.py only if the workflow changes (it should not). Implement brief "Design" items 5 (the tests: the default map.html has no off-site URL in any script, link, img or iframe tag; the imagery URL appears only in the data attribute and data/map.json, names exactly the host basemap.nationalmap.gov, uses https, and map.js contains no URL or host name; the About page carries the credit and the privacy line; the CONTRACTS entry exists) and 6 (smoke_map.py: in the default state zero off-site requests as now; a new check_imagery_switch: on the desktop context open the Layers menu, pick Imagery, wait for one tile request to the named host and its response (status 200, image/jpeg), check the vector land is hidden, the credit row shows, the page address carries base=imagery, the town bubbles and the weather frame still show, then switch back and check the white map and the max zoom; also open map.html?base=imagery directly; without internet the tile check reports "tile did not load" without failing the other checks; screenshots at 1280x800 and 390x844 in both modes into ${SCRATCH}/shots/). Code against the markup and data names in the brief (the integration builder is writing them now). Tests that need the integration should fail clearly, not error, until it lands.`, { label: 'build:checks', phase: 'Build', model: 'haiku', schema: SCHEMA }),
])
log('Build done')

phase('Integrate')
const integ = await agent(`${COMMON}

STAGE B, integrate and verify. Builders' reports: ${JSON.stringify(built)}. You may edit any file in website/, tests/, tools/, docs/, AGENTS.md. Steps: (1) git diff --stat against claude/storm-layers-p2 and read every changed file end to end; resolve mismatches against the brief. (2) python -m unittest discover -s tests: all must pass; never weaken a test. (3) Sample builds (--sample; --sample --storm-layers) into ${SCRATCH}/b-off and b-on; diff -rq each against a build of the base commit (git archive of claude/storm-layers-p2 into ${SCRATCH}/base) at a fixed --now: the only differences must be the base map switch markup, the data attribute, map.json's imagery key, map.js and map.css code and the About paragraph; confirm no off-site URL in any page tag. (4) Browser: PW_CHROMIUM=/opt/pw-browsers/chromium python tools/smoke_map.py ${SCRATCH}/b-on and b-off, and python tools/smoke_pages.py on both: must pass, and the imagery check must report real tiles loaded from the named host (this machine reaches it). Look at the screenshots (Read the PNGs) in both modes: imagery under the weather frame, bubbles and outlines visible, the credit row present, no sideways scroll; note what you see. (5) Write research/globe/validation-evidence/imagery-switch-verification.json (what was checked, numbers, tile bytes, screenshots list, zero off-site requests in the default state; no model names). (6) Re-run the unit tests. Report every command and result and what you could not verify.`, { label: 'integrate', phase: 'Integrate', model: 'haiku', schema: SCHEMA })

phase('Review')
const REVIEW_COMMON = `${COMMON}

You are a REVIEWER: do not edit repo files; run read-only commands, the tests, sample builds into ${SCRATCH}/review-* and scratch Python. Review the diff of this branch against claude/storm-layers-p2 (git diff claude/storm-layers-p2...HEAD plus untracked files). Integrate report: ${JSON.stringify(integ)}. Every claim is a claim to refute with evidence. Severity: blocking = an off-site request in the default state, the privacy line or credit missing, the white map not the default, a tile host other than the named one, a test that cannot fail, a crash path; major = a brief requirement missed, a wrong word in the decision; minor = wording, style.`
const reviews = await parallel([
  () => agent(`${REVIEW_COMMON}

LENS 1, rules and privacy: AGENTS.md rule 4 (the one exception is named and only on opt-in; no CDN; Python owns the source), the About page's privacy line and public-domain statement and credit "USDA, USGS", the decision D32 is factual (Carson chose: keep the white map as the default; add the switch; the recommended USGS imagery with names), DESIGN states, the card never uses imagery, the default build byte-identical in words and data apart from the switch markup and the attribute, the imagery words never claim the imagery is current or dated (USGS imagery is not dated on the tiles), dark mode shows imagery unfiltered.`, { label: 'review:rules', phase: 'Review', model: 'haiku', schema: REVIEW_SCHEMA }),
  () => agent(`${REVIEW_COMMON}

LENS 2, technical refuter: the tile layer is created once and only on switch (no request before the switch; verify with a Playwright request log in a scratch script); the tile URL template is z/y/x in USGS's order and the tiles load (status 200 image/jpeg) at zooms 6, 9, 13 and 16 over Billings; max zoom 16 in imagery mode and the clamp back to 11 (zoom out happens when switching back from zoom 14); the vector base map classes hidden and restored exactly; the credit row appears and disappears; base=imagery in the URL round-trips (open map.html?base=imagery&layer=wind); the card (?card=1) never loads tiles even with base=imagery; the weather frames, warning outlines, reports and bubbles unchanged in both modes; keyboard: the radios are reachable and switch; the tests fail when the host is changed or the privacy line removed (mutate a scratch copy).`, { label: 'review:technical', phase: 'Review', model: 'haiku', schema: REVIEW_SCHEMA }),
])
const findings = reviews.filter(Boolean).flatMap((r, i) => r.findings.map(f => ({ ...f, lens: i === 0 ? 'rules' : 'technical' })))
log(`Review: ${findings.length} findings, ${findings.filter(f => f.severity !== 'minor').length} blocking or major`)

phase('Fix')
const fix = await agent(`${COMMON}

STAGE D, fix. Findings: ${JSON.stringify(findings, null, 1)}. Verified-ok lists: ${JSON.stringify(reviews.filter(Boolean).map(r => r.verified_ok))}. For every blocking and major finding: reproduce it; if real, fix it minimally and add or strengthen a test; if not real, record why with evidence. Apply minor findings only when plainly right and cheap. Re-run python -m unittest discover -s tests, the two sample builds and their diffs, PW_CHROMIUM=/opt/pw-browsers/chromium python tools/smoke_map.py on the flag-on sample build and python tools/smoke_pages.py on it. Write research/globe/validation-evidence/imagery-switch-review.json (each finding: severity, file, claim, outcome, commands). Report what changed and what remains open.`, { label: 'fix', phase: 'Fix', model: 'haiku', schema: SCHEMA })

return { built, integ, findings, fix }