## 1. Bottom line

1. **What was asked (2026-10-17).** The owner wants "records of hail and wind within the past 5 years for the location of every house in the state of Montana", the programs that would help, and research of all weather information for each address (wave-1 brief, lines 3 to 6). Research only: nothing ships and no site file changes.
2. **For a roofer, in two sentences.** For a Montana address, the free data can show what radar estimated near it over five years, and which hail and wind reports and official warnings were nearby, each with its source, time and units. It cannot show that a roof was damaged, and a missing report is not "no hail".
3. **What free public data can build now** (window 2021-10-17 to 2026-10-17; counts are verified file counts unless marked estimate):

| Evidence | Free source | Scale | Limits to carry into every record |
|---|---|---|---|
| Radar estimate, MESH daily maximum | NOAA MRMS 12:00 UTC file, open bucket ([mrms-mesh-archive.json](validation-evidence/mrms-mesh-archive.json)) | 1,825 of 1,826 daily files, 901,938,706 bytes; 450,765 cells in the simplified Montana outline ([hosting-and-architecture.json](validation-evidence/hosting-and-architecture.json)) | Units read "unknown"; codes -1 and -3 unverified; 2022-06-09 missing |
| Point reports, hail and wind | NCEI Storm Events, SPC, IEM local storm reports ([point-reports-archives.json](validation-evidence/point-reports-archives.json)) | Hail 1,347 LSR reports ([point-reports-archives.json](validation-evidence/point-reports-archives.json)); thunderstorm wind 1,208 NCEI events ([wind-history.json](validation-evidence/wind-history.json)) | NCEI file ends 2026-06-30; summer 2025 times differ by 60 min between some sources, cause not established |
| Radar hail signatures | NCEI SWDI nx3hail ([swdi.json](validation-evidence/swdi.json)) | 60,357 Montana detections; 32,502 at 1.00 in or more | No records 2025-06-15 12:00 to 24:00 UTC; none on 2026-10-13 |
| Official warnings with hail and wind tags | IEM archive of NWS warnings ([warnings-archive.json](validation-evidence/warnings-archive.json)) | 2,240 severe thunderstorm and 17 tornado polygon events | Hail tags on 12.2 to 15.5 percent of 2010 to 2013 severe thunderstorm warnings; NWS alerts API keeps 7 days only |
| Station gusts | IEM daily summary, 60 Montana ASOS sites ([wind-history.json](validation-evidence/wind-history.json)) | 1,264 station-days at or above 50 kt | A 255.0 kt value needs quality control; source type undocumented |
| Modeled gusts | NOAA HRRR analysis ([wind-history.json](validation-evidence/wind-history.json)) | 43,824 hours; storm-day subset about 10.7 GB (computed) | Model value, not an observation |
| Address points | Montana State Library structures framework ([montana-addresses.json](validation-evidence/montana-addresses.json)) | 674,715 points; 493,975 residence-coded | Coordinates from the shapefile only; no owner field; accuracy disclaimed |

4. **What cannot be built yet, or not at all:**
- **A damage finding, damage probability or insurance answer** from any source here (AGENTS.md line 73, rule 5).
- **A hail size in inches at an address.** MESH units are unverified: GRIB units read "unknown" ([mrms-mesh-archive.json](validation-evidence/mrms-mesh-archive.json), "GRIB units attribute"). One 15 km test gives 35.7 at the brief's check point and 51.3 at the SPC report point, 12.7 km apart, if the unit is mm ([evaluation-and-wording.json](validation-evidence/evaluation-and-wording.json), "Benchland 15 km maximum depends on the centre").
- **A complete list of Montana houses.** No source is verified complete. 674,715 structure points against 514,803 housing units give a state ratio of 0.96 and county ratios from 0.48 (Glacier) to 1.36 (Sanders) ([montana-addresses.json](validation-evidence/montana-addresses.json), "Residence-coded address points"). The housing-unit layout is still unverified in [geocoding-and-lookup.json](validation-evidence/geocoding-and-lookup.json).
- **Wind at an address.** NCEI High Wind events carry no coordinates (2,968 for 2020 to 2026; [wind-history.json](validation-evidence/wind-history.json)); station gusts were sampled for one month only; HRRR gusts are model values.
- **Per-address publication before the owner and counsel decide.** The structure data are offered "for no other purpose"; parcel metadata quotes MCA 2-6-1017; GitHub's Actions and Pages clauses are for counsel ([montana-addresses.json](validation-evidence/montana-addresses.json); [hosting-and-architecture.json](validation-evidence/hosting-and-architecture.json)). Parcel owner names are not to be published.
- **A hit or false-alarm rate.** The predeclared evaluation (section 08) has not been run.

5. **Programs (section 07).** Free software and hosting (pygrib or eccodes, DuckDB, tippecanoe, PMTiles, GitHub Pages, and the Cloudflare R2 free tier if the owner accepts an off-site host) cover the build; commercial history services exist, but the terms read restrict resale, five were blocked or unreachable, and nothing is ranked ([commercial-and-tools.json](validation-evidence/commercial-and-tools.json)).
6. **Decisions the owner must make** (options and recommendations in section 09):

| ID | Decision |
|---|---|
| OW-H1 | Five-year window: trailing from today (2021-10-17 onward; section 04 gives the day count), or the brief's 2020-10-01 to 2025-10-17 ([point-reports-archives.json](validation-evidence/point-reports-archives.json)) |
| OW-H2 | Per-address publication: a public lookup by typed address, a private tool, or none; no address list is published under any option |
| OW-H3 | Hosting: GitHub Pages only (about 39.5 MB, estimate) or object storage (Cloudflare R2; needs the off-site host decision) |
| OW-H4 | Daily job and fallback: 4 scheduled runs in the P0 record (median gap 151.5 min); about 9.5 starts a day against 144 nominal ([hosting-and-architecture.json](validation-evidence/hosting-and-architecture.json)) |
| OW-H5 | MESH units and codes: mm assumed with a plausibility rule; no size shown until verified |
| OW-H6 | Address source and owner-name exclusion: structure points or parcels |
| OW-H7 | Counsel: MCA 2-6-1017 and 2-6-109, the "for no other purpose" line, GitHub clauses, NCEI reuse, vendor terms |

7. **First build step.** H1 as a raw-value prototype in this folder: daily maxima and codes for the 1,825 files, one Montana store with a point lookup. It can start now because it keeps file values and shows no size. The H0 gates on units and codes and on the window must close before any size or page. Check each file: the 12:00 UTC file matched its trailing 24-hour maximum on 2025-06-15, 2025-06-16 and 2026-10-16 but not on 2025-06-26, and the cause is not found ([mrms-mesh-archive.json](validation-evidence/mrms-mesh-archive.json); [hosting-and-architecture.json](validation-evidence/hosting-and-architecture.json)).
8. **Process.** Two workstreams exceeded the 300 MB download cap in review: W2 (about 318 MB; [point-reports-archives.json](validation-evidence/point-reports-archives.json)) and W6 (about 325 MB combined; [montana-addresses.json](validation-evidence/montana-addresses.json)). Section 10 has the byte counts.
