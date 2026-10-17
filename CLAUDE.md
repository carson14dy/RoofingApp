@AGENTS.md

## Claude Code notes
- This file imports `AGENTS.md` (the shared rules for every agent here). Change rules there, not here.
- For work touching architecture, feeds, alerts or the update channel, read `docs/DECISIONS.md` and
  `docs/ROADMAP.md` first; the handoff specs are in `docs/handoff/`.
- Before pushing: `python -m unittest discover -s tests` and `python desktop/launcher.py --selftest payload`.
- Ship (`python ship.py "note"`) only when Carson asks to ship.

## Project subagents (`.claude/agents/`)
Use these for focused work; keep each one to its own files and branch so parallel runs don't collide.
- `alert-tester`: alert matching and lifecycle tests (polygon, zone, county, null geometry, outages).
- `feed-verifier`: checks a feed's live content and units before anything is built on it.
- `grid-data-engineer`: MRMS and HRRR gridded data, units, missing values, build time and file size.
- `evidence-auditor`: wording and evidence separation across pages, map text and exports.
- `security-reviewer`: read-only review of the website build, DOM sinks and GitHub workflows.
- `browser-qa`: real-Chromium checks at 288, 390 and 1440 px, with screenshots.
- `evaluation-analyst`: runs the predeclared evaluation; never edits the preregistration after seeing results.
- `docs-researcher`: dated, sourced reference pages in `docs/`; no rankings, no vendor contact.
