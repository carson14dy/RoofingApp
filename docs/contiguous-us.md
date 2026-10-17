# Contiguous US: plan

Planning for D24 (the contiguous US after Montana) and Roadmap Next 14. This document is the only change: no code, data or settings were touched.

Measured on 16–17 October 2026 (UTC) from a 2-vCPU, 8 GB sandbox (Python 3.13, numpy, pygrib 2.1.8) against the live NWS, SPC, NOAA S3 and GitHub services. Each figure is marked **measured** (taken in those runs), **estimate** (arithmetic or extrapolation from measured parts) or **documented** (from GitHub's documentation). KB and MB are decimal. The rules that apply are AGENTS.md 5 (evidence) and 7 (feeds: check the content, not just HTTP 200).

## 1. Bottom line

1. **Fix the build cadence before any expansion.** GitHub recorded three scheduled runs of the Website workflow on `main` in about nine hours (19:42, 22:14 and 00:35 UTC, 142 to 152 minutes apart), not one every 10 minutes. The live site was 65 minutes old at 01:41 UTC. Each new region adds data to every build, so the freshness problem grows with the scope. Section 10.
2. **The NWS alerts query takes several states in one request** (measured). Five states: 37.5 KB. The 48 contiguous states: 1.1 MB. The national feed: 2.5 MB. Use the state list, as D24 proposes.
3. **SPC files are national and cannot be filtered on the server** (measured). A day's file is 49 bytes to 35 KB. A state or box filter saves parsing time only, not download.
4. **The map already downloads CONUS-wide data.** MRMS and HRRR are read as full continental grids, so a build downloads about 39 MB whatever the map's extent (measured). Only the number of picture pixels scales with extent.
5. **Frame resolution sets the cost to viewers.** One CONUS grid at Montana's resolution gives about 25 MB per full map visit and about 2 min 15 s of frame work in the sandbox (measured; the runner was not measured). A coarse CONUS grid is 3 MB, but its temperature and gust pixels are about 7 km, more than twice HRRR's 3 km. Regional grids at Montana's resolution cost about what Montana costs now (estimate).
6. **Towns, not the map, set the build time.** Each town costs 9 NWS requests and 1.0 to 1.5 s in series (measured). Without code changes, the 15-minute job limit allows roughly 500 to 870 towns, depending on the option and the NWS time per town (estimate).
7. **The base map is about eleven times today's file for the contiguous US**: 4.2 MB raw against 0.39 MB, at the same tolerances (measured). A region of three or four states is about today's size.
8. **Recommended order:** Phase 0 cadence; Phase 2 North and South Dakota and Wyoming; Phase 3 Kansas and Colorado; Phase 4 the contiguous US as regions. Section 12 lists the decisions for Carson. The first map decision is time zones: the Dakotas bring Central time into a map that shows only Montana time.

## 2. Method and limits

**Measured live:** NWS alerts (five requests); SPC daily CSVs (seven days, 14 files; one older day returned 404); the MRMS listing and seven radar files; HRRR index files and field byte ranges; GitHub Actions run history and job timings (REST API); the live Pages site (`map.json`, `state.json`, `basemap.json` transfer sizes); one full Montana build from live data, logged request by request (run twice); CONUS frame builds at three widths on a scratch copy of the website package; the Natural Earth and us-atlas source downloads. The proxy refused and timed out nothing.

**Measured by running code on scratch copies (the repository was not changed):** the basemap builder's layer functions for the Montana box, the two candidate regions and the contiguous US; the town check's run time on synthetic town lists.

**Read in the code:** the number of NWS requests per town, the frame preloading in `map.js` (`preload`, line 1086), the Montana references, the SPC missing-file rule in `build.reports`.

**Not checked:** GitHub runner speed and memory (only the runner's own step times are measured); NWS and S3 latency from GitHub's network; any CONUS town against the live NWS (no CONUS town was built); the full basemap builder for CONUS (labels, Canada and the context layer were not run); real phones; the private-repository minute quotas (not on the docs page read).

The repository is public (REST API), so standard runner minutes are free (documented).

## 3. Baseline: Montana today

| Item | Value | Basis |
|---|---|---|
| Full build, 14 towns, live data | 37.0 s and 32.1 s in two runs | measured, sandbox |
| "Build from live data" step on GitHub | 13 to 34 s across eight `main` runs | measured, Actions API |
| Scheduled run, build job | 50, 56, 60 s; deploy job 8 to 11 s | measured, Actions API |
| Requests in one build | 199: 127 NWS, 41 HRRR fields, 16 HRRR indexes, 7 MRMS, 2 MRMS listings, 6 SPC | measured |
| Bytes downloaded | 46.6 MB: HRRR fields 34.8 MB, NWS 7.3 MB (alerts included), MRMS 4.2 MB, indexes 0.16 MB, MRMS listings 44 KB, SPC 7 KB | measured |
| Failed requests | 3 of 199: two stations returned 404 (LDSM8, FASM8); one HRRR index for a run not yet published | measured |
| Site size | 3.84 MB: 48 frames 2.61 MB, basemap 0.38 MB, town pages 0.26 MB | measured |
| Live transfer | basemap 110 KB gzip (385 KB raw); `map.json` 5.9 KB gzip (47.5 KB raw) | measured, live |

NWS bytes per town per build: about 0.5 MB, mostly the hourly forecast (163 KB per response) and the gridpoint data (222 KB per response).

## 4. NWS alerts (question 1)

Yes. `area` takes a comma-separated list. Measured against `api.weather.gov/alerts/active`, 16–17 October 2026, 01:25 UTC:

| Request | Result | Bytes | Alerts |
|---|---|---|---|
| `area=MT` (today) | 200 | 12,586 | 3 |
| `area=MT,WY,SD,ND,ID` | 200; the title lists the five states | 37,544 | 8 |
| `area=` the 48 contiguous states plus DC | 200 | 1,106,903 | 196 |
| no `area` (national) | 200 | 2,531,441 | 524, including marine zones and Alaska, Hawaii and Puerto Rico |

- The five-state response contains the three Montana alerts (the same ids as `area=MT`) and five more, for SD, WY, MN, IA and NE.
- Two identical `area=MT` requests returned identical bytes. Per alert: 4 to 6 KB.
- Estimate: 500 alerts across 48 states would be about 2.5 to 3 MB per poll.
- D24 asked for the national response to be measured. It is 2.5 MB, so the state list stays.

Change for Phase 2: `website/build.py` `alerts()` builds its `area` from the region's states (today `{"area": "MT"}`), the text of `sources.CONTRACTS["alerts"]`, and a test that replays a saved five-state response (about 38 KB, no network). The per-town point checks (`add_town_alerts`) already cover out-of-state zones for towns near a border (code reading; not checked live).

## 5. SPC storm reports (question 2)

The files are national. Each file holds rows from many states (for example PA, WY and MN), and the code uses only the national file, `YYMMDD_rpts_filtered_{hail,wind}.csv`. I found no per-state file.

| Reporting day (UTC) | Hail | Wind | Rows (hail + wind) | In Montana box plus 0.75° |
|---|---|---|---|---|
| 2026-10-16 | 49 B (header only) | 3,418 B | 0 + 26 | 0 |
| 2026-10-15 | 49 B | 360 B | 0 + 2 | 0 |
| 2026-10-14 | 140 B | 2,500 B | 1 + 25 | 0 |
| 2025-06-15 | 4,160 B | 10,859 B | 38 + 125 | 22 + 35 |
| 2025-05-29 | 1,968 B | 6,925 B | 20 + 49 | 0 + 3 |
| 2024-05-21 | 6,265 B | 34,872 B | 74 + 305 | 0 + 0 |
| 2013-05-31 | 5,384 B | 14,715 B | 79 + 153 | 0 + 0 |

The 14 files total 91,664 bytes and 897 rows; 60 rows (6.7%) fall inside the Montana box. The filtered file for 27 April 2011 returned 404 for both kinds (measured). The build marks a missing file as a problem for an older day and not for today (`build.reports`), so an old gap would show in the status line.

**Filtering cost:** the file comes whole, so a state or box filter cannot reduce the download. The only cost is parsing, which takes milliseconds. Keep the national download and filter in Python, as now. The largest day tested had 305 wind rows (35 KB); a major outbreak day was not measured.

Phase 2 change: `parse_spc` takes a list of boxes (`near_montana` becomes `near_region`), and the text of `CONTRACTS["reports"]`.

## 6. MRMS and HRRR (question 3)

### 6.1 Grids (measured from the files)

| Source | Grid | Points | Extent | Use today |
|---|---|---|---|---|
| MRMS PrecipRate (`CONUS/PrecipRate_00.00`) | 7000 × 3500 at 0.01° | 24.5 M | 20.0 to 55.0° N, 130.0 to 60.0° W | whole grid decoded, then sampled to each frame |
| HRRR `wrfsfcf` and `wrfsubhf` | 1799 × 1059, 3 km Lambert | 1.9 M | 21.1 to 52.6° N, 134.1 to 60.9° W | 41 single fields by byte range |

Both grids cover the whole contiguous US. A CONUS frame (24 to 50° N, 125 to 66.5° W) sits inside both.

### 6.2 Sizes and times (measured)

| Item | Size | Time |
|---|---|---|
| MRMS file, gzip (the seven newest) | 580 to 590 KB each; 4.24 MB total | download 0.21 to 0.48 s each; decode 0.35 s each |
| HRRR TMP 2 m, run 00 UTC, hour 13 | 1.25 MB | 80 ms per download; decode 49 ms |
| HRRR GUST at the surface, same hour | 1.37 MB | as above |
| HRRR PRATE at the surface, same hour | 92 KB | as above |
| HRRR index (`.idx`) | 10.5 to 11.7 KB | 0.2 to 0.4 s |

Per build: 41 HRRR fields (34.8 MB) and seven MRMS files (4.2 MB), about 39 MB. D28's "about 40 MB" holds.

Because the files are full grids, the same bytes serve every extent. A CONUS build made 65 fresh fetches (39.25 MB) and spent 7.1 s on the network. Decoding reads the whole grid and does not change with extent. What scales with extent is the pixel count: sampling, bilinear interpolation, smoothing, colouring and PNG encoding.

### 6.3 Frame options (measured frame builds on the same live data)

Each build draws 48 frames: 22 precipitation (7 radar, 15 model), 13 temperature and 13 wind gust.

| Option | Precipitation, pixels per ° of longitude | Temperature and wind, pixels per ° | Frame work | Frames per build | Per full visit |
|---|---|---|---|---|---|
| Montana today | 80 | 40 | about 17 s in the profiled build, with downloads | 2.6 MB | 2.6 MB (dry evening) |
| A: CONUS, 1400 px | 24 | 12 | 21.8 s, including 7.1 s of downloads | 3.2 MB | 3.2 MB |
| B: CONUS, 2800 px | 48 | 24 | 37.9 s (cache warm) | 10.5 MB | 10.5 MB |
| C: CONUS at Montana's resolution | 80 | 40 | 127.5 s (cache warm); about 135 s with downloads (estimate) | 24.7 MB | 24.7 MB |
| D: regions at Montana's resolution, each | 80 | 40 | about 17 s per region (estimate; decode shared) | about 2.6 MB per region | about 2.6 MB per region visited |

Notes:
- At 37° N, one temperature or gust pixel is about 7 km wide in A, 3.7 km in B and 2.2 km in C. HRRR is 3 km. Montana's own pixels are about 2 km.
- Frame size depends on rain for precipitation only. Montana's precipitation frames weighed 0.03 MB on a dry evening; the coarse CONUS build's weighed 0.98 MB in the same hour. Temperature and wind frames are fixed by the field.
- `map.js` preloads every remaining frame of a layer once one shows (`preload`, called from line 1023 on the full map), so a visit downloads the layer's whole set.
- Peak memory in the sandbox: A 336 MB, B 531 MB, C 1.26 GB. The runner's memory was not measured.

Option D needs no extra download and decodes the grids once. Estimate for four regions: about 4.5 s of decoding once, then about 12.5 s per region, about 55 s in all.

### 6.4 Build time and the 15-minute limit

Model: T = F + p × N, where N is the number of towns, F the frame work plus fixed steps (alerts, SPC, pages) and p the NWS time per town. Measured: F is about 27 s for A (frames 22 s plus about 5 s), about 50 s for B and about 135 s for C. p is 1.0 to 1.5 s (in one run the 14 town calls took 13.3 s; in another all NWS requests took 21 s, about 1.5 s per town). The table gives estimates.

| Option | 14 towns | 100 towns | 300 towns | 500 towns | Most towns within 15 min (p = 1.5 s / 1.0 s) |
|---|---|---|---|---|---|
| A | 0.8 min | 3.0 min | 8.0 min | 12.9 min | 582 / 873 |
| B | 1.2 min | 3.3 min | 8.3 min | 13.3 min | 566 / 850 |
| C | 2.6 min | 4.8 min | 9.8 min | 14.8 min | 510 / 765 |

The 15-minute limit is the workflow's own `timeout-minutes: 15` on the build job, not a GitHub limit. Today's build step takes about a minute on GitHub (measured).

Two ways to widen the margin, both estimates:
- Fetch towns in parallel. Four workers would cut p by about four times, if NWS accepts it. Not tested.
- Cache model frames by HRRR run. 41 of the 48 frames are model frames, which change once an hour, so about 70% of frame work could be reused between builds (estimate). This is Roadmap Next 6, which becomes a prerequisite for Phase 4.

## 7. Map (question 4)

### 7.1 Base map size (measured with the builder's functions; same tolerances; US layers only)

Check: the lakes, rivers and roads sections of the committed Montana file are within 41 bytes of these measurements, so the method holds.

| Extent | Land | State lines | County lines | Lakes | Rivers | Roads | Total |
|---|---|---|---|---|---|---|---|
| Montana box (today) | 14 KB | 12 KB | 80 KB (all counties in the box; the file keeps Montana's 40 KB) | 53 KB | 161 KB | 80 KB | 400 KB |
| North and South Dakota plus Wyoming (0.5° margin) | 15 KB | 15 KB | 95 KB | 39 KB | 126 KB | 93 KB | 384 KB |
| Kansas plus Colorado (0.5° margin) | 12 KB | 13 KB | 77 KB | 14 KB | 82 KB | 91 KB | 290 KB |
| Contiguous US | 216 KB | 125 KB | 952 KB | 597 KB | 1,193 KB | 1,137 KB | 4,220 KB |

- `tools/build_basemap.py` has a 450,000-byte budget. The committed file is 384,594 bytes with Canada, labels and places included.
- Compression: the committed file gzips to 28% (the live transfer is 110 KB). At that ratio CONUS would transfer about 1.2 MB (estimate).
- Build time for the US layers: about 7 s on the sandbox, of which 3 s reads the cached sources (measured). Label placement and the layout check were not run for CONUS.
- Tolerances can be raised for the wide zooms, and rivers and roads can be cut by rank. Each change needs a decision (section 12).

### 7.2 Map extents and regions (how they would be set)

Montana is set in these places (counts from grep): `website/build.py` (`MAP_VIEW`, `OFFICES`, the alerts area, the map's `tz`); `website/sources.py` (`MT_BOX`, `near_montana`); `website/gridded.py` (`IMAGE_BOUNDS`, `WIDTHS`); `tools/build_basemap.py` (`IMAGE_BOUNDS`, the Montana county selection by FIPS prefix `30`, the label strips, `CONTEXT`); `website/static/map/map.js` (23 mentions: `TZ`, `fitView`, the `bm-mt` highlight); `map.css` (11); six templates; `website/sample.py` (9); and the tests (`test_basemap.py` 35, `test_site.py` 19, `test_gridded.py` 2).

Proposal: one record per region in a `website/regions.json`:
- `id`, `name`, `states` (for alerts and SPC), `bounds` (the frame grid and the map view), `towns` (slugs), `offices`, `timezone` (rule in 7.3), `basemap` (file) and `zoom` (range).
- The build loops over the regions: frames under `map/<id>/`, `data/map-<id>.json`, and a region picker in `map.js` (the viewer's location, D28, picks the region; a location outside every region is said so).
- `tools/build_basemap.py --region <id>` writes `static/map/basemap-<id>.json`.
- Alerts: the union of the states. SPC: the union of the region boxes plus the 0.75° margin.
- Zoom: `MAP_VIEW` starts at zoom 5. At zoom z, Leaflet's 256-pixel tiles show 360 / (256 × 2^z) degrees per pixel, so a 390-pixel phone at zoom 5 shows 17° of longitude. The 58.5° of the contiguous US needs zoom 3.2 (arithmetic). A CONUS view therefore needs a minimum zoom near 3, below the builder's zooms 5 to 11 and its label layout.

### 7.3 Time zones (the largest map change; not measured)

Every time on the map is Montana time: `map.json` carries `"tz": "America/Denver"` (`build.map_data`) and `map.js` has `TZ`. The NWS gives each town's zone (`parse_point` reads `timeZone`), so the data exists. From general knowledge, not checked against a source here: North and South Dakota are mostly Central, with Mountain time in the west; Kansas is mostly Central with a Mountain strip in the west; Wyoming and Colorado are Mountain. The policy is decision 2 in section 12.

## 8. Towns (question 5)

- Each town makes nine NWS requests per build: point, hourly forecast, gridpoint, 7-day forecast, point alerts, station list and three station readings (code reading; 127 requests for 14 towns, measured).
- Time: 1.0 to 1.5 s in series per town (measured in two runs).
- `website/towns.json` has 14 lines of about 90 bytes. Each town's label side is set by hand, and `tests/test_basemap.py` checks it with `check_layout` and `town_contacts`.
- The check's run time (measured, synthetic towns across CONUS): 14 towns 8 ms; 50 towns 60 ms; 100 towns 190 ms; 200 towns 440 ms; 400 towns 2.4 s. The check is not the limit.
- Density is the limit. On random CONUS points (not real towns), the check found 3 collisions at 50 towns, 35 at 100, 75 at 200 and 388 at 400. At real density the bubble layer needs: a minimum zoom per town (as places have `min_zoom`); an automatic label side (try the four sides and keep the first clear one); a rank so that low zooms show fewer towns; and the check run per zoom against the towns shown at that zoom.
- Per town per build (measured): town page 18.9 KB, `state.json` 3.2 KB, `map.json` 3.3 KB, about 25 KB in all. At 300 towns the site would be about 7.6 MB more (estimate).

## 9. Cost and limits (question 6)

### 9.1 GitHub Actions minutes
- A public repository's standard runners are free (documented).
- Cadence as designed: 144 runs a day. Measured job times: build about 50 to 60 s, deploy 8 to 11 s. If each job rounds up to the whole minute (the docs page read does not state the rounding rule), that is two billed minutes per run: 288 a day and about 8,640 in 30 days (estimate). With per-second billing it would be about 4,750 (estimate). This matters only if the repository goes private; private quotas were not checked.
- Observed: three scheduled runs in about nine hours, about 16 billed minutes a day at the same rounding (estimate).
- Branch builds (`claude/**`): build job 67 to 122 s and the Chromium smoke test 30 to 70 s (measured), two to three minutes each. A CONUS map test would take longer (not measured).

### 9.2 GitHub Pages (documented limits)
- A published site may be no larger than 1 GB. Now 3.8 MB; with option C and a CONUS base map, about 30 MB (estimate).
- Bandwidth: a soft limit of 100 GB a month. A full visit downloads 2.6 MB today (about 38,000 visits a month within the limit), 3.2 MB at A (31,000), 10.5 MB at B (9,500) and 24.7 MB at C (4,000). Estimates; they assume each visit loads every frame.
- The soft limit of 10 builds an hour does not apply to a custom Actions workflow, which this one is.
- A deployment times out after 10 minutes; the deploy job's limit is also 10 minutes.

### 9.3 Frame storage
Pages keeps only the latest deploy, so frames do not accumulate: each build replaces the 48 frames. Archiving frames every 10 minutes would cost about 3.6 GB a day at option C (estimate: 24.7 MB × 144). Do not archive frames; archive the numbers behind them.

### 9.4 State history (Roadmap Next 4)
`state.json` is 3.2 KB per town per build. Hourly commits (8,760 a year) would add about 0.4 GB a year uncompressed for 14 towns, 2.8 GB for 100 and 8.4 GB for 300 (estimate). Git's delta compression will reduce this; it was not measured. Keep the hourly record small (a few values per town), or sample it.

## 10. Build cadence (blocks Phase 2)

Measured (GitHub API, `website.yml`, event `schedule`): three runs in total, created at 19:42:35, 22:14:06 and 00:35:40 UTC on 16 and 17 October; gaps of 152 and 142 minutes. The first `main` run in the recent list was at 16:35 UTC. The live site's `built` field read 00:36:01 UTC when checked at 01:41 UTC, 65 minutes later.

Documented (GitHub, events that trigger workflows): a schedule "can be delayed during periods of high loads of GitHub Actions workflow runs"; "High load times include the start of every hour"; and "to decrease the chance of delay, schedule your workflow to run at a different time of the hour". The workflow runs at `*/10`, which includes minute 00 of every hour. The same page says public-repository schedules are disabled after 60 days without activity; this repository has activity.

Two facts shape the fix. A schedule event runs only from the default branch, so a change to the cron can be measured only once it is on `main`. No test pins the cron string; `tests/test_website_workflow.py` tests the plan step only.

Options (Carson's call; section 12):
- (a) Move the cron off the hour (for example minutes 3, 13, 23 and so on) and measure for 24 hours.
- (b) An external scheduler that starts `workflow_dispatch` every 10 minutes. This needs a token and an outside service.
- (c) Accept the delay, keep the age on every page (already shown) and say so on the About page.

## 11. Phases

### Phase 0: cadence (before Phase 2)
- Code: the cron in `.github/workflows/website.yml`. Option (b) would also need a token and a trigger.
- Exit check: 24 hours on `main` with a scheduled run at least every 15 minutes (`gh run list --workflow=website.yml --event schedule`).

### Phase 1: Montana (done)
- The alerts area is MT, with per-town point checks for border towns (code reading). Left for Montana: the company's limits and the 14 towns (Roadmap 1 and 3).

### Phase 2: North and South Dakota and Wyoming
Why first: these states are next to the market already served and have plains and mountain weather of the same kinds (general knowledge). The frame grid (about 1.3 M pixels at Montana's resolution) and the base map (384 KB) are about Montana's size, so no budget changes. The alert request grows to four states (37.5 KB measured for five). And it tests the two hard policies on a small surface before the 48-state work: time zones (Central in the Dakotas) and a list of regions.

Code:
- `website/regions.json` (new): ND, SD and WY, with their towns and offices.
- `website/sources.py`: `near_montana` becomes `near_region`; the SPC box per region; the `CONTRACTS` text.
- `website/build.py`: the alerts area from the states; `OFFICES` and `MAP_VIEW` per region; the map's time zone per town or region (decision 2); per-region output.
- `website/gridded.py`: per-region `IMAGE_BOUNDS`; frame names carry the region (`frame_src`); cache keys per region.
- `tools/build_basemap.py`: `--region`; county selection by state FIPS; one output file per region; label strips per region.
- `website/static/map/map.js` and `map.css`: region picker; `TZ` per region or per town; fit to the region; the highlight for the region's states; the "Montana" strings.
- Six templates and `website/sample.py`: the region name from a variable.

Tests: a replay of a saved five-state alert response; a border town with out-of-state zone codes; per-region frame bounds and sizes; the label check per region; a time-zone check. The existing Montana tests stay.

Exit: two live branch builds with towns in each state; SD and WY alerts in the list; the SPC box covering the region; the map in Chromium at 288 to 1440 px in both colour schemes; a check on a phone.

### Phase 3: Kansas and Colorado
Why third: it brings the Central and Mountain time split at scale, and Colorado's terrain stresses the label layout. Its frame grid is small (about 0.67 M pixels) and its base map is 290 KB, so the cost is low. It also proves a list of four or more regions, which Phase 4 needs.

Code: region records only, if Phase 2 generalised the code; automatic label sides once the town count passes about 20; labels for the Colorado mountain towns.

Exit: as Phase 2, plus the label check at 20 or more towns.

### Phase 4: the contiguous US
Recommended: regional frame grids at Montana's resolution (option D), a region picker, one base map per region, alerts by state list, and the SPC box as the union of regions.

Code:
- `website/build.py`: parallel NWS fetches (a worker pool, after measuring NWS's response); per-region output; a build-time check.
- `website/gridded.py`: decode once and render per region; a frame cache keyed by layer, valid time and HRRR run (about 70% of frame work saved, estimate).
- `tools/build_basemap.py`: a minimum zoom near 3; label layout for 48 states; a budget per region.
- `website/static/map/map.js`: zoom from 3; region picker by location and by list.

Exit: a full build from live data under 10 minutes at the planned town count (measured, not estimated), and page weight per visit checked against section 9.2.

## 12. Decisions only Carson can make

1. **Scope and order.** Confirm Phases 2 and 3, and whether Phase 4 is one contiguous product or regional pages.
2. **Time.** Local clock per town (the NWS zone), one zone per region, or Montana time everywhere. The Dakotas bring Central time.
3. **Frames.** Regional grids at Montana's resolution (about 2.6 MB per region visited) or one CONUS grid (3.2, 10.5 or 24.7 MB per full visit, with coarse fields at A).
4. **Phone data.** The per-visit size the team accepts, and whether all three layers load at once on a phone.
5. **Cadence.** Move the cron (free, not yet proven), add an external scheduler (a token and an outside service), or accept the delay and say so.
6. **Name and scope.** The product name for several states (D26's trademark check is still open), and whether the About page changes.
7. **Towns.** Which towns in each region, and how many. Today's 14 were chosen for Montana.
8. **Alert scope.** Marine zones, and Alaska, Hawaii and the territories (D24 leaves them out).
9. **Base map.** Raise the 450 KB budget, split by region (recommended), or thin the rivers and roads at wide zooms.
10. **History.** Whether to keep hourly state records, and how much per town.
11. **Limits by region.** Whether the company's limits (D16) differ by state or roof system.

## 13. Proposed roadmap and decision lines

Proposed DECISIONS (numbers for the coordinator to assign):
- **Contiguous US by region (proposed):** regional frame grids at Montana's resolution; one base map per region; alerts by state list; SPC box as the union of regions; no national grid unless Carson chooses one (docs/contiguous-us.md).
- **Measured 16–17 Oct 2026:** the NWS alerts query takes a comma list (five states 37.5 KB; 48 states 1.1 MB); SPC CSVs are national (49 B to 35 KB per file).
- **Measured 17 Oct 2026:** the Website workflow ran three times on its schedule in about nine hours, not every 10 minutes; GitHub documents schedule delays at the top of the hour.

Proposed ROADMAP:
- **Next 0 (new): fix the cadence.** Move the cron off minute 00, measure 24 hours on `main`, then decide on an external trigger (section 10).
- **Next 14:** Phases 2 to 4 as in docs/contiguous-us.md, starting with the time-zone decision (section 12, item 2).
- **Next 6:** cache model frames by HRRR run; now a prerequisite for Phase 4.

## 14. How to repeat the measurements

- Runs and job times: `gh run list --workflow=website.yml --event schedule`, then `gh api repos/<owner>/<repo>/actions/runs/<id>/jobs`.
- Alerts: `curl -H "Accept: application/geo+json" "https://api.weather.gov/alerts/active?area=MT,WY,SD,ND,ID"`, with the User-Agent in `website/sources.py`.
- SPC: `https://www.spc.noaa.gov/climo/reports/YYMMDD_rpts_filtered_hail.csv`.
- MRMS: list `noaa-mrms-pds` with `prefix=CONUS/PrecipRate_00.00/YYYYMMDD/`. HRRR: `hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcfNN.grib2.idx`.
- Build with a request log: run `python -m website.build --out <scratch>` with `requests.Session.get` wrapped to log each URL, its bytes and its time.
- Frame sizes and times: `website.gridded.build_gridded` on a scratch copy with `IMAGE_BOUNDS` and `WIDTHS` changed there only.
- Base-map layers: the functions of `tools/build_basemap.py`, with `BOX` set in a scratch import.

The measurement scripts and downloads were kept in the agent's scratch folder and are not committed.
