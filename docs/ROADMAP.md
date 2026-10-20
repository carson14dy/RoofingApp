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

## Built, not merged: hail history behind `--hail-history` and `--hail-addresses` (D34, D35, D36)
| Area | What works | Limits |
|---|---|---|
| B1 store and click-anywhere history (branch `claude/hail-b1`, not merged) | The trailing 1,826 SPC days of NOAA's MRMS MESH radar estimate as site files (`hail/`), rebuilt in full each day by `hail-store.yml` and read by the 10-minute build; a click or tap on the Map page opens a spot's day list (sizes to the hundredth of an inch, rounded down, with mm exact; the NWS size words; the SPC day); the outside rule is the store's own tile and state lists; town pages carry the same table; About explains it | Radar estimates, not measurements or inspections; off on `main` until the owner approves the About text and counsel confirms the D34 items; a late 12:00 UTC file makes that run's window end one day earlier; the Benchland 1.75 in report is in B2 (gate B2-1, pending the re-check); the B1 gates are pending the re-check (`research/hail-history/validation-evidence/b1-verification.json`), and B1-4 closes when B2-1 passes |
| B2 joins (branch `claude/hail-b2`, from `claude/hail-b1`, not merged) | In the sheet and each town table, six sections after the radar days, each row with its kind label: reports within 5 miles, official records within 5 miles (NCEI), radar hail detections within 2 miles, warnings whose issuance polygon covered the spot, zone products for the spot's public forecast zone (nine kinds, flood watch among them, named in D35) and the red flag warning for its fire weather zone (ten products in all), and peak gusts at the two nearest stations within 40 miles. A part that fails says so, in the words D20 sets. The daily job joins them after the store and publishes both | Kinds stay apart, and none is a damage finding, an inspection or an all-clear. Round 4 failed gate B2-7 on the page width at 288 and 320 px. Round 5 filled the placeholders, corrected open item 11 and the joins docstring, and fixed the width with an overflow-wrap rule on the joined sections. Round 6 records gate B2-7 as passing on the round-5 build, so every gate but the deferred B2-4 passes there (status pass). D34 (round 6) removed FL.W and FA.A from the zone products; D35 (round 7) restores FA.A as flood watch and keeps FL.W out, so FL.W and the 18 county-only flood watches are in the B5 hand-off (item 20). The round-7 rebuild's figures are in DECISIONS D35 and DESIGN section 9. Gate B2-4 (units) stays deferred as agreed. The byte budgets are measured on the round-7 store (`j/` 19,912,416 bytes of 40 MB; `z/` 919,402 and `s/` 22,478 bytes of 2 MB each; `hail/` 54,227,125 bytes of 60 MB); B3's budget is the open question (D35). A page's first click makes up to seven requests. The counts, the warm run time (96 s and 100 s), the Benchland rows and the Chromium checks are in the record (`research/hail-history/validation-evidence/b2-verification.json`); the cold run is not measured. Open decisions: D35 items 11 to 19 |
| B3 addresses, streets and building outlines (D36; branch `claude/hail-b3` from `claude/hail-b2`, not merged) | Behind `--hail-addresses`, which needs `--hail-history`: the State Library's address points as dots and in a typed-address search (674,715 points; 663,759 rows after 4,212 left out for no street and 6,744 duplicates merged); one dot per building outline from the FEMA and ORNL file (918,052 outlines; 347,838 with a Structure address inside, 99,453 with one within 15 m, 470,761 with none on file); a dot for each address that no outline holds (105,403 rows); the streets from the State Library's roads (258,208 segments; the Census roads as the fallback); the About terms, with the source lines in Leaflet's attribution control at the bottom right, above the timeline, on the first screen and on the About page. The search sends no request that carries the text. The sheet opens with the address line, then the cell's history. The counts are the module runs'; the re-check measures them again | Off on `main`; the terms wait for Carson and counsel (open items below). The outline shards are 196.3 MB raw and carry their own 250 MB budget (D42). The site re-check passed 14 of 18 gates; B3-5, B3-7, B3-10 and B3-18 are fixed in the completion pass (D43 to D46), and their re-check is pending. The 4x CPU run (B3-16) and a GitHub runner (B3-8) are not run. |

Measured for the daily job (`hail-store.yml`), in the re-check: run time, bytes of `hail/` and of the `tiles` list, the largest shard, the copy-check results (rederived, partial, skipped), the days missing, and the cold-cache and warm-cache shard hashes (B1-6); pending.

Measured for the joins (`website/joins.py`) in the re-check: the Benchland rows (B2-1), the counts against the research (B2-2), the bytes of `j/`, `z/` and `s/` against their budgets, the job's run time, the requests and failures per source, the two-run hashes (B2-8), and the Chromium widths and off-site requests (B2-7); round 4 measured them, and the record holds the results (the cold-cache run is not measured). The record is `research/hail-history/validation-evidence/b2-verification.json`.

## Hail B3: open items (D36)
The B3 build (branch `claude/hail-b3`, not merged) is built and checked in the module runs. It goes on `main` only when the owner approves the About text and counsel answers items 1 to 4. The re-check's numbers are in `research/hail-history/validation-evidence/b3-verification.json`.

| # | Item | Who | What is needed |
|---|---|---|---|
| 1 | The State Library's answer on both files | Carson, the Library | A written reuse statement (geoinfo@mt.gov, 406-444-5354, per the Library's readme) on whether derived address points, names and road lines may be published, what "for no other purpose" means for commercial use, and whether the contributing agencies' terms bind the derived file (counsel C4; questions 4 and 5). One answer covers the address points and the roads. |
| 2 | FEMA's licence for the outline file | Carson, FEMA, ORNL, counsel | A written statement on the 2026-09-13 file. Its metadata gives access and use as "None"; the hosted copy says CC BY 4.0; Data.gov says government-works; the 2023 deliverable limits access to FEMA's Response Geospatial Office (C1; question 10). The inputs named in the metadata, LightBox SmartParcels among them, need the same check (C2). |
| 3 | MCA 2-6-1017 and the repealed 2-6-109 | Counsel | Whether a public, searchable map of address points with no names is a "list of persons prepared by a public agency" or "personal contact information", and whether a roofing company's outreach makes it one "used to facilitate unsolicited contact" (questions 1 and 2; C5). MCA 2-6-109 is repealed on the live page, and the About text cites 2-6-1017 only (question 3; C6). |
| 4 | The no-address-text mode as the fallback | Carson | If counsel answers no to item 3, the site is built with `--address-text off`: the dots keep their positions and cell histories, with no address text and no search (D35). This is a configuration change; the data does not change. |
| 5 | The coverage ratio of D21 | Carson, supervisor | Meaning: for each county, the address points that the file's place-type field codes as residences, divided by the 2020 census housing units. The county ratios run from 0.48 (Glacier County: 2,550 points against 5,342 units) to 1.36 (Sanders County: 9,221 against 6,800); the state ratio is 0.96 (493,975 against 514,803). A ratio below 1 means fewer points than housing units, so the list may miss homes. A ratio above 1 means more points than units, so the ratio measures neither completeness nor accuracy. The list is of addresses, not of dwellings. The figure is a research read of the place-type field (`montana-addresses.json`), which the build never reads (D12); open: the owner or supervisor should confirm that this line may stay here (DECISIONS D36, open item (3)). |
| 6 | Four edge tiles outside the hail grid (D23) | Carson | The address list has five rows in four tiles: r0059_c0155, r0100_c0209, r0100_c0230 and r0100_c0231. The outline check finds seven tiles in all, with 17 outlines; the three more are r0100_c0229, r0100_c0232 and r0100_c0257. Their dots say that no hail history is kept there. Accept that sentence, or extend the grid (a B1 change). |
| 7 | The imagery check of the 15 m rule and the placement classes (D32) | Follow-up | The 15 m figure stays until an imagery check supports another distance. The placement classes take the file's Placement value as given. This is not part of this build. |
| 8 | The data-site split (D31; owner decision O3) | Carson | The hail store measures 372,880,597 B raw (31,129 files; D42) and packs to 72,030,584 B in the fresh job store; the outlines alone are 196,301,977 B raw. The 10-minute site should not carry it. Choose a second repository's Pages site; the modules write its base URL into `map.json`, so the switch is a configuration change. |
| 9 | The outline budget (D42) | Supervisor | D42 gives `hail/b/` its own 250 MB budget (196,301,977 B measured). D38's 60 MB covers the address dot shards (7,520,429 B) and the letter files (41,732,176 B). Confirm the 250 MB figure. |
| 10 | The Census county file | Counsel, builder | The county boundary file (`cb_2025_us_county_500k.zip`, read for the per-county counts and named on the About page) has no `CONTRACTS` row, and its terms were not read (C8). |
| 11 | Module items (the supervisor's D36 and the module fixer's list) | Builder | Settled: a wrong or unreadable `--zip` path and a missing projection library exit 0 with the module unavailable (D36; B3R-05, confirmed by the re-check). The zoom keys are settled by D47 (`limits` has no zoom; `zoom.dots` 15 and `zoom.choose` 17 sit at the top level). Settled by D49: the outline step rewrites the address block's figures with the files on disk and the job checks them once more after the rewrite. Open: the address build writes 817 empty shard files of 4,211 (the index's `a.empty`). |
| 12 | The Billings join figures (gate B3-10) | Builder, re-check | Settled by D46: gate B3-10 uses the closed box and the merged rows, with 864 points, 539 inside, 305 within 15 m and 20 farther, over 307 outlines. The synthesis's 869, 535, 313 and 21 were half-open and counted before the merge; 869 is reproduced only that way, and its split under neither rule (R-11). |
| 13 | The dot rule (D15) | Supervisor | The built rule is the midpoint of the longest interior chord when the centroid lies outside the outline (6,535 outlines). D15 says "the nearest interior point". Confirm the chord, or change the rule. |
| 14 | The site re-check (`b3-site-recheck.json`) | Re-check | The site build passed 14 of 18 gates. The sizes, the fetches per pan at zoom 15 over Billings (B3-2), the draw times (median 6.6 ms at zoom 15 and 10.5 ms at zoom 16), the 624 KB budget at 390 px (B3-15) and the Chromium smoke are measured there. B3-5, B3-7, B3-10 and B3-18 need the re-check after the completion pass. Not run: the 4x CPU slowdown (B3-16) and a GitHub runner (B3-8). The runner's memory for the Library build (6,728 MB resident in this VM; the Census fallback 10,034 MB) is not checked on the job's runner. |
| 15 | Commercial use and privacy (questions 17 and 18; C9, C16) | Counsel | None of the NWS, USGS, IEM or NCEI texts read here bars commercial use on its face, and the Library's terms do not address it (D8). The search box, geolocation and any analytics may raise privacy questions outside MCA 2-6-1017. The About text claims neither. |

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
18. **Hail B3, addresses, streets and building outlines (D36): built on `claude/hail-b3`, not merged.** It goes live only after the owner approves the About text and counsel answers the items in "Hail B3: open items (D36)" above; the flag stays off on `main` until then.
19. **Hail B5, the other kinds of record (the D34 hand-off; the B5 brief).** Next. Joins the kinds B2 does not read, with the research's counts for 2021-10-19 to 2026-10-19: NCEI county-coded records (points) within 5 miles, tornado (13 rows), flood (60), flash flood (52), heavy rain (85), funnel cloud (30), lightning (6) and debris flow (10), 256 rows in all; the flood products FL.W (43 events), FA.W (37), FA.Y (548), FL.A (35) and FL.Y (10), and the county-only FA.A (18) and FF.A (2); the snow squall warning SQ.W (78); and the winter, heat, frost and freeze zone products WW.Y (865), WS.A (226), HT.Y (58), EH.W (4), EH.A (3), FR.Y (14) and FZ.W (4). Under D35, B2 joins FA.A (flood watch) as a zone product; FL.W and the other flood products move to B5's polygon path and county path. Settle these first (`DECISIONS.md` D35 open items 17 and 18): whether the zone-coded FF.A (18) events join, and whether the high wind watch HW.A (277) and the blowing dust advisory DU.Y (3) join, which the B5 brief lists and D35 does not. The B5 brief's NCEI counts are 2020 to 2026 totals (open item 19). Zone products that B5 adds follow the period rule (D33). Starts after B2's gates pass on the round-7 build.
20. **Hail B4, live swaths (D34).** MESH 30 to 1440 minute swath layers on the Map behind `--storm-layers`, after B5 (the globe plan's P3). Units are verified (D34, the MRMS GRIB2 user table).

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
