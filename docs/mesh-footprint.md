# MRMS MESH hail footprint: feasibility and prototype (ROADMAP Next 11)

Checked 2026-10-16. Branch `claude/mesh-prototype`. Prototype only: `website/mesh.py` is not wired
into `website/build.py`, nothing is shown on the site, and no decision is recorded here.

MESH is a **radar estimate** of the largest hail size. It is not hail measured on the ground, not
verified hail and not damage. An outline says the estimate reached a size in those cells, in that
window. It is never a damage probability and never an insurance answer (AGENTS.md rule 5).

## Bottom line

- **Feasible.** The MRMS bucket answers from this sandbox. One MESH file of each of the seven
  products downloads at its listed size. pygrib 2.1.8 installs from PyPI here and decodes them
  (Python 3.13; CI uses 3.12, which was not run here).
- **Grid and units:** 0.01 degree, 7000 x 3500, values in millimetres (checked against the NSSL
  table, the WDTD page and the values themselves). Divide by 25.4 for inches.
- **Missing values are literal numbers, not masked.** -1 (missing) and -3 (no radar coverage) must
  be removed by the decoder. The file has no zeros.
- **Swath stamps mark the end of the window.** The 30-minute product stamped 00:30 equals the
  maximum of the 2-minute files from 00:00 to 00:30 (9,569 of 9,569 positive cells, zero difference).
- **Montana's download is the whole CONUS file.** The bucket has no regional files. That is
  144 to 188 MB a day for all seven products, or 26 to 31 MB a day for the 2-minute product alone.
  Newest file of each product, per 10-minute build: about 0.9 MB.
- **Prototype:** `website/mesh.py` turns a grid into GeoJSON outlines per size, with holes, corner
  contacts and missing cells handled. On real files it reproduced the cell counts and areas exactly.
  It ran in about 1 second on each full CONUS grid here.
- **Not done:** the SPC 2025-06-15 comparison (Benchland, 1.75 in), real phones, a CI run of the
  new test, and any decision to show MESH on the site.

## Sources checked

| Source | Used for | How it was checked |
|---|---|---|
| NSSL, MRMS operational GRIB2 tables: https://www.nssl.noaa.gov/projects/mrms/operational/tables.php | Product names, GRIB parameter numbers 28 to 34, units (mm), -1 "Missing", -3 "No Coverage", frequency column, "current for MRMS Version 12.2", folder note "00.50 is the height of the field in kilometers" | Read with WebFetch on 2026-10-16. curl fails certificate verification for this host even with the proxy bundle (`/root/.ccr/ca-bundle.crt`); not worked around. The page has no "last updated" date. |
| NSSL WDTD, "Maximum Estimated Size of Hail (MESH)": https://vlab.noaa.gov/web/wdtd/-/maximum-estimated-size-of-hail-mes-2 | "MESH base units (used in calculations): mm"; "MESH units as displayed in AWIPS: Inches"; the SHI and model-profile basis; underestimation cases; bright-band contamination | Read with WebFetch on 2026-10-16. The formula is an image and was not readable. |
| NOAA-NSSL MRMS support repo: https://github.com/NOAA-National-Severe-Storms-Laboratory/mrms-support | README says the flag and user tables moved here on 18 July 2024 | Read with WebFetch. The `GRIB2_TABLES` folder was not readable: `gh api` says the repo is not enabled for this session, and the web tree page is blocked for fetchers by robots rules. Not worked around. The meanings of -1 and -3 come from the NSSL table's column names and from the files. |
| AWS Open Data bucket `noaa-mrms-pds` (https://noaa-mrms-pds.s3.amazonaws.com/) | Folder names, file names, sizes, times, one download per product | S3 listing and GET with curl on 2026-10-16. Each download matched its listed size. |

## Products

All seven share one grid. Files are `CONUS/<folder>/YYYYMMDD/MRMS_<name>_YYYYMMDD-HHMMSS.grib2.gz`.

| Product (NSSL name) | Folder | GRIB param (disc. 209, cat. 3) | NSSL frequency | Files per day | Gzip size (2026-10-15) | Positive cells at 00:00 (2026-10-15) | Max at 00:00 |
|---|---|---|---|---|---|---|---|
| MRMS_MESH | `MESH_00.50` | 28 | 2-min | 720 | 33 to 44 KB (median 36 KB) | 1,959 (at 00:00:42) | 41.3 mm (1.63 in) |
| MRMS_MESHMax30min | `MESH_Max_30min_00.50` | 29 | 2-min | 720 | 38 to 65 KB (median 48 KB) | 11,848 | 58.7 mm (2.31 in) |
| MRMS_MESHMax60min | `MESH_Max_60min_00.50` | 30 | 2-min | 720 | 43 to 86 KB (median 59 KB) | 23,412 | 58.7 mm |
| MRMS_MESHMax120min | `MESH_Max_120min_00.50` | 31 | 30-min | 48 | 52 to 126 KB (median 80 KB) | 47,973 | 88.1 mm (3.47 in) |
| MRMS_MESHMax240min | `MESH_Max_240min_00.50` | 32 | 30-min | 48 | 80 to 187 KB (median 113 KB) | 86,290 | 88.1 mm |
| MRMS_MESHMax360min | `MESH_Max_360min_00.50` | 33 | 30-min | 48 | 101 to 225 KB (median 142 KB) | 102,075 | 88.1 mm |
| MRMS_MESHMax1440min | `MESH_Max_1440min_00.50` | 34 | 30-min | 48 | 372 to 655 KB (median 461 KB) | 400,787 | 88.1 mm |

- "Max" products are the swaths: 30, 60, 120, 240, 360 and 1440 minutes (the 1440 one is 24 hours).
  NSSL's table has no product named "MESH_Max" alone and no other swath lengths.
- `00.50` in the folder name is the field height in kilometres (NSSL's note), i.e. 500 m. The GRIB
  level in every file is 500, type `heightAboveSea`, which agrees.
- The GRIB product template is 0 (analysis), `stepType` `instant`, `stepRange` `0m` for all seven.
  The window length is therefore **not** in the GRIB; it is only in the product name.
- Compared with D28's PrecipRate: same grid, same bucket, same 2-minute cadence. `gridded.decode_mrms`
  checks parameter (209, 6, 1) for PrecipRate; a MESH decoder must check (209, 3, 28 to 34) instead.

## Grid and units

- Regular latitude-longitude, 7000 columns by 3500 rows, 0.01 degree. First point 54.995 N,
  230.005 E (129.995 W); last point 20.005 N, 299.995 E (60.005 W). Row 0 is the north row.
  Columns run west to east. Packing `grid_png`, 16 bits.
- One cell is about 1.1 km north to south and about 0.76 km east to west at 47 N.
- **Unit: millimetres.** NSSL's table says `mm`; the WDTD page says the base units used in
  calculations are mm and AWIPS displays inches. The file agrees: every positive value is on a
  0.1 mm step (checked on all positive cells of the 1440-minute and 2-minute files), and the largest
  values are 88.1 mm, which is 3.47 in. pygrib reports the unit as `unknown` because discipline 209
  is a local definition, so the unit comes from NSSL alone.
- **Conversion:** inches = mm / 25.4 (the exact definition of an inch). Neither NSSL page gives a
  conversion table, and the WDTD page does not say how AWIPS rounds, so the inch values shown in
  AWIPS may differ by a rounding step. Do not compare against AWIPS to the hundredth without checking.
- Threshold example: 1.75 in is 44.45 mm. With 0.1 mm values, the first value at or above it is
  44.5 mm (1.752 in).
- Montana is 2.3 percent of the grid: rows 600 to 1064 and columns 1395 to 2596 (49.0 N to 44.36 N,
  116.05 W to 104.04 W), 557,264 cells.

## Missing values

| Value | Meaning in NSSL's table | What the files do |
|---|---|---|
| -1 | "Missing" | Fills every covered cell without a hail estimate. In the 2-minute file on 2026-10-15 it covers 16.3 million of the 24.5 million cells. In the 2025-06-16 Montana box it covers 474,067 of 557,264 cells. |
| -3 | "No Coverage" | The same 8,195,637 cells in six of the seven 2026-10-15 files (the 1440-minute file has 8,174,021). Coverage is static. Mostly outside the radar network (in the 2-minute file, the Pacific and the grid's edges). The Montana box has none. |
| 9999 | not listed | The GRIB `missingValue` is 9999, but `numberOfMissingValues` is 0 and no 9999 appears. Ignore it. |
| NaN / masked | not listed | pygrib returned no masked values (`masked_count` 0), so the -1 and -3 cells arrive as ordinary numbers. |

- **Decoders must remove -1 and -3 themselves.** `gridded.sample_mrms` already sets negative values
  to NaN for PrecipRate.
- The files contain **no zeros**. The smallest positive value in every product is 0.8 mm (0.03 in).
  So the file cannot tell "covered, no hail-size estimate" apart from "missing" by value. NSSL calls
  -1 "missing". The honest reading is: -1 means no estimate; it is never calm, dry or no hail.
- A footprint shows only cells at or above a size. Everything else is "not drawn", never "no hail".

## Valid time and swath windows

- **The stamp is UTC and in the file name.** The file name carries seconds (for example 00:00:42);
  the GRIB time is minutes only, and eccodes warns "Truncating time: non-zero seconds(42) ignored".
- **2-minute MESH:** the stamp is the time of the estimate.
- **Swaths: the stamp is the end of the window.** Checked on 2026-10-15 against the 2-minute files
  (not the swath products):
  - Max30 stamped 00:30 equals the maximum of the 2-minute files from 00:00 to 00:29:xx: 9,569 of
    9,569 positive cells identical, largest difference 0.000 mm.
  - Max30 stamped 00:00 on 10/15 equals the maximum of the 2-minute files from 23:30 to 23:58 on
    10/14: 11,848 of 11,848 positive cells identical.
  - Longer windows: at the 00:00 stamp, every cell's value is non-decreasing from 30 to 60 to 120 to
    240 to 360 to 1440 minutes (0 violations). That is consistent with nested windows but was not
    tested against the 2-minute files for the longer windows.
- **The 2-minute files are not evenly spaced.** Gaps between consecutive files on 2026-10-15 run
  from 88 to 165 seconds, so "2-minute" is nominal.
- A 1440-minute footprint stamped 2025-06-16 00:00 covers 2025-06-15 00:00 to 24:00 UTC.

## Cadence, latency, size and volume

- **Cadence:** 2-minute products 720 files a day; 30-minute products 48 a day, every 30 minutes
  from 00:00.
- **Upload delay** (S3 `LastModified` minus the stamp, 2026-10-15): MESH median 46 s (range 38 to 98);
  30-minute swath median 72 s (69 to 80); 60-minute median 75 s (72 to 85); 1440-minute median 498 s
  (496 to 509), about 8 minutes. Plus the build's own schedule of 10 minutes.
- **Daily bytes, all files, full day (gzip):**

  | Product | 2026-10-14 | 2026-10-15 |
  |---|---|---|
  | MESH 2-min | 30.7 MB | 26.2 MB |
  | Max 30-min | 46.5 MB | 35.1 MB |
  | Max 60-min | 60.0 MB | 43.1 MB |
  | Max 120-min | 5.6 MB | 3.9 MB |
  | Max 240-min | 8.4 MB | 5.6 MB |
  | Max 360-min | 10.8 MB | 7.3 MB |
  | Max 1440-min | 25.7 MB | 23.2 MB |
  | **All seven** | **187.8 MB** | **144.4 MB** |

- **Montana's daily volume is the same as CONUS's.** The bucket has no regional or subset files, and
  a GRIB message is one compressed block, so a Montana download still costs the whole file. Montana
  is 2.3 percent of the grid, so cropping saves storage and drawing time, not download.
- **Per 10-minute build:** newest file of each product, about 0.94 MB (median sizes summed).

## Prototype: `website/mesh.py`

    footprint(grid, valid_time, sizes_in, *, window_minutes=None, nodata=(-1, -3),
              north=55.0, west=-130.0, cell_deg=0.01) -> GeoJSON FeatureCollection

- Input: a 2-D list or numpy array in millimetres, row 0 north. Missing: NaN, None, infinities, any
  negative value, and the `nodata` values. Missing cells never count as hail.
- Sizes are inches. A cell counts at or above the size, with a 0.0001 mm tolerance for float32
  rounding (MRMS values sit on 0.1 mm steps).
- Groups of cells joined along an edge become one feature per size. Cells that touch only at a
  corner stay in separate features. Holes become interior rings. A group with several outer rings
  becomes a MultiPolygon.
- Coordinates are lon/lat; outer rings counter-clockwise, holes clockwise (RFC 7946). Corner points
  only (straight runs removed).
- Properties per feature: `kind` ("radar estimate"), `threshold_in`, `threshold_mm`, `valid_time`
  (UTC, `Z`), `resolution_deg`, `cells`, and `window_minutes` when given. The collection carries
  `source` and `valid_time`.
- An outline that reaches the edge of the grid (or of a crop) stops there. The edge is where the
  data ends, not where hail ended.
- Pure Python labelling and tracing with numpy for the masks. No new dependency.

## Checks

**Live (this sandbox, 2026-10-16):**

- pygrib 2.1.8 decodes all seven product types. The GRIB metadata matches the NSSL table (parameter
  numbers, grid, level).
- 2026-10-15 00:00 30-minute swath, all six sizes (0.5 to 2.0 in): group counts, cell counts and
  areas match a numpy count exactly. 55 features in total; about 0.9 s.
- 2026-10-15 00:00 1440-minute swath, same six sizes: 1,622 features, every count and area matches;
  about 1.1 s.
- Montana crop, 2025-06-16 00:00 1440-minute file (the 2025-06-15 swath): 83,197 positive cells,
  largest 108.4 mm (4.27 in). Groups at 0.5, 1.0, 1.75 and 2.5 in: 414, 170, 50 and 16. At 0.25 in,
  8 groups touch the crop edge (the edge artifact above). A PNG of the outlines was checked by eye:
  nested outlines, no stray lines.
- Fuzz (scratch only): 400 random grids up to 80 by 80, plus checkerboard corner contacts: total
  outline area equals the cell count on every grid; every ring closed with no repeated vertex.

**In tests (`tests/test_mesh.py`, 27 tests, offline):** one cell; row 0 north; counter-clockwise
outer rings; edge-touching and corner-touching cells; a hole; a hole touching the outside at a
corner; nodata at the grid edge; every missing kind; custom and empty nodata; exact thresholds in
float32; nested sizes; property values; an all-missing grid, zero-size grids and no sizes all give an
empty collection; numpy and list input agree; UTC conversion; bad inputs raise `ValueError`; the MRMS
default grid; a randomised area check.

**Not checked:** a CI run of the test (the module was added to the workflow's test list, not run on
GitHub); CPython 3.12; the 2025-06-15 SPC report comparison (Benchland, 1.75 in: the swath is in the
archive, so it is possible); the flag table on GitHub; a real phone; the NSSL formula for MESH.

## What the files can and cannot show

**Can show:** where MRMS's radar-based estimate of the largest hail size reached each size in that
window, inside radar coverage, on a 0.01 degree grid (about 1 km), at the stamp time.

**Cannot show:**

- Hail that reached the ground, its size there, or whether it was verified. MESH is an estimate.
- Damage, a roof's condition, a damage probability or insurance eligibility.
- Whether a cell without an outline had no hail. -1 is "missing" in NSSL's table, and the file has no
  other value for "no estimate".
- Anything in no-coverage cells (-3), outside the grid, or past a crop's edge.
- Hail under 0.8 mm (no such values in the files). The estimate has a floor, not a measurement.
- Known biases (WDTD): MESH tends to underestimate hail in tilted storms in strong deep-layer shear,
  left-moving supercells, supercells with a large weak-echo region, and storms with low-density dry
  hail. It depends on the model's temperature profile and is contaminated by the bright band.
- Storm timing finer than the window: a 1440-minute outline covers 24 hours of possibly separate storms.
- Anything about the NWS, SPC or warnings. Keep it apart from reports (rule 5).

## Open items for the coordinator

1. Decide whether a MESH layer is wanted on the site, and as what (outlines, a separate legend,
   labelled "radar estimate"). Not decided here.
2. The SPC 2025-06-15 check (Benchland, 1.75 in) can use the archived swath: the 1440-minute file for
   the stamp 2025-06-16 00:00 is in the bucket. It has not been compared with SPC reports here.
3. Crop handling: if MESH is shown for Montana, outlines must be built from a grid larger than the
   visible box, or the edge must be drawn as cut.
4. Decoder: a MESH decoder needs its own parameter check, the -1 and -3 removal, and seconds from the
   file name (the GRIB time is minutes only).
5. Timing: a Montana build downloads about 0.94 MB per 10-minute run for MESH alone (newest file of
   each product); the 1440-minute file is half of that.
