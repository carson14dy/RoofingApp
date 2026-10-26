# B6 part 1: the map's own cartography data, the five-year pictures, the zone counts, the recent radar hail cells and the value bubble anchors

Stacked on PR 17 (B5). Python data products only; the Map page draws nothing new yet (that is B6-3). Every string the browser
will print comes from map.json or data/base.json, built by Python.

## What changed
- website/terrain.py: 3DEP hillshade and NLCD 2021 land cover tint tiles for zooms 5 to 10 (881 tiles per layer, 14,349,318 bytes).
- website/basemap2.py: reservations, forests, parks, water and route shields in four zoom bands; places with 2020 counts; peaks with 3DEP heights.
- website/landmarks.py: schools, hospitals, airports, fire and EMS stations and parks per tile (2,159 points; churches and the Census park points held for counsel).
- website/history_layers.py and website/labels.py: the five-year hail and heat pictures, the eight zone measures with the newest-warning date, the recent radar hail cells, and the bubble anchors (483,008 bubbles statewide at zoom 17).
- website/build.py: HAIL_FOLDERS_B6, the map.json pointer and data/base.json; sources.py CONTRACTS rows; the jobs; About; docs (D107 to D128).

## How it was verified
- Suite: 2,439 tests OK, 12 skipped (after the post-integration round: see below). Selftest: PASS payload 1.0.0.
- Local build from the adopted store with the new parts: 95.4 s, 665 MB; history-flag map.json 128,522 bytes raw against the 163,840 gate; data/base.json 30,861 bytes; hail.check_manifest: OK, 48,305 files (2,428 added by B6); smoke: passed (Chromium, --addresses --history).
- Branch Website run: __RUN__.

## Open for the owner
Decisions only the owner makes (docs/ROADMAP.md, "Open items for B6", items 1 to 11):
1. Bubble rule A (one bubble per cluster of houses; built; the default) or B (one per house; not built), and the below side.
2. The options sheet as DESIGN 13.6 specifies it, and its open choices (one at a time or many, the icons, the Points of interest default, the cell size wording).
3. The terrain tint and relief default: on at zooms 5 to 10, fading through zoom 12, hidden in dark mode; or off.
4. The bubble legend wording: one sentence, the D110(c) one (D135(a)); confirm or change it.
5. Landmark display names: 28 abbreviations kept as the sources give them, in 72 occurrences (St, El, Co, Mt and the rest).
6. The monthly terrain step: a 25-minute cap with --refresh-descriptions (D128(f)); confirm, or choose two monthly runs.
7. Issued-only zone counts, or every row (cancelled and upgraded rows included, as built).
8. The event number in the joins (B7).
9. The split threshold and the flag bytes: on a labelled copy four building shards are over the 250,000-byte raw threshold, all under the 100,000-byte gzip budget.
10. The NLCD wording "(public domain)" and the 3DEP and NLCD credit lines (D124).
11. The Salish name of the Flathead Reservation; businesses on the map; the top heat band; the coverage floor of the five-season pictures.

## Open for counsel
Counsel items 21 to 24 (docs/ROADMAP.md), read before the layers they cover go live:
21. Park and landmark terms: the TIGER/Line area landmark file (park points and names held), the TIGER point landmark file (a future park source), PAD-US and the FEMA places of worship list (held).
22. AirNow's Data Exchange Guidelines (an "Air quality" chip waits for that reading and for a key).
23. Forest Service terms: the boundaries layer's "read-only use" note (the forests ship with their credit line) and the hazard raster's Data Use Agreement (the hazard layer waits).
24. USGS National Hydrography Dataset terms (the water layers ship with the USGS credit line; the layer's own terms line was not read in the build).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01D7npHSU4NQFAmdz8Ep5sV7
