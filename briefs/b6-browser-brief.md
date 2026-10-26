# B6 browser brief: the Map page draws the new design (B6-3 to B6-6)

Supervisor: Fable. Workers: Haiku builders, skeptics, fixers and verifiers. Owner: Carson. Date: 2026-10-26.

## Goal
The Map page draws the B6 layers and the options sheet exactly as `docs/DESIGN.md` section 13 specifies them
(13.5 value bubbles, 13.6 the options sheet, 13.7 labels, type and credits) and `docs/DECISIONS.md` D107 to D142
decide them. The Python side (P1 to P4) is on main: the store files, `data/map.json`'s pointers and
`data/base.json`. This programme adds the browser side and nothing else. The owner's open picks are taken as
built (D143(c)): bubble rule A; the sheet as 13.6 specifies it; the terrain tint and relief on at zooms 5 to 10,
fading through zoom 12, hidden in dark mode; the D110(c) bubble legend sentence; landmark names as the sources
give them.

## Where and how
- Worktree: `/home/user/wt/wt-b6b`, branch `claude/map-b6-browser` from main at 687a609. Edit files there only.
- Python: `/home/user/hail-b1/venv/bin/python` (call it PY below). Never install packages.
- Never run a git command that writes (add, commit, push, checkout, switch, stash, reset, rebase, merge, branch -D).
  The supervisor commits. `git status`, `git diff` and `git log` are fine.
- `website/static/map/map.js` is 397,101 bytes. Never read it whole: find functions with
  `grep -n "function name" website/static/map/map.js` and read ranges with `sed -n 'a,bp'`. The same for
  `tools/smoke_map.py` (227,873 bytes) and `tests/test_site.py`.
- The site build (about 95 s; it writes 578 MB in place):
  `cd /home/user/wt/wt-b6b && PY -m website.build --out /home/user/hail-b5/out/b6b/site --hail-history --hail-addresses --hail-store /home/user/hail-b5/out/b6/store-copy --now 2026-10-17T12:00:00Z`
  Disk is tight (about 4 GB free). Only this one site directory: never build to another `--out`, never copy the
  store or the site, never leave large files behind. A change to a static file alone (`map.js`, `map.css`,
  `style.css`) can be copied into the built site instead of a rebuild:
  `cp website/static/map/map.js /home/user/hail-b5/out/b6b/site/static/map/map.js` (check the target path first).
  A template or `build.py` change needs the full build.
- Serve: `PY -m http.server -d /home/user/hail-b5/out/b6b/site PORT --bind 127.0.0.1 &` with the port the stage
  gives you. Note the pid and kill that pid when you finish. Never `pkill` by name: other agents run servers too.
- Browser: Playwright with Chromium is installed (`from playwright.sync_api import sync_playwright`;
  `chromium.launch()` needs no options). Sizes to check: 390 by 844 (phone) and 1280 by 800 (desk), light and dark
  (`browser.new_context(viewport=..., color_scheme="dark")`), and 320 by 568 for overflow. Screenshots and
  check scripts go under `/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/b6b/<your label>/`
  (`mkdir -p` it). Read the page's console errors and failed requests (`page.on("console")`, `page.on("requestfailed")`)
  and report them.
- Tests: `PY -m unittest tests.test_site` (a few minutes). The whole suite at a stage's end:
  `PY -m unittest discover -s tests` and `PY desktop/launcher.py --selftest payload`.
- Smoke: `PY tools/smoke_map.py /home/user/hail-b5/out/b6b/site --addresses --history --store /home/user/hail-b5/out/b6/store-copy`
  (it starts its own server; 10 minutes or more; `--shots DIR` saves pictures). Its checks drive the layer menu by
  its markup, so a markup change must update the smoke in the same stage.

## The data the browser reads
- `data/map.json` (first paint; its size is gated at 163,840 bytes raw, so add nothing to it beyond what is there):
  the blocks `base` (state, as_of, file `data/base.json`, zooms [5, 10], the tile templates `h` and `l`),
  `history_layers`, `recent` and `labels` (short blocks), beside the existing `layers`, `towns`, `alerts`,
  `reports` and `hail` blocks the page already uses.
- `data/base.json` (33,526 bytes; fetched once by the name `map.json` gives, after the first paint): the blocks
  `base` (state, problem, reason, as_of, sources, tiles, zooms, terrain, vector, landmarks, cells, held, credit),
  `history_layers` (state, problem, as_of, window, stale, pictures, zones, outlines, failures), `recent`
  (state, problem, url, as_of, window, stale, cells, days, floor_tenths, words), `labels` (state, problem, zooms,
  rule, words, budget), `sheet` (words) and `budget`. Learn the shapes from the built site:
  `PY -c "import json; print(json.dumps(json.load(open('/home/user/hail-b5/out/b6b/site/data/base.json'))['base']['vector'], indent=1))"`.
- The store file formats, each documented in its writer's docstring: `hail-base-vector-v1` and
  `hail-base-water-v1` (`website/basemap2.py`), `hail-landmarks-v1` (`website/landmarks.py`),
  `hail-base-peaks-v1` and `hail-base-places-v1` (`website/basemap2.py`), `hail-history-pictures-v1`,
  `hail-zone-counts-v1` and the zone outlines (`website/history_layers.py`), `hail-recent-v1`
  (`website/history_layers.py`), the building shards' `k` flags and `kv` texts (`website/labels.py`), the
  terrain tiles (`website/terrain.py`). Read the docstring before drawing a format; never change a format.
- The built store copy is at `/home/user/hail-b5/out/b6/store-copy` (its base map vectors are partial: band D
  water for 20 tiles; the pictures, zones, recent cells, landmarks and labels loaded). The site build copies it
  under the site's `hail/`.

## Rules that bind the browser
1. Python writes every word. The browser prints only strings from `data/map.json`, `data/base.json` or the
   template that `build.py` rendered from Python words. No label, heading, legend, reason, unit, threshold,
   window length or sentence as a literal in `map.js` (tests read it: `test_map_script_holds_no_threshold_unit_class_word_or_sentence`,
   `test_map_js_holds_no_address_or_host_name`). A word that the data lacks is added in Python
   (`website/build.py` `SHEET_WORDS`, or the module's `WORDS`), with a test that pins it, and reaches the browser
   through the rendered template (`data-legend`, `data-template`, `data-reason` attributes) or `data/base.json`.
2. No request to anything but this site's files, except the USGS imagery tiles while Imagery is on (D32).
3. Missing is not zero. A part whose state is not `loaded` shows its own `problem` sentence from the data; an
   unavailable chip is dashed with the data's words; a held kind shows "Held" and its reason, no count; a bubble with
   no value shows the `--` glyph with the `labels.words` sentence.
4. Colours come only from the roles in `website/static/style.css` `:root` (and the dark block); no hex value in
   `map.css` components. A new role, if one is needed, is added to both blocks with its contrast checked (3:1 for
   non-text, 4.5:1 for text).
5. Budgets. Nothing is added to the first paint. Every layer loads by zoom band or by tile, kept in a size-capped
   cache like the B3 draw cache (`hail.draw.cache_bytes`, least recently used first). The phone view at zoom 15 over
   Billings with the default layers stays under 700,000 bytes gzip (D82(b)); the smoke's `check_budget_and_pan`
   measures it.
6. Plain words from the user's side, sentence case, no em-dash anywhere, no AI vendor, model or product name in any
   file. Comments in `map.js` say why a piece is JavaScript (AGENTS.md rule 4); keep the header block current.
7. Accessibility: chips are `button`s with `aria-pressed`; the sheet is `section.sheet` with `role="dialog"`,
   `aria-modal="true"` and `hidden` until opened; every control is at least 44 by 44 px; keyboard focus shows a
   3 px ring; Escape closes; focus returns to `#btn-layers`; `prefers-reduced-motion` is respected
   (`reducedMotion()` exists).
8. Dark mode hides the terrain tint and the relief (D115(g)); everything else keeps its contrast in both schemes.
9. Tests with every behaviour change: `tests/test_site.py` for the template, the words and the data blocks;
   `tools/smoke_map.py` for the browser. A test is updated only when the new behaviour is the intended one, never
   deleted or skipped.
10. Nothing outside the stage's files: no change to a data module (`basemap2.py`, `landmarks.py`,
    `history_layers.py`, `labels.py`, `terrain.py`), no store format change, no workflow change, no new package,
    no JavaScript framework, no build step, no font or script from another site.

## Stages (one workflow run each; the supervisor gates between them)
- S1 The options sheet (DESIGN 13.6). The sheet replaces the layer menu (`#layers`): markup in
  `website/templates/map.html` rendered from `build.py` words; styles in `website/static/map/map.css`; the hooks
  `toggleOptions`, `setLive`, `setHistory`, `setLandmark`, `setPoi`, `landmarkLine`, `setHailRecent`,
  `renderOptions` and `resetOptions` in `map.js` (`setLayer(null)` hides the timeline and the legend card;
  `setBase` keeps its logic with the values `map` and `imagery`; `setWarnings` and `setReports` keep `#tg-warnings`
  and `#tg-reports`); the link parameters (the existing `layer` and `base`, plus `poi`, `hail_recent`, `history`
  and `landmarks`); the chip states off, on, unavailable, waiting and held from the data's states (Hail from
  `history_layers.pictures.hail1.state`, Heat from `heat90`, Wind and Flood from `history_layers.zones.state`,
  Fire and Smoke "Coming", the landmark kinds from `base.landmarks.state` and `base.held.kinds`, Highlight recent
  radar hail from `recent.state` and `recent.stale`); the legend lines in `data-legend`; the landmark line from
  `data-template`; Reset. The chips set state, the address and the lines in S1; the drawing of what they switch on
  lands in S2 to S4 (a chip whose layer is not drawn yet still switches and keeps its state; it says nothing false).
  The old menu's smoke checks and tests (`input[name=layer]`, `input[name=base]`, `#layers`, `<legend>Base map</legend>`)
  are moved to the new markup in the same stage. Ruling D144(a): the five-year Wind and Flood chips draw the
  forecast-zone counts of `hail/history/zones.json` over the zone outlines, with the words `history_layers.zones`
  carries (the module's legend, built by Python); the 13.6 mock lines for Wind and Flood are superseded by those
  words, and DESIGN 13.6 is updated in S5. Hail draws `hail1.png` and Heat `heat90.png` with their own `words`.
- S2 The base map: the terrain tiles (`h` relief and `l` tint, zooms 5 to 10, fading through 12, hidden in dark
  mode, drawn under the hail pane), the vector bands A to D by zoom (reservations, forests, parks, water, routes and
  shields; band D water per B1 tile from zoom 13, the `water_line_unavailable` sentence for a tile not built),
  the places with their minimum zooms and the peaks, every label at 13 px or more in the site's type with the
  town hierarchy kept (`tidyLabels`, `towns.json` label sides), and the credit lines in the attribution line.
- S3 The landmarks: the per-tile points (`hail/base/p/{name}.json`, kinds s, h, a, f, p and c) as dots with names
  for the kinds chosen, gated by Points of interest; the held church kind draws nothing.
- S4 The five-year pictures (image overlays on the picture bounds), the zone outlines with their counts and the
  newest-warning date, the recent radar hail highlight on the buildings, and the value bubbles at zooms 17 and 18
  from the building shards' `k` flags and `kv` texts, drawn only while `labels.state` is `loaded`
  (`labels.rule` holds the geometry: dot radius, pointer, body, padding, font).
- S5 Tests, smoke and docs: the smoke's new checks (the sheet, the chips, the bands, the bubbles, the phone budget
  with the default layers), `tests/test_site.py`, DESIGN 13.6 (the Wind and Flood lines) and 13.8 (status),
  DECISIONS D144 onward, ROADMAP item 22 and the B6 open items, the About page if a sentence changed.

## Roles in a stage
- Builder: builds the stage, runs `tests.test_site`, builds the site, checks it in Chromium at the sizes above, and
  returns the report. One builder at a time; it owns every file of the stage.
- Skeptics (three, in parallel, each with its own server port): try to refute the builder's report against the
  spec and the rules. Skeptic A: words and rules (rule 1 above, the tests, the data states). Skeptic B: the spec
  (13.6 or the stage's section) in Chromium at 390, 1280 and 320 px, light and dark, keyboard and touch sizes,
  console errors. Skeptic C: budgets, requests (none off-site), the link parameters and Reset, the smoke's
  affected checks. Each returns findings with evidence (a command and its output, a screenshot path, a line
  number); a finding without evidence is not a finding.
- Fixer: applies the confirmed findings, re-runs `tests.test_site`, rebuilds and re-checks.
- Verifier: runs the stage's gates again (tests, a Chromium pass, the smoke checks the stage names) and returns
  pass or fail per gate with the output.

## Report shape (every agent)
JSON: `{files: [...], words_added: {key: sentence}, tests: {added: [...], updated: [...], command: ..., result: ...},
checks: [{what, how, result, evidence}], shots: [...], open: [...]}`. A claim without its command or its screenshot
is not accepted.
