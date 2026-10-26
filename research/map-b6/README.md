# B6: the Map page like the owner's reference

Owner request, 2026-10-25: ten screenshots of Apple Maps as shown inside the Zillow app, and "I want the first map to look
exactly like this. And work like this." This file is the research record and the plan. The rulings are in `docs/DECISIONS.md`
once the owner decides; the evidence files are listed at the end.

## 1. What the reference is

The screenshots show Apple Maps (the base map Zillow uses on iPhone) from a city block out to the state, and Zillow's own
"Map options" sheet on top of it:

- A sheet with three base maps (Default, Satellite, 3D View), "Climate risks" chips (Flood, Fire, Wind, Air, Heat),
  "Neighborhood amenities" chips (Banks, Bars & clubs, Coffee shops, more), a "Points of interest" switch, a "Highlight open
  houses" switch and a Reset button.
- At the block: a dark value bubble on every house (Zillow's price estimate; "--" where there is none), building footprints,
  street names, a wide grey band for the arterial, green patches for parks.
- At the neighbourhood and the city: points of interest drawn with icons and names (schools, a record shop, an ice cream shop,
  a coffee shop, a deli, parks), route shields (US 12, I-90, MT 200), the river in blue, a cream urban fill, green parks.
- At the metro, the region and the state: terrain tint and hillshade, the airport, towns with dots, reservations with their
  names (the Flathead reservation with its Salish name), national forests, peaks, river names, the state border.

## 2. Where our map stands today (measured 2026-10-25)

A local build of the branch with every layer on (the history, the dots, the storm layers) was captured in Chromium at 390 px
beside each reference view (`views/`, nine composites; the five most telling are committed here, the rest are in the
session archive).

| View | Reference | Ours |
|---|---|---|
| Block (Blaine St, Missoula) | A value bubble on every house; parks; points of interest; the arterial named | 249 dots on 248 building outlines (B3), street names, no bubbles, white land, no parks |
| Neighbourhood (zoom 15) | Nine named points of interest with icons, every street named, a US 12 shield, parks | A field of dots, no street names below zoom 16, no points of interest, no shields, white land |
| City (zoom 14) | The river, parks, campus fill, the local grid, labels | Arterials only, two "buildings" count bubbles, no river band |
| Metro and region | Airport, highway shields, terrain tint, towns, creeks | The Missoula bubble and a few faint lines |
| State | Reservations with names, forests, ranges, rivers, terrain | Town bubbles and borders on white |

Facts behind the plan:

- Our top zoom is 17 (319 m across a 390 px phone); the reference block view is about zoom 17.4 (235 m). The dots layer was tuned
  to 17; a top zoom of 18 is a build item, not a limit of the data.
- The store holds one radar value per 1 km cell, not per house. The block view spans four cells (62, 56, 66 and 66 houses), so a
  bubble on every house shows four distinct values. The largest radar estimates there over five seasons are 0.39, 0.31 and 0.26 in,
  and one cell has no stored value (nothing of 0.25 in or more). No cell in that view has a day of 1 inch or more.
- At zoom 17 the median distance between neighbouring dots is 19 CSS px (10th percentile 14 px); a five to seven character label is
  40 to 55 px wide, so labels collide on almost every house unless the map engine thins them (the reference's own bubbles overlap in
  places). Labels in the building shards would add about 0.3 gzip bytes per building.

## 3. Two ways to the look, both checked live

### A. Apple's own web maps (MapKit JS)

The reference is Apple's map, so this is the only path that gives the same cartography at every zoom: Apple draws the points of
interest, parks, terrain, reservations, forests, shields, rivers and labels; we draw our layers on top.

Verified on 2026-10-25 against developer.apple.com (the documentation JSON, the MapKit JS pricing page, the licence text and the
served library):

| Fact | What Apple says |
|---|---|
| Cost | The Apple developer account is free; the Maps token and the quota need the Apple Developer Program membership, 99 US dollars a year |
| Free allowance | 250,000 map views a day and 25,000 service calls a day per membership; a request form for more |
| Token for a static site | Made in the developer console: type MapKit JS, restriction Domain, a comma-separated domain list, duration "No Expiration"; revocable. No server and no key file needed. A build job could also sign tokens with a private key (format checked locally, acceptance untested) |
| Map types | Standard, Satellite, Hybrid, Muted Standard; dark mode for the standard types |
| Points of interest | A filter that includes or excludes any of 73 categories, changeable on a live map. Bank, Cafe, Nightlife, Restaurant, School, Park and NationalPark exist, so the amenity chips and the "Points of interest" switch map one to one. Icons and names are Apple's |
| Our layers | Tile overlays from a URL template or a canvas callback (our radar frames, swaths and risk pictures as tiles); circle, polygon and polyline overlays; live DOM annotations with clustering, collision modes and display priorities (the value bubbles). No single georeferenced image overlay, so each frame is cut into tiles. Version 6 needs CORS on every image; GitHub Pages already sends `access-control-allow-origin: *` |
| 3D | None on the web: no pitch, tilt or 3D map type in the documentation or the served library (camera distance and rotation only). The "3D View" choice cannot be offered |
| Version | 6.1.182 is the current build on the autoupdate URL (changed 28 Sep 2026); the 5.x line is old |
| Terms | The Apple logo and the Legal link stay visible (undocumented options that hide them would breach the licence and can get the key revoked). Map data may not be cached, pre-fetched or stored: a sample or offline build cannot carry Apple tiles. Location features need notice and consent. The site may reach Apple Maps only through MapKit JS, which every example loads from Apple's CDN, so AGENTS.md rule 4's "no CDN" clause needs an exception for this one script. No fee may be charged for map access |

### B. A self-hosted stack (MapLibre GL JS, OpenStreetMap tiles, USGS imagery, public terrain)

A near look that is ours end to end. Verified the same day:

| Fact | Measurement |
|---|---|
| Tiles | Protomaps daily planet builds (139.2 GB; version 4.15.2; ODbL "Produced Work" wording with OpenStreetMap attribution). A Montana extract at zoom 13 is 98,834,814 bytes (under GitHub's 100 MiB file limit by 6 MB); at full zoom 15 about 404 MB (planned size; not written). A Missoula box at zoom 15 is 3.65 MB |
| Points of interest | In the Missoula tiles 9 of the 10 reference names exist (Rockin' Rudy's as a music shop; St. Paul Lutheran as "Saint Pauls Lutheran Church"); Rose Park is a neighbourhood label, not a park. Counts in the box: 35 banks, 38 cafes, 30 bars and pubs, 83 restaurants, 34 schools, 90 parks |
| Not in the tiles | Named national forests and reservations (no names on land use or boundary polygons) and hillshade; both need extra layers (Census and USFS boundaries, which are public domain; terrain tiles) |
| Terrain | AWS terrain tiles (Terrarium PNG) decode correctly: 980 m at Missoula; attribution per the Joerd page; MapLibre reads them for hillshade and 3D |
| 3D | Possible with terrain and extruded footprints, but only 239 of 33,784 Missoula buildings carry a height, so the 3D view would be default-height boxes |
| Library and fonts | MapLibre GL JS 6.16.0, BSD-3-Clause, 294 KB gzip (plus a 147 KB worker); glyphs from the site's own fonts build with a prebuilt tool (146 KB gzip) |
| Hosting | GitHub Pages serves byte ranges (206 responses verified on the live site), the site limit is 1 GB, and the live site publishes 32 MB of the hail store today; the full B5 store (552 MB) plus a 404 MB tiles file would be over the limit, the zoom-13 file fits |
| Licence | ODbL: attribution required; a map page is most likely a Produced Work and our hail and address data a Collective Database, so no share-alike on our data; counsel to confirm (item 21 for the counsel list) |

## 4. The supervisor's reading and recommendation

Path A is the reference. It costs 99 dollars a year, a script loaded from Apple, Apple's logo and Legal link on the map, and
a consent notice before the locate button; it cannot give the 3D view on the web, and it never appears in sample or offline
builds. Path B would take weeks of cartography (a style, glyphs, sprites, three extra boundary layers, a tile build in the
daily job) and would still not be Apple's map; its 3D view would be honest but plain.

Recommendation: build on Apple's web maps (path A), keep the present white map as the fallback the page shows when the token
is missing, the script does not load, or the build is a sample (so the offline tests and the parked checks keep running), and
leave the 3D choice out of the sheet with one sentence in About that says why. If the owner does not want an Apple membership,
path B at zoom 13 is the next best, and the caps decision (ROADMAP owner item 2) decides whether the full store and the tiles
can share one site.

Either way the following are ours and are built the same way:

- The Map options sheet: base map pictograms, chips for the live layers (precipitation, temperature, gusts, hail last hour and
  last 24 hours), chips for the five-year risk layers, amenity chips, the Points of interest switch, a "Highlight recent hail"
  switch (the open-houses equivalent: buildings in cells with a radar estimate of 1 inch or more in the last 30 days), Reset.
- The value bubble: the cell's largest five-year radar estimate ("0.39 in") on every house in the cell, "--" where nothing of
  0.25 in or more was stored, never a zero; the sheet says the value is the 1 km cell's; the map engine thins overlapping bubbles.
- The risk layers from our store and from verified public sources (section 5).

## 5. The risk chips, with the sources checked live

| Chip | Source | State | Legend sentence (draft) |
|---|---|---|---|
| Hail | Our five-year radar store (NOAA MRMS MESH): days with a radar estimate of 1 inch or more per 1 km cell; 144,522 of 450,765 Montana cells have at least one such day; 13,765 have three or more | Ready: one palette PNG of about 42 KB covers Montana at the native cell size | Radar estimate of hail 1 inch or more, days per 1 km cell, October 2021 to October 2026. A radar estimate, not a measurement; a cell with no day is not "no hail" |
| Heat | Our climate grid (NOAA nClimGrid-Daily, about 4.6 km): days at or above 90 F over five seasons; Billings cell 47 days in 2021-22 against 45 at the airport station | Ready: a 6 KB palette PNG | Grid estimate of days at or above 90 F, July 2021 to June 2026; monthly data that runs 4 to 68 days behind |
| Wind | Our zone products: high wind warnings 2,544, watches 2,010, wind advisories 427 by NWS forecast zone; the zone outlines (475 KB, Iowa State) | Ready as a per-zone count; the zone outline file is a new store part | High wind warnings and watches by NWS forecast zone, 2021 to 2026; each product covers the whole zone |
| Flood | Our NWS flood products by polygon and zone (flood warnings 43, areal flood warnings 37, watches 35, advisories 558) and the live river stages of 277 Montana gauges with flood categories | Ready as a per-zone count plus the gauge dots; FEMA flood zones stay out (DECISIONS D38, counsel item 12) | NWS flood watches, warnings and advisories 2021 to 2026, by polygon and zone; river stage categories live from NWS gauges |
| Fire | NIFC current perimeters (5 in Montana today; disclaimer only, no licence sentence) and historic perimeters (6,879 since 1915); MTBS burn severity (national zip 390 MB; "no restrictions on use, except for reasonable and proper acknowledgement"); USFS Wildfire Hazard Potential raster 270 m (reuse without permission or fees) | New store parts in the daily job; the NIFC terms and the MTBS outage of 28 Oct 2026 noted | Fire perimeters from NIFC, current and since 1915; burn severity from MTBS; hazard potential from the Forest Service |
| Air | NOAA Hazard Mapping System smoke polygons, daily (48.6 KB a day; 116 polygons on 2026-10-24); AirNow needs an API key and its terms were not readable; PurpleAir is not public domain | Smoke is buildable now; "Air quality" waits for an AirNow key and its terms | Smoke plumes from NOAA's satellite analysis, updated daily; not a ground measurement |

Every chip keeps rule 5: a cell or zone with no record reads as no record, never as no risk, and each legend names the kind of
record, its source and its age.

## 6. The build list (path A)

1. B6-1 Base map: the token (an Actions secret the build writes into map.json; the fallback when absent), the script from Apple
   with the map, overlays and annotations libraries, a content security policy line, the Apple logo and Legal link untouched, the
   Standard and Satellite choices, the Points of interest switch, the amenity chips through the category filter, the consent
   notice before the locate button, the About sentences (Apple's maps; tiles and points of interest come from Apple while the map
   is on).
2. B6-2 The Map options sheet, in the site's own tokens, replacing the layer menu; the same sheet drives the fallback map.
3. B6-3 Value bubbles: the cell value on every house as annotations with clustering and collision handling; top zoom 18; the
   building count bubbles stay at lower zooms; "Highlight recent hail".
4. B6-4 Risk layers from the store as tiles: hail, heat, wind, flood; legends with the kind words.
5. B6-5 Fire and smoke: new daily job steps, contract rows, terms in About.
6. B6-6 The live frames as tiles: `website/gridded.py` cuts each frame into z/x/y tiles for the tile overlay; playback as today.
7. B6-7 Tests: the Chromium smoke against Apple's map with a token that also lists localhost; the parity tests unchanged; the words
   and budget tests; the fallback smoke without a token.
8. Docs: DECISIONS (the rulings), DESIGN (the sheet and the bubbles), ROADMAP, AGENTS rule 4 (the Apple exception), the counsel list
   (Apple's terms; the ODbL reading if path B is ever taken).

## 7. Decisions for the owner

1. Hold an Apple Developer Program membership (99 dollars a year) and make a MapKit JS token restricted to carson14dy.github.io
   and localhost with no expiration; or choose path B.
2. Accept the one exception to AGENTS.md rule 4: Apple's script loads from Apple.
3. The map keeps the Apple logo and Legal link; a consent line precedes the locate button.
4. Leave the 3D choice out (not available on the web), or show it greyed with the reason.
5. The value bubble shows the cell's largest radar estimate (recommended) or the count of 1 inch days.
6. The caps and hosting (ROADMAP owner item 2) decide the fallback path B.

## 8. Evidence

- `views/`: five of the nine side-by-side captures (reference left, ours right, caption with the zoom); the rest and the raw
  captures are in the session archive (`session-archive/b6/`).
- Apple: the documentation JSON pages read (Map, PointOfInterestFilter and the 73 categories, TileOverlay, loading, the token
  page, the migration guide), the pricing page, the licence clauses quoted in the session archive.
- Open stack: the extract logs and sizes, the decoded Missoula tiles, the terrain tile decode, the Pages range test, the glyph
  build, the ODbL and OpenStreetMap attribution texts, all in the session archive.
- Risk sources: the live fetches, counts and quoted terms per source, in the session archive.

## 9. The owner's decision and stage 1 (2026-10-25, afternoon)

The owner, after the research above: "We don't need the apple design anymore. That was just a base that I don't want in the
finish." So the screenshots set the behaviour and the structure; the finished map is ours, on the architecture the site has
(Leaflet drawing Python-built site files), from public-domain data only. No Apple membership, no OpenStreetMap, no MapLibre
(DECISIONS D107 when recorded). The 3D choice is out. The amenity chips become landmark chips.

### 9.1 What stage 1 verified (all live, two skeptics per claim)

| Layer | Source and terms | Montana size | Build note |
|---|---|---|---|
| Terrain shading | USGS 3DEP hillshade, exportImage per 256 px tile (no tile cache); public domain, credit requested | zooms 5 to 10: 805 tiles, about 8 MB as grey JPEG (29 MB PNG); zooms 11 and 12 add 11,058 tiles, about 79 MB JPEG | tiles join without seams; built by the monthly job |
| Land cover tint | NLCD 2021 (MRLC): "public domain information"; Fees NONE | about 2 MB at 240 m statewide; palette tiles 5 to 9 KB each (zoom 10 about 5 MB; zoom 12 about 50 MB) | drawn under the hillshade at low opacity; fades out by zoom 13 |
| Water with names | USGS NHD map service (small-scale layer for low zooms, large-scale per tile); TIGER county files as the fallback (162 MB zipped, abbreviated names) | statewide sizes measured in stage 2 | Natural Earth rivers stay for the first paint |
| Reservations | Census TIGER AIANNH: 7 Montana reservations, English names only | 9.2 MB national file | the Salish name of the Flathead Reservation needs the Tribes' confirmation |
| National forests | Forest Service administrative boundaries: 7 forests with most of their area in Montana; federal work, no reuse sentence in the metadata | 93 MB national zip or the map service | a courtesy note to the Forest Service recorded; counsel sees the terms |
| Parks | PAD-US 4.1 Fee layer by its map service (public domain): 1,457 Montana polygons, 558 local parks; Sacajawea, McCormick and Rose Garden found; TIGER area landmarks as the fallback (104 parks, 101 state parks, 22 city parks) | attribute sample 133 KB; geometry per tile | city parks at zoom 13 and up, state parks from zoom 9 |
| Schools | NCES EDGE public (854) and private (109) school points; "All information contained in this file is in the public domain" | 234 KB of attributes | Loyola Sacred Heart and Hellgate both present |
| Hospitals | HIFLD copy of the state licensure list (71); no licence text; FAA heliport records and TIGER as checks | 59 KB | counsel confirms the licensure list's terms, else the USGS structures layer |
| Airports | FAA NASR airport file (318 Montana records) and the HIFLD copy of the national transportation atlas (United States government work) | 10 MB national zip | public-use airports only on the map |
| Churches | FEMA copy of an IRS-based places-of-worship layer (1,074; "no use limitations"); 499 are geocoded to a postal code only | 293 KB | point-address rows only; the geocoder's terms to counsel |
| Fire stations | USGS National Map structures layer (461) | 209 KB | optional kind |
| Peaks | GNIS summits (3,181) without elevation; 3DEP sampled at the point | 1.5 MB zip | the sampling check is in stage 2 |
| Places | TIGER places (497) with 2020 counts; min zoom by population | 2.3 MB | Lolo, Frenchtown, Florence, Stevensville, Hamilton, Seeley Lake, Darby all present |
| Route numbers | TIGER full names (US Hwy 12, State Hwy 200, I- 90) and the basemap refs | 2.6 MB | shields drawn by the browser from the data |

The proof pictures (`views/proof-region-side-by-side.jpg`, `views/proof-city-side-by-side.jpg`) were drawn by Python from these
sources in the site's palette: relief multiplied in at 0.28, soft green forest and cream developed land from the land cover,
blue water, Census roads with shields, towns by rank, forests and the reservation named in spaced capitals. The statewide
raster base measured about 57 MB as WebP tiles for zooms 5 to 12, or about 8 MB of hillshade plus 5 MB of tint for zooms 5 to 10
as separate layers.

### 9.2 The sheet and the bubbles (mocks in Chromium, `views/sheet-mock-side-by-side.jpg`, `views/bubbles-a-clusters-vs-b-per-building.jpg`)

The Map options sheet in the site's roles: Base map (Map, Imagery), Live weather and Five-year history as one-at-a-time chips,
Landmarks as independent chips, the switches Points of interest, Highlight recent radar hail, Warnings and Storm reports, Reset;
a one-line legend under whatever is on, with the source, the age and what a missing value shows. Measured: 0 hex values, 0
overflow from 288 to 1440 px, every target 44 px, text contrast at least 6.76:1 light and 7.87:1 dark. "Risks" is not used:
the five-year group is history (DESIGN section 12 rule 6).

The bubble on the block: 248 buildings in four radar cells (0.38 in, no value, 0.30 in, 0.26 in). One bubble per building with a
skip rule labels 91 of 248 at zoom 17; one bubble per cluster of buildings in the same cell labels every building with 56
bubbles. The cluster rule is recommended; the owner picks. Top zoom 18 is a build item.

### 9.3 The build list, revised (stage 2)

1. B6-1 Data products (Python, the monthly and daily jobs, the store): hillshade and tint tiles for zooms 5 to 10; rivers and
   lakes with names by zoom band and per tile; reservations, forests, parks, places and peaks as shards by zoom band; the
   landmark points per tile with their kind; the route shields' data; the hail and heat pictures and the wind and flood
   per-zone counts; the recent radar hail product (cells with 1 inch or more in the last 30 days); the bubble anchors per
   zoom in the building shards; a CONTRACTS row and an About sentence per source; sizes measured against the phone budget.
2. B6-2 The Map options sheet (the mock's HTML and CSS into the site's template and map.css; map.js wires the chips to the
   layers).
3. B6-3 The base map in the browser: the raster tiles under the vector layers, the new shards drawn by zoom, labels thinned by
   the Python placement, shields, landmark icons (ours), the tint fading by zoom 13.
4. B6-4 The value bubbles (the anchors from B6-1) and top zoom 18.
5. B6-5 The five-year layers in the sheet (hail, heat, wind, flood) with their legends; fire and smoke as new daily parts.
6. B6-6 Tests and smoke: the parity and words tests, the budget smoke with every new layer on, the sheet states, the fallback
   without the raster tiles; docs (DECISIONS, DESIGN, ROADMAP, About).

