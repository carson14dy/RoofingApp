# Hail history B5 brief: the past weather of every location (temperature highs and lows, rain and snow by year, flooding, ice, heat, wind, and the weather that matters for a roof)

Owner request (2026-10-19): "find the history of the locations past weather reports like the size of hail, wind, storm
history, temperature highs and lows, Snow amounts annually, Rain annually, any flooding, and weather that would be an issue
for a roof as well." Owner decisions (D34): 1 (trailing five years), 2 and 6 (a history at every address), 4 (recent and
consistent), 5 (units read and made understandable), 7 (follow the laws). Product north star: one map, one sheet per place
that leads with a plain summary; details behind headings in a fixed order; every number next to its unit and kind word.
B5 builds on B3 (branch claude/hail-b3). Research records: /home/user/wt/research-b35/ (temperature-rain-grid, snow-stations,
snow-alternatives, temperature-alternatives, flood-ice-heat-products, river-flood-gauges, roof-indicators, montana-events-
2020-2026, legal-terms-review, volume-and-job-budget, and their refuter files). Hail (B1, B2), addresses, streets and
shapes (B3) exist; B5 adds the rest of the history and the summary that leads the sheet.

## Sources (verified live by the research; quote the terms exactly as the records give them)
1. **Daily temperature and rain grid: NOAA nClimGrid-Daily** (AWS bucket noaa-nclimgrid-daily-pds, access/grids/YYYY/
   ncdd-YYYYMM-grd-scaled.nc; variables prcp, tmax, tmin; 1/24 degree; 25,902 Montana land cells; file attribute
   "license = no restrictions"; the registry asks for attribution). Scaled months appear 4 to 68 days after month end
   (median 66); prelim files cover newer days. Backfill once from 60 scaled months (3.55 GB in all; 57 MB a month, read with
   h5py) into per-cell monthly aggregates; monthly update when a new scaled file appears; daily update from the new prelim
   days by Range reads (about 1.4 MB a day). Never sum the -999.99 fill. Every value is a grid estimate about 4.6 km across,
   not a reading at the address (Billings: the grid differed from the airport by 18.8 mm in July 2025 and 1.0 C on one day).
   Not used: PRISM (Oregon State keeps ownership), Daymet (licence unconfirmed), gridMET (only as a later supplement with
   PRISM attribution; not in B5).
2. **Season snowfall grid: NOHRSC National Snow Analysis season-total snowfall GeoTIFF** (one file per water year, 0.04
   degree, about 2.4 MB each; 2021-22 to 2025-26 present, 11.6 MB in all; 2020-21 missing upstream). Units are not printed
   in the file: B5 confirms inches by comparing the Billings centre cell (2024-25 read 50.29) against the airport's GHCN
   season total (64.3 in) and the NOHRSC legend, and records the check; if the check fails the product is left out and the
   words say so. Terms: the NWS public-domain statement with its three conditions (no claim of ownership, no implied
   endorsement, no altered content presented as official) and the 17 U.S.C. 403 notice. An analysis, not a measurement.
3. **Stations: GHCN-Daily from NCEI** (https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/<ID>.dly; the S3 by_station
   copies are stale for SNOTEL and airport stations, so the .dly files are the source). Elements TMAX, TMIN (tenths of C),
   PRCP (tenths of mm), SNOW and SNWD (mm), with the quality flags honoured. 481 Montana stations have a 2025 record
   (392 MB in all; the two-nearest-per-element set for all town and tile centres is computed first and only those files
   are pulled; about 34 MB for the 45 candidates of two sample points). Station rule per element and location: candidates
   within 40 miles with a report in the last 30 days; coverage at least 80 percent of the days 2020 to 2025 with an
   unflagged value; the two nearest that pass; fewer than two: show those that pass and say so; none: say no station
   qualifies. Season values show only when at least 95 percent of the season's days have the element. Never fill a gap
   with zero. A station reading is at the station; the distance is shown.
4. **Flood, winter, heat and wind products, extending B2's machinery** (IEM watchwarn archive; terms: public domain, "may
   be used freely by anyone for any lawful purpose", attribution appreciated). Polygon path (like SV, TO, FF): FL.W (flood
   warning, 43 events in window), FA.W (37), FA.Y (548), FL.A (35), FL.Y (10), SQ.W (snow squall, 78). Zone path (like
   HW.W): WW.Y (865), WS.A (226), HW.A (277), HT.Y (58), EH.W (4), EH.A (3), FR.Y (14), FZ.W (4), DU.Y (3). County path
   (new: a Montana county boundary file from Census TIGER 2026 counties, public domain): FA.A and FF.A county-only events
   (18 and 2). Zone products carry few NEW rows (WS.W 4 of 313): the begin is the earliest utc_issue (B2's D25). Event-
   number re-use: periods per B2's D33 (a CAN, UPG or EXP closes a period; a later NEW, CON, EXT, EXA or EXB opens the
   next; each period is a span). No tags in these products except FF.W and SQ.W damage threat tags, shown as NWS tag labels.
5. **NCEI Storm Events, extending B2**: county-coded point rows of Flood (76), Flash Flood (60), Heavy Rain (144), Tornado
   (17), Funnel Cloud (35), Lightning (8) and Debris Flow (11) join as records within 5 miles like hail; the FLOOD_CAUSE
   field is shown as written ("Heavy Rain / Snow Melt", "Ice Jam"); zone-coded Heavy Snow, Winter Storm, Winter Weather,
   Blizzard, Ice Storm, Extreme Cold/Wind Chill, Cold/Wind Chill, Frost/Freeze, Excessive Heat, Heat join by zone as B2's
   zone records do. BEGIN times are MST-7 on every Montana row (confirmed).
6. **IEM local storm reports, extending B2**: FLASH FLOOD, FLOOD, HEAVY RAIN and RAIN (the label changed in 2023), FREEZING
   RAIN, HEAVY SNOW and SNOW (changed in 2023), BLIZZARD, EXTREME COLD and WIND CHILL (label changed in 2024), EXTREME HEAT,
   LIGHTNING, NON-TSTM WND GST and NON-TSTM WND DMG. Magnitude units for codes 5, 6, 7, I and J are unverified: those
   magnitudes are not shown until the IEM documentation confirms them (the remark text is shown as written).
7. **River gauges (narrow): NWS NWPS and USGS** (api.waterdata.usgs.gov; waterservices.usgs.gov is retired in 2027): for
   the nearest gauge with an NWS flood stage within 10 miles (17.3 percent of Montana; 12 of 14 towns), the flood
   categories (action, minor, moderate, major, in feet) and the USGS annual peak stage by water year (97 series keyed by USGS
   number; 207 KB raw for all). Words: "River flood record at the {name} gauge, {miles} miles away; it does not say water
   reached this address." Daily flood-day counts are out (no daily stage series). Terms: US government works; the NWS
   conditions; USGS credit. The owner confirms the 10-mile cut-off (alternatives 25 miles, 69.6 percent; 5 miles, 4.8).
8. **Not in B5**: FEMA flood zones (a hazard and insurance designation, not a weather event; AGENTS rule 5; owner and
   counsel first), lightning strike data (commercial), UV and sunlight, roof surface temperature, ponding (no public data):
   each gets a "Data unavailable" line that says why, per the roof-indicators record.

## Product
- **The sheet leads with a summary** (north star): under the address line, a five-season table (July to June, 2021-22 to
  2025-26) with one row per indicator, every cell a number with its unit, every row a kind word: hail days by size class
  and the largest hail (radar estimate; B1), reports and warnings in the area (B2 counts), peak gust days and the strongest
  gust at the nearest station (station reading), freeze-thaw days and days with a low below 32 F (grid estimate), days at
  or above 90 F and the highest temperature (grid estimate), rain total and the largest one-day rain (grid estimate),
  snowfall for the season (NOHRSC grid, inches) and the deepest snow at the nearest station (station reading), flood
  warnings and reports in the area (official alert, report), freezing rain and ice products and reports, snow and winter
  storm products. A cell with no data reads "Data unavailable" with the reason behind a heading, never zero.
- **Details behind headings in a fixed order**: hail; wind; storms and warnings (B2's six sections, now with the new
  phenomena); temperature (grid: records and counts by year; station rows where coverage passes); rain (grid totals by
  calendar and water year; largest day); snow (NOHRSC season totals; station season totals and deepest snow); flooding
  (products, records, reports, the river gauge line); ice and winter (freezing rain reports, ice storm and winter products);
  heat (heat products, days at or above 90 F); "Weather that matters for a roof" (the indicator lines with their kind words
  and one reference line per stressor from the roof-indicators record; the four Data unavailable lines).
- **Town pages** carry the same table and sections; the About page the sources, terms and caveats (grid estimate versus
  station reading; an analysis is not a measurement).
- **Words**: every sentence and template in Python (WORDS_CLIMATE, WORDS_INDICATORS, additions to WORDS_JOINS); the kind
  words grid estimate, station reading, radar estimate, report, record, official alert, analysis; "an estimate at the grid
  cell, about 4.6 km across, not a reading at this address"; the strict freeze-thaw rule stated ("days with a high above
  32 F and a low below 32 F"); "50 knots (58 mph)" as the NWS words; no damage, risk, probability, insurance, eligibility,
  all-clear; forbidden terms added per the roof-indicators record; "Data unavailable" with the reason.

## Rules fixed by the supervisor (D1 to D10 of this brief)
- D1 Thresholds on the unrounded converted grid values: freeze-thaw day = tmax above 0 C and tmin below 0 C; a day at or
  above 90 F = tmax at or above 32.222 C; a low below 32 F = tmin below 0 C; stated on the page once.
- D2 Per-cell monthly aggregates are the store's unit (rain total, rain max and its day, tmax max and day, tmin min and day,
  the three day counts, missing days); seasons and calendar and water years are sums of months; a month with missing days
  carries its count and the page says "n days missing".
- D3 Store layout: `hail/c/<tile>.json` one record per 1/24-degree cell in the tile (integers: hundredths of an inch,
  tenths of F, yyyymmdd), `hail/n/<tile>.json` the NOHRSC season values per 0.04-degree cell, `hail/s/<id>.json` extended
  with the station's daily elements for the window (or a sibling file `hail/sd/<id>.json`), `hail/g/<usgs>.json` the gauge
  table, the B2 files extended with the new phenomena, index.json blocks "climate", "snow", "stations", "gauges" with
  states, counts, sizes and sources; manifest entries for all.
- D4 Every cell lookup goes through website.hail.cell_for; the climate grid has its own cell function with the same
  half-open rule; the gates probe with those functions, never with their own arithmetic.
- D5 The job: a backfill step (once; cached aggregates kept as a release asset), a daily step (prelim days, station files
  of the candidate set, the new products, the gauge peaks), a monthly step (the new scaled month, the NOHRSC season file,
  the address and shape files per B3). Each step non-fatal per B3's D20. Budget measured and recorded.
- D6 The river gauge line waits behind the same counsel gate as the address layers (per-address output); the town pages
  may show it first.
- D7 The B2 period rule (B2's D33) is implemented here for every zone product, with tests on the four named cases.
- D8 B2's D34 hand-off: the NCEI point types and the flood products named there are joined here.
- D9 NOHRSC units: confirmed by the Billings check and the legend before display; else the product stays out and the snow
  section shows station seasons only.
- D10 Nothing in B5 states or implies damage, loss, a claim, coverage, or an all-clear. The roof section's lines are counts
  and measurements with kind words and one reference sentence per stressor quoting a public source.

## Gates (B5-1 to B5-10)
1. Grid: the Billings cell's 2025 calendar precipitation, the June 15, 2025 tmax and tmin, and the 2024-25 freeze-thaw days
   reproduce from an independent h5py read of the monthly files (0 difference); the airport station figures are shown as
   the comparison (GHCN 73 freeze-thaw days in calendar 2025; the grid value recorded).
2. Snow: the NOHRSC Billings cell against the airport season total with the unit check recorded; five seasons present.
3. Stations: the rule picks the right two stations at Billings (the airport and one more) and at Benchland (Stanford
   passes; Moccasin fails coverage and the page says so); no zero fills.
4. Products: FL.W 43, FA.W 37, FA.Y 548, SQ.W 78, WW.Y 865 events in the window (as the research counted); the June 2022
   flood shows FL.W and FA.W products over Red Lodge, Gardiner and Billings, the NCEI flood records and the Billings gauge's
   2022 peak (16.37 ft on 2022-06-15); the period rule on the four named zones.
5. NCEI points: the 17 tornado and 60 flash flood rows join as records; the Hays tornado (2021-07-07) is found at its
   point.
6. Readability: a reviewer reads the summary table of three places (the gate cell, Benchland, Billings) and finds every
   cell has a unit and a kind word and no sentence needs decoding; the sheet opens with the table within one screen at
   390 px.
7. Words: the forbidden-term check passes over every new word; the four Data unavailable lines present with reasons.
8. Flag-off and --hail-history-only builds unchanged; the B3 flag build unchanged by B5 except the new sections.
9. Chromium smoke at 390 and 1280 px; smoke_pages; the live preview.
10. Deterministic builds; the job's steps run locally end to end; the budget measured against the research's limits.

## Ownership (worktree /home/user/wt/wt-b5, branch claude/hail-b5 from claude/hail-b3's head)
- Builder 1 (climate grid): `website/climate.py` (nClimGrid reader with h5py, aggregates, tiles, words, verify, CLI,
  backfill and update steps), `tests/test_climate.py`.
- Builder 2 (snow and stations and gauges): `website/snowgrid.py` (NOHRSC), `website/stations.py` (GHCN .dly reader, the
  station rule, seasons), `website/gauges.py` (NWPS and USGS), their tests.
- Builder 3 (products): the B2 extensions in `website/joins.py` (the new phenomena by path, the county path, the period
  rule, the NCEI point types, the LSR types), `tests/test_joins.py`, the county boundary file reader.
- Builder 4 (summary and site): `website/summary.py` (the five-season table from every store, the roof indicator lines,
  WORDS_INDICATORS), `website/build.py`, `website/sources.py` (rows), templates, `tests/test_site.py`, `tools/smoke_map.py`,
  `.github/workflows/website.yml`.
- Builder 5 (browser): `website/static/map/map.js`, `map.css` (the summary table and the new sections in the sheet).
- Builder 6 (docs): D37, DESIGN section 11, ROADMAP, README, AGENTS, b5-verification.json, the job `.github/workflows/
  hail-store.yml` steps with the budget.
Same rules as B2 and B3: nobody commits or pushes; scratch under /home/user/hail-b5/out/<name>/; tests delete only what
they made; the skeptic rule with defect_real.

## Supervisor staging notes (2026-10-19 05:15 UTC)
- Caches under /home/user/hail-b5/cache/: nohrsc/ (the five season files 2021-22 to 2025-26, 12 UTC names), ghcn/
  (ghcnd-stations.txt, ghcnd-inventory.txt), counties/ (tl_2026_us_county.zip, 83,378,454 B, valid). The nClimGrid months
  are not staged (the climate builder streams them).
- The NOHRSC GeoTIFFs open with Pillow (a site dependency already): mode F, LZW, tags 33550 (0.04, 0.04) and 33922
  (corner -126.0 E, 55.0 N), no-data under -9000; the research values reproduce exactly (Billings row 230 col 437:
  50.29 for 2024-25 and 33.85 for 2025-26; Benchland row 198 col 399: 87.17 and 94.05). The unit check of D9 still
  applies before display.
