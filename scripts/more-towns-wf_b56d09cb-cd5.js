export const meta = {
  name: 'more-towns',
  description: 'Add Belgrade, Anaconda and Sidney to the site, rebuild the base map, verify in tests and a browser',
  phases: [
    { title: 'Build towns', detail: 'towns.json, min_zoom rule, base map rebuild, docs', model: WORKER },
    { title: 'Verify towns', detail: 'tests, sample and live builds, browser check, fixes', model: WORKER },
  ],
}
const WORKER = (typeof args !== 'undefined' && args && args.worker) || undefined  // the worker model alias, passed in args at launch

const WT = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/wt-towns'
const COMMON = `You work in a git WORKTREE at ${WT} on branch claude/more-towns (from main). Every command runs there (cd ${WT} first; use absolute paths under ${WT} for every file you read or edit). Never touch /home/user/RoofingApp itself (another job is editing it). Never commit, never push, never change git state (git status/diff/log are fine). Never write a model, vendor or AI-product name into any repo file. Plain wording, sentence case, no em-dashes in new prose. Verify first: git -C ${WT} branch --show-current must print claude/more-towns.

TASK (owner Carson, 2026-10-17): add every Montana city with a 2020 census population above 8,000 that the site lacks, plus Sidney at his request. Today's 14 towns: Billings, Bozeman, Butte, Glasgow, Glendive, Great Falls, Havre, Helena, Kalispell, Lewistown, Livingston, Miles City, Missoula, West Yellowstone. Add exactly three (2020 census, Wikipedia list of municipalities; coordinates from each town's infobox):
- Belgrade, Gallatin County, 10,460, lat 45.7803 lon -111.1752 (12 km west of Bozeman: its bubble would cover Bozeman's below about zoom 9)
- Anaconda (Anaconda-Deer Lodge County, consolidated), 9,421, lat 46.133 lon -112.933 (35 km west of Butte: bubbles touch below about zoom 8)
- Sidney, Richland County, 6,346, lat 47.7155 lon -104.1672 (north-east corner; Glendive is 65 km south and is a minor town)
Whitefish (7,751) and Laurel (7,222) are under 8,000: do not add them. Census-designated places (Lockwood, Evergreen) are not towns: do not add them.

RULES OF THE SITE you must honour: website/towns.json is the town list (AGENTS.md: set a new town's label side there; the label test must pass); the base map is rebuilt by python tools/build_basemap.py (downloads Natural Earth and us-atlas, pinned by hash; keep the downloads with --src ${WT}/../basemap-src so a rerun is fast) and committed; tests/test_basemap.py fails until it is rebuilt. "minor": true today means a town shows from zoom 7 (tools/build_basemap.py lines 841, 885-889, 1115, 1234, 1499; website/static/map/map.js lines 401, 632, 1354-1356, 1786; tools/smoke_map.py line 79; docs/DESIGN.md line 150). Generalise it to an integer "min_zoom" per town (default 5; "minor": true keeps meaning 7, so the four minor towns need no change): Belgrade min_zoom 9, Anaconda 8 (check both in the browser and raise or lower by one if bubbles still overlap or names collide; the label test is the arbiter for names). Python decides the rule (build.py's map_data passes "min_zoom" to data/map.json next to "minor"); map.js reads t.min_zoom (fallback: minor 7, else 5) in its four places, each change commented in the file's own style. The sample data (website/sample.py) must serve the new towns too (check the dict lookups by slug have defaults; invent SAMPLE values only where a dict needs an entry for a sensible page). Docs: README.md line 109 ("the 14 towns"), docs/DESIGN.md line 150 (the minor-town sentence becomes the min_zoom rule, naming the two new towns' zooms), docs/ROADMAP.md line 115 (the open question: answered 2026-10-17, state what was added and why), docs/DECISIONS.md: a new entry D31 "Towns: every Montana city over 8,000 plus Sidney (2026-10-17)" in the house style (bold title line, a short paragraph with the census figures and the min_zoom rule, then "*Why:*"). NWS offices: the build looks them up live; expected Belgrade -> Great Falls, Anaconda -> Missoula, Sidney -> Glasgow.`

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

phase('Build towns')
const build = await agent(`${COMMON}

STAGE 1, build. Do it in this order: (1) read towns.json, build_basemap.py's town handling, map.js's four minor places, build.py map_data, sample.py, tests/test_basemap.py and tests/test_site.py; (2) edit towns.json; (3) implement min_zoom in build_basemap.py, build.py and map.js, and in tools/smoke_map.py line 79 (count towns whose min_zoom is below 7 as the ones shown at the first view); (4) rebuild the base map: python tools/build_basemap.py --src ${WT}/../basemap-src (then --check must exit 0); (5) run python -m unittest discover -s tests (all must pass) and the sample builds python -m website.build --out ${WT}/../towns-off --sample and with --storm-layers; (6) docs. Report measured facts (basemap.json bytes before and after, label changes the builder printed, which label sides you chose and why).`, { label: 'build:towns', phase: 'Build towns', model: WORKER, schema: SCHEMA })
log('Build towns: ' + (build ? build.failures.length + ' failures, ' + build.open_issues.length + ' open issues' : 'no result'))

phase('Verify towns')
const verify = await agent(`${COMMON}

STAGE 2, verify and fix. The builder's report: ${JSON.stringify(build)}.
Do, and record each result: (1) git -C ${WT} diff --stat and read every changed file end to end; check the three coordinates against the task, and that nothing else in towns.json changed; (2) python -m unittest discover -s tests must pass; python tools/build_basemap.py --src ${WT}/../basemap-src --check must exit 0; (3) sample builds (both flags) and the browser smoke: PW_CHROMIUM=/opt/pw-browsers/chromium python tools/smoke_map.py <sample dir> and python tools/smoke_pages.py <sample dir> must pass; (4) a live build: python -m website.build --out ${WT}/../towns-live --require-live and read its status table and content: Belgrade, Anaconda and Sidney must have an NWS forecast, an office (Great Falls, Missoula, Glasgow) and station readings like the other towns; (5) in Chromium (Playwright, a scratch script outside the repo) open the live build's map.html at 1280x800 and 390x844, then zoom and pan to Bozeman at zooms 7, 8, 9 and to Butte at zooms 7, 8, and to Sidney at zoom 5 and 7: take screenshots into ${WT}/../towns-shots/ and LOOK at them (Read the PNGs): no bubble may cover another bubble or a name, Belgrade must appear only from its min_zoom, Anaconda from its; if anything overlaps, adjust min_zoom or the label side, rebuild the base map and re-run the tests; (6) the Now page lists 17 town cards and each new town page opens; (7) git diff of website/static/map/basemap.json: describe what changed (new places, shifted min_zooms) and confirm the file is still under its size budget test. Fix real defects minimally; never weaken a test. Report every command and result, and anything you could not verify.`, { label: 'verify:towns', phase: 'Verify towns', model: WORKER, schema: SCHEMA })

return { build, verify }