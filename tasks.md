# Task list as of the pause (2026-10-22 00:30 UTC)
Completed: 1 to 20, 22 to 25, 27 (the globe plan and research, P0 to P2, towns, imagery, schedule offset, the hail research scaffold, B1, B2 (PR 14), B3 (PR 16), B4 (PR 15), the research wave, B5 part A), and the B1 go-live merge (task 29: PR 13 merged into main at the owner's decision; the live check of the public pages is the one piece left, see RESUME.md).
Open:
- 21 (pending) Docs follow-ups: P1 "-99/-999 not verified" wording; globe README proposal labels D33..D40.
- 26 (in progress) B5: the past-weather history per location. Part A done; part B1 (Python side) done and twice re-checked; part B2 started and paused (see 28).
- 28 (in progress) Integrate B3 and B4 into B5 and run part B2: B3 merged (ad4962b) and B4 merged (cbf5a12) into claude/hail-b5, both reviewed, no losses; the products owner's part B2 work is a WIP commit on claude/hail-b5p (719e7c6; builder done, review and fix rounds stopped); the browser, site and smoke owners stopped before any edit. Then: main (the B1 go-live) merged into B5 under D59, the completion re-check, squash, push claude/hail-b5, the preview, the pull request on main (superseding PRs 14, 15 and 16, which are closed when it merges).
Open pull requests, waiting on Carson: 12 (research), 14 (B2, base claude/hail-b1 which is now merged; leave its base until B5 supersedes it), 15 (B4), 16 (B3).
