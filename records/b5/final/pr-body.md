## What changed
Five years of weather at every Montana address: a tap anywhere in Montana (and each town page) opens a plain summary table of the last five seasons, then eleven sections in a fixed order (hail, wind, storms, temperature, rain, snow, flooding, ice, heat, what matters for a roof, how this was made). Every number carries its unit and its kind word (radar estimate, station reading, grid estimate, analysis, river gauge, report, record, warning, zone product, reference, data unavailable); every unavailable, partial or held line ends "This is not an all-clear." This branch carries B2 (reports, records, radar detections, warnings and zone products joined per tile), B3 (every street, one dot per building outline with its addresses, the typed-address search, behind `--hail-addresses`, off on main), B4 (the live hail swath layers behind `--storm-layers`) and B5 (the climate grid, the station part with one pick rule, the river gauges, the held snow analysis, the roof indicators, the per-tile station lists), with main's B1 go-live scheme (the branch-named store asset, the wait step, the three-day stale rule) merged in. It supersedes pull requests 14 (B2), 15 (B4) and 16 (B3); they close when this merges.

## How it was verified
- [x] `python -m unittest discover -s tests` passes (SUITE_LINE)
- [x] `python desktop/launcher.py --selftest payload` passes
- [x] Checked in a real browser or the app window (for screen changes): Chromium at 390 and 1280 px on a build from the adopted combined store, the three reference cells compared word for word with the Python source, zero off-site requests; the branch's Website run (link below) runs the same smoke, the real-store parity step and the sample-flag identity check
- [x] Live feed content checked, not just HTTP 200 (for feed changes): every B5 source was read live and its content checked before it was built on (docs/DECISIONS.md D38 and later; the contract rows in `website/sources.py`)

## Ships to users?
- [x] No — `payload/manifest.json` version unchanged
- [ ] Yes — version raised (owner asked to ship)
- [ ] Needs a new installer (`desktop/` changed or a new package)

## Docs
- [x] `docs/DECISIONS.md` / `docs/ROADMAP.md` updated if a decision or status changed (D38 with the round rulings D44 to D102; the open items for the owner are in ROADMAP in one place)

Branch Website run: RUN_URL
Store job run: STORE_RUN_URL

Open decisions for the owner (also listed in docs/ROADMAP.md): the rebuild timer (GitHub's schedule ran six times a day); the data repository for the bulk files (the combined store is about 552 MB); the gauge distance (10 or 25 miles); whether the swath picture stops at the state line; the NOHRSC snow analysis held (regression slope 0.664); the counsel list (20 items; item 20 is the GHCN non-US note and the Environment and Climate Change Canada licence); the banned-name list to confirm; `ADDRESS_FRAMEWORK_ZIP` for the metadata test; the Placement class reading under decision 6.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01D7npHSU4NQFAmdz8Ep5sV7
