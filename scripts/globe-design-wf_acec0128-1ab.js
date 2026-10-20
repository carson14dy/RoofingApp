export const meta = {
  name: 'globe-design',
  description: 'Rendering and pipeline analyses, then three competing architectures judged by three lenses and synthesised',
  phases: [
    { title: 'Analyse and design', detail: 'W11 rendering, W12 pipeline, three designers' },
    { title: 'Judge', detail: 'three judges score all three designs' },
    { title: 'Synthesise', detail: 'one design section from the winner plus grafts' },
  ],
}

const REPO = '/home/user/RoofingApp'
const EVID = REPO + '/research/globe/validation-evidence/'
const SCRATCH = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad'

const CTX = `You are one of several agents working on the "globe view" research scaffold for RoofingApp, a Montana roofing company's weather desktop app. A supervisor reads your output; it is data, not prose for a person.

Read first, in this order:
1. ${REPO}/research/globe/README.md sections 1-7 (the plan, written before the evidence; several of its numbers were corrected by the evidence).
2. ${SCRATCH}/supervisor-log.md — the supervisor's verdicts on two critiques of the plan (the "ACCEPT" list is binding for you; the "REJECT" list explains what the supervisor kept and why) and the wave-1 refuter verdicts.
3. The evidence files under ${EVID} that your task names. Where a file has a "review" key, the review's corrections win over its "facts". Where a file has no "review" key yet, treat its facts as unreviewed: re-check live any fact you build a conclusion on (a size, a version, a licence sentence) and say you did.
4. ${REPO}/AGENTS.md hard rules and ${REPO}/docs/DECISIONS.md (D1, D2, D4, D7-D9, D12, D19, D23, D24), ${REPO}/docs/ROADMAP.md.

Binding constraints: Python first (rule 4 / D1: all data, time, geometry, thresholds and freshness logic in Python; browser JavaScript only draws and handles browser-only events, each duty documented); the self-test runs with the network off and checks HTTP status only; the 50 MiB cap is the WHOLE-REPO zipball; a new pip package means a new installer (rule 2); evidence kinds and freshness limits change only by a DECISIONS entry; no "best" claims (rule 9); evidence honesty (rule 5): observation / satellite estimate / radar estimate / official alert never merged, never damage, no echo is not clear, MRMS -99 and -999 are "no radar data" (meanings unverified), MRMS levels are heights above mean sea level (the 0.5 km level is below ground over most of Montana), cloud-top height is an estimate of the top only, parallax wording from ${EVID}parallax.json; no paid token in browser code; no saved-place lists sent to any third-party job (publish fixed statewide products); the 3D view ships behind a default-off setting.

Working rules: today is 2026-10-17 (UTC); outbound HTTPS works; use WebFetch/WebSearch (ToolSearch "select:WebFetch,WebSearch") for pages and quote the sentence you rely on with its URL. Write ONLY the one output file your task names (JSON, at most 30 KB) under ${EVID}. Never write model names or AI-vendor identifiers into any file. Do not modify any other repo file. Numbers carry units and a source (an evidence file name, a URL, or "computed: <formula>"); anything else is marked unverified.`

const ANALYSIS_SCHEMA = {
  type: 'object',
  properties: {
    slug: { type: 'string' },
    output_file: { type: 'string' },
    headline: { type: 'array', items: { type: 'string' } },
    numbers: { type: 'array', items: { type: 'string' } },
    unverified: { type: 'array', items: { type: 'string' } },
    questions_for_owner: { type: 'array', items: { type: 'string' } },
  },
  required: ['slug', 'output_file', 'headline', 'numbers', 'unverified'],
}

const DESIGN_SCHEMA = {
  type: 'object',
  properties: {
    slug: { type: 'string' },
    output_file: { type: 'string' },
    name: { type: 'string' },
    one_paragraph: { type: 'string' },
    js_duties: { type: 'array', items: { type: 'string' } },
    pip_packages_added: { type: 'array', items: { type: 'string' } },
    offline_and_selftest_behaviour: { type: 'string' },
    phases: { type: 'array', items: { type: 'string' } },
    biggest_risks: { type: 'array', items: { type: 'string' } },
  },
  required: ['slug', 'output_file', 'name', 'one_paragraph', 'js_duties', 'pip_packages_added', 'offline_and_selftest_behaviour', 'phases', 'biggest_risks'],
}

const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    lens: { type: 'string' },
    output_file: { type: 'string' },
    scores: { type: 'array', items: { type: 'object', properties: { design: { type: 'string' }, score_0_to_10: { type: 'number' }, reasons: { type: 'array', items: { type: 'string' } }, fatal_flaws: { type: 'array', items: { type: 'string' } } }, required: ['design', 'score_0_to_10', 'reasons', 'fatal_flaws'] } },
    ranking: { type: 'array', items: { type: 'string' } },
    grafts: { type: 'array', items: { type: 'string' } },
    facts_rechecked: { type: 'array', items: { type: 'string' } },
  },
  required: ['lens', 'output_file', 'scores', 'ranking', 'grafts', 'facts_rechecked'],
}

const W11 = `# Task W11 — rendering techniques for clouds and storms on a globe (slug: rendering)
Read ${EVID}mrms.json, goes-aws.json, gibs.json, globe-libs.json, webgl-runtime.json, parallax.json, and if present prototype-mrms.json and prototype-globe.json (measured voxel counts, bytes and draw results from the prototype).
Produce ${EVID}rendering-options.json: for each technique — (a) draped satellite texture, (b) cloud deck displaced by cloud-top height (mesh vertex displacement), (c) volumetric ray-marching in a 3D texture (WebGL2 Data3DTexture / custom shader), (d) sparse voxel points or boxes from MRMS (what the prototype draws), (e) isosurfaces (marching cubes in Python → glTF / 3D Tiles) at 20/35/50 dBZ display classes, (f) stacked translucent slabs per level, (g) 2D fallback drape (NWS WMS) — give: data needed; where computed (Python server-side vs browser); bytes to the browser per frame for the Montana + border box at the measured voxel counts (computed from the evidence numbers, formula shown); GPU and memory load class (low/medium/high with the reason: counts of points, texture sizes versus MAX_3D_TEXTURE_SIZE 2048 from webgl-runtime.json); what it honestly represents and the legend text it needs; failure modes (sub-terrain MSL levels; parallax; no-data cells; frame gaps; interpolation creating false precision — forbidden); which library supports it (from globe-libs.json, re-check the API doc for any claim you rely on); which phase it fits. Rank per phase with reasons; no "best". Also survey, with URLs and quoted sentences, 3-5 existing viewers that draw GOES or radar in 3D or pseudo-3D (open-source or public) and what technique each uses.`

const W12 = `# Task W12 — data pipeline and cost (slug: pipeline)
Read ${EVID}mrms.json, goes-aws.json, hosting-options.json, app-integration.json, webgl-runtime.json, and if present prototype-mrms.json and prototype-goes.json (measured download bytes, decode times, output bytes).
Produce ${EVID}pipeline-options.json comparing: (A) on each crew machine: download + decode on the desktop (needs eccodes + netCDF4 in the installer under rule 2 — measure the wheel sizes with "pip download --no-deps" for eccodes, eccodeslib, netCDF4, numpy into a scratch directory and report bytes; bytes per hour per machine from the evidence; CPU time from prototype measurements); (B) a scheduled job on GitHub Actions (5-min minimum, drops, terms doubt — from hosting-options.json) publishing fixed statewide products to object storage; (C) a small always-on server (prices in hosting-options.json; roadmap item 8 already needs one) producing the same products; (D) hybrid: server publishes products, desktop crops locally. For each: bytes per 2-min MRMS step and per 5-min GOES step in and out (formulas shown), monthly transfer per crew machine for a 12-hour storm day season, $/month from the quoted prices, latency added, failure surfacing and staleness fields, privacy (no place lists leave the machine), installer impact, what the self-test must do. Define the frame-bytes budget the plan's Phase 3 cites: a number per frame and per 2-hour loop with its derivation from the measured voxel counts at thresholds 20 and 35 dBZ. State the product format you propose (compact JSON vs binary + sidecar) with sizes. Include the MESH footprint job of roadmap item 4 as the same job. Rank with reasons; no "best".`

const DESIGNERS = [
  { slug: 'design-a', name: 'A — Jinja-generated CesiumJS page inside the Flask app (/globe)', brief: `Design the globe as a page of the existing payload: a Flask route /globe rendering a Jinja template that embeds configuration and layer lists computed in Python (the way Folium generates Leaflet today — note the app already loads Leaflet from a CDN, see supervisor-log.md), loads CesiumJS from a pinned CDN with an integrity hash, and a small documented JavaScript file that only draws. Data endpoints under /api/globe/… computed by Python (alerts with zone geometry handling, layer states, volume and cloud-height products). Behind a default-off setting. Must pass the self-test offline. Use the prototype under ${REPO}/research/globe/prototype as evidence of what works (read serve.py and globe.js, and prototype-globe.json if present).` },
  { slug: 'design-b', name: 'B — separate globe window served by the desktop shell, outside the payload', brief: `Design the globe as a second local server/window started by the desktop shell (desktop/launcher.py pattern: private port, session key, Host check), kept out of the self-updating payload so the globe library and any heavy decoders can ship with a new installer rather than through the 50 MiB zipball; the payload only links to it and shares the SQLite database read-only. Consider what this costs in installer churn (D3: desktop changes only with a new installer) and how updates reach crews. Use the prototype under ${REPO}/research/globe/prototype as evidence.` },
  { slug: 'design-c', name: 'C — Python-first 2.5D without a globe library, or a Python-wrapped globe (pydeck)', brief: `Design the most Python-first option that still meets the owner's wish for 3D clouds and storms: either (i) pydeck / deck.gl GlobeView generated from Python (check globe-libs.json and re-check pydeck's GlobeView support live — quote), with its installer impact under rule 2; or (ii) staying on the Folium flat map with 2.5D encodings computed in Python (radar echo tops as colour, cloud-top height contours, a side elevation profile image rendered server-side), i.e. no globe library at all. State plainly what each sub-option cannot do that the owner asked for, and what it protects (rule 4, D1, offline self-test, no CDN). Use the prototype under ${REPO}/research/globe/prototype only as a comparison.` },
]

function designPrompt(d) {
  return CTX + `\n\n# Task W13 — architecture design ${d.name} (slug: ${d.slug})\n${d.brief}\nRead ${EVID}globe-libs.json, webgl-runtime.json, app-integration.json, hosting-options.json, mrms.json, goes-aws.json, gibs.json, parallax.json, and ${REPO}/payload/app.py, payload/maps.py, payload/templates/live.html, desktop/launcher.py, desktop/updater.py (read-only).\nProduce ${EVID}${d.slug}.json with: name; summary; components (each with language, where it runs, what it owns); the COMPLETE list of hand-written JavaScript duties with a one-line reason each must run in the browser (this list is what the owner rules on); pip packages added (none, or which, and the installer consequence); library pin and integrity policy; offline and self-test behaviour (state per layer: "off" in the self-test; stale/unavailable live; "3D view could not load" separate from data states); data endpoints and their Python owners (reuse of weather.py functions by name from app-integration.json); evidence-kind and freshness entries needed (as DECISIONS proposals); alert handling for null geometry (zone outline, marker + text, can't-tell); how the 3D storms layer handles MSL levels below terrain, no-data codes, legend text and no interpolation; the default-off setting; route security tests; phases with numeric done-when checks and a stop option each; size impact on the zipball (numbers); risks ranked; what the owner must decide. No "best" claims; cite evidence files for every number.`
}

function judgePrompt(lens, designs) {
  return CTX + `\n\n# Task W13 — judge the three designs through the lens: ${lens.name} (slug: judge-${lens.slug})\nThe designs are ${EVID}design-a.json, ${EVID}design-b.json, ${EVID}design-c.json (summaries: ${JSON.stringify(designs.map(d => d && { slug: d.slug, name: d.name, one_paragraph: d.one_paragraph, js_duties: d.js_duties, pip_packages_added: d.pip_packages_added }))}).\n${lens.criteria}\nScore each design 0-10 on this lens only, with reasons that cite evidence files, repo rules (file:line) or facts you re-checked live; list fatal flaws (a rule or decision the design cannot satisfy without an owner decision — name the decision); rank; and list grafts (specific ideas from losing designs the winner should adopt). Re-check at least three facts the designs rely on against the evidence files' review keys or live requests, and list them. Write ${EVID}judge-${lens.slug}.json.`
}

const LENSES = [
  { slug: 'rules', name: 'rules and evidence honesty', criteria: 'Criteria: compliance with AGENTS.md hard rules 1-9 and DECISIONS D1-D4, D12, D19, D23; how little JavaScript carries logic; evidence kinds and freshness handled by DECISIONS entries; null-geometry alerts; no-data and sub-terrain handling; legends; demo policy; no paid tokens in the browser; privacy of place lists; the default-off setting; route security.' },
  { slug: 'engineering', name: 'engineering cost and risk', criteria: 'Criteria: installer and SHELL_API impact (rule 2, D3); zipball size (whole-repo 50 MiB cap, numbers); offline self-test behaviour; WebGL availability on WebView2 / WKWebView / Linux (webgl-runtime.json); CDN dependence and integrity; update path to crews (D3-D6); maintenance burden (lines of JavaScript, number of moving parts, test surface); performance plausibility from the prototype measurements; failure modes and how they surface.' },
  { slug: 'product', name: 'value to the office and crews, and fit with the pilot', criteria: 'Criteria: which decisions the view improves for which person (read ${SCRATCH}/plan-critique-product.json jobs_to_be_done); honesty traps avoided; fit with the roadmap order (installers, pilot, baseline — ROADMAP items 1-3 and the "baseline before any new feed" line) and with keeping the crews\' screen unchanged during the pilot; demo value with DEMO-only data; mobile/field reachability (open question); what the owner literally asked for (a Google Earth-like globe with 3D clouds and storms) versus what each design delivers.' },
]

const SYNTH = (judges, designs) => CTX + `\n\n# Task W13 — synthesise the design section (slug: design-synthesis)\nThree designers (${EVID}design-a.json, design-b.json, design-c.json) and three judges (${EVID}judge-rules.json, judge-engineering.json, judge-product.json) have reported. Judge summaries: ${JSON.stringify(judges.map(j => j && { lens: j.lens, ranking: j.ranking, grafts: j.grafts }))}.\nWrite ${EVID}design-synthesis.json: the recommended architecture (one of A/B/C or a named hybrid), why (citing the judges' scores and the evidence), the grafts adopted from the others, the complete JavaScript duty list for the owner's ruling, the pip/installer consequence, the DECISIONS entries it needs (proposed wording for each: evidence kinds, freshness limits, library pin and integrity policy, publish host, the Folium-CDN correction to D23), the phase plan with numeric done-when and stop criteria, the owner decisions it depends on (map them to D-G1…D-G9 from the README and add any new ones), and the dissent (what the losing designs do better and when the owner should prefer them). Keep it under 30 KB; no "best" claims; every number cites an evidence file.`

log('Wave 2b: rendering + pipeline analyses and three designers in parallel')
const [w11, w12, dA, dB, dC] = await parallel([
  () => agent(CTX + '\n\n' + W11, { label: 'analyse:rendering', phase: 'Analyse and design', model: 'haiku', schema: ANALYSIS_SCHEMA }),
  () => agent(CTX + '\n\n' + W12, { label: 'analyse:pipeline', phase: 'Analyse and design', model: 'haiku', schema: ANALYSIS_SCHEMA }),
  () => agent(designPrompt(DESIGNERS[0]), { label: 'design:A', phase: 'Analyse and design', model: 'haiku', schema: DESIGN_SCHEMA }),
  () => agent(designPrompt(DESIGNERS[1]), { label: 'design:B', phase: 'Analyse and design', model: 'haiku', schema: DESIGN_SCHEMA }),
  () => agent(designPrompt(DESIGNERS[2]), { label: 'design:C', phase: 'Analyse and design', model: 'haiku', schema: DESIGN_SCHEMA }),
])
const designs = [dA, dB, dC]
log('Wave 2b: three judges scoring all designs')
const judges = await parallel(LENSES.map(l => () => agent(judgePrompt(l, designs), { label: 'judge:' + l.slug, phase: 'Judge', model: 'haiku', schema: JUDGE_SCHEMA })))
log('Wave 2b: synthesis')
const synthesis = await agent(SYNTH(judges, designs), { label: 'synthesis', phase: 'Synthesise', model: 'haiku', schema: ANALYSIS_SCHEMA })
return { w11, w12, designs, judges, synthesis }
