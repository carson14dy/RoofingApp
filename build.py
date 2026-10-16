"""
Build the desktop app installer folder with PyInstaller.

PyInstaller builds for the computer it runs on (it can't cross-compile), so the
GitHub Actions workflow runs this on Windows and macOS for you. Locally:

    pip install -r requirements.txt
    python build.py                          # uses desktop/update_config.json as-is
    python build.py --repo owner/name        # bake in where updates come from

Output: dist/MontanaHailWatch/ (Windows, Linux) or dist/MontanaHailWatch.app (macOS)

The installer carries the current payload as its built-in version; after that,
the app updates itself from GitHub.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_ID = "MontanaHailWatch"


def main():
    ap = argparse.ArgumentParser(description="Build the Montana Hail Watch desktop app")
    ap.add_argument("--repo", help="GitHub owner/name the app updates from")
    ap.add_argument("--branch", help="branch to update from (default: main)")
    ap.add_argument("--token-env", help="name of an environment variable holding a read-only token (private repos)")
    a = ap.parse_args()

    stage = ROOT / "build" / "stage"
    shutil.rmtree(stage, ignore_errors=True)
    (stage / "desktop").mkdir(parents=True)
    cfg = json.loads((ROOT / "desktop" / "update_config.json").read_text(encoding="utf-8"))
    if a.repo:
        cfg["repo"] = a.repo
    if a.branch:
        cfg["branch"] = a.branch
    if a.token_env and os.environ.get(a.token_env):
        cfg["token"] = os.environ[a.token_env]     # read-only; it can only read code the installer already contains
    (stage / "desktop" / "update_config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    shutil.copytree(ROOT / "payload", stage / "payload", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".devdata"))

    icon = ROOT / "assets" / ("icon.ico" if sys.platform == "win32" else "icon.icns" if sys.platform == "darwin" else "icon.png")
    sep = os.pathsep
    import PyInstaller.__main__
    PyInstaller.__main__.run([
        str(ROOT / "desktop" / "launcher.py"),
        "--name", APP_ID, "--windowed", "--noconfirm", "--clean",
        "--paths", str(ROOT / "desktop"),
        "--add-data", f"{stage / 'payload'}{sep}payload",
        "--add-data", f"{stage / 'desktop' / 'update_config.json'}{sep}desktop",
        "--add-data", f"{ROOT / 'assets'}{sep}assets",
        "--collect-data", "folium", "--collect-data", "branca", "--collect-data", "xyzservices",
        "--collect-submodules", "folium", "--collect-data", "tzdata",
        # optional extras Folium imports only if present — the app doesn't use them
        *[x for m in ("pandas", "scipy", "matplotlib", "IPython", "notebook", "tkinter", "pytest", "PIL")
          for x in ("--exclude-module", m)],
        "--icon", str(icon),
        "--osx-bundle-identifier", "com.montana.hailwatch",
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "work"),
        "--specpath", str(ROOT / "build"),
    ])
    out = ROOT / "dist" / (f"{APP_ID}.app" if sys.platform == "darwin" else APP_ID)
    print(f"\nBuilt {out}  (updates from: {cfg.get('repo') or 'not set — choose in App & updates'})")


if __name__ == "__main__":
    main()
