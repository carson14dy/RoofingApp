# AGENTS.md: RoofingApp

Shared instructions for every AI coding agent in this repo. ChatGPT/Codex read this file
directly; Claude Code reads it through `CLAUDE.md`. Humans: start with `README.md`.

## What this is
Montana Hail Watch (D26), weather for a Montana roofing company (owner: Carson, `carson14dy`).
**The product is a website (D27):** official NWS alerts, an interactive radar, forecast and warning
map in the style of Apple Weather (D28), a 12-hour card and a 24-hour/7-day page per town, and SPC
storm reports. Python builds it into static pages;
GitHub Actions is asked to rebuild it every 10 minutes from `main` (and builds on every push to `main`) and publishes it with GitHub Pages, so
**anything merged to `main` is live within about 10 minutes**.
The desktop app was removed on 2026-10-26 (D143); its code is in git history, and the last commit that changed it is `33cda31`.

## Read before you change things
- `docs/handoff/Roofing_Weather_Claude_Handoff.md`: the original weather spec (the evidence kinds and
  the acceptance checks still apply; its app screens are history).
- `docs/handoff/Roofing_Weather_Independent_Review.md`: supersedes the handoff's provider shortlist;
  its P0/P1 priorities set the order of work.
- `docs/DECISIONS.md`: why the architecture is the way it is, including bugs already fixed (D27: the website).
- `docs/DESIGN.md`: the website's design (pages, states, tokens, and why).
- `docs/ROADMAP.md`: what's done, what's next, open questions.

## Layout
```
website/   the product. sources.py (NWS/SPC feeds, parsers, feed contracts) · gridded.py (MRMS radar
           + HRRR model → map frames) · storm.py, satellite.py and swath.py (radar echo tops, the GOES
           band 13 picture and the MRMS hail swath, all behind --storm-layers) · build.py (collect → frames + data/map.json →
           pages) · sample.py (labelled sample data) · towns.json · templates/ · static/ (style, Leaflet,
           fonts, map/ = map.js, map.css, basemap.json)
           hail.py (hail history: grid, size words, store readers, daily build; --hail-history) · hail_fixture_data.py (the
           SAMPLE store's events) · data/hail-fixture/ (the SAMPLE store) · joins.py (the hail history joins, B2, D35:
           reports, official records, radar detections, warnings, zone products and red flag warnings by fire weather
           zone, station gusts; pyshp imported lazily) · addresses.py (B3, D36: the State Library address points as
           dots, the search index and its verify; pyproj imported lazily; the job only) · streets.py (B3, D25, D33: the
           State Library roads, the Census fallback, the street shards; pyproj lazily) · buildings.py (B3, D14, D15, D32,
           D34: the FEMA and ORNL building outlines, one dot each, the address join; pyogrio imported lazily) · climate.py
           (the past weather, B5, D38: the NOAA nClimGrid daily grid per cell, the backfill once and its release archive,
           hail/c/; h5py imported lazily) · stations.py (GHCN-Daily station readings and the station rule, D5 and D18; the pool of stations in Montana and the neighbouring states, D62; the tile lists with their rejected candidates, D61 to D69;
           hail/sd/) · snowgrid.py (the NOHRSC season snowfall grid and its unit check, D7; hail/n/) · gauges.py (NWS
           flood stages and USGS annual peaks, the nearest gauge within 10 miles, D6; hail/g/) · summary.py (the
           five-season table that leads the sheet and the roof lines, B5; its words are Python's)
tools/     build_basemap.py (rebuilds static/map/basemap.json from Natural Earth + Census; by hand)
.github/workflows/website.yml   build every 10 min from main → GitHub Pages; branch pushes = live check
.github/workflows/tests.yml     the unit tests: on every push to main, on every pull request and by hand (requirements.txt)
.github/workflows/hail-store.yml   daily 12:43 UTC: build the hail store, join its sources (website/joins.py), add the B5 weather parts (climate, stations, NOHRSC, gauges; non-fatal steps with timeouts) and verify them, build and check the address, street and outline steps (B3, D36; each non-fatal), pack and publish the release assets; a plan job starts the monthly job (the first of the month, or by input) in its own job, and the once-only backfill runs by input (D34, D35, D36, D38, D42)
tests/     test_addresses.py, test_basemap.py, test_basemap2.py, test_buildings.py, test_climate.py,
           test_gauges.py, test_gridded.py, test_hail.py, test_hail_workflow.py, test_history_layers.py,
           test_joins.py, test_labels.py, test_landmarks.py, test_satellite.py, test_site.py,
           test_snowgrid.py, test_stations.py, test_storm.py, test_streets.py, test_summary.py,
           test_swath.py, test_terrain.py, test_website_workflow.py, test_words_rules.py (all website);
           words_rules.py (the word rules the tests share) · fixtures/ (the archives the tests read)
```

## Commands
```bash
pip install requests jinja2 pillow numpy pygrib h5py tzdata pyshp     # enough for the website
python -m website.build --out _site --sample             # labelled sample data, no network
python -m website.build --out _site --hail-history       # the five-year hail history (D34; on main at the owner's decision of 2026-10-21)
python -m website.build --out _site --hail-history --hail-store store   # a local store folder or hail-store.tar.gz instead of the download (D59)
python -m website.build --out _site --storm-layers       # B4, B5: the radar echo tops, the GOES picture and the MRMS hail swath (behind the flag; off on main)
python -m website.joins build --store store --cache joins-cache   # the hail joins (D35); needs pyshp
python -m website.joins verify store                     # check the hail joins
python -m website.build --out _site --sample --hail-history --hail-addresses   # the address dots, streets and outlines (D36); off by default
python -m website.build --out _site --sample --hail-history --hail-addresses --address-text off   # the same with no address text (D35)
pip install pyproj~=3.8 pyogrio~=0.13                   # the job's address, street and outline steps only (compatible releases)
python -m website.addresses build --store store --cache structures   # the address points (job); verify with: python -m website.addresses verify store
python -m website.streets build --store store --cache roads --roads-source msl   # the streets (job); --roads-source tiger is the fallback
python -m website.buildings build --store store --cache structures-fema --counties-cache counties   # the outlines and their dots (job)
python -m website.climate backfill --cache climate-cache   # B5, once: the 63 scaled months into aggregates (D38; 222 s measured)
python -m website.climate update --cache climate-cache     # B5 daily: prelim days (and a new scaled month when one appears)
python -m website.climate build --store store --cache climate-cache   # then: stations, snowgrid, gauges (the same store)
python -m website.stations build --store store --cache b5-cache --scope daily   # --scope monthly for the whole union
python -m website.stations verify --store store   # check the station figures and gates (exit 1 on a failure)
python -m website.snowgrid build --store store --cache b5-cache --offline       # drop --offline to check NOAA (monthly)
python -m website.gauges build --store store --cache b5-cache                   # --refresh for the monthly read
python -m website.build --out _site --require-live       # live data; exit 1 if any source failed
python -m http.server -d _site 8000                      # then open http://localhost:8000
pip install -r requirements.txt   # the website
python -m unittest discover -s tests -v         # offline; must pass before any merge
python tools/smoke_map.py _site --history --store store   # B5: the sheet's summary words from a store folder or hail-store.tar.gz (the build passed --hail-history)
```

## Hard rules
1. **Shipping.** Website: merging to `main` publishes. Keep `main` green; push to a branch first
   (the Website workflow builds branch pushes against live data) and check the pages in a browser. The hail history flag `--hail-history` is on for the public site from `main` (the owner's decision of 2026-10-21); `--hail-addresses` stays off on `main` until the owner approves its terms and counsel answers them (D34, D36).
2 and 3. Retired with the desktop app (D143); the numbers stay so older citations read.
4. **Python first.** Python builds all data and pages (Jinja; the radar and model frames in
   `website/gridded.py`). Hand-written JavaScript only for browser-only needs, documented inline
   (website: the page-age check in `website/templates/base.html` and the interactive map in
   `website/static/map/map.js`: playback, scrubbing, menus, sheets, geolocation, D28). Owner
   preference: don't add a JS framework. Third-party code (Leaflet) and fonts are served by the
   site, not a CDN. The browser fetches only site files, except the USGS imagery tiles, which it
   fetches only while Imagery is on (switched on by the viewer, or by a link that starts on it; D32),
   from the one host named in `website/build.py`.
5. **Evidence honesty.** Keep forecast, radar estimate, point report, official alert and
   inspection separate. Never state confirmed damage, insurance eligibility or a damage
   probability. No report is not “no hail.” Missing inputs show “Data unavailable,” never an
   all-clear. Demo data only under the demo event, labelled DEMO everywhere.
6. **Official alerts.** Match by warning polygon, else the place's NWS forecast zone / county /
   fire-zone codes. Null geometry never means “no alert”; can't-tell shows as can't-tell. Never
   clear a warning after a failed request. No AI-generated text anywhere in the alert path.
7. **Feeds.** `website/sources.py` `CONTRACTS` record each
   feed's units, timing, cadence and missing-value rules; change the parser, the table and the
   tests together. Before building on a source, make
   a live request **and check the content**, not just HTTP 200 (see the radar-layer bug in
   `docs/DECISIONS.md`).
8. **Verify UI in a real browser** (Playwright/Chromium is fine). String checks on HTML once
   missed a map that never ran.
9. **No “best” claims** for any provider or model until the evaluation in `docs/ROADMAP.md` supports it.

## Conventions
- Plain wording from the user's side; sentence case; an error says what happened and what to do.
- Website look: the light “field sheet” with automatic dark mode (`docs/DESIGN.md`); tokens in
  `website/static/style.css` `:root`, never hex values in components. Every hazard colour carries
  its word. Map labels: set a new town's label side (and, if its bubble would cover a neighbour's, its `min_zoom`) in `towns.json`; the label test must pass.
- Store UTC. Show a job's NWS time zone (or the company zone). SPC dates follow 12:00–11:59 UTC
  reporting days. Hail sizes in SPC CSVs are hundredths of an inch; `UNK` wind stays unknown.
- Hail history sizes (D34): to the hundredth of an inch, rounded down, with the millimetres exact beside them; the classes use the exact tenths.
- Building words (D34, D36): a dot is a building outline, never a house. Site words never say house, home, residence or dwelling. Owner and parcel appear only in the About sentence "Owner names and parcel identifiers are never read, stored or shown." (D8, gate B3-5) and in the Parcel placement phrase "at the parcel" (D32). "structure" appears only inside the two proper names. A dot's placement is said where the file did not place it on the building (D32).
- Hail history kinds (D35): every section names its kind, and every row starts with its kind label (D3: "Report:", "Record:", "Detection:", "Warning:", "Zone product:", "Station:"); a report is not an inspection; a detection is not hail on the ground; a warning's tags are the forecast threat; a zone product covers its whole zone; a station reading is at the station; NCEI times are MST-7 local, shown as Montana time; "damage" appears only as the NWS damage threat tag, in a quoted remark or as a source's type word (D4).
- Add or update tests with every behavior change.

## Owner's working preferences
- Direct, brief communication with a clear bottom line; data and ranked options over prose.
- Python-only where possible; minimal JavaScript, clearly documented.
- Verify data sources before building; be transparent about limitations and mistakes.
- When the approach needs to change, a clean rebuild beats patching around it.
- Single-file reference docs are preferred over many small ones.

## Two agents, one repo
Claude Code and ChatGPT both work here. Work on a branch and open a pull request; keep PRs small;
say what changed and how it was verified (tests, the branch's live Website build, browser check). Record decisions in
`docs/DECISIONS.md` and status changes in `docs/ROADMAP.md`. Don't rewrite the other agent's work
without explaining why in the PR. Check `docs/ROADMAP.md` before starting so work isn't duplicated.
