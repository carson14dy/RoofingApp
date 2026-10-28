# RoofingApp

Weather for a Montana roofing company: **Montana Hail Watch**.

**The product is a website** (decision D27, 2026-10-14). It shows official NWS warnings, a radar
and warning map, the next 12 hours for 17 Montana towns, a 24-hour and 7-day page per town, and
three days of SPC hail and wind reports. It also shows a five-year history of radar-estimated hail for any spot in Montana (D34; public at the owner's decision of 2026-10-21). GitHub is asked to rebuild it every 10 minutes from public data (its schedule ran 6 times in the 24 hours to 2026-10-21 23:00 UTC; the timer decision is open in the roadmap) and
publishes it with GitHub Pages at **https://carson14dy.github.io/RoofingApp/** once Pages is
turned on. Nothing to install: open it on any phone or computer.

The earlier desktop app was removed on 2026-10-26 (D143); the last commit that changed it is 33cda31.

**AI agents (Claude Code, ChatGPT/Codex):** read [`AGENTS.md`](AGENTS.md) first. Decisions live in
[`docs/DECISIONS.md`](docs/DECISIONS.md), the website design in [`docs/DESIGN.md`](docs/DESIGN.md),
status and next steps in [`docs/ROADMAP.md`](docs/ROADMAP.md), requirements in
[`docs/handoff/`](docs/handoff/).

---

## Contents
The website
1. [Turn the website on (once)](#turn-the-website-on-once)
2. [What is on it](#what-is-on-it)
3. [How it stays honest](#how-it-stays-honest)
4. [How it updates](#how-it-updates)
5. [Build it on your computer](#build-it-on-your-computer)
6. [Website files](#website-files)

---

## Turn the website on (once)

1. On GitHub: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. Merge the branch with the website into `main`.
3. Open **Actions → Website**. The run after the merge publishes the site; its summary lists each
   source and what it returned. After that it runs on a schedule set to every 10 minutes (GitHub ran it 6 times in the 24 hours to 2026-10-21 23:00 UTC; the timer decision is open in the roadmap).
4. Open https://carson14dy.github.io/RoofingApp/ on your phone. Add it to the home screen if you
   like: it gets the Montana Hail Watch icon.

The repository is public, so GitHub Actions and Pages cost nothing. GitHub pauses scheduled runs
after 60 days with no activity in the repository; if the site stops updating, open **Actions →
Website** and re-enable it. Every page says how old it is, so a stalled site is visible.

## What is on it

| Page | Shows | Source |
|---|---|---|
| Now | Active warnings, watches and advisories for Montana, most urgent first; a map card with the latest radar and the warning outlines; a card per town with the latest station reading, then temperature, highest gust, chance of rain or snow, and which hours pass a limit | NWS, NOAA |
| Map | A full-screen map of Montana in the style of Apple Weather's: press play to run the past hour of radar into the next 12 hours of forecast, switch to temperature or wind gusts, see warning outlines and storm reports, tap a town for its NWS forecast, or find your own location | NOAA MRMS radar estimate, NOAA HRRR model, NWS, SPC |
| Town (17) | Alerts at that town, what the three nearest weather stations measured (with each reading's age), the next 24 hours hour by hour (gusts first), the next 7 days | NWS |
| Storm reports | Hail and wind reports in and near Montana for the last three reporting days, on a map and in tables | SPC |
| Hail history (build flag `--hail-history`, on `main` at the owner's decision of 2026-10-21) | On the Map, tap or click a spot for its five-year history of NOAA radar-estimated hail: each day at 0.25 in or more, in inches and millimetres, with its SPC day. The same spot also lists its NWS local storm reports, NCEI Storm Events records, radar hail detections, the warnings whose polygon covered it, the zone products for its forecast zone, the red flag warnings for its fire weather zone and the gusts at the nearest stations, each under its own kind label. Station readings come from stations in Montana and the neighbouring states within 40 miles; Canadian stations within reach are not read while the terms for their data are under review. Each town page has the same tables. The history opens with a five-season table (2021-22 to 2025-26, July to June, with the partial 2026-27 season below it), then eleven sections in one fixed order: Hail, Wind, Storms and warnings, Temperature, Rain, Snow, Flooding, Ice and winter, Heat, Weather that matters for a roof, and How this was made. An estimate is not a measurement or an inspection | NOAA MRMS radar estimate (MESH); NWS reports, warnings and zone products (IEM); NCEI Storm Events and SWDI; NCEI GHCN-Daily and NOAA nClimGrid-Daily (station and grid values); IEM station data |
| Addresses, streets and building outlines (build flag `--hail-addresses`, on `main` since 2026-10-28, D146) | On the Map: the street lines, the arterials from zoom 13, the local streets from 15 and the names from 16; from zoom 15 each building outline has one dot, and each address that no outline holds has its own dot. Tap a dot for its address, if one is on file, and the weather history for its cell. A search box, "Find an address", finds a typed address; what is typed stays in the browser | Montana State Library (address points and roads); USA Structures, Oak Ridge National Laboratory and FEMA (building outlines); U.S. Census Bureau (roads, if the fallback is built). The terms are on the About page |
| About | What each part is, the flag limits, what happens when something fails, the data sources in detail | None |

Towns: every Montana city over 8,000 in the 2020 census, plus Sidney and four smaller towns
(Glasgow, Glendive, Lewistown, West Yellowstone): Anaconda, Belgrade, Billings, Bozeman, Butte,
Glasgow, Glendive, Great Falls, Havre, Helena, Kalispell, Lewistown, Livingston, Miles City,
Missoula, Sidney, West Yellowstone (D31). To change the list, edit `website/towns.json` (see
AGENTS.md for the map-label check).

Flag limits are placeholders until the company sets its own: gusts 25 mph, wind 20 mph, a 30%
chance of rain or snow, under 40 °F or over 95 °F (`website/sources.py`, `LIMITS`).

## How it stays honest

- **A failed check is never "no alerts".** If NWS doesn't answer, the page says so. The last
  verified list stays up with its time, and the page links the four NWS offices.
- **Missing is a dash, not a zero.** A missing value never raises a flag and never passes one.
  If gusts didn't load, the town card says gusts weren't checked.
- **Every page says its age.** It shows when it was built and which sources loaded, and warns in
  words when it is more than 25 minutes old.
- **No report is not "no hail".** The site never claims damage or that it is safe to work.
- **A radar estimate is not a measurement.** The hail history says so beside its numbers, and a day with no estimate is not "no hail".
- **Each kind of record has its own word.** A report is what someone sent the NWS, not an inspection. A radar detection is the radar algorithm's signature, not hail on the ground. A warning's tags are the forecast threat, not what fell. A zone product covers its whole zone. A station reading is at the station, not at the address.
- **No AI-written text.** Alert text is the NWS's own words.

## How it updates

`.github/workflows/website.yml` runs on GitHub on a schedule set to every 10 minutes, and on every push to `main` that touches the site:
1. It runs the website tests.
2. It fetches NWS alerts and forecasts and SPC reports. For the map it downloads the past hour of
   NOAA radar (MRMS) and the newest HRRR model run, and draws them as picture frames.
3. It builds the pages and publishes them.

GitHub sometimes starts scheduled runs late, so a page can be 10 to 20 minutes behind NWS when the schedule runs, and hours when GitHub delays it. Each page
links weather.gov for the latest. Pushes to `claude/**` and `codex/**` branches run the same build
against live data as a check. That run fails if any source failed, and its pages can be
downloaded from the run.

With `--hail-history` (on `main` at the owner's decision of 2026-10-21), a daily job, `.github/workflows/hail-store.yml`, runs at 12:43 UTC. It rebuilds the whole trailing five years of NOAA's radar archive each day (a full rebuild, not an append), joins the NWS reports, NCEI records, radar detections, warnings, zone products and station gusts to each tile (`website/joins.py`), verifies the result and publishes it as a release asset named after the branch (`hail-store-main.tar.gz` for `main`; slashes as dashes), which the 10-minute build downloads: each build reads its own branch's asset (`HAIL_STORE_ASSET`), so a branch job never touches what `main` reads, and a branch build waits for its branch's latest store job before it reads the asset (main does not wait). The B5 steps run after the store and the joins, each non-fatal, on one 40-minute clock: the climate restore and update (the preliminary grid days, and a new scaled month when NOAA posts one), the station readings, the river gauges and the NOHRSC snow analysis, with their checks. The monthly job, on the first of the month, reads every candidate station and asks NOAA about the snow analysis once.

The same job always builds the address dots, the street lines, the building outlines and the address search into that store (D36), from the State Library's address points and roads files and the FEMA and ORNL building outline file. The site shows them with `--hail-addresses`, a second flag that `main` passes since the owner's approval of 2026-10-28 (D146). Each of these steps is non-fatal: a source that fails marks its layer unavailable, and the rest of the store is published. The job installs `pyproj~=3.8` and `pyogrio~=0.13` (compatible releases) for these steps only; the site build needs neither.

## Build it on your computer

Needs Python 3.10+.
```bash
pip install requests jinja2 pillow numpy pygrib h5py tzdata
python -m website.build --out _site --sample   # invented sample data, labelled on every page
python -m website.build --out _site            # live data
python -m website.build --out _site --sample --hail-history   # the hail history with labelled sample data (off by default; it also carries the B5 weather files)
python -m website.hail build --out store --cache hail-cache  # the daily store from NOAA's archive; a cold cache works
python -m website.hail verify store                          # check a built store
python -m website.build --out _site --hail-history --hail-store hail-store.tar.gz   # a local store instead of the download
python -m website.build --out _site --storm-layers   # the radar echo tops, the GOES picture and the MRMS hail swath layers (behind the flag; on main since D146)
pip install pyshp                                                # the joins need it; the site build does not
python -m website.joins build --store store --cache joins-cache  # the joins: reports, records, detections, warnings, zone products, station gusts
python -m website.joins verify store                             # check the joins
python -m website.build --out _site --sample --hail-history --hail-addresses   # the address dots, streets and outlines with labelled sample data (D36; off by default, on main)
python -m website.build --out _site --sample --hail-history --hail-addresses --address-text off   # the same with no address text (D35)
pip install pyproj~=3.8 pyogrio~=0.13                   # the job's address, street and outline steps only (compatible releases)
python -m website.addresses build --store store --cache structures   # the address points (job)
python -m website.addresses verify store                 # check them (add --zip FILE to recount from the file)
python -m website.streets build --store store --cache roads --roads-source msl   # the streets (job); --roads-source tiger is the fallback
python -m website.streets verify store --roads-source msl
python -m website.buildings build --store store --cache structures-fema --counties-cache counties   # the outlines and their dots (job)
python -m website.buildings verify store
python -m website.climate backfill --cache climate-cache        # the past weather (D38): the 63 scaled months, once (222 s measured; needs h5py)
python -m website.climate update --cache climate-cache          # then daily: the prelim days and any new scaled month
python -m website.climate build --store store --cache climate-cache
python -m website.stations build --store store --cache b5-cache --scope daily   # station readings; --scope monthly reads the whole union
python -m website.stations verify --store store                      # check the station figures and gates (exit 1 on a failure)
python -m website.snowgrid build --store store --cache b5-cache --offline       # NOHRSC snow analysis; the unit check decides whether it shows
python -m website.gauges build --store store --cache b5-cache                   # NWS flood stages and USGS peaks, within 10 miles
python -m website.terrain build --store store --cache b6-cache/terrain --zooms 5-10   # B6 terrain tiles: 3DEP shading and NLCD land cover tint (the monthly job adds --refresh and --timeout 60)
python -m website.terrain verify --store store                    # check the terrain tiles and re-fetch a sample (exit 1 on a failure)
python -m website.basemap2 build --store store --cache b6-cache/basemap2   # B6 base map vectors: reservations, forests, parks, water, places, peaks (bands A to D)
python -m website.basemap2 verify --store store                   # check the vectors and their budgets
python -m website.landmarks build --store store --cache b6-cache/landmarks   # B6 landmark points per tile (schools, hospitals, airports, fire and EMS stations, parks)
python -m website.landmarks verify --store store                  # check the landmark files
python -m website.history_layers build --store store --cache b6-cache/zone-outlines   # B6 five-year pictures, zone counts, recent radar cells, zone outlines
python -m website.history_layers verify --store store              # check the files and recount a sample
python -m website.labels build --store store                       # B6 value bubble anchors on the building outlines, zooms 17 and 18 (after the outline step)
python -m website.labels verify --store store --sample 40          # recompute a sample of shards
python -m http.server -d _site 8000            # open http://localhost:8000
python -m unittest tests.test_site tests.test_gridded tests.test_basemap tests.test_storm tests.test_satellite tests.test_hail tests.test_joins tests.test_addresses tests.test_streets tests.test_buildings tests.test_swath tests.test_climate tests.test_stations tests.test_snowgrid tests.test_gauges tests.test_summary tests.test_words_rules tests.test_hail_workflow tests.test_website_workflow tests.test_terrain tests.test_basemap2 tests.test_landmarks tests.test_history_layers tests.test_labels   # website tests, offline
python tools/smoke_map.py _site                # the built map in Chromium (needs playwright)
python tools/smoke_map.py _site --history --store store   # the sheet's summary words read from a store folder or hail-store.tar.gz (the build passed --hail-history)
python tools/smoke_pages.py _site              # no page wider than the screen, 288–1440 px
```

## Website files
```
website/sources.py     NWS and SPC requests, parsers, flag limits, feed contracts
website/gridded.py     NOAA radar (MRMS) and HRRR model grids → map picture frames
website/storm.py       NOAA radar echo tops for each town (behind --storm-layers, text only)
website/satellite.py   NOAA GOES band 13 satellite picture → one map frame (behind --storm-layers)
website/swath.py        NOAA MRMS hail swath, last hour and last 24 hours → two map layers and per-tile live files (behind --storm-layers; a radar estimate, not observed hail)
website/hail.py        the hail history (behind --hail-history): grid, size classes and words, store readers, daily build
website/joins.py       the hail history joins (behind --hail-history): reports, official records, radar detections, warnings, zone products, station gusts; B5 adds the county path, the period rule and the per-tile event files
website/addresses.py   the address points (behind --hail-addresses): the State Library file read as a stream, the dots, the search index, verify (job only; pyproj)
website/streets.py     the street lines (behind --hail-addresses): the State Library roads (default) or the Census roads (fallback); job only
website/buildings.py   the building outlines (behind --hail-addresses): one dot per outline, the address join, verify (job only; pyogrio)
website/climate.py     the past weather (B5, D38): NOAA nClimGrid daily rain, highs and lows per 1/24 degree cell (grid estimates); the backfill once, the daily update, the release archive
website/stations.py    GHCN-Daily station readings (B5): the station rule (40 miles, 80 and 95 percent coverage), the pool of stations in Montana and the neighbouring states (D62), the tile lists with their rejected candidates (D61 to D69), season totals and season highs and lows
website/snowgrid.py    NOHRSC season snowfall (B5): the unit check; the analysis stays out unless the check passes
website/gauges.py      NWS flood stages and USGS annual peaks (B5): the nearest gauge within 10 miles
website/summary.py     the five-season table that leads the sheet and the roof lines (B5); every word is Python's
website/terrain.py        B6: the terrain tiles for the map, 3DEP hillshade and NLCD land cover tint, zooms 5 to 10 (grey JPEG and palette PNG tiles)
website/basemap2.py       B6: the base map vectors: reservations, forests, parks, lakes and rivers with names, places, summit names (bands A to D)
website/landmarks.py      B6: landmark points per tile: schools, hospitals, airports, fire and EMS stations, parks (places of worship held)
website/history_layers.py B6: the five-year hail and heat pictures, the zone counts (eight measures), the recent radar hail cells and the zone outlines
website/labels.py         B6: the value bubble anchors on the building outlines at zooms 17 and 18 (the cluster rule)
website/data/hail-fixture/ a labelled SAMPLE store for --sample builds and tests
website/build.py       collect every source → map frames and data/map.json → pages (Jinja) → _site/
website/sample.py      invented, labelled sample data for design checks and tests
website/towns.json     the 17 towns, with each map label's side and each town's min_zoom
website/templates/     base, Now, town, Storm reports, About
website/static/        style.css (tokens and look), Leaflet 1.9.4, Atkinson Hyperlegible fonts, icons
website/static/map/    map.js and map.css (the interactive map), basemap.json (outlines and names)
tools/build_basemap.py rebuilds basemap.json from Natural Earth and Census data (run by hand)
.github/workflows/hail-store.yml  the daily hail store job (12:43 UTC): build, join, add the B5 weather parts (non-fatal steps with timeouts) and verify them, build and check the address, street and outline steps (non-fatal), pack and publish the release assets; the monthly job runs in its own job on the first of the month or by input, and the once-only backfill by input (D26, D36, D38, D42)
tests/                 test_site.py (pages, failures), test_gridded.py (radar and model frames),
                       test_basemap.py (the outline file), test_basemap2.py (the base map vectors),
                       test_terrain.py (the terrain tiles), test_landmarks.py (the landmark points),
                       test_labels.py (the value bubble anchors), test_history_layers.py (the five-year
                       pictures and zone counts), test_storm.py (radar echo tops),
                       test_satellite.py (the GOES satellite picture), test_hail.py (the hail history store),
                       test_hail_workflow.py (the hail store job's workflow file), test_joins.py (the hail
                       history joins), test_addresses.py (the address dots and search), test_streets.py
                       (the street lines), test_buildings.py (the outlines and the join), test_swath.py (the
                       MRMS hail swath layers), test_climate.py (the grid), test_stations.py (the station rule),
                       test_snowgrid.py (the snow analysis), test_gauges.py (river gauges), test_summary.py
                       (the summary table and its words), test_words_rules.py (the word rules the tests
                       share), test_website_workflow.py (the workflow file)
```
