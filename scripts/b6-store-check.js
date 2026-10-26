export const meta = {
  name: 'b6-store-check',
  description: 'B6 stage 2: the store copy\'s parts rebuilt in sequence with the final modules and checked (the first half of the final check, D136(d))',
  phases: [{ title: 'Check', detail: 'one store checker' }],
}
const worker = 'haiku'
const WT = '/home/user/wt/wt-b6'
const PY = '/home/user/hail-b1/venv/bin/python'
const STORE = '/home/user/hail-b5/out/b6/store-copy'
const CACHE = '/home/user/hail-b5/out/b6/cache'
const CHECK = { type: 'object', properties: { steps: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, pass: { type: 'boolean' }, seconds: { type: 'number' }, evidence: { type: 'string' } }, required: ['name', 'pass', 'evidence'] } }, tests: { type: 'string' }, manifest: { type: 'string' }, measurements: { type: 'string' }, not_read: { type: 'array', items: { type: 'string' } }, scans: { type: 'string' }, notes: { type: 'string' } }, required: ['steps', 'tests', 'manifest', 'measurements', 'not_read', 'scans', 'notes'] }
const common = ' The worktree is ' + WT + ' (branch claude/map-b6); the Python is ' + PY + '. You edit nothing in the worktree; another agent edits website/build.py, website/templates/about.html and tests/test_site.py at the same time (not your concern; do not run tests.test_site). Your scratch is /home/user/hail-b5/out/b6/build/store-check/ only (make it; keep logs there). Never run a git write command (git status and git diff are allowed). Make no network request: every build runs --offline from its cache.'
phase('Check')
const check = await agent('You are the store checker of the B6 map build (the first half of the final check).' + common +
  ' The store copy is ' + STORE + ' (hail/index.json and hail/manifest.json are there; hail/base/index.json is the shared base index with "f": "hail-base-index-v1", which no writer discards: if a writer refuses it, say so, stop that step and never delete it). The caches are ' + CACHE + '/P1 (terrain), /P2 (base map vectors), /P3 (landmarks) and /P4 (history layers). Steps, in this order, each timed with its seconds recorded: ' +
  '1. ' + PY + ' -m unittest tests.test_terrain tests.test_basemap2 tests.test_landmarks tests.test_history_layers tests.test_labels tests.test_hail_workflow tests.test_website_workflow -v (counts and every failure by name). ' +
  '2. Read ' + PY + ' -m website.terrain --help (and build --help) for the exact flags, then run the terrain build on the store copy from the P1 cache with --offline, then the terrain check command. ' +
  '3. The same for website.basemap2 from the P2 cache with --offline, then its check. ' +
  '4. The same for website.landmarks from the P3 cache with --offline and --now 2026-10-17T12:00:00Z, then its check. ' +
  '5. The same for website.history_layers from the P4 cache with --offline and --now 2026-10-17T12:00:00Z, then its verify. ' +
  '6. The buildings verify (website.buildings, read --help) on the copy, then ' + PY + ' -m website.labels build --store ' + STORE + ' --tiles r0081_c0160 r0092_c0214 r0092_c0215 --now 2026-10-17T12:00:00Z (read --help for the exact flags), then the labels verify. ' +
  '7. The manifest check on the copy: hail.check_manifest (read its signature in website/hail.py; or the module command that calls it). ' +
  'Then measure and record: the byte sizes of hail/base/index.json, hail/index.json and hail/manifest.json; the terrain tile total in bytes and count under hail/base/h and hail/base/l; the landmark shard count and the shown point count across hail/base/p; the bubble count in the three label tiles; the newest warning date in hail/history/index.json or zones.json. Read hail/base/index.json and hail/index.json and list in not_read every source or layer whose state is not read, loaded, fetched or cache (the sources the About page must not credit), with the state word the index uses. ' +
  'Then scan website/terrain.py, website/basemap2.py, website/landmarks.py, website/history_layers.py, website/labels.py, website/sources.py and .github/workflows/hail-store.yml for em-dashes (U+2014) and for AI model, vendor or product names (a URL path, a repository URL, a service type code, a cited reference or the platform that serves a public data set is not one). ' +
  'At the end delete your scratch folder except the logs. Return the steps with pass, seconds and evidence, the test summary, the manifest result, the measurements, not_read, the scans and notes (what is open).',
  { label: 'check:store', phase: 'Check', model: worker, schema: CHECK })
return { check }
