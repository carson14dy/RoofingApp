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
inline — today one ~20-line bridge in `templates/live.html` (map click → form fields, drawn
shape → form submit, radar tile refresh every 4 minutes).
*Why:* the owner's requirement after the first HTML/JS version — a clean Python rebuild, not a hybrid.

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
*Lesson:* HTTP 200 is not proof — check the content.

**D8 · Folium's map script must be wrapped in `<script>` (2026-10-11; corrects the web version).**
The script part of Folium's render has no tags; the web version inserted it bare, so the map never
ran. HTML string tests missed it; a real browser caught it. UI checks now use a real browser.

**D9 · Base map = USGS The National Map (2026-10-11).** CARTO tiles now return “API KEY REQUIRED”.
USGS topo and imagery are public domain; dark mode is a CSS invert on the tile layer
(`hw-dark-base`); max native zoom 16. Folium's injected Bootstrap is removed (it fought the
app's styles).

**D10 · Alert applicability — review P0 (2026-10-11).** Poll `/alerts/active?area=MT` every 60 s.
An alert applies to a place when its polygon contains the place; otherwise when its UGC codes
include the place's NWS forecast zone, county or fire zone (looked up once from
`/points/{lat},{lon}` and stored). Unknown codes show “Can't tell yet”, never “no alert”.
Territories match by polygon or by zone geometry from `/zones/…`. When checked, all 19 active
Montana alerts had null geometry — polygon-only matching would have missed every one.

**D11 · Alert lifecycle — review P0 (2026-10-11).** Two-pass reconcile: Cancel messages and
`references` mark earlier messages cancelled or updated whatever order they arrive in; references
not yet seen become placeholders. Alerts never clear after a failed request. After a gap over
150 s the app backfills from `/alerts?area=MT&start=…` (up to 5 pages), so warnings issued during
an outage still produce matches. Notifications dedupe on `alert:{id}:{place|territory}` and
`spc:{record}:place:{id}:rule{size}/{radius}`. Tested with 240 scenarios and a busy-day replay
with a 30-minute outage.

**D12 · Evidence model and demo policy (2026-10-11).** From the handoff's `WeatherEvidence`: kinds
forecast, radar_estimate, point_report, station_observation, official_alert, inspection — never
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
handoff's suggested off-white/navy/teal — the handoff says to adapt to the existing design system.
The handoff's two images were not provided; synthetic images are never evidence. Place names show
on hover so labels don't overlap.

**D20 · Storage (2026-10-11).** One SQLite file per computer in the user data folder; timestamps in
UTC; append-only migrations (`MIGRATIONS[0]` = web-version schema, `[1]` = places, territories,
candidates, alerts, notices, reviews, acknowledgements, outlook log, settings). Web-version
databases upgrade in place: old reports → crew inspection findings, old outlines → crew-observed
areas. Alerts are pruned after 30 days.

**D21 · No “best” claims; providers are candidates (2026-10-11).** Per the review. SPC Conditional
Intensity Groups, ProbSevere v3, LightningCast, Xweather (including `/hail/archive`), The Weather
Company HailZone, Verisk and Cotality are listed under Data sources as trial candidates — not
integrated, not ranked.

**D22 · Repo and agents (2026-10-11).** Code lives in `carson14dy/RoofingApp` (public). `AGENTS.md`
holds the shared agent rules (read directly by ChatGPT/Codex); `CLAUDE.md` imports it with
`@AGENTS.md` for Claude Code. Work happens on branches with pull requests; CI (“Check the app”)
runs the self-test and tests on every pull request and every push to `main`.

**D23 · ChatGPT's Kansas City pilot branch — what carries over (2026-10-11).** Branch
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
  accepts four decimals (≤ 7 m quantization — disclose it); forecast grids are ~2.5 km; observations
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
- The TypeScript/Next.js/MapLibre/PostGIS service design — D1. The branch's own stdlib server shows
  the Python path works.
- The prototype as a second app. It duplicates the point lookup, hourly forecast and point-alert
  code in `weather.py` (`outlook()` already calls `/alerts/active?point=`), uses undocumented
  minified JavaScript (rule 4), has no session key or Host check (D2), and shows alert times in UTC
  beside local times. Its “Saved history” tab is query snapshots, not storm history.
- 1.3 MB of response captures, a screenshot and vendored Leaflet in git. Folium bundles Leaflet;
  every installed app downloads the repo zipball on each update (D6), so research artifacts cost
  every crew machine bandwidth without reaching the payload.
- The radar-reading skill inside the app — rule 6 and the release gate (≥ 500 adversarial AI
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
codes, which a Montana-only poll can never match — the change below fixes that too.

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

**D25 · ChatGPT's Montana pilot branch — findings that change the plan (2026-10-11).** Branch
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
  always shows the age, and shows stale values as stale — never hidden.
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
- **Units.** The prototype shows °C and km/h; the app keeps D15 — °F and mph for display, native
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
“Storm-to-roof” — the state is in the name now), page titles, the manifest `name`, the printable
summary footer, the shell window and dialogs. Because the shell changed and a new installer is built,
`SHELL_VERSION` is 1.1.0; `SHELL_API` stays 1 and the payload stays 1.0.0 (nothing was shipped).
`APP_ID` is `MontanaHailWatch` in `desktop/launcher.py` and `build.py`, so the installer, the
executable, the data folder, the webview storage, the waitress ident and the user agents are all
new names; no copies were installed under the old `APP_ID`, so nothing is orphaned. The macOS bundle
identifier is `com.montana.hailwatch`. Internal identifiers did not change: `hailwatch.stop`,
`hw_session`, the `hailwatch` and `hailwatch.updater` loggers, `hailwatch.db` and the backup
pattern, `store.MIGRATIONS`, and the manifest `version` and `min_shell`. The `--bigsky` colour
token stays — it names the sky, not the product.

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

Decision, 2026-10-17: Carson chose the staged route — storm layers on the Map page first (P1 text
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
  for the builds, which leave the top of the hour as the job does (D33 is on the schedule-offset branch).
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
  `days_differed`, `days_checked` and `skipped`. The partial list and the compare counts are measured in the re-check.
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

## Gotchas found the hard way
- An absolutely positioned element escapes a scroll box that isn't its containing block: the
  visually hidden "(over limit)" words in the hourly table widened every town page with a flagged
  cell by up to 24 px on a 288 px phone. `.table-box` is `position: relative` for that.
- A flex row of links shrinks its items (and wraps the text inside them) before it overflows; with
  `flex-wrap` it wraps whole items instead. Measure both on the narrowest phone.
- Jinja resolves `h.pop` to the dict method `pop`, not the key — the key is `precip_pct`.
- Folium camelizes keyword arguments (`_t` → `T`).
- `{% set %}` at the top level of a child template is ignored — set inside blocks.
- Leaflet controls lose their icons if CSS uses the `background` shorthand — use `background-color`.
- A scratch file named like a stdlib module (`inspect.py`) shadows it — run scripts with `python -I`.
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
