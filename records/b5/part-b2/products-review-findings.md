# Products owner (owner 3), part B2: the review's findings, the skeptics' verdicts and the supervisor's rulings

Source: the workflow journal /home/user/wt/wt-session/records/b5/journals/wf_44a6add9-a8e.jsonl (JSON lines: the
builder's report, the reviewer's findings R1 to R14 with their evidence, the skeptics' verdicts on R1 to R5). The
builder's work is committed on claude/hail-b5 as bd3ae20 (diff against cbf5a12). The rulings are D61 to D65 in
/home/user/wt/briefs/hail-b5-brief.md and they are the instructions; this file is the index.

| Id | Where | Claim (short) | Skeptics | Ruling | Who |
|---|---|---|---|---|---|
| R1 | website/build.py:705; summary.py gust_station | describe_joins gets no spot; the town page measures from the cell centre (2.3 against 2.6 miles) | 2 of 2 confirmed, blocking | D65 (D56) | owner 2 (site) |
| R2 | website/data/hail-fixture | the fixture lacks tl/, sd/ and a stations block; claimed as the Billings cause | 2 of 2 refuted as the cause; the gap is real | D64: regenerate after D61 and D62; budgets and list tests restated | fixer B (products), owner 2 for the B2-only test |
| R3 | website/stations.py:1010, :147 | tile candidates within 40 miles of the tile centre with no margin, capped at six; 1.15 percent of cell answers wrong, 5,646 false "No station" | 2 of 2 confirmed | D61: margin per tile, no cap, verify parity, named cells | fixer A (products); owner 1 mirrors |
| R4 | website/stations.py:326 | Montana-only pool while the words say "within 40 miles"; out-of-state stations within reach; 2,543 false absence or only-one answers at border tiles | 2 of 2 confirmed | D62: United States stations by position; Canadian stations not read and named; words | fixer A (products); owner 2 and owner 5 words |
| R5 | website/summary.py:1057 | chosen_from_tile_list duplicates tile_list_picks | 2 of 2 confirmed (should) | D63: delegate; parity test | owner 2 (site); fixer A documents the shape |
| R6 | website/summary.py:1011 | gust_station picks from the tile's two stations, not the candidates at the town point | not judged | D65 (D56) | owner 2 (site) |
| R7 | website/templates/about.html:19 | the About radar line still says "not proof of dry weather" (D53) | not judged | D65: the docs and record pass | owner 5 (docs) |
| R8 | brief gate B5-3; b5-verification.json | Benchland snowfall second pick is Harlowton 11NW under D18, not Lewistown 11 SSE | not judged | D65: the gate text and the record say so | owner 5 (docs); supervisor |
| R9 | tests/test_site.py:2055 | write_joined_store's gate-tile station is 113 miles away (invalid test data); the browser lacks the radius check | not judged | D65: a station within 40 miles; the format keys; the browser applies the radius | owner 2 (site); owner 1 (browser) |
| R10 | website/joins.py:4124 | the FW.W 169 comment says "the B5 recheck's figure"; cite the recount (6 files, 262 events, 169 research, 170 store) | not judged (nit) | D65: apply after checking | fixer B (products) |
| R11 | tests/test_snowgrid.py:673 | the comment says the residue rule strips the sentence "and nothing else"; words_rules EXEMPT also strips the D13 allowances | not judged (nit) | D65: apply | fixer B (products) |
| R12 | tests/test_stations.py:969 | the Billings unit test labels USW00024033 as ASOS; the store says WBAN | not judged (nit) | D65: apply | fixer A (products) |
| R13 | website/stations.py:675 | the tile_list_picks docstring says any unread candidate is named when there are fewer than two picks; the code names those within the radius (right) | not judged (nit) | D65: apply | fixer A (products) |
| R14 | website/joins.py:5140 | the sample-only stations block's problem text lacks the D20 sentence (D28) | not judged (nit) | D64: apply | fixer B (products) |

Also from the builder's "needed" list: the combined store is re-assembled by the supervisor from fixer B's candidate
store (D64, D65); the store window and the D8 begin stand (D65); summary.py's How-this-was-made sentence (line 2406)
reads "stations in Montana and the neighbouring states within 40 miles" (owner 2, D62).

Measured facts the fixers can rely on (from the skeptics, read-only runs on the combined store):
- Tile corner distance 4.13 to 4.25 miles across tiles. Widening the radius by it and dropping the cap gives 0 wrong of
  2,298,500 cell-element answers; widening with the cap of six kept gives 478 wrong. Listed passing entries rise from
  101,539 to 170,465; the largest list is 27.
- All 466 Montana stations with a 2026 record are already summarised in the cache (no new Montana pulls).
- Out-of-state candidates: 173 United States stations within reach with a 2026 record; 185 + 40 .dly files already
  pulled under /home/user/hail-b5/out/b2p/products/skeptic-r4/dly and skeptic2-r4/dly (124 MB + 39 MB). 249 Canadian
  stations with a 2026 record lie in the search box.
- Scratch of the review (scripts and logs; read-only inputs): /home/user/hail-b5/out/b2p/products/ (review/,
  skeptic1/, skeptic2/, skeptic1-r3/, skeptic2-R3/, skeptic-r4/, skeptic2-r4/, skeptic-r5/, fixture-d56/, store/ with the
  rebuilt joins, verify-final.json).
