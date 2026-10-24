# Completion pass items (collected 2026-10-24 07:50 UTC; run as args.fixes of hail-b5b2-completion.js after the round-2 owners finish)
Products (joins.py, stations.py, sources.py, hail.py, their tests, the fixture through the command):
- D78(c): display names in title case written by stations.py into the tile lists, the sd summaries and the stations block (ghcn_name kept); rebuild the station part into the candidate (adopted) store; regenerate the fixture by rename; tests follow.
- joins.py comment near line 346: the job has 150 minutes, not 60 (D75).
- WORDS_JOINS["warnings_row"] removed once tests/test_site.py no longer requires it (products round 2 reports the state).
Site (build.py, summary.py, test_site.py, test_summary.py): whatever the site round 2 check leaves; the name-case tests follow D78(c).
Tests outside the owners: tests/test_addresses.py line 870 follows D74's "its completeness varies from county to county" (unless the docs owner took it).
Docs (owner 5): the figures from the re-check (phone view bytes, largest tap file, map.json sizes, the suite count); About's SWDI row as a quoted definition (D78(a)).
- Products (D79(d)): remove WORDS_JOINS["warnings_row"] and its uses in tests/test_joins.py (lines near 2267, 2641, 2662, 2664); the B2 placeholder test is superseded by warnings_row_b5 and warnings_row_point.
- Products (D78(c)): stations.py WORDS["two_of_one"] drops "Stations that did not pass are not shown." (D69 names them).
- Docs (owner 5): DESIGN.md lines near 504, 530 and 541 and DECISIONS.md near 765 quote the sheet heading "Warnings that covered this cell or part of it" and the town page's "covered this spot"; b5-verification.json's county_suffix item no longer applies; D79(a)'s sentence in How this was made is Python's (site).
- Products (D80(a)): stations.GATE_POINTS["billings"] equals towns.json's Billings point; the gate test's expected distances are recomputed from it (never typed by hand); the brief's gate B5-3 text follows (supervisor).
- Products (D80(d)): the warnings no-outline clause has cell words on the sheet and spot words on town pages (a _point twin), with a test.
- Site (D80(b), D80(c)): the How-this-was-made sentence on station positions says "a few hundred yards"; the rejected note's distance is from the point in use.
- Supervisor: the adopted store is /home/user/hail-b5/out/combined/store (not yet immutable; set chattr -R +i after the products completion pass rebuilds the station part with the display names); delete the candidate copy /home/user/hail-b5/out/b2/products-fix/fixer-c/store once the browser, site and docs rounds finish.
- Products (D81(d)): sources.py's SWDI row reads "NOAA defines PROB as the probability of hail in percent".
- Site (D81(e)): tests/test_site.py's round-1 pins of the old sheet strings (test_the_sheet_shows_the_radar_days_before_the_joins near 1735; test_the_sheet_has_the_template_slots_for_the_six_sections near 1954) follow the browser's round-2 structure.
- Docs (D81(a), D81(e)): counsel item 20 for the GHCN and Canadian licence note; no WIP hash in ROADMAP or the record (the branch and the pull request only); the PARTIAL items of the docs check (DECISIONS round-2 block with D60, D65, D71, D78 to D81; DESIGN section 12; About; the record) finished with the re-check's numbers; D49 recorded after the main merge.
