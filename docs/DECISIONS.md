# Decisions

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

## Gotchas found the hard way
- Jinja resolves `h.pop` to the dict method `pop`, not the key — the key is `precip_pct`.
- Folium camelizes keyword arguments (`_t` → `T`).
- `{% set %}` at the top level of a child template is ignored — set inside blocks.
- Leaflet controls lose their icons if CSS uses the `background` shorthand — use `background-color`.
- A scratch file named like a stdlib module (`inspect.py`) shadows it — run scripts with `python -I`.
- In development the installed copy of the built-in payload goes stale; the updater reinstalls it
  when its content hash changes.
- `ship.py` and the update tests assume the bundled manifest version; the tests pin a copy to 1.0.0.
