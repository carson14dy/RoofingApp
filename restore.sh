#!/bin/bash
# Restore the session's working state from this branch into the paths the briefs and scripts use.
# Usage: bash restore.sh [workflow-scripts-dir]   (the dir the Workflow tool accepts scriptPath from:
#   /root/.claude/projects/-home-user-RoofingApp/<session-id>/workflows/scripts; created if given)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p /home/user/wt/briefs /home/user/wt/research-b35 /home/user/hail-b3/out/keep /home/user/hail-b4/out/keep /home/user/hail-b5/out/b1 /home/user/hail-b5/out/zone-editions /home/user/hail-b5/out/combined /home/user/hail-b5/cache /home/user/hail-b4/cache /home/user/hail-b3/cache
cp -a "$HERE"/briefs/*.md /home/user/wt/briefs/
cp -a "$HERE"/supervisor-log.md "$HERE"/venv-freeze.txt "$HERE"/tasks.md "$HERE"/RESUME.md /home/user/wt/
cp -a "$HERE"/tools/diskguard.py /home/user/wt/ 2>/dev/null || true
cp -a "$HERE"/records/research-b35/* /home/user/wt/research-b35/ 2>/dev/null || true
cp -a "$HERE"/records/b3/*.json /home/user/hail-b3/out/ 2>/dev/null || true; cp -a "$HERE"/records/b3/commit-msg.txt /home/user/hail-b3/ 2>/dev/null || true
cp -a "$HERE"/records/b4/*.json /home/user/hail-b4/out/ 2>/dev/null || true; cp -a "$HERE"/records/b4/cross-file.patch /home/user/hail-b4/out/keep/ 2>/dev/null || true; cp -a "$HERE"/records/b4/commit-msg.txt /home/user/hail-b4/ 2>/dev/null || true
cp -a "$HERE"/records/b5/*.json /home/user/hail-b5/out/ 2>/dev/null || true
cp -a "$HERE"/records/b5/store-ready.json /home/user/hail-b5/out/b1/ 2>/dev/null || true
cp -a "$HERE"/records/b5/zone-editions.json /home/user/hail-b5/out/zone-editions/ 2>/dev/null || true
cp -a "$HERE"/records/b5/combined/* /home/user/hail-b5/out/combined/ 2>/dev/null || true
cp -a "$HERE"/caches/hail-b5/* /home/user/hail-b5/cache/
cp -a "$HERE"/caches/hail-b4/* /home/user/hail-b4/cache/
cp -a "$HERE"/caches/hail-b3/* /home/user/hail-b3/cache/
mkdir -p /home/user/hail-b3 /home/user/hail-b4 /home/user/hail-b5
cp -a "$HERE"/scripts/*.js /home/user/hail-b5/
if [ -n "${1:-}" ]; then mkdir -p "$1" && cp -a "$HERE"/scripts/*.js "$1"/; echo "workflow scripts copied to $1"; fi
echo "restored: briefs, logs, records, caches, scripts (venv: python3 -m venv /home/user/hail-b1/venv && /home/user/hail-b1/venv/bin/pip install -r /home/user/wt/venv-freeze.txt)"
