export const meta = {
  name: 'b6-sheet-fix',
  description: 'Apply the design critic\'s findings to the Map options sheet mock (sentence case, the site\'s own tokens, switch contrast, the required legend sentences, the landmark legend behaviour, Imagery and Five-year history names), re-render in Chromium, then re-check',
  phases: [{ title: 'Fix', detail: 'one fixer on the mock files' }, { title: 'Recheck', detail: 'one critic' }],
}
const worker = args.worker
const dir = args.dir
const rules = 'Rules: never run git write commands; do not edit files under /home/user/wt; edit only the mock files under ' + dir + ' (map-options.html,' +
  ' its own style block, spec.md, render.py) and never the copied style.css or map.css (they must stay byte-identical to the site); plain' +
  ' words, sentence case, no em-dashes, no AI model or vendor names in files you write; colours only through the roles in style.css' +
  ' (--color-surface, --color-line, --color-text, --color-text-muted, --color-focus, --radius, --radius-sm and the chip roles), no hex' +
  ' values, no map.css glass or blue variables. The Python environment is /home/user/hail-b1/venv/bin/python with Playwright (if the' +
  ' bundled browser is missing, launch Chromium with executable_path=/opt/pw-browsers/chromium).'
const fixes = [
  'F1 The sheet surface: a solid --color-surface panel with a --color-line edge and the --radius corner (12 px), no backdrop blur and no' +
  ' glass variables; the base map options are plain labelled choices (a small outlined card each, the chosen one with a 2 px --color-focus' +
  ' edge and a tick), no round discs and no folded-map or globe icons.',
  'F2 Every heading in sentence case: remove text-transform uppercase from the mock\'s own rules and do not inherit it from map.css (override' +
  ' with text-transform: none). One heading token for all four groups: --color-text-muted; re-measure the contrast.',
  'F3 Group names: "Base map" (choices "Map" and "Imagery"; the value and the link parameter are imagery), "Live weather", "Five-year' +
  ' history" (not risks; the sub-line says these are past records, not a forecast or a damage estimate), "Landmarks".',
  'F4 Switches: the on state uses --color-focus; the off track gets a 1 px --color-text-muted outline so it reads at 3:1 on the sheet in' +
  ' light and dark; measure both states in both themes.',
  'F5 Legend sentences: the live hail legends end with the sentence DESIGN.md section 11 requires (uncoloured means no radar estimate of' +
  ' 0.25 in or more, or no value, and that is not "no hail"); the Heat, Wind and Flood legends each say what a missing value shows ("--"' +
  ' or "Data unavailable") and that it is not zero or an all-clear; wind reads "50 kt (58 mph)"; expand MESH, MRMS, HRRR, SPC and NWS' +
  ' at first use in the sheet.',
  'F6 The landmark legend is one line naming every kind that is on, rebuilt on each change; turning Points of interest off hides the' +
  ' dots but keeps the chosen kinds, and turning it on shows the line again; the Points of interest sub-line reads "Landmark dots and' +
  ' names, for the kinds chosen below"; the off reason shows only on a tap.',
  'F7 Legend and switch lines at 14 px (the --text-sm size), the rest unchanged; every control still at least 44 by 44 px.',
  'F8 Icons: each data kind has its own icon or none; the three hail chips do not share one icon with each other or with the five-year' +
  ' hail chip; the two wind chips differ.',
  'F9 Update spec.md to match (the names, the one-at-a-time rule for live weather and five-year history, independent landmark kinds, the' +
  ' legend rules, Reset, the data-* hooks the Python template writes, and the note that the glass look of map.css is not used by the sheet).',
]
phase('Fix')
const fixed = await agent('You are the fixer for the Map options sheet mock at ' + dir + ' (read map-options.html, spec.md, render.py and the' +
  ' critic\'s notes under ' + dir + '/../critic-sheet/ if present). Apply these fixes exactly, then re-run the renders (phone 390 by 844 at' +
  ' scale 2 light and dark, top and scrolled to the bottom; desktop 1280 by 800 light and dark; the demo-states view; the side-by-side with' +
  ' the owner\'s reference sheet /root/.claude/uploads/7638440a-a008-5ef8-a289-86be0a23e7a7/16cd4c34-image.jpg, reference left and ours' +
  ' right) and re-measure: contrast of every text and control state in both themes, tap targets, overflow at 320, 390, 667 by 375 and' +
  ' 1280, hex values in the page (must be 0), console errors. Fixes: ' + fixes.join(' ') + ' ' + rules,
  { label: 'fix:sheet', phase: 'Fix', model: worker, schema: { type: 'object', properties: { applied: { type: 'array', items: { type: 'string' } },
    not_applied: { type: 'array', items: { type: 'string' } }, pictures: { type: 'array', items: { type: 'string' } }, measurements: { type: 'object', additionalProperties: true } },
    required: ['applied', 'not_applied', 'pictures', 'measurements'] } })
phase('Recheck')
const critic = await agent('You are the design critic, second pass, for the Map options sheet mock at ' + dir + '. The fixer reported: ' +
  JSON.stringify(fixed).slice(0, 5000) + '. Read docs/DESIGN.md sections 1 and 8 in /home/user/wt/wt-b6 and AGENTS.md (sentence case, tokens' +
  ' only, 44 px targets, every hazard colour carries its word, no "risk" wording in five-year history text per DESIGN section 12). Open every' +
  ' picture (Read the image files) and the HTML. Check each of these and say pass or fail with the measurement: no uppercase headings; no' +
  ' glass or blur; no hex or map.css colour variables in the mock\'s own CSS; switch off-track contrast at least 3:1 in light and dark; text' +
  ' contrast at least 4.5:1; the live hail legends carry the "not no hail" sentence; the heat, wind and flood legends state the missing' +
  ' value; the landmark legend names every kind on after tapping Schools then Parks; "Imagery" and "Five-year history" names; targets at' +
  ' least 44 px; no overflow at 320 px; the pictures show the fixes. ' + rules.replace('edit only the mock files', 'write only under ' + dir + '/../critic-sheet-2/ and edit nothing'),
  { label: 'critic:sheet-2', phase: 'Recheck', model: worker, schema: { type: 'object', properties: { ok: { type: 'boolean' }, checks: { type: 'array', items: { type: 'object', properties: { check: { type: 'string' }, result: { type: 'string' }, measurement: { type: 'string' } }, required: ['check', 'result', 'measurement'] } }, problems: { type: 'array', items: { type: 'string' } } }, required: ['ok', 'checks', 'problems'] } })
log('sheet fix ok: ' + (critic && critic.ok))
return { fixed, critic }