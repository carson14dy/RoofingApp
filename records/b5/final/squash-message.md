Hail history B5: five years of weather at every Montana address, one map and one sheet per place (D34 to D38)

The sheet that opens on a tap anywhere in Montana, and each town page, now lead with a plain summary table of the last
five seasons (July to June) and continue with eleven sections in a fixed order: hail, wind, storms, temperature, rain,
snow, flooding, ice, heat, what matters for a roof, and how this was made. Every number carries its unit and its kind
word (radar estimate, station reading, grid estimate, analysis, river gauge, report, record, warning, zone product,
reference, data unavailable), and every unavailable, partial or held line ends "This is not an all-clear."

What is new on top of main (the B1 radar hail history, public since 2026-10-22):
- B2: NWS local storm reports, NCEI storm records, radar hail detections, warnings and zone products joined into the
  sheet and the town tables, per tile, with each part's freshness and failure state.
- B3: every street, one dot per building outline with its addresses, and a typed-address search, behind
  --hail-addresses (off on main until the owner turns it on); no owner, parcel, place-type or building-use field is
  read, stored or shown (owner decision 6).
- B4: the live hail swath layers (last hour and last 24 hours, MRMS MESH) on the Map behind --storm-layers, with the
  sheet's live line.
- B5: the climate grid (highs, lows, freeze-thaw and hot days), the station part (snowfall, snow depth, rain, gusts;
  one pick rule with the rejected candidates named), the river gauges, the NOHRSC snow analysis (held, with the reason
  shown), the roof indicators with their references, and the per-tile station lists.
- The store job builds and publishes the whole store as the branch-named release asset; the site reads its own
  branch's asset and waits for its store run (main's scheme, D59); a store older than three days is a failed source.
- Budgets measured and recorded: the history-flag map.json under 163,840 bytes raw, the phone view at zoom 15 with
  every layer under 700,000 bytes gzip, every tap file under 100,000 bytes gzip; the words gate (tests/words_rules.py)
  over every words table and the About page; the real-store parity tests in the branch preview.

Verified: python -m unittest discover -s tests (SUITE_COUNT tests, 0 failures); python desktop/launcher.py --selftest
payload (PASS); Chromium smoke at 390 and 1280 px on a build from the adopted combined store (the three cells compared
word for word with the Python source; zero off-site requests); the branch's Website run.

Supersedes pull requests 14 (B2), 15 (B4) and 16 (B3), whose work this branch carries.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01D7npHSU4NQFAmdz8Ep5sV7
