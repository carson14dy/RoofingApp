export const meta = {
  name: 'hail-history-research-wave1',
  description: 'Verify the sources for a 5-year Montana hail and wind history: ten workstreams, each researched then refuted',
  phases: [
    { title: 'Research', detail: 'ten researchers, live requests and content checks', model: 'haiku' },
    { title: 'Refute', detail: 'one refuter per workstream re-runs the key requests', model: 'haiku' },
  ],
}

const BRIEF = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/hail-brief.md'
const WT = '/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/wt-hail'
const OUT = WT + '/research/hail-history/validation-evidence'

const WS = [
  ['W1', 'mrms-mesh-archive'], ['W2', 'point-reports-archives'], ['W3', 'warnings-archive'], ['W4', 'swdi'],
  ['W5', 'wind-history'], ['W6', 'montana-addresses'], ['W7', 'geocoding-and-lookup'], ['W8', 'commercial-and-tools'],
  ['W9', 'hosting-and-architecture'], ['W10', 'evaluation-and-wording'],
]

const SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    facts_count: { type: 'integer' },
    key_findings: { type: 'array', items: { type: 'string' }, description: 'at most 8 one-line findings with numbers' },
    open_questions: { type: 'array', items: { type: 'string' } },
    bytes_downloaded: { type: 'integer' },
    problems: { type: 'array', items: { type: 'string' } },
  },
  required: ['file', 'facts_count', 'key_findings', 'open_questions', 'bytes_downloaded', 'problems'],
}

const COMMON = (id, slug) => `Read the brief at ${BRIEF} in full first, then the model evidence file ${WT}/research/globe/validation-evidence/mrms.json for the JSON shape. You work on workstream ${id} (${slug}). Output file: ${OUT}/${slug}.json (the worktree ${WT}, branch claude/hail-history; write nothing else in the repo; never commit or push; git status/diff/log only). Downloads under /tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/hail-dl/${slug}/ (untrusted: scripts live elsewhere, run with python -I). Make live requests with curl or Python (requests, pygrib, numpy, h5py, pyproj are installed; pip install small pure-Python packages only if you must and say so). Every number must come from a request or file you made or read: record URL, HTTP status, bytes and a content check. Quote terms verbatim with the URL. Never write a model, vendor or AI-product name into the JSON. No em-dashes. Cap: 300 MB of downloads and about 90 minutes; record what you skipped. Return the structured summary.`

phase('Research')
log('Wave 1: ten source workstreams, researcher then refuter per workstream')
const results = await pipeline(
  WS,
  ([id, slug]) => agent(`${COMMON(id, slug)}

ROLE: RESEARCHER. Answer every question the brief lists for ${id}. Write the JSON with "review" left as an empty object. Prefer primary sources (the agency's own pages, bucket listings, the files themselves) over summaries. For anything you could not verify, say so in limits or open_questions instead of guessing.`, { label: `research:${id}`, phase: 'Research', model: 'haiku', schema: SCHEMA }),
  (r, [id, slug]) => agent(`${COMMON(id, slug)}

ROLE: REFUTER. A researcher wrote ${OUT}/${slug}.json (their summary: ${JSON.stringify(r)}). Read it, then try to refute every fact: re-run the key requests yourself (fresh downloads of the small files; re-list the buckets; re-read the terms pages), recompute the numbers, and look for what the researcher missed from the brief's questions. Edit the JSON in place: a wrong fact gets "verified": false and "refuted_by"; a corrected value replaces the old one with "corrected_from"; add missing facts; fill "review" (checked_at_utc, scope, refuted_claims, corrections, confirmed, unverified, reviewer_checks with URL and content_check). Keep the file valid JSON and under 60 KB. Return the structured summary describing the file after your pass.`, { label: `refute:${id}`, phase: 'Refute', model: 'haiku', schema: SCHEMA }),
)
const done = results.filter(Boolean)
log(`Wave 1 done: ${done.length} of ${WS.length} workstreams have a refuted evidence file`)
return { workstreams: WS.map(([id, slug], i) => ({ id, slug, result: results[i] })) }