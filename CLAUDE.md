@AGENTS.md

## Claude Code notes
- This file imports `AGENTS.md` (the shared rules for every agent here). Change rules there, not here.
- For work touching architecture, feeds, alerts or the update channel, read `docs/DECISIONS.md` and
  `docs/ROADMAP.md` first; the handoff specs are in `docs/handoff/`.
- Before pushing: `python -m unittest discover -s tests` and `python desktop/launcher.py --selftest payload`.
- Ship (`python ship.py "note"`) only when Carson asks to ship.
