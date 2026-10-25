The browser's gust rows carry the partial stations note as summary.py does, and the names test reads behaviour, not one store's stations

The branch preview's parity step (D88(a)) ran the sheet against the branch's freshly built store, whose stations
part loaded for all but 65 station-years (parts.stations "partial"). summary.py closes both gust rows' notes with
the D20 sentence that names those station-years, with the reason and the all-clear sentence, and the wind section
carries it once; map.js built the gust rows without it, so the five cells disagreed on three fields. The gust part
of sumRows now adds the same note from the same joins block (ctx.parts, ctx.periods, ctx.reasons), after the rows'
own notes, as Python appends it.

tests/test_summary.py's real-store names test pinned the station names and the radar coverage of the adopted
combined store (Moccasin Exp Stn, 109 days missing), so it failed on any other store. It now checks the behaviour
on whatever store HAIL_PARITY_STORE names: every station name in the stations block is stations.display_name of
its GHCN name, a name the sheet prints is a store name in display form and never the GHCN form, and the radar rows
follow D37 with the coverage they state.

tests/test_site.py gains a fixture test for the note: a copy of the fixture store with parts.stations "partial",
two station-years and a reason of its own; the three fixture cells agree between the browser and the module, and
both gust rows and the wind section carry the sentence once, ending with the all-clear.

Verified: the seven-step parity class passes against the branch's published store (hail-store-claude-hail-b5.tar.gz,
run 11) and against the adopted combined store; the full suite (1,990 tests, 5 skipped) and the parked app's
self-test pass.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01D7npHSU4NQFAmdz8Ep5sV7
