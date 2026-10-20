# Synthesis: streets, house shapes and the past-weather history

Inputs: 15 worker records and their 15 refuter records in /home/user/wt/research-b35/, the B2, B3 and B4 briefs in /home/user/wt/briefs/, the existing draft /home/user/wt/briefs/hail-b5-brief.md, and AGENTS.md rule 5. All 15 refuters say the recommendation stands, with corrections or conditions. The corrections are applied here, and the worker figure is named where it was changed. Each number carries its record in square brackets; the key is the file name without .json (section 5 lists them). Readings of terms are not legal advice.

## Bottom line

- Streets: Census TIGER/Line 2026 All Roads is the one source with a stated federal basis, and it covers every vehicular class in the 56 county files. Most rural lines will have no name: 62.8 percent of statewide vehicular features are unnamed [streets-refuter]. Labels for those lines need a second name source or an owner decision.
- House shapes: the FEMA and ORNL USA Structures file (918,052 footprints, dated 2026-09-13) is the shape source. Its licence is not established for that file, so no tile is published until FEMA and ORNL confirm in writing [footprints-refuter]. Microsoft and Overture footprints are ODbL and stay out of published tiles [footprint-alternatives-refuter].
- One dot per house, as asked: every footprint gets a dot. Addresses join to a footprint when they are inside it or within 15 m. An address farther than 15 m keeps its own dot [footprints; B3 brief D15].
- Past weather: nClimGrid-Daily gives daily highs, lows and rain as grid estimates for 25,902 land cells [temperature-rain-grid]. NOHRSC gives a snow analysis by water year, with units still unconfirmed [snow-alternatives-refuter]. GHCN-Daily from NCEI gives station snow, rain and temperature [snow-stations]. IEM and NCEI give flood, ice, heat and wind products [flood-ice-heat-products]. NWPS and USGS give river gauges [river-flood-gauges]. FEMA flood zones are held.
- The daily job is not scheduled today: the store workflow is not on main, and scheduled runs fire only from the default branch [volume-and-job-budget].

## 1. Decision table

| Need | Recommended source | Legal basis (quoted terms) | Montana size and per-tile bytes | Cadence and lag | Refuter corrected | Open question |
|---|---|---|---|---|---|---|
| Streets (every vehicular class, named where the source names them) | Census TIGER/Line 2026 All Roads, 56 Montana county road files. Eight vehicular classes: S1100, S1200, S1400, S1500, S1630, S1640, S1730, S1740. Address ranges (TIGER ADDR) are a fallback only [streets-msl-vs-tiger] | "The TIGER/Line Shapefile products are not copyrighted however TIGER/Line and Census TIGER are registered trademarks of the U.S. Census Bureau. These products are free to use in a product or publication, however acknowledgement must be given to the U.S. Census Bureau as the source." [streets-msl-vs-tiger, legal] | Zip total 88,859,641 B [streets-msl-vs-tiger]. Vehicular JSON at 5 decimals: 168.95 MB before simplification, 77.07 MB at 2 m, 54.67 MB at 5 m [streets-refuter]. Store tile r0092_c0214: 165,392 B raw, 39,227 B gzip [rendering]. Shard cap 150,000 B [rendering] | Annual edition. TIGER2026 dated 2026-10-06 [streets-msl-vs-tiger]. TIGER2025 metadata dated 2025-09-18 [streets]. Release lag not checked | 62.8 percent of 213,613 vehicular features unnamed (county range 18.0 to 94.7 percent), not 23 to 55 percent [streets-refuter]. Sizes 77.07 and 54.67 MB, not 69 and 48. Dedupe must keep names. Census line on the cover or first page, not only the About page [streets-refuter] | Owner: accept unlabelled rural lines, or add a second name source. MSL names 99.9 percent of its records, reuse not confirmed [streets] |
| House shapes (footprints) | FEMA and ORNL USA Structures, MT_Structures_20260913.zip: 918,052 footprints, WGS 84, geometry only [footprints] | The 2026 file's metadata gives access and use constraints as "None" (two elements on consecutive lines) [footprints]. The Esri-hosted copy of a 2025 snapshot says: "This work is licensed under a Creative Commons by Attribution (CC BY 4.0) license. See Credits and Map for Attribution." [footprints, terms] No licence is established for the 2026 file | 135,516,372 B at 5 decimals [footprints]. Per zoom 15 map tile: median 427 B, p99 26,471 B; densest Billings tile 57,036 B JSON (10,773 B gzip) [footprints]. Per B1 tile: median 5,865 B, max 4,539,221 B [volume-and-job-budget]. 5,143 shards at a 250,000 B cap, 135.8 MB raw [rendering]. Live 2025 copy (768,908 features) about 92 MB raw, estimate [rendering-refuter] | File dated 2026-09-13; S3 Last-Modified 2026-09-22. Annual or on change, in a separate job [footprints; volume-and-job-budget] | The CC BY 4.0 statement is on the June 2025 hosted snapshot, not the 2026 file [footprints-refuter]. The 2023 deliverable limits access to FEMA's Response Geospatial Office and mentions personal data. The CC0 reading of the Figshare copy is wrong [footprints-refuter] | FEMA and ORNL written licence before any publish. Inputs named in metadata: LightBox SmartParcels, HIFLD, National Address Database. Only geometry is read [footprints] |
| Dot per house and address dots | Footprints (row 2) joined to MSL Structures and Addresses Framework points: 674,715 points, 663,759 rows after merge on the 2026-09-30 file [footprints; B3 brief D22] | "The Library makes these data and services available as a convenience to the public, and for no other purpose." Accconst: "None. All data contained in the Framework are publicly available and non-sensitive." The library's terms do not address commercial use [B3 brief; streets-msl-vs-tiger, legal] | About 1.0 million dots on the file basis: 918,052 house dots and 81,805 address dots farther than 15 m [footprints]. Billings phone view at zoom 15: 3,737 dots, 193,379 B gzip footprint shards, 87,368 B gzip address shards [volume-and-job-budget]. Address shards: 4,211 files, 43.1 MB raw, largest 171,818 B [volume-and-job-budget] | Addresses monthly (file exported 2026-09-30). Footprints annual or on change [B3 brief; volume-and-job-budget] | Billings with every nearby footprint: 535 inside, 314 within 15 m, 20 farther. Statewide exact tests: 143,301 within 15 m, 81,744 farther, 376,694 footprints (41.0 percent) with no address inside or within 15 m [footprints-refuter] | Owner: dots from zoom 13 (B3) or 15 (rendering). Zoom 13 needs 4.18 MB of shards for a 1280 by 800 Billings view, zoom 15 needs 0.79 MB [rendering] |
| Temperature highs and lows | NOAA nClimGrid-Daily scaled monthly files, tmax and tmin, 1/24 degree, 25,902 land cells in 4,568 B1 tiles [temperature-rain-grid]. Not used: PRISM, and gridMET and Daymet as later supplements only [temperature-alternatives] | NetCDF attribute: "license = no restrictions" [temperature-rain-grid, terms]. NODD: "NOAA data disseminated through NODD are open to the public and can be used as desired." [legal-terms-review] Public-domain wording only if the owner accepts 17 U.S.C. 105 and 101 as the basis [temperature-rain-grid-refuter] | One scaled month: 56,872,702 B whole, 40,961,974 B for three variables by Range. 60 months: 3,548,877,305 B [temperature-rain-grid]. Per tile with five season records: median 2,024 B, max 3,056 B, 337 B per cell. All tiles 8,739,694 B raw, 1,211,475 B gzip [temperature-rain-grid] | Scaled month 4 to 68 days after month end (median 66). Preliminary days 2 to 3 days behind. Newest scaled month 2026-09, created 2026-10-06 [temperature-rain-grid; volume-and-job-budget] | Cell is 4.6 km north to south and 3.0 to 3.3 km east to west, not 4.6 km across. Stored values are unrounded, so sums use daily values rounded to 0.01. A new preliminary day costs 1.8 MB with metadata. Airport USW00024033 is at 45.8072 N, 108.5461 W [temperature-rain-grid-refuter] | The 90 F rule (32.222 C or 322 tenths). Backfill must start July 2021 for July to June seasons (63 months, not 60) [roof-indicators; section 3] |
| Rain by year | nClimGrid-Daily prcp for calendar, water and July to June totals. GHCN-Daily PRCP at the two nearest passing stations as the station row [temperature-rain-grid; snow-stations] | As the row above, and as the snow row for GHCN | June 2025 precipitation chunks 7,583,742 B of the 40,961,974 B three-variable total [temperature-rain-grid]. Included in the tile figures above | As the temperature row | Billings July 2025 is 43.01 mm after rounding (not 43.02). The grid is 18.8 mm above the airport in July 2025. Calendar 2025 Billings: 468.94 mm, NCEI monthly sum 468.98 mm [temperature-rain-grid-refuter] | Show grid and station rows side by side. 71 water cells have no value and must read "no land value", not zero [temperature-rain-grid] |
| Snow by year | (a) NOHRSC season-total snowfall GeoTIFF per water year, 0.04 degree, labelled "analysis" [snow-alternatives]. (b) GHCN-Daily SNOW and SNWD at the two nearest passing stations, from the NCEI .dly files, not the S3 copies [snow-stations]. SNOTEL and SNODAS not used for towns | NWS: "The information on National Weather Service Web servers and Web sites is in the public domain, unless specifically annotated otherwise, and may be used freely by the public." with three conditions [flood-ice-heat-products, terms]. NOAA station records: NCEI-PD-10-2-02 section 4(a), "are in the public domain in the United States" [snow-stations-refuter]. CoCoRaHS records (176 files): CC BY 3.0 with acknowledgement [snow-stations-refuter] | NOHRSC 2,354,154 B (2025-26), 2,402,986 B (2024-25); five water years 11,562,084 B; Montana box 34,916 cells [snow-alternatives-refuter]. GHCN: 481 stations with a 2025 record, 392,170,950 B; 42 within 40 miles of the two sample points, 27,734,670 B [snow-stations; snow-stations-refuter] | NOHRSC 2026-27 file regenerated (Last-Modified 2026-10-19 03:18:11 GMT). GHCN .dly last modified 2026-10-18, newest value 2026-10-16. Archive values replace real-time values 45 to 60 days after month end. 114 S3 by-station files (89 SNOTEL, 25 WBAN) stop at 2025-02-06 [snow-alternatives-refuter; snow-stations] | 2020-21 NOHRSC file is missing, so "one per water year" is overstated. Five-season JSON is 1.54 MB, not 2.46 MB. 42 stations and 27.7 MB, not 45 and 33.7 MB [snow-alternatives-refuter; snow-stations-refuter] | NOHRSC units: Billings 2024-25 reads 50.29 against the airport's 64.3 in. The unit check must pass before display [snow-alternatives; hail-b5-brief D9]. Water years run October to September, the roof table runs July to June |
| Flooding | IEM watch and warning archive: polygon products FL.W (43 in window), FA.W (37), FA.Y (548), FL.A (35), FL.Y (10), SQ.W (78). Zone FA.A (64 zone and 18 county-only in window) and FF.A (18 zone, 2 county-only). NCEI Flood (76) and Flash Flood (60) county-coded points, 2020 to 2026. Nearest flood-stage gauge within 10 miles from NWPS, with USGS annual peaks. FEMA flood zones held [flood-ice-heat-products; B2 brief D35; river-flood-gauges] | IEM: "The materials found on this website are in the public domain and may be used freely by anyone for any lawful purpose." Its footer says "All rights reserved": a conflict to resolve [river-flood-gauges, legal]. NWPS gauge: "Observations courtesy of U.S. Geological Survey" [flood-ice-heat-products, terms]. NFHL service: copyrightText empty; FEMA terms not read (403) | Gauge table: 97 USGS series, 7,084 rows, 207,359 B raw, 54,253 B gzip [river-flood-gauges-refuter]. 15-minute stage not shipped (2.40 to 2.78 MB per gauge per water year). B2 files: hail/j/ 19,912,416 B, hail/z/ 919,402 B [B2 brief round 5] | IEM by year, current year re-pulled daily. NWPS live. USGS water-year peaks. USGS waterservices retires 2027-02-22, degraded from 2026-11-16 [river-flood-gauges] | FL.W returns zero events on the zone path (polygon rows). FA.A has 69 zone events in 2020 to 2026 (64 in window). FF.A is mostly zone-coded (24 of 28). Livingston is inside two June 2022 polygon blocks, so 10 towns (not 11) are inside none [flood-ice-heat-products-refuter; river-flood-gauges-refuter] | Gauge distance: 10 miles proposed, 25 miles covers 69.6 percent of Montana [river-flood-gauges]. FEMA zone display (counsel). County boundary licence not read [flood-ice-heat-products] |
| Ice and winter | IEM zone WW.Y (865 in window), WS.A (226), FR.Y (14), FZ.W (4). B2 already reads WS.W, BZ.W, IS.W, WI.Y. NCEI zone rows 2020 to 2026: Winter Storm 740, Winter Weather 383, Ice Storm 14, Blizzard 126, Frost/Freeze 25. LSR freezing rain (B2). Grid freeze-thaw days. Station days with snow on the ground and a low below 32 F [flood-ice-heat-products; roof-indicators; temperature-rain-grid] | IEM and NWS lines as in the flooding row. NCEI Storm Events text not read (metadata page 503) [legal-terms-review]. Roof reference lines R10 and R11 are quoted references, not findings [roof-indicators] | All B2 zone files: 919,402 B, 115 files [B2 brief round 5]. New products not yet measured | As flooding. NCEI annual, newest event shown as the lag | The flood record's totals (WW.Y 1,155, WS.A 276, FR.Y 17, FZ.W 5) are 2020 to 2026 totals. Window counts are 865, 226, 14 and 4 [flood-ice-heat-products; IEM table]. NCEI has no Freezing Rain event type in Montana [roof-indicators] | Strict or inclusive 32 F freeze-thaw rule [roof-indicators]. Freezing rain magnitude may be liquid or ice (unverified) |
| Heat | Grid days at or above 90 F (site threshold). Station days at or above 95 F and 100 F and station extremes from IEM daily. IEM HT.Y (58 in window), EH.W (4), EH.A (3). LSR EXTREME HEAT (2025-05-31 to 2025-08-19). NCEI Heat (10 zone) and Excessive Heat (3) [temperature-rain-grid; montana-events-2020-2026; flood-ice-heat-products] | NWS and IEM lines as above | IEM daily: 2,483 days per station, live pull 2026-10-19 [montana-events-2020-2026]. Grid as the temperature row | IEM daily, local calendar day. Grid as the temperature row | IEM and GHCN highs differ by up to 8.9 F (Billings), 16.2 F (Great Falls), 10.0 F (Missoula). Lows differ by a mean of 0.8 to 1.3 F. Not "up to 9 F" [montana-events-2020-2026-refuter] | 90 F is a site threshold; NWS heat thresholds are set regionally [roof-indicators]. NCEI has no heat rows for 2025 or 2026, though LSR has reports on 2025-08-19 [montana-events-2020-2026] |
| Wind additions (beyond B2) | IEM HW.A (high wind watch): 277 in window, 348 in 2020 to 2026, zone path [flood-ice-heat-products]. B2 keeps LSR wind types, NCEI High Wind (2,967 zone rows) and Strong Wind (68), and station gusts at 50 knots or more. Rules: reclassification (Missoula 2024 was thunderstorm wind) and a 130 knot cut for station gusts [montana-events-2020-2026] | NWS and IEM lines as above | HW.A rows in the zone files, not measured separately | IEM daily. NCEI annual | 50 knots is 58 mph in NWS wording and 57.5 mph by plain conversion. The site states which [roof-indicators] | A non-thunderstorm gust shows its recorded type word, never a type inferred from speed (the Missoula case) [montana-events-2020-2026] |
| Roof indicators ("weather that matters for a roof") | Derived from the rows above: 23 indicators with a public source; four Data unavailable lines (roof ponding, lightning, UV and sunlight, roof surface temperature). Ground snow load (a design value) held out. SNOTEL snow water equivalent not joined [roof-indicators] | Each reference line quotes its source with its URL (R1 to R20). NWS disclaimer conditions apply to NWS-derived text. A reference is not a finding about any roof [roof-indicators; roof-indicators-refuter] | Five-season table: 15 data rows and one unavailable row. Per-cell size not measured [roof-indicators] | Follows the rows above. Seasons July to June. A partial season from July 1, 2026 to the build date is a line, not a column [roof-indicators] | 90 F counts use 322 tenths of C. The M6 highs series [37, 40, 21, 33, 22] becomes [45, 42, 27, 35, 25]. Snow depth of 1 inch is 25 mm in GHCN, so the M6 snow series [55, 70, 30, 49, 18] becomes [55, 70, 30, 53, 25]. IEM and GHCN maxima differ by more than 1 F on 131 days. IS.W office is Great Falls. Nine LSR types (151 rows) are missing from the type list [roof-indicators-refuter] | Freeze-thaw rule and precision. 95 percent season coverage is a proposal. Benchland station: Moccasin fails temperature coverage in 2022, 2023 and 2025; Lewistown 42 WSW has no snow elements [roof-indicators] |

### 1.1 Corrections to earlier briefs

B3 brief (the B3 branch):
- D14: footprint shards are capped at 250,000 B, not 2,500 footprints. The 2,500-footprint rule leaves 52 shards over 300 KB, the largest 464 KB [rendering]. The fill draws from zoom 16, not 15 [rendering].
- D15: keep "every footprint gets a dot" (owner request). This supersedes the footprint worker's "shape only" rule for footprints with no address [footprints]. The zoom for address dots is an owner decision (section 4.2).
- D16: statewide vehicular JSON is 77.07 MB at 2 m, not 69 MB [streets-refuter]. Shards are 150,000 B, not 2,000 segments [rendering]. Statewide 62.8 percent of vehicular features are unnamed, which the brief does not say [streets-refuter]. Concurrent-route overlap is 13 to 22 percent (Billings) and 66 to 75 percent (Benchland), depending on junction handling, not 18.8 and 74.9 [streets-msl-vs-tiger-refuter]. Placeholder count 23,618 (9.15 percent) in D16a is correct; the worker's 22,662 is superseded [streets-msl-vs-tiger-refuter]. The Census line sits on the first screen of the map or an equally visible place, not only the About page [streets-refuter].
- D5: the hail/a/ shards hold only addresses that are not on a house dot (section 2.3). The search index keeps every row.
- D13: About cites MCA 2-6-1017 only. This is already in D13 and is confirmed by the legal record [legal-terms-review].

B2 brief (the B2 branch):
- D35 is confirmed. Ten zone products are read, FA.A included, and FL.W stays on the polygon path for B5. The 18 county-only FA.A events go to B5's county path [B2 brief D35; flood-ice-heat-products-refuter].
- The NCEI and LSR type names that B2's words mention but its code does not read (tornado, flash flood, flood) move to B5 [B2 brief D34].

B4 brief (the B4 branch): no change. The live swath layers and the sheet's live line are not touched by B5.

Existing draft hail-b5-brief.md:
- Source 1: a new preliminary day costs 1.8 MB with the 0.46 MB of file metadata, not 1.4 MB [temperature-rain-grid-refuter].
- Source 1 and D3: the backfill starts October 2021 (60 months). The five July to June seasons need July 2021 to September 2026, 63 months [roof-indicators; section 3].
- Source 2 and the product list: NOHRSC values are water years. The table labels them so.
- Source 3: 42 stations within 40 miles, 27.7 MB, not "about 34 MB for the 45 candidates" [snow-stations-refuter].
- Source 4: the county boundary file is TIGER counties, read under the Census statement. "Public domain" is not the basis [legal-terms-review].
- Source 5: the NCEI county-coded counts (76, 60, 144, 17, 35, 8, 11) are 2020 to 2026 totals, not window counts [flood-ice-heat-products].
- Source 5: BEGIN times are MST on Montana rows. Of 761 matched hail pairs, 679 differ by +7 h. The "768 of 932" figure is not reproduced [montana-events-2020-2026-refuter].
- Source 6: WIND CHILL starts 2024-01-11; EXTR WIND CHILL ends 2023-02-24 [flood-ice-heat-products-refuter].
- D1: one rule for 90 F, chosen in section 3 (D1).
- Gate 5: the Hays tornado (2021-07-07) is outside the five-year window, which starts 2021-10-19 [montana-events-2020-2026]. Use Glentana (T04, 2022-07-18 23:47 UTC) or Richland (T05, 2023-06-02 01:56 UTC).

### 1.2 Conflicts between records, resolved here

- TIGER edition: the streets worker picked 2025 and the MSL comparison picked 2026. This synthesis uses 2026, because it is newest and carries the ADDR files. Zip totals differ by 809 bytes, and the sizes are the same either way [volume-and-job-budget].
- Footprint copy: the 918,052-feature file and the 768,908-feature live layer (June 2025 snapshot) differ by 16.2 percent [footprints; rendering-refuter]. The file is the source, and each figure names its copy.
- Footprint dots: "shape only" (footprint worker) against a dot per house (owner request, B3 D15). The owner request wins.
- Footprint shard rule: 2,500 footprints (B3 D14) against a 250,000 B cap (rendering). The byte cap wins.
- Address dot zoom: 13 (B3) against 15 (rendering). Recommended 15, owner decision.
- 90 F rule: 32.222 C unrounded (existing D1) against 322 tenths of C (roof counts). Section 3, D1 recommends the second.
- Windows: the roof table runs July 2021 to June 2026 and the partial season to the build date. Reports run 1,826 SPC days from 2021-10-19 [B2 brief]. Both windows are shown and labelled. The backfill starts July 2021.
- Placeholder names: 22,662 (worker) against 23,618 (refuter, 9.15 percent). The refuter's count is used [streets-msl-vs-tiger-refuter].
- Address terms: the MSL metadata is a disclaimer with "for no other purpose", and gives no licence [streets-msl-vs-tiger, legal].

## 2. Draft section for the B3 brief: "B3 additions: streets, footprints and the dot per house"

### 2.1 Scope

This adds three layers to B3 behind the same flag (--hail-addresses): roads, house outlines with one dot per house, and the join of addresses to houses. B3's rules stay: no owner, parcel, place-type, building-use or occupancy field is read, and nothing says who lives at an address (decision 6, D12). The flag stays off on main until the owner and counsel answer section 4.

### 2.2 Modules and jobs

- `website/streets.py` (new): reads the 56 TIGER county road files with pyshp (job-only, lazy import, as B2 does). Keeps the eight vehicular classes. Merges exact duplicate geometry and joins the names with " / ", so no name is lost (2,159 exact duplicate vehicular features statewide) [streets-refuter]. Treats placeholder names as unnamed: "Internal" on TIGER, and Dwy, Driveway, Unknown, Unnamed, No Name on the state file if it is ever used [streets-msl-vs-tiger-refuter]. Simplifies with Douglas-Peucker in metres at 2 m (validated to 1.998 m). Writes 5-decimal coordinates and the 150,000 B shards.
- `website/buildings.py` (new): reads the FileGDB member with pyogrio (job-only, lazy import; the footprint refuter read the file with pyogrio and shapely wheels) [footprints-refuter]. Geometry only: an allow-list of the geometry, and a test that asserts none of OCC_CLS, PRIM_OCC, PROP_ADDR, SQFEET, HEIGHT, POP_MEDIAN, B_CODE, OUTBLDG and SEC_OCC is read. Rings at 5 decimals, no simplification (0.5 m saves 0.1 percent, 1 m saves 0.9 percent) [footprints]. Writes the shards, the house dot and the join.
- `website/addresses.py` (B3): writes the unmatched-address shards (section 2.3). The search index is unchanged.
- Tests: `tests/test_streets.py`, `tests/test_buildings.py`. The fixture holds real rows from the 401 North 27th Street block (about 300 rows) and a three-footprint block, under 50 KB.
- Jobs: three workflows, so each stays under the 60-minute timeout. Addresses monthly (65.8 MB zip; build 37 s; verify 9 to 39 s). Roads and footprints annual or on change: the statewide road parse is estimated at 26 to 35 s, and the footprint geodatabase read is not timed [volume-and-job-budget].
- Publishing place (owner decision): bulk files of about 358 MB raw (71 MB gzip per deploy) belong on a second Pages site in a data repository, not on the 10-minute site, which re-uploads everything on each run [volume-and-job-budget].

### 2.3 File layouts under hail/

- `hail/r/<name>.json`: roads. `{"f":"hail-roads-v1","b":[west,south,east,north],"n":count,"c":["S1100",...],"names":["...",...],"l":[[class_index,name_index,[[lon,lat],...]],...]}`. Name index -1 means unnamed. The name table cuts repeated names; the saving is not measured [rendering]. Quadtree on the B1 grid, 150,000 B cap.
- `hail/b/<name>.json`: house outlines and dots. `{"f":"hail-buildings-v1","b":[...],"n":count,"a":[[[[lon,lat],...outer ring],[[lon,lat],...hole ring],...,[dot_lon,dot_lat],[["line","city","zip"],...]],...]}`. The dot is the centroid when it is inside the footprint, otherwise the nearest interior point. The address list holds the lines inside the footprint or within 15 m, deduplicated, and is empty when none. 250,000 B cap, about 1,600 footprints per shard [rendering].
- `hail/a/<name>.json`: addresses that are not on any house dot (farther than 15 m from every footprint). `{"f":"hail-addresses-v1","b":[...],"n":count,"a":[[lon,lat,"number street","city","zip"],...]}`. About 81,800 rows statewide, estimate 5.3 MB raw at 65 bytes per row [volume-and-job-budget]. 2,500-row rule.
- `hail/a/idx/cities.json` and `hail/a/idx/<city-slug>/<key>.json`: the B3 search index, unchanged. It holds every address row, because search must find addresses on house dots too [B3 brief D5]. Largest letter file 149,537 B (7,501 files, 39,012,417 B) [volume-and-job-budget].
- `hail/counts.json`: per B1 tile, the house count and the address count, for the zoom 13 to 14 count layer [rendering].
- `hail/index.json` gains `"roads"`, `"buildings"` and `"addresses"` blocks: counts, shard counts, largest shard, totals, depth histogram, source file date and size, the quoted use sentence, and `"state":"loaded"|"unavailable"`. `hail/manifest.json` lists every new file (B2's pattern).

### 2.4 Zoom thresholds and shard sizes

| Layer | From zoom | Why (rendering) | Shard rule and size |
|---|---|---|---|
| Arterials (S1100, S1200) | 13 | 1.1 px wide at zoom 13; 30 KB per view against 634 KB for every vehicular class | Own shard; 6.8 KB per store tile |
| Local streets (other vehicular classes) | 15 | 8 m street is 1.2 px at zoom 14 and 2.4 px at zoom 15 | 150,000 B cap; store tile 165,392 B raw, largest 0.05 degree subtile 70,992 B |
| House dots | 15 | Centroid dot about 22 B; 5,807 dots (127 KB) in a zoom 15 view | In hail/b/ with the outline |
| Footprint fill and hairline | 16 | 10 m house is 3 px at zoom 15 (a dot) and 6 px at zoom 16 | 250,000 B cap; store tile 4,539,221 B |
| Outline emphasis | 17 | 10 m house is 12 px at zoom 17 | Same shards |
| Street names | 16 | 706 of 888 names have a long enough piece at zoom 16; 612 kept after fit and collision tests | One per name per shard; at most 300 labels per view |
| Unmatched address dots | 15 (owner decision) | 13 needs 64 shards and 4.18 MB for a 1280 by 800 Billings view; 15 needs 10 shards and 0.79 MB [rendering] | 2,500-row rule; address store tile 2,161,010 B raw |
| Count layer | 13 to 14 | Count per tile from counts.json | No shard fetch |

Statewide totals on the file basis: 5,143 footprint shards, 135.8 MB raw [rendering]. 4,211 address shards, 43.1 MB raw, all addresses [volume-and-job-budget]. Roads: about 77 MB at 2 m, so at least 514 shards at the 150,000 B cap (estimate, not measured).

### 2.5 The join and the dot rule

- Coordinates: EPSG:6514 to EPSG:4326 with always_xy, rounded to 5 decimals (B3 D2). Five-decimal rounding moves a vertex at most 0.67 m [footprints].
- Each address row (after the B3 merge) is inside a footprint, within 15 m of one (distance to the nearest edge), or farther (unmatched).
- Every footprint gets one house dot (every footprint, per the owner's request). A footprint with no address inside or within 15 m shows the text in section 2.6 and still opens the cell history.
- An address inside or within 15 m is listed on its footprint's dot, deduplicated by line, unit and zip. Multi-unit buildings list their units. The largest co-located count is 141 at one point [B3 brief D7].
- An unmatched address keeps its own dot in `hail/a/`.
- Statewide counts on the file basis: 674,715 points; 449,670 inside; 143,240 within 15 m but not inside; 81,805 farther. Footprints: 552,791 (60.2 percent) with no address inside; 376,985 (41.1 percent) with none inside or within 15 m [footprints]. The refuter's exact tests give 143,301, 81,744, 376,694 [footprints-refuter]. The method is stated with the number.
- Billings test box (45.78 to 45.79 N, 108.51 to 108.50 W): 307 footprints (293 on the live copy); 869 points: 535 inside, 313 within 15 m, 21 farther (median 24.9 m); 131 footprints (42.7 percent) with no address inside; 28 with none within 15 m [footprints; footprints-refuter].
- Fixture: 401 North 27th Street has three MSL records, two at one spot. They make one dot with deduplicated lines. The brief's coordinate 45.7836 N, 108.5047 W is inside 175 North 27th Street's footprint, about 299 m from 401's point, so the fixture uses the real 401 point [footprints].

### 2.6 Words

- Dot legend (B3, unchanged): "Dots are addresses from Montana's public address list; tap one for its history."
- Building legend: "Each dot is one building outline. Tap a dot for its address, if one is on file, and the weather history for its cell."
- Address line (B3 D3): "{number} {street}, {city} {zip}".
- Units: "Units on file: {n}."
- No address: "No address on file for this building. The weather history below is for this building's cell."
- Attributions, one line each, on the About page and on the map's first screen: "Building outlines: USA Structures, Oak Ridge National Laboratory and FEMA (file dated 2026-09-13). Outlines come from imagery and are not surveys." "Roads: U.S. Census Bureau, TIGER/Line 2026, acknowledgement required. Census TIGER and TIGER/Line are registered trademarks, and the site does not use them in its name." "Addresses: Montana State Library, Structures and Addresses Framework (file dated 2026-09-30). Use terms: 'The Library makes these data and services available as a convenience to the public, and for no other purpose.'"
- Forbidden: no word says who lives at an address, what a building is, or who owns it. The test forbids "home", "house", "residence", "dwelling", "owner", "parcel" and "use" in these templates. "structure" is allowed only inside the proper names "USA Structures" and "Structures and Addresses Framework", because the roof record's forbidden list includes "structure" [roof-indicators].

### 2.7 Gates (added to B3 gates 1 to 8 as gates 9 to 18)

9. Counts: house dots equal the footprints in the shards (918,052 on the file, or the copy used, named). Every address row appears once, as a line on a house dot or as an unmatched dot. The sum equals the index rows (663,759 on the 2026-09-30 file) [B3 brief D22].
10. Join: the Billings box reproduces 869, 535, 313 and 21 with the 307 box footprints (535, 314 and 20 with every nearby footprint; the test states the scope). The statewide counts reproduce for the stated method.
11. No-address text: every dot with no address lines shows "No address on file for this building", and every dot opens the cell history. Count: 376,694 to 376,985 statewide.
12. Shards: largest footprint shard 250,000 B or less; largest road shard 150,000 B or less; largest unmatched-address shard 175 KB or less. Totals measured and compared with 135.8 MB (footprints) and 43.1 MB (addresses).
13. Roads: only S1100, S1200, S1400, S1500, S1630, S1640, S1730 and S1740 are drawn. S1710, S1720, S1750, S1780, S1810, S1820 and S1830 are excluded and the test lists them. Placeholder names are never labelled or searchable. Each merged line carries the union of its names.
14. Zoom: arterials from 13; local streets and house dots from 15; fills, names and footprint shards from 16; outlines at 17. A zoom 13 request fetches no footprint shard.
15. Fetch budget: a 390 by 844 phone view over Billings at zoom 15 loads no more than 650 KB gzip for all layers (607,375 B measured before B5) [volume-and-job-budget]. The request count per pan is logged.
16. Draw time: a Billings tile redraw at zoom 15 and 16 stays under 30 ms on the test machine (measured 11 to 27 ms) [rendering]. A 4 times CPU slowdown run and a phone check happen before release (not measured).
17. Field test: a test lists every DBF and footprint field the readers take, and asserts the forbidden list (owner, parcel, place type, use, height, occupancy, population) is absent.
18. Words and attribution: the About page and the map's first screen carry the Census, ORNL and FEMA, and MSL lines. Quoted terms carry the " [...] " marker. The words test passes with the proper-name allow-list.

Chromium smoke (replaces B3 gate 7's scope): 390 and 1280 px over Billings at zoom 15 and 17, with screenshots. Tap a house dot with addresses, a house dot with none, and an unmatched address dot. The search still finds "401 N 27th St Billings" and "Colony Rd Roundup". Zero off-site requests except the shard files.

## 3. Draft brief: "B5: the past-weather history per location"

### 3.1 Purpose

B5 adds, behind --hail-history, the summary table that leads each sheet and the sections for temperature, rain, snow, flooding, ice and winter, heat, wind additions and the roof lines. Owner request: "find the history of the locations past weather reports like the size of hail, wind, storm history, temperature highs and lows, Snow amounts annually, Rain annually, any flooding, and weather that would be an issue for a roof as well." Owner decisions D34 1, 2, 4, 5, 6 and 7 apply. Product north star: one sheet per place that leads with a plain summary, details in a fixed order, every number with its unit and kind word [B2 brief; B3 brief].

### 3.2 Phenomenon by path

| Path | Products and window counts (five years to the build date) | Where it lives |
|---|---|---|
| Polygon (IEM watch and warning polygons; cell covered when its centre is inside; per-tile cover as in B2) | FL.W 43; FA.W 37; FA.Y 548; FL.A 35; FL.Y 10; SQ.W 78; FF.W 148 (already in B2) [flood-ice-heat-products; B2 brief] | hail/j/ warnings |
| Zone (IEM zone rows, B2 period rule) | WW.Y 865; WS.A 226; HW.A 277; HT.Y 58; EH.W 4; EH.A 3; FR.Y 14; FZ.W 4; DU.Y 3; FF.A 18 (new); FA.A 64 (already in B2) [flood-ice-heat-products; IEM table] | hail/z/ |
| County (county boundaries from TIGER 2026 counties; county-only events) | FA.A county-only 18; FF.A county-only 2 [flood-ice-heat-products] | hail/k/ (new) |
| NCEI points (county-coded, within 5 miles of the cell centre), 2020 to 2026 totals | Flood 76; Flash Flood 60; Heavy Rain 144; Tornado 17; Funnel Cloud 35; Lightning 8; Debris Flow 11; 351 rows in all [flood-ice-heat-products] | hail/j/ records |
| NCEI zone rows (by zone), 2020 to 2026 totals | Winter Storm 740; Winter Weather 383; Ice Storm 14; Blizzard 126; Frost/Freeze 25; Heat 10; Excessive Heat 3; High Wind 2,967; Strong Wind 68 [flood-ice-heat-products] | hail/z/ |
| LSR (within 5 miles, all types; type words by date) | FLOOD, FLASH FLOOD, HEAVY RAIN, RAIN, FREEZING RAIN, HEAVY SNOW, SNOW, BLIZZARD, EXTREME COLD, WIND CHILL, EXTREME HEAT, LIGHTNING [hail-b5-brief; roof-indicators] | hail/j/ reports |
| River gauges (nearest flood-stage gauge within 10 miles) | 277 Montana gauges; 102 with flood stage; 97 USGS series [river-flood-gauges] | hail/g/ (new) |
| Station (GHCN-Daily, the two nearest passing per element) | SNOW, SNWD, PRCP, TMAX, TMIN [snow-stations] | hail/sd/ (new) |
| Grid (nClimGrid-Daily) | prcp, tmax, tmin per land cell [temperature-rain-grid] | hail/c/ (new) |
| Analysis (NOHRSC) | season snowfall per water year, 0.04 degree [snow-alternatives] | hail/n/ (new) |
| Held, not in B5 | FEMA NFHL flood zones; lightning strikes (commercial); UV and sunlight; roof surface temperature; roof ponding; ground snow load (design value) [roof-indicators; flood-ice-heat-products] | none |

### 3.3 Rules

- D1 Thresholds (choose once and state it on the page). Option A is the existing draft's: freeze-thaw day means tmax above 0 C and tmin below 0 C; 90 F means tmax at or above 32.222 C; a low below 32 F means tmin below 0 C. Option B is the roof counts' rule: 90 F means tmax at or above 32.2 C (322 tenths; 32.20 C is 89.96 F and shows as 90 F). Recommendation: option B, because it is the value GHCN stores, it shows as 90 F, and it matches the corrected roof counts [roof-indicators-refuter]. Supervisor to confirm.
- D2 Aggregates per cell per month: rain total; rain maximum and its day; tmax maximum and its day; tmin minimum and its day; days at or above 90 F; days at or below 0 F; freeze-thaw days; days with a low below 32 F; missing days. July to June seasons, calendar years and water years are sums of months. A month with missing days carries its count, and the page says "n days missing". Sums use daily values rounded to 0.01 before conversion. The -999.99 fill is never summed [temperature-rain-grid-refuter].
- D3 Windows: the five seasons (July 1, 2021 to June 30, 2026) and the partial season need scaled months July 2021 to September 2026, 63 files. The reports window is the trailing 1,826 SPC days from 2021-10-19 [B2 brief]. Both windows are shown and labelled. The backfill runs once: 63 whole files at 56.9 MB each (about 3.6 GB; about 2.6 GB if read as three variables by Range), at 31.8 MB per second locally [temperature-rain-grid]. The runner speed is not measured. The aggregates are cached as a release asset, about 1.2 MB per month (estimate).
- D4 Stores: section 3.5.
- D5 Cells: the B1 row and column rule computed in integer thousandths (row = round((54.995 - lat) × 100) and col = round((lon + 129.995) × 100), tile = r{row // 10} and c{col // 10}). Half-cell points are where Python floats and exact decimal disagree: the Benchland LSR point (47.08 N, 110.02 W) is row 791.5, and the Petrolia Lake point is column 2174.5 [montana-events-2020-2026]. Choose one half-rounding rule, state it, and test both points. The climate and NOHRSC cell functions use the same half-open rule. Gates probe with those functions only [hail-b5-brief D4].
- D6 Stations (GHCN-Daily, NCEI .dly): candidates within 40 miles with a report in the last 30 days. Coverage is the share of days in 2020 to 2025 (2,192 days) with an unflagged value, per element, at least 80 percent. Take the two nearest that pass. Fewer than two: show those that pass and say so. None: "No station within 40 miles has enough reports for {element} from 2020 to 2025." Season values show only when at least 95 percent of the season's days have the element. A missing day is never zero. Q-flags other than blank exclude a value [snow-stations].
- D7 NOHRSC: kind word "Analysis" and the water-year label. Units check: the Billings cell reads 50.29 for 2024-25 and the airport's season reads 64.3 in (.dly) [snow-alternatives; snow-stations]. The check result is recorded. If it fails or units are not confirmed, the product is left out, and the snow section shows station seasons only [hail-b5-brief D9].
- D8 River gauges: the nearest gauge with a defined NWS flood stage within 10 miles (owner confirms the cut-off). Exclude gauges with no flood stage and gauges whose categories are elevations of 1,000 ft or more (the nearest such gauge to a Montana grid point is Lake Pend Oreille at Hope, 13.7 miles away) [river-flood-gauges]. Key the table by USGS number (CBMM8 and CLRM8 share 06185110) [river-flood-gauges-refuter]. Show the gauge name, distance, flood stage and water-year peaks at or above flood stage. No daily flood-day counts. Per-address gauge lines wait behind the counsel gate [hail-b5-brief D6].
- D9 Periods (B2 D33, implemented here): rows ordered by product time; a CAN, UPG or EXP closes the current period; a later NEW, CON, EXT, EXA or EXB opens the next; each period is a span. The four named cases: MTZ004 WS 2024 event 1 (a CON on 11 January after a CAN on 10 January); MTZ302 HW 2022 event 38 (second cancelled period); MTZ320 WS 2023 event 4 (the period after cancellation); MTZ003 WS 2021 event 12 (two periods). The MTZ003 case may fall before the window; the gate checks it [B2 brief D33].
- D10 Season counts: an event counts in the July to June season in which its begin time falls, in Montana time. "Cancelled at {time}" and "upgraded" replace "{begin} to {end}" as in B2 D26 and D31 [B2 brief].
- D11 Time rules: NCEI BEGIN_DATE_TIME is MST (UTC-7) on Montana rows; of 761 matched hail pairs, 679 differ by +7 h; 76 differ by +8 h, 4 by +6 h and 2 by +9 h, and the record does not explain those [montana-events-2020-2026-refuter]. LSR VALID is UTC. IEM daily is the local calendar day. GHCN has its own day definition. SPC day runs 12:00 UTC to 11:59 UTC [montana-events-2020-2026].
- D12 Gusts: IEM daily gusts at or above 130 kt are dropped and counted. The 182.5 kt value at LWT on 2023-03-13 is dropped. The 105.1 kt (HVR, 2025-02-20) and 86.0 kt (MSO, 2025-05-09) values are flagged for check [montana-events-2020-2026]. Non-thunderstorm gusts show their recorded type word.
- D13 Words and claims: nothing states damage, loss, a claim, coverage, insurance, eligibility, a probability, risk or an all-clear. The forbidden list is the roof record's list [roof-indicators], extended to the six sheet strings the refuter found [roof-indicators-refuter]. "damage" appears only as a source type word, inside a quoted remark, or as "NWS damage threat tag". "structure" appears only in the proper names "USA Structures" and "Structures and Addresses Framework". "warrant" appears only inside quotation marks.
- D14 Held: FEMA flood zones (a designation tied to insurance; AGENTS rule 5; counsel first). Lightning strikes (commercial; NCEI lightning events are not strike counts). UV and sunlight, roof surface temperature, ponding (no public record). Ground snow load (a design map value, not history). SNOTEL snow water equivalent (not joined; access restricted at AWDB). Each held item gets a "Data unavailable" line that says why [roof-indicators; legal-terms-review].

### 3.4 Store files and index blocks

- `hail/c/<tile>.json`: one record per land cell in each 0.1 degree tile. Five July to June season records and the partial line. Integers: rain in hundredths of an inch, temperatures in tenths of a degree F, dates as yyyymmdd. 337 B per cell and 2,024 B median per tile for five records [temperature-rain-grid]. Water-year fields add about 30 B per cell (estimate) [volume-and-job-budget].
- `hail/n/<tile>.json`: NOHRSC season values for each 0.04 degree cell whose centre falls in the tile, five water years, integers in hundredths of an inch once the unit check passes. The Montana box is about 1.54 MB of JSON for five seasons [snow-alternatives-refuter].
- `hail/sd/<station>.json`: per station, per element, per July to June season and calendar year: total, days reported, days unflagged, newest report date, and the coverage counts used by the rule in D6. The .dly input for the 42 candidates is 27.7 MB; the shipped file holds only season and calendar summaries [snow-stations-refuter]. `hail/s/` stays B2's gust files.
- `hail/g/<usgs>.json`: gauge peaks by water year, 97 series, 7,084 rows, 207,359 B raw, 54,253 B gzip [river-flood-gauges-refuter].
- `hail/k/<county>.json`: county-only FA.A and FF.A events (18 and 2 in window) [flood-ice-heat-products].
- `hail/j/` and `hail/z/` (B2): polygon-product warnings with their tile covers, new zone-product events, FF.A events, and the period spans. B2's budget is 40 MB for j/ (19.9 MB today) [B2 brief].
- `hail/index.json` blocks `"climate"`, `"snow"`, `"stations"`, `"gauges"` and `"county"`: each has a state (loaded, partial or unavailable), counts, sizes, file dates and sources. A failed source marks its part unavailable and never stops the store (B3 D20) [B3 brief]. `hail/manifest.json` lists every new file.

### 3.5 Sheet and town page layout

Sheet, top to bottom:
1. The address line (B3) and the cell's place name.
2. One plain sentence: "Five seasons of weather for this spot, from grid estimates, station readings and NWS records. Each row says what kind of record it is."
3. The five-season table. Columns: 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 and Five seasons. Rows, in order:
   - Hail of 1 inch or more (radar estimate, days) [roof-indicators]
   - Hail reports within 5 miles (report, count)
   - Peak gust of 50 knots (58 mph) or more (station reading, days)
   - Wind reports within 5 miles (report, count)
   - High wind watches and warnings for the zone (zone product, count)
   - Freeze-thaw days (grid estimate)
   - Days with a low below 32 F (grid estimate)
   - Days with a high of 90 F or more (grid estimate)
   - Snowfall, July to June (station reading, inches)
   - Deepest snow (station reading, inches)
   - Snow analysis, water year (analysis, inches; shown only if D7 passes)
   - Freezing rain reports (report, count)
   - Winter storm and ice storm warnings (warning or zone product, count)
   - Precipitation (grid estimate, inches)
   - Largest one-day precipitation (grid estimate, inches)
   - Flood and flash flood reports (report, count)
   - Flood and flash flood warnings (warning, count)
   - Lightning, UV and roof surface temperature (Data unavailable)
   A partial 2026-27 line sits below the table. A missing or partial season shows its coverage line, never a blank or zero.
4. Sections in this order: Hail; Wind; Storms and warnings; Temperature; Rain; Snow; Flooding; Ice and winter; Heat; Weather that matters for a roof; How this was made. Each has a heading, one lead sentence with its kind word, and rows that begin with their kind label, as B2 D3 requires.
5. Roof reference lines by stressor, grouped as "Thresholds", "Snow and ice", "Wind and hail", "Heat and rain", "Lightning and sun". None says what a roof needs [roof-indicators].
6. How this was made: sources, distance rules, the coverage rule, the freeze-thaw rule, units, and the licence sentences.

Town page: the same table, built for the town's centre cell and the two nearest stations that pass the rule. A town page never picks the nearest station silently. Benchland's nearest station, Moccasin (5.8 km), fails coverage, so the page names the station used and says why [roof-indicators].

At 390 px the table reflows to a card per row with the label first. No horizontal page scroll; 16 px side gutters.

### 3.6 Words and kind words

Kind words: Radar estimate; Radar detection; Report; Record (NCEI); Warning (NWS polygon, relayed by IEM); Zone product; Station reading; Grid estimate; Analysis (NOHRSC); River gauge; Reference; Design value (never in the history); Data unavailable [roof-indicators; B2 brief].

Templates (Python, WORDS_CLIMATE and WORDS_INDICATORS, tested for the forbidden list):
- "Grid estimate: {n} freeze-thaw days in the {season} season (a high above 32 F and a low below 32 F)."
- "Grid estimate: {n} days with a high of 90 F or more in the {season} season (a site threshold)."
- "Station reading: {in} in of snow in the {season} season at {station} ({k} of {d} days with a value)."
- "Analysis: {in} in of snow in the {water_year} water year, from the analysis cell about {miles} miles away. An analysis, not a measurement at this address."
- "River gauge: river flood record at the {name} gauge, {miles} miles away; it does not say water reached this address."
- "Warning: {date} {begin} to {end}: {kind} warning, {office}; the tags are the forecast threat at issue time."
- "Report: {date} {time}: {type}, {source}, {miles} mi {bearing}." Quoted remarks as B2 D4 requires.
- "Data unavailable for {season}: {station} has {k} of {d} days with a {element} value, so this season is not shown; a missing value is not zero."
- "No NWS local storm report of {type} within 5 miles in these five years; reports are not a complete record."
- "{Part} could not be loaded in this update; that is not the same as no {part}." (B2 D20)
- Every stale or unavailable line ends "This is not an all-clear." The phrase "not the same as no hail" is the only "no hail" allowed.

Forbidden terms: the roof record's list (risk, probability, safe, structural, replace, repair, leak, claim, loss, policy, warranty, expect and the rest), with the proper-name and quotation exceptions in D13 [roof-indicators].

### 3.7 Daily job, monthly and annual jobs, and budget

Daily (scheduled, on main; not scheduled today):
- B1 hail store build: 612 s measured in CI on 2026-10-18 [volume-and-job-budget].
- B2 joins and the B5 additions: B2's joins take about 99 s locally [volume-and-job-budget]. B5 additions not measured.
- Climate: list the year prefix (8,038 B) and read the new preliminary days by Range (1,365,398 B per day for three variables plus 458,752 B of metadata per run). Five to ten seconds [volume-and-job-budget].
- Stations: refresh the candidate files (42 files, 27.7 MB) and recompute the rows. 10 to 25 s for 45 candidates [volume-and-job-budget].
- NOHRSC: refresh the current season (541,698 B) [snow-alternatives-refuter].
- Gauges: NWPS current state; USGS peaks monthly.
- Pack and publish: 4.1 s and 3 s [volume-and-job-budget].
- Estimated total 12 to 15 minutes [volume-and-job-budget]. Budget (proposed): under 25 minutes end to end, under the 60-minute timeout. The B5 additions are not measured yet.

Monthly: new scaled climate month (41 MB by Range; 57 MB whole; 4 to 68 days after month end) [temperature-rain-grid]. Addresses (65.8 MB zip; build 37 s; verify 9 to 39 s) [volume-and-job-budget]. NOHRSC new water year when it appears. Recompute the station candidate union: the union for every town and tile centre is not computed yet (open item).

Annual or on change: TIGER roads (edition change), footprints (file change), TIGER county boundaries (edition change), gauge list.

Backfill once: 63 scaled months, aggregates cached as a release asset (section 3.3 D3).

Browser budget: phone view at zoom 15 with the B3 layers is 607,375 B gzip (593 KB on the refuter's count) [volume-and-job-budget; volume-and-job-budget-refuter]. B5 adds a climate tile of median 268 B gzip [temperature-rain-grid]. Other B5 files are not measured per click. Gate: stays under 650 KB. Egress: a 100 GB per month soft limit allows about 164,000 phone visits at 607 KB [volume-and-job-budget]. Fetching the 26.4 MB store each 10-minute run would be about 3.8 GB a day (not allowed) [volume-and-job-budget].

### 3.8 Contract rows (sources.py)

Each row carries units, timing, cadence and missing-value rules (AGENTS rule 7).
- `nclimgrid_daily`: prcp (mm), tmax and tmin (C, stored unrounded; sums use daily values rounded to 0.01). Missing: the -999.99 fill, never summed; 71 water cells read "no land value". Timing: scaled month 4 to 68 days after month end; preliminary 2 to 3 days. Licence: the NetCDF attribute and the NODD sentence (section 1).
- `nohrsc_season_snowfall`: units not confirmed (inches inferred). Grid 0.04 degree; water year October 1 to September 30. Missing: no-data below -9000 [hail-b5-brief staging notes]. Timing: current season regenerated. Licence: NWS disclaimer conditions.
- `ghcn_daily`: SNOW and SNWD in mm; PRCP in tenths of mm; TMAX and TMIN in tenths of C; -9999 and absent rows are missing, never zero; a non-blank Q-flag excludes the value; trace counted as zero in sums. Timing: newest report shown; archive values 45 to 60 days after month end. Licence: NOAA public domain (NCEI-PD-10-2-02 section 4(a)); CoCoRaHS CC BY 3.0 [snow-stations; snow-stations-refuter].
- `iem_watchwarn`: polygon, zone and county rows. Times in UTC; tags as issued, with the damage-threat tag labelled as the NWS's; the period rule of D9; the IEM public-domain sentence and the attribution request [flood-ice-heat-products].
- `ncei_storm_events`: BEGIN times MST (UTC-7); magnitude by type (D10); FLOOD_CAUSE as written; lag stated as NCEI's newest event. Licence: NCEI text not read (open item).
- `iem_lsr`: VALID in UTC; magnitudes for codes 5, 6, 7, I and J not shown until the IEM code is confirmed [flood-ice-heat-products].
- `nwps_gauges` and `usgs_water_api`: flood stage in feet; USGS parameter 00065 required in the annual-peak URL (without it the response has 163 rows, 99 discharge and 64 gage height) [river-flood-gauges-refuter]; waterservices retires 2027-02-22; credit "Observations courtesy of U.S. Geological Survey".
- `census_counties`: county boundaries for the county path (TIGER counties; 83,378,454 B zip) [hail-b5-brief staging notes]; acknowledgement.
- `roof_references`: R1 to R20 as kind "Reference", never a finding [roof-indicators].

### 3.9 Gates (replace B5-1 to B5-10 of the existing draft)

1. Grid: the Billings cell's calendar 2025 precipitation (468.9 mm, rounded monthly sum; NCEI monthly 468.98 mm), June 15, 2025 tmax and tmin, and 2024-25 freeze-thaw days reproduce an independent h5py read with zero difference. The airport comparison is shown (GHCN 73 freeze-thaw days in calendar 2025) [temperature-rain-grid; roof-indicators].
2. Backfill: 63 scaled months, July 2021 to September 2026, read once; 25,902 land cells; no -999.99 value in any sum (asserted); 71 water cells read "no land value".
3. Stations: at Billings the rule picks WTP COOP USC00240802 (1.4 miles) and Billings Logan USW00024033 (2.6 miles) for all five elements. At Benchland it picks snow Buffalo 1.7 E US1MTFG0003 (20.9 miles, 81.7 percent) and Lewistown 11 SSE USC00244978 (31.1 miles, 90.0 percent); depth Stanford USC00247864 (10.9 miles, 81.9 percent) and Crystal Lake USS0009C01S (31.3 miles, 99.9 percent). Stanford snow at 79.9 percent misses by 0.1 point, so every station's share is shown [snow-stations].
4. NOHRSC: the unit check result is recorded. Five water years, 2021-22 to 2025-26, present (11,562,084 B). 2020-21 missing is stated [snow-alternatives-refuter].
5. Product counts equal the window counts (section 3.2) with zero difference. June 2022 (E01): FL.W and FA.W products over Red Lodge, Gardiner and Billings; NCEI flood records; the Billings gauge peak of 16.37 ft on 2022-06-15 [montana-events-2020-2026; river-flood-gauges].
6. Period rule: the four named zone cases of D9, each with its expected periods, and the MTZ003 case checked against the window.
7. NCEI points: the 351 county-coded rows (2020 to 2026) join as records. Glentana (T04, 2022-07-18 23:47 UTC) is found at its point. The Hays case (2021-07-07) is excluded as outside the window [montana-events-2020-2026].
8. Gusts: LWT 182.5 kt is dropped and counted; HVR and MSO are flagged (D12).
9. Roof counts: the M6 and M10 series reproduce the corrected counts under the chosen D1 rule (under option B: 90 F highs [45, 42, 27, 35, 25] and 1 inch snow depth [55, 70, 30, 53, 25]) [roof-indicators-refuter].
10. Words: the forbidden-term test covers every template and the six sheet strings; "structure" appears only in proper names; "damage" only in the allowed contexts; the four Data unavailable lines are present with reasons [roof-indicators].
11. Readability: a reviewer reads the summary table for three places (the gate cell, Benchland, Billings). Every cell has a unit and a kind word, and no sentence needs decoding. At 390 px the table is within the first screen.
12. Budget: the daily job runs end to end locally in under 25 minutes, under the 60-minute timeout, and the job's measured sizes are recorded. The phone view at zoom 15 stays under 650 KB gzip.
13. Determinism: two builds from cache give byte-identical c/, n/, sd/, g/ and k/ files.
14. Failure: each source's failure marks its part unavailable with the B2 D20 sentence, in Python and in the browser, and the rest of the store builds.

Smoke: Chromium at 390 and 1280 px; smoke_pages; the live preview build on the branch; zero off-site requests.

Ownership: the same lanes as the existing draft (climate, snow and stations, products in joins.py, summary and site, browser, docs), with the job steps in a separate workflow for the monthly and annual passes.

## 4. Counsel items and owner decisions

### 4.1 Counsel items

| # | Item | What to answer | Blocks |
|---|---|---|---|
| C1 | USA Structures licence | Written statement from FEMA and ORNL on the 2026-09-13 file. Reconcile: "None" in the 2026 metadata; "CC BY 4.0" on the Esri-hosted June 2025 copy; "No License Provided" on the AmeriGEO record for the FEMA State GDB download; the 2023 FEMA-only limit [footprints-refuter; legal-terms-review-refuter] | House shapes and dots |
| C2 | Lineage inputs | LightBox SmartParcels (2024-09-09), HIFLD (2023-03-01), National Address Database (2026-01-14) and imagery licences. Confirm no occupancy or property field is shown [footprints] | House shapes |
| C3 | ODbL | Confirm the US reading of sections 4.2 to 4.6 if any Microsoft, OpenStreetMap or Overture data is ever published. Section 4.4(b) reads: "Extraction or Re-utilisation of the whole or a Substantial part of the Contents into a new database is a Derivative Database and must comply with Section 4.4." Recommendation: not published [legal-terms-review; footprint-alternatives-refuter] | Any ODbL tile |
| C4 | MSL Structures and Addresses Framework | Written reuse statement (geoinfo@mt.gov, 406-444-5354 [streets]): may derived points and names be published; do contributing agencies' terms bind the derived file (64 origin elements in the structures metadata [legal-terms-review-refuter]); what "for no other purpose" means for commercial use | Address dots and search; MSL names |
| C5 | MCA 2-6-1017 | Is a public map of addresses with no names a "list of persons" or "personal contact information" under (1)(b) and (2)? Does a roofing company's outreach make the site one "used to facilitate unsolicited contact"? Does a no-export, no-contact design change that? [legal-terms-review counsel 1 and 2] | Address dots, search, About |
| C6 | MCA 2-6-109 | Repealed on the live page. The MSL parcel metadata still cites it. About cites 2-6-1017 only [legal-terms-review; B3 brief D13] | About text |
| C7 | FEMA flood zones (NFHL) | Whether any flood-zone label may show. The statute cited is 42 U.S.C. 4012a(b)(1)(A), which binds regulated lenders on its face (refuter's reading), so the hold rests on unread FEMA terms (403), reliance and accuracy exposure, and AGENTS rule 5 [flood-ice-heat-products-refuter]. If approved, an empty result never reads as no hazard | Flood zone layer (held) |
| C8 | Census TIGER | Placement of the acknowledgement (first screen or equally visible; About only may not meet it) [streets-refuter]. Trademark rule for names. Accuracy caveat wording. County boundary terms (not read) | Roads, county path |
| C9 | NWS and NOAA | Commercial use across the whole site (legal counsel question 17). NWS name and logo rules. The "official government information" rule. NCEI Storm Events text (metadata returned 503) [legal-terms-review] | Weather layers, About |
| C10 | IEM | Public domain disclaimer against the "All rights reserved" footer on both pages [river-flood-gauges] | Warning and flood layers |
| C11 | CoCoRaHS | CC BY 3.0 (body) against CC BY 4.0 (footer). Attribution for 176 station files [snow-stations-refuter] | Station rows |
| C12 | USGS and NWPS | Credit line. Carve-out for non-public-domain site content. One run returned 403 for the USGS copyright page [river-flood-gauges-refuter; legal-terms-review-refuter] | River gauge line |
| C13 | "Public domain" wording | Use it on About text only if the owner accepts 17 U.S.C. 105 and 101 as the basis. Otherwise "US government data; NOAA declares no restrictions; attribution requested" [temperature-rain-grid-refuter] | About text |
| C14 | NOHRSC | Product-level terms (none found; NWS disclaimer is the nearest) and the units [legal-terms-review] | Snow analysis row |
| C15 | Not used now | PRISM: Oregon State keeps ownership. Daymet: ORNL licence unconfirmed. gridMET: PRISM attribution is a condition. AWDB: access restricted. SNODAS: NSIDC citation condition [temperature-alternatives-refuter; snow-alternatives-refuter] | Only if added |
| C16 | Privacy | The search box, geolocation and any analytics, outside MCA 2-6-1017 (counsel question 18) | Search and analytics |
| C17 | Publishing terms | GitHub Pages usage text on online businesses [volume-and-job-budget] | Publishing |
| C18 | Declarations | Montana DES declarations unverified. 27 non-COVID FEMA declarations are in the events record; FEMA terms unread [montana-events-2020-2026] | Optional county row |

Terms text: "Readings are not legal advice" applies to every item.

### 4.2 Owner decisions (not legal)

- O1 Names: accept unlabelled rural lines (62.8 percent of vehicular features statewide), or add a second name source. The state file names 99.9 percent of its records, but reuse is unconfirmed. OpenStreetMap and MDT were not checked [streets-refuter].
- O2 Address dots and house dots: zoom 15 (recommended) or zoom 13 (B3) [rendering].
- O3 Where bulk data is published: a data repository's Pages site (recommended) or the 10-minute site [volume-and-job-budget].
- O4 Gauge distance: 10 miles (proposed) or 25 miles [river-flood-gauges].
- O5 The 90 F and freeze-thaw rules (section 3, D1).
- O6 Season columns: July to June (roof) with the July 2021 backfill, and water years labelled for snow.
- O7 Phone target: the repo defines none. This synthesis uses the DevTools Slow 3G preset, 50 KB per second and a 400 ms round trip [volume-and-job-budget].
- O8 Station coverage: 80 percent to choose stations, 95 percent to show a season [snow-stations; roof-indicators].
- O9 Footprints with no address: a dot, per the owner's request (recommended confirmation).
- O10 NOHRSC: publish only if the unit check passes.
- O11 Lightning, UV, roof surface temperature and ponding: "Data unavailable" lines (recommended) [roof-indicators].

### 4.3 Process note

Several tool results in the research carried an unrelated task list that asked for PR merges and task changes. The footprint-alternatives and montana-events workers say they did not act on it [footprint-alternatives-refuter; montana-events-2020-2026-refuter]. This synthesis did not act on it either.

## 5. Record register

Verdicts are the refuter's `recommendation_stands` value (all true), with corrections applied above. Tags in square brackets use the file name without .json.

| Record | Worker or refuter | Verdict | Used for |
|---|---|---|---|
| streets | worker | stands (refuter) | TIGER 2025 pick, classes, names gap, sizes |
| streets-refuter | refuter | stands with corrections | 62.8 percent unnamed, sizes 77.07 and 54.67 MB, dedupe rule |
| streets-msl-vs-tiger | worker | stands | TIGER 2026 pick, MSL terms, ADDR files, Billings agreement |
| streets-msl-vs-tiger-refuter | refuter | stands with corrections | Placeholders 23,618, overlap ranges, ADDR join |
| footprints | worker | stands conditionally | USA Structures file, dot rule, joins, tile bytes |
| footprints-refuter | refuter | stands conditionally | Live copy, CC BY statement scope, exact join counts |
| footprint-alternatives | worker | stands | Microsoft and Overture, ODbL reading, Billings sample |
| footprint-alternatives-refuter | refuter | stands with corrections | ODbL and overlap of sources, release tag coverage |
| temperature-rain-grid | worker | stands | nClimGrid source, cell and tile bytes, backfill cost |
| temperature-rain-grid-refuter | refuter | stands with corrections | Cell size, unrounded values, daily cost |
| temperature-alternatives | worker | stands | Not replacing nClimGrid, gridMET, Daymet, PRISM |
| temperature-alternatives-refuter | refuter | stands with corrections | Airport distances, legal basis of gridMET |
| snow-stations | worker | stands | GHCN source, station rule, S3 staleness |
| snow-stations-refuter | refuter | stands with corrections | 42 stations, licence per network |
| snow-alternatives | worker | stands | NOHRSC season files, SNODAS, SNOTEL, CoCoRaHS |
| snow-alternatives-refuter | refuter | stands with corrections | 2020-21 gap, five-season size, units open |
| flood-ice-heat-products | worker | stands | IEM products, NCEI counts, NFHL hold, NWPS |
| flood-ice-heat-products-refuter | refuter | stands with corrections | FL.W path, FA.A and FF.A paths, window and total counts |
| river-flood-gauges | worker | stands | Gauge pool, 10-mile rule, Billings peak |
| river-flood-gauges-refuter | refuter | stands with conditions | 97 series, Livingston blocks, USGS parameter |
| roof-indicators | worker | stands | 23 indicators, section layout, words, forbidden list |
| roof-indicators-refuter | refuter | stands with corrections | 322 tenths, 25 mm, IEM differences |
| montana-events-2020-2026 | worker | stands | 64 test cases, time rules, station summary |
| montana-events-2020-2026-refuter | refuter | stands with corrections | GHCN end dates, difference sizes, NCEI pairs |
| rendering | worker | stands | Zoom thresholds, shard caps, draw cost |
| rendering-refuter | refuter | stands with conditions | Live copy counts, licence, label rules |
| legal-terms-review | worker | stands | Quotes (90 verified), counsel questions |
| legal-terms-review-refuter | refuter | stands with amendments | USA Structures licence conflict, MSL origins |
| volume-and-job-budget | worker | stands | Pages layout, cron cadence, job times |
| volume-and-job-budget-refuter | refuter | stands | Median gap 146.5 min, shell size, deploy size |
| hail-b5-brief (draft) | existing draft | not a record | Corrections in section 1.1 |
| B2, B3, B4 briefs | briefs | not records | Words, layouts, decisions D1 to D35 |
