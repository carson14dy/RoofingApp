# Roadmap

Status on 2026-10-11: payload 1.0.0, desktop shell 1.0.0. Branches: `claude/desktop-app` (the app,
pull request #1); `codex/kansas-city-weather-pilot` (ChatGPT's pilot — reviewed in D23, not merged;
its usable parts are items 5 and 7 below). Agents: check this file before starting,
move items to Done when merged, and keep “Next” in priority order.

## Bottom line
1. Build the installers and test them on a real Windows PC and Mac — not done yet.
2. Pilot one service territory and one roof-system family with real company rules.
3. Set the evaluation baseline (review P0) before adding any new feed.
4. Then a real hail-footprint source: MRMS processing or a commercial trial in shadow mode.

## Done in 1.0.0
| Area | What works | Limits |
|---|---|---|
| Live Storms | Radar with frame time, NWS alerts matched by polygon or zone/county/fire zone, feed freshness, address/city/ZIP search, territories, crew findings, review's home-screen order | Alerts poll Montana only |
| Storm History | SPC reporting day on a map and table, tiers with reasons in words, add inspection candidates | One reporting day at a time |
| Inspections | Statuses, assigned rep, notes, evidence snapshot, printable exposure summary, CSV export | — |
| Crew Outlook | Roof system/product, phase, duration, dry-in, site checks, job rule overrides, windows, WBGT + heat index, 7-day, supervisor review, crew acknowledgement | Rules are placeholders until the company sets them |
| Desktop app | Native window, self-updates from `main`, self-test before install, backups, rollback, recovery page, desktop notifications; update channel verified against real GitHub | App window tested on Linux only; installers unsigned |
| Tests | 44 tests incl. 240 alert scenarios and a 30-minute outage replay; CI on every PR | — |

## Handoff build sequence
| # | Step | Status |
|---|---|---|
| 1 | Source-labelled NWS forecasts/alerts, job locations, stale-feed states | Done |
| 2 | Preliminary storm reports and event history browsing | Done (single reporting day; no date ranges yet) |
| 3 | One validated estimated hail-footprint source + property intersections | Partial — adapter, intersections and demo done; no validated real source |
| 4 | Assignments, territories, notifications, exposure exports | Done (desktop notifications only) |
| 5 | Licensed lightning/nowcast, advanced history, measured targeting analytics | Not started |

## Independent review priorities
| Priority | Item | Status |
|---|---|---|
| P0 | Alert geography (polygon, county, zone, null geometry) | Done, tested |
| P0 | Lifecycle: revisions, out-of-order, duplicates, outages, replay | Done, tested |
| P0 | Baseline and predeclared evaluation metrics | **Not started — next after the pilot starts** |
| P1 | Roofing job context | Done |
| P1 | Advanced guidance trials (SPC CIG, ProbSevere v3, LightningCast) | Listed only |
| P1 | Broader vendor comparison | Listed only |
| P1 | Pinned feed contracts | Done for connected feeds (`weather.CONTRACTS`) |
| P2 | Raw national model ingestion | Deferred |

## Release gates (review's proposed targets)
| Gate | Status |
|---|---|
| ≥100 alert lifecycle/geography scenarios; no missed applicable severe/tornado alert; no duplicate notifications | 240 generated scenarios pass. To do: add curated real Montana events (boundary sites, null-geometry warnings) |
| Every injected outage shows stale/unavailable; no missing-data all-clear | Covered by tests |
| ≥500 adversarial AI summaries | Not applicable — the app generates no AI text. Required before adding any |
| Every displayed number/time/location traces to evidence | Partial — candidate evidence snapshots and outlook reasons; no full audit |
| p95 < 60 s from alert retrieval to notification accepted | Not measured (60 s polling, desktop only) |
| Replay a peak regional day at 3× input; recover from a 30-minute interruption without lost records | Recovery tested; 3× load not tested |
| Confidence intervals and limits for comparative results | Waits for the evaluation |

## Next, in priority order
1. **Installers on real machines.** Merge to `main` → Actions → **Build desktop installers** → install
   on a Windows PC and a Mac. Done when: the window opens, map and radar draw, a notification appears,
   and a test release (1.0.1) arrives through **Check for updates** and applies with **Update now**.
   Then decide on code signing (Windows certificate; Apple Developer ID + notarization).
2. **Pilot.** One service territory, one roof-system family, the company's real rules for that
   product, real jobs. Record what crews change or ignore.
3. **Evaluation baseline (review P0).** Predeclare metrics — weather misses/false alarms/lead time,
   review time, interruptions per 100 job-days, findings per crew-hour. Arms: A) company practice +
   NWS, B) + job rules, C) + extra feeds. Event/date held-out splits; decision-time data only (the app
   already logs outlook changes, reviews with the outlook at the time, and candidate evidence
   snapshots). Build an export and a replay harness.
4. **Real hail footprint.** Option A: an MRMS MESH processing job (GRIB2 → polygons per swath
   interval, nodata handled, 1 km resolution recorded) on a schedule — e.g. GitHub Actions or a small
   server — publishing GeoJSON for the app's footprint setting, which keeps GRIB libraries out of the
   desktop app. Option B: a commercial trial in shadow mode. Check against a known event, e.g. SPC
   2025-06-15 (Benchland, 1.75″).
5. **Nearby station observations.** A feed for the `station_observation` evidence kind: the nearest
   NWS stations with distance, observation time, age and the native QC flag beside each value
   (`X` withheld; `V`, `S`, `C`, `Z` shown with their flag). From ChatGPT's Kansas City prototype,
   see D23. After the baseline (3), like any new feed.
6. **Advanced guidance trials in shadow mode.** SPC outlooks with Conditional Intensity Groups,
   ProbSevere v3, LightningCast (a prediction) kept separate from observed lightning. A low score
   never suppresses an official warning.
7. **Vendor comparison.** Xweather (live; `/hail/archive` from 2024-01-01; published pay-as-you-go
   pricing with a 12× hail multiplier), The Weather Company HailZone, Verisk, Cotality — use the
   review's procurement questions and model cost with territory sharing and caching.
   ChatGPT's plugins (AccuWeather, Weather by WindBorne, Zoom Radar Weather, Tomorrow.io) are
   candidates only: chat-plugin access is not app API access, and ChatGPT's research retrieved no
   documentation for any of them (D23).
8. **Alerts when the app is closed.** Phone/SMS/email delivery needs a small always-on service;
   measure the p95 gate.
9. **History.** Date ranges and multi-day events in Storm History; NCEI Storm Events for older context.
10. **Beyond Montana.** Alerts poll `area=MT`; expanding means an area list and an updated coverage
   matrix (`weather.COVERAGE`).
11. **Shared data.** Each computer has its own database. Office and crews sharing jobs and candidates
    needs a server or sync — decide before building.

## Open questions for Carson
- **Kansas City or Montana?** ChatGPT's pilot branch targets downtown Kansas City; the app, its
  alert poll (`area=MT`) and the coverage matrix target Montana. Second territory, test site or
  mix-up? (See D23 and item 10, Beyond Montana.)
- **Product name.** “Big Sky Hail Watch” is a placeholder. The claude.ai project is called “Hail Trace
  2.0”, and HailTrace is an existing hail-mapping service sold to roofers — check trademarks before
  using a similar name.
- Work rules for each roof system and product (from manufacturer instructions and company procedure).
- Pilot territory and roof-system family.
- Keep the repo public? Private needs an `UPDATE_TOKEN` (see README).
- Crew computers: Windows, Apple Silicon Macs, Intel Macs? (The Mac build targets Apple Silicon.)
- Should office and crews share one set of jobs and candidates?
- Budget for commercial hail data?
- The repo description says “Roofing Weather and Maps Contact app” — what should “Contact” cover
  (customer contacts, homeowner outreach, a CRM)?

## Missing inputs
- The handoff's two images (dashboard concept, hero photo) were not provided.
- The review cites `Roofing_Weather_Engine_Blueprint.md`, which isn't in this repo — add it to
  `docs/handoff/` if it exists.
