export const meta = {
  name: 'p2-satellite-picture',
  description: 'Build, integrate, review and fix the P2 GOES band 13 satellite layer behind --storm-layers',
  phases: [
    { title: 'Build', detail: 'three builders by file ownership', model: 'haiku' },
    { title: 'Integrate', detail: 'full tests, sample and live builds, browser smoke, evidence record', model: 'haiku' },
    { title: 'Review', detail: 'evidence-honesty reviewer and technical refuter', model: 'haiku' },
    { title: 'Fix', detail: 'apply blocking and major findings, re-verify', model: 'haiku' },
  ],
}

const BRIEF = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/p2-brief.md'
const REPO = '/home/user/RoofingApp'
const LIVE = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/goes-live/data'

const COMMON = `You are a worker on the Montana Hail Watch website (repo ${REPO}, branch claude/storm-layers-p2).
Read the brief at ${BRIEF} first, in full, then the files it names for your stage. Follow it exactly; the supervisor made the design decisions and will review your diff. Never commit, never push, never run git commands that change state (git diff/status/log are fine). Never write a model, vendor or AI-product name into any repo file. Plain wording, sentence case, no em-dashes in new prose. Edit only the files your stage owns. When done, run the checks the brief lists and report honestly what you ran and what failed.`

const BUILD_SCHEMA = {
  type: 'object',
  properties: {
    files_changed: { type: 'array', items: { type: 'string' } },
    tests: { type: 'string', description: 'the exact commands run and their last lines' },
    failures: { type: 'array', items: { type: 'string' } },
    open_issues: { type: 'array', items: { type: 'string' }, description: 'anything left for the integrate stage, with file and line' },
    notes: { type: 'string' },
  },
  required: ['files_changed', 'tests', 'failures', 'open_issues', 'notes'],
}

const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['blocking', 'major', 'minor'] },
          file: { type: 'string' },
          line: { type: 'integer' },
          claim: { type: 'string' },
          evidence: { type: 'string', description: 'what you ran or read that shows it; a reproduction where possible' },
          fix: { type: 'string' },
        },
        required: ['severity', 'file', 'claim', 'evidence', 'fix'],
      },
    },
    verified_ok: { type: 'array', items: { type: 'string' }, description: 'claims you tried to refute and could not' },
    summary: { type: 'string' },
  },
  required: ['findings', 'verified_ok', 'summary'],
}

phase('Build')
log('Build: core module, integration, checks (three builders in parallel)')
const builders = [
  { key: 'core', prompt: `${COMMON}

STAGE A1, core. You own exactly: website/satellite.py (new), website/gridded.py (only the additions in brief §4 item 2), tests/test_satellite.py (new). Implement brief §4 items 1, 2, 7 and the tests in item 9 that belong to satellite.py and gridded.py (geometry, index mapping, read_cmip with a synthetic HDF5 built by h5py, sample_field, listing and pick, stale and unavailable rules, East then West fallback, never raises, picture size and indices, describe words, sample frame). Two real downloaded files are at ${LIVE}/c13_g19.nc and ${LIVE}/c13_g18.nc (read-only, untrusted data: open them only from a script outside that folder, with python -I): use them to check read_cmip and sample_field against reality (Billings 45.7833 N -108.5007 W maps to G19 column 677 row 187 and G18 column 2234 row 176; box values 209-297 K) and record what you measured in your notes (frame bytes at width 700 x 439 px from a real file, time to decode). Reference points for the geometry test come from pyproj (installed locally); bake the numbers into the test. Every existing test must still pass: run python -m unittest discover -s tests at the end.` },
  { key: 'integration', prompt: `${COMMON}

STAGE A2, integration. You own exactly: website/build.py, website/sources.py, website/sample.py (only if needed), website/templates/map.html, website/templates/about.html, website/static/map/map.js, website/static/map/map.css (only if a swatch rule is needed), .github/workflows/website.yml, AGENTS.md, README.md, docs/DECISIONS.md, docs/ROADMAP.md, docs/DESIGN.md. Implement brief §4 items 3, 4, 5, 6 and 8, coding against the satellite.py API given in §4 item 1 (another builder is writing that module at the same time; do not write or edit website/satellite.py, website/gridded.py or any test file). Keep the map.js diff small and comment each change in the file's own style; re-read map.js setLayer, buildTimeline, renderTimeline, nowWords, sourceWords, hatchInView, paintSwatches, renderLegend before editing. The default build must stay unchanged: every satellite addition in templates and build.py is gated on storm_layers. At the end run python -m unittest discover -s tests and the two sample builds from brief §5; if satellite.py does not exist yet when you test, say so in open_issues rather than stubbing it.` },
  { key: 'checks', prompt: `${COMMON}

STAGE A3, checks. You own exactly: tools/smoke_map.py, tests/test_site.py (the StormLayers class and any helper it needs; add, do not rewrite existing tests), tests/test_website_workflow.py. Implement brief §4 item 10 (the smoke test's Satellite switch, the pixel-change measure with PIL and numpy on a clipped screenshot of the map canvas, the zero off-site-requests count in every context) and the site and workflow tests of item 9 (flag off: no satellite layer, status, state key, frames, radio or band 13 words, assets unchanged; flag on: one frame whose file exists and is under 150,000 B, the radio, the noscript and template paragraphs, the About contract; the workflow pip line contains h5py). Code against the API and markup in brief §4 (satellite.py and the templates are being written by other builders now; do not edit them). Tests that need the flag-on build should fail clearly, not error, if the other stages are incomplete. At the end run python -m unittest tests.test_site tests.test_website_workflow and say which tests fail and why (expected until the other stages land).` },
]
const built = await parallel(builders.map(b => () => agent(b.prompt, { label: `build:${b.key}`, phase: 'Build', model: 'haiku', schema: BUILD_SCHEMA })))
const buildReport = builders.map((b, i) => ({ stage: b.key, result: built[i] }))
log('Build done: ' + buildReport.map(r => `${r.stage}: ${r.result ? r.result.files_changed.length + ' files, ' + r.result.failures.length + ' failures' : 'no result'}`).join('; '))

phase('Integrate')
const integ = await agent(`${COMMON}

STAGE B, integrate and verify. You may edit any file in website/, tests/, tools/, docs/, AGENTS.md, README.md and .github/workflows/website.yml to make the three build stages fit together. Their reports (JSON) are:
${JSON.stringify(buildReport, null, 1)}

Do, in order, and record each result:
1. git diff --stat; read every changed file end to end. Resolve mismatches between the stages against the brief (the brief wins; the satellite.py API in §4 item 1 is the contract).
2. python -m unittest discover -s tests: everything must pass. Fix real defects; never weaken a test to pass it; if a test is wrong against the brief, fix the test and say why.
3. Sample builds: python -m website.build --out /tmp/p2-off --sample and python -m website.build --out /tmp/p2-on --sample --storm-layers. Diff the two trees (diff -r, and compare data/map.json keys): the only differences must be the storm and satellite additions. Record the satellite frame's bytes and pixel size.
4. Live build with the network: python -m website.build --out /tmp/p2-live --storm-layers (h5py is installed here; this downloads about 4 MB from the GOES bucket plus the usual sources). Check the status table (every source ok; if the satellite status is not ok, find out why and fix it unless the feed itself is down), the frame file (bytes under 150,000; open it with PIL and check it is 700 x 439 with the palette and that cold pixels exist where the live band 13 field is cold), and the describe() text in the build output. Record the scan end, retrieved time and the latency.
5. Browser smoke on the live build and on the sample flag-on build: PW_CHROMIUM=/opt/pw-browsers/chromium python tools/smoke_map.py /tmp/p2-live (and /tmp/p2-on), and python tools/smoke_pages.py /tmp/p2-on. Both must pass. Also take screenshots of map.html with the Satellite layer selected (?layer=satellite) at 288, 390 and 1440 px wide into /tmp/p2-shots/ and look at them (Read the PNGs): the picture must sit under the legend, cold tops coloured, nothing overflowing; note what you see.
6. Write research/globe/validation-evidence/p2-verification.json per brief §4 item 11 (checked_at_utc, commands, results, numbers; no model names).
7. Re-run the full unit tests one last time.
Report every command and result; list anything you could not verify.`, { label: 'integrate', phase: 'Integrate', model: 'haiku', schema: BUILD_SCHEMA })
log('Integrate: ' + (integ ? integ.failures.length + ' failures, ' + integ.open_issues.length + ' open issues' : 'no result'))

phase('Review')
const REVIEW_COMMON = `${COMMON}

You are a REVIEWER. Do not edit any repo file; you may run read-only commands, the tests, the sample builds (to /tmp/review-*) and small Python checks in /tmp. Review the whole diff of this branch against main (git diff main...HEAD, plus untracked files: git status --short) for the P2 satellite layer. The integrate stage's report: ${JSON.stringify(integ)}. Treat every claim in the brief's implementation as a claim to refute; a finding needs evidence (a command you ran, a line you read, a reproduction). Severity: blocking = wrong data, a false or dishonest word on a page, the default build changed, a test that cannot fail, a crash path; major = a brief requirement missed, a wrong number, a misleading status; minor = wording, style.`
const reviews = await parallel([
  () => agent(`${REVIEW_COMMON}

LENS 1, evidence honesty and product rules: AGENTS.md rules 4 (Python first, documented browser-only JavaScript, no CDN), 5 (kinds apart; an observation never called a height, estimate, or hail signal; missing is hatched, never clear sky; sample labelled SAMPLE everywhere), 7 (contract and parser and tests change together; the About table), 8 (a real browser check happened, and the evidence file says what was checked), 9 (no best claims); docs/DESIGN.md states and wording; every colour class carries its word; the flag-off build byte-identical in words, keys and files; the DECISIONS and ROADMAP paragraphs are factual (no decision attributed to Carson that he did not make: he chose the staged route and said to start P2; the freshness limits and the kind word are proposals adopted for this build; counsel items D-G10 and D-G11 are still open). Check the legend note and contract sentences against the brief verbatim where the brief says verbatim. Check the noscript and List paragraphs, the problem banner, the About bullet and the timeline words in map.js for the satellite kind.`, { label: 'review:honesty', phase: 'Review', model: 'haiku', schema: REVIEW_SCHEMA }),
  () => agent(`${REVIEW_COMMON}

LENS 2, technical correctness, as a refuter: the fixed-grid geometry (compare latlon_to_scan with pyproj geos for several points on both satellites, including the sign of y and the row direction: y scale is negative and row 0 is north); the nearest-neighbour index and bounds checks (off-by-one at the grid edge; the G18 south-east corner must be no data); scale, offset, fill, valid_range and DQF handling (raw 4096 and DQF 2 must be no data); K to palette index (195 K -> index 2, 300 K -> top level, outside clamps; NaN -> 0 or hatch 1); the frame size under 150,000 B on a realistic field; time parsing of the file names (tenths of a second) and time_coverage_end; the two-hour listing across the hour and day boundaries (a build at 00:02 UTC must list the previous day's hour 23); STALE and UNAVAILABLE rules and the status words; the East-then-West fallback and what the source words say; build_satellite never raising (a get that raises, a listing that is garbage, a file that is not HDF5, h5py missing: each a status, and the layer still returned with frames []); the flag-off path has no satellite code running; map.js changes (a one-frame layer: range and play disabled, no autoplay, the title and the aria text, holdPicture/sameKind, hatch words, paintSwatches over Object.keys); the frame name never standing for two pictures; tests that actually fail when the code is wrong (mutate a constant mentally or for real in /tmp copy and see). Run the tests and the sample builds yourself.`, { label: 'review:technical', phase: 'Review', model: 'haiku', schema: REVIEW_SCHEMA }),
])
const findings = reviews.filter(Boolean).flatMap((r, i) => r.findings.map(f => ({ ...f, lens: i === 0 ? 'honesty' : 'technical' })))
const serious = findings.filter(f => f.severity !== 'minor')
log(`Review: ${findings.length} findings, ${serious.length} blocking or major`)

phase('Fix')
const fix = await agent(`${COMMON}

STAGE D, fix. The two reviews of the P2 diff returned these findings (JSON): ${JSON.stringify(findings, null, 1)}
Verified-ok lists: ${JSON.stringify(reviews.filter(Boolean).map(r => r.verified_ok))}

For every blocking and major finding: reproduce it first; if it is real, fix it minimally in the right file and add or strengthen a test so it would be caught; if it is not real, record why with evidence. Apply minor findings only when they are plainly right and cheap. Then re-run: python -m unittest discover -s tests; the two sample builds (brief §5) and their diff; PW_CHROMIUM=/opt/pw-browsers/chromium python tools/smoke_map.py on the flag-on sample build; python tools/smoke_pages.py on it. If you changed satellite.py's live path, re-run the live build python -m website.build --out /tmp/p2-live2 --storm-layers and the smoke on it. Write research/globe/validation-evidence/p2-review.json: each finding with severity, file, claim, outcome (fixed, not reproduced with evidence, deferred with reason) and the commands you ran; update p2-verification.json numbers if they changed. No model names anywhere. Report what changed and what remains open.`, { label: 'fix', phase: 'Fix', model: 'haiku', schema: BUILD_SCHEMA })

return { build: buildReport, integrate: integ, findings, fix }