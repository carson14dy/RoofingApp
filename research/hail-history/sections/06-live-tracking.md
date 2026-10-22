## 6. Live tracking

Research only; nothing ships. Keys: mrms = [mrms-mesh-archive.json](validation-evidence/mrms-mesh-archive.json); swdi = [swdi.json](validation-evidence/swdi.json); pr = [point-reports-archives.json](validation-evidence/point-reports-archives.json); ew = [evaluation-and-wording.json](validation-evidence/evaluation-and-wording.json). "f12" is fact 12 in the file's facts list, counted from 1. "flag F" means the file marks the fact verified false, so it is not restated here as true.

**Bottom line.** A MESH swath can be a research layer behind the storm-layers flag, but no size, class, footprint or "no coverage" wording until the MESH units and the codes -1 and -3 are verified. Build order: the LSR report layer first (it needs no units, but the ROADMAP Next 4 metrics come first, docs/ROADMAP.md:47-49), SWDI only as a labelled archive, and MESH swaths last (section 9, H5).

### 6.1 Swath products: cadence and bytes
| Product (NOAA bucket) | Step | Files per day | Bytes per day, 2023-06-15 | Bytes per day, 2025-06-15 | Mean per file, 2025-06-15 (computed) |
|---|---|---|---|---|---|
| MESH_00.50 (2-minute frame) | 120 s | 720 | 40,751,607 | 43,436,627 | 60,329 |
| MESH_Max_30min | 120 s | 720 | 65,378,571 | 73,569,935 | 102,181 |
| MESH_Max_60min | 120 s | 720 | 86,308,176 | 99,666,656 | 138,426 |
| MESH_Max_120min / 240min / 360min | 1800 s | 48 each | 8,255,427 / 12,772,638 / 16,992,544 | 9,741,861 / 15,330,219 / 20,576,353 | 202,955 / 319,380 / 428,674 |
| MESH_Max_1440min | 1800 s | 48 | 46,677,795 | 63,294,028 | 1,318,626 |

Steps and bytes: mrms f3 (steps) and f64 (gzip sizes from S3 listings). The 1440 file follows the season: daily median 52,301 B in 2025-01 and 1,289,918 B in 2025-07 (mrms f13). Five years of 1440 files at 30-minute steps: 87,637 files and 43,543,849,418 B (mrms f12). The daily 12:00 UTC series is 901,938,706 B (mrms f10; section 5).

- **Latency and refresh.** Measured for the 1440 file only: listed at 12:08:20 UTC for the 12:00 file on 2025-06-16 (ew f19); S3 LastModified minus file time had a median of 508 s on 2025-06-16 and 1,414 s on 2025-06-15, and a maximum of 3,623 s (ew f62). Not measured for the 30 to 360 minute products. The bucket describes a 2-minute update cycle (mrms f44). A site layer updates at the build rate: measured gaps between scheduled starts on main had a median of 151.5 min (research/globe/README.md:13; section 5).
- **Gaps.** 693 of 720 frames on 2021-06-15, largest gap 3,359 s (mrms f8); 112 frames on 2020-10-14, with a 73,088 s gap (mrms f56). IEM has no 12:00 files before 2022-06-15 (mrms f39) and differs from the bucket on four 12:00 files (mrms f40).
- **Window and time.** The 12:00 file equals the 720-frame maximum on 2025-06-16 (ew f59), but not on 2025-06-26, where 211,686 of 24.5 million points differ (computed from mrms f57; the general rule is flag F, mrms f15). No evidence file tests the 30 to 360 minute products against their frames. A swath has no time: the Benchland 35.7 equals the largest 2-minute frame, at 20:10:42 UTC on 2025-06-15 (mrms f16).

### 6.2 From a swath to "addresses inside the estimated footprint"
1. Read one file. Cells are 0.01 degree, about 1.11 km north to south and 0.73 km east to west at 49 N (ew f10). Codes -1 and -3 are counted as not a value, never as zero, dry or no hail (ew pre_checks). Over 721 frames of 2025-06-25 and 26, -3 was 33.68 to 77.93 percent of the full grid (mrms f59); its meaning is unverified (mrms f27, flag F).
2. Check plausibility. No rule exists; maxima of 457.4 and 199.8 file units occur (mrms f28, f61).
3. Convert classes only after units are verified: 0.75, 1.00, 1.50, 1.75 and 2.00 in are 19.05, 25.4, 38.1, 44.45 and 50.8 mm (ew f52).
4. Keep cells at or above the class, group touching cells (8-connected), and outline the union per swath (ew event_definitions; docs/ROADMAP.md:70-72). That union is the footprint.
5. An address is inside only if its point falls in a footprint cell. A circle is a search area, not a footprint (ew spatial_match). The centre matters: on the 1440 file, 51.3 units about the SPC point and 35.7 about 47.0 N, 109.9 W, 12.72 km apart, so the 1.75 class is missed from the second centre (ew f61; the file labels the values mm, which is unverified).
6. Word it with the address-count template and its required line: "... inside the estimated footprint ... It does not count damaged roofs" and "It does not show that a roof was damaged" (ew wording.templates.address_count, required_lines.not_damage). The radar_estimate template uses a search radius and needs a footprint version. No per-address result is published before section 8 and the owner decide; owner names stay out (ew privacy).

### 6.3 Live feeds
| Feed | Evidence kind and units | Latency and size (measured) | Limits and traps |
|---|---|---|---|
| IEM LSR API (lsr.py, CSV, Montana) | Point report: IEM copy of NWS Local Storm Reports; VALID in UTC; QUALIFIER E, M or U | "as live as when you query it" (pr urls_checked); no request limit found (pr terms); 73 monthly pulls, 8,288,063 B; the 2025 file alone is 1,470,975 B for 8,965 rows (ew urls_checked) | The IEM help page states no magnitude unit (pr f22, flag F). D and O rows carry MAG "None" (pr f21). Qualifier against NCEI type: 1,037 agree and 18 do not, of 1,055 (pr f55). Unquoted commas in CITY (pr f53). Do not chain reports: 44 hail rows on 2025-06-15 form 19 clusters (pr f41) |
| SWDI nx3hail (filtered: PROB 100, MAXSIZE above 0) | Radar signature at a point; MAXSIZE in inches per the NWS ICD (swdi f9, f10); accuracy about 1 km near the radar to 4 km at 230 km (swdi f22) | Not live: posted 0.56 to 4.09 days after the record day ended (Sep to Oct 2026, median 0.75; swdi f5). 24 h Montana box: 17,142 B for 304 rows (swdi urls_checked) | No records 2025-06-15 12:00 to 24:00 UTC, or on 2026-10-13 (swdi f4, f6); the gap is also in the Plains box (ew f63). 744-hour limit on row output (swdi f7). No warn or plsr product (swdi f3). Archive duplicates (swdi f18) |
| SPC daily hail and wind CSV | Preliminary, unfiltered report; hail in hundredths of an inch; wind in mph (pr f44) | Same report day (website/sources.py:107); 2025 yearly file came 114 days after year end (pr f14); NCEI Storm Events 2025 file came 231 days after year end (pr f34); 2025-06-15 hail file 7,960 B, 33 Montana rows (pr urls_checked) | 2026 yearly files return 404 while daily files exist (pr f47). The 2025 daily files have no hail below 1.00 in (ew f56). FAQ 6.11 filter: 10 miles, 15 minutes (ew f55) |

### 6.4 What is blocked, and what is not
| Blocked | Why | Unblocked by |
|---|---|---|
| Any MESH size, class or footprint, on the Map, in a record or an export | A NOAA web page gives mm as the base unit and inches for display (ew f9, verified). The file's units key reads "unknown" (mrms review.confirmed). That page says "Latest update 'MRMS Version 10'" (ew f10), but v12 began 2020-10-14 (mrms f29) | A units check against the NSSL table (its host failed TLS verification, mrms urls_checked) or an NCEP document |
| "No coverage", "missing" or "no hail" from codes -1 or -3 | Codes unverified (mrms f27, flag F; the search excerpt in mrms f33 is flag F too). Allowed now: "code -1 or -3 (meaning not verified). This is not an all-clear" (ew review.corrections; wording.templates.radar_no_value) | The NSSL table, read from a session that can open it |
| P3 layer of the globe plan | Gate: units and codes verified, and predeclared metrics at zero mismatch (research/globe/README.md:155, :423). No new MESH feed reaches main before the owner approves the evaluation (globe :550, D40; OW-21 at :69) | Section 9, H0 gates |
| 30 to 360 minute swaths | No window test in any evidence file (mrms f15, flag F; f57 covers one day) | A window test on held-out days (ew splits) |
| Address counts on any page | Publication rule (section 8); owner names excluded (ew privacy) | Owner and counsel decisions (section 9) |

Not blocked: file decoding and checks (mrms f20, f21, f23, f24), byte and timing measurements, the LSR and SPC report layers with their own labels, and the SWDI signature layer with inch labels from the ICD and a lag label.

### 6.5 Repo state and conflicts
- The flag is off by default (website/build.py:522-523) and set only on branch builds (.github/workflows/website.yml:95). A MESH layer would be P3 of the globe plan, labelled "Estimated hail (not observed hail size; not damage)" (research/globe/README.md:88). Frames are built in Python (AGENTS.md:66-72; decoder at website/gridded.py:452), and the browser fetches site files only (docs/DECISIONS.md:492). Neither LSR nor SWDI is in website/sources.py, so each needs a CONTRACTS entry and a live content check first (AGENTS.md:80-84).
- Conflict: the wording principle "MESH in inches with the mm base value in brackets" (ew wording.principles) against the globe rule of no size words until units are verified (research/globe/README.md:71, D-G23; :543, D33). Section 9 settles it.
