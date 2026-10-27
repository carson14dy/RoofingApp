# Base map fix brief: the vectors never load on main (claude/basemap2-fixes)

Supervisor: Fable. Workers: Haiku investigator-builder, two skeptics, a fixer, a verifier. Owner: Carson. Date: 2026-10-27.

## Where and how
- Worktree: `/home/user/wt/wt-bm2`, branch `claude/basemap2-fixes` from main at 3d62235. Edit files there only.
- Python: `/home/user/hail-b1/venv/bin/python` (PY). Never install packages. Never run a git command that writes.
- Disk is tight (about 3.7 GB free). A scratch store and a scratch cache go under
  `/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/bm2/<your label>/`, stay under
  300 MB together, and are removed when you finish. Never copy `/home/user/hail-b5/out/b6/store-copy` or its caches; read
  them in place (the P2 cache of the local build is `/home/user/hail-b5/out/b6/cache/P2`, read only).
- The runner logs of main's store run 21 (2026-10-27): the monthly job
  `/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/logs/monthly-run21.log` and the
  daily job `.../scratchpad/logs/store-run21.log` (same folder). Read them with grep and sed; they are 2,100 and 17,200 lines.
- The module is `website/basemap2.py` (its docstring holds the rules), its tests `tests/test_basemap2.py`, its contract
  rows in `website/sources.py` CONTRACTS, the job steps in `.github/workflows/hail-store.yml` (grep "basemap2").

## What happened on main
Both monthly runs (20 and 21) published the base map vectors as unavailable, and so does every daily run. Three facts:
1. `basemap2 verify` crashes: `FileNotFoundError: 'store/store/hail/base/v/b/n44w106.json'` from `read_band`
   (`website/basemap2.py` about line 2224), called from `verify` about line 2247. The cause is at about line 2243:
   `have = {(store / p).relative_to(store).as_posix() for p in (store / prefix).glob("*.json")}`: the glob already yields
   paths under `store`, so `store / p` doubles the folder when `--store` is a relative path (`store`, as the job passes
   it). With an absolute path, `store / p` is just `p`, which is why every local check passed. The daily job's verify step
   crashes the same way, so its mark step sets the vectors unavailable every day.
2. The monthly build hits its deadline. Run 21: 1,078.9 s, 13 requests, 2,395,851 bytes downloaded; every water band (A to
   D) failed with two HTTP 504 answers and then "deadline"; the peaks hit the deadline; band D built 0 of 4,597 tiles; the
   forests, parks, reservations, routes and places of bands A to C loaded (state partial). Run 20 (cold) was the same. The
   local build of 2026-10-25 and 2026-10-26 from this machine loaded the water statewide at zooms 5 to 12 and 20 band D
   tiles. So the question is where the runner's 1,020 s went: the NHD queries (`NHD_URL`, hydro.nationalmap.gov), their
   paging (250 features per page for the large-scale layers after a 504 at 1,000), the read timeout (`READ_TIMEOUT`), the
   pacing (`PACE_S`), and what a 504 costs (retries, waits) decide how much of the budget each failure eats.
3. The cache rule is not a defect: after a failed request the cache pruning is skipped (D112(m)); the workflow still saved
   the cache (25,290,082 bytes after run 20), and the daily job's offline build reads it and reports the same partial state
   ("the cache has no copy and this build makes no requests" for water and peaks). Do not change the pruning rule.

## Tasks
A. Fix fact 1 with a regression test: build a small store with the module's own test helpers (see how
   `tests/test_basemap2.py` makes a store and an index), then run `verify` with a relative `--store` path (chdir into the
   temporary folder, pass `store`). The test fails before the fix and passes after; say so with the output of both runs.
   Look for the same pattern elsewhere in the module (`store / p` where `p` is already under `store`; also for the cache).
B. Make the water fetch finish inside the cap on a slow service. First measure, from this machine, with live requests
   (AGENTS.md rule 7): time the band A water queries the module sends (the small-scale lines and areas over the state
   envelope; build the exact URL and params with the module's own functions, `nhd_params` and the paging in
   `fetch_pages`) and one band B cell's query; record status codes, seconds and feature counts for each, three times each,
   one request at a time, respecting `PACE_S`. Then read how the module applies the deadline per request and per kind, how a
   504 is retried and what one failed request costs at most. Then choose and implement the smallest change that makes bands
   A to C water load within the monthly budget on a slow service: for example split the statewide water envelope into cells
   before the first try when the statewide query times out, a smaller page, a bound on the retry cost of one request, the
   fast kinds first so the deadline falls on band D, or a wider deadline share for water. Keep the module's contract (the
   CONTRACTS rows, units, formats, budgets) unchanged; document each new rule in the module docstring and pin it with a
   test. Measure the result locally with a cold scratch cache and `--deadline-at` set to now plus 1,020 seconds, and report
   the figures (seconds, requests, bytes, state, water_bands_failed). If the service itself answers 504 to every statewide
   query from here too, say so with the evidence and implement the split anyway.
C. Do not change `.github/workflows/hail-store.yml` unless the fix needs a flag the step must pass (then the smallest
   change, with `tests/test_hail_workflow.py` updated); the cap itself is the owner's decision (ROADMAP open item 12).
D. Run `PY -m unittest tests.test_basemap2`, then the whole suite `PY -m unittest discover -s tests`, and the job's own
   commands as the yml writes them (build with `--deadline-at`, then `verify --store store --cache ...`) on the scratch store
   from a working directory where `store` is a relative path. Wording rules: sentence case, no em-dash, no AI vendor or
   product name, plain words in any visitor-facing sentence (the problem sentences come from `WORDS`).

## Report shape (every agent)
JSON: `{files: [...], measurements: [{what, url_or_params, status, seconds, features}], changes: [...], tests: {added,
updated, command, result}, checks: [{what, how, result, evidence}], open: [...], summary}`. A claim without its command
and output is not accepted.
