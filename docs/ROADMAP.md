# Roadmap

Status on 2026-10-14: the product is the **Montana Hail Watch website** (D27), built and tested on
branch `claude/desktop-app`. It goes live when that branch is merged to `main` and GitHub Pages is
turned on. The desktop app (payload 1.0.0, shell 1.1.0) is **parked**: unchanged, still tested,
not shipped. Branches: `claude/desktop-app` (the app, then the website); `codex/kansas-city-weather-pilot`
and `codex/montana-weather-pilot` (ChatGPT's pilots, reviewed in D23 and D25, not merged).
Agents: check this file before starting, move items to Done when merged, keep "Next" in priority
order.

## Bottom line
1. Turn on GitHub Pages and merge: the site is live within about 10 minutes.
2. Carson and a crew lead use it for a week on phones and desktops; fix what they trip on.
3. Replace the placeholder flag limits with the company's own.
4. Then: decision-time records for an evaluation, nearby station readings, a hail-size map, alerts
   to phones.
5. Decide whether to delete the parked desktop app.

## Done: the website (D27)
| Area | What works | Limits |
|---|---|---|
| Now | Montana's active NWS alerts, most urgent first (alerts without an outline listed with a note); radar picture with NOAA's frame time; warning outlines; a card per town for the next 12 hours with flags in words | Radar is a still frame (links to the live loop); Montana only |
| Town pages (14) | Alerts at that point, 24-hour table (gusts first), 7-day with high and low per day | Grid forecasts for a 2.5 km square, not a roof; placeholder limits |
| Storm reports | Three SPC reporting days on a map and in tables; hail in inches, unknown wind kept unknown | Preliminary reports only |
| Honesty | Per-source status line, last verified alerts kept after a failed refresh, "Alerts not checked" per town, page-age warning, sample data labelled on every page | — |
| Publishing | GitHub Actions every 10 minutes from `main`; branch builds check live data (`--require-live`) and keep a preview artifact; feed contracts on the About page | GitHub may delay schedules and pauses them after 60 days without activity |
| Design | Light "field sheet" look with dark mode, self-hosted fonts and Leaflet, contrast ≥ 5.86:1, collision-free map labels, 288–1440 px without sideways scroll (`docs/DESIGN.md`) | Phone Now page is long (P2) |
| Tests | 41 website tests (parsers, failures, maps, label layout) alongside the app's 44 | — |

## Next, in priority order
1. **Go live.** Settings → Pages → Build and deployment → Source: **GitHub Actions**; merge the
   branch; open Actions → **Website** → the first run's summary (every source loaded, counts
   plausible); open the site on a phone. Done when two scheduled runs in a row publish.
2. **Feedback week.** Carson and a crew lead use it daily. Record what they look for and can't
   find; run the first-click and timing checks in `docs/DESIGN.md` section 1.
3. **Company limits.** Replace the placeholder flags (D16: gusts 25 mph, wind 20 mph, rain or snow
   30%, under 40 °F, over 95 °F) with the company's limits, per roof system if they differ.
4. **Decision-time records (review P0 baseline).** Keep each build's `data/state.json` (alerts,
   what each town card said) somewhere durable, for example an hourly commit to a `data` branch, and
   predeclare the metrics (misses, false alarms, lead time) before any new feed is added.
5. **Phone density (design P2).** A compact one-line-per-town list on phones with the same flags.
6. **Nearby station observations** on town pages (D23, D25 rules): the nearest NWS stations, never
   filtered by state, with distance, elevation, observation time and age; about 75 minutes is
   "current"; QC flags shown; a null gust is "no gust reported". ChatGPT's 16-point Montana sweep is
   the first fixture.
7. **Real hail footprint.** MRMS MESH processed by a scheduled GitHub Actions job into outlines
   (GRIB2 → polygons per swath, nodata handled, 1 km resolution recorded), drawn on the Storm
   reports map as an estimate, apart from reports. Check against SPC 2025-06-15 (Benchland, 1.75″).
   Or a commercial trial in shadow mode (Xweather, The Weather Company HailZone, Verisk, Cotality;
   use the review's procurement questions). No "best" claims (D21).
8. **Alerts to phones.** A static site can't push. Needs a small service (push, SMS or email) and the
   p95 delivery gate below.
9. **History.** Date ranges and multi-day events; NCEI Storm Events for older context.
10. **More towns, then the contiguous US (D24).** Towns are one line each in `website/towns.json`
    (each needs a label side checked by the label test). Contiguous US: a state list for alerts,
    the SPC filter box and map extent per region.
11. **The parked app.** Keep or delete `payload/` and `desktop/` (Carson's call). If it comes back,
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
| P1 | Broader vendor comparison | Listed only (Next 7) |
| P1 | Pinned feed contracts | Done: `website/sources.py` `CONTRACTS`, shown on the About page |
| P2 | Raw national model ingestion | Deferred |

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
