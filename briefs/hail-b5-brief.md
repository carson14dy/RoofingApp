# Hail history B5 brief: the past weather of every location (temperature highs and lows, rain and snow by year, flooding, ice, heat, wind, and the weather that matters for a roof)

Owner request (2026-10-19): "find the history of the locations past weather reports like the size of hail, wind, storm
history, temperature highs and lows, Snow amounts annually, Rain annually, any flooding, and weather that would be an issue
for a roof as well." Owner decisions (D34): 1 (trailing five years), 2 and 6 (a history at every address), 4 (recent and
consistent), 5 (units read and made understandable), 7 (follow the laws). Product north star: one map, one sheet per place
that leads with a plain summary; details behind headings in a fixed order; every number next to its unit and kind word.
B5's data modules build on B2's head (db84d76, branch claude/hail-b5 in /home/user/wt/wt-b5); its site side builds on the B3 site build once that lands. Research records: /home/user/wt/research-b35/ (temperature-rain-grid, snow-stations,
snow-alternatives, temperature-alternatives, flood-ice-heat-products, river-flood-gauges, roof-indicators, montana-events-
2020-2026, legal-terms-review, volume-and-job-budget, and their refuter files). Hail (B1, B2), addresses, streets and
shapes (B3) exist; B5 adds the rest of the history and the summary that leads the sheet.

## Sources (verified live by the research; quote the terms exactly as the records give them)
1. **Daily temperature and rain grid: NOAA nClimGrid-Daily** (AWS bucket noaa-nclimgrid-daily-pds, access/grids/YYYY/
   ncdd-YYYYMM-grd-scaled.nc; variables prcp, tmax, tmin; 1/24 degree; 25,902 Montana land cells; file attribute
   "license = no restrictions"; the registry asks for attribution). Scaled months appear 4 to 68 days after month end
   (median 66); prelim files cover newer days. Backfill once from 63 scaled months, July 2021 to September 2026 (3.6 GB whole, about 2.6 GB when the three
   variables are read by Range; 57 MB a month, read with h5py; keep no month file once its aggregates are written) into per-cell monthly aggregates; monthly update when a new scaled file appears; daily update from the new prelim
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
   are pulled; about 27.7 MB for the 42 candidates of two sample points). Station rule per element and location: candidates
   within 40 miles with a report in the last 30 days; coverage at least 80 percent of the days 2020 to 2025 with an
   unflagged value; the two nearest that pass; fewer than two: show those that pass and say so; none: say no station
   qualifies. Season values show only when at least 95 percent of the season's days have the element. Never fill a gap
   with zero. A station reading is at the station; the distance is shown.
4. **Flood, winter, heat and wind products, extending B2's machinery** (IEM watchwarn archive; terms: public domain, "may
   be used freely by anyone for any lawful purpose", attribution appreciated). Polygon path (like SV, TO, FF): FL.W (flood
   warning, 43 events in window), FA.W (37), FA.Y (548), FL.A (35), FL.Y (10), SQ.W (snow squall, 78). Zone path (like
   HW.W): WW.Y (865), WS.A (226), HW.A (277), HT.Y (58), EH.W (4), EH.A (3), FR.Y (14), FZ.W (4), DU.Y (3). County path
   (new: a Montana county boundary file from Census TIGER 2026 counties, under the Census statement that its work is not copyrighted, with the acknowledgement): FA.A and FF.A county-only events
   (18 and 2). Zone products carry few NEW rows (WS.W 4 of 313): the begin is the earliest utc_issue (B2's D25). Event-
   number re-use: periods per B2's D33 (a CAN, UPG or EXP closes a period; a later NEW, CON, EXT, EXA or EXB opens the
   next; each period is a span). No tags in these products except FF.W and SQ.W damage threat tags, shown as NWS tag labels.
5. **NCEI Storm Events, extending B2**: county-coded point rows of Flood (76), Flash Flood (60), Heavy Rain (144), Tornado
   (17), Funnel Cloud (35), Lightning (8) and Debris Flow (11) (351 rows; counts are 2020 to 2026 totals as the research
   counted them, so the window counts are smaller) join as records within 5 miles like hail; the FLOOD_CAUSE
   field is shown as written ("Heavy Rain / Snow Melt", "Ice Jam"); zone-coded Heavy Snow, Winter Storm, Winter Weather,
   Blizzard, Ice Storm, Extreme Cold/Wind Chill, Cold/Wind Chill, Frost/Freeze, Excessive Heat, Heat join by zone as B2's
   zone records do. BEGIN times are MST-7 on every Montana row (confirmed).
6. **IEM local storm reports, extending B2**: FLASH FLOOD, FLOOD, HEAVY RAIN and RAIN (the label changed in 2023), FREEZING
   RAIN, HEAVY SNOW and SNOW (changed in 2023), BLIZZARD, EXTREME COLD and WIND CHILL (the type words changed over the window; the code keeps a dated table and shows the word the report carries), EXTREME HEAT,
   LIGHTNING, NON-TSTM WND GST and NON-TSTM WND DMG. Magnitude units for codes 5, 6, 7, I and J are unverified: those
   magnitudes are not shown until the IEM documentation confirms them (the remark text is shown as written).
7. **River gauges (narrow): NWS NWPS and USGS** (api.waterdata.usgs.gov; waterservices.usgs.gov is retired in 2027): for
   the nearest gauge with an NWS flood stage within 10 miles (17.3 percent of Montana; 12 of 14 towns), the flood
   categories (action, minor, moderate, major, in feet) and the USGS annual peak stage by water year (97 series keyed by USGS
   number, since CBMM8 and CLRM8 share 06185110; 207 KB raw for all; the annual-peak URL carries parameter 00065, without
   which the response mixes discharge rows in). Gauges with no flood stage, and gauges whose categories are elevations of
   1,000 ft or more (the nearest such to a Montana grid point is Lake Pend Oreille at Hope, 13.7 miles), are excluded. Words: "River flood record at the {name} gauge, {miles} miles away; it does not say water
   reached this address." Daily flood-day counts are out (no daily stage series). Terms: US government works; the NWS
   conditions; USGS credit. The owner confirms the 10-mile cut-off (alternatives 25 miles, 69.6 percent; 5 miles, 4.8).
8. **Not in B5**: FEMA flood zones (a hazard and insurance designation, not a weather event; AGENTS rule 5; owner and
   counsel first), lightning strike data (commercial), UV and sunlight, roof surface temperature, ponding (no public data):
   each gets a "Data unavailable" line that says why, per the roof-indicators record.

## Product (the sheet and the town page; the synthesis of 2026-10-19 with the supervisor's amendments)
Sheet, top to bottom:
1. The address line (B3) and the cell's place name.
2. One plain sentence: "Five seasons of weather for this spot, from grid estimates, station readings and NWS records. Each
   row says what kind of record it is."
3. **The five-season table** (the summary that leads the sheet). Columns 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 and
   Five seasons (July to June). Rows in this order, each with its kind word and unit:
   - Largest radar hail estimate at this cell (radar estimate, inches, with its date; B1)
   - Days with a radar hail estimate of 1 inch or more (radar estimate, days; B1)
   - Largest hail reported within 5 miles (report, inches, with its date; B2)
   - Hail reports within 5 miles (report, count)
   - Peak gust of 50 knots (58 mph) or more (station reading, days, the station named)
   - Strongest gust at that station (station reading, knots and mph, with its date)
   - Wind reports within 5 miles (report, count)
   - High wind watches and warnings for the zone (zone product, count)
   - Highest temperature (grid estimate, F, with its date)
   - Lowest temperature (grid estimate, F, with its date)
   - Days with a high of 90 F or more (grid estimate)
   - Days with a low below 32 F (grid estimate)
   - Freeze-thaw days (grid estimate)
   - Precipitation (grid estimate, inches)
   - Largest one-day precipitation (grid estimate, inches, with its date)
   - Snowfall, July to June (station reading, inches, the station named)
   - Deepest snow (station reading, inches, with its date)
   - Snow analysis, water year (analysis, inches; only if the unit check of D7 passes)
   - Freezing rain reports within 5 miles (report, count)
   - Winter storm and ice storm warnings (warning or zone product, count)
   - Flood and flash flood reports within 5 miles (report, count)
   - Flood and flash flood warnings (warning, count)
   - Lightning, UV and sunlight, roof surface temperature, ponding (Data unavailable, with the reason behind the heading)
   A partial 2026-27 line sits below the table. A missing or partial season shows its coverage line ("n days missing"),
   never a blank or a zero. The radar rows carry one sentence under the table: "Radar estimates can miss hail that people
   reported and can show hail that no one reported."
4. **Sections in this order**: Hail; Wind; Storms and warnings; Temperature; Rain; Snow; Flooding; Ice and winter; Heat;
   Weather that matters for a roof; How this was made. Each has a heading, one lead sentence with its kind word, and rows
   that begin with their kind label (B2 D3).
5. Roof reference lines by stressor, grouped "Thresholds", "Snow and ice", "Wind and hail", "Heat and rain", "Lightning
   and sun"; kind "Reference"; none says what a roof needs.
6. How this was made: sources, distance rules, the coverage rule, the freeze-thaw and 90 F rules, units, the licence
   sentences.
Town page: the same table for the town's centre cell and the two nearest stations that pass the rule, plus two station
rows the sheet does not carry (the station's season highest high and lowest low with dates, as station readings, with
the station's name); a town page never picks the nearest station silently (Benchland names the station used and says why
Moccasin is not). Town warnings are tested by the town point itself (D11). At 390 px the table reflows to one card per
row with the label first; no horizontal scroll; 16 px gutters.

## Rules fixed by the supervisor (D1 to D16)
- D1 Thresholds: a 90 F day is a day whose grid high, rounded to a tenth of a degree C, is at least 32.2 C (the value GHCN
  stores; 32.2 C shows as 90 F); a freeze-thaw day has a high above 0 C and a low below 0 C; a low below 32 F is a low
  below 0 C. Stated on the page once. (The synthesis's option B, which reproduces the corrected roof counts.)
- D2 Per-cell monthly aggregates are the store's unit: rain total; rain maximum and its day; tmax maximum and its day;
  tmin minimum and its day; days at or above 90 F; days at or below 0 F; freeze-thaw days; days with a low below 32 F;
  missing days. Seasons (July to June), calendar years and water years are sums of months. A month with missing days
  carries its count and the page says "n days missing". Sums use daily values rounded to 0.01 before conversion. The
  -999.99 fill is never summed; the 71 water cells read "no land value".
- D3 Windows: the five seasons (July 1, 2021 to June 30, 2026) and the partial season need the 63 scaled months July 2021
  to September 2026. The reports window stays B2's trailing 1,826 SPC days. Both windows are shown and labelled. The
  backfill runs once and its aggregates are cached as a release asset (about 1.2 MB a month, estimated); the builder
  measures the read speed and keeps no month file after its aggregates are written.
- D4 Every hail cell lookup goes through website.hail.cell_for; the climate grid and the NOHRSC grid have their own cell
  functions with the same half-open rule, computed in integer thousandths. The two half-cell points (Benchland LSR 47.08 N,
  110.02 W; the Petrolia Lake point) are test cases whose expected cells come from cell_for. Gates probe with those
  functions only.
- D5 Stations (GHCN-Daily .dly from NCEI): candidates within 40 miles with a report in the last 30 days; coverage is the
  share of the 2,192 days 2020 to 2025 with an unflagged value, per element, at least 80 percent; take the two nearest
  that pass; fewer than two: show those that pass and say so; none: "No station within 40 miles has enough reports for
  {element} from 2020 to 2025." A season value shows only when at least 95 percent of its days have the element; every
  station's share is shown. A missing day is never zero; a non-blank Q-flag excludes a value; trace counts as zero in sums
  and is said so.
- D6 The river gauge line: the nearest gauge with a defined NWS flood stage within 10 miles (the owner's open decision O4;
  25 miles is the alternative), keyed by USGS number, with the exclusions in source 7. It shows the gauge name, distance,
  flood stage and the water-year peaks at or above flood stage; no daily flood-day counts. Per-address gauge lines wait
  behind the counsel gate; town pages may show them first.
- D7 NOHRSC: kind word "Analysis", water-year label. The unit check is a regression of station season totals (inches, from
  the .dly files, seasons with at least 95 percent of days) on the NOHRSC cell values at every Montana GHCN station with a
  complete season: a slope near 1.0 supports inches, near 0.39 centimetres; the Billings cell alone (50.29 against the
  airport's 64.3 in for 2024-25; 33.85 against 40.9 in for 2025-26) does not settle it. The slope, the station count and
  the residuals are recorded. If the slope is not within 0.85 to 1.15 the product stays out of the sheet and the snow
  section shows station seasons only, with the words saying why.
- D8 Periods (B2 D33, implemented here for every zone product): rows ordered by product time; a CAN, UPG or EXP closes the
  current period; a later NEW, CON, EXT, EXA or EXB opens the next; each period is a span. Tests on the four named cases
  (MTZ004 WS 2024 event 1; MTZ302 HW 2022 event 38; MTZ320 WS 2023 event 4; MTZ003 WS 2021 event 12, which may fall before
  the window: the gate checks it).
- D9 Season counts: an event counts in the July to June season in which its begin time falls, in Montana time. "Cancelled
  at {time}" and "upgraded" replace "{begin} to {end}" as in B2 D26 and D31.
- D10 Time rules: NCEI BEGIN_DATE_TIME is MST (UTC-7) on Montana rows (679 of 761 matched hail pairs differ by +7 h; the 82
  others are listed in verify, not explained away); LSR VALID is UTC; IEM daily is the local calendar day; GHCN has its own
  day; SPC days run 12:00 to 11:59 UTC.
- D11 **Polygon products cover a cell when the polygon intersects the cell, not only when the cell's centre is inside**
  (the centre rule can show "none" for a point inside a warning whose cell centre lies outside; AGENTS rule 6). This
  applies to every polygon product, the B2 ones included, and the words say "covered this cell or part of it". The build
  records how many cell covers the change adds for each product. Town pages test the town point itself against each
  polygon (an exact point-in-polygon result, no cell); verify lists, for the 17 towns and every polygon product 2021 to
  2026, the cases where the centre rule and the point rule disagree. Blocks with a null or empty geometry never read as
  "no warning": they join by zone or county codes where the product carries them and are counted otherwise.
- D12 Gusts: IEM daily gusts at or above 130 kt are dropped and counted (the 182.5 kt LWT value of 2023-03-13); the HVR
  105.1 kt (2025-02-20) and MSO 86.0 kt (2025-05-09) values are flagged for check and shown with the flag words.
  Non-thunderstorm gusts show their recorded type word.
- D13 Words and claims: nothing states damage, loss, a claim, coverage, insurance, eligibility, a probability, risk or an
  all-clear. The forbidden list is the roof record's list extended to the six sheet strings the refuter found. "damage"
  appears only as a source type word, inside a quoted remark, or as "NWS damage threat tag"; "structure" only inside the
  two proper names; "warrant" only inside quotation marks. One source per row, never mixed: a grid row is a grid row and a
  station row names its station; where the two are both shown (town pages) each carries its own kind word and the page
  does not reconcile them. The Billings 111 F reading of 2026-07-12 is not claimed anywhere until an NWS climate product
  confirms it.
- D14 Held: FEMA flood zones (counsel first; AGENTS rule 5), lightning strikes (commercial), UV and sunlight, roof surface
  temperature, ponding (no public record), ground snow load (a design value, not history), SNOTEL (access restricted).
  Each held item has a "Data unavailable" line that says why.
- D15 Hail hit-and-miss record: verify builds a table of every LSR hail report of 1.00 in or more in the window against the
  B1 MESH maximum at the report's cell and the SWDI MAXSIZE within 2 miles (hit, miss, under by how much; Lewistown 2.50 in
  at a 0.0 mm cell and Glendive 4.00 in at 14.4 mm are known cases), recorded in b5-verification.json and summarised on
  the About page in words without numbers; the sheet shows the one radar sentence of the Product section. IEM magnitude
  units for codes 5, 6, 7, I and J stay unshown until the IEM documentation confirms them.
- D16 Failure: each source's failure marks its part unavailable with the B2 D20 sentence, in Python and in the browser,
  and the rest of the store builds (B3 D20).

## Store files and index blocks
- `hail/c/<tile>.json`: one record per land cell in each 0.1 degree tile; five July to June season records, the partial
  line and the calendar and water-year sums; integers: rain in hundredths of an inch, temperatures in tenths of a degree F,
  dates as yyyymmdd (337 B per cell, 2,024 B median per tile measured for five records).
- `hail/n/<tile>.json`: NOHRSC season values for each 0.04 degree cell whose centre falls in the tile, five water years,
  integers in hundredths of an inch once the unit check passes (about 1.54 MB for the Montana box).
- `hail/sd/<station>.json`: per station, per element, per July to June season and calendar year: total, days reported,
  days unflagged, newest report date, the coverage counts of D5, and the season highest high and lowest low with dates;
  `hail/s/` stays B2's gust files.
- `hail/g/<usgs>.json`: gauge peaks by water year (97 series, 7,084 rows, 207,359 B raw).
- `hail/k/<county>.json`: county-only FA.A and FF.A events.
- `hail/j/` and `hail/z/` (B2): polygon-product warnings with their tile covers under D11, the new zone-product events,
  FF.A events, the period spans. B2's j/ budget of 40 MB stands (19.9 MB today).
- `hail/index.json` blocks "climate", "snow", "stations", "gauges" and "county": state (loaded, partial, unavailable),
  counts, sizes, file dates, sources. `hail/manifest.json` lists every new file.

## Words and kind words
Kind words: Radar estimate; Radar detection; Report; Record (NCEI); Warning (NWS polygon, relayed by IEM); Zone product;
Station reading; Grid estimate; Analysis (NOHRSC); River gauge; Reference; Data unavailable. ("Design value" never appears
in the history.) Templates live in Python (WORDS_CLIMATE, WORDS_INDICATORS, additions to WORDS_JOINS), each tested against
the forbidden list:
- "Grid estimate: {n} freeze-thaw days in the {season} season (a high above 32 F and a low below 32 F)."
- "Grid estimate: {n} days with a high of 90 F or more in the {season} season."
- "Grid estimate: highest {f} F on {date}; lowest {f} F on {date}. An estimate for a grid cell about 4.6 km across, not a
  reading at this address."
- "Station reading: {in} in of snow in the {season} season at {station}, {miles} miles away ({k} of {d} days with a value)."
- "Analysis: {in} in of snow in the {water_year} water year, from the analysis cell about {miles} miles away. An analysis,
  not a measurement at this address."
- "River gauge: river flood record at the {name} gauge, {miles} miles away; it does not say water reached this address."
- "Warning: {date} {begin} to {end}: {kind} warning, {office}, covered this cell or part of it; the tags are the forecast
  threat at issue time."
- "Report: {date} {time}: {type}, {source}, {miles} mi {bearing}." Quoted remarks as B2 D4 requires.
- "Data unavailable for {season}: {station} has {k} of {d} days with a {element} value, so this season is not shown; a
  missing value is not zero."
- "No NWS local storm report of {type} within 5 miles in these five years; reports are not a complete record."
- "{Part} could not be loaded in this update; that is not the same as no {part}." (B2 D20)
- Every stale or unavailable line ends "This is not an all-clear." "not the same as no hail" is the only "no hail" allowed.

## Jobs and budget
- Daily (the store job on main, not scheduled today): B1 (612 s measured in CI), B2 joins (99 s locally) plus the B5
  additions: climate prelim days by Range (about 1.4 MB a day, 5 to 10 s), station refresh (42 files, 27.7 MB, 10 to 25 s),
  NOHRSC current season (541,698 B), NWPS current state, pack and publish (about 7 s). Proposed budget: under 25 minutes end
  to end, measured and recorded; the 60-minute timeout stands.
- Monthly: the new scaled climate month (41 MB by Range, 57 MB whole; 4 to 68 days after month end); NOHRSC's new water
  year when it appears; USGS peaks; the station candidate union recomputed for every town and tile centre (not computed
  yet: the builder computes and records it).
- Annual or on change: TIGER counties (edition change), the gauge list.
- Backfill once: 63 scaled months into the cached aggregates.
- Browser budget: a phone view at zoom 15 with the B3 layers measured at 607,375 B gzip; B5 adds a climate tile of median
  268 B gzip and the other per-click files, which the browser builder measures; the gate is 650 KB. The store is never
  fetched by the 10-minute site build.

## Contract rows (website/sources.py; each carries units, timing, cadence and missing-value rules, AGENTS rule 7)
`nclimgrid_daily` (prcp mm; tmax and tmin C unrounded; -999.99 never summed; 71 water cells "no land value"; scaled month 4
to 68 days after month end, prelim 2 to 3 days; the NetCDF licence attribute and the NODD sentence), `nohrsc_season_snowfall`
(units by the D7 check; 0.04 degree; water year; no-data below -9000; the NWS conditions), `ghcn_daily` (SNOW and SNWD mm;
PRCP tenths of mm; TMAX and TMIN tenths of C; -9999 and absent rows missing, never zero; Q-flag excludes; trace as zero in
sums; archive values 45 to 60 days after month end; NOAA public domain per NCEI-PD-10-2-02 section 4(a); CoCoRaHS CC BY 3.0
with attribution), `iem_watchwarn` (polygon, zone and county rows; UTC; tags as issued, the damage-threat tag labelled as the
NWS's; the period rule D8; the IEM public-domain sentence and the attribution request), `ncei_storm_events` (BEGIN times
MST; magnitude by type; FLOOD_CAUSE as written; lag as NCEI's newest event; licence text not read, said so), `iem_lsr`
(VALID UTC; magnitudes for codes 5, 6, 7, I and J unshown), `nwps_gauges` and `usgs_water_api` (flood stage in feet;
parameter 00065; waterservices retires 2027-02-22; "Observations courtesy of U.S. Geological Survey"), `census_counties`
(the acknowledgement), `roof_references` (R1 to R20 as kind "Reference", never a finding).

## Gates (B5-1 to B5-18)
1. Grid: the Billings cell's calendar 2025 precipitation (468.9 mm rounded monthly sum; NCEI monthly 468.98 mm), the June
   15, 2025 tmax and tmin, and the 2024-25 freeze-thaw days reproduce an independent h5py read with zero difference; the
   airport comparison is shown (GHCN 73 freeze-thaw days in calendar 2025).
2. Backfill: 63 scaled months July 2021 to September 2026 read once; 25,902 land cells; no -999.99 value in any sum
   (asserted); 71 water cells read "no land value"; the read speed and the aggregate sizes recorded.
3. Stations: at Billings the rule picks WTP COOP USC00240802 (1.4 miles) and Billings Logan USW00024033 (2.6 miles) for all
   five elements; at Benchland snow Buffalo 1.7 E US1MTFG0003 (20.9 miles, 81.7 percent) and Lewistown 11 SSE USC00244978
   (31.1 miles, 90.0 percent), depth Stanford USC00247864 (10.9 miles, 81.9 percent) and Crystal Lake USS0009C01S (31.3
   miles, 99.9 percent); Stanford snow at 79.9 percent misses by 0.1 point and every station's share is shown. For each of
   the 17 towns verify records how many of the five seasons pass the 95 percent rule at its two stations, per element.
4. NOHRSC: the D7 regression recorded (slope, stations, residuals) and the display decision follows it; five water years
   2021-22 to 2025-26 present (11,562,084 B); 2020-21 missing is stated.
5. Product counts equal the research's window counts (source 4) with zero difference; June 2022 (E01): FL.W and FA.W
   products over Red Lodge, Gardiner and Billings, the NCEI flood records, the Billings gauge peak of 16.37 ft on
   2022-06-15.
6. Period rule: the four named zone cases of D8 with their expected periods; the MTZ003 case checked against the window.
7. NCEI points: the county-coded rows join as records; Glentana (T04, 2022-07-18 23:47 UTC) is found at its point; the Hays
   case (2021-07-07) is excluded as outside the window and the exclusion is asserted.
8. Gusts: LWT 182.5 kt dropped and counted; HVR and MSO flagged (D12).
9. Roof counts: the M6 and M10 series reproduce the corrected counts under D1 (90 F highs [45, 42, 27, 35, 25]; 1 inch snow
   depth [55, 70, 30, 53, 25]).
10. Words: the forbidden-term test covers every template and the six sheet strings; "structure" only in proper names;
    "damage" only in the allowed contexts; the four Data unavailable lines present with reasons; the radar sentence present.
11. Readability: a reviewer reads the summary table for three places (the gate cell, Benchland, Billings): every cell has a
    unit and a kind word, no sentence needs decoding, the table is within the first screen at 390 px.
12. Budget: the daily job runs end to end locally in under 25 minutes; the measured sizes recorded; the phone view at zoom
    15 stays under 650 KB gzip.
13. Determinism: two builds from cache give byte-identical c/, n/, sd/, g/ and k/ files.
14. Failure: each source's failure marks its part unavailable (D16), in Python and in the browser, and the rest builds.
15. Polygon rule (D11): the cell-cover counts before and after the change recorded per product; the town point check lists
    every disagreement between the centre rule and the point rule for the 17 towns; a null-geometry block test.
16. Temperature extremes: the season highest high and lowest low rows carry dates and the grid kind word; the town pages'
    station rows carry the station's name; no row mixes sources.
17. Hail hit-and-miss (D15): the table built for every LSR hail report of 1.00 in or more in the window; the Lewistown and
    Glendive cases present; the About summary in words.
18. Flag-off and --hail-history-only builds unchanged; Chromium smoke at 390 and 1280 px; smoke_pages; the live preview
    build on the branch; zero off-site requests.

## Ownership (worktree /home/user/wt/wt-b5, branch claude/hail-b5 from db84d76; builders 1 to 3 run first, builders 4 to 6 after the B3 site build lands and B3 is merged in)
- Builder 1 (climate grid): `website/climate.py` (nClimGrid reader with h5py, aggregates, tiles, words, verify, CLI,
  backfill and update steps), `tests/test_climate.py`.
- Builder 2 (snow and stations and gauges): `website/snowgrid.py` (NOHRSC, with the D7 regression), `website/stations.py` (GHCN .dly reader, the
  station rule, seasons, the season extremes), `website/gauges.py` (NWPS and USGS), their tests.
- Builder 3 (products): the B2 extensions in `website/joins.py` (the new phenomena by path, the county path, the period
  rule D8, the polygon rule D11 with the town point check, the NCEI point types, the LSR types, the hit-and-miss record
  D15), `tests/test_joins.py`, the county boundary file reader.
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

## Supervisor rulings on the owner's open decisions (provisional until the owner answers; 2026-10-19 06:45 UTC)
- O4 gauge distance: 10 miles. O5 thresholds: D1 above. O6 season columns: July to June, water years labelled for snow.
  O8 station coverage: 80 percent to choose, 95 percent to show a season. O10 NOHRSC: only if D7's regression passes.
  O11: the "Data unavailable" lines. The owner can change any of these; each is one constant in the code and one sentence
  on the page.

## Supervisor decisions after the part A review (2026-10-19 15:10 UTC; D17 to D26) and the completion list for part A
The part A re-check (/home/user/hail-b5/out/b5a-recheck.json) passes gates B5-1 to B5-4, B5-6 to B5-9, B5-13 and B5-15;
the suite fails only in tests/test_site.py and tests/test_hail.py (the fixture's new k/ files, the B2 test store's old
formats, and word keys the B2 browser still fills). The rulings:
- D17 **Zone rows once.** Overlapping yearly requests share rows; one seen-set across every year and product (the key the
  data reviewer verified in scratch) keeps each row once, so z/ holds no copied event and the period cases hold.
- D18 **Station currency per element.** A station is current for an element when that element has a report in the last
  30 days; the rule runs per element and location (Source 3; owner decision 4). Gate B5-3's named Benchland picks follow
  the per-element rule; verify records which station replaced which and why.
- D19 **One rounding rule.** The daily grid value is rounded to the hundredth of a degree C (the store's precision); a
  90 F day is a high at or above 32.15 C, which shows as 32.2 C and 90 F; the same hundredth step applies to every
  temperature rule (freeze-thaw, below 32 F, at or below 0 F). D1 reads so and the page says it once. No stored number
  changes.
- D20 **The partial season.** The 2026-27 partial season is not in the season lists; it is the one line below the table:
  "{season} so far, {n} days to {date}: ..." with its own counts; when the store holds no day of it: "No day of the
  {season} season is in the store yet."
- D21 **Gauges.** The store keeps every pool gauge with a flood stage and a USGS number within 10 miles of any Montana
  cell (104 series, 7,560 rows, 285,713 B); the brief's 97 was the research sample; the nearest-gauge rule picks from them.
- D22 **The events table is split for the browser.** hail/j/events.json (6,083,996 B raw, about 850 KB gzip) is never
  fetched by the browser: part B's products builder writes per-tile event files (hail/j/e/<tile>.json holding the events
  the tile's records reference) and the browser fetches the tile's file on a tap; events.json stays for Python's town
  pages and verify. The 650 KB gate stands.
- D23 **The snow analysis stays out.** The D7 regression gives a slope of 0.664 over 682 station-seasons (correlation
  0.81, RMS residual 17.7 in), so the analysis is not shown; the snow rows are station readings; the About page says in
  one sentence that the analysis was checked against station totals and left out. The method and the held state are an
  open item for the owner (the data answers O10).
- D24 **Gate wordings restated.** Gate 5: FA.W at Red Lodge (2022-06-12), FL.W at Gardiner (2022-06-13) and at Billings
  (2022-06-14), FL.A at Billings; the NCEI flood record at Red Lodge (event 1039252, 2022-06-10) and none expected at
  Gardiner or Billings; the Billings gauge peak 16.37 ft on 2022-06-15. Gate 17: the window table (737 rows; hits 464,
  misses 273; Lewistown 2.50 in present) and the Glendive 4.00 in case named as outside the window (2021-06-08), as
  gate 7 names Hays.
- D25 **Figures.** Measured figures replace the brief's: climate tiles 4,569 files, 35,149,062 B, median 8,038 B raw and
  1,705 B gzip; the station rule set 466 files and 384 MB (304 chosen somewhere, 310 MB); the regression set 105 files,
  49 MB; gauges per D21; the products live build 467 s cold and 415 s warm; the joins events table per D22.
- D26 **Job scopes (part B's job builder; recorded now).** Daily: the station list and inventory, the files of the
  chosen stations only (a file whose Last-Modified is unchanged is not fetched), the NWPS list and details, the climate
  prelim days, the products pulls. Monthly: the whole candidate union and the regression set, the scaled climate month,
  the USGS peaks, the NOHRSC file check. Every step non-fatal (D16), with a timeout from its measured time; the daily sum
  measured again after the split against the 25-minute budget.
- Completion list for part A: D17 applied (the seen-set); D18 applied with its tests; D19's words in D1's sentence on the
  page and in the module docstring; D20 applied; the climate lead never formats None (rules-F06); tests/test_hail.py's
  fixture lists gain hail/k/MTC045.json and hail/k/MTC111.json; tests/test_site.py's B2 test store writes the v2 formats
  and row fields the branch reads; WORDS_JOINS keeps every key the B2 browser fills (warnings_tags_none and the B2
  template keys stay as they were, the B5 additions sit beside them) until part B's browser builder switches map.js and
  removes the old keys, so the whole suite passes on this branch with the B2 map.js; the TIGER use constraint quoted
  verbatim (rules-F23); the hit-and-miss summary sentence plain (rules-F10); the county product rows carry their own
  kind word "County product" (rules-F08); the one disallowed "no hail" phrase removed (rules-F09); the station refresh
  scope flag of D26 (daily and monthly) in stations.py's CLI; the gauges and snow crash paths of job-F2 to job-F4 marked
  unavailable per D16; the climate request errors of job-F7 caught with no partial file left.
- Part B item recorded 2026-10-19 16:05 UTC (B4's D22): B2's "in the window" phrases in the zone-product words (the town
  pages, the About zone row, the joins words in map.json, the wind zone contract row in sources.py) are reworded to
  "in these five years" by the summary and site builder, with the tests that quote them.

## Supervisor decisions after the part A completion (2026-10-19 16:25 UTC; D27 to D30) and the split of part B
Part A is complete (/home/user/hail-b5/out/b5a-recheck-completion.json: gates B5-1 to B5-9, B5-13 and B5-15 pass; the
suite passes; WIP on claude/hail-b5). Amendments: D20's no-day sentence reads "No day of the {season} season is in the
data yet. This is not an all-clear." ("store" is a developer word); D4's climate cell function works in exact 1/48-degree
integer units (the grid's own unit) under the same half-open rule. Part B splits in two so the Python side does not wait
for the B3 site build: part B1 (now, on claude/hail-b5) builds the summary module, the products additions, the site's
Python side (build.py, sources.py, the town and About templates) and the docs and job; part B2 (after B3 lands and is
merged in) builds the browser (map.js, map.css), the sheet's smoke and the browser gates.
- D27 **Zone editions.** 1,230 zone-product events (WW.Y 368, HW.W 354, HW.A 310, WS.A 57, WS.W 44, HT.Y 34, WC.W 32,
  FA.A 23, BZ.W 4, FF.A 4, across 20 codes) carry zone codes that the two current editions do not hold, so they join no
  cell. The products builder fetches the older public-zone editions that cover the window (the NWS GIS archive of previous
  zone shapefiles, each with its effective date) and places every event by the edition in force at its issue time; the
  unplaced count after that is recorded and explained event by event if not zero. Nothing is dropped silently; a zone
  section says how many of its products could not be placed, if any.
- D28 **Unavailable blocks carry the sentence.** The gauges and stations index blocks carry the D20 sentence beside the
  technical reason, as the snow block does, so D16 holds in Python before the page renders it.
- D29 **Kind words for every product.** KIND_WORDS covers every product the store joins (watch, warning, advisory, each
  by its NWS name: "flood watch", "flood advisory", "winter weather advisory", "wind chill warning" and so on), so no row
  reads "FA warning"; the test lists every code the store holds.
- D30 **Events per tile.** D22's per-tile event files are hail/j/e/<tile>.json, each holding the events the tile's
  records reference (format hail-events-tile-v1, the same row shapes as events.json), written by joins.py beside
  events.json; the browser (part B2) fetches the tile's file on a tap; verify checks every referenced event is in its
  tile's file and measures the largest file (budget 100 KB gzip).
- Part B1 list: website/summary.py (new) with tests; the products additions (D27, D29, D30; B2's "in the window" phrases
  reworded to "in these five years" with their tests; the radar sentence on the sheet words; the hit-and-miss About
  sentence); stations.py and gauges.py D28 (two small edits); build.py (the flag copies c/, sd/, g/, k/ and j/e/; n/
  only when the snow check passes; map.json blocks climate, snow, stations, gauges, county and summary from the
  map_data functions; the town pages with the summary table first and the sections in the fixed order; the About page
  with the new sources and terms, the D23 sentence, the hit-and-miss sentence, the Census acknowledgement); sources.py
  rows for every new feed; templates town.html and about.html (not map.html's sheet); tests/test_site.py; docs D38
  (B3 writes D36 and B4 wrote D37), DESIGN section 12, ROADMAP, README, AGENTS, b5-verification.json; the job steps in
  hail-store.yml under D26 with the measured budget.

## Supervisor decisions after the part B1 review (2026-10-20 00:05 UTC; D31 to D43) and the part B1 completion list
The part B1 re-check (/home/user/hail-b5/out/b5b1-recheck.json; the reviews in the run record) found the Python side
built but with honesty defects on the page. Rulings:
- D31 **Zone editions (D27 settled).** The NWS serves only two editions and the six older ones return 404 at the GIS
  address. A research step looks for them elsewhere (the IEM archive of zone geometries with their valid periods; the
  Wayback Machine's copies of the WSOM zips; the NWS GIS "previous versions" list) and checks any find's content (the
  Montana zone codes of 2021 to 2022, the effective date in the metadata). If an edition is found, the products builder
  places by it; if not, the 1,230 products stay unplaced, every zone row for a season before a zone's first placed product
  reads "Data unavailable" with the reason, the five-season total names the seasons it leaves out, and the 10,422
  placements by code identity are disclosed on About. Nothing is counted as zero.
- D32 **No absence claim from a failed part.** A failed or absent block never produces "No gauge within 10 miles", "no
  station has enough reports" or a zero: it produces the D20 sentence ending "This is not an all-clear." A candidate
  station whose file failed to load is named as failed in the problem line; the rule never silently skips to a farther
  station.
- D33 **Coverage lines on every cell.** A "No ..." cell for a season with missing days carries its "n days missing" line
  and the section leads carry the missing days. The partial line may show preliminary grid values labelled
  "preliminary"; nothing calls a value a record (D13's hold on the 111 F claim stands).
- D34 **Flood warnings include areal flood warnings (FA.W)** in the flood-warning row, the flood lead and the roof flood line.
- D35 **Detection days count distinct SPC days**, never rows.
- D36 **Station picks at the cell, not the tile centre.** The tile list carries up to six passing candidates with their
  positions and shares per element; the sheet (Python for the town pages, the browser for the sheet) picks the two nearest
  to the clicked cell's centre or the town point. Gate B5-3's named picks hold at the points.
- D37 **Gust coverage.** The station gust files carry days reported per station and season; a gust count of 0 shows only
  when the season's coverage is at least 95 percent, else "Data unavailable" with the days missing.
- D38 **Town pages test the town point (D11).** The products builder writes hail/j/towns.json with each town's polygon
  products by the point test; town pages count from it with "covered this spot"; the sheet counts the cell cover with
  "covered this cell or part of it".
- D39 **Town page order.** The forecast keeps the top of the town page (the daily use); the five-year history follows,
  under one heading, with a jump link in the page's first screen ("Five years of weather at {town}"); the summary table
  leads the history block. Gate B5-11's first-screen clause applies to the map sheet and to the history block when the
  link is followed.
- D40 **map.json weight.** No block lists every tile: the climate, stations, gauges and county blocks carry a URL pattern
  and a compact split map at most. Part B2 measures the phone view at zoom 15 under 650 KB after the change.
- D41 **Words.** Every unavailable, partial and held line ends "This is not an all-clear."; the D13 stem "coverage" leaves
  About; advisory and watch polygon rows carry their own kind ("Flood advisory", "Flood watch"), never "Warning"; the held
  row's unit is the reason, never "none"; "issuance polygon in effect" is reworded; the no-report sentence is present and
  the double negative gone; "River gauge:" and "n days missing" appear once per line; a five-season snowfall total shows
  only when one station covers all five seasons, else the five-season cell is "Data unavailable" and each season names
  its station (B5-16); the 25th row "Flood and flash flood watches for the county" (County product) stands; the roof
  references quote R1 to R20 where the record gives a quotable sentence (15 quoted; R2, R9, R13, R17 and R20 not, with
  the reason in D38); the ice-dam line names the measured pattern from the roof record with its kind word and never the
  hazard as a claim about a roof; the flag-off identity holds (the town template's stray blank line); the one failing
  test is fixed.
- D42 **Budget (B5-12).** The monthly steps run in their own job on the first of the month so the daily job stays under
  25 minutes; each step's timeout is 1.5 times its measured time so one stalled request never reaches the 60-minute
  limit; the pack publishes whatever built. The j/ and hail/ budgets are restated to the measured sizes with the reason
  (the B5 products and the per-tile event files); the viewer's budgets are the phone view (650 KB) and the per-tile
  files (100 KB gzip).
- D43 **Process.** The WIP commits are the supervisor's; branch names are allowed in docs (AGENTS.md excepts them).
- Part B1 completion list: D32 to D41 applied where they touch Python (summary.py, joins.py, stations.py, gauges.py,
  climate.py's partial line, build.py, the templates, tests), D42 in hail-store.yml and the docs, D31's research outcome
  applied or recorded; the full suite green; the flag-off identity exact; the docs and the record brought to the
  re-check's numbers.
- D44 **Zone editions settled by the research (2026-10-20 00:30 UTC; /home/user/hail-b5/out/zone-editions/zone-editions.json,
  refuted and standing).** No NWS copy of the 2021 to 2024 editions is reachable (HTTP 404 at the GIS address; the
  Wayback copies could not be fetched through the egress relay). The Iowa Environmental Mesonet API serves the Montana
  zone set by date (https://mesonet.agron.iastate.edu/api/1/nws/ugcs.geojson?state=MT&valid=<UTC>; "free to use for
  any lawful purpose", as-is; simplified geometry whose bounding boxes sit within 0.014 degrees of the NWS file for the
  83 current codes): 103 Montana zones through 2022-09-13T12:00Z and 83 from 2022-09-13T18:00Z (the 20 codes MTZ008 to
  MTZ015 and MTZ044 to MTZ055 removed; MTZ060 reshaped); the NWS change log dates the reconfiguration to 7 September
  2022 (z_07se22). The products builder places every zone product by the IEM set in force at its issue time: the 103-zone
  set to 2022-09-13T12:00Z and the 83-zone set after 2022-09-13T18:00Z; a product issued between 2022-09-07 and
  2022-09-13T18:00Z is placed by whichever set holds its code and counted as "placed in the changeover week". The
  current 83 zones keep the NWS full-resolution outlines; the 20 removed zones and MTZ060 before the switch use the IEM
  outlines, and their rows carry "placed with a simplified zone outline". The IEM snapshots are cached with their
  checksums, a CONTRACTS row iem_ugcs records the source, its terms and the simplification, About credits the IEM, and
  verify records the placement table (expected: 0 unplaced). D31's "Data unavailable" fallback stays for any product
  that still cannot be placed.

## Part B2 plan (recorded 2026-10-20 00:40 UTC; starts after the part B1 completion, the D44 products pass and the merge)
1. The supervisor merges claude/hail-b3 (the site side with streets, outlines, dots and the search) and claude/hail-b4
   (the live swath layers) into claude/hail-b5 with git merge --no-commit; a merge agent resolves the conflicts keeping
   every behaviour (the sheet's order: the B3 address lines on top, then the B4 live line, then the B5 summary table and
   the sections; build.py's flags and map.json blocks from all three; sources.py's rows; the templates; the tests; the
   docs entries D36, D37 and D38 in order; both workflows' steps); the supervisor commits.
2. The combined store for the real builds: B1's t/, B5's j/ (with j/e/ and towns.json), z/, s/, c/, sd/, g/, k/, and
   B3's a/, r/, b/ and counts.json, assembled from /home/user/hail-b3/out/keep/hail-store-b3-job1.tar.gz and
   /home/user/hail-b5/out/b1/store with one index.json and manifest.json carrying every block; every module's verify
   passes on it.
3. Part B2 builds the browser: the sheet opens with the B3 address lines, then the B4 live line when a hail layer is on,
   then the five-season summary table from map_data_summary and the per-tile files (one fetch per file, cached), then
   the sections in the fixed order; the per-tile event files replace events.json in the browser (D22, D30); the gust
   rows and the unavailable lines say what Python says (D37, D32); the town-point products are the town page's, not the
   sheet's; no literal sentence, unit, threshold or colour in map.js; map.css styles the table at 390 px.
4. The smoke (tools/smoke_map.py) covers the sheet at 390 and 1280 px (the table within the first screen; every cell
   with a unit and a kind word; the exact comparison with Python's words on three cells; the fetch list per tap with the
   650 KB budget at zoom 15 with every layer on; zero off-site requests); smoke_pages; the live preview on the branch.
5. The docs' final numbers, the verification record's browser gates, and the pull request stacked on the B4 one.

## Supervisor rulings after the part B1 completion (2026-10-20 01:20 UTC; D45 to D48) and the second completion list
The completion re-check (/home/user/hail-b5/out/b5b1-recheck-completion.json) shows D32 to D35, D37 to D41 largely in
place; seven of the eight failing tests compare the B2 browser's words with the B1 Python words and belong to part B2
(the switch of map.js); the rest is below.
- D45 **"Radar coverage" is allowed.** NOAA's term "no radar coverage", always preceded by "radar", is not the D13 stem;
  the stem rule applies to every other use (insurance, policy).
- D46 **Reference titles.** A roof reference line quotes the sentence; a source title that carries a D13 word (R20,
  "freeze-thaw damage to roofs") appears only in the About references list as a citation and nowhere else; a quoted
  NCEI remark may carry "structure" (D13 allows quotations).
- D47 **Counts per line.** One coverage statement per line that names each element once ("108 days missing for the high
  and 109 for the low") satisfies D41; a watch or advisory row whose product name carries its kind ("3 winter storm
  watches", "Zone product") satisfies D41's own-kind rule; the partial "Only one station within 40 miles" lines end
  with the all-clear sentence.
- D48 **Records are their own row.** NCEI flood and flash flood records within 5 miles (county-coded points) are a row
  of their own ("Flood and flash flood records within 5 miles", kind Record), never folded into the report row; the Red
  Lodge record of 2022-06-10 (0.3 miles) must appear in it and render in the flooding section (gate 5).
- Second completion list (Python side): D44 applied in joins.py (the IEM zone sets by date from the cached snapshots,
  the changeover week counted, the simplified-outline note, the iem_ugcs CONTRACTS row, the About credit, verify's
  placement table expected 0 unplaced; any remainder under D31's words); D48; D36's town-page station-gust list picks
  and measures from the town point (joins.py around line 2123); the five-season gust cells name their station or read
  "Data unavailable" with the reason; the ice-dam line's kind word on every page; the roof snow line's failure state
  carries the D20 reason; the "Only one station" partial lines' all-clear; the R20 title out of the roof line (D46);
  the Python test test_the_billings_town_page_joins_sit_in_their_sections_newest_first brought to the s/ v3 fixture
  (one gust day); the unplaced-caveat on zone rows for seasons with unplaced products after D44; the record's gates and
  the docs brought to the numbers; the seven browser-against-module tests left to part B2 and named in the record.

## Part B2, step 1: the merge of B3 and B4 into B5 (recorded 2026-10-20 02:10 UTC; D49 to D51)
- D49 **The preview waits for this commit's store job.** The Website preview on a branch push read the `hail-store`
  release asset as it stood when the build started, while the same push's Hail history store job was still running
  (PR 16, run 39355361294: "address_list, street_list, outline_list" failed; the same happened on the B2 branch). In
  `website.yml`, on branch pushes only, a step before "Build from live data" polls
  `gh run list --workflow hail-store.yml --commit "$GITHUB_SHA" --json status,conclusion --limit 1` once a minute
  until that run is completed, or at once when there is none (the store job runs only when the push touches the store
  code); the ceiling is the daily store job's timeout; the website job's `timeout-minutes` becomes that ceiling plus
  15; the step prints what it waited for and how long; `GH_TOKEN: ${{ github.token }}`; a test in
  `tests/test_website_workflow.py` reads the step, its branch condition and its ceiling. This is part B2's CI item,
  applied after the merge, not in it.
- D50 **The combined store.** `/home/user/hail-b5/out/combined/store` (496,331,217 bytes raw, 45,644 files) is B5's
  part B1 store (`t/`, `j/` with `j/e/` and `towns.json`, `z/`, `s/`, `c/`, `sd/`, `tl/`, `g/`, `k/`) plus the B3 job
  store's `a/`, `r/`, `b/` and `counts.json`, with one `index.json` (blocks: joins v2, climate, stations, gauges, snow
  unavailable, addresses, roads, buildings) and one `manifest.json` (45,643 entries), assembled by
  `/home/user/hail-b5/out/combined/assemble.sh`. The B3 job tarball carried the pre-rewrite address figures (D49 of
  the B3 brief: bytes.shards 45,783,814 in the index against 7,520,429 on disk), so `addresses.refresh_figures` was
  applied and the manifest's index entry recomputed. Every module's verify passes on it (addresses, streets,
  buildings, hail, joins with the joins cache, climate with the nClimGrid cache, stations, gauges; snowgrid reports
  unavailable by design): `/home/user/hail-b5/out/combined/verify-*.log`. Part B2 builds against this store; the
  merged daily job runs B1, the joins, the B5 steps (their 40-minute clock), then the B3 steps, then packs and
  publishes; its `timeout-minutes` is 150 (B5's 60 plus B3's 90) until the branch run measures it (the B3 branch job measured 35.6 minutes end to end on 2026-10-20: B1 build 11.8, joins 14.8, the B3 steps 8.2); the packed size is
  measured in the branch run (B3's pack alone was 72,030,584 bytes).
- D51 **Merge rules.** The supervisor runs `git merge --no-commit --no-ff claude/hail-b3` in `/home/user/wt/wt-b5`,
  a merge agent resolves, a reviewer checks, the supervisor commits; then the same for `claude/hail-b4`. Measured
  conflict sets (dry run at 26c737a): B3 into B5: `.github/workflows/hail-store.yml`, `AGENTS.md`, `README.md`,
  `docs/DECISIONS.md`, `docs/DESIGN.md`, `docs/ROADMAP.md`, `tests/test_hail.py`, `tests/test_site.py`,
  `website/build.py`, the fixture's `index.json` and `manifest.json`; B4 after that: `.github/workflows/website.yml`,
  `AGENTS.md`, `README.md`, `docs/DECISIONS.md`, `docs/DESIGN.md`, `docs/ROADMAP.md`, `tests/test_site.py`,
  `tools/smoke_map.py`, `website/build.py`, `website/static/map/map.js`. Rules: every behaviour of every branch is
  kept; where two branches add to the same list, table, section or function, both additions stay, in the order B3,
  B4, B5 (the order the stages land); the decisions log carries D36 (B3), D37 (B4) and D38 (B5) in that order and the
  sentences that said the other entries were not yet in the file are rewritten to say where they sit; the roadmap's
  three "Built, not merged" sections become one section with one row per stage and the open-item lists in the same
  order; `AGENTS.md` and `README.md` take the union of the layout and command lines; `build.py` carries every flag
  (`--hail-addresses` and `--address-text` from B3) and every map.json block and status row; `sources.py` CONTRACTS
  and the About page take the union; `hail-store.yml` is B5's two jobs with B3's steps inserted in the daily job after
  "Verify the station, gauge and snow parts" and before "Pack the store", the `on.push.paths` list the union, the
  daily job's timeout 150; `website.yml` takes B3's `--hail-addresses` and `--addresses`, B4's smoke flags and B5's
  test modules; the fixture is never hand-merged: after the merge `python -m website.hail fixture <dir>` is run from
  the merged `fixture_store` (B3's `addresses_from` and B5's parts both kept) and the tree copied over
  `website/data/hail-fixture`, the budget test deciding its size; `map.js` and `map.css` keep B3's layers, search and
  sheet address lines on top of B4's live layers and live line; the seven browser-against-module tests of
  `tests/test_site.py HailJoinedRecords` stay failing until part B2 switches `map.js` (never fixed by changing Python
  words); the suite otherwise passes with the venv python, the self-test passes, the sample build and a build with
  the combined store and every flag run. The agents never run a git write command (`add`, `commit`, `checkout`,
  `reset`, `stash`, `merge`, `push`); they resolve by editing the files and read the sides with `git show`.

## Supervisor rulings after the second part B1 re-check (2026-10-20 02:20 UTC; D52 to D58) and the Python remainder for part B2
The second re-check (/home/user/hail-b5/out/b5b1-recheck-completion2.json): D44 applied (joins verify 48 of 48, 0
unplaced), D45 to D48 largely in place; 10 of 1,264 tests fail (the seven browser-against-module subtests, which part
B2 clears, and three that are not allowed); gates B5-5 and B5-10 fail, B5-11 and B5-16 partial. Rulings:
- D52 **The footer disclaimer stays.** "Weather information only. It does not confirm roof damage ..." in
  `base.html` (and its copy on About) is the site-wide evidence-honesty sentence from the earlier site; it names what
  the site never claims. D13 governs the history words (sheet, table, sections, the history parts of About), not this
  sentence. The live block's "No reading from this station in this update" line (`town.html`) is the live block's own
  pre-existing wording and stays.
- D53 **About's older lines.** The words module's stems apply to the B5 history text. Two older About lines are
  changed because the fix is a word swap: the MESH row reads "-3 (no radar coverage)" (`sources.py`, D45), and the
  radar line reads "a blank area is not a statement about the weather" (the satellite line's words). Nothing else in
  the older About text is rewritten in B5.
- D54 **Budgets are restated to the measured sizes with the reason.** `j/` 87,628,936 bytes (63,082,924 of them the
  per-tile event files, D22 and D30) and `hail/` 177,677,748 bytes for B5 alone; the combined store 496,331,217 bytes
  (D50); the packed asset measured in the branch run. The ROADMAP's budget line says so; the data-repository
  decision (O12) is Carson's and stays open.
- D55 **The research-count differences are explained or fixed.** HW.A 276 against 277, HW.W 338 against 339 and FW.W
  170 against 169: a fixer finds each one-event difference (the event's VTEC, times and the store's or the research's
  rule that drops it, such as the D17 seen-set or the window edge), fixes the store's rule if it loses a product, and
  records the explanation in the verification record and in verify's output; the gate B5-5 passes with zero
  unexplained difference.
- D56 **The three tests.** `tests/test_snowgrid.py`'s two word tests are brought to the D41 wording through
  `tests/words_rules.py` (the residue rule strips "This is not an all-clear." before the forbidden check; the exact-text
  assertion carries the sentence). The Billings test's expectation stands (2.6 miles from the town point, D36):
  `build.py` passes the town point as the spot to `describe_joins` and `summary.py`'s `_Spot` and `gust_station`
  measure from the town point and pick from the candidate list at that point; the fixer also diagnoses why the test's
  joined store printed "Station reading: Data unavailable" with no Station line in run 6 (the station reader or the
  fixture) and fixes the cause, never the expectation.
- D57 **B5-16 and B5-11 remainders.** Every season cell of the "Strongest gust at that station" row names its
  station; the roof snowfall total line names the station (Glendive and any one-station page); the ice-dam line leads
  with "Station reading:" on all 17 pages. The cell summary's flood-record row keeps the count; the flooding section
  (the browser, per-tile events) lists each record with its date and distance (D48 is met by the section).
- D58 **Accepted as is.** The B5-14 gap (station files missing under an index that says loaded) is covered by the
  manifest check, which refuses such a store; the injected case had to edit the manifest to get past it. The
  banned-name proxy count of 0 is accepted (the rule is the supervisor's: no model, AI-vendor or AI-product names in
  repository files; branch names are allowed, D43).
- The Python remainder for part B2 (applied on the merged tree by the Python fixer, after the merge): D53, D55, D56,
  D57; the verification record and the docs brought to the numbers (0 unplaced, 10,422 placed by code identity is
  superseded by the D44 table 785 + 3,327 + 11,580 + 72, the `j/` and `hail/` bytes, the HW.A explanation, this
  re-check's results); the daily job's joins backstop at 1.5 times the measured time (D42); the D49 CI wait step.

## Part B2 build list (steps 3 to 5; recorded 2026-10-20 02:25 UTC; runs on the merged tree after D51)
Owners (one worktree, `/home/user/wt/wt-b5`; each owner edits only its files; the store is D50's combined store,
read-only; builds go under `/home/user/hail-b5/out/b2/<owner>/` and are deleted when checked):
1. **Browser** (`website/static/map/map.js`, `map.css`, `website/templates/map.html` if a hook is needed): the sheet
   opens with the B3 address lines, then the B4 live line when a hail layer is on, then the five-season summary table
   (23 to 25 rows, the Product section's order), then the sections in the fixed order; the table and the sections are
   computed from the per-tile files (`hail/j/e/<tile>.json`, `hail/c/<tile>.json`, `hail/tl/<tile>.json`, then the
   `hail/sd/<station>.json` and `hail/g/<gauge>.json` the picks name; one fetch per file, cached; never `j/events.json`)
   with the rules and words `map_data_summary` and the other map.json blocks carry: no literal sentence, unit,
   threshold or colour in map.js (D29, D41); the station picks at the clicked cell centre from the `tl/` candidates
   (up to six passing per element, D36); the gust rows and the unavailable lines say what Python says (D37, D32: a
   zero only at 95 percent coverage, otherwise "Data unavailable" with the days missing); cell covers read "covered
   this cell or part of it" (D38); the flooding section lists each NCEI flood record with its date and distance (D57);
   the gauge lines carry one "River gauge:" prefix (F8); every failed part prints the D20 sentence (D16, D28); the
   old B2 words in map.js give way to the B1 Python words (the seven `HailJoinedRecords` browser-against-module
   tests pass; the old WORDS_JOINS keys are removed only after the switch); `map.css` styles the table at 390 px (no
   sideways scroll, the table inside the first screen below the address lines). The JS stays hand-written and
   documented inline as a browser-only need (450,765 cells cannot be pre-rendered).
2. **Site Python** (`website/build.py`, `website/summary.py`, `tests/test_site.py`, `tests/test_summary.py`): the
   map.json blocks the browser needs (words, thresholds, the fixed orders, the file paths and budgets; no block lists
   every tile, D40); D56's build.py and summary.py halves (the town point as the spot); D57; the seven browser tests
   kept as the contract (they compare the browser's text with the module's on the fixture and on three cells of the
   combined store); map.json stays under 140 KB raw.
3. **Products Python** (`website/joins.py`, `website/stations.py`, `website/sources.py`, `tests/test_joins.py`,
   `tests/test_stations.py`, `tests/test_snowgrid.py`): D55 (the three one-event differences), D56's station-reader
   diagnosis and the snowgrid tests, D53's `sources.py` word swap, D36's candidate list at a point (the shared rule the
   browser and the town page use).
4. **Smoke and CI** (`tools/smoke_map.py`, `tools/smoke_pages.py`, `.github/workflows/website.yml`,
   `.github/workflows/hail-store.yml`, `tests/test_website_workflow.py`, `tests/test_hail_workflow.py`): the sheet
   smoke at 390 and 1280 px (the table inside the first screen; every cell with a unit and a kind word; the exact
   Python words on three cells: Billings, Benchland cell 792,1998, the gate cell 797,1986, through
   `summary.describe_summary` on the same store; the fetch list per tap, each file under 100 KB gzip; the phone view at
   zoom 15 with every layer on under 650 KB gzip; zero off-site requests); the D49 wait step and its test; the daily
   job's timeout 150 and the joins backstop at 1.5 times the measured time (D42); the smoke flags the preview passes.
5. **Docs and record** (`docs/DECISIONS.md` D38's entry, `docs/DESIGN.md`, `docs/ROADMAP.md`, `README.md`,
   `AGENTS.md`, `website/templates/about.html`, `research/hail-history/validation-evidence/b5-verification.json`):
   the numbers (D54; 0 unplaced and the D44 table; the HW.A explanation; the combined store's figures; the browser
   gates once measured); D53's About radar line; the open items for Carson (the timer, the data repository with the
   496 MB raw and the measured packed size, the gauge distance, the swath extent, the counsel list) in one place.
Gates for the re-check: the full suite passes (0 failures, with the venv python); the self-test passes; the sample
build, the flag-off build identical to the base, the combined-store build with every flag; the sheet smoke and
smoke_pages pass in Chromium at 390 and 1280 px; the three-cell comparison exact; the fetch list and the 650 KB
budget measured; zero off-site requests; the words rules (tests/words_rules.py) over every WORDS string and the
built pages; the D13 greps; no em-dash and no banned name in added lines; the decision 7 audit (no owner, parcel,
place-type or building-use field read, stored or shown); the docs' numbers equal the measured ones.

- D59 **The store asset is named after the branch (from the B1 go-live, 2026-10-21).** When `main` is merged into
  `claude/hail-b5`, the merged job and build take B1's scheme: the job publishes `hail-store-<branch>.tar.gz` (slashes
  as dashes; `main`'s is `hail-store-main.tar.gz`), the build reads its own branch's asset through `HAIL_STORE_ASSET`,
  every build waits for the same commit's store job (the website job has `actions: read`; on `main` the wait only
  waits; a branch preview fails when its job did not succeed), and a store older than three days is a failed source.
  The old shared name `hail-store.tar.gz` is removed by `main`'s job (it held the address stage's data); the B2, B3
  and B4 previews that read it stay as recorded and are not re-run.

- D60 **Part B2 runs on the merged tree cbf5a12 (B3 and B4 merged into B5).** The smoke and CI owner does not build the
  D49 wait step: the B1 go-live on `main` (D59) carries the branch-preview wait, the branch-named asset, the one-step
  asset replacement, the stale rule and the scope; they reach this branch when `main` is merged in, before the push.
  The storm wording is "code -999 means outside radar coverage" (D45; "no radar coverage" is barred by the storm words
  test and a bare "coverage" by the D13 stem rule); the About rows that still say "no coverage" (the hail_swath row
  and the MESH row) take "no radar coverage" or "outside radar coverage" under D53. The sheet's order is the B3
  address block, then the B4 live line, then the history (the live line leads only when there is no address block).

## Supervisor rulings on the products review (2026-10-24 01:40 UTC; D61 to D65; the review is records/b5/journals/wf_44a6add9-a8e.jsonl)
The products owner's part B2 build (D53, D55, D56, D36; committed on claude/hail-b5 as bd3ae20) was reviewed (R1 to R14)
and the skeptics judged R1 to R5 before the pause: R1, R3, R4 and R5 confirmed by both, R2 refuted by both as the cause
of the Billings failure. The rulings:
- D61 **The tile list covers every cell of its tile (R3).** `stations.collect` builds a tile's candidates within
  RADIUS_MILES of the tile centre with no margin and caps each element's list at six, so a cell up to about 4.2 miles
  from the centre can miss a station within 40 miles of it: on the combined store 26,478 of 2,298,500 cell-element
  answers differ from the full rule (1.15 percent), 5,646 of them a false "No station within 40 miles" sentence
  (snowfall 2.0 percent); the 17 towns and the two gate points are right. Rule: a tile's candidate radius is
  RADIUS_MILES plus the distance from the tile centre to its farthest cell centre, computed per tile from the hail cell
  geometry and recorded in the tile list block as `margin_miles`; the per-element cap is removed (the list holds every
  passing station within that radius, nearest the centre first; `capped` stays in the format and is false for new
  lists; `tile_list_picks` still answers None for a capped list from an older store). `tile_list_picks` at any cell
  centre of the tile then equals `point_rule` at that cell: verify checks every tile's centre and four corner cells for
  every element (zero differences) and records the largest list, the file sizes and the time (the per-tile budget stays
  100 KB gzip). Named checks: cell 753,2230 snowfall names USC00248498 and USC00249048; cell 920,1899 precipitation
  names USS0010D35S second. The browser (owner 1) runs the same rule on the same files and prints the D32 sentence,
  never the "none" sentence, when a list cannot answer.
- D62 **The station pool is every United States GHCN-Daily station within reach (R4).** `parse_station_list` keeps
  Montana stations while D5, the sheet words and About say "within 40 miles"; 173 stations in Idaho, Wyoming, South
  Dakota and North Dakota with a 2026 record lie within reach of Montana tiles, and at least 2,543 tile-element answers
  at border tiles would read a false "No station" or "Only one station" (40 of the 173 tested; town picks do not change,
  0 of 85). Rule: the pool is every GHCN-Daily station within the D61 radius of any Montana tile, filtered by position,
  not by state; United States stations are read under the ghcn_daily row's terms; Canadian stations (identifiers
  beginning CA) within reach are candidates "not read" (no pull, no summary) that the tile lists carry in the unread
  part with the reason "in Canada; the terms for its data are under review", so the words name them when they lie
  nearer than the second pick (D32) and never count them as passing; the counsel list gains item 19 (GHCN-Daily's note
  on non-US data; the Environment and Climate Change Canada licence). The .dly files the review pulled
  (/home/user/hail-b5/out/b2p/products/skeptic-r4/dly, 185 files; skeptic2-r4/dly, 40) seed the cache; the monthly step
  pulls the union (D26) and the daily step the chosen stations only. "Montana stations" becomes "stations in Montana and
  the neighbouring states" in stations.py, the ghcn_daily row, summary.py's How-this-was-made line (owner 2) and the docs
  (owner 5); DECISIONS D25 ("station lists are never filtered by state") is consistent with the position filter.
- D63 **One pick rule (R5).** `stations.tile_list_picks` is the rule; `summary._Spot.chosen_from_tile_list` delegates
  to it (owner 2) with a parity test at the 17 towns and the cells 753,2230, 792,1998 and 797,1986 after D61; the
  browser's JavaScript mirrors it with a comment naming the Python function (owner 1).
- D64 **The sample fixture carries the station part (R2: refuted as the cause of the Billings failure; the gap
  stands).** The committed fixture has no `hail/tl`, `hail/sd` or stations block, so the sample's station rows read
  "could not be loaded" and the browser-against-module tests cannot exercise the picks. Rule: after D61 and D62
  rebuild the tile lists, the fixture is regenerated with `python -m website.joins fixture --out <scratch copy of the
  committed fixture> --from-store <store carrying the new tl/, sd/ and stations block>` and swapped into
  `website/data/hail-fixture` by one rename; the 62 KB budget (tests/test_joins.py near line 897, tests/test_hail.py
  near line 759) is restated to the measured size with the reason (the station part: the three tile lists and the
  summaries of the stations they name; 228,154 bytes measured before D61); the file-list, manifest and fixture_store
  equality tests of tests/test_hail.py follow the regenerated tree; tests/test_site.py's B2-only test (near line 4044)
  builds its store by removing the B5 parts from a copy of the fixture (owner 2). The sample's station summaries are
  real season summaries cut to the stations the lists name, marked `sample: true` in the block, like the three real
  MESH days of the B1 fixture; the sample block's `problem` text carries the D20 sentence (R14). The store the fixture
  is cut from is the candidate the supervisor adopts as the combined store (D50; the rebuilt joins index with the D55
  edges and sorted failures, the new tl/ and sd/, the stations block, every module's verify passing).
- D65 **The remainder of the products review.** R1 (build.py line 705 passes the town point as the spot; D56's
  summary half: gust_station measures from the town point and picks from the candidates at that point) and R6 are
  owner 2's; R7 (the About radar line, D53) and R8 go to the docs and record pass: gate B5-3 reads with the D18
  replacement, the Benchland snowfall picks are Buffalo 1.7 E US1MTFG0003 (20.9 miles) and Harlowton 11NW USC00243947
  (34.8 miles), because Lewistown 11 SSE USC00244978 has no snowfall report in the 30 days before the as-of date, and
  verify records the replacement; R9: `write_joined_store` (tests/test_site.py) gives the gate tile a station within
  40 miles of the gate cell and its joins index the format keys (owner 2), and the browser applies the radius
  (owner 1); R10 to R13 are applied by the products fixer after checking the evidence (the FW.W 169 comment cites the
  independent recount of the cached rows: 6 files, 262 events, 169 in the research window and 170 in the store window;
  the test_snowgrid comment lists the EXEMPT allowances of tests/words_rules.py; the Billings unit test's net label is
  WBAN; the tile_list_picks docstring says unread candidates are named within the radius). The store window (the
  1,826 SPC days ending on the as-of date, 2026-10-16, while the cache holds events to 2026-10-18) and the D8 begin for
  an event whose archived rows all close it stand; the three D55 edge events (HW.A TFX 30 of 2026 and HW.W TFX 34 of
  2026 in the research window only; FW.W TFX 19 of 2021 in the store window only) are recorded by verify and the record.

## Supervisor rulings on the first part B2 reports (2026-10-24 02:50 UTC; D66 to D68)
Fixer A (the station rule) and the site owner reported; both are accepted. The figures: the tile lists now cover every cell
of their tile (largest margin 3.823 miles; no cap; longest list 32; 4,597 files, 24,108,522 bytes, largest 1,549 bytes
gzip), parity with the point rule is zero at all 2,298,500 cell-element answers (the old lists were wrong at 26,478); the
pool holds 2,772 stations in the box, 1,325 in Montana, 229 read in the neighbouring states (WY 111, ID 81, SD 23, ND 14),
20 Canadian stations not read (AB 10, SK 6, BC 4); 800 summary files; town and gate picks unchanged (95 rows).
- D66 **map.json budgets.** The 140 KB raw gate applies to the B5 blocks (136,569 bytes measured with the history flag,
  under it). The full-flag file is 404,103 bytes because B3's blocks (addresses.tiles, roads.tiles, buildings.tiles,
  buildings.split) list every tile as membership sets the browser reads; that is accepted with the reason and recorded,
  and a compact encoding is a B3 follow-up in the roadmap, not part B2's work. The gate a user feels is the phone view at
  zoom 15 with every layer on, measured by the smoke, and budgets are written as byte counts: 665,600 bytes gzip for the
  phone view (the smoke's unit for "650 KB") and 100,000 bytes gzip per tile file (the joins constant for "100 KB");
  map.json's hail.budget block carries both numbers.
- D67 **The station refresh budget restated (D26, D42).** The daily refresh covers the chosen stations, now 437 files
  (421,389,540 bytes worst case; 437 conditional requests, a file whose Last-Modified is unchanged is not fetched); the
  monthly job covers the 800 summary files (695 rule files, 532,000,980 bytes, plus the 105 regression-only Montana
  files); the local rebuild measured 86 seconds with 57 downloads (28,327,860 bytes). Step timeouts stay 1.5 times the
  measured time once the branch run measures them; the docs carry these numbers (owner 5).
- D68 **Judgement calls accepted.** Lewistown Municipal (LWT, within 40 miles) replaces Billings as the gate and Benchland
  tiles' station in the invented test store (R9), and the station test's expected name follows. A tile list without
  margin_miles cannot answer: in Python the stations block answers through point_rule; in the browser the D32 sentence
  is printed, never "No station". The How-this-was-made sentence carries the Canadian clause. The ice-dam label reads
  "(days; a measured pattern, not ice dams)" with the kind word in the lead. The immutable combined store refuses hard
  links, so store copies are full copies (cp -a; one at a time). The 13 Canadian .dly files in the review folders were
  not seeded into the cache (D62: never pulled, never summarised). Cross-owner items received: WORDS_JOINS gains the
  sentence for an unknown NCEI newest date (records_newest_unknown; Python's voice, the browser fills it; products
  fixer C), WORDS_JOINS["warnings_row"] goes once map.js no longer reads it, and the browser reads no map.json key the
  build does not write (county_suffix is dropped unless Python provides a constant); the two map.js source-string tests
  in tests/test_site.py follow the browser's final lines (owner 2 after owner 1).

## Supervisor rulings on the second round of part B2 reports (2026-10-24 03:20 UTC; D69 to D71)
Fixer B, the browser builder (partial: the five-season table matches describe_summary at 120 row-cells on the candidate
store in Chromium at 390 and 1280 px; the eleven sections, the roof lines and How this was made are not built), the site
reviewer (F1 to F15) and the smoke builder reported. Fixer B's candidate store (/home/user/hail-b5/out/b2/products-fix/
fixer-b/store: 45,873 files, 508,204,168 bytes; every module's verify ok; the fixture regenerated at 305,024 bytes outside
hail/a/ against a 320 KB budget) is adopted as the combined store once the three part B2 workflows finish (D50, D64).
- D69 **Rejected candidates are named (F6).** The Product section requires "Benchland names the station used and says why
  Moccasin is not" and D5 shows every station's share. The tile list gains a `rejected` part per element: the candidates
  within the radius nearer than the second pick that failed the coverage or currency test, with id, name, miles, the
  share and the newest report date (MOCCASIN EXP STN, 3.2 miles, 324 of 2,192 days, is the named case); the station note
  names them in plain words ("MOCCASIN EXP STN, 3.2 miles away, is not used: 15 percent of the days 2020 to 2025 have a
  snowfall value; the rule needs 80.") and the browser mirrors it; farther rejected candidates are counted in one clause.
  Owners: products (stations.py and the tile list format), site (the note words), browser (the mirror).
- D70 **The phone budget excludes the picture frames (smoke).** The 665,600-byte gate counts the shell, map.json and the
  data shards of a zoom 15 view with every layer on; the radar, model, satellite and swath pictures are the pre-existing
  map layers, listed apart as B3 did (with them the view is 3,361,080 bytes more; the precipitation frames alone 1.2 MB).
  Measured now: 663,276 bytes, of which map.json's gzip grew to 80,186 bytes with B3's tile membership sets (D66). The
  gate stands as the target; if the figure exceeds it once the browser's sections land, the budget is restated to the
  measured figure with the reason and the compact encoding of B3's tile sets becomes the first follow-up (roadmap), never
  a cut of words or rows. The joins backstop in the daily job is 54 minutes (1.5 times the measured 35.6 end to end; the
  joins step's own deadline is 35). pyyaml is a test-only dependency in the Install step and the docs' command lines.
- D71 **The site review's findings.** F1 (confirmed): a failed ice-dam count prints the D20 unavailable sentence with the
  reason, never station_none. F2: the browser's station-unavailable sentence ends with the all-clear and the test constant
  STATION_UNAVAILABLE in tests/test_site.py gains it (D41); records_newest_unknown is a WORDS_JOINS word (products) that
  the browser fills. F3: the Snow lead names the station of each figure (the five-season snowfall total under D41's
  one-station rule). F4: a town page's warning rows are the town-point rows (hail/j/towns.json, D11 and D38) worded
  "covered this spot", and the explanation sentence says so; the sheet keeps the cell words; describe_joins with a town
  spot lists the point rows (products) and summary words them (site). F5: the ice-dam five-season count follows D41's
  one-station rule (named when one station covers all five seasons; else each season's count names its station and the
  five-season cell reads Data unavailable with the reason). F7: the five sentences the browser asks for (all_clear,
  county_note, coverage_one, partial_no_report, these_five) and the literals Python keeps for them become WORDS keys
  carried in map.json (site), and the browser reads them (browser); the same for nouns, report_types, record_types,
  auto_sources, element_names, family_nouns and the day words the browser owner listed. F8: the browser fills status
  from the station_status words. F9: the per-season unavailable sentences carry "for {season}". F10: a failed roof section
  shows the D20 sentence. F11: ruled by D66. F12: About drops the D13 stem: the hail_swath row reads "no radar coverage"
  (D60) and the address rows read "its completeness varies from county to county" (sources.py and the B3 addresses.py
  words, in the completion pass). F13 to F15 applied as nits (imports instead of copies; the docstring; "the deepest snow
  on the ground was {depth}"). Also: build.py's HAIL_FOLDERS_B5 copies hail/tl into the site (the browser requests it;
  every tap 404s without it) and the stations block carries tile_list "hail/tl/{tile}.json" (site); the two Python
  defects the browser owner found (the county-unavailable line appended twice in describe_joins; station_failed formatted
  without status) are fixed in Python, never mirrored (products and site); the fixture's joins block stays without the
  D55 keys (verify skips D55 on a store without VTEC counts); the joins ledger lives outside the store root. The browser's
  second round builds the eleven sections in the fixed order, the roof lines, How this was made, the unread and rejected
  station words, the gauge lines (F8 of the B5 words), the D57 flooding listing, the unit constants from map.json (no
  9/5, 32 or 1000 literal), the sentence-case heading, and the failure mode where only the station rows fail (D16, D32).

## Supervisor rulings on the browser and products reviews (2026-10-24 03:50 UTC; D72 to D74)
The browser reviewer (R1 to R17) and the products reviewer (RV1 to RV10) reported. The browser's table only built with the
Python constants injected by hand: on the real build map.json lacks report_types and the TypeError takes the whole table
down (R1, R2; D71's exports and failure mode); row notes never reach the page (R4); the records failure row loses its label
and reason (R5); 22 lines of literal sentences, units and constants remain (R6); the sections are not built (R11); unread
candidates print a placeholder (R12); the tile-list path and the unplaced flags read keys the build does not write (R13,
R14); a redraw sample at zoom 16 took 70.9 ms against a 30 ms budget on this loaded sandbox and is re-measured on the CI
runner before it counts (R16). Phone view measured 653,442 of 665,600 bytes with three layers (a lower bound). Rulings:
- D72 **The tile margin covers every point of the tile (RV3).** The margin was the distance to the farthest cell centre
  (3.823 miles at most) while a routed point near the tile's edge (a town point, a typed address) lies up to 4.239 miles
  from the centre: 64 of 91,940 element answers at routed corner points differ from point_rule (12 false "none"). Rule:
  the margin is the distance from the tile centre to the tile's farthest corner (the tile extent, computed per tile), so
  every point of the tile is covered by construction; tile_list_picks answers None for a point farther from the tile
  centre than the margin (a routing error, never a false absence) and its docstring says so; verify adds the four routed
  corners of every tile to the parity sample; the tile lists are rebuilt into the candidate store and the fixture is
  regenerated (products fixer C, then the supervisor adopts).
- D73 **The daily refresh covers the stations that could resume (RV4; D26 amended).** The daily set is every loaded
  station within reach of a tile with at least 80 percent coverage for some element, whether or not it is current for
  it (today 437 chosen plus 56 more), so a station that starts reporting again is picked up the next day, not a month
  later; a file whose Last-Modified is unchanged is still not fetched; D67's figures are restated with the measured set.
- D74 **The two About rows (RV5, F12, D53, D60).** The hail_swath row reads "-1 is missing and -3 is no radar coverage in
  NOAA's table" (the MESH row's words; "no radar coverage" is NOAA's term, D45); the address rows read "its completeness
  varies from county to county" (sources.py line 247 and the B3 addresses.py words); storm.py keeps "code -999 means
  outside radar coverage" for its own product. Nits applied by the products fixer: the docstring fragment (RV7); the
  current-year filter on every unread candidate, not only the Canadian ones (RV8); the sample's stations block carries
  every station its tile lists name, with the summary file where one exists (RV9); a fixture test ties tl/, sd/ and the
  stations block together (RV10). The browser's round 2 adds R4 (every row's notes rendered as describe_summary gives
  them), R5 (the unavailable-row call with its label, kind word and reason), R13 (summary.tile_list and
  summary.tile_list_format), R14 (the unplaced statements read the key the build writes, zone_unplaced_rows, or the site
  adds the shape the browser needs) and R17 to D71's list; the smoke adds R15 (a --history run without --hail-addresses
  fails readably).

## Supervisor rulings on the smoke review (2026-10-24 04:15 UTC; D75)
The smoke reviewer (F-01 to F-15) reported: the sheet smoke cannot read the CI preview's own hail/ copy (B4 writes hail/live
after the manifest check, so hail.load_store refuses the site copy), the tl copy and the six summary keys are missing (F-02,
F-03, owner 2), the browser's words and notes (F-04, F-05), the store adoption (F-06), the test constant and the words key
(F-07, F-08), and the smoke's own gaps (F-09 to F-15).
- D75 **The smoke reads the site's own store copy; budgets come from map.json; a step with its own deadline.** (a) The
  built site's hail/ is the store the CI smoke checks: hail.load_store (or the manifest check it runs) gains a documented
  exclusion for hail/live/, B4's live files that the manifest never lists (products owner, website/hail.py), and the smoke
  reads the site copy without --store in CI; a test covers the site-copy path. (b) The three-cell comparison is exact:
  a cell's text equals Python's words plus its coverage line, nothing appended (F-09). (c) The tap budget is map.json's
  hail.budget.tile_events_gzip_bytes (100,000 bytes, D66), never a literal 100 times 1024 (F-10). (d) A step that enforces
  its own deadline (the joins step, JOINS_DEADLINE_S of 35 minutes) gets a backstop of 1.5 times that deadline, 53
  minutes, so the step's graceful stop runs before the backstop; D42's "1.5 times the measured time" applies to steps
  without one; the test's header and the docs say so (F-11; D70's 54 is corrected). (e) F-12 to F-15 are applied as nits
  (the stale 60-minute comment, the usage line, console errors with their URL, the duplicated error list). The round-2
  smoke items: R15, the re-run on the adopted store with the browser's second round, and whatever the fixer leaves.

## Supervisor rulings on fixer C (2026-10-24 05:50 UTC; D76)
Fixer C fixed RV1 and RV3 to RV10 and the county-line duplicate, rebuilt the station part with the margin at the tile's
farthest corner (4.248 miles at most; parity 0 of 206,865 points, nine per tile), added the `rejected` part (201,004
entries; the longest passing list 33; the largest tile list 3,401 bytes gzip) and the daily set of D73 (495 files: 439 picks
and 56 in reach; 487,235,520 bytes worst case), and regenerated the fixture (94 files, 471,538 bytes outside hail/a/, 67
sample station summaries; budget 480 KB). Its candidate is /home/user/hail-b5/out/b2/products-fix/fixer-c/store.
- D76 **Fixer C's calls accepted.** The candidate to adopt is fixer C's store (fixer B's with the new station part). The
  station note uses the computed distance (MOCCASIN EXP STN is 3.6 miles from the Benchland point; D69's 3.2 was the
  cell-centre figure). The rejected part draws on every loaded station, lapsed inventories included (Moccasin is loaded
  through the regression set), and the daily reach follows the same rule (D73). `records_newest_unknown` is the phrase
  "an unknown date" filling {newest} in "NCEI's database runs to {newest}." The hail_swath row's second bare stem is
  reworded too ("A cell with no radar coverage is hatched"). D67's figures are restated to fixer C's (495 daily files,
  487,235,520 bytes; tile lists 4,597 files, 56,947,475 bytes raw; summary files 805; pool 2,778 stations, 21 Canadian
  not read; rule files 700, 537,226,020 bytes). The six new failures in tests/test_summary.py (synthetic tile lists
  without centre, margin_miles and rejected) are the site owner's round-2 item, as are the rejected words in
  chosen_from_tile_list, the STATION_UNAVAILABLE constant, JOIN_SITE_WORDS["unknown_date"] (unused) and the
  warnings_row requirement at tests/test_site.py line 2004 (the products owner removes the key once that test drops
  it). The products owner's round 2: D71 F4 (describe_joins reads its spot and lists the town-point rows from
  hail/j/towns.json with "covered this spot", plus the words and tests), D75(a) (hail.py's load_store exclusion for
  hail/live/, with website/hail.py added to its files for this item), and the warnings_row removal when the test allows.

## Supervisor rulings after the smoke fixer (2026-10-24 07:15 UTC; D77)
The smoke fixer applied F-01, F-09, F-10 and F-12 to F-15 with D75 (the sheet's words from the site's own hail/ copy, exact
cells, budgets from map.json, the backstop 53, console errors with their URL; 64 owner tests; a mutation check of 9 of 9);
the CI-equivalent smoke now fails only on owner 1's and owner 2's items (the table's keys, the tl copy, the words).
- D77 **The flag-off identity allows D53's word swaps.** The default build must equal the base commit's except for the
  two About lines D53 changed (the radar line "a blank area is not a statement about the weather" and the MESH row's
  "-3 (no radar coverage)") and D74's address words ("its completeness varies from county to county"): the test that
  compares the default build with its base commit's manifest (tests/test_site.py HailSwathLayers) pins those lines as
  the expected difference instead of failing on about.html, and B3's words test (tests/test_addresses.py, the D21
  sentence) follows the D74 words. The flag-off gate of the re-check reads the same way. Leftovers for the completion
  pass: the joins.py comment near line 346 that says the job has 60 minutes (it is 150); the test_addresses words test
  (D74) if the docs owner does not take it; tests/test_site.py's base-manifest test (owner 2's round 2).

## Supervisor rulings after the smoke round (2026-10-24 07:50 UTC; D78)
The smoke owner's check (34 agents) passed its own items (the site-copy store, exact cells, budgets from map.json, the
backstop 53, zero off-site requests, smoke_pages at every width, the self-test) and left the sheet gates to the browser's
and the site's second rounds. Three word questions it raised are ruled here.
- D78 **Words the smoke raised.** (a) The About SWDI row's "PROB is the probability of hail in percent" is NOAA's own field
  definition and stays as a quoted source definition ("NOAA defines PROB as ..."), which D13 allows; it is never used as a
  statement about a roof or an address. (b) The storm layer's sentence "Not observed hail or damage." predates B5 and
  says what the radar estimate is not; it stands under D52's reasoning (D13 governs the history words). (c) Station names
  are shown in title case as the product's words ("Billings WTP", "Harlowton 11NW", "W Glacier", "Buffalo 1.7 E"; the
  direction and distance tokens keep their case), decided once in Python: stations.py writes the display name into the
  tile lists, the summary files and the stations block (the GHCN name kept beside it as ghcn_name), so the browser and
  the summary show the name as given and never re-case it; the gust rows keep the IEM station names as the source gives
  them; tests follow the display names. This is a products item for the completion pass (a tile-list rebuild into the
  candidate and a fixture regeneration follow). (d) The tile-list path and format live in map.json's summary block
  (summary.tile_list, summary.tile_list_format), which the browser reads (R13); the stations block need not repeat them.

## Supervisor rulings after the round-1 fixers and the products round 2 (2026-10-24 08:20 UTC; D79)
The site fixer applied F1, F3 to F7 (site halves), F9, F10, F13 to F15 and the D71 to D77 items (the tl copy, the stations
block keys, the WORDS keys the browser asks for, STATION_UNAVAILABLE, the base-manifest test by sentences); the browser
fixer applied R1, R3 to R6, R12 to R14 and R17 (every table part builds on its own, every word from map.json, the notes
under the table, the rejected and unread lines); the products round-2 fixer restored the sheet's cell words beside the
town-point words (its F1) and the suite stands at one failure (the B3 words test that follows D74). Rulings on what they
asked:
- D79 **Four calls.** (a) Two sources place the Billings airport 0.1 mile apart (the IEM gust station and the GHCN
  station): each row keeps its own source's distance, and How this was made says in one sentence that a station's
  position comes from its source and two sources may place one airport a few hundred feet apart; no mapping table.
  (b) A town page's storm and flood count sentences name the five-season count and the partial season's count
  separately ("19 in the five seasons; 2 more in 2026-27 so far") while the rows list every event in the window newest
  first (site owner). (c) The desktop sheet may widen to at most 640 px (60 percent of the view) while the table shows,
  so the columns read; the phone layout stays the one-card-per-row reflow; the reviewer judges the first screen at both
  widths; the row heads carry the unit beside the kind word as the town page does; the notes print once each under the
  table. (d) WORDS_JOINS["warnings_row"] is removed with its uses in tests/test_joins.py (the B2 placeholder test is
  superseded by the B5 keys; products, completion pass); the joins ledger stays at <store>/ledger/joins.jsonl, outside
  hail/ and outside the packed asset (no change). The browser's round 2 is the eleven sections, the roof groups and How
  this was made (R11), with summary.how_made and the section data written by the site owner, and the remaining
  placeholders (county.short_names; the station_status words read where the build writes them).

## Supervisor rulings after products round 2 (2026-10-24 08:50 UTC; D80)
Products round 2 (24 agents) is complete: the town-point warning rows (D71 F4), the hail/live exclusion (D75(a)), the
sheet's cell words restored; its check passed every products gate (D61 full-cell parity 0 of 2,298,500; the fixture equal
to a fresh run; the 17 town pages' count notes equal to their rows). The fixer C candidate is adopted as the combined store
at /home/user/hail-b5/out/combined/store (45,878 files, 541,075,953 bytes; the previous store removed). Rulings on the
check's questions:
- D80 **Points and figures.** (a) Billings has one point: towns.json's (45.7833, -108.5007). stations.GATE_POINTS and
  gate B5-3 follow it, so the Billings gate distances are the computed ones from that point (WTP about 1.2 miles, the
  airport about 2.7 miles; the test fixes the numbers from the computation, never by hand); the Benchland point stays
  47.08, -110.02. (b) A distance is always from the point in use: the sheet measures from the clicked cell's centre
  (MOCCASIN EXP STN 3.2 miles at cell 792,1998) and a town page from the town point (3.6 miles from the Benchland
  point); both are right and the words say "from this spot". (c) D79(a)'s separation of the two airport positions is
  about 0.19 miles, a fifth of a mile; the How-this-was-made sentence says "a few hundred yards". (d) The warnings
  no-outline clause uses the cell words on the sheet and the spot words on town pages, like the heading and the count
  note. These are completion-pass items (products for (a) and (d); site for the words of (b) and (c)).

## Supervisor rulings after the docs round (2026-10-24 09:15 UTC; D81)
The docs owner (42 agents) wrote the DECISIONS bullets for D44 to D76, the ROADMAP status and open items, the README and
AGENTS command lines, DESIGN section 12, About's D53, D19 and D62 lines, addresses.py's D74 words and the record with
every gate's round-2 status; several items stay partial until the browser round and the re-check give the final
numbers. Its questions:
- D81 **Five answers.** (a) The counsel list's item 19 is the legal review's disclaimer question; the GHCN-Daily non-US
  data note and the Environment and Climate Change Canada licence are item 20 (D62 and D64 read "item 20"). (b) The
  State Library's Placement value ("Parcel" as placement class L; "at the parcel" in the words) describes where the
  address point was placed, not a parcel identifier or any parcel attribute; decision 6 and D12 stand and the words
  stay. (c) tests/words_rules.py is the one forbidden list: "radar coverage" and "no radar coverage" are allowed (D45),
  the R20 title appears only as the About references citation (D46), and a source title such as "FEMA P-957, Snow Load
  Safety Guide" carries no listed stem, so no exemption is added for it. (d) The SWDI row reads "NOAA defines PROB as
  the probability of hail in percent" (D78(a); products, sources.py). (e) The roadmap and the record name the branch and
  the pull request, never a WIP commit hash (the squash changes it); the D49 wait step is recorded after the merge of
  main brings it (D59, D60); the two round-1 tests in tests/test_site.py that pin the old sheet strings (the radar days
  before the joins; the six-section template slots) follow the browser's round-2 structure (site owner).

## Supervisor rulings on the round-2 reviews (2026-10-24 10:00 UTC; D82)
The round-2 reviewers found 14 findings each. The browser's six blocking items are the missing summary.section_data block
(site), the two round-1 tests that pin the old sheet strings (site, D81(e)), the B3 words test (D74, completion pass),
the phone view over 665,600 bytes (below), and the smoke's sheet reader (owner 4's round 2). The site's blocking item is the
history-flag map.json at 153,127 bytes, with a gate test rewritten to measure six blocks and omit joins: a gate is never
met by narrowing what it measures. Rulings:
- D82 **Budgets, a zero, and the joined lines.** (a) The history-flag map.json gate is restated to 163,840 bytes raw
  (160 KB) with the reason: the words, orders and section data the browser reads from map.json instead of carrying
  literals (D29, D41) are 132 summary words, the joins words and summary.section_data; the test measures the whole
  file with the history flag, never a subset of blocks; the every-flag figure is recorded beside it (D66).
  (b) The phone view at zoom 15 with every layer on measured about 674,000 bytes gzip once the sections landed; as D70
  said, the budget is restated, to 700,000 bytes gzip, with the reason (the sheet's words and sections from map.json;
  B3's tile membership sets at 80,186 bytes gzip, D66), in map.json's hail.budget, the smoke and the docs; the compact
  encoding of B3's tile sets is the first follow-up and would recover most of the difference; no words or rows are cut.
  (c) A partial radar season never reads as zero: the row "Days with a radar hail estimate of 1 inch or more" follows
  D37's rule (a zero only at 95 percent coverage; otherwise "Data unavailable" with the days missing), the "No radar
  estimate of 0.25 in or more" sentence appears only at 95 percent coverage, and the "Largest radar hail estimate" row
  shows the largest value over the days present with its coverage line (2021-22 has 109 days missing: 108 before the archive's first day, 17 Oct 2021, and one inside the window; corrected under D87(i));
  Python first (summary.py), the browser mirrors; B1's own day list on town pages is unchanged.
  (d) The sheet's joined sections keep every line describe_joins gives for the cell (the freshness lines, the NCEI
  flood cause line, the zone-switch line, the no-county-product line with its evidence caveat, the implausible-count
  line), computed by the browser's mirror from the per-tile files and map.json's words, as the town page carries them;
  the B2 smoke's expectations for them stand. Also ruled: unavailable roof lines lead with their kind word (site F2);
  "from this spot" is the phrase on every page, the spot being the town point on a town page (D80(b), site F5); a
  partial season with no valid day keeps its count and days missing beside the D20 sentence (site F6); every section of
  a sample build carries the sample word (browser F11); sumSharePct rounds half to even as Python's round() does and
  takes its scale and step from map.json (browser F10).

## Supervisor rulings after the round-2 fixers (2026-10-24 13:35 UTC; D83)
The round-2 site fixer applied its F1 to F8 (the map.json gate measured whole against 163,840 bytes, the phone budget
700,000, "from this spot" everywhere, "a few hundred yards", unavailable roof lines led by their kind word, the partial
season's count kept, thousands separators in Python, the two old pins) and the browser fixer its F10 to F12 (round half to
even from map.json's percent rule, the sample word on every section, the rows-shown threshold from map.json). The browser
review's F1 (summary.section_data, owner site) was filed in the browser's pipeline, so the site fixer never received it:
the eleven sections still read placeholders on the real build. It heads the completion pass with the other cross-owner
items (summary.rule.percent; nouns.days; hail.joins.show_first; the browser's kind-word fill and thousands separators;
the smoke's DOM reader).
- D83 **Two browser calls.** (a) A section shows its first rows and a "Show all n rows" control, a browser-only need for
  a phone sheet with long lists; the threshold is map.json's hail.joins.show_first (the site writes 10), every row is
  rendered in the DOM so the text comparison and the smoke read all of them, and the control only toggles visibility.
  (b) The season rule's 95 percent and the unit scales come from map.json (summary.rule's season share; summary.units
  with a scale per unit), never from literals in map.js; a parity test covers the season rule as the share rule has one.

## Supervisor rulings on the display names (2026-10-24 14:30 UTC; D84)
The products completion builder wrote the display names (D78(c)) into the adopted store (805 summary files, 4,396,079
bytes; tile lists 67,832,479 bytes raw, largest 3,804 bytes gzip; the stations block 826 entries; 0 names differ from
display_name(ghcn_name)), moved the Billings gate to towns.json's point (WTP 1.2 miles, the airport 2.7), removed
warnings_row, fixed the SWDI row and the joins comment, and regenerated the fixture (485,066 bytes outside hail/a). Its
two questions:
- D84 **Names.** (a) The IEM gust names keep B2's rule (joins.py near line 1135 title-cases an all-capital IEM name, so
  "Billings/Logan Intl"), which is what D78(c) meant by "as the source gives them" after B2's own step; no rebuild of the
  joins for names. (b) In the GHCN display rule, initialisms keep their capitals (WTP, AP, RS, NP, ASOS, NWS, FAA, USGS,
  SNOTEL) and abbreviations of words are title-cased like words (INTL as Intl, EXP as Exp, STN as Stn, FT, ST, MT, CO, RCH,
  LK, CRK, MTN), so "Billings Intl AP" and "Moccasin Exp Stn"; compass and distance tokens keep their case (11NW, 1.7 E,
  SSE). If the products pass's check shows INTL, EXP or STN still in capitals, the fixer of the re-check round applies
  this rule, rebuilds the station part into the adopted store and regenerates the fixture; the summary and the browser
  show the names as given.

## Supervisor rulings after the products completion pass (2026-10-24 16:00 UTC; D85)
The products completion pass (18 agents) is complete: the display names are in the adopted store (826 stations, 805
summary files, 0 names differ from the rule), the Billings gate reads from towns.json's point (WTP 1.2 miles, the airport
2.7), warnings_row is gone, the fixture equals a fresh run (485,066 bytes outside hail/a), and the full suite passed in its
final run (1,896 tests, 0 failures). Left: D84(b)'s abbreviations (INTL, EXP and STN still in capitals in 10 names), the
second Billings point in snowgrid.py and one gauges test line (D80(a)), a test for the SWDI sentence and one for the
tile-list budget, and a question on About's contract text.
- D85 **About is inside the words gate.** The built About page and the About-visible fields of sources.CONTRACTS follow
  tests/words_rules.py like every other page text: a test scans those fields; "fails" becomes "does not pass" or "is left
  out" (the nohrsc_season_snowfall and hail_history rows), the ghcn_daily timing sentence says plainly when the archive
  values replace the preliminary ones, and the hail_swath row's "not damage" clause stays as the allowed negative form
  only if words_rules exempts it, else it is reworded without the stem. The products owner applies D84(b) and these in
  one pass (a station rebuild into the adopted store, the fixture regenerated, the exact new names reported so the site's
  test pins follow), then the store is marked immutable again.

## Supervisor rulings on the words gate over About (2026-10-24 17:05 UTC; D86)
D85 put the About page and the CONTRACTS rows inside the words gate; the products leftovers builder then reworded two
older rows and the reviewers found the conflicts: the storm layer's sentence (D78(b)) was reworded, the satellite row's
"clear sky" became "cloud-free sky" without its test, the R9 title carries the stem "safe", the State Library's name
carries "Structures", and B3's outside-grid sentence says "no hail". Rulings:
- D86 **Six words calls.** (a) D78(b) stands: the storm_levels row keeps "A radar estimate, not observed hail or damage."
  (the products fixer restores it; tests/test_storm.py's pin holds) and tests/words_rules.py exempts this one
  pre-existing negative sentence, as D52 exempts the footer. (b) The satellite row reads "never drawn as cloud-free sky"
  (the stem rule applies to a row B5 shows on About; "clear" is the all-clear stem); tests/test_site.py's pin follows
  (site), and website/satellite.py's docstring is not page text and may keep its words. (c) About's pre-existing prose
  inside the storm-layers block and the B3 terms block follows words_rules where the fix is a word swap that keeps the
  meaning (D53's pattern); a sentence that cannot be reworded without changing what it says is exempted by listing it in
  words_rules with the ruling cited; the words owner decides line by line and reports each. (d) D46 covers source titles:
  the About references list may quote a title that carries a stem ("freeze-thaw damage to roofs", "Snow Load Safety
  Guide"); words_rules exempts the quoted titles of that list (R9 and R20 named), nowhere else. (e) A source's proper
  name is a citation: "Montana State Library Structures and Addresses Framework" joins "USA Structures" in the exemptions.
  (f) B3's outside-grid sentence reads "This point is outside the hail grid's Montana outline; the history does not cover
  it." (website/addresses.py's words; the browser shows the words as given). These are the words owner's items in the
  completion round (files: website/templates/about.html, website/addresses.py's About and outside words,
  tests/words_rules.py, website/sources.py's storm_levels row, tests/test_storm.py and tests/test_site.py's two pins).

## Supervisor rulings on the round-3 reviews (2026-10-24 19:05 UTC; D87)
The round-3 reviewers found 10 (site), 14 (browser) and 6 (smoke) findings; the skeptics judged the site's ten and the
browser's F-01 to F-11 (F-04, F-05, F-06 and F-08 to F-10 survive both; F-03, F-07 and F-11 refuted; F-12 to F-14 and the
smoke's six still queued at the time of these rulings). The round-4 products names are adopted into the combined store
(277 files, three names, D84(b)). Rulings:
- D87 **Round-3 calls.** (a) An unavailable or held roof line carries its kind word once: the line leads with the kind word
  (D82, site F2; R1-F1) and the label's parenthetical keeps its unit word and drops the kind word (F-13: "Station reading:
  Peak gust of 50 knots (58 mph) or more (days). Data unavailable ..."); Python first (summary.py), the browser's histLine
  mirrors, the town page shows the same line. (b) D41 covers the town page's count sentences: a count sentence that names a
  partial season ends "This is not an all-clear." as the sheet's partial line does (R1-F8); the browser mirrors from the
  same words. (c) The picture status lines in map.js ("No ... picture in this update. Not an all-clear.", "The ... picture
  didn't load. Not an all-clear.", "Sample radar", the NOAA names; F-10) predate B5 and are live on main with the storm
  layers; they move to map.json words in a follow-up recorded in ROADMAP (with the D41 sentence replacing "Not an
  all-clear."); this PR does not widen into the storm-layer status code. (d) Every rule the browser applies comes from
  map.json: the season bounds (1 July to 30 June) are written once by Python (summary.rule.season with start_month 7,
  start_day 1, end_month 6, end_day 30, or an equivalent block the site owner names and documents) and read in place of the
  literals near map.js lines 3400 and 3407 (F-12); the inch rounding scale is summary.units.in.scale, not the literal 100
  (F-08, map.js near line 2396; the pin at tests/test_site.py near line 1687 follows); the season-rule parity test asked by
  D83(b) exists (F-09) and covers the 95 percent rule at every day count and the bounds. (e) The real-store parity tests
  (HAIL_PARITY_STORE) run in website.yml after the store download, beside the Chromium smoke, with the variable set to the
  extracted store and only when that store carries the B5 folders (hail/tl present); the offline test step stays offline
  (F-14). (f) The smoke's zoom_on_spot zooms to the level the check needs, read from map.json's layer rule (the swath layers'
  minimum zoom), not a fixed count of wheel steps, and keeps the spot on screen clear of the panels; the phone swath checks
  then report a result, never "not checked" (S-3; the timeline is the panel F-03 did not name). (g) The eleven section ids
  are pinned: the smoke takes the order from website.summary's constant and asserts map.json's section order and the sheet
  equal it (S-5); the three-cell comparison reads every row of every section, never a label list (S-4). (h) Test comments
  carry no measured sizes; they cite the budget constant and b5-verification.json (R1-F3); the fixture five-cell test names
  the cells the fixture lacks through subTest and skipTest with the present set asserted (R1-F2); the every-key test
  follows both the S.-prefixed aliases and direct h.summary reads (R1-F6); the zone fixture's field is wide enough for
  MTZ002 (R1-F9; tests/test_joins.py near line 601, one line, the site fixer's). (i) R1-F10 corrects D82(c) in place:
  2021-22 has 109 days missing, 108 before the archive's first day (17 Oct 2021) and one inside the window. (j) The file
  split for the completion fixers: words owns about.html, addresses.py and buildings.py (the About words and the
  outside-grid sentence, F-04, F-05, D86(c) to (f)), tests/words_rules.py, sources.py (the storm row, D86(a)),
  tests/test_storm.py (its pin) and tests/test_addresses.py (the D74 expectation and any outside-grid pin); site owns
  build.py, summary.py, tests/test_site.py (every pin, the satellite pin near lines 395 to 396 included, D86(b), F-06),
  tests/test_summary.py and tests/test_joins.py (line 601 only); browser owns map.js, map.css and map.html; smoke owns
  tools/smoke_map.py, tools/smoke_pages.py, the two workflow files and their tests. A fixer never edits another's file; a
  change needed there is listed under needed from others. (k) The words, site and browser fixers run now; the smoke fixer
  runs once the smoke skeptics have finished (their verdicts are the record); the gate re-check runs once after all four.
  The b2r4 products check's other leftovers go to the docs pass (the D56 cause line, the measured figures, the Benchland
  SNOW second pick Harlowton 11NW, the file list with hail.py and snowgrid.py) and to the browser (sumTilePicks mirrors
  stations.tile_list_picks as it stands: the rejected part, D69; None for a block without centre or margin_miles and for a
  point beyond the margin, D72; the D32 sentence, never a "none" sentence).

## Supervisor rulings after the D87 audit (2026-10-24 20:05 UTC; D88)
A read-only audit of D87 against D1 to D86 (record: /home/user/hail-b5/out/b2r3/supervisor/d87-audit.json) found one
blocking clause (D87(e)) and a dozen minor conflicts or ambiguities. Amendments:
- D88 **D87 amended.** (a) D87(e) is replaced: website.yml has no store download step (the build fetches the asset itself
  into a temporary directory, and tests/test_website_workflow.py pins that the workflow never passes --hail-store). The
  parity step runs after the build step on branch pushes only (the Chromium smoke's guard), with HAIL_PARITY_STORE set to
  the built site folder (_site, the site copy of the store, D75(a)); it runs whenever the step runs and fails when
  _site/hail/tl is missing (never a silent skip); after the merge of main it follows the D59 wait like every later step.
  (b) D87(a) read with the kind-word list: a line with a source leads with its source's kind word; a held line with no
  source leads with "Data unavailable", its kind word ("Data unavailable: Roof ponding. ..."); "Data unavailable" after a
  source lead is the state, not a second kind word; the season template "Data unavailable for {season}: ..." is unchanged;
  a held line's parenthetical carries the reason (D41); a station line's parenthetical keeps the unit word and drops the
  kind word. (c) D87(c) narrowed: the two sentences at map.js lines 3361 and 3362 end with the D41 sentence "This is not an
  all-clear." now (a two-string edit by the browser fixer; map.js line 1320 and build.py line 562 already do); the labels
  at line 3366 stay; moving the picture status sentences into map.json words (SWATH_SITE_WORDS no_picture and a
  picture_failed key) stays the ROADMAP follow-up; the storm layers are merged behind --storm-layers and off on main, not
  live on main. (d) D53's last sentence now reads: older About prose may be word-swapped where the meaning holds (D86(c));
  nothing else is rewritten. (e) D87(j) supersedes the fixer named in D86(a) and the owner list at the end of D86; words
  owns sources.py's storm row and the satellite row's missing text (both already as ruled); website/satellite.py's
  docstring line 11 takes "cloud-free sky" (the supervisor's one-line edit, done). (f) D41 is extended to count sentences
  (D87(b)); the D79(b) example reads "19 in the five seasons; 2 more in 2026-27 so far. This is not an all-clear."
  (g) D86(d) amends D81(c): the R9 title carries the safe stem and is exempt as a quoted citation (D46). (h) D87(f)
  corrected: map.json has no swath zoom key and none is added (the browser applies no minimum zoom to the swath layers);
  zoom_on_spot's zoom applies to the swath checks only and targets GATE_MIN_ZOOM (10, D17, tools/smoke_map.py line 2506);
  the phone budget stays measured at zoom 15 (ADDRESS_GATE_ZOOM); the panels that can cover the spot are the fixed-position
  elements of map.html (the timeline, the layer menu, the sheet, the card chip, the search box); the smoke pans the spot
  to the visible centre of the map before reading. (i) D87(g) made concrete: summary.py defines
  SECTION_ORDER = tuple(SECTION_KEYS) (the eleven ids in the brief's order) and the inline tuple near line 2863 uses it;
  build.py writes hail.summary.section_order; the smoke imports website.summary.SECTION_ORDER and asserts the key and the
  sheet's history section sequence equal it; hail.joins.section_order (the six joined parts) stays. (j) Each file has one
  owner: tests/test_hail.py, tests/test_stations.py, tests/test_snowgrid.py, tests/test_climate.py and website/stations.py
  are the products owner's and are not edited in this round unless a products fixer is named; the docs pass owns the B2
  step 5 files; the season-rule parity test lives in tests/test_site.py (site). (k) D87(d) reads: every rule and threshold
  the browser applies comes from map.json; sentences are governed by D41 and (c). (l) The season block is
  summary.rule.season as summary.py already writes it (SEASON_RULE, line 151, written at line 3164); the alternative is
  struck; the browser reads it; the parity test covers the thresholds 347 of 365 and 348 of 366 days (2023-24 has 366) and
  the bounds; the inch rounding reads both summary.units.in.scale and summary.units.in.decimals (UNIT_SPEC: 100 and 2), so
  map.js line 2396 keeps no literal. (m) The record of the skeptics' verdicts is
  /home/user/hail-b5/out/b2r3/supervisor/round3-reviews-and-verdicts.json; the rulings on S-3 to S-5, F-12 to F-14 and
  D-1 hold whatever the skeptics decide unless a pair refutes the code fact a ruling rests on, in which case the supervisor
  reviews that ruling before the smoke fixer runs. The adopted names: "Great Falls 16St", "Eastend Cypress (Aut)" and
  "Rockglen (Aut)" changed; "Billings Intl AP", "Moccasin Exp Stn" and "Lister" unchanged since round 3; stations verify
  37 of 37 and joins verify loaded on the adopted store at 18:58 UTC; the store is immutable again. (n) D29 gains: browser
  words and thresholds come from map.json (B2 build list step 1). (o) The docs pass also carries: DESIGN.md line 882's
  phone budget (700,000; D-1), the D87(c) follow-up in ROADMAP, the "clear sky" wording in DECISIONS.md line 514 and
  DESIGN.md lines 279 and 701 (cloud-free sky), and the record of the adoption. (p) One Python source for the sheet's text:
  summary.describe_summary with town None returns the table, its notes and the eleven sections with every row and note as
  the sheet renders them, and build.history_view uses the same for the town page; if section rows are built in
  build.history_sections today, the site moves the row text into summary (or exposes summary.describe_sheet that returns
  all of it) so the smoke and the parity tests compare against one function (S-4). (q) website/swath.py's sentence "It is
  an estimate, not observed hail and not damage." (a B4 sentence on the Map page) is exempted in words_rules by exact text
  like the storm row (D86(a)); swath.py is not edited. (r) A test pin on browser code asserts behaviour, not an
  expression: the hailInches pin asserts no literal 100 or 2 in the function and a read of units.in.scale and
  units.in.decimals; the budget pin asserts build.PHONE_GZIP_BUDGET equals map.json's hail.budget.phone_gzip_bytes equals
  700,000. (s) The partial count sentence's tail is written once in the words the browser reads (summary.section_data
  words, key named in the site's check) and both surfaces print it from there. (t) No browser item is needed for S-3's
  map.js lines 318 to 321 (the smoke fixer reads them) or for the held lines of R1-F1 (the browser prints held words as
  map.json gives them, map.js near line 5500). (u) Run 2 carries the smoke entry and two follow-up entries, site-2 and
  browser-2, for (c), (i), (l), (p), (r) and (s) and for whatever run 1's checks leave; a placeholder never ships: the
  re-check fails on any.

## Supervisor rulings on the run-1 checks (2026-10-24 20:20 UTC; D89)
The words fixer (20 of 24 items done; /home/user/hail-b5/out/b2r5/words/check.json) and the site fixer (17 of 19;
/home/user/hail-b5/out/b2r5/site/check.json) finished; the open items wait on the browser fixer (map.js lines 2396 and
3399 to 3408) and on files no fixer owned. Rulings:
- D89 **Run-1 calls.** (a) NWS forecast and observation words are outside the words gate: the forecast card's "chance of
  rain or snow" (index.html line 56, sources.py flags_for, map.js lines 2108 and 2117), the NWS text ("Clear", "Chance Rain
  Showers") and the sample's NWS wording (sample.py) are the forecast product, not history text; D13 governs the history
  words; the words scan excludes them; nothing changes there. (b) map.js line 175, "the file was incomplete or damaged",
  reads "the file was incomplete or unreadable" (browser-2). (c) map.js line 2131's literal "That is not an all-clear."
  in the no-alerts line predates B5 (the alerts feature); it joins the D87(c) follow-up and is unchanged now. (d) The B3
  streets "unavailable" lines (streets.py lines 354 and 365) end with "This is not an all-clear." like addresses.py's and
  buildings.py's (D41; the three lines sit together on About); words-2, with tests/test_streets.py. (e) D88(q) is
  withdrawn: swath.py's WORDS_SWATH strings (lines 108, 110 and 143 to 144) read "not observed hail and not an inspection"
  (the sources.py hail_swath row's form and About line 29's), the docstring line 11 follows, and no words_rules exemption
  is added for it; tests/test_swath.py line 751 follows (words-2) and tests/test_site.py lines 3491 and 3615 follow
  (site-2). (f) Run 2 is smoke, site-2, browser-2 and words-2 in parallel once run 1's browser fixer and the smoke
  skeptics finish; ownership as D87(j) and D88(j), with words-2 owning website/swath.py, website/streets.py,
  tests/test_swath.py, tests/test_streets.py and tests/words_rules.py. (g) The one full-suite failure of run 1
  (tests.test_site SummaryContract.test_the_browser_reads_the_season_bounds_and_the_inch_scale_from_map_json) is the
  site's new pin waiting on the browser fixer's map.js change; it is not a defect of the pin.

## Supervisor rulings after stopping the round-3 workflow (2026-10-24 20:45 UTC; D90)
The round-3 workflow (hail-b5b2-round2.js) carried fix and check stages after its skeptics. Its site fixer ran after
run 1's site fixer (20:20 to 20:33 UTC; it read D88 and fixed R1-F1 as D88(b) says: held lines read "Data unavailable:
{label}. {reason} This is not an all-clear."; full suite 1,933 tests OK with the store set; self-test PASS) and its browser
and smoke fixers started while run 1's browser fixer was editing map.js. The supervisor stopped the workflow at 20:40
UTC; the round-3 record (/home/user/hail-b5/out/b2r3/supervisor/round3-reviews-and-verdicts.json) holds every verdict
and the site fixer's report. Rulings:
- D90 **After round 3.** (a) D88(b) read as written by the round-3 site fixer: a held line's reason follows the lead as a
  sentence ("Data unavailable: Roof ponding. No public weather record shows water on a roof. This is not an all-clear.");
  no parentheses are added to held lines; the station line keeps its unit parenthetical without the kind word.
  (b) Measured by the round-3 site fixer on the adopted store: map.json with the history flag 162,347 bytes raw (32,417
  gzip); every flag 464,345 bytes raw (88,510 gzip); the headroom under the 163,840-byte gate is 1,493 bytes. The gate
  stands (D82(a)); the docs record the figures and the headroom, and ROADMAP names the next growth of the history blocks
  as a budget decision (a restated gate with its reason, or fewer words in map.json), never a silent breach.
  (c) tests/test_site.py line 403 carries a pre-existing em-dash in a test string: site-2 removes it, changing the source
  text it pins in the same way if it pins one (no em-dashes in repository files). (d) The browser-2 fixer reconciles
  map.js: it reads run 1's browser check and the current file, keeps every change that follows D87 to D89, and reports
  any edit it cannot attribute to an item (the stopped round-3 browser fixer may have left partial edits); node --check
  and the HailHistory tests gate its final state. (e) Run 2 starts when run 1's browser fixer has finished; no other
  workflow edits the worktree while run 2 runs.

## Supervisor rulings on the run-2 site, browser and words checks (2026-10-24 21:25 UTC; D91)
site-2 (/home/user/hail-b5/out/b2r6/site/check.json): SECTION_ORDER and hail.summary.section_order written; summary.describe_sheet
is the one Python source of the sheet's text (keys summary, radar, joined, built, section_order); SECTION_WORDS all_clear in
section_data.words; the roof label "Hail signatures within 2 miles (days)"; the em-dash placeholder replaced; map.json
162,512 bytes raw with the history flag (headroom 1,328), 464,566 with every flag. browser-2: one line (a missing held
word shows the placeholder, never "undefined"); everything else in place. words-2: swath and streets words done; the
D89(a) exclusion is a documented FORECAST tuple in words_rules.py; About and Map scan clean. Rulings:
- D91 **Reconciliation after run 2.** (a) tests/test_site.py near line 3176 follows the smoke's budget source: the pin
  asserts that the smoke reads the phone budget from map.json's hail.budget (whatever name the smoke check gives), not a
  module constant (site-3, after the smoke check). (b) The three pins that count the workflow's unittest lines (near
  tests/test_site.py 1885, 3161 and 3311) follow the smoke's final website.yml (site-3 verifies against the file as
  landed). (c) The SPC reports page (website/templates/reports.html lines 7 and 57, live on main before B5) joins the words
  gate because the scan reads built pages: "No report is not evidence that no hail fell." reads "No report is not the
  same as no hail."; "No hail or wind reports in or near Montana for this day." reads "No reports of hail or wind in or
  near Montana for this day; that is not the same as no hail."; the pin near tests/test_site.py line 596 follows (site-3).
  (d) tests/test_words_rules.py gains the D89(a) pins the words-2 fixer listed (pass and fail cases of the FORECAST rule)
  (words-3). (e) Pre-existing em-dashes outside the B5 files (gridded.py, sample.py, satellite.py, index.html, town.html,
  style.css, test_gridded.py, docs, payload) stay in this PR; the rule covers the lines B5 adds; ROADMAP lists the sweep as
  a follow-up. (f) website.yml's offline unittest module list names tests.test_words_rules, with the pin in
  tests/test_website_workflow.py (smoke-2). (g) The browser keeps reading summary.sections (the same eleven ids, from
  map.json): no switch to hail.summary.section_order is required; the smoke asserts both equal summary.SECTION_ORDER.
  (h) The partial count tail: the browser prints the table's partial line from summary.words.partial_counts and the town
  page from SECTION_WORDS all_clear through section_data.words; both come from map.json and carry the same sentence; the
  Recheck's three-cell comparison is the test that they agree. (i) Run 2b (site-3, words-3, smoke-2) runs after the smoke
  fixer's check lands; then the Recheck (run 3).

## Supervisor rulings on the smoke check (2026-10-24 21:40 UTC; D92)
The smoke fixer (/home/user/hail-b5/out/b2r5/smoke/check.json) landed the DOM reader (textContent), the SECTION_ORDER
checks, the every-row comparison against describe_sheet, the budgets from map.json, the swath zoom and centring, and the
parity step; the smoke passes on the adopted-store build at 390 and 1280 px; measured: phone view 682,102 bytes gzip
(budget 700,000), B3 files 267,789, largest B5 tap file j/e/r0092_c0214.json 18,052 bytes gzip, largest tap file of any
kind b/r0092_c021500.json 40,074 (budget 100,000). The parity step as written fails against the built site copy: the
build's _copy_hail runs the strict manifest check on its source, and a site copy holds hail/live files the manifest does
not list. Rulings:
- D92 **The parity step's source.** (a) website/build.py's _copy_hail checks its source with allow_live=True (D75(a):
  a built site's own copy may be the source; the copy takes only the listed folders, so hail/live is never copied); the
  copy's own check stays strict; a test pins both. (b) The build job's timeout rises from 15 to 25 minutes for the
  parity step (the smoke fixer's call stands; the step measured 132 seconds locally). (c) For run 2b no smoke fixer
  runs, so site-3 owns .github/workflows/website.yml and tests/test_website_workflow.py as well: the offline unittest
  module list names tests.test_words_rules (D91(f)) with its pin, and site-3 re-runs the parity step's own run: script
  against a fresh every-flag build (_site) and quotes the tail: seven tests, OK, no skip. (d) The one-hour swath layer's
  pixel gate is measured by the live preview only (no live file offline); the smoke says so and does not fail on it.

## Supervisor rulings on the re-check (2026-10-24 22:30 UTC; D93)
The read-only re-check (/home/user/hail-b5/out/b5b2-recheck.json, worktree 8f87d30) passed the suite (1,966 tests, 0
failures), the self-test, the sample and combined-store builds (history-flag map.json 162,374 bytes raw under 163,840;
every flag 464,287), the Chromium smoke at both widths with the three cells exact, the phone view at 682,129 bytes gzip
under 700,000, every tap file under 100,000, zero off-site requests, the parity step (7 tests, no skip), the words tables
(734 strings, 0 forbidden) and the dash and name counts. It failed four checks. Rulings:
- D93 **Re-check calls.** (a) The flag-off identity (D77, B5-18, BG3) covers the pages' text: the default build equals the
  base's except the ruled lines (D53, D74, D85, D86(c), D88(d), D91(c)) and the static assets map.js and map.css with
  their cache-busting hashes in map.html, because the browser code is one file for every build and the flags gate the
  data it reads, not the script; tests/test_site.py's identity test, which names the on-purpose differences, is the gate;
  a diff -rq of whole builds is not. (b) The town-page footnotes heading reads "Why a cell reads Data unavailable" (build.py
  near line 1043; a heading, not a status line); each footnote keeps its reason and its all-clear sentence (D41); the
  supervisor's one-line edit, done. (c) NWS forecast and observation words on the town pages outside the FORECAST tuple
  (the hourly rows, the forecast sentences) are outside the gate under D89(a) as before; the tuple is for the scan of the
  history words, not a second forbidden list; no change. (d) B5-11's reading that no sentence needs decoding is the
  supervisor's: done on the merged tree's build and on the live preview, recorded in the verification record. (e) The
  docs pass takes the re-check's mismatch list (checks.9_docs_numbers) and the missing D77 to D92 entries. (f) Order from
  here: this edit committed as WIP; main merged (D59, D60, D88(a), D92; the merge script); the docs pass on the merged
  tree; the full suite and the self-test; the squash onto the merge base with main; the push; the preview in Chromium; the
  pull request on main superseding PRs 14, 15 and 16.

## Supervisor rulings on the merge of main (2026-10-25 00:00 UTC; D94)
The merge resolver finished with the full suite passing on the merged tree (1,974 tests), the parity step passing against a
fresh build and the self-test passing; review round 1 found five losses (the build job timeout, two ROADMAP cells and a
heading, a README phrase, a sources.py sentence) and the fixer restored them (suite 1,975 OK), leaving two calls:
- D94 **Merge calls.** (a) The build job's timeout stays main's expression (15 minutes on main, 75 on branch pushes):
  the D59 wait for the branch's store job (up to 60 minutes) runs in that job before the build, the parity step and the
  smoke, so D92(b)'s 25 minutes is superseded for branch builds; tests/test_website_workflow.py's pin requires at least 75
  on a branch; DECISIONS records the reason. (b) Main's stale-rule sentence "and a branch preview fails." reads "and a
  branch preview is marked as failed." in the About-visible contract text, because the words gate (D85) forbids the
  stem; the meaning is unchanged; the test that pinned main's words follows. (c) Local builds from the combined store
  now meet main's three-day stale rule (the store's as_of is 2026-10-16): local checks pass --now within three days of
  the as_of (2026-10-17T12:00:00Z) or read the branch's fresh store; the live preview reads the branch's own store job.
  (d) After the merge commit, site-4 (the identity test's base and allowance list under D93(a); pyshp in the offline
  install) and the docs pass run in parallel on disjoint files.

## Supervisor rulings on merge review round 2 (2026-10-25 00:35 UTC; D95)
- D95 **Merge wording calls.** (a) The wait sentence: main's own sentences ("every build waits for the same commit's store
  job", README; "A build waits for the store job of its own commit", the hail_history timing row) disagree with main's
  code and its DECISIONS entry (the wait step is skipped on main and reads the branch's latest run); the resolver's
  sentence stands on both pages: "a branch build waits for its branch's latest store job before it reads the asset (main
  does not wait)"; the tests pin it; DECISIONS records the correction. (b) The unavailable joins block carries the same
  words as the loaded block (join_block reads one word table): no filter on words that mention HTTP; if a words rule
  forbids a word there, the word is reworded in the table, never dropped; the filter in build.py near line 749 and its
  test near tests/test_site.py line 2049 go. (c) README's sample build line keeps B5's "(off by default; it also carries
  the B5 weather files)": accurate and explicit. (d) D94(a) stands for the build job timeout: main's expression (15 on
  main, 75 on branch pushes); tests/test_website_workflow.py requires at least 75 on a branch; D92(b) is superseded for
  branch builds. (e) Any further wording where main's go-live text and B5's text differ and both are accurate: keep the
  sentence that matches the code as merged; where only one is accurate, that one; record the choice in the merge record. (f) website/templates/town.html: the resolver re-added the base's "{% if h.stale %}" line that B5
  had removed when it rewrote the hail section; B5's one stale line (v.stale) stands and the re-added line goes, so a stale
  store prints one notice. (g) The default-build identity pin (tests/test_site.py SWATH_BASE) is f96f5c7, main's head at
  the merge, and tests/fixtures/default-build-manifest.json is regenerated from that build (D93(a)); site-4 verifies the
  allowance list against the rulings. (h) The resolver's edits to files main did not change (the manifest fixture,
  tests/test_hail_workflow.py, tests/test_website_workflow.py, town.html) are part of the merge commit; the supervisor
  stages the whole tree.

## Supervisor rulings after the merge commit (2026-10-25 01:00 UTC; D96)
The merge is committed as b848989 (suite 1,975 OK on the merged tree; parity step 7 OK; self-test PASS). The third review
left four items against D95 and the stale line needs a D41 call: hail.py's WORDS["stale"] ("The newest day in this
history is {as_of}; newer days have not been added yet.") carries no all-clear sentence, while summary.py's stale
sentence does. Rulings:
- D96 **After the merge.** (a) The zone-edition reason (joins.py WORDS_JOINS reason_not_published) reads "the NWS does not
  publish this zone edition at its address (the address returned no file when checked on 2026-10-19)": no code in a
  user-facing word (main's plain-words rule, D59); tests/test_joins.py's pin follows; the HTTP word filter in
  build.py join_block_unavailable and its test (tests/test_site.py near line 2049) go (D95(b)). (b) One stale sentence,
  one source: hail.py's WORDS["stale"] ends with "This is not an all-clear." (D41), summary.py's stale line uses the
  same words (it imports hail's), and the town page prints one stale line (the hail line, with the summary line only
  as a fallback when the hail line is unset, as the merge left it; D95(f) is amended to this); main's test counts the
  hail sentence once and the summary sentence is the same text; map.html's hail_history line and map.js are checked
  so no page prints the all-clear sentence twice in one line. (c) The About timing row's "before it reads the store
  (main does not wait)" stands (the asset is the store); README and DECISIONS say "the asset"; both are accurate.
  (d) README's sample build line takes B5's "(off by default; it also carries the B5 weather files)" in the docs pass
  (D95(c)). (e) site-4 and the docs pass run now in parallel on disjoint files; then the final suite and self-test, the
  squash, the push, the preview and the pull request.

## Supervisor rulings on the site-4 check (2026-10-25 02:10 UTC; D97)
site-4 (/home/user/hail-b5/out/b2r8/site/check.json) verified the identity base f96f5c7 and its manifest (92 digests agree),
named every on-purpose difference with its ruling, added pyshp to the offline install, reworded the zone-edition reason
and removed the HTTP filter, and made hail's stale sentence the one source with the D41 ending; map.json with the history
flag 162,527 bytes raw (headroom 1,313), every flag 464,581. The suite's one failure (tests/test_hail.py WordTests scanning
the stale sentence) is fixed by the supervisor (the required sentence is scanned apart, as tests/test_site.py does).
- D97 **Last calls before the final round.** (a) About's CONTRACTS rows may name an HTTP code where they document a
  feed's behaviour (sources.py near lines 429, 504 and 578: editions not published, a file missing upstream); the words
  gate forbids stems, not codes; the pages' status lines use plain words (main's rule); no change. (b) The combined
  store's zone_editions reasons and the fixture's index.json keep "HTTP 404 when checked" until the next store build
  writes the new word; only the verify log reads them. (c) The three "chance of rain or snow" swaps made by the run-1
  words fixer (about.html's flag sentence; sources.py's forecast units row near line 84; the About flag row "Chance of
  rain or snow in %.") revert to main's words: D89(a) rules forecast words outside the gate and the plain phrase is the
  better one; the identity table in tests/test_site.py drops those entries and its mutation test uses another sentence;
  index.html's sentence and flags_for stay as they are (never swapped). (d) town/glasgow.html's live-block reason
  "(not published (HTTP 404))" is main's live text (D52) and stays. (e) After the docs pass: one final fixer round
  (words-4 for (c); the docs check's leftovers if any), then the supervisor runs the full suite and the self-test,
  squashes onto main's head, pushes, reads the branch run and opens the pull request.

## Supervisor rulings on the docs review's cross-owner findings (2026-10-25 02:45 UTC; D98)
The docs reviewer (round under /home/user/hail-b5/out/b2r8-docs/) found 20 findings; its skeptics are judging them and its
fixer takes the docs-owned ones. Four belong to other owners and are ruled now:
- D98 **Cross-owner calls from the docs review.** (a) The map banner's hail history heading follows the problem (F11): a
  stale store heads "Hail history is older than three days" and the sentence after it says what loaded and the as-of
  date; a failed download heads "Hail history didn't load"; Python supplies the heading word per state (hail.py's status
  words or build.py's problems entry) and map.html prints it, never a heading that contradicts its sentence; the
  site-final fixer owns map.html line 65 for this item. (b) summary.py's WORDS_SUMMARY zone_flag sentence ("Montana: {n}
  {noun} issued {when} could not be placed to a zone") ends with "This is not an all-clear." like the unplaced-zone note
  (D41; F19); tests follow. (c) Test comments carry no measured sizes (D87(h); F10): tests/test_hail.py near line 786 and
  the tests/test_joins.py comments the reviewer names cite the budget constant and b5-verification.json instead.
  (d) The smoke's local runs use the D94(c) clock (--now within three days of the store's as-of), and the stale banner's
  layout at 390 px (it moves the legend over the map centre; F20) is a ROADMAP follow-up: a fresh branch job never shows
  a stale store on the preview. (e) The docs pass continues through its skeptics, fixer and check; a final-a round
  (products-final for (c), site-final for (a) and (b)) runs now on disjoint files; words-4 (D97(c)) follows the docs pass
  because it edits about.html; then the supervisor's final suite and self-test.

## Supervisor rulings on the final-a round (2026-10-25 03:30 UTC; D99)
products-final and site-final finished (/home/user/hail-b5/out/b2r9/{products,site}/check.json; full suite 1,981 OK):
the banner heading follows the state (stale: "Hail history is older than three days"; failed: "Hail history didn't
load", with the technical detail in the log only), the zone_flag sentence ends with the all-clear and the test comments
cite constants and the record.
- D99 **Final-a calls.** (a) site-final's wider edit stands: summary._cover and _joined_flags take the sentence from the
  word through _flag_clause so a flagged line prints the all-clear once. (b) The browser prints the zone flag as Python's
  word gives it and adds no second all-clear sentence (map.js sumZoneFlag; one source, D29): browser-final, with the
  parity tests. (c) products-final's unpack-limit comment edit (tests/test_hail.py near line 2054) stands under D87(h).
  (d) The verification record names one measured total for the combined store (552,012,463 bytes in 45,878 files as
  adopted; the 541,075,953 figure is the pre-adoption round-2 measure and is labelled so) and one current fixture entry
  (94 files, 485,066 bytes outside hail/a, limit 480 KiB), the older entry labelled superseded; D74 keeps one meaning
  in the record (the About rows; the fixture budget citations in the tests say "the sample budget" with D64 and D69):
  docs-final after the docs pass, with words-4 (final-b). (e) Then the supervisor's final suite and self-test.

## Supervisor rulings on the docs pass (2026-10-25 04:50 UTC; D100)
The docs pass (44 agents: builder, reviewer, 40 skeptics, fixer, checker; /home/user/hail-b5/out/b2r8-docs/docs/check.json)
left: no D98 entry in DECISIONS and no ROADMAP follow-up for the stale banner's layout; the record's notes still name
541,075,953 bytes without the pre-adoption label; README line 406 says "about 600 tests"; the record's final test line is
stale (1,979 with a failure; the suite is 1,982 OK); DESIGN section 12 has lines the checker marked not current; the
phone-view figure moves between builds (682,129 at the re-check; 681,569 at the docs check). Rulings:
- D100 **Final-b.** (a) website.yml's on.push.paths lists the test modules the checker found missing (tests/test_words_rules.py,
  tests/words_rules.py, tests/test_summary.py, tests/test_stations.py, tests/test_climate.py, tests/test_gauges.py,
  tests/test_snowgrid.py), or tests/** if the list form allows it, with the pin in tests/test_website_workflow.py
  (D91(f); the ROADMAP follow-up C closes): ci-final. (b) docs-final carries the leftovers above: the D98 entry (banner
  heading per state; the zone flag sentence; test comments without sizes; the smoke clock) and D99 and D100 as bullets;
  the ROADMAP follow-up for the stale banner's 390 px layout; the record's notes labelled; README line 406 with the
  suite's size as "about 2,000 tests, offline, about 7 minutes"; the record's final test line from the last full run
  before the squash; DESIGN's not-current lines as the checker names them. (c) The phone-view figure in the docs is the
  re-check's (682,129 bytes gzip against 700,000) with its date; a later build within the budget is a note, not a
  restatement; the branch's live preview figure is recorded in the pull request. (d) final-b = words-4 (D97(c)),
  docs-final and ci-final in parallel on disjoint files; then the supervisor's final suite and self-test, the squash onto
  main's head f96f5c7, the push, the branch run and the pull request.

## Supervisor reading for B5-11 (2026-10-25 05:15 UTC; D101)
Read on a build of the merged tree from the adopted store at the local-check clock (--now 2026-10-17T12:00:00Z): the
Billings town page's five-season table (/home/user/hail-b5/out/sup-read/billings-history.txt) and the Benchland sheet at
390 px in Chromium (sheet-390.txt, sheet-390.png; zero off-site requests).
- D101 **B5-11 passes.** Every row names its kind of record and its unit; every value carries its unit or reads "Data
  unavailable" with a footnote under the heading "Why a cell reads Data unavailable"; the partial 2021-22 season says
  "the radar record has 256 of 365 days, so no figure is shown for this season; a missing day is not zero. This is not an
  all-clear."; the report rows say "reports are not a complete record"; the held roof lines lead with "Data unavailable"
  and end with the all-clear; nothing needs decoding. One note, not a change: the gust rows name the airport in the IEM
  form ("Billings/Logan Intl") and the GHCN rows in the display form ("Billings Intl AP"), two sources and two name
  rules (D84(a) and D78(c)); the record carries the note. The verification record's B5-11 gate reads pass with this
  reading as its evidence (docs-final or the supervisor before the squash).

## Supervisor rulings on words-4 and ci-final (2026-10-25 05:30 UTC; D102)
words-4 reverted the three forecast-word swaps to main's text (about.html line 132; sources.py lines 70 and 84) and trimmed
the identity table; ci-final added the seven test modules to website.yml's on.push.paths with a seven-test pin; full suite
1,989 OK.
- D102 **Final-b calls.** (a) The sources.py line 70 edit stands (the About flag row is main's "Chance of rain or snow in
  %."; D97(c) named the row). (b) on.push.paths also lists tests/fixtures/** (tests/test_site.py reads the default-build
  manifest there; the supervisor's edit, done); the parked-app test modules (test_alert_scenarios, test_updates,
  test_weather) stay exempt from the Website workflow's paths because check-app.yml runs them on every push to main and
  no website or tools module imports the parked app. (c) The em-dashes in website.yml's summary step predate B5 and
  fall under the D91(e) sweep.

## Supervisor ruling on the app check (2026-10-25 06:15 UTC; D103)
Pull request 17's app check (check-app.yml: the parked app's packages only, the whole suite) failed with five errors: the
two workflow tests imported pyyaml, the climate file-read class and one update test imported h5py, and the placement table
build test imported pyshp, none with a guard.
- D103 **Optional packages in tests.** A test that needs a package the app check does not install (pyyaml, h5py, pyshp,
  pygrib, pyarrow, pyproj, pyogrio) skips with the reason when the package is missing, as the suite's other optional
  tests do; the Website workflow's offline step and the daily job install the packages and run them. The fix is a second
  signed commit on claude/hail-b5 (tests only), reproduced first in a minimal environment with the app check's packages
  (five errors, then none) and checked in the full environment with the store (1,989 tests OK).

## Supervisor ruling on the real-store parity failure (2026-10-25 06:58 UTC; D104)
Website runs 118 and 119 on pull request 17 failed the parity step (D88(a)) against the branch's freshly published store
(hail-store-claude-hail-b5.tar.gz, run 11: as_of 2026-10-23, 721 stations, parts.stations "partial" with 65 station-years
that did not load). Reproduced locally against the downloaded asset: the five cells disagreed on gust_days.notes,
gust_max.notes and the wind section's notes (the module had the D20 partial sentence, the browser did not), and the
real-store names test pinned the adopted store's stations (Moccasin Exp Stn, 109 days missing).
- D104 **The gust rows' partial note and the names test.** (a) The browser's gust part adds the partial stations sentence
  from the joins block (parts, partial periods, reasons) after the rows' own notes, as summary.py appends it; the wind
  section carries it once through the rows. (b) The names test asserts behaviour on whatever store HAIL_PARITY_STORE names:
  every stations-block name is stations.display_name of its GHCN name, a printed name is a store name in display form and
  never the GHCN form, the radar rows follow D37 with the coverage they state; no store-specific name or count is pinned.
  (c) A fixture test (a copy of the fixture store with parts.stations "partial", two station-years and its own reason)
  pins the note in both the browser and the module, once, ending with the all-clear sentence. (d) Before any push that
  touches the sheet, the parity class runs against the branch's published store as well as the adopted store. The fix is
  the third signed commit on claude/hail-b5 (199dfa9; tests and map.js): parity class OK on both stores, full suite 1,990
  OK (5 skipped), selftest PASS.

## Supervisor ruling on the daily budget (2026-10-25 07:02 UTC; D105)
The branch's store job (run 11, commit bf2909b) ran 39.1 minutes end to end on the runner with its downloads (05:47:51 to
06:26:57 UTC on 2026-10-25) and published hail-store-claude-hail-b5.tar.gz at 88,647,098 bytes. The first-round gate B5-12
said under 25 minutes, a figure set before the B1 build, the B2 joins and the B3 parts shared the job.
- D105 **The daily budget.** (a) The daily job's budget is 60 minutes end to end on the runner: the bound the branch
  preview's wait step already holds (website.yml waits up to 60 minutes for the branch's store job), so a job over it
  fails the preview; the job's 150-minute timeout is the backstop for a stalled request (D94(a)). The 25-minute figure is
  superseded with this reason. (b) The measured 39.1 minutes is the figure the record and ROADMAP state; a later run over
  60 minutes is a budget decision (raise the wait bound, the job cap and the timeout together, as the wait step's comment
  says), never a silent breach (D90(b)). (c) Gate B5-12 reads pass against the restated budget, with the run time, the
  asset size and the phone view as its evidence; the record keeps the 25-minute wording as the gate's first-round text.

## B6: the owner's map reference (2026-10-25 08:00 UTC)
Carson sent ten screenshots of Apple Maps as shown inside the Zillow app and wrote: "I want the first map to look exactly like this. And
work like this." The screenshots: (1) a "Map options" sheet with Default / Satellite / 3D View, "Climate risks" chips (Flood, Fire, Wind,
Air, Heat), "Neighborhood amenities" chips (Banks, Bars & clubs, Coffee shops, ...), a Points of interest toggle, a Highlight open houses
toggle and a Reset button; (2) a block view of the Missoula slant streets (Brooks St, Blaine St, E Florence St) with a dark value bubble on
every house (Zillow's price; ours would be the weather figure) and "--" where there is none; (3) the neighbourhood with points of interest
drawn with icons (Loyola Sacred Heart High School, Rockin Rudy's, Florabella, Hellgate High School, Sacajawea Park, Rose Park, Big Dipper
Ice Cream, Clyde Coffee, Tagliare Delicatessen), route shields (US 12), street names; (4) to (6) the city and metro with parks, the
university, rivers, terrain tint, the airport, highway shields; (7) and (8) the region with hillshade, towns, the Flathead Indian
Reservation with its Salish name, national forests, peaks; (9) eastern Montana with the reservations and the state border; (10) the
state with the cities.
The supervisor's reading: the base map is Apple's; "exactly" has one honest path (Apple MapKit JS: Apple's own tiles, points of interest,
satellite and amenity filters; needs an Apple Developer account held by the owner, Apple's script from Apple's CDN (a change to AGENTS.md
rule 4's CDN clause, the owner's call), a token minted at each build; no 3D on the web) and one near path (MapLibre GL JS served by the site,
OpenStreetMap-derived Protomaps tiles for Montana as one PMTiles file in the Pages artifact, USGS imagery for Satellite, public-domain
terrain for hillshade and a real 3D view; not pixel-identical to Apple; the ODbL reading is a counsel question). The parts that are ours in
either path: the Map options sheet, the value bubble per house (the radar cell's figure, honest about the cell), the risk chips from our
store (hail, heat, wind, flood) plus new public sources (fire, air), the search, the sheet on tap.
Running (stage 0): wf_e43759f7-1a0 (the two base-map paths, verified live, two skeptics per claim) and wf_3b78ff46-de4 (side-by-side views
of our map against the reference at eight zooms from a local build with every layer on, the per-house bubble measurements, and the
risk-layer sources verified live). The question put to Carson: whether he is willing to hold an Apple Developer account for the site.

## Supervisor ruling on B6 stage 0 (2026-10-25 17:10 UTC; D106)
The research wave is in (records/b6/README.md is the record; the journals under records/b6/journals). Findings: the reference is
Apple's map; Apple's web maps (MapKit JS) give the same cartography at every zoom and the amenity and point-of-interest behaviour
one to one (a 73-category filter), with tile and DOM overlays for our layers; no 3D on the web; a domain-restricted static token
with no expiry from the developer console; 99 dollars a year for the Program membership; the logo and Legal link must stay; no
caching, so sample and offline builds never carry Apple tiles; the script loads from Apple (an exception to AGENTS rule 4). The
self-hosted stack (MapLibre, OpenStreetMap tiles 98.8 MB at zoom 13 or about 404 MB at zoom 15, USGS imagery, AWS terrain) is a near
look with weeks of cartography and an ODbL reading for counsel. Our map today: dots and outlines at the block, otherwise a white
map with no points of interest, parks, terrain, shields or river bands; top zoom 17 against the reference's 17.4; the store's
values are per 1 km cell (four cells, four values, in the block view); labels collide at zoom 17 unless thinned.
- D106 **B6 path and shape.** (a) Recommend Apple's web maps (path A) with the present white map as the fallback when the token
  is missing, the script fails or the build is a sample; the owner decides (the membership, the rule 4 exception, the logo and
  Legal link, the consent line before the locate button). (b) The 3D choice is left out of the sheet with one About sentence;
  never a greyed promise. (c) The value bubble is the cell's largest five-year radar estimate on every house in the cell, "--"
  where nothing of 0.25 in or more was stored, never a zero; the sheet names the cell; the engine thins collisions. (d) The risk
  chips: hail, heat, wind and flood from the store first; fire (NIFC, MTBS, USFS) and smoke (NOAA HMS) as new daily parts with
  their terms in About; FEMA stays out (counsel item 12); "Air quality" waits for an AirNow key and readable terms. (e) The build
  list B6-1 to B6-7 in the record; the branch is claude/map-b6 from the B5 head (906b49f); no code until the owner decides the
  path, except the Python products that both paths share (the risk pictures, the recent-hail product, the bubble values).
  (f) Skeptic verdicts so far confirm the figures and refute wording only; any claim that falls on substance is re-ruled.

## Owner decision on B6 (2026-10-25 17:35 UTC) and ruling D107
Carson: "We don't need the apple design anymore. That was just a base that I don't want in the finish." Reading: the screenshots
set the behaviour and the structure (the options sheet, the chips and switches, a value bubble per house, a map that carries
terrain, water, forests, reservations, parks, landmarks, shields and names at every zoom); the finished product is in the site's
own design, not Apple's, and Apple's maps are not used.
- D107 **B6 on our own map.** (a) No Apple membership, no MapKit JS, and no OpenStreetMap or MapLibre either: the map stays
  Leaflet with Python-built site files, as the architecture is (D27 to D29, B3), and the cartography is built from public-domain
  sources only (USGS 3DEP terrain, NLCD land cover or a USGS relief service, NHD or TIGER water with names, Census AIANNH
  reservations, Forest Service forest boundaries, PAD-US and TIGER landmarks for parks, schools, hospitals, airports and churches,
  GNIS peaks and places, TIGER or State Library route numbers), served by the site with no request to another site in use (the
  opt-in USGS imagery stays the one exception, D32). (b) The amenity chips become landmark chips from public-domain categories;
  businesses (banks, bars, coffee shops) are out until the owner asks for OpenStreetMap and counsel reads the ODbL (D106 record).
  (c) The 3D choice is out. (d) The value bubble rule of D106(c) stands; placement is computed by Python per zoom where it can be.
  (e) Stage 1 (running): the public-domain cartography sources verified live with a Python proof picture in the site's palette
  (wf b6-own-cartography), and the design mocks of the options sheet and the bubbles in Chromium at phone size (wf
  b6-design-mocks); the owner sees the mocks before any build. (f) The research record on claude/map-b6 gets the owner's decision
  and the revised plan in its next commit.

## Supervisor rulings on the stage 1 mocks (2026-10-25 18:20 UTC; D108)
The design workflow delivered the options sheet mock (nine renders, measured: 0 hex values, 0 overflow, 44 px targets, the body
scrolls) and the bubble placement (the block view: 248 houses in four cells with values 0.38 in, --, 0.30 in and 0.26 in; one bubble
per house with a skip rule labels 91 of 248 at zoom 17, 52 of 69 at zoom 18; one bubble per cluster of houses in the same cell
labels every house with 56 bubbles at zoom 17 and 34 at zoom 18). The sheet critic failed the mock on substance: uppercase headings,
the map.css glass panel and its blue switch, the off-track contrast at 1.3:1, the live hail legends without the "not no hail"
sentence, a landmark legend that names one kind only, "Satellite" clashing with the cloud picture, "risks" in a five-year
history heading (DESIGN section 12 rule 6).
- D108 **The sheet and the bubbles.** (a) The sheet is in the site's own roles (a solid surface, a line edge, the 12 px radius, the
  focus blue for a switch), sentence case throughout, no glass; the map page's existing chrome (D28) is not the Apple base map the
  owner dropped, but the sheet does not depend on it. (b) Names: "Base map" with "Map" and "Imagery" (D32), "Live weather",
  "Five-year history" (never "risks"), "Landmarks"; live weather and five-year history are one at a time, landmark kinds are
  independent, Points of interest shows the chosen kinds. (c) Every legend line carries its kind, its source, its age and what a
  missing value shows; the live hail legends end with the DESIGN section 11 sentence; wind reads "50 kt (58 mph)". (d) Bubbles: one
  bubble per cluster of houses in the same cell (the data has one value per cell), placed by Python per zoom and written into the
  building shards as label anchors; the per-house variant is shown to the owner as the alternative with its count (91 of 248). The
  owner picks; the recommendation is the cluster rule. (e) Top zoom 18 is a build item (the data supports it). (f) A fixer applies
  the critic's items to the mock and a second critic re-checks before the owner sees it (wf b6-sheet-fix).

## Supervisor rulings on the cartography sources (2026-10-25 19:45 UTC; D109)
The cartography workers reported (records to follow under records/b6/cartography): 3DEP hillshade comes only by exportImage per tile
(no cache); Montana-outline tiles for zooms 5 to 10 are 805 (about 8 MB as grey JPEG, 29 MB as PNG) and for zooms 5 to 12 are 11,863
(about 87 MB JPEG, 363 MB PNG); tiles join without seams; the USGS shaded relief cache has holes at zooms 9 to 11, the hydro cache
covers 5 to 12. NLCD 2021 land cover (public domain; Fees and AccessConstraints NONE) is about 2 MB statewide at 240 m and 25 to 35 MB
at 30 m; palette tiles are 5 to 9 KB each (zoom 10 about 5 MB statewide, zoom 12 about 50 MB). Water: TIGER county files (162 MB
zipped statewide, abbreviated names) or NHD (592 MB state file; the map service has small-scale and large-scale layers with GNIS
names). Reservations: TIGER AIANNH, 7 in Montana, English names only (the Salish name of the Flathead Reservation needs the
Tribes' confirmation). Forests: the Forest Service boundaries, 7 forests (federal work; the metadata has no reuse sentence). Parks:
PAD-US not readable from this session by ScienceBase; TIGER area landmarks give 104 parks, 101 state parks and 22 city parks
statewide. Landmarks: TIGER points are too thin (52 schools, 37 hospitals, 6 churches statewide). GNIS: 3,181 summits without
elevation, 1,870 populated places. Places: TIGER 497 with 2020 counts. Route numbers: TIGER full names and the State Library fields.
- D109 **The cartography stack and its budgets.** (a) Raster: hillshade as grey JPEG tiles from 3DEP for zooms 5 to 10 (about 8 MB,
  built by the monthly job into the store under hail/m/ or a new map/ part), drawn under the vector layers at low opacity; land cover
  tint as palette tiles from NLCD 2021 at zooms 5 to 10 (about 5 MB); zooms 11 and 12 are a later budget decision with the measured
  figures (87 MB and 50 MB); above the native zoom the tiles are scaled, and the tint fades out by zoom 13 where the streets and
  outlines take over. (b) Vector: rivers and lakes with names from the NHD small-scale layers for zooms 5 to 12 (simplified by Python,
  sizes to be measured) and the large-scale layer per B3 tile at zoom 13 and up; reservations from TIGER AIANNH with their English
  names (the Salish name added when the Tribes confirm it); national forests from the Forest Service boundaries (federal work, public
  domain by law; a courtesy line to the Forest Service recorded); parks from PAD-US when it can be read, else the TIGER landmarks;
  places from TIGER with a min-zoom rule by 2020 population; peaks from GNIS with elevations sampled from 3DEP by the build; route
  shields drawn from the refs already in basemap.json plus the state routes from TIGER. (c) Landmarks for the chips come from sources
  still to verify (NCES EDGE schools, HIFLD hospitals and places of worship, FAA airports); a chip whose source fails stays out.
  (d) Budget rule: nothing is added to the first-paint files; every new layer loads by zoom band or by tile as B3 does, and the phone
  view at zoom 15 over Billings stays under its 700,000-byte gzip budget with the new tiles counted (about 18,000 bytes of headroom
  today, so the first paint cannot grow). (e) Terms: every source gets a CONTRACTS row and an About sentence with its credit line;
  the State Library roads keep their counsel gate.

## Supervisor rulings on the sheet's second critique (2026-10-25 20:05 UTC; D110)
The fixer applied all nine items (measured: 0 hex values, 0 overflow at 288 to 1440 px, every target 44 px, text contrast at least
6.76:1 light and 7.87:1 dark, the off switch outline 6.97:1 and 7.87:1, sentence case everywhere, no "risk"). The second critic
passed those and failed six details, which become the build spec, not another mock round:
- D110 **Sheet copy and details for the build.** (a) The Points of interest sub-line reads "Landmark dots and names, for the kinds
  chosen above" (the kinds sit above the switch). (b) The five-year sub-line reads "Past records from the last five years. Not a
  forecast." (no "damage" wording; D86 and DESIGN section 9 keep that word to its three places). (c) Missing values: in every
  sentence the words are "Data unavailable" (AGENTS rule 5); the map bubble alone may show the glyph "--" for room, and its legend
  line says "-- means Data unavailable: no radar estimate of 0.25 in or more was stored for this cell; that is not zero and not an
  all-clear"; the owner sees the glyph in the mock and can veto it. (d) The Imagery line carries D32's words ("Imagery: USDA, USGS,
  The National Map. Your IP address and the map area you view go to USGS while it is on."); map.html's present line is brought to
  the same words in the build. (e) The switch knob has no shadow (box-shadow none in the sheet rules that move to map.css); every
  painted colour is a style.css role. (f) The Landmarks sub-line states no data fact until the sources are verified (D109(c));
  then it names the kinds and their sources. (g) The switch is named "Highlight recent radar hail" (a radar estimate, never hail
  seen; rule 5). (h) The build's smoke renders the states the critic found missing in the mock set: each legend, the Points of
  interest off state with its reason, the highlight and storm-report legends. (i) Sub-lines at 14 px like the legend lines.

## Supervisor ruling: B6 stage 2 part 1 launched (2026-10-25 21:05 UTC; D111)
- D111 **The data products build.** The brief briefs/map-b6-build-brief.md sets four products on the worktree
  /home/user/wt/wt-b6 (claude/map-b6): P1 terrain tiles (3DEP hillshade grey JPEG and NLCD tint palette PNG, zooms 5 to 10, the
  Montana outline's tiles), P2 the base map bands (reservations, forests, parks, water with names, places with a population
  rule, peaks with 3DEP-sampled elevations, route refs; bands A to D with gzip budgets), P3 landmark points per tile (schools,
  hospitals, airports, fire stations, parks; churches built but held for counsel), P4 the five-year pictures (hail 1 inch days,
  heat 90 F days), the per-zone counts, the recent radar hail cells and the bubble anchors (the cluster rule, zooms 17 and 18,
  deterministic). Each product: a module in the gauges and buildings pattern, tests, a report, measurements and integration notes;
  then a reviewer, two skeptics per finding, a fixer and a checker (wf b6-build-products and b6-build-products-b). Shared files
  wait for the phase B integrator. The owner's two open picks (bubble rule A or B; the sheet) do not block part 1: the anchors
  carry both rules' data if the builder finds it cheap, else rule A.

## Supervisor rulings on the part 1 builders' open points (2026-10-25 23:30 UTC; D112)
P1 terrain (built: 881 tiles per layer for zooms 5 to 10, 14,819,475 bytes, cold build 1,175 s, cache rebuild 14 s, verify 21 of 21,
10 of 10 re-fetched tiles byte for byte), P3 landmarks (2,185 points in 542 shards, 107,868 bytes gzip, 485 church rows counted and
held; reproduced exactly by the reviewer) and P4 (hail1.png 62,458 bytes with 144,522 cells at 1 inch or more; heat90.png 4,714
bytes; zones.json 103 zones; recent cells 64 in the 30 days to 2026-10-16; labels statewide 483,008 bubbles at zoom 17 covering
95.25 percent of 918,052 outlines, 732,531 at zoom 18 covering 98.78 percent, 1,386,996 gzip bytes added in all) reported open
points; the reviewers' findings go to the fixers as the workflow runs. The supervisor rules the open points:
- D112 (a) **Sampling and classes.** Nearest sampling of the land cover stands for part 1 (the speckle is judged on the browser
  look in B6-3; a majority option is a measured follow-up); wetlands (codes 90 and 95) take the shrub-and-grass colour, barren
  stays transparent; pasture stays with crop; developed land is one shade. (b) **Timeouts.** The terrain build's request timeout
  is 60 s (two zoom 5 land cover tiles take up to 30 s); the monthly job passes it. (c) **Credit lines.** The NLCD line reads
  "Land cover: National Land Cover Database 2021, U.S. Geological Survey and the Multi-Resolution Land Characteristics
  Consortium (public domain)"; the 3DEP line "Relief: 3DEP data courtesy of the U.S. Geological Survey"; both go to the counsel
  list as items to confirm, not as blockers. (d) **Tiles.** The 881-tile set (the exact overlap rule) stands; the 805 was a sample.
  (e) **Park names.** Where a TIGER park point and a PAD-US polygon are the same park, the PAD-US name stands and the TIGER name
  is kept in the row as an alternate for the search ("Rose Garden", alternate "Rose Park"). (f) **Hospitals and fire stations.**
  The USGS structures layers stand as the sources; the HIFLD licensure copy stays the tested fallback; the fire kind's label is
  "Fire and EMS stations". (g) **The FAA fixture.** No private owner name, address, phone or manager field goes into the
  repository: the test fixture keeps only the columns the module reads; every fixture of every product is checked for this
  before the commit. (h) **Zero is never a count for an unavailable kind** (rule 5): the map block carries "Data unavailable"
  with the reason. (i) **Flood measures.** Flash flood watches and warnings are counted as their own two measures beside the
  flood ones (eight zone measures). (j) **Bubbles.** Bubbles sit above their dot; the 56 px rule uses the measured label width
  (55.75 px); the clusters skipped for overlap (4.75 percent of outlines at zoom 17, 1.22 percent at zoom 18) are accepted: the
  tapped sheet always has the value; the 36 shards over the 250,000-byte raw split threshold are accepted because every shard
  stays under the 100,000-byte gzip budget (largest 45,053), and the threshold is not changed in this stage. (k) **Heat bands.**
  The 25-day bands stand with "125 days or more" as the top band. (l) **Zone counts** carry the newest-warning date (2026-09-19)
  in their words, as built. (m) **Caches.** Each product prunes its download cache to the newest cycle or month; a cache keeps no
  error page (a body that fails the content check is never written).

## Supervisor rulings from the risk-source skeptics (2026-10-26 00:40 UTC; D113)
The skeptic pass over the 53 risk-source claims ended (109 agents): the figures hold almost everywhere; the refutations are
wording, currency and licence-scope corrections, which become rules for the build:
- D113 (a) **No implied endorsement.** NOAA's open-data licence requests attribution and forbids stating or implying NOAA
  endorsement; every credit line reads "Source: ..." or "... data from ...", never "in partnership with" or "approved by".
  (b) **Cadence words.** The NOAA smoke analysis updates several times a day (observed 15:48 and 22:48 UTC on one day), so the
  legend says "updated during the day", never "daily". (c) **Grid words.** An nClimGrid cell in Montana is about 4.6 km north
  to south and 3 to 3.3 km east to west; the words are "about 1/24 degree cells (roughly 4.6 by 3 km in Montana)". (d) **Dates,
  not lags.** The store's warning, SWDI and NCEI dates are the newest event dates in the store, so the words read "the newest
  warning in the store is dated 2026-09-19", never "read through" or "lag"; P4's zones words change to match. (e) **Heat
  products.** NWS replaced the EH codes with XH (extreme heat) in 2025 (Service Change Notice 24-88); any heat-product count
  includes both; zone rows are not events, and a per-zone count counts the products that covered the zone, said in those words.
  (f) **Fire hazard.** The Forest Service hazard raster's catalog sentence opens a Data Use Agreement; counsel reads it before
  the hazard layer is built; the MTBS outage is 8 AM to 12 PM on 28 October 2026. (g) **Air.** AirNow's Data Exchange
  Guidelines exist as a PDF on the API docs site: an "Air quality" chip is possible once counsel reads them and a key is held
  (counsel list item 22); PurpleAir's terms are readable through its app's JSON endpoints and it is not public domain (out).
  (h) **Flood maps.** USGS flood inundation map data exist for some Montana reaches (the skeptic read them); a later option.
  (i) **Report figures.** The views report's building counts were off by 60 and 8 against the store (25,202 and 7,960); the
  record uses the store's figures; the pictures were right.

## Supervisor rulings on P2's report (2026-10-26 01:05 UTC; D114)
P2 built: band A 133,301 bytes gzip (budget 150,000), band B 21 files (largest 55,596; budget 100,000 each), band C 78 files
(largest 9,273; budget 60,000), places 497 with the population rule, peaks 3,181 all with 3DEP heights (Granite Peak 3,899 m;
McDonald Peak sampled 25.2 m under the listed height, inside the 30 m tolerance), two offline builds identical. Band D (water and
park polygons per B1 tile at zoom 13 and up) reached 20 of 4,597 tiles: the NHD large-scale service answered 504 for the rest.
- D114 (a) **Band D is optional for the first release.** The browser draws band C's rivers and lakes at zoom 13 and up until a
  tile's band D shard exists; a missing shard is never an error on the page. The monthly job builds band D over several runs
  under its deadline, resuming from the cache; the index says how many tiles are built. (b) **Forests are shown.** The Forest
  Service boundaries are federal work (public domain by 17 U.S.C. 105); the service's "read-only use" note is a usage note, not a
  licence; the credit line "Forest boundaries: USDA Forest Service" stands and counsel sees the terms as item 23, not as a hold.
  The NHD terms (USGS, public domain, credit requested) are counsel item 24. (c) **Cold timings** are measured by the first monthly
  run and recorded then; the job's step gets a 20-minute cap with the cache carrying the rest to the next run.

## Supervisor rulings from the cartography skeptics and the render critic (2026-10-26 04:10 UTC; D115)
The cartography research pass ended (96 agents; 46 claims, 36 standing, the rest corrected on wording, currency or licence
scope). Corrections that matter: NLCD 2021's data release carries a CC0 1.0 licence (public domain), better than the citation
request the worker quoted; the TIGER area landmark file's own use constraints are read by counsel before the park and landmark
points from it ship (the NCES, PAD-US and USGS structures sources carry the landmark chips without it); the Montana State
Library roads licence is a disclaimer (the existing counsel gate); the W3 river ranking in the research report was wrong (no
product effect). The render critic failed the proof pictures on points that are design decisions, not errors:
- D115 (a) **The base look.** The owner dropped Apple's design, not terrain: the reference's information (relief, land cover,
  forests, reservations, water, places, shields) is what "work like this" means, drawn in the site's own palette. DESIGN.md
  section 8's "white land" rule is amended for B6: the land is paper white at the street zooms (13 and up); the region zooms
  (5 to 10, fading through 11 and 12) carry a light land cover tint and relief shading under the field-sheet lines. The owner
  saw the proof pictures and can veto the tint; the default is on. (b) **Picture palettes.** The tint and relief colours are
  picture palettes defined once in Python with named constants and listed in DESIGN.md beside the radar palettes, as the frames
  are; the CSS token rule covers the page, not the pictures. (c) **Type.** The browser draws every map label at the site's
  type scale (13 px minimum; towns per the hierarchy in DESIGN section 8; the label side from towns.json); the proof's small
  type was the Python picture's, not the product's. (d) **Credits.** Every credit line names the party the terms ask for:
  "U.S. Census Bureau", "USDA Forest Service", "U.S. Geological Survey", "Natural Earth", "Multi-Resolution Land
  Characteristics Consortium"; one credit line per page state, complete, never implying endorsement (D113(a)). (e)
  **Reservation outlines** come from the full-resolution TIGER/Line AIANNH file at every zoom (P2 built it so); the 1:500,000
  cartographic file is never drawn above zoom 9. (f) **Streets at zoom 12 and below** are the main roads only (no stand-in
  local mesh); route-like street names ("FAS 533") get no label; street names keep the source's case rendered in the site's
  mixed-case style. (g) **Dark mode**: the tint and relief tiles are hidden in dark mode (the charcoal paper stands alone)
  until a dark palette is designed and measured for contrast; the sheet and the labels follow the existing dark tokens.

## Supervisor rulings on the part 1 chains and the owner-decision findings (2026-10-26 05:35 UTC; D116)
The two build workflows ran their refute stages two agents at a time (the per-workflow cap on 4 CPUs), with P1's fixer queued
behind P2's 19 remaining refutes and P3's behind P4's 7. A resume replays only the unchanged prefix of agent calls in order, so a
one-product resume re-ran the reviews (stopped at once); the chains were split instead into four fresh runs with the journals'
state passed as arguments (standing findings, pending findings) and the original prompts: P1 wf_2924148e-459, P3 wf_e68b48b6-2b3
(fixer then checker), P2 wf_420ecadb-f82 (19 refutes, fixer, checker), P4 wf_8d440c0d-382 (7 refutes, fixer, checker). Rulings
on the findings the reviewers left to the owner or the supervisor, passed to the fixers as notes:
- D116 (a) P1-07: the remap of the hillshade transparency value is dropped (a changed stored value is a wrong number). (b) P1-10
  and P2-19: --cache stays optional, defaulting to a folder beside the store, never a relative path in the repository; the
  integrator adds terrain-cache to .gitignore. (c) P1-11: a zoom subset is refused unless --keep-other-zooms is given. (d)
  P1-12: the monthly job passes --refresh; the land cover date is read from the service's layer name at each build. (e) P2-08:
  the per-cell band D request unit stands as a recorded decision; band D is not re-run before phase B (D114(a)). (f) P2-10: the
  water and summit sentence names the publisher and is held with the forest line until counsel reads the NHD and GNIS terms
  (item 24). (g) P3-12: the minimal name rule (Memorial, Field, USFS kept, 'at' lower case); the rest is an owner item. (h)
  P3-20: the label point's distance measure is stated as degrees; no change now. (i) M5: bubbles stay above the dot only for
  this stage; the coverage figures (95.25 percent at zoom 17, 98.78 at 18) are stated; the below-side option is an owner item.
  (j) M6: the 36 shards over the raw split threshold are accepted (D112(j)); the integrator keeps the buildings verify before the
  labels pass. (k) L10: the kv words stay "Data unavailable" with the "--" glyph (D110); the wording is an owner item. (l) L18:
  research notes under research/ may name the products they analyse (the owner's reference); product files, docs and tests may
  not. (m) L19: the per-zone sums are labelled as sums over zones, never as Montana totals. (n) Shared-file findings (website.yml,
  .gitignore, hail-store.yml, buildings.py) go to integration.md for the integrator; no fixer edits a shared file.

## Supervisor rulings on the P1 check (2026-10-26 06:25 UTC; D117)
P1's continuation (wf_2924148e-459) ended: the fixer applied the twelve standing findings (80 tests, 26 of which fail against
the unfixed module); the checker found the budgets met (14,819,458 bytes for zooms 5 to 10 against 20,000,000; 881 tiles; a
cache-only rebuild gives identical bytes; 10 of 10 live re-fetches byte for byte) and listed 15 items. Rulings, passed to the P1
rulings pass (wf_bcf01aa8-f13) as items X1 to X10:
- D117 (a) The job's 60 s timeout stands for build and for verify (verify's default stays 20 s). (b) Every layer-level
  unavailable or partial sentence carries the words "Data unavailable" beside the D20 wording (rule 5). (c) A URL path segment
  (the "arcgis" in a USGS service path) is not a product name under the names rule. (d) verify says "byte for byte" only when
  the bytes match; a palette-equal answer with different bytes is a failed match. (e) An offline build never deletes tile files;
  a layer that is not rebuilt keeps its block and date. (f) The record cites full-set figures (1,762 cache hits), not a
  subset run's. (g) The cold run's 1,175 s against the 1,500 s step budget is an owner item (the monthly job may need a longer
  step or two runs). (h) .gitignore gains terrain-cache/ and b6-cache/ (integrator).

## Supervisor rulings on the P3 check (2026-10-26 06:40 UTC; D118)
P3's continuation (wf_e68b48b6-2b3) ended: the fixer applied the twenty standing findings (71 tests, 31 of them skipped without
pyshp; the FAA fixture scrubbed of owner, address, phone and manager columns; the fire label "Fire and EMS stations"); the checker
found 18 of 18 verify checks passing, 542 shards reproduced byte for byte offline, budgets met, and listed 15 items. Rulings,
passed to the P3 rulings pass as X1 to X8:
- D118 (a) **Hospital sources.** The rule as coded stands: the HIFLD copy is read only when the USGS layer answers with no Montana
  rows; a failed USGS request makes the kind unavailable, never a silent switch of source (a map whose hospitals change source
  from day to day is not honest about its source). The notes follow the code. (b) **Held counts are not published.** No number
  derived from a held source goes into a published file: the index carries state "held" with the reason and count null; the
  figure (485 places of worship) stays in the build report. (c) **Display names.** A local rule after the shared title case:
  possessive 's, lower-case ordinals, Mc-capitalisation, a capital after a slash, backslash to slash, and the safe expansions
  (Hs, Ms at the end; Elem; Schl and Sch; Jr and Sr before High). Every other abbreviation stays as the source gives it and is
  listed for the owner with its count. (d) An en dash or an apostrophe in source text is kept (the ban is the em dash).
  (e) A repository URL in a User-Agent string, like a URL path, is not a vendor or product name (D117(c)).

## Supervisor rulings on the P2 refutations (2026-10-26 06:55 UTC; D119)
The 19 pending P2 findings were refuted in four parallel runs (38 skeptics): 14 stand, 5 are refuted (P2-10 the held water
sentence, P2-18 verify's manifest check, P2-20 the missing report, P2-22 the missing-count zoom, P2-24 the integrator's pins),
so the P2 fixer applies 19 standing findings (P2-01 to P2-09, P2-11 to P2-17, P2-19, P2-21, P2-23). Rulings passed as notes:
- D119 (a) **Band D's request unit.** The per-cell request stands as a recorded decision (the skeptics measured that per-tile
  requests would take roughly 24 to 47 hours serially, while a cell answers in one request when the service is up); band D is
  not re-run before phase B (D114(a)). (b) **Pieces carry size and a feature id** (the source OBJECTID), and the label sits on
  the piece with the label point. (c) **Placeholder and agency names.** A park whose name is blank, a placeholder ("Unknown
  Park") or the managing agency's name keeps its outline and gets no name and no label point (the D16a precedent for roads).
  (d) **Partial sentence.** Every failed kind is named, with no cap and no count. (e) **Missing sizes.** A river with no
  drainage area is left out and counted as unusable; a park with no acreage keeps its outline with size None, ordered last
  when a file is over budget; never a zero. (f) The 3DEP statement is marked as quoted from a secondary copy of the USGS text,
  as P1 does; the unrecorded river-rule figures leave the docstring. (g) A river check is skipped only when the bands that
  could hold the river (A and B) failed.

## Supervisor rulings on the P3 rulings pass (2026-10-26 07:05 UTC; D120)
The P3 rulings pass (wf_b1bb475d-6c2) applied 13 of 16 items (98 tests; the FAA fixture scrubbed; held sources and the shared
base index format; the hospital rule; display names; credits in one form). Three items need a follow-up: P3-R1 (three unread
FAA spans still carry text: columns 4 to 14, 94 to 133 and 184 to 185), X5 (the fixer refused the out-tree report and
measurements as outside its file list) and P3-R4 (its wording conflicted with D118(b)). Rulings:
- D120 (a) P3-R4 is amended: the index carries held kinds and sources with state and reason and count null; D118(b) stands.
  (b) A product's out-tree files (report.md, measurements.json, integration.md and its test store under
  /home/user/hail-b5/out/b6/build/<product>/) are the product's own and every fixer may edit them. (c) A product's test store
  is rebuilt offline from the cache before its verify is run against new code; a stale store is never cited as a verify result.
  (d) A data-format type code from a service's own schema ("esriFieldTypeOID"), like a URL path, is not a vendor name under
  the names rule (D117(c)). (e) The FAA fixture keeps only the spans the module reads (nine spans including the status code),
  every other column blank.

## Supervisor rulings on the P1 rulings pass (2026-10-26 07:20 UTC; D121)
The P1 rulings pass (wf_bcf01aa8-f13) applied all 16 items (92 tests; wetlands in the shrub-and-grass class, so 880 of 881 land
cover tiles change and the statewide bytes fall to 14,349,318; offline builds never delete files; the shading copyright read
from the service; "Data unavailable" in every layer sentence; verify's "byte for byte" only when true). The checker passed every
item and raised four points, ruled here and passed to a P1 follow-up as F1 to F4:
- D121 (a) **Credit forms.** The labelled lines ("Relief: 3DEP data courtesy of the U.S. Geological Survey", "Land cover:
  National Land Cover Database 2021, ...") are the legend's lines on the map; the About page's sentences are written by the
  integrator in the "Source: ..." form (D113(a)) from them. Both name the source and neither implies endorsement. (b) **The
  shared base index** is never discarded by any reader: a document with no "f" key or another format refuses the write with
  the reason and leaves the file unchanged (the P2-R7 and P3-R8 rule applied to terrain.py). (c) **CC0 evidence.** The CC0
  1.0 sentence stays only with a citation of the page and date read in the research record; otherwise it goes and the note
  says the statement was not confirmed. (d) The block-level "Data unavailable." sentence stands (rule 5). (e) **The adopted
  store's land tiles** predate the wetland change: the integrator's store copy takes the rebuilt land files from the P1 test
  store or runs the offline build; the monthly job rebuilds them on its first run.

## Supervisor rulings on the P2 check (2026-10-26 07:45 UTC; D122)
P2's continuation (wf_5024a4f7-0c1) ended: the fixer applied the 19 standing findings (85 tests, 28 new; pieces carry a size
and a feature id; placeholder and agency park names draw no label; the partial sentence names every failed kind), verify
passes 22 of 22 on the rebuilt test store, the offline build reproduces every data file, budgets met on the built set. The
checker listed 20 problems; rulings, passed to the P2 rulings pass as X1 to X14:
- D122 (a) **No coverage claim the counts contradict.** The index writes band D's built and unbuilt counts and the failed
  cells, never "every listed tile". (b) **Two true statements about an unbuilt band D tile.** The browser keeps drawing band
  C's lakes and rivers at zoom 13 and up (they loaded statewide), and the sheet's water line reads "Detailed water and local
  parks: Data unavailable for this area in this update. This is not an all-clear." Every text says both. (c) **Simplification
  never drops silently.** A feature that collapses at a band's tolerance moves to the next finer band; one that collapses in
  the finest band it can reach is dropped and counted (136 of 415 state parks and recreation areas, mostly fishing access
  sites under 0.02 square kilometres, collapsed silently at band B). (d) **Skipped checks are not passes.** verify reports a
  check it did not run as "not checked"; ok is over the checks that ran. (e) **Forests and water ship** in the first release
  with their credit lines (D114(b)); counsel items 23 and 24 are items to confirm, not holds. (f) **First-paint names.** The
  twenty first-paint towns keep the basemap's names and zooms; "Butte-Silver Bow (balance)" is Butte and "Anaconda-Deer Lodge
  County" is Anaconda through a documented table. (g) A cited reference (Peakbagger, Wikipedia) in a citation is not a vendor
  or product name under the names rule. (h) A missing shapefile reader is a named failure of the kinds that need it, never a
  crash. (i) The local park polygons appear as band D builds; the P3 park chips show the parks meanwhile. (j) The workflow
  step reads the vector state from the index because build exits 0 for an unavailable store.

## Supervisor rulings on the P3 follow-up (2026-10-26 07:50 UTC; D123)
The P3 follow-up (wf_2944b627-c8e) rebuilt the test store with the final code (verify 22 of 22; 101 tests; the held block names
each held kind and source with state, reason and count null; no Census row written) and scrubbed the three remaining FAA spans.
Rulings on its open points:
- D123 (a) The FAA parser reads eight spans (1 to 3, 15 to 27, 49 to 50, 134 to 183, 186 to 187, 524 to 538, 551 to 565, 841 to
  842); the fixture keeps those and nothing else; "nine" in D120(e) was my miscount. (b) A product's test store carries a
  manifest in the adopted format listing the files it holds (539 for P3); the adopted manifest's 45,877 entries belong to the
  full store, which the integrator checks. (c) The product cache's six layer descriptions are renamed to the module's names
  (bytes unchanged) so an offline build from the cache reproduces the store; the first live run refreshes them anyway. (d) The
  changed-name figure is recounted per row (66 pairs, not 53) and every stale figure in the P3 records (101 tests, 22 checks,
  539 entries) is corrected before the integrator reads them. A close-out run (wf_2f42c9f1-0fb) does (c) and (d).

## Supervisor ruling on the NLCD terms (2026-10-26 08:05 UTC; D124)
The P1 follow-up (wf_4a91573b-627; F1 to F4 pass; 100 tests; the terrain reader never discards a foreign base index) found no
record naming the NLCD 2021 release page with a CC0 statement. The cartography skeptic journal (wf_ef4c997e-067) holds the
reading: the Creative Commons CC0 1.0 Universal statement is on the Annual NLCD Collection 1 record (doi 10.5066/P94UXNTS); the
NLCD 2021 Products record (doi 10.5066/P9JZ7AO3) states "public domain information" with access constraints None, use
constraints None and fees None, and the MRLC WCS capabilities give Fees NONE and AccessConstraints NONE.
- D124 D115's "NLCD 2021's data release carries a CC0 1.0 licence" is corrected: CC0 applies to the Annual NLCD collection, a
  different product. The terrain module's terms note cites the NLCD 2021 record's own words and DOI and claims no CC0 for it
  (wf_c09cc861-aaf). The About sentence keeps "(public domain)" on the strength of the record's own words.

## Supervisor rulings on the P4 check (2026-10-26 08:20 UTC; D125)
P4's continuation (wf_8d440c0d-382) ended: 7 pending findings refuted (L13 stands; L14 refuted; the rest mixed), the fixer
applied the standing findings (55 history tests, 34 label tests; eight zone measures; newest_warning in place of lag; the
pictures' legends name the missing radar day; the labels unavailable command fails closed), both verify commands pass on the
test store, a rerun reproduces every output byte for byte. The checker listed 13 items; rulings, passed to the P4 rulings pass
as X1 to X8 and to the integrator:
- D125 (a) **The newest-warning date comes from the counted rows** (2026-10-10T21:00Z today), never from the polygon warnings'
  date in the joins index (2026-09-19); the test pins the computed date. (b) **Plain words for the counts.** Each count counts
  every warning, watch or advisory issued for the zone once per event, including ones later cancelled or upgraded; the legend
  says so and never says "archived products"; whether to show issued-only counts is an owner item with the figures. (c) The
  name of the platform that serves a public data set ("NOAA Open Data on AWS") and this repository's URL are not vendor names
  under the names rule (D117(c), D118(e)). (d) **The map.json budget.** The B6 words that only the sheet or a toggled layer
  needs go into a second Python-built data file, data/base.json, named from map.json with its as_of; map.json keeps the
  first-paint pointer (the tile URL templates, zooms and state) and its 163,840-byte raw gate (D82(a)); the D29 and D41 rule
  reads "every word the browser prints comes from map.json or from a data file map.json names, built by Python". (e) The
  phone view gate (700,000 bytes gzip, D82(b)) is measured by the integrator's smoke with the default layers; the zone
  outline file loads only when its layer is on. (f) The 36 building shards over the raw split threshold stay accepted
  (D112(j)); the daily job keeps the buildings verify before the labels pass; the threshold's treatment of flag bytes is an
  owner item. (g) hail.check_manifest runs on the assembled store, never on a partial test store.

## Supervisor rulings on the P2 rulings pass (2026-10-26 08:45 UTC; D126)
The P2 rulings pass (wf_4a61607c-6a4) applied all 21 items (110 tests; verify 24 of 24; the shared base index refused when
foreign; the collapse-move rule; coverage counts; the two water statements; first-paint names; a missing shapefile reader as a
named failure). Two record-keeping items failed (a stale parenthesis in integration.md; report.md not rewritten because the
harness refused the write) and were corrected by the supervisor by hand (report-rulings-pass.json holds the pass's report).
- D126 (a) The collapse-move rule stands: a feature that collapses at a band's tolerance moves to the next finer band with its
  minimum zoom raised to that band's first zoom (136 parks B to C, 27 of them C to D, 1 lake C to D; band C 109,088 gzip bytes,
  within budget). (b) Cache pruning runs only after a statewide online run with no failed request, never after an offline run,
  a test box or a deadline stop (stricter than the brief; accepted). (c) The integrator assembles the store copy from the
  product test stores; any base index written with the old "format" key is removed first and the three base parts rebuilt.
  (d) P2 is final for the integrator.

## Supervisor rulings on the P4 rulings pass (2026-10-26 09:00 UTC; D127)
The P4 rulings pass (wf_0d6568a7-302) applied the items (60 history tests, 34 label tests; the newest-warning date from the
counted rows, 2026-10-10; plain legend words; the picture bounds pinned to gridded.IMAGE_BOUNDS; the unread cache pages
deleted; the map.json budget table: 139 bytes raw for the first paint, 4,029 bytes for the second data file). Three items
need rulings:
- D127 (a) **P4-R6 amended.** The zone outline download is checked as a file of zone outlines before it is written and its
  SHA-256 is recorded; nothing is pinned, because the service puts a per-request id in the file so the bytes differ on every
  fetch; the valid date in the file name names the snapshot. (b) **Once per event is deferred.** The store's zone rows and
  polygon rows carry no VTEC event number, so the counts count the rows the store holds and the legend says so in plain words;
  carrying the event number in the joins and counting once per event is a B7 item for the owner (the figures: 1,603 of 2,544
  high wind warnings later cancelled; 1,711 of 2,010 high wind watches upgraded; 393 of 514 flood watches cancelled). (c) **The
  P4 notes are cleaned before the integrator reads them**: every section of integration.md agrees with its section 11
  (no block copied into map.json; newest_warning words; the measured bytes; 60 tests; no "archived products"; the Source: credit
  line); the integrator's run does this as its first step. (d) P4 is final for the integrator.

## Supervisor rulings on the first integrators (2026-10-26 09:45 UTC; D128)
The integrator run (wf_7425e7dc-00f) has finished the P4 notes cleanup, task 1 (build.py: the map.json pointer and
data/base.json; 301 site tests; map.json 163,250 bytes against the 163,840 gate on the adopted store), tasks 3 and 4 (the
jobs, website.yml, .gitignore, AGENTS.md; 111 workflow tests) and task 6 (docs: D107 to D127 bullets, DESIGN section 13,
ROADMAP open items, README). Rulings on the decisions they put to the supervisor:
- D128 (a) **One bubble legend.** The printed legend is the D110(c) sentence in labels.words.legend; the P4 module's own
  label_legend text is retired after the integrator finishes (a post-integration fix round on the product files). (b) **Rule 5
  words in the modules.** The P2 and P4 unavailable and partial sentences gain the words "Data unavailable" in their own WORDS
  (as P1 did under D117(b)); build.py's lead words stay as the safety net. (c) **Budgets** live in data/base.json "budget";
  hail.budget keeps the phone and tile-event budgets the smoke reads. (d) **map.json headroom** is 590 bytes on the adopted
  store: no further first-paint key goes into map.json. (e) **The landmark mirror.** landmarks.py writes its block into the
  hail/index.json "base" mirror as the other two writers do (post-integration fix). (f) **The monthly job.** The cap of 110
  minutes and the 80-minute clock stand; the daily B6 steps run on the 60-minute clock after the B5 steps; the terrain step
  gets a 25-minute cap (1,500 s, deadline 120 s earlier) because a cold month takes 1,175 s; the monthly terrain build re-reads
  the two service descriptions without re-fetching unchanged tiles (a --refresh-descriptions flag in terrain.py, post-integration
  fix; the data month in the cache key triggers the re-fetch when the data changes); a full --refresh runs only when the owner
  asks. (g) **Docs calls confirmed:** the counsel numbering follows the rulings (21 park and landmark terms, 22 AirNow, 23 Forest
  Service, 24 NHD); the live hail legend ends with the quoted form of the DESIGN section 11 sentence; a "Fire and EMS stations"
  chip is in the sheet; churches show a "Held" chip state with the reason and no count; the landmark sub-line reads "from the
  public lists named under About". (h) tools/smoke_map.py learns data/base.json in the B6-3 browser pass.

## Supervisor rulings from the landmark source skeptics (2026-10-26 10:05 UTC; D129)
The landmark source pass (wf_b7916376-008; 118 agents; 58 claims, 47 standing) ended. The refutations are licence-scope and
figure corrections: the HIFLD public school and hospital copies carry no licence text of their own (the NCES EDGE layers are
public domain in their own metadata, so P3 reads NCES directly and keeps the HIFLD hospital copy as the tested fallback with its
terms marked not checked, D118(a)); the FEMA copy of the IRS-based places of worship is not a public-domain source (the church
kind stays held, D112, D118(b)); the TIGER 2026 point landmark file (tl_2026_30_pointlm.zip, park code K2190) holds park points
the area landmark file lacks ("Mc Cormick Park", Missoula), a second TIGER file for the park chips once counsel clears the TIGER
use constraints; the "all attributes" byte figures for the NHD layers were six-attribute figures; FTYPE 466 is "Swamp Marsh",
not "Estuary"; the band D 504 answers came after about 60 s, not 30 s. None changes a built product.
- D129 (a) The TIGER point landmark file is recorded as a future park point source under the same counsel item as the area
  landmark file. (b) The research record's corrected figures are the record; the products cite none of the wrong ones. (c) The
  skeptic scratch (1.5 GB under landmarks/refute) is deleted; the journal and the result are archived on the state branch.

## Supervisor rulings on the About and CONTRACTS integrator (2026-10-26 10:20 UTC; D130)
Task 2 and task 5 (wf_7425e7dc-00f, integrate:I2) wrote 23 CONTRACTS rows and the About sections (315 site tests). Rulings on
its open points, folded into the post-integration round:
- D130 (a) The nClimGrid grid words of D113(c) apply to every printed grid sentence, so P4's heat legend takes them; the B5 town
  page's "about 4.6 km north to south and about 3 km east to west" says the same figures in other words and stands. (b) The
  About page prints the credit line of the hospital source the store actually used, never a line for a source not read; a
  credit date the index lacks prints "Data unavailable", never "date not recorded". (c) The TIGER credit line covers the place
  names ("reservations, roads and place names"). (d) The words-rule exemption for a USGS service path in a citation stands
  (D117(c)). (e) The About sentences that describe the browser (tint zooms, dark mode, the Highlight switch, bubble overlap,
  the water line) are checked in the B6-3 browser pass against the page as drawn.

## Supervisor rulings on the integrator's build and smoke (2026-10-26 11:15 UTC; D131)
Task 8 (wf_7425e7dc-00f, integrate:I5): the whole suite 2,439 tests OK (12 skipped) after three workflow pins followed the
job edit; self-test PASS; the store copy built in place by the four writers (hail.check_manifest OK, 48,305 files, 2,428 of
them B6); the site built in 95.4 s (665 MB); the history-flag map.json 128,522 bytes raw (35,318 under the 163,840 gate) and
data/base.json 30,861 bytes; the smoke passed after its imagery credit words followed D110(d). Rulings on its open items:
- D131 (a) **Gate scope.** The 163,840-byte raw gate of D82(a) is the history-flag build's; the every-flag build (397,716 bytes
  raw with --hail-addresses) is recorded, not gated, as D82(a) already did (464,802 bytes then). (b) **Local labels.** The
  local store copy labels the Billings tiles r0092_c0214 and r0092_c0215 and the Missoula tile, so the smoke's Billings
  address sees bubbles; statewide labels come from the daily job. (c) **The sheet water line** of D122(b) is a key of the sheet
  block in data/base.json, imported from basemap2.WORDS (post-integration site item F3). (d) **Reports.** When the harness
  refuses a subagent's report file, the supervisor writes the report from the structured result (done for P2 and for the
  integrator: build/integrator/report.md and integrator-reports.json). (e) The three words-gate hits in index.html (expect,
  expected, likely) are traced by the final checker; the suite's words gate passes, so they are exempted words to confirm.
