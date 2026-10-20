# Resume guide: the hail history programme, paused 2026-10-20 (about 03:15 UTC)

Read this first, then `briefs/hail-b5-brief.md` (the product, the rulings D1 to D58, the part B2 build list and the
merge rules D49 to D51) and the tail of `supervisor-log.md`. Carson's standing instructions: the worker model workers in parallel
workflows (builders, read-only reviewers, two skeptics per finding with `defect_real && !refuted`, fixers, a re-check),
the supervisor model supervising every output against the product north star (one map; one sheet per place that leads with a plain
summary; a fixed section order; every number with its unit and kind word; nothing to decode); PRs stacked and
small; no AI-vendor, model or product names in repository files; no em-dashes; sentence case.

## Where everything is
| Thing | Where | State at the pause |
|---|---|---|
| main | `origin/main` | unchanged by this programme (the hail flags are off there) |
| B1 | `claude/hail-b1`, PR 13 | green, waiting on Carson |
| B2 | `claude/hail-b2` = db84d76, PR 14 (base B1) | green, waiting on Carson |
| B3 | `claude/hail-b3` = 1e32779, PR 16 (base B2) | green (the preview was re-run once after the branch's store job published, see PR comment), waiting on Carson |
| B4 | `claude/hail-b4` = 9693997, PR 15 (base B2) | green, waiting on Carson |
| research | `claude/hail-history`, PR 12 | waiting on Carson |
| B5 | pushed as `origin/session/hail-b5-wip` = ad4962b (local name `claude/hail-b5`; base db84d76; WIP commits fa33c8d, de0793c, dcb7e93, 26c737a, ea8f325, then the merge commit) | part A and part B1 done; the merge of B3 resolved, reviewed (three supersessions ruled, no loss; see the supervisor log of 03:12) and committed as the tip; B4 not merged; part B2 not started. Pushed under `session/` on purpose: a `claude/**` push runs the preview and the store job, and the half-merged job would overwrite the shared release asset |
| this state | `origin/session/hail-2026-10-20` (orphan branch; delete it when the programme ends) | briefs, logs, records, scripts, small caches, this guide |
| the published store | the `hail-store` release asset `hail-store.tar.gz` (72 MB packed, 31,129 files): B1 `t/`, B2 `j/` v1, `z/`, `s/`, B3 `a/`, `r/`, `b/`, `counts.json`; published by the B3 branch job on 2026-10-20 02:22 UTC; only branch pushes touch it (no store job is on main) | |

Merge order for Carson: 13, 14, then 15 and 16 (siblings on B2), then the B5 pull request (to be opened on the B4 one).

## Restore (about 15 minutes, plus the store rebuild below)
```bash
cd /home/user/RoofingApp && git fetch origin
mkdir -p /home/user/wt
for b in hail-b2 hail-b3 hail-b4; do git worktree add /home/user/wt/wt-${b#hail-} -b claude/$b origin/claude/$b; done   # wt-b2, wt-b3, wt-b4
git fetch origin session/hail-b5-wip && git worktree add -b claude/hail-b5 /home/user/wt/wt-b5 FETCH_HEAD
git fetch origin session/hail-2026-10-20 && git worktree add --detach /home/user/wt/wt-session FETCH_HEAD
bash /home/user/wt/wt-session/restore.sh "/root/.claude/projects/-home-user-RoofingApp/<this session's id>/workflows/scripts"
python3 -m venv /home/user/hail-b1/venv && /home/user/hail-b1/venv/bin/pip install -r /home/user/wt/venv-freeze.txt
pip install requests jinja2 pillow numpy pygrib h5py tzdata pyarrow "pyproj~=3.8" "pyogrio~=0.13" playwright   # the system python, for the suite and the self-test
```
The Workflow tool accepts `scriptPath` only under that session's `workflows/scripts/` folder; the folder exists once
any workflow has run (or create it). The worktree names, the venv path `/home/user/hail-b1/venv/bin/python` and the
output roots `/home/user/hail-b3/out`, `/home/user/hail-b4/out`, `/home/user/hail-b5/out` are what the briefs and
scripts expect; keep them.

## The stores (about 40 minutes; the figures in the brief were measured on 2026-10-19 and 2026-10-20)
1. The published asset: `curl -L -o /home/user/hail-b3/out/keep/hail-store-b3-job1.tar.gz https://github.com/carson14dy/RoofingApp/releases/download/hail-store/hail-store.tar.gz`
   (if a later branch push replaced it, the B3 job's log in run 39355361340 lists what that asset held).
2. B5's parts into `/home/user/hail-b5/out/b1/store` (extract the asset there first; the commands are
   `records/b5/store-ready.json` "builds", run from `/home/user/wt/wt-b5` with the venv python):
   `website.joins build --store STORE --cache /home/user/hail-b5/cache/joins --procs 2 --today 2026-10-19` (the NCEI
   and NWS archives are re-downloaded, about 150 MB; the rest of the joins cache is restored), `website.stations build
   --cache /home/user/hail-b5/cache --procs 2` (re-downloads the GHCN .dly files, 384 MB), `website.gauges build
   --cache /home/user/hail-b5/cache --offline --procs 2`, `website.climate build --cache /home/user/hail-b5/cache/nclimgrid`
   (the aggregates are restored; the 3.7 GB backfill is not needed), `website.snowgrid build --cache
   /home/user/hail-b5/cache --offline` (unavailable by design, D23). A later `--today` moves the window; the brief's
   counts then move too, which the re-checks measure again.
3. The combined store: `records/b5/combined/assemble.sh` (B5's store plus the asset's `a/`, `r/`, `b/`,
   `counts.json`, one index and manifest), then the D49 figure refresh and the manifest entry for `index.json` as the
   supervisor log of 02:0x describes (`addresses.refresh_figures`), then every module's verify (the log shows the
   commands and the `--cache` arguments). D50 in the brief records the expected figures (496,331,217 bytes, 45,644 files).

## Next steps (task 28, then the rest of 26)
1. The B3 merge review is done (verdict and rulings in the supervisor log, 03:12; the fixture is regenerated with `python -m website.hail fixture --out D --addresses-from <combined store>` then `python -m website.joins fixture --out D --from-store <store>`, not the positional form D51 names). The merge agent's report is `wt-b5-merge/merge-b3-journal.jsonl` (the resolver's "decisions
   for you to confirm" were accepted: the county key rename `census_tiger_counties`, the `iem_lsr` assertion, the
   fixture budget 62 KB (D54), the `joins.fixture` D44 fix, the roadmap B4 wording). The read-only review's verdict is
   in the supervisor log's last lines if it finished before the pause; otherwise run `scripts/hail-b5-merge.js` with
   `{"branch": "claude/hail-b3", "label": "b3"}` again on a fresh `git merge --no-commit` only if losses are suspected
   (the tip already carries the merge; a review-only pass can diff the tip against `claude/hail-b3` per D51).
2. The B4 merge: in wt-b5 `git merge --no-commit --no-ff claude/hail-b4`, then the Workflow tool with
   `scripts/hail-b5-merge.js` and args `{"branch": "claude/hail-b4", "label": "b4"}`; expected conflicts:
   `.github/workflows/website.yml`, `AGENTS.md`, `README.md`, `docs/DECISIONS.md` (D37 goes between D36 and D38),
   `docs/DESIGN.md` (section 11), `docs/ROADMAP.md`, `tests/test_site.py`, `tools/smoke_map.py`, `website/build.py`,
   `website/static/map/map.js`; the supervisor commits after the review.
3. Part B2 on the merged tree: `scripts/hail-b5b2-build.js` with `{"owners": ["browser", "site"]}` in one workflow and
   `{"owners": ["products", "smoke"]}` in another (two agents per workflow on 4 CPUs), then the docs and record owner
   (build list item 5) and a completion re-check against the gates in the brief's "Part B2 build list"; the Python
   remainder (D53, D55, D56, D57) is in those owners' items.
4. Squash onto db84d76 (`git reset --soft db84d76; git add -A; git commit -F msg`; signed), push `claude/hail-b5`
   (the preview and the store job run; the D49 wait step makes the preview wait for the store job), check the preview
   in a browser, open the pull request on `claude/hail-b4` with the repo's template, subscribe to it.
5. Report to Carson the open decisions: the 10-minute timer (an external trigger with workflow_dispatch); the data
   repository for the bulk files (the combined store is 496 MB raw; the B3 asset alone 72 MB packed); the gauge
   distance 10 or 25 miles; whether the swath picture stops at the state line; the NOHRSC snow analysis held (slope
   0.664); the counsel list of 18 items (MSL "for no other purpose", MCA 2-6-1017, the FEMA licence).

## Harness facts learned (so Friday does not relearn them)
- 4 CPUs: 2 agents per workflow; several workflows side by side; the worker model workers (`model: WORKER`), the supervisor model supervises.
- Scripts are plain JS; a backtick inside a template literal breaks parsing (use quotes); check with `node --check`
  after wrapping the body in `async function __w(){...}`.
- The writable disk allowance is about 40 GB and fills fast: archive small evidence (<1 MB JSON, MD, LOG; never store
  shards) before deleting bulk scratch; never delete under a running stage's output root; `pkill -f` only with an
  anchored pattern or it kills the shell.
- Agents never run git write commands (the supervisor commits); WIP safety commits use `-c commit.gpgsign=false`;
  real commits are signed; the final squash is one signed commit; push with retries.
- Untrusted downloads are read with `python -I` from the venv; TLS verification is never disabled.
- Branch previews read the release asset as published when the build starts (D49 explains the wait step).
- `gh` has no valid token in these sessions; use the GitHub MCP tools (actions_get, actions_run_trigger,
  pull_request_read, add_issue_comment) and git over the ssh helper; the public REST API works without a token for
  run status.

## Model names
The worker and supervisor model names are not written in repository files (a repo rule). The scripts read the worker alias from `args.worker` at launch (pass `{"worker": "<alias>", ...}`); Carson names the worker and supervisor in chat (the small fast tier does the work; the session's own model supervises).
