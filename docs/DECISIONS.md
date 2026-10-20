# Decisions

**Publication repair (2026-10-16).** PR #3 merged, but its first deployment failed because
Pages was not enabled. The plan step had suppressed the GitHub CLI failure and mistaken its
404 JSON body for a site URL. Publishing now requires both a successful lookup and an HTTPS
URL; failed/invalid lookups warn with the Pages setup step, keep push builds as previews, and
skip scheduled builds. Regression tests execute the actual planning shell against fake CLI
responses. Enabling Pages still requires Settings → Pages → Source: GitHub Actions; the
repair environment's Pages API request returned Forbidden, so no settings were changed.

Why RoofingApp is built the way it is. Add new entries at the bottom; to reverse a decision, add
an entry that names the one it replaces. Web-version decisions date from September 2026; the
desktop app and weather module from 2026-10-11 (version 1.0.0).

## Architecture

**D1 · Python only (2026-09).** Flask + Jinja + Folium (Leaflet generated from Python) + SQLite +
requests, served by waitress. JavaScript only where the browser alone can do it, documented
inline; today one ~20-line bridge in `templates/live.html` (map click → form fields, drawn
shape → form submit, radar tile refresh every 4 minutes).
*Why:* the owner's requirement after the first HTML/JS version: a clean Python rebuild, not a hybrid.

**D2 · Desktop app = native window on a private local server (2026-10-11).** pywebview opens a
native window (WebView2 on Windows, WKWebView on macOS, Qt/GTK on Linux) onto a waitress server
bound to `127.0.0.1` on a random port. Each launch makes a one-time key; the window receives it
via `/__auth?k=…` as the HttpOnly, SameSite=Strict cookie `hw_session`. Requests without it get
403; a wrong `Host` header is refused. Falls back to the default browser if no window can open.
*Why:* keeps the Flask/Folium app unchanged and Python-only; the key and host check stop other
programs and web pages (DNS rebinding) from using the local server.

**D3 · Shell and payload are separate; the payload updates itself from GitHub (2026-10-11).**
`desktop/` changes only with a new installer. `payload/` ships when `version` in
`payload/manifest.json` increases on `main`. The shell declares `SHELL_API` (1); the payload
declares `min_shell`. A payload that needs a newer shell shows “A new desktop installer is
needed” with a download link instead of breaking.
*Why:* the owner asked to update the app without downloading another zip. The version gate keeps
work-in-progress commits away from crews.

**D4 · Update safety (2026-10-11).** The app downloads the exact commit it checked, loads that
payload in-process against a *copy* of the user's database with network off, and opens every
page in the manifest's `selftest` list. Any error rejects the version and shows why (e.g. a
missing package). Versions live in immutable `versions/<ver>/` folders. The database is backed up
before each install and daily (newest 14 kept). A version that fails at startup is rolled back
automatically; a manual rollback marks it bad (skipped until a higher version ships). A server
error shows a recovery page with a rollback button. Downloads are capped at 50 MB and checked
for path traversal, symlinks and file count.
*Why:* one bad push must not break every crew's app.

**D5 · Updates apply without a restart (2026-10-11).** A WSGI dispatcher points at the active Flask
app; “Update now” swaps it. Each version is imported as its own package (unique module name,
relative imports). The old app's background thread stops through `app.extensions["hailwatch.stop"]`.

**D6 · GitHub calls (2026-10-11).** `GET /repos/{repo}/commits/{branch}` with
`Accept: application/vnd.github.sha` and an ETag (unchanged → 304); the manifest from the contents
API at that SHA (`application/vnd.github.raw+json`); the zipball of that SHA. Checks at launch and
hourly. Public repo: no token. Private repo: a read-only token (`UPDATE_TOKEN` secret baked into
installers, or pasted into the app). Verified 2026-10-11 against this repo on github.com (branch
`claude/desktop-app`, local copy pinned to 0.9.9): found 1.0.0 → downloaded → self-tested →
applied live → next check “up to date”.

## Data and maps

**D7 · Radar = NOAA `radar_base_reflectivity` WMS, layer `1` (2026-10-11; corrects the web
version).** The web version requested layer `3`, which is “Boundary” and draws nothing. Verified
by fetching a tile and checking its pixels (≈48% colored over Montana at the time). The frame's
valid time comes from MapServer layer 2 (`idp_validtime`) and is shown apart from retrieval time.
Tiles refresh via a `cachebust` parameter (Folium camelizes `_t` to `T`).
*Lesson:* HTTP 200 is not proof: check the content.

**D8 · Folium's map script must be wrapped in `<script>` (2026-10-11; corrects the web version).**
The script part of Folium's render has no tags; the web version inserted it bare, so the map never
ran. HTML string tests missed it; a real browser caught it. UI checks now use a real browser.

**D9 · Base map = USGS The National Map (2026-10-11).** CARTO tiles now return “API KEY REQUIRED”.
USGS topo and imagery are public domain; dark mode is a CSS invert on the tile layer
(`hw-dark-base`); max native zoom 16. Folium's injected Bootstrap is removed (it fought the
app's styles).

**D10 · Alert applicability: review P0 (2026-10-11).** Poll `/alerts/active?area=MT` every 60 s.
An alert applies to a place when its polygon contains the place; otherwise when its UGC codes
include the place's NWS forecast zone, county or fire zone (looked up once from
`/points/{lat},{lon}` and stored). Unknown codes show “Can't tell yet”, never “no alert”.
Territories match by polygon or by zone geometry from `/zones/…`. When checked, all 19 active
Montana alerts had null geometry; polygon-only matching would have missed every one.

**D11 · Alert lifecycle: review P0 (2026-10-11).** Two-pass reconcile: Cancel messages and
`references` mark earlier messages cancelled or updated whatever order they arrive in; references
not yet seen become placeholders. Alerts never clear after a failed request. After a gap over
150 s the app backfills from `/alerts?area=MT&start=…` (up to 5 pages), so warnings issued during
an outage still produce matches. Notifications dedupe on `alert:{id}:{place|territory}` and
`spc:{record}:place:{id}:rule{size}/{radius}`. Tested with 240 scenarios and a busy-day replay
with a 30-minute outage.

**D12 · Evidence model and demo policy (2026-10-11).** From the handoff's `WeatherEvidence`: kinds
forecast, radar_estimate, point_report, station_observation, official_alert, inspection: never
merged; statuses preliminary, active, updated, expired, cancelled, archived. Every feed shows
Live, Stale, Unavailable, Demo, Not connected, Off, Needs subscription or On demand. Freshness
limits: radar 15 min, alerts 10 min, SPC 60 min, forecast 12 h, footprint 6 h. The hail footprint
source is off by default; the demo footprint (fictional ellipses near west Billings) appears only
under “Demo event”, labelled DEMO. A failed live feed never falls back to demo data.

**D13 · SPC reports (2026-10-11).** `YYMMDD_rpts_[filtered_]{hail|wind}.csv`. Reporting day =
12:00–11:59 UTC. Size in hundredths of an inch (175 → 1.75″). Wind in mph; `UNK` stays unknown.
Duplicates within a day are dropped. Filtered (default) or raw files are selectable.

**D14 · Geocoding (2026-10-11).** Census geocoder for street addresses (it doesn't resolve cities or
ZIPs); OpenStreetMap Nominatim as the fallback, at most 1 request/s with an identifying
User-Agent. Address precision is not weather precision.

**D15 · NWS forecast units (2026-10-11).** Gridpoint `windGust` is km/h, QPF is mm, WBGT and heat
index are °C; hourly wind text is mph. Converted at the adapter, raw units kept in the feed contract.

## Product rules

**D16 · Crew Outlook (2026-10-11).** Company default limits plus per-job overrides, field by field;
thresholds are never copied between products. Each hour is “Forecast meets configured
conditions”, “Weather review needed” or “Data unavailable”, with reasons; missing critical data is
never an all-clear, and “meets” is not shown green. A phase fits when an uninterrupted window
covers job duration plus dry-in time. WBGT and heat index are both shown as NWS forecast values;
the WBGT limit is optional and tied to the company's heat procedure; no generated work/rest
schedules. Supervisor reviews and crew acknowledgements store the outlook as it was. Defaults
(wind 20 mph, gust 25 mph, precipitation 30%, 40–95 °F, daylight only) are placeholders until
the company sets real rules.

**D17 · Inspection targeting (2026-10-11).** Tiers are company targeting choices, not damage
thresholds. Defaults: Tier 1 = report ≥1.75″ within 1 mi; Tier 2 = ≥1.0″ within 3 mi; search
radius 5 mi. Reasons in words. Candidates upsert idempotently (one per place per event) with an
evidence snapshot; statuses not contacted → scheduled → inspected → completed. Exports carry
“Weather exposure does not confirm roof damage. This is an internal summary, not certified weather
evidence.” No damage probability, insurance language or “confirmed damage”.

**D18 · Notifications (2026-10-11).** Every match becomes an in-app notice; OS notifications by
default only for severe items (convective warnings, hail reports). Text reaches PowerShell,
osascript and notify-send through environment variables, never a command line. No AI-generated
text anywhere in the alert path.

**D19 · Home screen and design (2026-10-11).** Order from the review: active warnings → today's jobs
needing review → tomorrow's scheduling conflicts → inspection candidates → storm matches; map
layers and freshness behind “details”. Kept the existing dark “storm” design rather than the
handoff's suggested off-white/navy/teal; the handoff says to adapt to the existing design system.
The handoff's two images were not provided; synthetic images are never evidence. Place names show
on hover so labels don't overlap.

**D20 · Storage (2026-10-11).** One SQLite file per computer in the user data folder; timestamps in
UTC; append-only migrations (`MIGRATIONS[0]` = web-version schema, `[1]` = places, territories,
candidates, alerts, notices, reviews, acknowledgements, outlook log, settings). Web-version
databases upgrade in place: old reports → crew inspection findings, old outlines → crew-observed
areas. Alerts are pruned after 30 days.

**D21 · No “best” claims; providers are candidates (2026-10-11).** Per the review. SPC Conditional
Intensity Groups, ProbSevere v3, LightningCast, Xweather (including `/hail/archive`), The Weather
Company HailZone, Verisk and Cotality are listed under Data sources as trial candidates, not
integrated, not ranked.

**D22 · Repo and agents (2026-10-11).** Code lives in `carson14dy/RoofingApp` (public). `AGENTS.md`
holds the shared agent rules (read directly by ChatGPT/Codex); `CLAUDE.md` imports it with
`@AGENTS.md` for Claude Code. Work happens on branches with pull requests; CI (“Check the app”)
runs the self-test and tests on every pull request and every push to `main`.

**D23 · ChatGPT's Kansas City pilot branch: what carries over (2026-10-11).** Branch
`codex/kansas-city-weather-pilot` (one commit, 53 files, 1.5 MB) was written from the initial commit
without the app, `AGENTS.md` or these docs. It holds a standard-library NWS point prototype for
downtown Kansas City (Python server, 37 lines of minified JavaScript, vendored Leaflet, light theme,
no session key); research notes on four ChatGPT weather plugins (AccuWeather, Weather by WindBorne,
Zoom Radar Weather, Tomorrow.io) in which every documentation request was blocked and nothing was
verified; and `skills/roofing-radar-reading`, a procedure for a language model to interpret radar,
with a synthetic metadata checker. Its 18 prototype tests and 35 checker tests pass. Its evidence
rules agree with D10–D12 and D16–D17.

Carried over (roadmap items, not merged code):
- **Nearby station observations.** The `station_observation` evidence kind (D12) has no feed; the
  prototype shows the value: the nearest NWS stations with distance, observation time and age. When
  built: `/stations/{id}/observations/latest`, the native MADIS `qualityControl` flag shown beside
  each value; `X` (rejected) withheld and kept raw; `V` (verified), `S` (screened), `C` (coarse pass)
  and `Z` (no QC yet) shown with their flag, not hidden. The prototype hides everything but `V`,
  which left wind “Unavailable” at the downtown airport in its own screenshot.
- **NWS facts** from documentation ChatGPT retrieved (API, alerts and geolocation guide): `/points`
  accepts four decimals (≤ 7 m quantization; disclose it); forecast grids are ~2.5 km; observations
  can lag ~20 min behind MADIS QC; poll alerts no more often than every 30 s; `/alerts` history is
  ~7 days; `/radar` routes return status, not imagery; PoP is the chance of ≥ 0.01 in of liquid in
  the period. The app's 60 s alert poll and D7 radar source comply.
- **Chat-plugin access is not app access.** A ChatGPT plugin subscription grants no server API,
  bulk queries, storage or redistribution rights. The four providers join D21's candidate list as
  unverified.
- **Test cases** to port with station observations: adjacent roofs sharing a grid cell; nearest
  station across terrain; a 20-minute-old observation beside a forecast valid now; a stale local
  tile under a fresh mosaic header.

Not carried over, and why:
- The TypeScript/Next.js/MapLibre/PostGIS service design (D1). The branch's own stdlib server shows
  the Python path works.
- The prototype as a second app. It duplicates the point lookup, hourly forecast and point-alert
  code in `weather.py` (`outlook()` already calls `/alerts/active?point=`), uses undocumented
  minified JavaScript (rule 4), has no session key or Host check (D2), and shows alert times in UTC
  beside local times. Its “Saved history” tab is query snapshots, not storm history.
- 1.3 MB of response captures, a screenshot and vendored Leaflet in git. Folium bundles Leaflet;
  every installed app downloads the repo zipball on each update (D6), so research artifacts cost
  every crew machine bandwidth without reaching the payload.
- The radar-reading skill inside the app: rule 6 and the release gate (≥ 500 adversarial AI
  summaries before any AI text). It stays an agent-side reference; its content mostly restates
  D10–D17 at five times the length.
- Replacing the repo README with a Kansas City section (`.gitignore` can be unioned). Statements in
  the skill docs that `api.weather.gov` was blocked, and ChatGPT sandbox paths
  (`/workspace/live-map-evidence`, `/tmp/roofing-wind-sources`), are stale.

*Resolved by D24:* Kansas City was a first draft; the targets are all of Montana, then the
contiguous US.

**D24 · Scope: all of Montana now, the contiguous US next (2026-10-11).** Carson: Kansas City was a
first draft; the targets are the entire state of Montana, then the entire contiguous US.

*Montana.* Already the app's scope: alerts poll `area=MT`, SPC reports filter to Montana plus a
0.75° border margin, the map opens on Montana, and forecasts, radar, geocoding and time zones are
per place. Nothing to build; what remains is roadmap 1–3 (installers on real machines, the pilot,
the baseline). Two limits to watch in the pilot: far from the four Montana radar sites (Billings,
Glasgow, Great Falls, Missoula) the beam overshoots low levels, so no echo must keep showing as no
data, never as clear; and a place just across the border carries Idaho, Wyoming or Dakota zone
codes, which a Montana-only poll can never match; the change below fixes that too.

*Contiguous US.* Poll alerts for the states where there is work, not the national feed:
- Alert areas = the state prefixes of saved places' NWS zone/county codes (`MTZ056` → `MT`), plus
  every state whose bounding box (with margin) touches a territory, plus the company state. One
  request, `area=MT,WY,…`; the same list for the outage backfill. Over-including a neighbour is
  harmless; a missing state is the failure. Before building (rule 7): confirm live that `area`
  takes a comma list and measure the national `/alerts/active` response, so a list past a measured
  size can fall back to the national feed at a longer interval (NWS asks for ≥ 30 s between polls).
- SPC filter: a "near my places" box (places and territories plus margin) replaces the Montana box;
  "all" stays.
- The map opens on the places' bounding box, else the company location, else the contiguous US.
- The "outside Montana" finding warning becomes "far from any saved place"; "No active NWS alerts
  for Montana" and "Montana + border" lose the state name; the tagline follows the product-name
  decision. `weather.CONTRACTS` and `COVERAGE` text updated with the code.
- Tests: a multi-state poll, a border place with out-of-state codes, a national-size replay (the
  3× load gate). The 240 Montana scenarios stay as they are.
- Out of scope: Alaska, Hawaii and the territories. The radar mosaic and SPC files are built for
  the contiguous US.
*Why:* every crew machine polling every state every 60 s is the national feed; polling the states
with places and territories is small, matches how alerts are matched anyway, and reaches a new
market the moment a place is saved there. *When:* its own small PR after PR #1 merges and the
installers are on real machines; before the pilot adds border places.

*Resolved by D26:* the tagline is “Storm-to-roof” now; the contiguous-US PR leaves it alone.

**D25 · ChatGPT's Montana pilot branch: findings that change the plan (2026-10-11).** Branch
`codex/montana-weather-pilot` extends the Kansas City prototype to Montana (territory selector, 13
town pins, station and grid elevation shown, time-zone fallback) and merges `main`, so it was written
with the app and these docs in view. It merges cleanly and touches nothing outside `research/` and
`skills/`; it would take the repo from 0.75 MB to 2.9 MB. Its 21 backend tests and 35 checker tests
pass here. Its 16-point live sweep (13 towns plus rural, divide and border points) resolved all four
Montana offices (BYZ, MSO, TFX, GGW) and America/Denver everywhere. D23's verdict stands: the
prototype stays a research branch; the evidence below changes the plan.

What the sweep showed, and what it changes:
- **Station observations are hourly, so a 30-minute freshness limit fails most of Montana.** At
  1:32 pm MDT, 35 of 48 station records were older than 30 minutes; four towns (Lewistown, Glasgow,
  West Yellowstone, the rural eastern point) had no station inside the limit. The fresh ones were
  airport ASOS stations reporting at about :55 each hour; the stale ones were RAWS and road-weather
  sites reporting hourly or less, and even the Glasgow airport was past the limit. Roadmap item 5
  uses a "current" limit of about 75 minutes (one hourly cycle plus the documented ingest delay),
  always shows the age, and shows stale values as stale; never hidden.
- **A missing gust usually means no gust to report, not a broken sensor.** Airport stations report
  a gust only when the peak exceeds the sustained wind by a reporting threshold; nine of the ten
  airports in the sweep returned a null gust beside a valid wind. Item 5 shows "no gust reported"
  beside the sustained wind, and "unavailable" only when the whole observation is missing.
- **Hiding non-V values hides real wind.** Arrow Creek Hill on I-90 reported a 30.6 km/h gust
  flagged S (screened); the prototype withheld it as "QC review needed". Item 5 shows the value
  with its flag (confirms D23).
- **Elevation belongs beside each station.** Billings airport sits at 1,088 m and Arrow Creek Hill
  at 1,196 m; in Montana a valley airport can misrepresent a bench or a pass. Item 5 shows station
  elevation and the forecast-grid elevation, and marks the job's own elevation unknown unless the
  job records it.
- **The nearest stations cross state lines.** West Yellowstone's three nearest stations are all in
  Wyoming (Old Faithful 30 km, Yellowstone Lake 48 km). Station lists are never filtered by state;
  D24's alert areas come from zone codes, not station lists.
- **Units.** The prototype shows °C and km/h; the app keeps D15: °F and mph for display, native
  units in the record.
- **Validation strata for the pilot (roadmap 2–3).** ChatGPT's matrix is a sound site plan:
  western valleys (Missoula, Kalispell); central (Great Falls, Helena, Bozeman); the south-central
  gap-wind corridor (Billings, Livingston, Big Timber); northern and eastern plains (Glasgow, Havre,
  Glendive, Miles City); rural basins and the Front (Libby, Seeley Lake, Browning); passes and
  borders (Rogers, Lookout, Beartooth; state-line points).
- **Billings-office gap-wind guidance.** The BYZ office publishes gap-wind probability charts for
  the Livingston–Big Timber–Harlowton corridor (a PDF issued every few days, not a feed). A
  candidate for roadmap item 6, not an integration.

Not carried over, for D23's reasons: the prototype itself, its 1.6 MB of captures, screenshots and
vendored Leaflet, and the skill. Its time-zone fallback to UTC for custom points is worse than the
app's company-zone fallback (D16). Stale sandbox path: `/tmp/roofing-montana-sources`.

*Why not merge the branch even though it merges cleanly:* every installed app downloads the repo
zipball on each update (D6), the prototype duplicates the app, and one app in the repo is the
point of D1. *Handoff:* ChatGPT's next job is roadmap item 5 in `payload/weather.py`, built to the
rules above, with its sweep as the first test fixture.

**D26 · Product name: Montana Hail Watch (2026-10-12).** Carson's decision; “Big Sky Hail Watch” was
the placeholder. The name shows in the header (plain “Montana”, accent “Hail Watch”, tagline
“Storm-to-roof”: the state is in the name now), page titles, the manifest `name`, the printable
summary footer, the shell window and dialogs. Because the shell changed and a new installer is built,
`SHELL_VERSION` is 1.1.0; `SHELL_API` stays 1 and the payload stays 1.0.0 (nothing was shipped).
`APP_ID` is `MontanaHailWatch` in `desktop/launcher.py` and `build.py`, so the installer, the
executable, the data folder, the webview storage, the waitress ident and the user agents are all
new names; no copies were installed under the old `APP_ID`, so nothing is orphaned. The macOS bundle
identifier is `com.montana.hailwatch`. Internal identifiers did not change: `hailwatch.stop`,
`hw_session`, the `hailwatch` and `hailwatch.updater` loggers, `hailwatch.db` and the backup
pattern, `store.MIGRATIONS`, and the manifest `version` and `min_shell`. The `--bigsky` colour
token stays: it names the sky, not the product.

*Why:* a rename is not a reason to touch the shell–payload contract (D3) or the identifiers D2 and
D5 define, or the data on disk; changing `APP_ID` is only free because there are no installs yet.
*Trademark caution:* check “Montana Hail Watch” against existing products and trademarks before it
goes on an installer, a release page or anything printed; HailTrace is an existing hail-mapping
service sold to roofers, so stay clear of that name too.

**D27 · A website first; the desktop app is parked (2026-10-14).** Carson: "Let's completely
rework this. It's too complicated and the design is ugly. Instead of an app let make a website
first." The product is now a static website in `website/`, built by Python and published with
GitHub Pages: a Now page (official alerts, a radar and warning-area map, one card per town for the
next 12 hours), a page per town (alerts at that point, 24 hours, 7 days), a Storm reports page
(three SPC reporting days) and an About page. GitHub Actions rebuilds it every 10 minutes from
`main` (`.github/workflows/website.yml`); branch pushes run the same build against live data with
`--require-live` and keep the result as an artifact. Design: `docs/DESIGN.md`.
- *Parked, not deleted:* `payload/` and `desktop/` are unchanged, their tests still run, no
  version is bumped and no installer is built. Deleting them is Carson's call. Not on the site
  yet: jobs and addresses, territories, inspections, per-roof-system rules, notifications, the
  hail-footprint demo.
- *Own code, same rules:* `website/sources.py` is a new ~400-line module rather than an import of
  `payload/weather.py`, which carries jobs, storage and rules the site doesn't need. What carries
  over is the rules, each with a test: radar layer `1` with its frame time (D7); alerts sorted
  most urgent first, test messages and replaced updates dropped, null geometry listed with a note;
  SPC reporting days 12:00–11:59 UTC, hail in hundredths of an inch, `UNK` wind unknown; gusts
  from the gridpoint series with their units checked; placeholder limits (D16).
- *Alerts on a static site:* each build saves what it verified in `data/state.json`. If the alert
  request fails, the next build keeps the last verified list from the live site with its time and
  says so; it never empties the list and never says "no alerts". A town whose alert check failed
  shows "Alerts not checked". No AI text. Every alert a town's point check finds joins the list
  (2026-10-16): the statewide request runs first, so a warning issued while the 14 towns are
  checked was only in their answers, and the map's town sheet could name no event or end time,
  draw no outline and leave it out of the List. A listed alert that a town's answer shows was
  replaced is dropped, as within one answer, unless a town's check still returned it.
- *Snapshot, not live tiles:* the radar is saved as one picture per build with NOAA's frame time,
  so the page and the map describe the same frame; it is marked stale past 15 minutes. Every page
  shows its build time, which sources loaded, and (a short documented script, rule 4) its age,
  with a warning past 25 minutes. A meta refresh reloads every 10 minutes.
- *Nothing from third-party servers but data:* Leaflet 1.9.4 and the Atkinson Hyperlegible fonts
  (SIL OFL) are served by the site; map tiles come from USGS, alerts and forecasts from NWS.
- *Map labels:* each town's label side and whether it is "minor" (hidden, dot and label, on maps
  narrower than 546 px, which open one zoom out) live in `towns.json`; a test checks that no label
  covers another label or a dot at either zoom. (D28's map replaced that test: "Town label test".)
- *Look:* the dark "storm" look (D19) is replaced by a light "field sheet" with automatic dark
  mode, chosen for sunlight; tokens in `website/static/style.css`.
- *Livingston* joins ChatGPT's 13 pilot towns for the gap-wind corridor (D25).

*Why a static site:* no server to keep running, nothing to install, free on a public repository,
works on any phone, and everyone sees the same checked snapshot. *Limits:* a page can be about
10–20 minutes behind NWS (GitHub may delay scheduled runs); no alerts reach a phone unless the page
is open; GitHub pauses scheduled workflows after 60 days without repository activity. Pages must be
turned on once: Settings → Pages → Source: GitHub Actions.

**D28 · An interactive Montana map in the style of Apple Weather (2026-10-15).** Carson sent a
screen recording of Apple Weather's full-screen precipitation map: "Lets turn this into a working
interactable map of montana that looks like this." The site gets a full-screen `map.html` and the
same map as a card on the Now and Storm reports pages. Design: `docs/DESIGN.md` section 8.
- *What it shows:* Precipitation (the past hour of NOAA's MRMS radar estimate every 10 minutes, then
  the NOAA HRRR model every 15 minutes for the next hour or hourly to 12 hours), Temperature and
  Wind gusts (HRRR, hourly to 12 hours), NWS warning outlines and SPC storm reports. Town bubbles
  carry the NWS hourly forecast for the hour on the timeline; tapping one opens its forecast.
- *Sources, checked live from this container on 2026-10-15 (content, not just HTTP 200):* MRMS
  `PrecipRate_00.00` on AWS Open Data (`noaa-mrms-pds`), a new 0.01° grid every 2 minutes in mm/h,
  negative values for no coverage; HRRR on AWS Open Data (`noaa-hrrr-bdp-pds`), single fields by
  byte range from each file's `.idx` (PRATE about 60 KB, TMP and GUST about 1.1 MB per hour),
  3 km Lambert grid; our projection matches the GRIB latitudes and longitudes to within
  a ten-billionth of a grid cell at all 1.9 million points. Values looked right: frame pixels at the towns decode back to the HRRR value within 1.1 °F and 0.8 mph; at 5 pm the towns read 49–57 °F with cold ranges and a warm Snake River Plain, gusts 25–35 mph on the eastern plains; rain on the North Dakota edge sat in the same place in radar and model; MRMS read −3 only outside radar coverage (the Pacific, Mexico, far Canada), none inside the map area.
- *Why not the NOAA radar picture (D7):* one frame, NOAA's colours and no forecast. Raw MRMS rates
  and HRRR precipitation rates share one honest legend (rate as liquid water, AMS classes) for past
  and future.
- *Honesty:* every frame says whether it is radar or model; the timeline title switches at "Now";
  areas without radar coverage are hatched; a failed download puts a sentence on the map; the
  bubbles are the NWS forecast, the coloured fields are the model.
- *Basemap:* our own vector map (Natural Earth, public domain; Census county lines from us-atlas
  3.0.1), built by `tools/build_basemap.py` into `static/map/basemap.json` (385 KB, identical bytes on a rerun). The USGS
  tiles and the Folium maps are retired from the website; Folium stays in the parked app.
- *JavaScript (rule 4):* playback, scrubbing, menus, sheets and geolocation can only happen in the
  browser. `static/map/map.js` is vanilla, documented, with no framework and no build step; Python
  still builds every number and frame. `tools/smoke_map.py` opens the built map in Chromium on every
  branch push. It ended at about 2,150 lines, most of it layout that keeps Montana and every town
  clear of the panels on crowded screens, failure states and accessibility; moving about 330 lines
  to the build is an open owner's call (ROADMAP).
- *Build cost:* about 40 MB downloaded and 48 frames (about 2 MB, most of it the temperature and gust fields) per build; numpy and
  pygrib on the runner.
- *Limits:* HRRR is a computer model, not the NWS forecast; MRMS rates run low far from a radar and
  in snow; frames are still pictures made at each build, so the newest radar is up to about 10
  minutes old plus GitHub's delay; no lightning or air-quality layer; snow and rain share one
  palette.
- *Verification (2026-10-16):* each piece had an independent review before it was merged into the
  branch (radar and model frames: 5 findings; base map: 2; map page: 15, each fixed and re-checked
  against the old code). Then seven independent lenses (look against the reference, interaction,
  honesty, accessibility, robustness, minimal JavaScript, the data path) reported findings, a
  skeptic reproduced each one before any fix (48 confirmed), fixers ran one group at a time, and a
  final checker re-ran everything: 201 unit tests, the smoke test, the map builder's 70 functional
  and 32 edge-state Playwright checks at phone and desktop sizes in both schemes. It also checked
  the map against the raw NOAA files: live radar and HRRR rain matched the near-dry grids, frame
  colours at the 14 towns matched HRRR temperature (median 0.3 °F) and gusts. Not yet seen: real
  phones (iOS Safari), and real NWS alerts, town forecasts and SPC reports on the map, which this
  container can't reach (the branch's Website build loads them live).
- *Background and hatch (2026-10-16, after review):* past the basemap's padded box the page is the
  neighbours' land colour (`--map-bg` = `--land`, #fafafa; dark #1b1e22; the theme-color metas
  match), not the spec's mist #eef1f4, and the hatch outside the pictures' box is a hairline (1 px
  every 6 px). With the mist and the old 2.5 px stripes the hatch was the loudest thing on a phone
  (three tones, about 40% of the screen); the reference's "not available" hatch is a faint hairline
  on white. The band's words say it is outside the map's area ("Outside map area", short enough for
  one line in a 140 px legend column), not "no radar coverage": NOAA's files have valid data there
  (checked against MRMS), the map just doesn't draw it.
- *Cache addresses (2026-10-16):* scripts, stylesheets and the basemap carry `?v=` = their content
  hash, so the 10-minute rebuilds no longer make every visit download about 150 KB of unchanged
  files; `data/map.json` and the map card keep the build minute.
- *Town label test (2026-10-16):* the label test models this map, not the old Folium one: 30 px
  bubbles, names 20 px from the point (`map.css` `.town`), minor towns from zoom 7.
  `tools/build_basemap.py` `check_layout` (run by `tests/test_basemap.py`) checks every town name
  against the other towns' bubbles and names as well as the basemap labels and places. One
  allowance: at zoom 5, where only maps narrower than about 340 px or very short open, a name may
  reach 4 px into another bubble (Missoula's 3.5 px into Kalispell's, Billings' 1 px into Miles
  City's); no choice of label sides clears zoom 5.
- *Sample legend (2026-10-16):* a sample build's legend notes say the pictures are invented ("not
  NOAA radar or the HRRR model") instead of naming the radar or the model as their source.
- *Words beside the card (2026-10-16):* the Now page's caption and the card's frame title come from
  the build's data (`build.py` `map_card`), not fixed text. They name the picture the card opens on,
  picked as `map.js` picks it: the NOAA radar estimate (stale radar is still radar, with its time),
  or the HRRR model forecast and its time when there is no radar. They list what this update is
  missing (radar, warning outlines, town temperatures) with "This is not an all-clear". The fixed
  caption called a model forecast "the latest NOAA radar estimate" and promised outlines and town
  temperatures that hadn't loaded. The card hides its legend, so the Storm reports page's key also
  names the town numbers (NWS forecast temperature) and the outlines, and says where alerts without
  an outline are listed (the Now page).
- *Context layer (2026-10-16):* a phone's first view reaches about 39–59.7° N, far past the basemap's
  padded box (42.5–51° N), so Montana floated on blank paper; the basemap now also carries Natural
  Earth's state and province lines (0.01°, about 300 points) out to 37.5–60.5° N and 122–95.2° W, east
  of the Pacific coast so no coastline is implied, with 7 state and province abbreviations and 10
  cities. The names start at zoom 6: at a phone's first view (zoom 5.25–5.5) the legend, buttons, note
  line and timeline cover nearly all of that area, and names at zoom 5 sat under them or in the note.
- *Phone pass (2026-10-16):* every portrait phone gets the two-column legend (keys beside a shorter
  scale, about 135–170 px tall instead of 270–340), so Montana sits higher and the fit never has to
  choose between forms; a phone's fit never settles below zoom 5.25 (town names clear) unless Montana
  is wider than the screen there. The limit ring marks the layer's own limit: temperatures outside
  40–95 °F on Temperature, gusts of 25 mph on Wind gusts, none on Precipitation (its picture is the
  rain, not the temperature; DESIGN's layer table gave the ring to Wind gusts). No key comes or goes
  during playback: the ring key stays for the whole timeline, and the gap key shows on frames with a
  gap and keeps its room, hidden, on the others. The card's hatch words are true of everything hatched
  in view ("No radar data on this map" when a gap and the outside band show together). The hatching
  note steps aside while a town is under it, rather than taking a backing that would hide the town;
  the legend's keys still name the hatching. The card zooms in 0.05 steps, which lets a 328 px card
  show Montana at 5.2 instead of 5.

**D29 · Live station readings on the Now page and the town pages (2026-10-16).** Carson: "find a way
to get live weather and add it. It says it's blocked." Everything the site showed was a forecast, a
radar estimate or a model; nothing said what a station measured. The "blocked" note was ChatGPT's
sandbox (D23 already called it stale): `api.weather.gov` answers this repo's builds and every branch
build of the Website workflow. Roadmap item 10, built to the rules of D23 and D25.

- *Source.* The point lookup's `observationStations` link (the stations NWS lists for the town's
  grid square), sorted here by distance, then `/stations/{id}/observations/latest` for the nearest
  three. Four more requests per town, about 55 more NWS requests per build; the live build went from
  31–38 s to 44 s. The station list is kept in `data/state.json` and reused when its lookup fails,
  like the point.
- *Rules.* Never filtered by state. A reading older than 75 minutes is kept and marked stale with its
  age, never hidden. A missing gust beside a measured wind is "no gust reported". Every value shows
  its MADIS flag in words (verified, screened, basic check only, not checked yet, questioned); X
  (failed quality control) and B (marked bad on review) are withheld from the page and kept raw in
  `data/state.json`, with every reading, as the record of what each town showed. °F and whole mph on
  the page, native units in the record; any unit other than °C, km/h, m/s, knots or mph is an error,
  never a guess. Station elevation and the forecast grid square's elevation are shown: a valley
  airport is not a bench or a pass.
- *Where.* Town page: "Observed now" above the 24-hour table, a card per station. Now page: one line
  on each town card with the nearest current reading that has a temperature or a wind (a road sensor
  that sends only a gust is listed on the town page, not quoted on the card), naming the station,
  distance, elevation and age. Values over the placeholder limits get the forecast flags' orange
  bold. Not on the map: D28's `map.json` contract is unchanged.
- *Status.* "NWS station readings" joins the per-source line on every page; it is ok when every town
  has a reading, so a branch build with `--require-live` fails when a town has none.
- *Live check, 10:50 am MDT:* every town had a reading under 75 minutes old. Billings: KBIL 3 mi,
  43 °F, 10 mph SSW, no gust reported. Lewistown's nearest station (MTLEW, MT-200 on the Lewistown
  Divide, 8 mi) sent only a gust, so its card quotes Judith Peak (JPKM8, 14 mi, 6,428 ft), and the
  elevation says why its numbers can differ from town. West Yellowstone's nearest answering station
  is Yellowstone Lake, WY (35 mi); Old Faithful answered 404 and says so on the town page.

**D30 · 3D storm view (globe) research recorded; the globe waits on owner decisions (2026-10-17).**
Carson asked for "a version of Google Earth with holographic imagery for clouds and storms". The
research is in `research/globe/` (plan and evidence sections, `validation-evidence/` with live
checks, and a prototype outside the site, checked in headless Chromium only). Nothing ships, and
nothing touches `website/`.

The globe waits on the owner decisions in `research/globe/README.md` section 2 (D-G1 to D-G26). The
chief ones are the site-files-only browser rule, which rules out streamed worldwide imagery; a
vendored WebGL library and JavaScript caps; placement; and how the publishing terms read for
products built from NOAA data. Two routes are recorded without a choice: storm layers on the Map
page first, or a globe page now.

Decision, 2026-10-17: Carson chose the staged route: storm layers on the Map page first (P1 text
values, P2 the Band 13 picture, P3 MESH only with verified units, P4 the echo-top raster, P5
cloud-top classes, P6 a two-hour loop), behind a build flag that is off by default; a link-only
globe only after the P4 gate and a separate approval of a vendored library and JavaScript caps.

P2 build, 2026-10-17: Carson asked to start P2. `website/satellite.py` draws one NOAA GOES-East (GOES-19)
band 13 picture (10.3 µm, clean infrared) of the newest 5-minute CONUS scan on the map's image box, as a
fourth layer named Satellite. It is built only with `--storm-layers` (the flag is off by default and only
branch previews pass it), so the default build's pages and data have no satellite words, keys or files. The
shared map script's code changed (its ?v= hash too); no satellite word reaches a default page or data file. The picture is an
observation: its frame kind is `satellite`, it is never blended with the radar estimate or the model
forecast, and its words never claim a height, a clear sky, a dry area or hail (they say "not a height" and
"not a hail signal"). Two of the README's proposals are adopted
for this build: the freshness limits (stale after 1,200 s, when the picture is still drawn; no picture
after 3,600 s, D34) and the observation wording of the proposed `satellite_image` kind (D33; this build
names its kind `satellite`). GOES-East is read first, and GOES-West (noaa-goes18) when East fails or has no
scan in the last hour, because GOES-West's CONUS grid misses the south-east corner of the map's box (about 0.2% of it). Only
quality flag 0 is drawn; every other value is hatched as no satellite data, never drawn as clear sky. An
uncorrected cloud top is drawn away from the satellite (the parallax in the corrections below), and the
About page and the picture's own words say so. The two counsel items, D-G10 (publishing terms for NOAA-derived
products) and D-G11 (the GOES access banner), are still open: no GOES layer reaches users until counsel has
read both (research/globe/README.md section 2).

The proposed decision entries that follow are listed in README
section 9b as D31 onward and wait for Carson.

Corrections of record:
- D23's "Folium bundles Leaflet" is wrong: the parked app loads Leaflet 1.9.3 from cdn.jsdelivr
  (folium 0.20.0, `folium.py:27`); the website vendors Leaflet 1.9.4, and rule 4 (third-party code
  served by the site, not a CDN) is the precedent.
- GOES-R has two cloud-top-height products, ACHAC (10 km) and ACHA2KMC (2 km); a height layer must
  say which one it uses.
- MRMS 3D levels are heights above mean sea level, so the 0.5 and 0.75 km levels lie below ground at
  Billings (952 m); MRMS has no coverage-mask product, so -999 is only a candidate coverage signal,
  and the meanings of -99 and -999 are unverified.
- GOES parallax over Montana moves an uncorrected cloud top away from the satellite by about 3 to 4
  km for a 2 km top and 20 to 33 km for a 12 to 15 km top (north-west for GOES-East, north-east for
  GOES-West).

*Why:* so the next agent does not repeat this work, and so the owner's choices are explicit before
any globe code is considered.

**D31 · Towns: every Montana city over 8,000 plus Sidney (2026-10-17).** Carson asked for every
Montana city over 8,000 in the 2020 census, and for Sidney. Wikipedia's list of municipalities has twelve
over 8,000, and all twelve are now on the site. Three were missing and are added: Belgrade (10,460),
Anaconda (9,421, consolidated with Deer Lodge County) and Sidney (6,346). Glasgow, Glendive, Lewistown and
West Yellowstone stay. Whitefish (7,751) and Laurel (7,222) are under 8,000, and Lockwood and Evergreen are
census-designated places, not towns, so none of them is added. *Live check (2026-10-17):* the NWS point
lookup answered for all three, with the offices the build will show (Belgrade TFX, Great Falls; Anaconda
MSO, Missoula; Sidney GGW, Glasgow). Anaconda's first request got a 500; the next requests got 200.

A town now shows from its `min_zoom` in `towns.json`: 5 when it has none, 7 for a `"minor"` town (D28), or
the zoom the layout needs. Anaconda shows from 8 with its label on the left, Belgrade from 9, and Sidney
from 5 with its label on top. The label test and a Chromium check at zooms 5 to 11 settle each value: a
town appears at the first zoom where its bubble is clear of the others by a usable margin. In Chromium
(rings included) Belgrade's bubble is 3 px from Bozeman's at zoom 8 and 40 px at zoom 9, and Anaconda's is
7 px from Butte's at zoom 7 and 48 px at zoom 8. Glasgow's label moved to the top: on the right its name
ran into Sidney's bubble at zoom 5 (5.1 px, beyond the 4 px allowance), and on the left into Havre's. The
base map was rebuilt (384,594 to 384,935 bytes): three site places were added and the phone-only "SK"
label moved about 0.03°; nothing else moved.

*Why:* a population cut-off anyone can check (the 2020 census) is easier to defend than a hand-picked list,
and each town gets its own card, page and forecast. A per-town `min_zoom` replaces the single "minor" flag,
so a town appears at the first zoom where it is clear of its neighbours, not at a fixed zoom 7.

**D32 · Imagery base map, opt-in (2026-10-17).** Carson asked for a satellite-style base map with roads and
names, after two screen recordings of Google Maps' satellite view. Decision: the white vector map stays the
default, and the Layers menu gets a Base map switch to imagery. The chosen source is USGS The National Map's
`USGSImageryTopo` service: aerial imagery with roads, rivers, boundaries and place names. USGS says its map
services are free and in the public domain, and asks for an acknowledgment. While imagery is on, the credit row
reads "Imagery: USDA, USGS, The National Map. Your IP address and the map area you view go to USGS." Tiles are 256 px
JPEG, need no key, send CORS headers and are served to zoom 16. Design: `docs/DESIGN.md` section 8, "Imagery base map".

- *Rule change.* The browser fetched only site files (AGENTS.md rule 4). Now it also fetches the imagery tiles,
  and only those, while Imagery is on: after the viewer switches to it, or when a link opens the page on it
  (`?base=imagery`). The tiles come from the one host named in `website/build.py` (`IMAGERY`). This amends the D27
  line "Nothing from third-party servers but data", and AGENTS.md rule 4. build.py passes the address and the two
  lines the credit row shows to the Map page as `data-imagery` and to `data/map.json` as `imagery`; `map.js` holds no
  address, host name or line of words. Tests check that the address is https on that host, that it appears only in
  those two places, and that `map.js` names no URL, host or line of words.
- *Privacy line.* While Imagery is on, the credit row says "Imagery: USDA, USGS, The National Map. Your IP address and
  the map area you view go to USGS.", and the same words, with "while it is on", sit under the Imagery choice and on
  the About page. With
  the switch off the page makes no request to another site. A link that opens on Imagery (`?base=imagery`) loads the
  tiles as the page opens; the credit row with the same words is there from the start, so the arrival case has the
  line too. While every tile fails, the row shows the failure words instead, without the sentence (the requests were
  still sent; the Layers menu and About keep the sentence). Each tile request also carries an Origin header (the
  page's origin) and a Referer that holds the page's origin only, which is the browser's default policy for a request
  to another site (checked 2026-10-18 from a local server; the live site was not checked, and the same policy applies
  there), the browser's User-Agent and client hints, and no cookies. The line names none of these; whether to add them
  is open for Carson.
- *What changes on the map.* The tile layer is made on the first switch. While imagery is on, the vector base
  map's land, water, roads, county lines, place dots and names are hidden; the Montana outline and the state and
  country borders stay. Weather frames, warning outlines, storm reports and town bubbles are unchanged. The zoom
  limit is 16 while imagery is on and 11 when it is off. The credit is a legend row. The card never uses imagery.
  The page address keeps `base=imagery`, and nothing else stores the choice. Dark mode shows the imagery as it is.
- *If a tile does not load.* A tile error (Leaflet's `tileerror`) replaces the credit in the row with "Imagery didn't
  load from USGS. Outlines and towns are still shown.", and the row goes back to the credit when a tile loads
  (`tileload`). With every tile refused, the map keeps a plain near-white background with the Montana outline, the
  state and country lines and the town bubbles. The base map's roads, lakes, rivers, counties and names stay hidden
  while Imagery is on: a white map under the tiles would draw its names over the photograph. The words come from
  `build.py` (`failed_line`), not from `map.js`. A 404 from USGS also counts as a tile error (outside the United
  States above zoom 8, see the facts above), so the row says imagery didn't load for that tile, and it returns when a
  tile loads. `tools/smoke_map.py` (check_imagery_refused) checks the words, the hidden shapes and names, and the
  return to the credit when a tile comes back (a note when no tile can come).
- *Facts checked on 2026-10-17, and the tiles and terms again on 2026-10-18.* The terms and the limits of the
  service are in `base-imagery.json`; the ImageryTopo facts are in `labels-on-globe.json` and
  `montana-imagery-buildings.json` (all in `research/globe/validation-evidence/`). The tile address is
  `.../USGSImageryTopo/MapServer/tile/{z}/{y}/{x}` (row before column). Measured tiles are 15.7 to 35.7 KB: 15.7 to
  32.3 KB at zoom 7 in the fit view, and 35.5 to 35.7 KB at zoom 16 over Billings and Missoula. Tiles at zoom 6, 9,
  13 and 16 over Billings answer 200 image/jpeg; zoom 17 and up return 404, because the service's largest scale is
  level 16 (its metadata gives 1:9,028). Outside the United States, USGS does not document what the tiles up to
  zoom 8 show. From zoom 9, Calgary, Lethbridge and Regina get a blank white tile (2,419 bytes), Toronto a
  near-white one (2,767 bytes; 99.7% of pixels at 250 or more), Vancouver a mostly white one (8,197 bytes; about
  91% at 250 or more), and Paris, Sydney and Tokyo a 404 (all checked 2026-10-18).
- *Licence.* USGS's FAQ says its map services and data are free and in the public domain, with no restrictions,
  and asks that products derived from them carry this acknowledgment: "Map services and data available from U.S.
  Geological Survey, National Geospatial Program." The About page quotes it verbatim and links the FAQ. The record
  gives USGS's own imagery credit as "USDA, USGS"; the credit row adds the service name and does not carry the full
  acknowledgment (decided 2026-10-18, owner-delegated: the About page carries it). USGS's topographic maps are public
  domain except three cases that apply only to US Topo maps (produced 2009 to date). The case that matters here: most
  US Topo maps from 2010 to 2016 contain commercially licensed road data. USGS states no licence for ImageryTopo's road
  and name data (`labels-on-globe.json`, `rights-matrix.json`). That is an open point for Carson, not a clearance.
- *History.* D9 used USGS tiles in the parked app; D28 retired them for the white map. The 3D research (D30; its
  D-G15 in `research/globe/README.md`) listed streamed tiles as a route that needs a rule change, a named host list
  and a privacy line. This entry supplies all three.
- *Sources checked and not chosen.* Google imagery: its terms exclude hosting and caching (D-G4 in
  `research/globe/README.md`). Esri: its terms bar programmatic use of session tokens and limit the public plan to
  personal use; whether anonymous tile requests are covered is not established. NASA GIBS: its licence is
  contested (NASA's data-use guidance says NASA-led data are CC0; its imagery pages say the imagery is not in the
  public domain), and the layers checked stop at zoom 8, 9 or 13. EOX's 2018 to 2025 layer is CC BY-NC-SA, which is
  non-commercial. Also not chosen: self-hosted tiles, our own labels over imagery (the rejected second option), and
  the globe.

*Why:* Carson wants a satellite look with the names on it. The service meets these tests in the record: USGS
states that its map services are public domain (with the US Topo exceptions); it needs no key; it sends CORS
headers; and its tiles load in a browser to zoom 16. Its main imagery, NAIP, is public domain by USGS's listing. Its
road and name licence is not settled, and that stays open for Carson. Carson kept the white map as the default on
2026-10-17, after comparing the satellite view; the reason was not recorded. The white map is the vector map D28
built, it loads the same first view, and with the switch off the page makes no request to another site. Writing
the exception down keeps the next change from streaming tiles from another host without a decision.

**D33 · Scheduled rebuilds run off the top of the hour (2026-10-18).** Carson asked for updates that are
consistent and as recent as possible. Between 2026-10-16 19:42 UTC and 2026-10-17 08:57 UTC (about 13
hours), the `*/10 * * * *` schedule on `main` started four times, with gaps of 151.5, 141.6 and 264.5
minutes (`research/globe/validation-evidence/p0-gates.json`). GitHub's docs say the schedule "can be
delayed during periods of high loads", that "High load times include the start of every hour", and that
"some queued jobs may be dropped". The schedule becomes 7, 17, 27, 37, 47 and 57 minutes past the hour:
still six rebuilds an hour, but not on the hour. The cause of the gaps has not been diagnosed, so this is
an experiment, not a fix. The measurement is the count of scheduled starts in the 24 hours after the change
reaches `main` (144 is the every-10-minutes figure), to compare with the four runs above.

*Why:* GitHub's own advice for delayed schedules is to "schedule your workflow to run at a different time of
the hour". The change is one line and easy to undo, so the measured count can decide whether it stays.

**D34 · Hail history for every address: the owner's decisions and the B1 build (2026-10-18).** Carson wrote on
2026-10-18, opening with "Decisions that are mine.", and then seven decisions. They are quoted word for word:

1. "Trailing 5 years to today."
2. "A public lookup by typed address or clicked location. Each address in montana should have a dot to click on the map with a popup on each history of weather."
3. "Pages only for now."
4. "Make the weather updates consistent and recent as possible"
5. "Try to find and read hail units and codes then process it and make the user understand it easier. Where they can find the exact date that the hail happened at that location."
6. "Don't include owners names. But I do want all addresses included and all types of weather at that address for the past 5 years in a popup after you click the house on the map."
7. "Follow the laws"

What they settle:

- *Window (1).* The store holds the 1,826 SPC days that end on the newest published day. On 2026-10-18 that is
  2021-10-17 to 2026-10-16, the last from the file stamped 2026-10-17 at 12:00 UTC. Day indexes count from
  2020-01-01 and never move, so the window can slide without renumbering. A day runs from 12:00 UTC to 12:00 UTC
  the next day: 6 am to 6 am Mountain daylight time, 5 am to 5 am in winter (the SPC reporting day).
- *Lookup, addresses and names (2, 6).* B1 is a public lookup by clicked location on the Map page. B3 adds typed
  addresses and a dot for each address in the Montana State Library (MSL) Structures and Addresses Framework
  (674,715 points). Owner fields are never read and parcel IDs are dropped, so no owner name is read, stored or
  shown. B2 adds the other kinds of weather (reports, warnings, station gusts) to each address's popup.
- *Pages only (3).* No server, database, account or second host. The store is site files under `_site/hail/`,
  copied in by the Pages build. The daily job publishes the store as one release asset on this repository
  (`hail-store`), which the 10-minute build downloads. The release is the transport, not a second site.
- *Recent and consistent (4).* The daily job, `.github/workflows/hail-store.yml`, runs at 12:43 UTC. It is a full
  rebuild: it rebuilds the whole window from NOAA's archive, verifies it and publishes it. The daily append that the
  first design carried forward is withdrawn.
  The committed seed and the Actions cache restore from the first specification are withdrawn with it: the 10-minute build downloads the release asset and nothing else, and the daily job may keep an optional download cache of the raw files.
  The gate is that a cold-cache and a warm-cache build give byte-identical
  shards (B1-6), so the cache only saves downloads. The 12:00 UTC file is published about 12:08 UTC (measured in
  `hosting-and-architecture.json` on the hail-history research branch). The newest day is added by a job that starts
  at 12:43 UTC and shows here on the next rebuild, usually within the hour. The schedule offset is the consistency fix
  for the builds, which leave the top of the hour as the job does (D33).
- *Units and codes (5).* NOAA's MRMS GRIB2 user table settles them (its evidence is
  `research/hail-history/validation-evidence/mrms-grib2-tables/` on the `claude/hail-history` research branch).
  MESH and the MESH maxima are in millimetres. -1 is missing and -3 is no coverage. In the reflectivity product, -99 is
  missing and -999 is no coverage. Table versions 12.0 to 12.2 agree; the archive files do not state their version. So
  a size shows to the hundredth of an inch, rounded down, with the millimetre value exact beside it, with its NWS size
  word and the exact SPC day. Missing and no-coverage values are never stored, and a day with no value is "no
  estimate", never "no hail".
- *Size display (10).* Sizes are shown to the hundredth of an inch, rounded down, with the millimetre value exact:
  513 tenths is 2.01 in (51.3 mm), 185 is 0.72 in (18.5 mm), 253 is 0.99 in (25.3 mm), 190 is 0.74 in (19.0 mm) and
  1015 is 3.99 in (101.5 mm). Rounding down never crosses a class edge, because every class edge is a whole hundredth
  of an inch, so one rule covers every size and no caps table is needed. The classes, the severe tag (254 tenths and
  up) and the 4.00 in note (1016 tenths and up) use the exact tenths. The browser applies the same rule: it rounds the
  tenths down to the hundredth and writes two decimals.
- *Floor, 0.25 in.* Values under 0.25 in (6.35 mm) are not stored. Pea size, 0.25 in, is the smallest size the
  NWS reports, so a smaller radar value has no report to compare with. The first stored value is 64 tenths of a
  millimetre (6.4 mm, which reads 0.25 in). The floor also keeps the store small: in the prototype, 0.25 in and up
  is 2,913,472 cell-days in 4,595 shards (13,415,025 bytes), against 11,054,458 positive cell-days at 0.1 mm and
  up (`h1-mesh-store.json`, research branch).
- *Review at 4.00 in.* 4.00 in (101.6 mm, 1,016 tenths) is the largest official Montana hail size in the research
  evidence (`warnings-archive.json`, fact 39, research branch) and the candidate review cap in research OW-H5,
  which proposed holding values above a cap out for review. The B1 contract shows them instead, with a note at
  4.00 in and up: "unusually large for a radar estimate; treat with care". The value stays visible, and its
  limits are stated beside it.
- *Kinds kept apart (rule 5).* The sheet and the town tables show one kind: a radar estimate (NOAA MRMS MESH) of the
  largest hail over this cell, about 0.7 miles north to south and 0.5 miles east to west, during the day. Reports,
  official warnings, radar detections and station readings join in B2, each row with its own kind word. No word calls
  a value damage, a roof finding or an insurance matter. Every loaded sheet and loaded town table says that an estimate is not a
  measurement at the ground and not an inspection, and that no estimate is not "no hail".
  Days not listed have no radar estimate of 0.25 in or more; that is not the same as no hail.
- *Outside Montana (11).* The store decides, not the grid box. Every tile that holds a Montana cell has a shard, even
  one with no events. Each shard lists the in-tile keys of its Montana cells in `state`, and `hail/index.json` and
  `data/map.json` list every shard's name in `tiles`.
  `data/map.json` carries the 4,597 tile names (about 64 KB on disk, about 11 KB over the wire because Pages compresses JSON in transit), so no bitset is used.
  In the browser, a tile not in `tiles` gets the outside words with no fetch; a key not in the shard's `state` gets the outside words; a key in `state` with no entry in `cells` gets the no-estimate words; any other key gets its rows.
  The browser also picks the largest day, counts the classes and chooses between the lead templates; every sentence it fills is Python's (website/hail.py WORDS).
  `tools/smoke_map.py` checks Wyoming (43.5, -108.0), Idaho (44.6,
  -115.0) and Canada (49.5, -110.0) for the outside words and zero shard requests, and an in-state cell with no events
  for the no-estimate words after one fetch.
- *Copy check and partial days (12).* For each SPC day the build compares the file's size in NOAA's bucket with Iowa
  State's archive (IEM). If both answer and the sizes differ, the day is re-derived as the maximum of its two-minute
  frames and listed in `copy_check.rederived`.
  If IEM has no copy or does not answer, the bucket copy is used and the index says so. A re-derived day with fewer than 720 two-minute slots filled is listed in `copy_check.partial` as
  `{"day": "2025-06-25", "frames": 717, "expected": 720}`, and is still stored as the maximum of
  the frames that exist. For 2025-06-25 the bucket's 1440-minute copy disagrees with its own frames, so the frames are
  the value kept. `compare` passes when every overlapping day that was not re-derived has 0 mismatches against the
  prototype and every re-derived day equals the frame maximum the builder recorded; it prints the partial list.
  `verify` does not fail on partial days. The index's `copy_check` keeps `coverage`, `partial`, `frames`, `rederived`,
  `days_differed`, `days_checked` and `skipped`. In the store the re-check packs (built 2026-10-18 at 12:42:28 UTC), the partial list has one day, 2025-06-25 (717 of 720 slots, stored as the frame maximum). Of the 1,586 days checked, four differ between the NOAA and IEM copies and are re-derived (2025-06-25, 2025-06-26, 2026-05-25 and 2026-09-10); 239 days from 2021-10-17 to 2022-06-13 have no IEM copy (HTTP 404) and use the bucket copy. B1's final check of that build against the prototype passes `compare`: 1,824 overlapping days with the same mask, 2,636,407 matched cells, 201 cells only in the store, 921 only in the prototype and 1,915 values that differ. Every mismatch falls on a re-derived day (3,037 in all: 3,033 on 2025-06-25 and 4 on 2026-05-25; none on other days), and every re-derived day equals its recorded frame maximum.
- *Off on main (7).* `--hail-history` is off by default. Branch previews pass it, as they pass `--storm-layers`;
  `main` does not. It stays off until Carson says the About text is right and counsel confirms the items that
  decision 7 covers: the MSL clause "for no other purpose", MCA 2-6-1017, and the GitHub Actions and Pages terms.
- *Known limits, recorded.* (a) The research record measured the 12:00 UTC file's upload 496 to 3,623 seconds after
  its stamp (`evaluation-and-wording.json`, fact 61, research branch). On some days the 12:43 UTC job reads before the
  file is up. In that run the window ends one day earlier, and the next daily run includes the day. The research had
  proposed a start after 13:15 UTC (OW-H4). B1 keeps 12:43 UTC, and the first runs measure it. (b) Where the NOAA and
  IEM copies of a file differ in size, the day is re-derived from its two-minute frames (see copy check and partial
  days above). The prototype found four such files, stamped 2025-06-26, 2025-06-27, 2026-05-26 and 2026-09-11. Those
  are the SPC days 2025-06-25, 2025-06-26, 2026-05-25 and 2026-09-10 (`h1-mesh-store.json`). (c) Montana membership is decided by the centre of the 0.01-degree cell, not by the point. So a point inside Montana within about one cell of the state line reads outside when its cell's centre lies outside Montana, and a point outside Montana within that distance reads inside when its cell's centre lies inside Montana.
- *Labels.* The globe research's proposed decision labels (`research/globe/README.md` section 9b, from D31) are
  proposals, not entries in this log. The D34 that D30 cites for the satellite freshness limits is one of those
  proposals. This entry is the D34 in the log.
- *Built on `claude/hail-b1`, not merged.* `website/hail.py` (the grid, size classes and words, store readers, the
  SAMPLE fixture, the full daily build and verify); `website/build.py`, the templates and `website/sources.py`
  (`--hail-history`, `--hail-store`, the town tables, the About paragraph, the contract row);
  `website/static/map/map.js` (the click, the outside rule, one shard fetch and the sheet, documented in its header);
  `.github/workflows/hail-store.yml` (installs unpinned, as the site build does); the tests and the docs. The words
  are in `docs/DESIGN.md` section 9. The gates and their results are in
  `research/hail-history/validation-evidence/b1-verification.json`, pending the re-check.

*Why:* the owner's seven decisions change what the site is for: a public history at any spot, five years, no owner
names, and the laws. The next agent needs them word for word before B2 and B3 are built. The radar estimate ships
first because its units are now verified and its source is one NOAA file a day. The flag keeps the history off
the public site until the owner has read the About text and counsel has read the terms.

**D35 · Hail history B2: the other kinds of evidence in the same sheet (2026-10-18).** Within this entry, D1 to D35 (such as D6, D26, D33, D34 or D35) cite the supervisor's B2 review decisions, which are not entries of this log. The supervisor's D34 (round 6, the flood products ruling) is applied below, and the supervisor's D35 (round 7) corrects part of it in the same entry, in place, as the round-6 entry was amended; the log's own D34, above, is the owner's seven decisions. B2 adds the other kinds of weather at a spot to the sheet and the town tables that B1 opened (D34). It serves Carson's decisions 2, 6, 4 and 7 in D34, quoted there by number: 2 (a popup on each history of weather), 6 (all types of weather at that address for five years, with no owner names), 4 (updates as consistent and recent as possible) and 7 (follow the laws). What they settle:

- *Kinds, apart (2, 6).* Six kinds of evidence sit in the same sheet. Every row starts with its kind label (D3): "Report:", "Record:", "Detection:", "Warning:", "Zone product:" or "Station:". Each section names its kind in its heading (the heading keeps the long form) and in its what-this-is sentence. No count adds two kinds together, and no kind is turned into another. The sources, their radii and units, and what each one does not show:
  - *Report* (heading "Reports within 5 miles"). IEM's LSR archive, every type the archive returns, with the archive's type word lower-cased (for example "tstm wnd dmg"). Within 5 miles (8.05 km) of the cell centre, for the five years to the as-of day. Units by type (D9): hail, rain and snow in inches; gusts (G and N) and sustained wind (A) in miles per hour. Tornado, funnel cloud, flood, lightning and every other type show the type word and no number. Qualifier E, M and U as "estimated", "measured" and "unknown" (IEM's changelog). Known gaps: no IEM document read states the wind unit, so mph is inferred (1,115 of 1,333 remarks match it); the hail unit is assumed; the NWS definition of the qualifier was not read (its LSR pages return 404), and some 2021 to 2023 rows carry qualifiers before IEM's changelog date (2024-09-23); SOURCE is shown in sentence case; REMARK is cut at 160 characters; MAG "None" is missing; two rows (2022-12-22 and 2023-08-19) have an unquoted comma in CITY, which the research says shifts the qualifier.
  - *Official record* (heading "Official records within 5 miles (NCEI Storm Events)"). NCEI's Storm Events bulk CSV for the window's years: hail and thunderstorm wind points within 5 miles, and the zone-coded rows of every type (such as High Wind, Strong Wind, Winter Storm and Drought), which are placed by the cell's public zone code (see Zone product below). Hail in inches; wind in knots with miles per hour beside (1 kt = 1.15078 mph); MAGNITUDE_TYPE MG, EG, MS and ES shown as "measured gust", "estimated gust", "measured sustained" and "estimated sustained" on every wind row (D5). Known gaps: the 2026 file ends 2026-06-30 in every state while LSR has rows after that, so the words give NCEI's newest event date; High Wind and Strong Wind rows have no coordinates and appear as zone rows only; the time is local standard time (see Time); in summer 2025 the NCEI-derived UTC ran an hour early against LSR for 42 hail and 55 gust pairs, and the cause is not established. NCEI's county-coded records of tornado, flood, flash flood, heavy rain, funnel cloud, lightning and debris flow (points with a county code, not zone rows) are not joined in B2 (round 6, D34); they are B5's (see Not joined below).
  - *Radar detection* (heading "Radar hail detections within 2 miles"). NCEI's SWDI nx3hail (probability 100 and a maximum size above zero), requested by month: detections within 2 miles (3.22 km) of the cell centre, counted by SPC day, with the largest MAXSIZE. MAXSIZE is in inches in steps of 0.25 (the ICD for RPG Build 18.0, 2018; its current revision was not checked). Known gaps: no records nationwide from 03:32:39 UTC to 24:00 UTC on 2025-06-15, the gate day, and none on 2025-01-12 to 19 or 2026-10-13 (research gap 4); no records is not evidence of no hail; the inventory is not complete; exact duplicate rows are dropped at build (KGGW produced 278 on 2023-05-24); positions carry 1 to 4 km error; the live service does not serve the warn or plsr products, so warnings come from IEM.
  - *Warning* (heading "Warnings that covered this spot"). IEM's watchwarn archive for severe thunderstorm (SV), tornado (TO) and flash flood (FF) warnings: significance W, issuance polygons, one phenomenon per request. A warning is listed when the cell's centre lies inside its issuance polygon (an even-odd test at build time). Its row reads "issuance polygon in effect"; its times are when that polygon was in effect, which can differ from the warning's own valid time, and the sheet does not show the valid time. EXP rows are skipped, and county rows are twins, skipped. A warning with no outline on file cannot be matched to a spot: the section says so and never reads that as no warning (AGENTS rule 6). Times in Montana time; tags as the archive gives them: hail in inches, wind in miles per hour, the NWS damage threat tag (D4), the tornado tag. Known gaps: tags are the forecast threat at issue time, not what fell; IEM drops the "<" that the official text carries (13 of 61 hail texts in the research), so a hail tag there is an upper bound, and the sheet shows the number as the archive gives it and says the archive keeps the number only; TO events carry no wind tag; the polygon test misses warnings that were in effect for the county but whose polygon did not cover the spot (the research found four TFX warnings in effect at 23:12 UTC on 2025-06-15 with no polygon over the test point); 103 SV and one TO EXP rows end before they begin, so skipping EXP leaves 21:51 to 22:00 UTC uncovered at the Benchland test point, and that rule needs a wording review. In the window the store holds 2,240 SV, 17 TO and 148 FF warning events (the index's counts; the SV and TO counts match the brief's B2-2 figures).
  - *Zone product* (heading "Zone products for {zone name} ({zone})", or "Zone products" when the cell has no public zone; label "Zone product:"). IEM's watchwarn archive for zone products, one phenomenon per request: high wind warning (HW.W), winter storm warning (WS.W), blizzard warning (BZ.W), ice storm warning (IS.W), extreme cold warning (EC.W), wind chill warning (WC.W), dust storm warning (DS.W), wind advisory (WI.Y) and flood watch (FA.A). D34 (round 6) removed flood warning (FL.W) and flood watch (FA.A) from this list. D35 (round 7) restores FA.A, whose zone-coded events the zone path places; its 18 county-only events are B5's. FL.W stays out: its polygon rows carry no zone code, so the zone path finds none, and it is B5's (below). Red flag warnings (FW.W) are not public-zone products; they are placed by fire weather zone, below. With FW.W the joined zone products are ten: HW.W, WS.W, BZ.W, IS.W, EC.W, WC.W, DS.W, WI.Y, FA.A and FW.W. Known gaps: the zone rows depend on the archive's own coding, which gate B2-6 checks live.
    - *Public zones (D8, D16).* The cell's public forecast zone is the NWS zone whose polygon holds the cell's centre, read from the NWS zone shapefile at the daily job (pyshp, imported lazily). A Montana cell that no public zone polygon holds takes the nearest zone edge within 2 km; beyond that it reads "The forecast zone for this cell could not be determined." The re-check counted 337 Montana cells with no public zone after that rule, all more than 2 km from an edge. Every public zone edition the NWS public zones page links is read: z_18mr25.zip and z_16ap26.zip. Each file name gives its day and month; the newer edition is in force from 2026-04-16, its cut-over date. A product or record takes the zone code of the newest edition in force on its issue day, and a day before the oldest linked edition takes the oldest. The two editions hold the same 83 Montana zones, and the re-check found no difference in names, bounding boxes or vertices between them, so the build states no boundary change. A code that no current zone holds is counted as unplaced (D11).
    - *Fire weather zones (D7, D17).* Red flag warnings are placed by the cell's fire weather zone, from the newest fire zone shapefile that the NWS fire zone page links (the page links fz16ap26.zip and fz18mr25.zip; this build reads fz16ap26.zip, the newest, and the brief's fz_<ddmmyy>.zip name is not the one the page uses). Every red flag warning code in the cache (32 codes, 2021 to 2026) is in the newest edition's list, so none is unplaced for its code; the older edition's 32 Montana zones were compared in review and match the newest edition's codes, names and outlines (open item 12 keeps only the D8 question). They have their own zone lead, "{m} red flag warnings for fire weather zone {name} ({code}) between {start} and {end}.", and the browser fetches `hail/z/fire-<zone>.json` for the cell's fire zone. A cell that no fire zone polygon holds reads "The fire weather zone for this cell could not be determined." If the fire zone shapefile cannot be read, the sentence is "Red flag warnings are not listed (fire weather zones were not available)." The nearest-edge rule of D8 is not applied to fire zones (open item 12). The zone section's what-this-is sentence (`zones_what`) still says "a forecast zone" only; it should name fire weather zones too (wording for the words owner, not a decision).
    - *Spans and keys (D6, D16, D25, D26, D30, D31).* One zone event is one VTEC event. Its key is the zone, the phenomenon, the significance, the event number and the year. The build also keys the issuing office, because the office assigns the event number; no event in the cache has rows from two offices, so the office splits nothing. The key holds no issue time: rows with other issue times (CON, EXT, EXA, EXB, UPG, EXP and CAN) update their event and never start a new one (D30). The build already keys events this way. Withdrawn: the sentence of review decision D25 that products sharing an event number with different issue times are different events. A known limit, open item 15: an event number that NWS re-used for separate periods in one zone is one event, so its periods read as one span (the four named cases are MTZ004 WS 2024, MTZ320 WS 2023, MTZ003 WS 2021 and MTZ302 HW 2022; a broader check, a row issued after the group's earliest end, flags 19 groups in the window). Review decision D33 (round 4 of the B2 review) sets the period rule that B5 implements (open item 16). The begin is the earliest issue time of the event's NEW and CON rows (D25). An event with neither begins at the earliest issue time its rows carry (D30); that is how the 3,687 cancellation-only groups in the window begin (open item 11). The build writes a begin on every event it lists, so "start not recorded" never appears in the sheet; the template keeps the words for a zone file with no begin. The end is the earliest cancellation (CAN) or upgrade (UPG) time among the event's rows; a tie reads as cancelled, and the row that sets the end gives the word. An upgrade ends the lower event at its upgrade time, as a cancellation does (D31). NWS Instruction 10-1703 (April 6, 2021) says that UPG implies the lower event is cancelled in the area of the segment, and every UPG row in the cache (41) has its expiry at its update time, which the build takes as the upgrade time. The span then reads "{begin} to {end}, cancelled" or "{begin} to {end}, upgraded". The event that the upgrade produces (its NEW row) is a separate event under its own phenomenon. Withdrawn: the sentence of review decision D26 that upgrade rows do not end an event, which the review's D31 cites as "D27"; review decision D27 (a station or zone file that fails to load gives its unavailable sentence) stands. A cancellation or upgrade time is the end even when it is at or before the begin (D26): the event then reads "cancelled at {time}" or "upgraded at {time}" in place of "{begin} to {end}". Otherwise the end is the latest expiry of the other rows, and "end not recorded" is written when that expiry is not after the begin (D6). The window takes an event by its begin.
    - *Zone leads and counts (D17, D11).* The public zone lead counts public products only: "{n} products for zone {name} ({code}) between {start} and {end}." (one: "1 product for zone ..."). With none: "No product for zone {name} ({code}) between {start} and {end} is listed. That does not mean the weather was calm." Products and records that no zone holds are counted for Montana as a whole, and the sentence says so: "{n} zone products in Montana in the window could not be placed on a zone; their zone codes are not in the public zone editions the NWS page links." The official record section says the same of its zone rows. Because the count is for Montana, it is never read as this zone's count (D11 as corrected). The brief's count of 1,648 IEM rows was not reproduced, because that figure counts every cache year. In the window the re-check counted 1,116 MTZ-coded rows outside the 83 public zones; 456 of them are public rows (not red flag warnings), and those rows make up 452 distinct products. The sentence above counts those 452 products; the index keeps the 456 rows as `zone_rows_unmatched`.
  - *Station reading* (heading "Peak gusts at the nearest stations"; label "Station:"). IEM's daily summaries for the MT_ASOS network (the daily maximum gust): the two nearest stations to the tile centre within 40 miles, and the days at 50 kt (58 mph) or more. Readings at 130 kt or more are left out as implausible and counted, because the station list carries no quality flag. Whole numbers only (D18): kt to a whole knot and mph to a whole mile per hour, both from the unrounded knots and rounded half up, printed as "{kt} kt ({mph} mph)". Known gaps: the source of the daily maximum is not documented, and 29,558 of 29,568 non-whole-knot values match whole miles per hour (research), so the words never say "measured"; a station is at the airport; of the 60 stations, 38 returned rows in the research's June 2025 sample; IEM's "None" is missing; the research did not state the day boundary of the daily summary, and that check is open in the record. In the window the store holds 1,261 station days at 50 kt or more, and 3 readings at 130 kt or more were left out as implausible (the index's counts).
- *The joined kinds, exactly (D34, round 6; D35, round 7).* B2 joins these kinds and no others; the store figures are the round-7 rebuild's (the Budget bullet below). Reports: every LSR type the archive returns within 5 miles. Records: NCEI hail and thunderstorm wind points within 5 miles, and NCEI zone-coded rows of every type for the cell's public forecast zone. Detections: the SWDI hail signatures within 2 miles. Warnings: the polygons of severe thunderstorm (SV.W), tornado (TO.W) and flash flood (FF.W) warnings that covered the cell. Zone products for the public forecast zone: high wind (HW.W), winter storm (WS.W), blizzard (BZ.W), ice storm (IS.W), extreme cold (EC.W), wind chill (WC.W), dust storm (DS.W), wind advisory (WI.Y) and flood watch (FA.A). Zone product for the fire weather zone: red flag warning (FW.W). Ten products in all; flood warning (FL.W) is not one of them. Stations: the daily peak gusts at the two nearest MT_ASOS stations within 40 miles. The tornado, flood, flash flood, heavy rain, funnel cloud, lightning and debris flow types already appear among the reports, when someone sent them to the NWS; what B2 does not join is NCEI's county-coded records of those types (next bullet).
- *Not joined in B2; B5 adds them (D34, round 6; D35, round 7).* The counts are for the window 2021-10-19 to 2026-10-19. IEM counts are events and NCEI counts are rows. The IEM counts are the research's (`/home/user/wt/research-b35/flood-ice-heat-products.json`); the NCEI counts were computed from the cached NCEI files (verification record, note 41).
  - *NCEI county-coded records within 5 miles* (points, under the 5-mile rule as for hail): tornado 13, flood 60, flash flood 52, heavy rain 85, funnel cloud 30, lightning 6 and debris flow 10, 256 rows in all. The 2020 to 2026 totals are 17, 76, 60, 144, 35, 8 and 11. The IEM reports of tornado, flood, flash flood, funnel cloud, lightning and debris flow are joined as reports in B2: the store holds tornado 10, flood 115, flash flood 68, funnel cloud 45, lightning 6 and debris flow 15 report points (round-6 checker, Montana, the window).
  - *Flood products, polygon path (B5):* flood warning (FL.W) 43, areal flood warning (FA.W) 37, areal flood advisory (FA.Y) 548, flood watch (FL.A) 35 and flood advisory (FL.Y) 10, 673 events in all. *County-only (B5's county path):* flood watch (FA.A) 18 and flash flood watch (FF.A) 2. Two products are named flood watch: FA.A, whose zone-coded events B2 joins, and FL.A, a polygon product that B5 joins; the codes tell them apart.
  - *Snow squall:* snow squall warning (SQ.W, polygon) 78.
  - *Winter, heat, frost and freeze zone products:* winter weather advisory (WW.Y) 865, winter storm watch (WS.A) 226, heat advisory (HT.Y) 58, excessive heat warning (EH.W) 4, excessive heat watch (EH.A) 3, frost advisory (FR.Y) 14 and freeze warning (FZ.W) 4, 1,174 events in all. Blizzard watch (BZ.A), lake effect snow warning (LE.W) and hard freeze warning (HZ.W) have no events in the window.
  - *Left out of B2:* FL.W, which the zone path finds no event for (its rows carry no zone code), and FA.A's 18 county-only events, which B5's county path takes. FA.A's 64 zone-coded events in the window are joined again (D35).
  - *Open, not in the hand-off:* FF.A's zone-coded events, 18 in the window (open item 17); the high wind watch (HW.A, 277 events) and the blowing dust advisory (DU.Y, 3), which the B5 brief lists in its zone path (open item 18).
- *Corrected in round 6 (D34).* Two claims were wrong. (a) ZONE_PRODUCTS listed FL.W and FA.A as joined zone products, and the first version of this entry listed flood (FL) and flood watch (FA) among the zone products. B2 finds no FL.W event: its 62 polygon events carry no zone code, so the zone path drops them. It kept the 64 zone-coded FA.A events in the window and dropped the 18 county-only ones. A viewer could read a missing flood warning as no flood warning, so both leave ZONE_PRODUCTS under D34. (b) The research read the brief's NCEI row (line 20) as naming tornado and flash flood among the records. That row, as the brief file reads now (the file was last edited at 04:37 UTC, after the research record of 03:46 UTC), names hail and thunderstorm wind points only, and the words and the code agree with it. The gap is real: NCEI's 17 Montana tornado and 60 flash flood rows for 2020 to 2026 are county-coded points, B2 drops them, and B5 takes them.
- *Corrected in round 7 (D35).* D34 removed FA.A on a misreading. The research's note "FA.A county-only events (18 in window)" names the exception, not the rule. The window has 82 FA.A events: 64 with zone codes and 18 without. Round 4's build placed 491 FA.A zone events over the 83 public zones, all beginning in the window (a zone event is one VTEC event in one zone), so the round-6 rebuild dropped them and the public zone events fell from 4,960 to 4,469. D35 returns FA.A to ZONE_PRODUCTS under the name flood watch, keeps FL.W out, and sends the 18 county-only events to B5's county path. The round-7 rebuild restores the figures in the Budget bullet below and in the open items.
- *Not joined, and why.* SPC reports derive from the same NWS local storm reports, so joining them would count each report twice. The HRRR modelled gust is a model value, not a reading; a later stage may add it, labelled as a model. The NWS damage survey points (DAT) are few in Montana (64 points, 5 lines and 4 polygons inside the Montana outline, per the research), and the sheet uses "damage" only as the NWS wrote it (see "Words and their limits" below).
- *Data layout (4).* Under `store/hail/`, beside B1's `t/` shards and `index.json`:
  - `j/events.json` (`hail-events-v1`): every report, NCEI point record and warning in the window, once each, in the fields the index's `shapes` gives.
  - `j/r{tr:04d}_c{tc:04d}.json` (`hail-joins-v1`), one per B1 tile: the indexes into `events.json` of its reports and records (sorted), its radar detections in full, its warnings as an index and a cover of 25 hex digits (bit k is set when the centre of cell key k lies inside the polygon), its public zone map and its fire zone map (zone code and cell keys), and the two nearest stations within 40 miles of the tile centre, with their miles. The brief's layout put the rows inside each tile. The joins module's note records that this needed 67.6 MB against the 40 MB budget, so the rows are written once and the tiles index them.
  - `z/MTZ###.json` (`hail-zone-v1`), one per current Montana public forecast zone: the zone's name, its NWS products (each with its begin `b`, its end `e` and `st` "cancelled" or "upgraded" when a cancellation or upgrade row set the end) and its NCEI zone rows.
  - `z/fire-MTZ###.json` (`hail-zone-v1`, kind `fire`), one per fire weather zone: its name and its red flag warnings in the same event shape (D7, D17).
  - `s/<station>.json` (`hail-station-v1`), one per MT_ASOS station: its name and position; its days at 50 kt or more as `[day index, mph, kt]`, whole numbers (D18; the day index counts from 2020-01-01, as in B1); and the count of readings left out as implausible.
  - `hail/index.json` gains a `joins` block: `state`; `parts` (`loaded`, `partial` or `unavailable` for reports, records, detections, warnings, zone products and station readings); `reasons`; `partial` (the periods that failed); `lags` (the newest NCEI event, SWDI detection and warning day); the counts; the malformed and short row counts (D10, D21); the zone editions; the report types; the request summary, with `served_from_cache_since` for each source whose stale copy was used, and its first failures; the Montana clock transitions; the bytes.
  - `hail/manifest.json` lists every `j/`, `z/` and `s/` file with its bytes and SHA-256, beside B1's entries.
- *Budget.* The brief sets `j/` at most 40 MB and `z/` and `s/` under 2 MB. B1 sets all of `hail/` at most 60 MB, and the B1 record measured `hail/` at 32,719,677 bytes. The round-4 re-check of 2026-10-19 measured the build's sizes, and the round-7 rebuild measures the same j/, z/, s/ and hail/ totals: `j/` 19,912,416 bytes in 4,598 files (49.8 percent of 40 MB), of which `events.json` is 5,351,807 bytes and the 4,597 tile files are 14,560,609 bytes; `z/` 919,402 bytes in 115 files (83 public zones holding 4,960 zone events and 32 fire weather zones holding 660), and `s/` 22,478 bytes in 60 files (1,261 station days at 50 kt or more), both against 2 MB; all of `hail/` 54,227,125 bytes in 9,372 files, against B1's 60 MB (90.4 percent); the release tar 12,876,689 bytes in the round-7 rebuild (12,876,467 in round 4); and a flag-on site of the same store, 58,098,447 bytes in 9,466 files, against 2,464,186 bytes in 94 files with the flag off, an increase of 55,634,261 bytes (both builds use `--sample` pages; these site figures are the round-4 measures and were not re-measured in round 7). The re-check measured every file, and the sizes in ROADMAP and in DESIGN section 9 are the same measurements. Round 6 (D34) had changed the zone products (z/ 875,220 bytes; 4,469 public zone events). Round 7 (D35) restores FA.A: the round-7 counts file gives z/ back at 919,402 bytes and 4,960 public zone events, 452 products unplaced (456 rows) and 447 cancellation rows at 00:00 UTC across the public and fire rows; j/, s/ and t/ are byte-identical to round 6 (the round-7 counts file), and hail/ measures the same 54,227,125 bytes in 9,372 files. B5 measures (D38; read from the file sizes of the products store, `store-ready.json`, announced 16:49 UTC on 2026-10-19): `j/` with `j/e/` is 86,247,482 bytes raw, 86.2 MB (`j/` 23,164,558 bytes in 4,598 files and `j/e/` 63,082,924 bytes in 4,597), against the 40 MB cap; all of `hail/` is 161,961,394 bytes in 19,269 files, 162.0 MB, against the 60 MB cap; `z/` is 1,793,693 bytes in 115 files (the 919,402 above is the round-7 figure, now superseded; still under 2 MB); `s/` is 25,000 bytes in 60 files. B5 breaks both caps. The owner or the supervisor rules on both (D38, O12), and nothing in the store changes before that ruling.
- *The daily job's joins step, its cache and its clock.* `.github/workflows/hail-store.yml` runs the joins after the store is built and verified. It restores the joins' download cache (`actions/cache`, keyed by month with a fallback key), runs `python -m website.joins build --store store --cache joins-cache --procs 4`, runs `python -m website.joins verify store`, and then packs and uploads as before. It installs pyshp with the other packages; the site build never imports it. The cache holds raw downloads only, and a cold cache fetches everything.
  - *Cache (D10, D15).* A response is cached only after its content check passes (the CSV header, or the shapefile's members). The re-pull windows bypass the cache: the last two months of LSR and SWDI, and the current year's warnings, zone products and station days (in January, the previous year's too). Each is fetched fresh, and the fresh copy is written over the cached one. The cached copy is used only when the fresh request fails, and the index's sources block then records "served from cache since" the day of that copy. The NWS zone page, the fire zone page, the NCEI listing and the station network list are read fresh at every build. NCEI files are keyed by the name in the listing, so a new creation stamp is a new download; zone and fire editions are keyed by their file names.
  - *Time limit (D23).* `JOINS_DEADLINE_S` is 35 minutes, counted from the start of the joins build; the job's timeout is 60 minutes. After 35 minutes no new request is made: each request not made is recorded as "the source did not answer", its part becomes partial or unavailable, and the store still builds.
  - *Failures.* A source that fails marks its part `partial` or `unavailable` with the reason. A crash in the joins build or verify fails the job before the upload, so the last published release stays. Gate B2-8 asks for two runs from one cache to give byte-identical `j/`, `z/` and `s/` files. In the re-check, two offline joins builds from one cache of 1,152 files gave byte-identical `j/` (4,598 files), `z/` (115) and `s/` (60) in 96 s and 100 s, and both verify runs passed (22 of 22 checks). B1's cold store build took 539.8 s (its record). The cold joins run, with an empty cache that fetches everything, is not measured; it stays open in the verification record.
- *States.* Each part has one state, set by its requests. *Loaded:* every request answered and parsed. *Partial:* some requests failed (for example, one month); the rows from the periods that loaded are shown, and a sentence names the periods that did not. *Unavailable:* every request failed, or the part's table could not be read. The joins state in the index is `unavailable` when every part is unavailable, `partial` when any part is partial or unavailable otherwise, and `loaded` when all six are. If the joins cannot be read at build time, the build writes an unavailable joins block, and each section says so.
  - *The sentence for a part that did not load (D20, D2).* Exactly, in Python and in the browser: "{Part} could not be loaded in this update; that is not the same as no {part}." The six parts give: "Reports could not be loaded in this update; that is not the same as no reports."; "Records could not be loaded in this update; that is not the same as no records."; "Detections could not be loaded in this update; that is not the same as no detections."; "Warnings could not be loaded in this update; that is not the same as no warnings."; "Zone products could not be loaded in this update; that is not the same as no zone products."; "Station readings could not be loaded in this update; that is not the same as no station readings." The reason is kept in the index (`reasons`), not in the sentence. The part's section shows no rows under it.
  - *The partial sentence.* "Data unavailable for some periods: {feed} did not load for {periods} ({reason}). This is not an all-clear." It sits above the rows that did load. D20 defines the unavailable sentence only; open item 14 covers the words.
  - *Empty parts.* An empty part is never a blank section; it shows its "no ... within" sentence.
- *Words and their limits (5, 6).* A report says what was sent to the NWS; it is not an inspection and not a finding about a roof. A detection is the radar algorithm's signature for a storm cell, not hail on the ground. A warning's tags are the forecast threat at issue time, not what fell. A zone product covers the whole zone, named, not this spot alone. A station reading is at the station (the airport), not at this address. A report's remark and a warning's tag are the NWS's own words about the report or the forecast threat, not a finding about this address (D4). The word "damage" appears in three places only: in the NWS damage threat tag, shown as "NWS damage threat tag: {value}" with the value the warning gave; in a report remark quoted as the NWS office wrote it, introduced by "Remark, as written:" in quotation marks; and as a source's own type word. No type word in this build contains it; the LSR archive writes "dmg" ("tstm wnd dmg", "non-tstm wnd dmg"). The forbidden-term test allows "damage" only in those three places. "No report", "no record" and "no warning" are said with what they do not show: a complete record, or a spot outside every polygon. No word says all clear, insurance, eligibility or "no hail" as a fact.
- *Rows and labels (D3, D9, D19).* Every row starts with its label: "Report:", "Record:", "Detection:", "Warning:", "Zone product:" or "Station:". The browser fills the label from the same template as Python. A report or record row shows a magnitude only for a type that carries a unit: hail, rain, snow, the gust and sustained-wind types, and the NCEI thunderstorm wind, high wind and strong wind types, which the map block lists as `unit_codes` (D19). A unit type with no number reads "no size given". Every other type gets the typed row, which shows the type word and no number, and never "no size given".
- *Time.* The store and the joins are UTC. Every shown time is Montana time with its zone abbreviation (MDT or MST), converted from the instant. LSR and warning times are UTC in their archives. NCEI's begin time is local standard time, MST-7: UTC is that time plus seven hours, and the words then show Montana time. The research's note on NCEI's PDF says it does not state whether daylight time is used; the summer pairs under Official record are the evidence for the gap. On the research's pairs, the MST-7 rule matched 1,713 of 1,921 NCEI and LSR pairs (89.2 percent) to the minute. Detections group by SPC day (12:00 UTC to 12:00 UTC the next day), as in B1. A station day is the day IEM's daily summary gives; the research did not state that summary's day boundary, so the re-check checks one station's day against its hourly readings before the words are relied on. A row that crosses midnight shows both dates (D13).
- *Qualifier words.* The brief fixes "estimated", "measured" and "unknown", IEM's changelog definitions. The research also recommended "provisional until the code is verified" (`evaluation-and-wording.json`, qualifier labels). That label is not shown; see open below.
- *Built on `claude/hail-b2`, not merged.* From `claude/hail-b1` at 7aec754: `website/joins.py` (the pulls and their cache, the parsers, the zone shapefile readers for public and fire zones, the joins per tile, `z/` and `s/`, the index and manifest, `verify`, the words in `WORDS_JOINS`, the map block); `website/build.py`, the templates and `website/sources.py` (six contract rows, one per source); `website/static/map/map.js` (the six sections, the distance filter and the templates, documented in its header); `.github/workflows/hail-store.yml`; the fixture's `j/`, `z/` (public and fire, including `fire-MTZ117` and `fire-MTZ128`) and `s/` files (real rows, under 50 KB); `tests/test_joins.py` and additions to `tests/test_site.py`; and the docs. The gates and their results are in `research/hail-history/validation-evidence/b2-verification.json`, pending the re-check. Gate B2-1 closes B1-4 when it passes; its text is D1's two-cell wording (Benchland's report cell and the hail gate cell).
- *Open, for the owner or the supervisor.* (1) B3's byte budget: B3 writes address shards into the same `hail/` store, which B1 caps at 60 MB for all of `hail/`; the B3 brief targets under 60 MB on disk for the address total. The owner or supervisor sets how that cap applies before B3 is built. B2 is checked against both limits at the sizes the re-check measures. (2) The `j/` layout as built (rows once in `events.json`) against the brief's layout (rows in each tile). (3) Fetches per click: up to seven on a page's first click (the B1 shard, the events table, the tile, the public zone file, the fire zone file and up to two station files), against the two to four the work order expected; fewer needs the events table or the station files inlined, which changes the contract. (4) The qualifier words. (5) Settled by D3: every row starts with its kind label, and the section headings keep the long form. Gate B2-3 checks the labels on every row. (6) Settled by D24: the reports' what-this-is sentence says that a report is not an inspection (`WORDS_JOINS` `reports_what`), and this entry and DESIGN.md section 9 say the same. (7) Settled by D14: the build pulls each calendar month the window touches, which is 61 months for the window that ends 2026-10-16 (62 for some windows), and this entry states that count. (8) Flood watch: the brief gives significance W; the build reads FA at significance A, the watch's own significance. The supervisor accepts that or changes it. Round 7 (D35) keeps FA.A in B2 on the zone path, so the significance question stays with B2. (9) The EXP rule, and warnings in effect for a county whose polygon missed the spot. (10) Whether the words state NCEI's summer offset. (11) Cancellation-only zone events. D16's "start not recorded" is superseded by D25 and D30: such an event begins at the earliest issue time its rows carry. A recount of the cached zone files on 2026-10-19 reproduces the window's figures under the build's key: 3,687 cancellation-only groups in the window (3,411 public and 276 fire weather), of which 446 public groups begin at 00:00 UTC and 2,965 public groups begin at other times. Of the 446, 298 begin on the day after the date of their earliest product time (`utc_prodissue`). The open choice is whether those 446 stay as the archive gives them or are blanked to "start not recorded", because a 00:00 UTC value may not be a real issue time. Blanking all 3,687 is not the rule under D30. The round-7 rebuild restores FA.A; its counts file does not re-count these groups, and it reports 447 cancellation rows at 00:00 UTC across the public and fire zone rows (`zone_can_midnight_rows`, a row count, not the group count). (12) Fire weather zones and D8. D8's nearest-edge rule is applied to public zones only. In this build 930 Montana cells have no fire zone, and 337 of them also have no public zone; those cells read "The fire weather zone for this cell could not be determined." The build reads only the newest fire zone edition (today fz16ap26.zip). The older one (fz18mr25.zip) was compared in review: its 32 Montana zones have the same codes, names, attributes and outlines as the newest edition's 32, and all 32 red flag codes in the cache are in both, so red flag rows placed on the newest edition are the same as on the older one. The two editions differ outside Montana, which the build does not read. The editions question is closed; the D8 question is not. The supervisor decides whether D8 applies to fire zones. (13) The missing-part sentence. D2's example reads "no report"; D20's template, with the part's name, gives "no reports", and the docs follow D20. The build's current words print the singular, so either the words change or D20 does. (14) AGENTS.md rule 5 asks for "Data unavailable" when a missing input is shown. D20's unavailable sentence does not use those words, while the partial sentence does. The supervisor decides whether D20 amends rule 5 for a part that did not load. (15) Re-used event numbers (D30). An event number that NWS re-used for separate periods in one zone is one event key, so its periods read as one span, and a period outside that span is not listed. Four zones in five years do this. In MTZ004 WS 2024 the continuation begins on 11 January, after the cancellation of 10 January, so the one event reads "cancelled at" a time before its own begin. In MTZ320 WS 2023 an expiration product after the cancellation is not listed. In MTZ003 WS 2021 the span runs from an expiration product to a later cancellation. In MTZ302 HW 2022 the second cancellation is not listed. The choices are to split an event where a row follows its cancellation or upgrade, or to keep the one-event key and say the limit in the words. The owner or supervisor decides. Review decision D33 (round 4 of the B2 review) sets the period rule, which B5 implements (item 16). (16) Re-used event numbers: the rule for B5 (review decision D33, round 4). B2 ships with D30's one-event key, so the limit in item 15 stands, with four cases named: MTZ004 WS 2024 event 1 (a CON on 11 January after a CAN on 10 January is not shown as its own period); MTZ302 HW 2022 event 38 (its second cancelled period is not shown); MTZ320 WS 2023 event 4 (the expiry period after the cancellation is not shown); and MTZ003 WS 2021 event 12 (its two periods read as one span). B5 implements this period rule, and its brief carries it as a must: within one event key, rows ordered by product time; a CAN, UPG or EXP closes the current period; a later NEW, CON, EXT, EXA or EXB opens the next; each period is its own span. (17) FF.A's zone-coded events. 18 of the 20 FF.A events in the window are zone-coded. B2 does not join them, and neither D34 nor the B5 brief names them. The owner or supervisor decides. (18) HW.A and DU.Y, and three codes with no events. The B5 brief's zone path lists the high wind watch (HW.A, 277 events in the window) and the blowing dust advisory (DU.Y, 3). D34's list does not, and neither does D35's list of ten products; this entry follows both. The blizzard watch (BZ.A), lake effect snow warning (LE.W) and hard freeze warning (HZ.W) have no events in the window: keep or drop. (19) The B5 brief's NCEI counts (76, 60, 144, 17, 35, 8 and 11) are 2020 to 2026 totals. The window counts are 60, 52, 85, 13, 30, 6 and 10 (256 rows). B5's gates should say which one they use. Round 7 (D35) closes items 17, 20 and 21 of the round-6 list (FA.A, the rebuild and the name) and renumbers items 18, 19 and 22 as 17, 18 and 19; the verification record uses these numbers.

*Why:* decisions 2 and 6 ask for every kind of weather at the address in the same popup, and decision 4 asks for updates that are recent and consistent. The radar estimate answers one question. The other kinds explain a day: a report that matches it, a warning that covered the spot, a station that gusted that day, a zone product for the whole zone. The kinds stay apart because each has its own gaps and its own meaning, and one count of events would hide them. The joins ride the daily job, so they publish with the store, and the 10-minute build reads them with it (decision 4). The byte budget is the cost, and the owner should choose which limit moves before B3 adds address shards to the same site.

**D38 · The past weather of every location (B5, 2026-10-19).** Within this entry, D1 to D30 (such as D1, D8, D11, D19 or D27) cite the supervisor's B5 review rulings, which are not entries of this log, as D35 does for B2. The owner's seven decisions are D34's, cited there by number. D36 (B3) and D37 (B4) arrive with their own branches and are not in this file yet.

Carson's request of 2026-10-19, quoted once:

"find the history of the locations past weather reports like the size of hail, wind, storm history, temperature highs and lows, Snow amounts annually, Rain annually, any flooding, and weather that would be an issue for a roof as well."

What it serves. It is D34's decisions 1 (trailing five years), 2 and 6 (a history at every address, with every kind of weather in the popup), 4 (recent and consistent), 5 (units read and made understandable) and 7 (follow the laws). The request adds the kinds D34 did not name: temperature highs and lows, rain and snow by year, flooding, ice and winter, heat, wind, and the weather that matters for a roof. B5 builds them behind `--hail-history`, with one summary table that leads the sheet.

What it settles:

- *Sources (eight), with their terms as the module docstrings and the records give them.*
  1. **NOAA nClimGrid-Daily** (`website/climate.py`): daily precipitation, highest and lowest temperature on NOAA's 1/24 degree grid, 25,902 Montana land cells. The file attribute reads "license = no restrictions". The registry, as the module quotes it: "NOAA requests attribution for the use or dissemination of unaltered NOAA data. However, it is not permissible to state or imply endorsement by or affiliation with NOAA. If you modify NOAA data, you may not state or imply that it is original, unaltered NOAA data." No NOAA page checked calls these grids public domain, so the page does not say so.
  2. **NOHRSC National Snow Analysis, season-total snowfall** (`website/snowgrid.py`): one GeoTIFF per water year, 0.04 degree, 2021-22 to 2025-26 (11,562,084 bytes). The NWS terms, as the live page read on 2026-10-19: "The information on National Weather Service (NWS) Web pages are in the public domain, unless specifically noted otherwise, and may be used without charge for any lawful purpose so long as you do not: 1) claim it is your own (e.g., by claiming copyright for NWS information -- see below), 2) use it in a manner that implies an endorsement or affiliation with NOAA/NWS, or 3) modify its content and then present it as official government material." And: "As required by 17 U.S.C. § 403, third parties producing copyrighted works consisting predominantly of the material appearing in NWS Web pages must provide notice with such work(s) identifying the NWS material incorporated and stating that such material is not subject to copyright protection."
  3. **GHCN-Daily from NCEI** (`website/stations.py`): one `.dly` file per station at `https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/<ID>.dly`; the S3 copies are stale for SNOTEL and airport stations. "These data are in the public domain in the United States." (NCEI-PD-10-2-02, section 4(a)). CoCoRaHS records (file prefix US1): "Unless otherwise noted, all CoCoRaHS content and data are released under a Creative Commons Attribution 3.0 License", and the source is to be acknowledged. Archive timing, from the NCEI product page: "Generally, real-time replacement of updated data streams are replaced by archive-ready data sources 45 to 60 days after the end of a month."
  4. **IEM watchwarn archive** (`website/joins.py`): the polygon products (FL.W, FA.W, FA.Y, FL.A, FL.Y and SQ.W; SV.W, TO.W and FF.W from B2), the zone products (HW.W, WS.W, BZ.W, IS.W, EC.W, WC.W, FW.W, DS.W, WI.Y, FA.A, WW.Y, WS.A, HW.A, HT.Y, EH.W, EH.A, FR.Y, FZ.W, DU.Y and FF.A) and the county-only FA.A and FF.A events. "The materials found on this website are in the public domain and may be used freely by anyone for any lawful purpose." "Attributing the Iowa Environmental Mesonet of Iowa State University would be appreciated." "We therefore provide this information without any warranty of accuracy." The NWS sentence the module quotes: "The information on National Weather Service Web servers and Web sites is in the public domain, unless specifically annotated otherwise, and may be used freely by the public." And: "You also cannot present information of your own in a way that makes it appear to be official government information."
  5. **NCEI Storm Events** (`website/joins.py`): county-coded point rows and zone-coded rows. The 2020 to 2026 totals are Flood 76, Flash Flood 60, Heavy Rain 144, Tornado 17, Funnel Cloud 35, Lightning 8 and Debris Flow 11 (351 rows). The licence text was not read in this run (the NCEI terms page returned 503 in the research), and the page says so.
  6. **IEM local storm reports** (`website/joins.py`): the same IEM sentences as source 4, since the archive is IEM's. Magnitudes for codes 5, 6, 7, I and J are not shown until the IEM documentation confirms their units; the remark is shown as written.
  7. **NWS NWPS and USGS river gauges** (`website/gauges.py`): the flood categories from NWPS, and the annual peaks from USGS (parameter 00065, from api.waterdata.usgs.gov; waterservices.usgs.gov is retired on 2027-02-22). "Observations courtesy of U.S. Geological Survey." The NWS terms are as in source 2.
  8. **Census TIGER/Line 2026 counties** (`website/joins.py`): the county file's own use constraint, matched to its ISO metadata: "The TIGER/Line shapefile products are not copyrighted; however, TIGER/Line and Census TIGER are registered trademarks of the U.S. Census Bureau. These products are free to use in a product or publication, however acknowledgement must be given to the U.S. Census Bureau as the source."
- *Left out, and why.* FEMA flood zones: a hazard and insurance designation, not a weather event (AGENTS rule 5); the owner and counsel first. Lightning strike data: commercial, and the national network is restricted (R18). PRISM: Oregon State keeps ownership. Daymet: licence unconfirmed. gridMET: a possible later supplement with PRISM attribution, not in B5. SNODAS: its solid precipitation is model output, not snowfall, and five years of its daily files come to about 19.6 GB at the 2025 mean (`snow-alternatives.json`). SNOTEL: access restricted (the Data.gov record says to contact the publisher); the SNOTEL site the station rule uses, Crystal Lake (USS0009C01S), is read from the GHCN copy, and counsel is asked to clear that (Stanford, USC00247864, is a COOP station, not a SNOTEL site). UV and sunlight, roof surface temperature and ponding have no public record for a spot; each gets a "Data unavailable" line. Ground snow load is a design value, not history, and the history never shows it.
- *Grid estimate and station reading.* A grid estimate is a value for a cell about 4.6 km across, not a reading at the address. A station reading is a value at a named station, and the page shows its distance. Billings shows the gap: the grid cell counts 104 freeze-thaw days in calendar 2025 and the airport 73 (GHCN), and the grid differed from the airport by 18.8 mm in July 2025 and by 1.0 C on one day. The kinds are never added or merged. Where both appear on a town page, each keeps its own kind word and the page does not reconcile them (D13).
- *Thresholds (D1 and D19).* One rounding rule covers every temperature rule: the daily grid value is rounded to the hundredth of a degree C, and the tenth GHCN stores is taken from it. A day at or above 90 F has a high of at least 32.15 C, which shows as 32.2 C and 90 F; 32.14 C does not count. A freeze-thaw day has a high above 32 F and a low below 32 F. A day with a low below 32 F has a low below 0 C. The page says this once. The first research counts were wrong: they used 323 tenths and 25.4 mm, which drop days that GHCN records as 322 tenths and 25 mm. The corrected Billings airport counts for 2021-22 to 2025-26 are days at 90 F or more [45, 42, 27, 35, 25] and days with 1 inch of snow on the ground [55, 70, 30, 53, 25] (gate B5-9).
- *Coverage (D5 and D18).* A station is a candidate within 40 miles (great-circle). For each element it is current only when it reported that element in the 30 days to the as-of day (D18), and it needs an unflagged value on at least 80 percent of the 2,192 days from 2020 to 2025 (the coverage share, per element). The two nearest that pass are used. With one, the page shows it and says so; with none: "No station within 40 miles has enough reports for {element} from 2020 to 2025." A season value shows only when 95 percent of its days have the element, and every station's share is shown. A missing day is never zero. A quality flag excludes a value. A trace is zero in sums, and the page says so. The worked case is Benchland's snow: Lewistown 11 SSE (31.1 miles, 90.0 percent) has no snow report in the last 30 days (its last is 2026-05-18), so Harlowton 11NW (34.8 miles, 99.5 percent) replaces it under D18. Stanford's snow, 79.9 percent, misses the 80 percent rule by 0.1 point, so it is not used there, and the gate shows its share.
- *Store layout.* Under `store/hail/`, beside B1's `t/` shards and B2's `j/`, `z/`, `s/` and `k/`:
  - `c/rRRRR_cCCCC.json` (`hail-climate-v1`): for each B1 tile, the Montana climate cells whose centre lies in it. Each cell has its five July to June seasons, six calendar years and seven water years, each a list of 13 integers (rain in hundredths of an inch, temperatures in tenths of a degree F, dates as yyyymmdd, null where no day has a value). 4,569 files, 35,149,062 bytes (D25: median 8,038 bytes raw, 1,705 gzip).
  - `sd/<station>.json` (`hail-stn-v1`): per station and element, per season and calendar year, the day counts of D5, and the season highest high and lowest low with their dates. 571 files, 3,071,175 bytes.
  - `g/<usgs>.json` (`hail-gauge-v1`): the stages and the water-year peaks of each gauge in scope. 104 files, 285,713 bytes, 7,560 peak rows.
  - `k/MTC###.json`: the county-only FA.A and FF.A events. 56 files, 13,689 bytes.
  - `j/e/r{tr:04d}_c{tc:04d}.json` (`hail-events-tile-v1`, D30): the events that tile's file refers to, in the events table's row shapes. 4,597 files, 63,082,924 bytes raw, 10,423,190 bytes gzip in all; the largest is 22,933 bytes gzip against a budget of 100,000. Each event is copied into every tile file that refers to it: the 4,597 files hold 453,855 references to 48,763 events (43,510 reports, 2,097 records and 3,156 warnings), which is why the files come to 63.1 MB. Proposed, not built, for the ruling on the caps (O12): one table for the 3,156 warnings (about 0.5 MB), and each report and record stored once in the shard of its own tile, with a tap fetching the shards its joins name. The review's estimate for that layout is about 29 MB for `j/` and about 105 MB for `hail/`, so the 60 MB cap would still need its own ruling, or the climate `c/` (35 MB) and `t/` (32 MB) would need cutting. It would also change D30's one-file-per-tap rule. Dropping `j/events.json` (6,083,996 bytes raw, about 0.85 MB gzip) from the site copy waits until part B2 stops fetching it (D22). `--hail-history` stays off `main`: `website.yml` passes it on branches only.
  - `n/<tile>.json` (`hail-snow-v1`): NOHRSC values in hundredths of an inch, written only when the unit check passes. It does not pass (D7), so `n/` is absent.
  - `index.json` blocks `climate`, `stations`, `gauges` and `snow`, each with its state, problem, counts, sources and words. The county counts sit in the `joins` block. `manifest.json` lists every new file with its bytes and SHA-256.
- *Backfill once, and its asset.* The 63 scaled months, July 2021 to September 2026, are read once. Each file (57 MB a month) is downloaded whole, aggregated per cell and deleted once its aggregates are written. The aggregates for the 64 months, the 63 scaled and the 2026-10 prelim, come to 16,013,234 bytes. The aggregates, their ledger and a manifest of every member's SHA-256 form the release archive (15.9 MB), published on the `hail-climate` release under a versioned name, `climate-aggregates-RUNID.tar.gz`, where RUNID is the run id of the daily run that wrote it. The store job restores the newest archive that unpacks (the highest run id; the first fixed name, `climate-aggregates.tar.gz`, is read only as the oldest), runs the update (the prelim days by Range reads, about 1.4 MB a day, and any new scaled month when NOAA posts one), builds the store, packs a new archive and publishes it. The upload has no `--clobber`: the job downloads the copy it uploaded and unpacks it into a scratch cache, where every member's SHA-256 is checked, and only then removes the older archives. A copy that does not unpack is removed at once, so the restore keeps the last good archive; an interrupted upload leaves the previous archive in place. The backfill itself is one manual run with its input on, and a run with no archive skips the update, so the backfill is never repeated by accident. Measured: the whole backfill took 222 s for 63 months and 3.72 GB (the builder's record), and a daily update with no new scaled month took 7 to 8 s.
- *Period rule (D8).* Zone rows of one VTEC event are taken in product order. A CAN, UPG or EXP closes the open period; a NEW, CON, EXT, EXA or EXB opens the next one. Each period is a span, and "cancelled at {time}" or "upgraded" replaces the end, as in D9, D26 and D31. All eight periods of the four named cases check out: MTZ004 WS 2024 event 1 (cancelled 2024-01-10 15:22Z, then a continuation from 2024-01-11 12:00Z to 2024-01-12 12:00Z); MTZ302 HW 2022 event 38 (two cancelled periods); MTZ320 WS 2023 event 4 (cancelled 2023-02-22 10:54Z, expired 2023-02-23 01:00Z); and MTZ003 WS 2021 event 12, which begins inside the window (2021-12-19 04:00Z to 15:00Z expired, and 18:00Z to 2021-12-20 03:27Z cancelled). A zone row shared by two yearly requests is kept once, with one seen-set across every year and product (D17): 4,986 copies are dropped, and the 14,703 public zone events carry no identical copy.
- *Polygon rule (D11).* A polygon covers a cell when it intersects the cell, not only when the cell's centre is inside (AGENTS rule 6). The words say "covered this cell or part of it". The centre rule stays as a subset, and the index counts both per product. The part A build adds these cells per product: SV.W +310,012; FA.Y +63,796; SQ.W +11,514; FF.W +11,650; TO.W +1,797; FL.W +3,629; FA.W +3,321; FL.A +3,103; FL.Y +848. No cell that the centre rule covers is lost (zero for all nine products). Town pages test the town point itself, and that can disagree with the cell rule. The 17-town check lists four cases: Belgrade SV.W 2023-08-30 03:01Z; Helena SV.W 2024-08-19 23:51Z and 2025-07-28 20:39Z; Kalispell SQ.W 2022-02-01 23:58Z. A polygon with no outline is never read as "no warning": it joins by its county or zone code when it carries one, and is counted otherwise (no such polygon in the window).
- *Zone editions (D27) and the events per tile (D30).* The zone products issued in 2021 and 2022 carry zone codes that the two current NWS zone editions do not hold: z_18mr25, effective 2025-03-18, and z_16ap26, effective 2026-04-16, the current one. The build asks for the six older editions that the NWS change history names (z_08se21, z_22mr22, z_07se22, z_13se22, z_08mr23 and z_05mr24). On 2026-10-19 each returned HTTP 404 at the address the build uses, so none could place a product. The 1,230 products issued while those editions were in force are counted, not dropped. Each is in the joins index with its product, zone code, day and edition, under the reason "edition_unpublished": WW.Y 368, HW.W 354, HW.A 310, WS.A 57, WS.W 44, HT.Y 34, WC.W 32, FA.A 23, BZ.W 4 and FF.A 4; by edition, z_08se21 828, z_22mr22 379 and z_07se22 23. A product issued while an unpublished edition was in force keeps its zone code and is checked against the current edition, and the zone words say so ("kept"). Whether another NWS address holds the older editions is an open question. The per-tile event files let the browser fetch one tile's events on a tap (D22, D30); `events.json` stays for Python's town pages and verify.
- *The snow analysis, checked and left out (D7, D23).* The NOHRSC file does not print its units. D7 checks them with a regression of station season totals in inches (seasons with at least 95 percent of their days) on the grid values at each Montana station with a complete season. The slope is 0.664 over 682 station-seasons (intercept 12.03, correlation 0.81, RMS residual 17.7 inches), outside the 0.85 to 1.15 band that would support inches. The two Billings cells the research checked (50.29 against 64.3 inches for 2024-25, and 33.85 against 40.9 for 2025-26) do not settle the unit, which is why the regression decides. The analysis stays out: the snow block is unavailable with its reason, `n/` is absent, the snow rows are station readings, and the About page says in one sentence that the analysis was checked against station totals and left out. Whether a different method would be published is the owner's decision (O10).
- *The summary table, and why it leads the sheet.* The north star: one map; one sheet per place that leads with a plain summary; details behind headings in a fixed order; every number next to its unit and its kind word; nothing a roofer has to decode. So the sheet opens with the address line (B3) and one sentence: "Five seasons of weather for this spot, from grid estimates, station readings and NWS records. Each row says what kind of record it is." Then the table: the columns 2021-22 to 2025-26 (July to June) and "Five seasons", one row per measure, each cell with its value, unit and kind word. The rows, in the brief's order and as `website/summary.py` builds them: the largest radar hail estimate and the days of 1 inch or more; the largest hail reported within 5 miles and the report count; peak gusts of 50 knots (58 mph) or more and the strongest gust at that station; wind reports; high wind watches and warnings for the zone; the highest and the lowest temperature; days at 90 F or more; days below 32 F; freeze-thaw days; precipitation and the largest one day; snowfall and the deepest snow; freezing rain reports; winter storm and ice storm warnings; flood and flash flood reports and warnings; and the county's flood and flash flood watches, a row the brief did not list (the county path). The last row is the held line, "Data unavailable", with its reason. The snow analysis is not a row (D23). Below the table come the partial season, one line with its own counts (D20), and the one radar sentence: "Radar estimates can miss hail that people reported and can show hail that no one reported." Town pages add the station's highest and lowest with their dates. A missing or partial season shows its coverage line, "n days missing", never a blank or a zero. The radar and report rows cover the trailing 1,826 SPC days, so 2021-22 shows the days before the window start as missing (D3). The sections follow in a fixed order: Hail, Wind, Storms and warnings, Temperature, Rain, Snow, Flooding, Ice and winter, Heat, Weather that matters for a roof, How this was made. Each has a heading, a lead sentence with its kind word, and rows that begin with their kind label (B2 D3).
- *The roof section's basis.* The roof section reports the weather that roofing references name as stresses. It never says what a roof needs. Its record (`roof-indicators.json`) holds 29 indicators, each with its kind word, unit, source and status, and the references R1 to R20, quoted with their links, which give the thresholds (for example the 1-inch severe hail size and the 58 mph, 50-knot wind). The reference lines are kind "Reference", in the groups "Thresholds", "Snow and ice", "Wind and hail", "Heat and rain" and "Lightning and sun". The record's refuter re-ran the counts, made the corrections above, and stands with conditions: the 322-tenth and 25 mm rules; the freeze-thaw gap stated as a disagreement between sources, not as rounding; the IS.W office (NWS Great Falls); the nine LSR types the first list omitted; the NWS disclaimer conditions; and no derived count presented as an NWS product. The held lines (ponding, lightning, UV and sunlight, roof surface temperature, and the FEMA flood zone, ground snow load and SNOTEL lines, D14) say "Data unavailable" and why. The sheet's reference groups use R1, R3, R4, R5 to R8, R10 to R12, R14 to R16, R18 and R19; R2, R9, R13, R17 and R20 stay in the record.
- *Hail hit-and-miss record (D15).* Every LSR hail report of 1.00 inch or more in the window (737 rows) is set against the MESH maximum in its own cell and the SWDI maximum size within 2 miles. 464 are hits and 273 are misses, each miss under by up to 3.01 inches (median 0.88). In 297 of the 737 (40.3 percent) the report's own cell had a radar estimate of 1 inch or more. The About page says it in words without numbers: the reports were checked against the radar estimate and the radar signatures near each report, and "The radar missed many of them." The fuller summary, "fewer than half" at the report's own cell and "most" with the detections within 2 miles, is `hit_miss_summary` in `WORDS_JOINS`; it has no page yet. Lewistown 2.50 inches (2025-06-15, MESH 0.0 mm) is one of the misses. The row table comes from `python -m website.joins verify` (its hit-and-miss part, not stored in the index); `b5-verification.json` holds the counts and the named cases.
- *Counsel items (B5).* These go to counsel with the B3 questions, from the legal terms review: whether NRCS AWDB values may be published without written NRCS confirmation (question 11; this decides the held SNOTEL item and the Crystal Lake site read from the GHCN copy); the disclaimer and flood-zone wording before any flood layer (12, FEMA NFHL, not read); whether NOHRSC has a product-level data-use statement beyond the NWS terms (13); PRISM and Daymet (14 and 15; neither is used); the Census acknowledgement and the rule against implied endorsement (16); commercial use under the NWS, USGS, IEM, NCEI and NODD texts (17); privacy questions outside MCA 2-6-1017 for the search box, geolocation and analytics (18); and the disclaimers, so the About text does not imply legal accuracy for a business that sells roofing work (19). The NCEI Storm Events licence text is unread (source 5). Per-address gauge lines wait behind the counsel gate (D6); town pages may show them first.
- *Open owner decisions (O4 to O12; O4 to O11 ruled provisionally on 2026-10-19; O12 not ruled).* O4, the gauge distance: 10 miles (the 25-mile alternative covers 69.6 percent of Montana; 5 miles covers 4.8 percent; 10 miles covers 17.3 percent). O5, the thresholds: D1 and D19. O6, the season columns: July to June, with water years labelled for snow. O7 (the phone target) and O9 (footprints with no address, B3) are not ruled for B5. O8, the station coverage: 80 percent to choose a station and 95 percent to show a season. O10, NOHRSC: shown only if the regression passes; it does not, so the analysis is held. O11, the "Data unavailable" lines for lightning, UV and sunlight, roof surface temperature and ponding. Each ruling is one constant in the code and one sentence on the page, and the owner may change any of them. O12, the byte caps (B5 review; not ruled): `j/` with `j/e/` is 86,247,482 bytes (86.2 MB) against the 40 MB cap, and all of `hail/` is 161,961,394 bytes (162.0 MB) against the 60 MB cap. The owner or the supervisor rules on both. The choices are a higher cap, the dedupe proposed under the B2 budget (which changes D30's one-file-per-tap rule), or cutting another part (the climate `c/` or `t/`).
- *Job and budget (`.github/workflows/hail-store.yml`, D26; amended by the job review of 2026-10-19 for the clock and the archive).* Daily: the B1 build and verify; then the B2 joins, which also carry the B5 product pulls (D27, D30), and their verify. The join is fatal by the B2 rule, with `timeout-minutes: 50`: the joins stop new requests at 35 minutes from their own start (JOINS_DEADLINE_S, D23), parsing and writing then take about 7 minutes measured live, and requests in flight add up to about 5 minutes, so 50 minutes is the backstop for a response that trickles past the per-read timeout. Then the B5 steps, non-fatal, on one clock: the first step writes `JOB_START`; the B5 window is 2,400 seconds (40 minutes) from it; a clock step before each B5 step writes the seconds left; a B5 step runs only with more than 60 seconds left; each program it runs is wrapped in `timeout --kill-after=30` at the seconds left; and each deadline is the smaller of its own deadline and the seconds left less 440, because an in-flight request can run about 440 seconds past its deadline. In order: the climate restore (the newest archive that unpacks, see the backfill bullet), the update, the build, the verify and the versioned publish; the station carry, the station readings, the drop, the river gauges, the snow analysis and the verify. Then the pack and the release upload, unchanged. Scopes as D26: every run reads the station list and inventory, the changed files of the chosen stations, the NWPS files missing from the cache, the climate prelim days, and the cached NOHRSC files (no request); the monthly run (the first of the month, or its input) reads the whole station union and the regression set, refreshes the NWPS and USGS files, and asks NOAA about the NOHRSC file. Not built yet, recorded as open: (a) D26 asks for the NWPS list and each pool detail on every daily run; the daily gauges step reads only the files missing from the cache. (b) The station carry and drop are edits to `index.json` that do not refresh `manifest.json`, and the drop removes the block only. A stations run that fails after writing some `sd/` files can therefore leave files the manifest does not list, and the site build would refuse the store. The fix is a tested stations command for the carry and the drop, and a containment step before the pack: run `hail.check_manifest`; on failure, or if containment itself fails, remove `c/`, `sd/`, `g/`, `k/` and `n/` and their manifest entries, set the climate, stations, gauges, snow and county blocks to unavailable with the D16 sentence, name the part removed, and delete hidden `.stations-<8 random characters>` temp files. The fatal B1 and B2 gates (`python -m website.hail verify store`, `python -m website.joins verify store`) come after containment, never before it, because a B5 failure must not block the B1 and B2 publish (D26). (c) The joins are not on the job clock (`joins.py` has no job-clock deadline), so a join that starts about 11 minutes in and uses its full 35 minutes can leave no time before the pack, and the 60-minute cap then binds. (d) The daily total with downloads is not measured, so the 25-minute budget (B5-12) is open, and the byte caps (O12) are with the owner. The release asset `hail-store` keeps its fixed name, because the site build reads `releases/download/hail-store/hail-store.tar.gz`. The 60-minute timeout stands.
- *Built on `claude/hail-b5`, not merged.* `website/climate.py` (the nClimGrid reader, aggregates, tiles, backfill and update, the release archive), `website/stations.py` (the GHCN reader, the station rule, the season figures), `website/snowgrid.py` (NOHRSC and the D7 check), `website/gauges.py` (NWPS and USGS), `website/joins.py` (the B5 phenomena, the county path, the period rule, the polygon cover, the events per tile), `website/summary.py` (the table and the roof lines), `website/build.py` and the templates, `website/sources.py` (the feed rows), the tests (`tests/test_hail_workflow.py` checks the job's clock, timeouts and archive steps), `.github/workflows/hail-store.yml`, and the record `research/hail-history/validation-evidence/b5-verification.json`. As of this entry that record holds 10 gates passing, 4 partial and 4 pending. The browser (part B2) is not built.

- *Part B1 rulings, D31 to D43, applied 2026-10-20.* One bullet per ruling. The figures come from the store rebuilt offline with two processes (`/home/user/hail-b5/out/b1/store-ready.json`, rebuilt 2026-10-20T00:15:32Z). "In place" means the code already did it when checked on 2026-10-20; this part did not change it.
  - *D31, zone editions: researched, not placed.* The NWS publishes two zone editions: z_18mr25 (effective 2025-03-18) and z_16ap26 (current, effective 2026-04-16). The six older editions the build asks for (z_08se21, z_22mr22, z_07se22, z_13se22, z_08mr23, z_05mr24) return HTTP 404 at the NWS address (checked 2026-10-19). The research (`zone-editions.json`, generated 2026-10-19 23:49 UTC) found no full-resolution copy: the archived captures of four files could not be downloaded from this session, the change log gives the dates but no file, and the NWS notification page and the tgftp listings hold none. The IEM archive gives Montana zone sets for every date tested, simplified: 103 MTZ zones through 2022-09-13 12:00 UTC and 83 from 2022-09-13 18:00 UTC. The research recommends them for code identity and coarse placement only, and the full-resolution NWS file before any polygon-precise work. One conflict is open: the change log dates the Montana switch to 2022-09-07 (SCN 22-61), and IEM shows it between 2022-09-13 12:00 and 18:00 UTC. The build does not place by them yet.
  - *Zone placement the build makes (D27, D31).* Placed zone groups: 14,534, of which 785 by the current edition's codes, 3,327 through the mapping of a retired code, and 10,422 by their zone code alone ("kept", disclosed on About). Unplaced: 1,230 groups, each with its reason `edition_unpublished` (828 from z_08se21, 379 from z_22mr22, 23 from z_07se22). The store holds 14,703 zone events. An unplaced zone line reads "Data unavailable: some products could not be placed to a zone. This is not an all-clear." (summary.py:204, in place).
  - *D32, no absence claim from a failed part (in place in the words).* A failed or absent block gives the D20 sentence, which ends "This is not an all-clear." The station words (stations.py:174 to 185) name the candidates whose file did not load: "Station readings could not be loaded in this update for {names}; that is not the same as no station reading. This is not an all-clear." `_named_list` (stations.py:1167) shows the first names in full and counts the rest. A gauge that did not load reads "could not be loaded", with its name and distance, never "none" and never a farther gauge (gauges.py, module docstring). A failed gauge with no listed position never reads as no gauge (tests/test_gauges.py:509). Each tile list keeps every candidate whose file did not load, with its name, position, miles and reason (`unread`). Tests: tests/test_stations.py (TileListTests, line 822) and tests/test_gauges.py (RoutedBuildTests, line 328).
  - *D33, coverage lines and the preliminary label.* The climate partial line reads "Grid estimate, preliminary: {season} so far, ..." and ends "This is not an all-clear." (climate.py:1405 to 1409, `partial_season`). The page's partial line (summary.py `partial_grid`, line 281) reads "Preliminary grid estimate: {season} so far, ..." and ends "The newest days are preliminary and provisional until NOAA publishes the scaled month." It has no all-clear sentence and is open with the summary builder. The Billings 111 F reading is held under D13 and appears nowhere on the pages (0 matches). The re-check's preliminary highs, which carry the provisional caveat, were 112.6 F at Billings and Glendive on July 13, 2026, and 114.8 F at Miles City; the owner confirms that preliminary grid highs may show (below).
  - *D34, flood warnings include the areal flood warnings (in place in summary.py).* The flood and flash flood warning count takes FF.W, FL.W and FA.W that covered the spot's cell or part of it (summary.py, the docstring at line 1814); advisories and watches are not counted. The joins keep FA.W's own name, "Areal flood warning" (joins.py:243), and its "Warning:" label.
  - *D35, distinct SPC days (in place).* A detection row is `[day index, hhmm, lat, lon, size]` (joins.py:2071). Its SPC day is `spc_day` (joins.py:1493), the 12:00 to 12:00 UTC reporting day. summary.py counts the distinct SPC days (`detection_days`, summary.py:2192). No joins row changed.
  - *D36, station picks at the cell (the lists are built; the picks are part B2).* `hail/tl/<tile>.json` (`hail-stn-tiles-v1`, stations.py:146) holds, for each tile and element, up to six passing stations within 40 miles of the tile centre, nearest first (`TILE_LIST_CAP`, stations.py:147), each with its name, position, miles, unflagged days and share, and every candidate whose file did not load (`unread`). 4,597 files, 13,667,217 bytes raw (2,586,828 bytes gzip in all; median 574 and largest 856 bytes gzip). Of the 22,985 element lists, 10,543 reach the cap of six; the longest holds six; the store has no unread entry (`unread_entries` 0). The sheet is to pick the two nearest to the clicked cell's centre from the list (part B2, not built). `verify` records the two picks at each gate point, from the tile that holds the point (`tile_picks`): Billings WTP COOP USC00240802 (1.4 miles) and Billings Logan USW00024033 (2.6 miles) for all five elements; Benchland snow Buffalo 1.7 E US1MTFG0003 (20.9 miles) and Harlowton 11NW USC00243947 (34.8 miles); Benchland depth Stanford USC00247864 (10.9 miles) and Crystal Lake USS0009C01S (31.3 miles).
  - *D37, gust days (the store side is in place; the summary reads it).* `hail/s/<station>.json` (`hail-station-v3`, joins.py:179) carries `periods.season` for the five seasons: `n`, the days in the season, and `ok`, the days with a gust value. 60 files, 34,913 bytes (16,975 bytes gzip); the D37 check in `joins verify` finds no problem. The summary shows a season's gust figures only where `ok` is at least 95 percent of `n` (`_gust_rows`, summary.py:1354 to 1358). The partial 2026-27 season is not in these files: it is a line below the table, not a season list entry (D20). The gust rows were not re-read in a site build in this part.
  - *D38, town polygons (the file is in place; the town pages count from it).* `hail/j/towns.json` (`hail-joins-towns-v1`, joins.py:171; 29,467 bytes) lists, for each of the 17 towns, every polygon warning of the window whose outline holds the town point (the exact test of D11, not the cell), with its event ref, product, office, begin and end (`towns_polygon_file`, joins.py:2679 to 2702): 469 town-event pairs. `verify` compares each town with its cell cover: 0 town events are missing from a cover (the B5-15 check holds), and 12 cover-only events are recorded (the cell rule reaches further than the point). The town pages count from this file ("covered this spot") and the sheet counts the covers ("covered this cell or part of it"); both wordings are in place (summary.py:57, 310 to 312, 1109 to 1110).
  - *D39, town page order (in place).* The five-season history follows the forecast under one heading, with its summary table first (town.html:176, the section after the forecast, with its comment on D39). A jump link near the top of the page links to it (town.html:16). The About text says the same: "The history sits below the town's forecast, under one heading, and a link at the top of the page jumps to it." (about.html:46 to 47).
  - *D40, weight of map.json (in place in build.py).* The climate block lists no tile names: it carries the URL pattern and a compact split map of its tiles. The stations, gauges and county blocks carry their URL patterns only (build.py:783 to 784). The per-tile files are fetched on a tap: `hail/j/e/<tile>.json` (median 1,735 bytes gzip, largest 22,933) and `hail/tl/<tile>.json` (median 574 bytes gzip, largest 856). The phone view at zoom 15 (650 KB gzip, the B5 gate) is measured in part B2.
  - *D41, words.* The unavailable, partial and unplaced lines in the joins, stations, gauges and climate word tables end with "This is not an all-clear." An advisory or a watch row takes its label from its significance, "Advisory:" or "Watch:" (`SIGNIFICANCE_LABEL`, joins.py:173); "Warning:" is for a warning product only, and the row names its product, for example "Areal flood advisory" for FA.Y (joins.py:243). FA.A is "Areal flood watch" (joins.py:240; `KIND_WORDS` takes its kind word from there, joins.py:252). The gauge words no longer repeat "River gauge:" (gauges.py:99). Open, in other owners' files: summary.py's partial-season line (`partial_grid`, no all-clear sentence), its five-season snowfall cell (B5-16, below), and the duplicate "N days missing" count (F9, not re-examined); snowgrid.py's unavailable and unit lines (no all-clear sentence); and the section router in build.py (below).
  - *D42, budget and the monthly job (the workflow is in place).* `hail-store.yml` has three jobs. `plan` decides the monthly run (the first day of the month by schedule, or the monthly input). `store` is the daily run. `monthly` (it needs `plan` and `store`) starts from the release asset the daily run published, reads the whole station union, refreshes the gauges, asks NOAA once about the NOHRSC file, and publishes again. Every B5 and monthly step is non-fatal and has a timeout; the B1 and B2 build and publish steps stay fatal (the workflow header, lines 12, 21 and 22). The step timeouts are 1.5 times the measured time, rounded up to whole minutes, for the steps measured offline: the B1 store build 16 minutes (its 612 s CI time in the brief), the joins verify 1 minute (13.9 s, measured 2026-10-20), the climate build 1 minute (11 s) and the snow analysis 1 minute (1.0 s). The network steps keep their deadlines, because 1.5 times an offline time would cut a normal run short. The join step keeps 50 minutes, since its own deadline is 35 (JOINS_DEADLINE_S, D23; line 144 and its comment). The restated sizes, 2026-10-20 (store-ready.json): `j/` is 86,276,949 bytes raw in 9,196 files (the tiles 17,080,562, the events table 6,083,996, the towns file 29,467 and the per-tile event files 63,082,924, which are 10,423,190 bytes gzip in all), against the 40 MB of B2; `hail/` is 176,293,267 bytes in 23,866 files, against the 60 MB of B2. The increase is the B5 products: the per-tile event files (63,082,924 bytes raw) and the tile lists (13,667,217 bytes raw). The viewer budgets are the phone view (650 KB gzip) and the per-tile files (100,000 bytes gzip). The daily total with downloads is not measured (B5-12).
  - *D43, process.* The WIP commits on the branch (fa33c8d, de0793c, and HEAD dcb7e93) are the supervisor's, and this part commits nothing. The branch-name mentions in these docs are open for the owner (the banned-names item below); AGENTS.md has no exception for them.
  - *Dependency: the section router in `website/build.py` (not this part's file).* The router takes a joined row's kind from `_KIND_LABEL` (build.py:689), which accepts the labels Report, Record, Detection, Warning, Zone product, County product and Station. It reads a warning's product from "in effect:" (build.py:717). The B5 rows begin "Watch:" or "Advisory:" for those products and no longer write "in effect:", so they do not match the router. The change belongs to the site builder: accept the labels "Watch" and "Advisory", and take the product as the words after the span's colon and before the first comma.
  - *Decisions carried from the re-check, for the owner or the supervisor.* Confirm that preliminary grid highs may show on the partial line (D33; the owner). Record in DECISIONS the five roof references not quoted: R2, R9, R13, R17 and R20 (R9 and R17 are held, D14; the supervisor). Confirm the 25th table row, "Flood and flash flood watches for the county" (the supervisor). Choose the wording of the ice-dam roof line, "weather that can form ice dams" (the owner). Confirm the list of banned names behind the "no model or vendor names" rule, which is not in the repository, and whether branch names count (the owner). Decide the zone editions: place by the IEM sets, or find the full-resolution older files (D27; the owner or the supervisor).

*Why:* the owner asked for every kind of weather at a place, in one view, in words a roofer reads without decoding. The grid and the station readings answer the temperature, rain and snow questions, each with its own kind word and, for a station, its distance. The zone, county and warning products answer the wind, storm and flood questions for the zone, county or spot they cover, and they say so. The summary puts five seasons on one screen because the north star is one place that leads with the plain answer. The snow analysis stays out until its unit is settled, because a wrong unit would be a wrong number in every snow row. Nothing here says what a roof needs: the roof lines report the weather and quote their references, and the counts are corrected in the record, not left wrong on the page.

## Gotchas found the hard way
- An absolutely positioned element escapes a scroll box that isn't its containing block: the
  visually hidden "(over limit)" words in the hourly table widened every town page with a flagged
  cell by up to 24 px on a 288 px phone. `.table-box` is `position: relative` for that.
- A flex row of links shrinks its items (and wraps the text inside them) before it overflows; with
  `flex-wrap` it wraps whole items instead. Measure both on the narrowest phone.
- Jinja resolves `h.pop` to the dict method `pop`, not the key; the key is `precip_pct`.
- Folium camelizes keyword arguments (`_t` → `T`).
- `{% set %}` at the top level of a child template is ignored; set inside blocks.
- Leaflet controls lose their icons if CSS uses the `background` shorthand: use `background-color`.
- A scratch file named like a stdlib module (`inspect.py`) shadows it: run scripts with `python -I`.
- In development the installed copy of the built-in payload goes stale; the updater reinstalls it
  when its content hash changes.
- `ship.py` and the update tests assume the bundled manifest version; the tests pin a copy to 1.0.0.
- Folium's `Popup` always calls jQuery (`$(…)`); on a page without jQuery use a direct
  `bindPopup` (the website's `LinkPopup`).
- Folium adds Leaflet's stylesheet after anything added to the map's header, so header styles
  need selectors more specific than Leaflet's (`.leaflet-tooltip.town-label`).
- `actions/upload-artifact@v4` skips dotfiles such as `.nojekyll` unless `include-hidden-files: true`.
- A zone written into a template is wrong half the year: the Storm reports page said reporting days
  start "at 6 am MDT" in winter too (12:00 UTC is 5 am MST). Format the instant with `%Z`.
