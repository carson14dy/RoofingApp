# Roadmap

Status on 2026-10-16: the product is the **Montana Hail Watch website** (D27) with an interactive
radar, forecast and warning map in the style of Apple Weather (D28) and live station readings
(D29). The website was merged to `main` on 2026-10-16 (pull request #3) and Carson turned on GitHub
Pages the same day, so `main` publishes to https://carson14dy.github.io/RoofingApp/ every 10
minutes. The desktop app (payload 1.0.0, shell 1.1.0) is **parked**: unchanged, still tested, not
shipped. Branches: `claude/desktop-app` (the app, then the website); `codex/kansas-city-weather-pilot`
and `codex/montana-weather-pilot` (ChatGPT's pilots, reviewed in D23 and D25, not merged). It also
carries the 3D storm view research in `research/globe/`, with `main` merged in; pull request #2 is open.
Agents: check this file before starting, move items to Done when merged, keep "Next" in priority
order.

## Bottom line
1. Live since 2026-10-16: check that the scheduled runs keep publishing (Actions → Website).
2. Carson and a crew lead use it for a week on phones and desktops; fix what they trip on.
3. Replace the placeholder flag limits with the company's own.
4. Then: decision-time records for an evaluation, nearby station readings, a hail-size map, alerts
   to phones.
5. Decide whether to delete the parked desktop app.

## Done: the website (D27)
| Area | What works | Limits |
|---|---|---|
| Now | Montana's active NWS alerts, most urgent first (alerts without an outline listed with a note); a map card with the latest radar and warning outlines; a card per town for the next 12 hours with flags in words | Montana only |
| Map (D28) | Full screen, Apple-Weather style: the past hour of NOAA MRMS radar into the HRRR model forecast (15-minute steps for an hour, hourly to 12 hours) with play, scrub and 1h/12h; temperature and wind-gust layers; warning outlines and storm reports; town bubbles with the NWS forecast for the hour; town sheets; my location; a list of every alert and town | HRRR is a model, not the NWS forecast; frames are pictures made each build; no lightning or air quality; rain and snow share one palette; checked in Chromium only, not yet on a real iPhone or Android phone; `map.js` is about 2,100 lines |
| Town pages (17) | Alerts at that point, 24-hour table (gusts first), 7-day with high and low per day | Grid forecasts for a 2.5 km square, not a roof; placeholder limits |
| Observed now (D29) | The latest reading at each town's three nearest NWS stations (any state): temperature, wind, gusts, time and age, quality flags in words, station and grid elevation; one line per town card on the Now page | Stations report hourly or less, so readings run up to 75 minutes old before they show as stale; a station is not a roof; not on the map |
| Storm reports | Three SPC reporting days on the map card and in tables; hail in inches, unknown wind kept unknown | Preliminary reports only |
| Honesty | Per-source status line, last verified alerts kept after a failed refresh, "Alerts not checked" per town, page-age warning, sample data labelled on every page | None |
| Publishing | GitHub Actions every 10 minutes from `main`; branch builds check live data (`--require-live`) and keep a preview artifact; feed contracts on the About page | GitHub may delay schedules and pauses them after 60 days without activity. Measured 2026-10-17 from the Actions API: the four scheduled runs on `main` started 2026-10-16 at 19:42 and 22:14 UTC and 2026-10-17 at 00:35 and 05:00 UTC, with gaps of 151.5, 141.6 and 264.5 minutes, not every 10, so the live site updated hours apart while the page-age banner carried the real age. GitHub's docs say scheduled runs can be delayed at high load and queued jobs may be dropped (`research/globe/validation-evidence/hosting-options.json`). The offset cron (`7,17,27,37,47,57 * * * *`) was adopted on 2026-10-18 as an experiment; the count of scheduled starts on `main` in the 24 hours after merging is the measurement, to compare with the four runs in about 13 hours before. |
| Design | Light "field sheet" look with dark mode, self-hosted fonts and Leaflet, contrast ≥ 5.86:1, collision-free map labels, 288–1440 px without sideways scroll, checked on every branch push (`docs/DESIGN.md`) | Phone Now page is long (P2) |
| Tests | 179 website tests (64 pages, map data and station readings, 69 radar and model frames, 41 base map and label layout, 5 Pages publication planning); a Chromium page-width check of every page at 288–1440 px on every branch push alongside the app's tests; a Chromium smoke test of the built map on every branch push (frames, base map, bubbles, play, layers, menu taps, legend, card and its caption) | None |

## Built, not merged: hail history behind `--hail-history` (D34, D35, D38)
| Area | What works | Limits |
|---|---|---|
| B1 store and click-anywhere history (branch `claude/hail-b1`, not merged) | The trailing 1,826 SPC days of NOAA's MRMS MESH radar estimate as site files (`hail/`), rebuilt in full each day by `hail-store.yml` and read by the 10-minute build; a click or tap on the Map page opens a spot's day list (sizes to the hundredth of an inch, rounded down, with mm exact; the NWS size words; the SPC day); the outside rule is the store's own tile and state lists; town pages carry the same table; About explains it | Radar estimates, not measurements or inspections; off on `main` until the owner approves the About text and counsel confirms the D34 items; a late 12:00 UTC file makes that run's window end one day earlier; the Benchland 1.75 in report is in B2 (gate B2-1, pending the re-check); the B1 gates are pending the re-check (`research/hail-history/validation-evidence/b1-verification.json`), and B1-4 closes when B2-1 passes |
| B2 joins (branch `claude/hail-b2`, from `claude/hail-b1`, not merged) | In the sheet and each town table, six sections after the radar days, each row with its kind label: reports within 5 miles, official records within 5 miles (NCEI), radar hail detections within 2 miles, warnings whose issuance polygon covered the spot, zone products for the spot's public forecast zone (nine kinds, flood watch among them, named in D35) and the red flag warning for its fire weather zone (ten products in all), and peak gusts at the two nearest stations within 40 miles. A part that fails says so, in the words D20 sets. The daily job joins them after the store and publishes both | Kinds stay apart, and none is a damage finding, an inspection or an all-clear. Round 4 failed gate B2-7 on the page width at 288 and 320 px. Round 5 filled the placeholders, corrected open item 11 and the joins docstring, and fixed the width with an overflow-wrap rule on the joined sections. Round 6 records gate B2-7 as passing on the round-5 build, so every gate but the deferred B2-4 passes there (status pass). D34 (round 6) removed FL.W and FA.A from the zone products; D35 (round 7) restores FA.A as flood watch and keeps FL.W out, so FL.W and the 18 county-only flood watches are in the B5 hand-off (item 20). The round-7 rebuild's figures are in DECISIONS D35 and DESIGN section 9. Gate B2-4 (units) stays deferred as agreed. The byte budgets are measured on the round-7 store (`j/` 19,912,416 bytes of 40 MB; `z/` 919,402 and `s/` 22,478 bytes of 2 MB each; `hail/` 54,227,125 bytes of 60 MB); B3's budget is the open question (D35). A page's first click makes up to seven requests. The counts, the warm run time (96 s and 100 s), the Benchland rows and the Chromium checks are in the record (`research/hail-history/validation-evidence/b2-verification.json`); the cold run is not measured. Open decisions: D35 items 11 to 19 |
| Done on the branch: the past weather of every location (B5, D38; branch `claude/hail-b5` from B2 at `db84d76`, not merged) | The Python side is built. A five-season table leads the sheet (2021-22 to 2025-26, July to June, plus the partial 2026-27 line), with every row's kind word and unit: radar hail (B1), reports, warnings, county and zone products and station gusts (B2 and B5), grid temperature and rain (nClimGrid, 4,569 tile files), station snowfall and deepest snow at the two nearest stations that pass the coverage rule (GHCN, 571 station files), and on town pages the river flood record for the nearest gauge within 10 miles (104 gauge files). A roof section of reference lines and held lines, and a hit-and-miss record of hail reports (737 rows, 464 hits, 273 misses). The store adds `c/`, `sd/`, `tl/` (the station tile lists), `g/`, `k/`, `j/e/` (the per-tile events) and `j/towns.json` (the town polygons). The daily job runs the B5 steps non-fatally, with a monthly path and a once-only backfill whose archive is the `hail-climate` release | The browser is part B2, not built (item 20). The town pages and the About page are part B1 in the site build. The snow analysis is held: its regression slope is 0.664 over 682 station-seasons, outside 0.85 to 1.15 (D7, D23), and `n/` is absent. FEMA flood zones, lightning, PRISM, Daymet, SNODAS and SNOTEL are left out with reasons (D38). 1,230 zone products cannot be placed, because the six older zone editions return 404 (D27). Counsel items and the owner's O4 to O11 are open (D38). The gates are in `research/hail-history/validation-evidence/b5-verification.json`, as of the B1 completion (2026-10-20): B5-1 to B5-9 and B5-15 pass; B5-14 and B5-17 pass in Python (the browser halves are part B2); B5-10 and B5-11 are fixed pending re-check for this part's files; B5-18's flag-off clause is fixed pending re-check; B5-16 is open with its owner; B5-12 and B5-13 are partial. The daily job's run time with its downloads, and the phone view's gzip size, are pending |

Measured for the daily job (`hail-store.yml`), in the re-check: run time, bytes of `hail/` and of the `tiles` list, the largest shard, the copy-check results (rederived, partial, skipped), the days missing, and the cold-cache and warm-cache shard hashes (B1-6); pending.

Measured for the joins (`website/joins.py`) in the re-check: the Benchland rows (B2-1), the counts against the research (B2-2), the bytes of `j/`, `z/` and `s/` against their budgets, the job's run time, the requests and failures per source, the two-run hashes (B2-8), and the Chromium widths and off-site requests (B2-7); round 4 measured them, and the record holds the results (the cold-cache run is not measured). The record is `research/hail-history/validation-evidence/b2-verification.json`.

Measured for the B5 job (`hail-store.yml`, D26, D38), in the re-check: the run time of the daily job with its downloads, the bytes of the climate archive and of `c/`, `sd/`, `g/`, `k/` and `j/e/` (the offline sizes are in the record), the cold-cache run, and the two-run hashes of `j/e/` and `n/`; pending, except the offline figures the record holds (on 2026-10-20: joins build 277 s, stations 29.5 s, gauges 1.5 s, joins verify 13.9 s; the re-check: climate build 11 s, NOHRSC build 1 s).

## Open items for B5 (D38)
- **The gauge cut-off.** 10 miles (O4, provisional). The brief's figures: 10 miles covers 17.3 percent of Montana and 12 of 14 towns; 25 miles covers 69.6 percent; 5 miles covers 4.8 percent. The owner confirms.
- **The NOHRSC method.** The regression slope is 0.664 over 682 station-seasons, outside 0.85 to 1.15, so the analysis stays out and the snow rows are station readings. Whether another method may be shown is the owner's decision (O10).
- **The LSR unit codes.** Magnitudes for codes 5, 6, 7, I and J stay unshown until the IEM documentation confirms their units (D15). The documentation was not read in the research.
- **The zone editions.** 1,230 zone groups are unplaced (`edition_unpublished`). The six older editions return HTTP 404 at the NWS address the build uses (checked 2026-10-19). The research (`zone-editions.json`, 2026-10-19) found IEM's Montana zone sets for every date tested, simplified: 103 zones through 2022-09-13 12:00 UTC and 83 from 18:00 UTC. They serve code identity and coarse placement only, and IEM does not show the change log's 2022-09-07 date for the Montana switch. The owner or the supervisor decides between placing by the IEM sets and finding the full-resolution older files (D27, D31).
- **The data-site split.** The browser fetches the per-tile files on a tap: `hail/j/e/<tile>.json` (4,597 files; the largest 22,933 bytes gzip against a 100,000-byte budget) and `hail/tl/<tile>.json` (the largest 856 bytes gzip). The events table `hail/j/events.json` (6,083,996 bytes) stays for Python. The browser change is part B2 and not built; the determinism check of `j/e/` and `tl/` (B5-13) is pending.
- **The caps (O12).** `j/` is 86,276,949 bytes raw in 9,196 files, `j/e/` included, against 40 MB; `hail/` is 176,293,267 bytes in 23,866 files against 60 MB. The owner or the supervisor rules on both (D38, D42).
- **The schedule and the monthly job.** The daily job runs at 12:43 UTC. The monthly job (D42) runs on the first day of each month or by the monthly input; the climate backfill runs once, by hand. The daily station refresh needs the station list carried from the last published store. The daily total with downloads is not measured against the 25-minute budget (B5-12).
- **The job clock and the joins.** The B5 steps share a 40-minute clock in `hail-store.yml`, but the joins do not: `joins.py` counts its 35 minutes from its own start, so a late join can leave no time before the pack. The choice is a job-clock deadline in `joins.py`, a separate products step with its own deadline, or a different cap (the brief fixes 60 minutes). The supervisor also rules on whether the join stays fatal (it does now, by the B2 rule).
- **The station carry, drop and containment.** The carry and drop edit `index.json` without refreshing `manifest.json`. The tested stations command, the containment step and the fatal store gates before the pack are still to be built (DECISIONS D38).
- **The daily NWPS read and the gauge dates.** D26 asks for the NWPS list and the pool details on every daily run; the daily gauges step does not read them yet. The gauges block's read dates come with that change.
- **The NOHRSC revision check.** A daily rebuild replaces the snow block, so the monthly check's record is erased until the snow module keeps it through the rebuild.
- **The summary and the section router.** Open in other owners' files, as DECISIONS D38 and D41 name them: `website/summary.py` (the partial-season line's all-clear sentence; the five-season snowfall cell, which still sums stations, B5-16; the F7 and F9 re-checks); `website/snowgrid.py` (the unavailable and unit lines have no all-clear sentence); `website/build.py` (the section router needs the labels "Watch" and "Advisory" and the product after the span's colon).
- **The flag-off and browser checks.** The flag-off build matches db84d76 (94 files, zero differences, 2026-10-20). The live preview build, the zero off-site request count, the 390 and 1280 px smoke, and the 390 px first-screen check are part B2.
- **Counsel.** Items 11 to 19 of the legal terms review, and the NCEI Storm Events licence text, which was not read (D38).
- **Smaller items.** A cache with no climate ledger makes `climate build` raise and write no climate block, so the sheet would not carry the D16 sentence for climate; the climate owner decides the fix. The owner confirms the list of banned names behind the "no model or vendor names" rule, which is not in the repository. The branch carries the WIP commits `fa33c8d`, `de0793c` and HEAD `dcb7e93`, and the uncommitted part B1 edits; the supervisor decides the clean-up.

## Next, in priority order
1. **Go live.** Done in part, 2026-10-16: PR #3 merged; its first deployment (run 38933159167)
   failed with Pages disabled; the publication repair (PR #4) now rejects failed or invalid Pages
   lookups; Carson turned on Pages (Source: GitHub Actions) and run 38934427870 published the
   site. Left: open the runs' summaries in Actions → **Website** (every source loaded, counts
   plausible); open the site on a phone. Done when two scheduled runs in a row publish.
2. **Feedback week.** Carson and a crew lead use it daily. Record what they look for and can't
   find; run the first-click and timing checks in `docs/DESIGN.md` section 1. Open the map on an
   iPhone (Safari) and an Android phone: glass blur, notch and home-bar insets, the location prompt,
   playback on mobile data. All map checks so far ran in headless Chromium.
3. **Company limits.** Replace the placeholder flags (D16: gusts 25 mph, wind 20 mph, rain or snow
   30%, under 40 °F, over 95 °F) with the company's limits, per roof system if they differ.
4. **Decision-time records (review P0 baseline).** Keep each build's `data/state.json` (alerts,
   what each town card said) somewhere durable, for example an hourly commit to a `data` branch, and
   predeclare the metrics (misses, false alarms, lead time) before any new feed is added.
5. **Phone density (design P2).** A compact one-line-per-town list on phones with the same flags.
6. **Cache map frames between builds.** Each build downloads about 40 MB (mostly HRRR temperature and
   gusts, which change only hourly) and redraws frames it drew 10 minutes earlier. Reuse frames by
   HRRR run and radar time (an Actions cache or the live site's previous frames).
7. **Rain and snow on the map.** Colour snow apart from rain (MRMS PrecipFlag, HRRR CSNOW), with the
   legend saying which.
8. **Text version of the map pictures (accessibility).** The List gives every NWS alert and each
   town's NWS forecast as text, but nothing says what the radar and model pictures show at a town.
   Sample the radar estimate and the HRRR values at each town in `website/gridded.py`, add them to
   `data/map.json` (a D28 contract change) and list them, worded as a "radar estimate" or "model",
   never "dry" or "no hail". Until then the map's description says the pictures have no text version.
9. **Less JavaScript in the map (Carson's call).** `map.js` is about 2,100 lines. The verification's
   JavaScript review found about 330 that could move to the build: Montana-time labels written into
   `data/map.json` (removes the Intl code), the legend rendered by Jinja, the note's room reserved in
   CSS. Its skeptic rejected them as defects: AGENTS.md rule 4 gives sheets and layout to `map.js`,
   and each move adds map.json keys that tie the build to the page's wording. Worth doing only
   together, with the Playwright suites as the guard.
10. **Nearby station observations: done (D29, 2026-10-16).** Next for them: the readings on the map's
   town sheets (a D28 contract change), and a check on real phones that the card line stays one
   line.
11. **Real hail footprint.** MRMS MESH (same bucket and decoder as the map's radar, D28) drawn as a
   map layer and as outlines per swath (nodata handled, 1 km resolution recorded), labelled as a
   radar estimate, apart from reports. Check against SPC 2025-06-15 (Benchland, 1.75″).
   Or a commercial trial in shadow mode (Xweather, The Weather Company HailZone, Verisk, Cotality;
   use the review's procurement questions). No "best" claims (D21).
12. **Alerts to phones.** A static site can't push. Needs a small service (push, SMS or email) and the
   p95 delivery gate below.
13. **History.** Date ranges and multi-day events; NCEI Storm Events for older context.
14. **More towns, then the contiguous US (D24).** Towns are one line each in `website/towns.json`
    (each needs a label side checked by the label test). Contiguous US: a state list for alerts,
    the SPC filter box and map extent per region.
15. **The parked app.** Keep or delete `payload/` and `desktop/` (Carson's call). If it comes back,
    its plan (installers on real machines, pilot, evaluation, guidance trials, vendor comparison)
    is in this file's history at commit 33cda31.
16. **3D storm view (globe).** Research done 2026-10-17 in `research/globe/` (read sections 1, 2 and 6).
    It waits on the owner decisions in README section 2 (D-G1 to D-G26). Chosen 2026-10-17: route (a),
    storm layers on the Map page behind a default-off flag, P1 (text values) first. P0 gates before it:
    schedule cadence, counsel on publishing terms before P2, the -99/-999 check, the below-ground share.
    Nothing reaches `main` until they pass. A link-only globe only after P1 to P4 and a library approval.
    P1 merged in pull request #7 behind the flag (on `main`, off by default: website/storm.py,
    tests/test_storm.py). P2 is built on branch `claude/storm-layers-p2` behind the same flag (the GOES
    band 13 picture as a Map layer: website/satellite.py, tests/test_satellite.py) and waits for review
    and a small pull request. The clear-night reading of -99/-999 needs Carson's ruling first, and no
    GOES layer reaches users until counsel has read D-G10 and D-G11.
17. **Imagery base map (D32, opt-in).** Built on its own branch, not merged: a Base map switch in the Layers
   menu, from white (the default) to USGS ImageryTopo aerial imagery with roads and names. Its tiles are requested
   only while Imagery is on (after the switch, or on a link that starts on it); the one exception to the site-files
   rule. Checked on 2026-10-18: the unit tests, the sample builds, the browser check (`tools/smoke_map.py`, real
   tiles, with checks for a leftover tile layer, the failure words and the return to the credit) and the evidence
   records (`research/globe/validation-evidence/imagery-switch-verification.json` and `imagery-switch-review.json`).
   Left for Carson: the licence for the road and name data (USGS states none; `rights-matrix.json`); whether the
   privacy line should also name the request headers; whether a town bubble's name may sit beside USGS's own name;
   the phone legend's height with imagery; and a small pull request. Decided 2026-10-18 (owner-delegated): the credit
   row carries the privacy words; a failed tile says so in the credit row; a link that opens on Imagery loads the
   tiles as the page opens; the About page quotes USGS's requested acknowledgment; the landscape menu scroll is
   accepted.
18. **Hail B3, addresses and search (D34): the legal go-live gate.** Starts after B2 passes its re-check and the byte budget question in D35 is decided. Dots from zoom 13 for the 674,715 MSL points, search and About terms; the flag waits for counsel on D34's items.
19. **Hail B4, live swaths (D34).** MESH 30 to 1440 minute swath layers on the Map behind `--storm-layers`, after B1 to B3 (the globe plan's P3).
20. **Hail B5, the past weather of every location (D38; the B5 brief).** Built on `claude/hail-b5` (the table above, "Done on the branch"); its browser is item 21. Joins the kinds B2 did not read, with the research's counts for 2021-10-19 to 2026-10-19: NCEI county-coded records (points) within 5 miles, tornado (13 rows), flood (60), flash flood (52), heavy rain (85), funnel cloud (30), lightning (6) and debris flow (10), 256 rows in all; the flood products FL.W (43 events), FA.W (37), FA.Y (548), FL.A (35) and FL.Y (10), and the county-only FA.A (18) and FF.A (2); the snow squall warning SQ.W (78); and the winter, heat, frost and freeze zone products WW.Y (865), WS.A (226), HT.Y (58), EH.W (4), EH.A (3), FR.Y (14) and FZ.W (4). Under D35, B2 joins FA.A (flood watch) as a zone product; FL.W and the other flood products move to B5's polygon path and county path. Settle these first (`DECISIONS.md` D35 open items 17 and 18): whether the zone-coded FF.A (18) events join, and whether the high wind watch HW.A (277) and the blowing dust advisory DU.Y (3) join, which the B5 brief lists and D35 does not. The B5 brief's NCEI counts are 2020 to 2026 totals (open item 19). Zone products that B5 adds follow the period rule (D33).
21. **Hail B5, part B2 (the browser; after B3 lands and is merged in).** The sheet's summary table and its sections in `website/static/map/map.js` and `map.css`, with every word read from Python (`map_data_summary`; no literal words in the browser); the per-tile event fetch from `hail/j/e/` on a tap; the browser's halves of the failure rule (D16); the phone view at zoom 15 against the 650 KB gzip gate; the Chromium smoke at 390 and 1280 px, `smoke_pages`, the live preview build and the zero off-site request count. Gates B5-10, B5-11, B5-14 (browser half), B5-16 (town pages), B5-17 (the About page) and B5-18 are recorded in `research/hail-history/validation-evidence/b5-verification.json`. B3's changes to `map.js` and the sheet markup come first, so this part builds on the merged page.

## Independent review priorities, for the website
| Priority | Item | Status |
|---|---|---|
| P0 | Alert geography (polygon, county, zone, null geometry) | Statewide list from NWS; per-town check by point (NWS matches polygons and zones); null geometry listed; tested |
| P0 | Lifecycle: revisions, duplicates, outages | Replaced updates and test messages dropped; failed refresh keeps the last verified list; tested. No notifications yet, so no duplicate-notification risk |
| P0 | Baseline and predeclared evaluation metrics | **Not started** (Next 4) |
| P1 | Roofing job context | Parked with the app |
| P1 | Advanced guidance trials (SPC CIG, ProbSevere v3, LightningCast) | Listed only |
| P1 | Broader vendor comparison | Listed only (Next 9) |
| P1 | Pinned feed contracts | Done: `website/sources.py` `CONTRACTS`, shown on the About page |
| P2 | Raw national model ingestion | HRRR precipitation rate, temperature and gusts for Montana only (D28); nothing national |

## Release gates (review's proposed targets)
| Gate | Status for the website |
|---|---|
| No missed applicable severe/tornado alert | NWS does the matching; the statewide list shows every active Montana alert. Real-event checks: add curated Montana cases |
| Every injected outage shows stale/unavailable; no missing-data all-clear | Covered by tests (alerts, gusts, every source down) |
| AI summaries | Not applicable: the site generates no AI text |
| Every displayed number/time/location traces to evidence | Each section names its source and time; feed contracts on the About page |
| p95 < 60 s from alert retrieval to notification | Not applicable until alerts reach phones (Next 8) |
| Recover from a 30-minute interruption without lost records | Next build after an outage is complete; last verified alerts carried across |

## Open questions for Carson
- Answered 2026-10-17 (D31): every Montana city over 8,000 in the 2020 census, plus Sidney at Carson's
  request. Anaconda, Belgrade and Sidney were added (17 towns); none was dropped. Glasgow, Glendive,
  Lewistown and West Yellowstone stay (under 8,000). Whitefish (7,751) and Laurel (7,222) are under
  8,000, and Lockwood and Evergreen are census-designated places, not towns, so none of those was added.
- The company's weather limits for each roof system (Next 3).
- Delete the parked desktop app, or keep it in the repo?
- Should the site have its own web address (a custom domain) instead of the GitHub one?
- Check "Montana Hail Watch" against existing products and trademarks before printing it anywhere
  (D26).
- The repo description says "Roofing Weather and Maps Contact app". What should "Contact" cover?
- Globe questions (3D storm view): see `research/globe/README.md` section 14. Answer these first: keep or
  relax the site-files-only browser rule; rule on the one new browser script for the storm text (P1) and,
  later at the P4 gate, a vendored WebGL library; may storm or height views ever reach homeowners, adjusters
  or insurers?

## Missing inputs
- The handoff's two images (dashboard concept, hero photo) were not provided.
- The review cites `Roofing_Weather_Engine_Blueprint.md`, which isn't in this repo. Add it to
  `docs/handoff/` if it exists.
