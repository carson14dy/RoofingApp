export const meta = {
  name: 'b6-words-check',
  description: 'B6 stage 2: the second-opinion read-only reader of the About page words and data/base.json on the final build',
  phases: [{ title: 'Check', detail: 'one words reader' }],
}
const worker = 'haiku'
const WT = '/home/user/wt/wt-b6'
const SITE = '/home/user/hail-b5/out/b6/site'
const WORDS = { type: 'object', properties: { findings: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, line: { type: 'integer' }, text: { type: 'string' }, why: { type: 'string' } }, required: ['file', 'line', 'text', 'why'] } }, notes: { type: 'string' } }, required: ['findings', 'notes'] }
const common = ' The worktree is ' + WT + ' (branch claude/map-b6). You edit nothing and build nothing; you read the built site only. Never run a git write command. Make no network request.' +
  ' The rules: no AI model, vendor or product names; no em-dashes (U+2014); sentence case; plain words; a missing input shows "Data unavailable", never a zero or an all-clear (rule 5); every credit line reads "Source: ..." or "... data courtesy of ..." and never implies endorsement; no number derived from a held source and no licence conclusion for a held source on any page; the About page prints the modules\' sentences.'
phase('Check')
const words = await agent('You are a second-opinion read-only reader of the words on the B6 About page and in data/base.json of the final build.' + common +
  ' Read ' + SITE + '/about.html (its B6 sections: Base map, Landmarks, Five-year pictures, Zone counts, Recent radar hail, Value bubbles, and the Terms lines that cover those sources) and every string in ' + SITE + '/data/base.json, as a Montana roofer would. Flag any sentence that claims more than the data holds, any count beside a held source, any credit line that implies endorsement or names a source not used, any sentence about browser behaviour the page does not draw yet (the B6 layers are not drawn until B6-3; a sentence may say what the files hold, not what the map shows), any zero that stands for a missing input, any em-dash, and any plain-words failure (jargon, an unexplained acronym, a sentence over about 30 words). For each finding give the file, the line (of the HTML file, or the JSON path as the line 0 with the path in the text) and the text, and say why. Keep findings to what a reader would stumble on; the notes say what you read and what is sound. Return findings and notes.',
  { label: 'check:words', phase: 'Check', model: worker, schema: WORDS })
return { words }
