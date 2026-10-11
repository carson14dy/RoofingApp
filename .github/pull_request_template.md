## What changed
<!-- One or two lines, from the user's side. -->

## How it was verified
- [ ] `python -m unittest discover -s tests` passes
- [ ] `python desktop/launcher.py --selftest payload` passes
- [ ] Checked in a real browser or the app window (for screen changes)
- [ ] Live feed content checked, not just HTTP 200 (for feed changes)

## Ships to users?
- [ ] No — `payload/manifest.json` version unchanged
- [ ] Yes — version raised (owner asked to ship)
- [ ] Needs a new installer (`desktop/` changed or a new package)

## Docs
- [ ] `docs/DECISIONS.md` / `docs/ROADMAP.md` updated if a decision or status changed
