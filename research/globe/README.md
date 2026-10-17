# Globe view with 3D clouds and storms — research scaffold

Status 2026-10-17 · branch `codex/montana-weather-pilot` · research only — nothing ships
(`payload/manifest.json` unchanged). §1–7 are the plan. §8 onward are findings from parallel
agents; every fact there names its evidence file in `validation-evidence/` or is marked
*unverified*. The prototype lives in `prototype/` and is not part of the app.

Read with: `docs/DECISIONS.md` (D1 Python-only, D4 50 MB update cap, D7 radar, D9 base map,
D12 evidence model, D24 scope), `docs/ROADMAP.md`, `AGENTS.md` hard rules.

## 1. Bottom line

1. **What was asked.** A Google Earth-like globe with "holographic" imagery of clouds and storms.
2. **What it really is.** A WebGL globe in the app window (3D rendering on a flat screen — call it
   **3D storm view** to users; "holographic" promises a hologram we cannot deliver), draped with
   satellite cloud imagery, clouds lifted to their measured cloud-top height, storms drawn as
   3D radar-reflectivity volumes, all on a time slider. Every layer keeps its source, valid time,
   retrieval time and freshness state exactly as the flat map does today (D12).
3. **Every needed input exists as free US-government data, reachable from this sandbox today**
   (§8): GOES-East/West satellite imagery and cloud-top height (NOAA, 5-min CONUS cadence), the
   MRMS 3D reflectivity mosaic (33 heights, 0.5–19 km, 1 km cells, every 2 min), NEXRAD volumes,
   NWS alerts (already in the app), USGS imagery (already the base map), NASA GIBS imagery for the
   rest of the globe, open terrain tiles. Google's own imagery and 3D tiles are *not* reusable
   except through its paid, no-caching Map Tiles API (§8, D-G4).
4. **The one real blocker is a rule, not a technology.** Rule 4 / D1: a globe cannot be drawn by
   Python; it needs a WebGL library (CesiumJS, three.js, deck.gl or MapLibre). Folium is the
   precedent — Python generating a Leaflet page. The proposal is the same shape: Python (Jinja)
   generates the globe page and its layer list; the WebGL library is a pinned dependency like
   Leaflet; the hand-written JavaScript is a documented layer loader, not a framework. **Carson
   decides (D-G1 below) before any app code changes.**
5. **Second constraint: size and offline.** The payload zipball is capped at 50 MB (D4) and the
   self-test runs with the network off, so the globe library cannot be vendored into the payload
   and the page must degrade to "Data unavailable" without it. Options in §9.
6. **Third constraint: data volume.** The full MRMS 3D mosaic is tens of MB every 2 minutes.
   Crew laptops should receive a crop around saved places, produced either on each machine (needs
   GRIB2/netCDF libraries → new installer, rule 2) or by a small scheduled job that publishes
   ready-made tiles (as roadmap item 4 already proposes for MESH). Measured sizes in §8/§10.
7. **Order of work.** Verify sources (done, §8) → prototype outside the app (`prototype/`, §11) →
   Carson's decisions (§2) → Phase 1 `/globe` page in the app → clouds with height → 3D storm
   volumes → time animation → laptop performance (§6). Nothing here changes roadmap items 1–3
   (installers, pilot, baseline); this is a new roadmap item placed after them unless Carson
   moves it up.

## 2. Decisions Carson needs to make

| # | Decision | Options (ranked by fit with the rules) | Default if no answer |
|---|---|---|---|
| D-G1 | Allow a WebGL globe library (JavaScript) in the app? | (a) Yes — Python generates the page; library pinned and documented, like Leaflet under Folium. (b) Yes, but as a separate window/page outside the Flask app. (c) No — stay 2.5D on the flat map (radar tops as colour, no globe). | Research stays in `research/globe/`; no app change |
| D-G2 | Where does heavy data processing run? | (a) Small scheduled job (GitHub Actions or a $5–10/mo server) publishing crops/tiles — keeps GRIB/netCDF libraries out of the desktop app. (b) On each crew machine — new installer with netCDF4 + eccodes (rule 2). | (a) |
| D-G3 | Scope of storm volumes | Montana + border now (saved places' bounding box), contiguous US as D24 lands. Globe imagery is worldwide either way. | Montana + border |
| D-G4 | Budget | $0: public NOAA/NASA/USGS data + pinned CDN library. Paid candidates only in shadow mode: Google Photorealistic 3D Tiles, Cesium ion terrain, commercial satellite imagery. | $0 |
| D-G5 | Where it appears | (a) New **3D view** tab beside Live Storms, same layer list and alert matching. (b) Replace the flat map. (c) Separate "globe" window. | (a) |
| D-G6 | Name | "3D storm view" / "Storm globe" in the UI; "holographic" stays an internal nickname. | "3D storm view" |
| D-G7 | Hardware floor | Which crew laptops must it run on (integrated GPU, Windows WebView2 / Mac WKWebView)? Sets the voxel budget. | Integrated GPU, 2018+ |

## 3. Target picture — what the finished view shows

Each layer carries source · valid time · retrieved time · Live/Stale/Unavailable (D12 limits:
GOES 15 min, MRMS 10 min, alerts 10 min, imagery daily). Nothing is merged across kinds.

| Layer | Kind (D12) | Source (free unless noted) | Shape on the globe |
|---|---|---|---|
| Earth imagery | base map | USGS imagery (CONUS, public domain, D9); NASA GIBS Blue Marble / VIIRS true colour (rest of the world) | Draped tiles |
| Terrain | base map | Open terrain tiles (AWS Terrain Tiles / USGS 3DEP); Cesium World Terrain needs an ion account | Height mesh |
| Clouds | observation | GOES-East (GOES-19) / GOES-West (GOES-18) ABI GeoColor or Band 13 IR, via NASA GIBS tiles or NOAA's AWS buckets | Draped texture (Phase 1) → lifted to cloud-top height (Phase 2) |
| Cloud-top height | satellite estimate | GOES ABI L2 ACHA (cloud top height), optional COD (optical depth) | Displaces the cloud deck; drives opacity |
| Storms | radar estimate | MRMS 3D MergedReflectivityQC (33 levels), MESH hail swath | Voxels / isosurfaces (≥20, 35, 50 dBZ); swath as ground overlay |
| Flat radar | radar estimate | NWS WMS base reflectivity (D7) | Fallback drape when volumes are unavailable |
| Official alerts | official alert | NWS API polygons + zone geometry (reuse `weather.py`) | Outlines, optionally extruded walls |
| Places, territories, jobs, candidates | — | app database | Pins and outlines, hover names (D19) |
| Time | — | per layer | Last 2 h loop, scrub; valid time shown apart from retrieval time |

## 4. Evidence rules applied to the globe

- Satellite imagery is an **observation**; cloud-top height is a **satellite estimate**;
  reflectivity volumes and MESH are **radar estimates**. None is damage, insurance eligibility or
  a probability (rule 5). Legends say so.
- **No echo is not clear.** Far from the four Montana radars the beam overshoots low levels (D24);
  MRMS carries its own no-coverage mask. The view draws "No radar coverage" where the data says
  so, never empty sky as all-clear.
- **Cloud base is not observed** from satellite; a lifted cloud deck shows the top surface only.
  Say so in the legend. Ceilometers at NWS stations are the only base observations (roadmap 5).
- **Parallax.** GOES views Montana (45–49°N) at a steep angle; high cloud tops appear displaced
  tens of km poleward unless corrected with cloud-top height. GIBS imagery is not parallax
  corrected (§8 checks this claim). A lifted deck must correct it or disclose it.
- A failed feed shows Stale/Unavailable and keeps the last frame labelled with its age; never a
  demo frame; no AI-generated text in the alert path (rule 6).
- Vertical exaggeration, if offered, is labelled on screen.

## 5. Workstreams run by the agents

| # | Workstream | Done when | Output |
|---|---|---|---|
| W1 | NASA GIBS WMTS: GOES GeoColor/Band 13, Blue Marble, VIIRS | Capabilities parsed, one Montana tile decoded with pixel stats, cadence, latency, CORS, terms | `validation-evidence/gibs.json` |
| W2 | NOAA GOES on AWS: CMIPC band 13, ACHAC cloud-top height, CODC | Latest file opened as netCDF; variables, units, fill, scan time, Montana coverage, bytes per step, CORS | `goes-aws.json` |
| W3 | MRMS on AWS: 33 reflectivity levels, composite, MESH, coverage products | Levels enumerated with sizes; four levels decoded (grid, bounds, missing vs no-coverage codes, dBZ stats over Montana); bytes per 2-min step | `mrms.json` |
| W4 | NEXRAD Level II, NWS WMS radar, IEM tile caches | Latest Montana volumes listed; tiles decoded; terms | `radar-tiles.json` |
| W5 | Terrain: AWS Terrain Tiles, USGS 3DEP, Cesium World Terrain terms | Billings elevation decoded from a tile within ±50 m of 952 m; options for Cesium without ion | `terrain.json` |
| W6 | Base imagery: USGS tiles for a globe tiling scheme, GIBS Blue Marble/VIIRS, Esri and Sentinel-2 cloudless terms | Tiles decoded; max zoom; terms quoted | `base-imagery.json` |
| W7 | Globe libraries: CesiumJS, three.js/globe.gl, deck.gl + pydeck, MapLibre globe, Google 3D Tiles | Versions, licences, sizes, ion requirements, volume/3D-texture support, WebGL2 needs | `globe-libs.json` |
| W8 | WebGL in pywebview backends + headless Chromium here | Backend table; a WebGL2 context created in this sandbox's Chromium | `webgl-runtime.json` |
| W9 | App integration map | Which `weather.py`/`store.py` functions a `/globe` route reuses; self-test and 50 MB constraints measured; CSP/headers | `app-integration.json` |
| W10 | Google Earth / Maps Platform terms | What "recreate Google Earth" may legally reuse; 3D Tiles pricing and no-caching terms | `google-terms.json` |
| W11 | Rendering techniques | Options ranked per phase with bytes/frame, GPU load, honesty limits | §9 |
| W12 | Pipeline and cost | In-app vs scheduled job vs server, with measured sizes and $/month | §10 |
| W13 | Architecture designs | Three designs, three judges, one synthesis | §9 |
| W14 | Prototype | Globe page, MRMS volume script, GOES height script, 3D storms layer, browser check | `prototype/`, §11 |
| W15 | Synthesis and critic | §8–12 written from evidence; completeness and rule check | this file |

Each W1–W10 report was re-checked by an independent agent told to refute it; corrections are
recorded in §8.

## 6. Build phases (after the §2 decisions)

| Phase | Scope | Done when |
|---|---|---|
| 0 | This scaffold; prototype outside the app | Browser check passes on the prototype; Carson has answered §2 |
| 1 | `/globe` page: Earth imagery + terrain + places + territories + alerts + NWS WMS radar + GOES drape (2D), layer list with freshness | Real-browser test shows the globe drawn; alerts shown equal Live Storms' matches; page returns "Data unavailable" with the network off; `/globe` in `manifest.selftest`; CI green |
| 2 | Clouds lifted by cloud-top height (GOES ACHA), parallax corrected or disclosed | Height texture refreshes every 5 min; a known high-top storm shows higher than stratus in a recorded case |
| 3 | 3D storm volumes near saved places from MRMS (≥20/35/50 dBZ), MESH swath, "No radar coverage" mask | Voxels for a recorded Montana hail day (e.g. SPC 2025-06-15 Benchland 1.75″) line up with SPC reports within 5 km; frame bytes under the §10 budget |
| 4 | Time: last 2 h loop, scrub, per-frame freshness | Each frame shows its valid time; a gap shows as a gap |
| 5 | Laptop performance and offline behaviour; installer impact decided | 30 fps on the D-G7 floor; memory under 1 GB; outage test shows Stale then Unavailable |

Tests with every phase (rule: add tests with behaviour changes): feed contract entries in
`weather.CONTRACTS` for GOES and MRMS, synthetic-grid unit tests for crop/threshold/voxel code,
a Playwright check that the canvas is drawn (rule 8), and the 240 alert scenarios untouched.

## 7. Risks, ranked

1. **Rule 4 / D1 conflict** — needs an owner decision, not a workaround.
2. **Data volume** — the 3D mosaic is tens of MB per 2 min; a crop-and-publish job is likely
   required (D-G2).
3. **WebGL in the desktop shell** — WebView2 and WKWebView are fine on paper; Linux GTK is weak;
   must be verified on real machines like the installers (roadmap 1).
4. **50 MB payload cap and offline self-test** (D4) — library from a pinned CDN, or shipped in a
   new installer.
5. **Terms** — Sentinel-2 cloudless is non-commercial; Google imagery/tiles are paid and cannot be
   cached; Cesium's ion assets need an account; IEM tiles are best-effort. Free, public-domain
   sources exist for every layer.
6. **Expectation gap** — "holographic" clouds: satellite gives tops, not bases; radar gives
   reflectivity, not hail. The view must look like what the data is.
7. **Montana radar gaps** — four sites; overshoot in the east and mountains; MRMS mask must be shown.

<!-- Findings from the agents follow. Sections 8–12 are written from structured results. -->
