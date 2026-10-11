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
installers, or pasted into the app).

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

## Gotchas found the hard way
- Jinja resolves `h.pop` to the dict method `pop`, not the key — the key is `precip_pct`.
- Folium camelizes keyword arguments (`_t` → `T`).
- `{% set %}` at the top level of a child template is ignored — set inside blocks.
- Leaflet controls lose their icons if CSS uses the `background` shorthand — use `background-color`.
- A scratch file named like a stdlib module (`inspect.py`) shadows it — run scripts with `python -I`.
- In development the installed copy of the built-in payload goes stale; the updater reinstalls it
  when its content hash changes.
- `ship.py` and the update tests assume the bundled manifest version; the tests pin a copy to 1.0.0.
