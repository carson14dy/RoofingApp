#!/bin/bash
# Adopt a verified candidate as the combined store (D50, D64, D65). Usage: adopt-store.sh <candidate dir holding hail/>
# The combined store's files are immutable (chattr +i); hardlinked copies share those inodes, so the flag is cleared on
# the old tree first, the trees are swapped by rename, and the flag is set again on the adopted tree. The old tree is kept
# as store-prev until the re-check passes; remove it with: chattr -R -i store-prev && rm -rf store-prev && chattr -R +i store
set -eu
C=${1:?candidate}
OUT=/home/user/hail-b5/out/combined
test -f "$C/hail/index.json" && test -f "$C/hail/manifest.json" || { echo "no index or manifest under $C/hail"; exit 1; }
for d in t j z s c sd tl g k a r b; do test -d "$C/hail/$d" || { echo "missing $C/hail/$d"; exit 1; }; done
python3 -I - "$C/hail/index.json" <<'PY'
import json, sys
i = json.load(open(sys.argv[1]))
need = ["joins", "climate", "stations", "gauges", "snow", "addresses", "roads", "buildings"]
missing = [k for k in need if k not in i]
print("index blocks:", sorted(i)); print("missing blocks:", missing)
st = i.get("stations", {}); print("stations state:", st.get("state"), "tile_lists:", {k: st.get("tile_lists", {}).get(k) for k in ("files", "capped", "longest", "margin_miles")} )
j = i.get("joins", {}); print("joins keys with D55:", [k for k in ("vtec_store_window", "vtec_window_edges") if k in j])
sys.exit(1 if missing else 0)
PY
echo "[$(date -u +%H:%M:%S)] clearing the immutable flag on the old store"; chattr -R -i "$OUT/store"
test -e "$OUT/store-prev" && { echo "store-prev exists; remove it first"; exit 1; }
mv "$OUT/store" "$OUT/store-prev"; mv "$C" "$OUT/store"
echo "[$(date -u +%H:%M:%S)] setting the immutable flag on the adopted store"; chattr -R +i "$OUT/store"
echo "adopted: $(find "$OUT/store" -type f | wc -l) files, $(du -sb "$OUT/store" | cut -f1) bytes; previous kept at $OUT/store-prev"
