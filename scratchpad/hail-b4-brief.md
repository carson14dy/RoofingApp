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
