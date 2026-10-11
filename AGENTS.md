# AGENTS.md — RoofingApp

Shared instructions for every AI coding agent in this repo. ChatGPT/Codex read this file
directly; Claude Code reads it through `CLAUDE.md`. Humans: start with `README.md`.

## What this is
A desktop app for a Montana roofing company (owner: Carson, `carson14dy`): live NWS radar and
official alerts, SPC storm reports, inspection candidates with plain-language reasons, and a
per-job crew weather outlook. Installed copies **update themselves from this repo**: increasing
`version` in `payload/manifest.json` on `main` ships to every user. “Big Sky Hail Watch” is a
placeholder product name.

## Read before you change things
- `docs/handoff/Roofing_Weather_Claude_Handoff.md` — the weather module spec (Live Storms, Storm
  History, Crew Outlook, evidence kinds, acceptance checks).
- `docs/handoff/Roofing_Weather_Independent_Review.md` — supersedes the handoff's provider shortlist;
  its P0/P1 priorities set the order of work.
- `docs/DECISIONS.md` — why the architecture is the way it is, including bugs already fixed.
- `docs/ROADMAP.md` — what's done, what's next, open questions.

## Layout
```
payload/   the app — updates itself. app.py (routes) · weather.py (feeds, evidence, alert matching,
           rules, targeting, feed contracts) · store.py (SQLite) · maps.py (Folium) · templates/
desktop/   the shell — changes only with a new installer. launcher.py (window, local server,
           notifications, recovery page) · updater.py (GitHub updates, self-test, rollback)
tests/     acceptance checks · 240 alert scenarios + outage replay · update channel vs fake GitHub
build.py   PyInstaller build      ship.py   test → bump version → commit → push
```

## Commands
```bash
pip install -r requirements.txt
python desktop/launcher.py                      # native window (--browser, or --headless --offline for tests)
python desktop/launcher.py --selftest payload   # the check installed apps run before accepting an update
python -m unittest discover -s tests -v         # offline, ~5 s; must pass before any merge
python ship.py "one-line note" [--minor]        # ships to users — only when the owner asks
```

## Hard rules
1. **Shipping.** Users get a change only when `payload/manifest.json` `version` increases on
   `main`. Don't bump it in a PR unless the owner asked to ship; never lower it. Use `ship.py`.
2. **Payload contract (SHELL_API 1).** The shell imports `payload/` as a package: `app.py` exposes
   `create_app(config)`; sibling modules use relative imports; the app registers
   `app.extensions["hailwatch.stop"]`. A new pip package needs a new installer: add it to
   `requirements.txt` and `desktop/launcher.py::_bundle_imports`, raise `SHELL_API` and the
   manifest's `min_shell`, and rebuild installers.
3. **Database.** Only append to `store.MIGRATIONS`; never edit a shipped migration (two shipped).
4. **Python first.** Server-rendered Flask/Jinja + Folium. Hand-written JavaScript only for
   browser-only events, documented inline (today: the ~20-line bridge in `templates/live.html`).
   Owner preference — don't add a JS framework.
5. **Evidence honesty.** Keep forecast, radar estimate, point report, official alert and
   inspection separate. Never state confirmed damage, insurance eligibility or a damage
   probability. No report is not “no hail.” Missing inputs show “Data unavailable,” never an
   all-clear. Demo data only under the demo event, labelled DEMO everywhere.
6. **Official alerts.** Match by warning polygon, else the place's NWS forecast zone / county /
   fire-zone codes. Null geometry never means “no alert”; can't-tell shows as can't-tell. Never
   clear a warning after a failed request. No AI-generated text anywhere in the alert path.
7. **Feeds.** `weather.CONTRACTS` records each feed's units, timing, cadence and missing-value
   rules; change the parser, the table and the tests together. Before building on a source, make
   a live request **and check the content**, not just HTTP 200 (see the radar-layer bug in
   `docs/DECISIONS.md`).
8. **Verify UI in a real browser** (Playwright/Chromium is fine). String checks on HTML once
   missed a map that never ran.
9. **No “best” claims** for any provider or model until the evaluation in `docs/ROADMAP.md` supports it.

## Conventions
- Plain wording from the user's side; sentence case; an error says what happened and what to do.
- Keep the established dark “storm” look: tokens in `templates/base.html` `:root`.
- Store UTC. Show a job's NWS time zone (or the company zone). SPC dates follow 12:00–11:59 UTC
  reporting days. Hail sizes in SPC CSVs are hundredths of an inch; `UNK` wind stays unknown.
- Add or update tests with every behavior change.

## Owner's working preferences
- Direct, brief communication with a clear bottom line; data and ranked options over prose.
- Python-only where possible; minimal JavaScript, clearly documented.
- Verify data sources before building; be transparent about limitations and mistakes.
- When the approach needs to change, a clean rebuild beats patching around it.
- Single-file reference docs are preferred over many small ones.

## Two agents, one repo
Claude Code and ChatGPT both work here. Work on a branch and open a pull request; keep PRs small;
say what changed and how it was verified (tests, self-test, browser check). Record decisions in
`docs/DECISIONS.md` and status changes in `docs/ROADMAP.md`. Don't rewrite the other agent's work
without explaining why in the PR. Check `docs/ROADMAP.md` before starting so work isn't duplicated.
