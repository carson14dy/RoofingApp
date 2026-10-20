# Hail history B3 brief: a dot for every Montana address, the typed-address search, and the terms text

Owner decisions (D34): 2 "A public lookup by typed address or clicked location. Each address in montana should have a dot
to click on the map with a popup on each history of weather."; 6 "Don't include owners names. But I do want all addresses
included"; 7 "Follow the laws". Research: /home/user/wt/wt-hail/research/hail-history/README.md section 3 (every house) and
8.3 (terms), validation-evidence/montana-addresses.json (the MSL Structures and Addresses Framework: 674,715 points,
493,975 residence-coded, DBF lat/lon zero so the shapefile geometry is the only position, NGUID not unique, no owner
field; the use constraint "for no other purpose"; MCA 2-6-1017 and 2-6-109 quoted in the parcel metadata) and
geocoding-and-lookup.json. B3 builds on B2 (branch claude/hail-b2).

## Product
A second default-off flag `--hail-addresses` (branch previews pass it with --hail-history; main does not; it is separate
so the hail history can go live before the address terms are confirmed). With it:
1. **Dots.** From zoom 13 on the Map page (white map or Imagery), every address in the viewport is a small dot (a canvas
   circle marker; no new library). A click or tap on a dot opens the hail sheet for the dot's cell with the address line on
   top: "{number} {street}, {city} {zip}". The dot's record is `[lon, lat, "number street", "city", "zip"]` and nothing
   else: no owner, no parcel id, no NGUID, no place type (decision 6; the research's "no owner field" check is re-run at
   build: the builder lists the DBF fields it reads and asserts none is an owner or parcel field).
2. **Shards.** `hail/a/<name>.json` from the 0.1-degree hail tiles, split into quarters (0.05 degree, then 0.025) while a
   shard would hold more than 2,500 addresses: `{"f":"hail-addresses-v1","b":[west,south,east,north],"n":count,
   "a":[[lon,lat,"street","city","zip"],...]}` with coordinates rounded to 5 decimals. `hail/index.json` gains
   `"addresses":{"count":674715,"shards":n,"split":{"<tile>":[sub-shard names]}, "source":{...the MSL file, its date, its
   stated use constraint quoted...},"state":"loaded"|"unavailable"}`; map.json["hail"]["addresses"] carries the split map
   and the shard URL pattern so the browser can name the shards for the viewport. Measure: the largest shard (target under
   300 KB on disk), the total (target under 60 MB on disk), the shard count.
3. **Search.** A "Find an address" box on the Map page (Python-rendered form; the browser code: read the typed text, pick
   the city and street files, filter, list up to 20 matches, zoom to the chosen one and open its sheet). Index files:
   `hail/a/idx/cities.json` (the city names with counts) and `hail/a/idx/<city-slug>/<letter>.json` (addresses of that
   city whose street name starts with that letter: `[[number, "street", lon, lat, "zip"],...]`), so one search costs at
   most two small fetches. Typing "1 N 27th St Billings" finds that address; a street name alone lists its addresses; a
   rural address (a highway or county road) is found by its street name. Measure the largest letter file. The typed text
   never leaves the browser (the privacy sentence says so).
4. **Terms (decision 7).** The About page states: the source (Montana State Library Structures and Addresses Framework),
   that it is public and non-sensitive in the library's own words, the use constraint quoted ("for no other purpose" with
   its purpose sentence as the metadata gives it), that owner names and parcel identifiers are never read, stored or shown,
   that MCA 2-6-1017 and 2-6-109 concern lists of persons and the site publishes no such list (the owner's and counsel's
   reading to confirm), and the privacy sentence for the search. The flag stays off on main until Carson says the terms
   text is right and counsel confirms (D34).
5. **Job.** `.github/workflows/hail-store.yml` gains an addresses step: download the framework shapefile zip (the current
   download URL from the MSL MSDI page; cache by file name and size; re-check monthly), read it with pyshp (geometry for
   the position; DBF for number, street, city, zip only), build the shards and the index files into the same store, verify
   (count equals the shapefile's record count minus rows with no geometry or no street; the no-owner assertion; manifest
   hashes), tar as before.
6. **Words.** Python: the address line template, the search box words ("Find an address", "Type a street address and a
   town", "No match in Montana's address list; try the street name alone", the privacy sentence "What you type stays in
   your browser."), the dot legend line ("Dots are addresses from Montana's public address list; tap one for its history"),
   the About paragraph. No word says who lives there or what the building is.

## Gates (B3-1 to B3-8)
1. The shards hold every address with a position and a street (count stated against the shapefile's record count); no
   owner, parcel or place-type field is read (test on the DBF field list); the largest shard under 300 KB; totals measured.
2. Dots appear only at zoom 13 and above, only for the viewport's shards, and never off-site; the request log per pan is
   small (measure the fetches when panning across Billings at zoom 15).
3. A dot click opens the sheet with the address line on top and the cell's hail days (and B2's sections) below.
4. Search: "1 N 27th St Billings" opens that address; a street name alone lists its addresses; a rural address is found;
   a nonsense string gives the no-match sentence; nothing is sent off-site.
5. The About text carries the terms, the quoted constraint, the no-owner sentence and the privacy sentence; the words
   pass the forbidden-term check.
6. Flag-off (both flags) build unchanged except shared static assets; --hail-history alone unchanged by B3.
7. Chromium smoke at 390 and 1280 px on Imagery and the white map over Billings at zoom 15 (screenshots); smoke_pages.
8. Deterministic build from cache; the job's steps run locally end to end; sizes measured.

## Ownership (worktree /home/user/wt/wt-b3, branch claude/hail-b3 from claude/hail-b2's head)
- Builder 1 (addresses): `website/addresses.py` (new: download with cache, pyshp reader with a lazy import, the field
  allow-list, the quadtree shards, the search index, index and manifest updates, verify, WORDS_ADDRESSES, map_data_addresses),
  `tests/test_addresses.py`, `.github/workflows/hail-store.yml`, the fixture (a few hundred real Billings addresses for the
  fixture tiles, under 50 KB in all).
- Builder 2 (site): `website/build.py` (the flag, copy a/, map.json block), `website/sources.py` (contract row
  msl_addresses), templates (map.html: the search form and the dot legend line, gated; about.html paragraph),
  `website/static/map/map.js` (the dots layer, shard naming from the split map, the click, the search; documented), map.css,
  `tools/smoke_map.py`, `tests/test_site.py`, `.github/workflows/website.yml` (the flag on previews).
- Builder 3 (docs): D36, DESIGN section 9, ROADMAP, README, AGENTS, b3-verification.json skeleton.
Same rules as B2: nobody commits or pushes; scratch under /home/user/hail-b3/out/<name>/; tests delete only what they made.

## Pre-check of the source file (supervisor, 2026-10-19 01:50 UTC; scripts and summaries in /home/user/hail-b3/precheck/)
Facts the builders may cite (re-run `stream_points.py` and `quadtree_measure.py` with the venv python to reproduce):
- File: https://ftpgeoinfo.msl.mt.gov/Data/Spatial/MSDI/AddressStructures/StructuresFramework_shp.zip, 65,788,772 B (HTTP 200),
  cached at /home/user/hail-b3/cache/structures/. Members: SiteStructureAddressPoint .shp 18,892,120 B, .dbf 1,905,396,826 B
  (inflated; 51 fields, record length 2,824), .prj, .shx, .sbn, .sbx, SSAP_Metadata.dbf (80 load records),
  StructuresFramework_metadata.xml (pubdate 20260930, progress "In work", update "Continually"), _ReadMe.txt ("exported
  monthly, around the end of the month (the exact date varies)"; export date 20260930).
- Points: 674,715, shape type 1, 0 null shapes. Projection per .prj: NAD_1983_2011_StatePlane_Montana_FIPS_2500 (Lambert
  conformal conic, metres) = EPSG:6514. pyproj 3.8.0 (PROJ 9.8.1) EPSG:6514 -> EPSG:4326 (always_xy) agrees with the
  library's live map service (msdi_structures_addresses_map_v1, outSR=4326) within 1.25 m on 14 sampled points (every
  50,000th record). Longitude -116.049 to -104.032, latitude 44.471 to 49.000 (inside the B1 grid).
- DBF fields (51): DiscrpAgID, DateUpdate, Effective, Expire, NGUID, Country, State, County, Inc_Muni, Uninc_Comm, Nbrhd_Comm,
  AddNum_Pre, Add_Number, AddNum_Suf, St_PreMod, St_PreDir, St_PreTyp, St_PreSep, St_Name, St_PosTyp, St_PosDir, St_PosMod,
  LSt_PreDir, LSt_Name, LSt_Typ, LSt_PosDir, Post_Comm, Post_Code, PostCodeEx, Building, Floor, Unit, Room, Seat, Addtl_Loc,
  LandmkName, Milepost, Place_Type, Placement, Longitude, Latitude, Elevation, MT_PlcType, ParcelID, LocalID, Addtl_Desc,
  GNIS_ID, DatasetTyp, ProcessID, ProcessDte, GlobalID. No owner field exists; ParcelID does (never read).
- Fill: St_Name blank 4,212 (all with Add_Number 0; left out); Add_Number blank or 0 on 4,948; Post_Comm blank 3,886
  (Inc_Muni then reads Unincorporated 3,355, Chinook 346, Roundup 118 ...; County reads Glacier County 2,413, Blaine 378,
  Liberty 259, Pondera 222 ...); Post_Code blank 3,603 and one 6-character value; Unit 87,431 (10,128 distinct values such
  as "UNIT A", "Unit 2", "APT 1", "A", "UNIT 201"); Building 4,820 ("Lot 2" ...), Floor 1,184, Room 612; AddNum_Pre 82,
  AddNum_Suf 7,681 ("1/2" 2,589, "A", "B" ...); St_PreMod 1,007 ("Old"); St_PosMod 1,224. State labels MT 674,712, ID 2, ND 1.
- Street words are spelled out: St_PreDir and St_PosDir are North, South, East, West, Northeast, Northwest, Southeast,
  Southwest; St_PreTyp (20 values) United States Highway 11,312, Highway 7,681, Montana Highway 6,443, Avenue, Road, County
  Road, State Highway, Bureau of Indian Affairs Route, Interstate ...; St_PosTyp (103 values) Street 138,202, Road 130,906,
  Avenue 127,365, Drive, Lane, Way, Court, Trail, Loop, Boulevard, Circle, Place, Highway, Square, Parkway, Run, Terrace ...
  129,133 street names start with a digit ("27th", "212"). No non-ASCII characters in any line. Billings has "401 North 27th
  Street" (59101), "310 North 27th Street", "701 South 27th Street"; there is no "1 North 27th Street".
- Measured on the distinct rows (quadtree below): 663,763 address rows = 674,715 points - 4,212 without a street - 6,740 exact
  duplicates (same position, line, unit, city and zip). Shards: 4,212; 43.5 MB of JSON in all; the largest 173.9 KB (2,490
  rows); depths 1: 3,767, 2: 153, 3: 133, 4: 155, 5: 4; none over the limit at the cap. Search index: 457 cities (plus the
  fallbacks below); 7,021 letter files keyed by the first character of St_Name; the largest, Billings "S", 9,801 rows
  (about 470 KB), hence the two-character split in D5.
- Terms text in the metadata (quote exactly, with the file date): accconst "None. All data contained in the Framework are
  publicly available and non-sensitive."; useconst "DISCLAIMER: The Montana State Library Geographic Information Services
  provides this product/service for informational purposes only. The Library did not produce it for, nor is it suitable for
  legal, engineering, or surveying purposes. [...] The Library makes these data and services available as a convenience to
  the public, and for no other purpose. The Library reserves the right to change or revise published data and/or services
  at any time."; purpose "To provide a statewide, standardized repository for structure and address point data. The
  Structures/Addresses Framework complies with the NENA Standard for NG9-1-1 GIS Data Model and is designed to support a
  wide range of public and private sector uses including: 9-1-1 and emergency response, elections management, broadband
  internet mapping, census programs, planning, natural resource studies, etc."

## Decisions from the pre-check (D1 to D12; they refine the Product section above)
- D1 **Reader.** `website/addresses.py` reads the .shp and .dbf members straight from the zip as streams (point records are
  8 + 20 bytes; the DBF header is 32 bytes plus 32 per field and one 0x0D byte, then fixed-width records of the stated
  length; the deletion flag is byte 0). No pyshp. Fields are read through an allow-list: Add_Number, AddNum_Pre, AddNum_Suf,
  St_PreMod, St_PreDir, St_PreTyp, St_PreSep, St_Name, St_PosTyp, St_PosDir, St_PosMod, Post_Comm, Post_Code, Inc_Muni,
  County, Unit. A test asserts the allow-list holds none of ParcelID, LocalID, NGUID, GlobalID, Place_Type, MT_PlcType,
  LandmkName, Addtl_Desc, Addtl_Loc, GNIS_ID, Latitude, Longitude, DiscrpAgID, and the reader never slices any other field.
  The reader asserts the .prj names NAD_1983_2011_StatePlane_Montana_FIPS_2500 and the DBF field list equals the 51 names
  above (a changed file fails loudly, "unavailable", never a silent misread).
- D2 **Projection.** pyproj (job-only, lazy import; pinned in the job) EPSG:6514 -> EPSG:4326 with always_xy=True;
  coordinates rounded to 5 decimals. Verify in the job: three recorded live-service pairs reproduce within 2 m
  (1611 South Avenue West, Missoula: file -114.02078, 46.84868; 500 Colony Road, Roundup: -108.50031, 46.71750;
  1617 Euclid Avenue, Helena: -112.05997, 46.60374). The test skips when pyproj is missing; the job always has it.
- D3 **Address line.** `{AddNum_Pre}{Add_Number}{AddNum_Suf}` (omitted when the number is 0 or blank) + the street parts in
  NENA order (St_PreMod St_PreDir St_PreTyp St_PreSep St_Name St_PosTyp St_PosDir St_PosMod, blanks skipped, single spaces)
  + the unit when present. The unit is written as given but title-cased ("Unit A", "Apt 1"); a bare value gets "Unit " in
  front ("A" -> "Unit A"). Building, Floor and Room are not read. Rows without St_Name are left out; exact duplicate rows
  are merged; both counts are stated in index.json ("left_out_no_street": 4212, "merged_duplicates": 6740 for this file).
- D4 **City and zip.** City = Post_Comm; when blank, Inc_Muni unless it reads "Unincorporated"; else the County value as
  given ("Glacier County"). Zip = Post_Code when it is exactly 5 digits, else blank (the line then omits it). Out-of-state
  labels (ID, ND) are kept; the position decides where a dot sits.
- D5 **Shards and index.** Quadtree on the B1 tile grid: split into quarters while a shard holds more than 2,500 rows, depth
  cap 6 (0.0015625 degree); a shard at the cap may exceed the limit (none does today). Names: the tile name plus one digit
  per level, 0 NW, 1 NE, 2 SW, 3 SE (`r0092_c0213123`). The search index: `hail/a/idx/cities.json` = {"f":"hail-address-
  cities-v1","cities":{"<city>":{"n":count,"keys":{"<key>":rows,...}}}} where a key is the first character of St_Name,
  upper-cased (digits stay digits), or two characters when the one-character file would hold more than 2,500 rows (the
  one-character file is then not written); letter files `hail/a/idx/<city-slug>/<key>.json` = {"f":"hail-address-idx-v1",
  "a":[[number_text, "full street", "unit", lon, lat, "zip"], ...]} sorted by street then number. Slug: lower-case, spaces
  and punctuation to "-", ASCII only. One search costs cities.json (cached per page) plus one letter file.
- D6 **Search normalisation.** Python writes `hail/a/idx/words.json`: the directional and type abbreviations mapped to the
  file's spelled-out words (N/S/E/W/NE/NW/SE/SW; St, Ave, Rd, Dr, Ln, Ct, Trl, Blvd, Cir, Pl, Hwy, Pkwy, Ter, Sq, Lp, Way;
  US -> United States, MT -> Montana, Apt and Unit kept; "#" -> Unit). The browser lower-cases, strips punctuation, expands
  the abbreviations, takes a leading number, finds the city as the longest trailing match against cities.json (else the
  map's current town or no city), and the core name as the first remaining token that is not a directional or a type
  word; it fetches that city's key file (one or two characters per cities.json) and lists rows whose normalised street
  contains every typed non-number token, exact number first, then nearest numbers, up to 20. Gate B3-4 uses
  "401 N 27th St Billings" (exists) and "Colony Rd Roundup" (a rural road) and "qwzx 99" (no match).
- D7 **Dots.** A canvas layer drawn from the shards whose bounds intersect the viewport, from zoom 13; shards named from
  map.json's split map (the tile list with the depth names). Dot radius 2.5 px at zoom 13 to 4 px at 16+; the
  hazard-free dot colour comes from a token. A tap picks the nearest dot within 12 px; the sheet shows the address line
  (and city, zip) on top, then B1's cell history and B2's sections for that cell. Co-located dots (up to 141 at one
  point: unit buildings) open a list of their lines above the shared history.
- D8 **Terms (About).** Quote the accconst sentence, the "convenience to the public, and for no other purpose" sentence
  with the purpose statement, the "informational purposes only ... not suitable for legal, engineering, or surveying
  purposes" sentence, and the file date; state that owner names and parcel identifiers are never read, stored or shown
  (the allow-list), that no list of persons is published (MCA 2-6-1017 and 2-6-109, owner's and counsel's reading to
  confirm), and the privacy sentence. No positive claim that commercial use is permitted: "The library's terms do not
  address commercial use; the owner's counsel is to confirm before this layer goes live" stays in ROADMAP, not on the site.
- D9 **Job.** The addresses step runs after the joins step: download (cache by name, size and the zip's export date from
  _ReadMe.txt), build, verify (counts against the record count, the allow-list, the projection pairs, manifest hashes),
  into the same store and tar. pyproj is pinned in the job's pip line. Budget: the stream takes about 30 s locally.
- D10 **Fixture.** Real rows from the fixture tiles' area plus 300 rows around 401 North 27th Street, Billings (its tile
  joins the fixture), under 50 KB in all, with the matching cities.json, words.json and letter files; the sample build
  with both flags shows dots over Billings and over Benchland at zoom 13.
- D11 **Measures to publish** (in index.json "addresses" and b3-verification.json): points, left out, merged, rows,
  shards, largest shard bytes, total bytes, depth histogram, cities, letter files, largest letter file bytes, pyproj
  version, the three projection pairs with their offsets, the file date and size.
- D12 **Scope.** No place type, no owner, no parcel id, no building use, nothing about who lives there, anywhere in data or
  words. The search text never leaves the browser (no request carries it: letter files are named by city and key only).

## Product north star (owner, 2026-10-19; applies to every stage)
Carson: the goal is "an all in one mapping and easy to read all weather app". For builders and reviewers this means:
one map that carries every layer in one layer menu with consistent words; one sheet per place that leads with a plain
summary a roofer can read in a glance (what happened here, how big, when), with details behind headings in a fixed
order (hail, wind, storms and warnings, temperature, rain, snow, flooding, roof indicators as stages add them); every
number next to its unit and its kind word; no section that is a data dump; the same words on the sheet, the town page
and the About page; nothing the viewer must decode. A reviewer finding that a section is hard to read at a glance is a
real finding. Quality over speed: a stage ships when its gates pass, not when the clock says so.

## Supervisor decisions from the research wave (2026-10-19 03:25 UTC; D13 to D17; they bind the site side, task 25)
- D13 **Montana law citation.** The About text cites MCA 2-6-1017 only. MCA 2-6-109 is repealed (live legislature page:
  "2-6-109. Repealed. Sec. 59, Ch. 348, L. 2015."); the state library's parcel metadata still quotes it, and D8's
  "MCA 2-6-1017 and 2-6-109" is corrected to 2-6-1017 alone. The counsel list carries the question whether a map of
  addresses with no names is a "list of persons" or "personal contact information" under 2-6-1017(1)(b) and (2), and
  whether a roofing company's use counts as facilitating unsolicited contact; the site stays flag-off on main until
  Carson and counsel answer (legal-terms-review.json, counsel questions 1 to 5).
- D14 **Building shapes.** Source: FEMA and ORNL "USA Structures", the Montana file MT_Structures_20260913.zip
  (173,088,786 B; 918,052 footprints; WGS 84; imagery to 2025-11; file geodatabase read with pyogrio, a job-only
  dependency behind a lazy import). Legal basis as read: Data.gov lists the licence as U.S. government works (public
  domain) with public access; the hosted copy is read as CC BY 4.0 by one worker and as unstated by another; the file's
  own metadata states no constraints. The site attributes "Oak Ridge National Laboratory and FEMA, USA Structures" with
  the file date, and the counsel list asks FEMA to confirm in writing. Microsoft and Overture footprints are not used
  (ODbL share-alike on derived tiles). Only the geometry is read: no OCC_CLS, PRIM_OCC, PROP_ADDR, SQFEET, HEIGHT, population
  or any other attribute (decision 6, D12; the occupancy fields also rest on commercial inputs named in the metadata).
  Rings at 5 decimals, no simplification (positions are limited by the imagery at 3.5 to 5 m; 5-decimal rounding moves a
  vertex at most 0.67 m). Shards: the same quadtree rule as the addresses (2,500 footprints per shard), `hail/b/` with
  {"f":"hail-buildings-v1","b":[...],"n":count,"a":[[[lon,lat],...ring],...]} (holes as further rings), drawn from zoom
  15 as a light fill with a hairline from the tokens.
- D15 **One dot per house.** Every footprint gets a dot at a point inside it (the centroid when inside, else the nearest
  interior point). Address points inside the footprint or within 15 m of it are listed on that dot's sheet (deduplicated
  lines); a footprint with none says "No address on file for this building" and opens the cell history all the same. An
  address point matched to no footprint keeps its own dot. Measured in Billings: 61.6 percent of points inside a
  footprint, 36.0 percent within 15 m, 2.4 percent farther; 42.7 percent of footprints hold no point inside and 9.1
  percent none within 15 m; rural Benchland: 26 of 28 footprints have no address inside. The join runs in the build
  (Python); the browser draws dots from the shard and never joins. Dots show from zoom 13 (addresses) and the footprint
  dots replace the address dots inside a footprint from zoom 15, so one house shows one dot.
- D16 **Streets.** Default source: Census TIGER/Line 2026 All Roads, the 56 Montana county files (88,859,641 B; ISO
  metadata: not copyrighted, free to use in a product or publication, acknowledgement of the U.S. Census Bureau required;
  TIGER/Line and Census TIGER are registered trademarks: the names never appear in the site's product names). Draw the
  vehicular classes S1100, S1200, S1400, S1500, S1630, S1640, S1730, S1740; merge concurrent features that share
  geometry (measured: 18.8 percent of the Billings tile's length and 74.9 percent of Benchland's) so each line is drawn
  once with its names joined by " / "; a blank FULLNAME (11 percent of Billings segments, 27 percent of Benchland's) is
  drawn without a label. Douglas-Peucker at 2 m (measured: 69 MB statewide at 5 decimals, Billings tile 148 KB); shards
  `hail/r/` by the same quadtree rule with a 2,000-segment limit, drawn from zoom 13, names from zoom 16 along the
  longest piece per name per tile. The state library's Transportation Framework (258,208 segments, names on 99.9
  percent, cached at /home/user/hail-b3/cache/roads/TransportationFramework_shp.zip) is read by a second reader behind
  `--roads-source msl` for the day the Library confirms reuse in writing (counsel question 4 and 5); until then it is not
  built into the store. About page: the Census acknowledgement and the accuracy caveat ("not suitable for high-precision
  measurement applications such as engineering problems, property transfers").
- D17 **Attribution lines** (About page, one per source, from the quoted terms): U.S. Census Bureau (TIGER/Line 2026,
  acknowledgement required); Oak Ridge National Laboratory and FEMA (USA Structures, file date); Montana State Library
  (Structures and Addresses Framework, file date, the quoted use sentence); the IEM line already in B2 stays ("in the
  public domain and may be used freely by anyone for any lawful purpose"; attribution appreciated).
- D16a **Placeholder road names.** TIGER FULLNAME values that are placeholders (for example "Internal") and, when the state
  file is used, its Driveway, Dwy, Unknown, Unnamed and No Name values (23,618 statewide, 9.15 percent) are treated as
  unnamed: drawn, never labelled, never searchable. Concurrent routes (US Highway 87, Montana Highway 3 and 200 share one
  line for 4.72 miles in the Billings tile) are one drawn line with the names joined by " / "; the refuter's figures
  (streets-msl-vs-tiger-refuter.json) replace the worker's where they differ.

## Supervisor decisions after the data-module review (2026-10-19 04:20 UTC; D18 to D24) and the completion list
- D18 **Fixture layout.** The shared fixture grows by hail/a/ exactly as B2 grew it by j/, z/ and s/: hail.py's fixture
  path (or joins.py's documented extension of it) calls addresses' fixture writer, index.json and manifest.json include
  the a/ entries, and the B1 and B2 fixture tests in tests/test_hail.py and tests/test_joins.py are updated to the new
  layout (as B2's D12 did). The addresses owner may edit those two test files for this item only. The whole fixture
  stays under 50 KB plus the a/ budget of 50 KB (D10).
- D19 **Unpinned job installs.** B1's rule stands: the daily job installs like the site build, with no "==" anywhere in the
  workflow text. pyproj is installed as `pyproj~=3.8` (a compatible release); the verify step's three projection pairs
  within 2 m catch drift. D9's "pinned" wording is corrected to this. The awk header test uses a regex, not "==".
- D20 **A failed address source never stops the store.** The address step is non-fatal in the job: a failed HEAD, download,
  field-list or projection assertion marks the addresses part "unavailable" with its reason (a SourceUnavailable state),
  leaves the rest of the store untouched, and the job still packs and publishes. download() sits inside the try that
  marks the part unavailable. One record with no city after D4's fallbacks is counted as left_out_no_city, not a list
  failure; the list fails only on the field list and the projection.
- D21 **Coverage words.** The About page says "The list is of addresses, not of dwellings, and its coverage varies from
  county to county." and nothing numeric; the county ratio range (residence-coded points over 2020 housing units, 0.48 to
  1.36) moves to docs/ROADMAP.md under the B3 open items with its meaning spelled out. REVIEW_NOTE is deleted.
- D22 **Counts.** The module's merge rule stands (same position at 5 decimals, line, unit, city after D4 and the spelling
  rule, validated zip): 6,744 merged, 663,759 rows on the 2026-09-30 file. The brief's pre-check figures (6,740 and
  663,763) came from a cruder key and are superseded; the pre-check line "all with Add_Number 0" reads "all but six".
  The city spelling rule is the most-used spelling per city (pass the list, not a set); a test covers it.
- D23 **Dots outside the hail grid.** An address tile with no B1 shard (today four tiles, five rows, at the state's edge:
  Polebridge, Belfry, Big Horn County, Decker) is listed by verify, and the site shows "This point is outside the hail
  grid's Montana outline; no hail history is kept here." for such a dot, never "no hail".
- D24 **Cache key and quotes.** The download cache is keyed by file name, size and the HTTP Last-Modified header (stricter
  than the export date; D9 corrected). Non-adjacent sentences quoted from the metadata are joined with " [...] " and the
  words test asserts the marker. The About source line never carries a date the index did not read: when the addresses
  block is missing it reads "Source: Montana State Library Structures and Addresses Framework (file date not available in
  this update)."
- **Completion list (every item below is applied whether or not a skeptic kept the reviewer's framing):** the fixture per
  D18 with the four B1 and B2 tests green; the "==" removal per D19; non-fatal source handling per D20 with a test of each
  failure path; the About citation to MCA 2-6-1017 only (D13) in both places; the coverage words per D21; the city
  spelling rule and its test (D22); the quadtree midline compare in integers (64ths of a 5-decimal degree) so a point on
  a midline files in one quarter deterministically; unit title-casing of letter runs with digits ("APT2" to "Apt2"); the
  verify limit check on two-character letter files; the job timeout 90 minutes; tests for download() (HEAD, cache hit,
  refetch on a changed Last-Modified, failure marking unavailable), the deleted-record flag, the ID and ND labels, the
  statute citation; .gitignore entries for the local cache folders; D23's verify listing and words; D24's source line.

## Supervisor decisions from the research synthesis (2026-10-19 06:30 UTC; D25 to D31; they amend D14 to D16a)
- D25 **Streets source, revised.** The Census road files leave 62.8 percent of Montana's vehicular features unnamed
  statewide (134,137 of 213,613; county range 18 to 95 percent; streets-refuter.json), which fails the owner's "every
  street, like a commercial map" for rural Montana. The default source is therefore the Montana State Library
  Transportation Framework (258,208 segments, names on 99.9 percent, 48.8 MB at 2 m, cached at /home/user/hail-b3/cache/
  roads/), read under the same use sentence and the same counsel gate as the address points (the layer is flag-off on
  main until the Library's written answer and counsel's reading; one question covers both files). The Census reader
  stays as the fallback behind `--roads-source tiger` (the 56 county files cached under /home/user/hail-b3/cache/tiger/),
  with the Census acknowledgement when it is built. D16's placeholder rule (D16a) applies to both. Concurrent features
  keep every name (" / "), so no name is lost in a merge.
- D26 **Shards by bytes.** Road shards split while over 150,000 B and footprint shards while over 250,000 B (the 2,500-
  footprint rule left 52 shards over 300 KB; rendering.json); the address shards keep the 2,500-row rule. Road shards
  carry a name table (`"names":[...]`, index -1 for unnamed) so repeated names cost one entry.
- D27 **Zoom thresholds (measured by the rendering record).** Arterials (primary and secondary classes) from zoom 13; local
  streets, house dots and unmatched address dots from 15; footprint fills, hairlines and street names from 16; outline
  emphasis at 17. At zooms 13 and 14 a count layer draws one bubble per B1 tile with the house count from
  `hail/counts.json` ("1,240 buildings"), so the map says what is there without fetching the dots (a Billings view at
  zoom 13 would cost 4.2 MB of dot shards; at 15 it costs 0.8 MB). Owner decision 2's "dots at every address" is met
  from zoom 15 with the counts above it.
- D28 **Address shards hold the unmatched rows only.** `hail/a/` keeps the addresses that sit on no house dot (farther than
  15 m from every footprint; about 81,800 rows, about 5.3 MB); the matched rows live on their house dots in `hail/b/`;
  the search index keeps every row (a search must find an address on a house dot). verify checks that every address row
  appears exactly once across the two.
- D29 **House-dot words.** Building legend: "Each dot is one building outline. Tap a dot for its address, if one is on
  file, and the weather history for its cell." No address: "No address on file for this building. The weather history
  below is for this building's cell." Units: "Units on file: {n}." The attribution lines sit on the map's first screen
  (the attribution line) and on the About page: "Building outlines: USA Structures, Oak Ridge National Laboratory and
  FEMA (file dated 2026-09-13). Outlines come from imagery and are not surveys." and the roads line for the source built
  (the Library line, or the Census line with the trademark note when the fallback is built). The forbidden-word test for
  these templates adds "home", "house", "residence", "dwelling" and "use"; "structure" is allowed only inside the two
  proper names.
- D30 **Gates 9 to 18 of the synthesis apply** (counts: house dots equal footprints and every address row appears once;
  the Billings box join figures 869, 535, 313, 21; the no-address text on every dot without lines; shard caps; the
  class and placeholder rules; the zoom rules with a zoom-13 request fetching no footprint shard; the fetch budget of
  650 KB gzip for a 390 px Billings view at zoom 15; draw time under 30 ms per redraw at 15 and 16; the field test; the
  attribution placement). The synthesis's Chromium smoke scope replaces gate 7's.
- D31 **Publishing place.** The bulk files (about 358 MB raw, 71 MB gzip) stay in the hail store for the branch previews;
  the data-site split (a second repository's Pages site, deployed daily or monthly) is the owner's open decision; the
  modules write a base URL into map.json so the switch is a configuration change.
- D32 **Address placement classes.** The address file's Placement field decides the join (statewide: Structure 93.3 percent;
  Property Access and PropertyAccess 3.2 percent, read as one value; Geocoding 1.5 percent; Parcel, Site and Unknown the
  rest; by county up to 98.4 percent not Structure, Sanders). Only Structure points may join a footprint under D15's 15 m
  rule. Every other class keeps its own dot where the file puts it, and its popup says how it was placed: "This address
  point was placed {how}, not on the building." with {how} = "at the property entrance" (Property Access), "along the
  road by its number" (Geocoding), "at the parcel" (Parcel), "at the site" (Site), "by a method the file does not state"
  (Unknown). verify records the class counts per county. The 15 m figure stays until an imagery check (a follow-up, not
  this build) supports another.
- D33 **Streets, measured on the 2026 files.** D25's unnamed share and sizes were measured on the 2025 edition; the streets
  builder measures the 2026 county files it builds from and records them (the named share statewide and per county, the
  bytes at 2 m). Library class "Other" (15,416 records) is classified by the builder from its attributes: a public road
  keeps the local-street style; a trail, ferry or private drive is left out with its count recorded. The Census classes
  S1750 (internal census-use roads) and S1780 (parking lot roads) are left out with their counts recorded. Nothing is
  dropped silently. The field test includes Madrid Drive, Billings (in the Library file, not in the Census file).
- D34 **Building words.** The footprint file does not separate houses from sheds and barns (OUTBLDG is blank on every
  feature), its accuracy is tied to imagery dated 2008 to 2025, and no accuracy test exists. So the site says "building
  outline" and never "house", "home" or "residence"; the About page carries "Outlines come from imagery dated 2008 to
  2025 and are not surveys; sheds and barns are outlines too." verify records each county's outline count beside its
  address count (the page carries coverage words only, D21).
- D35 **No-address-text mode.** The site builder takes `--address-text off`: dots carry no address text and no search
  index is written (a dot still opens its cell history), so a counsel "no" on MCA 2-6-1017 is a configuration change.
  The Chromium smoke runs once in each mode.

## Supervisor rulings after the data-module re-check (2026-10-19 06:50 UTC; D36 to D38; the re-check is /home/user/hail-b3/out/b3a-recheck.json)
- D36 **Any source failure leaves the store standing (settles B3R-05).** Every failure to read or validate the address
  source (HEAD, download, the field list, the projection, a format assertion in the reader, a changed terms sentence)
  marks the list unavailable with its reason, keeps the rest of the store, and exits 0; verify without the zip passes
  with the unavailable state. The job never stops for the address source (D20). A changed terms sentence is an
  unavailable state too, so the site never shows a quote that no longer matches the file.
- D37 **"buildings" stands (settles B3R-08).** D21's coverage sentence says "buildings", never "dwellings" (D34 forbids the
  house words). The docs builder records the wording.
- D38 **Two budgets (settles B3R-09).** The 60 MB target applies to the dot shards (43.1 MB today; about 5.3 MB once D28
  moves the matched rows onto the building dots). The search letter files (39.0 MB) carry their own 60 MB budget. Both
  are measured and recorded by the site build.
- B3R-01 is settled by the rebase onto db84d76 (43aa57b). B3R-02, B3R-03, B3R-04, B3R-06 and B3R-07 are completion items.

## Supervisor rulings after the module completion (2026-10-19 07:40 UTC; D39 to D41) and the module items that ride the site build
The module completion (/home/user/hail-b3/out/b3a-recheck-completion.json) passes gate B3-1 (every D22 count exact; the
17-field allow-list; four byte-identical builds) and leaves two D36 gaps that ride the site build as the address module
fixer's items: a wrong or unreadable --zip path and a missing projection library still exit 1 without an unavailable
block, and the job cannot write an unavailable block after a crashed build or a failed verify.
- D39 **Duplicate groups keep the Structure row.** Of the 4,863 merged groups, 2,847 hold rows of two placement classes
  (P and S in 2,841, S and U in 6); the kept row is the Structure-placed one, so the dot sits on the building. The count
  of 6,744 merged rows stands. Recorded in the module docstring and verify.
- D40 **Row formats carry the class.** Shard rows are [lon, lat, line, city, zip, class] and letter rows are [number,
  street, unit, lon, lat, zip, class]; the buildings module and the browser read the class by position (the sixth and
  seventh element) and never guess it.
- D41 **Placement is the seventeenth allow-listed field.** D1 listed sixteen; Placement (the method that placed the
  point) is read for D32. It is not an owner, parcel, place-type or building-use field; decision 6 and D12 stand.
- Address module items for the site build's module fixer: build() marks the list unavailable and exits 0 on a wrong or
  unreadable --zip path and on a missing projection library (a ModuleNotFoundError from the lazy import becomes the
  unavailable state with the reason "the projection library is not installed"), and the test that asserted exit 1
  asserts the unavailable state instead (D36 wins); a subcommand `python -m website.addresses unavailable --store STORE
  --reason TEXT` writes the unavailable block with the reason and removes a/, and the job's failure branch calls it so a
  crashed build or a failed verify leaves an unavailable block, never a missing one; the job's address steps stay
  non-fatal end to end.

## Supervisor rulings after the site build (2026-10-19 23:10 UTC; D42 to D48) and the completion list
The site build's re-check (/home/user/hail-b3/out/b3-site-recheck.json; WIP fd3de57) passes 14 of 18 gates: the suite
(1,069), the self-test, the counts (every address row once: 558,356 on building dots and 105,403 unmatched), the zoom
rules, the shard caps, the search, the budget (624 KB gzip for the B3 files and the shell at 390 px), the draw times
(median 6.6 ms at 15 and 10.5 ms at 16) and determinism. Open: B3-5, B3-7, B3-10, B3-18 and the store's size.
- D42 **Store limits and the outline budget.** The B3 store is 31,129 files and 373 MB raw under hail/ (72 MB packed), over
  website/hail.py's unpack limits of 20,000 files and 300 MiB, so a --hail-history build from the asset marked the
  history unavailable. The limits rise to 60,000 files and 800 MiB with a test. The outline shards (196 MB, 213 B per
  outline at 5 decimals, no simplification by D14) carry their own budget of 250 MB; D38's two 60 MB budgets cover the
  address dot shards (7.5 MB) and the letter files (41.7 MB). The data-site split (D31) stays the owner's decision, now
  with these numbers; the Pages deploy carries the store only when the flag is on.
- D43 **Phone layout (R-01).** The two B3 legend sentences move into the layer menu; at phone width the find form sits
  behind a "Find an address" button (or inside the layer menu), so the legend card never covers the map's centre; the
  smoke's checks stand: the phone legend at most 180 px tall and a centre tap opening the sheet.
- D44 **Attribution (R-03, B3-18).** map.json's attribution carries the addresses line (the Montana State Library, the
  file date, the convenience sentence) with the roads and outlines lines, and the About page the same (D29).
- D45 **Words (R-04, R-06).** The usa_structures row says "no other field of the file is ever read, stored or shown"
  ("occupancy" never appears outside a quotation); the outline caveat sentence appears once, in the About caveat.
- D46 **The Billings box (R-11, B3-10).** Gate 10 reads the module's closed-box, merged-row figures: 864 points, 539
  inside, 305 within 15 m, 20 farther (the synthesis's 869, 535, 313 and 21 were half-open and before the merge).
- D47 **Zoom keys and the chooser (R-02).** map_data_addresses carries zoom.dots 15, zoom.choose 17 and dot_radius_px;
  the browser reads them; choosing a search row zooms to 17 and opens the sheet; the smoke counts the chooser zoom and
  the address dots at zoom 15 on the sample build.
- D48 **The rest.** R-05 (the unmatched-address legend sentence shows only when the outline layer is absent); R-07
  (--address-text off also drops the letter-index keys from the index block and rewrites the manifest); R-08 (the
  outline verify compares a missing key with a clear message, never a KeyError); R-09 (.gitignore roads/, counties/,
  structures-fema/); R-13 (the smoke expects the addresses attribution line; offline tests for the zoom keys and the
  phone legend height); the road simplification bound: the 2 m gate applies before rounding and verify and the docs
  state the post-rounding maximum (2.48 m measured); dots strictly inside the rounded rings with the exceptions counted
  (applied by the buildings fixer); the draw-time gate is read on a quiet machine (the re-check's figures stand); the
  budget line lists the B3 files plus the shell (624 KB) and the pre-existing precipitation layer (630 KB) separately;
  the Website workflow's test step installs pyproj and pyogrio and runs tests.test_addresses, tests.test_streets and
  tests.test_buildings; the counties file gets its CONTRACTS row (census_counties) with the Census statement; the
  roads and address "unavailable" steps in hail-store.yml are non-fatal; the store for the preview is the fresh job
  store /home/user/hail-b3/out/keep/hail-store-b3-job1.tar.gz (the stale buildings tar is not used).

## Supervisor ruling after the site completion (2026-10-20 01:20 UTC; D49) and the pre-push item
The completion re-check (/home/user/hail-b3/out/b3-site-recheck-completion.json) passes 16 of 18 gates; B3-7's imagery
leg and B3-8's runner leg run on the branch preview. The "==" count in website.yml is GitHub's own if: expressions,
allowed (D19 covers pip pins). R-13's offline legend-height test is not possible offline; the Chromium check stands.
- D49 **The index is rewritten with the store (N-1).** When the outline step rewrites hail/a (D28), it also rewrites the
  addresses block's figures in hail/index.json (bytes, shard count, largest shard, depth histogram) and the manifest
  entry, and addresses' verify checks those figures against the files on disk, so no stale figure is ever cited.
