# Hail history build brief (stage H1 to H3 on the site): the owner's decisions of 2026-10-18

Owner (Carson) decided, 2026-10-18: (1) the five-year window is the trailing five years to today; (2) a public
lookup by typed address or clicked location, with a dot for every Montana address on the map and a popup with
that location's weather history; (3) GitHub Pages only for now; (4) updates as consistent and recent as
possible; (5) find and read the hail units and codes, then make the sizes easy to understand, with the exact
date hail happened at the location; (6) no owner names; all addresses; all types of weather at the address for
the past five years in the popup; (7) follow the laws.

Units and codes are now verified: NOAA's MRMS GRIB2 user table (research/hail-history/validation-evidence/
mrms-grib2-tables/mrms-grib2-tables.json): MESH and the MESHMax swaths are millimetres; -1 is the missing value
and -3 is no coverage (never "no hail"); MergedReflectivityQC -99 is missing and -999 no coverage. Sizes may now
be shown in inches, rounded to a tenth, with the mm value kept in the data.

Research: research/hail-history/README.md (read sections 1, 4, 5, 8, 9 first) and the prototype
research/hail-history/prototype/mesh_history.py with its evidence h1-mesh-store.json and h1-mesh-store-review.json.
Site rules: AGENTS.md (Python first; the map's browser-only script is documented; the one off-site exception is
the opt-in USGS imagery, D32; evidence honesty rule 5; feed contracts rule 7; real-browser checks rule 8).

## Product (what the site does when the flag is on)
A new build flag `--hail-history` (off by default; branch previews pass it like `--storm-layers`). With it:
1. **Hail store as site files.** `website/hail.py` builds (or carries forward) the five-year store for the
   state into `_site/hail/`: per-0.1-degree-tile gzip JSON shards of (cell, SPC day, mm) for every positive
   cell-day (10,007,756 rows in the window; the prototype's 0.25 in subset was 13.4 MB in 4,595 shards; the
   full positive set is larger, measure it; the budget is 60 MB of shards) plus `hail/index.json` (the grid,
   the mask, the day list, the as-of date, the missing days, the copy rule results). The backfill is a
   one-off outside the 10-minute build (the prototype does it in 5 minutes here); the 10-minute build never
   downloads the archive. Carry-forward: the build restores the store from the Actions cache (key by the
   latest SPC day) or, when the cache misses, from a committed seed `website/data/hail-seed.tar.zst`
   (if the seed is over 50 MB, keep it as a GitHub Release asset instead and say so); then, when the newest
   12:00 UTC file is published and not yet in the store, it fetches that one file (39 KB to 1.8 MB), applies
   the copy rule (HEAD both copies; if the bytes differ, re-derive the day from the two-minute frames), decodes
   it (about 1 s) and appends the day. The as-of date and "not yet published" state are on every page that
   shows history. A day that fails stays missing and is listed, never zero.
2. **Click anywhere: the cell's history.** On the Map page, with the flag on, a click (or tap) on the map
   opens a popup (the existing sheet pattern, Python-rendered words) for the 0.01-degree cell: "Radar
   estimated hail at this location, five years to <as-of date>" with the list of days (date in Montana time
   of the SPC day, the estimated size in inches and mm, a class word: 0.25 to 0.74 in small, 0.75 to 0.99
   penny to nickel, 1.00 to 1.49 quarter to golf ball, 1.50 to 1.99, 2.00 and up; the words name the coin or
   ball size as the NWS does and never say damage), the count of days per class, "No radar estimate on other
   days is not 'no hail'", the cell size (about 0.6 by 0.8 miles), the missing-day note, and the source line
   with the as-of date. The browser only fetches the tile shard for the clicked cell and renders the words the
   build wrote (templates in the shard or a words table in map.json; the JavaScript is the click, the fetch and
   the sheet, documented in map.js's header like the satellite work).
3. **Reports, warnings and wind in the same popup** (the "all types of weather" ask): from the H2 joins:
   the NWS local storm reports (hail and wind, with size or gust, measured or estimated, distance and bearing
   from the cell, source) within 5 miles in the window; NCEI Storm Events hail and thunderstorm-wind points
   within 5 miles; SWDI hail signatures within 2 miles (count and the largest MAXSIZE, labelled a radar
   detection); the NWS warnings whose polygon covered the cell (severe thunderstorm and tornado with their
   hail and wind tags; also the zone-based warnings for the cell's NWS zone: high wind, winter storm,
   blizzard, flood, red flag, from IEM's VTEC archive if it is reachable, else say so); the nearest station's
   gusts at or above 50 kt by date (station name, distance). Every item carries its kind word (report, official
   warning, radar detection, station observation) and never a damage word. Where a source has a known gap
   (NCEI after 2026-06-30; SWDI gaps), the popup says it.
4. **Address dots and search.** A dot for every address in the state structures and addresses framework
   (674,715 points; owner fields never read; ParcelID dropped), drawn only from zoom 13 inside the viewport
   from per-tile address shards (0.02-degree tiles so the largest shard stays under 300 KB; measure), on the
   imagery base map or the white map; a click on a dot opens the same popup for that address (the address
   line on top: street, city, ZIP). A search box ("Find an address") with a Python-built index of street
   names by city (prefix search in the browser over one small index file per city; measure the bytes) that
   zooms to the address and opens its popup. No address list is exposed as one file; the shards are the
   tiles the map needs. The imagery switch (branch claude/imagery-basemap) is a prerequisite for the
   zoom-13-and-up view; stack on it.
5. **Laws and terms** (decision 7): the About page states the sources and their terms (MSL framework:
   public, "for no other purpose" quoted with its purpose sentence; NOAA public domain with attribution;
   IEM attribution; USGS credit), that owner names are never read, that the history is radar estimates and
   reports and warnings, not damage findings, and a privacy line for the search (the typed address stays in
   the browser; nothing is sent off-site). MCA 2-6-1017 and 2-6-109 (lists of persons) do not apply to
   addresses without names on the plain reading recorded in the research; this is the owner's and counsel's
   call, so the flag stays off on main until he says the About text is right.
6. **Updates (decision 4).** The daily append runs inside the 10-minute build (item 1), so the newest day
   appears within one build of its 12:08 UTC publication; the schedule offset (branch claude/schedule-offset)
   is the consistency fix for the builds themselves; a "History as of <date>; next day expected after
   12:10 UTC" line shows the state.

## Stages and gates for this build (each a pull request; previews on the branch)
- **B1 store and click-anywhere popup** (hail.py, the shards, the carry-forward with the Actions cache and
  the seed, the popup words, tests, contract rows, docs, the About text). Gate: the flag-off build unchanged;
  the flag-on site at most 60 MB larger; a click on Benchland (47.08 N, 110.02 W) lists 2025-06-15 with
  2.0 in (51.3 mm) and the SPC report of 1.75 in that day within 5 miles once B2 lands; the store equals the
  prototype's on every cell; the daily append verified against a re-decode; smoke test in Chromium at 390 and
  1280 px; zero off-site requests in the default state.
- **B2 joins** (reports, signatures, warnings, station gusts): offline pulls into `website/data/hail-joins/`
  (gzip JSON, measured; refreshed by a weekly job or by hand with a tool under tools/), joined into the
  popup. Gate: the Benchland day reproduces the research's matches; every item has its kind word; the words
  pass the forbidden-term check (damage, dry, clear, no hail, insurance, eligible).
- **B3 addresses** (dots, shards, search, the About terms text). Gate: 674,715 points in the shards; the
  largest shard under 300 KB; dots only from zoom 13; search finds "1 N 27th St Billings" and a rural
  address; no owner field anywhere (test); screenshots at 390 and 1280 px over Billings at zoom 15 on
  imagery.
- **B4 live swaths** (the globe plan's P3: MESH 30 to 1440 minute swath layers on the Map behind
  --storm-layers, units now verified) comes after B1 to B3.

## Conventions
Python 3.12 in CI; numpy, pygrib (lazy import), h5py; no new browser libraries; map.js changes documented in
its header; store UTC, show Montana time; sizes in inches to a tenth with mm kept; every colour and class
carries its word; tests with every behaviour change; no model, AI-vendor or AI-product names in repo files;
no em-dashes; plain wording, sentence case.

cat >> /tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/hail-build-brief.md <<'EOF'

## B1 interface spec (fixed; every builder works against this)

Measured 2026-10-18: GitHub Pages serves `.json` with `content-encoding: gzip` in transit (data/map.json 45,928 B on disk,
5,713 B on the wire; `cache-control: max-age=600`). So shards are plain `.json` files; no decompression in the browser;
on-disk bytes are uncompressed and the budget below is on-disk.

### Grid (the prototype's, from the GRIB2 header; `research/hail-history/prototype/mesh_history.py` lines 60-70)
- 3,500 rows x 7,000 cols at 0.01 degree; row 0 centre at lat 54.995 (north edge); col 0 centre at lon -129.995.
- `row = round((54.995 - lat) * 100)`, `col = round((lon + 129.995) * 100)`; cell centre `lat = 54.995 - row/100`,
  `lon = -129.995 + col/100`. Integer arithmetic in thousandths where exactness matters (Python side).
- Tile = 10 x 10 cells (0.1 degree). Shard for a cell: `hail/t/r{row//10:04d}_c{col//10:04d}.json`.
- In-tile cell key `k = (row % 10) * 10 + (col % 10)` (0..99).
- Day index `d = (spc_day - 2020-01-01).days`; `d0 = "2020-01-01"` is fixed for ever so indexes never shift as the
  window moves. The SPC report day D is held by the 12:00 UTC file stamped D+1 (prototype `day_of_stamp`).
- Values: tenths of a mm as integers (prototype `pack_tenths`: `rint(raw*10)`, 0 = no data; -1 missing and -3 no
  coverage are never stored; a value above uint16 raises). Event floor 64 tenths (0.25 in = 6.35 mm, prototype
  `EVENT_MIN_TENTHS`). Only state cells (the Montana polygon mask from `website/static/map/basemap.json`, 450,765 cells).

### Files the build publishes under `_site/hail/`
- `hail/index.json`: `{"format":"hail-store-v1","built_at":"<UTC>","as_of":"<last SPC day>","window":["<start>","<end>"],
  "d0":"2020-01-01","grid":{"cell_deg":0.01,"tile_cells":10,"row0_lat":54.995,"col0_lon":-129.995,"rows":3500,"cols":7000},
  "state":"Montana","cells_in_state":450765,"floor_tenths":64,"floor_in":0.25,"days_expected":1826,"days_present":1825,
  "missing_days":["2022-06-09"],"events":<n>,"shards":<n>,"bytes":<n>,"source":{"product":"MESH_Max_1440min_00.50",
  "bucket":"https://noaa-mrms-pds.s3.amazonaws.com","file_time":"12:00 UTC","spc_day_rule":"the file stamped D+1 at 12:00
  UTC holds SPC report day D (12:00 UTC D to 11:59 UTC D+1)","units_table":"UserTable_MRMS_v12.2 (MESH mm; -1 missing;
  -3 no coverage)"},"copy_check":{"days_checked":<n>,"days_differed":[...],"rederived":[...],"skipped":"<reason or null>"}}`.
  The window is the trailing 1,826 SPC days ending at `as_of` (decision 1).
- `hail/t/r0790_c0199.json`: `{"f":"hail-cells-v1","r":790,"c":199,"d0":"2020-01-01","u":"tenths of a mm",
  "cells":{"37":[[2357,513],[1996,89]]}}`; only cells with at least one event; each list sorted by day; integers only.
- `hail/manifest.json`: sha256 and bytes of every file above plus the index's counts; the build verifies it after unpacking.
- Budget: all of `hail/` at most 60 MB on disk (expect 25 to 40 MB for 2.64 M events); measured in the verification record.

### Where the store comes from (the daily job) and how the 10-minute build gets it
- `.github/workflows/hail-store.yml`: `schedule: "43 12 * * *"` (the 12:00 UTC file posts about 12:08) + `workflow_dispatch`;
  `permissions: contents: write`; `timeout-minutes: 60`; Python 3.12; `pip install numpy pygrib requests`; steps:
  `python -m website.hail build --out store` (full rebuild of the trailing window from the NOAA bucket; a local download
  cache dir is allowed, and an Actions cache of the downloaded `.grib2.gz` files is allowed, but a build from an empty
  cache must work and must produce byte-identical shards), `python -m website.hail verify store` (counts, manifest hashes,
  the Benchland fixture day), `tar czf hail-store.tar.gz -C store hail`, then
  `gh release create hail-store --prerelease --title "Hail history store" --notes "..."` if the release does not exist and
  `gh release upload hail-store hail-store.tar.gz --clobber`. One rolling asset; its URL is
  `https://github.com/carson14dy/RoofingApp/releases/download/hail-store/hail-store.tar.gz` (owner/repo from
  `GITHUB_REPOSITORY` when set, else that constant).
- Copy rule (decision 4 and research OW-H4): for each day, HEAD the NOAA bucket copy and the IEM copy
  (`mtarchive.geol.iastate.edu`); if both answer and the byte sizes differ, re-derive that day as the maximum of the
  720 two-minute `MESH_00.50` frames and record the day under `copy_check.rederived`; if IEM does not answer, record
  `skipped` and use the bucket copy. The prototype found four differing stamps (2025-06-26, 2025-06-27, 2026-05-26,
  2026-09-11) and that the bucket copy of 2025-06-26 is the outlier against its own frames.
- `website/build.py --hail-history` (default off; branch previews in website.yml pass it like `--storm-layers`):
  `Collector.hail` downloads the asset through the collector's `get` (follows redirects), verifies `manifest.json`,
  unpacks into `_site/hail/`, writes `data/map.json["hail"]` and renders the town tables. A failed fetch or a bad
  manifest is a failed source under `--require-live` like every other feed (the previous deploy stays live); without
  `--require-live` the pages show the unavailable words. `--sample` uses the fixture store (two tiles: Benchland
  r0790/c0199 area and Billings) labelled SAMPLE on the sheet and the town tables.
- `website/sources.py` CONTRACTS["hail_history"]: units (mm stored as tenths; shown in inches to a tenth with mm),
  timing (SPC day 12:00 to 11:59 UTC; 12:00 UTC file of D+1), cadence (one day per day, job 12:43 UTC), missing rules
  (-1 missing and -3 no coverage never stored; 0 or absent = no estimate, never "no hail"; absent days listed), the
  copy rule, the floor, the source and the units table.

### `website/hail.py` public API (builder 1 writes the skeleton with these names first, then fills it in)
```python
FLOOR_TENTHS = 64; D0 = date(2020, 1, 1); TILE = 10; STORE_URL = "...releases/download/hail-store/hail-store.tar.gz"
CLASSES = (...)        # see Words; min_tenths, max_tenths, word, severe flag
WORDS = {...}          # every sentence template the sheet and the town tables use (placeholders in braces)
class HailStoreError(Exception)                      # message is the plain words shown as the problem
def cell_for(lat: float, lon: float) -> tuple[int, int]
def cell_centre(row: int, col: int) -> tuple[float, float]
def shard_path(row: int, col: int) -> str             # "hail/t/r0790_c0199.json"
def cell_key(row: int, col: int) -> int
def day_index(spc_day: date) -> int; def day_of_index(d: int) -> date
def inches(tenths: int) -> str                        # "2.0" for 513 (51.3 mm / 25.4 = 2.02); one decimal, no trailing noise
def class_for(tenths: int) -> dict
def fetch_store(get, dest_dir, url=STORE_URL) -> dict  # download, verify manifest, unpack hail/; returns the index
def load_index(store_dir) -> dict
def cell_events(store_dir, lat, lon) -> list[tuple[date, int]]   # from the shard; for town tables and tests
def describe(index, events, now, sample=False) -> dict            # Python-rendered words for a cell (town pages, tests)
def map_data(index, sample=False) -> dict                         # the map.json["hail"] block (grid, window, words, classes)
def fixture_store(dest_dir) -> dict                               # the SAMPLE store for --sample and tests
# CLI: python -m website.hail build|verify|compare|fixture|fetch (argparse; build takes --start/--end/--cache/--procs)
```
`compare --store <dir> --prototype /tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/hail-store/h1-mesh`
maps the prototype's crop cell indexes (its `grid.json` crop row0/col0 and `mask.bin`) to global row/col and reports
mismatches between its `events.parquet` (cell, day, mm; pyarrow is in the venv
`/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/hail-venv`) and the new shards:
the gate is 0 mismatches. The prototype's downloads are at
`/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/hail-dl/mesh-backfill` (1,825 files,
901,938,706 B): point `--cache` there so the build does not download again.

### `data/map.json["hail"]` (present only with the flag)
`{"state":"loaded"|"unavailable"|"sample","as_of":"...","window":[...],"d0":"2020-01-01","missing_days":[...],
"grid":{...as index...},"shard":"hail/t/r{r}_c{c}.json","floor_in":0.25,"classes":[{"min_in":0.25,"max_in":0.74,
"word":"pea to mothball","severe":false},...],"words":{...},"source":"...","problem":null|"..."}`.
The browser (map.js) does only: the click or tap, the row/col/shard arithmetic above, one fetch of the shard, the
day-index to date arithmetic, filling the Python templates, the sheet open/close, and `?at=lat,lon` in the URL.
No threshold, unit or wording literal lives in map.js (a test greps for them). Document the duty in map.js's header.

### Words (Python; tested for forbidden terms: damage, damaged, dry, clear, insurance, eligible, confirmed, "no hail"
### outside the one negation sentence)
Classes follow the NWS hail size chart (weather.gov): 0.25-0.74 in "pea to mothball"; 0.75-0.99 "penny to nickel";
1.00-1.49 "quarter to half dollar" (severe size, 1 in or more); 1.50-1.99 "ping-pong ball to golf ball";
2.00-2.74 "hen egg to tennis ball"; 2.75 and up "baseball or larger"; at 4.00 in and above add "unusually large for a
radar estimate; treat with care" (research OW-H5). Every size shows inches to a tenth and mm.
- Title: "Hail history at this spot" (B3 puts the address line above it).
- Lead, n > 0: "{n} days with a radar-estimated hail size of 0.25 in or more between {start} and {end}. Largest:
  {largest_in} in ({largest_mm} mm) on {largest_date}." (singular form for 1).
- Lead, n = 0: "No day between {start} and {end} has a radar-estimated hail size of 0.25 in or more at this spot.
  That is not the same as no hail: radar estimates miss some hail, and {missing} days have no data."
- Row: "{date}: {in} in ({mm} mm), {class}" plus "severe size" for 1 in and up; newest first.
- What this is: "A radar estimate (NOAA MRMS MESH) of the largest hail over this 0.01-degree cell, about 0.7 by 0.5
  miles, during the day. An estimate is not a measurement at the ground and not an inspection. A day runs from
  12:00 UTC to 12:00 UTC, about 6 am to 6 am Mountain time (the SPC reporting day)."
- Missing: "Days with no data, not counted: {list}." Outside: "Outside Montana. The history covers Montana only."
- Unavailable: "Hail history is unavailable: {problem}. Nothing shown here means 'no hail'."
- Source: "Source: NOAA MRMS MESH 24-hour maximum, 12:00 UTC files, NOAA Open Data on AWS. History as of {as_of}; the
  next day is expected after 12:45 UTC." Sample: "SAMPLE data" on the sheet title and every town table.
Dates read "Jun 15, 2025" in the sheet and the tables.

### Town pages (Python only, no script)
With the flag on, each town page gets a "Hail history, five years" section: the lead sentence, the table of days (date,
size in inches and mm, class word, severe tag), the what-this-is and missing lines, the source line; the SAMPLE label in
sample builds. Rendered from the town's cell via `cell_events` and `describe`. Flag off: no section, no bytes.

### Map page
With the flag on: a click or tap on the map (not on a bubble, control, popover or sheet) opens the hail sheet for that
point using the existing sheet pattern (D28); the legend gets the line "Tap or click the map for the five-year hail
history at that spot"; `?at=lat,lon` opens the sheet on arrival (and is written on click); the noscript and List
template paragraphs say the history is in the town pages' tables and needs the interactive map elsewhere. Outside the
state mask: the outside words, no fetch. Fetch failure: the unavailable words. Zero off-site requests.

### Ownership (one worktree; disjoint files)
- Builder 1 (store): `website/hail.py`, `tests/test_hail.py`, `.github/workflows/hail-store.yml`,
  `website/data/hail-fixture/` (the SAMPLE store, generated by `fixture`, committed, under 50 KB).
- Builder 2 (site): `website/build.py`, `website/sources.py`, `website/templates/{map,town,about,base}.html` as needed,
  `website/static/map/map.js`, `website/static/map/map.css`, `tools/smoke_map.py`, `tests/test_site.py` additions,
  `.github/workflows/website.yml` (the flag on branch previews).
- Builder 3 (docs): `docs/DECISIONS.md` D34 (Carson's seven decisions verbatim, the units table result, this design and
  why), `docs/DESIGN.md` (sheet and table states and words), `docs/ROADMAP.md` (Done row, Next items for B2 to B4),
  `README.md`, `AGENTS.md` (layout line for hail.py and the flag; rule 7 unchanged), the verification record skeleton
  `research/hail-history/validation-evidence/b1-verification.json` (the reviewers fill the measurements).
EOF
wc -l /tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/hail-build-brief.md

cat >> /tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/hail-build-brief.md <<'EOF'

### Additions fixed on 2026-10-18 before the build started
- `--hail-store PATH` on `website.build` (a local directory or tar.gz holding `hail/`) replaces the asset download; the
  daily job's tar is exactly that file. The Website workflow's branch previews use the download; local checks use the path.
- `map.json["hail"]["tenths_per_inch"] = 254` so map.js divides by a data value, never a literal; the test for map.js
  forbids the strings "25.4", "254", "6.35", every class word and every sentence template.
- WORDS gets a stale line for an `as_of` older than 3 days: "The newest day in this history is {as_of}; newer days have
  not been added yet." and a loading line "Loading the hail history for this spot".
- Dates in the sheet come from the day index through the browser's own date formatting as "Jun 15, 2025" (UTC, so the
  SPC day's date is never shifted by the viewer's time zone); the town tables are formatted in Python the same way.
- The store's window ends at the newest 12:00 UTC file published at build time (the SPC day before that stamp) and
  starts 1,825 days earlier (1,826 SPC days). The comparison with the prototype store runs on the overlapping days.
- Branch `claude/hail-b1`, worktree `/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/wt-hail-b1`,
  based on the imagery branch commit 825d6c7 (which includes P2). Nobody commits or pushes in that worktree; the supervisor does.
EOF
echo ok

## Supervisor decisions after review round 1 (2026-10-18 06:00 UTC); these override the spec above where they differ
1. **Inches to two decimals.** Sizes show inches to two decimals with the mm value ("2.02 in (51.3 mm)"; "0.99 in (25.3 mm)"),
   the NWS report convention, so a displayed size never crosses a class boundary its exact value does not cross. Classes,
   the severe tag (254 tenths and up) and the 4.00 in note (1016 tenths and up) stay on the exact tenths. The town tables
   and the sheet use the same rule; `inches()` returns the two-decimal string; `tenths_per_inch` stays 254 in map.json and
   the browser rounds to two decimals. Update the brief's "to a tenth" wording everywhere it is quoted in docs and tests.
2. **Outside the state is decided by the store, not by the grid box.** Every tile that holds at least one Montana cell gets
   a shard, even with zero events; each shard carries `"state": [k, ...]` (the in-tile keys of the Montana cells, sorted) next
   to `"cells"`; `hail/index.json` carries `"tiles": ["r0790_c0199", ...]` (every shard's name; about 4,600 entries) and
   map.json["hail"] carries the same list (or a compact row-major bitset of the tile grid with its bounds, if the list is
   over 60 KB; say which). The browser: tile not in the list means the outside words with no fetch; the key not in the
   shard's `state` list means the outside words; otherwise the events, or the no-estimate words when the list is empty.
   The sample fixture follows the same format.
3. **The Benchland gate point.** The brief's gate named 2.0 in (51.3 mm) at 47.08 N, 110.02 W, but that point sits on a cell
   edge (row 791.5) and the real store holds 185 tenths at the cell the formula picks (792, 1998). Find the cell nearest
   Benchland holding 513 tenths on SPC day 2025-06-15 (the research's 2.0 in came from the prototype's nearest-centre
   lookup, which chose a different cell), and make the gate point that cell's centre. The gate then reads "2.02 in
   (51.3 mm) on Jun 15, 2025" at that centre, and the 185 tenths cell shows "0.73 in (18.5 mm)". The SAMPLE fixture must
   carry the real decoded values for the Benchland and Billings tiles for the days it includes (no invented 513), from the
   real store; it stays labelled SAMPLE because it holds only two tiles and a few days.
4. **`?at=` is dropped when the sheet closes** (Escape or the close button), like `?town=`, so a reload does not reopen it.
5. **The flag-off gate.** The flag-off build may differ from the base build only in the shared static assets map.js and
   map.css and in their `?v=` hashes inside pages; the sheet markup in map.html is gated on the flag; no other byte differs.
6. **The compare gate.** `compare` reports the re-derived days separately: on those days the store equals the maximum of the
   two-minute frames by design and differs from the bucket's 1440-minute copy, so the gate is 0 mismatches on every day
   that was not re-derived, plus, for each re-derived day, 0 mismatches against the frame maximum (the builder's own
   re-decode counts as that check when it is written to a file the reviewer can read).
7. **Tests never delete above their own folder.** No test may call rmtree, rm -rf or unlink on anything but a directory it
   created itself (a test deleted the shared temporary directory's parent on 2026-10-18 and wiped the session's scratch
   area three times). A reviewer greps every test for rmtree and checks the argument is a directory the test made.
8. **A town bubble covers its own cell.** On the Map, a click on a town's bubble opens the town card, not the hail sheet;
   the town's hail table is on its page; the sheet's what-this-is line does not need to say so, but DESIGN.md does.
9. **Verify checks integers.** `verify` fails on any non-integer in a shard's cell lists.

## Supervisor decisions for round 2 (2026-10-18 07:10 UTC); these override round 1 where they differ
10. **One display rule: inches to two decimals, rounded down** (floor), with the exact mm value beside it: 513 tenths is
    "2.01 in (51.3 mm)", 185 is "0.72 in (18.5 mm)", 253 is "0.99 in (25.3 mm)", 190 is "0.74 in (19.0 mm)", 1015 is
    "3.99 in (101.5 mm)". Rounding down never crosses a class edge (every class edge in tenths lies at or above its inch
    value), so no caps table: remove `display_caps` and `display_hundredths`; `inches()` returns the floored two-decimal
    string; map.js computes `Math.floor(tenths * 100 / tenths_per_inch) / 100` and formats with two decimals (the 100 and the
    2 are formatting constants, allowed). The words say "shown to the hundredth of an inch, rounded down, with the
    millimetre value exact". Update every example in docs, tests and the record (2.02 becomes 2.01; 0.73 becomes 0.72).
11. **Decision 2 format, fixed.** Shard: `{"f":"hail-cells-v1","r":..,"c":..,"d0":"2020-01-01","u":"tenths of a mm",
    "state":[k,...],"cells":{"k":[[d,t],...]}}` where `state` lists every in-tile key (0..99) of a Montana cell, sorted, and
    `cells` holds only keys with events. Every tile with at least one Montana cell gets a shard, even with no events.
    `hail/index.json` gets `"tiles": ["r0790_c0199", ...]` sorted; map.json["hail"] carries the same list under `tiles`
    (measure its bytes; about 4,600 names). Browser rule: tile name not in `tiles` means the outside words and no fetch;
    key not in the shard's `state` means the outside words; key in `state` with no entry in `cells` means the no-estimate
    words; otherwise the rows. The fixture follows the same format. tools/smoke_map.py checks Wyoming (43.5, -108.0), Idaho
    (44.6, -115.0) and Canada (49.5, -110.0): the outside words and zero shard requests; and an in-state cell with no
    events shows the no-estimate words after one fetch.
12. **Compare gate and partial days.** A re-derived day whose two-minute frames are incomplete is recorded in
    `copy_check.partial` as `{"day": "2025-06-25", "frames": 717, "expected": 720}` and still stored as the maximum of the
    frames that exist (the bucket's 1440 copy for that day disagrees with its own frames, so it is not the better value).
    `compare` passes when every non-re-derived overlapping day has 0 mismatches and every re-derived day equals the frame
    maximum the builder recorded; it prints the partial list. `verify` does not fail on partial days. The index's
    `copy_check` keeps `coverage`, `partial`, `frames`, `rederived`, `days_differed`, `days_checked`, `skipped`.
13. **The daily job installs like the site build.** `.github/workflows/hail-store.yml` uses the same unpinned pip line
    style as website.yml (`pip install numpy pygrib requests`); no version pins (the site build is unpinned and the job
    must not drift from it; a broken dependency fails the job visibly and the site keeps the previous asset).
14. **Words.** The day sentence: "A day runs from 12:00 UTC to 12:00 UTC the next day: 6 am to 6 am Mountain daylight
    time, 5 am to 5 am in winter (the SPC reporting day)." The cell sentence: "the largest hail over this cell, about 0.7
    miles north to south and 0.5 miles east to west, during the day". The next-day sentence: "The newest day is added by a
    job that starts at 12:43 UTC and shows here on the next rebuild, usually within the hour." The contract row, DESIGN,
    About and D34 use the same three sentences.
15. **Gate texts in the record.** B1-3: "the centre of the cell nearest Benchland that holds 513 tenths on SPC day
    2025-06-15 (row 797, col 1986) shows 2.01 in (51.3 mm) on Jun 15, 2025; Benchland's own cell (792, 1998) shows 0.72 in
    (18.5 mm)". B1-5 per decision 12. B1-6: "the daily job is a full rebuild: a cold-cache and a warm-cache build give
    byte-identical shards, and the newest day re-decodes with 0 mismatches" (the carry-forward append in the first spec is
    withdrawn). B1-1 per decision 5.
16. **Test clean-up audit (decision 7) is a reviewer gate**: grep every test under tests/ for rmtree, rm -rf, unlink and
    os.remove; each must act only on a path the test created (tempfile.mkdtemp or TemporaryDirectory inside the test).
