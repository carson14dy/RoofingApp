# Cleanup brief: remove the parked desktop app and the 3D globe research (D143(b))

Supervisor: Fable. Workers: Haiku builder, two skeptics, a fixer. Owner: Carson. Date: 2026-10-26.

## Why
Carson, 2026-10-26: "I want you to merge everything into the app main then. And delete old stuff you think is
unnecessary for our new maps." The product is the website (docs/DECISIONS.md D27); the desktop app was parked
and is now removed; the 3D globe research is out because the map has no 3D view (D107(c)). Everything removed
stays in git history.

## Where and how
- Worktree: `/home/user/wt/wt-clean`, branch `claude/cleanup` from main at 687a609. Edit files there only.
- Python: `/home/user/hail-b1/venv/bin/python` (PY below). Never install packages.
- Never run a git command that writes (add, commit, push, checkout, switch, stash, reset, rebase, merge, rm, mv,
  branch). The supervisor commits. Plain `mv` and `rm` of a file you are told to rename or remove are fine;
  `git status`, `git diff` and `git log` are fine.
- The inventory two readers made (read-only) is at
  `/tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/cleanup-inventory.json`
  (the key `app` and, after it, the globe reader's findings; the file is the raw task output, read it whole with
  `python3 -c` or `sed`). Its line numbers are from the B6 worktree, which equals main here; check each before
  editing. It is advice: the rulings below win where they differ.

## Already done by the supervisor (`git rm`, staged in the worktree)
`payload/`, `desktop/`, `build.py` (the PyInstaller build; `website/build.py` stays, it is the site), `ship.py`,
`tests/test_weather.py`, `tests/test_alert_scenarios.py`, `tests/test_updates.py`,
`.github/workflows/build-desktop.yml`, `research/globe/`, `assets/` (the app icons; the site has its own
`website/static/icon-180.png` and `favicon.svg`).

## Rulings (the builder follows these)
1. `requirements.txt` stays and becomes the website's list: exactly the packages `.github/workflows/website.yml`
   installs with pip (read its `pip install` lines), one per line, with a two-line comment saying it is the
   website's list. The AGENTS.md Commands block says `pip install -r requirements.txt   # the website`.
2. `.github/workflows/check-app.yml` is renamed `tests.yml` (plain `mv`), its name is `Tests`, it runs on push to
   `main`, on `pull_request` and on `workflow_dispatch`, and its steps are checkout, Python, `pip install -r
   requirements.txt` and `python -m unittest discover -s tests`. The self-test step goes. Keep its Python version.
3. Both documents in `docs/handoff/` stay. AGENTS.md's read-first bullet for the handoff says it is the original
   weather spec (the evidence kinds and the acceptance checks still apply; its app screens are history).
4. AGENTS.md: apply the inventory's AGENTS.md edits. Rules 2 and 3 become one line, "2 and 3. Retired with the
   desktop app (D143); the numbers stay so older citations read.", so rules 4 to 9 keep their numbers. The
   layout block drops `payload/`, `desktop/`, `build.py` and `ship.py`, and the tests entry lists the website
   test modules (`ls tests`). The Commands block keeps the website, test and smoke commands only. Rule 1 keeps its
   website half. Rule 4 and rule 7 lose their app clauses. The "What this is" paragraph says the app was removed
   on 2026-10-26 (D143) instead of parked.
5. CLAUDE.md: the read-first sentence loses "or the update channel" and the handoff clause (keep DECISIONS and
   ROADMAP); "Before pushing" keeps `python -m unittest discover -s tests` only; the ship bullet goes.
6. README.md: the whole parked-app section goes (from its "# Parked: the desktop app" heading to the end of the
   app's project layout); the intro's parked paragraph becomes one line (the app was removed on 2026-10-26, D143;
   its last commit is 33cda31); the Contents list and the "parked desktop app" heading lines go; the website
   unittest line lists the website test modules as `.github/workflows/website.yml` does.
7. docs/DECISIONS.md: a bold entry **D143** after the last decision (D142 and the paragraph after it) and before
   "## Gotchas found the hard way", in the file's own style, that records: Carson's words above, verbatim; the
   merges of 2026-10-26 (PR 17 as ec7bfbb, PR 18 as 687a609, PR 12 as aaf4455; PRs 14, 15, 16 and 2 closed as
   superseded); what was removed and why, with the last commit that held the app (33cda31) and the last commit
   that held the globe research (the supervisor gives it: run `git log -1 --format=%h -- research/globe` in the
   worktree); rules 2 and 3 retired; the workflow rename; requirements.txt; that the branch deletion was refused
   by the tool and is left to the owner; and one honest line that PR 12's merge message says 2,537 tests where the
   merged tree's suite was 1,990 tests OK and 12 skipped. Name the decision it replaces: D27's "Parked, not
   deleted" bullet. The Gotchas list loses the app-only bullets the inventory names (Folium kwargs, the installed
   payload copy, ship.py and the update tests, the two Folium bullets). D1 to D142 stay unchanged. Update the
   header's "D31 to D142" to "D31 to D143" if it names the range.
8. docs/ROADMAP.md: the inventory's edits, and for the globe: item 16 and the "Globe questions" open question
   become closed lines (the 3D view is out, D107(c); the research folder was removed, D143, its last commit
   named). The "| Live hail swaths" row at its line stays untouched (a test reads it). Range headers that say
   "D106 to D142" or "D107 to D142" stay.
9. docs/DESIGN.md: the three edits (the app's design note, "Jinja + Folium" becomes "Jinja + Leaflet", the
   home-screen icon line). The "## 11. " heading stays (a test splits on it).
10. `tests/test_storm.py`, `website/satellite.py`, `website/storm.py` and any other remaining file that cites
    `research/globe`: the citation says the research was removed on 2026-10-26 (D143) and lives in git history
    at the commit named in 7; the cited fact stays.
11. Every remaining reference to a removed path or name is fixed or justified: grep the tree (not `.git`) for
    `payload`, `desktop/`, `launcher`, `ship.py`, `selftest`, `SHELL_API`, `manifest.json`, `MIGRATIONS`, `Folium`,
    `research/globe`, `build-desktop`, `check-app`, `assets/` and the root `build.py` (not `website/build.py`).
    A mention that is history (a DECISIONS entry, a ROADMAP row that says what happened) stays as history.
12. Wording: plain words, sentence case, no em-dash, no AI vendor, model or product name in any file.

## Checks before the report
- `PY -m unittest discover -s tests` passes (fewer tests than before; say how many).
- `PY -c "import yaml,sys; [yaml.safe_load(open(p)) for p in sys.argv[1:]]" .github/workflows/*.yml` passes
  (if PyYAML is missing, say so and check the file by eye).
- `PY -m website.build --out /tmp/claude-0/-home-user-RoofingApp/7638440a-a008-5ef8-a289-86be0a23e7a7/scratchpad/cleanup-site --sample`
  passes; remove that folder after.
- `git status --short` shows only the deletions above, the rename and the edits this brief names.

## Report shape (every agent)
JSON: `{files: [...], checks: [{what, how, result, evidence}], open: [...], summary}`. A claim without its command
and output is not accepted.
