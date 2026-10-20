#!/bin/bash
# Assemble the combined store for B5 part B2: B5's store (B1 t/, B5 j/ z/ s/ c/ sd/ g/ k/ tl/) plus B3's a/, r/, b/ and counts.json.
set -u
OUT=/home/user/hail-b5/out/combined
STORE=$OUT/store
B5=/home/user/hail-b5/out/b1/store/hail
B3TAR=/home/user/hail-b3/out/keep/hail-store-b3-job1.tar.gz
PY=/home/user/hail-b1/venv/bin/python
rm -rf "$STORE"; mkdir -p "$STORE"
echo "[$(date -u +%H:%M:%S)] copy B5 store"; cp -a "$B5" "$STORE/hail"
echo "[$(date -u +%H:%M:%S)] extract B3 a/ r/ b/ counts.json"; tar -xzf "$B3TAR" -C "$STORE" --wildcards 'hail/a/*' 'hail/r/*' 'hail/b/*' 'hail/counts.json'
mkdir -p "$OUT/b3meta"; tar -xzf "$B3TAR" -C "$OUT/b3meta" hail/index.json hail/manifest.json
echo "[$(date -u +%H:%M:%S)] merge index.json and manifest.json"
$PY - "$STORE/hail" "$OUT/b3meta/hail" <<'EOF'
import json, sys, os, collections
store, b3 = sys.argv[1], sys.argv[2]
def load(p): return json.load(open(p))
def style(p):
    t = open(p).read(2000)
    return 1 if t.startswith('{\n ') else (2 if t.startswith('{\n  ') else None)
i5, i3 = load(os.path.join(store, 'index.json')), load(os.path.join(b3, 'index.json'))
m5, m3 = load(os.path.join(store, 'manifest.json')), load(os.path.join(b3, 'manifest.json'))
for k in ('addresses', 'roads', 'buildings'):
    assert k in i3 and k not in i5, k
    i5[k] = i3[k]
added = {p: e for p, e in m3['files'].items() if p.split('/')[1] in ('a', 'r', 'b', 'counts.json')}
clash = [p for p in added if p in m5['files']]
assert not clash, clash[:5]
m5['files'].update(added)
# every listed file is on disk and every file on disk under a/ r/ b/ is listed
missing = [p for p in added if not os.path.exists(os.path.join(os.path.dirname(store), p))]
ondisk = []
for sub in ('a', 'r', 'b'):
    for root, _, files in os.walk(os.path.join(store, sub)):
        for f in files:
            ondisk.append(os.path.relpath(os.path.join(root, f), os.path.dirname(store)))
unlisted = [p for p in ondisk if p not in m5['files']]
print('added manifest entries', len(added), 'missing on disk', len(missing), missing[:3], 'unlisted on disk', len(unlisted), unlisted[:3])
si, sm = style(os.path.join(store, 'index.json')), style(os.path.join(store, 'manifest.json'))
json.dump(i5, open(os.path.join(store, 'index.json'), 'w'), indent=si)
json.dump(m5, open(os.path.join(store, 'manifest.json'), 'w'), indent=sm)
print('index keys', list(i5)); print('manifest files', len(m5['files']), collections.Counter(p.split('/')[1] for p in m5['files']))
EOF
echo "[$(date -u +%H:%M:%S)] sizes"; du -sb "$STORE"; find "$STORE" -type f | wc -l; for d in "$STORE"/hail/*/; do printf '%s %s files %s bytes\n' "$(basename $d)" "$(find "$d" -type f | wc -l)" "$(du -sb "$d" | cut -f1)"; done
run_verify () {  # worktree module
  local wt=$1 mod=$2
  echo "[$(date -u +%H:%M:%S)] verify $mod (from $wt)"
  ( cd /home/user/wt/$wt && timeout 1500 $PY -m website.$mod verify --store "$STORE" > "$OUT/verify-$mod.log" 2>&1; echo "exit $?" >> "$OUT/verify-$mod.log" )
  tail -c 1500 "$OUT/verify-$mod.log" | tail -12
}
for mod in addresses streets buildings; do run_verify wt-b3 $mod; done
for mod in hail joins climate stations gauges snowgrid; do run_verify wt-b5 $mod; done
echo "[$(date -u +%H:%M:%S)] done"
