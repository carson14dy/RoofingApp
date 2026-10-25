# RoofingApp

Weather for a Montana roofing company: **Montana Hail Watch**.

**The product is a website** (decision D27, 2026-10-14). It shows official NWS warnings, a radar
and warning map, the next 12 hours for 17 Montana towns, a 24-hour and 7-day page per town, and
three days of SPC hail and wind reports. It also shows a five-year history of radar-estimated hail for any spot in Montana (D34; public at the owner's decision of 2026-10-21). GitHub is asked to rebuild it every 10 minutes from public data (its schedule ran 6 times in the 24 hours to 2026-10-21 23:00 UTC; the timer decision is open in the roadmap) and
publishes it with GitHub Pages at **https://carson14dy.github.io/RoofingApp/** once Pages is
turned on. Nothing to install: open it on any phone or computer.

The earlier desktop app is **parked**, not deleted. It is described in the second half of this
file.

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

The parked desktop app

7. [Bottom line](#bottom-line) and the app's sections after it.

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
| Addresses, streets and building outlines (build flag `--hail-addresses`, off on `main`) | On the Map: the street lines, the arterials from zoom 13, the local streets from 15 and the names from 16; from zoom 15 each building outline has one dot, and each address that no outline holds has its own dot. Tap a dot for its address, if one is on file, and the weather history for its cell. A search box, "Find an address", finds a typed address; what is typed stays in the browser | Montana State Library (address points and roads); USA Structures, Oak Ridge National Laboratory and FEMA (building outlines); U.S. Census Bureau (roads, if the fallback is built). The terms are on the About page |
| About | What each part is, the flag limits, what happens when something fails, the data sources in detail | — |

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

The same job always builds the address dots, the street lines, the building outlines and the address search into that store (D36), from the State Library's address points and roads files and the FEMA and ORNL building outline file. The site shows them only with `--hail-addresses`, a second flag that is off on `main`. Each of these steps is non-fatal: a source that fails marks its layer unavailable, and the rest of the store is published. The job installs `pyproj~=3.8` and `pyogrio~=0.13` (compatible releases) for these steps only; the site build needs neither.

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
python -m website.build --out _site --storm-layers   # the radar echo tops, the GOES picture and the MRMS hail swath layers (behind the flag; off on main)
pip install pyshp                                                # the joins need it; the site build does not
python -m website.joins build --store store --cache joins-cache  # the joins: reports, records, detections, warnings, zone products, station gusts
python -m website.joins verify store                             # check the joins
python -m website.build --out _site --sample --hail-history --hail-addresses   # the address dots, streets and outlines with labelled sample data (D36; off by default)
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
python -m http.server -d _site 8000            # open http://localhost:8000
pip install pyyaml                                                  # test-only: the workflow-file tests read YAML (requirements.txt does not list it)
python -m unittest tests.test_site tests.test_gridded tests.test_basemap tests.test_storm tests.test_satellite tests.test_hail tests.test_hail_workflow tests.test_joins tests.test_addresses tests.test_streets tests.test_buildings tests.test_swath tests.test_climate tests.test_stations tests.test_snowgrid tests.test_gauges tests.test_summary tests.test_words_rules tests.test_website_workflow   # website tests, offline
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
                       test_basemap.py (the outline file), test_storm.py (radar echo tops),
                       test_satellite.py (the GOES satellite picture), test_hail.py (the hail history store),
                       test_joins.py (the hail history joins),
                       test_addresses.py (the address dots and search), test_streets.py (the street lines),
                       test_buildings.py (the outlines and the join), test_swath.py (the MRMS hail swath layers),
                       test_climate.py (the grid), test_stations.py
                       (the station rule), test_snowgrid.py (the snow analysis), test_gauges.py (river gauges),
                       test_summary.py (the summary table and its words),
                       test_website_workflow.py
                       (the workflow file)
```

---

# Parked: the desktop app

Everything below describes the desktop app, parked on 2026-10-14 (D27). It still works and its
tests still run. No new version is shipped and no installer is built unless Carson asks.

## Bottom line

| You want to… | Do this |
|---|---|
| Try it now on your computer | `pip install -r requirements.txt` then `python desktop/launcher.py` |
| Turn on automatic updates | Already on — installed copies follow this repo's `main` branch |
| Give crews an installer | GitHub → **Actions → Build desktop installers → Run workflow**, download the Windows/macOS zip |
| Ship a change | `python ship.py "what changed"` — tests it, bumps the version, pushes. Apps update within the hour or on **Check for updates** |

**Two fixes to the earlier web version you should know about:** its radar layer
requested NOAA's WMS layer `3`, which is the *boundary* layer and draws nothing —
the radar is layer `1`. And its map script was inserted without `<script>` tags, so
the map never actually ran in a browser. Both are fixed here and checked in a real
browser and a real desktop window. Its base map (CARTO) also now requires an API
key; this version uses USGS's public-domain maps.

---

## Run it today

Needs Python 3.10+.

```bash
pip install -r requirements.txt
python desktop/launcher.py            # opens the app in its own window
python desktop/launcher.py --browser  # or in your web browser
```

Windows needs the Microsoft Edge **WebView2** runtime (built into Windows 11 and
installed on most Windows 10 PCs). If the window can't open, the app falls back
to your browser automatically.

---

## Set up updates (once)

Already done: installed copies follow **`carson14dy/RoofingApp`, branch `main`**
(`desktop/update_config.json`; installers built by GitHub Actions bake it in too).

- This repo is **public**, so apps need no token — and anyone can read the code and docs. To make it
  private: Settings → General → Change visibility, then create a fine-grained token with
  *Contents: read-only* on this repo and add it as the repository secret `UPDATE_TOKEN` (installers
  carry it; it can only read code the installer already contains) or paste it under
  **App & updates → Update source**.
- The app checks GitHub when it opens and every hour after (unauthenticated GitHub allows 60 checks
  per hour per network; unchanged checks are answered from cache).

---

## Get the installers (once)

PyInstaller can't cross-compile, so GitHub builds them for you:

- **Actions → Build desktop installers → Run workflow** → download
  `MontanaHailWatch-Windows.zip` / `MontanaHailWatch-macOS.zip` from the run, **or**
- push a tag `desktop-v1.1.0` to also publish a GitHub Release with both attached.

Both builds run the app's self-test *inside the built app* before packaging.

**First launch warnings (the apps aren't code-signed):**
- *Windows:* SmartScreen → **More info → Run anyway**. Unzip anywhere and run `MontanaHailWatch.exe`.
- *macOS:* right-click the app → **Open**, or System Settings → Privacy & Security → **Open Anyway**.
  The default runner builds for Apple Silicon Macs.

Linux: run from source, or `python build.py` on a Linux machine.

---

## Ship an update (every time)

```bash
python ship.py "Fixed the alert list order"          # 1.0.0 -> 1.0.1
python ship.py "Added territory reports" --minor     # -> 1.1.0
```

`ship.py` stops at the first problem: it runs the same self-test installed apps
run, runs the full test suite, bumps `payload/manifest.json`, commits and pushes.
Pushing without changing the version ships nothing — that's deliberate, so
work-in-progress commits never reach crews.

Claude Code or ChatGPT can make the change: `AGENTS.md` tells them how to test and ship.
Work happens on a branch with a pull request; merging a version bump to `main` ships it.

---

## What updates itself vs. what needs a new installer

| Change | Ships by itself? |
|---|---|
| Anything in `payload/` — screens, wording, rules, feeds, maps, database additions | **Yes** — bump the version and push |
| New Python package (e.g. `shapely`) | **No** — rebuild installers; raise `min_shell` in the manifest and `SHELL_API` in `desktop/launcher.py` |
| Anything in `desktop/` (window, updater, notifications) | **No** — rebuild installers |

If you push a version that needs a newer installer, apps show **“A new desktop
installer is needed”** with a download link instead of breaking.

---

## How updates stay safe

1. **Checked:** the app reads `payload/manifest.json` at the newest commit; it only
   considers a strictly higher version.
2. **Tested before install:** it downloads that exact commit, then runs the new
   version against a *copy* of your real database and opens every page listed in
   the manifest. Any error (syntax, missing package, template, migration) → rejected
   and skipped, with the reason under **App & updates**.
3. **Installed with a backup:** the database is backed up before every install
   (and daily; newest 14 kept). Each version lives in its own folder and is never
   edited in place.
4. **Swapped live:** **Update now** switches versions instantly — no restart. Or it
   installs the next time the app opens.
5. **Rolled back automatically** if a version fails to start; **manually** from
   **App & updates** or the window menu. A rolled-back version is skipped until a
   newer number ships.
6. **Recovery screen:** if a page crashes, you get a one-click roll back instead of
   an error page.

Database rule for app code: only *add* migrations at the end of
`payload/store.py → MIGRATIONS`; never edit shipped ones.

---

## Data feeds: live, demo, needs a subscription

Verified working 2026-10-11. The **Data sources** screen shows each feed's
status, data time and last check, plus the full feed contracts (units, timing,
cadence, missing-value rules).

| Feed | Status | Notes |
|---|---|---|
| NWS official alerts (Montana) | **Live** | Every 60 s in the background. Matched by warning polygon, otherwise by the place's NWS forecast zone / county / fire zone. Updates and cancellations reconciled; kept on screen through outages; backfilled after a gap. |
| NWS forecasts per job (hourly, gridpoint gusts/rain/WBGT, 7-day) | **Live** | Fetched when Crew Outlook opens; NWS caching honored. |
| NOAA NEXRAD radar mosaic | **Live** | WMS layer `1`; frame valid time shown separately from retrieval time. Precipitation echoes, not hail size. |
| SPC preliminary hail & wind reports | **Live** | 12:00–11:59 UTC reporting days; `175` = 1.75″; `UNK` wind stays unknown. |
| Address / city / ZIP search | **Live** | U.S. Census geocoder (addresses), OpenStreetMap (cities, ZIPs). |
| Base map | **Live** | USGS The National Map (public domain). |
| Estimated hail footprint | **Demo** (off by default) | Fictional shapes, shown only under “Demo event” and labelled Demo everywhere. A GeoJSON slot is ready for a real source. |
| MRMS MESH estimated hail | Not connected | Free, but published as GRIB2 grids — needs a processing job, then point the GeoJSON setting at it. |
| SPC outlooks (Conditional Intensity), ProbSevere v3, LightningCast | Trial candidates | Listed, not built — per the review, evaluate first. |
| Xweather, The Weather Company HailZone, Verisk, Cotality | Needs subscription | Trial shortlist, not a ranking. No accounts or purchases made. |
| NOAA NCEI Storm Events | Not connected | Historical context, later. |

---

## The screens

- **Live Storms (home)** — in the review's order: active alerts (who each applies to,
  and how it was matched), today's jobs needing review, tomorrow's scheduling
  conflicts, inspection candidates, storm matches. Map layers and data freshness
  sit behind a details panel. Search an address or ZIP and save it as a job or
  property. Draw a territory or a crew-observed hail area. Log crew inspection
  findings (kept separate from weather data).
- **Storm History** — pick an SPC reporting day; see reports on a map and table;
  every property gets a tier and the reasons in words; add selected ones as
  inspection candidates. No reports ≠ no hail, and it says so.
- **Inspections** — candidates with status (not contacted → scheduled → inspected →
  completed), assigned rep, notes, the evidence captured at the time, a printable
  exposure summary, and CSV export. Never “confirmed damage.”
- **Crew Outlook** — per job: phase, roof system and exact product, work hours and
  time to dry-in, required site checks, and job-specific limits on top of company
  rules. Hourly status (“Forecast meets configured conditions” / “Weather review
  needed” / “Data unavailable”) with the reasons, whether a long-enough window
  exists, forecast WBGT and heat index, rain amounts, 7-day view, supervisor review
  and crew acknowledgement.
- **Places** — jobs, properties, territories, and each place's NWS zones.
- **Data sources** — feed status, trial candidates, settings, feed contracts.
- **App & updates** — version, update status, update source, roll back, data folder.

The only hand-written JavaScript is a ~20-line bridge (in `live.html`) that passes
map clicks and drawn shapes to Python and refreshes radar tiles. Everything else
is Python (Flask, Folium, SQLite).

---

## Your data and backups

| OS | Data folder |
|---|---|
| Windows | `%LOCALAPPDATA%\MontanaHailWatch` |
| macOS | `~/Library/Application Support/MontanaHailWatch` |
| Linux | `~/.local/share/MontanaHailWatch` |

Inside: `hailwatch.db` (your data), `backups/`, `versions/`, `logs/hailwatch.log`,
`settings.json`. **App & updates → Open data folder** opens it.

**Bringing data from the earlier web version:** quit the app, copy that version's
`hailwatch.db` into the data folder, start the app. It upgrades the file in place
(old reports become crew inspection findings; old outlines become crew-observed areas).

---

## Handoff and review status

**Independent review P0s (before any production claim):**
- Alert geography — polygon, else county / forecast zone / fire zone; missing
  polygon is never “no alert”; can't-tell is shown as can't-tell. Tested.
- Lifecycle — updates, cancellations, out-of-order delivery, duplicates, outages,
  history backfill after a gap. 240 generated scenarios + a busy-day replay with a
  30-minute outage. Tested.
- “Better forecasting” claim — **not made.** Evaluation (company practice + NWS vs.
  deterministic job rules vs. extra feeds) is the next step; the app already keeps
  decision-time records to support it (candidate evidence snapshots, outlook
  change log, supervisor reviews with the outlook at the time).

**Handoff acceptance checks** (all automated in `tests/`): 175 → 1.75 in; unknown
wind stays unknown; UTC/local midnight and daylight-saving dates; warning
update/cancel reconciliation; feed failures show stale/unavailable; estimates and
reports stay distinct; no report is not an all-clear; repeated ingestion makes no
duplicate candidates or notifications; no “confirmed damage” wording; exports keep
sources, legend and timestamps; demo data never shown as live.

**Not done yet:** advanced guidance feeds and vendor trials (shadow mode first),
the evaluation harness with held-out storm days, phone notifications, the MRMS
processing job, NCEI history, release-gate load tests at regional scale.

---

## Tests

```bash
python desktop/launcher.py --selftest payload   # what installed apps run before accepting an update
python -m unittest discover -s tests -v          # about 2,000 tests, offline, about 7 minutes
```

- `tests/test_weather.py` — handoff acceptance checks, alert geography, outlook rules, targeting, exports, wording.
- `tests/test_alert_scenarios.py` — 240 geography × lifecycle × message-order scenarios; outage replay with backfill.
- `tests/test_updates.py` — the whole update channel against a fake GitHub: apply without restart, broken
  update rejected, needs-new-installer, startup failure rolled back, manual rollback and skip, rate limit,
  private repo token, unchanged-check caching, zip path traversal, the local server's key/host checks and recovery page.

GitHub runs both on every push (**Actions → Check the app**).

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Radar is empty | Clear skies — no echoes to draw. **Data sources** shows the radar frame time; if it says stale/unavailable, NOAA's service is down. |
| “Update check failed” | Read the message under **App & updates**: offline, GitHub's hourly limit (add a token), wrong repo name, or a private repo without a token. |
| An update was “skipped” | It failed its self-test on your data; the reason is in the update history. Fix, bump the version, ship again. |
| Window doesn't open (Windows) | Install Microsoft Edge WebView2 Runtime; meanwhile the app opens in your browser. |
| “This page only opens inside the app” | You opened the local address in a browser tab. Use the app window. |
| Anything else | `logs/hailwatch.log` in the data folder. |

---

## Security notes

- The app runs a private local server bound to `127.0.0.1`. Each launch creates a
  one-time key that only the app's window receives; other programs and websites
  get “403”. Requests with a wrong host name are refused.
- Updates are trusted from your GitHub repo — protect that account with two-factor
  sign-in. Downloads are checked for path tricks and size before anything is installed.
- A token entered under **Update source** is stored in `settings.json` in your data folder.
- Desktop notifications pass text through environment variables, never through a shell command line.

---

## Known limits

- Windows and macOS builds are produced by GitHub Actions and haven't been run on
  a real Windows PC or Mac yet; desktop notifications on those systems are untested.
  The Linux build, the native window (Qt), and a full update cycle inside the frozen app were tested.
- Unsigned installers trigger the first-launch warnings above.
- Real hail-size footprints need MRMS processing or a licensed provider.
- Alerts reach you through the desktop app while it's open; there's no phone delivery yet.
- Address precision is not weather precision: reports are points, grids are ~1–2.5 km, and nothing here measures a specific roof.

---

## Renaming

To rename: grep for `Hail Watch` and `HailWatch` and change every hit — templates (header, titles,
summary footer, App & updates line), `payload/manifest.json` `name`, `payload/app.py`,
`desktop/launcher.py`, `desktop/updater.py`, `build.py`, the build workflow and this file. Payload
changes ship; shell and build changes need a new installer. Changing `APP_ID` (in
`desktop/launcher.py`, `build.py` and the workflow paths) moves the data folder and renames the
installer, so leave it unless you're starting fresh; the 2026-10-12 rename to Montana Hail Watch
did change it before any copies were installed (D26).

---

## Project layout

```
AGENTS.md                rules for AI agents (ChatGPT/Codex read it; CLAUDE.md imports it for Claude Code)
docs/handoff/            the weather module spec and the independent review
docs/DECISIONS.md        why things are built this way, bugs already fixed
docs/ROADMAP.md          status, next steps, open questions
payload/                 ← the app; updates itself from GitHub
  manifest.json          version, min_shell, release notes, self-test pages
  app.py                 screens and routes (Flask)
  weather.py             feed adapters, evidence model, alert matching, rules, targeting, feed contracts
  store.py               SQLite schema (append-only migrations)
  maps.py                Folium maps and the printable exposure map
  templates/             pages
  fixtures/              the fictional demo hail footprint
desktop/                 ← the desktop app shell; changes only with a new installer
  launcher.py            window, local server, menu, notifications, recovery screen
  updater.py             GitHub checks, self-test, install, backups, rollback
  update_config.json     default update source (filled in by the GitHub build)
tests/                   acceptance, alert scenarios, update channel
assets/                  app icons
build.py                 builds the installer folder (PyInstaller)
ship.py                  test → bump version → commit → push
.github/workflows/       Check the app (every push) · Build desktop installers
```
