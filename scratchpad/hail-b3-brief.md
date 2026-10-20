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
