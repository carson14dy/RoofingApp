export const meta = {
  name: 'cleanup-inventory',
  description: 'Inventory of everything in the repository that belongs to the parked desktop app or the 3D globe research, for the cleanup PR (D143(b)): read-only',
  phases: [{ title: 'Inventory', detail: 'two readers in parallel, then one merge' }],
}
const worker = 'haiku'
const WT = '/home/user/wt/wt-b6'
const INV = { type: 'object', properties: { delete_paths: { type: 'array', items: { type: 'string' } }, edit_sites: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, lines: { type: 'string' }, what: { type: 'string' } }, required: ['file', 'lines', 'what'] } }, keep_notes: { type: 'array', items: { type: 'string' } }, risks: { type: 'array', items: { type: 'string' } } }, required: ['delete_paths', 'edit_sites', 'keep_notes', 'risks'] }
const common = ' The repository checkout to read is ' + WT + ' (branch claude/map-b6, which carries everything main will hold after the merges). Read only: edit nothing, run no git write command, make no network request. You may run grep, find, ls, cat and python -c for counting.'
phase('Inventory')
const [app, globe] = await parallel([
  () => agent('You inventory the parked desktop app in a Python repository, for a cleanup that removes it.' + common +
    ' The product is now the website (website/, tools/, tests of the website, docs/). The parked app lives in payload/ and desktop/ with build.py (PyInstaller) and ship.py (test, bump, push) at the root, requirements.txt, and tests under tests/ for the app (acceptance checks, alert scenarios, outage replay, the update channel against a fake GitHub, the self-test). Find every file and every reference that belongs only to the app: list the paths to delete (whole folders where the folder is the app\'s), every edit site elsewhere (AGENTS.md, CLAUDE.md, README.md, docs/*.md, .github/workflows/*.yml, .gitignore, requirements*.txt, tests that import payload or desktop, tools that reference them) with the lines and what to change, what must stay because the website uses it (for example a shared module, a fixture, a requirement the website also needs: check website/ imports against requirements.txt), and the risks (a website test that imports from payload; a workflow step that runs the self-test; docs that cite app rules). Return delete_paths, edit_sites, keep_notes and risks.',
    { label: 'inventory:app', phase: 'Inventory', model: worker, schema: INV }),
  () => agent('You inventory the 3D globe research in a Python repository, for a cleanup that removes it.' + common +
    ' The decision D107 (docs/DECISIONS.md) says the finished map has no 3D view; the globe plan and prototype under research/globe/ (the README, the plan sections, the prototype page, MRMS volume, GOES cloud height and 3D storms layer files) are research that the product does not use. Find every file under research/ that belongs to the globe work and every reference to it elsewhere (docs/ROADMAP.md, docs/DECISIONS.md, README.md, AGENTS.md, tests, tools, workflows), and separately list what else under research/ exists and whether the roadmap or decisions still cite it (the hail research scaffold, the programs list, the owner decisions, the B6 reference records): those stay unless nothing cites them. Return delete_paths (the globe files), edit_sites (each reference to change, with lines and what to change), keep_notes (what under research/ stays and why) and risks.',
    { label: 'inventory:globe', phase: 'Inventory', model: worker, schema: INV }),
])
return { app, globe }