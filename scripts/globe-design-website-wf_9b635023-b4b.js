export const meta = {
  name: 'globe-design-website',
  description: 'Designer D on the website architecture, re-judge all four designs with the website as the ruling constraint, synthesise; W19 rights and hosting matrix',
  phases: [
    { title: 'Design D + W19', detail: 'website-native globe design; rights/hosting matrix' },
    { title: 'Re-judge', detail: 'three lenses over A-D with main-architecture.json ruling' },
    { title: 'Synthesise', detail: 'website synthesis' },
  ],
}

const REPO = '/home/user/RoofingApp'
const EVID = REPO + '/research/globe/validation-evidence/'
const SCRATCH = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad'

const CTX = `You are one of several agents working on the "globe view" research scaffold for RoofingApp. A supervisor reads your output; it is data, not prose for a person.

THE RULING FACTS: the product is now the Montana Hail Watch WEBSITE (docs/DECISIONS.md D26-D29; AGENTS.md on this branch after merging main at 195d68c). Read ${EVID}main-architecture.json FIRST and treat it as the governing description: static pages built by website/build.py, rebuilt from empty every 10 minutes by .github/workflows/website.yml within a 15-minute job and published by GitHub Pages; the browser may fetch only site files (website/static/map/map.js:9; tests/test_site.py:459-471); third-party code is vendored and pinned (Leaflet 1.9.4), never a CDN (AGENTS.md rule 4); the base map is Natural Earth + Census under 450 KB (USGS tiles were retired, DECISIONS.md:379-381); 14 towns, no places/territories/jobs; audience phones 288 px to 1440 px desktops, sunlight, slow connections (docs/DESIGN.md); states loaded / problem / stale plus the page-age banner; gap words "No radar coverage", "No model data", "Outside map area", "This is not an all-clear."; disclaimer "Weather information only. It does not confirm roof damage"; the map keeps a text List; freshness radar 30 min (gridded.py:53; doc drift vs 15 min), station 75 min, page 25 min; no past frame survives a build except --previous state; one live build downloads 45.7 MB and writes 3.9 MB; map.js is 2,155 lines / 115 KB; the Website workflow runs branch-push previews with --require-live and a Chromium smoke check.

Then read: ${REPO}/research/globe/README.md sections 1-7 (the ORIGINAL plan, written for the parked desktop app — its constraints are superseded; its evidence rules in section 4 stand), ${SCRATCH}/supervisor-log.md (verdicts; the "ARCHITECTURE SHIFT" section), the evidence files your task names under ${EVID} (a "review" key wins over "facts"), ${REPO}/AGENTS.md, docs/DESIGN.md, docs/DECISIONS.md D25-D29, website/build.py, website/gridded.py, website/sources.py, website/templates/map.html, website/static/map/map.js (skim its sections), tests/test_site.py, tools/smoke_map.py.

Binding rules: Python builds all data and pages; hand-written JavaScript only for browser-only needs, documented, no framework, with a stated byte budget; evidence honesty (rule 5): observation / satellite estimate / radar estimate / official alert never merged, never damage, no echo is not clear, MRMS -99 and -999 are "no radar data" (meanings unverified), MRMS levels are heights above mean sea level, cloud-top height is an estimate of the top only (parallax wording in ${EVID}parallax.json), no interpolation between frames, no severity colour ramps, every hazard colour carries its word; no "best" claims (rule 9); every number carries a unit and a source (evidence file, file:line, URL, or "computed: formula"), else "unverified".

Working rules: today is 2026-10-17 (UTC); outbound HTTPS works; WebFetch/WebSearch via ToolSearch "select:WebFetch,WebSearch", quote the sentence you rely on with its URL. Write ONLY the one output file your task names under ${EVID} (JSON, at most 30 KB). Never write model names or AI-vendor identifiers into any file. Do not modify any other repo file.`

const DESIGN_SCHEMA = {
  type: 'object',
  properties: {
    slug: { type: 'string' }, output_file: { type: 'string' }, name: { type: 'string' }, one_paragraph: { type: 'string' },
    js_duties: { type: 'array', items: { type: 'string' } },
    vendored_bytes: { type: 'string' },
    build_additions: { type: 'array', items: { type: 'string' } },
    owner_decisions: { type: 'array', items: { type: 'string' } },
    phases: { type: 'array', items: { type: 'string' } },
    biggest_risks: { type: 'array', items: { type: 'string' } },
  },
  required: ['slug', 'output_file', 'name', 'one_paragraph', 'js_duties', 'vendored_bytes', 'build_additions', 'owner_decisions', 'phases', 'biggest_risks'],
}
const ANALYSIS_SCHEMA = {
  type: 'object',
  properties: { slug: { type: 'string' }, output_file: { type: 'string' }, headline: { type: 'array', items: { type: 'string' } }, numbers: { type: 'array', items: { type: 'string' } }, unverified: { type: 'array', items: { type: 'string' } } },
  required: ['slug', 'output_file', 'headline', 'numbers', 'unverified'],
}
const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    lens: { type: 'string' }, output_file: { type: 'string' },
    scores: { type: 'array', items: { type: 'object', properties: { design: { type: 'string' }, score_0_to_10: { type: 'number' }, reasons: { type: 'array', items: { type: 'string' } }, fatal_flaws: { type: 'array', items: { type: 'string' } } }, required: ['design', 'score_0_to_10', 'reasons', 'fatal_flaws'] } },
    ranking: { type: 'array', items: { type: 'string' } }, grafts: { type: 'array', items: { type: 'string' } }, facts_rechecked: { type: 'array', items: { type: 'string' } },
  },
  required: ['lens', 'output_file', 'scores', 'ranking', 'grafts', 'facts_rechecked'],
}

const DESIGN_D = `# Task — design D: the globe as a page of the Montana Hail Watch website (slug: design-d)
Read also ${EVID}globe-libs.json (vendored sizes: CesiumJS 1.146 Cesium.js 6.08 MB + Workers 1.03 MB + Assets 4.38 MB; MapLibre GL JS 5 globe ~0.8 MB; three.js / globe.gl ~1 MB; licences; WebGL2 needs), ${EVID}webgl-runtime.json (the headless Chromium recipe for tests), ${EVID}rendering-options.json, ${EVID}pipeline-options.json, ${EVID}prototype-mrms.json, ${EVID}prototype-goes.json, ${EVID}prototype-globe.json, ${EVID}gibs.json, ${EVID}goes-aws.json, ${EVID}mrms.json, ${EVID}terrain.json, ${EVID}base-imagery.json, ${EVID}labels-on-globe.json, ${EVID}montana-imagery-buildings.json, ${EVID}hosting-options.json, ${EVID}evaluation-predeclared.json.
Design the globe so that it obeys the site's rules as they stand, and state separately what the owner would have to relax to get closer to "Google Earth":
1. Page and placement: a fifth page (globe.html) generated by Jinja from build.py data like map.html, linked from the map page; the phone layout (288 px) and the desktop layout; the text List equivalent (every drawn value also listed as text, or the site's "no text version" statement); the page-age banner and states loaded / problem / stale; the disclaimer in the legend or footer.
2. The library, vendored and pinned under website/static/<lib>/ with exact version, licence file and bytes (choose from the measured sizes; show the arithmetic for page weight on a slow connection; state what each candidate cannot do: e.g. MapLibre has no volumes, CesiumJS is 11.5 MB vendored and needs WebGL2, three.js has no map tiling). Give a stated JavaScript byte and line budget for the hand-written loader and the complete list of its duties, each with why it must run in the browser.
3. Data produced by the SAME 10-minute build (no second job unless you justify it against website.yml's single-publisher model): a Montana-box GOES GeoColor or Band 13 frame (from GIBS or the AWS netCDF — say which, bytes per build, latency), a cloud-top-height PNG + sidecar (ACHA2KMC 2 km or ACHAC 10 km — bytes per build), an MRMS volume crop for the frame box at thresholds 20/35 dBZ (bytes per build from prototype-mrms.json; the heights are MSL and the 0.5 km level is below ground over most of Montana — say how the view handles it), a terrain height field for the frame box (from which source, bytes, licence, hostable once by hand like basemap.json), town labels from towns.json, alerts from the site's existing data. Total bytes written per build and downloaded per visitor; fit inside the 15-minute job and the measured 45.7 MB download; what --previous must carry for any time loop.
4. Imagery for the globe surface: what the site can host (a static low-resolution Earth texture under a stated size with a CC0/public-domain source; a Montana-box static orthoimage built by hand; or none, just the Natural Earth base) and what would need the owner to relax "browser fetches only site files" (streaming NASA GIBS or other tiles directly). Present the relaxation as decision D-G1 with its consequences (privacy, reliability, test_site.py change).
5. Honesty: legends (dBZ-only "radar echo strength"; "cloud top only, satellite estimate"; parallax wording from parallax.json; "No radar data" for -99/-999; the site's gap words; no severity ramps; vertical exaggeration labelled); kinds kept apart per AGENTS.md; freshness per source following sources.py seconds (propose numbers from measured latency: GOES via GIBS ~40 min, via AWS ~2-3 min; MRMS 2 min source but 10-min build).
6. Tests and CI: test_site.py additions (page uses only site files; legend text present; frames present or the failure text), test_gridded.py-style unit tests for the crop/threshold/voxel and cloud-height code, a Chromium smoke check like tools/smoke_map.py with pixel sampling and a layer toggle, the 288-1440 px width test, the website.yml path filter and test command changes.
7. Phases with numeric done-when and a stop option; byte budgets per phase; what the owner must decide (D-G1 browser fetch rule, library, page placement, name, phone floor, whether to host a static Earth texture, the Actions-terms note from hosting-options.json).
Write ${EVID}design-d.json with these sections, every number sourced.`

const W19 = `# Task W19 — rights, attribution and hosting matrix, and byte budgets (slug: rights-matrix)
Read every evidence file under ${EVID} that has a "terms" key or a "review" with licence corrections (gibs, goes-aws, mrms, radar-tiles, terrain, base-imagery, globe-libs, google-terms, labels-on-globe, montana-imagery-buildings, hosting-options), plus website/templates/about.html (the site's source table and how it states each source) and tools/build_basemap.py (the licences it states for Natural Earth and Census).
Produce ${EVID}rights-matrix.json: one row per candidate layer or library (NASA GIBS imagery layers; NOAA GOES on AWS; MRMS; NEXRAD Level II; NWS radar services; NCEP GeoServer; IEM tiles; AWS Terrain Tiles; USGS 3DEP; USGS imagery (retired on main — say so); NASA Blue Marble; VIIRS; Natural Earth; Census TIGER; MSL imagery (expiry 2026-07-31); Overture buildings; Microsoft footprints; OSM/Overpass/Nominatim; Esri; Sentinel-2 cloudless; Google Map Tiles; CesiumJS; MapLibre; three.js/globe.gl; deck.gl; Leaflet as the existing precedent) with columns: licence (quoted sentence + URL from the evidence), attribution text to show, commercial use (yes / no / unverified, with the quote), can the site HOST it (serve from website/static or _site) and at what bytes, can the browser fetch it directly today (no — site files only; note what rule would change), caching/retention terms, expiry or retirement, the About-table row text the site would show. Mark unverified where the evidence says so. Then: the byte budgets — the research/ folder today (du -sb research), the website static assets today (du -sb website/static), GitHub Pages limits from hosting-options.json, a proposed per-build data budget and per-page weight budget with their derivation.`

function judgePrompt(lens, dD) {
  return CTX + `\n\n# Task — re-judge designs A, B, C and D through the lens: ${lens.name} (slug: judge2-${lens.slug})\nDesigns: ${EVID}design-a.json, design-b.json, design-c.json (written for the parked desktop app) and ${EVID}design-d.json (written for the website; summary: ${JSON.stringify(dD && { name: dD.name, one_paragraph: dD.one_paragraph, vendored_bytes: dD.vendored_bytes, js_duties: dD.js_duties, owner_decisions: dD.owner_decisions })}). Earlier judge files ${EVID}judge-rules.json, judge-engineering.json, judge-product.json may exist; read them if present but score afresh with the WEBSITE as the ruling architecture (main-architecture.json). A design that assumes the desktop app must be scored on what of it transfers to the website.\n${lens.criteria}\nScore each design 0-10 on this lens only with reasons citing evidence files, repo rules (file:line) or facts you re-checked live; list fatal flaws (a site rule the design cannot satisfy without an owner decision — name the decision); rank; list grafts for the winner. Re-check at least three facts the designs rely on (a vendored size, a licence sentence, a build limit) and list them. Write ${EVID}judge2-${lens.slug}.json.`
}

const LENSES = [
  { slug: 'rules', name: 'site rules and evidence honesty', criteria: 'Criteria: AGENTS.md rules 4-9 as they now read (vendored third-party code, documented browser-only JS, no framework); browser fetches only site files; evidence kinds kept apart; freshness per sources.py; gap words and not-all-clear wording; disclaimer; text List; DEMO/sample labelling (website/sample.py); no severity ramps; legends with words.' },
  { slug: 'engineering', name: 'engineering cost and risk on the website', criteria: 'Criteria: fits the 10-minute cron and 15-minute job with measured bytes; build-from-empty and --previous handling for any loop; vendored bytes and page weight on slow connections; WebGL2 on phones; test_site/test_gridded/smoke additions; path filter and test command changes; failure modes surfacing as problem/stale; maintenance burden (JS lines, moving parts); what the prototype already proved (prototype-*.json).' },
  { slug: 'product', name: 'value to the roofing company and fit with the site', criteria: 'Criteria: which decision the view improves for which person (read ' + SCRATCH + '/plan-critique-product.json jobs_to_be_done, re-read for a website audience: office on desktop, crews on phones, the public); honesty traps; placement among the four pages and the map card; the owner\'s literal ask (a Google Earth-like globe with 3D clouds and storms) versus what each design delivers and what it asks the owner to relax; ROADMAP fit (read docs/ROADMAP.md on this branch) and the naming/trademark note (D26).' },
]

const SYNTH = (judges) => CTX + `\n\n# Task — website synthesis (slug: design-synthesis-website)\nRead ${EVID}design-a.json, design-b.json, design-c.json, design-d.json, ${EVID}judge2-rules.json, judge2-engineering.json, judge2-product.json (summaries: ${JSON.stringify(judges.map(j => j && { lens: j.lens, ranking: j.ranking, grafts: j.grafts }))}) and, if present, ${EVID}design-synthesis.json (the earlier desktop-era synthesis — note what of it survives).\nWrite ${EVID}design-synthesis-website.json: the recommended architecture for the WEBSITE (likely D or a named hybrid), why (citing scores and evidence), grafts adopted, the complete JavaScript duty list and byte/line budget for the owner's ruling, the library with its vendored bytes and licence, the build additions with bytes per build and per visitor, the DECISIONS entries needed (proposed wording: browser-fetch rule or its exception, library pin, freshness seconds per new source in sources.py CONTRACTS, evidence-kind separation for satellite layers, the doc-drift fix radar 15 vs 30 min, the Actions-terms note), the phase plan with numeric done-when and stop criteria, the owner decisions (map to D-G1…D-G9 and add new ones), and the dissent. Under 30 KB; no "best" claims; every number cites an evidence file.`

log('Design D (website) and W19 rights matrix in parallel')
const [dD, w19] = await parallel([
  () => agent(CTX + '\n\n' + DESIGN_D, { label: 'design:D-website', phase: 'Design D + W19', model: 'haiku', schema: DESIGN_SCHEMA }),
  () => agent(CTX + '\n\n' + W19, { label: 'analyse:rights-matrix', phase: 'Design D + W19', model: 'haiku', schema: ANALYSIS_SCHEMA }),
])
log('Re-judging A-D with the website as the ruling architecture')
const judges = await parallel(LENSES.map(l => () => agent(judgePrompt(l, dD), { label: 'judge2:' + l.slug, phase: 'Re-judge', model: 'haiku', schema: JUDGE_SCHEMA })))
log('Website synthesis')
const synthesis = await agent(SYNTH(judges), { label: 'synthesis-website', phase: 'Synthesise', model: 'haiku', schema: ANALYSIS_SCHEMA })
return { dD, w19, judges, synthesis }
