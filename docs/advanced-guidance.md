# Advance guidance: what is documented and reachable

Research note for Roadmap P1, "Advanced guidance trials" (the review's "More useful advance guidance"
and D25). It records what three SPC and CIMSS sources publish, how to reach them, and what their own
documents say they cannot do. It ranks nothing and has no accuracy results. Checked 17 October 2026,
01:25 to about 01:40 UTC (16 October in Montana). No accounts, no vendor or agency contact, no paid access.

## Bottom line

1. **SPC Conditional Intensity Groups (CIG): ready to trial.** Published and live in SPC's GeoJSON,
   GRIB2, text and ArcGIS files. The probability is for severe weather "within 25 miles of any point".
   The CIG level describes intensity if the hazard occurs. SPC's notices give the start as 2 and 3 March 2026.
2. **ProbSevere v3 (CIMSS): ready to trial, with its limits.** Operational at NOAA since August 2025
   (contiguous US). An anonymous NOAA bucket holds a GeoJSON file every two minutes: 720 for 16 October
   UTC, each arriving 74 to 238 seconds after its valid time. No ProbSevere document says a low score must
   never suppress an official warning.
3. **LightningCast (CIMSS): not ready as a feed.** It forecasts lightning occurrence (target: GLM flash
   extent) for the next 60 minutes from GOES imagery. It is not a ground-strike feed. Its deployed version
   is not confirmed: the newest primary statement (5 May 2026) says v1 is "being transitioned to
   NOAA/NESDIS operations" and v2 is under evaluation. No documented file feed exists; the routes are a
   viewer, GRLevelX placefiles, or a local processing package.
4. **Limits of this check.** One NSSL page failed TLS verification; one SPC archive listing timed out
   twice at the origin. No Montana point was queried against any source.

## Requests made

| Source | Address (abbreviated) | HTTP | Type | Bytes | Content check |
|---|---|---|---|---|---|
| SPC | spc.noaa.gov/about/outlooks/ | 200 | text/html | 58,585 | 25-mile and CIG wording present |
| SPC | .../outlooks/SPC_Conditional_Intensity_Reference.pdf | 200 | PDF | 1,085,678 | "beginning March 3, 2026" |
| SPC | spc.noaa.gov/exper/conditional-intensity-information/ | 200 | text/html | 60,439 | "On March 3, 2026 with the 1630Z Day 1 Convective Outlook" |
| NWS | weather.gov/.../scn26-11_SPC_conditional-intensity.pdf | 200 | PDF | 51,996 | Service Change Notice 26-11, 29 Jan 2026 |
| SPC | spc.noaa.gov/gis/ | 200 | text/html | 49,664 | File names; DN definitions |
| SPC | spc.noaa.gov/products/outlook/day1otlk.html | 200 | text/html | 31,169 | 0100Z: no severe areas |
| SPC | .../outlook/archive/2026/day1otlk_20261017_0100-geojson.zip | 200 | zip | 15,932 | 28 GeoJSON files; CIG files empty |
| NWS | mapservices.weather.noaa.gov SPC_wx_outlks, metadata, layers 2 and 1 | 200 | text | 13,639; 12,135; 15 | 26 layers; Day 1 tornado CIG count 0; categorical count 1 |
| SPC | .../outlook/archive/2026/ (directory) | 504 twice | CloudFront | 936; 1,033 | Origin timeout; not used |
| CIMSS | cimss.ssec.wisc.edu/probsevere/ps/ | 200 | text/html | 77,532 | Operational August 2025 |
| CIMSS | ProbSevere_QuickGuide.pdf | 200 | PDF | 2,109,832 | Limits, thresholds |
| CIMSS | ProbSevere_v3_FileDescription.docx.pdf | 200 | PDF | 146,586 | Fields, units, two-minute frequency |
| NWS | weather.gov/idp/MRMS_v12.3_Supplemental | 200 | text/html | 64,876 | PSv2 to PSv3 upgrade in MRMS v12.3 |
| NOAA | bucket noaa-mrms-pds, prefix ProbSevere/ (two listings) | 200 | XML | 1,951; 306,979 | File names; 720 objects on 16 Oct |
| NOAA | one object, MRMS_PROBSEVERE_20261016_235841.json | 200 | octet-stream | 273,744 | GeoJSON; matches the file description |
| NCEP | mrms.ncep.noaa.gov/ProbSevere/PROBSEVERE/ (index) | 200 | text/html | 139,472 | 794 files, to 01:24 UTC |
| NSSL | inside.nssl.noaa.gov/mrms/code-updates/ | none | none | 0 | TLS verification failed (curl 60); not worked around |
| CIMSS | LightningCast_QuickGuide.pdf | 200 | PDF | 2,577,136 | "Last updated: January 2024" |
| CIMSS | cimss.ssec.wisc.edu/probsevere/lc/ | 200 | text/html | 96,419 | 60-minute target; LCv1 verification |
| CIMSS | severe_conv loops, GOES-East and GOES-West CONUS | 200 | viewer pages | 3,063,372; 436,046 | Frames every 5 min; labels to 01:21 and 01:26 UTC |
| CIMSS | csppgeo/lightningcast.html | 200 | text/html | 5,563 | Release v1.0beta2, 6 March 2025 |
| CIMSS | satellite-blog archives 62924 and 70244 | 200 | text/html | 76,494; 72,724 | Version statements, 31 Jan 2025 and 5 May 2026 |
| NESDIS | news/predicting-lightning-it-strikes-noaas-lightningcast | 200 | text/html | 81,782 | "experimental status", dated 26 June 2025 |

Raw responses and parsed listings are in the scratch folder, not in the repository.

## 1. SPC Conditional Intensity Groups

### Definitions

- Probability (SPC outlook page): "The probability values represent the chance of severe weather
  occurring within 25 miles of any point, which is approximately the size of a major metropolitan area."
  Day 1 and 2 give tornado, wind and hail separately. "Day 3: Due to greater uncertainty, the outlook
  only forecasts the combined probability of all three types of severe weather."
- Intensity (same page): "These three intensity distributions (CIG1, CIG2, and CIG3) will be utilized to
  communicate increasing intensity of significant severe hazards, should severe hazards occur."
- Conditional meaning (SPC reference PDF): "Intensity information will now be conditional, meaning IF a
  tornado/wind gust/hail occurs, the expected strength/intensity/size will be represented in the hazard
  outlooks produced by SPC."
- Target caveat (SPC outlook page): "Note: This is the target over a large number of events and is
  unlikely to verify for a single event due to the low sample size."

So the event probability (per hazard, within 25 miles of a point) and the CIG level (intensity if the
hazard occurs) are separate quantities. The definition describes a 25-mile neighbourhood, so it is not the
chance of hail on one roof.

Intensity by group (SPC reference PDF; no outline is "None Highlighted (<CIG1)"):

| Level | Tornado | Wind | Hail |
|---|---|---|---|
| None highlighted (<CIG1) | mostly EF0 to EF1 | mostly under 74 mph | mostly under 2 in |
| CIG1 | reasonable maximum EF2 | peak gusts 74 mph or more | largest hail over 2 in |
| CIG2 | reasonable maximum EF3 | bow echo or derecho possible | largest hail over 3.5 in |
| CIG3 | maximum EF4+ (historic outbreak) | high-end ongoing derecho | no entry |

The probability-to-category tables change with the group. A 15% tornado probability is ENH with no CIG or
CIG1, and MDT with CIG2 or CIG3. A 15% hail probability is SLGT with no CIG or CIG1, and ENH with CIG2
(no CIG3 column for hail). The page's bar charts give target shares (tornado EF4+: 0.1%, 1.0%, 3.0%, 5.0%
for <CIG1 to CIG3). The page calls these targets, not verification.

### Products and formats

| Form | Published (SPC GIS page, SCN 26-11, SPC pages) | Notes |
|---|---|---|
| Text | Outlook points product, WMO headers WUUS01 to WUUS03 KWNS PTSDY1 to PTSDY3. CIG outlines appear as lat/lon blocks under each hazard (SPC's example). A printable Day 1 text product is also linked. | GIS files are built from the points product (KWNSPTS). |
| GRIB2 | CIG grids: HMNE01 to HMNE03 and HMNE16 to HMNE18 (Day 1); HMNI01 to HMNI03 and HMNI16 to HMNI18 (Day 2); HMNK19 and HMNK20 (Day 3 total severe). Probability grids use other headers. | Listed in SCN 26-11. Not opened. |
| GeoJSON | day1otlk_cigtorn, _cigwind, _cighail and day2 equivalents, as .lyr and .nolyr files; day3otlk_cigprob | Day 1 opened (see the live check). |
| KML/KMZ | day3otlk_cigprob.kmz is the only CIG KML or KMZ named | Days 1 and 2 CIG are GeoJSON only, per the GIS page. |
| Shapefile | Zip per day (day1otlk-shp.zip; archive zips carry the issue time) | Named; not opened. |
| ArcGIS REST | outlooks/SPC_wx_outlks MapServer (version 11.3). CIG layers 2, 4, 6 (Day 1 tornado, hail, wind), 10, 12, 14 (Day 2), 18 (Day 3 severe). Categorical 1, 9, 17. | Label renderer classes CIG1, CIG2, CIG3. Queryable. |
| CSV | None named on the outlook GIS page | — |

Names differ across SPC's outputs: "CIG1" to "CIG3" (SCN, PTS, ArcGIS), "Significant" (GIS page labels),
"cig" (file names), and "SIGN" (the label CIG replaces). Keep published names in the records and map them
to CIG1 to CIG3 in one place.

### Issue, valid and start

- Day 1 issuance (SPC page): 0100Z, 0600Z, 1300Z, 1630Z, 2000Z. Day 2: "1:00 AM (CST/CDT)" and 1730Z.
  Day 3: "2:30 AM (CST/CDT)" and 1930Z. Local times are given without UTC equivalents (derived: 0600Z or
  0700Z, and 0730Z or 0830Z).
- The 17 October Day 1 files: product label 0100Z; fields ISSUE 00:50Z, VALID 01:00Z, EXPIRE 12:00Z. Store
  the file's own fields, since the label and ISSUE differ by ten minutes.
- Start: SCN 26-11 (29 January 2026) says "On or about March 2, 2026". The SPC page says "On March 3, 2026
  with the 1630Z Day 1 Convective Outlook". The reference PDF says "beginning March 3, 2026". The CIG files
  and layers exist now; these sources do not confirm the first issue.

### Live check (Day 1 outlook, 17 October 2026, product 0100Z)

- The SPC Day 1 text reads "...NO SEVERE THUNDERSTORM AREAS FORECAST...".
- The categorical GeoJSON has one MultiPolygon: LABEL "TSTM", DN 2 (Thunderstorm, per the GIS page).
- The three CIG GeoJSON files (tornado, wind, hail) each hold one feature with no geometry
  (GeometryCollection) and DN 0. The ArcGIS tornado CIG layer returns a count of 0; the categorical layer
  returns 1, which matches the files.
- So the CIG files and layers are live and empty today. CIG1 to CIG3 are confirmed in the layer
  definition, not in an issued outline. No day with a CIG area was opened.

## 2. ProbSevere v3 (CIMSS)

### Status and data path

- Status (CIMSS): "ProbSevere v3 is a set of four machine-learning models that predict the probabilities
  of severe hail (≥ 1″ diameter), severe wind gusts (≥ 50 kt), tornadoes, and any of those hazards in any
  identified convective storm in the contiguous United States (Quick Guide). ProbSevere v3 became
  operational at NOAA in August 2025."
- Access: NOAA's bucket noaa-mrms-pds (prefix ProbSevere/), read anonymously over HTTPS. The NCEP mirror
  (mrms.ncep.noaa.gov/ProbSevere/PROBSEVERE/) is a rolling index of about 26 hours. No API is documented.
- The MRMS v12.3 supplement (NWS): "In MRMS v12.3, PS is being upgraded from Version 2 (PSv2) to Version 3
  (PSv3)". PSv2 files were at the NCEP path; PSv3 was tested at a separate QA host. No release date is in
  the text read.

| Item | Documented | Observed, 16 October UTC (720 files) |
|---|---|---|
| Format | GeoJSON; one file per MRMS validTime, named MRMS_PROBSEVERE_YYYYMMDD_HHMMSS.json | Names match the description; one body read, a FeatureCollection |
| Cadence | "Frequency: 2 minutes (updates with MRMS 2D severe-weather products)" | Spacing median 120 s (min 110, max 128); no gap over 150 s |
| Size | "generally between 20 kB and 2 MB" | 111,743 to 393,268 bytes (median 239,026) |
| Latency, file time to bucket time | Not documented | Median 108 s; 95th percentile 144 s; maximum 238 s |
| Production time | productionTime field (UTC) | One file: valid 23:58:41, produced 00:00:13 (92 s), bucket 00:00:38 |
| Coverage | Contiguous US | The file read has eastern US objects; other regions not checked |

### Products, units and fields

- Four products: ProbSevere (any severe), ProbHail (severe hail, 1 inch or more), ProbWind (severe gust:
  "≥ 58 mph" in the quick guide, "≥ 50 kt" on the status page, which is 57.5 mph), and ProbTor. The
  horizon is 60 minutes (file description) or "next-hour" (quick guide). Models are gradient-boosted
  decision trees. Inputs: MRMS radar, GOES-R ABI and GLM, the ENI/ENGLN lightning network, and HRRR.
- Each feature is one storm object: a closed polygon in WGS84 (western longitudes negative). `models` holds
  probsevere, probhail, probwind and probtor, each with PROB in percent ("the computed probability for the
  storm at the validTime"). `properties` holds 48 values in the sample, with units in the file description:
  MESH in inches, VIL in kg/m², FLASH_RATE in flashes per minute, SIZE as a pixel count (about km²), and ID
  for following an object over time.
- PROB is stored as text (for example "11"); cast it before use. Motion fields "often have large variances
  from one time to the next", so average before use. MESH is a radar-derived estimate, not ground truth.

### Documented limits and warnings

- Quick guide, quoted: "Requires storm object to be identified"; "Shallow and low-lightning storms often
  have low probabilities"; "Poor object-tracking in squall lines can adversely affect probability trends";
  "Radar inputs coarser than NEXRAD L2".
- Validation: "ProbSevere validation on thousands of storms in 2023." No figures in the text read; not checked.
- Feedback claims (quick guide): "Increases forecaster confidence in warning decision making" and "Helps
  increase warning lead time to hazards". These are the producer's claims.
- Low score and warnings: the status page, quick guide, file description and MRMS v12.3 supplement were all
  searched. None says a low score must not suppress or replace an official warning, and none gives a rule for
  warnings. The review's line "Never let a low score suppress an official warning" is a project rule
  (AGENTS.md rule 6), not a documented property of the product.

### Live check

- The bucket lists 290 daily folders for 2026 (1 January to 17 October). The 16 October folder lists 720 objects.
- One object (MRMS_PROBSEVERE_20261016_235841.json, 273,744 bytes) was read: FeatureCollection; source
  "NOAA/NCEP Central Operations"; product "ProbSevere 3.0"; validTime 20261016_235841 UTC; productionTime
  20261017_000013 UTC; 88 features. In it, 56 of 88 storm objects had PROB 0; the highest were 11%
  (ProbSevere), 1% (ProbHail), 6% (ProbWind) and 4% (ProbTor). One file shows the format; it is not a
  performance result.
- The NCEP index was current (794 files, last 01:24 UTC). Its file bodies were not opened.

## 3. LightningCast (CIMSS)

### Version and status: dated statements

| Date | Source | Statement (quoted where it matters) |
|---|---|---|
| "since 2021" | Status page (undated) | "LightningCast has been used extensively by NWS forecasters since 2021." |
| 31 Jan 2025 | CIMSS blog (v2 post) | v1 "will be operational at NOAA later in 2025." v2 adds MRMS reflectivity at -10 °C; in research. |
| 6 Mar 2025 | CSPP-Geo page | "CSPP Geo LightningCast v1.0beta2", last updated 6-Mar-2025 |
| 26 Jun 2025 | NESDIS news | "This system is currently in experimental status and is planned to become operational in 2026." |
| Jan 2024 (text) | Quick guide | "Last updated: January 2024" (PDF uploaded 18 November 2025) |
| 5 May 2026 | CIMSS blog (v1 vs v2) | v1 "is being transitioned to NOAA/NESDIS operations." v2 "has been developed and is being evaluated at NOAA's Hazardous Weather Testbed." |
| 17 Oct 2026 | Status page | Verification named for "LCv1 (ABI-only predictors)", GOES-16 CONUS, 2023. No version or date line. |

The deployed version and its date are not confirmed by any page read. The newest primary statement puts v1
in transition and v2 in evaluation. The May 2026 post says v2 "provides superior guidance" in its examples;
that is the developer's claim, not a test here. Log the version the data states, or "not_stated". Do not call
either version operational until a dated NOAA notice says so. The guide's January 2024 text predates both.

### Target and inputs

- Target (quick guide): "It was trained using GLM flash-extent density as the target or “truth” data."
  Output (CSPP-Geo page): "the probability of a Geostationary Lightning Mapper (GLM) observation of lightning
  occurring in the next hour within a region of interest."
- So the target is a GLM detection from geostationary orbit, not a ground-strike record. Observed lightning
  is a separate input, as the review asks.
- Inputs: ABI bands C02 (0.64 µm), C05 (1.6 µm), C13 (10.3 µm), C15 (12.3 µm). v2 adds MRMS reflectivity.
- The guide says "Probabilities in the 20-50% range often provide 20 minutes or more of lead time to
  initiation." That is a documented claim, not tested here.

### Access, cadence and coverage

- Viewer and dashboards (real-time, multi-location, airports, stadiums, wildfires). An on-demand dashboard
  request exists for NOAA users only (not used).
- GRLevelX placefiles (v2.60 or later) for GOES-East and GOES-West CONUS and Meso1 and Meso2: "parallax-
  corrected with a constant cloud-height assumption of 9 km".
- Local processing: CSPP-Geo LightningCast v1.0beta2 needs only GOES-16, GOES-18, GOES-19 or Himawari-9 imagery
  (GRB or NODD ABI Level 1B).
- No NODD bucket, NCEP directory or API for LightningCast output appears on the status page, the guide or the
  CSPP-Geo page. Every link on those pages was read.
- Cadence: the viewer loops step in 5 minutes (GOES-East CONUS labels to 01:21 UTC; GOES-West CONUS to 01:26
  UTC on 17 October). The product's update rate is not stated; verification was computed "every 10 minutes".
- Coverage (quick guide, text dated January 2024): GOES-West PACUS, Mesoscales 1 and 2, American Samoa, and
  Alaska/west Canada; GOES-East CONUS, Mesoscales 1 and 2, and OPC/TAFB offshore zones; Himawari Guam. The
  guide omits GOES-West CONUS, which the status page offers as a placefile set. Whether Montana sits inside
  the sector used is not tested.

### Documented limits (quick guide, quoted)

- "Convection under thick ice: Limited ability to monitor convection developing under a thick anvil."
- "Tropical Cyclones: Very tall, cold clouds that don’t produce much lightning can cause false alarms."
- "Diurnal/Seasonal: LightningCast is more accurate during the day and during the warm season (Apr-Oct). It
  tends to over-predict convection in the cool season (Nov-Feb)."

October and November trial days fall in the months these notes cover, so results should be split by month
and by day or night.

### Live check

- Status page: 200, text/html, 96,419 bytes. Content matches (60-minute target, ABI channels, LCv1 verification).
- Quick guide: 200, PDF, 2,577,136 bytes. Text matches, including "Last updated: January 2024".
- CSPP-Geo page: 200, 5,563 bytes. Release v1.0beta2, 6 March 2025.
- GOES-East and GOES-West CONUS loops: 200 viewer pages (MHTML files titled as NOAA LightningCast loops), not data
  files. Frame labels present. No placefile, probability value or GLM count was fetched.

## Conflicts in the sources

1. CIG start: "on or about March 2, 2026" (SCN 26-11) against "On March 3, 2026" (SPC page) and "beginning March 3,
   2026" (SPC reference PDF). The SPC outlook page still says CIG "will be visible" on a page updated 3 March 2026.
2. CIG naming: "CIG1" to "CIG3", "Significant" (GIS page labels), "cig" (file names), "SIGN" (replaced).
3. ProbSevere wind: "58 mph" (quick guide) against "50 kt" (status page). The same threshold to rounding.
4. ProbSevere path: the NCEP path carried PSv2 before the v12.3 upgrade; the 16 October bucket file is labelled
   "ProbSevere 3.0". Check the product label, not the path. The NCEP file bodies were not opened.
5. LightningCast status: "later in 2025" (January 2025), "planned to become operational in 2026" (June 2025,
   experimental), "being transitioned" (May 2026). The status page's "used extensively ... since 2021" sits beside
   the June 2025 "experimental" wording.
6. LightningCast coverage: the guide omits GOES-West CONUS; the status page includes it.
7. The review cites the ProbSevere guide for "Never let a low score suppress an official warning". The guide does
   not say that.

## Not checked, or could not check

- SPC's 2026 archive directory: 504 from the CloudFront origin on two tries. Earlier CIG files were not opened.
- A live CIG outline with a label: none on 17 October 0100Z (no severe areas).
- SPC shapefile zips and GRIB2 files: named, not opened.
- NSSL MRMS code-updates page: TLS verification failed (curl error 60, "unable to get local issuer
  certificate"). Not worked around, per the coordinator's rules. The NWS v12.3 supplement was used instead.
- MRMS v12.3 release date, and NWS service change notices for LightningCast: not found or not searched.
- Accuracy or verification of any source: none. The sources cite their own validation without figures in the text read.
- Montana points and outcome data (storm reports, GLM counts, warnings): none queried or fetched.

## Readiness, without ranking

- SPC CIG: documented meaning, public files in several formats, visible empty-state behaviour. A trial needs a
  point-in-outline test per hazard and a rule for "None Highlighted".
- ProbSevere v3: documented format, measured cadence and lag, anonymous access. A trial needs a storm-object
  rule with a search radius fixed in advance, and separate states for "no object" and "low score".
- LightningCast: no documented feed; version unconfirmed; output by viewer or local run. A trial needs a placefile
  format check (not done) or a local CSPP run on ABI data (not set up).

## What a shadow trial would log

These are proposed fields for the evaluation/ harness, which owns the schema.

Rules for every record:

- One decision record per source, per point, per read, written at read time. Records are not edited; later
  information goes to the outcome table.
- Keep read time and the source's own time as separate fields; compute age at decision.
- Keep the SHA-256 of the raw body and the file name or URL, so a record can be replayed.
- A missing value is null with a reason code (unavailable, stale, outside_sector, no_object, polygon_invalid,
  parse_error). A null is never a zero, and "data unavailable" is never an all-clear.
- Each source's values stay in their own fields. Event probability and CIG level are separate. Model scores are
  never merged with NWS warnings, reports or alerts (AGENTS.md rule 5). Search radius, interpolation rule and
  time window are fixed before the trial and written into each record. No generated text in the record.

Common fields (all sources):

| Field | Meaning |
|---|---|
| decision_id, point_id, point_lat, point_lon | Unique per read; town or job; WGS84 |
| read_started_utc, read_finished_utc | Wall-clock times of the read |
| source, source_url | spc_cig, probsevere_v3 or lightningcast; the address read |
| http_status, content_type, bytes, body_sha256 | As returned; hash of the raw body for replay |
| parse_status, reason_code | ok, or why a value is null |
| source_version_stated | Product label or version string, or not_stated |
| source_time_utc, source_age_min | The source's own issue, valid or frame time; age at decision |

SPC CIG fields (one row per point, day and hazard):

| Field | Meaning |
|---|---|
| spc_day, spc_hazard | 1, 2 or 3; tornado, wind, hail, or total_severe (Day 3 only) |
| spc_issue_utc, spc_valid_utc, spc_expire_utc | From the file's ISSUE, VALID and EXPIRE fields |
| spc_product_ref | PTS header, GRIB2 header, GIS file name or ArcGIS layer id |
| spc_cat_label, spc_cat_dn | Categorical label and DN at the point; none if outside every area |
| spc_event_prob_pct | Probability for the point's contour; "outside_all_areas" is its own status, not 0 |
| spc_cig_level | none_highlighted (<CIG1), CIG1, CIG2 or CIG3; null if unavailable |
| spc_point_status, spc_file_empty | in_area, outside_all_areas or unavailable; true for a valid empty file |

ProbSevere v3 fields (one row per point, per two-minute file):

| Field | Meaning |
|---|---|
| ps_file_name, ps_valid_utc, ps_production_utc, ps_bucket_modified_utc | From the file name, validTime, productionTime, bucket time |
| ps_product_label | Must read "ProbSevere 3.0" |
| ps_point_status | in_object, object_within_radius, no_object_within_radius, polygon_invalid or unavailable |
| ps_search_radius_km | Fixed in the protocol |
| ps_object_id, ps_object_distance_km, ps_object_size_km2 | ID; distance from the point; SIZE (pixel count, about km²) |
| ps_prob_severe_pct, ps_prob_hail_pct, ps_prob_wind_pct, ps_prob_tor_pct | PROB for the nearest object, as numbers; 60-minute horizon |
| ps_mesh_in, ps_flash_rate_per_min | Radar and lightning inputs, labelled as estimates |
| ps_object_seen_prev_file | True when the same ID appeared in the previous file |

LightningCast fields (one row per point, per read):

| Field | Meaning |
|---|---|
| lc_frame_utc | Frame time from the viewer or placefile; null if not shown |
| lc_version_stated, lc_source | LCv1, LCv2 or not_stated; viewer, placefile name, or local CSPP run with its version |
| lc_sector | GOES-East or GOES-West CONUS, Meso1 or Meso2; or outside_sector |
| lc_prob_pct, lc_point_status | Value under the fixed interpolation rule; value, outside_sector, unavailable or stale |
| lc_read_age_min | Read time minus frame time |
| lc_parallax_assumption_km | 9 for placefiles, as documented; null otherwise |
| lc_local_hour, lc_month | For the documented day and season split |
| lc_cloud_flags | not_computed, unless a method is fixed in advance for the guide's thick-anvil and tropical-cyclone limits |

Outcome fields (written later, in their own table, each with an as-of time):

- NWS warnings and watches overlapping the point: polygon or zone, issue and expiry times.
- SPC storm reports: time, place, hazard, size or speed, preliminary or final.
- LightningCast: GLM flashes or flash extent within the fixed radius for the next 60 minutes (the stated target).
- ProbSevere hail: independent reports. MESH alone is not an outcome.
- SPC CIG: outcomes conditional on an event, because CIG is intensity given occurrence.
