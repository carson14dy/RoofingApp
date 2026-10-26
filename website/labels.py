"""Bubble anchors for the value bubbles on the building outlines (B6 product P4, the label pass).

What it is. Each building outline in hail/b/<shard>.json (the B3 shards, website/buildings.py) sits in one 1 km radar cell.
A value bubble shows that cell's largest radar estimate over the five seasons ("0.39 in") on the one outline of each cluster
of houses that the bubble stands for. This module decides which outline carries the bubble at zoom 17 and at zoom 18, and
writes the decision into the shard:
  k     on every outline: [z17 flag, z18 flag]. 1 means this outline carries the cluster's bubble at that zoom; 0 means not.
        The browser draws the bubble above the outline's dot, and only when the labels block reads loaded.
  kv    in the shard header: the value text of each cell key that an outline of the shard sits in. The key is the cell's
        in-tile key (hail.cell_key). The text is "0.39 in" (inches to the hundredth, rounded down, as hail.inches), or
        "Data unavailable" when the cell has no stored estimate of 0.25 in or more (hail.FLOOR_TENTHS). The browser prints
        "--" for such a bubble. A dash is never zero.

The rule. The owner's reference for the value bubble is research/map-b6/README.md: a value bubble on every house, and "--"
where nothing is stored. The rule that places the bubbles is this module's:
  1. Each outline's dot is projected to Web Mercator pixels at the zoom (256 px tiles).
  2. Within one 1 km cell, the dots are taken north to south, then west to east, then by index. A dot joins the nearest
     cluster leader of its cell when the leader is within cluster_px(), the width of the label "0.38 in" in the site's font
     (55.75 px). A dot with no leader in reach starts a cluster, so every member lies within that radius of its first dot.
  3. The anchor is the member nearest the middle of the cluster (the mean of its members); ties go to the earlier member.
  4. The bubbles are placed greedily: value descending (a dash last), then north to south, then west to east, then by the
     anchor's index. A bubble is placed unless its box overlaps a placed box by more than TOL (2 px) in both directions.
     A bubble is placed above its dot only, because a flag carries no side, so the outlines of a skipped cluster have no
     bubble.
  Coverage, measured on the statewide store (read only: 5,615 shards and 918,052 outlines): 95.25 percent of outlines lie
  inside a placed cluster at zoom 17 and 98.78 percent at zoom 18. On the two test tiles a below side would raise the zoom 17
  share from 91.4 to 98.5 percent; that needs a side in the flag, which is an owner decision.
  The label box is measured in the site's own font: the text is set in the woff2 face Atkinson Hyperlegible Next 700 with
  tabular figures and -0.02 em letter spacing, at 13 px on the page, measured by Pillow (with raqm) at 26 px and halved.

A cluster is computed within one shard, because the shard is the unit the browser loads (buildings.py). An outline whose
cell lies in another tile than its shard gets no flag and is counted (off_tile). The store writes none, and verify checks it.

Deterministic. The same shards and values give the same flags and the same bytes: every sort has a total order, and the shard
bytes keep the buildings writer's layout, so an outline that does not change keeps its bytes.

Sources and terms. The outlines are the USA Structures file (Oak Ridge National Laboratory and FEMA; buildings.py). The
values are the store's radar estimates (NOAA MRMS MESH; hail.py). The shard holds the dot, the rings and the address lines,
and this module adds flags and value text beside them. It reads no owner and no parcel.

Units. Pixels (CSS px at the zoom) for the geometry; tenths of a mm for the stored values; inches to the hundredth for the text.

Missing rules (rule 5). A radar shard the index lists that cannot be read leaves its cells "Data unavailable", and the block is
partial with the tile named. A shard that cannot be labelled is rewritten without its flags and kv when it parses, and it is
named; a shard that does not parse is left as it is, and it is named. Without Pillow, without raqm, without the site font, or
with a font file that cannot be read, the block is unavailable with the reason, and every readable shard loses its flags.

Failures (D16, D20). Each shard fails alone, and no stale bubble is drawn: a failed shard loses its flags, the block reads
partial, and the browser draws no bubble unless the block reads loaded (see the integration notes). The unavailable command
writes its block before it touches any shard, removes the flags and the value text from every readable shard, names each
shard it could not read, and exits 0 with those names. A run that stops part way still reads unavailable.

Store (format hail-buildings-v1, unchanged except the two keys above): hail/b/<shard>.json gains "k" on each outline and "kv" in
the header; hail/manifest.json lists each rewritten shard with its bytes and SHA-256; hail/index.json gains "labels".

Command line (run from the repository root):
    python -m website.labels build --store DIR [--tiles NAME ...] [--now ISO]
    python -m website.labels verify --store DIR [--tiles NAME ...] [--sample N]
    python -m website.labels measure --store DIR [--out FILE]     (statewide and read only: it writes nothing)
    python -m website.labels unavailable --store DIR --reason TEXT

--tiles limits build and verify to the named B1 tiles (for example r0081_c0160). A run that names tiles reads partial, since the
other shards keep their last flags. measure labels every shard in memory and writes nothing, so it runs on the read-only
adopted store.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import random
import sys
import time
from pathlib import Path

from . import hail
from . import history_layers as H

FORMAT = "hail-buildings-v1"              # the shard format the outlines are written in (buildings.py)
INDEX_KEY = "labels"                      # the block in hail/index.json
ZOOMS = (17, 18)
TILE_PX = 256                             # Web Mercator tile size in CSS pixels
DOT_R = 4.0                               # the dot radius: min(4.0, 2.5 + 0.5 * (zoom - 13)) is 4.0 at zooms 17 and 18
TIP_GAP = 1.0                             # the pointer's tip sits this far above the dot's top edge
POINTER_H = 5.0
BODY_H = 22.0
PAD = 7.0                                 # padding on each side of the text
LETTER = -0.26                            # letter spacing in px per character (-0.02 em at 13 px)
MIN_W = 30.0                              # the minimum body width
FONT_PX = 26                              # measured at 26 px and halved to the 13 px label
TOL = 2.0                                 # boxes overlapping by more than this in both directions clash
REFERENCE_TEXT = "0.38 in"                # the label whose width is the cluster radius
FONT_FILE = Path(__file__).resolve().parent / "static" / "fonts" / "atkinson-hyperlegible-next-latin-700-normal.woff2"
DASH = "--"                               # the bubble glyph for a cell with no value
UNAVAILABLE_TEXT = "Data unavailable"     # the kv text for a cell with no value (rule 5)
SCALE = 100000                            # outline coordinates have five decimals (buildings.py)

_WIDTHS: dict = {}
_FONT: dict = {}


class LabelError(Exception):
    """A label pass that cannot run (no Pillow, no raqm, or no site font). The message is plain words."""


def _font():
    if "font" in _FONT:
        return _FONT["font"]
    try:
        from PIL import ImageFont, features
    except ImportError as exc:
        raise LabelError("Pillow is not installed, so the bubble widths cannot be measured") from exc
    if not features.check("raqm"):
        raise LabelError("Pillow was built without raqm, so the font features (tabular figures) cannot be set")
    if not FONT_FILE.is_file():
        raise LabelError("the site font for the bubble labels is missing")
    try:
        _FONT["font"] = ImageFont.truetype(str(FONT_FILE), FONT_PX)
    except OSError as exc:
        raise LabelError("the site font for the bubble labels could not be read") from exc
    return _FONT["font"]


def label_width(text: str) -> float:
    """The body width of a bubble for this text, in CSS px: the 26 px measure halved, with the letter spacing and the
    padding, and at least MIN_W, rounded to two decimals."""
    width = _WIDTHS.get(text)
    if width is None:
        raw = _font().getlength(text, features=["tnum"]) / 2.0 + LETTER * len(text) + 2 * PAD
        width = max(MIN_W, round(raw, 2))
        _WIDTHS[text] = width
    return width


def cluster_px() -> float:
    """The cluster radius: the width of the reference label (55.75 px in the site's font)."""
    return label_width(REFERENCE_TEXT)


def label_text(tenths) -> str:
    """The bubble's glyph text for a cell value in tenths of a mm, or the dash when there is no value of FLOOR_TENTHS (0.25 in)
    or more."""
    if tenths is None or int(tenths) < hail.FLOOR_TENTHS:
        return DASH
    return f"{hail.inches(int(tenths))} in"


def kv_text(tenths) -> str:
    """The shard header's text for a cell: its inches, or "Data unavailable" when no value of FLOOR_TENTHS or more is stored."""
    if tenths is None or int(tenths) < hail.FLOOR_TENTHS:
        return UNAVAILABLE_TEXT
    return f"{hail.inches(int(tenths))} in"


def world(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Web Mercator pixel coordinates of a point at a zoom (256 px tiles)."""
    scale = TILE_PX * 2 ** zoom
    x = (lon + 180.0) / 360.0 * scale
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * scale
    return x, y


def box_for(x: float, y: float, text: str) -> tuple[float, float, float, float]:
    """The bubble's box (body and pointer) above the dot at (x, y)."""
    w = label_width(text)
    tip = y - DOT_R - TIP_GAP
    bottom = tip - POINTER_H
    return (x - w / 2, bottom - BODY_H, x + w / 2, tip)


def clash(a, b) -> bool:
    """True when two boxes overlap by more than TOL in both directions."""
    ox = min(a[2], b[2]) - max(a[0], b[0])
    oy = min(a[3], b[3]) - max(a[1], b[1])
    return ox > TOL and oy > TOL


def _units(value) -> int:
    """A coordinate in whole 1e-5 degrees (the shards' five decimals)."""
    return int(round(float(value) * SCALE))


def cell_of_units(lat5: int, lon5: int) -> tuple[int, int]:
    """The hail cell (row, col) of a point in whole 1e-5 degrees, in exact integer arithmetic. It is hail.cell_for's rule:
    row = floor((5500000 - lat5) / 1000) and col = floor((lon5 + 13000000) / 1000)."""
    return (5500000 - lat5) // 1000, (lon5 + 13000000) // 1000


def cell_of(outline: dict) -> tuple[int, int]:
    lon, lat = outline["p"]
    return cell_of_units(_units(lat), _units(lon))


# ---------------------------------------------------------------- the placement (pure: the widths come from the font)

def clusters_for(items: list) -> list[dict]:
    """The clusters of one zoom. Each item: i (the outline index), x and y (pixels at the zoom), cell (row, col), and tenths
    (the value, or None). Returns [{"anchor", "members", "tenths", "x", "y", "text"}], one per cluster."""
    radius = cluster_px()
    by_cell: dict = {}
    for item in items:
        by_cell.setdefault(item["cell"], []).append(item)
    out = []
    for cell in sorted(by_cell):
        group = sorted(by_cell[cell], key=lambda d: (d["y"], d["x"], d["i"]))
        leaders: list = []                         # [first dot, members]
        for d in group:
            best, best_dist = None, None
            for lead in leaders:
                dist = math.hypot(d["x"] - lead[0]["x"], d["y"] - lead[0]["y"])
                if dist <= radius and (best_dist is None or dist < best_dist):
                    best, best_dist = lead, dist
            if best is None:
                leaders.append([d, [d]])
            else:
                best[1].append(d)
        for _first, members in leaders:
            cx = sum(m["x"] for m in members) / len(members)
            cy = sum(m["y"] for m in members) / len(members)
            anchor = min(members, key=lambda m: (m["x"] - cx) ** 2 + (m["y"] - cy) ** 2)
            out.append({"anchor": anchor["i"], "members": [m["i"] for m in members], "tenths": anchor["tenths"],
                        "x": anchor["x"], "y": anchor["y"], "text": anchor["text"], "cell": cell})
    return out


def place(clusters: list[dict]) -> list[dict]:
    """The greedy placement: value descending (a dash last), then north to south, then west to east, then the anchor's index.
    A bubble is skipped when its box clashes with a placed box (box_for and clash)."""
    import numpy as np
    order = sorted(clusters, key=lambda c: (0 if c["tenths"] is not None else 1, -(c["tenths"] or 0), c["y"], c["x"],
                                            c["anchor"]))
    placed: list = []
    boxes = np.zeros((max(1, len(order)), 4), dtype=np.float64)
    count = 0
    for cluster in order:
        b = box_for(cluster["x"], cluster["y"], cluster["text"])
        if count:
            ox = np.minimum(boxes[:count, 2], b[2]) - np.maximum(boxes[:count, 0], b[0])
            oy = np.minimum(boxes[:count, 3], b[3]) - np.maximum(boxes[:count, 1], b[1])
            if np.any((ox > TOL) & (oy > TOL)):
                continue
        boxes[count] = b
        count += 1
        placed.append(cluster)
    return placed


def label_shard(doc: dict, tops: dict, tile: tuple[int, int]) -> dict:
    """The flags, the kv and the statistics of one buildings shard. tops maps a cell (row, col) to its largest value in
    tenths over the window (absent when none is stored). tile is the shard's B1 tile (row // 10, col // 10)."""
    outlines = doc["a"]
    flags = [[0, 0] for _ in outlines]
    stats = {"outlines": len(outlines), "off_tile": 0, "zooms": {}}
    in_tile = []
    for i, outline in enumerate(outlines):
        lon, lat = outline["p"]
        row, col = cell_of(outline)
        if (row // hail.TILE, col // hail.TILE) != tile:
            stats["off_tile"] += 1
            continue
        tenths = int(tops.get((row, col), 0))
        in_tile.append({"i": i, "cell": (row, col), "lat": lat, "lon": lon,
                        "tenths": tenths if tenths >= hail.FLOOR_TENTHS else None})
    kv: dict = {}
    for item in in_tile:
        key = str(hail.cell_key(*item["cell"]))
        if key not in kv:
            kv[key] = kv_text(item["tenths"])
    for z_index, zoom in enumerate(ZOOMS):
        items = []
        for item in in_tile:
            x, y = world(item["lat"], item["lon"], zoom)
            items.append({"i": item["i"], "x": x, "y": y, "cell": item["cell"], "tenths": item["tenths"],
                          "text": label_text(item["tenths"])})
        clusters = clusters_for(items)
        placed = place(clusters)
        for c in placed:
            flags[c["anchor"]][z_index] = 1
        stats["zooms"][str(zoom)] = {
            "clusters": len(clusters), "bubbles": len(placed),
            "bubbles_with_value": sum(1 for c in placed if c["tenths"] is not None),
            "bubbles_dash": sum(1 for c in placed if c["tenths"] is None),
            "outlines_covered": sum(len(c["members"]) for c in placed),
            "skipped_clusters": len(clusters) - len(placed)}
    return {"flags": flags, "kv": kv, "stats": stats}


def render(doc: dict, flags, kv) -> bytes:
    """The shard's bytes in the buildings writer's layout: compact keys, the values as json.dumps writes them, "k" last on
    each outline and "kv" last in the header. flags None and kv None give the shard without either key."""
    parts = []
    for key, value in doc.items():
        if key in ("a", "kv"):
            continue
        parts.append(f"{json.dumps(key)}:{json.dumps(value)}")
    outlines = []
    for i, outline in enumerate(doc["a"]):
        items = [(k, v) for k, v in outline.items() if k != "k"]
        if flags is not None:
            items.append(("k", flags[i]))
        outlines.append("{" + ",".join(f"{json.dumps(k)}:{json.dumps(v)}" for k, v in items) + "}")
    parts.append('"a":[' + ",".join(outlines) + "]")
    if kv is not None:
        parts.append('"kv":{' + ",".join(f"{json.dumps(k)}:{json.dumps(v)}" for k, v in kv.items()) + "}")
    return ("{" + ",".join(parts) + "}").encode("utf-8")


# ---------------------------------------------------------------- the radar values

class TileValues:
    """The window's largest estimate per cell, read tile by tile from hail/t/ and cached. A listed tile whose shard cannot be
    read gives no values (its cells read "Data unavailable") and is recorded in self.failed."""

    def __init__(self, store: Path, index: dict):
        self.store = store
        self.index = index
        self.first, self.last = H.window_days(index)
        self.listed = set(index.get("tiles", []))
        self.cache: dict = {}
        self.failed: dict = {}

    def tile(self, row_tile: int, col_tile: int) -> dict:
        name = hail.tile_name(row_tile, col_tile)
        if name in self.cache:
            return self.cache[name]
        values: dict = {}
        if name in self.listed:
            try:
                doc = json.loads((self.store / "hail" / "t" / f"{name}.json").read_bytes().decode("utf-8"))
                if not isinstance(doc, dict) or doc.get("f") != hail.SHARD_FORMAT:
                    raise ValueError("not a radar shard")
                d_first = hail.day_index(self.first)
                d_last = hail.day_index(self.last)
                r0, c0 = int(doc["r"]) * hail.TILE, int(doc["c"]) * hail.TILE
                for key_text, rows in doc.get("cells", {}).items():
                    best = 0
                    for day, tenths in rows:
                        if d_first <= int(day) <= d_last and int(tenths) > best:
                            best = int(tenths)
                    if best:
                        k = int(key_text)
                        values[(r0 + k // hail.TILE, c0 + k % hail.TILE)] = best
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.failed[name] = type(exc).__name__
                values = {}
        self.cache[name] = values
        return values

    def for_cells(self, cells) -> dict:
        out = {}
        for row, col in cells:
            values = self.tile(row // hail.TILE, col // hail.TILE)
            if (row, col) in values:
                out[(row, col)] = values[(row, col)]
        return out


def _shard_cells(doc: dict):
    for outline in doc["a"]:
        yield cell_of(outline)


def _tile_of(path: Path) -> tuple[int, int]:
    return int(path.name[1:5]), int(path.name[7:11])


def _shard_paths(store: Path, tiles) -> list[Path]:
    root = store / "hail" / "b"
    if not root.is_dir():
        return []
    paths = sorted(root.glob("*.json"))
    if tiles:
        wanted = tuple(tiles)
        paths = [p for p in paths if p.name.startswith(wanted)]
    return paths


def _read_index(store: Path) -> dict:
    try:
        doc = json.loads((store / "hail" / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise H.HistoryError("the store index could not be read") from exc
    if not isinstance(doc, dict) or doc.get("format") != hail.FORMAT:
        raise H.HistoryError("the store index is not in the hail-store-v1 format")
    return doc


def rule_words() -> dict:
    return {"zooms": list(ZOOMS), "cluster_px": cluster_px(), "tol_px": TOL, "dot_radius_px": DOT_R,
            "tip_gap_px": TIP_GAP, "pointer_px": POINTER_H, "body_px": BODY_H, "pad_px": PAD, "letter_px": LETTER,
            "min_width_px": MIN_W, "font": FONT_FILE.name,
            "order": "value descending, a dash last; then north to south, west to east, then the anchor's index",
            "placement": "above the dot only; skipped when it overlaps a placed bubble by more than tol_px in both directions",
            "clusters": "within one 1 km cell, a dot joins the nearest leader within cluster_px; the anchor is the member "
                        "nearest the middle",
            "words": {"dash": DASH, "unavailable": UNAVAILABLE_TEXT, "legend": H.WORDS["label_legend"]}}


def _write_block(store: Path, index: dict, block: dict, written: dict, removed=()) -> None:
    """Writes the labels block into hail/index.json first, then the manifest (which records the new index bytes)."""
    index[INDEX_KEY] = block
    H._write_index(store, index)
    H.update_manifest(store, written, removed=removed)


# ---------------------------------------------------------------- build

def _clear_paths(paths) -> tuple[dict, list]:
    """Removes the flags and the kv from each shard that can be read, writing it in place. Returns the files rewritten (keyed
    by their store path, with their bytes) and the shards that could not be read, each named with its reason (D20)."""
    written: dict = {}
    failures: list = []
    for path in paths:
        try:
            raw = path.read_bytes()
            doc = json.loads(raw.decode("utf-8"))
            if not isinstance(doc, dict) or doc.get("f") != FORMAT or not isinstance(doc.get("a"), list):
                raise ValueError("not a buildings shard")
            data = render(doc, None, None)
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            failures.append({"shard": path.name, "reason": f"the shard could not be read ({type(exc).__name__}), so its "
                                                           "flags could not be checked"})
            continue
        if data != raw:
            H._write_atomic(path, data)
            written[f"hail/b/{path.name}"] = data
    return written, failures


def _mark_unavailable(store: Path, index: dict, fields: dict) -> dict:
    """Writes the unavailable block first, so a run that stops part way still reads unavailable; then removes the flags and the
    kv from every shard that can be read; then records how many shards were cleared and which could not be read (D20)."""
    block = dict(fields, state="unavailable", shards_cleared=0, failures=[])
    _write_block(store, index, block, {})
    written, failures = _clear_paths(_shard_paths(store, None))
    block = dict(block, shards_cleared=len(written), failures=failures[:50])
    _write_block(store, index, block, written)
    return block


def build(store, *, tiles=None, now=None) -> dict:
    """Writes the flags and the kv of every buildings shard (or of the named tiles), the manifest entries of the shards it
    rewrote, and the labels block. A shard that fails is rewritten without its flags when it parses. A font that cannot be
    read removes the flags from every shard and marks the block unavailable (D20). A run that names tiles reads partial,
    since the other shards keep their last flags. Returns the summary."""
    store = Path(store)
    t0 = time.monotonic()
    built_at = H._parse_now(now).strftime("%Y-%m-%dT%H:%M:%SZ")
    index = _read_index(store)
    try:
        cluster_px()
    except LabelError as exc:
        return _mark_unavailable(store, index, {"problem": H.WORDS["unavailable"].format(
            what="The bubble values on the building outlines", reason=str(exc)), "built_at": built_at})
    if not (store / "hail" / "b").is_dir():
        block = {"state": "unavailable", "problem": H.WORDS["unavailable"].format(
            what="The bubble values on the building outlines", reason="the building outline shards are not in the store"),
            "built_at": built_at}
        _write_block(store, index, block, {})
        return block
    values = TileValues(store, index)
    written: dict = {}
    failures: list = []
    totals = {"shards": 0, "outlines": 0, "off_tile": 0, "bubbles": {str(z): 0 for z in ZOOMS},
              "covered": {str(z): 0 for z in ZOOMS}, "bytes_before": 0, "bytes_after": 0, "shards_changed": 0}
    for path in _shard_paths(store, tiles):
        try:
            raw = path.read_bytes()
            doc = json.loads(raw.decode("utf-8"))
            if not isinstance(doc, dict) or doc.get("f") != FORMAT or not isinstance(doc.get("a"), list):
                raise ValueError("not a buildings shard")
            tops = values.for_cells(_shard_cells(doc))
            result = label_shard(doc, tops, _tile_of(path))
            data = render(doc, result["flags"], result["kv"] or None)
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            failures.append({"shard": path.name, "reason": f"the shard could not be labelled ({type(exc).__name__}); its "
                                                           "flags were removed where it could be read"})
            cleared, _unread = _clear_paths([path])
            written.update(cleared)
            continue
        totals["shards"] += 1
        totals["outlines"] += len(doc["a"])
        totals["off_tile"] += result["stats"]["off_tile"]
        for zoom in ZOOMS:
            z = result["stats"]["zooms"][str(zoom)]
            totals["bubbles"][str(zoom)] += z["bubbles"]
            totals["covered"][str(zoom)] += z["outlines_covered"]
        totals["bytes_before"] += len(raw)
        totals["bytes_after"] += len(data)
        if data != raw:
            totals["shards_changed"] += 1
            written[f"hail/b/{path.name}"] = data
            H._write_atomic(path, data)
    for name, reason in sorted(values.failed.items()):
        failures.append({"tile": name, "reason": f"the radar shard could not be read ({reason}); its cells read Data unavailable"})
    reasons = []
    if tiles:
        reasons.append("this run labelled only the named tiles")
    if failures:
        reasons.append(f"{len(failures)} files could not be read")
    state = "partial" if reasons else "loaded"
    block = {"state": state,
             "problem": None if state == "loaded" else H.WORDS["unavailable"].format(
                 what="Some bubble values on the building outlines", reason="; ".join(reasons)),
             "built_at": built_at, "as_of": index.get("as_of"), "window": index.get("window"),
             "zooms": list(ZOOMS), "rule": rule_words(), "tiles": tiles or "all", "counts": totals,
             "bytes_added": totals["bytes_after"] - totals["bytes_before"], "failures": failures[:50],
             "seconds": round(time.monotonic() - t0, 1)}
    _write_block(store, index, block, written)
    return block


def unavailable(store, reason: str) -> dict:
    """Removes the flags and the value text from every shard that can be read, and marks the block unavailable (D20): no stale
    bubble is drawn. The block is written before any shard is touched, and a shard that cannot be read is named in the block
    rather than stopping the run. Returns the summary, which names those shards."""
    store = Path(store)
    text = " ".join(str(reason).split())
    if not text:
        raise LabelError("give the reason the bubble values are unavailable (--reason TEXT)")
    index = _read_index(store)
    block = _mark_unavailable(store, index, {
        "problem": H.WORDS["unavailable"].format(what="The bubble values on the building outlines", reason=text),
        "built_at": H._utc_now()})
    return {"state": "unavailable", "shards_cleared": block["shards_cleared"], "failures": block["failures"],
            "problem": block["problem"]}


# ---------------------------------------------------------------- verify

def verify(store, *, tiles=None, sample: int = 40, seed: int = 4) -> dict:
    """Recomputes the flags, the kv and the bytes of a sample of shards (or of every shard of the named tiles) and compares
    them with the files; checks the manifest entries; checks that no two flagged bubbles of a shard clash, and that each
    cluster has at most one flagged outline at each zoom; checks that each flagged cell has its kv text."""
    store = Path(store)
    checks: list = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "pass": bool(passed), "detail": detail})

    index = _read_index(store)
    block = index.get(INDEX_KEY)
    check("labels block present", isinstance(block, dict))
    if not isinstance(block, dict):
        return {"ok": False, "checks": checks}
    if block.get("state") == "unavailable":
        return {"ok": True, "checks": checks, "note": block.get("problem")}
    paths = _shard_paths(store, tiles)
    if not tiles and sample and len(paths) > sample:
        paths = random.Random(seed).sample(paths, sample)
    manifest = json.loads((store / "hail" / "manifest.json").read_text(encoding="utf-8"))
    values = TileValues(store, index)
    bad = {"manifest": [], "recompute": [], "clash": [], "cluster": [], "kv": [], "unflagged": []}
    for path in paths:
        raw = path.read_bytes()
        entry = manifest["files"].get(f"hail/b/{path.name}")
        if entry is None or entry["bytes"] != len(raw) or entry["sha256"] != H._sha256(raw):
            bad["manifest"].append(path.name)
        doc = json.loads(raw.decode("utf-8"))
        tops = values.for_cells(_shard_cells(doc))
        result = label_shard(doc, tops, _tile_of(path))
        if render(doc, result["flags"], result["kv"] or None) != raw:
            bad["recompute"].append(path.name)
        for z_index, zoom in enumerate(ZOOMS):
            boxes = []
            for i, outline in enumerate(doc["a"]):
                if result["flags"][i][z_index]:
                    lon, lat = outline["p"]
                    x, y = world(lat, lon, zoom)
                    tenths = tops.get(cell_of(outline))
                    boxes.append(box_for(x, y, label_text(tenths)))
            for a in range(len(boxes)):
                for b in range(a + 1, len(boxes)):
                    if clash(boxes[a], boxes[b]):
                        bad["clash"].append(path.name)
        for z_index, zoom in enumerate(ZOOMS):
            items = []
            for i, outline in enumerate(doc["a"]):
                lon, lat = outline["p"]
                x, y = world(lat, lon, zoom)
                cell = cell_of(outline)
                if (cell[0] // hail.TILE, cell[1] // hail.TILE) != _tile_of(path):
                    continue
                tenths = tops.get(cell)
                items.append({"i": i, "x": x, "y": y, "cell": cell, "tenths": tenths, "text": label_text(tenths)})
            for cluster in clusters_for(items):
                flagged = [m for m in cluster["members"] if result["flags"][m][z_index]]
                if len(flagged) > 1:
                    bad["cluster"].append(path.name)
        for i, outline in enumerate(doc["a"]):
            if result["flags"][i] != [0, 0]:
                cell = cell_of(outline)
                if (cell[0] // hail.TILE, cell[1] // hail.TILE) == _tile_of(path):
                    if str(hail.cell_key(*cell)) not in (doc.get("kv") or {}):
                        bad["kv"].append(path.name)
        if doc.get("kv") is None and any(o.get("k", [0, 0]) != [0, 0] for o in doc["a"]):
            bad["unflagged"].append(path.name)
    labels = {"manifest": "manifest entries match the shards' bytes and SHA-256",
              "recompute": "recomputed flags, kv and bytes equal the files",
              "clash": "no two flagged bubbles overlap by more than 2 px",
              "cluster": "no cluster has two flagged outlines at one zoom",
              "kv": "every flagged cell has its kv text",
              "unflagged": "a shard without kv carries no flags"}
    for key, text in labels.items():
        check(text, not bad[key], f"{len(paths)} shards; {', '.join(sorted(set(bad[key]))[:5])}".rstrip("; "))
    return {"ok": all(c["pass"] for c in checks), "checks": checks, "shards_checked": len(paths)}


# ---------------------------------------------------------------- measure (statewide, read only)

def measure(store, *, out=None) -> dict:
    """Labels every shard of the store in memory and writes nothing. Reports the bubbles per zoom, the outlines covered, the
    dashes and value bubbles, the off-tile count, the bytes and gzip bytes each shard gains, and the run times."""
    store = Path(store)
    t0 = time.monotonic()
    index = _read_index(store)
    try:
        cluster_px()
    except LabelError as exc:
        return {"state": "unavailable", "problem": str(exc)}
    values = TileValues(store, index)
    totals = {"shards": 0, "outlines": 0, "off_tile": 0, "clusters": {}, "bubbles": {}, "covered": {}, "dash": {},
              "value": {}, "bytes_before": 0, "bytes_after": 0, "gzip_before": 0, "gzip_after": 0, "failures": []}
    for z in ZOOMS:
        for key in ("clusters", "bubbles", "covered", "dash", "value"):
            totals[key][str(z)] = 0
    added = []
    gadded = []
    seconds_values = None
    for path in _shard_paths(store, None):
        try:
            raw = path.read_bytes()
            doc = json.loads(raw.decode("utf-8"))
            if not isinstance(doc, dict) or doc.get("f") != FORMAT:
                raise ValueError("not a buildings shard")
            tops = values.for_cells(_shard_cells(doc))
            result = label_shard(doc, tops, _tile_of(path))
            data = render(doc, result["flags"], result["kv"] or None)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            totals["failures"].append({"shard": path.name, "reason": type(exc).__name__})
            continue
        if seconds_values is None:
            seconds_values = round(time.monotonic() - t0, 1)
        totals["shards"] += 1
        totals["outlines"] += len(doc["a"])
        totals["off_tile"] += result["stats"]["off_tile"]
        totals["bytes_before"] += len(raw)
        totals["bytes_after"] += len(data)
        gb = len(gzip.compress(raw, 6))
        ga = len(gzip.compress(data, 6))
        totals["gzip_before"] += gb
        totals["gzip_after"] += ga
        added.append(len(data) - len(raw))
        gadded.append(ga - gb)
        for zoom in ZOOMS:
            z = result["stats"]["zooms"][str(zoom)]
            totals["clusters"][str(zoom)] += z["clusters"]
            totals["bubbles"][str(zoom)] += z["bubbles"]
            totals["covered"][str(zoom)] += z["outlines_covered"]
            totals["dash"][str(zoom)] += z["bubbles_dash"]
            totals["value"][str(zoom)] += z["bubbles_with_value"]
    result = {
        "state": "measured", "store": str(store), "as_of": index.get("as_of"), "window": index.get("window"),
        "rule": rule_words(), "shards": totals["shards"], "outlines": totals["outlines"], "off_tile": totals["off_tile"],
        "clusters": totals["clusters"], "bubbles": totals["bubbles"], "outlines_covered": totals["covered"],
        "bubbles_with_value": totals["value"], "bubbles_dash": totals["dash"],
        "bytes_before": totals["bytes_before"], "bytes_after": totals["bytes_after"],
        "bytes_added_total": totals["bytes_after"] - totals["bytes_before"],
        "bytes_added_per_shard": {"mean": round(sum(added) / len(added), 1) if added else 0,
                                  "max": max(added) if added else 0, "min": min(added) if added else 0},
        "gzip6_before": totals["gzip_before"], "gzip6_after": totals["gzip_after"],
        "gzip6_added_total": totals["gzip_after"] - totals["gzip_before"],
        "gzip6_added_per_shard": {"mean": round(sum(gadded) / len(gadded), 1) if gadded else 0,
                                  "max": max(gadded) if gadded else 0},
        "radar_failed_tiles": values.failed, "failures": totals["failures"][:20],
        "seconds_first_shard": seconds_values, "seconds_total": round(time.monotonic() - t0, 1),
        "font": FONT_FILE.name}
    if out:
        Path(out).write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    return result


# ---------------------------------------------------------------- command line

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m website.labels", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write the flags and the kv of the building shards")
    b.add_argument("--store", required=True)
    b.add_argument("--tiles", nargs="*", default=None, help="limit to these B1 tile names (for example r0081_c0160)")
    b.add_argument("--now", default=None)
    v = sub.add_parser("verify", help="recompute a sample of shards and compare")
    v.add_argument("--store", required=True)
    v.add_argument("--tiles", nargs="*", default=None)
    v.add_argument("--sample", type=int, default=40)
    m = sub.add_parser("measure", help="statewide and read only: anchors, bytes and gzip bytes added, run time")
    m.add_argument("--store", required=True)
    m.add_argument("--out", default=None, help="also write the measurement as JSON to this file")
    u = sub.add_parser("unavailable", help="remove the flags and mark the bubble values unavailable")
    u.add_argument("--store", required=True)
    u.add_argument("--reason", required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "build":
            result = build(Path(args.store), tiles=args.tiles, now=args.now)
            print(json.dumps(result, indent=1, sort_keys=True, default=str))
            return 0
        if args.cmd == "verify":
            result = verify(Path(args.store), tiles=args.tiles, sample=args.sample)
            print(json.dumps(result, indent=1, sort_keys=True, default=str))
            return 0 if result["ok"] else 1
        if args.cmd == "measure":
            result = measure(Path(args.store), out=args.out)
            print(json.dumps(result, indent=1, sort_keys=True, default=str))
            return 0
        result = unavailable(Path(args.store), args.reason)
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0
    except (LabelError, H.HistoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
