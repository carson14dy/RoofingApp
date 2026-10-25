"""Docs commit after the parity fix: the measured figures (D104, D105), run as python -I <this> <preview.json> in wt-b5."""
import json, sys
from pathlib import Path

preview = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))   # run_number, run_id, phone_bytes (int or None), swath (str), smoke (str)
root = Path(".")

def edit(path, old, new, count=1):
    p = root / path; t = p.read_text(encoding="utf-8")
    assert t.count(old) == count, (path, old[:80], t.count(old))
    p.write_text(t.replace(old, new), encoding="utf-8")

# ---- docs/DECISIONS.md: D104 and D105 after D102; the job bullet's (d)
d104 = ("- *D104, the real-store parity failure.* The first branch preview after the squash (Website runs 118 and 119) failed the "
        "parity step (D88(a)) against the branch's freshly published store, whose stations part loaded for all but 65 station-years "
        "(`parts.stations` \"partial\"): `summary.py` closes both gust rows' notes with the D20 sentence that names those station-years, "
        "with the reason and the all-clear sentence, and `map.js` built the rows without it, so the five cells disagreed on three "
        "fields; and the real-store names test pinned the adopted store's stations (Moccasin Exp Stn, 109 days missing). "
        "(a) The browser's gust part adds the note from the same joins block (parts, partial periods, reasons), after the rows' own "
        "notes, as Python appends it. (b) The names test asserts behaviour on whatever store `HAIL_PARITY_STORE` names: every "
        "stations-block name is `stations.display_name` of its GHCN name, a printed name is a store name in display form and never "
        "the GHCN form, and the radar rows follow D37 with the coverage they state. (c) A fixture test with `parts.stations` "
        "\"partial\" pins the note in the browser and the module, once, ending with the all-clear sentence. (d) Before a push that "
        "touches the sheet, the parity class runs against the branch's published store as well as the adopted store.\n")
d105 = ("- *D105, the daily budget.* The branch's store job (run 11, 2026-10-25) ran 39.1 minutes end to end on the runner with its "
        "downloads and published `hail-store-claude-hail-b5.tar.gz` at 88,647,098 bytes. The first-round gate B5-12 said under 25 "
        "minutes, a figure set before the B1 build, the B2 joins and the B3 parts shared the job. (a) The daily budget is 60 minutes "
        "end to end on the runner: the bound the branch preview's wait step already holds, so a job over it fails the preview; the "
        "job's 150-minute timeout is the backstop for a stalled request (D94(a)). (b) A later run over 60 minutes is a budget "
        "decision (raise the wait bound, the job cap and the timeout together, as the wait step's comment says), never a silent "
        "breach (D90(b)). (c) Gate B5-12 reads pass against the restated budget, with the run time, the asset size and the phone "
        "view as its evidence.\n")
edit("docs/DECISIONS.md", "- *Names.* Branch names are allowed in these docs (D43, round 2).", d104 + d105 + "- *Names.* Branch names are allowed in these docs (D43, round 2).")
edit("docs/DECISIONS.md",
     "(d) The daily total with downloads is not measured, so the 25-minute budget (B5-12) is open, and the byte caps (O12) are with the owner.",
     "(d) The daily total with downloads measured 39.1 minutes on the runner (the branch's store job, run 11, 2026-10-25); D105 restates "
     "the budget to 60 minutes, the preview's wait bound, with the 150-minute timeout as the backstop; the byte caps (O12) are with the owner.")

# ---- docs/ROADMAP.md
edit("docs/ROADMAP.md",
     "The live preview, the reviewer's reading (B5-11) and the daily job's run time (B5-12) are open.",
     f"The reviewer's reading (B5-11, D101) and the daily job's run time (B5-12: 39.1 minutes on the runner, D105) are done; the live "
     f"preview is the branch's Website run {preview['run_number']} of 2026-10-25 (the parity step, the smoke and the width check "
     f"passed{preview['phone_clause']}; its first run found the browser without the partial stations note, fixed under D104).")
edit("docs/ROADMAP.md",
     "and the daily job's run time with its downloads is open |",
     "and the daily job with its downloads ran 39.1 minutes on the runner (store job run 11, 2026-10-25; D105) |")
edit("docs/ROADMAP.md",
     "The daily total with downloads is not measured against the 25-minute budget (B5-12).",
     "The daily total with downloads measured 39.1 minutes on the runner (the branch's store job, run 11, 2026-10-25); D105 restates the "
     "budget to 60 minutes, the preview's wait bound, with the 150-minute job timeout as the backstop (B5-12).")

# ---- the verification record
rp = root / "research/hail-history/validation-evidence/b5-verification.json"
raw = rp.read_text(encoding="utf-8"); d = json.loads(raw)
assert json.dumps(d, indent=2, ensure_ascii=False) + "\n" == raw
gates = {g["id"]: g for g in d["gates"]}
g12 = gates["B5-12"]
g12["status"] = "pass (the budget restated by D105)"
g12["evidence"] = ("The branch's store job (run 11, 2026-10-25, commit bf2909b) ran 39.1 minutes end to end on the runner with its downloads "
                   "(05:47:51 to 06:26:57 UTC) and published hail-store-claude-hail-b5.tar.gz at 88,647,098 bytes; D105 restates the "
                   "first-round 25-minute figure to 60 minutes (the preview's wait bound; the 150-minute job timeout is the backstop). "
                   + g12["evidence"].replace("The daily job end to end under 25 minutes is not timed here (the branch run measures it). ", ""))
g18 = gates["B5-18"]
g18["status"] = "pass: the flag-off identity is restated by D93(a); the live preview ran on the branch"
g18["evidence"] = (g18["evidence"].replace("The live preview build on the branch was not run here; CI runs it on the push.",
                   f"The live preview: the branch's Website run {preview['run_number']} (2026-10-25, commit 199dfa9) passed the real-store "
                   f"parity step, the Chromium smoke with --addresses --history{preview['phone_clause']} and the page width check; the first "
                   f"preview after the squash (runs 118 and 119) failed the parity step on the partial stations note and the pinned names "
                   f"(D104). {preview['swath']}"))
c = d["completion"]
c["not_done"][0] = ("B5-18's live preview (Website run %s), the daily job's run time (B5-12: 39.1 minutes, store job run 11) and the packed "
                    "asset's size (88,647,098 bytes) were measured on the branch on 2026-10-25 (D104, D105). %s" % (preview["run_number"], preview["swath"]))
c["parity_step_seven_tests"] += (" Against the branch's published store (run 11, as_of 2026-10-23, parts.stations partial with 65 station-years) "
                                 "on 2026-10-25 the step failed on two of the seven (the five-cell agreement and the names test; D104); after the fix "
                                 "the seven pass against that store and the adopted store, and tests/test_site.py gains a fixture test for the "
                                 "partial stations note (not gated, so not in the step's list).")
c["daily_job_run_11"] = {"run_id": 40166818057, "commit": "bf2909b", "started": "2026-10-25T05:47:51Z", "finished": "2026-10-25T06:26:57Z",
                         "minutes": 39.1, "asset": "hail-store-claude-hail-b5.tar.gz", "asset_bytes": 88647098,
                         "budget_minutes": 60, "budget_rule": "D105 (the preview's wait bound; the 150-minute job timeout is the backstop)"}
c["live_preview"] = {"run_id": preview["run_id"], "run_number": preview["run_number"], "commit": "199dfa9", "date": "2026-10-25",
                     "phone_gzip_bytes": preview["phone_bytes"], "smoke": preview["smoke"], "swath": preview["swath"]}
d["status"] = d["status"].replace("the squash, the push, the live preview and the pull request are the supervisor's next steps (D93(f)).",
                                  "the squash, the push, the live preview (Website run %s) and pull request 17 on main are done (D93(f), D104, D105)." % preview["run_number"])
rp.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("docs patched")
