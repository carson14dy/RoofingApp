# README brief: README.md tells the truth about main today (2026-10-27)

Supervisor: Fable. Workers: Haiku builder, two skeptics, a fixer, a verifier. Owner: Carson, who asked "Can you update the readme".

## Where and how
- Worktree: `/home/user/wt/wt-readme`, branch `claude/readme-update` from main at 3d62235. Edit `README.md` there and
  nothing else (a test that pins a README sentence is read, not changed).
- Python: `/home/user/hail-b1/venv/bin/python` (PY). Never install packages. Never run a git command that writes.
- The live site: https://carson14dy.github.io/RoofingApp/ with its data files `data/map.json` and `data/base.json`
  (curl them; read the `state` and `problem` fields of the blocks `hail`, `hail.climate`, `base`, `base.vector`,
  `base.terrain`, `base.landmarks`, `history_layers`, `recent` and `labels`). Say what they say at the time you read them.
- The facts live in the tree: `docs/ROADMAP.md` (what is done, the open items), `docs/DESIGN.md` (sections 9 to 13: the
  hail history, the addresses, the swath layers, the past weather, the map's own cartography), `docs/DECISIONS.md` (D143
  is the newest), `.github/workflows/website.yml`, `hail-store.yml` and `tests.yml`, `website/build.py --help`,
  `requirements.txt`, `AGENTS.md`. Read with grep -n and sed -n ranges; never a large file whole.

## What the README is for
Three readers: Carson (the owner), a crew lead who opens the site on a phone, and a contributor or agent who builds it.
It says what the site is and shows, how it stays honest, how it updates, how to build and check it, and where the
files are. Keep the file's structure (the Contents list and its six sections), its voice (plain words from the user's
side, sentence case) and its length (about 190 lines now; stay under 240). Change what is stale, add what main has and
the README lacks, and leave right sentences alone.

## What main has today that the README may lack or misstate
1. The five-year weather history of every location (B5, DESIGN section 12): the five-season table that leads the sheet
   (2021-22 to 2025-26, July to June, with the partial 2026-27 line) and the sections (hail, wind, storms and warnings,
   temperature, rain, snow, flooding, ice and winter, heat, weather that matters for a roof, how this was made), the town
   pages, the station readings, the river gauge record on town pages, and what is held (the snow analysis, D7).
2. The Map page's own cartography data (B6 part 1, DESIGN section 13; on main since PR 18): the terrain tiles (relief and
   land cover tint, zooms 5 to 10), the base map vectors in four zoom bands (reservations, forests, parks, water, routes,
   places, summits), the landmark points (schools, hospitals, airports, fire and EMS stations, parks; places of worship
   and the Census park points held for counsel), the five-year hail and heat pictures, the zone counts (eight measures),
   the recent radar hail cells and the value bubble anchors. The store jobs build them; the Map page does not draw them
   yet: the browser side (the options sheet and the layers, DESIGN 13.5 to 13.7) is being built on a branch and lands
   with its own pull request. The README says so in one sentence and does not describe the sheet as if it were live.
3. The store jobs: the daily job (`hail-store.yml`, 12:43 UTC; the store, the joins, the B5 parts, the B3 steps, the
   B6 parts from the caches, the bubble labels, the manifest check, the asset `hail-store-main.tar.gz`) and the monthly
   job (the first of the month or by hand: the station union, the gauges, the landmarks asked again, the snow check,
   the terrain tiles and the base map vectors with their caps). The Website build reads the asset; a store older than
   three days is a failed source.
4. The checks: `tests.yml` ("Tests") runs the suite on every push to main, every pull request and by hand after
   `pip install -r requirements.txt`; `requirements.txt` is the website's package list; the Website workflow builds
   every branch push against live data and runs the Chromium smoke. The desktop app was removed on 2026-10-26 (D143).
5. The public site as of today, honestly and briefly: read the live data files and say what reads Data unavailable and
   why, in one short paragraph headed with the date: the base map vectors (a verify defect and the water service's
   timeouts; a fix is on a branch), the climate rows and the heat picture (the once-only climate backfill is running on
   main; its archive is the hail-climate release). Point to `docs/ROADMAP.md` for the owner's open items and the counsel
   items rather than listing them.
6. Every command in the README works: run each `python -m website.<module> ... --help` to confirm the flags exist, and
   run the test command lines you cite. Every path named exists on main (`ls`). Every number comes from DESIGN, ROADMAP
   or the live site and is the current one (the test count is 2,492 OK with 12 skipped on main; the town count; the
   file counts). Relative links and anchors resolve (write a short script that checks every `](...)` target).

## Rules
- Plain words from the user's side; sentence case; no em-dash; no AI vendor, model or product name beyond the existing
  line that addresses the agents; a feature that fails says what happened and what the reader sees.
- Evidence honesty in every sentence about data: estimates are estimates, not measurements or inspections; missing is
  never zero; held is held.
- The tests that read the README keep passing: grep "README" in `tests/test_addresses.py`, `tests/test_gridded.py`,
  `tests/test_storm.py` and `tests/test_streets.py` to see which sentences they pin, and keep those sentences.
- Check: `PY -m unittest tests.test_addresses tests.test_gridded tests.test_storm tests.test_streets tests.test_site`.

## Report shape (every agent)
JSON: `{files: [...], changes: [...], checks: [{what, how, result, evidence}], open: [...], summary}`. A claim without
its command and output is not accepted.
