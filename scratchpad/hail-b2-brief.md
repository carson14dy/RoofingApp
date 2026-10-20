# Hail history B2 brief: reports, radar detections, warnings, zone products and station gusts in the same sheet

Owner decisions (2026-10-18, quoted in docs/DECISIONS.md D34): 2 "a popup on each history of weather", 6 "all types of
weather at that address for the past 5 years in a popup", 4 "updates consistent and recent as possible", 7 "Follow the laws".
B1 (branch claude/hail-b1, merged into this branch's base) ships the radar-estimated hail days per cell. B2 adds the other
kinds of evidence for the same cell, each with its own kind word, in the same sheet and the same town tables, behind the
same default-off flag `--hail-history`. Nothing here states damage, an all-clear, insurance or eligibility (AGENTS.md rule 5).

Read first: /home/user/wt/briefs/hail-build-brief.md (the B1 contract, decisions 1 to 16), docs/DECISIONS.md D34 and
docs/DESIGN.md section 9 in the worktree, website/hail.py (the store, the words, describe(), map_data()), map.js's hail
section, and the research evidence on the research worktree /home/user/wt/wt-hail/research/hail-history/: README.md
sections 2, 4 and 6, and validation-evidence/point-reports-archives.json, warnings-archive.json, swdi.json,
wind-history.json, evaluation-and-wording.json (templates, qualifier labels, forbidden terms). Every URL form, unit and gap
below is recorded there; make one live request per source and check the content before building on it (rule 7).

## Sources, kinds and radii (fixed)
| Kind word in the sheet | Source | Request form (verify live) | Join | Units shown |
|---|---|---|---|---|
| Report (NWS local storm report) | IEM LSR archive CSV, `https://mesonet.agron.iastate.edu/cgi-bin/request/gis/lsr.py?state=MT&sts=<ISO>Z&ets=<ISO>Z&fmt=csv&wfo=ALL`, pulled by month (73 months in the window; the last 2 months re-pulled daily) | every LSR type the archive returns (H hail, G thunderstorm wind gust, D thunderstorm wind damage, N non-thunderstorm wind gust, A high sustained wind, O non-thunderstorm wind damage, M marine, B?, T tornado, C funnel cloud, F flash flood, E flood, R heavy rain, S heavy snow, Z blizzard, I ice storm, L lightning, W waterspout, X funnel... use IEM's TYPETEXT lower-cased as the type word) within 5 miles (8.05 km) of the cell centre, trailing 1,826 SPC days | hail: inches as reported; gusts and sustained wind: mph (the archive's unit, inferred by the research; the contract says so); qualifier E/M/U shown as "estimated", "measured", "unknown" (IEM's changelog definitions); SOURCE normalised to sentence case; REMARK first 160 characters; MAG text "None" is missing |
| Official record (NCEI Storm Events) | NCEI bulk CSV `https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/StormEvents_details-ftp_v1.0_d<YYYY>_c<creation>.csv.gz` for the window's years (read the directory listing for the current creation dates; cache by file name) | Hail and Thunderstorm Wind rows with BEGIN_LAT/LON within 5 miles; High Wind, Strong Wind and other zone-coded rows (CZ_TYPE Z) by the cell's NWS zone (CZ_FIPS -> MTZ###) | hail inches; wind knots converted to mph (1 kt = 1.15078 mph, both shown); MAGNITUDE_TYPE MG/EG/MS/ES as "measured gust", "estimated gust", "measured sustained", "estimated sustained"; BEGIN_DATE_TIME is MST-7 local: convert to UTC then to Montana time; the lag is stated (the newest event in the files) |
| Radar detection (NEXRAD hail signature) | NCEI SWDI nx3hail (filtered: PROB 100, MAXSIZE > 0) CSV, `https://www.ncei.noaa.gov/swdiws/csv/nx3hail/<YYYYMMDD>:<YYYYMMDD>?bbox=-116.05,44.36,-104.04,49.00`, by month (startDate inclusive, endDate exclusive; 744-hour row limit observed), exact duplicate rows dropped, cache by month, last 2 months re-pulled | detections within 2 miles (3.22 km) of the cell centre, grouped by SPC day: count and largest MAXSIZE | MAXSIZE inches (multiples of 0.25); the sentence says a signature is a detection by the radar algorithm, not hail on the ground; the known gaps are stated generally (the inventory is not complete) |
| Warning (NWS polygon warning) | IEM `https://mesonet.agron.iastate.edu/cgi-bin/request/gis/watchwarn.py` with accept=shapefile (or csv), states[]=MT, timeopt=1 per year, limitps=1, one phenomenon per request: SV (severe thunderstorm), TO (tornado), FF (flash flood); issuance polygons (default; no addsvs); EXP rows skipped; county rows (gtype C) are twins, skipped | a cell is covered when its centre lies inside the issuance polygon (even-odd test in Python at build time); per tile, each warning carries the 100-bit cover of the tile's cells | begin and end in Montana time; office; tags: hail inches, wind mph, damage threat word, tornado tag, exactly as the archive gives them (a "<" value is lost by IEM: say "up to" is not possible; show the number as the archive gives it with the word "tag") |
| Zone product (NWS warning for the whole zone) | the same IEM CGI for zone-based products (gtype Z rows with UGC): phenomena HW (high wind), WS (winter storm), BZ (blizzard), IS (ice storm), EC/WC (extreme cold / wind chill), FW (red flag), FL and FA (flood), DS (dust storm), significance W; plus WI with significance Y (wind advisory); per year, limitps=1 one phenomenon per request; verify the CGI returns zone rows, else use the IEM API `/api/1/vtec/...` the openapi document lists, else record "zone products unavailable" and ship without them | the cell's NWS public forecast zone from the NWS zone shapefile (`https://www.weather.gov/source/gis/Shapefiles/WSOM/z_<ddmmyy>.zip`, the current edition; read the page for the file name) by point-in-polygon per cell at build; the zone's events in the window | begin and end in Montana time; product name in words ("High wind warning"); the sentence says the product covered the whole zone, named, not this spot alone |
| Station reading (ASOS daily peak gust) | IEM daily summary, network MT_ASOS: `https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py?network=MT_ASOS&stations=<id>&year1=...&var=max_wind_gust_kts&format=csv` (verify the form; the research used it; 60 stations, 42 ongoing) per station per year, cache by station-year, current year re-pulled | the two nearest stations to the tile centre within 40 miles; days with max gust at or above 50 kt (58 mph); values at or above 130 kt dropped as implausible and counted | mph and knots both shown; station name and distance from the tile centre ("about N miles") |

Not joined, said in the About page: SPC reports (they derive from the LSRs above and would duplicate them); the HRRR
modelled gust (a model, not a reading; a later stage may add it); the DAT damage surveys (few in Montana, and "damage" is
not a word this site states). Known gaps stated in the words: NCEI's lag; SWDI's incomplete inventory; LSR units
inferred; polygon tags are the forecast threat, not what fell.

## Data layout (fixed)
- `hail/j/r{tr:04d}_c{tc:04d}.json` per hail tile (every tile the store has): `{"f":"hail-joins-v1","r":..,"c":..,"d0":"2020-01-01",
  "reports":[[d, hhmm_utc, lat, lon, type_code, mag_text, unit, qualifier, source, city, remark]...] for reports within
  5 miles of the tile's bounds (the browser filters by distance from the cell centre), "records":[...] (NCEI point rows, same
  shape, with "mag_mph" and "mag_kt"), "detections":[[d, hhmm_utc, lat, lon, maxsize_hundredths_in]...] within 2 miles of the
  tile's bounds, "warnings":[{"k":"SV"|"TO"|"FF","b":"<UTC>","e":"<UTC>","o":"TFX","tags":{"hail_in":..,"wind_mph":..,
  "damage":..,"tornado":..},"cells":"<25 hex digits, 100 bits, key order>"}...], "zones":{"<key>":"MTZ048",...} (one entry per
  Montana cell of the tile), "stations":[{"id":"BIL","name":"Billings Logan","lat":..,"lon":..,"miles":12.3}...]}`.
- `hail/z/MTZ048.json`: `{"f":"hail-zone-v1","zone":"MTZ048","name":"...","events":[{"k":"HW","s":"W","b":"<UTC>","e":"<UTC>","o":"BYZ"}...],
  "records":[...NCEI zone rows...]}`.
- `hail/s/BIL.json`: `{"f":"hail-station-v1","id":"BIL","name":"...","lat":..,"lon":..,"days":[[d, mph, kt]...],"dropped":n}`.
- `hail/index.json` gains `"joins": {"built_at","lsr_rows","ncei_rows","ncei_newest_event","swdi_rows","warnings":{"SV":n,"TO":n,"FF":n},
  "zone_events":n,"zones":n,"stations":n,"station_days":n,"sources":{...request counts and failures...},"state":"loaded"|"partial"|"unavailable"}`,
  and `hail/manifest.json` lists every j/, z/ and s/ file. A source that fails in the daily job marks its part "unavailable"
  with the reason; the hail store still builds; the sheet says which part did not load (never silently empty).
- Budget: the j/ files together at most 40 MB on disk (measure; Pages compresses in transit); z/ and s/ under 2 MB.

## Words (Python, in website/joins.py WORDS_JOINS; tested for forbidden terms, with the LSR and NCEI type names that
## contain "damage" allowed only as the source's own type word next to the kind word "report" or "record")
Sheet and town table sections after the hail days: "Reports within 5 miles" (lead: "{n} NWS local storm reports within 5
miles between {start} and {end}." or "No NWS local storm report within 5 miles in these five years. Reports are what
people sent the NWS; they are not a complete record."), rows "{date} {time}: {type}, {magnitude} ({qualifier}), {source},
{miles} mi {bearing}" with the remark on a second line; "Official records within 5 miles (NCEI Storm Events)" (lead with
the lag sentence: "NCEI's database runs to {newest}."); "Radar hail detections within 2 miles" (rows "{date}: {n}
detections, largest {in} in"; the sentence "A detection is the radar algorithm's hail signature for a storm cell, not hail
on the ground."); "Warnings that covered this spot" (rows "{date} {begin} to {end}: {kind} warning, {office}; tags: hail
{in} in, wind {mph} mph{, tornado}{, damage threat}" with "Tags are the forecast threat at issue time, not what fell.");
"Zone products for {zone name} ({zone})" (grouped by product with dates; "These covered the whole zone, not this spot
alone."); "Peak gusts at the nearest stations" (rows "{date}: {mph} mph ({kt} kt) at {station}, about {miles} miles
away" with "A station reading is at the airport, not at this address."). Each section's kind word is in its heading and
its what-this-is sentence. Nothing says damage, an all-clear, insurance, eligibility or "no hail"/"no wind" as a fact;
"no reports" is said as "no report ... reports are not a complete record". Montana time with the zone abbreviation.

## The job
`.github/workflows/hail-store.yml` gains a step after the hail build: `python -m website.joins build --store store
--cache joins-cache --procs 4` (its own Actions cache, keyed by month, optional), then `python -m website.joins verify
store`, before the tar. `pip install numpy pygrib requests pyshp` (pyshp for the shapefiles; the site build never imports
it). The push paths filter adds website/joins.py. Verify checks the Benchland facts below.

## Gates (B2-1 to B2-9)
1. Benchland, SPC day 2025-06-15: the sheet for the gate cell (row 797, col 1986) lists an LSR hail report of 1.75 in within
   5 miles on Jun 15, 2025 (the SPC report at 47.08 N 110.02 W, 20:10 UTC) and an NCEI hail record for the same event; the
   warnings section lists the TFX severe thunderstorm warnings that covered the point (the research found ETN 33, 40 and 48
   on 2025-06-15 at 47.0 N 109.9 W; check the gate cell's own cover).
2. Counts reproduce the research within the window (five years to the build date): LSR hail about 1,347 and G about 2,733
   statewide; NCEI hail by year 139/233/75/96/190 (2021 to 2025); SWDI nx3hail about 60,357 distinct detections in the
   window; SV polygon events about 2,240 and TO 17 (plus FF, counted); station-days at or above 50 kt by year 305/285/121/
   238/247 (2021 to 2025). Deviations are explained (the window moves daily).
3. Every row carries its kind word; the forbidden-term check passes over every new word and template.
4. Units: LSR hail in, gusts mph (inferred, stated); NCEI kt and mph both; SWDI inches; tags inches and mph; station kt and mph.
5. A tile with no joins shows the "no report" sentences, never empty sections; a failed source part shows its unavailable
   sentence.
6. Zone products: the gate cell's zone is named and its high wind warnings in the window are listed (or the unavailable
   sentence if the source could not be read, with the reason).
7. Chromium smoke at 390 and 1280 px: the gate cell's sheet shows all six sections with the Benchland rows; Billings' town
   page tables match an independent read of the shards; zero off-site requests.
8. The joins build is deterministic from cache (two runs give byte-identical j/, z/ and s/ files) and the job's steps run
   locally end to end; sizes measured.
9. Flag-off build unchanged except shared static assets and their hashes.

## Ownership (one worktree: /home/user/wt/wt-b2, branch claude/hail-b2 from claude/hail-b1 at 7aec754)
- Builder 1 (joins): `website/joins.py` (new: pulls with cache, parsers, the zone shapefile reader via pyshp with a lazy
  import, point-in-polygon in numpy, the joins per tile, z/ and s/ files, index and manifest updates, verify, compare
  with the research counts, WORDS_JOINS, describe_joins() for Python rendering, map_data_joins()), `tests/test_joins.py`,
  `.github/workflows/hail-store.yml`, `website/data/hail-fixture/` (the fixture gains j/, z/ and s/ files for its three
  tiles with real rows from the real joins build, under 50 KB in all).
- Builder 2 (site): `website/build.py` (copy j/, z/, s/; index joins block into map.json["hail"]["joins"]; town tables),
  `website/sources.py` (one contract row per source: lsr, ncei_storm_events, swdi_nx3hail, nws_warnings_polygons,
  nws_zone_products, asos_daily_gusts), templates (map.html sheet sections, town.html tables, about.html paragraph),
  `website/static/map/map.js` (the second fetch, distance filter, the six sections from WORDS_JOINS templates, the zone
  and station fetches on demand; documented in the header; no literal words or units), `map.css`, `tools/smoke_map.py`,
  `tests/test_site.py`, `.github/workflows/website.yml` (nothing unless needed).
- Builder 3 (docs): `docs/DECISIONS.md` (D35: B2, the kinds, the radii, the sources not joined, the known gaps, why),
  `docs/DESIGN.md` (section 9 sections, states, words, data contract), `docs/ROADMAP.md`, `README.md`, `AGENTS.md` (layout
  line for joins.py), `research/hail-history/validation-evidence/b2-verification.json` (skeleton).
Nobody commits or pushes; the supervisor does. Scratch under /home/user/hail-b2/out/<name>/; never delete anything
outside a folder you created; tests delete only folders they created (decision 7).

## Supervisor decisions after review round 1 (2026-10-18 17:40 UTC); these override the text above where they differ
D1. Gate B2-1 is two cells. Benchland's own cell (row 792, col 1998; centre 47.075 N 110.015 W) lists the LSR 1.75 in
    report of 2025-06-15 20:10 UTC (0.42 miles away) and its NCEI record; the hail gate cell (row 797, col 1986) lists the
    TFX warnings whose issuance polygon covers it (drop any ETN from the gate text that does not cover that cell) and its
    zone with the zone's high wind warnings. verify measures distance from the cell centre with the 5-mile rule, never from
    tile bounds.
D2. A source part that did not load shows its unavailable sentence in the browser exactly as describe_joins does in Python
    ("Reports could not be loaded in this update; that is not the same as no report"), never a "No ..." lead. The sheet and
    the town table must agree; a test renders both from the same partial index.
D3. Every row starts with its kind word as a short label: "Report:", "Record:", "Detection:", "Warning:", "Zone product:",
    "Station:" (the section heading keeps the long form). The template carries the label; map.js fills it.
D4. The word "damage": (a) an NWS warning's damage threat tag is the NWS's own product field; show it as "NWS damage threat
    tag: considerable" (or destructive), never as a statement about this address; (b) a report's REMARK is quoted as the
    NWS office wrote it, introduced by "Remark, as written:" and shown in quotation marks; (c) the LSR and NCEI type names
    that contain "damage" stay as the source's type word next to the kind label. The what-this-is sentence of the reports
    and warnings sections says: "A report's remark and a warning's tag are the NWS's own words about the report or the
    forecast threat, not a finding about this address." The forbidden-term test allows "damage" only inside a quoted
    remark, a tag label or a type word, and nowhere else.
D5. NCEI wind qualifiers (MG measured gust, EG estimated gust, MS measured sustained, ES estimated sustained) are shown
    on every record row in the module and the sheet.
D6. Zone product spans: an event runs from its issue time to the earliest of its expiry and its cancellation (CAN) or
    expiration (EXP) product time; a span is never zero-length; an event with no end is shown as "end not recorded".
    Zone editions: the NWS public forecast zones changed edition during the window (the reviewers found MTZ060 records
    before April 2026 attributed to the wrong zone). Fetch the prior zone edition from the NWS GIS archive (the dated
    z_<ddmmyy>.zip files) and map each cell to the zone code in force at the event's issue time; if the archive is not
    reachable, list only events whose zone code matches the current edition and add the sentence "Zone boundaries changed
    in {month year}; {n} earlier products under other zone codes are not listed."
D7. Red flag warnings (FW) are issued for fire weather zones, not public forecast zones. Fetch the NWS fire weather zone
    shapefile (fz_<ddmmyy>.zip) and map each cell to its fire zone for FW products; if unreachable, drop FW with the
    sentence "Red flag warnings are not listed (fire weather zones were not available)".
D8. Cells with no zone polygon hit (939 cells on the state line) take the nearest zone polygon within 2 km; beyond that the
    sentence "The forecast zone for this cell could not be determined".
D9. LSR magnitude units by type: hail inches; G, N, A gusts and sustained wind mph; snow (S) and rain (R) inches; tornado,
    funnel, flood, lightning and other types have no magnitude (show the type word only). No unitless number is shown.
D10. The daily job's cache: a 200 response is cached only after its content check passes (CSV header or shapefile
    members); the re-pull windows bypass the cache (the last 2 months of LSR and SWDI, the current year of warnings, zone
    products and station days, every NCEI file whose name is not in the listing); a re-pull that fails keeps the cached
    copy and records "served from cache since {date}" in the index's sources block; a short or malformed CSV row is
    skipped and counted, never aborting the build; a missing NCEI year drops that year only with the reason.
D11. Zone rows the join cannot place (the 1,648 IEM rows and 451 NCEI rows the reviewers counted) are counted in the
    index and the zone section says "{n} zone products in the window could not be placed on a zone".
D12. The four B1 tests in tests/test_hail.py that assert the fixture's file count, bytes or manifest list are updated for
    the B2 layout (the fixture now holds j/, z/ and s/ files); website/hail.py may get the minimal change that lets its
    manifest and fixture code list those folders. The joins fixer owns those two files for this purpose.
D13. Warnings that cross midnight show both dates in the browser (the end date is never dropped).
D14. Docs state only what the build does (the reviewers' list: the budget sentence, "73 months", "the rest are not kept").

## Supervisor decisions for round 2 (2026-10-18 23:00 UTC); these override round 1 where they differ
D15. Re-pull windows beat the cache: for the windows D10 names (and, in January, also the previous year's warnings, zone
     products and station days), the build fetches fresh and writes the fresh copy over the cached one; the cached copy is
     used only when the fresh request fails, and the index then says "served from cache since {date}".
D16. Zone event spans: begin is the earliest issue time among the event's NEW and CON rows; when only cancellation rows
     exist, "start not recorded". End is the earliest cancellation (CAN) row's expire time when one exists (the zone CSV
     carries it), else the latest non-cancellation expiry; "end not recorded" only when neither exists. The prior public
     zone edition (z_18mr25.zip, linked on the NWS PublicZones page) is fetched and each event takes the zone code of the
     edition in force at its issue time; the cut-over date is the newer edition's effective date from its file name.
D17. The zone section has two leads: "{n} products for zone {name} ({code})" and "{m} red flag warnings for fire weather
     zone {name} ({code})"; the browser fetches hail/z/fire-<zone>.json and renders the red flag rows like the public ones.
D18. Station rows: s/ files carry whole numbers (mph and kt rounded to integers); both Python and the browser print
     "{kt} kt ({mph} mph)" with integers.
D19. Typed report rows: joins.py exports the set of type codes that carry a unit (J.unit_codes in map.json); the browser
     uses the typed template (type word only) for every other code and never prints a bare number or "no size given".
D20. The unavailable sentence for a part is exactly "{Part} could not be loaded in this update; that is not the same as
     no {part}." in Python and in the browser (parts: Reports, Records, Detections, Warnings, Zone products, Station
     readings).
D21. Malformed rows (bad dates, short rows) are skipped and counted in the index, never failing a file or the build.
D22. The warnings sentence "older years have fewer tags" is dropped (the counts contradict it).
D23. JOINS_DEADLINE_S of 35 minutes stands and is recorded in D35 (not D34).
D24. Docs restate the final build's measured sizes from the re-check, document the fire zones, the two zone leads, the
     D3 labels on every row template, and that a report is not an inspection (the sentence is in WORDS_JOINS reports_what).

## Supervisor decisions for round 3 (2026-10-19 01:05 UTC); these override round 2 where they differ
D25. Zone event begin (supersedes the "start not recorded" clause of D16): every zone row carries the event's issue time,
     so begin is the earliest issue time among the event's NEW and CON rows, else the issue time the rows carry; "start not
     recorded" is written only when no row carries an issue time (the build never does today). Products that share an
     event number but have different issue times are different events: the group key includes the issue time.
D26. Zone event end: when a cancellation time exists it is the end, even when it is at or before the start; such an event
     reads "cancelled at {time}" in place of "{begin} to {end}". "End not recorded" only when neither a cancellation time
     nor an expiry exists. Upgrade (UPG) rows do not end an event (their expire field is the update time).
D27. A station or zone file that fails to load, or is unreadable or malformed, makes its section unavailable with D20's
     sentence in Python (describe_joins raises or marks the part) and in the browser, never a "No day" or "No product"
     lead; a failed zone file does not hide the point records that loaded (the records section shows its rows with the
     partial sentence for the zone part).
D28. The smoke's sheet check compares each section's rows in order and their count with describe_joins, and one case
     aborts a station file request and expects the stations section's unavailable sentence.
D29. Docs: the open-item figures follow the data reviewer's recount (3,684 cancellation-only groups; 446 at 00:00 UTC, 298
     on the day after the product date; 3,238 at other times); open item 12 closes (the two fire zone editions are
     identical); the docstring says 110 zone groups with a NEW row (157 NEW rows).
