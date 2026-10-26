# B6 build brief, stage 2, phase B: the integrator (the shared files)

Read first: briefs/map-b6-build-brief.md (the product brief; the store layout), the four products' integration.md and report.md
under /home/user/hail-b5/out/b6/build/P1..P4/, the supervisor rulings D107 to D114 (the text is in the brief file
briefs/hail-b5-brief.md, the sections of 2026-10-25 and 2026-10-26; the integrator copies the rulings into docs/DECISIONS.md as the
D38 round's next bullets in the same style as D101 to D105), docs/DECISIONS.md, docs/DESIGN.md, docs/ROADMAP.md, AGENTS.md,
website/build.py (the store copy list HAIL_FOLDERS and HAIL_FOLDERS_B5, the map.json blocks, the budgets), website/sources.py
(CONTRACTS), .github/workflows/hail-store.yml (the daily B5 steps on the clock and the monthly job), .github/workflows/website.yml
(on.push.paths and the offline unittest line; PushPathsCoverTheTests pins them), website/templates/about.html, tests/test_site.py
(the copy list, the map.json keys and the About words are pinned there), tests/test_website_workflow.py.

The worktree is /home/user/wt/wt-b6 (branch claude/map-b6). Never run git write commands. Keep every product module as the
reviewers and fixers left it; the integrator edits only the shared files and the tests that pin them. No AI model, vendor or
product names in repository files; no em-dashes; sentence case; plain words; every credit line reads "Source: ..." or "... from
..." and never implies endorsement (D113(a)).

Tasks, in order:
1. website/build.py: HAIL_FOLDERS_B6 = ("base", "history", "recent") copied by _copy_hail when present (a missing folder is a
   stated absence in the index, never an error); the map.json blocks the products' integration notes name: "base" (the tile URL
   templates for h and l with their zooms 5 to 10, the band files and cells, the landmark shard pattern, the peaks and places
   files, each source's credit line, the as_of per source, the held kinds with their reason, the words the browser prints:
   "Data unavailable" sentences per layer, the legend lines of D110), "history_layers" (the two pictures with their bounds,
   classes, colours and legend words; zones.json; the newest-warning date in D113(d) words), "recent" (cells.json, the window,
   the as_of, the stale sentence) and the label flags' words (the bubble glyph "--" and its legend sentence, D110(c)); the
   budgets block gains the base tiles' statewide bytes and the per-band budgets. Every string the browser will print comes from
   map.json (D29, D41). The identity rule: a build without the new store parts writes the blocks as "unavailable" with the D20
   sentence, so the sample build and the default build keep their byte-identical pages apart from the new keys (tests pin this).
2. website/sources.py: one CONTRACTS row per source from the integration notes (name, request, units, timing, missing), the
   words corrected by D112(c), D113(b), D113(c), D113(d); tests/test_site.py or tests/test_sources.py pins the rows exist.
3. .github/workflows/hail-store.yml: the monthly job runs P1 (terrain build, --timeout 60, a 20-minute step cap, non-fatal, the
   cache restored and saved) and P2 (band A to C each run, band D continued under the step's deadline), each with its verify and
   its unavailable mark; the daily job runs P3 (landmarks), P4 history_layers and recent after the joins, and the labels pass
   after the outlines step, all non-fatal on the B5 clock with the clock checks the other B5 steps use; pyshp installed for the
   parks source; the pack and the manifest check cover the new folders; hail.check_manifest runs after the last part.
4. .github/workflows/website.yml: on.push.paths and the offline unittest line list the five new test modules (PushPathsCoverTheTests
   passes); the parity step is unchanged.
5. website/templates/about.html: one sentence per source with its credit line under the existing hail history headings (the
   base map sources, the landmark kinds and the held church kind with its reason, the five-year pictures, the zone counts, the
   recent radar hail switch); the words from the integration notes corrected by the rulings.
6. docs: docs/DECISIONS.md gains the D107 to D114 bullets (and D115 for anything the integrator had to decide, stated as a
   question for the supervisor); docs/DESIGN.md gains section 13 "The map's own cartography, the options sheet and the value
   bubbles (B6)" with the store layout, the bands, the budgets, the sheet spec (from /home/user/hail-b5/out/b6/design/sheet/spec.md
   with D110 applied) and the bubble rule; docs/ROADMAP.md: the B6 row and the owner items (bubble rule A or B, the sheet,
   counsel items 21 to 24); README.md's layout and commands lines for the new modules.
7. Tests: extend the pins (the copy list, the map.json keys, the words) and run the whole suite: python -m unittest discover -s
   tests must pass with no failure; the parked self-test python desktop/launcher.py --selftest payload must pass.
8. A local build from the adopted store with the new parts: copy the products' test stores' new folders into one writable copy
   of the store's index, manifest and the folders the site build reads (or build the parts in place into that copy from the
   caches: P1 and P2 cache-only builds take seconds; P3 20 s; P4 a few minutes statewide for the labels, which may be skipped for
   the Missoula and Billings tiles only); run python -m website.build --out /home/user/hail-b5/out/b6/site --hail-history
   --hail-addresses --hail-store <copy> --now 2026-10-17T12:00:00Z; run hail.check_manifest on the copy; run the Chromium smoke
   tools/smoke_map.py with --addresses --history and record the phone view bytes (the new tiles and bands are not drawn yet, so
   the figure is the baseline for B6-3); write /home/user/hail-b5/out/b6/build/integrator/report.md with every figure, the
   suite result and what is open.

## Additions from the part 1 chains (2026-10-26; D116 to D121)
- Read each product's integration.md "Rulings pass" section: it carries the exact website.yml lines (the five test modules in
  on.push.paths and the offline unittest line), the .gitignore lines (terrain-cache/, b6-cache/, !tests/fixtures/**/*.zip), the
  hail-store.yml commands (P1 build and verify with --timeout 60 and --refresh monthly; P2 with --deadline-at under a 20-minute
  cap; P3 daily and monthly with --refresh; hail.check_manifest after the last store writer), and the words for map.json.
- The store writers run one after another; every base index writer now carries "f": "hail-base-index-v1" and keeps the other
  products' keys. The store copy for the local build takes the land cover tiles from /home/user/hail-b5/out/b6/build/P1/store
  (the adopted store's tiles predate the wetland class change) and the rebuilt P3 store (held rows and counts are not written).
- About sentences are in the "Source: ..." form (D113(a), D121(a)); the legend keeps the labelled lines ("Relief: ...", "Land
  cover: ..."). No number derived from a held source appears anywhere on the page (D118(b)); held kinds and sources show
  "held" with the reason.
- The landmark display-name owner items, the bubble side option, the kv wording and the cold-run figure are owner items in
  docs/ROADMAP.md; the counsel items 21 to 24 and the TIGER area landmark use constraints stay listed.
- D122: the P2 monthly step reads vector.state from hail/base/index.json after the build (build exits 0 for an unavailable
  store); the water line words of D122(b) go into map.json; the About sentences for the forest boundaries and the lakes and
  rivers are written (not held); AGENTS.md's website install line gains pyshp; .gitignore gains !tests/fixtures/**/*.zip.
