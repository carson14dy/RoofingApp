"""
Ship an app update to every installed copy — no installer, no zip.

    python ship.py "Fixed the alert list order"            # 1.0.0 -> 1.0.1
    python ship.py "Added territory reports" --minor       # 1.0.1 -> 1.1.0
    python ship.py "Notes" --no-push                       # commit only

What it does, in order (and stops at the first problem):
  1. runs the same self-test installed apps run before accepting an update
  2. runs the acceptance, alert-scenario and update tests
  3. bumps the version in payload/manifest.json and saves your one-line notes
  4. commits everything and pushes to GitHub

Installed apps notice within the hour, or right away with "Check for updates".
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "payload" / "manifest.json"


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=check)


def main():
    ap = argparse.ArgumentParser(description="Ship an app update")
    ap.add_argument("notes", help="one line about what changed (shown in the app)")
    size = ap.add_mutually_exclusive_group()
    size.add_argument("--minor", action="store_true", help="new features: 1.2.3 -> 1.3.0")
    size.add_argument("--major", action="store_true", help="big change: 1.2.3 -> 2.0.0")
    ap.add_argument("--no-push", action="store_true", help="commit but don't push")
    a = ap.parse_args()

    try:
        git("rev-parse", "--is-inside-work-tree")
    except (FileNotFoundError, subprocess.CalledProcessError):
        sys.exit("This folder isn't a git repository connected to GitHub yet — see README, “Set up updates (once).”")

    original = MANIFEST.read_text(encoding="utf-8")
    m = json.loads(original)
    major, minor, patch = (int(x) for x in m["version"].split("."))
    new = f"{major + 1}.0.0" if a.major else f"{major}.{minor + 1}.0" if a.minor else f"{major}.{minor}.{patch + 1}"
    m["version"], m["notes"] = new, a.notes
    MANIFEST.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")

    def stop(msg):
        MANIFEST.write_text(original, encoding="utf-8")
        sys.exit(f"Not shipped — {msg}")

    print(f"Testing {new}…")
    r = subprocess.run([sys.executable, str(ROOT / "desktop" / "launcher.py"), "--selftest", str(ROOT / "payload")],
                       text=True, capture_output=True)
    print(" ", r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        stop("the self-test failed (above). Installed apps would reject this version too.")
    t = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=ROOT,
                       text=True, capture_output=True)
    print(" ", (t.stderr.strip().splitlines() or ["tests ran"])[-1])
    if t.returncode != 0:
        print(t.stderr[-3000:])
        stop("a test failed (above).")

    git("add", "-A")
    commit = git("commit", "-m", f"Ship {new}: {a.notes}", check=False)
    if commit.returncode != 0:
        stop(commit.stdout.strip() or commit.stderr.strip())
    if a.no_push:
        print(f"Committed {new}. Run `git push` when you're ready to ship it.")
        return
    push = git("push", check=False)
    if push.returncode != 0:
        print(push.stderr.strip())
        sys.exit(f"Committed {new}, but the push failed (above). Fix that and run `git push`.")
    print(f"Shipped {new}. Installed apps will offer it within the hour — or now, with “Check for updates.”")


if __name__ == "__main__":
    main()
