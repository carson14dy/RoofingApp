export const meta = {
  name: 'globe-sources-a',
  description: 'Live-verify NASA GIBS GOES tiles, NOAA GOES on AWS and MRMS 3D reflectivity, then refute each report',
  phases: [
    { title: 'Verify', detail: 'live request + content check per source' },
    { title: 'Refute', detail: 'independent re-check of each report' },
  ],
}

const SCRATCH = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad'
const EVID = '/home/user/RoofingApp/research/globe/validation-evidence/'

const CTX = `You are one of several agents building the "globe view" research scaffold for RoofingApp (a Montana roofing company's weather desktop app). A supervisor reads your output; it is data, not prose for a person.

Repo: /home/user/RoofingApp. First read /home/user/RoofingApp/research/globe/README.md sections 1-7 (the plan); your workstream is in section 5.

Rules that bind you (from AGENTS.md):
- Rule 7: make the live request AND check the content. Decode the tile or file and report what is inside (pixel stats, variable names, grid dimensions). HTTP 200 proves nothing.
- Rule 9: no "best" claims; comparisons with evidence only.
- Rule 5: observation, satellite estimate, radar estimate and official alert stay separate; never "confirmed damage".

Working rules:
- Today is 2026-10-17 (UTC); day-of-year 290. Outbound HTTPS works through a preconfigured proxy (Python requests and curl honour it). pip install works; you may install packages for research and must list them in your result. Never edit requirements.txt.
- Downloads go into a fresh empty directory ${SCRATCH}/globe-dl/<your-slug>/ . Scripts you write go in ${SCRATCH}/globe-scripts/<your-slug>/ and read downloads by path; run them with "python -I".
- Montana bounding box: lon -116.05 to -104.04, lat 44.36 to 49.00. Billings: 45.7833, -108.5007.
- Write ONLY the files your task names. Your evidence file goes in ${EVID} as JSON of at most 20 KB: no binary captures, no large response bodies (every crew machine downloads the repo zipball, so research artifacts must stay small).
- Never write model names or AI-vendor identifiers into any file.
- Do not modify payload/, desktop/, tests/, docs/, or research/globe/README.md.
- For documentation and terms pages use WebFetch or WebSearch (load them with ToolSearch "select:WebFetch,WebSearch"). Quote the exact sentence you rely on, with its URL.
- If something cannot be verified, write "unverified" and why. Never guess a number.

Evidence file shape (JSON):
{
  "workstream": "W#", "slug": "...", "checked_at_utc": "...",
  "urls_checked": [{"url": "...", "method": "GET", "status": 200, "bytes": 0, "content_type": "...", "cors_allow_origin": "... or null", "content_check": "what you decoded and what it showed", "verified": true}],
  "facts": [{"claim": "...", "value": "...", "evidence": "url or file", "verified": true}],
  "terms": {"license": "...", "attribution_required": true, "quote": "...", "url": "..."},
  "limits": ["..."], "installed_packages": ["..."], "open_questions": ["..."]
}`

const SRC = {
  type: 'object',
  properties: {
    slug: { type: 'string' },
    evidence_file: { type: 'string' },
    headline_facts: { type: 'array', items: { type: 'string' } },
    blockers: { type: 'array', items: { type: 'string' } },
    installed_packages: { type: 'array', items: { type: 'string' } },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
  },
  required: ['slug', 'evidence_file', 'headline_facts', 'blockers', 'confidence'],
}

const REV = {
  type: 'object',
  properties: {
    slug: { type: 'string' },
    refuted_claims: { type: 'array', items: { type: 'string' } },
    corrections: { type: 'array', items: { type: 'string' } },
    confirmed: { type: 'array', items: { type: 'string' } },
    unverified: { type: 'array', items: { type: 'string' } },
    evidence_file_updated: { type: 'boolean' },
  },
  required: ['slug', 'refuted_claims', 'corrections', 'confirmed', 'unverified', 'evidence_file_updated'],
}

const ITEMS = [
  {
    slug: 'gibs', title: 'W1 NASA GIBS WMTS: GOES GeoColor / Band 13, Blue Marble, VIIRS true colour',
    task: `1. Fetch https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/1.0.0/WMTSCapabilities.xml (and the epsg4326 one). Parse it (xml.etree). List every layer whose identifier contains "GOES" (expect names like GOES-East_ABI_GeoColor, GOES-East_ABI_Band13_Clean_Infrared, GOES-West_ABI_GeoColor), plus BlueMarble_ShadedRelief_Bathymetry, VIIRS_SNPP_CorrectedReflectance_TrueColor, VIIRS_NOAA20_CorrectedReflectance_TrueColor. For each: TileMatrixSet(s), format, Dimension time (default value, the time period such as PT10M, the start of the available range), ResourceURL template.
2. For a GOES GeoColor layer and a Band 13 layer: fetch a tile over Montana (zoom 5 in the GoogleMapsCompatible scheme covers lon -110 lat 47 at roughly x=6, y=11 - compute it yourself and show the formula) at the default time and at the previous time step. Decode with PIL: size, mode, percent of non-transparent pixels, number of distinct colours, mean RGB. A tile that is fully transparent or one flat colour is NOT verified imagery - say so.
3. Measure latency: latest available time in the capabilities versus now (UTC). Measure the update period from the dimension.
4. Record the CORS header (Access-Control-Allow-Origin) on a tile GET sent with an Origin header, because the globe fetches tiles from inside a browser page.
5. Find and quote GIBS terms/citation and any usage limits, and the GOES layers' native resolution and whether GIBS GOES imagery is parallax-corrected (search GIBS layer documentation; if nothing says so, write unverified).
Write ${EVID}gibs.json.`,
  },
  {
    slug: 'goes-aws', title: 'W2 NOAA GOES-East/West on AWS: band 13 imagery, ACHA cloud-top height, cloud optical depth',
    task: `Buckets: noaa-goes19 (GOES-East since 2025 - verify by listing recent data), noaa-goes18 (GOES-West), and check whether noaa-goes16 still receives new data. Use the S3 REST listing: https://noaa-goes19.s3.amazonaws.com/?list-type=2&prefix=ABI-L2-ACHAC/2026/290/ then narrow to the latest hour.
1. For products ABI-L2-ACHAC (cloud top height, CONUS), ABI-L2-CMIPC (band 13 only: files containing M6C13 or M3C13), ABI-L2-CODC (cloud optical depth), ABI-L2-ACTPC (cloud phase): list the latest files, decode the s/e/c timestamps in the names, record file sizes, and derive the cadence from consecutive files (expect 5 minutes for CONUS). Also record one ABI-L2-MCMIPC (all bands) size and one full-disk ACHAF size for comparison.
2. Download the latest ACHAC file and the matching CMIPC band 13 file into the download directory. pip install netCDF4 (and h5netcdf if needed). Open each: list variables (expect HT, DQF, x, y, t, goes_imager_projection), units (HT in metres, CMI in kelvin), _FillValue, scale_factor/add_offset, valid_range, grid shape (CONUS 2 km is 1500 x 2500), time attributes (time_coverage_start/end).
3. Compute latitude/longitude for the grid from the geostationary projection attributes (perspective_point_height, semi_major_axis, semi_minor_axis, longitude_of_projection_origin) with numpy - the standard GOES fixed-grid formulas. Report the fraction of valid cloud-top-height cells inside the Montana bounding box and the 10/50/90th percentile height there, plus the fraction flagged by DQF. Report the band 13 brightness temperature range over Montana.
4. Latency: now minus the file's time_coverage_end at listing time. Bytes per 5-minute step for the three CONUS products you would need (ACHAC + CMIPC C13 + CODC).
5. CORS: GET one object with an Origin header; record Access-Control-Allow-Origin (or its absence).
6. Terms: quote the licence statement from https://registry.opendata.aws/noaa-goes/ (NOAA Open Data Dissemination) and the GOES-R Product Definition and Users' Guide note that ACHA is a retrieval (an estimate) if you can find it; else unverified.
Write ${EVID}goes-aws.json.`,
  },
  {
    slug: 'mrms', title: 'W3 MRMS on AWS: 3D MergedReflectivityQC (33 heights), composite, MESH, coverage products',
    task: `Bucket noaa-mrms-pds. Start with https://noaa-mrms-pds.s3.amazonaws.com/?list-type=2&prefix=CONUS/&delimiter=/ to enumerate product prefixes.
1. List every MergedReflectivityQC_XX.XX level present (expect 33 from 00.50 to 19.00 km). For the latest common timestamp list the file name and gz size per level, and sum them: bytes per 2-minute step for the full 3D mosaic. Also list latest file and size for MergedReflectivityQCComposite_00.50, MESH_00.50, MESH_Max_60min_00.50 (or whatever MESH max products exist), ReflectivityAtLowestAltitude_00.50, RadarQualityIndex_00.50, EchoTop_18_00.50, VIL_00.50, and any product whose name suggests radar coverage or quality (list all names you see that contain Quality, Coverage, Mask).
2. Download the latest files for levels 00.50, 03.00, 06.00 and 10.00 and the MESH_00.50 file. gunzip them. Decode GRIB2: pip install eccodes (binary wheels include the library); import eccodes and read keys Ni, Nj, latitudeOfFirstGridPointInDegrees, longitudeOfFirstGridPointInDegrees, latitudeOfLastGridPointInDegrees, longitudeOfLastGridPointInDegrees, iDirectionIncrementInDegrees, jDirectionIncrementInDegrees, dataDate, dataTime, and the values array. If eccodes fails, try pip install cfgrib xarray (xr.open_dataset(path, engine='cfgrib')) or pygrib; record every failure message verbatim. Expect a 7000 x 3500 grid at 0.01 degrees covering lon -129.995..-60.005, lat 54.995..20.005.
3. From the decoded values: the distinct negative sentinel values and their counts (MRMS uses one code for "missing" and another for "no radar coverage" - identify which is which from the NSSL MRMS GRIB2 tables at https://www.nssl.noaa.gov/projects/mrms/operational/tables.php or the MRMS operational product guide; quote). For the Montana bounding box at each decoded level: percent of cells with no coverage, percent missing, percent >= 20 dBZ and >= 35 dBZ, max dBZ. For MESH: units (mm) and max over Montana. The no-coverage percentages are the Montana radar gaps the plan warns about - report them exactly.
4. Cadence from consecutive file timestamps; latency = now minus latest file time. CORS header on one object GET with an Origin header.
5. Terms: quote the licence statement from https://registry.opendata.aws/noaa-mrms-pds/ . Note the MRMS version if the files or docs state it.
Write ${EVID}mrms.json.`,
  },
]

function researchPrompt(it) {
  return CTX + '\n\n# Your workstream: ' + it.title + '\n\n' + it.task +
    '\n\nWhen done, return: slug, evidence_file (absolute path), headline_facts (the 5-10 facts that matter for the plan, each with its number and unit), blockers (anything you could not do, with the exact error), installed_packages, confidence.'
}

function refutePrompt(it, res) {
  return CTX + '\n\n# Your job: REFUTE the report for ' + it.title +
    '\n\nA previous agent wrote ' + EVID + it.slug + '.json and summarised it as:\n' + JSON.stringify(res, null, 2) +
    '\n\nRead the evidence file. Then independently re-check every fact that matters to the plan, using different inputs where possible (a different tile, time step, level or file than the first agent used), and re-read each quoted terms page yourself. Default to suspicion: a claim with no decoded content behind it is unverified; a number copied from memory is unverified. Check especially: cadence, latency, bytes per step, grid dimensions, sentinel values, CORS headers, licence wording, and any claim about parallax or resolution.' +
    '\n\nThen UPDATE the evidence file in place: fix wrong values in "facts" and add "corrected_by_review": true to each one you changed; add a top-level "review" object {"refuted_claims": [...], "corrections": [...], "confirmed": [...], "unverified": [...], "reviewer_checks": [{"url": "...", "content_check": "...", "verified": true}]}. Keep the file at or under 20 KB. Return the same lists plus evidence_file_updated.'
}

log('Wave 1A: verifying GIBS, GOES on AWS, MRMS - each report then refuted')
const results = await pipeline(ITEMS,
  it => agent(researchPrompt(it), { label: 'verify:' + it.slug, phase: 'Verify', model: 'haiku', schema: SRC }),
  (res, it) => res ? agent(refutePrompt(it, res), { label: 'refute:' + it.slug, phase: 'Refute', model: 'haiku', schema: REV }) : null,
)
return { slugs: ITEMS.map(i => i.slug), reviews: results }
