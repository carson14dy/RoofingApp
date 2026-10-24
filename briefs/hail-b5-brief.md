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
