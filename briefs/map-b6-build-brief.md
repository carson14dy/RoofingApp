# B6 build brief, stage 2, part 1: the data products (Python, the store, the jobs)

Read first: research/map-b6/README.md in the worktree (sections 1, 2, 9), docs/DESIGN.md sections 8 to 12, AGENTS.md (rules 4, 5,
7), website/gauges.py and website/buildings.py (the module pattern: a docstring that names the source, its terms, units, missing
rules and failures; build, verify and unavailable commands; an index block; manifest entries; D16 failures and D20 unavailability),
website/hail.py (the grid: TILE 10 cells of 0.01 degree, tile_name, the store layout), website/gridded.py (palette PNG pictures on
IMAGE_BOUNDS), tools/build_basemap.py (the present base map). The worktree is /home/user/wt/wt-b6 on branch claude/map-b6 (from the
B5 head, PR 17). The adopted combined store is /home/user/hail-b5/out/combined/store (read only; chattr +i); a local build is
`python -m website.build --out DIR --hail-history --hail-addresses --hail-store STORE --now 2026-10-17T12:00:00Z` (that clock keeps
the store fresh; live feeds load). The Python environment is /home/user/hail-b1/venv/bin/python.

Rules for every builder: agents never run git write commands (the supervisor commits); edit only your own files (listed per
product) plus the tests you own; shared files (website/build.py, website/sources.py, .github/workflows/hail-store.yml,
website/templates/about.html, docs) are the integrator's in phase B, so write what they need into your product's `integration.md`
under your output folder instead; no AI model, vendor or product names in repository files; no em-dashes; sentence case; plain
words; every number with its unit; a missing input shows "Data unavailable", never a zero or an all-clear (rule 5); every source
gets a CONTRACTS row text (name, request, units, timing, missing) in integration.md; downloads go to a cache directory under
/home/user/hail-b5/out/b6/cache/<product>/ keyed so a second run reads the cache; disk is limited (keep each product's downloads
under 1 GB and delete scratch); tests are offline (fixtures small, under 200 KB per product) and skip when an optional package is
absent; `python -m unittest tests.test_<module>` must pass and the whole suite must stay green; run `python -m py_compile` on every
file you touch. Output folders: /home/user/hail-b5/out/b6/build/<product>/ (report.md, integration.md, measurements.json, logs).

Store layout for B6 (new part "base" under the store root hail/, copied by the site build like the other folders):
  hail/base/h/<z>/<x>/<y>.jpg       hillshade tiles, grey JPEG, Web Mercator, zooms 5 to 10, tiles that touch the Montana outline
  hail/base/l/<z>/<x>/<y>.png       land cover tint tiles, palette PNG with alpha, zooms 5 to 10, the same tile set
  hail/base/v/a.json                vector band A (zooms 5 to 7): one file
  hail/base/v/b/<cell>.json         band B (zooms 8 to 10): 2 by 2 degree cells, named like "n46w114" (south-west corner)
  hail/base/v/c/<cell>.json         band C (zooms 11 and 12): 1 by 1 degree cells, the same naming
  hail/base/w/<tile>.json           band D (zooms 13 and up): per B1 tile (hail.tile_name), water and park polygons and names
  hail/base/p/<tile>.json           landmark points per B1 tile, with kind, name and source
  hail/base/peaks.json              summits with elevation, ranked, with min zoom
  hail/base/places.json             places with population rank and min zoom (the present basemap places stay for the first paint)
  hail/base/index.json              the part's own index (sources, as_of, counts, bytes, the budgets measured); hail/index.json gains
                                    a "base" block that mirrors it (state, as_of, counts, sources, bytes); hail/manifest.json lists
                                    every file (hail.check_manifest must pass)
  hail/history/hail1.png, heat90.png   the five-year pictures on gridded.IMAGE_BOUNDS (palette PNG with alpha) with a sidecar
                                    hail/history/index.json (classes, colours, the legend words, as_of, bytes)
  hail/history/zones.json           per-zone counts (wind, flood) keyed by NWS zone code with the zone outline reference
  hail/recent/cells.json            cells with a radar estimate of 1 inch or more in the last 30 days (day list per cell), as_of
  hail/b/<shard>.json               gains, per outline, "k": [z17 flag, z18 flag] label anchors (1 = this outline carries the
                                    cluster bubble at that zoom) and the shard header gains "kv": the cell value text per cell key

Products (each a module under website/, a test module under tests/, a report):

P1 terrain (website/terrain.py, tests/test_terrain.py). Hillshade: USGS 3DEP ImageServer exportImage, rendering rule
"Hillshade Gray", one 256 px tile per request in EPSG:3857 (bbox from the tile's x, y, z), grey JPEG quality 80, for the tiles
that touch the Montana outline (the basemap land polygon; the research measured 805 tiles for zooms 5 to 10, about 8 MB). Land
cover: NLCD 2021 land cover through the MRLC WCS (the research notes under /home/user/hail-b5/out/b6/cartography/raster/notes.md
hold the working request form: a geographic subset in EPSG:4326 or the 3857 form that works; nearest sampling), classed into
five tint classes (forest, shrub and grass, developed, crop, water; everything else transparent) as palette PNG tiles with alpha,
the colours from the proof script /home/user/hail-b5/out/b6/cartography/render/proof_render.py (soft green forest, cream developed,
pale sage shrub and grass, blue water), zooms 5 to 10, the same tile set. The browser draws the tint under the hillshade at low
opacity, so the tiles hold colour, not a merged picture (the merge is the browser's; keep the two layers apart so either can be
off). Requests: at most 4 at a time, a 20 s timeout, three tries with a wait, a cache keyed by z, x, y and the source's as-of month;
a tile that fails after three tries is recorded in the index as missing (the browser shows the paper colour there) and never
blocks the pack. Verify: every listed tile is a valid image of 256 px; the count and bytes match the index; a random sample of 10
tiles re-fetched matches byte for byte or within a stated tolerance for JPEG. Measurements: tiles, bytes per zoom, total, the
run time; a budget line: zooms 5 to 10 under 20 MB in total. Commands: build --store DIR [--cache DIR] [--zooms 5-10] [--only h|l],
verify --store DIR, unavailable --store DIR --reason TEXT. Terms in the docstring: USGS 3DEP (public domain, credit "3DEP data
courtesy of the U.S. Geological Survey"; the service copyright line), MRLC NLCD ("public domain information", Fees NONE).

P2 areas, water, places and peaks (website/basemap2.py, tests/test_basemap2.py). Sources (verified in stage 1; URLs in
research/map-b6/README.md section 9 and the notes under /home/user/hail-b5/out/b6/cartography/vector/ and
/home/user/hail-b5/out/b6/landmarks/): Census TIGER/Line 2026 AIANNH (the 7 Montana reservations), the Forest Service
administrative forest boundaries (the 7 forests; through the EDW map service query or the national zip), PAD-US 4.1 Fee layer by
its map service (state parks and recreation areas, national park land; local parks go to band D), the USGS NHD map service
(small-scale flowlines and waterbodies with gnis_name for bands A to C; large-scale per tile for band D), TIGER 2026 places with
the 2020 counts (places.json: name, lat, lon, population, min_zoom by the rule: 50,000 and up zoom 5; 10,000 zoom 7; 2,000 zoom 8;
500 zoom 9; the rest zoom 10; the present basemap places keep their min_zoom), GNIS Montana summits with the elevation sampled from
3DEP (getSamples, batched; feet and metres; peaks.json ranked by elevation with a 25 km spacing rule for min zoom 8, 10 km for
zoom 10, the rest zoom 12), route numbers from TIGER primary and secondary roads (full names such as "US Hwy 12", "State Hwy 200",
"I- 90") written as shield refs on the band files' road lines (band A and B carry only interstate, US and state routes;
local roads stay in hail/r/ as B3 built them). Geometry: Web Mercator or WGS 84 coordinates rounded to 5 decimals, Douglas-Peucker
simplified per band (band A 500 m, band B 150 m, band C 50 m, band D none), polygons as rings, lines as paths, names as given
(TIGER abbreviations expanded by a table: Riv to River, Crk to Creek, Lk to Lake, Mtn to Mountain, Natl to National). Each feature
carries kind (reservation, forest, park, river, lake, place, peak, route), name, and for areas a label point (the pole of
inaccessibility, computed in Python) and a min zoom. Budgets (gzip): band A under 150,000 bytes; each band B file under 100,000;
each band C file under 60,000; each band D shard under 30,000; measured and listed in the index. Verify: counts per kind, every
named reservation and forest present, Clark Fork and Bitterroot River present with their names, Lolo and Frenchtown in places.json,
McDonald Peak in peaks.json with an elevation within 30 m of a published figure cited in the test. Commands as P1.

P3 landmarks (website/landmarks.py, tests/test_landmarks.py). Kinds and sources: school (NCES EDGE public 2024-25 and private
2023-24 layers, public domain), hospital (the USGS National Map structures layer where it carries hospitals, else the HIFLD copy of
the state licensure list with its terms noted as unconfirmed; the builder reports which is used and why), airport (FAA NASR APT
file or its HIFLD copy; public-use airports only), church (the FEMA copy of the IRS-based places-of-worship layer, point-address
rows only; the geocoder's terms are a counsel question, so this kind is built but marked "held" in the index until the owner
clears it), fire station (USGS National Map structures), park (PAD-US local parks and TIGER area landmark parks, as points at
the label point for the chip, with the polygon in band D from P2). Output: hail/base/p/<tile>.json per B1 tile: {"f":
"hail-landmarks-v1", "t": tile, "n": count, "i": [[lon, lat, kind, name, source_key], ...]} with the kinds as short codes
documented in the module; an index block with counts per kind and per source, the held flag per kind, and the as_of per source.
Every row keeps only name, kind, position and source; no owner, no contact, no attribute beyond those (decision 6 spirit).
Verify: counts recomputed from the files; the Missoula tile holds Loyola Sacred Heart High School, Hellgate High School, Missoula
Montana Airport, Community Medical Center and St Patrick Hospital. Budget: each shard under 20,000 bytes gzip.

P4 the five-year pictures, the zone counts, the recent radar hail cells and the bubble anchors (website/history_layers.py,
website/labels.py, tests/test_history_layers.py, tests/test_labels.py). (a) hail1.png: days with a radar estimate of 1 inch (254
tenths of a mm) or more per cell over the five seasons, from hail/t/ (the rule in website/summary.py for the radar_1in row), four
classes (1, 2, 3 to 5, 6 and up; a cell with no such day is transparent, and the legend says transparent is not "no hail"), on
gridded.IMAGE_BOUNDS at the native cell size; heat90.png: days at or above 90 F over the five seasons from hail/c/ (the climate
grid's record index for 90 F days; bands of 25 days). (b) zones.json: per NWS public forecast zone the counts of high wind
warnings, high wind watches, wind advisories, flood watches, flood warnings and advisories from hail/z/ and hail/j/events.json
(the joins' rows), with the lag date the index gives; the zone outlines come from the Iowa State zone file the research measured
(475 KB) simplified at 150 m into hail/base/v/zones.json with the zone code and name. (c) recent/cells.json: for every cell with
a radar value of 254 tenths or more on any day in the last 30 days before as_of, the list of those days; as_of from the store; a
sentence in the index when the store is older than 3 days. (d) labels.py: the bubble anchors. For zoom 17 and zoom 18, in pixel
space of each zoom, cluster the outlines of a shard that sit in the same radar cell when they lie within 56 px of the cluster's
first outline (the stage 1 rule; /home/user/hail-b5/out/b6/design/bubbles/ holds the measured script to mirror), choose the
outline nearest the cluster's middle as the anchor, and place bubbles greedily (by value descending then position) skipping any
that would overlap a placed one by more than 2 px; write k flags into each outline and kv (the cell value text, "0.39 in" or
"Data unavailable" for the shard header, the browser prints "--" for the bubble glyph) into the shard header; rewrite the manifest
entries. The value text is the cell's largest radar estimate over the five seasons from hail/t/, two decimals, or Data unavailable
when nothing of 64 tenths or more is stored. Deterministic: the same input gives the same flags (a test runs it twice). Report
the statewide counts (anchors per zoom, outlines covered, run time) and the bytes added per shard. Verify: a sample of shards
re-checked; no outline flagged at a zoom where its cluster has another flagged outline within 2 px overlap.

Phase B integrator (one agent, after P1 to P4): website/build.py (the base part in the store copy list; the map.json blocks
"base" (tile URL templates, zooms, bands, the sources' credit lines, the as_of), "history_layers", "recent" and "landmarks" with
their words; the budget keys), website/sources.py (CONTRACTS rows from each integration.md), .github/workflows/hail-store.yml
(the monthly job runs P1 and P2 (the big downloads) and the daily job runs P3, P4 and the label pass after the outlines, all
non-fatal on the B5 clock with their verify steps and unavailable marks, mirroring the gauges and buildings steps), the About
page sentences (each source and its credit line; what a chip shows; the held church kind), docs/DECISIONS.md D107 to D110 as
recorded in the supervisor's brief (the integrator receives the text), docs/ROADMAP.md and DESIGN.md section 13 (the sheet, the
bubbles, the base map), and the tests that pin the copy list, the map.json keys and the words. Then a local build from the
adopted store with the new parts (P1 and P2 run against the cache; the tiles for zooms 5 to 10 take minutes) and the smoke with
every layer on; the budgets measured and written into the record.
