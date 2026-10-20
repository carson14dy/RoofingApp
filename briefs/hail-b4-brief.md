# Hail history B4 brief: live MESH hail swath layers on the Map (the globe plan's P3), behind --storm-layers

Owner decisions (D34): 2 and 6 (a history of weather at a spot), 4 (recent and consistent), 5 (hail units read and made
understandable). Units and codes are verified (NOAA's MRMS GRIB2 user table: mm; -1 missing; -3 no coverage), so the
globe plan's P3 gate on units is met (research/globe/README.md section 6, P3 row; docs/ROADMAP.md Next 11). B4 builds on
B3 (branch claude/hail-b3). It reuses the B1 decode (website/hail.py pack rule, the MRMS grid) and the P2 layer pattern
(website/satellite.py, gridded.py STYLE and legend, map.js one-frame layers with freshness states).

## Product (with --storm-layers, as the satellite picture)
Two Map layers in the Layers menu, under the weather layers: **Hail, last hour** (MRMS `CONUS/MESH_Max_60min_00.50`, a
file every 2 minutes) and **Hail, last 24 hours** (`CONUS/MESH_Max_1440min_00.50`, a file every 30 minutes). Each is one
current frame drawn on the map's image box (the same box and PNG pipeline as the radar frames in gridded.py: crop the
CONUS grid to the box, palette, PNG), with the legend "Radar estimate of the largest hail in the last {window}, in inches
(NOAA MRMS MESH). An estimate, not observed hail and not damage." and the class stops of B1 (0.25 pea to mothball, 0.75
penny to nickel, 1.00 quarter to half dollar, 1.50 ping-pong ball to golf ball, 2.00 hen egg to tennis ball, 2.75 baseball
or larger), every colour with its word; cells under 0.25 in are not drawn (uncoloured is "no estimate of 0.25 in or more",
never "no hail"; the words say so); missing (-1) and no coverage (-3) are hatched like the satellite's missing pixels.
Freshness as the satellite layer: valid time shown; stale after 20 minutes for the hour layer and 60 minutes for the day
layer (the day file is a rolling 24-hour maximum, published every 30 minutes); unavailable after 60 and 120 minutes, with
"This is not an all-clear" on every problem line. The List view and the no-JavaScript panel carry the words: the valid
time, the largest value in the box and where (lat, lon, nearest town and distance), the number of cells at or above 1.00
in, and the parallax-free note that MESH is a radar estimate at the grid cell.
The sheet (B1) gains one line when a layer is on and the clicked cell has a value in the current frame: "In the last
{window}: {in} in ({mm} mm), {class word}, radar estimate at {valid time}" (from the frame's decoded values, which the
build writes as a small per-tile JSON only for cells at or above 0.25 in: `hail/live/<window>/<tile>.json`, so the
browser fetches one small file; measure the bytes; when nothing in the tile is at or above 0.25 in there is no file and
the line is "No estimate of 0.25 in or more in the last {window} here").

## Build
- `website/swath.py` (new): list the bucket folder for today (and yesterday near 00:00 UTC) for the newest file of each
  product; download it (GRIB2 gz, about 0.2 to 1.8 MB); decode with pygrib (lazy import); crop to gridded.IMAGE_BOUNDS;
  pack tenths with hail.pack_tenths; write the PNG through gridded's palette machinery (a new STYLE "hail_swath" with
  the B1 class stops in mm and their words), the per-tile live files, and the text (describe()); freshness from the file's
  valid time against the build's now; the East or West fallback does not apply (one source); on a failed listing or
  download, the layer's state is "unavailable" with the plain reason and the words carry "This is not an all-clear".
- build.py: `Collector.swath` behind --storm-layers, like the satellite; map.json layers "hail_60" and "hail_1440" with
  their frame, legend, words and state; the status line "Hail swath (radar estimate)".
- sources.py: CONTRACTS["hail_swath"] (units mm shown in inches, the two cadences, the file time, missing and no coverage
  codes, the floor, "an estimate, not observed hail and not damage").
- map.js: two more one-frame layers (as the satellite layer: LAYER_WORD, HATCH, titles and source words from map.json),
  the sheet's live line (template from map.json words), documented in the header; no literal thresholds, words or units.
- website.yml: nothing new (the flag is already on for previews); the test step runs tests.test_swath.
- Smoke (tools/smoke_map.py): switch to each hail layer, the legend words, the pixel-change gate (the frame changes the
  picture by more than 2 percent of pixels when the live file has values, else the note), the sheet live line on a cell
  with a value (find one from the live file; skip with a note when the state has none), zero off-site requests.

## Gates (B4-1 to B4-7)
1. Round trip: at 1,000 sampled pixels of each PNG, the palette class equals the class of the decoded value (0 mismatches),
   and the per-tile live files equal the decoded tenths for every cell at or above 0.25 in (0 mismatches).
2. Live content: the newest file of each product listed, downloaded and decoded (grid 3500 by 7000, product name in the
   GRIB header, units check against the table), on at least two builds an hour apart; the valid time read from the file.
3. Freshness states exercised by tests (fresh, stale, unavailable) and the smoke on a live build.
4. Words: every colour carries its word; "not observed hail", "not damage" and "This is not an all-clear" present where the
   brief puts them; forbidden-term check passes.
5. Bytes: each PNG under 150 KB; the live per-tile files measured (expect small on a quiet day).
6. Default build (no --storm-layers) byte-identical to the base except shared static assets and their hashes; a
   --storm-layers build without --hail-history still works (the live line needs the sheet, which needs --hail-history; the
   layers do not).
7. Chromium smoke at 390 and 1280 px; smoke_pages; the live preview build on the branch.

## Ownership (worktree /home/user/wt/wt-b4, branch claude/hail-b4 from claude/hail-b3's head)
- Builder 1: `website/swath.py` (new), `tests/test_swath.py` (new), gridded.py STYLE/legend additions (coordinate: the
  satellite's pattern), `website/sample.py` (sample frames for --sample, labelled SAMPLE).
- Builder 2: build.py, sources.py, templates (map.html radios and List words, about.html bullet), map.js, map.css,
  tools/smoke_map.py, tests/test_site.py, .github/workflows/website.yml (the test module).
- Builder 3: D37, DESIGN (layers, colours, states, data contract), ROADMAP (Next 11 done; the globe P3 row), README,
  AGENTS layout line, research/globe/validation-evidence/p3-verification.json skeleton.
Same rules as B2 and B3.

## Pre-check of the two products (supervisor, 2026-10-19 02:00 UTC; scripts in /home/user/hail-b4/precheck/, files in /home/user/hail-b4/cache/mesh-max/)
- Listing: `https://noaa-mrms-pds.s3.amazonaws.com/?list-type=2&prefix=CONUS/MESH_Max_60min_00.50/YYYYMMDD/` returns the day's keys
  `CONUS/MESH_Max_60min_00.50/YYYYMMDD/MRMS_MESH_Max_60min_00.50_YYYYMMDD-HHMMSS.grib2.gz`; 60 files by 01:58 UTC (one every 2
  minutes; 36,991 to 38,943 B gzipped, about 55 KB as GRIB2). `MESH_Max_1440min_00.50`: 4 files by 01:30 UTC (00:00, 00:30,
  01:00, 01:30; 119,036 to 123,783 B gzipped, about 157 KB as GRIB2). The newest hour file was listed within 2 minutes of its
  time; the newest day file within about 30 minutes.
- GRIB2 header (pygrib 2.1.8 reads the grid_png packing): discipline 209, category 3, parameter 30 (the table's MESHMax60min,
  "MESH Hail Swath 60-min", 2-min, mm, Missing -1, No Coverage -3) and 34 (MESHMax1440min, "MESH Hail Swath 1440-min", 30-min,
  same units and codes); centre 161 (NOAA OAR), generating process 97, product definition template 0 (instantaneous: the
  window is implied by the parameter number, not written in the header); dataDate 20261019 and dataTime 158 (HHMM) give the
  valid time 2026-10-19 01:58 UTC, equal to the file name's time; pygrib's `validDate` attribute returns it.
- Grid: regular_ll 7000 by 3500, first point 54.995 N, 230.005 E (longitudes are stored 0 to 360; subtract 360: -129.995),
  last 20.005 N, 299.995 E, 0.01 degree, scanning mode 0: the B1 grid exactly (hail.py's row 0 and column 0).
- Values: no zeros in either file. -3 on 8,227,860 cells (outside radar coverage, the CONUS frame); -1 on every other cell
  without an estimate. Hour file: 1,582 positive cells over CONUS, largest 16.9 mm; day file: 38,837, largest 41.4 mm.
  Montana window (44.3 to 49.1 N, -116.1 to -104.0): 580,800 cells; day file 8 positive (largest 6.6 mm), the rest -1; hour
  file none positive, all -1; no -3 cell in the window.

## Decisions from the pre-check (D1 to D6; they refine the Product section above)
- D1 **-1 is not hatched.** Every cell without an estimate is -1 in these products (there are no zeros), so hatching -1
  would cover the whole state. -1 cells stay uncoloured, and the legend's uncoloured sentence reads "Uncoloured: no radar
  hail estimate of 0.25 in or more in the last {window}, or no value; NOAA's data does not tell the two apart. (Amended by the swath fixer, 2026-10-19, browser-6: the window is named per layer, "hour" or "24 hours"; this supersedes "in the window".)" -3 cells are
  hatched with the word "no radar coverage" (none in Montana today; the tests use a synthetic frame with -3 cells).
- D2 **Valid time and window.** The valid time comes from the header (dataDate, dataTime) and must equal the file name's
  time, else the layer is unavailable with the reason; the window comes from the parameter number (30 is 60 minutes, 34 is
  1,440 minutes) and must match the product folder, else unavailable. The valid time is the end of the window.
- D3 **File choice.** One listing per product (list-type=2 with the day prefix); the newest key; when today's folder is
  empty (just after 00:00 UTC) the newest key of yesterday's folder; one download per product per build; cached by key.
- D4 **Live per-tile files.** `hail/live/60/<tile>.json` and `hail/live/1440/<tile>.json` only for tiles with a cell at or
  above 64 tenths (0.25 in; B1's floor): {"f":"hail-live-v1","window":60,"valid":"2026-10-19T01:58:00Z","cells":[[row,col,
  tenths],...]}; cells below the floor are not written; the browser fetches at most one file per window per click; the
  sheet's line follows B1's two-decimal floor and class words with the exact millimetres.
- D5 **Words for a -1 cell.** The sheet's line when the clicked cell is not in the live file: "No radar hail estimate of
  0.25 in or more in the last {window} here (as of {valid time})." It never says "no hail".
- D6 **Freshness.** Hour layer: fresh within 20 minutes of the valid time, stale to 60, then unavailable; day layer: fresh
  within 60 minutes, stale to 120, then unavailable; every stale or unavailable line ends "This is not an all-clear."

## Folded follow-ups (small, docs and wording only; they ride B4 so no extra pull request is needed)
- F1 **P1 code meanings (builder 2, who also owns website/storm.py and tests/test_storm.py for this item only).** The P1
  text still says the meaning of -99 and -999 is "not verified" (storm.py lines 11 to 14, the NO_DATA comment at line 60,
  the sentence at line 243; sources.py CONTRACTS["storm_levels"] "missing" at line 142). docs/DECISIONS.md D34 records the
  verification from NOAA's MRMS GRIB2 user tables (versions 12.0 to 12.2 agree; the archive files do not state their table
  version): in the reflectivity product -99 is missing and -999 is no coverage. Reword those four places to the verified
  meanings with that source, keep "never a value, never 0", keep the clear-night product question open (ROADMAP), and update
  any test that asserts the old sentence. No behaviour change.
- F2 **Globe plan labels (builder 3, who owns research/globe/README.md for this item).** The globe plan's proposal table
  (research/globe/README.md lines 543 to 545 and every mention: D33 to D40 in sections 2, 4, 6, 8 and the freshness
  tables) used decision numbers that main has since assigned to other decisions (D33 schedule offset, D34 hail history,
  D35 hail B2, D36 hail B3, D37 this stage). Rename the proposals GP-1 to GP-8 (globe proposal) throughout that file, keep
  their content, and add one sentence under the table: "GP numbers are proposals from this plan; D numbers are decisions
  recorded in docs/DECISIONS.md." ROADMAP lines 97 and 102: the -99/-999 check is done (D34); the clear-night reading of a
  missing cell still needs the owner's ruling. Nothing else in the globe plan changes.

## Product north star (owner, 2026-10-19; applies to every stage)
Carson: the goal is "an all in one mapping and easy to read all weather app". For builders and reviewers this means:
one map that carries every layer in one layer menu with consistent words; one sheet per place that leads with a plain
summary a roofer can read in a glance (what happened here, how big, when), with details behind headings in a fixed
order (hail, wind, storms and warnings, temperature, rain, snow, flooding, roof indicators as stages add them); every
number next to its unit and its kind word; no section that is a data dump; the same words on the sheet, the town page
and the About page; nothing the viewer must decode. A reviewer finding that a section is hard to read at a glance is a
real finding. Quality over speed: a stage ships when its gates pass, not when the clock says so.

## Supervisor decisions after review (2026-10-19 04:25 UTC; D7 to D12) and the completion list for the module run
- D7 **The browser computes freshness at view time.** The site is rebuilt far less often than every 10 minutes today
  (measured: 7.8 scheduled runs a day) and pages are cached, so a state fixed at build time would read "fresh" long after
  the file aged. map.json carries, per layer, the valid time, fresh_min and stale_min; the browser computes the age and the
  state when the sheet or legend is drawn and fills the Python templates (this is a documented browser-only duty, like the
  page-age check in base.html). The no-JavaScript panel shows the build-time state with "as of the build at {time}". The
  module writes the templates and the thresholds; the site run wires map.js.
- D8 **Live tile URLs carry the valid time.** The per-tile live file pattern is `hail/live/<window>/<tile>.json?v=<YYYYMMDDHHMM>`
  of the frame's valid time, so a cached tile from an earlier build is never paired with a newer layer.
- D9 **The sheet line takes the layer state.** sheet_line(window, tenths, valid, state, state_line) returns the state line
  first when the layer is unavailable; when stale, both the live line and the no-estimate line end with "This is not an
  all-clear."; the 4.00 in note (B1) is appended at or above 1,016 tenths exactly as in the List view; a -3 cell reads "No
  radar coverage at this point in the product." from a `nocov` list the tile carries for any -3 cell inside it.
- D10 **SAMPLE everywhere.** A sample build's List view credits the sample, never NOAA; tile files carry "sample": true and
  the sheet line begins "SAMPLE: invented values" on a sample build.
- D11 **The contract row ships with the parser.** CONTRACTS["hail_swath"] is added in this module run (the module owner edits
  sources.py for this row only): units mm shown in inches to the hundredth rounded down with exact millimetres; cadences 2
  and 30 minutes; the valid time is the end of the window; -1 missing (uncoloured), -3 no coverage (hatched); the 64-tenth
  floor; "an estimate, not observed hail and not damage"; the freshness thresholds of D6. tests.test_swath runs in the
  Website workflow's test step from this branch on (the module owner edits website.yml for that line and the paths entry).
- D12 **Globe plan labels.** The follow-up renamed D31, D32 and D41 as well (GP-9 to GP-11); keep them and move their table
  rows after GP-8 so the table runs GP-1 to GP-11 in order.
- **Completion list (every item is applied whether or not a skeptic kept the reviewer's framing):** F-1 sample source line
  (D10); the CONTRACTS row and the CI test line (D11); sheet_line state, stale sentence, 4.00 in note, nocov (D9); the
  ?v= live pattern (D8); the thresholds and valid time in map_data_swath for D7 with the templates taking {age}; the
  unavailable reason rounds the age up (61 min, not 60) and says "newer than this build's time" instead of "after this
  build's clock"; "{title} is unavailable: {problem}. This is not an all-clear." and plain words for "in the picture"
  ("in this map's area"); the bands-equal-B1-classes test; tests for sample describe, offline mode, the CLI, the hatched
  line, bare "clear"; the one-picture-column docstring; the GP table order (D12).

## Supervisor decisions after the module fix pass (2026-10-19 05:45 UTC; D13, D14) and the completion list
- D13 **No-coverage tiles get a file.** D4 is amended: a live tile file is written when the tile holds a cell at or above
  64 tenths or any -3 cell; a tile with only -3 cells carries an empty "cells" list and its "nocov" list, so the sheet can
  say "No radar coverage at this point in the product." (D9) wherever the product has no coverage. Montana has no -3
  cell today; the labelled sample has 17,500 per product, so the sample build exercises the words.
- D14 **The valid time is in the live path, not a query string.** D8 is replaced: live tile files live under
  `hail/live/<window>/<YYYYMMDDHHMM>/<tile>.json`, the stamp being the frame's valid time exactly as the frame PNG's name
  carries it; each build writes only the current stamp's folder (the previous one is not copied), and map.json's live
  pattern carries the stamp. A cached tile from an earlier build can then never pair with a newer layer.
- **Completion list for the module run (every item applied whether or not a skeptic kept the reviewer's framing):**
  (1) the CONTRACTS["hail_swath"] row with build.py's STORM_CONTRACTS and the tests/test_site.py expectations, from the
  verified three-file patch at /home/user/hail-b4/out/fixer-followups/hail_swath_row.patch (apply all three hunks
  together; the module owner may edit build.py and tests/test_site.py for this item only); (2) D13 in live_files and
  sheet_line with a test on a tile that holds only -3 cells; (3) D14 in live_files, map_data_swath and the tests; (4) the
  Website workflow's test step runs tests.test_swath and its paths list names tests/test_swath.py (the module owner edits
  website.yml for those lines only); (5) D12's table order in research/globe/README.md if the follow-ups fixer did not do
  it; (6) the brief's F1 key name is storm_levels (corrected in this file).

## Supervisor decisions after the module completion (2026-10-19 07:15 UTC; D15, D16) and the site-side list for part B
The module is complete on claude/hail-b4 (WIP c860e23 on db84d76): the full suite passes (849), the self-test passes,
the default build is byte-identical to db84d76, the round trip has 0 mismatches, the live tile folders carry the valid-
time stamp, the CONTRACTS row is in and listed by STORM_CONTRACTS. Gate B4-2's "two builds an hour apart" is met by the
day's module runs (02:53, 03:55, 05:45 and 06:56 UTC, each decoding a valid time equal to its file name); the site
re-check cites them. Part B builds the site side on the same branch (based on db84d76; B3 is on its own branch and is
merged later, so the sheet's live line is built against the B1 and B2 sheet).
- D15 **The words name Montana first.** The picture box reaches into Canada (the hour layer's largest cell on 2026-10-19
  06:40 UTC lay in Saskatchewan, 179.7 miles from Sidney). describe() reports the largest value inside Montana's outline
  (the B1 grid's Montana mask) with its nearest town and distance; when the picture's largest value lies outside Montana
  a second sentence says so: "The largest value in the picture, {in} in, is outside Montana." The nearest-town line is
  never computed for a cell outside Montana. The module writes montana_largest_tenths already; the words change is the
  swath module's (a small, owned edit in part B) with its test.
- D16 **A missing live tile is "no estimate" only on a fresh or stale layer.** The browser fetches
  hail/live/<window>/<stamp>/<tile>.json from the pattern in map.json; a 404 is D5's no-estimate line when the layer's
  view-time state is fresh or stale, and the unavailable line otherwise; a fetch error other than 404 is the D20-style
  "could not be loaded" sentence from map.json, never an estimate and never an error in the console. One fetch per
  window per click (D4), cached by stamp.
- Part B list: build.py Collector.swath wiring behind --storm-layers (frames, hail/live/ stamp folders, map.json layers
  hail_60 and hail_1440 from map_data_swath, the status line, the List view and no-JavaScript words from describe; the
  page-side SAMPLE credit of D10); templates (map.html radios and List block; about.html bullet); map.js (the two
  one-frame layers as the satellite layer; the view-time freshness of D7 from valid, fresh_min and stale_min with the
  {age} templates; the sheet's live line with D16; header duties documented; no literal threshold, word, unit or window
  length); map.css; tools/smoke_map.py (the hail checks of the Build section, the state line, the live line, the 404
  path, zero off-site requests); tests/test_site.py (the flag plumbing, the identity check against c860e23, the map.js
  literal scan, the templates with and without the flag, the List words from a fixture frame); docs (D37, DESIGN,
  ROADMAP Next 11 done and the globe P3 row, README and AGENTS layout lines, p3-verification.json with gates B4-1 to
  B4-7 and the measurements of the module re-checks /home/user/hail-b4/out/b4a-recheck.json and
  b4a-recheck-completion.json).

## Supervisor decisions after the site build (2026-10-19 14:50 UTC; D17 to D21) and the completion list for part B
The site build's re-check (/home/user/hail-b4/out/b4b-recheck.json) passes B4-1, B4-3, B4-5 and B4-6 (full suite 891,
the self-test, the default build identical, the view-time freshness at every threshold, the 404 and 500 paths, the
List and no-JavaScript words, the SAMPLE credit, zero off-site requests). The open rulings:
- D17 **The picture gate for sparse layers.** The 2 percent rule belongs to dense pictures (radar, satellite). The hail
  swath smoke zooms to a cell the live file lists (zoom 10 or closer, where a 0.01 degree cell spans about 7 by 5 screen
  pixels) and requires the picture to change at least 16 pixels at that spot; when no cell in the box reaches the floor,
  the note "no values in the box: pixel gate not applicable". The changed-pixel count is recorded. Gate B4-7 reads so.
- D18 **Product identity.** The product is identified by discipline 209, category 3 and parameter 30 or 34, with the
  units from NOAA's table (pygrib reads the header names as unknown); gate B4-2's "product name in the GRIB header"
  clause reads so. B4-2 is met by the module runs of 02:53, 03:55, 05:45, 06:56 and 14:23 UTC.
- D19 **Picture extent and counts.** The picture keeps the image box, as the radar and satellite layers do; every count
  and largest-value word is Montana-only; the whole-area count line is dropped; D15's one sentence covers a larger value
  outside Montana. ROADMAP keeps the owner's open question whether the picture should stop at the state line.
- D20 **The live line.** "In the last {window}: {in} in ({mm} mm), {class}, the largest radar estimate for the period
  ending {valid}." stands (the module's wording; the Product section's older line is superseded; D37 and DESIGN quote
  this line).
- D21 **Plain words.** "this map's area" replaces "the picture" in D15's sentence and wherever a viewer reads it; "in the
  window" is replaced by the window's own words on every page (the About bullet, the contract row); the browser's state
  tick is once a minute (D7) and the docs say so; PNG sizes are "about 3 KB on a quiet day"; the docs no longer say the
  sample build fails the 2 percent rule (D17 replaces it); the "7.8 rebuilds a day" figure cites the schedule record in
  docs/DECISIONS.md D33 or is removed.
- Completion list (part B): map.js decides Montana before fetching a live file (one request, not two, for a point outside
  Montana); the swath fixer's cross-file patch (/home/user/hail-b4/out/keep/cross-file.patch, with apply_cross_current.py)
  is checked pair by pair and any pair still missing is applied; the stale docs text named by the re-check (DESIGN 11
  lines 618 to 663, D37, ROADMAP lines 34, 48 and 122, p3-verification.json) is brought to the current code and the
  measured numbers; tests/fixtures/default-build-manifest.json and research/globe/validation-evidence/p3-verification.json
  are part of the change (committed by the supervisor); after the pass the supervisor pushes claude/hail-b4 for the
  branch preview (B4-7's last clause).

## Supervisor rulings after the completion pass (2026-10-19 16:05 UTC; D22) and the close-out
The completion re-check (/home/user/hail-b4/out/b4b-recheck-completion.json) passes the suite (895), the self-test, the
default-build identity, the live build, the D17 smoke on live and sample builds, smoke_pages and the Chromium probes.
- D22 **Scope of D21.** D21's "every page" covers B4's hail words. The "in the window" phrases in B2's zone-product
  words (the town pages, the About zone row, the joins words in map.json, the wind zone contract row) are B2's and are
  reworded in B5 part B's sheet work ("in these five years"), recorded in the B5 brief. D17 and D18 are confirmed as
  written; gate B4-2's record reads "met per D18; the name clause is not met as written".
- Close-out (supervisor): the stale status statements (DESIGN.md section 11 status, ROADMAP rows 48 and 122, the record's
  gates B4-3 and B4-7 and its pending list) are corrected to "run and passed locally; the branch preview pending the
  push"; the WIP commits are squashed into one signed commit on db84d76; the branch is pushed for the preview; the pull
  request stacks on claude/hail-b2 once the preview is green.
