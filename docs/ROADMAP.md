# Roadmap

Status on 2026-10-16: the product is the **Montana Hail Watch website** (D27) with an interactive
radar, forecast and warning map in the style of Apple Weather (D28) and live station readings
(D29). The website was merged to `main` on 2026-10-16 (pull request #3) and Carson turned on GitHub
Pages the same day, so `main` publishes to https://carson14dy.github.io/RoofingApp/ every 10
minutes. The desktop app (payload 1.0.0, shell 1.1.0) is **parked**: unchanged, still tested, not
shipped. Branches: `claude/desktop-app` (the app, then the website); `codex/kansas-city-weather-pilot`
and `codex/montana-weather-pilot` (ChatGPT's pilots, reviewed in D23 and D25, not merged).
Agents: check this file before starting, move items to Done when merged, keep "Next" in priority
order.

## Bottom line
1. Live since 2026-10-16: check that the scheduled runs keep publishing (Actions → Website).
2. Carson and a crew lead use it for a week on phones and desktops; fix what they trip on.
3. Replace the placeholder flag limits with the company's own.
4. Then: decision-time records for an evaluation, nearby station readings, a hail-size map, alerts
   to phones.
5. Decide whether to delete the parked desktop app.

## Done: the website (D27)
| Area | What works | Limits |
|---|---|---|
| Now | Montana's active NWS alerts, most urgent first (alerts without an outline listed with a note); a map card with the latest radar and warning outlines; a card per town for the next 12 hours with flags in words | Montana only |
| Map (D28) | Full screen, Apple-Weather style: the past hour of NOAA MRMS radar into the HRRR model forecast (15-minute steps for an hour, hourly to 12 hours) with play, scrub and 1h/12h; temperature and wind-gust layers; warning outlines and storm reports; town bubbles with the NWS forecast for the hour; town sheets; my location; a list of every alert and town | HRRR is a model, not the NWS forecast; frames are pictures made each build; no lightning or air quality; rain and snow share one palette; checked in Chromium only, not yet on a real iPhone or Android phone; `map.js` is about 2,100 lines |
| Town pages (14) | Alerts at that point, 24-hour table (gusts first), 7-day with high and low per day | Grid forecasts for a 2.5 km square, not a roof; placeholder limits |
| Observed now (D29) | The latest reading at each town's three nearest NWS stations (any state): temperature, wind, gusts, time and age, quality flags in words, station and grid elevation; one line per town card on the Now page | Stations report hourly or less, so readings run up to 75 minutes old before they show as stale; a station is not a roof; not on the map |
| Storm reports | Three SPC reporting days on the map card and in tables; hail in inches, unknown wind kept unknown | Preliminary reports only |
| Honesty | Per-source status line, last verified alerts kept after a failed refresh, "Alerts not checked" per town, page-age warning, sample data labelled on every page | — |
| Publishing | GitHub Actions every 10 minutes from `main`; branch builds check live data (`--require-live`) and keep a preview artifact; feed contracts on the About page | GitHub may delay schedules and pauses them after 60 days without activity |
| Design | Light "field sheet" look with dark mode, self-hosted fonts and Leaflet, contrast ≥ 5.86:1, collision-free map labels, 288–1440 px without sideways scroll, checked on every branch push (`docs/DESIGN.md`) | Phone Now page is long (P2) |
| Tests | 179 website tests (64 pages, map data and station readings, 69 radar and model frames, 41 base map and label layout, 5 Pages publication planning); a Chromium page-width check of every page at 288–1440 px on every branch push alongside the app's tests; a Chromium smoke test of the built map on every branch push (frames, base map, bubbles, play, layers, menu taps, legend, card and its caption) | — |

## Next, in priority order
1. **Go live.** Done in part, 2026-10-16: PR #3 merged; its first deployment (run 38933159167)
   failed with Pages disabled; the publication repair (PR #4) now rejects failed or invalid Pages
   lookups; Carson turned on Pages (Source: GitHub Actions) and run 38934427870 published the
   site. Left: open the runs' summaries in Actions → **Website** (every source loaded, counts
   plausible); open the site on a phone. Done when two scheduled runs in a row publish.
2. **Feedback week.** Carson and a crew lead use it daily. Record what they look for and can't
   find; run the first-click and timing checks in `docs/DESIGN.md` section 1. Open the map on an
   iPhone (Safari) and an Android phone: glass blur, notch and home-bar insets, the location prompt,
   playback on mobile data. All map checks so far ran in headless Chromium.
3. **Company limits.** Replace the placeholder flags (D16: gusts 25 mph, wind 20 mph, rain or snow
   30%, under 40 °F, over 95 °F) with the company's limits, per roof system if they differ.
4. **Decision-time records (review P0 baseline).** Keep each build's `data/state.json` (alerts,
   what each town card said) somewhere durable, for example an hourly commit to a `data` branch, and
   predeclare the metrics (misses, false alarms, lead time) before any new feed is added.
5. **Phone density (design P2).** A compact one-line-per-town list on phones with the same flags.
6. **Cache map frames between builds.** Each build downloads about 40 MB (mostly HRRR temperature and
   gusts, which change only hourly) and redraws frames it drew 10 minutes earlier. Reuse frames by
   HRRR run and radar time (an Actions cache or the live site's previous frames).
7. **Rain and snow on the map.** Colour snow apart from rain (MRMS PrecipFlag, HRRR CSNOW), with the
   legend saying which.
8. **Text version of the map pictures (accessibility).** The List gives every NWS alert and each
   town's NWS forecast as text, but nothing says what the radar and model pictures show at a town.
   Sample the radar estimate and the HRRR values at each town in `website/gridded.py`, add them to
   `data/map.json` (a D28 contract change) and list them, worded as a "radar estimate" or "model",
   never "dry" or "no hail". Until then the map's description says the pictures have no text version.
9. **Less JavaScript in the map (Carson's call).** `map.js` is about 2,100 lines. The verification's
   JavaScript review found about 330 that could move to the build: Montana-time labels written into
   `data/map.json` (removes the Intl code), the legend rendered by Jinja, the note's room reserved in
   CSS. Its skeptic rejected them as defects: AGENTS.md rule 4 gives sheets and layout to `map.js`,
   and each move adds map.json keys that tie the build to the page's wording. Worth doing only
   together, with the Playwright suites as the guard.
10. **Nearby station observations: done (D29, 2026-10-16).** Next for them: the readings on the map's
   town sheets (a D28 contract change), and a check on real phones that the card line stays one
   line.
11. **Real hail footprint.** MRMS MESH (same bucket and decoder as the map's radar, D28) drawn as a
   map layer and as outlines per swath (nodata handled, 1 km resolution recorded), labelled as a
   radar estimate, apart from reports. Check against SPC 2025-06-15 (Benchland, 1.75″).
   Or a commercial trial in shadow mode (Xweather, The Weather Company HailZone, Verisk, Cotality;
   use the review's procurement questions). No "best" claims (D21).
12. **Alerts to phones.** A static site can't push. Needs a small service (push, SMS or email) and the
   p95 delivery gate below.
13. **History.** Date ranges and multi-day events; NCEI Storm Events for older context.
14. **More towns, then the contiguous US (D24).** Towns are one line each in `website/towns.json`
    (each needs a label side checked by the label test). Contiguous US: a state list for alerts,
    the SPC filter box and map extent per region.
15. **The parked app.** Keep or delete `payload/` and `desktop/` (Carson's call). If it comes back,
    its plan (installers on real machines, pilot, evaluation, guidance trials, vendor comparison)
    is in this file's history at commit 33cda31.

## Independent review priorities, for the website
| Priority | Item | Status |
|---|---|---|
| P0 | Alert geography (polygon, county, zone, null geometry) | Statewide list from NWS; per-town check by point (NWS matches polygons and zones); null geometry listed; tested |
| P0 | Lifecycle: revisions, duplicates, outages | Replaced updates and test messages dropped; failed refresh keeps the last verified list; tested. No notifications yet, so no duplicate-notification risk |
| P0 | Baseline and predeclared evaluation metrics | **Not started** (Next 4) |
| P1 | Roofing job context | Parked with the app |
| P1 | Advanced guidance trials (SPC CIG, ProbSevere v3, LightningCast) | Listed only |
| P1 | Broader vendor comparison | Listed only (Next 9) |
| P1 | Pinned feed contracts | Done: `website/sources.py` `CONTRACTS`, shown on the About page |
| P2 | Raw national model ingestion | HRRR precipitation rate, temperature and gusts for Montana only (D28); nothing national |

## Release gates (review's proposed targets)
| Gate | Status for the website |
|---|---|
| No missed applicable severe/tornado alert | NWS does the matching; the statewide list shows every active Montana alert. Real-event checks: add curated Montana cases |
| Every injected outage shows stale/unavailable; no missing-data all-clear | Covered by tests (alerts, gusts, every source down) |
| AI summaries | Not applicable: the site generates no AI text |
| Every displayed number/time/location traces to evidence | Each section names its source and time; feed contracts on the About page |
| p95 < 60 s from alert retrieval to notification | Not applicable until alerts reach phones (Next 8) |
| Recover from a 30-minute interruption without lost records | Next build after an outage is complete; last verified alerts carried across |

## Open questions for Carson
- Are these the right 14 towns? Which should be added or dropped?
- The company's weather limits for each roof system (Next 3).
- Delete the parked desktop app, or keep it in the repo?
- Should the site have its own web address (a custom domain) instead of the GitHub one?
- Check "Montana Hail Watch" against existing products and trademarks before printing it anywhere
  (D26).
- The repo description says "Roofing Weather and Maps Contact app". What should "Contact" cover?

## Missing inputs
- The handoff's two images (dashboard concept, hero photo) were not provided.
- The review cites `Roofing_Weather_Engine_Blueprint.md`, which isn't in this repo. Add it to
  `docs/handoff/` if it exists.
