# B6 browser stage S2: the base map drawn (terrain tiles, the vector bands, places, summits, credits)

Read `/home/user/wt/wt-session/briefs/b6-browser-brief.md` first (the programme, the rules, the commands, the rulings
after S1), then this file. Worktree `/home/user/wt/wt-b6b` (branch `claude/map-b6-browser`, S1 committed as 06b57f4),
the one site directory `/home/user/hail-b5/out/b6b/site`, the Python and the commands as the programme brief says.

## Rulings that shape S2 (D145, the supervisor, 2026-10-27)
- (a) The B6 drawing code lives in a second script, `website/static/map/layers.js`, loaded by `map.html` after
  `map.js` with a plain script tag (no on-demand loading, no build step). Its header says why it is JavaScript (AGENTS.md
  rule 4) and what it draws; `map.js` exposes one small, documented interface for it (for example `window.hailMapLayers`
  or a custom event when `data/base.json` has loaded, with the map, the panes, the options state and the words), and
  nothing else in `map.js` changes beyond that interface and the sheet hooks that switch the layers.
- (b) The phone budget: the 700,000-byte gate of D82(b) counts the B3 files and the B3 shell; the B6 additions
  (`layers.js`, `data/base.json`, the files under `hail/base/`) are measured and listed apart in the smoke's budget note,
  and the whole page total is printed with them. S2 reports the bytes of `layers.js` (gzip) and of every B6 file fetched
  in the zoom 15 Billings view and in a zoom 8 statewide view. The owner decides the new budget for the default view
  (the supervisor proposes it with S2's figures); S5 makes it a gate.
- (c) Every colour the base map uses is a role in `map.css`'s token blocks (light and dark), named for its kind
  (`--map-water`, `--map-water-line`, `--map-forest`, `--map-park`, `--map-reservation`, `--map-route`, `--map-route-shield`,
  `--map-place-text`, `--map-summit`, and the like); no hex in a drawing call. Dark mode hides the terrain tiles (D115(g))
  and keeps every vector readable (3:1 or more against the paper).
- (d) The base map draws in every build that has `base.state` loaded or partial; a part whose state is unavailable draws
  nothing and the sheet's base map line shows that part's `problem` sentence from `data/base.json`. A band D tile that is
  not built shows the `water_line_unavailable` sentence (already in `sheet` words) in the base map line while such a tile
  is in view at zoom 13 or more. Nothing is drawn from a guess.

## What S2 draws
1. Terrain tiles: the relief (`h`) and the land cover tint (`l`) as two tile layers from the templates in `map.json`
   `base.tiles`, native zooms 5 to 10, shown through zoom 12 with the opacity fading (full at 10, gone after 12), under
   the vectors; hidden in dark mode; a missing tile shows paper (no broken-image mark, no console error). Only when
   `base.terrain.state` is loaded or partial.
2. The vector bands (`hail-base-vector-v1`; read the format in `website/basemap2.py`'s docstring and its writer: the
   feature keys, the geometry encoding, `k` kind, `n` name, `z` minimum zoom, `s` shield): band A (one file, zooms 5 to 7),
   band B (2 by 2 degree cells, zooms 8 to 10), band C (1 by 1 degree cells, zooms 11 and 12), band D (one shard per B1
   tile, zooms 13 to 18; `hail-base-water-v1`). Fetch the cells in view by band, once each, into a size-capped cache
   (least recently used first, the cap from `map.json` or `data/base.json` if one is there, else the B3 draw cache cap),
   never a file outside the current band, never a request off this site. Draw on one canvas in its own pane under the
   hail pane and above the terrain: fills for reservations, forests, parks and lakes; lines for rivers and routes, with
   widths by zoom from `map.css` roles; route shields with their number from `s`; each feature only from its `z`.
3. Places and summits (`hail/base/places.json`, `hail/base/peaks.json`): labels at their minimum zooms from the data,
   13 px or more in the site's type, placed with the existing collision helpers (`tidyLabels`, `placeCrowded`) so that
   town labels keep their priority and side (`towns.json`); a summit label carries its height in feet from the data.
4. Credits: when the base map draws, the attribution line carries the credit lines of `base.credit` (D113(a), D115(d))
   exactly as the data gives them, once each, beside the lines already there.
5. The sheet's base map line (`#mo-base-line`): the part's problem sentence or the water line as (d) says; empty and
   hidden when everything in view is drawn.

## Checks S2 must pass before its report
- `PY -m unittest tests.test_site` passes with the new tests: the script tag, the roles exist in both token blocks, no
  literal sentence in `layers.js` (extend the test that reads `map.js` to read `layers.js` too), the interface names.
- Chromium (390 by 844 and 1280 by 800, light and dark) at zooms 6 (statewide), 9 (Billings region), 12 and 15 over
  Billings: the canvas draws (sample pixels; not all paper), the requests are exactly the expected band files and tiles,
  no request leaves the site, no console error, the terrain is hidden in dark mode, the credit lines are in the
  attribution, the labels do not overlap the town labels, and a redraw after a pan takes under 50 ms (measure with
  performance.now around the draw).
- The whole smoke passes (`tools/smoke_map.py ... --addresses --history --store ...`) with a new check `check_base_map`
  that does the Chromium items above at 390 px and prints the B6 bytes apart as (b) says.
- The figures for (b): `layers.js` raw and gzip; the B6 files fetched at zoom 15 Billings and at zoom 8 statewide, by
  name and gzip bytes; the whole page total at zoom 15.

## Report shape
As the programme brief says, plus `figures: {layers_js_gzip, zoom15_b6_files: [{name, gzip}], zoom15_page_total,
zoom8_b6_files: [...], redraw_ms: [...]}`.
