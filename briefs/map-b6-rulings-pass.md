# B6 stage 2 part 1: the supervisor rulings pass over P1 to P4 (D112 to D115)

One fixer and one checker per product, after the review, refute, fix and check rounds of the build workflows. The fixer
applies the items below to its product's module, tests and fixtures only (listed per product); the checker is read-only
and verifies each item with evidence (a line, a test name, a command's output). Rules for both: never run git write
commands; edit no shared file (website/build.py, website/sources.py, the workflows, about.html, docs are the integrator's;
write what they need into the product's integration.md under /home/user/hail-b5/out/b6/build/<product>/); no AI model,
vendor or product names in repository files; no em-dashes; sentence case; plain words; a missing input shows "Data
unavailable", never a zero or an all-clear (rule 5); every credit line reads "Source: ..." or "... data courtesy of ..."
and never implies endorsement (D113(a)); run `python -m py_compile` on every file touched and `python -m unittest
tests.test_<module> -v` (the Python is /home/user/hail-b1/venv/bin/python); the worktree is /home/user/wt/wt-b6. An item
that is already so is reported as "already so" with the line; an item the fixer judges wrong for the code is reported as
"not applied" with the reason for the supervisor, never silently skipped.

## P1 terrain (website/terrain.py, tests/test_terrain.py, tests/fixtures/terrain/)
- P1-R1 (D112(a)) Wetlands: NLCD codes 90 and 95 take the shrub-and-grass tint class (the module's TINT table and the
  docstring's class list; today line 39 lists them as transparent). Barren (31, 32) stays transparent; pasture (81) stays
  with crop; the four developed codes stay one shade. A test asserts the class of 90 and 95.
- P1-R2 (D112(b)) The request timeout: the module's default may stay 20 s, but the docstring and the integration notes say
  the monthly job passes --timeout 60 (two zoom 5 land cover tiles take up to 30 s); --timeout must accept 60 (it does,
  5 to 120). Already so if the words are there; report the lines.
- P1-R3 (D112(c), D115(d)) Credit lines, exact words, in SOURCES and in the words the browser prints: land cover "Land
  cover: National Land Cover Database 2021, U.S. Geological Survey and the Multi-Resolution Land Characteristics Consortium
  (public domain)"; relief "Relief: 3DEP data courtesy of the U.S. Geological Survey". The terms note records that the
  NLCD 2021 data release carries a CC0 1.0 licence (public domain) beside the MRLC "public domain information" line.
- P1-R4 (D112(m)) Cache pruning: the build prunes the download cache to the newest as-of month (older month folders are
  deleted after a successful build; a test with two month folders shows the old one gone), and no body that fails the
  content check is ever written to the cache (already so per the docstring; the checker finds the line).
- P1-R5 (D115(b)) The tint and relief palettes are named Python constants (TINT is one; the hillshade's grey treatment,
  if any constant applies, is named too) and the integration.md lists them for DESIGN.md with their hex values and class
  names so the integrator can copy the table.
- P1-R6 (D115(a), D115(g)) integration.md states for the browser: the tint and relief draw at zooms 5 to 10 and fade
  through 11 and 12, off at 13; hidden in dark mode; the default is on; the owner can veto.

## P2 areas, water, places and peaks (website/basemap2.py, tests/test_basemap2.py, tests/fixtures/basemap2/)
- P2-R1 (D114(a)) Band D is optional: the index block says how many tiles are built and how many are not
  (tiles_built, tiles_unbuilt, the failed cells), a missing shard is documented as "not built, the browser draws band C's
  water there" in the docstring and integration.md, and a second run with the same cache fetches only the cells that failed
  (resume). A test shows the resume: a first build with one failing cell, a second build where that cell answers, the
  count rises and nothing else is re-fetched.
- P2-R2 (D114(c)) --deadline-at stops band D cleanly (the cells reached are kept, the rest are listed as unbuilt with the
  reason "deadline"); the integration notes say the monthly job's step cap is 20 minutes and the cache carries the rest.
- P2-R3 (D114(b), D115(d)) Credit lines: "Forest boundaries: USDA Forest Service" (today the CREDIT tuple reads "Source:
  U.S. Forest Service, Forest System Boundaries (national forests)": change the party to "USDA Forest Service" and keep the
  "Source: ..." form, so "Source: USDA Forest Service, forest boundaries (national forests)."); the NHD line credits
  "U.S. Geological Survey, National Hydrography Dataset"; TIGER credits "U.S. Census Bureau"; the terms note says the
  Forest Service "read-only use" sentence is a usage note on a federal work (public domain, 17 U.S.C. 105) and that
  counsel sees it as item 23 and the NHD terms as item 24.
- P2-R4 (D115(e)) The reservation outlines come from the full-resolution TIGER/Line AIANNH file (tl_2026_us_aiannh.zip,
  already so) at every zoom; the docstring says the 1:500,000 cartographic file is never used. Report the line.
- P2-R5 (D115(f)) Shields: only interstate, US and state routes carry a shield text; route-like local names ("FAS 533",
  "W US Hwy 12") carry none; a test asserts "FAS 533" gives no shield.
- P2-R6 (D112(m)) Cache pruning: the cache keeps the newest cycle of each source (TIGER 2026 files, the EDW, PAD-US and
  NHD pages, the PL file) and deletes older ones after a successful build; a failed or unexpected body is never cached.
- P2-R7 (P1-14, the shared base index) hail/base/index.json is one document shared by P1, P2 and P3: a writer that starts a
  new document gives it "f": "hail-base-index-v1" (the key and value terrain.py uses; basemap2.py today starts it with
  "format"), every writer keeps the other products' blocks and writes only its own keys, and a document whose "f" differs is
  reported as a failure of this product, never discarded. A test writes the three blocks in each order and shows all three
  survive.

## P3 landmarks (website/landmarks.py, tests/test_landmarks.py, tests/fixtures/landmarks/)
- P3-R1 (D112(g)) The FAA fixture tests/fixtures/landmarks/faa_apt_mt_sample.txt carries owner names, owner and manager
  addresses and phone numbers. Rewrite it so every column the module does not read is blank (spaces of the same width, so
  the fixed-width offsets hold); the module reads only the record type, the site number, the facility type, the state, the
  city, the facility name, the ownership and use codes and the position. Check sources_sample.json the same way (keep only
  the attributes the module reads: names, positions, status, state, kind codes; drop any address, phone, contact or owner
  attribute) and the TIGER sample (shapefile fields: only STATEFP, MTFCC, FULLNAME, INTPTLAT, INTPTLON needed; a zip with
  other fields may stay if none is an owner, address or phone). A test asserts no fixture line matches a phone pattern
  ([0-9]{3}-[0-9]{3}-[0-9]{4}) or the words OWNER, MANAGER, PHONE, CONTACT, EMAIL outside the module's own column names.
- P3-R2 (D112(f)) The fire kind's label is "Fire and EMS stations" (KIND_LABEL "fire", today "Fire stations") and the plural
  words "fire and EMS stations"; the words in WORDS follow.
- P3-R3 (D112(e)) Park names: where a TIGER park point and a PAD-US polygon are the same park, the PAD-US name stands and the
  TIGER name is kept as an alternate for the search: an optional sixth element on that row (the alternate name) documented
  in the module's row format; absent on every other row. See P3-R4 for when it is written.
- P3-R4 (D115 intro) TIGER area landmarks are held: the TIGER area landmark file's own use constraints are read by counsel
  before any text from it ships. Add a held-sources rule beside the held-kinds rule: rows from source "tiger_park" and the
  alternate names of P3-R3 are built and counted but never written to the store while held; PAD-US park rows ship. The
  index's "held" block lists kinds and sources with state and reason and count null (D118(b): no number derived from a held
  source is published; the figures stay in report.md); integration.md says the About sentence.
- P3-R5 (D113(a)) Every credit line in SOURCES reads "Source: ..." (today the USGS fire line reads "USGS The National Map,
  fire and EMS stations, October 2026 refresh." and others vary): one form for all, no endorsement words.
- P3-R6 (D112(h)) Zero is never a count for an unavailable kind: the index gives "Data unavailable" words and the reason
  (already so per WORDS kind_unavailable; the checker confirms the index block carries null, not 0, for the count).
- P3-R7 (D112(m)) Cache pruning: the cache keeps the newest cycle per source and deletes older cycles after a successful
  build; a failed body is never cached.
- P3-R8 (P1-14, the shared base index) landmarks.py writes its block into hail/base/index.json without the "f" key: a writer
  that starts a new document gives it "f": "hail-base-index-v1", keeps the other products' blocks and writes only its own
  keys; a document whose "f" differs is reported as a failure of this product, never discarded. A test shows the terrain and
  basemap blocks survive a landmarks write and the reverse.

## P4 pictures, zones, recent cells and anchors (website/history_layers.py, website/labels.py, tests/test_history_layers.py,
## tests/test_labels.py, tests/fixtures/history_layers/, tests/fixtures/labels/)
- P4-R1 (D112(i)) Eight zone measures: flash flood watches (FF.A) and flash flood warnings (FF.W) are counted as their own
  two measures beside the six (high wind warnings, high wind watches, wind advisories, flood watches, flood warnings,
  flood advisories); the docstring sentence "Flash flood products are not among the six counts" goes; the legend words and
  the measures list follow; the fixture gains one flash flood row of each so the test counts them.
- P4-R2 (D113(d)) Words: "The newest warning in these counts is dated {date}" stands; the word "lag" appears in no printed
  word; the index key "lag" is renamed "newest_warning" ({"date": ..., "words": ...}) and integration.md says so for the
  map.json block; tests follow.
- P4-R3 (D112(k)) Heat bands: six bands of 25 days with "125 days or more" as the top band (already so; report the line).
- P4-R4 (D112(j)) labels.py: the cluster radius is the measured width of "0.38 in" (55.75 px; already so), the bubble glyph
  "--" and the kv text "Data unavailable" (already so); integration.md states the accepted figures (4.75 percent of
  outlines at zoom 17 and 1.22 percent at zoom 18 skipped for overlap; 36 shards over the 250,000-byte raw split threshold,
  every shard under the 100,000-byte gzip budget, largest 45,053) and that the threshold is not changed in this stage.
- P4-R5 (D112(h)) A zone whose product file is absent shows null ("Data unavailable") for its measures, never 0 (already so
  per the docstring; the checker confirms with the test).
- P4-R6 (D112(m)) The zone outline download (the ugcs snapshot) is cached by its valid date and the SHA-256 is checked
  before the file is written; an unexpected body is never cached (confirm).
