# Resume guide: the hail history programme, paused 2026-10-22 00:30 UTC (second pause)

Read this first, then `briefs/hail-b5-brief.md` (the product, the rulings D1 to D60, the part B2 build list, the
merge rules) and the tail of `supervisor-log.md`. Carson's standing instructions: the worker model in parallel
workflows (builders, read-only reviewers, two skeptics per finding with `defect_real && !refuted`, fixers, a re-check);
the supervisor model reads every output against the product north star (one map; one sheet per place that leads with
a plain summary; a fixed section order; every number with its unit and kind word; nothing to decode); PRs stacked and
small; no AI-vendor, model or product names in repository files; no em-dashes; sentence case.

## What happened between the pauses (2026-10-21 22:05 to 2026-10-22 00:30 UTC)
1. **B1 went public.** Carson chose "merge B1 and turn the hail history on for the public site". PR 13 was merged
   into `main` (f96f5c7) after a go-live change (413fd56, c3caf9e) that four review rounds shaped: `main` builds with
   `--hail-history` (never `--require-live`); the daily store job publishes a release asset named after the branch
   (`hail-store-main.tar.gz` for `main`; slashes as dashes), one run per branch, the new file uploaded as `.new`, the
   old asset moved aside and removed last; each build reads its own branch's asset (`HAIL_STORE_ASSET`) and falls back
   to `main`'s only on a 404; a branch preview waits up to 60 minutes for the branch's latest store run (the build job
   has `actions: read`); a real store older than three days is a failed source; the public pages say the site is
   rebuilt "on a schedule set to every 10 minutes" (GitHub ran it 6 times in 24 hours; D33 records it) and no longer
   promise the newest day within the hour; a failed download reads "the history store could not be downloaded in this
   update". The old shared asset `hail-store.tar.gz` (which held the B3 address data) was removed by the branch job.
   Records: `records/b1-go-live/` (the four review journals, the commit messages, the PR addendum).
2. **B4 merged into B5** (cbf5a12, after B3 at ad4962b): reviewed, no losses; the storm wording ruled "code -999
   means outside radar coverage" (D45); the swath step runs after the store copy; the sheet order is the B3 address
   block, then the B4 live line, then the history. Journal: `records/b5/journals/wf_c52db39b-d90.jsonl`.
3. **Part B2 started.** The products owner ran in a second worktree from ad4962b and finished its build (D55 count
   differences, D56 station reader and snowgrid tests, D53 word swap, D36 candidate list); its review and fix rounds
   were stopped at the pause. Its WIP is `origin/session/hail-b5p-wip` (719e7c6); the diff against ad4962b is
   `records/b5/products-wip-719e7c6.patch`; its journal `records/b5/journals/wf_44a6add9-a8e.jsonl` holds the builder's
   report, the reviewer's findings, the skeptics' verdicts and what the fixer had done. The browser, site and smoke
   owners were stopped before they edited anything (journals `wf_52097ea0-29e`, `wf_aca43642-f97`).

## Where everything is
| Thing | Where | State at the pause |
|---|---|---|
| main | `origin/main` = f96f5c7 | B1 public. Main's push build (run 96) succeeded; its first store job was running at the pause and publishes `hail-store-main.tar.gz`; the pages show the hail history after the next main build (the schedule, every few hours, or a dispatch of `website.yml` on `main`) |
| B5 | `origin/session/hail-b5-wip` = cbf5a12 (local `claude/hail-b5`, base db84d76) | B3 and B4 merged in, clean tree; part B2 not yet applied |
| products WIP | `origin/session/hail-b5p-wip` = 719e7c6 (local `claude/hail-b5p`, from ad4962b) | apply onto B5 with `git apply --3way records/b5/products-wip-719e7c6.patch` (or cherry-pick 719e7c6; sources.py has B4's rows and the storm wording in B5, expect a small conflict) |
| B2, B3, B4, research | PRs 14 (base `claude/hail-b1`, now merged), 16, 15 (base `claude/hail-b2`), 12 | open, green as recorded; their previews read the old shared asset, which is gone: do not re-run them. The B5 pull request on `main` supersedes 14, 15 and 16 |
| this state | `origin/session/hail-2026-10-20` (orphan; delete when the programme ends) | briefs, logs, records, scripts, small caches, this guide |
| the published store | release `hail-store`: `hail-store-claude-hail-b1.tar.gz` (the B1 branch job's) and, once main's job finishes, `hail-store-main.tar.gz` | B1 format only (`t/`, index, manifest; 8.4 MB) |

## Restore (if the container is gone; otherwise everything is in place under /home/user)
```bash
cd /home/user/RoofingApp && git fetch origin
mkdir -p /home/user/wt
for b in hail-b2 hail-b3 hail-b4; do git worktree add /home/user/wt/wt-${b#hail-} -b claude/$b origin/claude/$b; done
git fetch origin session/hail-b5-wip && git worktree add -b claude/hail-b5 /home/user/wt/wt-b5 FETCH_HEAD
git fetch origin session/hail-b5p-wip && git worktree add -b claude/hail-b5p /home/user/wt/wt-b5p FETCH_HEAD
git worktree add /home/user/hail-b1/wt -b claude/hail-b1 origin/claude/hail-b1
git fetch origin session/hail-2026-10-20 && git worktree add --detach /home/user/wt/wt-session FETCH_HEAD
bash /home/user/wt/wt-session/restore.sh "/root/.claude/projects/-home-user-RoofingApp/<this session's id>/workflows/scripts"
python3 -m venv /home/user/hail-b1/venv && /home/user/hail-b1/venv/bin/pip install -r /home/user/wt/venv-freeze.txt
pip install requests jinja2 pillow numpy pygrib h5py tzdata pyarrow "pyproj~=3.8" "pyogrio~=0.13" playwright
```
The stores: the first pause's guide (records of 2026-10-20 in `supervisor-log.md`) says how to rebuild the combined
store (`records/b5/combined/assemble.sh`, D50) from the published B1 asset (now `hail-store-main.tar.gz`) plus the B3
job's `a/`, `r/`, `b/` (the B3 job tarball is gone from the release; rebuild them with `website.streets`,
`website.addresses` and `website.buildings build` from the cached zips, about 25 minutes, or take them from the
local `/home/user/hail-b5/out/combined/store` if the container survived).

## Next steps, in order
1. **B1's public pages: done at 00:39 UTC on 2026-10-22.** `hail-store-main.tar.gz` was published at 00:36 UTC, `website.yml`
   was dispatched on `main`, and `tools/live_check.py` in Chromium found map.json's hail block loaded, the Billings
   town page's table and the Benchland sheet (10 days) at 390 and 1280 px with no off-site request. Nothing is left
   on B1; the daily job runs at 12:43 UTC from `main`.
2. **Part B2 on B5** (`briefs/hail-b5-brief.md`, "Part B2 build list" and D59, D60): apply the products WIP onto
   `claude/hail-b5` first (it is the finished builder state; let a fixer answer the reviewer's findings from the
   journal), then run `scripts/hail-b5b2-build.js` with `{"owners": ["browser", "site"], "worker": "<alias>"}` and
   `{"owners": ["smoke"], "worker": "<alias>"}` (the script takes `args.wt` and `args.out`; the smoke owner must not
   add a wait step, D60). The combined store is `/home/user/hail-b5/out/combined/store` (D50).
3. **Merge `main` into B5** (D59): `git merge --no-commit --no-ff origin/main` in wt-b5, then `scripts/hail-b5-merge.js`
   with `{"branch": "origin/main", "label": "main"}`; expect conflicts in `website.yml`, `hail-store.yml`,
   `website/hail.py`, `website/build.py`, `tests/test_site.py`, `tests/test_hail.py`, the docs; B5 adopts the
   branch-named asset, the wait step, the stale rule and the plain download words.
4. Completion re-check against the gates in the build list; the docs' numbers; squash onto db84d76... no: onto `main`
   (B5 now includes B1's go-live through the merge; the squash target is the merge base with `main`); push
   `claude/hail-b5`; the branch's store job publishes `hail-store-claude-hail-b5.tar.gz` and the preview waits for it;
   check the preview in a browser; open the pull request on `main` with the repo's template; subscribe; say in it that
   PRs 14, 15 and 16 are superseded and close them when it merges.
5. Report to Carson the open decisions: the 10-minute timer (GitHub's schedule ran 6 times a day); the data repository
   for the bulk files (the combined store is 496 MB raw); the gauge distance 10 or 25 miles; whether the swath picture
   stops at the state line; the NOHRSC snow analysis held; the counsel list of 18 items (MSL "for no other purpose",
   MCA 2-6-1017, the FEMA licence, the GitHub terms).

## Harness facts (so Friday does not relearn them)
- 4 CPUs: 2 agents per workflow; several workflows side by side; the worker model does the work, the supervisor rules.
- Scripts are plain JS; a backtick inside a template literal breaks parsing (use quotes); check with `node --check`
  after wrapping the body in `async function __w(){...}`; the worker alias comes from `args.worker`.
- The writable disk allowance is about 40 GB and fills fast: archive small evidence before deleting bulk scratch;
  never delete under a running stage's output root; `pkill -f` only with an anchored pattern.
- Agents never run git write commands (the supervisor commits); WIP safety commits use `-c commit.gpgsign=false`;
  real commits are signed; push with retries; `gh` has no valid token (use the GitHub MCP tools and the public REST
  API for run status); workflow_dispatch works on any branch that has the workflow file.
- A step with no `shell:` runs as `bash -e {0}` (no pipefail); GitHub's schedule is loose (hours between runs).
