# Task list as of 2026-10-24 02:05 UTC (resumed; part B2 running)
Completed: 1 to 20, 22 to 25, 27, 29 (the globe plan and research, P0 to P2, towns, imagery, schedule offset, the hail research scaffold, B1, B2 (PR 14), B3 (PR 16), B4 (PR 15), the research wave, B5 part A, the B1 go-live: PR 13 merged into main at the owner's decision and the public pages verified in Chromium at 00:40 UTC on 2026-10-22).
Open:
- 21 (pending) Docs follow-ups: P1 "-99/-999 not verified" wording; globe README proposal labels D33..D40.
- 26 (in progress) B5: the past-weather history per location. Part A done; part B1 done and twice re-checked; part B2 running (30 to 32).
- 28 (in progress) Integrate B3 and B4 into B5 and run part B2: B3 (ad4962b) and B4 (cbf5a12) merged and reviewed; the products owner's part B2 work applied as bd3ae20; the review's rulings D61 to D65 recorded.
- 30 (in progress) Part B2 products fix round (D61 to D65): workflow hail-b5b2-products-fix.js (fixer A stations, fixer B fixture and store candidate, reviewer, skeptics, fixer C, check); run wf_2e5d7061-a55.
- 31 (in progress) Part B2 browser and site owners: hail-b5b2-build.js {"owners": ["browser", "site"]}; run wf_48b63724-db5.
- 32 (in progress) Part B2 smoke and CI owner: hail-b5b2-build.js {"owners": ["smoke"]}; run wf_3aa401ed-8c2.
- 33 (pending, after 30 to 32) Adopt fixer B's candidate store as the combined store (D50, D64; the combined store's files are immutable: chattr -R -i before replacing), the part B2 completion re-check against the build list's gates, the docs and record pass (owner 5), a WIP commit.
- 34 (pending, after 33) Merge main (f96f5c7) into claude/hail-b5 under D59: git merge --no-commit --no-ff origin/main in wt-b5, then scripts/hail-b5-merge-main.js (base 7aec754; nine conflicts measured in a dry run).
- 35 (pending, after 34) Completion: full suite and self-test, squash onto the merge base with main, push claude/hail-b5 (its store job publishes hail-store-claude-hail-b5.tar.gz; the preview waits), the preview in Chromium, the pull request on main superseding PRs 14, 15 and 16 (close them when it merges), subscribe; report the open decisions to Carson (the timer, the data repository, the gauge distance, the swath extent, the snow analysis, the counsel list with item 19).
Open pull requests, waiting on Carson: 12 (research), 14 (B2), 15 (B4), 16 (B3); PR 2 (codex/montana-weather-pilot) is the other agent's. main is green: the Website schedule ran 6 times on 2026-10-23 and the store job ran on 2026-10-22 and 2026-10-23 (success).
