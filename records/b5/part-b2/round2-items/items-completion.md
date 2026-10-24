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
