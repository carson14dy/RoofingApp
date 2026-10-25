Docs: the branch run's measured figures (D104, D105): the store job's 39.1 minutes, the asset size and the preview's results

docs/DECISIONS.md records D104 (the real-store parity failure the first preview found: the gust rows' partial
stations note the browser lacked, the names test that pinned one store's stations, the fixture test and the
two-store rule before a push) and D105 (the daily budget: the branch's store job ran 39.1 minutes end to end
on the runner and published an asset of 88,647,098 bytes; the first-round 25-minute figure is restated to 60
minutes, the preview's wait bound, with the 150-minute job timeout as the backstop), and the job bullet's
clause (d) carries the measurement.

docs/ROADMAP.md: the B5 row says the reviewer's reading (B5-11) and the run time (B5-12) are done and names
the live preview (Website run 121 of 2026-10-25: the parity step, the smoke and the width check passed; the
phone view at zoom 15 over Billings measured 681,988 bytes gzip against the 700,000-byte budget); the
schedule bullet carries the measured run time and D105.

The verification record: gate B5-12 reads pass against the restated budget with the run time and the asset
size; gate B5-18 reads pass with the live preview; the completion block gains daily_job_run_11 and
live_preview, and its not_done and parity entries state what the branch run measured. The one-hour swath
pixel gate was not exercised (no hail values in the box during the preview's smoke) and the record says so.

No site file changes, so this commit starts no Website run; the modules that read the record and the words
rules pass (575 tests, 1 skipped).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01D7npHSU4NQFAmdz8Ep5sV7
